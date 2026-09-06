"""What `run.integrate()` promises: a landing into the parent, serialized per target, and a chain
that advances.

The suite over `sdk/_engine/integration.py` and over the half of `sdk/workflow.py` that reaches it.
`tests/contracts/integration.py` holds the *port* to `land`, `retry` and `abort`; nothing here
repeats any of that. What this file is about is the six decisions the framework makes around those
three calls, each of which fails silently or destructively rather than loudly:

  * **The advance.** "`integrate()` advances the parent's `last_good`. A child landing moves
    the parent's physical head, but `last_good` is chained from step entries and `integrate()` is
    not a step - so the parent's next step to miss its fingerprint would `restore()` to a commit
    *before* every landed child and delete all of it." Two tests, deliberately: one asserts the
    value, and one produces the deletion. The second is the one that could not be argued away.
  * **The lease.** Landings into one target are taken one at a time, and the lease outlives an
    unresolved conflict - so a workflow that walks away from one and a run that exits are two
    different things, and the second gives the lease back while deliberately leaving the adapter's
    hold where it is - the hold is durable so a later invocation can find one it did not take.
  * **The containment check.** `land` answers a pre-existing hold with a `Conflict`, so a `retry`
    can conclude a landing this call never offered - somebody else's child. Unchecked, that head
    becomes this child's `last_good` and the workflow believes work landed that is not there. The
    two-run test at the bottom is that scenario end to end, and it is the sharpest thing here.
  * **The root refusal.** `main` is unaddressable rather than policy-protected, and
    the message has to say which, because the difference decides whether a reader goes looking for
    a flag.
  * **The gate.** "The framework runs exactly one build: the merge gate." It stands between a
    landing and the advance and is the only thing in AGL that catches a semantic conflict - two
    pieces of work that each build alone and are broken together, which every check before it has
    already said yes to. A red one reverts with `Workspace.restore` and comes back as a `Conflict`
    with the lease still held, so its tests sit beside the textual ones rather than in a file of
    their own: the two conflicts have one shape and one pair of verbs, and the only thing that tells
    them apart is `Integration.verdict`, which `Integration.refused_by_the_gate` reads as a
    predicate.
  * **The settling.** Every path out of a hold has to give it back. `integrate()` already says so
    with `except BaseException: lease.release(); raise`, and `api.run` says it again with `finally:
    leases.release_all()` - but `retry()` and `abort()` are the two verbs a *workflow* calls on a
    live conflict, and a raise out of either of them is the one exit neither of those two clauses
    covers. The failure is not an error, it is a hang: the next landing into that parent waits on
    `Leases.claim` for the life of the process with nothing raised, which is why the two tests at
    the bottom bound the second claim rather than awaiting it.

**Every test above the gate section runs with a green one**, because `FakeVerifier` passes a command
nobody scripted - "a gate that failed by default would reject every landing of a run whose point was
to show the shape of the work". So the landings asserted there are gated landings, and a test that
wants a red gate scripts `container.FAKE_BUILD` and says so in its own name.

**The bundle is `container.fakes(...)` and the repository is in memory.** Unlike
`test_run_worktree.py`, nothing here is a claim about git: `FakeIntegrator` runs a real three-way
merge (`adapters/git/_merging.py`), holds a conflicted landing in the repository rather than in
itself, and refuses the same overwrites the real adapter refuses - which is every property these
tests read. What real git would add is a `MERGE_HEAD` on disk, and no test here looks at one.

**Two `Run` trees over one bundle is how a resumed run is spelled.** A second `Run` at the same
scope, over the same `MemoryStore` and the same `FakeRepository`, replays every recorded step,
reopens every checkout and builds fresh `Fingerprints`, `Worktrees`, `Leases` and `Journal`s - which
is exactly what a second process does, minus the process. The one thing it cannot model is a hold
surviving the interpreter, which `adapters/git/fake.py` already says is unreachable for a fake.

The fixtures are duplicated from `test_run_worktree.py` rather than imported, for that file's
reason: nothing under `tests/` imports another test module, and a shared fixture module would make
one file's arrangement another file's dependency.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.config import container, registry
from agl.ports.agent import AgentTask, Claude, Restriction
from agl.ports.errors import InputError, InternalError, UpstreamUnexpected
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.integration import IntegrationOutcome, Integrator
from agl.ports.tree_layout import TreesRoot
from agl.ports.verifier import Verifier, VerifierOutcome
from agl.ports.workspace import Workspace
from agl.sdk.roles import Role, role
from agl.sdk.testing import Agent, Call, Reply
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run, workflow

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

TICKET: Final = Namespace("T-01")
SIBLING: Final = Namespace("T-02")

# What the repository is seeded with, and the three files the tests below move about. `CONTESTED` is
# the one two lines of work both create, sharing not a single line - which is the only shape no
# honest implementation can combine, and `tests/contracts/_integration_targets.py` argues why a
# suite has to cause one rather than declare it.
SEEDED: Final = "src/a.txt"
SEED: Final = b"the user's own work\n"
FIRST: Final = "src/first.py"
SECOND: Final = "src/second.py"
CONTESTED: Final = "src/contested.py"

PARENT_BODY: Final = b"parent\nparent\nparent\n"
CHILD_BODY: Final = b"child\nchild\nchild\n"
RESOLVED: Final = b"what a person decided\n"

# What a person types into the target's checkout at a refusal screen and does not commit. It goes
# into `FIRST`, which is the one file the landing writes, because that is what makes the next `land`
# refuse: an integrator may not write over work in the target that nothing has recorded.
HAND_EDITED: Final = b"the fix a person typed and did not commit\n"

# What an `Integrator` whose far side has gone wrong says. `UpstreamUnexpected` and not `AglError`,
# because a raise out of `retry` or `abort` is the adapter's own vocabulary reaching a workflow.
BROKE: Final = "the integrator's far side failed while giving up on this landing"

# The gate's vocabulary. `CONFIGURED` is a build command that is deliberately **not**
# `container.FAKE_BUILD`, so a test asserting that the project's own command reached the port cannot
# pass by agreeing with a default; `ARTIFACT` is what a build tool leaves in the directory it was
# pointed at, which is the thing `Workspace.restore` has to take away along with the landing; `RED`
# is the output a person would be reading on the conflict screen.
CONFIGURED: Final = "agl-fake-build --this-projects-own"
ARTIFACT: Final = "build.log"
RED: Final = "1 test failed: the two changes disagree about what `parse` returns\n"

# How long a landing that should not be waiting on anything is given before the test calls it a
# lease nobody gave back. **Never waited for on a green run** - every integration below completes
# in microseconds - so the only thing this trades away is how long a broken build takes to say so,
# and a bound tight enough to fire on a loaded machine would report a flake as a deadlock.
_LIVENESS: Final = 30.0

# How long the one test that proves a negative waits before concluding that a landing really is
# waiting for the target's own step. This one **is** spent on every green run, because the wait is
# the proof. Short, because the thing it has to outlast is one dispatch against fakes - no process,
# no git, no network - and long, because a bound that fired before the landing could have got as far
# as its first `await` would pass against exactly the implementation it is written to catch.
_SERIALIZED: Final = 1.0

# How many times a conflict screen may go up over one integration before the test calls the loop
# unterminating. One is the answer the test that spends this expects; the slack is here so that the
# failure it reports is "this loop does not end" rather than an off-by-one about how many times a
# person was asked.
_PATIENCE: Final = 3

@dataclass(frozen=True)
class _Pause:
    """A rendezvous a scripted agent parks on, so a test can hold one namespace's step open.

    Two events rather than a sleep: `started` says the step is genuinely inside its worker, and
    `release` is the test deciding when it ends. Nothing here waits on a scheduler, so the only
    duration in the test that uses it is the bound it spends proving a negative.
    """

    started: asyncio.Event
    release: asyncio.Event

@dataclass(frozen=True)
class Summary:
    """A reporting payload: one string, which is the whole of what these agents have to say."""

    text: str

@dataclass(frozen=True)
class NoParams:
    """A workflow that takes no flags - `api.run` still parses an empty argv against it."""

REPORT: Final = reporting_tool("report", "report what you did", Summary)

@role(model=Claude.SONNET)
def _role(name: str, instructions: str) -> Role[Summary]:
    """A reporting role that may commit: its result is `REPORT`'s payload, read back as a
    `Summary`. `name` is the address its entries go to, `run.step` carrying none."""
    return Role(
        name=name,
        instructions=instructions,
        restrictions=set[Restriction](),
        tools=(REPORT,),
    )

# Module-level, which is what a `Role` is, and distinct per writer: the scripted agent below
# decides what to write from the instructions it was handed, so two roles that shared a string would
# be two children writing one file.
PREPARE: Final = _role("prepare", "prepare the parent")
IMPLEMENT_FIRST: Final = _role("implement", "implement T-01")
IMPLEMENT_SECOND: Final = _role("implement", "implement T-02")
COLLIDE: Final = _role("implement", "implement T-01, over the same file the parent touched")
REVIEW: Final = _role("review", "review the parent's worktree")
HOLDING: Final = _role("review", "review the parent's worktree, slowly")

# Which files each role's agent leaves behind, keyed by the instructions it is dispatched with.
# Keyed on the prompt because that is the only thing the port hands a script that says which step
# this is - `AgentTask` carries no namespace and no step name, deliberately.
_WRITES: Final[Mapping[str, Mapping[str, bytes]]] = {
    PREPARE.instructions: {CONTESTED: PARENT_BODY},
    IMPLEMENT_FIRST.instructions: {FIRST: b"the first child's work\n"},
    IMPLEMENT_SECOND.instructions: {SECOND: b"the second child's work\n"},
    COLLIDE.instructions: {CONTESTED: CHILD_BODY},
    REVIEW.instructions: {},
    HOLDING.instructions: {},
}

def _agent(pause: _Pause | None = None) -> Agent:
    """One agent for every role here: write what this prompt is meant to write, then report.

    Writing to `task.workspace` with the stdlib is the agent's own code and not the adapter's,
    which is what lets a fake agent leave real files in a real directory for `commit=` to record.

    `pause` parks the `HOLDING` role inside its worker until a test lets it go, which is how one
    test below holds the target namespace's step lock open while a landing asks for it. An `async
    def` in `sdk/testing.py`'s own vocabulary, which is what `container.fakes(agent=...)` takes.
    Before an `Agent` could await, parking on an event had to be written as a raw per-provider
    `Script`.
    """

    async def _one(task: AgentTask) -> Reply:
        if pause is not None and task.instructions == HOLDING.instructions:
            pause.started.set()
            await pause.release.wait()
        for name, content in _WRITES.get(task.instructions, {}).items():
            where = task.workspace / name
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_bytes(content)
        return Reply(calls=[Call(REPORT.name, {"text": task.instructions})])

    return _one

# --- the bundle, the run, and the two places on disk ---------------------------------------------

class _Recorded(Verifier):
    """A `Verifier` that answers a fixed verdict, remembers what it was asked, and can leave a mess.

    Two things `FakeVerifier` cannot do, and neither is a defect in it. It "accepts `workdir` and
    never reads it", because "what a runner can be pointed at is a fact about that runner" and a
    dict has no filesystem in it to be pointed at - so where the gate ran is exactly the fact that
    fake was designed not to have. And it starts nothing, so it leaves nothing behind, where a real
    build tool writes a log, a cache and a coverage file into the tree it was pointed at.

    Both are properties of this module's call site rather than of the port, which is why this lives
    here beside the tests that read it and not in `adapters/shell/fake.py`. It is substituted into
    the bundle rather than constructed with it, because `container.fakes()` has no parameter for a
    second verifier and should not grow one for a test.
    """

    def __init__(self, *, passed: bool, leaves: str | None = None) -> None:
        self.calls: list[tuple[str, Path]] = []
        self._passed = passed
        self._leaves = leaves

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        """Record the pair, optionally write a build's leavings into `workdir`, and answer."""
        self.calls.append((command, workdir))
        if self._leaves is not None:
            (workdir / self._leaves).write_bytes(b"what the build left behind\n")
        return VerifierOutcome(
            passed=self._passed, status=0 if self._passed else 1, output="" if self._passed else RED
        )

def _harness(
    tmp_path: Path, pause: _Pause | None = None, *, build: str = container.FAKE_BUILD
) -> container.FakeServices:
    """The all-fakes bundle: no network, no git, no process, one repository behind all three.

    `build` is the merge gate's command, defaulted to the constant a test scripts a verdict against
    so that `harness.verifier.answers(container.FAKE_BUILD, ...)` and the bundle are one string.
    Named only by the one test that asks whether the *project's* command is what reaches the port.
    """
    return container.fakes(
        TreesRoot(tmp_path / "trees"), files={SEEDED: SEED}, build=build, agent=_agent(pause)
    )

async def _base(harness: container.FakeServices) -> str:
    """The pinned commit a run is cut from - `RunSpec.base_sha`'s shape, through the port."""
    history = harness.services.history
    return await history.resolve(await history.default_ref())

async def _tree(harness: container.FakeServices) -> Run[None]:
    """One root `Run` over this bundle. Called twice with one bundle it is a resumed run: the same
    ledger, the same repository, the same checkouts, and everything the process held rebuilt."""
    return Run(params=None, services=harness.services, scope=SCOPE, base=await _base(harness))

async def _tree_gated_by(harness: container.FakeServices, verifier: Verifier) -> Run[None]:
    """One root `Run` over this bundle, with the gate's verifier swapped for the one passed.

    `Services` is a frozen dataclass of ports and a string, so a substitution is `replace` and
    nothing else - every other field is the *same object* the bundle holds, which is what keeps
    `harness.repository` and `harness.store` readable afterwards. `container.fakes()` deliberately
    has no parameter for a second verifier, and adding one so that a test could ask where a build
    ran would be the composition root growing a member for this file's benefit.
    """
    return Run(
        params=None,
        services=replace(harness.services, verifier=verifier),
        scope=SCOPE,
        base=await _base(harness),
    )

async def _tree_integrated_by(harness: container.FakeServices, integrator: Integrator) -> Run[None]:
    """One root `Run` over this bundle, with the `Integrator` swapped for the one passed.

    `_tree_gated_by` for the other port, and `replace` for the same reason: every other field stays
    the *same object* the bundle holds, so `harness.repository` and the checkouts on disk are still
    the ones the substituted integrator is deciding about.
    """
    return Run(
        params=None,
        services=replace(harness.services, integrator=integrator),
        scope=SCOPE,
        base=await _base(harness),
    )

async def _head(harness: container.FakeServices, namespace: Namespace | None) -> str:
    """Where one checkout's line of work is now, asked through the port rather than of a dict.

    `WorkspaceProvider.open` is idempotent by contract - "an existing workspace is returned exactly
    as it stands" - so this reopens what the run already provisioned and cuts nothing. `None` is the
    run's own `_base`, which is the target every landing here goes into.
    """
    workspace = await harness.services.workspaces.open(LABEL, namespace, await _base(harness))
    return await workspace.head()

# Both paths are **spelled out** rather than composed through `tree_layout`, for
# `test_run_worktree.py`'s reason: a test that asked the layout where a checkout should be and then
# looked there would agree with the layout whatever either of them said.

def _target_dir(tmp_path: Path) -> Path:
    """`.trees/auth/_base/` - the run's own checkout, which is what children land into."""
    return tmp_path / "trees" / "auth" / "_base"

def _child_dir(tmp_path: Path, namespace: str) -> Path:
    """`.trees/auth/<namespace>/` - a child's checkout, a flat sibling of `_base`."""
    return tmp_path / "trees" / "auth" / namespace

# --- the root has no parent ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_root_run_refuses_to_integrate_and_says_main_is_unaddressable(
    tmp_path: Path,
) -> None:
    """"The root Run has no parent, so calling it there raises, and there is no argument to
    point it elsewhere."

    **The class is `InputError`**, which is `Namespace`'s and `params.parse`'s: what the caller
    supplied cannot be used and nothing was attempted, so exit 2 sends a workflow author to the line
    they wrote. `InternalError` would send them hunting for a bug in the framework over a call they
    made on purpose.

    **And the message is asserted, not merely the class.** There is one claim about
    `main` that a refusal can get wrong without failing any test: it is **unaddressable rather than
    policy-protected**. A message phrased as a permission - "AGL will not write to your branches" -
    invites the reader to go looking for the flag that lets it, and there is none to find, because
    AGL never checks out or writes to any ref outside `agl/*` at all. So the words that carry the
    distinction are what this asserts.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)

    with pytest.raises(InputError) as raised:
        await run.integrate()

    said = str(raised.value)
    assert "unaddressable" in said, (
        f"the refusal does not say the word: {said!r}. `main` is unaddressable "
        f"rather than protected, and a refusal that reads as a policy sends the reader looking for "
        f"the setting that relaxes it"
    )
    assert "agl/*" in said, (
        "the refusal does not name the invariant it follows from - AGL never checks out or writes "
        "to any ref outside `agl/*` - so it reads as a rule rather than as a consequence"
    )
    assert "worktree" in said, (
        "the refusal does not say what a caller should have done instead. Only a child opened with "
        "`run.worktree(namespace)` has a parent to land into, and that is the whole of the fix"
    )

# --- the landing, and the advance it must not forget ---------------------------------------------

@pytest.mark.asyncio
async def test_a_childs_work_lands_in_the_parents_line_of_work(tmp_path: Path) -> None:
    """`run.integrate()`: this Run's branch, into its parent's worktree.

    Three things are asserted about one landing and each is a different claim. The outcome says it
    landed and carries the target's resulting state, which is the port's two-case answer. The
    parent's line of work now **contains** the child's, asked of `History` rather than of a
    directory - a landing that moved files without recording anything would satisfy the third
    assertion and not this one. And the parent's *checkout* holds the file, because that tree is
    what the build gate runs in and what the next step in the parent will be handed.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    landed = await _head(harness, TICKET)

    outcome = await ticket.integrate()

    assert outcome.conflicted is False, f"a landing into an untouched target conflicted: "\
        f"{outcome.conflict}"
    assert outcome.head is not None
    assert await harness.services.history.contains(landed, outcome.head), (
        f"the target is at {outcome.head!r} and that state does not contain the child's own "
        f"{landed!r}. The outcome says the work went in, so the one thing it may not be is a head "
        f"the child's line of work is absent from"
    )
    assert (_target_dir(tmp_path) / FIRST).is_file(), (
        "the child's file is not in the target's checkout. A landing goes into `_base` because "
        "that is where AGL's own integration branch is checked out, and it is the tree the build "
        "gate runs in - a landing recorded but not applied is a gate deciding about another tree"
    )

@pytest.mark.asyncio
async def test_the_parents_last_good_advances_to_the_landing_head(tmp_path: Path) -> None:
    """In as many words: "`IntegrationOutcome.head` carries the value; the engine must write
    it into the parent's chain."

    The arithmetic half of the claim, asserted where it is cheapest: the parent's chain, which was
    the commit its own last step ended at, is now the commit the landing produced. The next test
    produces what leaving it out costs, which is the half that matters and the slower one to reach.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await run.step(PREPARE, commit="prepare the parent")
    before = run._steps.last_good
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")

    outcome = await ticket.integrate()

    assert outcome.head is not None and outcome.head != before
    assert run._steps.last_good == outcome.head, (
        f"the parent's chain is at {run._steps.last_good!r} and the landing produced "
        f"{outcome.head!r}. `integrate()` is not a step, so nothing journals it and nothing else "
        f"will ever move this value - forgetting it is one of three paths in the design "
        f"that destroy work rather than costing a re-run"
    )

@pytest.mark.asyncio
async def test_the_parents_next_step_does_not_delete_the_child_that_landed(tmp_path: Path) -> None:
    """The destructive half, produced rather than argued.

    Without the advance "the parent's next step to miss its fingerprint would `restore()` to a
    commit *before* every landed child and delete all of it". So this runs that step. `review` takes
    no `commit=`, so both restores fire - the unconditional one before the worker and the
    wipe after it - and each of them is `reset --hard` *and* `clean -fd` against `last_good`.

    With the advance, `last_good` is the landing and the child's file survives. Without it,
    `last_good` is the commit the parent's own `prepare` ended at, the restore takes the tree back
    there, and the file the child landed is gone - with nothing raising, nothing re-running and the
    workflow still believing the landing happened. That is the whole failure, and it is why this
    test asserts a file's existence rather than a value.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await run.step(PREPARE, commit="prepare the parent")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    outcome = await ticket.integrate()
    assert outcome.conflicted is False

    await run.step(REVIEW)

    assert (_target_dir(tmp_path) / FIRST).is_file(), (
        "the landed child's file is gone from the target's checkout after a read-only step in the "
        "parent. That step restored to `last_good`, which means the landing never reached the "
        "parent's chain - one of the three paths that destroy work rather than costing a re-run"
    )
    assert (_target_dir(tmp_path) / CONTESTED).read_bytes() == PARENT_BODY, (
        "the parent's own work is gone too, so the restore went back further than the landing"
    )

@pytest.mark.asyncio
async def test_two_children_landing_at_once_serialize_and_both_go_in(tmp_path: Path) -> None:
    """"Landings into one target are serialised". Both land, and neither is lost.

    The two children are gathered, which is the shape a `drive` loop produces and the only one that
    can fail: `FakeIntegrator.land` reads the target's head, combines against it and records - so
    two of them interleaved at that suspension both compute a combination from the *same* head, and
    whichever records second replaces the first one's landing with one that never saw it. Nothing
    raises. The child that lost is simply not in the target, and its `integrate()` returned a head
    saying it was.

    So the assertions are about containment and not about ordering: the parent's chain ends at a
    state that contains **both** children's lines of work, and both files are in the checkout the
    gate would run in. Which of the two landed first is asyncio's business and no part of the claim.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    first = run.worktree("T-01")
    second = run.worktree("T-02")
    await first.step(IMPLEMENT_FIRST, commit="implement T-01")
    await second.step(IMPLEMENT_SECOND, commit="implement T-02")
    landed = (await _head(harness, TICKET), await _head(harness, SIBLING))

    outcomes = await asyncio.wait_for(
        asyncio.gather(first.integrate(), second.integrate()), timeout=_LIVENESS
    )

    assert [one.conflicted for one in outcomes] == [False, False], (
        f"two children touching different files did not both land: {outcomes[0].conflict}, "
        f"{outcomes[1].conflict}"
    )
    settled = run._steps.last_good
    for child, head in zip(("T-01", "T-02"), landed, strict=True):
        assert await harness.services.history.contains(head, settled), (
            f"the parent's chain is at {settled!r}, which does not contain {child}'s work. Both "
            f"children landed and both were told they had, so one of the two landings was computed "
            f"against a head the other had already moved past"
        )
    assert (_target_dir(tmp_path) / FIRST).is_file()
    assert (_target_dir(tmp_path) / SECOND).is_file()

@pytest.mark.asyncio
async def test_a_landing_waits_for_a_step_already_running_in_the_target_namespace(
    tmp_path: Path,
) -> None:
    """The exclusion nothing writes down, and the only test in this file that proves a
    negative.

    "**A namespace's workspace is single-threaded** ... two concurrent steps in one namespace
    share one `Workspace`", and overlapped, "A's pre-run restore wipes the files B's worker has just
    written, B's `commit_all` records A's changes under B's message, and A's `head()` after its own
    commit reads B's". Every one of those sentences is true of a **landing** into that namespace,
    which restores nothing but writes the whole tree, moves the branch and reads the head. Nothing
    says so in as many words, because one rule is about steps and the other is about integrations.

    So an integration takes the target namespace's step lock behind its lease, and this is that
    claim in the only form that can fail: a step in the parent is parked inside its worker, the
    child's `integrate()` is started, and the landing must **not** have finished while the step is
    still in flight. The wait is the assertion; letting the step go afterwards is what shows the
    landing was queued rather than broken.

    Nothing here sleeps against a scheduler. `started` is set from inside the parent's own agent, so
    the step is genuinely mid-walk when the landing is offered, and the bound below only decides how
    long a green run spends proving the negative.
    """
    pause = _Pause(asyncio.Event(), asyncio.Event())
    harness = _harness(tmp_path, pause)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")

    step = asyncio.create_task(run.step(HOLDING))
    await asyncio.wait_for(pause.started.wait(), timeout=_LIVENESS)
    landing = asyncio.create_task(ticket.integrate())

    finished, _ = await asyncio.wait({landing}, timeout=_SERIALIZED)

    assert not finished, (
        "the landing completed while a step in the target namespace was still inside its worker. "
        "A landing writes that namespace's whole checkout, moves its branch and reads its head - "
        "which is every one of the things the serialization lock exists to keep two writers "
        "from doing at once, and none of the ways it goes wrong raises anything"
    )

    pause.release.set()
    outcome = await asyncio.wait_for(landing, timeout=_LIVENESS)
    await asyncio.wait_for(step, timeout=_LIVENESS)

    assert outcome.conflicted is False, (
        f"the landing failed once the step let go of the namespace: {outcome.conflict}. It was "
        f"queued, not broken - the lock is released when the step ends and the landing goes on"
    )
    assert (_target_dir(tmp_path) / FIRST).is_file()

# --- the conflict, and the two verbs that end it -------------------------------------------------

async def _hold_the_target(tmp_path: Path) -> tuple[container.FakeServices, Run[None], Run[None]]:
    """A run whose child cannot land: the parent and the child both create `CONTESTED`.

    The child is cut **before** the parent's own step, so the two lines of work share a base in
    which the file does not exist and neither of them has ever seen the other's version. There is no
    combination of those two states that is anybody's answer, which is what
    `tests/contracts/_integration_targets.py` requires of a conflict a suite causes on purpose.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await run.step(PREPARE, commit="prepare the parent")
    await ticket.step(COLLIDE, commit="implement T-01")
    return harness, run, ticket

@pytest.mark.asyncio
async def test_a_conflicted_landing_comes_back_live_and_abort_puts_the_target_back(
    tmp_path: Path,
) -> None:
    """"On conflict the framework does not ask. It returns a `Conflict` outcome and holds the
    lease; the workflow shows its own screen and decides."

    Four claims in one arrangement. The outcome is the port's second case, with no head and a
    `Conflict` whose `summary` says something - that string is what the workflow puts on a screen,
    and the decision being asked of the person reading it is which of the two verbs to call. Nothing
    is shown here: this deliverable builds both halves of the conflict loop and never executes
    the middle line, which came later. It is executable now -
    `tests/sdk/test_terminal_priorities.py` runs the whole snippet on both branches, with a real
    conflict, the workflow's own view and a person choosing - and this test deliberately stays the
    one that asks what the two verbs do with nobody watching.

    Then `abort()`: the hold goes, the target goes back to where `land` found it - which is the
    state the parent's own step left, not the state the run started in - and the parent's chain
    never moved, because nothing landed.
    """
    harness, run, ticket = await _hold_the_target(tmp_path)
    before = await _head(harness, None)
    chain = run._steps.last_good

    outcome = await ticket.integrate()

    assert outcome.conflicted is True, (
        "two lines of work that both created one file, sharing not a line and neither having seen "
        "the other, were combined anyway - which is forbidden in as many words: a conflict is not "
        "resolved by guessing"
    )
    assert outcome.head is None, "the two-case outcome, and this is the case with no head in it"
    assert outcome.conflict is not None and outcome.conflict.summary, (
        "a conflicted integration came back with nothing for the workflow's screen. `summary` is "
        "the only part of a `Conflict` guaranteed to say anything"
    )

    await outcome.abort()

    assert await _head(harness, None) == before, (
        f"after an abort the target is at a state other than {before!r}, where it stood before the "
        f"landing that conflicted"
    )
    assert (_target_dir(tmp_path) / CONTESTED).read_bytes() == PARENT_BODY, (
        "the file the two lines of work collided over does not hold what the target held before "
        "the landing. Putting the head back is not the whole of it: whatever the attempt left in "
        "the working tree is what the next step, and the next person to look, would read"
    )
    assert run._steps.last_good == chain, "nothing landed, so the parent's chain must not move"

@pytest.mark.asyncio
async def test_retry_after_abort_is_an_internal_error_where_a_second_abort_says_nothing(
    tmp_path: Path,
) -> None:
    """The asymmetry, inherited from `ports/integration.py` rather than reinvented here.

    An aborted integration is **settled**: the lease is back, the hold is released, and the parent's
    chain has been decided. `retry()` on one would have to act on a landing nothing is holding and
    take a lease this object no longer has, so it raises - the same answer the port gives for the
    same reason, that a two-case outcome has no honest spelling for "there was nothing to do".

    `abort()` meets that state on every ordinary path and says nothing, which is
    `Integrator.abort`'s own tolerance clause reaching the surface unchanged. Both are asserted
    against one outcome in one state, so the contrast is written down rather than inferred from two
    tests that sit near each other.

    **The refusal's wording is read here as well as on the raising path at the bottom of this
    file**, because widening it was the other half of that repair. `_nothing_to_retry`'s
    `head is None` branch used to say "it was aborted, and the hold was released", which was true
    while an abort was the only ending that could reach it. A verb that raises now settles too, and
    both halves of that sentence are false there. So one sentence has to be true of every ending
    that is not a landing, and this is the ending it was originally written for: it still has to
    fit here, or widening it traded one wrong message for another.
    """
    _, _, ticket = await _hold_the_target(tmp_path)
    outcome = await ticket.integrate()
    assert outcome.conflicted is True
    await outcome.abort()

    with pytest.raises(InternalError) as refused:
        await outcome.retry()

    assert "nothing landed" in str(refused.value), (
        f"the refusal does not say how this integration ended: {str(refused.value)!r}. What a "
        f"reader is owed is which of the two endings they are looking at, and the one thing every "
        f"ending other than a landing has in common is that nothing landed"
    )

    await outcome.abort()

@pytest.mark.asyncio
async def test_a_landed_outcome_is_settled_too_and_neither_verb_acts_on_it(tmp_path: Path) -> None:
    """A landing settles the outcome exactly as an abort does, and both verbs answer accordingly.

    `retry()` raises, for the reason above: there is nothing pending, the lease is back, and the
    chain has already been advanced. `abort()` does nothing at all - not "undoes the landing", which
    is the one genuine hazard `ports/integration.py` names for that verb and the reason it is
    tolerant: undoing a landing that *succeeded* is `Workspace.restore` at a different moment
    entirely, and a run that reached for `abort` to do it would silently destroy work.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    outcome = await ticket.integrate()
    assert outcome.conflicted is False
    settled = outcome.head

    with pytest.raises(InternalError):
        await outcome.retry()

    await outcome.abort()

    assert await _head(harness, None) == settled, "an abort undid a landing that had succeeded"
    assert (_target_dir(tmp_path) / FIRST).is_file(), "the landed work is gone after that abort"
    assert run._steps.last_good == settled

# --- the containment check: a retry may conclude somebody else's landing -------------------------

@pytest.mark.asyncio
async def test_a_retry_that_concludes_another_childs_landing_is_not_reported_as_this_ones(
    tmp_path: Path,
) -> None:
    """The recoverable state, followed all the way to where it can lie.

    The arrangement is the one a resume walks into: a process dies holding child A's conflict; the
    run that resumes walks the same workflow, reaches `integrate()` for child **B**, and offers B
    into a target that is still held. `land` answers a pre-existing hold with a `Conflict` -
    because "a resumed run must be able to find a hold it did not take" and exit 70 is forbidden -
    the person picks retry, and `Integrator.retry` concludes **A's** landing - because that is
    the landing the target is holding, and `retry` takes only the target.

    **Unchecked, that head becomes B's `last_good`.** The gate would run on a tree with none of B's
    work in it, the workflow would believe B landed, and B's branch would sit there unmerged with
    nothing anywhere disagreeing. So the framework asks `History.contains(source.head(),
    outcome.head)` after every landing, and lands again into the now-free target when the answer is
    no.

    What makes this test able to fail is the last assertion pair: the head handed back contains
    **both** children, which no single landing here could produce. An implementation that trusted
    `retry`'s answer returns a head containing A and not B, and every other assertion in this file
    still passes.

    The person resolving the collision is simulated by writing into the target's checkout, which is
    what `tests/contracts/_integration_targets.py` does for the same reason: the port offers no
    other vocabulary for "somebody fixed it", and a landing needs something to have been fixed.
    """
    harness = _harness(tmp_path)

    # The run that died. Its conflict is left live, and `release_all` is the only thing `api.run`
    # does on the way out - the adapter's hold is deliberately not aborted.
    first = await _tree(harness)
    a = first.worktree("T-01")
    await first.step(PREPARE, commit="prepare the parent")
    await a.step(COLLIDE, commit="implement T-01")
    held = await a.integrate()
    assert held.conflicted is True, "this test needs a target left holding a landing"
    first.leases.release_all()

    # The run that resumes: same ledger, same repository, same checkouts, everything the process
    # held rebuilt from nothing. Both children replay; the parent's `prepare` replays too, which is
    # why the held checkout is still dirty when the second walk reaches the integration.
    second = await _tree(harness)
    a_again = second.worktree("T-01")
    b = second.worktree("T-02")
    await second.step(PREPARE, commit="prepare the parent")
    await a_again.step(COLLIDE, commit="implement T-01")
    await b.step(IMPLEMENT_SECOND, commit="implement T-02")
    (_target_dir(tmp_path) / CONTESTED).write_bytes(RESOLVED)

    outcome = await b.integrate()
    assert outcome.conflicted is True, (
        "landing into a target that is already holding somebody else's landing was not reported as "
        "a conflict, which is the answer a resumed run needs and the whole premise here"
    )

    await outcome.retry()

    assert outcome.conflicted is False, (
        f"the retry did not land: {outcome.conflict}. The collision A was holding was resolved in "
        f"the target's checkout, so concluding it succeeds - and what follows a conclusion is the "
        f"same path a first landing takes"
    )
    assert outcome.head is not None
    history = harness.services.history
    assert await history.contains(await _head(harness, SIBLING), outcome.head), (
        f"the head this integration reports, {outcome.head!r}, does not contain T-02's work - and "
        f"T-02 is what was being integrated. `Integrator.retry` concluded the landing the *target* "
        f"was holding, which was T-01's, and that head was handed back to a call that asked about "
        f"T-02. Unchecked it becomes T-02's `last_good`, the gate runs on a tree with none of its "
        f"work in it, and the workflow believes it landed"
    )
    assert await history.contains(await _head(harness, TICKET), outcome.head), (
        "T-01's landing was concluded on the way through and then lost, so retrying it destroyed "
        "the resolution a person had just made"
    )
    assert second._steps.last_good == outcome.head
    assert (_target_dir(tmp_path) / SECOND).is_file()
    assert (_target_dir(tmp_path) / CONTESTED).read_bytes() == RESOLVED, (
        "what the person put in the target's checkout is not what the target holds - `retry` "
        "concludes what they staged, and this port has no other opinion about their work"
    )

# --- run exit: the lease goes back, and the hold deliberately does not ---------------------------

_LEFT_HOLDING: list[Run[object]] = []
"""Where the workflow below hands its `Run` tree back to the test that started it.

A module-level cell because a workflow function takes a `Run` and returns `None` - there is no
return value and no argument to smuggle one through, which is the shape chosen and not
something to work around. The one test that reads it clears it first.
"""

@workflow
async def walks_away(run: Run[NoParams]) -> None:
    """A workflow that hits a conflict and simply ends, which is the case run exit is for.

    Not a contrived one: a workflow showing a conflict screen, a workflow that raised
    while deciding, and a person who pressed Ctrl-C all reach `api.run`'s `finally` in exactly this
    state - a live `Integration` holding a lease and a namespace's step lock, reachable only from an
    object that is going away with the workflow.
    """
    ticket = run.worktree("T-01")
    await run.step(PREPARE, commit="prepare the parent")
    await ticket.step(COLLIDE, commit="implement T-01")
    outcome = await ticket.integrate()
    if not outcome.conflicted:  # pragma: no cover - the arrangement guarantees a collision
        raise AssertionError("this workflow exists to leave a conflict unresolved")
    _LEFT_HOLDING.extend((run, ticket))

def _point() -> EntryPoint:
    """The registration line, constructed rather than installed - `test_api.py`'s seam."""
    return EntryPoint(name="walks-away", value=f"{__name__}:walks_away", group=registry.GROUP)

@pytest.mark.asyncio
async def test_run_exit_gives_the_lease_back_and_leaves_the_adapters_hold_alone(
    tmp_path: Path,
) -> None:
    """The sweeper - "run exit is the sweeper, not the lifetime" - and only the lease.

    **The release is asserted by asking for it again.** A lease is not observable: `Leases` has no
    predicate, deliberately, because one would be answerable only in the instant between two
    `await`s. What is observable is that a second integration into the same target does not wait
    forever, and the bound below is what turns "does not wait forever" into a failing test. The
    second integration goes through the *same* `Leases` object `api.run` built, because `_child`
    hands it down the tree - so this is the run's own lease being re-taken and not a fresh table.

    **The hold is asserted by what is still in the checkout.** `Integrator.abort` puts the target's
    files back where `land` found them, so a run exit that aborted would leave `CONTESTED` holding
    the parent's own body again. It holds neither side's body, because a conflicted landing wrote
    both into it and nobody has decided - which is the durable hold required so that "a resumed
    run must be able to find a hold it did not take", and the reason aborting on the way out is
    `abort()`-before-land wearing a different hat: it would discard a partial resolution somebody
    may be in the middle of making.
    """
    _LEFT_HOLDING.clear()
    harness = _harness(tmp_path)
    points: Sequence[EntryPoint] = (_point(),)

    await api.run(harness.services, PROJECT, "walks-away", LABEL, (), points=points)

    assert len(_LEFT_HOLDING) == 2, "the workflow did not reach the end it was written for"
    _, ticket = _LEFT_HOLDING
    assert (_target_dir(tmp_path) / CONTESTED).read_bytes() not in (PARENT_BODY, CHILD_BODY), (
        "the target's checkout holds one side of the collision whole, so run exit released the "
        "adapter's hold as well as the lease. The hold is durable precisely so a later "
        "invocation can find one it did not take, and undoing it here discards whatever resolution "
        "a person had started"
    )

    again = await asyncio.wait_for(ticket.integrate(), timeout=_LIVENESS)

    assert again.conflicted is True, (
        "a second integration into a target still holding a landing was not reported as a conflict"
    )
    await again.abort()
    assert (_child_dir(tmp_path, "T-01") / CONTESTED).read_bytes() == CHILD_BODY, (
        "the child's own checkout changed under an integration, which lands what the source "
        "*recorded* and never touches the place it was recorded from"
    )

@pytest.mark.asyncio
async def test_resume_exit_gives_the_lease_back_the_way_run_exit_does(tmp_path: Path) -> None:
    """The test above, mirrored through `api.resume`. One claim, and there are two exits.

    `api.resume`'s last paragraph says it is "`run`'s last paragraph, line for line, and
    deliberately so: a resumed run is the same run", and the `finally: leases.release_all()` under
    it is a copy of the one this file already measures. A copy carrying a claim and no test is what
    drifts: deleting the clause from `run` fails the test above and deleting it from `resume` used
    to fail nothing at all, which made half of "run exit gives every live lease back" an unverified
    sentence in a docstring.

    **The arrangement is the same workflow twice**, which is what makes this a resume rather than a
    second run. The first invocation walks away holding a conflict, and the hold is durable - it
    is a fact about the repository and not about a `FakeIntegrator` - so the resumed walk replays
    both steps, reaches the same `integrate()` and is answered with a conflict by the target that is
    still holding the first one. It ends there, holding a lease taken by a `Leases` that only
    `api.resume` can release.

    **The release is asserted by asking for it again**, exactly as above and for the same reason: a
    lease is not observable, and a second integration into the same target either returns or waits
    forever. The ticket is the *resumed* run's, so the lease being re-taken is the one `api.resume`
    was holding rather than the first invocation's, which `api.run` gave back at its own exit and
    which is a different table. The bound turns "waits forever" into a failure and not a hung suite.
    """
    _LEFT_HOLDING.clear()
    harness = _harness(tmp_path)
    points: Sequence[EntryPoint] = (_point(),)

    await api.run(harness.services, PROJECT, "walks-away", LABEL, (), points=points)
    await api.resume(harness.services, PROJECT, LABEL, points=points)

    assert len(_LEFT_HOLDING) == 4, "the resumed workflow did not reach the end it was written for"
    _, ticket = _LEFT_HOLDING[2:]
    assert (_target_dir(tmp_path) / CONTESTED).read_bytes() not in (PARENT_BODY, CHILD_BODY), (
        "the target's checkout holds one side of the collision whole, so resume exit released the "
        "adapter's hold as well as the lease - and the hold is durable precisely so that "
        "this invocation could find one it did not take"
    )

    again = await asyncio.wait_for(ticket.integrate(), timeout=_LIVENESS)

    assert again.conflicted is True, (
        "a second integration into a target still holding a landing was not reported as a conflict"
    )

# --- the merge gate, and the revert that follows a red one ---------------------------------------

@pytest.mark.asyncio
async def test_a_landing_that_passes_the_gate_advances_the_chain(tmp_path: Path) -> None:
    """The green path, asserted where a reader would otherwise assume it.

    "**The framework runs exactly one build: the merge gate**, inside `integrate()`." A gate
    that passes changes nothing about what a landing does - it falls through to the advance, and the
    outcome is the ordinary landed one - which is a claim worth a test precisely because it is the
    shape every other landing in this file already relies on: the bundle's verifier passes an
    unscripted command, so a gate that got the sense of `passed` backwards would fail every test in
    this file at once and none of them would say why.

    The verdict is asserted too. It is not a thing the framework branches on when the build passed,
    and it is on the outcome anyway, because a person looking at what landed is entitled to the
    output of the build it was decided by.
    """
    harness = _harness(tmp_path)
    harness.verifier.answers(container.FAKE_BUILD, passed=True, status=0, output="42 passed")
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    landed = await _head(harness, TICKET)

    outcome = await ticket.integrate()

    assert outcome.conflicted is False, (
        f"a build the gate was told passes rejected a landing anyway: {outcome.conflict}"
    )
    assert outcome.head is not None
    assert await harness.services.history.contains(landed, outcome.head)
    assert run._steps.last_good == outcome.head, (
        f"the parent's chain is at {run._steps.last_good!r} and the gated landing produced "
        f"{outcome.head!r}. A green gate falls through to the advance and changes nothing about it"
    )
    assert (_target_dir(tmp_path) / FIRST).is_file()
    assert outcome.verdict is not None and outcome.verdict.passed is True, (
        "a landing that went through the gate reports no verdict, so the one build AGL runs "
        "left no trace on the outcome it decided"
    )
    assert outcome.verdict.output == "42 passed"

@pytest.mark.asyncio
async def test_a_failing_gate_reverts_the_landing_and_never_reaches_the_advance(
    tmp_path: Path,
) -> None:
    """The whole of what a red gate must do, in one arrangement, because each half is silent alone.

    The framework "runs the build gate and reverts on failure", and the reason
    that gate exists is concrete: it is "the only thing that catches semantic conflicts, where two
    items each work alone, merge without textual conflict, and the combination is broken". Every
    check before this point said yes - `land` found no collision and `History.contains` found the
    work in - so the only thing that can still reject this landing is the build, and the only way to
    reject it is to put the target back.

    Five claims, and none of them is implied by another:

      * the target is at the head it was read at inside the lease, not at the landing's;
      * the source's work is **not** in the target's line of work, asked of `History` - a revert
        that moved files and left the branch where the landing put it would pass the next
        assertion and not this one;
      * the target's working tree is clean, which is `restore` being `reset --hard` *and*
        `clean -fd` rather than a head move;
      * the parent's `last_good` did not move, which is the one that destroys work when it is
        wrong, and the reason the gate returns before the advance exists rather than around
        it;
      * the outcome is conflicted and carries the verdict, because a conflict screen that shows one
        sentence about a red build is a screen a person cannot act on.
    """
    harness = _harness(tmp_path)
    harness.verifier.answers(container.FAKE_BUILD, passed=False, status=2, output=RED)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await run.step(PREPARE, commit="prepare the parent")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    landed = await _head(harness, TICKET)
    before = await _head(harness, None)
    chain = run._steps.last_good

    outcome = await ticket.integrate()

    assert outcome.conflicted is True, (
        "the gate was scripted to fail and the landing stood anyway: the framework runs the "
        "build gate and reverts on failure, and a landing kept over a red build is the semantic "
        "conflict this gate is the only thing in AGL that can catch"
    )
    assert outcome.head is None, "the two-case outcome, and this is the case with no head in it"
    now = await _head(harness, None)
    assert now == before, (
        f"after a failed gate the target is at {now!r} rather than {before!r}, the head read "
        f"inside the lease before anything landed. That value is the revert target for exactly "
        f"this moment - the fourth use of `Workspace.restore` - and it is read before the "
        f"landing because afterwards it names the state that has to be undone"
    )
    assert not await harness.services.history.contains(landed, now), (
        f"the target's line of work is at {now!r} and still contains the child's {landed!r}, so "
        f"the revert put the tree back without putting the branch back. The criterion is that a "
        f"failing gate leaves the branch unmerged, and a branch that still holds the "
        f"rejected work is one the next landing builds on top of"
    )
    assert not (_target_dir(tmp_path) / FIRST).exists(), (
        "the child's file is still in the target's checkout after the gate rejected it. `restore` "
        "is `reset --hard` and `clean -fd` together, so a tree that keeps it means only the head "
        "moved - and the next step in the parent, and the next person to look, read the tree"
    )
    assert (_target_dir(tmp_path) / CONTESTED).read_bytes() == PARENT_BODY, (
        "the parent's own work is gone from its checkout, so the revert went back past the state "
        "the landing was offered against rather than to it"
    )
    assert run._steps.last_good == chain, (
        f"the parent's chain moved to {run._steps.last_good!r} over a landing that was undone. "
        f"Nothing landed, so there is nothing to advance to - and this is the one value "
        f"whose being wrong deletes work instead of costing a re-run"
    )
    assert outcome.conflict is not None
    assert outcome.conflict.paths == (), (
        f"the conflict names {outcome.conflict.paths} as the colliding files. The port protects "
        f"the empty spelling - `()` means 'I cannot tell you which' - and the framework genuinely "
        f"cannot say which files are semantically incompatible, because there is no such file"
    )
    assert container.FAKE_BUILD in outcome.conflict.summary, (
        f"the only line a person is guaranteed to get does not say which command failed: "
        f"{outcome.conflict.summary!r}"
    )
    assert outcome.verdict is not None, (
        "the conflicted outcome carries no verdict, so the build's own output never reached the "
        "workflow - and `Conflict` has nowhere to put it, which is why `Integration` has a field"
    )
    assert (outcome.verdict.passed, outcome.verdict.status, outcome.verdict.output) == (
        False,
        2,
        RED,
    ), "the verdict on the outcome is not the one the gate was answered with"

@pytest.mark.asyncio
async def test_the_gate_runs_the_configured_command_in_the_targets_own_checkout(
    tmp_path: Path,
) -> None:
    """`verify(services.build, target.path)`, and both arguments are a decision.

    **The command is the project's**, carried to this call site on `Services.build` because
    `Verifier.verify` takes it as a parameter and that method has one caller. So the bundle
    is built with a command that is deliberately not the default a test scripts against: an
    implementation that reached for a constant, or for the fake's unscripted answer, would agree
    with `FAKE_BUILD` and this would still pass if the two were the same string.

    **The directory is the target's**, which is the whole point of a merge gate: `_base` is where
    AGL's own integration branch is checked out, and therefore the only place the combined state
    exists. Building in the child's checkout would build the child alone, which is the thing the
    framework does not do and the agent already did; building in the user's repository would be AGL
    writing outside a `Workspace`, which is forbidden outright.

    The artifact is the same claim from the filesystem's side, and it is what makes the `Path`
    comparison worth having: a build that writes into the directory it was handed leaves the file in
    `_base`, so the two assertions would have to be wrong together.
    """
    harness = _harness(tmp_path, build=CONFIGURED)
    gate = _Recorded(passed=True, leaves=ARTIFACT)
    run = await _tree_gated_by(harness, gate)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")

    outcome = await ticket.integrate()

    assert outcome.conflicted is False, f"the landing did not reach the advance: {outcome.conflict}"
    assert gate.calls == [(CONFIGURED, _target_dir(tmp_path))], (
        f"the gate ran {gate.calls}, and the one call it owes is the project's own build command "
        f"in the target's own checkout. `Verifier.verify` has exactly one call site in "
        f"AGL and this is it, so a second call would be a second build the framework runs"
    )
    assert (_target_dir(tmp_path) / ARTIFACT).is_file(), (
        "what the build wrote into the directory it was pointed at is not in the target's "
        "checkout, so the working directory that reached the port is not the one named above"
    )

@pytest.mark.asyncio
async def test_a_failing_gate_takes_the_builds_leavings_away_with_the_landing(
    tmp_path: Path,
) -> None:
    """The second half of what a failing gate owes: the tree is left **clean**.

    A build tool writes into the tree it builds - a log, a cache directory, a coverage file - and a
    failed gate's revert is `Workspace.restore`, which is `reset --hard` **and** `clean -fd`. So the
    leavings go with the landing, and that is wanted rather than tolerated: `Integrator.land` is
    entitled to refuse a landing that would write over unrecorded work in the target's checkout, so
    a target left holding a rejected build's output is a target the *next* child cannot land into,
    for a reason that has nothing to do with either of them.

    Written with a verifier that actually writes something, because no assertion about a fake that
    starts no process can produce this: `FakeVerifier` leaves nothing behind, so against it every
    implementation of the revert looks identical.
    """
    harness = _harness(tmp_path)
    run = await _tree_gated_by(harness, _Recorded(passed=False, leaves=ARTIFACT))
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")

    outcome = await ticket.integrate()

    assert outcome.conflicted is True
    assert not (_target_dir(tmp_path) / ARTIFACT).exists(), (
        "the rejected build's own output is still in the target's checkout. The revert moved the "
        "head and stopped there, and `Workspace.restore` is one verb doing both halves precisely "
        "so that 'restored but not cleaned' is not a state a caller reaches by forgetting a line"
    )
    assert not (_target_dir(tmp_path) / FIRST).exists(), "the landing itself was not undone"
    assert (_target_dir(tmp_path) / SEEDED).read_bytes() == SEED, (
        "the user's own work is gone from the target's checkout, so the revert took away more than "
        "the landing and the build put together"
    )

@pytest.mark.asyncio
async def test_abort_after_a_failed_gate_settles_it_and_gives_the_lease_back(
    tmp_path: Path,
) -> None:
    """A red gate is a conflict, so it ends the way a conflict ends: with one of the two verbs.

    That is the design rather than an accident of the encoding. Both kinds of conflict hold the
    lease, hold nothing else, and are decided by `retry()` or `abort()` - which is what lets the
    conflict loop be written once, with one branch, by a workflow author who does not have to ask
    which kind of "would not combine" they are looking at.

    `abort()` here reaches an `Integrator.abort` with nothing pending, which is the tolerant case
    the port names in as many words: the landing succeeded and was undone by `restore`, so there
    is no hold to release. What it does do is **settle** - so `retry()` afterwards raises, a second
    `abort()` says nothing, and the lease goes back, which is asserted the only way a lease can be:
    by asking for it again and requiring the answer to arrive.
    """
    harness = _harness(tmp_path)
    harness.verifier.answers(container.FAKE_BUILD, passed=False)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    before = await _head(harness, None)
    chain = run._steps.last_good
    outcome = await ticket.integrate()
    assert outcome.conflicted is True

    await outcome.abort()

    assert await _head(harness, None) == before, (
        "the abort moved a target the gate had already put back"
    )
    assert run._steps.last_good == chain
    assert outcome.conflict is not None, (
        "the aborted outcome cleared its conflict, and giving up on a landing does not make the "
        "build have passed - it is the record of why nothing landed"
    )
    with pytest.raises(InternalError):
        await outcome.retry()
    await outcome.abort()

    again = await asyncio.wait_for(ticket.integrate(), timeout=_LIVENESS)

    assert again.conflicted is True, (
        "the second integration passed a gate that is still scripted red, so the outcome above did "
        "not settle the way it claimed to"
    )
    await again.abort()

@pytest.mark.asyncio
async def test_retry_after_a_failed_gate_lands_again_and_goes_through_the_gate_again(
    tmp_path: Path,
) -> None:
    """"Fix the build and press retry", which only works if a retry is gated.

    **This is the hole the whole deliverable exists to close.** A landing reached through `retry()`
    is the least framework-shaped landing there is: either a person resolved a collision by hand in
    the target's checkout, or a build was fixed and offered again. Either way it is a state nothing
    in AGL composed, and a `retry` that advanced the parent's chain without building would send
    exactly that state past the one check there is. There is one path and `_conclude` is it, so
    every landing - first, re-landed, or human-concluded - is checked for containment and then built
    before anything advances.

    Both directions are asserted against one outcome, because the interesting one is the first.
    Retried while the build is still red, the landing goes in again, the gate runs again, and the
    revert happens again: still conflicted, still nothing in the target, still nothing advanced. An
    implementation that gated only the first `land` would come back landed here, and every other
    assertion in this file would still pass.

    Then the build is fixed and the same button pressed again, which is the shape a workflow's
    conflict screen actually produces - `while outcome.conflicted` - and this time it lands.
    """
    harness = _harness(tmp_path)
    harness.verifier.answers(container.FAKE_BUILD, passed=False)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    landed = await _head(harness, TICKET)
    chain = run._steps.last_good
    outcome = await ticket.integrate()
    assert outcome.conflicted is True

    await outcome.retry()

    assert outcome.conflicted is True, (
        "a retry against a build that is still red came back landed, so the second landing never "
        "reached the gate. A retry is offered to a person who went and changed something, and what "
        "they changed is the one thing the framework has no way to inspect"
    )
    assert outcome.verdict is not None and outcome.verdict.passed is False
    assert not (_target_dir(tmp_path) / FIRST).exists(), "the second landing was not reverted"
    assert run._steps.last_good == chain

    harness.verifier.answers(container.FAKE_BUILD, passed=True, status=0, output="")

    await outcome.retry()

    assert outcome.conflicted is False, f"the fixed build did not land: {outcome.conflict}"
    assert outcome.head is not None
    assert await harness.services.history.contains(landed, outcome.head), (
        "the head this integration reports does not contain the child's work, so what landed on "
        "the retry was not what was being integrated"
    )
    assert run._steps.last_good == outcome.head
    assert (_target_dir(tmp_path) / FIRST).is_file()
    assert outcome.verdict is not None and outcome.verdict.passed is True, (
        "the outcome still carries the failing verdict from before the retry, so a workflow "
        "reading it would put a red build on the screen for a landing that went in"
    )

@pytest.mark.asyncio
async def test_a_retry_that_collides_leaves_no_trace_of_the_gate_that_refused_the_last_one(
    tmp_path: Path,
) -> None:
    """One outcome reaching a *second* terminal state, which no other test in this file produces.

    Every other conflict here follows an outcome to one ending and stops, so `_verdict` is already
    `None` when the conflicted branch of `_conclude` runs and clearing it is indistinguishable
    from not clearing it. The sequence below is the one where it is not:

      * the gate refuses the landing, so the field is set - the `VerifierOutcome` of the build that
        said no;
      * the person, looking at that screen, commits something of their own into the held target's
        checkout - which is a thing they are entitled to do and the framework has no way to hear of;
      * they press retry. The gate's revert left nothing pending, so `Integrator.retry` raises and
        `land` is offered again - and this time the two lines of work would not combine at all.

    **What the workflow is then holding decides which screen a person is sent to.** `Integration`'s
    own docstring makes `verdict` the discriminator between the two kinds of conflict - "`None`
    means the work would not combine, and set means it combined and then did not build" - so a
    verdict left standing beside somebody else's `Conflict` routes the conflict loop to a build-log
    screen for a collision with no build anywhere in it.

    The collision is arranged through the checkout rather than through a step in the parent,
    deliberately: the live outcome is holding that namespace's step lock, so `run.step(...)` here
    would queue behind a conflict nobody has decided yet, and this test would hang rather than
    fail.
    """
    harness = _harness(tmp_path)
    harness.verifier.answers(container.FAKE_BUILD, passed=False, status=2, output=RED)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(COLLIDE, commit="implement T-01")

    outcome = await ticket.integrate()

    assert outcome.conflicted is True, (
        f"the gate was scripted red and the landing stood anyway: {outcome.head!r}"
    )
    assert outcome.verdict is not None and outcome.verdict.passed is False, (
        "the red gate left no verdict on the outcome, so the field this test is about was never "
        "standing and the clearing below would be asserted against nothing"
    )

    # What a person does while the conflict screen is up, in the only vocabulary this port has for
    # it. `PARENT_BODY` into a file the child also created, from a base holding neither, is the one
    # shape no honest implementation can combine - so the retry below re-lands into a collision.
    target = await harness.services.workspaces.open(LABEL, None, await _base(harness))
    collision = _target_dir(tmp_path) / CONTESTED
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_bytes(PARENT_BODY)
    await target.commit_all("what a person committed while the conflict screen was up")

    await outcome.retry()

    assert outcome.conflicted is True, (
        f"the retry landed {outcome.head!r} into a target that had grown a collision under it, so "
        f"the arrangement this test is about never happened"
    )
    assert outcome.verdict is None, (
        f"a textual collision came back carrying {outcome.verdict}, which is the build output of "
        f"the landing before this one. `Integration.verdict` is what a workflow reads to tell 'the "
        f"work would not combine' from 'it combined and then did not build', so this sends the "
        f"person to a build-log screen for a conflict with no build in it"
    )
    assert outcome.conflict is not None and outcome.conflict.summary, (
        "the new conflict says nothing, and `summary` is the only part of a `Conflict` guaranteed "
        "to"
    )
    assert outcome.head is None, "the two-case outcome, and this is the case with no head in it"

@pytest.mark.asyncio
async def test_refused_by_the_gate_is_true_for_a_red_build_and_false_for_a_textual_collision(
    tmp_path: Path,
) -> None:
    """The discriminator with a name on it: `conflicted` is one shape, and this is which cause.

    **Two causes, one shape, deliberately.** A landing comes back conflicted either because the
    work would not combine - `Integrator.land` found a textual collision and the target is holding
    it - or because it combined cleanly and the build gate then refused it, at which point `_gated`
    reverts with `restore(self._before)` and fabricates a `Conflict` of its own. The collapsing is
    the design rather than an accident of the encoding: both hold the lease, hold nothing else, and
    are ended by `retry()` or `abort()`, which is what lets the conflict loop be written once, with
    one branch, by an author who does not have to ask which kind of "would not combine" this is.

    **`verdict` is what tells them apart**, and this predicate is that reading given a name.
    `_gated` sets the field on every refusal and `_conclude` clears it on every textual conflict,
    so a live conflict carrying a verdict is the gate's and one carrying none is the integrator's.
    The distinction earns a name because the two screens are different things: a list of files
    somebody has to open, against a build log with no file in it anywhere.

    **`paths == ()` is not the test.** It is true of every gate refusal - there is no such thing as
    a semantically colliding file to name, which is why `_gate_refused` says so in its summary - but
    it is not true of gate refusals *only*. `adapters/git/_conflicts.py` emits an empty tuple for a
    genuine textual collision whenever git names no unmerged file, and the port's own suite in
    `tests/ports/test_integration.py` pins that spelling as legal in as many words: a far side that
    can only answer "these cannot be combined cleanly" is a real implementation. So a workflow
    branching on the emptiness sends a person to a build log for a collision that has no build
    anywhere in it, which is exactly the routing mistake the field exists to prevent.

    **A second `IntegrationOutcome` case would be the other way to say this, and it is worse.** The
    refusal is fabricated here, in the engine, after a landing the `Integrator` already reported as
    clean - so a third case on that type would be a value no adapter can ever return, owed by every
    implementation of the port and produced by none of them.

    Two arrangements rather than one, because a claim about two causes asserted against a single one
    of them says only that the predicate is a constant. Each is its cause in the plainest form: a
    parent and a child that both create `CONTESTED` from a base holding neither, and a child that
    touches nothing anybody else touched, offered into a gate scripted red. Two bundles under one
    `tmp_path`, because each ends holding a live conflict of its own - which is the state the two
    causes are indistinguishable in, and the whole reason the question is asked.
    """
    _, _, colliding = await _hold_the_target(tmp_path / "collision")
    collision = await colliding.integrate()

    refusing = _harness(tmp_path / "gated")
    refusing.verifier.answers(container.FAKE_BUILD, passed=False, status=2, output=RED)
    run = await _tree(refusing)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    refused = await ticket.integrate()

    assert (collision.conflicted, refused.conflicted) == (True, True), (
        f"the two arrangements did not both come back conflicted: {collision.conflict!r} and "
        f"{refused.conflict!r}. There is nothing to tell apart until both causes wear one shape, "
        f"and that shape is the thing this predicate is written beside"
    )
    assert collision.verdict is None, (
        f"the textual collision carries the verdict {collision.verdict}, and no build ran: `land` "
        f"refused to combine the two lines of work, so the gate was never reached"
    )
    assert collision.refused_by_the_gate is False, (
        "a collision the integrator reported reads as the build gate's refusal, so a workflow is "
        "sent to a build-log screen for a conflict with no build in it. The predicate is `verdict "
        "is not None` and nothing else - not the emptiness of `paths`, which a textual collision "
        "is entitled to and `adapters/git/_conflicts.py` produces when git names no unmerged file"
    )
    assert refused.verdict is not None and refused.verdict.passed is False, (
        "the gate refused this landing and left no failing verdict on it, so the field the "
        "discriminator reads was never set and what follows would be asserted against nothing"
    )
    assert refused.refused_by_the_gate is True, (
        "the build gate's own refusal does not say it is one. The landing combined cleanly and was "
        "undone by `_gated`, so the only thing separating it from a textual collision is the "
        "verdict standing beside the fabricated `Conflict` - and a workflow that cannot read that "
        "has one shape, two causes and no way to tell which screen a person is owed"
    )

# --- a verb that raises: every path out of a hold has to settle it -------------------------------

class _RaisesGivingUp(Integrator):
    """The bundle's own integrator with one verb replaced by a failure it is entitled to have.

    `land` and `retry` are delegated, so the conflict the test below holds is a real one held in the
    real repository and everything up to the abort is the ordinary path. Only `abort` raises.

    It has to be substituted rather than provoked, unlike the raise the retry test above produces
    with nothing but a file: `FakeIntegrator.abort` reads the hold it took and puts the tree back,
    and there is no state a test can arrange from outside that stops it. The real adapter can fail
    there for a dozen reasons this suite has no vocabulary for - a lock file `git merge --abort`
    meets, a checkout somebody deleted underneath the run - and what `Integrator.abort` promises is
    tolerance of a *missing hold*, never that the call cannot raise.
    """

    def __init__(self, real: Integrator) -> None:
        self._real = real

    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        return await self._real.land(source, target)

    async def retry(self, target: Workspace) -> IntegrationOutcome:
        return await self._real.retry(target)

    async def abort(self, target: Workspace) -> None:
        raise UpstreamUnexpected(BROKE)

@pytest.mark.asyncio
async def test_a_retry_whose_landing_raises_settles_it_and_gives_the_targets_lease_back(
    tmp_path: Path,
) -> None:
    """A raise out of `retry()` must not strand the target's lease - and it must settle the outcome.

    **The scenario is the most ordinary thing a person does at a refusal screen.** The gate said no,
    so they open the target's checkout, put the file the build wanted back by hand, and press retry
    without committing it. `Integrator.retry` has nothing pending - the gate's revert left no hold -
    so the framework offers `land` again, and `land` refuses outright rather than conflicting:
    landing would write over work in the target that nothing has recorded, which is a refusal the
    adapter owes and `FakeIntegrator._refuse_to_overwrite` produces for the same reason git does. So
    this raise is arranged with one `write_bytes` and no substituted port anywhere.

    **What that raise costs is not the exception.** A workflow sees an `UpstreamUnexpected` and can
    say so; what nothing sees is that `retry()` returned through neither of the two paths that give
    the lease back, so the target stays leased. `integrate()`'s own `except BaseException:
    lease.release(); raise` does not cover this - the object it protects was already handed to the
    workflow - and `api.run`'s `finally: leases.release_all()` does not run until the workflow ends.
    Every later landing into that parent, and every later step in that namespace, then waits on
    `Leases.claim` for the life of the process. **A hang, not a failure**, which is why the second
    landing below is bounded and asserted rather than awaited: against the defect this test has to
    fail inside `_LIVENESS`, not sit there until `pytest-timeout` names the wrong thing.

    **`abort()` is the same defect one method over**, and its test is the next one down. One method
    is not the shape of the bug: the shape is "a verb a workflow calls on a live conflict returned
    without settling", and there are exactly two such verbs.

    **The outcome settles rather than merely releasing.** That is a decision and it is the one thing
    here a reader could reasonably want argued, because `integrate()` picks the other answer -
    release the lease, re-raise, leave nothing settled. It picks it correctly: the exception
    propagates *before* any `Integration` reaches the workflow, so there is no object left holding a
    landing and nothing that could be retried. Here the workflow **is** holding the object, and the
    two answers differ in what its next call does:

      * released but unsettled, the guard at the top of `retry()` lets a second call through, and
        that call acts on a landing nothing is holding - the lease is gone, so that namespace's
        step lock is gone with it. Should it succeed, `_conclude` calls `_journal.advance(head)`
        having given the step lock back, so a step in the parent may be running against the very
        checkout the landing is writing. That is precisely what the lease is for, and it is the
        state `_nothing_to_retry` exists to refuse;
      * settled, the second call raises `_nothing_to_retry` and the chain cannot be corrupted. A
        second `abort()` stays tolerant and says nothing, which is the asymmetry the port already
        pins for its own two verbs.

    **Settling made the refusal's own wording false, so the fix had to reach it.**
    `_nothing_to_retry` reads its `head is None` branch as one sentence, and that sentence used to
    be "it was aborted, and the hold was released" - true while an abort was the only ending that
    could arrive there, and false on both counts here: nothing was aborted, and the target may still
    be holding the landing the raise interrupted. The branch was widened to say what is true of
    **every** ending that is not a landing rather than to name which one it was. A third state on
    `Integration` would be a field carried for the sole purpose of wording one message, and it could
    not be honest even so: a raise out of `Integrator.abort` may have half-finished, so whether the
    hold is still there is not a thing this object can ask. What the message may claim is therefore
    the hedge, and the assertions below read it rather than settling for the exception's class.

    So the assertions are four, in the order that matters: the raise reaches the caller, the target
    is claimable again inside the bound, the settled object refuses a second retry while tolerating
    a second abort, and that refusal says how this ended without promising a hold went back.
    `Lease.release` is idempotent behind its `_released` flag, so nothing here risks the
    `RuntimeError` a doubly-released `asyncio.Lock` raises.
    """
    harness = _harness(tmp_path)
    harness.verifier.answers(container.FAKE_BUILD, passed=False, status=2, output=RED)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    chain = run._steps.last_good
    outcome = await ticket.integrate()

    assert outcome.refused_by_the_gate is True, (
        f"this test needs a live conflict the gate refused - that is the screen a person presses "
        f"retry at - and the landing came back as {outcome.conflict!r}"
    )

    # The person's fix, typed into the target's checkout, uncommitted. `FIRST` because a landing
    # only refuses over a file it would itself write, and that is the one file this child writes.
    hand = _target_dir(tmp_path) / FIRST
    hand.parent.mkdir(parents=True, exist_ok=True)
    hand.write_bytes(HAND_EDITED)

    with pytest.raises(UpstreamUnexpected):
        await outcome.retry()

    # The person takes their uncommitted fix away again, so that what the next landing meets is the
    # lease and nothing else. Without this the second `land` would refuse for the first one's reason
    # and the bound below would be measuring the refusal rather than the hold.
    hand.unlink()
    landing = asyncio.create_task(ticket.integrate())
    arrived, waiting = await asyncio.wait({landing}, timeout=_LIVENESS)
    for stalled in waiting:
        stalled.cancel()

    assert arrived, (
        f"a landing offered into the target after a `retry()` that raised did not finish within "
        f"{_LIVENESS} seconds, so that retry kept the target's lease. Nothing will give it back: "
        f"`integrate()`'s own `except BaseException` guards the call that builds an `Integration` "
        f"and not the verbs a workflow calls on one, and `api.run`'s `finally` does not run until "
        f"the workflow is over. Every later landing into this parent and every later step in this "
        f"namespace waits for the life of the process, with nothing raised and no predicate to ask"
    )
    again = landing.result()
    assert again.conflicted is True, (
        f"the second landing passed a gate that is still scripted red: {again.head!r}. It is meant "
        f"to reach the gate and be refused by it, which is what shows the lease came back to a "
        f"target still in the state the first refusal left it in"
    )
    assert run._steps.last_good == chain, (
        f"the parent's chain moved to {run._steps.last_good!r} over a retry that raised and a "
        f"landing the gate then refused. Nothing landed, so there is nothing to advance to"
    )

    with pytest.raises(InternalError) as refused:
        await outcome.retry()

    said = str(refused.value)
    assert "nothing landed" in said, (
        f"the refusal does not say how this integration ended: {said!r}. It settled over a raise "
        f"and not over a landing, and a reader told only that it is over cannot tell which of the "
        f"two endings they are looking at"
    )
    assert "may still be there" in said, (
        f"the refusal tells the reader what the target is holding: {said!r}. Nothing here knows "
        f"that. This outcome settled because a verb raised, so any hold the target took is exactly "
        f"the thing nobody released - and a raise out of `Integrator.abort` can half-finish, which "
        f"is why the sentence hedges instead of naming an ending it cannot check"
    )

    await outcome.abort()
    await again.abort()

@pytest.mark.asyncio
async def test_a_workflow_that_catches_the_raise_and_loops_again_is_not_refused_its_own_loop(
    tmp_path: Path,
) -> None:
    """`while outcome.conflicted:` has to terminate for every ending, including the raising one.

    **This is the conflict loop, written the way `workflows/split/` writes it**, around the raise
    the test above provokes. A workflow is entitled to catch what `retry()` raised - the exception
    is the adapter's own vocabulary reaching a workflow, and `ports/verifier.py` is emphatic that
    the ordinary refusals are outcomes rather than exceptions, so the ones that do raise are the
    unusual far-side failures a run may reasonably decide to show and carry on from. Carrying on
    means going back to the top of the loop it is already inside.

    **The defect was that the loop had no way out.** `retry()` settles on the way out of a raise -
    which is the fix one test up, and the right one - and `_settle()` deliberately leaves
    `self._conflict` standing, because the conflict is the record of why nothing landed and
    `test_abort_after_a_failed_gate_settles_it_and_gives_the_lease_back` requires it to survive.
    With `conflicted` reading nothing but that field, a settled outcome still answered *yes*: the
    loop re-entered, `retry()` met its own `if self._settled` guard, and the workflow was handed an
    `InternalError` - exit 70, *file a bug* - for doing exactly what the object's own public
    predicate had just invited it to do. The `InternalError` is not caught by the `except` below,
    because a workflow catching a raise out of `retry()` catches what the *port* raises and has no
    reason to expect the framework's own refusal, so it escapes this loop and fails this test.

    **So `conflicted` is now the live question and not the record.** It reads "there is a conflict
    here and this integration has not settled", which makes it the one predicate a loop can be
    written against: every path out of a hold settles it - `ARCHITECTURE.md` states that as an
    invariant - so every path out of a hold now ends the loop. The alternative fix, clearing
    `_conflict` inside `_settle`, was rejected rather than overlooked: two tests require that field
    to outlive the settling, in this file and in `tests/sdk/test_terminal_priorities.py`, and both
    argue the same thing - giving up on a landing is not the collision not having happened.

    **`refused_by_the_gate` follows `conflicted` rather than the record**, which is the one
    judgement call here. It is the discriminator over a shape - `ARCHITECTURE.md` calls
    `conflicted` "one shape over two causes" and this predicate "what tells the two apart" - so a
    true answer from it asserts the shape is present. A settled outcome answering "not conflicted"
    and "refused by the gate" at once is the same class of contradiction this test exists to
    remove. The record itself is still readable: `conflict` and `verdict` are both still there,
    and asserted below.

    The three assertions after the loop are what the loop terminating is worth: the outcome is over,
    the record of why is intact, and the two verbs answer the way `ports/integration.py` says a
    settled pair answers - `retry()` refuses, `abort()` says nothing.
    """
    harness = _harness(tmp_path)
    harness.verifier.answers(container.FAKE_BUILD, passed=False, status=2, output=RED)
    run = await _tree(harness)
    ticket = run.worktree("T-01")
    await ticket.step(IMPLEMENT_FIRST, commit="implement T-01")
    outcome = await ticket.integrate()

    assert outcome.refused_by_the_gate is True, (
        f"this test needs the live conflict a person presses retry at, and the landing came back "
        f"as {outcome.conflict!r}"
    )

    # The person's fix, typed into the target's checkout and not committed, exactly as one test up:
    # `land` refuses over unrecorded work it would itself write, so the retry below raises rather
    # than conflicting. Left in place, because this loop never gets a second chance to land.
    hand = _target_dir(tmp_path) / FIRST
    hand.parent.mkdir(parents=True, exist_ok=True)
    hand.write_bytes(HAND_EDITED)

    # The loop `workflows/split/` ships, with the one line a workflow is entitled to add. Bounded
    # twice: the count fails a loop that never terminates, and the deadline fails one that stops
    # making progress instead of spinning.
    screens = 0
    async with asyncio.timeout(_LIVENESS):
        while outcome.conflicted:
            screens += 1
            assert screens <= _PATIENCE, (
                f"the conflict screen went up {screens} times over one integration that has "
                f"already settled. `while outcome.conflicted:` is the loop every workflow writes "
                f"around this object, and a predicate that stays true after the last verb has run "
                f"is a loop with no exit in it"
            )
            try:
                await outcome.retry()
            except UpstreamUnexpected:
                continue

    assert screens == 1, (
        f"the conflict screen went up {screens} times. There was one conflict and one decision "
        f"about it; the retry raised, which settled the integration, and a settled integration is "
        f"not something to show a person a second screen about"
    )
    assert outcome.head is None, "nothing landed, so there is no head to report"
    assert outcome.conflict is not None, (
        "the settled outcome cleared its conflict. `conflicted` going false is this integration "
        "being over, not the collision not having happened - the `Conflict` is the record of why "
        "nothing landed and a workflow is entitled to read it after the loop"
    )
    assert outcome.verdict is not None and outcome.verdict.passed is False, (
        "the settled outcome cleared the build's verdict too, so the record of why nothing landed "
        "is missing the half that says which of the two causes it was"
    )
    assert outcome.refused_by_the_gate is False, (
        "a settled outcome says the build gate refused it while saying it is not conflicted. The "
        "predicate tells two causes of one shape apart, so answering it at all asserts the shape "
        "is there - and a pair that can contradict is the defect this test is about, one property "
        "over"
    )

    with pytest.raises(InternalError):
        await outcome.retry()
    await outcome.abort()

@pytest.mark.asyncio
async def test_an_abort_whose_integrator_raises_settles_it_and_gives_the_targets_lease_back(
    tmp_path: Path,
) -> None:
    """The same defect one method over, in the verb that is supposed to be the way out.

    `abort()` is what a workflow calls when a person gives up on a conflict, and it is the only
    thing between a live hold and a target nobody can land into. So a raise from
    `Integrator.abort` reaching it is the worst version of the previous test: the call whose whole
    purpose is to end the integration is the call that leaves it holding the lease forever. There is
    no third verb to reach for afterwards.

    The reasoning about **settling** rather than merely releasing is argued in full one test up and
    is not repeated; what it buys here is the tolerance clause staying true. `Integrator.abort` says
    nothing on a second call, and `Integration.abort` returns early on a settled outcome - so an
    outcome that settled on the way out of a failed abort answers a second `abort()` with silence
    rather than with the same exception again, which is what a `finally` cleaning up after a
    workflow needs. Unsettled, the second call would go back to the port and raise again, over
    whatever the workflow was already failing with.

    The raise is substituted rather than provoked, for `_RaisesGivingUp`'s stated reason. Everything
    else in the arrangement is real: a parent and a child that both create `CONTESTED` from a base
    holding neither, which is the one shape no honest implementation combines, so the target is
    genuinely holding a landing when the abort is called and is still holding it afterwards.
    """
    harness = _harness(tmp_path)
    run = await _tree_integrated_by(harness, _RaisesGivingUp(harness.services.integrator))
    ticket = run.worktree("T-01")
    await run.step(PREPARE, commit="prepare the parent")
    await ticket.step(COLLIDE, commit="implement T-01")
    chain = run._steps.last_good
    outcome = await ticket.integrate()

    assert outcome.conflicted is True, (
        "this test needs a target left holding a landing, and the two lines of work that both "
        "created one file were combined anyway"
    )

    with pytest.raises(UpstreamUnexpected):
        await outcome.abort()

    landing = asyncio.create_task(ticket.integrate())
    arrived, waiting = await asyncio.wait({landing}, timeout=_LIVENESS)
    for stalled in waiting:
        stalled.cancel()

    assert arrived, (
        f"a landing offered into the target after an `abort()` that raised did not finish within "
        f"{_LIVENESS} seconds, so giving up on the conflict kept the target's lease. This is the "
        f"worse half of the pair: `abort()` is the verb a workflow reaches for to end an "
        f"integration it cannot finish, so there is nothing left to call, and the parent is leased "
        f"for the life of the process with nothing raised"
    )
    again = landing.result()
    assert again.conflicted is True, (
        f"the second landing into a target still holding the first came back at {again.head!r}. "
        f"The abort raised, so nothing was given up: the hold is durable and the next `land` must "
        f"meet it"
    )
    assert run._steps.last_good == chain, (
        f"the parent's chain moved to {run._steps.last_good!r} over two landings that both "
        f"conflicted, and a conflict advances nothing"
    )

    await outcome.abort()

    with pytest.raises(InternalError):
        await outcome.retry()
