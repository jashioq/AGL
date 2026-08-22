"""`AgentContract` - what every `AgentRunner` owes, asserted before an implementation of one exists.

Subclass it once per implementation, override the two fixtures, and add nothing:

    class TestTheRunnerIWrote(AgentContract):
        @pytest.fixture
        def runner(self) -> AgentRunner:
            return TheRunnerIWrote(...)

        @pytest.fixture
        def model(self) -> ModelId:
            return SomeModel.THE_ONE_IT_SERVES

The real adapters and the fakes run this class, which is the whole mechanism keeping a fake from
drifting into fiction (§1.9). It is written here, at stage 3, before any of them exists, because a
subagent that writes its own tests writes tests that pass - and stages 4 to 8 each end with "the
contract suite passes", a sentence worth something only when the suite had no stake in the outcome.

`AgentContract` is one class assembled from four modules, and only this name is public. Its own
tests are the four things a `run` answers for that need no machinery: the outcome, a refused tool
call, a tool call whose handler *failed*, and the activity it may or may not report. The three it
inherits follow seams the port draws itself. `_agent_preflight` holds the two members that are asked
*about* an agent rather than running one; `_agent_questions` holds §3.7's negotiation and the two
edge cases the port settles by hand;
`_agent_hermeticity` holds §3.5's poisoned repository and the table it is built from, and is the
centrepiece. `_agent_tasks` under all of them holds the workspace, the tasks, the tool and the two
callbacks every test is made of, and argues there why this suite touches a filesystem when the store
suite refuses to.

## Written against the port, never against a harness

The audience is an adapter that does not exist yet, possibly one nobody has thought of. Nothing here
assumes a subprocess, a command line, a config file, an HTTP call, a session object or a machine.
The tests speak `AgentTask`, `AgentOutcome`, `Capability`, `Question` and `ToolResult`, because
those are the whole of what the port accepts and answers with.

Where a backend genuinely differs, the suite branches on **what the port says it can do** and never
on which implementation it is: `Capability.MID_RUN_QUESTIONS` decides whether a handler must be
called, `Capability.TOOL_CALLING` whether a tool call can be rejected. Those are the port's own
escape hatches, stated in `capabilities()` by the adapter itself. A test that asked "is this the X
adapter" would be a test somebody has to edit when the second X arrives.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe.

1. **That any adapter is hermetic - when the runner is a fake.** A fake reads no configuration, so
   the poisoned repository cannot catch it doing anything. The test is trivially satisfied there by
   construction and bites only at stages 6 and 7. `_agent_hermeticity` says this at more length and
   says why it is still written to bite.

2. **A configuration an adapter loaded that the agent then ignored.** The poison is instructions,
   and instructions are only visible once acted on. Three channels make that likelier; none of them
   makes it certain.

3. **Anything at all about the environment a backend runs in.** No test here reads or asserts an
   environment variable. That is **deferred by decision, not overlooked**: §3.11's
   "Credential-environment isolation" row states that v1.1 inherits the parent environment, that
   managing what reaches a spawned agent interacts with proxies, cloud credentials and each
   harness's own precedence rules, and that the operator simply keeps the key unset. §3.5 names it
   the *second* channel and puts it out of scope in the same breath as putting hermeticity in.
   Adding an environment assertion here would be building the thing the plan declined to build.

4. **That a `Restriction` was enforced.** The port lets a backend with no mechanism put a
   restriction to the agent as an instruction, so a dropped `NO_FILE_WRITES` and an agent that did
   not happen to write a file are the same observation. Every task here declares none, which is the
   only honest thing a suite that cannot check them can ask for.

5. **That `plan_only` changed anything**, for the same reason and with the same two honest
   implementations behind it - a harness that selects a mode, and one that says it in the prompt.

6. **That `context` was kept apart from `instructions`.** A backend that distinguishes standing
   context honours the distinction and one that does not joins two strings; both are correct, and
   an `AgentOutcome` cannot tell them apart.

7. **That `run` raises only from `errors.py`.** Nothing here can make a backend fail on demand -
   there is no member for it and inventing one would be inventing a port - so no test provokes a
   translation. `check_ready` is the one error path this suite sees, and only in an environment
   where the backend is genuinely not ready.

8. **That `on_activity` does not block, or that a line is passed through untouched.** The first
   needs a clock and a threshold that would fail an honest adapter on a loaded machine; the second
   needs knowing what the adapter meant to say. What is left, and asserted, is that whatever
   arrives is a `str`.

9. **That an adapter reporting `MID_RUN_QUESTIONS` asks every time it should.** A backend that asks
   once and then stops asking passes. "At least the number of rounds the prompt asked for, inside
   one run" is the shape of the clause this suite can see.

10. **That a `stop_reason` is true.** A backend that always answers `COMPLETED`, including when it
    hit its own limit, passes: this suite cannot make a run reach a limit and has no second source
    for the fact. What is pinned is the set of legal values and that `None` is one of them.

11. **Anything about two runs at once.** The port says one runner serves many concurrent tasks -
    a workflow's two reviewers run against one instance - and nothing here starts two.

12. **Most of this is behavioural, and reads a model's conduct as evidence about an adapter.** That
    a refused tool call was tried again, that two questions were asked, that an answer came back in
    the closing text: each is what the port promises, and each is visible only because an agent
    followed an instruction. A model that ignores a numbered, literal prompt fails these tests and
    the failure names the adapter. There is no version of this port whose promises are observable
    without running an agent, so the cost is the price of asserting them at all.

## Where the port is silent, and what this suite assumed

Three readings had to be settled to write a test at all. **That `capabilities()` asked twice a
moment apart answers the same** - the port makes it async so the answer may depend on what is
installed, which is a fact about restarts rather than about consecutive calls, and preflight asks
once and then runs a workflow for an hour on the answer. **That a task carrying tools may be handed
to a backend reporting no `TOOL_CALLING`** - the port neither promises nor forbids it, preflight
would have refused such a role, so that one test declares its skip out loud rather than asserting
into a silence. And **that a run in the poisoned repository is expected to succeed** - a raise there
is treated as this suite's failure and not as evidence about hermeticity, because "the adapter
choked on a settings file it should not have read" and "the backend was down" are the same
exception from out here.
"""

from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from agl.ports.agent import AgentRunner, Capability, ModelId, StopReason

from ._agent_hermeticity import AgentHermeticityContract
from ._agent_preflight import AgentPreflightContract
from ._agent_questions import AgentQuestionContract
from ._agent_tasks import (
    CORRECT_A_REFUSED_NOTE,
    KEEP_CALLING_A_FAILING_NOTE,
    SAY_WHAT_THIS_IS,
    Activity,
    Notes,
    outcome_of,
    task,
    workspace,
)


class AgentContract(AgentPreflightContract, AgentQuestionContract, AgentHermeticityContract):
    """The suite. Everything an `AgentRunner` promises, and nothing an implementation gets to pick.

    Its own four tests are what a `run` answers for with no machinery around it: an outcome whose
    stop reason may be `None`, a refused tool call that goes back to the agent inside the same run,
    a tool call whose handler raised, which goes back the same way, and activity that may never
    arrive at all. The three halves it inherits are named in this module's docstring, and
    `_agent_hermeticity` among them is the centrepiece - the one test here whose failure mode is to
    silently prove nothing.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and
    a test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def runner(self) -> AgentRunner | Iterator[AgentRunner]:
        """The implementation under test. Override this and `model`, and override nothing else.

        Two knobs, and the second one only because every member of this port takes a `ModelId`.
        Everything else - the workspace, the tasks, the tool, the handlers - this suite builds
        out of the port's own types, so pointing it at an implementation is two visible overrides
        and there is no third place to point it somewhere else by accident.

        The return type is a union so that `mypy --strict` accepts either shape of override:
        return a runner, or `yield` one and tear it down after. pytest takes both, and an override
        narrowing a plain `-> AgentRunner` to `-> Iterator[AgentRunner]` would not typecheck. An
        `async def` fixture (`@pytest_asyncio.fixture`) is a third shape no annotation here can
        cover; if an implementation needs one, a `# type: ignore[override]` on it is the honest
        escape and costs this suite nothing.
        """
        raise NotImplementedError(
            "the AgentRunner contract suite has no implementation to run against: subclass "
            "AgentContract and override the `runner` fixture to hand back the runner under test"
        )

    @pytest.fixture
    def model(self) -> ModelId:
        """A model this runner serves. Both query methods take one, so the suite has to be told.

        It cannot be derived and it cannot be guessed. `capabilities` and `check_ready` take a
        `ModelId` because `adapters/routing.py` implements this same ABC over one adapter per
        provider, and a runner asked "what can you do" with no model named could only answer for
        some provider or other - so there is no model this suite could name that every
        implementation would serve, and asking about one an adapter does not serve would be asking
        a question the port has no answer for.

        An implementation serving several is covered by parametrising the override -
        `@pytest.fixture(params=[...])` returning `request.param` - which runs the whole suite once
        per model. That is the honest way to cover them all, and it is one line in the subclass.
        """
        raise NotImplementedError(
            "the AgentRunner contract suite has no model to ask about: subclass AgentContract and "
            "override the `model` fixture with a ModelId the runner under test serves"
        )

    async def test_a_run_answers_with_an_outcome_whose_stop_reason_may_be_none(
        self, runner: AgentRunner, model: ModelId, tmp_path: Path
    ) -> None:
        """Three legal answers to "why did it stop", and `None` is one of them.

        `None` means "this backend cannot tell you". It is not `COMPLETED` and it is not `LIMIT`,
        and a consumer that reads it as either is inventing a fact: stage 8 reports honestly
        precisely because a harness that says nothing here has a way of saying so. The port chose
        `None` over a third `UNKNOWN` member so that "did not say" is not listed beside two things
        that actually happened.

        `isinstance` and not `in`, because `StopReason` is a `StrEnum` and `"completed"` compares
        equal to `StopReason.COMPLETED` - a membership test would wave through an adapter handing
        back whatever string its backend printed, which is exactly the leak §1.1 caught this port
        carrying before. And `text` is asserted to be a `str` because `""` is what the port says
        "the agent said nothing" looks like: an adapter answering `None` there hands the one member
        that reports what an agent said a second spelling of nothing.
        """
        outcome = await outcome_of(runner, task(workspace(tmp_path), model, SAY_WHAT_THIS_IS))

        reason = outcome.stop_reason
        assert reason is None or isinstance(reason, StopReason), (
            f"a run stopped for {reason!r}. Why an agent stopped has exactly three legal answers: "
            f"it ended its own turn, the backend stopped it against its will, or this backend "
            f"does not distinguish - and the third is spelled None, not a string of its own"
        )
        assert isinstance(outcome.text, str), (
            f"a run answered with text of {type(outcome.text).__name__}. This is the port's only "
            f"content channel - an effect step has no payload anywhere else - and an agent that "
            f"said nothing is reported as the empty string, which is a str"
        )

    async def test_a_refused_tool_call_is_put_back_to_the_agent_inside_the_same_run(
        self, runner: AgentRunner, model: ModelId, tmp_path: Path
    ) -> None:
        """§3.3: a malformed payload is rejected back to the model inside the same conversation.

        Not an adapter retry, not a workflow retry, and not an exception. By the time a call is
        malformed there is a session in flight holding all the reasoning that produced it, and
        throwing that away to start again is the expensive move - so the agent is told, gets
        another go, and carries on from what it already knows.

        What is asserted is the outcome and never the mechanism: the handler invoked more than once
        inside **one** `run`, and that run returning normally. `ToolResult.rejected` is a channel a
        backend may not have, and the port explicitly lets an adapter render the refusal into the
        text the agent reads instead - so a test that looked for an error frame on the wire would
        be refusing a correct implementation for using its own words.

        A second `run` would show up as one call here and fail this, which is the point. So would
        an exception, since a run that raised never reaches the assertion.
        """
        reported = await runner.capabilities(model)
        if Capability.TOOL_CALLING not in reported:
            pytest.skip(
                "this backend reports no TOOL_CALLING, so no tool call of its can be refused; "
                "preflight refuses a role that declares tools against it, and the port has no "
                "opinion on a task carrying tools that a backend cannot call"
            )

        notes = Notes(reject_first=1)
        outcome = await outcome_of(
            runner, task(workspace(tmp_path), model, CORRECT_A_REFUSED_NOTE, tools=(notes.tool,))
        )

        assert len(notes.received) >= 2, (
            f"the tool handler was called {len(notes.received)} time(s) in one run, and the first "
            f"call was refused. A refusal goes back to the agent inside the same conversation so "
            f"it corrects itself and calls again - an adapter that ended the run on it, retried "
            f"the whole task itself, or raised, leaves exactly this trace"
        )
        odd = [payload for payload in notes.received if not isinstance(payload, Mapping)]
        assert not odd, (
            f"a tool handler was handed {odd}, and a handler takes the mapping the port declares - "
            f"an adapter that passes on the raw text its backend produced makes every handler in "
            f"the framework parse a payload the port says is already parsed"
        )
        assert isinstance(outcome.text, str), "and the run itself ended normally"

    async def test_a_tool_handler_that_raises_is_a_refusal_and_not_the_end_of_the_run(
        self, runner: AgentRunner, model: ModelId, tmp_path: Path
    ) -> None:
        """The other half of §3.3's mechanism: a handler that *failed*, not one that refused.

        A tool handler is the caller's own code and it can hit a bug - an unwritable file, a
        service that is down, a `KeyError` in somebody's payload reading. The agent is told and
        gets another go, exactly as it does for a payload the handler turned down: by the time a
        call has failed there is a session in flight holding all the reasoning that produced it,
        and the argument for not throwing that away is the same argument.

        **This clause exists because its silence was doing damage.** The suite pinned the refusal
        path and said nothing here, and two fakes of this port answered it differently for a whole
        stage - one carrying the run on, one killing it - with every suite green. A clause can only
        be written where every implementation agrees, so writing it is what closes that: an
        implementation that lets a handler's exception out of `run` reports a failure in
        `--dry-run` that the backend it stands in for would have carried through, and one that
        swallowed it silently would leave the agent with nothing to correct.

        What is asserted is the outcome and never the mechanism, exactly as above: the handler
        invoked more than once inside **one** `run`, and that run returning normally. The words the
        agent was told are not asserted, because every implementation has its own - one prefixes
        the tool's name, another hands over the vendor's rendering of the exception - and a suite
        that read them would be refusing a correct adapter for its phrasing.

        A run that raised never reaches the assertion, which is the point of provoking it this way.
        """
        reported = await runner.capabilities(model)
        if Capability.TOOL_CALLING not in reported:
            pytest.skip(
                "this backend reports no TOOL_CALLING, so no tool call of its can fail; preflight "
                "refuses a role that declares tools against it, and the port has no opinion on a "
                "task carrying tools that a backend cannot call"
            )

        notes = Notes(raise_first=1)
        outcome = await outcome_of(
            runner,
            task(workspace(tmp_path), model, KEEP_CALLING_A_FAILING_NOTE, tools=(notes.tool,)),
        )

        assert len(notes.received) >= 2, (
            f"the tool handler was called {len(notes.received)} time(s) in one run, and the first "
            f"call raised. A handler that failed reaches the agent as a refusal it can read and "
            f"act on, inside the same conversation - an adapter that ended the run on it, retried "
            f"the whole task itself, or let the exception out of `run`, leaves exactly this trace"
        )
        odd = [payload for payload in notes.received if not isinstance(payload, Mapping)]
        assert not odd, (
            f"a tool handler was handed {odd} on a call after one that raised. A retry after a "
            f"failure is an ordinary call and carries the mapping the port declares, not the raw "
            f"text a backend produced"
        )
        assert isinstance(outcome.text, str), "and the run itself ended normally"

    async def test_activity_lines_are_plain_strings_and_may_never_arrive_at_all(
        self, runner: AgentRunner, model: ModelId, tmp_path: Path
    ) -> None:
        """A string, passed through untouched, sync, and never something a caller may expect.

        "It was called" is not assertable and is not asserted: an adapter with nothing to report
        calls it never, activity is live-only and never persisted, and a step replayed from cache
        correctly has none at all. What is left is what arrives when something does - a plain
        string, because the port refuses an `Activity` type, a shared verb taxonomy and any shape
        imposed on what an adapter may say, and the cost of that is cosmetic inconsistency rather
        than a backend forced to map its vocabulary onto another's.

        That it must not block is not asserted either. It would need a clock and a threshold, and a
        threshold fails an honest adapter on a loaded machine before it catches a slow callback.
        """
        activity = Activity()
        outcome = await outcome_of(
            runner, task(workspace(tmp_path), model, SAY_WHAT_THIS_IS), on_activity=activity
        )

        strange = [line for line in activity.lines if not isinstance(line, str)]
        assert not strange, (
            f"activity arrived as {[type(line).__name__ for line in strange]}. It is a plain "
            f"string and the framework passes it through untouched: an adapter with an event "
            f"object to report formats its own line, which is the whole of what this port asks"
        )
        assert isinstance(outcome.text, str), "and the run itself ended normally"
