"""16.5's acceptance criterion, written the way the person it is for would write it.

> A trivial workflow written against the harness runs green with no network and no git.

**So this file is deliberately not a fixture.** Everything above the first test is what a workflow
author writes and nothing else: a params dataclass of `arg()` fields, a payload dataclass, a
reporting tool, three roles, a screen, and three `@workflow` functions. Every import of AGL is one
line - `agl.sdk` for the workflow and `agl.testing` for the test - and nothing here reaches into
`agl.ports`, `agl.sdk._engine`, `agl.config` or `agl.adapters` except in the two places that are
about the escape hatch and say so. If any of that had needed a third import or a piece of framework
knowledge, the harness would have been wrong and the fix would have been in the harness.

The four things the deliverable asks for, one test each and in order: a workflow runs to completion
on fakes; a scripted agent's reported payload comes back as the step result; a scripted question
reaches a workflow-defined screen and the answer returns into the same session; and an interrupted
run resumes without redoing completed steps. The rest of the file is the properties those four
rest on, the refusals the harness makes, and a last section for the keywords it takes.

## Every keyword is passed by something here, and that is a rule rather than a tidy-up

`harness()` takes six and the two operations take one each, and a keyword no test ever passes is a
keyword wired by inspection - which is not the care the rest of the SDK gets, and matters more here
than elsewhere because stages 17 and 18 build every end-to-end test on this module. `agent=`,
`files=` and `terminal=` are passed by the tests above; the last section covers the other five,
each driven through the thing that keyword changes rather than read back off the harness, since
reading it back would measure an assignment and not the wiring. `interrupt_after=` on a resume
takes two tests, because one of them can measure the arming and neither can measure both that and
what the count is counted from.

## What each test can fail on, because a green harness test proves nothing by itself

  * **The replay assertion counts agent dispatches**, not entries, and it counts them across both
    invocations. §3.6's replay has no observable difference from a re-run that happens to produce
    the same answer other than that the worker was not called - so `seen` below is the instrument,
    and it lives in the author's own `Agent` function, which is exactly where `config/container.py`
    says a test's knowledge belongs ("what a test wants to know is already held by the tool handlers
    and question handler it supplied itself").
  * **The payload assertion reads the ledger** through `harness.recorded`, and the value it compares
    is one nothing in the framework could have invented: it is the mapping this file's own agent
    handed to the reporting tool.
  * **The question assertion reads a string a person typed.** The answer that reaches the agent
    exists nowhere in this file except as a keystroke, so nothing a handler answering from a
    constant could produce would satisfy it.

## The one place this is not author-shaped, and it is a finding rather than a shortcut

`container.fakes()` builds a `HeadlessTerminal`, which refuses every `Screen[T]` with
`UpstreamUnavailable` - correctly, since a workflow needing human input cannot run with nobody
there. AGL ships no second input-capable `Terminal`, and `adapters/rich_terminal/headless.py` and
`tests/sdk/test_agent_questions.py` both argue at length that a third one written for tests would be
under `tests/contracts/terminal.py`'s eye nowhere at all. So answering a screen means the real
`RichTerminal` over a `Keys`, which is the seam that port exists for - and here that is
`instruments.keyboard.Typing`, a module inside this repository that a workflow author outside it
does not have.

That is a real gap in what `agl.testing` can offer on a bare `pip install agl`, it is reported as
one, and it is not papered over by pretending the arrangement is simpler than it is. Everything
*else* in the two question tests is the author's: the screen is a view of theirs, the handler is a
closure over their `Run`, and the assertion is about their workflow.

## Every await is bounded

§3.7 has no timeouts anywhere - "an unanswered question blocks its step indefinitely" - so a mistake
in a test that answers a screen is a hang rather than a failure. The two that drive a terminal run
under `asyncio.timeout`; the rest cannot block, there being nobody to wait for.
"""

import asyncio
import io
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import pytest
from rich.console import Console

from agl import testing
from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.rich_terminal.terminal import RichTerminal
from agl.config import container
from agl.ports.agent import AgentOutcome, StopReason
from agl.ports.errors import InputError
from agl.ports.tree_layout import TreesRoot
from agl.sdk import (
    Answer,
    Choice,
    Claude,
    OpenAI,
    Question,
    Restriction,
    Role,
    Run,
    Screen,
    Text,
    arg,
    reporting_tool,
    workflow,
)
from agl.testing import Agent, AgentTask, Call, Recorded, Reply
from instruments.keyboard import DEADLINE, Typing

# `asyncio_mode = "strict"`, so every async test below carries its own marker.


# --- what a workflow author writes -----------------------------------------------------------


@dataclass(frozen=True)
class DemoParams:
    """§3.3's shape: named flags, no positionals. `agl run demo -n test -r "add oauth"`."""

    request: str = arg("-r", "--request", help="what to build")


@dataclass(frozen=True)
class Findings:
    """What the review reports through its tool, and therefore what that step's result is."""

    summary: str
    high: int


REPORT: Final = reporting_tool("report_findings", "report what the review found", Findings)

IMPLEMENT: Final = Role(
    instructions="implement what the request asks for",
    model=Claude.SONNET,
)
"""An effect role: no reporting tool, so the step's result is `null` and its effect is commits."""

REVIEW: Final = Role(
    instructions="review the worktree and report what you found",
    model=OpenAI.SOL,
    restrictions={Restriction.NO_VCS_WRITES},
    tools=[REPORT],
)
"""A reporting role, on the other provider - §3.3's `fix` shape: Claude implements, OpenAI
reviews. Paired below with a step that passes no `commit=`, which is what §3.3 asks of a
read-only role."""

DECIDE: Final = Role(
    instructions="propose something, ask whether to go ahead, then report what was decided",
    model=Claude.SONNET,
    tools=[REPORT],
)
"""The role the two question tests use. `on_question` is not declared here and cannot be: §3.7's
handler is a closure over the workflow's own `Run`, so the role that runs is
`replace(DECIDE, on_question=...)`, built inside the function."""


def approve(question: Question) -> Screen[Answer]:
    """The screen the agent's question is shown on. A pure function of what it was handed (§3.7).

    Its options become the choices in the order the agent offered them, so the digit that answers
    this screen means whatever that question's second option said.
    """
    return Screen(
        body=Text(question.prompt),
        responses=[Choice(option, value=Answer(option)) for option in question.options],
    )


@workflow(name="demo", version="1", params=DemoParams, roles=[IMPLEMENT, REVIEW])
async def demo(run: Run[DemoParams]) -> None:
    """Implement, then review what was implemented. Two steps, two providers, one worktree."""
    await run.step("implement", IMPLEMENT, commit=f"implement {run.params.request}")
    findings = await run.step("review", REVIEW, request=run.params.request)
    if findings.high:
        await run.step("repair", IMPLEMENT, note=findings.summary, commit="address the review")


@workflow(name="asking", version="1", params=DemoParams, roles=[DECIDE])
async def asking(run: Run[DemoParams]) -> None:
    """One step whose agent stops to ask, answered by a person at a screen this workflow owns."""

    async def answered(question: Question) -> Answer:
        asked.append(question)
        picked = await run.terminal.show(approve, question=question, priority=5)
        answers.append(picked)
        return picked

    await run.step("decide", replace(DECIDE, on_question=answered))


@workflow(name="landing", version="1", params=DemoParams, roles=[IMPLEMENT])
async def landing(run: Run[DemoParams]) -> None:
    """One child worktree, one committing step, one integration - §3.9's shape at its smallest.

    Here because a landing is the only thing that runs a build. §3.4: "the framework runs exactly
    one build: the merge gate, inside `integrate()`" - so a workflow that never integrates never
    reaches the project's build command, and a test about which command the harness carries has to
    take a run all the way to a landing to see one.
    """
    ticket = run.worktree("T-01")
    await ticket.step("implement", IMPLEMENT, commit=f"implement {run.params.request}")
    outcome = await ticket.integrate()
    verdict = outcome.verdict
    gated.append((outcome.conflicted, "" if verdict is None else verdict.output))


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


# --- the agent, which is the author's own function -------------------------------------------

SUMMARY: Final = "one thing worth changing"
PROPOSAL: Final = "Shall I go ahead with the change I proposed?"
GO_AHEAD: Final = "go ahead"
NOT_YET: Final = "not yet"
LANDED: Final = "landed.py"
"""What `landing`'s agent writes into the child's checkout, so `commit=` records something and the
integration has work to carry. Top level in the tree, there being no directory to make first."""


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
        return Reply(activity=["Edit: src/a.py"], says="implemented it")

    return agent


def _building() -> Agent:
    """An agent that leaves a file behind, which is what gives a landing something to land.

    Writing into `task.workspace` is the author's own code and not AGL's: a `Reply` says what the
    agent *reported*, and what it did is whatever it left in the directory it was pointed at -
    which is the same seam `ports/agent.py` promises a real harness, "a workspace genuinely is a
    directory". Nothing else in this file needs one, the steps elsewhere being about the ledger.
    """

    def agent(task: AgentTask) -> Reply:
        (task.workspace / LANDED).write_bytes(b"the child's own work\n")
        return Reply(activity=[f"Write: {LANDED}"], says="implemented it")

    return agent


def _asking_agent(seen: list[str]) -> Agent:
    """An agent that stops to ask before it reports. The question is this file's, the answer is
    the workflow's, and what a `Reply` cannot do is read one - see `agl.sdk.testing`."""

    def agent(task: AgentTask) -> Reply:
        seen.append("asking")
        return Reply(
            asks=[Question(prompt=PROPOSAL, options=(GO_AHEAD, NOT_YET), allow_free_text=False)],
            calls=[Call(REPORT.name, {"summary": SUMMARY, "high": 0})],
            says="asked and reported",
        )

    return agent


# --- fixtures the two question tests need, and nothing else does -----------------------------


@pytest.fixture
def keys() -> Typing:
    """A keyboard, standing in for the person a `Screen[T]` is waiting on."""
    return Typing()


@pytest.fixture
def terminal(keys: Typing) -> RichTerminal:
    """The one terminal AGL ships that can answer a question, over a console nobody watches.

    The module docstring records this as the gap it is: a workflow author outside this repository
    has `RichTerminal` but no `Keys` to drive it with.
    """
    return RichTerminal(Console(file=io.StringIO(), width=100), keys)


@pytest.fixture(autouse=True)
def _nothing_carried_over() -> None:
    """The module-level records, emptied before each test and never by a workflow."""
    asked.clear()
    answers.clear()
    gated.clear()


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
    """§3.3's capture mechanism, end to end: what the agent reported *is* the step's result.

    The value on the ledger is the mapping this file's own agent handed to the reporting tool, and
    the effect step's is `null` because it declared no tool - which is §3.3's two step kinds, both
    of them observable in one list.
    """
    harness = testing.harness(tmp_path, agent=_agent([]), files={"src/a.py": b"pass\n"})

    await harness.run(demo, "-r", "add oauth")

    assert [entry.value for entry in harness.recorded] == [None, {"summary": SUMMARY, "high": 0}]
    assert [entry.namespace for entry in harness.recorded] == [None, None]


@pytest.mark.asyncio
async def test_a_scripted_question_reaches_the_workflows_own_screen(
    tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """The agent asks, the workflow's handler shows its own screen, and a person answers it.

    Each assertion rules out a different way of passing: the handler was called with the question
    the agent asked, and with all three of its fields (`allow_free_text=False` included); the
    keystroke came back as the `Answer` the workflow's *own* view built out of that question's first
    option, which nothing answering from a constant could produce; the step completed and recorded;
    and it was **one** dispatch, which is §3.7's "one step, one session, N rounds" - a workflow loop
    that re-invoked the step per round would reach the same final answer and cost a second session.
    """
    seen: list[str] = []
    harness = testing.harness(tmp_path, agent=_asking_agent(seen), terminal=terminal)

    async with asyncio.timeout(DEADLINE):
        running = asyncio.create_task(harness.run(asking, "-r", "add oauth"))
        await keys.entered("1")
        await running

    assert [question.prompt for question in asked] == [PROPOSAL]
    assert asked[0].options == (GO_AHEAD, NOT_YET) and asked[0].allow_free_text is False
    assert answers == [Answer(GO_AHEAD)]
    assert _steps(harness.recorded) == ["decide"]
    assert seen == ["asking"], "the question was answered by re-running the step, not in-session"


@pytest.mark.asyncio
async def test_the_answer_returns_into_the_same_session(
    tmp_path: Path, terminal: RichTerminal, keys: Typing
) -> None:
    """§3.7's other half: what the person picked reaches the agent, inside the call it asked from.

    **This is the escape hatch, used as an escape hatch.** A `Reply` is computed before the run and
    has nowhere to put an answer, so an agent whose next move depends on one is a raw `Script`
    through `container.fakes(claude=...)` - and `over()` is what keeps such a bundle inside the
    harness rather than outside it. `agl.sdk.testing` states the limitation and names this way
    round it; this test is what proves the way round works.

    The value on the ledger is the string the keyboard typed, which exists nowhere else in this
    file: nothing a framework interposing on the answer could produce would satisfy it.
    """

    fakes = container.fakes(TreesRoot(tmp_path / "trees"), claude=_negotiating())
    harness = testing.over(fakes.with_terminal(terminal))

    async with asyncio.timeout(DEADLINE):
        running = asyncio.create_task(harness.run(asking, "-r", "add oauth"))
        await keys.entered("2")
        await running

    assert answers == [Answer(NOT_YET)]
    assert [entry.value for entry in harness.recorded] == [{"summary": NOT_YET, "high": 0}]


@pytest.mark.asyncio
async def test_an_interrupted_run_resumes_without_redoing_completed_steps(tmp_path: Path) -> None:
    """§3.6's replay, driven the way a workflow author drives it.

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

    §3.10's `agl resume <label>` reads this file and nothing else, which is why the params are in
    it: an author who wants to know what a resume will be handed reads the same thing a resume
    does, through the bundle the harness is holding.
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
    """The harness resolves a workflow the way an installed one is resolved, so it can say no.

    §3.3 registers a workflow as `<module>:<name>`, and a `@workflow` declared inside something
    else names no module attribute - so it could never be installed. Refused here, in front of the
    author, rather than on the day they publish the package.
    """

    @workflow(name="hidden", version="1", params=DemoParams)
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
    it is what `container.fakes(claude=...)` takes and the thing `agl.sdk.testing` says a `Reply`
    cannot do. The whole of what it adds over a `Reply` is the line that branches on `answer`.
    """

    async def script(conversation: Conversation) -> AgentOutcome:
        answer = await conversation.ask(
            Question(prompt=PROPOSAL, options=(GO_AHEAD, NOT_YET), allow_free_text=False)
        )
        said = NOT_YET if answer is None else answer.text
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

    §3.6's acceptance criterion is a sweep over kill points, and stage 17.3 is "run, kill mid-step,
    resume, assert identical" - so a harness whose interruption could only arm the *first*
    invocation would stop every workflow at its second step and never reach the rest.
    `Harness._interrupting` arms the ledger around one call and resets its count precisely so that
    `interrupt_after=1` on a resume means the first step of that resume: here one entry is already
    on the ledger before the resume starts, and the resume was asked for one more.

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

    assert _steps(harness.recorded) == ["implement", "review", "repair"]
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

    assert _steps(harness.recorded) == ["implement", "review", "repair"], (
        "the resume stopped short of the two steps it was asked for, so `interrupt_after=` counted "
        "what an earlier invocation wrote as well as its own"
    )
    assert seen == ["effect", "reporting", "effect"]


@pytest.mark.asyncio
async def test_a_run_can_be_started_from_a_ref_other_than_the_default(tmp_path: Path) -> None:
    """`base_ref=` is `--from` reaching the harness, and the record is where it lands.

    §3.9 makes the default the repository's own default branch and §3.6 pins whatever the ref
    resolved to, so a run started from somewhere else is a run whose `base_sha` is that branch's
    head. The two heads differ by a commit, which is what makes the assertion unsatisfiable by a
    harness that dropped the argument and resolved the default instead - and `base_ref` is asserted
    beside it because the record keeps both, the ref for `clear` to ask about and the commit for
    the resume hours later.

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
    """`build=` is the project's own command, and §3.4's merge gate is the only thing that runs it.

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

    Two runs in one directory is the case they are parameters for, and §3.5's layout is what makes
    the second one need a name of its own: the trees root is keyed by the label alone, so two
    harnesses sharing a directory and a label provision `<where>/trees/<label>/_base` twice, and
    the second is refused - `WorkspaceProvider.open` will not provision over a directory that holds
    files nothing there has open. Naming the second run is the whole fix and it is one keyword,
    which is why `second.run` below is an assertion in its own right, before any of them are
    reached. **Both repositories are seeded for that reason**: an empty checkout holds no files and
    is adopted rather than refused, so a bundle with no `files=` would not reach that clause.

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
