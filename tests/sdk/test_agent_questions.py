"""The mid-run question path, end to end: an agent asks, a person answers, the run goes on.

The framework's half of "agent questions are a callback on the Role". Both adapter halves already
exist - AGL's own MCP asking tool for Claude Code and the equivalent for Codex, and each is held to
the port by `tests/contracts/_agent_questions.py` - so what is left for this file is the part no
adapter can see: a `Role`'s handler reaching the workflow that declared it,
the answer coming back into the call the agent asked from, and the whole negotiation staying inside
**one** step and one session.

Every test below goes through `api.run`, which is not ceremony. The handler is a closure over the
workflow's own `Run`, so it does not exist until a workflow is running; and the terminal it shows on
is only legal inside the context `api.run` opens (`ports/terminal.py` makes a `show` outside it an
`InternalError`). A test that built a `Run` by hand could still exercise the callback, but it could
not exercise the thing this deliverable is about, which is that all of it composes.

## What is asserted here, and what is deliberately not

  * **The framework interposes nothing.** The question the agent produced is the object the handler
    receives, and the answer the handler produced is the object the agent receives - asserted by
    identity, in both directions, because that is the only spelling with teeth. A framework that
    normalised a `Question`, dropped an option it had no view for, or re-wrapped an `Answer` would
    satisfy every value comparison and would be an opinion about presentation in the one layer
    that is meant to have none.
  * **One session, N rounds.** The load-bearing one, and the reason it counts rather than checking
    the outcome: an approval loop that re-invokes a step is forbidden, because a fresh session per
    round "discards the reasoning that produced the proposal". A workflow loop written that way
    reaches the same final answer - it is not a wrong answer, it is a wrong bill and a lost
    argument - so the assertion is one `AgentTask`, one dispatch, one journal entry.
  * **The handler really is a closure over the `Run`.** `approving` below shows the question on
    `run.terminal` and returns what a person picked, so the answer that reaches the agent is a
    string that exists nowhere in this file except in the keystrokes a test typed. Nothing a
    handler answering from a constant, a policy or a lookup could produce.
  * **Nobody listening does not block.** `ports/agent.py` settles that edge case for the adapters;
    what is this layer's is that the framework supplies no answerer of its own when a role declares
    none - the agent is told nobody is listening, and the step records a result as though the run
    were fine. That is `sdk/roles.py`'s "the workflow's approval gate is then simply absent",
    observed rather than argued.

Not here, and each for its own reason. **`Role.requires` gaining `MID_RUN_QUESTIONS` at
declaration** is pinned by `tests/sdk/test_roles.py` in four tests and is not restated.
**A handler reaching the runner at all, with the answer's text arriving** is `tests/sdk/
test_run_step.py::test_a_roles_question_handler_reaches_the_runner_and_its_answer_returns`, one
round and prompt-only; what is added here is the two fields that test's question does not carry and
the identity that its value comparison cannot make. **Priority, preemption and the conflict screen**
are elsewhere. `priority=5` is written below because the standing example writes it and a handler
that omitted it would be modelling something no workflow does, but nothing here asserts a thing
about what it means.

## The arrangement, and why each half of it is real

**Real git and a real ledger**, for `tests/sdk/test_run_step.py`'s reasons: "one journal entry" is a
directory listing here, not a digest this file recomputed, and a run that provisions no checkout
takes no step at all.

**A real `RichTerminal`, driven by a scripted keyboard.** `container.fakes()` builds a
`HeadlessTerminal`, which refuses any `Screen[T]` with `UpstreamUnavailable` - correctly, since a
workflow needing human input genuinely cannot run with nobody there - so an interactive screen
cannot be answered on that bundle and the terminal is substituted through
`FakeServices.with_terminal`, as `tests/sdk/test_run_terminal.py` substitutes its own - the two
views of one bundle moving together, which a `dataclasses.replace` of `services` alone would not
do. The other three ports here have no sibling field and are still a plain `replace`.
**A third `Terminal` was not written *here***, and that is the decision rather than a convenience:
a hand-rolled queueing terminal in a test file would be under `tests/contracts/terminal.py`'s eye
nowhere at all, and the input port exists precisely so the real adapter can be driven without a tty.
A third implementation did arrive - `adapters/rich_terminal/scripted.py`, which
`agl.testing.answering([...])` builds - and it is a third *adapter* that runs the contract suite
rather than a mock, which is the whole difference this paragraph was about. **This file stays on
the real one deliberately**: what it grades is the engine's question path against the terminal a
person actually sits in front of, so substituting a class written for tests would take the one
implementation under test out of the test. `tests/test_testing.py` is where a scripted terminal
belongs, that file being what a workflow author can write. The keyboard is `instruments.keyboard`,
promoted out of `tests/adapters/test_rich_terminal.py` for this file and unchanged by the move.

The console is a plain `Console(file=StringIO())` and deliberately not `force_terminal=True`: that
takes `_display.py`'s appending path, with no `rich.Live` and so no process-global `sys.stdout` and
`sys.stderr` takeover inside pytest. Nothing here reads a frame - what a frame looks like is
`tests/adapters/test_rich_terminal.py`'s - so the animating path would buy a takeover and nothing
else.

**Every await is bounded.** There are no timeouts anywhere: "an unanswered question blocks its step
indefinitely, so 'stuck' and 'waiting for you' look alike from outside". That is the design, and it
makes an honest mistake in any of these tests a hang rather than a failure, so each one runs under
`asyncio.timeout` and the expiry is the failure.
"""

import asyncio
import io
import json
import subprocess
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

import pytest
from rich.console import Console

from agl import api
from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.history import GitHistory
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.rich_terminal.terminal import RichTerminal
from agl.config import container, registry
from agl.ports.agent import AgentOutcome, AgentTask, Claude, QuestionHandler, StopReason
from agl.ports.home_layout import AglHome, RunScope, step_dir
from agl.ports.ids import ProjectName, RunLabel, StepName
from agl.ports.questions import Answer, Question
from agl.ports.terminal import Choice, Response, Screen, Text, TextInput
from agl.ports.tree_layout import TreesRoot
from agl.sdk._engine.services import Services
from agl.sdk.roles import Role, role
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run, workflow
from instruments.keyboard import DEADLINE, Typing

# Marked one by one rather than through a module-level `pytestmark`, matching the rest of
# `tests/sdk/`: `asyncio_mode = "strict"` turns a missing marker into a test pytest silently
# *skips*, which is how a file like this passes without ever having awaited anything.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

STEP: Final = "decide"
"""The name every role below carries, and so the one step every workflow below takes. Named once,
because "one journal entry" is read out of `steps/<name>/` and a test naming that directory
separately from the declaration would be checking its own spelling. It is on the role, because
`run.step` carries no name of its own."""


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""


@dataclass(frozen=True)
class Summary:
    """A reporting payload: the whole of what these agents have to say, which is what they heard."""

    text: str


REPORT: Final = reporting_tool("report", "report what you decided", Summary)

PROMPT: Final = "propose, ask for approval, revise until approved, then report"
"""The standing instruction to the agent, shortened. It is never read by anything - the fake does
not read `task.instructions`, on purpose - and it is here because a role's prompt is what makes a
negotiating agent a negotiating agent rather than a detail this file invented."""

# --- what the agents ask --------------------------------------------------------------------------

ASKED: Final = Question(
    prompt="I can split this two ways. Which do you want?",
    options=("split by layer", "split by feature"),
    allow_free_text=False,
)
"""One question, carrying all three of what a `Question` can carry.

`allow_free_text=False` is the interesting field and it is why the options are two rather than none:
the port defaults it to `True`, so a framework that dropped it, defaulted it, or rebuilt the
question without it would produce something that still answers `Question(prompt=...)` correctly.
`approve` below reads it, which is what makes it visible as more than a value in a record."""

ROUNDS: Final = (
    Question(prompt="Here is a first cut of the backlog. Approve it?"),
    Question(prompt="I have folded your note in. Approve it now?"),
    Question(prompt="Last one: shall I report this?"),
)
"""Three rounds of one negotiation - propose, revise, revise - all inside one step and one session.

Three rather than two because two is the smallest number that can be a coincidence: a step invoked
twice by a workflow loop asks once per invocation, so a two-round transcript and a two-invocation
loop are the same list of questions. Three is not, and neither is one entry."""

NOBODY: Final = "<nobody was listening>"
"""What the script writes down when `ask` answers `None`. It is the fake's way of saying the port's
second edge case happened - see `adapters/claude_code/fake.py::Conversation.ask`, where `None` is
the return type rather than a sentence because a script is not a model and cannot read one."""


# --- the views a workflow shows, and the answer type they produce ---------------------------------


@dataclass(frozen=True)
class Verdict:
    """What answering one of these screens produces: the workflow's own type, in shape.

    The rule: "the workflow's own answer type carries more than this and goes on carrying it: a
    `Screen[T]` returns its `T`, and the workflow's handler maps that down to a string on the way
    out". One field here, because the mapping is what matters and not how rich the type is.
    """

    said: str


def approve(question: Question) -> Screen[Verdict]:
    """The approval screen, built out of whatever the agent asked.

    **It reads all three fields of the `Question`**, which is what makes them load-bearing rather
    than recorded: the options become the choices, in the order the agent offered them, and
    `allow_free_text` decides whether there is a field to type into at all. So the shape of the
    screen a person sees is a function of the question, and the digit that answers round one means
    something different in round two - which no view built from a constant could arrange.

    A pure function of its arguments, as every view must be: it is invoked again ten times
    a second for as long as it is on screen, and it reads nothing but what it was handed.
    """
    responses: list[Response[Verdict]] = [
        Choice(option, value=Verdict(said=option)) for option in question.options
    ]
    if question.allow_free_text:
        responses.append(TextInput("Say more", maps=lambda typed: Verdict(said=typed)))
    return Screen(body=Text(question.prompt), responses=responses)


# --- the workflows, reached through hand-constructed entry points ---------------------------------

# What each workflow saw, at module level because the workflows have to be: `EntryPoint.load`
# imports a module and reads an attribute in it, and sees no local. Emptied by `_nothing_carried
# _over` before each test and never by a workflow, so a workflow that ran when nothing asked it to
# shows up here as a list that is too long rather than as one somebody tidied away.
asked: Final[list[Question]] = []
given: Final[list[Answer]] = []
reported: Final[list[Summary]] = []


# The three workflows below share one role, and the difference this file is about is the one
# argument its factory takes. They were once three `Role(...)` literals, on the argument that "a
# factory taking `on_question=` as an argument would put that difference behind a default value in
# a signature nobody reads" - which was since decided the other way: a role *is* a
# `@role(model=…)` factory, and its parameter list is the whole of what a call site may vary. What
# survives of the objection is why the call is written out at each `run.step` below rather than
# parametrised once: the difference between these three is meant to be visible at the line that
# takes the step, which is the only line on which they differ.


@role(model=Claude.SONNET)
def deciding(*, on_question: QuestionHandler | None = None) -> Role[Summary]:
    """The one role this file drives, in its three states.

    `deciding(on_question=…)` is what a negotiating workflow steps with - the handler is a
    closure over the `Run`, so it can only arrive here as an argument - and `deciding()` is the
    same role with nothing to answer it, which is the third workflow below and the case
    `sdk/roles.py` says costs a workflow its approval gate silently.
    """
    return Role(name=STEP, instructions=PROMPT, tools=(REPORT,), on_question=on_question)


@workflow(version="1")
async def negotiating(run: Run[NoParams]) -> None:
    """A role whose handler answers from the workflow, without showing anybody anything.

    This is allowed - "the handler routes it to a view, or to a log, or answers it from a
    policy without showing anybody anything - all three are a workflow's business" - and it is the
    right shape for the two tests that are about routing and counting rather than about a person.
    A terminal in those would be a second thing able to fail.

    The `Answer` it returns is kept in `given` so that a test can ask whether the object the agent
    received is the object this produced, which value equality could not tell it.
    """

    async def on_question(question: Question) -> Answer:
        asked.append(question)
        answer = Answer(text=f"answer {len(asked)}")
        given.append(answer)
        return answer

    reported.append(await run.step(deciding(on_question=on_question)))


@workflow(version="1")
async def approving(run: Run[NoParams]) -> None:
    """The standing example, spelled out: the handler shows the question and returns what came back.

        async def approve(q: Question) -> Answer:
            return await run.terminal.show(views.approve_backlog, question=q, priority=5)

    A closure over this `Run` and nothing else, which is why `Role` can be built here and not at
    module level, and why `QuestionHandler` takes one parameter. The `Verdict` a person's response
    produced is mapped down to `Answer.text` here - at the workflow's layer, in the workflow's own
    language - because `Answer` carries one string and that mapping belongs on this side of the
    port on purpose.
    """

    async def on_question(question: Question) -> Answer:
        asked.append(question)
        verdict = await run.terminal.show(approve, question=question, priority=5)
        given.append(Answer(text=verdict.said))
        return given[-1]

    reported.append(await run.step(deciding(on_question=on_question)))


@workflow(version="1")
async def unattended(run: Run[NoParams]) -> None:
    """The same role with the handler left off, and nothing else changed.

    `sdk/roles.py` names what this costs and this is what it looks like from outside: "preflight
    passes, the run starts, and the agent asks into an adapter that must not block... The workflow's
    approval gate is then simply absent, and 'propose, ask for approval, revise until
    approved' becomes an agent approving itself."
    """
    reported.append(await run.step(deciding()))


def _point(name: str) -> EntryPoint:
    """The `probe = "agl.workflows.probe:probe"` entry point, pointed at this module."""
    return EntryPoint(name=name, value=f"{__name__}:{name}", group=registry.GROUP)


POINTS: Final = tuple(_point(name) for name in ("negotiating", "approving", "unattended"))


# --- the agent, and the one thing it is asked to do -----------------------------------------------


class _Agent:
    """What the fake was dispatched and what it was told, written down.

    A recorder here rather than on `FakeAgentRunner`, which deliberately holds no record of what it
    ran: what a test wants to know is already reachable from the script it supplied.
    """

    def __init__(self) -> None:
        self.tasks: list[AgentTask] = []
        """One entry per dispatch. A script is invoked once per `AgentRunner.run`, so the length of
        this is the number of times the framework paid for an agent, and the entries are the
        `AgentTask`s it composed - which is what "one task, one dispatch" is asked of."""

        self.heard: list[Answer | None] = []
        """Every answer the agent was given, in order, `None` included."""


def _asks(record: _Agent, *rounds: Question) -> Script:
    """An agent that asks each of `rounds` in turn and then reports what it was told.

    A negotiating agent in the only vocabulary the port has: it asks, it uses the answer, it
    asks again, and it reports once - so the step returns exactly once, at the end, and everything
    before that happened inside one session. Each answer is written into the report *in the order
    it arrived*, which is what makes "the answer came back into the round it was asked from" a
    thing the step's own return value can be read for.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        record.tasks.append(conversation.task)
        said: list[str] = []
        for question in rounds:
            answer = await conversation.ask(question)
            record.heard.append(answer)
            said.append(NOBODY if answer is None else answer.text)
        await conversation.call(REPORT.name, {"text": " then ".join(said)})
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="reported")

    return _script


# --- the repository, the bundle, and the run ------------------------------------------------------


def _git(where: Path, *argv: str) -> str:
    """One git command, for arranging. Never for the thing under test."""
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit, and no configuration from this machine.

    `tests/sdk/test_run_step.py`'s fixture and its argument: the `GIT_CONFIG_*` variables are what
    make this the same suite everywhere, and they go through `monkeypatch` so the adapter, which
    inherits the environment, sees them too.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "AGL contract")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "spec.md").write_bytes(b"the work this run was cut from\n")
    _git(work, "add", "spec.md")
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work


@pytest.fixture
def keys() -> Typing:
    """The person, played by the suite: a real `Keys` a test types digits and sentences into."""
    return Typing()


@pytest.fixture
def terminal(keys: Typing) -> RichTerminal:
    """The real adapter over a console nobody watches, built and not yet entered - `api.run` does
    that. The width is fixed so what a frame holds is a fact about the terminal and not about the
    machine, though nothing here reads one."""
    return RichTerminal(Console(file=io.StringIO(), width=100), keys)


def _services(repository: Path, tmp_path: Path, terminal: RichTerminal, script: Script) -> Services:
    """One bundle: real git, a real ledger, the real terminal, and one scripted agent.

    The composition root's fakes with four of its eight fields replaced, which is the smallest
    arrangement that puts the things this file makes claims about under a run without constructing
    eight ports by hand. `history` is real for `test_run_step.py`'s reason - a step resolves its
    base through it, and a `FakeHistory` answers about a repository that has never heard of these
    commits - and `terminal` is real because a `HeadlessTerminal` refuses every interactive screen.
    """
    trees = TreesRoot(tmp_path / "trees")
    harness = container.fakes(trees, claude=script)
    return replace(
        harness.with_terminal(terminal).services,
        store=FilesystemStore(AglHome(tmp_path / "home")),
        workspaces=GitWorkspaceProvider(repository, trees),
        history=GitHistory(repository),
    )


async def _ran(services: Services, name: str) -> None:
    """`api.run` over one of the workflows above, bounded.

    The bound is not a performance assertion and every test needs it: an unanswered question blocks
    its step forever by design - there are no timeouts - so the difference between a failing test
    and a hung suite is this line.
    """
    async with asyncio.timeout(DEADLINE):
        await api.run(services, PROJECT, name, LABEL, (), points=POINTS)


def _entries(tmp_path: Path) -> list[dict[str, object]]:
    """Everything recorded under `steps/<STEP>/`, in filename order. Empty when nothing is.

    Read as files rather than through the `Store`, because "one entry" is a claim about a directory:
    a `read_entry` at an address the test computed could only say that *that* address holds one.
    """
    directory = step_dir(AglHome(tmp_path / "home"), SCOPE, StepName(STEP))
    found = sorted(directory.glob("*.json"))
    return [json.loads(path.read_text(encoding="utf-8")) for path in found]


@pytest.fixture(autouse=True)
def _nothing_carried_over() -> None:
    """The three module-level records, emptied before each test rather than after.

    Before, so that a test which fails leaves its evidence behind for the next reader, and so that
    a workflow that ran when nobody expected it to shows up as a list that is too long rather than
    as one somebody cleared on the way out.
    """
    for record in (asked, given, reported):
        record.clear()


# --- the framework interposes nothing, in either direction ----------------------------------------


@pytest.mark.asyncio
async def test_the_question_the_agent_asked_is_the_one_the_handler_is_given(
    repository: Path, tmp_path: Path, terminal: RichTerminal
) -> None:
    """The framework "maps whatever payload the vendor produced into a `Question`, and calls
    the workflow's handler. The framework has no opinion on presentation."

    Both halves of that are asserted here as identity, which is the only spelling that can tell an
    opinion from a pass-through. `tests/sdk/test_run_step.py` already pins that a handler is
    reached and that its answer's *text* arrives; what a value comparison there cannot see is a
    framework that rebuilt either object on the way past - and rebuilding is exactly what a layer
    with an opinion does. A `Question` normalised into something a view could render, or an
    `Answer` re-wrapped to carry which option it matched, would compare equal to nothing this test
    could have written down in advance and would be a policy nobody chose.

    `ASKED` carries options and forbids free text, so the two fields most easily lost are in flight
    rather than defaulted: the port's own defaults are `()` and `True`, so a question that arrived
    stripped would still be a perfectly well-formed one.
    """
    record = _Agent()
    services = _services(repository, tmp_path, terminal, _asks(record, ASKED))

    await _ran(services, "negotiating")

    assert asked and asked[0] is ASKED, (
        f"the handler was given {asked!r}. A `Question` crosses the port as the value the "
        f"adapter built out of what the model produced, and this layer's whole job with it is to "
        f"hand it to the role's own handler - so anything but the same object is a framework that "
        f"read it, decided something about it, and passed on its own reading"
    )
    assert asked[0].options == ("split by layer", "split by feature")
    assert asked[0].allow_free_text is False
    assert record.heard and record.heard[0] is given[0], (
        f"the agent was handed {record.heard!r} and the handler returned {given!r}. The answer is "
        f"serialised back into the same live session by the adapter; a different object arriving "
        f"there is something between the two having produced an answer of its own"
    )


# --- one session, N rounds ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_rounds_of_one_negotiation_are_one_task_one_dispatch_and_one_entry(
    repository: Path, tmp_path: Path, terminal: RichTerminal
) -> None:
    """Negotiation stays inside one step and one session, asserted as a count.

    "An approval loop is **not** a workflow loop re-invoking a step. That would start a fresh agent
    session per round, discarding the reasoning that produced the proposal and re-deriving from the
    spec each time." The failure this exists to catch therefore produces the **right answer**: a
    workflow that looped over `run.step` would ask three times, be answered three times, and report
    the same approved backlog at the end. What it would cost is three sessions instead of one,
    three entries in the ledger instead of one, and the reasoning behind each proposal thrown away
    between rounds - none of which any assertion about the outcome can see.

    So the outcome is asserted last and the counts first. One `AgentTask`, because the task is
    composed inside `Steps.step`'s worker and a second one means the worker ran twice. One dispatch,
    which is the same fact read off the script: a script is entered once per `AgentRunner.run`. One
    entry under `steps/decide/`, which is the record of a step having happened and is the half a
    resume would replay.

    The transcript is the fourth assertion and it is what makes the other three about *questions*
    rather than about arithmetic: three answers, in the order they were given, inside one report.
    An answer that came back into the wrong round, or that the agent never received, shows up here
    and nowhere else.
    """
    record = _Agent()
    services = _services(repository, tmp_path, terminal, _asks(record, *ROUNDS))

    await _ran(services, "negotiating")

    assert len(record.tasks) == 1, (
        f"the agent was dispatched {len(record.tasks)} times for one step. A negotiation is N "
        f"rounds inside one session; N dispatches is a workflow loop re-invoking the step, "
        f"which reaches the same answer, bills for three agents and discards the reasoning behind "
        f"every proposal but the last"
    )
    assert len(_entries(tmp_path)) == 1, (
        f"the ledger holds {len(_entries(tmp_path))} entries under steps/{STEP}/. One step that "
        f"asked three times is one entry - the fingerprint deliberately covers the "
        f"final outcome only, and that a crash mid-negotiation re-runs the step and re-asks"
    )
    assert len(asked) == len(ROUNDS) and len(given) == len(ROUNDS), (
        f"the handler was asked {len(asked)} times and answered {len(given)}, for a negotiation of "
        f"{len(ROUNDS)} rounds. Every round is one call to the handler and one return from it"
    )
    assert all(seen is sent for seen, sent in zip(asked, ROUNDS, strict=True))
    assert all(back is made for back, made in zip(record.heard, given, strict=True))
    assert reported == [Summary(text="answer 1 then answer 2 then answer 3")], (
        f"the step returned {reported!r}. Each answer goes into the agent's report in the order it "
        f"arrived, so this is the whole exchange read back through the one thing a workflow gets: "
        f"the step's own result"
    )


# --- the handler is a closure over the Run, and answers through the terminal ----------------------


@pytest.mark.asyncio
async def test_the_handler_shows_the_question_and_the_answer_is_what_a_person_picked(
    repository: Path, tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """The whole path in one run: agent asks, workflow shows, person answers, agent carries on.

    This is the path the deliverable exists for, and every layer of it is the real one - `api.run`
    opening the terminal, a `Role` built inside a workflow with a handler closed over its `Run`,
    `run.terminal.show` registering a workflow-defined view, `RichTerminal`'s redraw loop drawing
    it, its reader taking a line off a `Keys` on a worker thread, and the `Answer` going back into
    the session the agent asked from.

    **Two rounds, and the questions differ in shape on purpose.** The first offers two options and
    forbids free text, so `approve` builds two responses and `2` picks the second of them. The
    second offers one option and allows free text, so the same view builds a choice and a field,
    and `2` now opens the field - after which what the agent is told is a sentence this test typed.
    That sentence is what makes the claim unfakeable: it exists nowhere in the framework, nowhere
    in the view and nowhere in the role, so a handler answering from a constant, a policy or the
    question's own first option cannot produce it. It is also the assertion that the `Question`'s
    fields reached the *view* and not merely the handler - the digit means two different things in
    the two rounds, and only the question can have decided which.

    `keys.entered` types and waits until the terminal has taken every line, which is what
    sequences this test against a run that is otherwise racing it: the second round cannot be
    answered before the first has been, because the terminal reads only while something answerable
    is on screen.
    """
    record = _Agent()
    first = Question(
        prompt="Which split?",
        options=("split by layer", "split by feature"),
        allow_free_text=False,
    )
    second = Question(prompt="Approve the backlog?", options=("approve",))
    services = _services(repository, tmp_path, terminal, _asks(record, first, second))

    async with asyncio.timeout(DEADLINE):
        running = asyncio.create_task(
            api.run(services, PROJECT, "approving", LABEL, (), points=POINTS)
        )
        await keys.entered("2")
        await keys.entered("2", "not yet - fold in the migration first")
        await running

    assert len(record.tasks) == 1, (
        f"the agent was dispatched {len(record.tasks)} times. Two rounds of negotiation are two "
        f"rounds inside one session, and the person answering them never left the same screen"
    )
    assert reported == [
        Summary(text="split by feature then not yet - fold in the migration first")
    ], (
        f"the step returned {reported!r}. The first half is the option a person picked out of the "
        f"two the agent offered and the second is what they typed into a field the agent's own "
        f"`allow_free_text` opened - so this string is the evidence that the answer came back "
        f"through `run.terminal.show` and not from anything the framework could have decided"
    )
    assert keys.given == ["2", "2", "not yet - fold in the migration first"], (
        f"the terminal read {keys.given!r}. Three lines: a digit for each round and the text the "
        f"second round's field opened a read for. Fewer means a screen was never drawn to be "
        f"answered; more means one was answered twice"
    )


# --- a role with no handler, whose agent asks anyway ----------------------------------------------


@pytest.mark.asyncio
async def test_an_agent_that_asks_with_no_handler_is_told_so_and_the_step_records_anyway(
    repository: Path, tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """`ports/agent.py`'s second edge case, seen from the layer that decides there is no handler.

    "If the agent asks while `on_question` is `None`, the adapter must **not** block. It tells the
    agent that no answer is available and lets it carry on with its own judgement. A run hanging on
    a question nobody is listening for is the worst outcome available, because it looks exactly like
    work." The adapters are held to that by `tests/contracts/_agent_questions.py` and it is not
    re-proved here.

    What is this layer's is the line before it: **the framework supplies no answerer of its own.**
    A `Steps.step` that defaulted `on_question` to something - a logger, a policy, a screen the
    framework composed - would satisfy the port perfectly and would be the framework answering for
    a workflow that declared no handler. The agent is told nobody is listening, so nothing did.

    And the consequence is the one `sdk/roles.py` names as the reason the capability is folded in at
    declaration: the run *finishes*. One entry, a result recorded, an exit code of zero, and the
    approval gate simply absent - "an agent approving itself. Nothing raises, nothing is logged as
    wrong, and the step reports a result." That is what a forgotten handler looks like from outside,
    and it is why forgetting one is not left to discipline.

    `keys.given` being empty is the other half: the terminal was there, entered and reading, and
    nothing was ever put in front of a person. With the run bounded, that distinguishes "no screen
    was shown" from "a screen was shown and nobody answered it", which would have hung.
    """
    record = _Agent()
    services = _services(repository, tmp_path, terminal, _asks(record, *ROUNDS))

    await _ran(services, "unattended")

    assert record.heard == [None, None, None], (
        f"the agent was handed {record.heard!r} by a run whose role declares no handler. `None` is "
        f"the fake's spelling of the port's second edge case; anything else is the framework "
        f"having answered on a workflow's behalf"
    )
    assert asked == [] and given == []
    assert keys.given == [], f"somebody was asked to type {keys.given!r} with no handler declared"
    assert reported == [Summary(text=f"{NOBODY} then {NOBODY} then {NOBODY}")]
    assert len(_entries(tmp_path)) == 1, (
        "the step recorded nothing. A run whose approval gate is absent does not fail - it "
        "succeeds, quietly, which is the whole reason `on_question` folds `MID_RUN_QUESTIONS` "
        "into `Role.requires` at declaration rather than leaving it to be remembered"
    )
