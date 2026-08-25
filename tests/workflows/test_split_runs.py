"""`split` as a run: N children at once, a merge train, and the one screen it asks a person for.

18.3, and the second half of `tests/workflows/test_split.py` - the half that needs a run to exist
before it can be seen at all. The line between the two files is that file's own: a view is a pure
function and reading one is a call and a comparison, so the screens stay cheap and stay there; the
concurrency, the child worktrees, the integration queue, the build gate and the conflict path are
arguments to calls, and nothing imports an argument.

`fix` already proved routing, both preflight checks and restriction translation on this harness.
What is new here is everything `fix` never touches, and every one of these has been proved one
layer down against hand-built `Run`s in `tests/sdk/` and never through a workflow an author could
have written:

  * **children that genuinely overlap**, not two coroutines a `gather` collected;
  * **landings serialized into one target**, which is §3.4's merge train;
  * **the conflict path**, driven through `views.conflict` by a scripted gesture - which no test in
    this repository has ever reached from a workflow;
  * **the red gate**, and what it leaves behind.

## The rendezvous, and the mirror of it

`tests/sdk/test_concurrent_namespaces.py` makes the argument this file inherits whole: a test that
starts two children and afterwards finds two entries proves nothing, because a framework that ran
them strictly in order leaves exactly that ledger. The only arrangement that can tell the two apart
is one where **neither child can finish until the other has started** - a barrier reached from
inside each agent. Under the design it is passed at once; under any lock spanning namespaces the
second child never arrives, the first waits forever, and the test hangs.

The serialization claim is that same instrument used the other way up, and it has to be, because
"one at a time" is a negative: two landings whose **gates** rendezvous would prove they overlapped,
and the design says they cannot, so the barrier must expire. The gate is the one hook a workflow's
test has *inside* a landing, which is what makes it the instrument here rather than a decoration.

**Nothing here sleeps against a scheduler.** A rendezvous two coroutines can reach is reached in
microseconds whatever the machine is doing, and one they cannot reach is not reached in an hour. The
bounds below only decide how long a broken build takes to say so, and - in the two tests that prove
a negative - how long a passing one spends proving it.

**Every await is bounded and the expiry is the failure.** §3.7 has no timeouts anywhere and
`answering` idles when its script runs out, so an honest mistake in any of these tests is a hang
rather than a failure. Nothing below is awaited outside a bound.

## Two findings this file reported at 18.3, both closed at 19.2, and what closing them changed here

**`testing.Agent` was synchronous - `(AgentTask) -> Reply` - so an agent written in the harness's
own vocabulary could not take part in a rendezvous.** It could not await a barrier, an event or
anything else, and a threading primitive on one event loop is a deadlock rather than a wait. That
ruled out the one arrangement that distinguishes real concurrency from a framework that serialized
everything - which is precisely the property `split` exists to demonstrate - so every test here that
needs two agents to meet was written on a raw per-provider `Script` through
`container.fakes(claude=...)`, and the door an author actually uses could not express the claim its
workflow is for. 19.2 widened the return to `Reply | Awaitable[Reply]`, so `_agent` below is an
`async def` that awaits a barrier and every one of those tests goes through `agent=`. The
synchronous spelling is untouched: `testing.Agent` still admits a one-line lambda, which is what
`sdk/testing.py` argues the type is for.

**One test still uses the escape hatch, and it is the honest one.** `_correcting` reads what came
back from a tool call it made, which no `Reply` can carry and which awaiting an agent does not
change - an `async def` agent has returned before `_performs` makes the first call, so it has
nothing to read. That is the second face of the same finding and it is *not* closed: what would
close it is an agent handed the conversation rather than the task, which is the `Script` this file
uses for exactly that arrangement and nothing else.

**`FakeServices` had `with_terminal` and `with_store` and no `with_verifier`.** The gate is the only
hook inside a landing, and reaching it was `dataclasses.replace(fakes, services=replace(fakes
.services, verifier=...))` in `_over` below - which left `fakes.verifier` naming an object the
bundle no longer used, the two-views-of-one-bundle defect `with_terminal`'s own docstring exists to
close, reproduced by hand at the one call site that wanted it. 19.2 added the third verb and `_over`
calls it. Its argument is a `FakeVerifier` rather than a `Verifier`, so the two gates below extend
the fake instead of replacing it - which costs them nothing and leaves them scriptable, `super()
.verify` being the verdict.

**What that costs, recorded rather than paid**: naming `FakeVerifier` means importing it from
`agl.adapters.shell.fake`, and no door re-exports it. `agl.testing` re-exports `Press` and
`ScriptedTerminal` from the composition root for exactly this reason - a workflow author's test
needs to *name* the fake it is substituting - and a third such name would be the same repair a
third time. This file already reaches into `agl.adapters.claude_code.fake` for `Script`, which is
what `container.fakes(claude=...)` takes and is deliberate; `FakeVerifier` is a second reach and a
narrower one, and it is reported here rather than fixed in a deliverable that owns `agl.sdk`'s door
and not this one's.

## What is not observable from here, said rather than worked around

§3.4 holds the target namespace's **step lock** behind the lease, so a parent's own `run.step`
queues behind every child's gate. That is real and it is unobservable from any test of *this*
workflow: `split` takes exactly one step on the root, `plan`, and it happens before the first
worktree is opened, so no landing is ever in flight while the root wants to step. Seeing it would
need a workflow that steps after its children, and the only way into this harness is
`harness.run(workflow, ...)` - so it would need a second workflow, which is a different
deliverable's subject. `tests/sdk/test_run_integrate.py`'s
`test_a_landing_waits_for_a_step_already_running_in_the_target_namespace` is where that claim
lives, one layer down, and it is not restated here.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Final, Self, cast

import pytest

from agl import testing
from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.shell.fake import FakeVerifier
from agl.config import container
from agl.ports.agent import AgentOutcome
from agl.ports.run import JsonValue
from agl.ports.tree_layout import TreesRoot
from agl.sdk import Row, Rows, Screen, Terminal, ToolResult, VerifierOutcome
from agl.testing import AgentTask, StopReason
from agl.workflows.split import split
from agl.workflows.split.chunks import report_chunks

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

REQUEST: Final = "split the importer into three pieces"
"""What an operator asked for. It reaches the planner as a step input and nothing else reads it."""

SEED: Final = {"src/a.py": b"the user's own work\n"}
"""What the repository holds when a run starts: the state `agl/test` is cut from, and the state a
reverted landing has to leave behind. One file, whose content nothing below reads - what it is for
is that "the child added a file" and "the checkout was replaced" are different observations."""

PARSER: Final = "parser"
API: Final = "api"
DOCS: Final = "docs"
PLAN: Final = (PARSER, API, DOCS)
"""A plan, in the order a planner reported it, which is deliberately not alphabetical.

The same three ids `test_split.py` builds its board out of, for the same reason: they are what the
framework files a worktree, a branch and a ledger under, so a ledger read back in this order is a
ledger that kept the planner's own."""

PLANNING: Final = "plan"
"""What a planning dispatch is called in `_Dispatches`, where every other entry is a chunk id.

Deliberately the step's own name and not an id, because `ids.py` would refuse it as a namespace -
so it can never collide with a chunk of any plan this file reports."""

CONTESTED: Final = "src/parse.py"
"""The file two chunks of the conflict arrangement both create, from a base holding neither.

The one shape no honest integrator can combine - `tests/sdk/test_run_integrate.py` causes a conflict
exactly this way and `tests/contracts/_integration_targets.py` argues why a suite has to cause one
rather than declare it. Here it is also the plan that a planner drew wrong, which is the only way
two chunks of a `split` run ever collide: `Chunk.files` is a boundary and not a contract."""

SEPARATE: Final[Mapping[str, tuple[str, bytes]]] = {
    chunk: (f"src/{chunk}.py", f"the {chunk} chunk's own work\n".encode()) for chunk in PLAN
}
"""What each chunk's agent writes when the plan is a good one: one file each, nobody's shared.

**The agents below really do write these**, which is `agl/testing.py`'s single biggest documented
trap: no field on a `Reply` and nothing an `AgentOutcome` carries touches the worktree, and
`commit_all` is a no-op on a clean tree - so agents that only report leave N empty branches, every
`commit=` becomes indistinguishable from every other and from none at all, and there is nothing for
a landing to be about. `task.workspace` is an absolute `Path` to this step's checkout."""

COLLIDING: Final[Mapping[str, tuple[str, bytes]]] = {
    PARSER: (CONTESTED, b"what the parser chunk made of it\n"),
    API: (CONTESTED, b"what the api chunk made of it\n"),
    DOCS: SEPARATE[DOCS],
}
"""The plan drawn wrong: two chunks over one file, and one that was independent all along.

`docs` is not decoration. It is the sibling whose landing has to wait behind somebody else's
undecided conflict and then go in, and without it "the lease is held across the decision" has
nothing to be held against."""

_LIVENESS: Final = 30.0
"""How long a run that should not be waiting on anything is given before this file calls it a
deadlock. **Never spent on a green run** - every rendezvous below that can be reached is reached in
microseconds - so all it trades away is how long a broken build takes to say so. Generous, because
a bound tight enough to fire on a loaded machine would report a flake as a deadlock, which is the
one failure here that has to mean exactly what it says."""

_SERIALIZED: Final = 1.0
"""How long the two tests that prove a negative wait before concluding that something really is
queued. **Spent on every green run**, because the wait is the proof. Short, because what it has to
outlast is a handful of dispatches against in-memory fakes - no process, no git, no network - and
long, because a bound that fired before a queued landing could reach its first `await` would pass
against exactly the implementation it is written to catch."""


# --- the plan, and the agents that carry it out --------------------------------------------------


def _payload(work: Mapping[str, tuple[str, bytes]]) -> dict[str, JsonValue]:
    """`work` as the call the planner makes: the JSON a model sends, not a `Chunks`.

    `sdk/tools.py` derives the schema from the payload type precisely so the model is shown the
    shape, and a call carrying an already-built `Chunks` would be testing a conversion no session
    performs. `files` is the planner's own boundary and is reported honestly here even in the
    arrangement where it is drawn wrong - two chunks naming one file is a plan the tool accepts and
    a merge train stops on, which is the whole of the conflict path below.
    """
    items: list[JsonValue] = [
        {"id": chunk, "work": f"do the {chunk} part", "files": [path]}
        for chunk, (path, _body) in work.items()
    ]
    return {"items": items}


@dataclass(frozen=True, slots=True)
class _Dispatches:
    """Which chunk's agent was dispatched, which of them got through, and where each one worked.

    `entered` is what a barrier's failure message is written out of, `left` separates an agent that
    was paid for from one that was dispatched and torn down when a bound expired, and `where` is the
    checkout the framework handed each chunk - which is how the assertions below reach a worktree
    without composing a path out of §3.9's layout and then agreeing with themselves about it.

    The planner is in `entered` and `left` under `PLANNING`, and not left out as "not a chunk": what
    these two lists are is **every agent this run paid for**, and a test that could not see a second
    planning dispatch could not tell a session that corrected itself from one that was run again.
    """

    entered: list[str] = field(default_factory=list[str])
    left: list[str] = field(default_factory=list[str])
    where: dict[str, Path] = field(default_factory=dict[str, Path])
    refusals: list[ToolResult] = field(default_factory=list[ToolResult])
    """What `report_chunks` said back to the planner, in order, for the one arrangement that
    reports a plan the payload type will not have. Empty everywhere else."""


def _whose(task: AgentTask, work: Mapping[str, tuple[str, bytes]]) -> str:
    """Which chunk this dispatch is for, read off the prompt the framework composed.

    **The inputs and not the checkout's name.** `AgentTask` carries no namespace and no step name,
    deliberately (§3.3), and the two handles it does carry are the tools and the prompt; every
    implementer here shares one role, one model and one empty tools tuple, so what tells them apart
    is the only thing that differs - `chunk=`, appended as canonical JSON under `## Inputs`, where
    `"id":"parser"` is a key and its value. Keying on `task.workspace.name` would work and would
    make the assertion that a chunk's worktree is named after the chunk circular, since the name
    would then be what the test used to decide which chunk it was looking at.
    """
    for chunk in work:
        if f'"id":"{chunk}"' in task.instructions:
            return chunk
    raise AssertionError(  # pragma: no cover - a dispatch this file did not arrange
        f"an implementer was dispatched with no chunk of this plan in its inputs:\n"
        f"{task.instructions!r}"
    )


def _agent(
    work: Mapping[str, tuple[str, bytes]],
    seen: _Dispatches,
    *,
    barrier: asyncio.Barrier | None = None,
    waits: Mapping[str, asyncio.Event] | None = None,
) -> testing.Agent:
    """One agent's conduct for a whole run of `split`: report the plan, or implement one chunk.

    **In the harness's own vocabulary, rendezvous and all**, which is what 19.2 widened `Agent` for
    and what every test below except one is now driven on. It is an `async def` returning a `Reply`,
    which `testing.Agent` admits beside the plain `def` and the one-line lambda: `container.fakes`
    awaits what the call produced when there is something to await, so `await barrier.wait()` is a
    line an author may write here. Until then it could not be, and the whole of section 2 and 3
    below sat on `container.fakes(claude=...)` with a raw per-provider `Script` instead - for the
    property `split` exists to demonstrate, through a door that could not express it.

    `barrier` is the rendezvous: reached **before** anything is written, so no child can finish
    until every other has started. `waits` holds one child back until something outside it has
    happened, which is how a merge train's order stops being asyncio's business and becomes the
    test's - each event below is set from a place that provably holds the target's lease, so a child
    released there is a child whose landing must queue.

    It writes into `task.workspace` for `SEPARATE`'s reason and returns a `Reply` that says so.
    """

    async def agent(task: testing.AgentTask) -> testing.Reply:
        if any(tool.name == report_chunks.name for tool in task.tools):
            seen.entered.append(PLANNING)
            seen.left.append(PLANNING)
            return testing.Reply(
                calls=[testing.Call(report_chunks.name, _payload(work))], says="divided it up"
            )
        mine = _whose(task, work)
        seen.entered.append(mine)
        seen.where[mine] = task.workspace
        if waits is not None and mine in waits:
            await waits[mine].wait()
        if barrier is not None:
            await barrier.wait()
        path, body = work[mine]
        written = task.workspace / path
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(body)
        seen.left.append(mine)
        return testing.Reply(says=f"implemented {mine}")

    return agent


def _correcting(
    work: Mapping[str, tuple[str, bytes]], seen: _Dispatches, refused: Mapping[str, JsonValue]
) -> Script:
    """The same conduct as a raw per-provider `Script`, for the arrangement that reads an answer.

    `refused` is a plan reported **first** and expected to come back refused, which is the one thing
    a `Reply` cannot express at all and which awaiting an `Agent` does not change: a `Reply` is a
    value computed before the run, so an agent written in the harness's vocabulary can make a bad
    call and a good one but can never *read* the answer to the first - an `async def` one has
    already returned by the time the call is made. Reading it is the whole claim here - §3.3's
    rejection goes back to the model inside the same conversation, and what a script does with it is
    what a model would do with it.

    This is the escape hatch `sdk/testing.py` names, used for exactly what it is named for, and the
    one place in this file that still needs it.
    """

    async def script(conversation: Conversation) -> AgentOutcome:
        task = conversation.task
        if any(tool.name == report_chunks.name for tool in task.tools):
            seen.entered.append(PLANNING)
            seen.refusals.append(await conversation.call(report_chunks.name, refused))
            await conversation.call(report_chunks.name, _payload(work))
            seen.left.append(PLANNING)
            return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")
        mine = _whose(task, work)
        seen.entered.append(mine)
        seen.where[mine] = task.workspace
        path, body = work[mine]
        written = task.workspace / path
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(body)
        seen.left.append(mine)
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return script


# --- the bundle, the run, and reading one back ---------------------------------------------------


def _over(
    tmp_path: Path,
    *,
    agent: testing.Agent | None = None,
    claude: Script | None = None,
    verifier: FakeVerifier | None = None,
    terminal: Terminal | None = None,
) -> testing.Harness:
    """A harness over an all-fakes bundle this file has arranged. `testing.over`'s own seam.

    `agent=` and `claude=` are `container.fakes`' own two parameters and mean what they mean there:
    one provider-blind agent in the harness's vocabulary, or a raw per-provider script when a test
    needs to read something back mid-conversation. Both roles in `split` are Claude models, so one
    of either serves a whole run.

    `verifier=` and `terminal=` both go in through `FakeServices`' own verbs, so each lands in the
    port-typed bundle and the sibling field at once. `with_verifier` is 19.2's and this file is why
    it exists: substituting the gate used to be `replace(fakes, services=replace(fakes.services,
    verifier=...))` here, which left `fakes.verifier` naming an object the bundle no longer used -
    the two-views defect `with_terminal` was written to close, reproduced by hand at the one call
    site that wanted a hook inside a landing.
    """
    fakes = container.fakes(
        TreesRoot(tmp_path / "trees"), files=SEED, agent=agent, claude=claude
    )
    if verifier is not None:
        fakes = fakes.with_verifier(verifier)
    if terminal is not None:
        fakes = fakes.with_terminal(terminal)
    return testing.over(fakes)


def _started(harness: testing.Harness, chunks: int) -> asyncio.Task[None]:
    """`agl run split -n test -r <request> -c <chunks>`, as a task this file can wait on with a
    bound. Flags and not an instance, because that is the round trip `agl.testing` insists on."""
    return asyncio.create_task(harness.run(split, "-r", REQUEST, "-c", str(chunks)))


async def _ended(running: asyncio.Task[None], seen: _Dispatches, why: str) -> None:
    """Wait for the run under `_LIVENESS`, and make the expiry the failure with `why` as the reason.

    `asyncio.wait` and not `wait_for`, so that nothing in the passing path depends on what a
    cancellation does to a `TaskGroup`: the workflow's own group re-raises as a `BaseExceptionGroup`
    and a bound that had to interpret one would be a bound that could report the wrong thing. What
    is cancelled here is only a run that has already failed this assertion.

    **`seen` is read here rather than interpolated by the caller**, and that is not a tidiness: an
    f-string at the call site is evaluated as the argument is passed, which is before the run has
    taken a single turn, so every failure message this file could produce would report that no agent
    had been dispatched. Where a hang is the failure, what the agents did before they stopped is the
    whole of the diagnosis.
    """
    done, pending = await asyncio.wait({running}, timeout=_LIVENESS)
    for stalled in pending:
        stalled.cancel()
    if not done:  # pragma: no cover - the failure these bounds exist to produce
        pytest.fail(
            f"{why} After {_LIVENESS:g}s the agents dispatched were {seen.entered} and the ones "
            f"that finished were {seen.left}."
        )
    running.result()


async def _record(harness: testing.Harness) -> Mapping[str, JsonValue]:
    """This run's `run.json`, through the store the harness wrapped - which `agl/testing.py`
    sanctions in as many words, and which is where the branch name and the base commit come from.
    Composing either here would mean this file holding its own copy of §3.9's naming scheme."""
    record = await harness.fakes.store.read_record(harness.scope)
    assert record is not None, "the run wrote no run.json, so it never started"
    return record


def _text(record: Mapping[str, JsonValue], key: str) -> str:
    """One string field of the record. `run.json` holds `JsonValue`s and two of them are needed."""
    value = record[key]
    assert isinstance(value, str), f"run.json holds a {type(value).__name__} at {key!r}"
    return value


def _target(seen: _Dispatches) -> Path:
    """The run's own checkout, found beside a child's rather than composed out of the layout.

    §3.9 flattens the trees root, so `_base` is every child's own sibling - which is the one fact
    about the layout this file spends, and it spends it because the alternative is asking
    `tree_layout` where a checkout should be and then agreeing with whatever it said.
    """
    return next(iter(seen.where.values())).parent / "_base"


def _files(where: Path) -> dict[str, bytes]:
    """Every file in a checkout, by its path relative to it. What a person would see in there."""
    return {
        path.relative_to(where).as_posix(): path.read_bytes()
        for path in sorted(where.rglob("*"))
        if path.is_file()
    }


def _committed(
    harness: testing.Harness, base: str, chunk: str, work: Mapping[str, tuple[str, bytes]]
) -> str:
    """The commit `implement <chunk>` was supposed to make, recomputed rather than read back.

    `FakeRepository` addresses a state by the digest of its tree, its parents and its message, and
    `record` is idempotent - so rebuilding the commit this chunk's step was supposed to produce and
    finding it in the target's line of work asserts every term at once: what the agent wrote, what
    it was made on top of, and **what the workflow called it**. Without it a workflow that dropped
    the `commit=` entirely would leave a chain nothing here could tell from the right one.

    **19.2 gave `History` a `message` member and this is still a recomputation, which is worth
    saying rather than leaving to be wondered about.** That member answers about a commit the
    caller *names*, and the commit this function is about is not one this test can name: it is a
    chunk's own commit, sitting inside `_base`'s line of work behind however many landings followed
    it, and no port hands back an id for it - §3.10 forbids the listing that would be the general
    form of asking. `tests/workflows/test_fix.py` converted its own version of this because there
    the commit in question is a *tip*, which is a name a test already holds.
    """
    path, body = work[chunk]
    return harness.fakes.repository.record({**SEED, path: body}, (base,), f"implement {chunk}")


# --- 1. N children, all at once ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_chunk_can_finish_until_every_other_has_started_and_all_of_them_land(
    tmp_path: Path,
) -> None:
    """`split`'s whole premise, arranged so that a framework which serialized it cannot pass.

    Three chunks, three worktrees, three ledgers, three landings into one `_base`. The barrier is
    reached from **inside each agent** before any of them writes anything, so no child can finish
    until every other has been dispatched: under the design all three are dispatched before the
    first can return, and under any lock spanning namespaces the second child never arrives, the
    first waits for it forever, and this run never ends. The failure is a hang, so the wait is
    bounded and the bound expiring **is** the assertion - a `gather` and a count of entries cannot
    tell the two designs apart, because a run that did the three strictly in order leaves exactly
    the ledger this one does.

    The rest is what a run of `split` is, and each part fails on its own:

    * **the ledger** is one `plan` in the run's own namespace and one `implement` per chunk in a
      namespace of its own, which is §3.6's flat trees root and §3.3's `run.worktree(chunk.id)`
      arriving together. Compared sorted, because the order three concurrent children record in is
      asyncio's business and no part of the claim;
    * **the base branch carries every chunk's commit under the message the workflow composed**,
      recomputed by `_committed` from the tree and the message rather than read back, which is the
      only way a commit message is assertable at all;
    * **no child could see another's work**, which is what §3.9 cuts a checkout per child for. Two
      agents sharing one tree would each be editing the other's files with nothing raising, and the
      commit each of them made would carry the other's edits.
    """
    seen = _Dispatches()
    harness = _over(tmp_path, agent=_agent(SEPARATE, seen, barrier=asyncio.Barrier(len(PLAN))))

    await _ended(
        _started(harness, len(PLAN)),
        seen,
        "three chunks of one run could not all be inside a step at once. §3.6 serializes steps "
        "within a namespace and nothing across them - a lock spanning namespaces leaves the second "
        "child waiting for a first child that is waiting for the second, which is the only real "
        "concurrency AGL has, deadlocked.",
    )

    assert [entry.step for entry in harness.recorded] == ["plan", *["implement"] * len(PLAN)]
    assert harness.recorded[0].namespace is None, "the plan step did not run in the run's own tree"
    assert sorted(str(entry.namespace) for entry in harness.recorded[1:]) == sorted(PLAN), (
        f"the chunks recorded their work under {[e.namespace for e in harness.recorded[1:]]}, and "
        f"§3.3 files a child's ledger under the name `run.worktree(chunk.id)` was given"
    )

    record = await _record(harness)
    tip = harness.fakes.repository.tip(_text(record, "branch"))
    assert tip is not None
    history = harness.fakes.services.history
    for chunk in PLAN:
        wanted = _committed(harness, _text(record, "base_sha"), chunk, SEPARATE)
        assert await history.contains(wanted, tip), (
            f"the run's branch does not contain the commit {chunk!r} was supposed to make: its "
            f"tree, its parent and the message `implement {chunk}` compose a state this line of "
            f"work has never held. A chunk that landed something else, landed nothing, or was "
            f"committed under another message all arrive here"
        )
        checkout = seen.where[chunk]
        assert checkout.name == chunk, (
            f"{chunk!r}'s agent was dispatched into a checkout called {checkout.name!r}, so the "
            f"worktree a chunk runs in is not the one its own id names"
        )
        for other in PLAN:
            present = (checkout / SEPARATE[other][0]).is_file()
            assert present is (other == chunk), (
                f"{chunk!r}'s checkout {'holds' if present else 'is missing'} {other!r}'s file, so "
                f"the children are not working in one checkout each (§3.9) - and two agents in one "
                f"tree each commit the other's edits under their own message"
            )


@pytest.mark.asyncio
async def test_a_plan_the_payload_type_refuses_is_corrected_inside_the_planners_own_session(
    tmp_path: Path,
) -> None:
    """`chunks.py`'s whole argument for enforcing its three rules in a `__post_init__`, driven.

    The rules themselves are `tests/workflows/test_split.py`'s - they are facts about a payload type
    and reading one is a call. What that file cannot show is the sentence its docstring rests on:
    *"a refusal here is a refusal inside the tool call, so the planner is told what it did and sends
    another call. Same rule, same run, one round trip instead of a dead run."* Everything in that
    sentence is about a live session, and this is the one place a session exists.

    So the planner reports two ids that differ only by case, reads what came back, and reports a
    plan that will do. Four things follow and each of them is the claim:

    * the first call was **rejected** rather than raised - `ToolResult.rejected`, which is the
      channel §3.3 puts the answer on;
    * the text it carries names the rule, because that text is the only place a model that guessed
      wrong is told what it may write - a derived schema renders a `str` field as
      `{"type": "string"}` and cannot carry a word of it;
    * **nothing was recorded for the rejected call.** One `plan` entry, holding the good plan. A
      refusal that had written an entry would be a run whose ledger holds a plan the framework
      refuses to open worktrees for, replayed as a cache hit by every resume;
    * and the run finished. One dispatch for `plan`, so the planner was paid once and corrected
      itself inside the session it was already in, which is what the round trip is for.

    Written on a raw `Script` because a `Reply` cannot express it: a `Reply` is computed before the
    run, so an agent in the harness's own vocabulary can make a bad call followed by a good one and
    can never read the answer to the first - which is the whole of what is asserted here. That is
    the same finding the module docstring records about the rendezvous, from its second side.
    """
    seen = _Dispatches()
    plan = {chunk: SEPARATE[chunk] for chunk in (PARSER,)}
    collides: dict[str, JsonValue] = {
        "items": [
            {"id": PARSER, "work": "pull the token reader out", "files": []},
            {"id": PARSER.upper(), "work": "and expose it", "files": []},
        ]
    }
    harness = _over(tmp_path, claude=_correcting(plan, seen, collides))

    await _ended(
        _started(harness, len(plan)),
        seen,
        "the run never finished after its planner was told its plan would not do. A rejection is "
        "carried back into the same conversation and the session goes on; a run that stops here is "
        "one where a malformed payload ended something.",
    )

    assert len(seen.refusals) == 1 and seen.refusals[0].rejected, (
        f"the tool did not refuse a plan naming {PARSER!r} and {PARSER.upper()!r}: "
        f"{seen.refusals}. Those are two refs to git and one directory on a case-insensitive "
        f"filesystem, so the second `run.worktree()` raises - after `plan` is journalled, which is "
        f"a run only `agl clear` gets out of"
    )
    assert "one directory" in seen.refusals[0].text, (
        f"the refusal reached the model saying nothing it can act on: {seen.refusals[0].text!r}"
    )
    assert [entry.step for entry in harness.recorded] == ["plan", "implement"], (
        f"the ledger holds {[entry.step for entry in harness.recorded]}. A rejected call records "
        f"nothing - the refusal says so in as many words - and a run that wrote an entry for one "
        f"would replay a plan the framework will not open a worktree for, on every resume"
    )
    assert harness.recorded[0].value == _payload(plan), (
        "the plan on the ledger is not the one the planner corrected itself to"
    )
    assert seen.entered == [PLANNING, PARSER], (
        f"the agents dispatched were {seen.entered}, where one planner and one implementer were "
        f"due. A rejection is answered inside the session that made the call, so the planner "
        f"corrects itself and is paid for once - a second planning dispatch means the refusal "
        f"ended the step and the framework ran it again, which is the round trip this rule exists "
        f"to avoid, paid in full"
    )


# --- 2. one target, one landing at a time --------------------------------------------------------


class _Rendezvous(FakeVerifier):
    """A merge gate two landings would meet inside, if two landings could ever be inside one.

    The mirror of the barrier above and the reason it has to be one: "landings into one target are
    serialised" (§3.4) is a negative, and a test that watched two children land and found both of
    them in the target afterwards would be green against an implementation that ran the two gates at
    the same moment over the same checkout. What can fail is a rendezvous **in the gate**: if two
    landings overlap the barrier is passed and `together` is not empty; if they cannot, the first
    landing waits until its bound expires and no gate ever meets another.

    The gate is the only hook a workflow's own test has inside a landing, which is what makes this
    the instrument here rather than something more direct. What the framework does with it is
    exactly what it does with the real one - `verify(services.build, target.path)`, once per
    landing, in the target's own checkout.

    **A `FakeVerifier` subclass and not a bare `Verifier`**, which is what `with_verifier` takes and
    why: `FakeServices.verifier` is at the fake's own type so that `answers` is reachable, so an
    instrument goes into the bundle by extending the fake rather than replacing it. That costs
    nothing and buys the verdict - `super().verify` below is the scripted answer or the unscripted
    default, so this gate rendezvouses *and* stays scriptable, where an independent `Verifier` had
    to invent a passing outcome of its own and could never be told to go red.

    The barrier is **aborted** after the first expiry rather than left to expire again: the evidence
    is one bound spent by one landing that could not find a partner, and every later gate then
    raises `BrokenBarrierError` at once. Otherwise a run with three landings in it would pay the
    bound three times over for one claim.
    """

    def __init__(self, parties: int) -> None:
        super().__init__()
        self.entered: list[Path] = []
        """Every gate this run ran, in order, at the directory the framework pointed it at."""

        self.together: list[Path] = []
        """The gates that found another gate inside the barrier with them. Must stay empty."""

        self._barrier = asyncio.Barrier(parties)

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        """Wait for a second landing's gate, bounded, and then answer whatever the fake would."""
        self.entered.append(workdir)
        try:
            async with asyncio.timeout(_SERIALIZED):
                await self._barrier.wait()
            self.together.append(workdir)
        except TimeoutError:
            await self._barrier.abort()
        except asyncio.BrokenBarrierError:
            pass
        return await super().verify(command, workdir)


@pytest.mark.asyncio
async def test_a_siblings_landing_waits_rather_than_meeting_another_inside_the_gate(
    tmp_path: Path,
) -> None:
    """§3.4's merge train: two children that overlap everywhere except in the target.

    The same two children as the test above - dispatched together, held at a barrier neither can
    pass alone, so both are provably finished and both are offering a landing at the same moment -
    and then a second barrier in the **gate**, which they must not be able to pass. That pair is the
    whole test: the first says the concurrency is real, and the second says it stops at the target's
    door. A test with only the second could be green over a framework that never ran two children at
    once at all.

    What a failure looks like is worth naming, because §3.4 names it: `FakeIntegrator.land` reads
    the target's head, combines against it and records, so two landings interleaved at that
    suspension both compute a combination from the same head and whichever records second replaces
    the first one's landing with one that never saw it. Nothing raises. The child that lost is
    simply not in the target and its `integrate()` returned a head saying it was.

    So both are asserted: no two gates met, **and** both children are in the target's line of work
    afterwards - the second being what turns "one at a time" from a claim about exclusion into a
    claim about a queue. `_SERIALIZED` is spent on every green run here and its constant says why
    that is the price of a negative.
    """
    seen = _Dispatches()
    gate = _Rendezvous(2)
    plan = {chunk: SEPARATE[chunk] for chunk in (PARSER, API)}
    harness = _over(
        tmp_path, agent=_agent(plan, seen, barrier=asyncio.Barrier(2)), verifier=gate
    )

    await _ended(
        _started(harness, len(plan)),
        seen,
        "a run of two chunks that touch nothing in common never finished, so one of the two "
        "landings is waiting on something the other one is holding for good.",
    )

    assert gate.together == [], (
        f"two landings into one target were inside the build gate at the same moment: "
        f"{gate.together}. §3.4 serialises landings into one target behind a lease and the target "
        f"namespace's own step lock, and two that overlap both combine against the head the other "
        f"has already moved past - the child that loses is not in the target, its `integrate()` "
        f"reported a head saying it is, and nothing raises"
    )
    assert len(gate.entered) == len(plan), (
        f"the gate ran {len(gate.entered)} times for {len(plan)} landings. The framework runs "
        f"exactly one build (§3.4), the merge gate, and it runs it once per landing"
    )
    assert set(gate.entered) == {_target(seen)}, (
        "a gate ran somewhere other than the target's own checkout, which is the only place the "
        "combined tree exists - building in a child's checkout builds the child alone"
    )

    record = await _record(harness)
    tip = harness.fakes.repository.tip(_text(record, "branch"))
    assert tip is not None
    history = harness.fakes.services.history
    for chunk in plan:
        wanted = _committed(harness, _text(record, "base_sha"), chunk, plan)
        assert await history.contains(wanted, tip), (
            f"{chunk!r} is not in the run's branch, so the queue excluded rather than serialised: "
            f"both children were told they landed and only one of them did"
        )


# --- 3. the conflict path ------------------------------------------------------------------------


class _Held(FakeVerifier):
    """A green gate that says when it has been reached - which is a moment the lease is held.

    The ordering instrument for everything below. §3.4 holds the target's lease from the start of a
    landing until its outcome settles, and the gate runs inside that, so a child released **here**
    is a child whose own landing cannot possibly get in front of the one that is running: it has to
    queue for a lease somebody else is holding. That is what makes the merge train's order this
    file's rather than asyncio's, without a sleep anywhere and without a poll.

    The alternative was releasing the second child when the first child's *agent* finished, which is
    ordering by hope: both children then race through a commit, an entry and an `integrate()` with
    nothing but a head start between them, and the test that reads "the second one collided" would
    be reading whichever one lost.

    A `FakeVerifier` subclass for `_Rendezvous`' reason, one class up: that is what `with_verifier`
    takes, and `super().verify` is what keeps a substituted gate scriptable.
    """

    def __init__(self) -> None:
        super().__init__()
        self.reached = asyncio.Event()
        """Set from inside the first gate, and therefore inside the first lease."""

        self.entered: list[Path] = []
        """Every gate this run ran. A landing that will not combine never reaches one."""

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        self.entered.append(workdir)
        self.reached.set()
        return await super().verify(command, workdir)


class _Watched(Terminal):
    """A `Terminal` that says when a question is going up, and hands everything to a real one.

    Two members and no behaviour: it invokes the view once to see whether the screen carries
    responses - which is the port's own dispatch and what `RichTerminal`, `HeadlessTerminal` and
    `ScriptedTerminal` all do - keeps it **with the priority it was shown at**, calls `watching()`
    if it is a question, and delegates.

    **The priority is kept because nothing else in this run can see it.** `split` declares no
    `on_question` on either role, so no agent question is ever queued, so nothing else is ever in
    the queues for a conflict screen to preempt and the number does not discriminate: `priority=10`
    and `priority=0` produce identical runs. §3.7's reason for the number is not about `split`'s
    current roles, though - a conflict screen queued behind two agent questions stalls the merge
    queue on something unrelated, which is the entire justification for having one level of
    preemption at all - so what a test can hold is the number the workflow asked for, which is what
    would make the preemption happen the day anything else queues.
    Everything a terminal actually decides is the delegate's: the queues, the priorities, the slot
    and the script are `adapters/rich_terminal/scripted.py`'s, which is a conforming implementation
    under `tests/contracts/terminal.py`'s eye, so a workflow driven through this queues and preempts
    the way it will in front of a person.

    **It exists for a moment rather than for a value.** `watching()` is called while the landing
    that produced this screen holds the target's lease and is about to block on it, which is the one
    instant "a person is deliberating" is a state of the run rather than a description - and no
    conforming terminal has anywhere to report it, because no workflow needs it. Reading `displayed`
    afterwards cannot substitute: a test would have to poll for it, and polling for the start of a
    window is how a test comes to assert about a window that had already closed.

    Not a second `ScriptedTerminal` and no claim to be one: it answers nothing itself, and
    `tests/contracts/terminal.py` has never looked at it. `tests/workflows/test_fix.py::_Watching`
    is the same object one workflow over, for the same reason and with the same disclaimer.
    """

    def __init__(self, inner: Terminal, watching: Callable[[], None]) -> None:
        self._inner = inner
        self._watching = watching
        self.shown: list[tuple[int, Screen[object]]] = []
        """One entry per `show`, in order: the priority it asked for and the screen it produced."""

    @property
    def questions(self) -> list[tuple[int, Screen[object]]]:
        """The interactive screens only - the ones that queue, and therefore the ones a priority
        is a fact about. A passive screen goes to the slot and its number is never read."""
        return [(priority, screen) for priority, screen in self.shown if screen.responses]

    @property
    def boards(self) -> list[tuple[int, Screen[object]]]:
        """The passive screens only. `split` shows exactly one, at the default priority."""
        return [(priority, screen) for priority, screen in self.shown if not screen.responses]

    async def show[T](
        self,
        view: Callable[..., Screen[T]],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        screen = view(**params)
        self.shown.append((priority, cast("Screen[object]", screen)))
        if screen.responses:
            self._watching()
        return await self._inner.show(view, priority=priority, **params)

    @property
    def pending(self) -> Mapping[int, int]:
        return self._inner.pending

    async def __aenter__(self) -> Self:
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc, tb)


@pytest.mark.asyncio
async def test_the_target_is_held_across_the_decision_and_a_sibling_waits_behind_it(
    tmp_path: Path,
) -> None:
    """§3.4's conflict, driven through the workflow, with a third chunk queued behind the screen.

    Three chunks and a plan drawn wrong: `parser` and `api` both create one file from a base holding
    neither, which is the one shape no honest integrator can combine, and `docs` was independent all
    along. `parser` lands first - it is the only child whose agent is not waiting for anything -
    and the gate it runs releases `api`, which cannot get in front of it because the lease is
    held for the whole of that landing. So `api` collides, and `views.conflict` goes up.

    **The screen is where `docs` is released**, which is the arrangement's centre: it is dispatched,
    finishes, records its entry and offers its landing while a person is still reading. Then nothing
    happens, and the nothing is the assertion - the entry is on the ledger, so the child is between
    its step and its landing and there is nowhere else for it to be; the gate has run exactly once,
    so `docs` never reached the build; and one screen has gone up, so its landing was not answered
    with a conflict of its own either. §3.4 holds the lease and the target namespace's step lock
    until the outcome settles, and this is the whole reason `views.conflict` is shown at priority
    10: every other chunk's landing is stopped behind it.

    **What this cannot separate, said rather than claimed.** A target mid-landing is held by the
    *integrator* as well as leased by the framework, and `land` answers a pre-existing hold with a
    `Conflict` of its own - so a sibling offered into a target whose conflict nobody has decided is
    stopped by either mechanism alone, and a workflow's own test can only see that it was stopped.
    That is the honest altitude for this file: what a run of `split` promises is that an undecided
    conflict does not let the next chunk past, and `tests/sdk/test_leases.py` is the one arrangement
    in the repository that isolates the lease from everything that covers for it - two `Journal`s
    over one scope, which `Steps` cannot produce and no workflow can ask for.

    **`retry()` and `abort()` are what release it, and not run exit.** The proof is that `docs`
    lands *inside this run* - after the abort, with the workflow still going. If the lease were
    given back only when the run exits, §3.4's own words, "that would serialise every landing in a
    run behind the first one forever", and there would be no run left to land in.

    And the screen comes up twice, which is 18.2's `while` doing what an `if` cannot: the retry
    fixes nothing, the landing comes back conflicted, and the same screen goes up again. The test
    below makes that the difference between a pass and a failure on its own; here it is one more
    thing this arrangement gets to see for free.

    The board is asserted too, in the slot behind the question, because a passive screen keeps being
    written under a queued one (§3.7): three rows, in the planner's own order, with nothing running.
    """
    seen = _Dispatches()
    gate = _Held()
    queued = asyncio.Event()
    term = testing.answering()
    watched = _Watched(term, queued.set)
    waits = {API: gate.reached, DOCS: queued}
    harness = _over(
        tmp_path, agent=_agent(COLLIDING, seen, waits=waits), verifier=gate, terminal=watched
    )

    running = _started(harness, len(PLAN))
    async with asyncio.timeout(_LIVENESS):
        await queued.wait()
    # Long enough for a landing that is not being held to have finished several times over, which
    # is what makes the negative below a negative rather than a race the test happened to win.
    settled, _ = await asyncio.wait({running}, timeout=_SERIALIZED)

    assert not settled, "the run finished while a conflict screen was still waiting to be answered"
    assert DOCS in [entry.namespace for entry in harness.recorded], (
        "the sibling's step never recorded, so it is not yet offering a landing and the wait below "
        "is a wait for nothing"
    )
    assert gate.entered == [_target(seen)], (
        f"the gate has run {len(gate.entered)} times, so a sibling's landing went through while a "
        f"conflict nobody has decided is holding the target. §3.4 holds the lease **and** the "
        f"target namespace's step lock until the outcome settles, which is exactly what a person "
        f"deliberating in front of `views.conflict` is doing to the merge queue"
    )
    assert len(watched.questions) == 1, (
        f"{len(watched.questions)} screens are up where one person is deciding one thing. The "
        f"sibling's landing was let through and answered with a conflict of its own - which is "
        f"what a target that admits a second landing while the first is undecided produces, and "
        f"there is no gesture in front of it and no timeout anywhere to end it"
    )
    assert term.slot() == Screen(Rows([Row(chunk, "") for chunk in PLAN])), (
        "the board is not in the slot behind the conflict screen. §3.7 keeps writing a passive "
        "screen under a queued one, so a run whose board is missing here either never put it up or "
        "put it up as something that had to be answered"
    )
    displayed = term.displayed()
    assert displayed is not None and displayed.responses, "no question is in front of the terminal"

    term.respond(0)
    term.respond(1)
    await _ended(
        running,
        seen,
        "the run did not finish once the conflict had been given up on. The lease and the step "
        "lock are released by `retry()` and `abort()`, so a sibling still waiting here is a "
        "sibling waiting for the run to exit - which is the reading §3.4 refuses, because it "
        "serialises every landing in a run behind the first one forever.",
    )

    assert term.remaining == (), (
        "a gesture was never spent, so the conflict screen came up fewer times than twice: a retry "
        "that fixed nothing has to come back conflicted and put the same screen up again, and the "
        "`if` spelling §3.4 names as a bug falls out of the branch instead, holding the lease"
    )
    assert len(watched.questions) == 2, (
        f"{len(watched.questions)} conflict screen(s) went up where two were due - retry, then "
        f"giving up - so the loop that put them there is not a loop"
    )
    assert watched.boards == [(0, Screen(Rows([Row(chunk, "") for chunk in PLAN])))], (
        f"the board was shown {len(watched.boards)} time(s), at "
        f"{[priority for priority, _screen in watched.boards]}. §3.3 shows it once, passively, at "
        f"the default priority - a second `show` would only ever mean putting a different view on "
        f"screen, and a board that had to be answered would block before the first chunk was "
        f"dispatched"
    )
    assert [priority for priority, _screen in watched.questions] == [10, 10], (
        f"the conflict screen was shown at {[p for p, _ in watched.questions]} where §3.4 shows it "
        f"at 10, above the board's own {watched.boards[0][0]}. Nothing in *this* run discriminates "
        f"on it - `split` declares no `on_question`, so no agent question is ever queued for a "
        f"conflict to preempt - and the number is what §3.7 gives one level of preemption for: "
        f"`integrate()` holds the target's lease and step lock until this screen is answered, so a "
        f"conflict queued behind an agent question stalls every other chunk's landing on something "
        f"unrelated. A workflow that shipped the default here would look identical until the day a "
        f"role grew a handler, and then stall the merge queue"
    )
    record = await _record(harness)
    tip = harness.fakes.repository.tip(_text(record, "branch"))
    assert tip is not None
    history = harness.fakes.services.history
    landed = _committed(harness, _text(record, "base_sha"), DOCS, COLLIDING)
    assert await history.contains(landed, tip), (
        "the sibling's work is not in the run's branch, so its landing was never let through. It "
        "landed *in this run*, after the abort and before the workflow ended, which is what makes "
        "`abort()` the thing that released the lease rather than run exit"
    )


@pytest.mark.asyncio
async def test_giving_up_puts_the_target_back_and_leaves_the_chunks_own_branch_alone(
    tmp_path: Path,
) -> None:
    """The other half of the decision: what a person who gives up gets, and what they keep.

    Two chunks over one file, `parser` landing and `api` colliding, and the script is **retry then
    give up** - the two gestures §3.4's loop is written for. What the run leaves behind is the whole
    of the policy `views.conflict`'s `ABORT` label promises and `split`'s own docstring argues:

    * the target is back where the landing found it - `parser`'s landing and not the run's base, so
      the revert undid the attempt and not the merge train;
    * the target's checkout holds no half of the collision. `FakeIntegrator` writes the contested
      file into the target's tree while it is held, so a target left holding one is a target the
      next child cannot land into for a reason that has nothing to do with either of them;
    * the abandoned chunk's own branch still carries its commit. Nothing is lost by giving up: a
      person merges it by hand or re-runs, and the branch and the worktree survive until `agl
      clear`. That is what makes the second clause of the `ABORT` label true rather than reassuring;
    * and its step is on the ledger, because it ran. A chunk that did not land is not a chunk that
      did not happen, and a resume would replay the step and offer the landing again.

    **The `while` is what this test can fail on.** Two gestures are scripted and `remaining` is
    asserted empty: a retry that fixed nothing comes back conflicted and the screen goes up a second
    time, so under the `if` §3.4 names as a bug the second gesture is never spent - and that run
    also falls out of the branch still holding the lease and the target's step lock, which is what
    the `if` costs in a run with anything else left to land. Without this assertion the two
    spellings are indistinguishable and 18.2's `continue` is unproven.
    """
    seen = _Dispatches()
    gate = _Held()
    plan = {chunk: COLLIDING[chunk] for chunk in (PARSER, API)}
    term = testing.answering([0, 1])
    harness = _over(
        tmp_path, agent=_agent(plan, seen, waits={API: gate.reached}), verifier=gate, terminal=term
    )

    await _ended(
        _started(harness, len(plan)),
        seen,
        "the run never finished. A conflict screen with no gesture left waits forever - §3.7 has "
        "no timeouts anywhere - so a run that hangs here put up more screens than the two this "
        "script answers, or is holding a lease nobody is going to release.",
    )

    assert term.remaining == (), (
        "the second gesture was never spent, so the retry did not come back to the same screen. A "
        "person who retries without having fixed anything gets a conflicted outcome back and goes "
        "round again; the `if` spelling falls through instead, holding the lease and the target's "
        "step lock for the rest of the run"
    )
    assert [entry.step for entry in harness.recorded] == ["plan", "implement", "implement"], (
        "a chunk that gave up on its landing is still a chunk whose step ran and recorded"
    )

    record = await _record(harness)
    base = _text(record, "base_sha")
    tip = harness.fakes.repository.tip(_text(record, "branch"))
    assert tip is not None
    ahead = _committed(harness, base, PARSER, plan)
    gave_up = _committed(harness, base, API, plan)
    history = harness.fakes.services.history

    assert await history.contains(ahead, tip), "the chunk that did land is not in the run's branch"
    assert not await history.contains(gave_up, tip), (
        "the abandoned chunk's work is in the run's branch. Nothing landed - the collision was "
        "never resolved - so a branch that carries it is one the next landing builds on top of"
    )
    assert _files(_target(seen)) == {**SEED, plan[PARSER][0]: plan[PARSER][1]}, (
        f"the target's checkout holds {sorted(_files(_target(seen)))}, and after an abort it holds "
        f"what it held before the landing that conflicted: the seed and the chunk that went in. A "
        f"conflicted landing writes both sides into that tree, so a target still holding one is a "
        f"target the next child is refused from for a collision nobody has ever seen"
    )
    assert harness.fakes.repository.tip(f"agl/_work/test/{API}") == gave_up, (
        "the chunk that gave up lost its branch. Giving up releases the lease and loses nothing "
        "else: `agl/_work/<label>/<id>` and its worktree survive until `agl clear`, which is the "
        "second clause of the label a person read before they chose it"
    )


# --- 4. the red gate -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_red_gate_leaves_the_branch_unmerged_and_the_target_clean(tmp_path: Path) -> None:
    """§3.4's one build, answered no, twice - and the honest limit of what that answer means.

    **A red gate does not say this child broke anything, because the gate has no baseline.** It says
    the *combined* tree is broken, and the framework reverts the landing either way. The two chunks
    below touch nothing in common and each one builds perfectly well alone; a target the parent's
    own ungated `run.step` had already broken would fail every subsequent child's gate in exactly
    this way, each with a `Conflict` naming the child, and there is nothing anywhere in AGL that
    would say so. That is the difference between "your work was wrong" and "your work was thrown
    away", and `prompts/implement.md` tells an implementer as much because nothing else will.

    What is asserted is the revert, which is §3.4's `Workspace.restore(before)` - `reset --hard`
    **and** `clean -fd` - in the two halves that fail separately:

    * **the branch is left unmerged.** The run's branch is exactly where it was cut, so neither
      child's line of work is in it. A revert that moved the tree back and left the branch where the
      landing put it passes the next assertion and not this one, and the next landing would build on
      top of the work the gate rejected;
    * **the tree is clean.** The target's checkout is the seed and nothing else - not the child's
      file, not a merge's leavings. `Integrator.land` is entitled to refuse a landing that would
      write over unrecorded work in the target, so a target left holding a rejected build's output
      is a target the *next* child cannot land into either.

    Written on `testing.harness(agent=...)` and `fakes.verifier.answers(FAKE_BUILD, passed=False)`,
    which is a workflow author's own vocabulary end to end: this is the one test in this file that
    needs no rendezvous, and it is here in that spelling to show that the raw scripts elsewhere are
    the arrangements' cost and not this file's habit.
    """
    seen = _Dispatches()
    plan = {chunk: SEPARATE[chunk] for chunk in (PARSER, API)}
    term = testing.answering([1, 1])
    harness = testing.harness(tmp_path, agent=_agent(plan, seen), files=SEED, terminal=term)
    harness.fakes.verifier.answers(
        container.FAKE_BUILD, passed=False, status=2, output="E   ImportError: src.parse\n"
    )

    await _ended(
        _started(harness, len(plan)),
        seen,
        "the run never finished with both red gates given up on. A conflict screen with no "
        "gesture left waits forever, so this is a run that put up more screens than the one per "
        "landing a red gate produces.",
    )

    assert term.remaining == (), (
        "a gesture was never spent, so one of the two landings was not offered a screen at all - "
        "a red gate is a `Conflict` like any other and reaches the same `while`"
    )
    record = await _record(harness)
    assert harness.fakes.repository.tip(_text(record, "branch")) == _text(record, "base_sha"), (
        "the run's branch moved over landings the gate rejected. §3.4 runs the build gate and "
        "reverts on failure, and the criterion is that a failing gate leaves the branch unmerged - "
        "a branch that still holds the rejected work is one the next landing builds on top of"
    )
    assert _files(_target(seen)) == SEED, (
        f"the target's checkout holds {sorted(_files(_target(seen)))} after two rejected landings, "
        f"where it holds what the run was cut from. The revert is `Workspace.restore`, which is "
        f"`reset --hard` and `clean -fd` together - a tree that keeps the landing means only the "
        f"head moved, and the next step and the next person to look read the tree"
    )
    for chunk in plan:
        assert harness.fakes.repository.tip(f"agl/_work/test/{chunk}") == _committed(
            harness, _text(record, "base_sha"), chunk, plan
        ), f"{chunk!r} lost the branch its work is on, and a rejected landing takes nothing away"
