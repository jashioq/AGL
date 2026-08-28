"""§3.2's preflight: what a run refuses before it starts, and what a step refuses after it has.

The suite over `sdk/_engine/preflight.py`, over the registry UF1.3 put in place of `@workflow`'s
`roles=`, and over the one line it put into `sdk/_engine/steps.py`. Four properties carry it.

**Nothing here constructs a real adapter, and that is a rule rather than a convenience.**
`check_ready` on the Claude harness costs a real turn and on the Codex harness spawns a process, so
every runner below is either `container.fakes()`'s or `_Stub`, declared in this module. `scripts
/check`'s paid-endpoint gate would catch a lapse; not writing one is cheaper than being caught.

**"At second zero" is asserted mechanically and not by reading the source.** The stage's acceptance
criterion is that a role naming a harness that is missing, out of date or logged out fails with
`UpstreamUnavailable` - and what makes that *second zero* rather than merely early is that nothing
durable exists afterwards. So the refused run is asked two questions the ordering decides: is there
a record under `AGL_HOME`, and was `WorkspaceProvider.open` reached at all. The second is asked with
a provider whose every member raises `AssertionError`, because a directory that is not there is also
what a provider that failed would leave, and only a tripwire tells the two apart.

**The registry is a module namespace, so several claims are claims about a whole module.** Since
UF1.3, a workflow's roles are the `@role(model=…)` factories bound in the module its `def` was
executed in, and since UF1.5 also the ones bound in any module bound there. This file is *one*
namespace, and it holds six factories bound directly over two models - the right shape for dedup
and ordering, and the wrong shape for every claim about what a namespace does not hold or about how
a factory reaches it. `tests/instruments/preflight/` is where those four live, one module each: no
factory at all, a factory imported and never used, a factory written below the workflow function,
and a factory reached only as `roles.implementer()` through a bound module.

**The two halves are tested against each other, not separately.** The interesting case is a role
that *passes* preflight and must still be refused: `implementer(on_question=handler)` is the
spelling for §3.7's handler, which is a closure over the `Run`, so the role a module declares and
the role a workflow steps with are different values. A suite that only checked what preflight saw
would go green against an engine in which a handler-carrying role reaches a backend that cannot ask
- which raises nothing, logs nothing, and reports a result (`sdk/roles.py`).

**The refusals are pinned on the part of the message the reader acts on**, which for a capability
miss is the member that is missing and, when a declaration put it there rather than the author, the
word that declaration is spelled with - `on_question` for `MID_RUN_QUESTIONS`, and since 19.2
`tools` for `TOOL_CALLING`. Those clauses are what `roles.py` asks stage 16 for by name: "otherwise
the reader goes looking for a line that is not in their file." Each is conditioned on the trigger
and not on the member, and there is a test for the negative of both: a role that typed its own
requirement is told nothing about where it came from. For an unavailable provider it is now also
*which factory in which module* asked for that model, because the namespace over-approximates and a
person refused for a provider they never meant to use has otherwise no thread to pull.

## What moved at UF1.3, and why it is here rather than deleted

**Capability containment left second zero with `roles=`.** It compares `role.requires` against what
a backend reports, `requires` is on the `Role` a factory *returns*, and preflight may not call a
factory - it has no arguments for a parameter list the author chose. So four suites that measured
containment through `api.run` now measure it through `run.step`:

  * a role requiring what its backend lacks, refused with the member named;
  * a missing `MID_RUN_QUESTIONS` saying that `on_question` put it there;
  * a missing `TOOL_CALLING` saying that `tools` did;
  * a role that typed its own requirement being told nothing about where it came from.

Every one of those claims is unchanged - the class, the exit code and the sentence are the same. All
that moved is the moment, and the moment is what they no longer assert: three of them used to assert
that no record and no workspace existed afterwards, and that is exactly what UF1.3 gave up. The cost
is not merely recorded in prose here - `test_a_negotiating_role_is_checked_at_the_step_it_is_handed
_to` asserts the record is **present** when containment refuses, which is the same fact read from
the other side.

What did not move is the provider half. A logged-out harness is still refused before anything
durable exists, and the acceptance criterion is still met in as many words.
"""

from collections.abc import Set as AbstractSet
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

import pytest

from agl import api
from agl.config import container, registry
from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    Claude,
    ModelId,
    OpenAI,
    QuestionHandler,
    StopReason,
)
from agl.ports.errors import DeniedError, UpstreamUnavailable, exit_code_for
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.questions import Answer, Question
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace, WorkspaceProvider
from agl.sdk._engine import preflight
from agl.sdk.roles import Role, role
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run, workflow
from instruments.preflight import NoParams, entered

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# What the backends in this file can do when nothing says otherwise: everything the port has, which
# is what both real adapters report and what `container.fakes()` reports. Written out as the enum
# so that a fifth member arriving in `ports/agent.py` widens this with the port rather than leaving
# a hand-copied list quietly narrower than the thing it stands in for.
EVERYTHING: Final = frozenset(Capability)

# Everything except the one member §3.2's third check is about. The interesting backend in this
# file, and the one `docs/codex-cli-findings.md` says is a live possibility rather than a fiction:
# `MID_RUN_QUESTIONS` on that harness rests on an asking tool AGL registers itself.
CANNOT_ASK: Final = EVERYTHING - {Capability.MID_RUN_QUESTIONS}


# Everything except the member 19.2's second implication is about. A backend that cannot call a
# tool at all is the sharper of the two cases: the role's reporting tool never reaches the model,
# so the agent cannot fire it, and `Run.step` ends the step with `RoleIncompleteError`.
CANNOT_CALL: Final = EVERYTHING - {Capability.TOOL_CALLING}


@dataclass(frozen=True)
class _Found:
    """The smallest reporting payload there is: one field, so a schema can be derived from it."""

    summary: str


async def _answer(question: Question) -> Answer:
    """§3.7's handler, reduced to the one thing this file needs of it: that it exists.

    A role carrying one has `Capability.MID_RUN_QUESTIONS` folded into `requires` at declaration
    time (`sdk/roles.py`), and that is the whole of its part here - nothing below ever asks a
    question, because every refusal this file is about happens before an agent is dispatched.
    """
    return Answer(text="yes")


# --- the roles, as the `@role(model=…)` factories §3.3 says a role is ----------------------------
#
# Six of them, and since UF1.3 the fact that they are bound *in this module* is the whole of what
# makes them the roles of every workflow declared below: there is no list on a decorator, and the
# namespace is the registry. So this block is also the declaration the availability tests are about
# - two distinct models over six factories, which is what "once per model, not once per role" needs
# to be able to tell apart.


@role(model=Claude.OPUS)
def implementer(*, on_question: QuestionHandler | None = None) -> Role:
    """Requires nothing, and is the role every workflow below that means to *pass* preflight is
    written on.

    **The `on_question` parameter is the whole of the step-time check's case**, and it is
    `fix/roles.py`'s shape: `implementer()` requires nothing and is what a reader of a declaration
    sees; `implementer(on_question=…)` requires `MID_RUN_QUESTIONS`, because `Role.__post_init__`
    folds it in, and is what reaches `run.step`. Nothing before the workflow's body has run can see
    the second, which is why containment is a step-time check and always was."""
    return Role(name="implement", instructions="implement it", on_question=on_question)


@role(model=OpenAI.SOL)
def reviewer() -> Role:
    """A second provider in one run, which is §3.2's motivating case and the reason dedup is
    testable: two models in this namespace, so a run asks twice however many factories name them."""
    return Role(name="review", instructions="review it")


@role(model=Claude.OPUS)
def repairer() -> Role:
    """A third role on `implementer`'s model. Distinct as a value and identical in what preflight
    asks about it, which is exactly what "once per distinct model, not once per role" has to
    distinguish."""
    return Role(name="repair", instructions="repair it")


@role(model=Claude.OPUS)
def builder() -> Role:
    """Declares its requirement in as many words - §3.7's own example role does the same."""
    return Role(
        name="build",
        instructions="run the build until it passes",
        requires={Capability.SHELL},
    )


@role(model=Claude.OPUS)
def proposer() -> Role:
    """Declares no `requires` at all, and requires `MID_RUN_QUESTIONS` all the same. That folding
    is `Role.__post_init__`'s, and it is why the refusal has to say where the member came from."""
    return Role(name="propose", instructions="propose, then ask", on_question=_answer)


@role(model=Claude.OPUS)
def reporter() -> Role[_Found]:
    """The same shape one implication over: declares no `requires` and needs `TOOL_CALLING` all the
    same, because 19.2 folds it in behind `tools=`. §3.3's reporting step, in the smallest form
    that has a payload at all."""
    return Role(
        name="report",
        instructions="read the change, then report what you found",
        tools=[reporting_tool("report_findings", "report what the review found", _Found)],
    )


# --- what each workflow did, recorded at module level because the workflows have to be there -----
#
# `entered` is `instruments/preflight/`'s list, shared with the three workflow modules over there:
# every test that reads it asks one question - did this run reach its workflow, or was it refused
# first - and the answer must not depend on which module the workflow happens to be written in.


@workflow(version="1.1")
async def two_providers(run: Run[NoParams]) -> None:
    """§3.2's own case: this module names Claude and OpenAI, so one run asks both.

    It takes no step, deliberately. What half one measures is what a run asks *before* it does
    anything, and a workflow with a body would put a second reason in every assertion below.
    """
    entered.append("two_providers")


@workflow(version="1.1")
async def replacing(run: Run[NoParams]) -> None:
    """Steps with a role that requires asking, in a module whose factories require nothing.

    **This is the workflow containment exists for**, and it is written the way §3.7 says a
    negotiating workflow is written: the handler is a closure over this `Run`, so the role carrying
    it is built here, by calling the factory with the one argument it exposes. Preflight saw a
    model; what runs is `implementer(on_question=…)`, which needs `MID_RUN_QUESTIONS`, and no scan
    of a namespace could have known that - the value did not exist until this line ran.
    """
    entered.append("replacing")

    async def approve(question: Question) -> Answer:
        """A closure over `run` in the only way that matters here: it is defined inside it."""
        return Answer(text=f"{run.scope.label}: yes")

    await run.step(implementer(on_question=approve))


def _point(name: str, target: str) -> EntryPoint:
    """§3.3's `probe = "agl.workflows.probe:probe"`, pointed at this module or an instrument."""
    return EntryPoint(name=name, value=target, group=registry.GROUP)


POINTS: Final = (
    _point("two_providers", f"{__name__}:two_providers"),
    _point("replacing", f"{__name__}:replacing"),
    # The four whose claim is about a namespace this file cannot have, each in a module of its
    # own - `tests/instruments/preflight/` says why one file could not hold all four.
    _point("unstaffed", "instruments.preflight.unstaffed:unstaffed"),
    _point("unused", "instruments.preflight.unused:unused"),
    _point("late", "instruments.preflight.late:late"),
    _point("qualified", "instruments.preflight.qualified:qualified"),
)


# --- the runner this file drives preflight with --------------------------------------------------


class _Stub(AgentRunner):
    """An `AgentRunner` that answers whatever a test needs and writes down what it was asked.

    Declared here and not in `src/`, because it exists to fail: a backend that is not ready is what
    `container.fakes()` deliberately cannot arrange - "there is nothing to install, nothing to
    resolve on `PATH` and no far side to authenticate against", so both fakes' `check_ready` is
    unreachable by construction. Nothing about it is a second implementation of the port for the
    suite to trust: `tests/contracts/agent.py` holds the real ones and both fakes to the port, and
    this class is an instrument.

    `refusal` is built once and raised by identity, which is what lets a test assert that the
    sentence reaching `api.run`'s caller is the adapter's own and that the exception it raised is
    the cause preflight chained rather than something rebuilt from a class name.
    """

    def __init__(
        self, *, offers: AbstractSet[Capability] = EVERYTHING, ready: bool = True
    ) -> None:
        self.offers: Final = frozenset(offers)
        self.ready: Final = ready
        self.refusal: Final = UpstreamUnavailable(
            "the harness is not on PATH: install it, or log in and try again"
        )
        self.asked_ready: Final[list[ModelId]] = []
        self.asked_offers: Final[list[ModelId]] = []
        self.ran: Final[list[AgentTask]] = []

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        self.asked_offers.append(model)
        return self.offers

    async def check_ready(self, model: ModelId) -> None:
        self.asked_ready.append(model)
        if not self.ready:
            raise self.refusal

    async def run(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        self.ran.append(task)
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")


class _Untouched(WorkspaceProvider):
    """A provider that refuses to have been reached. Every member is a tripwire.

    The assertion "no workspace was opened" cannot be made by looking for a directory: a provider
    that was called and failed leaves no directory either, and so does one that was never called.
    `AssertionError` is not an `AglError`, so it cannot be mistaken for the refusal under test on
    the way out - a `pytest.raises(UpstreamUnavailable)` around a run that opened a workspace fails
    with this message rather than passing on the wrong exception.
    """

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        raise AssertionError("preflight refused this run and a workspace was provisioned anyway")

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("nothing in `api.run` takes a workspace back")

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("nothing in `api.run` deletes a line of work")

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        raise AssertionError(
            "preflight refused this run and its claim on the trees root was taken anyway. §3.10's "
            "run lock sits below preflight for the reason the record does: a refusal that costs "
            "real turns is the last thing that can happen while the run has left nothing behind"
        )


def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment: one repository seeded with a file, one store, one frozen clock."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})


async def _start(
    harness: container.FakeServices, name: str, *, agents: AgentRunner, opens: bool = True
) -> None:
    """One `api.run` with this module's entry points and one substituted port - or two.

    `opens=False` swaps the workspace provider for the tripwire, which every test about a run that
    must not reach the repository passes.
    """
    services = replace(harness.services, agents=agents)
    if not opens:
        services = replace(services, workspaces=_Untouched())
    await api.run(services, PROJECT, name, LABEL, (), points=POINTS)


async def _no_record(harness: container.FakeServices) -> bool:
    """Whether this run left nothing under `AGL_HOME` - half of what "second zero" means."""
    return await harness.services.store.read_record(SCOPE) is None


# --- half one: availability, over the models the workflow's module names -------------------------


@pytest.mark.asyncio
async def test_a_role_whose_harness_is_missing_fails_at_second_zero(tmp_path: Path) -> None:
    """**The stage's acceptance criterion.** A role names a provider whose harness is missing, out
    of date or logged out, and the run dies with `UpstreamUnavailable` before anything durable
    exists. UF1.3 changed where the model comes from and changed nothing about this.

    Four assertions and each is a different failure. The adapter's own sentence is asserted to reach
    the caller **whole**, because it is the only thing that knows which of installed, current and
    authenticated failed, and a preflight that summarised it would drop the one line a person can
    act on. Its exception is asserted to be the `__cause__`, which is where the object itself
    survives now that preflight has something of its own to add - see the provenance test below for
    what that is and why no adapter could have said it. The record is asserted absent, because a run
    refused here must not need an `agl clear` before it can be retried. And the provider is a
    tripwire rather than a directory listing, because a provider that ran and failed leaves no
    directory either.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(ready=False)

    with pytest.raises(UpstreamUnavailable) as caught:
        await _start(harness, "two_providers", agents=stub, opens=False)

    assert str(stub.refusal) in str(caught.value), "the adapter's own reason was not passed on"
    assert caught.value.__cause__ is stub.refusal, "the adapter's refusal is not the cause"
    assert exit_code_for(caught.value) == 6
    assert await _no_record(harness), "a run refused at preflight left a record to be cleared"
    assert entered == [], "the workflow ran although its backend was never ready"


@pytest.mark.asyncio
async def test_check_ready_is_asked_once_per_model_and_not_once_per_role(tmp_path: Path) -> None:
    """§3.2's first check, over *distinct models*. Six factories in this module, two models, two
    questions.

    The dedup is not tidiness. `check_ready` costs a real turn on one of the two harnesses in view,
    so a module with five roles on one model would spend five turns before a line of work had been
    done. Two roles on one model are one question about the state of the world.

    Order is asserted along with the count: a refusal should arrive in the order the author wrote
    their roles, which since UF1.3 is binding order in the module's namespace - a `dict`, and
    therefore ordered - rather than the order of a list on a decorator.
    """
    harness = _fakes(tmp_path)
    stub = _Stub()

    await _start(harness, "two_providers", agents=stub)

    assert stub.asked_ready == [Claude.OPUS, OpenAI.SOL]


@pytest.mark.asyncio
async def test_a_workflow_whose_module_names_no_role_asks_no_backend_anything(
    tmp_path: Path,
) -> None:
    """What an empty registry buys: a workflow that runs no agent runs.

    Not merely "it does not fail". `workflows/noop/` was the case this was written against, and a
    preflight that asked about some default model, or about every provider the bundle was assembled
    with, would have made `agl run noop` depend on a harness that workflow never named - when `noop`
    existed precisely to prove the wiring with nothing else in the way. 19.1 deleted it and the
    argument outlived it.

    The workflow is `instruments/preflight/unstaffed.py`'s and cannot be this module's: since UF1.3
    "declares no roles" is a fact about a whole namespace, and this file's namespace holds six
    factories that every workflow written in it inherits.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(ready=False)

    await _start(harness, "unstaffed", agents=stub)

    assert (stub.asked_ready, stub.asked_offers) == ([], [])
    assert entered == ["unstaffed"]


@pytest.mark.asyncio
async def test_a_factory_written_below_the_workflow_is_still_found(tmp_path: Path) -> None:
    """The scan happens at preflight, not at decoration, and this is the difference between them.

    A module executes top to bottom, so `instruments/preflight/late.py`'s `latecomer` is bound to
    nothing at the moment `@workflow` runs on the function above it. A decoration-time snapshot
    would therefore find an empty namespace, admit the run naming no model at all, and let the first
    step reach a backend nobody had asked about - a fail-open, and the quiet kind. Reading
    `vars(sys.modules[...])` at second zero reads the module after it is whole.

    `Claude.HAIKU` is named by no other module this suite drives, so the one question below can only
    have come from a declaration written under its own workflow.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub()

    await _start(harness, "late", agents=stub)

    assert stub.asked_ready == [Claude.HAIKU]
    assert entered == ["late"]


@pytest.mark.asyncio
async def test_a_role_reached_through_a_module_is_refused_at_second_zero(tmp_path: Path) -> None:
    """**UF1.5's acceptance criterion**: a module-qualified workflow refuses at second zero.

    `instruments/preflight/qualified.py` writes the two lines §3.3 puts in front of every author -
    `from . import roles`, then `await run.step(roles.implementer())` - and binds no `RoleFactory`
    in its own namespace at all. UF1.3's scan read that namespace and only that namespace, so it
    found nothing, asked **zero** backends anything, cleared second zero naming no provider, and
    let the run die at its first step with whatever the adapter said. That is the failure §3.2
    exists to prevent arriving with no warning, and it is worse than the over-approximation below
    for one reason: it is silent. `@workflow(roles=[…])` could not have had it, because the list
    named the roles.

    So the same four questions as the acceptance criterion above, because "at second zero" means
    the same thing here and is not weaker for the role having been harder to find: the class and
    exit 6, no record under `AGL_HOME` for an operator to `agl clear` before retrying, the
    `_Untouched` tripwire rather than a directory listing - a provider that ran and failed leaves
    no directory either - and the workflow function never entered.

    The refusal is the whole test rather than the count of what was asked. `stub.asked_ready` is
    the positive case's business one test down; what this one is about is that a run which used to
    start does not.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(ready=False)

    with pytest.raises(UpstreamUnavailable) as caught:
        await _start(harness, "qualified", agents=stub, opens=False)

    assert exit_code_for(caught.value) == 6
    assert await _no_record(harness), "a run refused at preflight left a record to be cleared"
    assert entered == [], "the workflow ran although its backend was never ready"


@pytest.mark.asyncio
async def test_a_module_qualified_workflow_passes_on_the_model_reached_through_the_module(
    tmp_path: Path,
) -> None:
    """The other side of it: a ready harness, and the question was asked about the right model.

    A refusal alone would go green against a scan that had learned to refuse module-qualified
    workflows on principle, so this asks what the run actually spent. One question, about
    `OpenAI.TERRA`, which no other module this suite drives names - so it can only have come from
    `instruments/preflight/roles.py`, reached one level through the `roles` binding next door.

    The dispatch is asserted with it, because the two together are what make the demand *correct*
    rather than merely present: the model preflight asked about is the model the body then ran on.
    A scan that guessed at some other model would satisfy the first assertion and fail this one.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub()

    await _start(harness, "qualified", agents=stub)

    assert stub.asked_ready == [OpenAI.TERRA], (
        "preflight did not ask about the one model this workflow names, which it names through a "
        "module binding rather than through a factory bound beside its own function"
    )
    assert [task.model for task in stub.ran] == [OpenAI.TERRA]
    assert entered == ["qualified"]


# --- half one: the over-approximation, which is documented behaviour -----------------------------


@pytest.mark.asyncio
async def test_a_role_imported_and_never_used_still_demands_its_provider(tmp_path: Path) -> None:
    """The stage's "known cost, accepted", asserted rather than described.

    `instruments/preflight/unused.py` imports `fix`'s OpenAI `reviewer` and steps with nothing at
    all, and this run asks OpenAI's backend whether it is ready. That is a demand the run does not
    need, and it is the price of the registry being a namespace: which of a module's roles a run
    reaches is decided by the workflow's body, and the body has not run when preflight asks.

    It is pinned because it is **behaviour and not an accident**. A future reader who finds this
    surprising should find a test saying it was chosen, next to the argument for why erring toward
    refusing early is the right direction: this failure is loud and one deleted import from being
    fixed, where an unchecked provider is silent and forty minutes expensive.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub()

    await _start(harness, "unused", agents=stub)

    assert stub.asked_ready == [OpenAI.SOL], "an imported-but-unused role stopped being demanded"
    assert entered == ["unused"]


@pytest.mark.asyncio
async def test_the_refusal_names_the_factory_and_the_modules_the_model_came_from(
    tmp_path: Path,
) -> None:
    """What the over-approximation owes the one person it inconveniences.

    A `fix`-shaped workflow refused because the Codex CLI is logged out has a fix it can act on. A
    workflow that never meant to run an OpenAI model at all has, from the adapter's message alone, a
    provider name and nothing to pull on - the adapter cannot know why AGL asked, because since
    UF1.3 the model came from a namespace scan rather than from a line the author wrote.

    So four things are asserted, and each is a step of the same reader's walk: the factory's own
    name, so they can find the `@role(model=…)` line; the module it was declared in, so they can
    find the file; the module it was *bound* in, which is the workflow's own and therefore where the
    import to delete lives; and the word "imported", because being told that an unused import is a
    known cause is what turns a provider name into a next move.

    This is the one place `UpstreamUnavailable` no longer passes through untouched, and the test
    above holds the other half of that bargain: the adapter's sentence is quoted whole and its
    exception is the cause, so nothing it said is lost to what preflight added.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(ready=False)

    with pytest.raises(UpstreamUnavailable) as caught:
        await _start(harness, "unused", agents=stub, opens=False)

    said = str(caught.value)
    assert "reviewer" in said, "the refusal does not name the factory that demanded the model"
    assert "agl.workflows.fix.roles" in said, "the refusal does not say where it was declared"
    assert "instruments.preflight.unused" in said, "the refusal does not say where it was seen"
    assert "imported" in said, "the refusal does not name the known cause of a false demand"
    assert await _no_record(harness)


@pytest.mark.asyncio
async def test_preflight_asks_whether_a_backend_is_ready_and_never_what_it_can_do(
    tmp_path: Path,
) -> None:
    """What UF1.3 took out of second zero, asserted as an absence at both of its ends.

    Containment used to run here too, over the roles `@workflow(roles=…)` declared, and it cannot:
    it needs `role.requires`, which lives on the `Role` a factory returns, and preflight may not
    call a factory - `implementer(on_question=…)` takes a handler that does not exist until a `Run`
    does. So `capabilities()` is asked by nothing at second zero.

    Both ends, because one of them alone would pass against a preflight that had merely reordered
    itself: a run that is refused asks no capability *after* the refusal, and a run that passes asks
    none *at all*. The first arrangement is also the one that used to carry the "availability before
    capability" ordering rule, which had a reason worth keeping visible - `capabilities()` still
    answers on a machine where the harness is missing, since both adapters report a frozen constant,
    so refusing on it first would tell an operator with no harness installed that their *workflow*
    was wrong.
    """
    harness = _fakes(tmp_path)
    refusing = _Stub(offers=frozenset(), ready=False)

    with pytest.raises(UpstreamUnavailable):
        await _start(harness, "two_providers", agents=refusing, opens=False)

    assert refusing.asked_offers == [], "a capability was asked about a backend that is not there"

    passing = _Stub()
    await _start(_fakes(tmp_path / "second"), "two_providers", agents=passing)

    assert passing.asked_ready == [Claude.OPUS, OpenAI.SOL]
    assert passing.asked_offers == [], "containment ran at second zero, where it cannot"


# --- half two: containment, over the role a step is actually handed ------------------------------
#
# The four suites below measured the same claims through `api.run` until UF1.3. What moved is the
# moment and not the claim: same class, same exit code, same sentence, one `run.step` later. The
# module docstring lists them and says what they stopped being able to assert.


@pytest.mark.asyncio
async def test_a_role_requiring_what_its_backend_lacks_is_refused_with_the_member_named(
    tmp_path: Path,
) -> None:
    """§3.2's second check. `DeniedError` - exit 5 - and the message names the missing member.

    **The class is the port's and not preflight's**, which is why it is pinned here by code as well
    as by name. `ports/errors.py` holds the one exception-to-exit-code table in the codebase and
    lists this case on `DeniedError` in as many words - "an agent lacks a capability the role
    requires" - under a class whose whole distinction is "refusal, not absence: something reachable
    said no. If nothing answered at all, that is `UpstreamUnavailable`."

    That contrast is what the two assertions on exit codes are for, here and in the availability
    test above. 5 and 6 are the two ways a run can end on a backend's answer and they send a reader
    to two different places: the harness is there and cannot do this, so the workflow changes; or
    the harness is not there, so a login does. An `InputError` would be a third answer - input AGL
    could not make sense of - and every term of this role was well-formed when `Role.__post_init__`
    read it.

    Driven through `run.step` because that is where containment now happens, and the agent is
    asserted never to have run: the refusal costs no dispatch, which is the part of "before anything
    happens" that survived the move.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=EVERYTHING - {Capability.SHELL})
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError) as caught:
        await run.step(builder())

    assert exit_code_for(caught.value) == 5
    assert "shell" in str(caught.value)
    assert stub.ran == []


@pytest.mark.asyncio
async def test_a_missing_mid_run_questions_says_that_on_question_put_it_there(
    tmp_path: Path,
) -> None:
    """§3.2's third check, which is §3.2's second check plus one clause in the message.

    `proposer()` declares `on_question` and no `requires` at all, so `mid_run_questions` is in its
    requirement because `Role.__post_init__` folded it in - and a reader told only that the role
    "requires mid_run_questions" goes looking for a line that is not in their file. `sdk/roles.py`
    asks stage 16 for this sentence by name, and this is the test that keeps it there.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_ASK)
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError) as caught:
        await run.step(proposer())

    said = str(caught.value)
    assert "mid_run_questions" in said
    assert "on_question" in said


@pytest.mark.asyncio
async def test_a_missing_tool_calling_says_that_tools_put_it_there(tmp_path: Path) -> None:
    """The same clause one implication over, owed for the same reason and added at 19.2.

    `reporter()` declares `tools=` and no `requires` at all, so `tool_calling` is in its requirement
    because `Role.__post_init__` folded it in - and "either the role names a model whose backend
    has it, or it stops requiring it" is unactionable advice about a line nobody wrote. What the
    reader needs is which declaration implied it, because that is the line they would edit.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_CALL)
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError) as caught:
        await run.step(reporter())

    said = str(caught.value)
    assert "tool_calling" in said
    assert "tools" in said
    assert "on_question" not in said, "a role with no handler was told about one"


@pytest.mark.asyncio
async def test_a_role_that_typed_the_member_itself_gets_no_extra_clause(tmp_path: Path) -> None:
    """The clause above is about a *handler*, not about the member, which is what keeps it honest.

    `builder()` requires `SHELL` because its author typed `requires={Capability.SHELL}`, and there
    is nothing to explain: a message telling them the framework put it there would be false, and a
    message mentioning `on_question` at all would send them looking for a handler they never wrote.

    Both clauses are asserted absent, because both are conditioned on the *trigger* rather than on
    the member - and a clause conditioned on the member would fire here for a role that declares
    neither a handler nor a tool.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=EVERYTHING - {Capability.SHELL})
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError) as caught:
        await run.step(builder())

    assert "on_question" not in str(caught.value)
    assert "folds it in" not in str(caught.value)


@pytest.mark.asyncio
async def test_a_negotiating_role_is_checked_at_the_step_it_is_handed_to(tmp_path: Path) -> None:
    """**What makes §3.2's third check real, and what UF1.3 costs, in one run.**

    §3.7's handler is a closure over the `Run`, so a workflow that negotiates calls its role's
    factory - `declared(on_question=handler)` - inside its own function, and that value has a
    requirement no scan of a namespace could have seen: the value did not exist until the body ran.
    Preflight admitted a model, and the step is where the difference becomes visible.

    Without this line, the run does not fail. `AgentRunner.run` forbids an adapter that cannot ask
    from blocking, so it tells the agent no answer is available; the workflow's approval gate is
    simply absent, the step reports a result, and nothing anywhere raises. That is the outcome
    `sdk/roles.py` spends four paragraphs refusing to accept.

    **The record is asserted present, and since UF1.3 that assertion carries two meanings.** It is
    still the contrast that makes this the other half rather than a copy of the first - preflight
    passed, so the run exists and only one step of it was refused. It is now also the cost the stage
    accepted written down where it can be checked: a capability mismatch is caught here, with a
    record written and a worktree opened, and no earlier - so this run needs an `agl clear` where
    one refused at second zero does not.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_ASK)

    with pytest.raises(DeniedError) as caught:
        await _start(harness, "replacing", agents=stub)

    said = str(caught.value)
    assert "'implement'" in said, "the refusal does not name the step the role was handed to"
    assert "mid_run_questions" in said
    assert "on_question" in said
    # The same class and the same code as a declared role's would have been, pinned here because
    # this is now the only place containment refuses: a step that answered a workflow author
    # differently from what `sdk/roles.py` promises would be one rule described in two ways.
    assert exit_code_for(caught.value) == 5
    assert entered == ["replacing"]
    assert stub.ran == [], "the role reached the adapter although it could not be served"
    assert not await _no_record(harness), "preflight passed, so this run exists and can be cleared"


async def _direct(harness: container.FakeServices, agents: AgentRunner) -> Run[None]:
    """A `Run` built the way a great many tests build one: directly, never through `api.run`.

    Which is the point of most of the tests around it. A directly-built `Run` has been through no
    preflight at all, so its `Capabilities` is empty - and the step-time check has to be correct
    anyway, which is what `sdk/_engine/preflight.py` means by "containment needs no injection".

    The base is resolved through the bundle's own `History` rather than read off the repository,
    because that is the value `api.run` pins into `RunSpec.base_sha` and hands `Run` (§3.6).
    """
    history = harness.services.history
    return Run(
        params=None,
        services=replace(harness.services, agents=agents),
        scope=SCOPE,
        base=await history.resolve(await history.default_ref()),
    )


@pytest.mark.asyncio
async def test_the_step_time_check_costs_one_capabilities_call_per_model_per_run(
    tmp_path: Path,
) -> None:
    """One question per model for the whole run, children included - which is why `Capabilities` is
    a field on `Run` handed down by `_child` rather than something each namespace builds.

    Four steps over two models in two namespaces, and two calls. §3.2 contracts the answer stable
    for the duration of a run, so a table per namespace would be asking a second time for an answer
    that cannot have changed - and the child is in this test because a per-namespace table passes
    every version of it that only steps in the root.

    **Two models rather than one, since UF1.3.** The claim that two answers to a question contracted
    to have one would let a run admit a role and refuse its twin used to be measured at second zero,
    over the declared tuple; there is no such moment now, so it is measured here, where the calls
    are. Order is asserted with the count for the same reason it is in half one.

    Three calls on one role, since the call carries no name (§3.3): the first two share an address
    and are separated by §3.6's counter, and the third is in a namespace of its own. What is counted
    here is dispatches and questions, neither of which the addresses decide.
    """
    harness = _fakes(tmp_path)
    stub = _Stub()
    run = await _direct(harness, stub)

    await run.step(implementer())
    await run.step(implementer())
    await run.step(reviewer())
    await run.worktree("T-01").step(implementer())

    assert stub.asked_offers == [Claude.OPUS, OpenAI.SOL]
    assert len(stub.ran) == 4


@pytest.mark.asyncio
async def test_check_ready_is_not_repeated_at_the_step(tmp_path: Path) -> None:
    """The other half of what half two is: containment only, and never a second `check_ready`.

    It costs a turn, and it asks about a state of the world preflight has already asked about at
    second zero. A step that asked again would spend one turn per step to re-learn it. Arranged with
    a backend that would refuse if it were asked, so the assertion is that the call did not happen
    rather than that its answer was ignored.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(ready=False)
    run = await _direct(harness, stub)

    await run.step(implementer())

    assert stub.asked_ready == []
    assert len(stub.ran) == 1


@pytest.mark.asyncio
async def test_a_step_is_refused_before_its_checkout_is_provisioned(tmp_path: Path) -> None:
    """Where the check sits inside `run.step`: above the journal lookup and above the lazy open.

    A role that cannot run should cost nothing at all - no worktree cut, no journal built, no agent
    paid for - which is `StepName`'s own argument one line earlier, applied to the other thing that
    can be wrong with a step before anything has happened. It is also the sharpest thing left of
    "before anything happens" now that containment runs at the step: the run's record exists by
    then, and this namespace's checkout still does not.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_ASK)
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError):
        await run.step(implementer(on_question=_answer))

    assert not (tmp_path / "trees" / str(LABEL)).exists()
    assert stub.ran == []


# --- the module's own surface --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_takes_a_runner_and_a_workflow_function_and_nothing_else() -> None:
    """`preflight.check` is callable with one port and one function, which is the signature
    decision.

    It takes an `AgentRunner` and never a `Services`: one port answers both of preflight's
    questions, the bundle would hand it eight, and a second reader would then be one field access
    away in the module whose whole job is to refuse before anything has happened. The second
    argument is the workflow's own `async def` and not a `Workflow` - which this module could not
    import without a cycle, `sdk/workflow.py` importing `Capabilities` from here - and it is the
    smallest thing that names the registry, since a function knows the module its `def` ran in. So
    the composition root passes what it already holds and learns nothing about how a role is found.

    The call below is the whole assertion - it compiles and it runs with no bundle in sight - and
    the second half of it is that what got walked was this module's namespace: two models, in
    binding order, and no capability asked about either.
    """
    stub = _Stub()

    await preflight.check(stub, two_providers.fn)

    assert (stub.asked_ready, stub.asked_offers) == ([Claude.OPUS, OpenAI.SOL], [])
