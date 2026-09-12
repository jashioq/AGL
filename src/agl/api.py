import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
from agl.config import distribution, registry, sources, toml_file, workflow_files, workspace_path
from agl.config.comparison import Updated, compared, replacements
from agl.config.inspection import PlaceableWorkflow, inspected
from agl.config.placement import Got, Removed, placed, removed
from agl.config.questions import Confirm, Questions, Removal, answered, needed
from agl.config.removal import removable
from agl.config.schema import Settings
from agl.ports.errors import ConflictError, InputError, InternalError, NotFoundError, UpstreamError
from agl.ports.fetch import Fetcher
from agl.ports.get_request import Fetch, GetRequest, RequestedWorkflow
from agl.ports.home_layout import AglHome, RunScope, workspace_dir
from agl.ports.ids import Namespace, ProjectName, RunLabel, WorkflowName
from agl.ports.run import RunSpec, checked_text
from agl.ports.store import Store
from agl.ports.sync import Syncer, SyncOutcome
from agl.ports.tree_layout import BASE_DIRNAME, TreesRoot, run_branch, worktree_branch
from agl.sdk import params
from agl.sdk._engine import preflight
from agl.sdk._engine.integration import Leases
from agl.sdk._engine.journal import Fingerprints
from agl.sdk._engine.services import Services
from agl.sdk.workflow import Run, Workflow

__all__ = [
    "Ask",
    "Cleared",
    "Listing",
    "Replayed",
    "clear",
    "get",
    "init",
    "list_workflows",
    "new_workflow",
    "remove",
    "resume",
    "run",
    "update",
    "workflow_help",
]

_TREES_DIRNAME: Final = ".agl-trees"

# How many files a resume's refusal names before it starts counting, per kind of difference. A
# directory rewritten wholesale would otherwise put its whole listing on a terminal, and what the
# message owes is enough to recognise the edit that was made - `git status` in the workspace is
# the complete answer. `tests/test_resume.py` pins the bound.
_SHOWN: Final = 5

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

@dataclass(frozen=True, slots=True)
class Replayed:
    """What a walk did not pay for: the steps it served off the ledger, over every namespace."""

    steps: int

async def run(
    services: Services,
    project: ProjectName,
    name: str,
    label: RunLabel,
    argv: Sequence[str] = (),
    *,
    base_ref: str | None = None,
    syncer: Syncer | None = None,
    home: AglHome | None = None,
    points: Iterable[EntryPoint] | None = None,
) -> Replayed:
    # Above the discovery chain, because `config/registry.py`'s `discovered` is what puts the
    # workspace venv on `sys.path` and its `load` is what imports the workflow's own module. A
    # dependency added to a workflow and not yet installed fails that import, and an install
    # underneath it never runs - so the next run fails identically and nothing ever heals.
    await _sync_workspace(syncer, home)
    found = _discovery(home, points)
    wf = _loaded(found, name)
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
        workflow_digests=_digests(found, name),
        label=label,
        base_ref=ref,
        base_sha=await services.history.resolve(ref),
        branch=branch,
        params=params.to_json(given),
        created_at=services.clock.now(),
    )

    async with services.workspaces.hold(label):
        await services.store.write_record(scope, spec.to_json())
        return await _walk(services, wf, scope, spec, given)

async def resume(
    services: Services,
    project: ProjectName,
    label: RunLabel,
    *,
    syncer: Syncer | None = None,
    home: AglHome | None = None,
    points: Iterable[EntryPoint] | None = None,
) -> Replayed:
    scope = RunScope(project, label)
    record = await services.store.read_record(scope)
    if record is None:
        raise NotFoundError(
            f"run {str(label)!r} does not exist - `agl run <workflow> -n {label}` starts one."
        )
    spec = RunSpec.from_json(record)

    await _sync_workspace(syncer, home)
    found = _discovery(home, points)
    wf = _loaded(found, spec.workflow)

    measured = _digests(found, spec.workflow)
    if measured != spec.workflow_digests:
        raise ConflictError(
            f"run {str(label)!r} was started by {spec.workflow!r}, and that workflow's own "
            f"directory is not what it was then: {_moved(spec.workflow_digests, measured)}. A run "
            f"digests every file there but bytecode and any `.DS_Store`, and AGL refuses a "
            f"resume that disagrees rather than migrating one: every step already on this run's "
            f"ledger was produced by those files as they stood. So this run finishes against them "
            f"and no others - put the directory back to what it was when the run started, out of "
            f"version control or from wherever the earlier copy is. Otherwise `agl clear {label}` "
            f"drops the ledger and starts the run again on the {spec.workflow!r} you have now."
        )

    given = params.from_json(wf.params, spec.params)

    await preflight.check(services.agents, services.history, wf.fn)

    async with services.workspaces.hold(label):
        return await _walk(services, wf, scope, spec, given)

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

# The workspace is made unconditionally rather than after a check: `make_workspace` creates each of
# the three things it makes only where that thing is absent, so the workspace an operator already
# has is left exactly as it stands and there is no second answer here about what "already there"
# means. `registry.GROUP` travels as an argument because `config/registry.py` imports this module,
# so the group is defined once and reaches the writer the only way round the import allows. The
# bound travels beside it for a different reason - the writer renders documents and has no business
# knowing what AGL is - and reading it costs a look at this interpreter's own metadata, which is
# what keeps `agl new` a command that resolves no project.
#
# The scaffold is written before the install, so an installer that refuses leaves the two documents
# on disk and a second `agl new` under the same name refuses them rather than writing them again.
async def new_workflow(syncer: Syncer, home: AglHome, name: WorkflowName) -> Path:
    toml_file.make_workspace(home)
    written = toml_file.make_workflow(home, name, registry.GROUP, distribution.requirement())
    await _sync_workspace(syncer, home)
    return written

# What became of each workflow is reported before the sync, because a sync that raises would
# otherwise take the only account of what was placed out with it.
async def get(
    fetcher: Fetcher,
    syncer: Syncer,
    home: AglHome,
    request: GetRequest,
    confirm: Confirm,
    report: Callable[[Got], None],
) -> Got:
    got = await _placed_after_asking(fetcher, home, request.fetches, confirm, needed, measured={})
    report(got)
    if got.placed:
        await _sync_workspace(syncer, home)
    return got

# No sync, and so no uv and no network: discovery walks workflows/, where the entry is gone at once,
# and the next sync - `run` and `resume` start with one - drops the member from uv.lock and
# uninstalls what only it needed (uv 0.11, measured).
def remove(home: AglHome, name: str, confirm: Confirm) -> Removed | None:
    entry = removable(home, name)
    if not confirm(str(Removal(entry))):
        return None
    return removed(home, entry.path)

# `get`'s phases over whatever moved, and reported before the sync for `get`'s reason.
async def update(
    fetcher: Fetcher,
    syncer: Syncer,
    home: AglHome,
    name: str | None,
    confirm: Confirm,
    report: Callable[[Updated], None],
) -> Updated:
    comparison = await compared(fetcher, home, name)
    replacing = replacements(home, comparison.moved)
    got = await _placed_after_asking(
        fetcher, home, replacing.fetches, confirm, replacing.questions, replacing.measured
    )
    updated = Updated(comparison, replacing, got)
    report(updated)
    if got.placed:
        await _sync_workspace(syncer, home)
    return updated

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
) -> Replayed:
    await services.workspaces.open(scope.label, None, spec.base_sha)
    leases = Leases()
    fingerprints = Fingerprints()
    try:
        async with services.terminal:
            await wf.fn(
                Run(
                    params=given,
                    services=services,
                    scope=scope,
                    base=spec.base_sha,
                    fingerprints=fingerprints,
                    leases=leases,
                )
            )
    finally:
        leases.release_all()
    return Replayed(steps=fingerprints.replays)

# Three phases, and nothing reaches the workspace before the last of them: every download is fetched
# and inspected, then every question is asked, and only then is anything placed - so no question is
# ever put about a workspace the command has already changed, and a copy `update` measured that has
# moved by the time it would be replaced is refused there rather than asked about again.
# `tests/test_get.py` holds the order, and `tests/test_update.py` holds it from `update`'s side.
async def _placed_after_asking(
    fetcher: Fetcher,
    home: AglHome,
    fetches: Sequence[Fetch],
    confirm: Confirm,
    questions: Questions,
    measured: Mapping[RequestedWorkflow, str],
) -> Got:
    fetched = [answer for fetch in fetches for answer in await fetcher.fetch(fetch)]
    inspections = inspected(fetched, home)
    placeables = [one for one in inspections if isinstance(one, PlaceableWorkflow)]
    return placed(home, fetched, inspections, answered(placeables, confirm, questions), measured)

# A caller that handed no syncer installs nothing, the way one that handed its own points walks no
# workspace: `agl.testing`'s harness is both at once and `cli/main.py` is neither. Making the
# workspace is the job of whatever writes a workflow into it and not this one's - `run` and
# `resume` read a workflow out of one that is already there.
#
# An installer that could not be *started* raises out of `sync` rather than answering, which is
# `ports/sync.py`'s own clause, and it is deliberately not caught: nothing was tried, and a machine
# with no installer on it is not one a run can carry on past.
#
# The environment is stat-ed before the installer is spawned and never after, because `uv sync`
# builds the venv before it resolves: a first-ever sync that then failed leaves one standing, and
# an answer read afterwards would let `_unchanged` describe a state no sync has ever produced.
async def _sync_workspace(syncer: Syncer | None, home: AglHome | None) -> None:
    if syncer is None or home is None:
        return
    stood = workspace_path.venv_exists(home)
    outcome = await syncer.sync(workspace_dir(home))
    if outcome.synced:
        workspace_path.write_editor_pth(home)
        return
    if not stood:
        raise UpstreamError(_refused(outcome))
    print(_unchanged(outcome), file=sys.stderr)

# Never on stdout, for `cli/commands/__init__.py`'s reason: what a machine consumes goes there and
# this is a note to whoever is reading the terminal. It is written here rather than handed back for
# a command to print, because what a run hands back it hands back at the end - and the end of a run
# is hours after the point at which knowing this would have been worth anything.
def _unchanged(outcome: SyncOutcome) -> str:
    return (
        f"warning: the sync was refused - uv exited {outcome.status} rather than 0 - and this "
        f"workspace already had an environment, so it stands exactly as the last sync that "
        f"succeeded left it and AGL carries on against that. What a workflow imports may therefore "
        f"be older than what it now declares, and anything added since is not installed at all. "
        f"Nothing above uv decided this and nothing above it can explain it - a resolution that "
        f"cannot be satisfied, an index that could not be reached and a package that will not "
        f"build all arrive here as the same non-zero exit - so what uv said is printed whole below "
        f"rather than summarised:\n\n{outcome.output.rstrip()}"
    )

def _refused(outcome: SyncOutcome) -> str:
    return (
        f"the sync was refused: uv exited {outcome.status} rather than 0, and this workspace has "
        f"no environment to fall back on - so what the workflows in it declare is not installed "
        f"and a run that imports one of those packages will not find it. Carrying on would only "
        f"defer the same failure to the first workflow that imports one, where it would name a "
        f"package rather than the install that never happened. Nothing above uv decided this and "
        f"nothing above it can explain it - a resolution that cannot be satisfied, an index that "
        f"could not be reached and a package that will not build all arrive here as the same "
        f"non-zero exit - so what uv said is printed whole below rather than "
        f"summarised:\n\n{outcome.output.rstrip()}"
    )

async def _under(store: Store, scope: RunScope) -> tuple[Namespace, ...]:
    found: list[Namespace] = []
    for namespace in await store.namespaces(scope):
        found.append(namespace)
        found.extend(await _under(store, scope.inside(namespace)))
    return tuple(found)

def _loaded(found: registry.Discovery, name: str) -> Workflow[object]:
    registry.check_unbroken(found, name)
    registry.check_satisfied(found, name)
    return registry.load(found.points, name, Workflow)

# A caller that handed its own points over walked no workspace, so its workflow was read out of no
# directory and there is nothing to digest. Every declaration `config/registry.py` reads out of a
# workspace carries the directory it came from, so the empty answer is that seam and never a
# workflow whose files went unmeasured.
def _digests(found: registry.Discovery, name: str) -> Mapping[str, str]:
    directory = found.directories.get(name)
    return {} if directory is None else workflow_files.digests(directory)

def _moved(recorded: Mapping[str, str], measured: Mapping[str, str]) -> str:
    changed = sorted(
        name for name in recorded if name in measured and measured[name] != recorded[name]
    )
    added = sorted(name for name in measured if name not in recorded)
    removed = sorted(name for name in recorded if name not in measured)
    return "; ".join(
        f"{what} {_listed(names)}"
        for what, names in (("changed", changed), ("added", added), ("removed", removed))
        if names
    )

def _listed(names: Sequence[str]) -> str:
    rest = len(names) - _SHOWN
    shown = ", ".join(names[:_SHOWN])
    return shown if rest <= 0 else f"{shown} and {rest} more"

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
