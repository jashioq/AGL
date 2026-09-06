"""`agl resume <label>` from the library side: replay, driven through the real entry point.

`tests/sdk/test_kill_and_resume.py` is replay's own acceptance criterion and is not repeated here.
It kills a real process at every step boundary and resumes in a second one - which is the only way
to falsify half of the rules - but it constructs its ports and its `Journal` directly and never goes
through `api` at all. What this module owes is the other half of that sentence: that **`api.resume`
genuinely replays**, that the operation a person types is the one wired to the ledger, and that the
refusals asked of it are the ones it makes.

The headline property is therefore stated the way `ARCHITECTURE.md`'s "Invariants where a mistake
is silent" states it - "the worker was not called" is the whole of what a replay hit *is* - so
every test that cares counts **agent dispatches**, not entries. A run is interrupted between two
steps, resumed, and the first step's agent must have run exactly once across both invocations while
still handing back the value it produced the first time. An implementation that re-ran it would
pass every assertion about the final state and cost the operator an agent; one that skipped the
second step would pass every assertion about the first.

**Everything is `container.fakes()`** - no network, no git, no process - which is target #8 and what
lets a two-invocation replay cost milliseconds. Most of the workflows are declared in this module
and reached through hand-constructed `EntryPoint` values, exactly as `tests/test_api.py` does, and
that seam is how the params drift below is arranged: the class a record was written from and the
class a resume meets are two attributes of this module registered under one entry-point name.
Nothing is monkeypatched to produce it.

**What a resume compares is a directory and not an attribute**, so the tests that are about the
comparison itself are the ones that cannot use that seam - `points=` reaches no workspace and so
measures nothing - and they scaffold a real workflow directory under `tmp_path` instead. Their own
banner says what each of them buys.

**The comparison is asserted with the record afterwards.** Resume gets one line - digest the
directory, refuse on a difference, because runs live hours - and a refusal that had already touched
the run would be worse than none: the ledger it refused to finish against edited code is the thing
an operator is about to put the directory back for.

**What `api.run` and `api.resume` answer with is a count of what they replayed**, and its own
section asserts it against `dispatched` rather than against the ledger, for the reason above. Both
verbs answer, because the condition the CLI reports on is the number and never which verb was
typed; that a run's number is always nought is a consequence of `api.run` refusing a label that has
a record, and is asserted here as a claim about the count rather than left implied.
"""

import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import timedelta
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.adapters.claude_code.fake import Conversation, Script
from agl.config import container, registry
from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    Claude,
    ModelId,
    Restriction,
    StopReason,
)
from agl.ports.errors import (
    ConflictError,
    InputError,
    InternalError,
    NotFoundError,
    UpstreamUnavailable,
    exit_code_for,
)
from agl.ports.home_layout import AglHome, RunScope, workflows_dir
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.tree_layout import TreesRoot, base_worktree, run_branch
from agl.ports.workspace import Workspace, WorkspaceProvider
from agl.sdk.params import arg
from agl.sdk.roles import Role, role
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run, Stop, workflow

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# The file every repository below is seeded with, and the one a commit landing between the run and
# the resume adds - a commit landing on `main` between run and resume.
SEEDED: Final = "src/a.txt"
LANDED: Final = "src/landed.txt"

@dataclass(frozen=True)
class ResumeParams:
    """The example params shape. `concurrent` is a default the user never typed, the half of
    "params come from `run.json`" that is lost if the record is not the whole story."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)

@dataclass(frozen=True)
class OtherParams:
    """`ResumeParams`' fields under other names: what a workflow that changed its params looks
    like from the record's side, once the digest comparison has let it past."""

    ask: str = arg("-a", "--ask", help="what to build, spelled another way")

@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""

@dataclass(frozen=True)
class Summary:
    """A reporting payload: one string, which is the whole of what these agents have to say."""

    text: str

REPORT: Final = reporting_tool("report", "report what this step produced", Summary)

# Two roles, differing in name and prompt, so the two steps below are two addresses and two
# fingerprints. Read-only and paired with steps that pass no `commit=`, which is what an author is
# asked to write.
#
# Two factories rather than one `replace` of the other, which is what a later change took away: a
# factory closes the override surface, and a role that could be re-spelled at a call site is a role
# whose fingerprint terms a call site can move. The duplication is four literals and it is the
# honest version of a distinction that is only ever declared once.

@role(model=Claude.SONNET)
def first() -> Role[Summary]:
    """The first of two steps, and the address `steps/first/`."""
    return Role(
        name="first",
        instructions="do the first thing",
        restrictions={Restriction.NO_VCS_WRITES},
        tools=(REPORT,),
    )

@role(model=Claude.SONNET)
def second() -> Role[Summary]:
    """The second, differing in the two terms that make it a second address and a second digest."""
    return Role(
        name="second",
        instructions="do the second thing",
        restrictions={Restriction.NO_VCS_WRITES},
        tools=(REPORT,),
    )

class Interrupted(Exception):
    """What a run dying between two steps looks like from here.

    A plain exception rather than a `Stop`: a deliberate end and a crash leave the same ledger, and
    this module wants the one that is unambiguously not a decision. `api.run` catches nothing, so
    it arrives at the test as itself.
    """

class ReviewNotConverging(Stop):
    """A workflow's own reason to stop, spelled against the SDK's `Stop`."""

# What each workflow was handed, what its steps gave back, and the interruption a test arms. Module
# level because the workflows have to be: `EntryPoint.load` imports a module and reads an attribute
# in it, and sees no local of a test function.
handed: Final[list[Run[object]]] = []
produced: Final[list[Summary]] = []
interrupt: Final[list[str]] = []
raised: Final[list[Stop]] = []

@workflow
async def two_steps(run: Run[ResumeParams]) -> None:
    """Two steps, with a place between them for the process to die.

    `interrupt` is armed by the test before the first invocation and cleared before the resume,
    which is this module's stand-in for `tests/instruments/replay.py`'s `os._exit`: what is under
    test here is the wiring from `api.resume` to the journal, and that a workflow raised where a
    kernel would have killed it changes nothing about the ledger it left behind.
    """
    handed.append(run)
    produced.append(await run.step(first()))
    if interrupt:
        raise Interrupted(interrupt[0])
    produced.append(await run.step(second()))

@workflow
async def branching(run: Run[ResumeParams]) -> None:
    """One step here and one in a child worktree, so a replay of it spans two namespaces.

    A namespace has a journal and a chain of its own, and the count a resume reports is the walk's
    rather than one journal's - which is only visible where there is more than one journal to be
    wrong about.
    """
    handed.append(run)
    produced.append(await run.step(first()))
    produced.append(await run.worktree("side").step(second()))

@workflow
async def quiet(run: Run[NoParams]) -> None:
    """Takes no step at all - the run for which "`agl/<label>` is a real ref from run start" is
    only true if something above the first step provisioned `_base`."""
    handed.append(run)

@workflow
async def halting(run: Run[NoParams]) -> None:
    """Ends deliberately, with a reason of its own - which the framework must not rename."""
    handed.append(run)
    stop = ReviewNotConverging("two rounds and no convergence")
    raised.append(stop)
    raise stop

@workflow
async def drifting_before(run: Run[ResumeParams]) -> None:
    """The params class the record is written from. Registered under `drifting`."""
    handed.append(run)

@workflow
async def drifting_after(run: Run[OtherParams]) -> None:
    """The same declared name with its params renamed underneath - the one way a record reaches
    `params.from_json` disagreeing with the class, once no directory is measured to catch it."""
    handed.append(run)

def _point(name: str, attribute: str) -> EntryPoint:
    """A `probe = "agl.workflows.probe:probe"` line, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)

POINTS: Final = (
    _point("two_steps", "two_steps"),
    _point("branching", "branching"),
    _point("quiet", "quiet"),
    _point("halting", "halting"),
)

# The params drift, as two states of one workspace. Kept out of `POINTS` so that a test resuming
# under `AFTER` is resuming against a workspace holding one `drifting`, which is what editing that
# directory leaves behind.
BEFORE: Final = (*POINTS, _point("drifting", "drifting_before"))
AFTER: Final = (*POINTS, _point("drifting", "drifting_after"))

def _reporting(dispatched: list[str]) -> Script:
    """An agent that writes nothing, reports one payload, and records that it was paid for.

    `dispatched` is the whole instrument of this module: a replay has no observable difference
    from a re-run that happens to produce the same answer, other than that the worker was not
    called. `task.instructions` names which role was served, because the two roles differ only
    there.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        dispatched.append(conversation.task.instructions)
        await conversation.call(REPORT.name, {"text": f"{conversation.task.instructions} done"})
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script

def _fakes(tmp_path: Path, dispatched: list[str]) -> container.FakeServices:
    """Target #8's deployment: one repository seeded with a file, one store, one frozen clock."""
    return container.fakes(
        TreesRoot(tmp_path / "trees"), files={SEEDED: b"one\n"}, claude=_reporting(dispatched)
    )

async def _record(harness: container.FakeServices) -> dict[str, JsonValue]:
    """The run's record, asserted present - every caller below is testing what is in it."""
    record = await harness.services.store.read_record(SCOPE)
    assert record is not None, "no run.json was written for this run"
    return record

async def _start(
    harness: container.FakeServices,
    name: str = "two_steps",
    argv: Sequence[str] = ("-r", "add oauth"),
    *,
    points: Sequence[EntryPoint] = POINTS,
) -> api.Replayed:
    """The first invocation: `agl run <name> -n auth`, with this module's entry points."""
    return await api.run(harness.services, PROJECT, name, LABEL, argv, points=points)

async def _resume(
    harness: container.FakeServices,
    *,
    label: RunLabel = LABEL,
    points: Sequence[EntryPoint] = POINTS,
) -> api.Replayed:
    """The second invocation: `agl resume auth`, and the label is the whole of what it takes."""
    return await api.resume(harness.services, PROJECT, label, points=points)

def _clear() -> None:
    """Every module-level recorder, between invocations. Called by hand rather than through a
    fixture so that a test can clear one of them mid-scenario and keep the rest."""
    handed.clear()
    produced.clear()
    interrupt.clear()
    raised.clear()

# --- the headline property: a resumed run replays what is on the ledger --------------------------

@pytest.mark.asyncio
async def test_a_resumed_run_replays_the_completed_step_and_runs_only_the_rest(
    tmp_path: Path,
) -> None:
    """Replay, through the command rather than through a hand-built `Run`.

    The workflow function is re-run from the top - `handed` gets a second `Run` - the step that
    already has an entry is a no-op returning its stored value, and only the step that never ran
    reaches an agent. Three assertions, because each of the other two is satisfied by a build that
    gets the third wrong: an `api.resume` that started the workflow at the second step would leave
    `dispatched` right and never prove the walk; one that re-ran `first` would leave `produced`
    right and cost the operator an agent; one that replayed both would leave `handed` right and
    finish nothing.

    The counter is rebuilt from nothing on the way, which is what makes the first step *hit* at
    all: the ordinal `n` is never persisted, so the resume's fresh `Fingerprints` walks the same
    calls in the same order and arrive at the same digest.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    interrupt.append("killed between the two steps")

    with pytest.raises(Interrupted):
        await _start(harness)

    assert dispatched == ["do the first thing"]
    assert produced == [Summary("do the first thing done")]

    _clear()
    await _resume(harness)

    assert len(handed) == 1, "the resumed workflow function was not re-run from the top"
    assert dispatched == ["do the first thing", "do the second thing"], (
        "across both invocations each step's agent must have run exactly once. A repeat is a step "
        "that re-ran because the resume computed a different digest for it, and it is paid for in "
        "tokens and raises nothing"
    )
    assert produced == [
        Summary("do the first thing done"),
        Summary("do the second thing done"),
    ], "the replayed step did not hand back the value its entry recorded"

@pytest.mark.asyncio
async def test_resuming_a_finished_run_runs_no_worker_at_all(tmp_path: Path) -> None:
    """The other end of the sweep: everything is on the ledger, so nothing is asked of an agent.

    This is the case that separates "replays" from "happens to produce the same answer" - both
    steps hit, both hand back what they recorded, and `dispatched` does not move.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()

    await _start(harness)
    assert dispatched == ["do the first thing", "do the second thing"]

    _clear()
    await _resume(harness)

    assert dispatched == ["do the first thing", "do the second thing"], (
        "a resume of a run with nothing left to do paid an agent anyway"
    )
    assert produced == [
        Summary("do the first thing done"),
        Summary("do the second thing done"),
    ]

@pytest.mark.asyncio
async def test_the_workflow_is_handed_its_params_as_the_dataclass_the_record_stored(
    tmp_path: Path,
) -> None:
    """Params are persisted into `run.json`, which is why `agl resume auth` takes no flags.

    `concurrent` is asserted at 4 - a value the resume's own command line could not have carried,
    since there is no command line - and `request` at what was typed hours earlier. The type is
    asserted too: `run.params` is an instance of the workflow's class and not the mapping the store
    handed over, which is the difference between the typing promise holding on a resume and holding
    only on a fresh run.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()

    await _start(harness, argv=("-r", "add oauth", "-c", "4"))
    _clear()
    await _resume(harness)

    assert isinstance(handed[0].params, ResumeParams)
    assert handed[0].params == ResumeParams(request="add oauth", concurrent=4)
    assert type(handed[0].params.concurrent) is int

# --- what the walk replayed, counted --------------------------------------------------------------
#
# `Replayed.steps` is one per `run.step` invocation served off the ledger and is what
# `cli/commands/__init__.py` turns into `replayed <n> steps from cache`. It is asserted here against
# `dispatched`, which is the same instrument the section above uses: a step that was replayed did
# not reach an agent, so the two numbers have to add up to the calls the workflow made. Counting
# entries instead would say nothing, since a resume reads entries a divergent fingerprint never
# hits.

@pytest.mark.asyncio
async def test_a_resume_counts_the_step_it_replayed_and_the_run_before_it_counted_none(
    tmp_path: Path,
) -> None:
    """The number and its complement, in one scenario: one step off the ledger and one paid for.

    The run that wrote the ledger reports nought, and not because it is `run`: it walked a ledger
    that was empty when it started, having written its own record a line earlier. `api.run` refuses
    a label that already has one, so nought is the only count a run can reach - which is what makes
    the CLI's silence at nought a fact about the count rather than about the verb.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    interrupt.append("killed between the two steps")

    with pytest.raises(Interrupted):
        await _start(harness)

    _clear()
    replayed = await _resume(harness)

    assert replayed == api.Replayed(steps=1)
    assert dispatched == ["do the first thing", "do the second thing"], (
        "one step was replayed and one was paid for, so exactly one agent ran in each invocation"
    )

@pytest.mark.asyncio
async def test_a_run_that_took_two_steps_of_its_own_replayed_neither_of_them(
    tmp_path: Path,
) -> None:
    """The run's own count, on its own, so the assertion above is not carrying two claims.

    Nought over a run that genuinely stepped twice - it wrote both entries and read neither -
    rather than over a workflow that never touched a journal at all.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()

    replayed = await _start(harness)

    assert replayed == api.Replayed(steps=0)
    assert dispatched == ["do the first thing", "do the second thing"]

@pytest.mark.asyncio
async def test_resuming_a_finished_run_counts_every_step_the_ledger_already_held(
    tmp_path: Path,
) -> None:
    """The far end of the sweep, where the count is the whole workflow and no agent is paid.

    Worth its own line beside the one above because a count taken at the first miss would be right
    there and silent here: this run never misses, so there is no moment inside the walk at which
    "replay is over" happens. It is why the number is read after the walk and not during it.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()

    await _start(harness)
    _clear()
    replayed = await _resume(harness)

    assert replayed == api.Replayed(steps=2)
    assert dispatched == ["do the first thing", "do the second thing"], (
        "a resume with nothing left to do paid an agent anyway"
    )

@pytest.mark.asyncio
async def test_the_count_spans_namespaces_and_holds_a_child_worktrees_replayed_steps(
    tmp_path: Path,
) -> None:
    """One number for the run tree, not one per journal.

    `branching` steps once in its own namespace and once in a child's, and each namespace opens a
    `Journal` of its own. What they share is the `Fingerprints` `api._walk` builds and `Run._child`
    hands down, which is why the tally lives there: a counter on `Journal` would report the root's
    step and lose the child's.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()

    await _start(harness, name="branching")
    assert await harness.services.store.namespaces(SCOPE) == (Namespace("side"),), (
        "the child never got a namespace of its own, so this run has one journal and the count "
        "below would be right for the wrong reason"
    )

    _clear()
    replayed = await _resume(harness)

    assert replayed == api.Replayed(steps=2)
    assert dispatched == ["do the first thing", "do the second thing"]

# --- the record is read and never written --------------------------------------------------------

class _Counting(Store):
    """The bundle's own store with a note taken of every write it is asked for, and nothing changed.

    `_Watching` below is the same instrument one port over, and `src/agl/testing.py::_Ledger` is the
    precedent for the shape: a decorator whose every member delegates, so the store underneath is
    still the bundle's `MemoryStore` and `tests/contracts/store.py` remains the only thing that says
    how a `Store` behaves. This one has no behaviour of its own to be wrong about either.

    `wrote` counts the *scopes* rather than the calls, because the one thing a reader wants from a
    failure is which run was written to. `entries` is the same note one member over, and the two
    live on one instrument because `Store` has exactly two writing members - so "nothing was
    written", which the refusal test at the foot of this module asserts of a resume, is a claim
    about both, and a decorator watching one of them would leave half that sentence resting on
    nothing. Installed with `FakeServices.with_store`, which is what keeps `harness.store` and
    `harness.services.store` the same object - a `replace` around the bundle would leave the test
    reading a different ledger from the one the run used.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self.wrote: list[RunScope] = []
        self.entries: list[str] = []

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        return await self._store.read_record(scope)

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        self.wrote.append(scope)
        await self._store.write_record(scope, value)

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        return await self._store.read_entry(scope, step, digest)

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        self.entries.append(str(step))
        await self._store.write_entry(scope, step, digest, value)

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        return await self._store.namespaces(scope)

    async def remove(self, scope: RunScope) -> None:
        await self._store.remove(scope)

@pytest.mark.asyncio
async def test_a_resume_does_not_rewrite_run_json(tmp_path: Path) -> None:
    """The pin, from the side only a resume can show it from - and `api.resume`'s bold claim.

    Both hands that could move the record are moved between the two invocations: the clock, so a
    `created_at` rewritten with "now" would differ, and the repository's default branch, so a
    `base_sha` re-resolved from `base_ref` would name the commit that landed rather than the one
    the run was cut from.

    **The count is what measures the claim, and the equality below it does not.** `api.resume` says
    "The record is read and never rewritten", and comparing the contents afterwards is strictly
    weaker than that: `RunSpec.from_json(record).to_json()` is a fixpoint over the wire shape, so a
    resume that read the record and wrote the very same mapping back would leave every field equal
    and every assertion about them green. That write is not nothing. It is a port call, and on a
    `FilesystemStore` it rewrites the file, moves its mtime, and turns a crash mid-resume into a
    truncated record that was never meant to move - which is `ports/store.py`'s "the one value in
    AGL that has no other copy anywhere".

    **The run's own write is what makes the count non-vacuous.** One `write_record` before the
    interruption and not one more afterwards, so a counter that never counted anything would fail
    the first assertion rather than pass the second. The equality is kept beside it because it says
    which *fields* a rewrite would have moved, and the clock and the landed commit are arranged for
    exactly that.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    counting = _Counting(harness.store)
    harness = harness.with_store(counting)
    _clear()
    await _start(harness)
    before = await _record(harness)
    pinned = before["base_sha"]
    assert isinstance(pinned, str)
    assert counting.wrote == [SCOPE], "the run itself did not write the record this counts"

    harness.clock.advance(timedelta(hours=3))
    landed = harness.repository.record(
        {SEEDED: b"one\n", LANDED: b"landed while nobody was looking\n"},
        (pinned,),
        "a commit landing between the run and the resume",
    )
    harness.repository.move("main", landed)

    _clear()
    await _resume(harness)

    assert counting.wrote == [SCOPE], (
        "a resume called `Store.write_record`. `api.resume` promises the record is read and never "
        "rewritten, and the contents being unchanged is not that promise: the wire shape is a "
        "fixpoint, so a resume rewriting what it read is invisible in the record and visible only "
        "here - as a moved mtime on a real store, and as a truncated `run.json` if it dies partway"
    )
    assert await _record(harness) == before, (
        "a resume rewrote the record. `base_sha` pins the resolved commit so that a commit landing "
        "on `main` between run and resume cannot move the first step's starting head - a "
        "resume that re-resolved and stored the answer performs the failure the field prevents"
    )
    assert handed[0].base == pinned, "the resumed run started from somewhere other than the pin"

class _Watching(WorkspaceProvider):
    """The bundle's own provider with a note taken of every `open`.

    Substituted with `dataclasses.replace`, which is what `tests/test_api.py` does for its refusing
    provider: the port-typed field is the seam, and `container.fakes()` has no `workspaces=`
    parameter to reach for instead. It delegates rather than pretends - what is being asked is
    which arguments `api.resume` passed, and everything else has to go on working.
    """

    def __init__(self, provider: WorkspaceProvider) -> None:
        self._provider = provider
        self.opened: list[tuple[RunLabel, Namespace | None, str]] = []

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        self.opened.append((label, namespace, base))
        return await self._provider.open(label, namespace, base)

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        await self._provider.remove(label, namespace)

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        await self._provider.discard(label, namespace)

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        return self._provider.hold(label)

@pytest.mark.asyncio
async def test_a_resume_reopens_base_from_the_pin_even_when_the_workflow_takes_no_step(
    tmp_path: Path,
) -> None:
    """The decision `api.resume` makes about `workspaces.open`, and both halves of why.

    `agl/<label>` is promised to be a real ref a person can `git log` from run start, and
    `run.step`'s open is lazy - so a resumed run whose workflow takes no step provisions nothing
    unless the operation does. That is `api.run`'s own argument, and the state a resume exists to
    recover from makes it sharper: a crash between the record and the checkout leaves a run whose
    `_base` was never cut at all.

    The base it is opened from is the assertion with teeth. A commit lands on `main` between the two
    invocations, and `open` accepts a ref expression as happily as a commit id - so handing it
    `base_ref` would work every day except the one somebody pushes on, and then the checkout would
    start at a commit the record never pinned.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    watching = _Watching(harness.services.workspaces)
    services = replace(harness.services, workspaces=watching)
    _clear()

    await api.run(services, PROJECT, "quiet", LABEL, (), points=POINTS)
    pinned = (await _record(harness))["base_sha"]
    assert isinstance(pinned, str)
    landed = harness.repository.record(
        {SEEDED: b"one\n", LANDED: b"landed\n"}, (pinned,), "a commit landing in between"
    )
    harness.repository.move("main", landed)
    watching.opened.clear()

    await api.resume(services, PROJECT, LABEL, points=POINTS)

    assert watching.opened == [(LABEL, None, pinned)], (
        "a resumed run either provisioned nothing or provisioned it from something other than the "
        "commit its record pins"
    )
    assert base_worktree(TreesRoot(tmp_path / "trees"), LABEL).is_dir()
    assert harness.repository.tip(run_branch(LABEL)) == pinned

# --- the refusals ---------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_label_with_no_record_is_a_not_found_and_reads_as_runs_mirror(
    tmp_path: Path,
) -> None:
    """`resume` on a missing label errors symmetrically. Keeping both verbs makes a typo'd label
    a loud error rather than a silent replay of something unrelated.

    Both messages are asserted here, in one test, because the claim is about the pair: `run` says
    the label is taken and names the verbs that free it, `resume` says it is free and names the verb
    that takes it. A change to either wording that stopped them reading as one vocabulary fails
    here rather than being noticed by an operator holding two terminals.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()

    with pytest.raises(NotFoundError) as caught:
        await _resume(harness)

    assert str(caught.value) == (
        "run 'auth' does not exist - `agl run <workflow> -n auth` starts one."
    )
    assert exit_code_for(caught.value) == 3
    assert handed == [], "a resume of a run that does not exist invoked a workflow anyway"

    await _start(harness)
    with pytest.raises(ConflictError) as taken:
        await _start(harness)
    assert str(taken.value) == "run 'auth' already exists - `agl resume auth` or `agl clear auth`."

@pytest.mark.asyncio
async def test_params_the_workflows_current_class_will_not_take_are_refused(
    tmp_path: Path,
) -> None:
    """`sdk/params.py`'s refusal, reached the only way this module's seam can reach it.

    The workflow changes its params class where the digest comparison cannot see it - these
    workflows are attributes of this file, reached through `points=`, so no directory is measured
    and the comparison passes over a pair of empty maps. That is the shape that module's refusal
    names, and it is why the refusal is still there behind the comparison. `InputError` - exit 2 -
    because the reader is the workflow's author and the fix is a line in their package, where exit
    70 would send them to file a bug against AGL. The message names the keys, because "the params
    do not match" leaves them to work out which field moved.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    await _start(harness, "drifting", ("-r", "add oauth"), points=BEFORE)

    with pytest.raises(InputError) as caught:
        await _resume(harness, points=AFTER)

    assert exit_code_for(caught.value) == 2
    message = str(caught.value)
    assert "'request'" in message and "'concurrent'" in message and "ask" in message
    assert len(handed) == 1, "a workflow was handed params its own class does not declare"

@pytest.mark.asyncio
async def test_a_workflow_the_record_names_and_nothing_registers_is_a_not_found(
    tmp_path: Path,
) -> None:
    """`RunSpec.workflow` is the entry-point key, so a resume that cannot find it is the registry's
    `NotFoundError` - exit 3 - and not this module inventing a second way to say the same thing."""
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    await _start(harness, "quiet", ())

    with pytest.raises(NotFoundError) as caught:
        await _resume(harness, points=(_point("two_steps", "two_steps"),))

    assert exit_code_for(caught.value) == 3
    assert "quiet" in str(caught.value)

# --- the workflow's own directory, which is what a resume actually compares ----------------------
#
# Every test under this banner drives `api` with `home=` rather than `points=`, because the thing
# under test is the walk: `config/registry.py` reads a declaration out of a directory and hands the
# directory along with it, and `api` digests that directory rather than reading an attribute off
# the imported object. The entry point in each scaffolded pyproject.toml names an attribute of
# *this* module, so what is imported is a file pytest has already loaded and the directory holds
# code nothing runs - which is the point rather than a shortcut, the map being about the directory
# and not about what an import happened to reach. A prompt is the sharpest case of that: no import
# reads one, and no attribute of the loaded object could answer for one.
#
# `test_a_resume_of_an_untouched_directory_replays_although_the_run_imported_it_first` is the one
# that does not take that shortcut, for the reason its own docstring gives.

_ROLES_DOCUMENT: Final = 'NOTE = "a module beside the workflow, which the digest map covers"\n'

_PROMPT_DOCUMENT: Final = "# review\n\nread what changed and say what is wrong with it\n"

# The importable workflow the ordering test below scaffolds and runs, so it becomes a top-level
# module in this interpreter for the length of one test - distinctive for that reason.
IMPORTED: Final = "resumed_workflow"

_IMPORTED_DOCUMENT: Final = f"""from agl.sdk import Run, workflow
from .roles import NOTE

@workflow
async def {IMPORTED}(run: Run) -> None:
    assert NOTE
"""

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _declaring(named: str, value: str) -> str:
    """The project file a workflow directory declares itself in, naming the object AGL runs."""
    return (
        f'[project]\nname = "{named}"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{registry.GROUP}"]\n{named} = "{value}"\n'
    )

def _directory(home: AglHome, named: str = "triage", attribute: str = "quiet") -> Path:
    """One workflow directory under the workspace: a declaration, a module and a prompt."""
    path = workflows_dir(home) / named
    (path / "prompts").mkdir(parents=True)
    (path / "pyproject.toml").write_text(
        _declaring(named, f"{__name__}:{attribute}"), encoding="utf-8"
    )
    (path / "roles.py").write_text(_ROLES_DOCUMENT, encoding="utf-8")
    (path / "prompts" / "review.md").write_text(_PROMPT_DOCUMENT, encoding="utf-8")
    return path

@pytest.fixture
def _forgotten_afterwards() -> Iterator[None]:
    """The imported workflow, out of `sys.modules` again once the test that imported it is done.

    `tests/conftest.py` restores `sys.path` and not `sys.modules`, and the directory this name was
    imported from is deleted with `tmp_path` - so a later test scaffolding it would silently run
    this one's code out of a directory that is gone.
    """
    yield
    for held in [
        name for name in sys.modules if name == IMPORTED or name.startswith(f"{IMPORTED}.")
    ]:
        del sys.modules[held]

@pytest.mark.asyncio
async def test_a_file_edited_in_the_workflow_directory_refuses_the_resume_and_is_named(
    tmp_path: Path,
) -> None:
    """The refusal `api.resume` makes, and the whole of what makes it worth more than a count.

    `ConflictError` - exit 4, the same code `run` answers a taken label with - because the record
    exists and the workflow exists and neither is wrong: they do not fit, which is
    `ports/errors.py`'s "the world already holds something this operation would have to take or
    overwrite". `NotFoundError` would be wrong twice over, both things having been found.

    **The file is named and no other file is.** A refusal saying only "the workflow changed" ends
    a run somebody was in the middle of and leaves them to work out what they touched; naming the
    file is the whole of the difference. The prompt is what is edited here, because it is the file
    furthest from anything the imported object could have been asked about.

    The record is asserted untouched afterwards, since the ledger this refused to finish is what
    the restored directory is about to finish, and the workflow is asserted not to have run again.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    home = _home(tmp_path)
    directory = _directory(home)
    _clear()
    await api.run(harness.services, PROJECT, "triage", LABEL, (), home=home)
    before = await _record(harness)

    (directory / "prompts" / "review.md").write_text("# review\n\nsay it differently\n", "utf-8")
    with pytest.raises(ConflictError) as caught:
        await api.resume(harness.services, PROJECT, LABEL, home=home)

    assert exit_code_for(caught.value) == 4
    message = str(caught.value)
    assert "changed prompts/review.md" in message
    assert "roles.py" not in message, "a file nobody touched was named as though it had moved"
    assert "put the directory back" in message
    assert "agl clear auth" in message
    assert await _record(harness) == before, "a refused resume changed the run it refused"
    assert len(handed) == 1, "the workflow ran against files the ledger was not written by"

@pytest.mark.asyncio
async def test_a_file_added_beside_the_workflow_and_one_taken_away_are_told_apart(
    tmp_path: Path,
) -> None:
    """The other two of the three differences a map comparison can see, kept distinct in the words.

    They are three because they send an operator to three places. A file that is gone is the one
    that cannot be restored by editing anything - it has to come back - and reporting it as
    "changed" would send somebody looking through a diff of a file that is not there.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    home = _home(tmp_path)
    directory = _directory(home)
    _clear()
    await api.run(harness.services, PROJECT, "triage", LABEL, (), home=home)

    (directory / "prompts" / "plan.md").write_text("# plan\n", encoding="utf-8")
    (directory / "roles.py").unlink()
    with pytest.raises(ConflictError) as caught:
        await api.resume(harness.services, PROJECT, LABEL, home=home)

    message = str(caught.value)
    assert "added prompts/plan.md" in message
    assert "removed roles.py" in message
    assert "changed" not in message, "nothing was edited, and two files were reported as though"

@pytest.mark.asyncio
async def test_a_directory_rewritten_wholesale_names_five_files_and_counts_the_rest(
    tmp_path: Path,
) -> None:
    """The bound, which exists because an unbounded list in a terminal is its own kind of failure.

    Fifteen files are added at once and five of them are named. The count is what keeps the message
    honest about being an excerpt - a truncated list with nothing saying so reads as the whole
    answer - and the names are sorted, so which five they are is a fact about the directory rather
    than about the order a filesystem listed it in.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    home = _home(tmp_path)
    directory = _directory(home)
    _clear()
    await api.run(harness.services, PROJECT, "triage", LABEL, (), home=home)

    for index in range(15):
        (directory / f"step{index:02d}.py").write_text(f"STEP = {index}\n", encoding="utf-8")
    with pytest.raises(ConflictError) as caught:
        await api.resume(harness.services, PROJECT, LABEL, home=home)

    message = str(caught.value)
    assert "added step00.py, step01.py, step02.py, step03.py, step04.py and 10 more" in message
    assert "step05.py" not in message, "the sixth file of fifteen was named, so nothing is bounded"

@pytest.mark.asyncio
@pytest.mark.usefixtures("_forgotten_afterwards")
async def test_a_resume_of_an_untouched_directory_replays_although_the_run_imported_it_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering hazard the digest map was built against, measured rather than reasoned about.

    `api.resume` loads the workflow before it digests the directory, and loading it is an *import*
    - which makes CPython write bytecode into the very directory about to be hashed.
    `config/workflow_files.py` leaves `__pycache__` out for that reason, and this is where the
    exclusion meets the ordering it exists for: a resume that hashed what its own import had just
    written would refuse every run, always, and the message would name files nobody wrote.

    So this is the one test under this banner that scaffolds a workflow the workspace really
    imports, rather than pointing a declaration back at this module. The assertion that the
    directory holds bytecode afterwards is what says the hazard was actually present - with
    `sys.dont_write_bytecode` set on the machine this runs on, nothing would be written and a green
    line here would have measured nothing.
    """
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(sys, "pycache_prefix", None)
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    home = _home(tmp_path)
    directory = workflows_dir(home) / IMPORTED
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_text(
        _declaring(IMPORTED, f"{IMPORTED}:{IMPORTED}"), encoding="utf-8"
    )
    (directory / "__init__.py").write_text(_IMPORTED_DOCUMENT, encoding="utf-8")
    (directory / "roles.py").write_text(_ROLES_DOCUMENT, encoding="utf-8")
    _clear()

    await api.run(harness.services, PROJECT, IMPORTED, LABEL, (), home=home)
    await api.resume(harness.services, PROJECT, LABEL, home=home)

    assert (directory / "__pycache__").is_dir(), (
        f"no bytecode was written under {directory}, so this test measured nothing: the import "
        f"the ordering is a hazard for either did not happen or wrote nothing"
    )
    stamped = (await _record(harness))["workflow_digests"]
    assert isinstance(stamped, dict)
    assert tuple(stamped) == ("__init__.py", "pyproject.toml", "roles.py"), (
        "the record's map is not the directory's three files, so the resume above passed over a "
        "comparison of two maps that were measured from something other than what was written"
    )

@pytest.mark.asyncio
async def test_a_record_predating_digests_is_refused_and_agl_clear_still_takes_the_run_away(
    tmp_path: Path,
) -> None:
    """What a run started before AGL digested anything meets, and the decision behind it.

    Those records carry a declared `workflow_version` and no `workflow_digests`, so `WireShape`
    refuses them by both halves at once: the key AGL needs is missing and the key it used to write
    is unexpected. `InternalError` - exit 70 - is not the shape "your run predates this AGL"
    deserves, and it is kept anyway. `ports/run.py` refuses records rather than migrating them, so
    a clause there that knew the name of a key AGL no longer writes would be a migration path in
    the one module whose whole rule is that it has none, and it would outlive by years the handful
    of records it was written for.

    What makes that affordable is the second half, and it is asserted rather than argued: `clear`
    reads the record only to find out whether one is there and never parses it, so the way out of
    the refusal is the command the refusals beside it already name. The alternative to refusing at
    all - reading an absent map as an empty one - is the one answer that must not happen, an empty
    map being exactly what a caller handing its own entry points over records.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    await _start(harness, "quiet", ())
    current = await _record(harness)
    stale: dict[str, JsonValue] = {
        key: value for key, value in current.items() if key != "workflow_digests"
    }
    await harness.services.store.write_record(SCOPE, {**stale, "workflow_version": "1.0"})

    with pytest.raises(InternalError) as caught:
        await _resume(harness)

    assert exit_code_for(caught.value) == 70
    assert "workflow_digests" in str(caught.value)
    assert "workflow_version" in str(caught.value)

    cleared = await api.clear(harness.services, PROJECT, LABEL)

    assert cleared.branches == (run_branch(LABEL),)
    assert await harness.services.store.read_record(SCOPE) is None

# --- the ordering hazard, on the resumed side ----------------------------------------------------

@pytest.mark.asyncio
async def test_a_stop_raised_by_a_resumed_workflow_leaves_api_resume_unwrapped(
    tmp_path: Path,
) -> None:
    """The criterion, asserted of `resume` as `tests/test_api.py` asserts it of `run`.

    Identity and not `isinstance`: a resume that caught the workflow's `ReviewNotConverging`, threw
    it away and raised a fresh one of the same class would still exit 7 and would name this module
    in the traceback instead of the step that stopped. `api.py` has no `except` of any width, and
    the `async with` around the workflow cannot become one - `Terminal.__aexit__` is `-> None` on
    the port and a context manager suppresses only by returning something truthy.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    with pytest.raises(ReviewNotConverging):
        await _start(harness, "halting", ())

    _clear()
    with pytest.raises(ReviewNotConverging) as caught:
        await _resume(harness)

    assert caught.value is raised[0]
    assert exit_code_for(caught.value) == 7
    assert (await _record(harness))["workflow"] == "halting"

# --- the ordering of the refusals in front of preflight -------------------------------------------

class _NotReady(AgentRunner):
    """An `AgentRunner` whose `check_ready` refuses, and which writes down that it was asked.

    Declared here rather than in `src/` for `tests/sdk/test_preflight.py::_Stub`'s reason: a backend
    that is not ready is the one thing `container.fakes()` deliberately cannot arrange, there being
    nothing to install and no far side to authenticate against. It is an instrument and not a second
    implementation of the port - `tests/contracts/agent.py` is what holds implementations to it.

    `asked` is the whole point. "Preflight was not reached" cannot be shown by an exception type
    alone: an `api.resume` that called `check_ready` first and let its refusal out would raise a
    different class, but one that called it, ignored what came back and then refused on the params
    would raise the right class having already spent the turn.
    """

    def __init__(self) -> None:
        self.asked: Final[list[ModelId]] = []

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        raise AssertionError("a capability was asked of a backend that is not there")

    async def check_ready(self, model: ModelId) -> None:
        self.asked.append(model)
        raise UpstreamUnavailable("the harness is not on PATH: install it, or log in and try again")

    async def run(
        self,
        task: AgentTask,
        *,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        raise AssertionError("preflight refused this run and an agent was dispatched anyway")

@pytest.mark.asyncio
async def test_the_params_rebuild_refuses_before_preflight_spends_a_turn(tmp_path: Path) -> None:
    """`api.py`'s cheapest-refusal-first rule, applied to the one refusal that could have sat
    either side of it.

    Preflight is the only call in `resume` that costs real turns - `check_ready` asks a live harness
    - so every refusal that is free goes in front of it, and rebuilding the params from a mapping is
    two key-set comparisons. The failure this orders against is not exotic: a workflow author edits
    a params dataclass while a run is part-way through, which is what happens repeatedly to
    whoever is iterating, and it should not cost them a round trip to a harness first.

    Arranged so that **both** refusals are available and only one can be reported - the params have
    drifted *and* the backend is not there - which is the shape `tests/sdk/test_preflight.py` uses
    for the one place the same rule is deliberately not followed. The second half is what makes it
    non-vacuous: the identical bundle, resumed against a record whose params still fit, gets as far
    as `check_ready` and is refused by it, so the stub really was armed.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    await _start(harness, "drifting", ("-r", "add oauth"), points=BEFORE)
    runner = _NotReady()
    services = replace(harness.services, agents=runner)

    with pytest.raises(InputError):
        await api.resume(services, PROJECT, LABEL, points=AFTER)

    assert runner.asked == [], (
        "a resume asked a live harness whether it was ready before telling the author that their "
        "workflow's params class had moved - which is the turn `api.py`'s "
        "cheapest-refusal-first rule exists to keep off the bill"
    )

    with pytest.raises(UpstreamUnavailable):
        await api.resume(services, PROJECT, LABEL, points=BEFORE)

    assert runner.asked == [Claude.SONNET], (
        "the stub never refused anything, so the assertion above is not about an ordering"
    )

class _NotTaken(WorkspaceProvider):
    """A provider that refuses to have been reached. Every member is a tripwire, `hold` above all.

    `tests/sdk/test_preflight.py::_Untouched` is this instrument for `api.run`, and this is a second
    small class rather than that one promoted to `tests/instruments/`. **The messages are the
    instrument**, a tripwire's entire output being the sentence it fails with, and a resume's are
    different sentences rather than `run`'s with a noun swapped. `_Untouched.open` says a workspace
    "was provisioned anyway", which of a resume would be wrong twice over: `api.resume` provisions
    one deliberately two lines under preflight, and does it over a checkout that is usually already
    there, idempotently, by `ports/workspace.py`'s "an existing workspace is returned exactly as it
    stands". `_Untouched.remove` and `.discard` name `api.run` outright. Sharing one class means
    either templating every message on which operation is under test - four hand-written sentences
    turned into four that say less - or loosening them until they fit both, which is weakening the
    file that already leans on them. The duplication being bought here is eight lines with no
    behaviour in them, and it is cheaper than either.

    `AssertionError` and never an `AglError`, which is what makes this legible from a `raises`: a
    `pytest.raises(UpstreamUnavailable)` around a resume that took the lock fails carrying the
    sentence below rather than passing on the exception the test was already expecting.

    **`hold` is the member this class exists for.** The run lock is a claim on the run's own
    directory and *making that directory is its one side effect* - `FakeWorkspaceProvider.hold` and
    the real provider agree about that - so a resume that took it and then refused would have left
    something behind on a run it declined to walk. That is the half of `api.py`'s ordering rule this
    module can falsify: "everything above it refuses for free; nothing below it does".
    """

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        raise AssertionError(
            "preflight refused this resume and `_base` was opened anyway, so `agl/<label>` "
            "was cut - or reopened - for a run nobody is walking"
        )

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("nothing in `api.resume` takes a workspace back - that is `clear`")

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("nothing in `api.resume` deletes a line of work - that is `clear`")

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        raise AssertionError(
            "preflight refused this resume and the run lock was taken anyway. The claim is a "
            "lock on the run's own directory and making that directory is the one side effect of "
            "taking it, so a refusal underneath it is a refusal that left something behind"
        )

@pytest.mark.asyncio
async def test_a_resume_refused_at_preflight_takes_no_lock_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """`api.resume`'s own sentence about preflight, pinned by something that is not that sentence.

    "Everything above it refuses for free; nothing below it does" is a claim about the two lines
    directly under it - the run lock and `_base` - and `tests/sdk/test_preflight.py` makes the same
    claim mechanical for `api.run`, with a tripwire provider and an assertion about what is under
    `AGL_HOME`. `api.resume` had neither wired in: its tests asserted that `UpstreamUnavailable`
    came out and nothing about what was taken or written on the way, so the ordering rested on a
    comment. **The ordering is not what this test changes** - `preflight.check` already sits above
    `workspaces.hold`, and this adds no more than a way to find out when it stops.

    **The "nothing written" half is not `api.run`'s, and cannot be.** There it is `_no_record`: a
    run refused at preflight must leave nothing under `AGL_HOME`, or an operator has to `agl clear`
    a run that never started before retrying the one they meant. A resume *requires* a record to
    exist, so its absence is not available as the assertion; what a refused resume owes is the
    record it found, unmoved - `api.resume`'s "The record is read and never rewritten" - and not one
    new step on the ledger.

    The run in front is what stops that being a claim about an empty store. It is interrupted
    between its two steps, so there is exactly one record and one entry standing when the resume is
    refused, and both counters are asserted to have moved before they are cleared - an instrument
    that recorded nothing would otherwise report silence and be believed.

    Six assertions and each fails differently. The class and the exit code say the refusal reaching
    the operator is still preflight's. The tripwire says the lock was not taken and `_base` not
    opened, which no directory listing could say - the run has a checkout already, so its presence
    afterwards is evidence of nothing. The store says the record was not rewritten and the ledger
    not appended to. `handed` says the workflow itself never started. And `runner.asked` is what
    stops the whole thing passing for the wrong reason: preflight really was reached, and
    `check_ready` really was what said no, rather than the resume having refused somewhere above for
    a reason of its own.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    counting = _Counting(harness.store)
    harness = harness.with_store(counting)
    _clear()
    interrupt.append("killed between the two steps")

    with pytest.raises(Interrupted):
        await _start(harness)

    before = await _record(harness)
    assert counting.wrote == [SCOPE], "the run in front wrote no record for the resume to leave"
    assert counting.entries == ["first"], (
        "the run in front left no entry, so 'no entry was appended' below would hold over an empty "
        "ledger and measure nothing"
    )
    counting.wrote.clear()
    counting.entries.clear()

    runner = _NotReady()
    services = replace(harness.services, agents=runner, workspaces=_NotTaken())
    _clear()

    with pytest.raises(UpstreamUnavailable) as caught:
        await api.resume(services, PROJECT, LABEL, points=POINTS)

    assert exit_code_for(caught.value) == 6
    assert runner.asked == [Claude.SONNET], (
        "preflight was never reached, so nothing here is about an ordering: every other assertion "
        "in this test holds of a resume that refused above it for some reason of its own"
    )
    assert counting.wrote == [], (
        "a resume refused at preflight rewrote `run.json`. `api.resume` promises the record is "
        "read and never rewritten, and the invocation with least business moving it is the one "
        "that declined to walk the run at all"
    )
    assert counting.entries == [], "a resume refused at preflight appended a step to the ledger"
    assert await _record(harness) == before, (
        "the record a refused resume found is not the record it left behind"
    )
    assert handed == [], "the workflow was invoked although preflight had refused its backend"
