"""The mid-run question path, end to end: an agent asks, a person answers, the run goes on.

The framework's half of "a question is an ordinary tool the workflow supplies". There is no other
half any more, which is the change this file is written across: AGL used to put an asking tool on
every task on every backend and route what came back through a `QuestionHandler` on the `Role`, and
each adapter's copy of that was held to the port by `tests/contracts/_agent_questions.py`. All of it
is gone - the port member, the capability, the two vendor tools, the contract module. What is left
is what a workflow declares for itself, and this file is what says the framework does not interpose
between it and the agent.

Every test below goes through `api.run`, which is not ceremony. The tool's handler is a closure over
the workflow's own `Run`, so it does not exist until a workflow is running; and the terminal it
shows on is only legal inside the context `api.run` opens (every terminal implementation makes a
`show` outside that context an `InternalError`). A test that built a `Run` by hand could still
call the handler, but it could not exercise the thing this file is about, which is that all of it
composes.

## What is asserted here, and what is deliberately not

  * **The framework interposes nothing.** The payload the agent produced is what the handler is
    given, and the `ToolResult` the handler produced is the object the agent receives - the second
    asserted by identity, because that is the only spelling with teeth. A framework that rebuilt a
    result to carry which tool answered it, or that normalised the text, would satisfy every value
    comparison and would be an opinion in the one layer meant to have none. The first direction is a
    value comparison rather than an identity one, and the reason is the mechanism: `sdk/tools.py`'s
    `tool()` *builds* the payload dataclass out of the JSON a model sent, so there is no object on
    the agent's side for a handler to receive twice. What is asserted instead is that every field
    arrived - including the two a schema most easily defaults away.
  * **One session, N rounds.** The load-bearing one, and the reason it counts rather than checking
    the outcome: an approval loop that re-invokes a step is forbidden, because a fresh session per
    round discards the reasoning that produced the proposal. A workflow loop written that way
    reaches the same final answer - it is not a wrong answer, it is a wrong bill and a lost
    argument - so the assertion is one `AgentTask`, one dispatch, one journal entry.
  * **The handler really is a closure over the `Run`.** `approving` below shows the question on
    `run.terminal` and returns what a person picked, so the answer that reaches the agent is a
    string that exists nowhere in this file except in the keystrokes a test typed. Nothing a
    handler answering from a constant, a policy or a lookup could produce.
  * **The framework supplies no asking tool of its own.** The third workflow declares no asking
    tool and its agent has nothing to call: `task.tools` holds what the role declared and nothing
    else, and the fake refuses a call to anything else by name. Under the old mechanism this was a
    thing to *observe* - the framework put `agl_ask` on the task whatever the role said, and a role
    that declared no handler got an agent told nobody was listening. Now the absence is structural,
    and that is what this test reads.

Not here, and each for its own reason. **`Role.requires` gaining `TOOL_CALLING` from `tools`** is
pinned by `tests/sdk/test_roles.py` and is not restated. **A tool handler reaching the runner at
all, with its result arriving** is `tests/sdk/test_run_step.py`; what is added here is a whole
negotiation rather than one call, and a person at the end of it. **Priority, preemption and the
conflict screen** are elsewhere. `priority=5` is written below because the standing example writes
it and a handler that omitted it would be modelling something no workflow does, but nothing here
asserts a thing about what it means.

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
the real one deliberately**: what it grades is the engine's tool path against the terminal a person
actually sits in front of, so substituting a class written for tests would take the one
implementation under test out of the test. `tests/test_testing.py` is where a scripted terminal
belongs, that file being what a workflow author can write. The keyboard is `instruments.keyboard`,
promoted out of `tests/adapters/test_rich_terminal.py` for this file and unchanged by the move.

The console is a plain `Console(file=StringIO())` and deliberately not `force_terminal=True`: that
takes `_display.py`'s appending path, with no `rich.Live` and so no process-global `sys.stdout` and
`sys.stderr` takeover inside pytest. Nothing here reads a frame - what a frame looks like is
`tests/adapters/test_rich_terminal.py`'s - so the animating path would buy a takeover and nothing
else.

**Every await is bounded.** There are no timeouts anywhere: an unanswered question blocks its step
indefinitely, so "stuck" and "waiting for you" look alike from outside. That is the design, and it
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
from agl.ports.agent import AgentOutcome, AgentTask, Claude, StopReason, Tool, ToolResult
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome, RunScope, step_dir
from agl.ports.ids import ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.terminal import Choice, Response, Screen, Text, TextInput
from agl.ports.tree_layout import TreesRoot
from agl.sdk._engine.services import Services
from agl.sdk.roles import Role, role
from agl.sdk.tools import describe, reporting_tool, tool
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

# --- the asking tool, which is the workflow's and not the framework's -----------------------------

@dataclass(frozen=True, slots=True)
class Asked:
    """The payload the agent fills in to ask something, and the whole of what a schema carries.

    Three fields because a `Question` has three, and the two with defaults are the interesting
    ones: they are what a derived schema most easily loses, and `approve` below reads both. A
    payload dataclass is how a workflow says what it will accept - `sdk/tools.py` derives the schema
    from it, refuses a payload that does not fit before the handler runs, and hands the handler the
    built instance - so this class is this workflow's half of the vocabulary the two vendor asking
    tools used to carry twice.
    """

    question: str = describe("What you are asking, in full, in your own words.")

    options: tuple[str, ...] = describe(
        "The answers you are suggesting, if any, written as answers rather than as labels.",
        default=(),
    )

    allow_free_text: bool = describe(
        "Whether an answer other than the ones you offered is acceptable.", default=True
    )

ASK: Final = "ask_the_operator"
"""The tool's name, which is the workflow's own. Nothing in AGL knows it, which is the point: the
old `mcp__agl_ask__ask` was a constant in two adapters and reached every task ever dispatched."""

NO_QUESTION: Final = "That call asked nothing: write out what you are asking and call again."
"""What a blank question comes back as. A *rejection* and not a raise, because
`Question.__post_init__` refuses an empty prompt and an exception out of a tool handler ends the
run - so a model that sent a blank question would kill the step over a correctable mistake."""

# --- the views a workflow shows, and the answer type they produce ---------------------------------

@dataclass(frozen=True, slots=True)
class Question:
    """What this file's workflow maps an agent's payload into, declared here because it is its own.

    **AGL has no question type and this is not a stand-in for one.** There was one in `ports/` and
    a facade over it on the SDK's front door; both are gone, and `Question` and `Answer` now live in
    `workflows/fix/questions.py`, beside the tool that asks and the view that renders - the same
    move `ask_the_operator` made, one layer down. Importing that workflow's copy here would be an
    SDK suite reaching into a shipped workflow for a vocabulary the framework is being asserted not
    to have, on the one file whose whole thesis is that it has none. So this is a throwaway, three
    fields wide because `Asked` above is, and it is what `approve` renders.

    **The two refusals are load-bearing rather than decoration.** `_asking` below guards a blank
    question and normalises the offer-nothing-and-refuse-free-text pair, and both of those lines are
    written *because* a question nobody could answer raises rather than arriving on screen. A
    stand-in that accepted anything would leave the guard unexplained, the paragraph arguing for it
    untrue, and a step that a blank question should have corrected passing either way.
    """

    prompt: str

    options: tuple[str, ...] = ()

    allow_free_text: bool = True

    def __post_init__(self) -> None:
        if not self.prompt:
            raise ValueError("a question with an empty prompt asks nothing and shows nothing")
        if not self.options and not self.allow_free_text:
            raise ValueError("that question offers no options and forbids free text")

@dataclass(frozen=True)
class Verdict:
    """What answering one of these screens produces: the workflow's own type, in shape.

    The rule: the workflow's own answer type carries more than a string and goes on carrying it -
    a `Screen[T]` returns its `T`, and the workflow's handler maps that down to the text a tool
    result carries on the way out. One field here, because the mapping is what matters and not how
    rich the type is.
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
asked: Final[list[Asked]] = []
given: Final[list[ToolResult]] = []
reported: Final[list[Summary]] = []

# The three workflows below share one role, and the difference this file is about is the one
# argument its factory takes. A role *is* a `@role(model=…)` factory, and its parameter list is the
# whole of what a call site may vary - so the asking tool arrives the way every other override
# does, and the call is written out at each `run.step` below rather than parametrised once, because
# the difference between these three is meant to be visible at the line that takes the step.

@role(model=Claude.SONNET)
def deciding(*, ask: Tool | None = None) -> Role[Summary]:
    """The one role this file drives, in its three states.

    `deciding(ask=…)` is what a negotiating workflow steps with - the tool's handler is a closure
    over the `Run`, so it can only arrive here as an argument - and `deciding()` is the same role
    with nothing to ask through, which is the third workflow below.

    `Role[Summary]` is written out because the display is mixed: a list holding a `ReportingTool`
    and a plain `Tool` does not solve for `P`, which `tests/sdk/test_roles.py` pins in both
    directions. The explicit parameter is that file's own sanctioned fallback, and it is checked
    there rather than believed.
    """
    return Role[Summary](
        name=STEP, instructions=PROMPT, tools=[REPORT] if ask is None else [REPORT, ask]
    )

def _asking(run: Run[NoParams], *, on_screen: bool) -> Tool:
    """This workflow's asking tool: a payload dataclass, a handler, and one `tool()` call.

    Two shapes behind one signature, because two of the three workflows below want a handler that
    answers from the workflow itself - allowed, and the right shape for the tests that are about
    routing and counting rather than about a person, where a terminal would be a second thing able
    to fail - and one wants the standing example spelled out:

        return await run.terminal.show(views.approve_backlog, question=q, priority=5)

    The `Verdict` a person's response produced is mapped down to the tool result's text here, at
    the workflow's layer and in the workflow's own language, because a `ToolResult` carries one
    string and that mapping belongs on this side of the port on purpose.

    The blank-question guard is the third thing every asking tool owes and the one that is easy to
    miss: `Question.__post_init__` raises on an empty prompt, a raise out of a handler ends the run,
    and "the model sent a blank question" is a correctable mistake rather than a reason to throw a
    session away. So it comes back as a rejection, which is what the deleted framework tool did.
    """

    async def answered(sent: Asked) -> ToolResult:
        asked.append(sent)
        if not sent.question.strip():
            return ToolResult(text=NO_QUESTION, rejected=True)
        question = Question(
            prompt=sent.question,
            options=sent.options,
            allow_free_text=sent.allow_free_text or not sent.options,
        )
        if on_screen:
            verdict = await run.terminal.show(approve, question=question, priority=5)
            given.append(ToolResult(text=verdict.said))
        else:
            given.append(ToolResult(text=f"answer {len(asked)}"))
        return given[-1]

    return tool(ASK, "ask the person running this task, and wait for their answer", Asked, answered)

@workflow(version="1")
async def negotiating(run: Run[NoParams]) -> None:
    """A role whose asking tool answers from the workflow, without showing anybody anything.

    This is allowed - the handler routes the question to a view, or to a log, or answers it from a
    policy without showing anybody anything, and all three are a workflow's business.
    """
    reported.append(await run.step(deciding(ask=_asking(run, on_screen=False))))

@workflow(version="1")
async def approving(run: Run[NoParams]) -> None:
    """The standing example: the handler shows the question and returns what came back."""
    reported.append(await run.step(deciding(ask=_asking(run, on_screen=True))))

@workflow(version="1")
async def unattended(run: Run[NoParams]) -> None:
    """The same role with the asking tool left off, and nothing else changed."""
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

        self.heard: list[ToolResult] = []
        """Every result the agent was given, in order."""

        self.refused: list[InputError] = []
        """Every call the fake refused outright, which is what a tool nobody declared looks like."""

def _payload(question: Question) -> dict[str, JsonValue]:
    """One question as the JSON a model would send, which is what crosses the port.

    Written out by hand rather than built from `Asked`, for `sdk/testing.py`'s reason: a session
    carries JSON, the schema is derived from the payload type precisely so the model is shown the
    shape, and a call carrying an already-built payload would be testing a conversion no session
    performs.
    """
    return {
        "question": question.prompt,
        "options": list(question.options),
        "allow_free_text": question.allow_free_text,
    }

def _asks(record: _Agent, *rounds: Question) -> Script:
    """An agent that asks each of `rounds` in turn and then reports what it was told.

    A negotiating agent in the only vocabulary the port has: it calls a tool, it uses the answer, it
    calls again, and it reports once - so the step returns exactly once, at the end, and everything
    before that happened inside one session. Each answer is written into the report *in the order it
    arrived*, which is what makes "the answer came back into the round it was asked from" a thing
    the step's own return value can be read for.

    A call to a tool the task does not declare is an `InputError` out of the fake, and it is caught
    here rather than left to end the run: the third workflow below declares no asking tool, and what
    that refusal says by name is the assertion that test makes.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        record.tasks.append(conversation.task)
        said: list[str] = []
        for question in rounds:
            try:
                result = await conversation.call(ASK, _payload(question))
            except InputError as refused:
                record.refused.append(refused)
                break
            record.heard.append(result)
            said.append(result.text)
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

# --- what the agent asked ------------------------------------------------------------------------

ASKED: Final = Question(
    prompt="I can split this two ways. Which do you want?",
    options=("split by layer", "split by feature"),
    allow_free_text=False,
)
"""One question, carrying all three of what a `Question` can carry.

`allow_free_text=False` is the interesting field and it is why the options are two rather than none:
the derived schema defaults it to `True`, so a framework - or a payload walker - that dropped it
would produce something that still answers `Asked(question=...)` correctly. `approve` reads it,
which is what makes it visible as more than a value in a record."""

ROUNDS: Final = (
    Question(prompt="Here is a first cut of the backlog. Approve it?"),
    Question(prompt="I have folded your note in. Approve it now?"),
    Question(prompt="Last one: shall I report this?"),
)
"""Three rounds of one negotiation - propose, revise, revise - all inside one step and one session.

Three rather than two because two is the smallest number that can be a coincidence: a step invoked
twice by a workflow loop asks once per invocation, so a two-round transcript and a two-invocation
loop are the same list of questions. Three is not, and neither is one entry."""

# --- the framework interposes nothing, in either direction ----------------------------------------

@pytest.mark.asyncio
async def test_the_payload_the_agent_sent_is_the_one_the_handler_is_given(
    repository: Path, tmp_path: Path, terminal: RichTerminal
) -> None:
    """The JSON a model produced arrives at the workflow's handler as its own payload type, whole.

    Both directions are asserted, and they are asserted differently because the mechanism is not
    symmetric. Outbound there is nothing to compare by identity: `tool()` builds the payload out of
    the mapping the adapter handed it, so what the handler receives is a fresh `Asked` either way.
    What a test can see is whether every field survived - and `ASKED` carries the two that are most
    easily lost, `options` and an `allow_free_text` the schema defaults to `True`, so a payload that
    arrived stripped would still be a perfectly well-formed one.

    Inbound the identity is available and is the only spelling with teeth. `tests/sdk/
    test_run_step.py` already pins that a handler is reached and that its result's *text* arrives;
    what a value comparison there cannot see is a framework that rebuilt the `ToolResult` on the way
    past - which is exactly what a layer with an opinion does.
    """
    record = _Agent()
    services = _services(repository, tmp_path, terminal, _asks(record, ASKED))

    await _ran(services, "negotiating")

    assert asked == [
        Asked(question=ASKED.prompt, options=ASKED.options, allow_free_text=False)
    ], (
        f"the handler was given {asked!r}. A payload crosses the port as the mapping the adapter "
        f"read off its backend, `tool()` builds the workflow's own class out of it, and this "
        f"layer's whole job with it is to hand that to the handler the role declared - so a "
        f"missing field is either a schema that never asked for it or a walker that dropped it"
    )
    assert record.heard and record.heard[0] is given[0], (
        f"the agent was handed {record.heard!r} and the handler returned {given!r}. A tool result "
        f"is serialised back into the same live session by the adapter; a different object "
        f"arriving there is something between the two having produced an answer of its own"
    )

# --- one session, N rounds ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_three_rounds_of_one_negotiation_are_one_task_one_dispatch_and_one_entry(
    repository: Path, tmp_path: Path, terminal: RichTerminal
) -> None:
    """Negotiation stays inside one step and one session, asserted as a count.

    An approval loop is **not** a workflow loop re-invoking a step. That would start a fresh agent
    session per round, discarding the reasoning that produced the proposal and re-deriving from the
    spec each time. The failure this exists to catch therefore produces the **right answer**: a
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
        f"the handler was called {len(asked)} times and answered {len(given)}, for a negotiation "
        f"of {len(ROUNDS)} rounds. Every round is one call to the handler and one return from it"
    )
    assert [sent.question for sent in asked] == [round.prompt for round in ROUNDS]
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
    """The whole path in one run: agent calls, workflow shows, person answers, agent carries on.

    Every layer of it is the real one - `api.run` opening the terminal, a `Role` built inside a
    workflow carrying a tool whose handler is closed over its `Run`, `run.terminal.show`
    registering a workflow-defined view, `RichTerminal`'s redraw loop drawing it, its reader taking
    a line off a `Keys` on a worker thread, and the result going back into the session the agent
    called from.

    **Two rounds, and the questions differ in shape on purpose.** The first offers two options and
    forbids free text, so `approve` builds two responses and `2` picks the second of them. The
    second offers one option and allows free text, so the same view builds a choice and a field,
    and `2` now opens the field - after which what the agent is told is a sentence this test typed.
    That sentence is what makes the claim unfakeable: it exists nowhere in the framework, nowhere
    in the view and nowhere in the role, so a handler answering from a constant, a policy or the
    question's own first option cannot produce it. It is also the assertion that the payload's
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

# --- a role that declares no asking tool, whose agent tries anyway -------------------------------

@pytest.mark.asyncio
async def test_a_role_with_no_asking_tool_leaves_the_agent_nothing_to_call(
    repository: Path, tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """**The framework supplies no asking tool of its own**, read off the task it composed.

    This used to be a thing to observe rather than a structural fact. AGL put `agl_ask` on every
    task on every backend, so a role that declared no `on_question` still got an agent that could
    call it - and what came back was a sentence telling the agent nobody was listening, after which
    the run *finished*, the approval gate silently absent, "propose, ask for approval, revise until
    approved" having become an agent approving itself.

    Now the tool is the workflow's. `task.tools` holds `REPORT` and nothing else, and the fake
    refuses a call to `ask_the_operator` by name because the task declares no such tool - which is
    the fake saying what a real backend would have said differently and meant the same by: there is
    no tool there. A framework that supplied one of its own would show up here as a second entry in
    `task.tools`, and the refusal would never happen.

    The rest of the run is the part that did not change. Nothing raises, the step records, the exit
    code is zero, and a workflow that forgot its asking tool gets a step that ran without ever
    consulting anybody. What is different is where a reader looks for the omission: at the `Role`
    the workflow built, in the workflow's own file, rather than at a keyword nobody typed.

    `keys.given` being empty is the other half: the terminal was there, entered and reading, and
    nothing was ever put in front of a person. With the run bounded, that distinguishes "no screen
    was shown" from "a screen was shown and nobody answered it", which would have hung.
    """
    record = _Agent()
    services = _services(repository, tmp_path, terminal, _asks(record, *ROUNDS))

    await _ran(services, "unattended")

    assert [declared.name for declared in record.tasks[0].tools] == [REPORT.name], (
        f"the task carried {[declared.name for declared in record.tasks[0].tools]}. A role's tools "
        f"are the whole of what an agent may call, and a framework that added one of its own would "
        f"be answering for a workflow that declared nothing"
    )
    assert len(record.refused) == 1 and ASK in str(record.refused[0]), (
        f"the fake refused {record.refused!r} for a script that called {ASK!r} against a task "
        f"declaring no such tool. One refusal, naming it, is what 'there is no asking tool here' "
        f"looks like from inside a session"
    )
    assert asked == [] and given == []
    assert keys.given == [], f"somebody was asked to type {keys.given!r} with no asking tool"
    assert reported == [Summary(text="")]
    assert len(_entries(tmp_path)) == 1, (
        "the step recorded nothing. A run whose approval gate is absent does not fail - it "
        "succeeds, quietly, and what a reader has to notice is a `tools=` that is missing a tool"
    )
