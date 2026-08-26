"""`agl resume <label>` from the library side: §3.6's replay, driven through the real entry point.

`tests/sdk/test_kill_and_resume.py` is §3.6's own acceptance criterion and is not repeated here. It
kills a real process at every step boundary and resumes in a second one - which is the only way to
falsify half of §3.6's rules - but it constructs its ports and its `Journal` directly and never goes
through `api` at all. What this module owes is the other half of that sentence: that **`api.resume`
genuinely replays**, that the operation a person types is the one wired to the ledger, and that the
refusals §3.10 and §3.11 ask of it are the ones it makes.

The headline property is therefore stated the way §3.6 states it - "the worker was not called" is
the whole of what a replay hit *is* - so every test that cares counts **agent dispatches**, not
entries. A run is interrupted between two steps, resumed, and the first step's agent must have run
exactly once across both invocations while still handing back the value it produced the first time.
An implementation that re-ran it would pass every assertion about the final state and cost the
operator an agent; one that skipped the second step would pass every assertion about the first.

**Everything is `container.fakes()`** - no network, no git, no process - which is target #8 and what
lets a two-invocation replay cost milliseconds. The workflows are declared in this module and
reached through hand-constructed `EntryPoint` values, exactly as `tests/test_api.py` does, and that
seam is also how the two mismatches below are arranged: a workflow whose *version* moved between the
run and the resume, and one whose *params class* did, are two attributes of this module registered
under one entry-point name. Nothing is monkeypatched to produce either.

**The version stamp is asserted with the record afterwards.** §3.11 gives resume one line - "stamp
the version, refuse on mismatch. Runs live hours" - and a refusal that had already touched the run
would be worse than none: the ledger it refused to finish under a stranger's version is the thing
an operator is about to install the right version for.
"""

from collections.abc import Mapping, Sequence
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
    QuestionHandler,
    Restriction,
    StopReason,
)
from agl.ports.errors import (
    ConflictError,
    InputError,
    NotFoundError,
    UpstreamUnavailable,
    exit_code_for,
)
from agl.ports.home_layout import RunScope
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
# the resume adds - §3.6's "a commit landing on `main` between run and resume".
SEEDED: Final = "src/a.txt"
LANDED: Final = "src/landed.txt"


@dataclass(frozen=True)
class ResumeParams:
    """§3.3's example shape. `concurrent` is a default the user never typed, which is the half of
    "params come from `run.json`" that is lost if the record is not the whole story."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)


@dataclass(frozen=True)
class OtherParams:
    """`ResumeParams`' fields under other names: what a workflow that changed its params looks
    like from the record's side, once the version stamp has let it past."""

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
# fingerprints. Read-only and paired with steps that pass no `commit=`, which is what §3.3 asks an
# author to write.
#
# Two factories rather than one `replace` of the other, which is what UF1.2 took away: a factory
# closes the override surface, and a role that could be re-spelled at a call site is a role whose
# fingerprint terms a call site can move. The duplication is four literals and it is the honest
# version of a distinction that is only ever declared once.


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
    """§3.1's own example of a workflow's reason to stop, spelled against the SDK's `Stop`."""


# What each workflow was handed, what its steps gave back, and the interruption a test arms. Module
# level because the workflows have to be: `EntryPoint.load` imports a module and reads an attribute
# in it, and sees no local of a test function.
handed: Final[list[Run[object]]] = []
produced: Final[list[Summary]] = []
interrupt: Final[list[str]] = []
raised: Final[list[Stop]] = []


@workflow(name="two_steps", version="1.1", params=ResumeParams)
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


@workflow(name="quiet", version="1", params=NoParams)
async def quiet(run: Run[NoParams]) -> None:
    """Takes no step at all - the run for which §3.9's "`agl/<label>` is a real ref from run start"
    is only true if something above the first step provisioned `_base`."""
    handed.append(run)


@workflow(name="halting", version="0.1", params=NoParams)
async def halting(run: Run[NoParams]) -> None:
    """Ends deliberately, with a reason of its own - which the framework must not rename."""
    handed.append(run)
    stop = ReviewNotConverging("two rounds and no convergence")
    raised.append(stop)
    raise stop


@workflow(name="shifting", version="1.0", params=NoParams)
async def shifting_before(run: Run[NoParams]) -> None:
    """The workflow the record is stamped by. Registered under `shifting`."""
    handed.append(run)


@workflow(name="shifting", version="2.0", params=NoParams)
async def shifting_after(run: Run[NoParams]) -> None:
    """The same entry-point name at another version - the installation a resume meets hours later.

    Two attributes of this module rather than a mutated `Workflow`: `Workflow` is frozen, and what
    an operator actually has is a package that was upgraded, which is a different object behind one
    entry-point key.
    """
    handed.append(run)


@workflow(name="drifting", version="1.0", params=ResumeParams)
async def drifting_before(run: Run[ResumeParams]) -> None:
    """The params class the record is written from. Registered under `drifting`."""
    handed.append(run)


@workflow(name="drifting", version="1.0", params=OtherParams)
async def drifting_after(run: Run[OtherParams]) -> None:
    """The same name and the **same version**, with the params renamed underneath - the one way a
    record can reach `params.from_json` disagreeing with the class, and the fault it names."""
    handed.append(run)


def _point(name: str, attribute: str) -> EntryPoint:
    """§3.3's `probe = "agl.workflows.probe:probe"`, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)


POINTS: Final = (
    _point("two_steps", "two_steps"),
    _point("quiet", "quiet"),
    _point("halting", "halting"),
)

# The two mismatches, as two installations of one workflow. Kept out of `POINTS` so that a test
# resuming under `AFTER` is resuming under an installation that holds one `shifting` and one
# `drifting`, which is what an upgrade leaves behind.
BEFORE: Final = (
    *POINTS, _point("shifting", "shifting_before"), _point("drifting", "drifting_before")
)
AFTER: Final = (
    *POINTS, _point("shifting", "shifting_after"), _point("drifting", "drifting_after")
)


def _reporting(dispatched: list[str]) -> Script:
    """An agent that writes nothing, reports one payload, and records that it was paid for.

    `dispatched` is the whole instrument of this module: §3.6's replay has no observable difference
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
) -> None:
    """The first invocation: `agl run <name> -n auth`, with this module's entry points."""
    await api.run(harness.services, PROJECT, name, LABEL, argv, points=points)


async def _resume(
    harness: container.FakeServices,
    *,
    label: RunLabel = LABEL,
    points: Sequence[EntryPoint] = POINTS,
) -> None:
    """The second invocation: `agl resume auth`, and the label is the whole of what it takes."""
    await api.resume(harness.services, PROJECT, label, points=points)


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
    """§3.6, through the command rather than through a hand-built `Run`.

    The workflow function is re-run from the top - `handed` gets a second `Run` - the step that
    already has an entry is a no-op returning its stored value, and only the step that never ran
    reaches an agent. Three assertions, because each of the other two is satisfied by a build that
    gets the third wrong: an `api.resume` that started the workflow at the second step would leave
    `dispatched` right and never prove the walk; one that re-ran `first` would leave `produced`
    right and cost the operator an agent; one that replayed both would leave `handed` right and
    finish nothing.

    The counter is rebuilt from nothing on the way, which is what makes the first step *hit* at
    all: §3.6's `n` is never persisted, so the resume's fresh `Fingerprints` has to walk the same
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
    """§3.3: "persisted into `run.json`, which is why `agl resume auth` takes no flags", read back.

    `concurrent` is asserted at 4 - a value the resume's own command line could not have carried,
    since there is no command line - and `request` at what was typed hours earlier. The type is
    asserted too: `run.params` is an instance of the workflow's class and not the mapping the store
    handed over, which is the difference between §3.3's typing promise holding on a resume and
    holding only on a fresh run.
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


# --- the record is read and never written --------------------------------------------------------


class _Counting(Store):
    """The bundle's own store with a note taken of every `write_record`, and nothing else changed.

    `_Watching` below is the same instrument one port over, and `src/agl/testing.py::_Ledger` is the
    precedent for the shape: a decorator whose every member delegates, so the store underneath is
    still the bundle's `MemoryStore` and `tests/contracts/store.py` remains the only thing that says
    how a `Store` behaves. This one has no behaviour of its own to be wrong about either.

    It counts the *scopes* rather than the calls, because the one thing a reader wants from a
    failure is which run was written to. Installed with `FakeServices.with_store`, which is what
    keeps `harness.store` and `harness.services.store` the same object - a `replace` around the
    bundle would leave the test reading a different ledger from the one the run used.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self.wrote: list[RunScope] = []

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
        await self._store.write_entry(scope, step, digest, value)

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        return await self._store.namespaces(scope)

    async def remove(self, scope: RunScope) -> None:
        await self._store.remove(scope)


@pytest.mark.asyncio
async def test_a_resume_does_not_rewrite_run_json(tmp_path: Path) -> None:
    """§3.6's pin, from the side only a resume can show it from - and `api.resume`'s bold claim.

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
        "on `main` between run and resume cannot move the first step's starting head (§3.6) - a "
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

    §3.9 promises `agl/<label>` is a real ref a person can `git log` from run start, and
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
    """§3.10: "`resume` on a missing label errors symmetrically. Keeping both verbs makes a typo'd
    label a loud error rather than a silent replay of something unrelated."

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
async def test_a_workflow_version_the_record_was_not_stamped_with_is_refused(
    tmp_path: Path,
) -> None:
    """§3.11: "Schema migration | Stamp the version, refuse on mismatch. Runs live hours."

    `ConflictError` - exit 4, the same code `run` answers a taken label with - because the record
    exists and the workflow exists and neither is wrong: they do not fit, which is
    `ports/errors.py`'s "the world already holds something this operation would have to take or
    overwrite". `NotFoundError` would be wrong twice over, both things having been found.

    The message is asserted for the two facts an operator acts on - which version the run is
    stamped with, and that `agl clear` is the other way out - and the record is asserted untouched
    afterwards, since the ledger this refused to finish is what the right version is about to
    finish.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    await _start(harness, "shifting", (), points=BEFORE)
    before = await _record(harness)

    with pytest.raises(ConflictError) as caught:
        await _resume(harness, points=AFTER)

    assert exit_code_for(caught.value) == 4
    message = str(caught.value)
    assert "'1.0'" in message and "'2.0'" in message
    assert "agl clear auth" in message
    assert await _record(harness) == before, "a refused resume changed the run it refused"
    assert len(handed) == 1, "the workflow ran under a version the record was not stamped with"


@pytest.mark.asyncio
async def test_the_same_version_is_not_a_mismatch(tmp_path: Path) -> None:
    """The other side of `==`, so that the test above is about a comparison and not about refusing.

    Worth its own line because a stamp that refused everything would satisfy every assertion in the
    test above, and the workflow that resumes normally elsewhere in this file is a different one.
    """
    dispatched: list[str] = []
    harness = _fakes(tmp_path, dispatched)
    _clear()
    await _start(harness, "shifting", (), points=BEFORE)

    await _resume(harness, points=BEFORE)

    assert len(handed) == 2


@pytest.mark.asyncio
async def test_params_the_workflows_current_class_will_not_take_are_refused(
    tmp_path: Path,
) -> None:
    """`sdk/params.py`'s refusal, reached the only way an operator can reach it.

    The workflow keeps its version and changes its params class, which is exactly the case the
    version stamp cannot catch and the case that module names as the realistic one. `InputError` -
    exit 2 - because the reader is the workflow's author and the fix is a line in their package,
    where exit 70 would send them to file a bug against AGL. The message names the keys, because
    "the params do not match" leaves them to work out which field moved.
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


# --- the ordering hazard, on the resumed side ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_stop_raised_by_a_resumed_workflow_leaves_api_resume_unwrapped(
    tmp_path: Path,
) -> None:
    """§3.1's criterion, asserted of `resume` as `tests/test_api.py` asserts it of `run`.

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
        on_question: QuestionHandler | None = None,
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
    a params dataclass and leaves the `version` line alone, which is what happens repeatedly to
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
        "workflow's params class had moved without its version - which is the turn `api.py`'s "
        "cheapest-refusal-first rule exists to keep off the bill"
    )

    with pytest.raises(UpstreamUnavailable):
        await api.resume(services, PROJECT, LABEL, points=BEFORE)

    assert runner.asked == [Claude.SONNET], (
        "the stub never refused anything, so the assertion above is not about an ordering"
    )
