"""§3.7's two priorities, driven by a workflow: the conflict that preempts, and the queue behind it.

15.1 wired `run.terminal` and 15.2 proved the mid-run question path end to end. What is left is the
thing those two make possible for the first time - **two priorities live at once**, with a person in
front of them and the framework's own merge queue behind them - and §3.3's conflict snippet, which
no deliverable before this one could execute.

Stage 6 built the slot, the two queues, preemption, `pending` and the fallback order.
`tests/adapters/test_rich_terminal_queues.py` and `tests/contracts/_terminal_queues.py` own every
one of those mechanics against `Screens` and against both implementations, and nothing here
re-proves any of it. The subject of this file is a **workflow** driving them, which is the only
place they mean anything: the questions are asked by agents in two children, the conflict comes out
of a real landing, the priorities are the two §3.7 writes down, and the person is a scripted
keyboard.

## Preemption is not cosmetic, and stage 14 is what made that literal

§3.7: "`integrate()` holds the target lease while a conflict is unresolved, so a conflict screen
queued behind two agent questions would stall the merge queue on something unrelated. That is the
entire justification for one level of preemption." Stage 14 made it sharper than the plan states,
and `sdk/_engine/integration.py` says so where it happens: `Leases.claim` takes the lease **and the
target namespace's step lock**, because a landing is a second writer of a checkout §3.6 promises is
single-threaded. So an undecided conflict does not merely hold up other landings - it holds up the
**parent's own next step**.

That is what `test_a_conflict_preempts_two_agent_questions_and_the_parents_step_goes_on` makes
observable, and it is why that test asserts something about a `run.step` rather than only about
which screen is current. A test that checked the screen alone would pass against a terminal where
preemption was decoration: the conflict would be drawn, the two questions nobody is ever going to
answer would still own the answer path, and the parent's step would wait for the rest of the run.
Here the questions are left unanswered on purpose, and the parent's step is asserted to have gone
on anyway - which is "the merge queue did not stall on something unrelated", written as an
assertion.

## `pending` excludes what is on screen, and §3.7's own example is asserted exactly

`{5: 2, 10: 0}` is written into the plan as a specification, and this file reproduces it from a run
rather than from a `Screens` built by hand: two agent questions waiting, a conflict displayed, and
the `10: 0` there because the priority has been asked for and its one entry is on screen rather than
queued. There is no `0:` key, because the board is a passive `show` and `queues.py` decided a
passive registration registers no priority at all (the contract suite's gap #5, and that module's
argument for the side it took).

## The arrangement, and why each half of it is the real one

**A real `RichTerminal` over a console nobody watches.** `container.fakes()` builds a
`HeadlessTerminal`, which refuses every `Screen[T]` with `UpstreamUnavailable` - correctly, since a
workflow needing human input cannot run with nobody there - so it is substituted through
`FakeServices.with_terminal`, exactly as `tests/sdk/test_run_terminal.py` and `tests/sdk/
test_agent_questions.py` substitute theirs. **No third `Terminal` is written**: a hand-rolled
queueing terminal in a test would be under `tests/contracts/terminal.py`'s eye nowhere at all, and
the whole point of the `Keys` seam is that the real adapter can be driven without a tty. The console
is a plain `Console(file=StringIO())` and deliberately not `force_terminal=True`, which takes
`_display.py`'s appending path and so leaves `sys.stdout` and `sys.stderr` alone inside pytest.

**The substitution is `harness.with_terminal(...)` and not `dataclasses.replace`, and 16.5 is why.**
`container.fakes()` holds one terminal under two names - `services.terminal` and the sibling
`FakeServices.terminal` - and a `replace(harness.services, terminal=...)` moved only the first, so
`harness.terminal` afterwards named the `HeadlessTerminal` that had just been discarded. Nothing
reported that and nothing could: the two views simply disagreed. `with_terminal` swaps both at once
and hands back a bundle, which is the shape in which the disagreement is not expressible; every read
below is of the `RichTerminal` the fixture built, and now so is `harness.terminal`.

**What is on screen is `RichTerminal.written`**, which is the screen the adapter last **wrote**,
assigned at the write site after the diff decided the frame changed. It is what the contract suite's
driver reports `displayed()` with, and reading it rather than deriving one is the point: a terminal
that never wrote reports `None` and fails, instead of reporting what it would have shown if asked.

**Fakes and an in-memory repository**, for `tests/sdk/test_run_integrate.py`'s reason: nothing here
is a claim about git. `FakeIntegrator` runs a real three-way merge, holds a conflicted landing in
the repository rather than in itself, and the collision below is that file's own shape - a child
cut before the parent's own step, both creating one file, sharing not a line. The shape is reused
and the module is not imported, for the rule the rest of `tests/` keeps: no test module imports
another.

**Every await is bounded, and it has to be.** §3.7 has no timeouts anywhere - "an unanswered
question blocks its step indefinitely" - so a mistake in any test below is a hang rather than a
failure. Each wait carries its own deadline and a message naming what it was waiting for, what was
on screen and what `pending` said; the outer `asyncio.timeout` is the net under everything the
individual waits do not cover.

**And the rendezvous with the workflow is explicit.** A workflow function takes a `Run` and returns
`None`, so a test that needs to act at a particular moment inside one has nowhere to put a hook -
`test_run_integrate.py` reaches for a module-level cell and a `_Pause` for the same reason. `_Scene`
below is that - two events, both of them the test letting the workflow go on - and the module-level
records are what the workflow hands back.

## Not here, and each for its own reason

**Timeouts and part-typed input are left alone.** §3.7 lists both as known and accepted for v1.1:
preemption loses text a person was part-way through typing, and there are no question timeouts.
Nothing below builds either, and the tests are written so that the second one costs a bounded
failure rather than a hung suite.

**The question round trip is 15.2's** - that the `Question` the agent asked is the object the
handler was given, that the answer goes back into the round it was asked from, and that a
negotiation is one task, one dispatch and one entry. Questions are asked here because two of them
have to be waiting; what is asserted about them is where they sit in a queue.

**The five decisions around `integrate()` are 14's** - the advance, the lease, the containment
check, the root refusal and the merge gate, all in `tests/sdk/test_run_integrate.py`. What is added
here is the middle line of §3.3's snippet, which that file could build both halves of and never run.
"""

import asyncio
import io
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

import pytest
from rich.console import Console

from agl import api
from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.rich_terminal.terminal import RichTerminal
from agl.config import container, registry
from agl.ports.agent import AgentOutcome, Claude, QuestionHandler, StopReason
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.questions import Answer, Question
from agl.ports.tree_layout import TreesRoot
from agl.sdk._engine.integration import Integration
from agl.sdk.roles import Role
from agl.sdk.terminal import Choice, Row, Rows, Screen, Text
from agl.sdk.workflow import Run, workflow
from instruments.keyboard import DEADLINE, TICK, Typing

# Marked one by one rather than through a module-level `pytestmark`, matching the rest of
# `tests/sdk/`: `asyncio_mode = "strict"` turns a missing marker into a test pytest silently
# *skips*, which is how a file like this passes without ever having awaited anything.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")

AGENT: Final = 5
CONFLICT: Final = 10
"""§3.7's own two priorities, written as the plan writes them:

    await term.show(views.agent_question, question=q, priority=5)
    await term.show(views.conflict,       outcome=out, priority=10)

Named here so that the two numbers a workflow shows at and the two keys `pending` is asserted with
are one pair. They are plain `int`s and nothing below treats them as anything else - §3.7 refuses
named levels because `MEDIUM` and `HIGH` would encode "agent question" and "merge conflict", which
are one workflow's concepts and not the framework's."""

# The repository's seed and the files these runs move about. `CONTESTED` is the one two lines of
# work both create, sharing not a single line, which is the only shape no honest implementation can
# combine; `CHILD_ONLY` is the part of the child's work that has no argument with anybody, and it is
# what makes "the landing went in" and "the abort took it away again" different assertions.
SEEDED: Final = "src/a.txt"
SEED: Final = b"the user's own work\n"
CONTESTED: Final = "src/contested.py"
CHILD_ONLY: Final = "src/only-the-child.py"
AFTERWARDS: Final = "src/afterwards.py"

PARENT_BODY: Final = b"parent\nparent\nparent\n"
CHILD_BODY: Final = b"child\nchild\nchild\n"
CHILD_WORK: Final = b"the part of the child nobody disagrees with\n"
AFTER_WORK: Final = b"what the parent did once the landing let go\n"
RESOLVED: Final = b"what a person decided at the conflict screen\n"

FIRST_CHILD: Final = "T-01"
SECOND_CHILD: Final = "T-02"
LANDING_CHILD: Final = "T-03"
TICKET: Final = Namespace(LANDING_CHILD)
"""The three children, and the one of them the repository is asked about.

Plain strings, because that is what `run.worktree` takes and what the board's own rows are made of;
`Namespace` is a validated value type rather than a `str` subclass, so the two spellings are
deliberately not interchangeable and the conversion happens once, here."""

LANDING_ROW: Final = "landing"
AFTER_ROW: Final = "landed, and the parent went on"
"""What the board says about the child that is landing, before and after. The second is written into
the board's dict while a question is on screen, so it is the value that has to appear when the
queues drain."""

_HUNG: Final = 30.0
"""The net under a whole test, and never the thing that reports a failure.

Every wait below carries `instruments.keyboard.DEADLINE` and a message of its own, so this fires
only for a hang none of them was watching for - a run that stopped after everything had been typed,
say. Deliberately larger than that deadline, so the specific complaint always arrives first."""

_STALLED: Final = 1.0
"""How long the one test that proves a negative waits before concluding that the parent's step
really is behind the landing.

Spent on every green run, because the wait *is* the proof. Short, because what it has to outlast is
one dispatch against fakes - no process, no git, no network - and long enough that a bound firing
before the step could have reached its worker would pass against exactly the build it is written to
catch. `tests/sdk/test_run_integrate.py` spends the same second for the same reason one layer
down."""


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""


# --- the rendezvous, and what the workflows hand back ---------------------------------------------


@dataclass(frozen=True)
class _Scene:
    """One test's two rendezvous points with the workflow it is driving.

    A workflow function takes a `Run` and returns `None` (§3.3), so there is no argument to pass a
    handle through and no return value to read one out of - `tests/sdk/test_run_integrate.py` meets
    the same wall and answers it with a module-level cell and a `_Pause`. These are events rather
    than sleeps for that file's reason: nothing here waits on a scheduler, so a green run spends no
    time on either of them.
    """

    proceed: asyncio.Event
    """Set by the test once both agent questions have reached the terminal. Until then the workflow
    does not integrate, so "the conflict arrived while two questions were queued" is arranged rather
    than raced for."""

    finish: asyncio.Event
    """Set by the test when it has finished looking. The workflow's last line waits on this, because
    `api.run` shuts the terminal down on the way out and `__aexit__` clears `written` - so a claim
    about the frame that comes back when the queues drain has to be read while the run is still
    alive, which is also when a person would be reading it."""


_STAGED: Final[list[_Scene]] = []
"""Where a test leaves the `_Scene` its workflow will pick up. Module level because the workflows
have to be: `EntryPoint.load` imports a module and reads an attribute in it, and sees no local."""

asked: Final[list[Question]] = []
"""Every question a handler was given, in the order the handler was called.

**The order is the queue's order**, which is what lets the FIFO claim below name a question rather
than assume one: the handler appends here and then awaits `show`, and `show` reaches the queue
without suspending in between, so nothing can be enqueued between an entry appearing here and its
own registration joining the queue."""

answered: Final[list[str]] = []
"""What a person picked, one entry per question they finished. Its **length** is the load-bearing
part: "with the two questions still unanswered" is this list being empty."""

decided: Final[list[Integration]] = []
"""The live `Integration` a workflow is deciding about, published before §3.3's snippet reads it, so
that a test can read the summary that is on the screen while the screen is still up."""

boards: Final[list[Mapping[str, str]]] = []
"""One entry per `show` of the board. It counts registrations and nothing else: §3.7's "no extra
machinery" is that the dashboard comes back **with no second `show`**, and the only way to assert
"no second one" is for the workflow to say how many it made."""

under: Final[list[int]] = []
"""How many questions had been answered at the moment the workflow wrote into the board's own dict.

One entry, holding `0`, is what makes "the slot was written while a question was up" a fact rather
than a hope: a question is displayed for as long as one is queued, so a write made with nothing
answered is a write made behind a screen the board was not on."""


# --- the views a workflow shows ------------------------------------------------------------------

# Built out of `agl.sdk.terminal`, which is the front door §5 put there for exactly this: a workflow
# author writing a view never reaches into `agl.ports`. Every name it re-exports is the object
# `ports/terminal.py` defines, so this is a spelling and not a second set of classes.


def board(lines: Mapping[str, str]) -> Screen:
    """§3.7's board: one row per thing the run is doing, over a mapping the workflow keeps.

    Passive - no responses - which is what sends it to the slot rather than to a queue, and what
    makes it the screen everything else falls back to.

    **It takes the live dict and not a copy**, which is the whole of §3.7's per-frame design: "this
    is why arguments need not be values ... mutating a `Ticket` in place shows up for the same
    reason". The workflow re-`show`s only to change *which* view is on screen, and never to change
    what one says.

    Pure, as §3.7 requires of every view: invoked again ten times a second for as long as it is on
    screen, reading nothing but what it was handed.
    """
    return Screen(Rows([Row(name, state) for name, state in lines.items()]))


def choose(question: Question) -> Screen[str]:
    """The screen an agent's question becomes: what it asked, and the answers it offered.

    Interactive, so it joins a queue at whatever priority the handler showed it with. It returns the
    option a person picked, and the workflow's handler maps that down to an `Answer` at its own
    layer - which is where §3.7 puts that mapping.
    """
    return Screen(
        body=Text(question.prompt),
        responses=[Choice(option, value=option) for option in question.options],
    )


TRY_AGAIN: Final = "Try again"
GIVE_UP: Final = "Give up on this landing"
RETRY_KEY: Final = "1"
ABORT_KEY: Final = "2"
"""The conflict screen's two responses and the digits that pick them.

Numbered from 1 in the order the view offers them, which is `terminal.py`'s input convention and the
one translation between what a person reads and what the port indexes from 0. The keys are named
because they are what a test types, and a digit typed inline would be the one place this file agreed
with an implementation detail by coincidence."""

_SETTLED: Final = "this landing has already been decided"


def conflict(outcome: Integration) -> Screen[bool]:
    """§3.3's conflict view, in the workflow's own words and out of the outcome's own summary.

    §3.4: "On conflict the framework does not ask. It returns a `Conflict` outcome and holds the
    lease; the workflow shows its own screen and decides." This is that screen. The framework
    contributes the sentence on it - `Conflict.summary` is "the only part of a `Conflict`
    guaranteed to say anything" - and everything else here is the workflow's: which words the two
    buttons carry, what picking one produces, and that there are two of them at all.

    **The outcome is passed whole**, which is §3.3's own snippet and not a shortcut: the view is
    re-invoked every frame, so a screen built from the live object keeps saying what the outcome
    currently says rather than what it said when `show` was called.

    The `_SETTLED` branch is unreachable while this is on screen - an entry is retired before its
    `show` returns, so nothing invokes the view of a question that has been answered - and it is
    written because the type is honest that `conflict` may be `None` and a view may not raise on
    the redraw loop's behalf.
    """
    return Screen(
        body=Text(_SETTLED if outcome.conflict is None else outcome.conflict.summary),
        responses=[Choice(TRY_AGAIN, value=True), Choice(GIVE_UP, value=False)],
    )


# --- the agents, and what each of them is for -----------------------------------------------------


def _role(instructions: str) -> Role[None]:
    """An effect role: its result is `None` and its effect is commits (§3.3).

    No reporting tool anywhere in this file, because nothing here reads a step's value - what these
    steps are for is the files they leave, the lock they hold and the questions they ask.
    """
    return Role(instructions=instructions, model=Claude.SONNET)


def _asking(instructions: str, handler: QuestionHandler) -> Role[None]:
    """The same role with §3.7's callback on it, which is why it is built and not declared.

    A `Role` is module-level data (§3.3) right up until it declares `on_question`, because the
    handler "is a closure over the workflow's `Run`, keeping its signature to one parameter" - so
    this one cannot exist before a run does. Declaring it also folds `MID_RUN_QUESTIONS` into
    `requires`, which `tests/sdk/test_roles.py` pins and nothing here restates.
    """
    return Role(instructions=instructions, model=Claude.SONNET, on_question=handler)


PREPARE: Final = _role("prepare the parent")
COLLIDE: Final = _role("implement T-03, over the same file the parent touched")
AFTER: Final = _role("the parent's own next step, taken while a child is landing")

ASK_FIRST: Final = "implement T-01, and ask which way before deciding"
ASK_SECOND: Final = "implement T-02, and ask which way before deciding"
"""The two asking roles' instructions, kept as strings because their `Role`s are built inside the
workflow. Distinct on purpose: the fake is handed no namespace and no step name (§3.3 keeps both off
`AgentTask`), so the prompt is the only thing that tells one dispatch from another."""

QUESTIONS: Final[Mapping[str, Question]] = {
    ASK_FIRST: Question(
        prompt="T-01: split this by layer or by feature?",
        options=("split by layer", "split by feature"),
    ),
    ASK_SECOND: Question(
        prompt="T-02: rename the module, or leave the name alone?",
        options=("rename it", "leave it"),
    ),
}
"""One question per asking role, and they differ in every word.

Two agents asking the *same* question would be two entries the terminal keeps apart by identity
(`queues.py` argues that at length) and two screens this file could not tell apart at all - and
which of them is on screen is the FIFO claim below."""

_WRITES: Final[Mapping[str, Mapping[str, bytes]]] = {
    PREPARE.instructions: {CONTESTED: PARENT_BODY},
    COLLIDE.instructions: {CONTESTED: CHILD_BODY, CHILD_ONLY: CHILD_WORK},
    AFTER.instructions: {AFTERWARDS: AFTER_WORK},
}
"""Which files each agent leaves behind, keyed by the instructions it was dispatched with. The two
asking roles write nothing: their steps take no `commit=`, so anything they left would be wiped on
the way out anyway (§3.3), and what they are here for is the question."""


class _Agent:
    """What the fake was dispatched, what it was told, and one reading taken at a moment.

    A recorder here rather than on `FakeAgentRunner`, which deliberately holds no record of what it
    ran: what a test wants to know is already reachable from the script it supplied.
    """

    def __init__(self) -> None:
        self.dispatched: list[str] = []
        """The instructions of every task, in dispatch order. A role appearing here is a step that
        got past the target namespace's step lock and paid for an agent."""

        self.heard: list[Answer | None] = []
        """Every answer an agent was given. Read only to say that none had arrived yet."""

        self.answered_when_the_parent_stepped: int | None = None
        """How many questions had been answered at the instant the parent's own step reached its
        agent - the whole claim of the preemption test, taken **inside** the dispatch rather than
        checked afterwards, so that no scheduling between the two moments can make it true."""


def _agent(record: _Agent) -> Script:
    """One agent for every role here: ask if this role asks, write what it writes, and stop.

    Writing to `task.workspace` with the stdlib is the script's own code and not the adapter's,
    which is what lets a fake agent leave real files in a real directory for `commit=` to record.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        instructions = conversation.task.instructions
        if instructions == AFTER.instructions:
            # Before the append below, so that a test which waits for this dispatch to appear
            # cannot observe the dispatch without the reading that goes with it.
            record.answered_when_the_parent_stepped = len(answered)
        record.dispatched.append(instructions)
        question = QUESTIONS.get(instructions)
        if question is not None:
            record.heard.append(await conversation.ask(question))
        for name, content in _WRITES.get(instructions, {}).items():
            where = conversation.task.workspace / name
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_bytes(content)
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script


# --- the workflows, reached through hand-constructed entry points ---------------------------------


@workflow(name="deciding", version="1", params=NoParams)
async def deciding(run: Run[NoParams]) -> None:
    """§3.3's conflict snippet, run - and the middle line of it is what 15.3 is.

        outcome = await run.integrate()
        if outcome.conflicted:
            if await run.terminal.show(views.conflict, outcome=outcome, priority=10):
                await outcome.retry()
            else:
                await outcome.abort()

    Copied out of the plan and not paraphrased. `sdk/_engine/integration.py` says of this snippet
    that "`run.terminal` is stage 15, so §3.3's snippet cannot be executed end to end by anything in
    this repository today: what is built is both halves it touches ... and the middle line is 15's".
    This is the workflow that closes that.

    The child is cut **before** the parent's own step, so the two lines of work share a base in
    which `CONTESTED` does not exist and neither has ever seen the other's version. There is no
    combination of those two states that is anybody's answer, which is what
    `tests/contracts/_integration_targets.py` requires of a conflict a suite causes on purpose.
    """
    ticket = run.worktree(LANDING_CHILD)
    await run.step("prepare", PREPARE, commit="prepare the parent")
    await ticket.step("implement", COLLIDE, commit="implement T-03")

    outcome = await ticket.integrate()
    # Published before the branch below, and this is the only line of this workflow that is here for
    # the test: the summary on the screen belongs to an outcome that is still live, so a test that
    # read it afterwards would be reading a settled one.
    decided.append(outcome)
    if outcome.conflicted:
        if await run.terminal.show(conflict, outcome=outcome, priority=CONFLICT):
            await outcome.retry()
        else:
            await outcome.abort()


@workflow(name="contested", version="1", params=NoParams)
async def contested(run: Run[NoParams]) -> None:
    """Two children asking, a third one landing, and the parent's own next step behind all of it.

    §3.3's `drive` in the small: a board shown once and live over everything, children opened as
    worktrees, and each of them running its own agent concurrently. What is added is the arrangement
    §3.7's justification for preemption describes and no test has ever built - two agent questions
    queued at 5, a conflict arriving at 10 while both are unanswered, and the merge queue's own
    victim, `run.step` in the target namespace, waiting behind the landing.

    **The parent's step is started and not awaited**, which is the shape that makes the claim
    visible: `Leases.claim` holds the target's step lock for as long as it holds the lease, so this
    task sits inside `journal.step`'s `async with` - before any agent is dispatched - until the
    conflict is decided. A workflow would more usually reach that state by gathering, and §3.3 says
    a `gather` over a parent's step and a child's landing "is legal and simply does not overlap".

    The last line is the test's, and the module docstring says why: `api.run` shuts the terminal
    down on the way out, so a frame has to be read while the run is still alive.
    """
    scene = _STAGED[-1]
    lines: dict[str, str] = {LANDING_CHILD: LANDING_ROW}
    boards.append(lines)
    await run.terminal.show(board, lines=lines)

    async def answering(question: Question) -> Answer:
        """§3.7's handler, spelled as §3.7 spells it: show it, and answer with what came back."""
        asked.append(question)
        picked = await run.terminal.show(choose, question=question, priority=AGENT)
        answered.append(picked)
        return Answer(text=picked)

    first = run.worktree(FIRST_CHILD)
    second = run.worktree(SECOND_CHILD)
    landing = run.worktree(LANDING_CHILD)
    await run.step("prepare", PREPARE, commit="prepare the parent")
    await landing.step("implement", COLLIDE, commit="implement T-03")

    questions = asyncio.gather(
        first.step("ask", _asking(ASK_FIRST, answering)),
        second.step("ask", _asking(ASK_SECOND, answering)),
    )
    await scene.proceed.wait()

    outcome = await landing.integrate()
    decided.append(outcome)
    behind = asyncio.create_task(run.step("after", AFTER, commit="the parent's own next step"))
    if outcome.conflicted:
        if await run.terminal.show(conflict, outcome=outcome, priority=CONFLICT):
            await outcome.retry()
        else:
            await outcome.abort()

    await behind
    # Written into the board's own argument while both questions are still on the queue - so the
    # slot is being updated with nothing drawing it, which is §3.7's "no extra machinery".
    lines[LANDING_CHILD] = AFTER_ROW
    under.append(len(answered))
    await questions
    await scene.finish.wait()


def _point(name: str) -> EntryPoint:
    """§3.3's `probe = "agl.workflows.probe:probe"`, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{name}", group=registry.GROUP)


POINTS: Final = tuple(_point(name) for name in ("deciding", "contested"))


# --- the bundle, the terminal, and the place on disk ----------------------------------------------


@pytest.fixture
def keys() -> Typing:
    """The person, played by the suite: a real `Keys` a test types digits into."""
    return Typing()


@pytest.fixture
def terminal(keys: Typing) -> RichTerminal:
    """The real adapter over a console nobody watches, built and not yet entered - `api.run` does
    that. The width is fixed so that what a frame holds is a fact about the terminal rather than
    about the machine, though nothing here reads a rendered one."""
    return RichTerminal(Console(file=io.StringIO(), width=100), keys)


def _harness(tmp_path: Path, record: _Agent) -> container.FakeServices:
    """The all-fakes bundle: no network, no git, no process, one repository behind all three."""
    return container.fakes(
        TreesRoot(tmp_path / "trees"), files={SEEDED: SEED}, claude=_agent(record)
    )


async def _base(harness: container.FakeServices) -> str:
    """The pinned commit a run is cut from - `RunSpec.base_sha`'s shape, through the port."""
    history = harness.services.history
    return await history.resolve(await history.default_ref())


async def _head(harness: container.FakeServices, namespace: Namespace | None) -> str:
    """Where one checkout's line of work is now, asked through the port rather than of a dict.

    `WorkspaceProvider.open` is idempotent by contract, so this reopens what the run already
    provisioned and cuts nothing. `None` is the run's own `_base`, which is what children land into.
    """
    workspace = await harness.services.workspaces.open(LABEL, namespace, await _base(harness))
    return await workspace.head()


# The path below is spelled out rather than composed through `tree_layout`, for the reason
# `test_run_worktree.py` gives: a test that asked the layout where a checkout should be and then
# looked there would agree with the layout whatever either of them said.


def _target_dir(tmp_path: Path) -> Path:
    """`.trees/auth/_base/` - the run's own checkout, which is what children land into (§3.9)."""
    return tmp_path / "trees" / "auth" / "_base"


@pytest.fixture(autouse=True)
def _nothing_carried_over() -> None:
    """The module-level records, emptied before each test rather than after.

    Before, so that a test which fails leaves its evidence behind for the next reader, and so that a
    workflow that ran when nobody expected it to shows up as a list that is too long rather than as
    one somebody cleared on the way out.
    """
    for record in (asked, answered, decided, boards, under, _STAGED):
        record.clear()


def _staged() -> _Scene:
    """A fresh rendezvous, left where the workflow will pick it up."""
    scene = _Scene(proceed=asyncio.Event(), finish=asyncio.Event())
    _STAGED.append(scene)
    return scene


# --- reading what is on screen --------------------------------------------------------------------


def _text(screen: Screen[object] | None) -> str | None:
    """The body of a screen whose body is one `Text` - a question's prompt, or a conflict's summary.

    `None` for a screen that has no such body, which includes there being no screen at all, so a
    comparison against it is false rather than an error at the one moment a test is racing a redraw
    loop it does not control.
    """
    if screen is None or not isinstance(screen.body, Text):
        return None
    return screen.body.value


def _rows(screen: Screen[object] | None) -> tuple[str, ...]:
    """Every cell of a `Rows` body, flattened, in the order the view laid them out."""
    if screen is None or not isinstance(screen.body, Rows):
        return ()
    return tuple(cell.value for row in screen.body.rows for cell in row.cells)


async def _until(terminal: RichTerminal, ready: Callable[[], bool], what: str) -> None:
    """Wait for `ready`, and say what was still waiting if it never comes.

    Every wait in this file goes through here, and the deadline is the point of it: §3.7 has no
    timeouts, so a question nobody answers blocks its step forever *by design* and a test that gets
    one wrong hangs rather than fails. The message carries the two things that decide which of the
    possible mistakes it was - what the terminal last drew, and what it thinks is queued.
    """
    loop = asyncio.get_running_loop()
    expires = loop.time() + DEADLINE
    while loop.time() < expires:
        if ready():
            return
        await asyncio.sleep(TICK)
    raise AssertionError(
        f"waited {DEADLINE:.0f}s for {what}, and it never happened. The terminal last wrote "
        f"{_text(terminal.written)!r} (rows {_rows(terminal.written)}), `pending` reports "
        f"{dict(terminal.pending)}, {len(asked)} question(s) have been asked and {len(answered)} "
        f"answered. §3.7 has no timeouts anywhere, so this is a wait that would otherwise never end"
    )


# --- §3.3's conflict snippet, both branches -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_person_who_resolves_the_collision_and_retries_lands_the_work(
    tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """§3.3's snippet end to end, on the branch a person takes when they have fixed the collision.

    Every layer of this is the real one: a real landing that would not combine, the workflow's own
    view built out of `Conflict.summary`, `RichTerminal` drawing it, a reader taking a line off a
    `Keys` on a worker thread, and `Integration.retry` carrying the answer down the one path every
    landing takes - containment, then the merge gate, then the parent's chain.

    **The person's resolution is written into the target's checkout**, which is the only vocabulary
    this port has for "somebody fixed it" and is what `tests/contracts/_integration_targets.py` does
    for the same reason. It is also exactly what the person at this screen is being asked to have
    done: `Integrator.retry` "is called after something *outside this port* changed the situation,
    and this port has no opinion about what they did".

    What makes the claim unfakeable is the last assertion but one: the target holds the bytes this
    test wrote by hand, reached through one digit typed at a screen that was drawn out of the
    framework's own sentence. A `retry` the framework decided on its own, or a screen answered by
    anything but the keyboard, produces some other file.
    """
    record = _Agent()
    harness = _harness(tmp_path, record)
    services = harness.with_terminal(terminal).services

    async with asyncio.timeout(_HUNG):
        running = asyncio.create_task(
            api.run(services, PROJECT, "deciding", LABEL, (), points=POINTS)
        )
        await _until(terminal, lambda: bool(decided), "the child's landing to come back conflicted")
        outcome = decided[0]
        assert outcome.conflicted is True, (
            "two lines of work that both created one file, sharing not a line and neither having "
            "seen the other, were combined anyway - which §3.4 forbids in as many words"
        )
        assert outcome.conflict is not None
        summary = outcome.conflict.summary
        await _until(
            terminal, lambda: _text(terminal.written) == summary, "the conflict screen to be drawn"
        )

        # What a person does before pressing retry, and the port has no other word for it.
        (_target_dir(tmp_path) / CONTESTED).write_bytes(RESOLVED)
        await keys.entered(RETRY_KEY)
        await running

    assert keys.given == [RETRY_KEY], (
        f"the terminal read {keys.given!r}. One digit decided this landing, and it is the one that "
        f"picks the first response the workflow's own view offered"
    )
    assert outcome.conflicted is False, (
        f"the retry did not land: {outcome.conflict}. The collision was resolved in the target's "
        f"checkout before the button was pressed, so concluding it succeeds - and what follows a "
        f"conclusion is the same path a first landing takes"
    )
    assert outcome.head is not None
    assert await harness.services.history.contains(await _head(harness, TICKET), outcome.head), (
        f"the head this integration reports, {outcome.head!r}, does not contain the child's own "
        f"line of work - and the child is what was being integrated"
    )
    assert (_target_dir(tmp_path) / CONTESTED).read_bytes() == RESOLVED, (
        "what the person put in the target's checkout is not what the target holds. `retry` "
        "concludes what they staged, and this port has no other opinion about their work"
    )
    assert (_target_dir(tmp_path) / CHILD_ONLY).read_bytes() == CHILD_WORK, (
        "the part of the child's work nobody disagreed with is not in the target's checkout, so "
        "what landed was the resolution alone"
    )


@pytest.mark.asyncio
async def test_a_person_who_gives_up_at_the_conflict_screen_puts_the_target_back(
    tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """The same snippet, the other branch, and the one that has to leave no trace.

    `abort()` releases the hold, releases the lease and settles - and putting the head back is not
    the whole of it: whatever the attempt left in the working tree is what the next step, and the
    next person to look, would read. So both halves are asserted, and against different files: the
    contested one holds the parent's own body again, and the child's uncontested file - which the
    landing had already written into the target's checkout - is gone.

    **`conflict` stays set on the aborted outcome**, deliberately. Giving up on a landing does not
    make the collision not have happened, and the port's invariant is that exactly one of `head` and
    `conflict` is set.

    The two tests around this snippet differ in exactly one keystroke, which is the point of writing
    them as a pair: one workflow, one arrangement, one screen, and a person deciding.
    """
    record = _Agent()
    harness = _harness(tmp_path, record)
    services = harness.with_terminal(terminal).services

    async with asyncio.timeout(_HUNG):
        running = asyncio.create_task(
            api.run(services, PROJECT, "deciding", LABEL, (), points=POINTS)
        )
        await _until(terminal, lambda: bool(decided), "the child's landing to come back conflicted")
        outcome = decided[0]
        assert outcome.conflicted is True and outcome.conflict is not None
        summary = outcome.conflict.summary
        assert summary, (
            "a conflicted integration came back with nothing for the workflow's screen. `summary` "
            "is the only part of a `Conflict` guaranteed to say anything, and it is what this "
            "workflow's view is built out of"
        )
        await _until(
            terminal, lambda: _text(terminal.written) == summary, "the conflict screen to be drawn"
        )

        await keys.entered(ABORT_KEY)
        await running

    assert keys.given == [ABORT_KEY]
    assert outcome.conflicted is True, (
        "the aborted outcome cleared its conflict. Giving up on a landing is not the collision not "
        "having happened - it is the record of why nothing landed"
    )
    assert outcome.head is None, "the two-case outcome, and this is the case with no head in it"
    assert (_target_dir(tmp_path) / CONTESTED).read_bytes() == PARENT_BODY, (
        "the file the two lines of work collided over does not hold what the target held before "
        "the landing, so the abort put the head back and left the working tree as the attempt "
        "wrote it"
    )
    assert not (_target_dir(tmp_path) / CHILD_ONLY).exists(), (
        "the child's uncontested file is still in the target's checkout after the abort. `land` "
        "wrote the whole combination into that tree before it found the collision, so an abort "
        "that only moved the branch leaves the next step reading half of somebody's landing"
    )


# --- preemption, and the merge queue that does not stall ------------------------------------------


async def _reached_the_conflict(terminal: RichTerminal, keys: Typing, scene: _Scene) -> None:
    """Drive `contested` to the moment §3.7 describes: a conflict on screen, two questions behind.

    Three waits, and the order between them is the arrangement rather than a convenience.

    The first is what makes "the conflict arrived while both were still unanswered" true: the
    workflow does not integrate until both handlers have been called, and a handler reaches its
    queue without suspending after it records itself, so two entries here are two entries in the
    queue at 5.

    The second is the person. `RichTerminal` reads only while something answerable is on screen, so
    a read being in flight is the terminal genuinely sitting in front of the first question - and
    waiting for it here is what makes the preemption below happen *underneath somebody*, which is
    the case §3.7 is describing and the only one in which "preemption is not cosmetic" is a claim
    about the answer path rather than about the drawing. Without it, whether the reader had started
    its read before the conflict arrived would be a matter of which of two tasks the loop got to
    first, and the sharp case would be exercised some of the time.

    The third is the preemption itself - the conflict joins at 10 with a question already on screen,
    and the frame changes without anybody dismissing anything.
    """
    await _until(terminal, lambda: len(asked) == 2, "both agent questions to reach the terminal")
    await keys.waiting_for_a_key()
    scene.proceed.set()
    await _until(terminal, lambda: bool(decided), "the child's landing to come back conflicted")
    outcome = decided[0]
    assert outcome.conflicted is True and outcome.conflict is not None
    summary = outcome.conflict.summary
    await _until(
        terminal,
        lambda: _text(terminal.written) == summary,
        "the conflict to take the screen from the question that was on it",
    )


@pytest.mark.asyncio
async def test_a_conflict_preempts_two_agent_questions_and_the_parents_step_goes_on(
    tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """§3.7's justification for preemption, as an arrangement that fails when it is not honoured.

    "`integrate()` holds the target lease while a conflict is unresolved, so a conflict screen
    queued behind two agent questions would stall the merge queue on something unrelated. That is
    the entire justification for one level of preemption." Stage 14 made the sentence bigger than it
    reads: `Leases.claim` takes the target namespace's **step lock** behind the lease, so what an
    undecided conflict holds up is not only other landings but the parent's own next step.

    So the run below is built to have all four things true at once, and then asserts about the one
    that is not a screen:

      * two agent questions, from two children running at once, queued at 5 and unanswered;
      * a conflict at 10, which takes the screen without anybody dismissing anything;
      * the parent's `run.step`, started after the landing and therefore behind its step lock;
      * a board underneath all of it, which nothing in this test looks at.

    **The negative is proved first.** With the conflict on screen and undecided, the parent's step
    must not have reached its agent - it is inside `journal.step`'s lock, which the landing holds -
    and that wait is spent on every green run because the wait is the proof.

    **Then the positive, and it is what the whole file is for.** One digit decides the conflict, and
    the parent's step goes on **with both questions still unanswered**. That reading is taken inside
    the dispatch rather than after it, so no scheduling between the two moments can make it true. A
    terminal whose preemption was cosmetic - the conflict drawn, the answer path still owned by the
    question underneath - passes every assertion about which screen is current and hangs here,
    because nobody is ever going to answer those two questions.

    **And FIFO survives it.** The question that was displaced kept its place: what comes back when
    the conflict is decided is the first question asked, not the second. `queues.py` gets that for
    nothing by never dequeuing in order to display - "the queue was never disturbed, so it is still
    in arrival order" - and this is that property observed from a run, where the two questions came
    from two children racing each other and the order they arrived in is read rather than assumed.
    """
    record = _Agent()
    harness = _harness(tmp_path, record)
    services = harness.with_terminal(terminal).services
    scene = _staged()

    async with asyncio.timeout(_HUNG):
        running = asyncio.create_task(
            api.run(services, PROJECT, "contested", LABEL, (), points=POINTS)
        )
        await _reached_the_conflict(terminal, keys, scene)

        assert answered == [], (
            f"{answered} had been answered by the time the conflict took the screen. Both agent "
            f"questions are meant to be waiting underneath it, which is the whole arrangement §3.7 "
            f"justifies preemption with"
        )

        # The parent's own step, behind the landing's hold on the target namespace's step lock.
        await asyncio.sleep(_STALLED)
        assert AFTER.instructions not in record.dispatched, (
            "the parent's own step ran while a conflicted landing into its namespace was still "
            "undecided. `Leases.claim` takes that namespace's step lock behind the lease, because "
            "a landing writes the whole checkout, moves the branch and reads the head - which is "
            "every one of the things §3.6's serialization exists to keep two writers from doing at "
            "once, and none of the ways it goes wrong raises anything"
        )

        await keys.entered(ABORT_KEY)

        await _until(
            terminal,
            lambda: AFTER.instructions in record.dispatched,
            "the parent's step to reach its agent once the conflict had been decided",
        )
        assert record.answered_when_the_parent_stepped == 0, (
            f"the parent's step reached its agent with "
            f"{record.answered_when_the_parent_stepped} question(s) already answered, so the "
            f"landing was not what it was waiting for. The point of one level of preemption is "
            f"that the merge queue moves as soon as the *conflict* is decided - if it has to wait "
            f"for two agent questions nobody has answered, a run stalls on something entirely "
            f"unrelated to it"
        )

        prompts = {question.prompt for question in asked}
        await _until(
            terminal,
            lambda: _text(terminal.written) in prompts,
            "the displaced question to come back once the conflict was gone",
        )
        assert _text(terminal.written) == asked[0].prompt, (
            f"the screen came back to {_text(terminal.written)!r}, and the question that was "
            f"displaced by the conflict was {asked[0].prompt!r}. A displaced question keeps its "
            f"place: it was never taken out of its queue in order to be displayed, so preemption "
            f"cannot have moved it - and a person sent to the back of a queue they were already at "
            f"the front of would answer the question that arrived while theirs was off screen"
        )

        await keys.entered(RETRY_KEY)
        await keys.entered(RETRY_KEY)
        await _until(terminal, lambda: len(answered) == 2, "both agent questions to be answered")
        scene.finish.set()
        await running

    assert (_target_dir(tmp_path) / AFTERWARDS).read_bytes() == AFTER_WORK, (
        "the parent's own step left nothing in its checkout, so what went on after the conflict "
        "was decided was not the step this test was watching for"
    )
    assert len(record.heard) == 2, (
        f"{len(record.heard)} of the two agents were answered in the end. Both were, eventually, "
        f"which is what makes 'still unanswered' above a statement about *when* rather than about "
        f"a run that never got past them - the round trip itself is 15.2's and is not re-proved"
    )


@pytest.mark.asyncio
async def test_pending_is_the_plans_own_map_with_the_conflict_displayed(
    tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """§3.7's `{5: 2, 10: 0}`, produced by a run rather than declared.

    The plan states that map as a specification and the port repeats it: "the zero is the
    specification: the map reports every priority this terminal has been asked for, not only the
    ones with something waiting". Every part of it is a different decision, and this arrangement
    exercises all three at once:

      * **`5: 2`** - two agent questions are waiting, and one of them is waiting *again*, having
        been displaced from the screen by the conflict. A displaced question is queued, not lost.
      * **`10: 0`** - the priority has been asked for and its one entry is on screen, which is
        displayed rather than pending. A terminal that counted what a person is looking at would
        tell a workflow it had a backlog of one when there is nobody behind it at all.
      * **no `0:` key** - the board was shown with `show`'s default priority and registered none.
        `queues.py` took that side of the contract suite's gap #5 and `hold()` takes no priority
        argument at all, so the decision is structural; what this adds is that a workflow which
        shows a dashboard does not thereby acquire a key in a map whose whole subject is people
        being kept waiting.

    `tests/adapters/test_rich_terminal_queues.py` asserts the same map against a `Screens` built by
    hand, which is where the arithmetic belongs. What is different here is the provenance: the two
    at 5 are two agents in two children, the one at 10 is a real landing holding a real lease, and
    the map is read off the `Terminal` a workflow was handed.
    """
    record = _Agent()
    harness = _harness(tmp_path, record)
    services = harness.with_terminal(terminal).services
    scene = _staged()

    async with asyncio.timeout(_HUNG):
        running = asyncio.create_task(
            api.run(services, PROJECT, "contested", LABEL, (), points=POINTS)
        )
        await _reached_the_conflict(terminal, keys, scene)

        assert dict(terminal.pending) == {AGENT: 2, CONFLICT: 0}, (
            f"`pending` reports {dict(terminal.pending)} with a conflict on screen and two agent "
            f"questions behind it. §3.7 writes that state out as `{{5: 2, 10: 0}}`: the two are "
            f"waiting, the conflict is displayed and so counts as nothing, the priority it arrived "
            f"at keeps its key, and the board underneath contributes no key at all"
        )

        await keys.entered(ABORT_KEY)
        await keys.entered(RETRY_KEY)
        await keys.entered(RETRY_KEY)
        await _until(terminal, lambda: len(answered) == 2, "both agent questions to be answered")
        scene.finish.set()
        await running


# --- the board that comes back, and what it says when it does -------------------------------------


@pytest.mark.asyncio
async def test_the_board_that_comes_back_shows_what_changed_while_it_was_off_screen(
    tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """§3.7's "no extra machinery", from the workflow's side and with the value moving underneath.

    "The slot keeps updating while a question is displayed - `show` re-registers, the terminal
    simply isn't drawing it - so when the queue empties, the current dashboard appears."

    Three claims, and the interesting one is the middle:

      * **the queues fall back to the slot.** With the conflict decided and both questions
        answered, the board is what is on screen - the port's own fallback order, reached by a run
        rather than by a `Screens` asked directly.
      * **it shows what changed while it was off screen.** The workflow writes into the board's own
        dict at a moment when both questions are still unanswered, so the board is provably not
        being drawn; `under` records how many had been answered at that instant, which is what
        makes the timing a fact rather than a hope. A terminal that had kept the *screen* the board
        produced when it was last drawn comes back still saying `landing`, and every other assertion
        in this file still passes.
      * **with no second `show`.** The workflow registers the board once, at its first line, and
        `boards` counts registrations. That is what "no extra machinery" means: no notification when
        a question is dismissed, nothing for the workflow to re-show, and no state anywhere for the
        two to disagree about.
    """
    record = _Agent()
    harness = _harness(tmp_path, record)
    services = harness.with_terminal(terminal).services
    scene = _staged()

    async with asyncio.timeout(_HUNG):
        running = asyncio.create_task(
            api.run(services, PROJECT, "contested", LABEL, (), points=POINTS)
        )
        await _reached_the_conflict(terminal, keys, scene)
        await keys.entered(ABORT_KEY)

        await _until(
            terminal, lambda: bool(under), "the workflow to write into the board it showed once"
        )
        assert under == [0], (
            f"the board's own dict was written with {under} question(s) already answered. A "
            f"question is displayed for as long as one is queued, so a write made with none "
            f"answered is a write made while the board was off screen - which is the state this "
            f"test is about, and it is arranged rather than hoped for"
        )

        await keys.entered(RETRY_KEY)
        await keys.entered(RETRY_KEY)
        await _until(
            terminal,
            lambda: _rows(terminal.written) == (LANDING_CHILD, AFTER_ROW),
            "the board to come back saying what was written into it while it was off screen",
        )
        scene.finish.set()
        await running

    assert len(boards) == 1, (
        f"the workflow showed the board {len(boards)} times. §3.7's claim is that the dashboard "
        f"comes back with **no extra machinery** - the slot is a register that is written whether "
        f"or not anything is drawing it - so a second `show` would be the workflow doing by hand "
        f"the thing the design says it does not have to"
    )
