"""§3.2's preflight: what a run refuses before it starts, and what a step refuses after it has.

The suite over `sdk/_engine/preflight.py`, over the `roles=` 16.1 added to `@workflow`, and over
the one line it put into `sdk/_engine/steps.py`. Four properties carry it.

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

**The two halves are tested against each other, not separately.** The interesting case is a role
that *passes* preflight and must still be refused: `replace(module_level_role, on_question=handler)`
is the natural spelling for §3.7's handler, which is a closure over the `Run`, so the role the
workflow declares and the role it steps with are different values. A suite that only checked the
declared tuple would go green against an engine in which a handler-carrying role reaches a backend
that cannot ask - which raises nothing, logs nothing, and reports a result (`sdk/roles.py`).

**The refusals are pinned on the part of the message the reader acts on**, which for a capability
miss is the member that is missing and, when a handler put it there, the word `on_question`. That
clause is the one thing `roles.py` asks stage 16 for by name: "otherwise the reader goes looking for
a line that is not in their file."
"""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
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
from agl.sdk.roles import Role
from agl.sdk.workflow import Run, workflow

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


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""


async def _answer(question: Question) -> Answer:
    """§3.7's handler, reduced to the one thing this file needs of it: that it exists.

    A role carrying one has `Capability.MID_RUN_QUESTIONS` folded into `requires` at declaration
    time (`sdk/roles.py`), and that is the whole of its part here - nothing below ever asks a
    question, because every refusal this file is about happens before an agent is dispatched.
    """
    return Answer(text="yes")


# --- the roles, at module level, which is where §3.3 keeps them ----------------------------------

IMPLEMENTER: Final = Role(instructions="implement it", model=Claude.OPUS)
"""Requires nothing. The role every workflow below that means to *pass* preflight is written on."""

REVIEWER: Final = Role(instructions="review it", model=OpenAI.SOL)
"""A second provider in one run, which is §3.2's motivating case and the reason dedup is testable:
two models, so a run naming both asks twice, and a third role on the first model asks no more."""

REPAIRER: Final = Role(instructions="repair it", model=Claude.OPUS)
"""A third role on `IMPLEMENTER`'s model. Distinct as a value and identical in what preflight asks
about it, which is exactly what "once per distinct model, not once per role" has to distinguish."""

DEMANDING: Final = Role(
    instructions="run the build until it passes",
    model=Claude.OPUS,
    requires={Capability.SHELL},
)
"""Declares its requirement in as many words - §3.7's own example role does the same."""

ASKING: Final = Role(instructions="propose, then ask", model=Claude.OPUS, on_question=_answer)
"""Declares no `requires` at all, and requires `MID_RUN_QUESTIONS` all the same. That folding is
`Role.__post_init__`'s, and it is why the refusal has to say where the member came from."""


# --- what each workflow did, recorded at module level because the workflows have to be there -----

entered: Final[list[str]] = []
"""Which workflow functions were awaited. A refusal at preflight must leave this empty."""


@workflow(name="two_providers", version="1.1", params=NoParams, roles=[IMPLEMENTER, REVIEWER])
async def two_providers(run: Run[NoParams]) -> None:
    """§3.2's own case: Claude implements, OpenAI reviews, one run."""
    entered.append("two_providers")


@workflow(
    name="three_roles",
    version="1.1",
    params=NoParams,
    roles=[IMPLEMENTER, REVIEWER, REPAIRER],
)
async def three_roles(run: Run[NoParams]) -> None:
    """Three roles over two models - the shape `fix` has, and the shape dedup is measured on."""
    entered.append("three_roles")


@workflow(name="unstaffed", version="1.1", params=NoParams)
async def unstaffed(run: Run[NoParams]) -> None:
    """Declares no roles at all: `workflows/noop/`'s shape, and the reason `roles` defaults."""
    entered.append("unstaffed")


@workflow(name="demanding", version="1.1", params=NoParams, roles=[DEMANDING])
async def demanding(run: Run[NoParams]) -> None:
    """Never reached on a backend without `SHELL`, which is the whole assertion."""
    entered.append("demanding")


@workflow(name="asking", version="1.1", params=NoParams, roles=[ASKING])
async def asking(run: Run[NoParams]) -> None:
    """Declares a handler-carrying role at module level, so preflight itself sees the fold."""
    entered.append("asking")


@workflow(name="replacing", version="1.1", params=NoParams, roles=[IMPLEMENTER])
async def replacing(run: Run[NoParams]) -> None:
    """Declares a role that requires nothing and steps with one that requires asking.

    **This is the workflow the step-time check exists for**, and it is written the way §3.7 says a
    negotiating workflow is written: the handler is a closure over this `Run`, so the role carrying
    it cannot be the module-level declaration and is built here with `replace`. Preflight was shown
    `IMPLEMENTER`; what runs is a role needing `MID_RUN_QUESTIONS`.
    """
    entered.append("replacing")

    async def approve(question: Question) -> Answer:
        """A closure over `run` in the only way that matters here: it is defined inside it."""
        return Answer(text=f"{run.scope.label}: yes")

    await run.step("review", replace(IMPLEMENTER, on_question=approve))


def _point(name: str, attribute: str) -> EntryPoint:
    """§3.3's `probe = "agl.workflows.probe:probe"`, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)


POINTS: Final = tuple(
    _point(name, name)
    for name in ("two_providers", "three_roles", "unstaffed", "demanding", "asking", "replacing")
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
    exception reaching `api.run`'s caller is the adapter's own object and not a copy preflight made
    on the way past.
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


# --- half one: availability, over the roles the workflow declares --------------------------------


@pytest.mark.asyncio
async def test_a_role_whose_harness_is_missing_fails_at_second_zero(tmp_path: Path) -> None:
    """**The stage's acceptance criterion.** A role names a provider whose harness is missing, out
    of date or logged out, and the run dies with `UpstreamUnavailable` before anything durable
    exists.

    Three assertions and each is a different failure. The exception is compared by **identity**,
    because a preflight that caught the adapter's refusal and raised its own of the same class would
    satisfy every `isinstance` check while dropping the one sentence a person can act on - the
    adapter is the only thing that knows which of installed, current and authenticated failed. The
    record is asserted absent, because a run refused here must not need an `agl clear` before it can
    be retried. And the provider is a tripwire rather than a directory listing, because a provider
    that ran and failed leaves no directory either.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(ready=False)

    with pytest.raises(UpstreamUnavailable) as caught:
        await _start(harness, "two_providers", agents=stub, opens=False)

    assert caught.value is stub.refusal, "preflight rebuilt the adapter's refusal on the way past"
    assert exit_code_for(caught.value) == 6
    assert await _no_record(harness), "a run refused at preflight left a record to be cleared"
    assert entered == [], "the workflow ran although its backend was never ready"


@pytest.mark.asyncio
async def test_check_ready_is_asked_once_per_model_and_not_once_per_role(tmp_path: Path) -> None:
    """§3.2's first check, over *distinct models*. Three roles, two models, two questions.

    The dedup is not tidiness. `check_ready` costs a real turn on one of the two harnesses in view,
    so a workflow with five roles on one model would spend five turns before a line of work had been
    done. Two roles on one model are one question about the state of the world.

    Order is asserted along with the count: a refusal should arrive in the order the author wrote
    their roles, which is what `preflight._models` uses `dict.fromkeys` rather than a set for.
    """
    harness = _fakes(tmp_path)
    stub = _Stub()

    await _start(harness, "three_roles", agents=stub)

    assert stub.asked_ready == [Claude.OPUS, OpenAI.SOL]


@pytest.mark.asyncio
async def test_a_workflow_that_declares_no_roles_asks_no_backend_anything(tmp_path: Path) -> None:
    """`roles=()` is the default, and this is what it buys: `workflows/noop/` keeps working.

    Not merely "it does not fail". A preflight that asked about some default model, or about every
    provider the bundle was assembled with, would make `agl run noop` depend on a harness that
    workflow never names - and `noop` exists precisely to prove the wiring with nothing else in the
    way.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(ready=False)

    await _start(harness, "unstaffed", agents=stub)

    assert (stub.asked_ready, stub.asked_offers) == ([], [])
    assert entered == ["unstaffed"]


# --- half one: capability match ------------------------------------------------------------------


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
    test above. 5 and 6 are the two ways preflight can end a run and they send a reader to two
    different places: the harness is there and cannot do this, so the workflow changes; or the
    harness is not there, so a login does. An `InputError` would be a third answer - input AGL could
    not make sense of - and every term of this role was well-formed when `Role.__post_init__` read
    it.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(offers=EVERYTHING - {Capability.SHELL})

    with pytest.raises(DeniedError) as caught:
        await _start(harness, "demanding", agents=stub, opens=False)

    assert exit_code_for(caught.value) == 5
    assert "shell" in str(caught.value)
    assert await _no_record(harness)
    assert entered == []


@pytest.mark.asyncio
async def test_capabilities_is_asked_once_per_model_within_one_pass(tmp_path: Path) -> None:
    """§3.2 makes `capabilities()` stable for the duration of a run, so one answer serves every role
    naming that model. Three roles, two models, two questions - `check_ready`'s rule, one loop
    down, for a different reason: not cost, but that two answers to a question contracted to have
    one would be a preflight that could admit a role and refuse its twin."""
    harness = _fakes(tmp_path)
    stub = _Stub()

    await _start(harness, "three_roles", agents=stub)

    assert stub.asked_offers == [Claude.OPUS, OpenAI.SOL]


@pytest.mark.asyncio
async def test_a_missing_mid_run_questions_says_that_on_question_put_it_there(
    tmp_path: Path,
) -> None:
    """§3.2's third check, which is §3.2's second check plus one clause in the message.

    `ASKING` declares `on_question` and no `requires` at all, so `mid_run_questions` is in its
    requirement because `Role.__post_init__` folded it in - and a reader told only that the role
    "requires mid_run_questions" goes looking for a line that is not in their file. `sdk/roles.py`
    asks stage 16 for this sentence by name, and this is the test that keeps it there.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_ASK)

    with pytest.raises(DeniedError) as caught:
        await _start(harness, "asking", agents=stub, opens=False)

    said = str(caught.value)
    assert "mid_run_questions" in said
    assert "on_question" in said
    assert await _no_record(harness)


@pytest.mark.asyncio
async def test_a_role_that_typed_the_member_itself_gets_no_extra_clause(tmp_path: Path) -> None:
    """The clause above is about a *handler*, not about the member, which is what keeps it honest.

    `DEMANDING` requires `SHELL` because its author typed `requires={Capability.SHELL}`, and there
    is nothing to explain: a message telling them the framework put it there would be false, and a
    message mentioning `on_question` at all would send them looking for a handler they never wrote.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=EVERYTHING - {Capability.SHELL})

    with pytest.raises(DeniedError) as caught:
        await _start(harness, "demanding", agents=stub, opens=False)

    assert "on_question" not in str(caught.value)


@pytest.mark.asyncio
async def test_availability_is_asked_before_capability(tmp_path: Path) -> None:
    """The one place `api.py`'s cheapest-refusal-first rule is deliberately not followed.

    `capabilities()` still answers on a machine where the harness is missing - both adapters report
    a frozen constant - so its answer there is hypothetical. Refusing on it first would tell an
    operator with no harness installed that their *workflow* is wrong. Arranged so that both checks
    would fail and only one can be reported: the backend is not ready **and** cannot do what the
    role asks.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=frozenset(), ready=False)

    with pytest.raises(UpstreamUnavailable):
        await _start(harness, "demanding", agents=stub, opens=False)

    assert stub.asked_offers == [], "a capability was asked about a backend that is not there"


# --- half two: the role a step is actually handed ------------------------------------------------


@pytest.mark.asyncio
async def test_a_role_built_with_replace_is_checked_at_the_step_it_is_handed_to(
    tmp_path: Path,
) -> None:
    """**What makes §3.2's third check real.** The declared role passes preflight; the role that
    runs does not.

    §3.7's handler is a closure over the `Run`, so a workflow that negotiates writes
    `replace(declared, on_question=handler)` inside its own function - and that value has a
    requirement the declaration never had. Preflight admitted `IMPLEMENTER`, which requires nothing,
    and the step is where the difference becomes visible.

    Without this line, the run does not fail. `AgentRunner.run` forbids an adapter that cannot ask
    from blocking, so it tells the agent no answer is available; the workflow's approval gate is
    simply absent, the step reports a result, and nothing anywhere raises. That is the outcome
    `sdk/roles.py` spends four paragraphs refusing to accept.

    The record is asserted **present**, which is the contrast that makes this the other half rather
    than a second copy of the first: preflight passed, the run exists, and what was refused is one
    step of it.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_ASK)

    with pytest.raises(DeniedError) as caught:
        await _start(harness, "replacing", agents=stub)

    said = str(caught.value)
    assert "'review'" in said, "the refusal does not name the step the role was handed to"
    assert "mid_run_questions" in said
    assert "on_question" in said
    # The same class and the same code as half one's, pinned on both halves rather than on the one
    # that happens to be reached first: they are one refusal made at two moments, and a step that
    # answered a workflow author differently from preflight would be two rules under one name.
    assert exit_code_for(caught.value) == 5
    assert entered == ["replacing"]
    assert stub.ran == [], "the role reached the adapter although it could not be served"
    assert not await _no_record(harness), "preflight passed, so this run exists and can be cleared"


async def _direct(harness: container.FakeServices, agents: AgentRunner) -> Run[None]:
    """A `Run` built the way a great many tests build one: directly, never through `api.run`.

    Which is the point of the three tests below. A directly-built `Run` has been through no
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

    Three steps on one model in two namespaces, and one call. §3.2 contracts the answer stable for
    the duration of a run, so a table per namespace would be asking a second time for an answer that
    cannot have changed - and the child is in this test because a per-namespace table passes every
    version of it that only steps in the root.
    """
    harness = _fakes(tmp_path)
    stub = _Stub()
    run = await _direct(harness, stub)

    await run.step("one", IMPLEMENTER)
    await run.step("two", IMPLEMENTER)
    await run.worktree("T-01").step("three", IMPLEMENTER)

    assert stub.asked_offers == [Claude.OPUS]
    assert len(stub.ran) == 3


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

    await run.step("one", IMPLEMENTER)

    assert stub.asked_ready == []
    assert len(stub.ran) == 1


@pytest.mark.asyncio
async def test_a_step_is_refused_before_its_checkout_is_provisioned(tmp_path: Path) -> None:
    """Where the check sits inside `run.step`: above the journal lookup and above the lazy open.

    A role that cannot run should cost nothing at all - no worktree cut, no journal built, no agent
    paid for - which is `StepName`'s own argument one line earlier, applied to the other thing that
    can be wrong with a step before anything has happened.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_ASK)
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError):
        await run.step("review", replace(IMPLEMENTER, on_question=_answer))

    assert not (tmp_path / "trees" / str(LABEL)).exists()
    assert stub.ran == []


# --- the module's own surface --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_takes_a_runner_and_roles_and_nothing_else(tmp_path: Path) -> None:
    """`preflight.check` is callable with one port and a sequence, which is the signature decision.

    It takes an `AgentRunner` and never a `Services`: one port answers both of its questions, the
    bundle would hand it eight, and a second reader would then be one field access away in the
    module whose whole job is to refuse before anything has happened. The call below is the whole
    assertion - it compiles and it runs with no bundle in sight.
    """
    stub = _Stub()
    roles: Sequence[Role[object]] = (IMPLEMENTER, REVIEWER, REPAIRER)

    await preflight.check(stub, roles)

    assert (stub.asked_ready, stub.asked_offers) == (
        [Claude.OPUS, OpenAI.SOL],
        [Claude.OPUS, OpenAI.SOL],
    )
