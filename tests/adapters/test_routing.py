"""`RoutingAgentRunner`: the right adapter for every model, and a loud refusal for every other.

The stage's named acceptance is two sentences - correct provider dispatch, and an unknown provider
failing loudly - and everything below is one of them, one of the port's own promises surviving the
trip through this class, or one of the constructor's refusals.

## Yes, the contract suite runs here, and it runs over fakes

§1.9's rule is that every implementation of a port passes that port's contract suite, and
`RoutingAgentRunner` is an implementation of `AgentRunner` - in fact the *only* one a workflow ever
holds, since `config/container.py` puts this in the services bundle and the vendor runners behind
it. Declining the suite on the grounds that this class is "only a dispatcher" would leave the one
runner every step addresses as the one implementation nobody held to the port. A dispatcher is
precisely where a promise gets dropped in transit: five of the suite's eight tests pass through
`run` holding a callback, a tool or a question, and each of them is a thing this class could
silently fail to carry.

So `TestRoutingOverBothFakes` is `AgentContract` with the two fixtures overridden and nothing else
touched, and the `model` fixture is parametrised over **every model both providers serve**, which
the suite blesses as "the honest way to cover them all". Eight tests, six models: the whole port,
end to end through the dispatch path, once per member of both enums.

**Over fakes, and never over the vendor runners.** Forty-eight harness sessions is a bill and a
wait, and no test in this repository spends a token or starts a process; the fakes are what stage 7
and stage 8 built for exactly this. Nothing is lost, because what is under test here is dispatch,
and dispatching to a fake exercises this module identically to dispatching to a subprocess. What a
green run here does *not* say is anything about the vendor adapters - `test_claude_code_fake.py`,
`test_openai_fake.py` and the two runner files are where those are held to the same suite.

## Two fakes, one set of names, and the pattern this file establishes

`FakeAgentRunner`, `Conversation`, `Script` and `unscripted` are exported by both
`adapters/claude_code/fake.py` and `adapters/openai/fake.py`, deliberately: they are two
implementations of one idea, and a reader who has met one should not have to learn a second
vocabulary for the other. The OpenAI fake's docstring states what an importer of both must therefore
do - import the *modules*, not the names - and this file is the first place both are imported, so
the pattern is set here:

    from agl.adapters.claude_code import fake as claude_fake
    from agl.adapters.openai import fake as openai_fake

Every use below is qualified by its module. The two `Conversation` classes are unrelated types that
happen to share a name, which is why `Ran` further down carries two methods holding the same two
lines twice: a `Script` is `(Conversation) -> Awaitable[AgentOutcome]` in both modules, over two
classes no annotation can unify, and one method would have to lie about one of them.
`config/container.py` inherits this constraint at stage 11, where it compiles a workflow-level
scripting vocabulary into one callable per provider.

## Nothing in this file implements `AgentRunner` except the class under test

A recording stub runner is the obvious way to see which adapter a call reached, and it is
deliberately absent. A third implementation of this port, written by the author of the tests that
read it and held to the contract suite by nobody, is the fiction §1.9 exists to keep out of a
codebase - and it would be a fourth `AgentRunner` whose agreement with the port nothing checks.

What a router dispatched to is observed through two things that already exist instead. **A script**,
which is the fakes' own sanctioned extension point and an agent's conduct in the only vocabulary the
port has: a script records the task it was handed and answers with a text naming which fake ran it.
And **an adapter's own refusal**, which names the models that adapter serves - so a router wired
deliberately wrongly, with one provider's fake registered under the other's key, reveals through the
refusing adapter's own words which entry of the table was consulted. That is the only instrument
that can see `capabilities` and `check_ready` dispatch at all, since the two fakes answer both of
them identically for every model they serve.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import pytest

from agl.adapters.claude_code import fake as claude_fake
from agl.adapters.openai import fake as openai_fake
from agl.adapters.routing import RoutingAgentRunner
from agl.ports.agent import (
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Claude,
    ModelId,
    OpenAI,
    Provider,
    StopReason,
)
from agl.ports.errors import AglError, InputError, InternalError, exit_code_for
from contracts._agent_tasks import (
    NOTE_WHAT_THIS_IS,
    SAY_WHAT_THIS_IS,
    Activity,
    Answers,
    Notes,
    task,
    workspace,
)
from contracts.agent import AgentContract

# Module-level tests do not inherit the marker the contract class sets on itself, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is how
# a file like this passes against a dispatch it never performed.
pytestmark = pytest.mark.asyncio


class TestRoutingOverBothFakes(AgentContract):
    """The port in full, six times over - once per model either provider serves.

    Two overrides and nothing else, which is what the suite asks for. Neither is gated: nothing
    here starts a process, binds a socket or spends a token, so a skip would be hiding something
    rather than declining to do it. All eight tests run against every model, and each one of them
    reaches its fake through `RoutingAgentRunner._serving` and back.
    """

    @pytest.fixture
    def runner(self) -> AgentRunner:
        """A router over both fakes, unscripted, which is the bundle stage 9 will assemble.

        Deliberately unscripted, for the reason `test_openai_fake.py` gives: a fake handed a script
        written by the author of its own tests answers an exam it set itself, and the suite's five
        prompts are the set this dispatch must carry without having been shown them.
        """
        return RoutingAgentRunner(
            {
                Provider.CLAUDE: claude_fake.FakeAgentRunner(),
                Provider.OPENAI: openai_fake.FakeAgentRunner(),
            }
        )

    @pytest.fixture(params=[*Claude, *OpenAI])
    def model(self, request: pytest.FixtureRequest) -> ModelId:
        """Every model in the port, one whole run of the suite each.

        The one runner in the repository for which this parametrisation is not a thoroughness
        decision: a router answers for several providers, so a suite that named one model would be
        eight tests about one arm of a dispatch and silence about the other.
        """
        return cast(ModelId, request.param)


# --- What the fakes are asked to do, and how it is seen ------------------------------------------

CLAUDE_RAN: Final = "the adapter registered under claude ran this task"
OPENAI_RAN: Final = "the adapter registered under openai ran this task"

# A representative model per provider, for the tests that are about the dispatch rather than about
# covering the enums - `TestRoutingOverBothFakes` above is what walks every member.
SERVED: Final[Mapping[Provider, ModelId]] = {
    Provider.CLAUDE: Claude.SONNET,
    Provider.OPENAI: OpenAI.TERRA,
}

# Each provider's fake, reached through its own module. Two classes of one name: this mapping is
# the whole reason the imports at the top of this file are module imports.
FAKES: Final[Mapping[Provider, Callable[[], AgentRunner]]] = {
    Provider.CLAUDE: claude_fake.FakeAgentRunner,
    Provider.OPENAI: openai_fake.FakeAgentRunner,
}


class Ran:
    """A script for either fake that records what it was handed and says which fake ran it.

    Two methods holding the same two lines, because `Script` is
    `(Conversation) -> Awaitable[AgentOutcome]` in both fake modules over two unrelated
    `Conversation` classes - the collision the module docstring describes, in the one shape where it
    cannot be papered over. A single method annotated against either one would be a type error at
    the other's constructor, and annotating it against `object` would give up the thing that makes a
    script worth writing: `conversation.task`.

    It records the task rather than a count, so a test can assert not only that an adapter ran but
    that it ran *the task that was asked for* - a router that dispatched correctly and passed on a
    task of its own devising would be invisible to a counter.
    """

    def __init__(self) -> None:
        self.asked: list[tuple[str, AgentTask]] = []

    async def claude(self, conversation: claude_fake.Conversation) -> AgentOutcome:
        return self._record(CLAUDE_RAN, conversation.task)

    async def openai(self, conversation: openai_fake.Conversation) -> AgentOutcome:
        return self._record(OPENAI_RAN, conversation.task)

    def _record(self, said: str, work: AgentTask) -> AgentOutcome:
        self.asked.append((said, work))
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text=said)


def recorded() -> tuple[Ran, RoutingAgentRunner]:
    """A router over both fakes, each scripted to say which one it is, and the record they share."""
    ran = Ran()
    return ran, RoutingAgentRunner(
        {
            Provider.CLAUDE: claude_fake.FakeAgentRunner(ran.claude),
            Provider.OPENAI: openai_fake.FakeAgentRunner(ran.openai),
        }
    )


type Member = Callable[[AgentRunner, ModelId, Path], Awaitable[None]]


async def _capabilities(runner: AgentRunner, model: ModelId, where: Path) -> None:
    await runner.capabilities(model)


async def _check_ready(runner: AgentRunner, model: ModelId, where: Path) -> None:
    await runner.check_ready(model)


async def _run(runner: AgentRunner, model: ModelId, where: Path) -> None:
    await runner.run(task(where, model, SAY_WHAT_THIS_IS))


# Every member of the port, so that the tests about refusing name all three rather than the one
# that was easiest to write. A member that dispatched while its neighbours did not would be a
# preflight admitting a run that the step then cannot start.
MEMBERS: Final[Mapping[str, Member]] = {
    "capabilities": _capabilities,
    "check_ready": _check_ready,
    "run": _run,
}


# --- Dispatch: the right adapter, the whole task, and nothing added on the way back --------------


@pytest.mark.parametrize("provider", sorted(SERVED))
async def test_a_task_is_run_by_the_adapter_registered_for_its_providers_key(
    provider: Provider, tmp_path: Path
) -> None:
    """The stage's first acceptance: `task.model.provider` decides, and one adapter runs.

    Both halves are asserted from one record. That the right fake ran is the pair's first element;
    that the *other* fake did not is the list holding one entry, which a test asserting only "the
    Claude one ran" could not tell from a router that ran both and returned the first answer.
    """
    ran, router = recorded()
    work = task(workspace(tmp_path), SERVED[provider], SAY_WHAT_THIS_IS)

    outcome = await router.run(work)

    said = CLAUDE_RAN if provider is Provider.CLAUDE else OPENAI_RAN
    assert ran.asked == [(said, work)], (
        f"a task naming {str(SERVED[provider])!r} produced {ran.asked}. It is served by "
        f"{str(provider)!r} and the runner registered under that key is the one that must see it - "
        f"unchanged, since a router that composed a task of its own would be answering a question "
        f"the workflow did not ask"
    )
    assert outcome.text == said


async def test_the_outcome_handed_back_is_the_one_the_adapter_answered_with(tmp_path: Path) -> None:
    """Identity, not equality: nothing is rebuilt, annotated or filled in on the way out.

    `AgentOutcome` is frozen and slotted, so the object that comes back out of `run` being the same
    object the adapter produced is a fact worth asserting - it is the strongest available statement
    that this class adds no field of its own. `stop_reason=None` is the one to carry it: "the
    backend did not say" is the value a router would be most tempted to improve into `COMPLETED`,
    and `text=""` is the same temptation on the other field.
    """
    answered: Final = AgentOutcome(stop_reason=None, text="")

    async def hands_back(conversation: claude_fake.Conversation) -> AgentOutcome:
        return answered

    router = RoutingAgentRunner({Provider.CLAUDE: claude_fake.FakeAgentRunner(hands_back)})
    outcome = await router.run(task(workspace(tmp_path), Claude.HAIKU, SAY_WHAT_THIS_IS))

    assert outcome is answered, (
        "the outcome that came back is not the object the adapter answered with. A router that "
        "rebuilds one has somewhere to put a field of its own, and 'which adapter served this' is "
        "exactly the field §1.1 caught this port carrying before"
    )


@pytest.mark.parametrize("member", sorted(MEMBERS))
async def test_a_query_is_answered_by_the_runner_under_the_key_and_not_by_the_model(
    member: str, tmp_path: Path
) -> None:
    """`capabilities` and `check_ready` reach the table's entry, not some adapter that fits.

    The router here is wired **deliberately wrongly** - the OpenAI fake registered under
    `Provider.CLAUDE` - and no correct bundle ever looks like this. It is the only instrument that
    can see these two dispatch at all: both fakes report the same four capabilities and neither
    `check_ready` can fail, so two correct answers are indistinguishable and a wrong one is not.

    Asked for a Claude model, the router hands it to the runner under `claude`, which refuses it
    because that runner serves OpenAI models - and says so by naming them. A router that read the
    model instead of its own table would have found no Claude adapter and refused in its own words;
    one that fell back to a runner that fits would not have refused at all.
    """
    router = RoutingAgentRunner({Provider.CLAUDE: openai_fake.FakeAgentRunner()})

    with pytest.raises(InputError) as refusal:
        await MEMBERS[member](router, Claude.OPUS, workspace(tmp_path))

    assert str(OpenAI.SOL) in str(refusal.value), (
        f"{member} was refused with {str(refusal.value)!r}, which lists no OpenAI model. The "
        f"runner registered under 'claude' here is the OpenAI fake, and its refusal names what it "
        f"serves - a message without one of those in it came from somewhere other than the entry "
        f"this router was built with"
    )


async def test_one_router_serves_two_providers_at_once(tmp_path: Path) -> None:
    """Two runs in flight against one instance, which is what a workflow's `split` does.

    The port says a runner serves many concurrent tasks and gives the reason both callbacks are
    per-call parameters. A router holding per-run state of any kind - the last model, a resolved
    adapter, a cached answer - is the shape that passes every sequential test in this file and
    crosses two reviewers' work the first time a workflow runs them together.
    """
    ran, router = recorded()
    where = workspace(tmp_path)
    mine = task(where, Claude.OPUS, SAY_WHAT_THIS_IS)
    yours = task(where, OpenAI.LUNA, NOTE_WHAT_THIS_IS)

    both = await asyncio.gather(router.run(mine), router.run(yours))

    assert sorted(ran.asked, key=lambda seen: seen[0]) == [(CLAUDE_RAN, mine), (OPENAI_RAN, yours)]
    assert [outcome.text for outcome in both] == [CLAUDE_RAN, OPENAI_RAN]


# --- An unknown provider fails loudly ------------------------------------------------------------


@pytest.mark.parametrize("member", sorted(MEMBERS))
async def test_a_provider_with_no_adapter_is_refused_as_input_and_never_substituted(
    member: str, tmp_path: Path
) -> None:
    """The stage's second acceptance, on all three members, with the exit code asserted.

    `InputError`, so exit 2, so the reader is sent to the configuration that decides which providers
    this run was assembled with. Everything the caller supplied is well-formed - the model exists,
    the provider exists - and what is missing is an adapter nobody configured or nobody installed;
    that is a fact about this machine, not about the framework, which is what makes exit 70 the
    wrong answer and a bug report the wrong destination.

    The message names both the provider that is missing and the ones that are held, because that
    pair is what turns "it did not work" into a choice between configuring one and naming a model
    from another. And the record is asserted empty: the adapter that *is* present was never asked
    to stand in, which the port and both adapters state as the rule and which is the failure worth
    fearing here - a run that quietly produces work nobody asked for.
    """
    ran = Ran()
    router = RoutingAgentRunner({Provider.CLAUDE: claude_fake.FakeAgentRunner(ran.claude)})

    with pytest.raises(InputError) as refusal:
        await MEMBERS[member](router, OpenAI.SOL, workspace(tmp_path))

    said = str(refusal.value)
    assert exit_code_for(refusal.value) == 2
    assert str(OpenAI.SOL) in said and str(Provider.OPENAI) in said, (
        f"{member} refused with {said!r}, which does not name the model or the provider it needed. "
        f"A refusal that does not say which provider was missing leaves a reader comparing a "
        f"workflow's roles against a configuration by hand"
    )
    assert str(Provider.CLAUDE) in said, (
        f"{member} refused with {said!r}, which does not say what this router does hold. The next "
        f"move is either configuring the missing provider or naming a model from one that is "
        f"there, and only one of those two is visible from a message that lists neither"
    )
    assert ran.asked == [], (
        f"the adapter this router does hold was asked to run {ran.asked}. It serves another "
        f"provider entirely: the model was named beside the prompt because the choice was "
        f"semantic, so substituting answers a different question than the workflow asked"
    )


@pytest.mark.parametrize("member", sorted(MEMBERS))
async def test_a_model_whose_prefix_names_no_provider_stays_an_internal_error(
    member: str, tmp_path: Path
) -> None:
    """The distinction the refusal above turns on, asserted as the exit code it decides.

    `ModelId.provider` refuses a member whose prefix names no `Provider` as an `InternalError`,
    because model ids are that module's own enum members and nobody types one - so a malformed one
    was written in AGL's source and exit 70 sends the reader to a bug report. This class must let
    that through untouched. Catching it and re-raising anything softer would send somebody hunting
    through a settings file for a typo in `ports/agent.py`; and the two facts are genuinely
    different, which is the whole reason a provider with no adapter is not this class.

    The model below is defined here rather than found: the port has no malformed member, which is
    the point of it, so the only way to ask this question is to write one that no adapter could
    serve and hand it in.
    """

    class Nowhere(ModelId):
        A_MODEL = "nowhere:a-model"

    router = RoutingAgentRunner({Provider.CLAUDE: claude_fake.FakeAgentRunner()})

    with pytest.raises(InternalError) as broken:
        await MEMBERS[member](router, Nowhere.A_MODEL, workspace(tmp_path))

    assert exit_code_for(broken.value) == 70, (
        "a model id that names no provider came back as something other than our own bug. That is "
        "the one refusal ports/agent.py makes an InternalError, and a router that translated it "
        "into a refusal about configuration would report a typo in the framework as a typo in a "
        "workflow"
    )


# --- The constructor ------------------------------------------------------------------------------


async def test_a_router_over_no_adapters_is_refused_where_it_is_built() -> None:
    """Nothing to route to is a fact about the bundle, so it is refused at the composition root.

    Not deferred to the first run. A router built empty would fail one step at a time, each with a
    message about the provider that step happened to name, when the fact worth reporting once is
    that this run has no agent backend at all. `InputError` is the port's convention for a
    constructor turning down what it was handed - nothing has been attempted - and exit 2 sends the
    reader to the configuration rather than to a bug report.
    """
    with pytest.raises(InputError) as refusal:
        RoutingAgentRunner({})

    assert exit_code_for(refusal.value) == 2
    assert str(refusal.value), "an empty refusal leaves a reader to guess what was empty"


async def test_the_mapping_is_copied_so_routing_cannot_be_changed_underneath_a_run(
    tmp_path: Path,
) -> None:
    """The table a router was built with is the table it uses, whatever the caller does next.

    `Tool.payload_schema`'s reason, one layer out: a caller that keeps the dict it passed could
    otherwise re-point a provider halfway through a workflow, and a step would be served by an
    adapter that was not there when preflight admitted it.
    """
    ran = Ran()
    built: dict[Provider, AgentRunner] = {Provider.CLAUDE: claude_fake.FakeAgentRunner(ran.claude)}
    router = RoutingAgentRunner(built)

    built.clear()
    built[Provider.OPENAI] = openai_fake.FakeAgentRunner(ran.openai)
    work = task(workspace(tmp_path), Claude.OPUS, SAY_WHAT_THIS_IS)
    outcome = await router.run(work)

    assert ran.asked == [(CLAUDE_RAN, work)]
    assert outcome.text == CLAUDE_RAN


# --- What crosses the port on the way through -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transcript:
    """Everything one run of a fake can be seen doing, from outside the port.

    Four channels, because a router can drop a thing on each of them independently: what the agent
    said, why it stopped, every activity line it reported, every question it asked, and every
    payload it handed a tool. `repr` for the last two rather than the objects themselves - the
    contract suite's own instruments keep them as `object` on purpose, so that an adapter handing
    over the raw text its backend produced is catchable, and comparing reprs asserts that whatever
    arrived arrived identically without claiming a type it might not have.
    """

    text: str
    stop_reason: StopReason | None
    activity: tuple[str, ...]
    questions: tuple[str, ...]
    payloads: tuple[str, ...]


async def transcript(runner: AgentRunner, model: ModelId, where: Path) -> Transcript:
    """One unscripted run with all three of the port's per-call channels wired up, recorded."""
    notes = Notes(reject_first=1)
    activity = Activity()
    answers = Answers()
    outcome = await runner.run(
        task(where, model, NOTE_WHAT_THIS_IS, tools=(notes.tool,)),
        on_question=answers,
        on_activity=activity,
    )
    return Transcript(
        text=outcome.text,
        stop_reason=outcome.stop_reason,
        activity=tuple(repr(line) for line in activity.lines),
        questions=tuple(repr(asked) for asked in answers.asked),
        payloads=tuple(repr(payload) for payload in notes.received),
    )


@pytest.mark.parametrize("provider", sorted(SERVED))
async def test_a_routed_run_is_indistinguishable_from_the_same_run_made_directly(
    provider: Provider, tmp_path: Path
) -> None:
    """One fake, two callers, one transcript: `on_question` and `on_activity` pass straight through.

    The control is the same *instance*, addressed directly and then through a router holding it, so
    any difference between the two transcripts is this class's and nothing else's. That is what
    makes the assertion worth making at all: an adapter's own behaviour cancels out of both sides.

    **This is the test that exists because a contract suite cannot catch one half of it.** A dropped
    `on_question` the suite would see, since both fakes report `MID_RUN_QUESTIONS` and it asserts
    two rounds inside one run against a backend that claims to ask. A dropped `on_activity` it would
    not: the suite asserts only that whatever arrives is a `str`, and an adapter with nothing to
    report calls it never, so a router that swallowed every line would pass the whole suite and show
    up as a dashboard that has gone quiet.
    """
    adapter = FAKES[provider]()
    router = RoutingAgentRunner({provider: adapter})
    where = workspace(tmp_path)

    direct = await transcript(adapter, SERVED[provider], where)
    routed = await transcript(router, SERVED[provider], where)

    assert routed == direct, (
        f"the same run made through a router differs from the one made against the adapter "
        f"itself:\n  direct: {direct}\n  routed: {routed}\nEverything a run carries is a per-call "
        f"parameter, and a router that filters, wraps or forgets one of them is a capability "
        f"regression that no workflow could see and no adapter is to blame for"
    )
    assert direct.activity and direct.questions and direct.payloads, (
        "the control run reported no activity, asked nothing and called no tool, so the comparison "
        "above would hold against a router that dropped all three"
    )


@pytest.mark.parametrize("provider", sorted(SERVED))
async def test_a_run_with_neither_callback_reaches_the_adapter_unchanged(
    provider: Provider, tmp_path: Path
) -> None:
    """`None` is a value both callbacks have, and it means "nobody is listening", not "unset".

    A router that defaulted either one - to a handler of its own, to a reporter that swallows lines
    - would turn the port's second settled edge case into something no adapter ever sees: the agent
    would be answered by the framework instead of being told that no answer is available. The fakes
    make that observable, since `unscripted` asks once, is answered `None`, and carries on.
    """
    adapter = FAKES[provider]()
    router = RoutingAgentRunner({provider: adapter})
    where = workspace(tmp_path)

    direct = await adapter.run(task(where, SERVED[provider], SAY_WHAT_THIS_IS))
    routed = await router.run(task(where, SERVED[provider], SAY_WHAT_THIS_IS))

    assert (routed.text, routed.stop_reason) == (direct.text, direct.stop_reason)


@pytest.mark.parametrize("provider", sorted(SERVED))
async def test_an_error_from_the_adapter_arrives_as_the_adapter_raised_it(
    provider: Provider, tmp_path: Path
) -> None:
    """Nothing is caught on the way through, which is what keeps `errors.py` meaning anything.

    An adapter translates whatever its backend throws at its own boundary, and every layer above
    catches those classes by name - preflight catches `UpstreamUnavailable`, a workflow catches
    `Stop`. A router that wrapped one would turn a logged-out session into a framework bug and a
    deliberate end into a failure, and it would do it for every provider at once.

    The exception here is the fake's own refusal of a model it does not serve, which is the one an
    adapter can be made to raise without a backend to break: the router is asked for a model that
    is served by the *other* provider's runner, through a table that sends it to this one.
    """
    other = Claude.OPUS if provider is Provider.OPENAI else OpenAI.SOL
    router = RoutingAgentRunner({other.provider: FAKES[provider]()})

    with pytest.raises(AglError) as refusal:
        await router.run(task(workspace(tmp_path), other, SAY_WHAT_THIS_IS))

    assert type(refusal.value) is InputError, (
        f"the adapter's refusal arrived as {type(refusal.value).__name__}. A router that re-raises "
        f"anything of its own around what an adapter threw breaks every `except` clause above it "
        f"at once, and the subclass is the whole of what those clauses read"
    )
