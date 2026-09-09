"""The acceptance criterion, written the way the person it is for would write it.

> A trivial workflow written against the harness runs green with no network and no git.

**So this file is deliberately not a fixture.** Everything above the first test is what a workflow
author writes and nothing else: a params dataclass of `arg()` fields, a payload dataclass, a
reporting tool, three roles, two screens, and four `@workflow` functions. Every import of AGL is one
line - `agl.sdk` for the workflow and `agl.testing` for the test - and nothing here reaches into
`agl.ports`, `agl.sdk._engine`, `agl.config` or `agl.adapters` except in the two places that are
about the escape hatch and say so, plus `tree_layout.run_branch` in the last section, which has to
name the branch a run's commits land on in order to say that one run's `commit=` left nothing on it.
If any of that had needed a third import or a piece of framework knowledge, the harness would have
been wrong and the fix would have been in the harness.

The four things the deliverable asks for, one test each and in order: a workflow runs to completion
on fakes; a scripted agent's reported payload comes back as the step result; a scripted question
reaches a workflow-defined screen and the answer returns into the same session; and an interrupted
run resumes without redoing completed steps. The rest of the file is the properties those four
rest on, the refusals the harness makes, and a last section for the keywords it takes.

## Every keyword is passed by something here, and that is a rule rather than a tidy-up

`harness()` takes six and the two operations take one each, and a keyword no test ever passes is a
keyword wired by inspection - which is not the care the rest of the SDK gets, and matters more here
than elsewhere because every end-to-end test elsewhere is built on this module. `agent=`,
`files=` and `terminal=` are passed by the tests above; the last section covers the other five,
each driven through the thing that keyword changes rather than read back off the harness, since
reading it back would measure an assignment and not the wiring. `interrupt_after=` on a resume
takes two tests, because one of them can measure the arming and neither can measure both that and
what the count is counted from.

## What each test can fail on, because a green harness test proves nothing by itself

  * **The replay assertion counts agent dispatches**, not entries, and it counts them across both
    invocations. A replay has no observable difference from a re-run that happens to produce the
    same answer other than that the worker was not called - so `seen` below is the instrument, and
    it lives in the author's own `Agent` function, which is exactly where the agent fakes say a
    test's knowledge belongs ("what a test wants to know is already held by the tool handlers it
    supplied itself" - `adapters/claude_code/fake.py` and its OpenAI twin).
  * **The payload assertion reads the ledger** through `harness.recorded`, and the value it compares
    is one nothing in the framework could have invented: it is the mapping this file's own agent
    handed to the reporting tool.
  * **The question assertion reads what a person picked.** The answer that reaches the agent gets
    there only by a gesture spent on a screen the *workflow* built out of the agent's own question,
    so nothing a handler answering from a constant could produce would satisfy it - the script says
    "the second response", and which string that is was decided by the view under test.

## The place this used to not be author-shaped, and what closed it

`container.fakes()` builds a `HeadlessTerminal`, which refuses every `Screen[T]` with
`UpstreamUnavailable` - correctly, since a workflow needing human input cannot run with nobody
there. AGL once shipped no second input-capable `Terminal`, so answering a screen meant the real
`RichTerminal` over a `Keys` of the test's own, which here was
`instruments.keyboard.Typing` - a module inside this repository that a workflow author outside it
does not have, driving an adapter class a workflow may not reach past the SDK for. That was
reported as a gap rather than papered over, and closed since: `testing.answering([...])` is a third
implementation that runs `tests/contracts/terminal.py`'s input-capable half, so the seam is a list
of gestures rather than a tty.

**Both question tests are written on it**, which is the point rather than a tidy-up: this file is
what an author can write on a `pip install agents-gl`, and a test here that still needed a keyboard
of AGL's own would be measuring something they cannot have. Everything else in the two was always
theirs - the screen is a view of theirs, the handler is a closure over their `Run`, and the
assertion is about their workflow.

## Every await is bounded

There are no timeouts anywhere - "an unanswered question blocks its step indefinitely" - so a
mistake in a test that answers a screen is a hang rather than a failure, and `answering()` says so
in as many words: a question with no gesture left waits exactly as a real terminal with nobody at
it does. The two that answer a screen therefore run under `asyncio.timeout`; the rest cannot block,
there being nobody to wait for.
"""

import asyncio
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final
import pytest
from agl import testing
from agl.adapters.claude_code.fake import Conversation, Script
from agl.config import container
from agl.ports.agent import AgentOutcome, StopReason
from agl.ports.errors import InputError
from agl.ports.tree_layout import TreesRoot, run_branch
from agl.sdk import (
    ActivityReporter,
    Choice,
    Claude,
    OpenAI,
    Restriction,
    Role,
    Row,
    Rows,
    Run,
    Screen,
    Text,
    Tool,
    ToolResult,
    arg,
    describe,
    reporting_tool,
    role,
    tool,
    workflow,
)
from agl.testing import Agent, AgentTask, Call, Press, Recorded, Reply

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

DEADLINE: Final = 5.0
"""Seconds a test that answers a screen is allowed to take, and the whole of why it exists is that
there are no timeouts: an exhausted script waits forever, exactly as a real terminal with nobody at
it does, so a scripting mistake is a hang rather than a failure. Generous, because it is not a
performance assertion - these runs are in-memory and take milliseconds - and it fires only when
something is genuinely never going to be answered. `remaining` catches the opposite mistake, a
script the run never fully spent, and it is a comparison rather than a wait."""

# --- what a workflow author writes -----------------------------------------------------------

@dataclass(frozen=True)
class DemoParams:
    """The params shape: named flags, no positionals. `agl run demo -n test -r "add oauth"`."""

    request: str = arg("-r", "--request", help="what to build")

@dataclass(frozen=True)
class Findings:
    """What the review reports through its tool, and therefore what that step's result is."""

    summary: str
    high: int

REPORT: Final = reporting_tool("report_findings", "report what the review found", Findings)

@dataclass(frozen=True)
class Request:
    """What the run was asked for, as a type a role declares: an input is an instance of one."""

    text: str

@dataclass(frozen=True)
class Note:
    """A review's findings handed back to the role that implements, on the second pass."""

    text: str

@role(model=Claude.SONNET, accepts=(Note,))
def implement(*, watch: ActivityReporter | None = None) -> Role:
    """An effect role: no reporting tool, so the step's result is `null` and its effect is
    commits.

    `accepts=(Note,)` is a permission and not a demand: `demo` steps this role twice, once with
    nothing and once with the note the review produced, and both are calls this declaration allows.
    The prompt names `{{Note}}` all the same, because the declaration is checked against the prompt
    and not against a call - the first step renders `Not provided` there and the second the note.

    `watch` is `decide(ask=...)`'s shape one field over and is there for the same reason: what an
    author watches a run on is built inside their workflow, so a reporter cannot be written at this
    level either. Omitted, the role reports to nobody, which is how `demo` and `landing` step it.
    """
    return Role(
        name="implement",
        instructions="implement what the request asks for. Earlier findings: {{Note}}",
        on_activity=watch,
    )

@role(model=OpenAI.SOL, accepts=(Request,))
def review() -> Role[Findings]:
    """A reporting role, on the other provider - `fix`'s shape: Claude implements, OpenAI
    reviews. Paired below with a step that passes no `commit=`, which is what a read-only role is
    owed."""
    return Role(
        name="review",
        instructions="review the worktree against {{Request}} and report what you found",
        restrictions={Restriction.NO_VCS_WRITES},
        tools=[REPORT],
    )

@role(model=Claude.SONNET)
def decide(*, ask: Tool | None = None) -> Role[Findings]:
    """The role the two question tests use, and the one factory here with a parameter.

    An asking tool's handler is a closure over the workflow's own `Run`, so the tool cannot be
    written at this level - which is exactly what a factory parameter is for: `decide()` is what a
    workflow declares and `decide(ask=...)` is what it steps with, and nothing else about this role
    is reachable from either call.

    `Role[Findings]` is written out because the display is mixed - a list holding a `ReportingTool`
    and a plain `Tool` does not solve for `P`, and `tests/sdk/test_roles.py` calls the explicit
    parameter the sanctioned fallback."""
    return Role[Findings](
        name="decide",
        instructions="propose something, ask whether to go ahead, then report what was decided",
        tools=[REPORT] if ask is None else [REPORT, ask],
    )

@dataclass(frozen=True, slots=True)
class Asked:
    """The payload of the asking tool `asking` supplies. AGL declares none, so a workflow does.

    Two fields, both described, because `describe()` is what puts a sentence beside a field name in
    the derived schema - which is the whole of what the model reads to know what belongs there.
    """

    question: str = describe("What you are asking, in full.")

    options: tuple[str, ...] = describe("The answers you are suggesting.", default=())

ASK: Final = "ask_the_operator"
"""What this file's workflow calls its asking tool. A workflow's own name for its own tool: the
framework supplies none and so knows none."""

@dataclass(frozen=True, slots=True)
class Question:
    """What `asking`'s handler maps a payload into, and what `approve` renders. Also its own.

    The framework has no question type either, and it is worth being explicit about why this one is
    declared here rather than imported. There was a `ports/questions.py` and an `agl.sdk.Question`
    re-exporting it, and both are gone: no port ABC spoke those types and no adapter named them, so
    they went where the tool that asks went, into `workflows/fix/questions.py`. This file is what a
    *workflow author* can write, so what it writes is what an author writes - a payload class, a
    view, a value type between them - and reaching into a shipped workflow for the middle one would
    be the one step of that an author cannot copy.

    Three fields: the two `Asked` carries, plus the one this workflow pins for itself. It refuses
    nothing, and that is deliberate rather than an omission - every screen here is built out of
    options an agent supplied, so there is no unanswerable question for a `__post_init__` to catch.
    What a refusal is worth, and what a view rests on it for, is a claim about the workflow that
    needs one, so it belongs to that workflow's own suite rather than here.
    """

    prompt: str

    options: tuple[str, ...] = ()

    allow_free_text: bool = True

@dataclass(frozen=True, slots=True)
class Answer:
    """What answering one of these screens produces. One string, and the workflow's own type.

    Frozen, so two built from the same option compare equal and `answers` below can say *which*
    answer came back rather than only that something did - which is what makes a keystroke
    traceable to the `Choice` it picked.
    """

    text: str

def approve(question: Question) -> Screen[Answer]:
    """The screen the agent's question is shown on. A pure function of what it was handed.

    Its options become the choices in the order the agent offered them, so the digit that answers
    this screen means whatever that question's second option said.
    """
    return Screen(
        body=Text(question.prompt),
        responses=[Choice(option, value=Answer(option)) for option in question.options],
    )

def a_board(lines: list[str], request: str) -> Screen:
    """The other screen: what the run was asked for, and what its agent last said it was doing.

    Passive - no responses - so it goes in the slot and nobody is waited for. It takes the author's
    own list and not the `Run`, and that is the whole of what there is to know about watching one: a
    reporter writes wherever the workflow points it, and the framework keeps no copy for a `Run` to
    hand back. Blank until something is reported, an empty cell being the honest thing to show for
    an agent that has not said anything yet.
    """
    return Screen(Rows([Row("request", request), Row("agent", lines[-1] if lines else "")]))

@workflow
async def demo(run: Run[DemoParams]) -> None:
    """Implement, then review what was implemented, and repair what the review found.

    `fix`'s shape at its smallest, including the naming: the repair runs `implement()` a second
    time, and since `run.step` carries no name of its own the two land under one `steps/implement/`
    - which is why `harness.recorded` below reads `implement`, `review`, `implement` rather than
    naming a third step. Their inputs differ, so they are two digests.
    """
    await run.step(implement(), commit=f"implement {run.params.request}")
    findings = await run.step(review(), Request(run.params.request))
    if findings.high:
        await run.step(implement(), Note(findings.summary), commit="address the review")

@workflow
async def asking(run: Run[DemoParams]) -> None:
    """One step whose agent stops to ask, answered by a person at a screen this workflow owns.

    The asking tool is built here rather than at module level for the reason its handler is a
    closure: `run.terminal` is this run's, and a tool declared beside the role would have no run to
    show anything on.
    """

    async def answered(sent: Asked) -> ToolResult:
        question = Question(prompt=sent.question, options=sent.options, allow_free_text=False)
        asked.append(question)
        picked = await run.terminal.show(approve, question=question, priority=5)
        answers.append(picked)
        return ToolResult(text=picked.text)

    await run.step(decide(ask=tool(ASK, "ask whether to go ahead", Asked, answered)))

@workflow
async def landing(run: Run[DemoParams]) -> None:
    """One child worktree, one committing step, one integration - a run's shape at its smallest.

    Here because a landing is the only thing that runs a build: the framework runs exactly one
    build, the merge gate, inside `integrate()` - so a workflow that never integrates never reaches
    the project's build command, and a test about which command the harness carries has to take a
    run all the way to a landing to see one.
    """
    ticket = run.worktree("T-01")
    await ticket.step(implement(), commit=f"implement {run.params.request}")
    outcome = await ticket.integrate()
    verdict = outcome.verdict
    gated.append((outcome.conflicted, "" if verdict is None else verdict.output))

@workflow
async def watching(run: Run[DemoParams]) -> None:
    """One step with the board up, which is the whole of how a workflow watches its own agent.

    The board goes up before the step and is never shown again: `show` registers this function
    against the list rather than the `Screen` it returns here, so the line the step reports reaches
    a screen put up while there was nothing on it, with no second `show` and no notification of any
    kind. That registration is `tests/sdk/test_run_terminal.py`'s claim; what this workflow adds is
    the shape it has from the side an author writes it on.
    """
    await run.terminal.show(a_board, lines=watched, request=run.params.request)
    await run.step(implement(watch=watched.append), commit=f"implement {run.params.request}")

asked: Final[list[Question]] = []
"""Every question this file's workflows were asked, at module level because the workflows are:
an entry point imports a module and reads an attribute in it, and sees no local of a test."""

answers: Final[list[Answer]] = []
"""What the person at the screen picked, as the workflow's own handler produced it.

The instrument for "the screen was `approve`'s": a `Choice`'s value is built from
`question.options[n]`, so an `Answer` here holding the second option is a keystroke that went
through the view this file wrote and came back as the type it declared."""

gated: Final[list[tuple[bool, str]]] = []
"""What the merge gate said about `landing`'s one integration: whether the landing was refused,
and the build output a person would be reading on the conflict screen.

Two plain values and not the `Integration` itself, for `answers`' reason: what an author asserts
on is what their own workflow saw, and a framework type parked at module level here would be a
name this file has to import in order to read a `bool` and a `str` back out of it."""

watched: Final[list[str]] = []
"""Every line `watching`'s agent reported, as the reporter its role carries was handed them.

The workflow's own cell and not the framework's: there is nowhere else one could be, `Role` being
the only thing that carries a reporter and `run.step` handing it to the adapter unwrapped. A list
rather than the one string a board shows, so that "in the order they arrived" stays sayable."""

# --- the agent, which is the author's own function -------------------------------------------

SUMMARY: Final = "one thing worth changing"
PROPOSAL: Final = "Shall I go ahead with the change I proposed?"
GO_AHEAD: Final = "go ahead"
NOT_YET: Final = "not yet"
LANDED: Final = "landed.py"
"""What `landing`'s agent writes into the child's checkout, so `commit=` records something and the
integration has work to carry. Top level in the tree, there being no directory to make first."""

EDITING: Final = "Edit: src/a.py"
"""What this file's implementer says it is doing, in the shape a serving adapter's own line has.

Named where the review's is left a literal, because this one is spelled at both ends - the agent
that reports it and the board that shows it - and two copies are free to disagree. `translate.py`
in each agent adapter is where the real ones are formed, a tool's name and its subject, and nothing
between there and a board parses one: what is on screen is what the backend said, character for
character."""

def _agent(seen: list[str], *, high: int = 0) -> Agent:
    """What every role's agent does, and a record of which of them ran.

    **There is no step name on an `AgentTask`**, so this keys on the reporting tool the role
    declared - which is the sharpest of the handles, an author having named that tool themselves.
    The model would do as well and is how `fix` will split its two roles.

    `seen` is the whole instrument of the replay test below: a replayed step returns its stored
    value without running anything, so a name appearing twice across a run and a resume is a step
    that was paid for twice.

    `high` is what the review reports, and `demo`'s third step is behind it - so an agent that
    finds something is how this file gets a three-step run out of a two-step workflow, which is
    what a resume with a kill point of its own needs to have something left to abandon.
    """

    def agent(task: AgentTask) -> Reply:
        if any(tool.name == REPORT.name for tool in task.tools):
            seen.append("reporting")
            return Reply(
                activity=["Read: src/a.py"],
                calls=[Call(REPORT.name, {"summary": SUMMARY, "high": high})],
                says="reviewed it",
            )
        seen.append("effect")
        return Reply(activity=[EDITING], says="implemented it")

    return agent

def _building() -> Agent:
    """An agent that leaves a file behind, which is what gives a landing something to land.

    Writing into `task.workspace` is the author's own code and not AGL's: a `Reply` says what the
    agent *reported*, and what it did is whatever it left in the directory it was pointed at -
    which is the same seam `ports/workspace.py` promises a real harness, "a workspace genuinely is
    a directory". Nothing else in this file needs one, the steps elsewhere being about the ledger.
    """

    def agent(task: AgentTask) -> Reply:
        (task.workspace / LANDED).write_bytes(b"the child's own work\n")
        return Reply(activity=[f"Write: {LANDED}"], says="implemented it")

    return agent

def _asking_agent(seen: list[str]) -> Agent:
    """An agent that stops to ask before it reports. The question is this file's, the answer is
    the workflow's, and what a `Reply` cannot do is read one: `agl.sdk.testing`'s `Agent` is handed
    a task and answers with one whole `Reply`, and `config/container.py`'s `_performs` awaits that
    reply before it makes the first call - so no call's answer is back yet when the agent is asked.

    **A question is a `Call` and no longer a field of its own.** `Reply.asks` existed while AGL
    supplied an asking tool to every task; a workflow supplies its own now, so asking is calling it
    by the name that workflow gave it, with the payload its schema asks for. The two calls are in
    the order the agent makes them, which is what puts the report after the answer.
    """

    def agent(task: AgentTask) -> Reply:
        seen.append("asking")
        return Reply(
            calls=[
                Call(ASK, {"question": PROPOSAL, "options": [GO_AHEAD, NOT_YET]}),
                Call(REPORT.name, {"summary": SUMMARY, "high": 0}),
            ],
            says="asked and reported",
        )

    return agent

@pytest.fixture(autouse=True)
def _nothing_carried_over() -> None:
    """The module-level records, emptied before each test and never by a workflow."""
    asked.clear()
    answers.clear()
    gated.clear()
    watched.clear()

def _steps(recorded: tuple[Recorded, ...]) -> list[str]:
    """Which steps recorded something, in the order they did it."""
    return [entry.step for entry in recorded]

# --- the four the deliverable asks for --------------------------------------------------------

@pytest.mark.asyncio
async def test_a_workflow_runs_to_completion_on_fakes(tmp_path: Path) -> None:
    """The criterion: a workflow written against the harness runs green, with no network and no git.

    Three lines of test, and the two assertions are what "ran" means from outside: both steps
    recorded, in the order the function calls them, and the third step - the one behind
    `if findings.high` - did not, because the agent reported none.
    """
    seen: list[str] = []
    harness = testing.harness(tmp_path, agent=_agent(seen), files={"src/a.py": b"pass\n"})

    await harness.run(demo, "-r", "add oauth")

    assert _steps(harness.recorded) == ["implement", "review"]
    assert seen == ["effect", "reporting"]

@pytest.mark.asyncio
async def test_a_scripted_payload_comes_back_as_the_step_result(tmp_path: Path) -> None:
    """The capture mechanism, end to end: what the agent reported *is* the step's result.

    The value on the ledger is the mapping this file's own agent handed to the reporting tool, and
    the effect step's is `null` because it declared no tool - which is the two step kinds, both of
    them observable in one list.
    """
    harness = testing.harness(tmp_path, agent=_agent([]), files={"src/a.py": b"pass\n"})

    await harness.run(demo, "-r", "add oauth")

    assert [entry.value for entry in harness.recorded] == [None, {"summary": SUMMARY, "high": 0}]
    assert [entry.namespace for entry in harness.recorded] == [None, None]

@pytest.mark.asyncio
async def test_a_scripted_question_reaches_the_workflows_own_screen(tmp_path: Path) -> None:
    """The agent asks, the workflow's handler shows its own screen, and a person answers it.

    Each assertion rules out a different way of passing: the handler was called with the question
    the agent asked, and with all three of its fields (`allow_free_text=False` included); the
    gesture came back as the `Answer` the workflow's *own* view built out of that question's first
    option, which nothing answering from a constant could produce; the step completed and recorded;
    and it was **one** dispatch, which is "one step, one session, N rounds" - a workflow loop that
    re-invoked the step per round would reach the same final answer and cost a second session.

    `answering([0])` is the whole of the person here, and a bare `int` is `Press(int)` - so "the
    first response of whatever is on screen" is what this scripts, and which string that is was
    decided by `approve` out of the agent's own `options`. This once needed the real `RichTerminal`
    and a `Keys` of AGL's own; the module docstring says what that cost.
    """
    seen: list[str] = []
    term = testing.answering([0])
    harness = testing.harness(tmp_path, agent=_asking_agent(seen), terminal=term)

    async with asyncio.timeout(DEADLINE):
        await harness.run(asking, "-r", "add oauth")

    assert [question.prompt for question in asked] == [PROPOSAL]
    assert asked[0].options == (GO_AHEAD, NOT_YET) and asked[0].allow_free_text is False
    assert answers == [Answer(GO_AHEAD)]
    assert _steps(harness.recorded) == ["decide"]
    assert seen == ["asking"], "the question was answered by re-running the step, not in-session"
    assert term.remaining == (), "the run never showed a screen, so nothing spent the gesture"

@pytest.mark.asyncio
async def test_the_answer_returns_into_the_same_session(tmp_path: Path) -> None:
    """The other half: what the person picked reaches the agent, inside the call it asked from.

    **This is the escape hatch, used as an escape hatch.** A `Reply` is computed before the run and
    has nowhere to put an answer, so an agent whose next move depends on one is a raw `Script`
    through `container.fakes(claude=...)` - and `over()` is what keeps such a bundle inside the
    harness rather than outside it. The limitation is the `Agent` type in `agl.sdk.testing`, which
    takes a task and answers with a `Reply`; nothing in `src/` names a way round it, and this test
    is what proves that this one works.

    **Two seams in one test, and only one of them is the escape hatch.** The bundle is composed by
    hand because the agent has to branch on an answer; the *terminal* is `answering([1])`, the
    supported one, handed to that bundle through `with_terminal` exactly as `harness(terminal=...)`
    hands it to the one it built. So reaching for a raw `Script` costs a bundle and does not cost a
    person - which is what `over()` is for.

    The value on the ledger got there only by the second response of a screen `approve` built out
    of the agent's own `options`, so nothing a framework interposing on the answer could produce
    would satisfy it. `Press(1)` and not `Press(0)`: the two options differ, and a terminal that
    answered with the first would pass an assertion written against `GO_AHEAD`.
    """
    term = testing.answering([Press(1)])
    fakes = container.fakes(TreesRoot(tmp_path / "trees"), claude=_negotiating())
    harness = testing.over(fakes.with_terminal(term))

    async with asyncio.timeout(DEADLINE):
        await harness.run(asking, "-r", "add oauth")

    assert answers == [Answer(NOT_YET)]
    assert [entry.value for entry in harness.recorded] == [{"summary": NOT_YET, "high": 0}]
    assert term.remaining == ()

@pytest.mark.asyncio
async def test_an_interrupted_run_resumes_without_redoing_completed_steps(tmp_path: Path) -> None:
    """Replay, driven the way a workflow author drives it.

    `interrupt_after=1` leaves one entry on the ledger and abandons the rest; the resume walks the
    workflow again, replays the step that has an entry and runs only the one that does not. The
    assertion with teeth is the last: each step's agent ran exactly once **across both
    invocations**, so an implementation that recomputed the first step's fingerprint differently
    would show `effect` twice and would have cost the operator an agent.

    The harness's own docstring is emphatic that this is an interruption and not a kill - the
    process lives, `finally` blocks run, and `tests/sdk/test_kill_and_resume.py` is the version
    that kills. What is being asserted here is the property a workflow author owns: their workflow
    is resumable and does not redo completed work.
    """
    seen: list[str] = []
    harness = testing.harness(tmp_path, agent=_agent(seen), files={"src/a.py": b"pass\n"})

    await harness.run(demo, "-r", "add oauth", interrupt_after=1)

    assert _steps(harness.recorded) == ["implement"]
    assert seen == ["effect"]

    await harness.resume(demo)

    assert _steps(harness.recorded) == ["implement", "review"]
    assert seen == ["effect", "reporting"]

# --- the properties those four rest on --------------------------------------------------------

@pytest.mark.asyncio
async def test_a_whole_workflow_runs_with_no_agent_written_at_all(tmp_path: Path) -> None:
    """`agent=None` is each provider's unscripted default, and target #8 is that it is enough.

    A workflow author's first run of their workflow is this one: nothing scripted, and every step
    still completing, because the default composes a payload out of the reporting tool's own
    schema. What it cannot do is mean anything - the summary below is the fake's placeholder - which
    is why every other test here writes an agent.
    """
    harness = testing.harness(tmp_path, files={"src/a.py": b"pass\n"})

    await harness.run(demo, "-r", "add oauth")

    assert _steps(harness.recorded) == ["implement", "review"]
    reported = harness.recorded[-1].value
    assert isinstance(reported, dict) and set(reported) == {"summary", "high"}

@pytest.mark.asyncio
async def test_the_run_is_recorded_where_agl_would_have_recorded_it(tmp_path: Path) -> None:
    """The harness runs the real operation, so `run.json` is the real record.

    `agl resume <label>` reads this file and nothing else, which is why the params are in it: an
    author who wants to know what a resume will be handed reads the same thing a resume does,
    through the bundle the harness is holding.
    """
    harness = testing.harness(tmp_path, agent=_agent([]), files={"src/a.py": b"pass\n"})

    await harness.run(demo, "-r", "add oauth")

    record = await harness.fakes.store.read_record(harness.scope)
    assert record is not None
    assert record["workflow"] == "demo"
    assert record["params"] == {"request": "add oauth"}

@pytest.mark.asyncio
async def test_the_workflows_own_flags_are_parsed_by_the_parser_agl_run_uses(
    tmp_path: Path,
) -> None:
    """Params are flags, so a missing one is the refusal an operator would have got.

    That is the argument for taking argv rather than an instance of the params dataclass: this
    fails at `params.parse`, before anything is written, exactly as `agl run demo -n test` would.
    """
    harness = testing.harness(tmp_path, agent=_agent([]))

    with pytest.raises(InputError):
        await harness.run(demo)

    assert harness.recorded == ()

@pytest.mark.asyncio
async def test_a_workflow_declared_inside_a_function_is_refused_with_the_reason(
    tmp_path: Path,
) -> None:
    """The harness resolves a workflow the way a workspace declaration is, so it can say no.

    A workflow is declared as `<module>:<name>`, and a `@workflow` declared inside something else
    names no module attribute - so no pyproject.toml could ever point at it. Refused here, in front
    of the author, rather than on the day they move it into a workspace directory.
    """

    @workflow
    async def hidden(run: Run[DemoParams]) -> None:
        """Declared inside this test, which is exactly what is being refused."""

    harness = testing.harness(tmp_path, agent=_agent([]))

    with pytest.raises(InputError, match="top level of its module"):
        await harness.run(hidden, "-r", "add oauth")

@pytest.mark.asyncio
async def test_an_interruption_before_the_first_step_is_refused(tmp_path: Path) -> None:
    """`interrupt_after=0` asks for a run that recorded nothing, which is a run that did nothing."""
    harness = testing.harness(tmp_path, agent=_agent([]))

    with pytest.raises(InputError, match="smallest one"):
        await harness.run(demo, "-r", "add oauth", interrupt_after=0)

@pytest.mark.asyncio
async def test_the_workflows_own_exception_leaves_the_harness_untouched(tmp_path: Path) -> None:
    """The harness catches its own interruption and nothing else.

    A workflow that raises is a workflow that raises: `api.run` wraps nothing, and neither does
    this - which is what makes a test of a workflow's own halt policy possible at all.
    """
    harness = testing.harness(tmp_path, agent=_raising())

    with pytest.raises(Refused, match="would not"):
        await harness.run(demo, "-r", "add oauth")

    assert harness.recorded == ()

class Refused(Exception):
    """What an agent that will not do the work raises. A workflow author's own class."""

def _raising() -> Agent:
    """An agent that raises rather than replying, which is an ordinary thing to want to test."""

    def agent(task: AgentTask) -> Reply:
        raise Refused("this agent would not do the work")

    return agent

def _negotiating() -> Script:
    """A raw script that reads the answer it was given and reports it. The escape hatch itself.

    `Conversation` is `adapters/claude_code/fake.py`'s and is reached here, in a test, on purpose:
    it is what `container.fakes(claude=...)` takes, and branching on what a call came back with is
    the thing `agl.sdk.testing`'s `Agent` type has no room for. That line is the whole of what it
    adds over a `Reply` - and that is still the limitation, a `Reply` being computed before the run
    whether its calls ask a person something or not.
    """

    async def script(conversation: Conversation) -> AgentOutcome:
        answered = await conversation.call(
            ASK, {"question": PROPOSAL, "options": [GO_AHEAD, NOT_YET]}
        )
        said = answered.text or NOT_YET
        await conversation.call(REPORT.name, {"summary": said, "high": 0})
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text=f"decided: {said}")

    return script

# --- the five remaining keywords, each through the operation it reaches --------------------------
#
# The module docstring argues why this section exists. Each keyword below is measured by what it
# changes downstream - the record, the ledger, the merge gate, the layout - and never by reading it
# back off the harness that was handed it.

RELEASE: Final = "release"
"""A second line of work in the fake repository, one commit ahead of the default branch. What
`--from` names, and the only way a `base_ref` assertion can tell a pin from a fallback."""

BUILD: Final = "make check --this-projects-own"
"""A merge-gate command that is deliberately **not** `container.FAKE_BUILD`, so a test asserting
that the project's own command reached the port cannot pass by agreeing with the default."""

RED: Final = "1 failed: the two changes disagree about what `parse` returns\n"
"""What the build said, which is what a person reads on the conflict screen rather than anything
the framework branches on."""

PROJECT: Final = "checkout-service"
"""A project of the author's own naming, and not `agl.testing`'s `project` default."""

FIRST_RUN: Final = "auth"
SECOND_RUN: Final = "billing"
"""Two runs in one directory, neither of them the `test` a harness falls back to."""

@pytest.mark.asyncio
async def test_a_resume_can_be_interrupted_at_its_own_first_step(tmp_path: Path) -> None:
    """`interrupt_after=` counts what *this* invocation wrote, which is what makes a sweep possible.

    The acceptance criterion is a sweep over kill points - run, kill mid-step, resume, assert
    identical - so a harness whose interruption could only arm the *first* invocation would stop
    every workflow at its second step and never reach the rest. `Harness._interrupting` arms the
    ledger around one call and resets its count precisely so that `interrupt_after=1` on a resume
    means the first step of that resume: here one entry is already on the ledger before the resume
    starts, and the resume was asked for one more.

    **Three steps, and the third is why this is not vacuous.** The review reports something, so
    `demo` takes the branch it has for that - and a two-step run would make the resume's kill point
    its last step, where interrupting and finishing are the same outcome and the assertion could
    not tell them apart.

    The last two assertions are the pair worth having. `recorded` reaching all three says the
    interruption abandoned work rather than losing it, and `seen` says each step's agent ran
    exactly once across all three invocations - so an interrupted resume that re-ran what the
    earlier ones recorded would show here and be paid for in tokens.
    """
    seen: list[str] = []
    harness = testing.harness(tmp_path, agent=_agent(seen, high=1), files={"src/a.py": b"pass\n"})

    await harness.run(demo, "-r", "add oauth", interrupt_after=1)
    assert _steps(harness.recorded) == ["implement"]

    await harness.resume(demo, interrupt_after=1)

    assert _steps(harness.recorded) == ["implement", "review"], (
        "the resume did not stop after its own first step. `interrupt_after=1` on a resume that "
        "already has one entry behind it asks for one more, and a harness that armed nothing here "
        "leaves a sweep over kill points unable to reach anything past the first invocation"
    )

    await harness.resume(demo)

    assert _steps(harness.recorded) == ["implement", "review", "implement"]
    assert seen == ["effect", "reporting", "effect"], (
        "across three invocations each step's agent must have run exactly once: an interrupted "
        "resume abandons what comes after its kill point and replays what came before it"
    )

@pytest.mark.asyncio
async def test_a_resumes_kill_point_counts_that_resumes_own_entries(tmp_path: Path) -> None:
    """The other half of the keyword: on a resume, *two* means two more, not the second one ever.

    `interrupt_after=1` cannot tell those apart, a count carried across invocations and a count
    reset per invocation both firing on the resume's first write - so `_Ledger.interrupt_after`'s
    reset, which its docstring argues at length is "the difference between 'the second step of this
    resume' and 'the second step ever'", is only observable from `k` above one. Here one entry is
    already on the ledger and the resume asks for two.

    Why it is worth a second test rather than a larger first one: a harness counting every entry
    ever would make `k` mean a different depth on every invocation, offset by however much the
    previous ones happened to record - and a sweep over kill points cannot carry that offset,
    because the number of entries before the resume is exactly what the sweep is varying.
    """
    seen: list[str] = []
    harness = testing.harness(tmp_path, agent=_agent(seen, high=1), files={"src/a.py": b"pass\n"})

    await harness.run(demo, "-r", "add oauth", interrupt_after=1)
    await harness.resume(demo, interrupt_after=2)

    assert _steps(harness.recorded) == ["implement", "review", "implement"], (
        "the resume stopped short of the two steps it was asked for, so `interrupt_after=` counted "
        "what an earlier invocation wrote as well as its own"
    )
    assert seen == ["effect", "reporting", "effect"]

@pytest.mark.asyncio
async def test_a_run_can_be_started_from_a_ref_other_than_the_default(tmp_path: Path) -> None:
    """`base_ref=` is `--from` reaching the harness, and the record is where it lands.

    The default is the repository's own default branch and `base_sha` pins whatever the ref
    resolved to, so a run started from somewhere else is a run whose `base_sha` is that branch's
    head. The two heads differ by a commit, which is what makes the assertion unsatisfiable by a
    harness that dropped the argument and resolved the default instead - and `base_ref` is asserted
    beside it because the record keeps both: the commit is what a resume hours later walks on, and
    the ref is the name the operator typed, kept so that what a run says it started from is what
    they asked for rather than whatever that name has since moved to.

    The second branch is put there through `harness.fakes.repository`, the bundle's own fake, which
    is the only vocabulary there is for "somebody else's work is already on a branch" - the same
    two calls `tests/test_resume.py` makes to land a commit between two invocations.
    """
    harness = testing.harness(tmp_path, agent=_agent([]), files={"src/a.py": b"pass\n"})
    repository = harness.fakes.repository
    default = repository.tip("main")
    assert default is not None, "the fake repository has no default branch to be ahead of"
    head = repository.record(
        {"src/a.py": b"pass\n", "src/b.py": b"work the release branch has\n"},
        (default,),
        "a commit on the release branch and on nothing else",
    )
    repository.move(RELEASE, head)

    await harness.run(demo, "-r", "add oauth", base_ref=RELEASE)

    record = await harness.fakes.store.read_record(harness.scope)
    assert record is not None
    assert record["base_ref"] == RELEASE
    assert record["base_sha"] == head, (
        "the run was pinned to something other than the head of the ref it was started from. "
        "`--from` names where the work begins, so a run that fell back to the default branch is "
        "one whose first step starts on a tree the operator did not ask for"
    )

@pytest.mark.asyncio
async def test_the_merge_gate_runs_the_build_command_the_harness_was_given(tmp_path: Path) -> None:
    """`build=` is the project's own command, and the merge gate is the only thing that runs it.

    `Verifier.verify(command, workdir)` takes the command as a parameter, so what the bundle
    carries is what the gate asks about - and the verdict is scripted against that exact string and
    against no other. That is what makes this non-vacuous in both directions: `FakeVerifier` passes
    a command nobody scripted, so a harness carrying `FAKE_BUILD` here would put the landing
    through a green gate, advance the chain and report no verdict at all.

    Read back through the workflow, because a refused landing is what an author sees: `conflicted`
    is what their own code branches on, and the output is what a person would be reading on the
    conflict screen rather than anything the framework acts on.
    """
    harness = testing.harness(
        tmp_path, agent=_building(), files={"src/a.py": b"pass\n"}, build=BUILD
    )
    harness.fakes.verifier.answers(BUILD, passed=False, output=RED)

    await harness.run(landing, "-r", "add oauth")

    assert gated == [(True, RED)], (
        "the gate did not answer with the verdict scripted against this harness's own build "
        "command, so what reached `Verifier.verify` is not what the bundle was built with"
    )

@pytest.mark.asyncio
async def test_two_harnesses_in_one_directory_are_told_apart_by_project_and_label(
    tmp_path: Path,
) -> None:
    """`project=` and `label=` name the run, and `harness.scope` is the address they compose.

    Two runs in one directory is the case they are parameters for, and the layout is what makes the
    second one need a name of its own: the trees root is keyed by the label alone, so two harnesses
    sharing a directory and a label provision `<where>/trees/<label>/_base` twice, and the second
    is refused - `WorkspaceProvider.open` will not provision over a directory that holds files
    nothing there has open. Naming the second run is the whole fix and it is one keyword, which is
    why `second.run` below is an assertion in its own right, before any of them are reached. **Both
    repositories are seeded for that reason**: an empty checkout holds no files and is adopted
    rather than refused, so a bundle with no `files=` would not reach that clause.

    The record is then read back **at `harness.scope`**, which is the address `api` was called
    with. A harness whose scope said one thing while its run was recorded at another would hand an
    author a project and a label that `api.clear(harness.fakes.services, harness.scope.project,
    harness.scope.label)` - the line the module docstring tells them to write - could not find.
    """
    seed: Final = {"src/a.py": b"pass\n"}
    first = testing.harness(
        tmp_path, agent=_agent([]), files=seed, project=PROJECT, label=FIRST_RUN
    )
    second = testing.harness(tmp_path, agent=_agent([]), files=seed, label=SECOND_RUN)

    await first.run(demo, "-r", "add oauth")
    await second.run(demo, "-r", "add sso")

    assert str(first.scope.project) == PROJECT
    assert [str(first.scope.label), str(second.scope.label)] == [FIRST_RUN, SECOND_RUN]
    record = await first.fakes.store.read_record(first.scope)
    assert record is not None, "nothing was recorded at the scope this harness says it runs at"
    assert record["label"] == FIRST_RUN
    assert record["params"] == {"request": "add oauth"}

# --- `a_run`, a board, and what a `Reply` alone does not do --------------------------------------
#
# Three things an author meets once they go past a workflow that merely runs: getting a live `Run`
# to hand their own code, which needs a `Services` and a `RunScope` that are not on the authoring
# surface; putting a board up, where the two spellings that carry a line are theirs at both ends and
# the framework holds nothing in between; and testing a `commit=`, where an agent scripted only as a
# `Reply` leaves nothing for the framework to commit.

SEED: Final[Mapping[str, bytes]] = {"src/a.py": b"pass\n"}
"""The repository every run in this section starts from, so that "nothing was committed" is a
comparison against a tree and not against emptiness."""

WRITTEN: Final = "implemented.py"
"""What the implementer in this section leaves in its checkout - the side effect a `Reply` has no
field for and a real agent would have had."""

ELSEWHERE: Final = "b7c1d4f09a2e63518cd047fb29e15a83d604c7f2"
"""A head of the caller's own choosing, to tell `base=` from the default `a_run` falls back to."""

def _writing(seen: list[str]) -> Agent:
    """`_agent`'s replies, plus the file an implementer would have left in the checkout.

    Keyed on whether the task declares any tool, which is `sdk/testing.py`'s own sharpest handle
    and here picks out the effect step - `implement()` declares none and `review()` reports through
    one: the reviewer runs under `NO_VCS_WRITES` and its step passes
    no `commit=`, so anything written there is wiped on the way out by design.

    **The return type is the alias's own and not `Reply`**, which is what composing two agents
    costs now that `Agent` is `(AgentTask) -> Reply | Awaitable[Reply]`: `replies(task)` is typed at
    the union whatever the function behind it does, so a wrapper narrowing it back would have to
    await or assert something it has no reason to. One line, at the one site in this repository that
    wraps an agent rather than writing one, and worth knowing before writing the second.
    """
    replies = _agent(seen)

    def agent(task: AgentTask) -> Reply | Awaitable[Reply]:
        if not task.tools:
            (task.workspace / WRITTEN).write_bytes(b"what the implementer wrote\n")
        return replies(task)

    return agent

def _on_the_branch(harness: testing.Harness) -> Mapping[str, bytes]:
    """What the run's own line of work holds now - which is what its `commit=` steps put there.

    `run_branch` is the one reach into `agl.ports` this section makes and the module docstring
    names it: "what did this run commit" has no answer that does not name the branch, and
    `harness.fakes.repository` is addressed by branch and by state.
    """
    tip = harness.fakes.repository.tip(run_branch(harness.scope.label))
    assert tip is not None, "the run's branch does not exist, so nothing ran here at all"
    return harness.fakes.repository.tree_of(tip)

def test_a_run_is_built_over_the_harnesss_own_bundle_and_its_own_address(tmp_path: Path) -> None:
    """`a_run` composes the two things a `Run` needs and `agl.sdk` cannot hand over.

    Asserted by identity, because "the same bundle" is the property and not "an equal one": a
    factory that built a second `FakeServices` would give an author a `Run` whose terminal, store
    and repository were not the ones their harness reads back afterwards, and every assertion they
    made after calling their own code would be about a bundle nothing else touches.
    """
    harness = testing.harness(tmp_path, files=SEED)

    run = testing.a_run(harness, DemoParams(request="add oauth"))

    assert run.params == DemoParams(request="add oauth")
    assert run.services is harness.fakes.services
    assert run.scope is harness.scope
    assert run.terminal is harness.fakes.services.terminal

@pytest.mark.asyncio
async def test_a_run_an_author_was_handed_starts_where_it_was_told_and_records_nothing(
    tmp_path: Path,
) -> None:
    """The other half of what `a_run` promises: `base=`, and that none of this is a run.

    The default base is a well-formed sha naming no state the bundle holds, which is honest because
    nothing built here takes a step - so the assertion worth writing is that a caller who does have
    a head gets theirs. And nothing is written anywhere: no record at the scope, no entry on the
    ledger. A factory that had quietly opened a workspace or written a record would make a test of
    the author's own code into a run, and their next `harness.run` would meet a label in use.
    """
    harness = testing.harness(tmp_path, files=SEED)

    default = testing.a_run(harness, DemoParams(request="add oauth"))
    named = testing.a_run(harness, DemoParams(request="add oauth"), base=ELSEWHERE)

    assert named.base == ELSEWHERE
    assert default.base != ELSEWHERE
    assert harness.recorded == ()
    assert await harness.fakes.store.read_record(harness.scope) is None

@pytest.mark.asyncio
async def test_a_watched_roles_reporter_feeds_the_board_the_line_its_agent_reported(
    tmp_path: Path,
) -> None:
    """A dashboard end to end, in the two spellings an author has and with nothing between them.

    `Reply`'s activity is what their agent says it is doing and `Role.on_activity` is where that
    line arrives. Both are theirs, the framework holds no copy of what passes between them, and no
    `Run` is anywhere on the path - so the two screens below are the whole claim: the empty one is
    taken before the run, from the same view over the same list, and what separates them is a line
    that came out of an agent.

    Nothing here is about drawing one. `show` registers a view and its arguments, the redraw loop
    and the diff belong to the adapter, and `HeadlessTerminal` drops a passive screen and answers
    at once - so what a run proves is that the line arrived and that a board built from the list
    reads it. Which is also why the reporter is the assertion and not `harness.recorded`: activity
    reaches no entry, no fingerprint and no store, so the ledger of this run says nothing about it.
    """
    harness = testing.harness(tmp_path, agent=_agent([]), files=SEED)
    idle = a_board(watched, "add oauth")

    await harness.run(watching, "-r", "add oauth")

    assert watched == [EDITING], (
        "the line this file's own agent reported is not what its role's reporter was handed. A "
        "`Reply`'s activity is performed through the fake's own `report`, and a step hands the "
        "adapter the reporter its role carries and wraps it in nothing"
    )
    assert idle == Screen(Rows([Row("request", "add oauth"), Row("agent", "")]))
    assert a_board(watched, "add oauth") == Screen(
        Rows([Row("request", "add oauth"), Row("agent", EDITING)])
    )

@pytest.mark.asyncio
async def test_an_agent_that_only_replies_leaves_every_commit_message_with_nothing_to_carry(
    tmp_path: Path,
) -> None:
    """The trap a `Reply` sets under a `commit=`, made into the failure it actually produces.

    A `Reply` has no member that touches the worktree, and `commit_all` is "a no-op when nothing is
    dirty, returning the unchanged head" - so a step passing `commit="implement add oauth"` over an
    agent that only replied records the head it started from and the branch stays exactly where the
    run cut it. The two harnesses below run the *same workflow* with the *same `commit=`* and differ
    in one line of the author's own agent, and that line is the whole difference between a branch
    holding work and an empty one.

    **Why this is worth a test rather than a paragraph.** Both runs succeed, both ledgers are
    identical, `harness.recorded` cannot tell them apart, and neither the framework nor the fake
    reports anything - the framework does not inspect whether HEAD moved, deliberately. So a test
    written to pin a workflow's three `commit=` decisions passes against a workflow that dropped
    all three, and the only place that shows is here, on the branch.

    Two labels in one directory, because the trees root is keyed by the label alone and the second
    harness would otherwise provision over the first one's checkout.
    """
    quiet: list[str] = []
    replying = testing.harness(tmp_path, agent=_agent(quiet), files=SEED, label="replying")
    await replying.run(demo, "-r", "add oauth")

    busy: list[str] = []
    working = testing.harness(tmp_path, agent=_writing(busy), files=SEED, label="working")
    await working.run(demo, "-r", "add oauth")

    assert quiet == busy == ["effect", "reporting"], "the two runs did not walk the same workflow"
    assert _steps(replying.recorded) == _steps(working.recorded) == ["implement", "review"], (
        "the ledgers differ, so this is not a comparison between one workflow and itself"
    )
    assert _on_the_branch(replying) == SEED, (
        "the run whose agent only returned a `Reply` committed something, which nothing in it "
        "could have produced - a `Reply` has no member that writes a file"
    )
    assert _on_the_branch(working) == {**SEED, WRITTEN: b"what the implementer wrote\n"}, (
        "the run whose agent wrote into `task.workspace` did not commit it, so the one line an "
        "author has to add for a `commit=` to carry anything does not in fact reach the branch"
    )
