from collections.abc import Callable, Iterable, Sequence
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
from agl.config import registry, sources, toml_file
from agl.config.schema import Settings
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.history import History
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.run import RunSpec, checked_text
from agl.ports.store import Store
from agl.ports.tree_layout import TreesRoot, run_branch
from agl.sdk import params
from agl.sdk._engine import preflight
from agl.sdk._engine.integration import Leases
from agl.sdk._engine.services import Services
from agl.sdk.workflow import Run, Workflow

__all__ = ["Ask", "clear", "init", "list_workflows", "resume", "run", "workflow_help"]

_TREES_DIRNAME: Final = ".agl-trees"

_BUILD_PROMPT: Final = (
    "What command builds and tests this project? AGL runs it at the merge gate, through a shell, "
    "in a worktree of its own - `./gradlew build`, `make test`, `npm run build`.\n"
    "build command: "
)

type Ask = Callable[[str], str]

async def run(
    services: Services,
    project: ProjectName,
    name: str,
    label: RunLabel,
    argv: Sequence[str] = (),
    *,
    base_ref: str | None = None,
    points: Iterable[EntryPoint] | None = None,
) -> None:
    wf: Workflow[object] = registry.load(_points(points), name, Workflow)
    given = params.parse(wf.params, argv, prog=f"agl run {name}")

    scope = RunScope(project, label)
    if await services.store.read_record(scope) is not None:
        raise ConflictError(
            f"run {str(label)!r} already exists - `agl resume {label}` or `agl clear {label}`."
        )

    branch = run_branch(label)
    if await services.history.exists(branch):
        raise ConflictError(
            f"the branch {branch!r} already exists, so run {str(label)!r} cannot start: AGL would "
            f"attach this run to that line of work and carry on from wherever it got to, with "
            f"whatever `--from` said ignored. This is what an unfinished run leaves - "
            f"`clear` keeps a branch whose work is not yet in the base ref, and takes that run's "
            f"records away with everything else, so there is nothing left here for `agl clear "
            f"{label} -f` to address. `git log {branch}` is what is on it, `git branch -D "
            f"{branch}` frees the label, and any other label starts a run of its own."
        )

    await preflight.check(services.agents, wf.fn)

    ref = (
        await services.history.default_ref()
        if base_ref is None
        else checked_text(base_ref, "base_ref")
    )
    spec = RunSpec(
        workflow=name,
        workflow_version=wf.version,
        label=label,
        base_ref=ref,
        base_sha=await services.history.resolve(ref),
        branch=branch,
        params=params.to_json(given),
        created_at=services.clock.now(),
    )

    async with services.workspaces.hold(label):
        await services.store.write_record(scope, spec.to_json())
        await _walk(services, wf, scope, spec, given)

async def resume(
    services: Services,
    project: ProjectName,
    label: RunLabel,
    *,
    points: Iterable[EntryPoint] | None = None,
) -> None:
    scope = RunScope(project, label)
    record = await services.store.read_record(scope)
    if record is None:
        raise NotFoundError(
            f"run {str(label)!r} does not exist - `agl run <workflow> -n {label}` starts one."
        )
    spec = RunSpec.from_json(record)

    wf: Workflow[object] = registry.load(_points(points), spec.workflow, Workflow)

    if wf.version != spec.workflow_version:
        raise ConflictError(
            f"run {str(label)!r} was started by {spec.workflow!r} version "
            f"{spec.workflow_version!r} and the installed {spec.workflow!r} is version "
            f"{wf.version!r}. A run stamps its workflow's version and AGL refuses a mismatch "
            f"rather than migrating one: every step already on this run's ledger was "
            f"produced by the workflow as it was then. Install {spec.workflow_version!r} to finish "
            f"this run, or `agl clear {label} -f` and start it again on {wf.version!r}."
        )

    given = params.from_json(wf.params, spec.params)

    await preflight.check(services.agents, wf.fn)

    async with services.workspaces.hold(label):
        await _walk(services, wf, scope, spec, given)

async def clear(
    services: Services, project: ProjectName, label: RunLabel, *, force: bool = False
) -> str | None:
    scope = RunScope(project, label)
    record = await services.store.read_record(scope)
    if record is None:
        raise NotFoundError(f"run {str(label)!r} does not exist - there is nothing to clear.")

    async with services.workspaces.hold(label):
        for namespace in await _under(services.store, scope):
            await services.workspaces.remove(label, namespace)
            await services.workspaces.discard(label, namespace)

        await services.workspaces.remove(label, None)

        branch = run_branch(label)
        kept = (
            None
            if force
            else await _kept(services.history, label, branch, RunSpec.from_json(record).base_ref)
        )
        if kept is None:
            await services.workspaces.discard(label, None)

        await services.store.remove(scope)
        return kept

def init(settings: Settings, cwd: Path, ask: Ask) -> Path:
    root = toml_file.git_root(cwd)
    name = ProjectName(root.name)

    destination = toml_file.check_unregistered(settings.home, name)

    trees = TreesRoot(root.parent / _TREES_DIRNAME / str(name))
    toml_file.check_trees_root(destination, root, trees.path)

    build = ask(_BUILD_PROMPT).strip()
    if not build:
        raise InputError(
            "a build command is what AGL runs at the merge gate before a run's work is landed, "
            "so an empty one would make every gate pass without building anything. "
            "Nothing has been written - run `agl init` again and give the command this project is "
            "built and tested with. If it genuinely has none, that is a decision to make in the "
            "project's settings file rather than a value that arrives here empty"
        )
    return toml_file.write_project(
        settings.home, name, root, trees, build, sources.DEFAULT_BUILD_TIMEOUT
    )

def list_workflows(*, points: Iterable[EntryPoint] | None = None) -> tuple[str, ...]:
    return registry.names(_points(points))

def workflow_help(name: str, *, points: Iterable[EntryPoint] | None = None) -> str:
    wf: Workflow[object] = registry.load(_points(points), name, Workflow)
    return params.parser_for(wf.params, prog=f"agl run {name}").format_help()

async def _walk(
    services: Services, wf: Workflow[object], scope: RunScope, spec: RunSpec, given: object
) -> None:
    await services.workspaces.open(scope.label, None, spec.base_sha)
    leases = Leases()
    try:
        async with services.terminal:
            await wf.fn(
                Run(
                    params=given,
                    services=services,
                    scope=scope,
                    base=spec.base_sha,
                    leases=leases,
                )
            )
    finally:
        leases.release_all()

async def _under(store: Store, scope: RunScope) -> tuple[Namespace, ...]:
    found: list[Namespace] = []
    for namespace in await store.namespaces(scope):
        found.append(namespace)
        found.extend(await _under(store, scope.inside(namespace)))
    return tuple(found)

async def _kept(history: History, label: RunLabel, branch: str, base_ref: str) -> str | None:
    if await history.contains(branch, base_ref):
        return None
    return (
        f"the branch {branch!r} was kept: it is not yet in {base_ref!r}, and everything else this "
        f"run held has been taken away, its records included. Until that branch goes, `agl run "
        f"... -n {label}` is refused rather than started from the wrong place - so `git log "
        f"{branch}` is what is still there, and `git branch -D {branch}` is what frees the label "
        f"now. `agl clear {label} -f` is what would have deleted it in this call."
    )

def _points(points: Iterable[EntryPoint] | None) -> Iterable[EntryPoint]:
    return registry.installed() if points is None else points
