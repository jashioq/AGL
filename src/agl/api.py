from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
from agl.config import registry, sources, toml_file
from agl.config.schema import Settings
from agl.ports.errors import ConflictError, InputError, InternalError, NotFoundError
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.run import RunSpec, checked_text
from agl.ports.store import Store
from agl.ports.tree_layout import BASE_DIRNAME, TreesRoot, run_branch, worktree_branch
from agl.sdk import params
from agl.sdk._engine import preflight
from agl.sdk._engine.integration import Leases
from agl.sdk._engine.services import Services
from agl.sdk.workflow import Run, Workflow

__all__ = [
    "Ask",
    "Cleared",
    "Listing",
    "clear",
    "init",
    "list_workflows",
    "resume",
    "run",
    "workflow_help",
]

_TREES_DIRNAME: Final = ".agl-trees"

_BUILD_PROMPT: Final = (
    "What command builds and tests this project? AGL runs it at the merge gate, through a shell, "
    "in a worktree of its own - `./gradlew build`, `make test`, `npm run build`.\n"
    "build command: "
)

type Ask = Callable[[str], str]

@dataclass(frozen=True, slots=True)
class Cleared:
    """A cleared run's branches and the checkouts they were on, by name: none is there now."""

    branches: tuple[str, ...]

    worktrees: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class Listing:
    """What a workspace holds: the names it declares, and the directories that declared none."""

    names: tuple[str, ...]

    broken: tuple[registry.BrokenWorkflow, ...]

async def run(
    services: Services,
    project: ProjectName,
    name: str,
    label: RunLabel,
    argv: Sequence[str] = (),
    *,
    base_ref: str | None = None,
    home: AglHome | None = None,
    points: Iterable[EntryPoint] | None = None,
) -> None:
    wf = _loaded(_discovery(home, points), name)
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
            f"whatever `--from` said ignored. AGL did not leave it - `clear` takes a run's own "
            f"branch away with everything else it held, so a branch by this name with no record "
            f"beside it is one something else made. `git log {branch}` is what is on it, `git "
            f"branch -D {branch}` frees the label, and any other label starts a run of its own."
        )

    await preflight.check(services.agents, services.history, wf.fn)

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
    home: AglHome | None = None,
    points: Iterable[EntryPoint] | None = None,
) -> None:
    scope = RunScope(project, label)
    record = await services.store.read_record(scope)
    if record is None:
        raise NotFoundError(
            f"run {str(label)!r} does not exist - `agl run <workflow> -n {label}` starts one."
        )
    spec = RunSpec.from_json(record)

    wf = _loaded(_discovery(home, points), spec.workflow)

    if wf.version != spec.workflow_version:
        raise ConflictError(
            f"run {str(label)!r} was started by {spec.workflow!r} version "
            f"{spec.workflow_version!r} and {spec.workflow!r} in your workspace is now version "
            f"{wf.version!r}. A run stamps its workflow's version and AGL refuses a mismatch "
            f"rather than migrating one: every step already on this run's ledger was "
            f"produced by the workflow as it was then. So this run finishes against that workflow "
            f"and no other - put the directory back to what it was at {spec.workflow_version!r}, "
            f"out of version control or from wherever the earlier copy is, rather than editing "
            f"the `version=` line back, which would replay the ledger against code that never "
            f"wrote it. Otherwise `agl clear {label}` drops the ledger and starts the run again "
            f"on {wf.version!r}."
        )

    given = params.from_json(wf.params, spec.params)

    await preflight.check(services.agents, services.history, wf.fn)

    async with services.workspaces.hold(label):
        await _walk(services, wf, scope, spec, given)

async def clear(services: Services, project: ProjectName, label: RunLabel) -> Cleared:
    scope = RunScope(project, label)
    if await services.store.read_record(scope) is None:
        raise NotFoundError(f"run {str(label)!r} does not exist - there is nothing to clear.")

    worktrees: list[str] = []
    branches: list[str] = []
    async with services.workspaces.hold(label):
        for namespace in await _under(services.store, scope):
            await services.workspaces.remove(label, namespace)
            await services.workspaces.discard(label, namespace)
            worktrees.append(str(namespace))
            branches.append(worktree_branch(label, namespace))

        await services.workspaces.remove(label, None)
        await services.workspaces.discard(label, None)
        worktrees.append(BASE_DIRNAME)
        branches.append(run_branch(label))

        await services.store.remove(scope)
        return Cleared(branches=tuple(branches), worktrees=tuple(worktrees))

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

def list_workflows(
    *, home: AglHome | None = None, points: Iterable[EntryPoint] | None = None
) -> Listing:
    found = _discovery(home, points)
    return Listing(names=registry.names(found.points), broken=found.broken)

def workflow_help(
    name: str, *, home: AglHome | None = None, points: Iterable[EntryPoint] | None = None
) -> str:
    wf = _loaded(_discovery(home, points), name)
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

def _loaded(found: registry.Discovery, name: str) -> Workflow[object]:
    registry.check_unbroken(found, name)
    return registry.load(found.points, name, Workflow)

# Points handed over are the whole of what the caller has: the walk is skipped, so nothing reaches
# the operator's home and `config/workspace_path.py` writes no entry to `sys.path`. That is what
# `agl.testing`'s harness runs a workflow through, and it is why the parameter is still here.
def _discovery(home: AglHome | None, points: Iterable[EntryPoint] | None) -> registry.Discovery:
    if points is not None:
        return registry.Discovery(tuple(points), ())
    if home is None:
        raise InternalError(
            "an operation was asked to resolve a workflow and was handed neither a home to read "
            "the workspace under nor the entry points to read in its place. Nothing typed on the "
            "command line reaches this: `cli/main.py` passes the resolved home on every "
            "invocation and `agl.testing`'s harness passes points on every one of its own, so the "
            "two parameters are one argument spelled two ways and a call site naming neither has "
            "dropped it. That is AGL's own bug"
        )
    return registry.discovered(home)
