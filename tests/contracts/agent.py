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
drifting into fiction. It is written against the port alone, before any of them exists, because a
subagent that writes its own tests writes tests that pass - and every adapter ships only once "the
contract suite passes", a sentence worth something only when the suite had no stake in the outcome.

`AgentContract` is one class assembled from three modules, and only this name is public. Its own
tests are the five things a `run` answers for that need no machinery: the outcome, a refused tool
call, a tool call whose handler *failed*, the activity it may or may not report, and what becomes
of a run whose activity reporter raises. The two it inherits follow seams the port draws itself.
`_agent_preflight` holds the two members that are asked *about* an agent rather than running one;
`_agent_hermeticity` holds the poisoned repository and the table it is built from, and is the
centrepiece. `_agent_tasks` under all of them holds the workspace, the tasks, the tool and the one
callback every test is made of, and argues there why this suite touches a filesystem when the store
suite refuses to.

**There was a fourth module and it was deleted rather than emptied.** `_agent_questions` held the
mid-run negotiation - a handler on the port, two rounds inside one run, and an adapter that must not
block on a question nobody was listening for. Its subject was `on_question`, a port member that no
longer exists: a question is an ordinary tool a workflow supplies, so what is left of that clause is
the two tool clauses below, which every implementation already owed. Nothing about a *question* is
asserted here now, and nothing should be - the port has never heard of one.

## Written against the port, never against a harness

The audience is an adapter that does not exist yet, possibly one nobody has thought of. Nothing here
assumes a subprocess, a command line, a config file, an HTTP call, a session object or a machine.
The tests speak `AgentTask`, `AgentOutcome`, `Capability`, `Question` and `ToolResult`, because
those are the whole of what the port accepts and answers with.

Where a backend genuinely differs, the suite branches on **what the port says it can do** and never
on which implementation it is: `Capability.TOOL_CALLING` decides whether a tool call can be rejected
or failed. That is the port's own escape hatch, stated in `capabilities()` by the adapter itself. A
test that asked "is this the X adapter" would be a test somebody has to edit when the second X
arrives.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe.

1. **That any adapter is hermetic - when the runner is a fake.** A fake reads no configuration, so
   the poisoned repository cannot catch it doing anything. The test is trivially satisfied there by
   construction and bites only against the real adapters. `_agent_hermeticity` says this at more
   length and says why it is still written to bite.

2. **A configuration an adapter loaded that the agent then ignored.** The poison is instructions,
   and instructions are only visible once acted on. Three channels make that likelier; none of them
   makes it certain.

3. **Anything at all about the environment a backend runs in.** No test here reads or asserts an
   environment variable. That is **deferred by decision, not overlooked**: credential-environment
   isolation was left unbuilt because AGL inherits the parent environment, because managing what
   reaches a spawned agent interacts with proxies, cloud credentials and each harness's own
   precedence rules, and because the operator can simply keep the key unset. It is the *second*
   channel, put out of scope in the same breath that put hermeticity in. Adding an environment
   assertion here would be building the thing that was declined.

4. **That a `Restriction` was enforced.** The port lets a backend with no mechanism put a
   restriction to the agent as an instruction, so a dropped `NO_FILE_WRITES` and an agent that did
   not happen to write a file are the same observation. Every task here declares none, which is the
   only honest thing a suite that cannot check them can ask for.

5. **That `plan_only` changed anything**, for the same reason and with the same two honest
   implementations behind it - a harness that selects a mode, and one that says it in the prompt.

6. **That `context` was kept apart from `instructions`.** A backend that distinguishes standing
   context honours the distinction and one that does not joins two strings; both are correct, and
   an `AgentOutcome` cannot tell them apart.

7. **That a backend failure is translated into `errors.py`.** Nothing here can make a backend fail
   on demand - there is no member for it and inventing one would be inventing a port - so no test
   provokes a translation. `check_ready` is the one error path this suite sees, and only in an
   environment where the backend is genuinely not ready. Two clauses below do put an exception
   through `run` on purpose - a tool handler that raises, an activity reporter that raises - and
   neither is evidence about translation: both assert that the *caller's own* exception arrives
   untranslated, which is the opposite promise and says nothing about what an adapter does with a
   failure of its backend's.

8. **That `on_activity` does not block, or that a line is passed through untouched.** The first
   needs a clock and a threshold that would fail an honest adapter on a loaded machine; the second
   needs knowing what the adapter meant to say. What is left, and asserted, is that whatever
   arrives is a `str`.

9. **That an agent can be made to call a tool more than once, except by refusing it.** The
   rejection clause gets a second call because the handler refused the first and the prompt orders
   a retry; nothing here can ask for N *accepted* calls and check the count, and a backend that
   calls a tool once and then stops calling passes everything below.

10. **That a `stop_reason` is true.** A backend that always answers `COMPLETED`, including when it
    hit its own limit, passes: this suite cannot make a run reach a limit and has no second source
    for the fact. What is pinned is the set of legal values and that `None` is one of them.

11. **Anything about two runs at once.** The port says one runner serves many concurrent tasks -
    a workflow's two reviewers run against one instance - and nothing here starts two.

12. **Most of this is behavioural, and reads a model's conduct as evidence about an adapter.** That
    a refused tool call was tried again, that a failed one was not, that a poisoned repository was
    ignored: each is what the port promises, and each is visible only because an agent followed an
    instruction. A model that ignores a numbered, literal prompt fails these tests and the failure
    names the adapter. There is no version of this port whose promises are observable without
    running an agent, so the cost is the price of asserting them at all.

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
from ._agent_tasks import (
    CORRECT_A_REFUSED_NOTE,
    KEEP_CALLING_A_FAILING_NOTE,
    SAY_WHAT_THIS_IS,
    Activity,
    Notes,
    ReporterFailed,
    ToolFailed,
    outcome_of,
    task,
    workspace,
)


class AgentContract(AgentPreflightContract, AgentHermeticityContract):
    """The suite. Everything an `AgentRunner` promises, and nothing an implementation gets to pick.

    Its own five tests are what a `run` answers for with no machinery around it: an outcome whose
    stop reason may be `None`, a refused tool call that goes back to the agent inside the same run,
    a tool call whose handler *raised*, which - unlike the refusal - ends the run with the
    handler's own exception, activity that may never arrive at all, and an activity reporter that
    raised, which ends it the same way. The two halves it inherits are named in this module's
    docstring, and `_agent_hermeticity` among them is the centrepiece - the one test here whose
    failure mode is to silently prove nothing.

    Eight clauses: two ask *about* an agent and six run one. Of the six, five are evidence about an
    adapter obtained by watching an agent follow an instruction (gap 12) - a tool called, a tool
    refused, a poisoned repository ignored - and that is what keeps them behind the real adapters'
    live gate, where they are deferred to the manual QA pass. The activity-reporter clause is the
    exception and is written to be one: it asks the agent for nothing, so any free instrument that
    produces a single line of activity reaches it, and the real adapters' own suites run exactly
    that assertion offline beside their other activity tests.

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
        and a consumer that reads it as either is inventing a fact: an adapter reports honestly
        precisely because a harness that says nothing here has a way of saying so. The port chose
        `None` over a third `UNKNOWN` member so that "did not say" is not listed beside two things
        that actually happened.

        `isinstance` and not `in`, because `StopReason` is a `StrEnum` and `"completed"` compares
        equal to `StopReason.COMPLETED` - a membership test would wave through an adapter handing
        back whatever string its backend printed, which is exactly the leak this port was found
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
        """A malformed payload is rejected back to the model inside the same conversation.

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

    async def test_a_tool_handler_that_raises_ends_the_run_with_its_own_exception(
        self, runner: AgentRunner, model: ModelId, tmp_path: Path
    ) -> None:
        """The other half of that mechanism, and it runs the other way: a handler that *failed*.

        A tool handler is the caller's own code and it can hit a bug - an unwritable file, a
        service that is down, a `KeyError` in somebody's payload reading. The port settles what an
        adapter does about it: the exception comes out of `run` in place of an `AgentOutcome`, as
        the object the handler raised, and the session stops rather than running on to its natural
        end.

        **This clause used to say the opposite, and answering that is the point.** It read
        `test_a_tool_handler_that_raises_is_a_refusal_and_not_the_end_of_the_run`, and its argument
        was the one the clause above still makes: by the time a call has failed there is a session
        in flight holding all the reasoning that produced it, and throwing that away is the
        expensive move. What answers it is that a handler which wants the agent to try again
        already has a way to say so, and it is `ToolResult(rejected=True)` - pinned immediately
        above, unchanged, and the reason nothing is lost by reading a *raise* as something else.
        The split is: refusal returns, failure raises. Absorbing the failure instead is what makes
        an unanswerable approval gate silently absent while the step records an answer anyway - the
        agent shrugs off a refusal it cannot act on, the run finishes normally, and `run.step`
        writes down a result nobody stood behind. And the expense is smaller than it looks: a step
        that dies is a step the journal never recorded, so a resume replays everything before it
        and the session is bought again rather than lost.

        **This clause exists because its silence was doing damage**, which was true when it was
        written the other way round and is still the reason it is written at all. The suite pinned
        the refusal path and said nothing here, and two fakes of this port answered it differently
        for a long time - one carrying the run on, one killing it - with every suite green. A
        clause can only be written where every implementation agrees; what changed is which way
        they were made to agree.

        What is asserted is the exception and the trace, never the mechanism. The words the agent
        was told before the run ended are not asserted, because every implementation has its own
        and a suite that read them would be refusing a correct adapter for its phrasing - what
        matters is that the handler was not asked a second time, which is what "the session stops"
        looks like from out here.

        **The prompt is the control.** `KEEP_CALLING_A_FAILING_NOTE` orders the agent to call again
        on any error, failure or refusal until a call is accepted, so an implementation that put
        the failure back into the conversation gets a model actively trying to make a second call -
        and `received` of more than one is what that leaves behind.
        """
        reported = await runner.capabilities(model)
        if Capability.TOOL_CALLING not in reported:
            pytest.skip(
                "this backend reports no TOOL_CALLING, so no tool call of its can fail; preflight "
                "refuses a role that declares tools against it, and the port has no opinion on a "
                "task carrying tools that a backend cannot call"
            )

        notes = Notes(raise_first=1)
        with pytest.raises(ToolFailed) as raised:
            await outcome_of(
                runner,
                task(workspace(tmp_path), model, KEEP_CALLING_A_FAILING_NOTE, tools=(notes.tool,)),
            )

        assert raised.value is notes.failure, (
            f"the run ended with {raised.value!r} and the handler raised {notes.failure!r}. It is "
            f"the caller's own exception that comes out, as itself: a `raise ... from` or an "
            f"AglError built around it destroys what the caller wrote its `except` against, and a "
            f"workflow's own Stop then has its exit code decided by whichever adapter served the "
            f"step"
        )
        assert len(notes.received) == 1, (
            f"the tool handler was called {len(notes.received)} time(s) in one run, and the first "
            f"call raised. A handler that failed ends the run, and the prompt this task carries "
            f"orders the agent to keep calling on any error - so a second call is an adapter that "
            f"put the failure back into the conversation and spent more of the run on a session "
            f"that was already over"
        )
        odd = [payload for payload in notes.received if not isinstance(payload, Mapping)]
        assert not odd, (
            f"a tool handler was handed {odd}. A call that goes on to fail is an ordinary call on "
            f"the way in and carries the mapping the port declares, not the raw text a backend "
            f"produced"
        )

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

    async def test_an_activity_reporter_that_raises_ends_the_run_with_its_own_exception(
        self, runner: AgentRunner, model: ModelId, tmp_path: Path
    ) -> None:
        """The port's rule about a broken reporter, which used to be four implementations agreeing.

        `on_activity` is the caller's code and it can hit a bug - a dashboard that has gone away, a
        `KeyError` in somebody's formatting. The port settles what an adapter does about it, and
        the answer is nothing: the exception comes out of `run` in place of an `AgentOutcome`, no
        adapter guards the call, and no adapter carries the rest of the run on without it.

        **Why that and not the swallow.** Activity is decoration - live-only, never persisted, and
        a run that dies because a progress line could not be drawn has lost real work for a
        cosmetic reason. Against which: the framework's own reporter is a single assignment, so a
        reporter that raises is a *broken* one and the trade is not "a step or a progress line" but
        "a bug that says so or a bug that does not, on every step, for the length of a run"; the
        clause above says the same of a **tool handler**, which is the closest neighbour there is -
        the other piece of caller code an adapter invokes during a run, ending it with its own
        exception for its own reasons; terminal views are decoration by the same definition and
        what a view raises comes straight out; and a step that dies is a step the journal never
        recorded, so a resume replays everything before it. `ports/agent.py` carries the argument
        in full.

        The tool handler is cited here and `on_question` is not, although `on_question` raising
        ended a run too and used to be the evidence this paragraph gave. It was a callback on its
        way *out* of the port, and it has since gone - along with the framework-supplied asking tool
        and `Capability.MID_RUN_QUESTIONS` - which is precisely why the citation was moved off it
        while it still existed. A rule resting on a member that could be deleted was a rule with no
        support; the tool handler is the member every implementation of this port is built around,
        and it is what a question travels on now.

        **This clause exists because its silence was doing damage**, exactly as the tool-handler
        one above does. Both fakes and both real adapters let the exception out, and none of them
        had a rule to be following - so the next adapter, or the next tidy-up of an existing one,
        would have been free to wrap the call in a `try` and be correct by every test in the build.

        **It needs no model conduct**, which is what separates it from the seven other clauses
        here that run an agent. Nothing is asked of the agent: whatever the backend happens to
        report is what the reporter fails on, so a scripted fake, a canned transport or a stub CLI
        reaches it. The real adapters' own suites run it that way, offline, beside their other
        activity tests.

        The first run is a probe rather than a duplicate. The port lets an adapter report nothing
        at all, and a reporter that is never called cannot raise; without asking first, an
        implementation that reports nothing would fail this for having no activity rather than for
        breaking a promise. No implementation in this build takes the skip, and it is written
        because the port permits one that would.
        """
        watched = Activity()
        await outcome_of(
            runner, task(workspace(tmp_path), model, SAY_WHAT_THIS_IS), on_activity=watched
        )
        if not watched.lines:
            pytest.skip(
                "this backend reported no activity for this task, which the port explicitly "
                "allows - 'an adapter with nothing to report calls it never'. A reporter that is "
                "never called cannot raise, so there is nothing here for a rule about raising"
            )

        failing = Activity(raise_first=1)
        with pytest.raises(ReporterFailed):
            await outcome_of(
                runner, task(workspace(tmp_path), model, SAY_WHAT_THIS_IS), on_activity=failing
            )

        assert len(failing.lines) == 1, (
            f"the reporter was called {len(failing.lines)} time(s) and it raised on the first. An "
            f"adapter that kept reporting caught the exception somewhere and carried on, which is "
            f"the swallow this clause exists to forbid - a broken callback then goes unmentioned "
            f"for the length of the run, on every line, in code the port says is the caller's"
        )
