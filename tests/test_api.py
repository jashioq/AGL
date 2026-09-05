"""The walking skeleton, driven from the library side: `api.run` on `container.fakes()`.

Every operation addressed to a run goes through the all-fakes bundle - no network, no git, no
process - which is measurable target #8 and the reason those three take a bundle rather than build
one. The other two take no bundle at all, which is per-command composition arriving as a
signature: `init` takes settings alone, `list_workflows` takes neither. The workflows
are declared in this module and reached through hand-constructed `EntryPoint` values, exactly as
`tests/config/test_registry.py` and `tests/sdk/test_workflow.py` do: an entry point is a name, a
`module:attr` string and a group, so a registration line resolves without installing a package.
`workflows/noop/` was deliberately not used - it did not exist yet when this file was written, and
it has since been deleted, so the workflows here have outlived it twice over.

**The `Stop` criterion is pinned by identity, not by class.** An `assert isinstance(...)` would pass
against an `api.run` that caught the workflow's `ReviewNotConverging`, threw it away and raised a
fresh one of the same class - which is the version of this bug worth catching, since the exit code
would still be 7 and the traceback would name this module instead of the step that stopped.

**The record is asserted field by field**, key set included, because `run.json` is the
one value in AGL with no other copy anywhere. The `base_sha` assertions are the ones with teeth:
full length, and not the ref name - `refs/heads/main` would satisfy every "is a string" check.

**A real repository is in this file, and only where a fake cannot answer.** The bundle's
`FakeWorkspaceProvider` is a full implementation of the port - it makes real directories under the
trees root and keeps a real registry of which line of work each one holds - so "a workflow that
takes no step at all still leaves `_base` provisioned" is asserted on fakes, where it costs a
millisecond and no git. What fakes cannot answer is the real promise: that `agl/<label>` is a *ref
in a git repository* a person can `git log`, that the checkout sits at the pinned commit rather
than at wherever the ref has got to since, and that a step reopening it registers no second
worktree. Those two tests build a repository, put `GitWorkspaceProvider` and `GitHistory` under
`api.run`, and ask git itself.
"""

import subprocess
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.git.history import GitHistory
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.config import container, distribution, registry, sources
from agl.ports.agent import AgentOutcome, Claude, StopReason
from agl.ports.errors import ConflictError, InputError, NotFoundError, exit_code_for
from agl.ports.home_layout import AglHome, RunScope, workflows_dir, workspace_pyproject
from agl.ports.ids import Namespace, ProjectName, RunLabel, WorkflowName
from agl.ports.run import JsonValue, RunSpec
from agl.ports.tree_layout import TreesRoot, base_worktree, run_branch
from agl.ports.workspace import Workspace, WorkspaceProvider
from agl.sdk.params import arg
from agl.sdk.roles import Role, role
from agl.sdk.workflow import Run, Stop, workflow

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# `run.json`, key for key. Written out rather than read off `RunSpec`'s fields, because the
# published shape of the file is what this asserts and a record that agreed with itself would pass.
WIRE_KEYS: Final = frozenset(
    {"workflow", "workflow_version", "label", "base_ref", "base_sha", "branch", "params",
     "created_at"}
)

@dataclass(frozen=True)
class ProbeParams:
    """The example params shape, which `agl run probe -r "add oauth" -c 4` fills in."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)

@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""

class ReviewNotConverging(Stop):
    """A workflow's own reason to stop, spelled against the SDK's `Stop`."""

# The file the real repository below is seeded with, matching what `_fakes` seeds its own with, and
# the one a commit landing mid-`api.run` adds.
SEEDED: Final = "src/a.txt"
LANDED: Final = "src/landed.txt"

@role(model=Claude.SONNET)
def looking() -> Role:
    """An effect role: no reporting tool, so a step over it results in `null` and its whole purpose
    is that a step happened at all.

    `Claude.SONNET` because a role has to name a model and the fakes bundle serves both providers;
    nothing below depends on which."""
    return Role(name="look", instructions="look at what is already here")

# What each workflow was handed and what one of them raised, at module level because the workflows
# have to be: `EntryPoint.load` imports a module and reads an attribute in it, and sees no local.
handed: Final[list[Run[ProbeParams]]] = []
raised: Final[list[Stop]] = []

@workflow(version="1.1")
async def probe(run: Run[ProbeParams]) -> None:
    """Returns. The wiring probe, with params it can be asserted on."""
    handed.append(run)

@workflow(version="0.1")
async def halting(run: Run[NoParams]) -> None:
    """Ends deliberately, with a reason of its own - which the framework must not rename."""
    stop = ReviewNotConverging("two rounds and no convergence")
    raised.append(stop)
    raise stop

@workflow(version="0.1")
async def stepping(run: Run[NoParams]) -> None:
    """Takes one step, so that the checkout `api.run` provisioned is asked for a second time.

    No `commit=` and a role with no reporting tool, because neither is what this is for: the step
    exists to reach `Steps._namespace`, which is the lazy open that stopped being the first caller.
    The walk restores the checkout on the way out and records `null`.
    """
    await run.step(looking())

def _point(name: str, attribute: str) -> EntryPoint:
    """A `probe = "agl.workflows.probe:probe"` line, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)

POINTS: Final = (_point("probe", "probe"), _point("halting", "halting"))

# Deliberately not in `POINTS`. `test_list_workflows_is_the_registrys_sorted_names` asserts the
# whole listing, so a third workflow added to that tuple would be one test editing an unrelated
# assertion about something else entirely; the two tests that need it pass both.
STEPPING: Final = (_point("stepping", "stepping"),)

def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment: one repository seeded with a file, one store, one frozen clock."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})

async def _record(harness: container.FakeServices) -> dict[str, JsonValue]:
    """The run's record, asserted present - every caller below is testing what is in it."""
    record = await harness.services.store.read_record(SCOPE)
    assert record is not None, "no run.json was written for this run"
    return record

async def _run(
    harness: container.FakeServices, name: str = "probe",
    argv: Sequence[str] = ("-r", "add oauth"), *, base_ref: str | None = None,
    points: Sequence[EntryPoint] = POINTS,
) -> None:
    """One invocation, with this module's entry points supplied instead of what is installed."""
    await api.run(harness.services, PROJECT, name, LABEL, argv, base_ref=base_ref, points=points)

# --- a run that completes ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_workflow_that_returns_runs_to_completion(tmp_path: Path) -> None:
    """`agl run probe -n auth` end to end on fakes - the first acceptance criterion."""
    handed.clear()
    harness = _fakes(tmp_path)

    await _run(harness)

    assert len(handed) == 1
    assert handed[0].services is harness.services

@pytest.mark.asyncio
async def test_the_record_holds_exactly_the_published_fields(tmp_path: Path) -> None:
    """`run.json`'s published shape, key for key and value for value. `created_at` is the sample
    moment because the fakes bundle's clock is frozen at it, and `concurrent` is a default the user
    never typed - `resume` takes no flags, so an unspoken one is lost if it is not here."""
    harness = _fakes(tmp_path)
    await _run(harness)
    record = await _record(harness)

    assert set(record) == WIRE_KEYS
    assert record["workflow"] == "probe"
    assert record["workflow_version"] == "1.1"
    assert record["label"] == "auth"
    assert record["branch"] == run_branch(LABEL) == "agl/auth"
    assert record["created_at"] == "2026-08-18T09:14:02Z"
    assert record["params"] == {"request": "add oauth", "concurrent": 3}
    # Written by AGL and read back by AGL: the record survives the round trip it exists for.
    assert RunSpec.from_json(record).label == LABEL

@pytest.mark.asyncio
async def test_the_base_sha_is_the_resolved_commit_and_not_the_ref_name(tmp_path: Path) -> None:
    """The pin. An abbreviation is refused by `RunSpec`; a ref name would pin nothing."""
    harness = _fakes(tmp_path)
    history = harness.services.history
    default = await history.default_ref()
    resolved = await history.resolve(default)

    await _run(harness)
    record = await _record(harness)

    assert record["base_ref"] == default
    assert record["base_sha"] == resolved
    assert record["base_sha"] != record["base_ref"]
    assert isinstance(record["base_sha"], str)
    assert len(record["base_sha"]) in {40, 64}

@pytest.mark.asyncio
async def test_from_names_the_base_ref_and_the_default_is_the_repositorys(tmp_path: Path) -> None:
    """`--from <ref>`. What the user said is kept; what it meant is resolved beside it."""
    harness = _fakes(tmp_path)

    await _run(harness, base_ref="main")
    record = await _record(harness)

    assert record["base_ref"] == "main"
    assert record["base_sha"] == await harness.services.history.resolve("main")

@pytest.mark.asyncio
async def test_a_workflow_that_takes_no_step_still_leaves_base_provisioned(tmp_path: Path) -> None:
    """Provisioning, and the whole of what it is observable as. `probe` takes no steps at all, so
    the lazy open in `sdk/_engine/steps.py` is never reached - which makes this precisely the run
    for which "`agl/<label>` is a real ref from run start, so progress is inspectable live" used to
    be false. This file once asserted the opposite in as many words, that a completed run left
    nothing but `run.json`; what changed is not how strong the claim is but which of the two callers
    of `WorkspaceProvider.open` gets there first.

    Both halves, because a provisioning that made the directory and no line of work - or the line of
    work and no directory - is one that neither `git log agl/auth` nor a person going to look at
    what the agents did could use. The branch is asserted to be *at the pin*, not merely to exist:
    a `_base` cut from somewhere else is a run whose first step chains its fingerprint off one
    commit and whose checkout starts at another."""
    harness = _fakes(tmp_path)

    await _run(harness)

    assert base_worktree(TreesRoot(tmp_path / "trees"), LABEL).is_dir()
    assert harness.repository.tip(run_branch(LABEL)) == (await _record(harness))["base_sha"]

class _Refusing(WorkspaceProvider):
    """A provider that provisions nothing, which is the one failure `container.fakes()` cannot
    arrange.

    A stub rather than a broken bundle: what the test below needs is `open` raising, and the two
    teardown verbs exist only because the port has four members - reaching either of them would
    mean `run` had started taking workspaces back, which it does not. `ConflictError` is `open`'s
    own refusal class (`ports/workspace.py`), so nothing about the shape of the failure is invented
    for the occasion.

    `hold` is the fourth and is granted rather than refused, because `api.run` takes the run's claim
    before it writes anything and this test is about the line after that. A stub that refused it
    would move the failure and assert nothing about the ordering it is here for.
    """

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        raise ConflictError("this provider refused to provision anything, deliberately")

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("nothing in `api.run` takes a workspace back")

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("nothing in `api.run` deletes a line of work")

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        return _granted()

@asynccontextmanager
async def _granted() -> AsyncIterator[None]:
    """A run claim nothing contends for: what `WorkspaceProvider.hold` is when the test is about
    something else entirely."""
    yield

@pytest.mark.asyncio
async def test_a_provisioning_that_fails_leaves_the_record_where_clear_can_find_it(
    tmp_path: Path,
) -> None:
    """The order of the last two lines of `run`, pinned from the one side it is visible from.

    `run.json` is written before the workspace is provisioned because it is the only enumeration
    `clear` has: `WorkspaceProvider` offers none by design, so a crash after `open()` with no record
    on disk leaves `agl/<label>` and `.trees/<label>/_base/` behind with nothing in AGL able to name
    either again. This is that ordering asserted through the failure that isolates it - a provider
    that cannot provision at all - and the second assertion is the other half of it: provisioning
    failed, so the workflow must not have been entered."""
    handed.clear()
    harness = _fakes(tmp_path)
    services = replace(harness.services, workspaces=_Refusing())

    with pytest.raises(ConflictError, match="refused to provision"):
        await api.run(services, PROJECT, "probe", LABEL, ("-r", "add oauth"), points=POINTS)

    assert (await _record(harness))["branch"] == run_branch(LABEL)
    assert handed == [], "the workflow ran although its workspace was never provisioned"

# --- params, and the two refusals -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_workflow_gets_its_dataclass_and_the_record_its_values(tmp_path: Path) -> None:
    """One chain: argv, the instance the workflow reads, and the mapping `run.json` holds."""
    handed.clear()
    harness = _fakes(tmp_path)

    await _run(harness, argv=["-r", "add oauth", "-c", "4"])

    assert handed[0].params == ProbeParams(request="add oauth", concurrent=4)
    assert isinstance(handed[0].params, ProbeParams)
    record = await _record(harness)
    assert record["params"] == {"request": "add oauth", "concurrent": 4}

@pytest.mark.asyncio
async def test_flags_the_workflow_refuses_stop_it_before_anything_runs(tmp_path: Path) -> None:
    """Validation failure is `InputError` -> exit 2, *before anything runs* - so no record."""
    handed.clear()
    harness = _fakes(tmp_path)

    with pytest.raises(InputError) as caught:
        await _run(harness, argv=[])

    assert exit_code_for(caught.value) == 2
    assert handed == []
    assert await harness.services.store.read_record(SCOPE) is None

@pytest.mark.asyncio
async def test_the_same_label_twice_is_refused_in_the_refusals_own_words(tmp_path: Path) -> None:
    """The second acceptance criterion: exit 4, and the message it is written with. The refusal is
    here rather than in the command because commands staying dumb is the whole repair - and because
    a library caller needs the same answer as `agl run` does."""
    handed.clear()
    harness = _fakes(tmp_path)
    await _run(harness)

    with pytest.raises(ConflictError) as caught:
        await _run(harness)

    assert str(caught.value) == (
        "run 'auth' already exists - `agl resume auth` or `agl clear auth`."
    )
    assert exit_code_for(caught.value) == 4
    assert len(handed) == 1, "the refused run invoked the workflow anyway"

@pytest.mark.asyncio
async def test_a_deliverable_branch_that_already_exists_refuses_the_run(tmp_path: Path) -> None:
    """The refusal, and the silent misdirection underneath it.

    A branch standing where the store has nothing is the state `WorkspaceProvider.open` takes its
    **attaching** path in - `worktree add <path> <branch>` rather than `add -b <branch> ... <base>`
    - so a later `agl run ... -n auth --from main` starts from the old tip with `--from` silently
    ignored, because `base` is consulted only when provisioning.

    Nothing of AGL's leaves that state: a run's record is written before its checkout is cut and
    taken away after its branches are, so what this arranges through the repository is a branch
    somebody made by hand or one that outlived the repository AGL was pointed at. Arranging it that
    way is also what makes this a test about `run` rather than about `clear`. `--from` is passed
    explicitly, because the flag being ignored is the failure this refusal exists to prevent.

    Both halves of "leaves nothing behind" are asserted: no record, because a refusal in front of
    `write_record` must leave the label as it found it, and no workflow invocation, because a run
    that got as far as its function has already started."""
    handed.clear()
    harness = _fakes(tmp_path)
    branch = run_branch(LABEL)
    harness.repository.move(branch, await harness.services.history.resolve("main"))

    with pytest.raises(ConflictError) as caught:
        await _run(harness, base_ref="main")

    assert exit_code_for(caught.value) == 4
    assert branch in str(caught.value), "the refusal does not name the branch that is in the way"
    assert f"git branch -D {branch}" in str(caught.value), (
        "the refusal does not say how to free the label. `agl clear` is not the answer and must "
        "not be offered as one: it takes a run's branch away with everything else it held, so by "
        "the time a branch stands alone there is no record left for it to address"
    )
    assert await harness.services.store.read_record(SCOPE) is None, (
        "a run refused before `write_record` left a record behind, so an operator now has to clear "
        "a run that never started"
    )
    assert handed == [], "the refused run invoked the workflow anyway"

@pytest.mark.asyncio
async def test_an_unknown_workflow_name_is_a_not_found_and_records_nothing(tmp_path: Path) -> None:
    """The third: exit 3, from `config/registry.py`, before the store is touched at all."""
    harness = _fakes(tmp_path)

    with pytest.raises(NotFoundError) as caught:
        await _run(harness, name="nosuch")

    assert exit_code_for(caught.value) == 3
    assert "nosuch" in str(caught.value)
    assert await harness.services.store.read_record(SCOPE) is None

# --- the ordering hazard -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_stop_subclass_leaves_api_run_unwrapped_and_exits_seven(tmp_path: Path) -> None:
    """The criterion: the *same object*, and 7 rather than 6 or 70. Identity is the
    assertion, not the class - see the module docstring. The last line is the other half of the
    order `run` is written in: the record is written before the workflow is invoked, so a stop or a
    crash leaves a run to resume or to clear, which is `Stop`'s own promise that results persist."""
    raised.clear()
    harness = _fakes(tmp_path)

    with pytest.raises(ReviewNotConverging) as caught:
        await _run(harness, name="halting", argv=[])

    assert caught.value is raised[0]
    assert exit_code_for(caught.value) == 7
    assert (await _record(harness))["workflow"] == "halting"

# --- against a real repository --------------------------------------------------------------------

def _git(where: Path, *argv: str) -> str:
    """One git command, for arranging and observing. Never for the thing under test.

    `tests/sdk/test_run_step.py`'s helper and its argument: a test that built its repository through
    the adapter would be resting its arrangement on the behaviour it is about to check.
    """
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout

@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit on `main`, and no configuration from this machine.

    The `GIT_CONFIG_*` variables are what make these two tests the same tests everywhere - a
    developer with `commit.gpgsign` on, a `core.hooksPath` of their own or a template directory
    would otherwise be running different ones - and they go through `monkeypatch` so the adapters,
    which inherit the environment, see them too. It sits beside `tmp_path/trees` rather than under
    it: the trees root is not the repository, and a worktree cut into the user's own checkout is
    the arrangement the layout exists to end.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL api")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    seeded = work / SEEDED
    seeded.parent.mkdir(parents=True)
    seeded.write_bytes(b"one\n")
    _git(work, "add", SEEDED)
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work

class _MovingHistory(GitHistory):
    """`GitHistory`, except that a commit lands on the ref the instant it has been resolved.

    `base_sha` is pinned against a commit landing on `main` between run and resume. Inside
    `api.run` that same hazard has a much smaller window - between the `resolve` that computes the
    pin and the `open` that cuts the checkout - and nothing a test can do from outside fits into it,
    the two being consecutive lines. So it is arranged from inside, and that is not decoration: it
    is the only arrangement under which handing `open` the `--from` string and handing it
    `spec.base_sha` name different commits. Without the move the two are the same commit and the
    assertion would pass against either.

    Subclassed rather than written out, because the difference from the real adapter is exactly one
    method and a hand-rolled `History` here would be six members of boilerplate agreeing with it.
    """

    def __init__(self, repository: Path) -> None:
        super().__init__(repository)
        self._at = repository

    async def resolve(self, ref: str) -> str:
        """What `GitHistory` answers, and then a commit on `ref` that its answer predates."""
        pinned = await super().resolve(ref)
        (self._at / LANDED).write_bytes(b"landed while the run was starting\n")
        _git(self._at, "add", LANDED)
        _git(self._at, "commit", "-q", "-m", "a commit landing between the resolve and the open")
        return pinned

def _over(
    repository: Path, tmp_path: Path, *, moving: bool = False, claude: Script | None = None
) -> container.FakeServices:
    """The fakes bundle with its two git ports made real - the smallest arrangement that puts
    `api.run` over an actual repository.

    Two of nine fields replaced, and both are needed: `workspaces` because the claims here are
    about a git worktree and a git ref, and `history` because `api.run` resolves the pin through it
    and a `FakeHistory` answers about a `FakeRepository` that has never heard of these commits. The
    store stays the in-memory one - `run.json`'s content is asserted on fakes above, and nothing
    here is a claim about a file under `AGL_HOME`.
    """
    trees = TreesRoot(tmp_path / "trees")
    harness = container.fakes(trees, claude=claude)
    return replace(
        harness,
        services=replace(
            harness.services,
            workspaces=GitWorkspaceProvider(repository, trees),
            history=_MovingHistory(repository) if moving else GitHistory(repository),
        ),
    )

def _worktrees(repository: Path) -> tuple[Path, ...]:
    """Every checkout git has registered against this repository, resolved, in git's own order.

    Resolved on both sides wherever this is compared, because git records a worktree's real path
    and `/tmp` is a symlink on macOS - the same trap `GitWorkspaceProvider._branch_at` documents.
    """
    listing = _git(repository, "worktree", "list", "--porcelain")
    at = "worktree "
    return tuple(
        Path(line[len(at) :]).resolve() for line in listing.splitlines() if line.startswith(at)
    )

def _looking(seen: list[Path]) -> Script:
    """An agent that writes nothing, reports nothing, and records where it was pointed.

    `AgentTask.workspace` is the only place the checkout a step actually ran in is observable from
    above the engine, which makes it the honest way to ask whether the second `open` handed back
    the place the first one provisioned.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        seen.append(conversation.task.workspace)
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script

@pytest.mark.asyncio
async def test_the_checkout_is_cut_from_the_pin_and_not_from_the_ref(
    repository: Path, tmp_path: Path
) -> None:
    """The pin, carried all the way into the working checkout. `--from main` is resolved once,
    the ref moves under it, and `agl/auth` still starts where the record says the run started.

    This is what "pass `spec.base_sha`, never `base_ref`" costs to get wrong: `open` accepts a ref
    expression too, so handing it the string would work every day except the one where somebody
    pushes while a run is starting - and then the checkout begins at a commit the `Journal` never
    hashed, and every first fingerprint in the run is taken over a head the worktree is not at."""
    pinned = _git(repository, "rev-parse", "--verify", "main").strip()
    harness = _over(repository, tmp_path, moving=True)

    await _run(harness, base_ref="main")

    assert _git(repository, "rev-parse", "--verify", "main").strip() != pinned, (
        "the arrangement never moved the ref, so this test distinguishes nothing"
    )
    assert (await _record(harness))["base_sha"] == pinned
    assert _git(repository, "rev-parse", "--verify", f"refs/heads/{run_branch(LABEL)}").strip() == (
        pinned
    )
    place = base_worktree(TreesRoot(tmp_path / "trees"), LABEL)
    assert _git(place, "rev-parse", "HEAD").strip() == pinned
    assert not (place / LANDED).exists(), "the checkout carries a commit made after the pin"

@pytest.mark.asyncio
async def test_a_step_reopens_that_checkout_rather_than_cutting_a_second(
    repository: Path, tmp_path: Path
) -> None:
    """Idempotence end to end: `api.run` provisions, `run.step` asks again, and git registers one
    worktree.

    `WorkspaceProvider.open` promises this and `tests/contracts/workspace.py` holds both adapters
    to it, but neither says anything about the two callers now being different modules - and that
    is the whole of the risk. The worktree count is the assertion with teeth: a second `add` at
    this path is not merely waste, it is the refusal `open` makes instead of provisioning over a
    place something already holds, so an engine that had stopped reopening would not quietly cut a
    second checkout - it would fail the run."""
    seen: list[Path] = []
    harness = _over(repository, tmp_path, claude=_looking(seen))

    await _run(harness, name="stepping", argv=(), points=(*POINTS, *STEPPING))

    place = base_worktree(TreesRoot(tmp_path / "trees"), LABEL)
    assert seen == [place], "the step ran somewhere other than the place `api.run` provisioned"
    assert _worktrees(repository) == (repository.resolve(), place.resolve())
    assert _git(place, "rev-parse", "--abbrev-ref", "HEAD").strip() == run_branch(LABEL)

# --- `--from` reaches git before the record that checks it ----------------------------------------

# The one value that cannot be handed to a child process, written the long way round: a
# module-level `Final` holding a surrogate *literal* crashes `mypy --strict` inside its own cache,
# which `tests/test_no_literal_surrogates.py` is the fence around and this is one of the shapes
# that fence permits.
LONE_SURROGATE: Final = chr(0xD800)

class _RecordingHistory(GitHistory):
    """`GitHistory`, plus a note of every ref it was asked to resolve.

    `_MovingHistory`'s subclassing argument, for the opposite purpose: that one changes what
    `resolve` does, this one changes nothing and only records that it happened. What it makes
    assertable is a **negative** - that a value refused upstream never reached git at all - and a
    negative is not readable from the answer, because the refusal has the same class either way.
    """

    def __init__(self, repository: Path) -> None:
        super().__init__(repository)
        self.asked: list[str] = []

    async def resolve(self, ref: str) -> str:
        """What `GitHistory` answers, with the question kept."""
        self.asked.append(ref)
        return await super().resolve(ref)

@pytest.mark.asyncio
async def test_a_base_ref_that_cannot_be_encoded_is_refused_before_git_is_asked_about_it(
    repository: Path, tmp_path: Path
) -> None:
    """`--from` is checked where the caller still knows what it handed over, not three layers down.

    **The ordering was the defect.** `RunSpec.__post_init__` checks `base_ref` for surrogates -
    `tests/ports/test_run.py` argues the whole of why - but `api.run` writes `base_sha=await
    services.history.resolve(ref)` as an *argument* to that constructor, and a constructor's
    arguments are all evaluated before its body runs. So the check sat behind the git call it was
    written to stand in front of, and the value reached `git rev-parse` first.

    **What arrived there was not one of AGL's errors.** `asyncio.create_subprocess_exec` runs
    `os.fsencode` over argv; a surrogate outside `\\udc80`-`\\udcff` has no encoding under
    `surrogateescape` either, so it raises `UnicodeEncodeError` - a `ValueError`, which
    `adapters/git/_runner.py::_spawned` did not catch, because it caught `OSError`. It escaped the
    adapter untranslated: a raw traceback, `cli/main.py`'s *this is our bug*, and exit 70 for a
    string somebody typed.

    That range is exactly what `tests/ports/test_run.py` reasoned about and stopped at. Its
    paragraph is right that `agl run --from` cannot produce one of these - `sys.argv` is decoded
    with `surrogateescape`, which mints only `\\udc80`-`\\udcff` - and right that "the subprocess
    never starts". What it does not say is what happens instead, and the reason the case is not
    hypothetical: `api.run` is a Python entry point with a `base_ref=` keyword, and `src/agl/
    testing.py` passes one straight through from a workflow author's own harness.

    **The negative is the assertion.** Both the fix and the defect answer `InputError` now - the
    adapter translates the encode failure, which is the guarantee half and
    `tests/adapters/test_git_runner.py` is where it is pinned - so the class alone distinguishes
    nothing. What distinguishes them is that git was never asked, and that the message names the
    field the caller supplied rather than the argv it became.
    """
    history = _RecordingHistory(repository)
    harness = _over(repository, tmp_path)
    harness = replace(harness, services=replace(harness.services, history=history))

    with pytest.raises(InputError) as refused:
        await _run(harness, base_ref=LONE_SURROGATE)

    assert history.asked == [], (
        f"the ref was handed to `History.resolve` before anything checked it: {history.asked!r}. "
        f"That call is `git rev-parse`, and this value has no encoding a process can be started "
        f"with - so the refusal came back from three layers down, about an argv, instead of from "
        f"the line that took it"
    )
    assert exit_code_for(refused.value) == 2, (
        "a `--from` that cannot be written down came back with an exit code other than 2. It is "
        "malformed input; 70 tells whoever hit it that AGL is broken when what is broken is the "
        "value they passed"
    )
    said = str(refused.value)
    assert "base_ref" in said and "U+D800" in said, (
        f"the refusal does not name the field or the character: {said!r}. This is the only place "
        f"in the path where both are still known - by the time it reaches the adapter the value is "
        f"one element of an argv, and the adapter cannot name it any more precisely than that"
    )
    assert await harness.services.store.read_record(SCOPE) is None, (
        "a run record was written for a run that was refused before it started"
    )

@pytest.mark.asyncio
async def test_the_same_ref_reaching_git_anyway_is_still_one_of_agls_own_errors(
    repository: Path, tmp_path: Path
) -> None:
    """The backstop under the check above, asserted through the port rather than around it.

    The caller-side check is about the *message*; this is about the guarantee. `History.resolve` is
    a port member anything may call, and the check in `api.run` guards the one call site in `src/`
    that does - a call site rather than the member, so a second caller would arrive at the adapter
    with no check in front of it at all. So the adapter translates the encode failure itself, and
    the value that used to escape as a `UnicodeEncodeError` comes back as an `InputError` like
    every other unusable input.

    Asserted here as well as in `tests/adapters/test_git_runner.py` because the two files are about
    different things: that one is about `_runner.py`'s mapping, and this is about the seam - the
    same string, through the same port `api.run` uses, arriving as an AGL error rather than a
    traceback.
    """
    with pytest.raises(InputError) as refused:
        await GitHistory(repository).resolve(LONE_SURROGATE)

    assert exit_code_for(refused.value) == 2
    assert "could not be started" in str(refused.value), (
        "the refusal does not say that nothing ran. A value git never received is not git refusing "
        "anything, and a message that reads as a refusal sends a person to the repository"
    )

# --- the rest of the surface ---------------------------------------------------------------------

def test_list_workflows_is_the_registrys_sorted_names() -> None:
    """`agl workflows`, complete: the command prints this and does nothing more.
    Sorted, so a listing is stable across environments rather than ordered by whatever sequence a
    metadata scan produced, and nothing is imported to answer it."""
    assert api.list_workflows(points=POINTS).names == ("halting", "probe")

def test_list_workflows_needs_no_bundle_and_no_registered_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`list_workflows` takes neither a bundle nor a project, and that is the whole assertion.

    Not a stronger version of the test above but a different claim, the composition's half of it:
    this reads the workspace, which is a fact about the operator's own home rather than about any
    repository, so it must answer from a directory that is not a git repository, has no project
    file naming it, and never built a port. A `Services` parameter it did not read would have made
    `agl workflows` refuse here with `NotFoundError` - a listing of what the operator has, withheld
    until they register a repository they were not asking about.
    """
    monkeypatch.chdir(tmp_path)

    assert api.list_workflows(points=POINTS).names == ("halting", "probe")

# --- the workspace, which answers whenever no entry points are handed over -----------------------

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _directory(home: AglHome, named: str, pyproject: str) -> None:
    """One directory under `workspace/workflows/`, holding the project file it is handed."""
    path = workflows_dir(home) / named
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(pyproject, encoding="utf-8")

def _declaring(named: str, attribute: str) -> str:
    """A project file declaring one workflow, pointed at this module so it resolves already."""
    return (
        f'[project]\nname = "{named}"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{registry.GROUP}"]\n{named} = "{__name__}:{attribute}"\n'
    )

def test_the_listing_reads_the_workspace_wherever_no_entry_points_were_handed_over(
    tmp_path: Path,
) -> None:
    """`points=` is the escape hatch and the home is the ordinary route, and this drives the latter.

    Both halves of `Listing` in one case, because they are one claim: a directory that declares
    nothing must not cost the operator the names of the directories that do.
    """
    home = _home(tmp_path)
    _directory(home, "triage", _declaring("triage", "probe"))
    _directory(home, "half-written", "[project\n")

    listing = api.list_workflows(home=home)

    assert listing.names == ("triage",)
    assert [entry.directory for entry in listing.broken] == ["half-written"]

@pytest.mark.asyncio
async def test_a_run_named_after_a_broken_directory_refuses_with_that_directorys_own_reason(
    tmp_path: Path,
) -> None:
    """Exit 2 and what is wrong with the directory, rather than exit 3 and "no workflow by that
    name": the operator typed the name of the thing they are writing, and `NotFoundError` would
    send them looking for a workflow to write instead of opening the file that will not parse."""
    home = _home(tmp_path)
    _directory(home, "half-written", "[project\n")
    harness = _fakes(tmp_path)

    with pytest.raises(InputError) as refused:
        await api.run(harness.services, PROJECT, "half-written", LABEL, (), home=home)

    assert exit_code_for(refused.value) == 2
    assert "half-written" in str(refused.value)

def test_a_declared_workflow_keeps_the_name_a_broken_directory_happens_to_share(
    tmp_path: Path,
) -> None:
    """A directory's name is not a workflow's name, so a shared one is not two answers to refuse
    between: the declaration wins, and the broken directory is still named in the listing.

    `_index`'s `ConflictError` is what two *declarations* of one name get. This is not that - the
    broken directory declares nothing at all, so there is no second workflow for the name to be
    ambiguous between, and refusing here would cost the operator a workflow that works.
    """
    home = _home(tmp_path)
    _directory(home, "elsewhere", _declaring("triage", "probe"))
    _directory(home, "triage", "[project\n")

    listing = api.list_workflows(home=home)

    assert listing.names == ("triage",)
    assert [entry.directory for entry in listing.broken] == ["triage"]
    assert "usage: agl run triage" in api.workflow_help("triage", home=home)

# --- the workspace's own pin, and which operations are entitled to refuse over it ----------------
#
# `config/toml_file.py`'s `check_workspace_pin` is the comparison and the suite over that module
# holds it; what is drawn here is the line between the operations that ask it and the operations
# that do not, which is a fact about this module and about nothing else.
#
# `run` and `resume` ask, because they are the two that read a workflow out of the workspace in
# order to spend agent turns on it, and a workflow written against another AGL's `agl.sdk` fails
# after the money has gone rather than before. Nothing else here asks. A listing and a help print
# what the operator already has and buy nothing, and they are the first two things somebody types
# when a command has just refused them - withholding those would leave a refusal with nothing to
# act on. `new_workflow` writes a scaffold this AGL rendered, so it is the one thing in an old
# workspace that cannot be stale, and it is the on-ramp: an operator upgrading AGL must be able to
# start writing. `clear` takes no home at all and so could not ask if it wanted to.
#
# Every arrangement below pins a version this tree is not, and each asserts the *class* rather than
# just that something raised: without the check the same call raises `NotFoundError` off an empty
# workspace, so the class is what says the refusal came first.

def _stale(home: AglHome) -> None:
    """A workspace root recording an AGL this one is not, which is the state the pin refuses on."""
    workflows_dir(home).mkdir(parents=True, exist_ok=True)
    workspace_pyproject(home).write_text(
        f'[tool.uv.workspace]\nmembers = ["workflows/*"]\n\n'
        f'[tool.agl]\nrequires = "{distribution.DISTRIBUTION}==0.0.0"\n',
        encoding="utf-8",
    )

@pytest.mark.asyncio
async def test_a_run_out_of_a_workspace_another_agl_made_refuses_before_it_reads_one(
    tmp_path: Path,
) -> None:
    """Exit 4, and it arrives before the workspace has been walked for the name that was typed.

    The workspace declares nothing, so an `api.run` that walked first would answer `NotFoundError`
    and send the operator looking for a workflow to write. The pin is a fact about the whole
    workspace and the walk is a question about one name in it, so the order is not a preference:
    the run is refused, and then it does not matter what the name resolved to.
    """
    home = _home(tmp_path)
    _stale(home)
    harness = _fakes(tmp_path)

    with pytest.raises(ConflictError) as refused:
        await api.run(harness.services, PROJECT, "probe", LABEL, (), home=home)

    assert exit_code_for(refused.value) == 4
    assert str(workspace_pyproject(home)) in str(refused.value)

@pytest.mark.asyncio
async def test_a_resume_out_of_that_same_workspace_refuses_on_the_pin_as_well(
    tmp_path: Path,
) -> None:
    """The second spender, and the one whose ledger makes the stakes concrete.

    A resume replays what is recorded and runs the rest, so a workspace whose workflow was written
    against another `agl.sdk` is a run that half-replays and then buys the remainder against code
    it was not recorded by. The run below is started through `points=`, which is the seam that
    reads no workspace, so what the resume meets is a workspace that went stale between the two.
    """
    home = _home(tmp_path)
    harness = _fakes(tmp_path)
    await _run(harness)
    _stale(home)

    with pytest.raises(ConflictError) as refused:
        await api.resume(harness.services, PROJECT, LABEL, home=home)

    assert exit_code_for(refused.value) == 4

def test_a_stale_pin_costs_the_operator_neither_the_listing_nor_the_help(tmp_path: Path) -> None:
    """Both readers answer over a workspace no run would touch, and that is deliberate.

    These are what somebody reaches for after a refusal - which workflows are in there, and what
    flags one takes - so refusing them too would take away the means of acting on the refusal
    while adding no protection: neither imports an agent, and neither spends.
    """
    home = _home(tmp_path)
    _stale(home)
    _directory(home, "triage", _declaring("triage", "probe"))

    listing = api.list_workflows(home=home)

    assert listing.names == ("triage",)
    assert "usage: agl run triage" in api.workflow_help("triage", home=home)

def test_a_stale_pin_leaves_the_on_ramp_open_for_the_scaffold_this_agl_writes(
    tmp_path: Path,
) -> None:
    """`agl new` is what an operator types straight after an upgrade, and it must still write.

    The scaffold is rendered by the AGL running now, against the `agl.sdk` that AGL ships, so it is
    the one thing in an old workspace that cannot be stale - and `api.new_workflow` calls
    `make_workspace` on every invocation, so a refusal here would fire on every `agl new` in a
    workspace made before the upgrade, which is exactly when there is work to be started.
    """
    home = _home(tmp_path)
    _stale(home)

    written = api.new_workflow(home, WorkflowName("release"))

    assert written.is_dir()
    assert api.list_workflows(home=home).names == ("release",)

def test_init_needs_neither_a_bundle_nor_a_registered_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-command composition for the operation it was written about, as a signature.

    `init` writes `AGL_HOME/projects/<name>.toml`, so the repository it is run in is by definition
    not registered yet and no container can be built for it. Composing before dispatching once made
    this call unreachable rather than merely unbuilt: the `NotFoundError` would have arrived before
    the operation did. So the settings come from `resolve_settings` with a literal mapping - the
    pure core, no process environment touched - and what is asserted is that a real `init` runs
    there and leaves a file, with no `Services` anywhere in the call.

    **The `cwd` is a parameter and this test is what that buys.** `monkeypatch.chdir` is
    deliberately not called: the directory below is handed over, so the process never moves, and
    `tests/test_init.py` drives every case the same way. An `init` reading `Path.cwd()` would have
    made this the file that had to move the process in order to test anything.
    """
    monkeypatch.delenv("AGL_HOME", raising=False)
    home = tmp_path / "home"
    repo = tmp_path / "dev" / "myapp"
    (repo / ".git").mkdir(parents=True)
    settings = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home)})

    written = api.init(settings, repo, lambda _: "make test")

    assert written == home / "projects" / "myapp.toml"
    assert written.read_text(encoding="utf-8").splitlines()[0] == 'name = "myapp"'

def test_every_operation_the_module_declares_is_built() -> None:
    """One list, and nothing on it refuses for being unfinished.

    `api.py`'s operations are named in its own bullet under `ARCHITECTURE.md`'s "The layers", and
    the CLI's dispatch has been written against the whole surface from the start, one clause at a
    time as each was built. `resume` left the unbuilt list first and `clear` next, each into a
    suite of its own - `tests/test_resume.py` and `tests/test_clear.py` - and `init` was the one
    left.

    `workflow_help` is on `__all__` beside the six verbs `agl` dispatches and is not one of them:
    it is the operation behind `agl workflows <name>`, which extends that grammar, and
    `cli/commands/workflows.py` is where the deviation is argued. `new_workflow` is a verb and is
    spelled unlike the command it serves, `agl new`, because `new` is an adjective and every other
    name here is what the operation does. `Ask`, `Cleared` and `Listing` are the three entries that
    are not operations at all - the callable `init` asks its one question through, and the two
    values `clear` and `list_workflows` answer with - and they are here because a caller annotating
    any of them has to be able to name it.
    """
    assert set(api.__all__) == {
        "Ask",
        "Cleared",
        "Listing",
        "clear",
        "init",
        "list_workflows",
        "new_workflow",
        "resume",
        "run",
        "workflow_help",
    }
    assert not [name for name in api.__all__ if "unbuilt" in name.lower()]
    assert not hasattr(api, "_unbuilt")
