"""Preflight: what a run refuses before it starts, and what a step refuses after it has.

The suite over `sdk/_engine/preflight.py`, over the registry that stands in place of `@workflow`'s
`roles=`, and over the one line it put into `sdk/_engine/steps.py`. Five properties carry it.

**Nothing here constructs a real adapter, and that is a rule rather than a convenience.**
`check_ready` on the Claude harness costs a real turn and on the Codex harness spawns a process, so
every runner below is either `container.fakes()`'s or `_Stub`, declared in this module. `scripts
/check`'s paid-endpoint gate would catch a lapse; not writing one is cheaper than being caught.

**"At second zero" is asserted mechanically and not by reading the source.** The acceptance
criterion is that a role naming a harness that is missing, out of date or logged out fails with
`UpstreamUnavailable` - and what makes that *second zero* rather than merely early is that nothing
durable exists afterwards. So the refused run is asked two questions the ordering decides: is there
a record under `AGL_HOME`, and was `WorkspaceProvider.open` reached at all. The second is asked with
a provider whose every member raises `AssertionError`, because a directory that is not there is also
what a provider that failed would leave, and only a tripwire tells the two apart. There are two
refusals of that shape now: the harness one, and a repository that can name no committer, which is
`History.check_committer_identity` and is measured with the same four assertions - a run whose
commits git will not make loses a step's turn inside `Journal._ending`, where there is no ledger
entry for a resume to hit.

**The order the questions are asked in is chosen on what each one costs, and is asserted.** Free
and local first - the repository - then the backends, cheapest probe leading: `codex login status`
is a process, and the Claude harness's `check_ready` is a paid turn. `sorted` is stable, so the
property that used to carry the ordering on its own, binding order in the workflow's module
namespace, survives as the tie-break between two models whose probes cost the same. The table those
costs live in is asserted total over `Provider` by a test of its own, since an unranked provider is
the one that would land on the wrong side of the paid probe with nothing to say so.

**The registry is a module namespace, so several claims are claims about a whole module.** A
workflow's roles are the `@role(model=…)` factories bound in the module its `def` was executed in,
and also the ones bound in any module bound there. This file is *one* namespace, and it holds six
factories bound directly over two models - the right shape for dedup and ordering, and the wrong
shape for every claim about what a namespace does not hold or about how a factory reaches it.
`tests/instruments/preflight/` is where those live, one module each: no factory at all, a factory
written below the workflow function, a factory reached only as `roles.implementer()` through a
bound module, a `Role` already built and imported by name with no factory beside it, and two
factories naming one model at two efforts with no second model beside them. Another -
a factory imported and never used - went with the shipped workflow whose role it imported; the
section that used to read it says what is unmeasured in its absence.

**The last of those four is the one claim here that pins a gap rather than closing one.** A built
`Role` in a namespace demands nothing of preflight, and that is a verdict rather than an omission:
the scan is over declarations, and reading values instead has no stopping point. Its test carries
the whole argument, including what the shape costs and which half of it could not be probed at all.

**The two halves are tested against each other, not separately.** The interesting case is a role
that *passes* preflight and must still be refused: `implementer(ask=tool)` is the spelling for a
role a workflow hands its own tool to, and that tool's handler is a closure over the `Run`, so the
role a module declares and the role a workflow steps with are different values. A suite that only
checked what preflight saw would go green against an engine in which a tool-carrying role reaches a
backend that cannot call one - where the reporting tool never reaches the model, the agent cannot
fire it, and the step ends with `RoleIncompleteError` rather than with the refusal it was owed.

**This half used to be measured on `MID_RUN_QUESTIONS` and it is measured on `TOOL_CALLING` now.**
`fix` handed its implementer an `on_question=` handler, `Role.__post_init__` folded the capability
in behind it, and that was the value no namespace scan could have seen. Both went: a question is an
ordinary tool the workflow supplies, so the same workflow hands the same role a `Tool` at the same
line, and `Role.__post_init__` folds `TOOL_CALLING` in from `tools` where it used to fold
`MID_RUN_QUESTIONS` in from `on_question`. The check did not vanish with the member - it moved one
fold over, and this suite is where that is measured rather than asserted.

**The refusals are pinned on the part of the message the reader acts on**, which for a capability
miss is the member that is missing and, when a declaration put it there rather than the author, the
word that declaration is spelled with - `tools` for `TOOL_CALLING`. That clause is what `roles.py`
asks for by name: "otherwise the reader goes looking for a line that is not in their file." It is
conditioned on the trigger and not on the member, and there is a test for its negative: a role that
typed its own requirement is told nothing about where it came from. For an unavailable provider it
is now also *which factory in which module* asked for that model, because the namespace
over-approximates and a person refused for a provider they never meant to use has otherwise no
thread to pull.

## What moved when the registry replaced `roles=`, and why it is here rather than deleted

**Capability containment left second zero with `roles=`.** It compares `role.requires` against what
a backend reports, `requires` is on the `Role` a factory *returns*, and preflight may not call a
factory - it has no arguments for a parameter list the author chose. So four suites that measured
containment through `api.run` now measure it through `run.step`:

  * a role requiring what its backend lacks, refused with the member named;
  * a missing `TOOL_CALLING` saying that `tools` put it there;
  * a role that typed its own requirement being told nothing about where it came from.

There were four, and the fourth was a missing `MID_RUN_QUESTIONS` saying that `on_question` put it
there. It went with the member: `_unmet` has one such clause now, not two.

Every one of the remaining claims is unchanged - the class, the exit code and the sentence are the
same. All that moved is the moment, and the moment is what they no longer assert: they used to
assert that no record and no workspace existed afterwards, and that is exactly what the move gave
up. The cost is not merely recorded in prose here - `test_a_role_built_inside_a_workflow_is_checked
_at_the_step_it_is_handed_to` asserts the record is **present** when containment refuses, which is
the same fact read from the other side.

What did not move is the provider half. A logged-out harness is still refused before anything
durable exists, and the acceptance criterion is still met in as many words.
"""

from collections.abc import Callable
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
    ClaudeEffort,
    Installation,
    ModelEfforts,
    ModelId,
    OpenAI,
    OpenAIEffort,
    Provider,
    StopReason,
    Tool,
    ToolResult,
    VersionRange,
)
from agl.ports.errors import DeniedError, UpstreamUnavailable, exit_code_for
from agl.ports.history import FileChange, History
from agl.ports.home_layout import AglHome, RunScope, workspace_dir
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.sync import Syncer, SyncOutcome
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace, WorkspaceProvider
from agl.sdk._engine import preflight
from agl.sdk._workflow import Run, workflow
from agl.sdk.roles import Role, role
from agl.sdk.tools import reporting_tool, tool
from instruments.preflight import NoParams, entered
from instruments.preflight.efforts import efforts as two_levels
from instruments.preflight.late import late
from instruments.preflight.providers import broad

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# What the backends in this file can do when nothing says otherwise: everything the port has, which
# is what both real adapters report and what `container.fakes()` reports. Written out as the enum
# so that a fifth member arriving in `ports/agent.py` widens this with the port rather than leaving
# a hand-copied list quietly narrower than the thing it stands in for.
EVERYTHING: Final = frozenset(Capability)

# Everything except the member the folded implication is about, and the interesting backend in this
# file. A backend that cannot call a tool is where a role built inside a workflow gets caught: the
# tool never reaches the model, so the agent cannot fire it, and `Run.step` would otherwise end the
# step with `RoleIncompleteError` - a failure that names a prompt where the fact is a backend.
#
# There was a second one, `CANNOT_ASK`, for a backend that reported no `MID_RUN_QUESTIONS`. Both the
# member and the constant went when a question became an ordinary tool: the backend that cannot
# serve `fix`'s implementer is the one that cannot call a tool, which is this one.
CANNOT_CALL: Final = EVERYTHING - {Capability.TOOL_CALLING}

# What a backend reports about itself where the version is not what a test is about: a tool sitting
# inside the one release it was tested against, which is `Standing.WITHIN` and so is silent. It is
# the default every `_Stub` carries, so a test asserting on stderr is asserting about its own
# arrangement rather than about whatever an unconfigured stand-in happened to say.
CURRENT: Final = Installation(
    tool="a stand-in harness",
    version="1.0.0",
    tested=VersionRange("1.0.0", "1.0.0"),
    efforts={},
)

@dataclass(frozen=True)
class _Found:
    """The smallest reporting payload there is: one field, so a schema can be derived from it."""

    summary: str

@dataclass(frozen=True)
class _Asked:
    """The payload an asking tool would carry. One field, because nothing here is ever asked."""

    question: str

def _asking() -> Tool:
    """An asking tool, reduced to the one thing this file needs of it: that it exists.

    A role carrying any tool has `Capability.TOOL_CALLING` folded into `requires` at declaration
    time (`sdk/roles.py`), and that is the whole of its part here - nothing below ever calls this,
    because every refusal this file is about happens before an agent is dispatched.
    """

    async def answered(asked: _Asked) -> ToolResult:
        return ToolResult(text="yes")

    return tool("ask_the_operator", "ask the person running this task", _Asked, answered)

# --- the roles, as the `@role(model=…)` factories a role is declared by --------------------------
#
# Six of them, and the fact that they are bound *in this module* is the whole of what
# makes them the roles of every workflow declared below: there is no list on a decorator, and the
# namespace is the registry. So this block is also the declaration the availability tests are about
# - two distinct models over six factories, which is what "once per model, not once per role" needs
# to be able to tell apart.

@role(model=Claude.OPUS)
def implementer(*, ask: Tool | None = None) -> Role:
    """Requires nothing, and is the role every workflow below that means to *pass* preflight is
    written on.

    **The `ask` parameter is the whole of the step-time check's case**, and it is `fix/roles.py`'s
    shape: `implementer()` requires nothing and is what a reader of a declaration sees;
    `implementer(ask=…)` requires `TOOL_CALLING`, because `Role.__post_init__` folds it in from
    `tools`, and is what reaches `run.step`. Nothing before the workflow's body has run can see the
    second, which is why containment is a step-time check and always was."""
    return Role(
        name="implement", instructions="implement it", tools=() if ask is None else (ask,)
    )

@role(model=OpenAI.SOL)
def reviewer() -> Role:
    """A second provider in one run, which is the port's motivating case and the reason dedup is
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
    """Declares its requirement in as many words - a negotiating role does the same."""
    return Role(
        name="build",
        instructions="run the build until it passes",
        requires={Capability.SHELL},
    )

@role(model=Claude.OPUS)
def reporter() -> Role[_Found]:
    """Declares no `requires` at all and needs `TOOL_CALLING` all the same, because it is folded in
    behind `tools=`. That folding is `Role.__post_init__`'s, and it is why the refusal has to say
    where the member came from. A reporting step, in the smallest form that has a payload at all."""
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

@workflow
async def two_providers(run: Run[NoParams]) -> None:
    """The multi-vendor case: this module names Claude and OpenAI, so one run asks both.

    It takes no step, deliberately. What half one measures is what a run asks *before* it does
    anything, and a workflow with a body would put a second reason in every assertion below.
    """
    entered.append("two_providers")

@workflow
async def replacing(run: Run[NoParams]) -> None:
    """Steps with a role that requires tool calling, in a module whose factories require nothing.

    **This is the workflow containment exists for**, and it is written the way a negotiating
    workflow is written: the tool's handler is a closure over this `Run`, so the role carrying it is
    built here, by calling the factory with the one argument it exposes. Preflight saw a model; what
    runs is `implementer(ask=…)`, which needs `TOOL_CALLING`, and no scan of a namespace could have
    known that - the value did not exist until this line ran.
    """
    entered.append("replacing")

    async def answered(asked: _Asked) -> ToolResult:
        """A closure over `run` in the only way that matters here: it is defined inside it."""
        return ToolResult(text=f"{run.scope.label}: yes")

    await run.step(
        implementer(
            ask=tool("ask_the_operator", "ask the person running this", _Asked, answered)
        )
    )

def _point(name: str, target: str) -> EntryPoint:
    """The `probe = "agl.workflows.probe:probe"` entry point, pointed here or at an instrument."""
    return EntryPoint(name=name, value=target, group=registry.GROUP)

POINTS: Final = (
    _point("two_providers", f"{__name__}:two_providers"),
    _point("replacing", f"{__name__}:replacing"),
    # The ones whose claim is about a namespace this file cannot have, each in a module of its
    # own - `tests/instruments/preflight/` says why one file could not hold them all.
    _point("unstaffed", "instruments.preflight.unstaffed:unstaffed"),
    _point("late", "instruments.preflight.late:late"),
    _point("qualified", "instruments.preflight.qualified:qualified"),
    _point("prebuilt", "instruments.preflight.prebuilt:prebuilt"),
    _point("efforts", "instruments.preflight.efforts:efforts"),
    _point("broad", "instruments.preflight.providers:broad"),
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
        self,
        *,
        offers: AbstractSet[Capability] = EVERYTHING,
        ready: bool = True,
        installed: Installation = CURRENT,
    ) -> None:
        self.offers: Final = frozenset(offers)
        self.ready: Final = ready
        self.installed: Final = installed
        self.refusal: Final = UpstreamUnavailable(
            "the harness is not on PATH: install it, or log in and try again"
        )
        self.asked_ready: Final[list[ModelId]] = []
        self.asked_offers: Final[list[ModelId]] = []
        self.asked_installation: Final[list[ModelId]] = []
        self.ran: Final[list[AgentTask]] = []

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        self.asked_offers.append(model)
        return self.offers

    async def check_ready(self, model: ModelId) -> None:
        self.asked_ready.append(model)
        if not self.ready:
            raise self.refusal

    async def installation(self, model: ModelId) -> Installation:
        self.asked_installation.append(model)
        return self.installed

    async def run(
        self,
        task: AgentTask,
        *,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        self.ran.append(task)
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

class _Repository(History):
    """The third port preflight reaches, answering the two questions `api.run` puts to it and no
    more.

    `exists` is asked about the deliverable branch above preflight and answers `False`, so a run
    gets as far as the thing under test. `check_committer_identity` is that thing, and
    `attributable=False` is the arrangement `container.fakes()` cannot build for the reason it
    cannot build an unready backend: the fake repository attributes a state to nobody, so there is
    no identity there to be missing.

    Every other member is a tripwire, on `_Untouched`'s argument. `api.run` resolves the base two
    lines under preflight, so a `default_ref` that answered would let a test claiming the run died
    at second zero pass over one that got further - and `AssertionError` is not an `AglError`, so
    it cannot be mistaken for the refusal under test on the way out.

    `refusal` is built once and raised by identity, so a test can assert that the sentence reaching
    the caller is the adapter's own and that its exception is the cause preflight chained. The text
    is `adapters/git/history.py`'s shape: `GitRunner` prefixes what git said, and what git says
    here is the block naming the two `git config --global` lines that fix it.
    """

    def __init__(self, *, attributable: bool = True) -> None:
        self.attributable: Final = attributable
        self.refusal: Final = UpstreamUnavailable(
            "git refused `git var GIT_COMMITTER_IDENT`: Committer identity unknown - run `git "
            "config --global user.email` and `git config --global user.name`"
        )

    async def default_ref(self) -> str:
        raise AssertionError("preflight refused this run and its base ref was asked for anyway")

    async def resolve(self, ref: str) -> str:
        raise AssertionError("preflight refused this run and its base was pinned anyway")

    async def exists(self, ref: str) -> bool:
        return False

    async def contains(self, ancestor: str, descendant: str) -> bool:
        raise AssertionError("nothing in `api.run` asks about ancestry")

    async def changed_files(self, base: str, head: str) -> tuple[FileChange, ...]:
        raise AssertionError("nothing in `api.run` asks which files differ")

    async def diff(self, base: str, head: str) -> str:
        raise AssertionError("nothing in `api.run` reads a patch")

    async def message(self, commit: str) -> str:
        raise AssertionError("nothing in `api.run` reads what a commit was called")

    async def check_committer_identity(self) -> None:
        if not self.attributable:
            raise self.refusal

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

    async def residue(self, label: RunLabel) -> tuple[Namespace, ...]:
        raise AssertionError("a run preflight refused asks nothing about what a run left standing")

    async def check_removable(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("a run preflight refused asks nothing about taking a workspace back")

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("a run preflight refused takes no workspace back")

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("a run preflight refused deletes no line of work")

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        raise AssertionError(
            "preflight refused this run and its claim on the trees root was taken anyway. The run "
            "lock sits below preflight for the reason the record does: a refusal that costs real "
            "turns is the last thing that can happen while the run has left nothing behind"
        )

class _Installer(Syncer):
    """A syncer that records having been asked, and starts nothing: `api.run` syncs above preflight.

    A `FakeSyncer` would answer just as harmlessly and could not be asked afterwards whether it was
    reached, which is the whole of what this is for.
    """

    def __init__(self) -> None:
        self.asked: list[Path] = []

    async def sync(self, workspace: Path) -> SyncOutcome:
        self.asked.append(workspace)
        return SyncOutcome(synced=True, status=0, output="")

def _fakes(tmp_path: Path) -> container.FakeServices:
    """End-to-end on fakes alone: one repository seeded with a file, one store, one frozen clock."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})

async def _start(
    harness: container.FakeServices,
    name: str,
    *,
    agents: AgentRunner,
    history: History | None = None,
    opens: bool = True,
    syncer: Syncer | None = None,
    home: AglHome | None = None,
) -> None:
    """One `api.run` with this module's entry points and one substituted port - or three.

    `opens=False` swaps the workspace provider for the tripwire, which every test about a run that
    must not reach the repository passes. `history=` swaps the repository preflight now asks first,
    which only the tests about that question need. `syncer=` and `home=` are the pair `api.run`
    installs against, left unpassed everywhere the install is not the subject: without both, the
    run reaches no installer at all.
    """
    services = replace(harness.services, agents=agents)
    if history is not None:
        services = replace(services, history=history)
    if not opens:
        services = replace(services, workspaces=_Untouched())
    await api.run(services, PROJECT, name, LABEL, (), syncer=syncer, home=home, points=POINTS)

async def _no_record(harness: container.FakeServices) -> bool:
    """Whether this run left nothing under `AGL_HOME` - half of what "second zero" means."""
    return await harness.services.store.read_record(SCOPE) is None

# --- half one: availability, over the models the workflow's module names -------------------------

@pytest.mark.asyncio
async def test_a_role_whose_harness_is_missing_fails_at_second_zero(tmp_path: Path) -> None:
    """**The acceptance criterion.** A role names a provider whose harness is missing, out of date
    or logged out, and the run dies with `UpstreamUnavailable` before anything durable exists. The
    registry changed where the model comes from and changed nothing about this.

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
async def test_a_repository_that_can_name_no_committer_fails_at_second_zero(
    tmp_path: Path,
) -> None:
    """**The acceptance criterion for the one failure a resume cannot repair.**

    `Journal._ending` commits the agent's work at the end of every step declaring `commit=`, and
    `adapters/git/workspace.py`'s `commit_all` invents no identity to do it with. Where git can
    derive none it refuses *there* - inside the step's ending, after the agent has finished and
    before the entry is written - so a run record exists, no step entry does, the edits sit
    uncommitted, and a resume re-dispatches the step it had already paid for. There is nothing on
    the ledger for it to hit.

    So the question is asked at second zero and it is asked **first**, before any backend: it is
    free, it is local, and it is the refusal that costs the most to arrive late. `stub.asked_ready`
    is what pins the ordering - not one probe was spent on a run that could never have committed
    anything.

    The same four questions as the harness criterion above, because "at second zero" means the same
    thing here: git's own sentence reaching the caller whole, since it names the two `git config
    --global` lines that fix it and preflight only adds why AGL asked; its exception as the
    `__cause__`; exit 6, which is the class for a state of the world that clears when the operator
    changes theirs; no record under `AGL_HOME` for somebody to `agl clear` before retrying; and the
    `_Untouched` tripwire rather than a directory listing, because a provider that ran and failed
    leaves no directory either.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub()
    repository = _Repository(attributable=False)

    with pytest.raises(UpstreamUnavailable) as caught:
        await _start(
            harness, "two_providers", agents=stub, history=repository, opens=False
        )

    assert str(repository.refusal) in str(caught.value), "git's own reason was not passed on"
    assert caught.value.__cause__ is repository.refusal, "the repository's refusal is not the cause"
    assert exit_code_for(caught.value) == 6
    assert stub.asked_ready == [], (
        "a backend was probed before the free local question that decides whether this run could "
        "ever have committed anything, and one of those probes costs a turn"
    )
    assert await _no_record(harness), "a run refused at preflight left a record to be cleared"
    assert entered == [], "the workflow ran although nothing it did could have been committed"
    assert stub.asked_installation == [], (
        "a backend was asked what it is running on before the free local question, and reading "
        "that costs a subprocess on both real adapters - spent here on a run that never starts"
    )

@pytest.mark.asyncio
async def test_a_run_installs_what_the_workspace_declares_before_preflight_is_asked_anything(
    tmp_path: Path,
) -> None:
    """The install `api.run` folds in sits *above* preflight, and this is where that is pinned.

    It has to. `check` below reads its role factories out of the module the workflow's `def` ran
    in, so preflight cannot be asked until `config/registry.py`'s `load` has imported that module -
    and a workflow whose dependency is not installed yet fails that import. An install underneath
    preflight would never run on the very machine that needed it, and the next run would fail the
    same way: `tests/test_api.py` is where that heals, over a workflow importing what only a sync
    puts there.

    What the order does not weaken is offline, and nothing here compensates for it with a probe of
    AGL's own. A machine with no network and no environment is refused by the install below; one
    with an environment already gets a warning and reaches `check`, whose Claude probe is a real
    round trip and fails loudly there.

    The refusal used here is preflight's free local one, so the claim costs nothing to make: a run
    whose commits git will not make is refused after the workspace was installed and before any
    backend was asked.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    home = AglHome(tmp_path / "home")
    installer = _Installer()
    probe = _Stub()

    with pytest.raises(UpstreamUnavailable):
        await _start(
            harness,
            "two_providers",
            agents=probe,
            history=_Repository(attributable=False),
            opens=False,
            syncer=installer,
            home=home,
        )

    assert installer.asked == [workspace_dir(home)], (
        "the run reached preflight without installing what the workspace declares, so a workflow "
        "whose dependency is missing would have failed at its own import line one step earlier"
    )
    assert probe.asked_ready == [], (
        "a backend was probed although preflight refused on the free local question, which is the "
        "ordering this file's own cost argument rests on"
    )

@pytest.mark.asyncio
async def test_check_ready_is_asked_once_per_model_and_not_once_per_role(tmp_path: Path) -> None:
    """The first check, over *distinct models*. Six factories in this module, two models, two
    questions.

    The dedup is not tidiness. `check_ready` costs a real turn on one of the two harnesses in view,
    so a module with five roles on one model would spend five turns before a line of work had been
    done. Two roles on one model are one question about the state of the world.

    Order is asserted along with the count, and what decides it is what a probe costs: the free one
    goes first, which is the test below this one. Binding order in the module's namespace - a
    `dict`, and therefore ordered - is what survives as the tie-break between two models whose
    probes cost the same, so this module, which declares `Claude.OPUS` first, is nevertheless asked
    about `OpenAI.SOL` first.
    """
    harness = _fakes(tmp_path)
    stub = _Stub()

    await _start(harness, "two_providers", agents=stub)

    assert stub.asked_ready == [OpenAI.SOL, Claude.OPUS]

@pytest.mark.asyncio
async def test_the_free_probe_is_asked_first_so_a_refusal_never_costs_a_turn(
    tmp_path: Path,
) -> None:
    """**The order the probes run in is chosen, and it is chosen on what one costs.**

    `adapters/openai/runner.py`'s `check_ready` spawns `codex login status`, which is a local
    process and free. `adapters/claude_code/runner.py`'s is a real one-turn `query(...)` against
    the model it is asking about, and is on somebody's bill. Logged into one harness and out of the
    other - the ordinary state of a machine the day a second vendor is added - a run that probed
    the paid one first would buy a turn and then be refused for the other, which is the whole of
    what this ordering is for.

    **Two arrangements, because one of them alone proves nothing.** With both backends refusing,
    only the free question is asked at all: the turn is never bought, and that is the money claim.
    With both passing, both are asked and the free one is still first, which is what stops the
    assertion above passing against a preflight that had merely stopped after its first refusal.

    This module declares `Claude.OPUS` first and `OpenAI.SOL` second, so namespace order and cost
    order disagree here and the answer says which one won. The tie-break is the test above: `sorted`
    is stable, so two models of one cost keep the order their author wrote them in.
    """
    refusing = _Stub(ready=False)

    with pytest.raises(UpstreamUnavailable):
        await _start(_fakes(tmp_path), "two_providers", agents=refusing, opens=False)

    assert refusing.asked_ready == [OpenAI.SOL], (
        "a run that was going to be refused anyway asked the harness that charges for the question "
        "before the one that does not, and that turn is on somebody's bill"
    )

    passing = _Stub()
    await _start(_fakes(tmp_path / "second"), "two_providers", agents=passing)

    assert passing.asked_ready == [OpenAI.SOL, Claude.OPUS], (
        "with both backends ready the paid probe went first, so the assertion above was about a "
        "preflight that stops at its first refusal rather than about an order"
    )

@pytest.mark.asyncio
async def test_two_efforts_on_one_model_are_one_readiness_question_about_the_bare_model(
    tmp_path: Path,
) -> None:
    """De-duplication is over the model a role runs on, never over the level it reasons at.

    `instruments/preflight/efforts.py` declares `Claude.OPUS` at two efforts and nothing else. The
    port's `check_ready` takes a bare `ModelId`, and the Claude harness's costs a turn, so a
    preflight keyed on the whole choice would ask twice and pay twice for one fact about the world.

    The dispatch is asserted with it, because the other half is that nothing was unwrapped to get
    there: the tasks the adapter was handed carry each role's level, and the one step-time
    capability question the two steps share is asked about the bare model too.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub()

    await _start(harness, "efforts", agents=stub)

    assert stub.asked_ready == [Claude.OPUS]
    assert [task.model for task in stub.ran] == [
        Claude.OPUS(effort=ClaudeEffort.XHIGH),
        Claude.OPUS(effort=ClaudeEffort.LOW),
    ]
    assert stub.asked_offers == [Claude.OPUS]
    assert entered == ["efforts"]

def test_every_provider_is_ranked_so_a_new_one_cannot_land_where_a_default_puts_it() -> None:
    """The mechanical half of the ordering: the table is total over the enum it is keyed on.

    A ranking read with a `dict.get` default would put a third provider wherever that default sits -
    silently, and on the wrong side of the paid one half the time. `_PROBE_COST` is indexed rather
    than got, so an unranked provider is a `KeyError` at the first run instead; this is what makes
    it a build failure instead, at the moment the member is added and before anybody spends a turn
    finding out.

    Read off `ports/agent.py`'s enum rather than a list written here, so that a fourth `Provider`
    widens the claim with the port rather than leaving a hand-copied set quietly narrower.
    """
    assert set(preflight._PROBE_COST) == set(Provider), (
        f"the probe-cost table ranks {sorted(str(member) for member in preflight._PROBE_COST)} and "
        f"`Provider` has {sorted(str(member) for member in Provider)}. Every provider needs a rank "
        f"before its backend can be probed in a chosen order, and a new one is exactly the case "
        f"where getting it wrong costs a turn"
    )

@pytest.mark.asyncio
async def test_a_workflow_whose_module_names_no_role_asks_no_backend_anything(
    tmp_path: Path,
) -> None:
    """What an empty registry buys: a workflow that runs no agent runs.

    Not merely "it does not fail". `workflows/noop/` was the case this was written against, and a
    preflight that asked about some default model, or about every provider the bundle was assembled
    with, would have made `agl run noop` depend on a harness that workflow never named - when `noop`
    existed precisely to prove the wiring with nothing else in the way. It was deleted later and
    the argument outlived it.

    The workflow is `instruments/preflight/unstaffed.py`'s and cannot be this module's: "declares
    no roles" is a fact about a whole namespace, and this file's namespace holds six factories that
    every workflow written in it inherits.
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
    """**The acceptance criterion**: a module-qualified workflow refuses at second zero.

    `instruments/preflight/qualified.py` writes the two lines an author ordinarily writes -
    `from . import roles`, then `await run.step(roles.implementer())` - and binds no `RoleFactory`
    in its own namespace at all. A scan of that namespace and only that namespace found nothing,
    asked **zero** backends anything, cleared second zero naming no provider, and let the run die
    at its first step with whatever the adapter said. That is the failure the provider check exists
    to prevent arriving with no warning, and it is worse than the over-approximation below for one
    reason: it is silent. `@workflow(roles=[…])` could not have had it, because the list
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

@pytest.mark.asyncio
async def test_a_role_a_module_binds_already_built_is_no_declaration_preflight_can_read(
    tmp_path: Path,
) -> None:
    """**A supported shape, pinned so that it stops reading as an oversight.**

    `instruments/preflight/prebuilt.py` writes `from .prebuilt_roles import IMPLEMENTER`, so its
    namespace holds a `Role` carrying `Claude.SONNET` and no `RoleFactory` and no module. The scan
    finds nothing, no backend is asked anything, and the step runs on a model nobody probed - here
    against a stub that would have refused every model it was asked about, so the empty
    `asked_ready` is the claim and the completed dispatch is what stops it being vacuous.

    **Why this is not `qualified.py`'s hole with a new hat.** Preflight scans *declarations*: a
    `@role(model=…)` factory carries a model readable without calling it, which is the whole reason
    `RoleFactory.model` exists and the reason `Role.model` is not a field an author writes. A `Role`
    is what a declaration produces, and reading values rather than declarations has no stopping
    point - `ROLES = [implementer()]` is the next complaint, and a dataclass holding one is the one
    after. Preflight's registry scan is best-effort, and containment at every step is the
    guarantee.

    **The other half of the shape cannot be probed at all**, which is what makes skipping it correct
    rather than merely tolerated: a `Role(...)` built by hand carries no model, and
    `test_a_role_that_never_went_through_a_factory_refuses_to_name_a_model` in
    `tests/sdk/test_roles.py` is where `Role.model`'s refusal is pinned. There is nothing for
    `check_ready` to be asked about.

    **And three of the four ways to reach a built role are already covered.** `@role` beside the
    binding, `from .roles import implementer` before a call, and `from . import roles` each leave a
    factory or a module in the namespace the scan reads. Only importing the built value hides it,
    which is the one spelling that imports a role in place of its declaration.

    What it costs is the accepted one, and it is the same one
    `test_a_role_built_inside_a_workflow_is_checked_at_the_step_it_is_handed_to` writes down: a
    record and a checkout exist by the time the step refuses, so such a run needs an `agl clear`
    where one refused at second zero does not.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(ready=False)

    await _start(harness, "prebuilt", agents=stub)

    assert stub.asked_ready == [], (
        "preflight probed a backend for a role its workflow's module holds as a built value, which "
        "is a declaration the scan is not written to read"
    )
    assert [task.model for task in stub.ran] == [Claude.SONNET], (
        "the run did not reach the step, so the empty probe list above is about a run that never "
        "needed a backend rather than about a role the scan did not see"
    )
    assert entered == ["prebuilt"]

# --- half one: the over-approximation, which is documented behaviour -----------------------------
#
# **Both tests of it are gone, and the behaviour is not.** `instruments/preflight/unused.py` was a
# workflow module that imported a role it never stepped with, so that a run of it demanded a
# provider it was never going to use - a false refusal, accepted deliberately because it is loud and
# one deleted import from being fixed, where an unchecked provider is silent and forty minutes
# expensive. Two tests read it: that the demand happens at all, and that the refusal names the
# factory, the module the role was declared in, the module it was *bound* in, and the word
# "imported", so that the one person it inconveniences has a next move.
#
# The role it imported was `fix`'s OpenAI `reviewer`, and `fix` is gone. **The instrument's whole
# shape was that the role came from an import of another module** - its own docstring said a role
# declared locally "would leave that line out of the measurement", the import being the thing
# somebody hitting this has to find and delete. The only other role module here is `roles.py`, whose
# `OpenAI.TERRA` is reserved: `qualified.py` discriminates on it being named by nothing else this
# file drives, so spending it here would cost that claim. Rebuilding the instrument therefore means
# a fifth module holding an `OpenAI.SOL` role of its own, which is new apparatus rather than a
# repair, and the two tests were deleted instead of rewritten.
#
# **What is unmeasured, for whoever restores it.** `sdk/_engine/preflight.py` still scans the
# namespace one level deep and still over-approximates - `test_a_factory_bound_below_the_workflow_
# is_still_in_the_namespace_preflight_reads` and the `qualified` case below cover the scan itself -
# but nothing now asserts that an imported-and-unstepped role demands its provider, and nothing
# asserts what that refusal has to say. Both come back with the fifth module.

@pytest.mark.asyncio
async def test_preflight_asks_whether_a_backend_is_ready_and_never_what_it_can_do(
    tmp_path: Path,
) -> None:
    """What left second zero with `roles=`, asserted as an absence at both of its ends.

    Containment used to run here too, over the roles `@workflow(roles=…)` declared, and it cannot:
    it needs `role.requires`, which lives on the `Role` a factory returns, and preflight may not
    call a factory - `implementer(ask=…)` takes a tool whose handler does not exist until a `Run`
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

    assert passing.asked_ready == [OpenAI.SOL, Claude.OPUS]
    assert passing.asked_offers == [], "containment ran at second zero, where it cannot"

# --- half one and a half: what the tool is, which warns and never refuses -------------------------
#
# A third question, and the only one in this file whose whole answer is a sentence: what is
# installed, and is it what this adapter was exercised against. It refuses nothing, ever - a version
# is not a state of the world AGL is entitled to have an opinion about beyond saying what it sees -
# so every claim below is a claim about a *line*, and every one of them is paired with the run
# carrying on. There is no cache and no flag: a tool outside its range warns on every run until it
# is moved, which is the whole of why the line has to be worth reading.
#
# `instruments/preflight/late.py` carries the version claims because its namespace names one model
# and so one provider - a note per provider over `two_providers` would be two copies of one
# sentence, and a count would then say nothing about what a standing produces.

# A range with two different ends, so what is printed exercises the spelling that names both of
# them rather than the one a single-release adapter happens to produce today.
_TESTED: Final = VersionRange("1.0.0", "1.1.0")

def _installed(version: str | None, *, where: str | None = "a stand-in binary") -> Installation:
    """What a backend reports, with only the half each test below varies left to vary."""
    return Installation(
        tool="a stand-in harness", version=version, tested=_TESTED, efforts={}, where=where
    )

async def _notes_for(installed: Installation, declared_by: Callable[..., object]) -> list[str]:
    """Every note one preflight wrote, over a namespace and a backend reporting this installation.

    `preflight.check` rather than `api.run`, because a note is what this half is about and a run
    can write more of its own on the way out - `sdk/_engine/teardown.py`'s, about what it kept.
    """
    notes: list[str] = []
    await preflight.check(_Stub(installed=installed), _Repository(), declared_by, notes.append)
    return notes

@pytest.mark.asyncio
async def test_only_a_tool_outside_its_tested_range_warns_and_each_way_warns_differently() -> None:
    """Five arrangements over one namespace: silence inside the range, and four ways to be outside.

    **Silence is the first of them and the load-bearing one.** A line on every run about a tool
    that is exactly what AGL was tested against is noise that trains an operator to skip the place a
    real line appears - the same argument `tests/test_api.py` makes about a sync that worked, and
    the reason its count of stderr lines on a good run is still one.

    **The other four are four different next moves**, which is why `Standing` has four members
    outside `WITHIN` and not one. Newer: nothing to do, watch for behaviour no workflow explains.
    Older: update the tool. Unreadable: AGL cannot order what the tool said, so compare the two
    versions yourself. Unreported: nothing answered at all. A single sentence covering all four
    would send every reader to the same place, and three of them to the wrong one.

    So the distinctness of the four lines is asserted as well as their content: the version that was
    read is in each one that has one, the range is in all of them, and no two are the same sentence.
    """
    silent = await _notes_for(_installed("1.1.0"), late.fn)
    said = [
        await _notes_for(_installed(version), late.fn)
        for version in ("1.2.0", "0.9.0", "1.1.0-rc1", None)
    ]

    assert silent == [], "a tool sitting inside the range it was tested against was warned about"
    assert [len(one) for one in said] == [1, 1, 1, 1], (
        f"four standings produced {[len(one) for one in said]} lines. One standing is one note - "
        f"a provider asked twice would double them and a branch that fell through would drop one"
    )
    lines = [one[0] for one in said]
    assert all(line.startswith("WARNING: ") for line in lines), lines
    assert all("a stand-in harness" in line for line in lines), (
        "a line left out the name of the tool it is about, which is the one thing no layer above "
        "`ports/agent.py` may spell for itself - `Installation.tool` carries it as data"
    )
    assert all("1.0.0 to 1.1.0" in line for line in lines), (
        "a line left out the range AGL was tested against, so the reader was told their version is "
        "wrong and not what it is being measured against"
    )
    assert all(
        version in line
        for version, line in zip(("1.2.0", "0.9.0", "1.1.0-rc1"), lines[:3], strict=True)
    ), "a line left out the version the tool reported, which is half of what it is comparing"
    assert len(set(lines)) == 4, (
        f"four standings produced {len(set(lines))} distinct sentences. Each is a different next "
        f"move for the person reading it, and two spelled alike send one of them nowhere"
    )

@pytest.mark.asyncio
async def test_a_tool_that_answered_nothing_is_told_apart_from_one_that_was_never_found() -> None:
    """`Installation.where` exists for this one sentence, and here is where it earns its place.

    Both are `UNREPORTED` and they are two different machines. A binary that is there and would not
    say what version it is sends somebody to that binary, named; nothing found at all sends them to
    whether the tool is installed where AGL looks for it, and naming a path there would be naming a
    path that is not on the machine. The port answers the second with `None`, and this is the only
    reader that can tell them apart.
    """
    quiet = await _notes_for(_installed(None, where="/opt/stand-in/harness"), late.fn)
    missing = await _notes_for(_installed(None, where=None), late.fn)

    assert "/opt/stand-in/harness" in quiet[0], (
        "a binary that was found and would not answer was not named, so the reader has nothing to "
        "go and run by hand"
    )
    assert "/opt/stand-in/harness" not in missing[0]
    assert quiet != missing, (
        "a tool nothing could find and a tool that would not answer got the same sentence, and "
        "they are two different things to go and do"
    )

@pytest.mark.asyncio
async def test_a_version_warning_is_out_before_a_readiness_probe_that_refuses_the_run() -> None:
    """**Why the note is handed to a callback and not returned**, asserted rather than argued.

    `check` is allowed to raise, and a readiness probe refusing is exactly the case where the
    version that was reported is the thing most worth having read - a harness too old to answer the
    way this adapter asks is refused *by* that probe. Notes returned from `check` would leave with
    the exception and reach nobody, and the operator would be told their backend is not ready with
    no mention of the version sitting underneath it.

    The ordering is also what keeps the free local question first: the test above this half asserts
    that a repository that can name no committer spends no installation probe at all.
    """
    notes: list[str] = []
    stub = _Stub(ready=False, installed=_installed("1.2.0"))

    with pytest.raises(UpstreamUnavailable):
        await preflight.check(stub, _Repository(), late.fn, notes.append)

    assert len(notes) == 1 and "1.2.0" in notes[0], (
        f"a run refused at the readiness probe reported {notes}. The version was read before that "
        f"probe and is the likeliest explanation of it, so it has to be out before it can be lost"
    )

@pytest.mark.asyncio
async def test_the_installation_probe_is_asked_once_per_provider_and_not_once_per_role() -> None:
    """Two counts that differ, over `instruments/preflight/providers.py`'s three models.

    `installation` describes the tool a backend starts and not the model it was handed, so a second
    model on one provider re-reads one binary - two spawns on the OpenAI adapter and one on the
    Claude adapter, every run, for an answer already in hand. Readiness is the other way round: it
    is a question about serving *this* model, so it is asked once per model and the count below is
    three against two.

    Three models over two providers is the smallest namespace where those two numbers differ, which
    is why this claim cannot be made in this file: its own namespace names one model per provider.
    """
    stub = _Stub()
    notes: list[str] = []

    await preflight.check(stub, _Repository(), broad.fn, notes.append)

    assert stub.asked_ready == [OpenAI.SOL, OpenAI.LUNA, Claude.OPUS]
    assert stub.asked_installation == [OpenAI.SOL, Claude.OPUS], (
        f"the tool was asked about {[str(model) for model in stub.asked_installation]}. Two models "
        f"of one provider are one tool, and asking twice spends a spawn to learn what was just read"
    )
    assert notes == [], "a backend inside its range with no listing at all still found something"

@pytest.mark.asyncio
async def test_a_role_naming_a_level_the_catalogue_lacks_is_warned_about_and_never_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """**The specific half**, and the whole reason a listing is read at all.

    `providers.editor` asks for `OpenAI.LUNA` at `ultra`, and the backend below lists every level
    but that one for it. What the operator is owed is not "your version is odd" but the actual
    disagreement: which factory, which model, which level, and what the tool does list instead - in
    the tool's own order, so that the last of them can be named as the ceiling. `ports/agent.py`'s
    `ModelEfforts.levels` is a tuple and not a set for exactly this sentence.

    **The ceiling is named as the top of the listing and never as what this step will run at.** The
    tool lowers a level it does not offer rather than refusing - `adapters/claude_code/translate.py`
    and `adapters/openai/translate.py` each say so above the constant they translate an effort
    through - and which level it lowers to is not something measured here, so the line says what
    the catalogue says and stops.

    Two other roles in that namespace name no level at all and one of them shares this one's
    provider, so the single line is also the claim that a bare model is not warned about.

    Driven through `api.run` because "never refuses" is the other half: the run reaches its
    workflow, the step is dispatched at the level the role asked for, and the warning is a line on
    stderr.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(
        installed=Installation(
            tool="a stand-in harness",
            version="1.0.0",
            tested=VersionRange("1.0.0", "1.0.0"),
            efforts={
                OpenAI.LUNA: ModelEfforts(
                    levels=("low", "medium", "high", "xhigh", "max"), default="medium"
                )
            },
        )
    )

    await _start(harness, "broad", agents=stub)

    printed = capsys.readouterr().err
    warned = [line for line in printed.splitlines() if line.startswith("WARNING: ")]
    assert len(warned) == 1, printed
    for part in ('"editor"', '"openai:luna"', '"ultra"', "low, medium, high, xhigh, max", '"max"'):
        assert part in warned[0], (
            f"the line left out {part!r}: {warned[0]}. It is one sentence and each of those is a "
            f"different half of the disagreement - the line to edit, the model, the level asked "
            f"for, what the tool offers instead, and the most it will do"
        )
    assert entered == ["broad"], "a level the tool does not list refused the run instead of warning"
    assert [task.model for task in stub.ran] == [OpenAI.LUNA(effort=OpenAIEffort.ULTRA)], (
        "the level the role named did not reach the adapter, so AGL substituted one of its own - "
        "the whole point of warning rather than refusing is that the tool decides this"
    )

@pytest.mark.asyncio
async def test_two_levels_one_model_lacks_are_two_warnings_where_readiness_is_one_probe() -> None:
    """The de-duplication here is over the whole choice, where readiness de-duplicates over the
    model.

    `instruments/preflight/efforts.py` declares `Claude.OPUS` at two efforts, and the backend below
    lists neither. Readiness is one question - whether that backend can serve that model is one
    fact about the world and one bill - but "the level you named is not on offer" is a different
    sentence about each level, naming a different factory and a different line to edit. A scan that
    reused `_demanded`'s mapping would type-check, ask readiness correctly, and drop one of the two
    warnings on the floor.
    """
    listing = Installation(
        tool="a stand-in harness",
        version="1.0.0",
        tested=VersionRange("1.0.0", "1.0.0"),
        efforts={Claude.OPUS: ModelEfforts(levels=("medium",), default="medium")},
    )
    stub = _Stub(installed=listing)
    notes: list[str] = []

    await preflight.check(stub, _Repository(), two_levels.fn, notes.append)

    assert stub.asked_ready == [Claude.OPUS], "readiness stopped being one question per model"
    assert len(notes) == 2, notes
    assert ['"deliberate"' in notes[0], '"hurried"' in notes[1]] == [True, True], (
        f"the two lines named {notes}. Each is about one factory's own declaration, so a pair "
        f"de-duplicated on the model names one line to edit and leaves the other unfindable"
    )

@pytest.mark.asyncio
async def test_a_version_warning_reaches_stderr_and_the_run_it_warns_about_still_finishes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The wiring, end to end: the engine builds the sentence and `api.py`'s `_warn` writes it.

    `sdk/` may not import `api` - contract 1 - so the note travels as the callback `api.run` hands
    `check`, which is `sdk/_engine/teardown.py`'s arrangement one stage earlier in the same run.
    Stderr and never stdout, for `cli/commands/__init__.py`'s reason: a name a machine reads goes to
    stdout and a note about the run does not.

    And the run finishes. Nothing about a version reaches an exit code, so the record is there to
    resume or clear afterwards exactly as it would have been, and the workflow ran.
    """
    entered.clear()
    harness = _fakes(tmp_path)

    await _start(harness, "late", agents=_Stub(installed=_installed("1.2.0")))

    printed = capsys.readouterr()
    warned = [line for line in printed.err.splitlines() if line.startswith("WARNING: ")]
    assert len(warned) == 1 and "1.2.0" in warned[0], printed.err
    assert printed.out == "", "a note about a run went to the stream a machine reads"
    assert entered == ["late"], "a version outside the tested range stopped the workflow"
    assert not await _no_record(harness), "the run was warned about and did not finish"

# --- half two: containment, over the role a step is actually handed ------------------------------
#
# The four suites below measured the same claims through `api.run` once. What moved is the
# moment and not the claim: same class, same exit code, same sentence, one `run.step` later. The
# module docstring lists them and says what they stopped being able to assert.

@pytest.mark.asyncio
async def test_a_role_requiring_what_its_backend_lacks_is_refused_with_the_member_named(
    tmp_path: Path,
) -> None:
    """The second check. `DeniedError` - exit 5 - and the message names the missing member.

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
async def test_a_missing_tool_calling_says_that_tools_put_it_there(tmp_path: Path) -> None:
    """The third check, which is the second check plus one clause in the message.

    `reporter()` declares `tools=` and no `requires` at all, so `tool_calling` is in its requirement
    because `Role.__post_init__` folded it in - and "either the role names a model whose backend
    has it, or it stops requiring it" is unactionable advice about a line nobody wrote. What the
    reader needs is which declaration implied it, because that is the line they would edit.
    `sdk/roles.py` asks for this sentence by name, and this is the test that keeps it there.

    There was a second clause of this shape, for a `MID_RUN_QUESTIONS` that `on_question` had
    folded in, and it was deleted with the member rather than rewritten: `_unmet` has one such
    clause now, and this is it.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_CALL)
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError) as caught:
        await run.step(reporter())

    said = str(caught.value)
    assert "tool_calling" in said
    assert "tools" in said

@pytest.mark.asyncio
async def test_a_role_that_typed_the_member_itself_gets_no_extra_clause(tmp_path: Path) -> None:
    """The clause above is about a *declaration*, not about the member, which keeps it honest.

    `builder()` requires `SHELL` because its author typed `requires={Capability.SHELL}`, and there
    is nothing to explain: a message telling them the framework put it there would be false, and a
    message mentioning `tools` at all would send them looking for a declaration they never wrote.

    The clause is conditioned on the *trigger* rather than on the member - and one conditioned on
    the member would fire here for a role that declares no tool at all.
    """
    harness = _fakes(tmp_path)
    stub = _Stub(offers=EVERYTHING - {Capability.SHELL})
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError) as caught:
        await run.step(builder())

    assert "declares `tools`" not in str(caught.value)
    assert "folds it in" not in str(caught.value)

@pytest.mark.asyncio
async def test_a_role_built_inside_a_workflow_is_checked_at_the_step_it_is_handed_to(
    tmp_path: Path,
) -> None:
    """**What makes the third check real, and what the registry costs, in one run.**

    An asking tool's handler is a closure over the `Run`, so a workflow that negotiates calls its
    role's factory - `declared(ask=tool)` - inside its own function, and that value has a
    requirement no scan of a namespace could have seen: the value did not exist until the body ran.
    Preflight admitted a model, and the step is where the difference becomes visible.

    **This clause used to be measured on `MID_RUN_QUESTIONS` and the check moved rather than
    vanishing.** `Role.__post_init__` folded that member in from `on_question` at the very line it
    folds `TOOL_CALLING` in from `tools`, and the workflow that hands its implementer a handler now
    hands it a `Tool` - so the same statement, in the same place, still produces a role a namespace
    scan cannot have seen, and `Steps.step` still calls `require` before `_namespace()` opens
    anything. Losing the member cost this check nothing; it changed which fold carries it.

    Without this line, the run does not fail *here*. The tool never reaches the model, the agent
    cannot fire it, and the step ends with `RoleIncompleteError` at exit 6 - a failure that names
    a prompt where the fact is a backend that cannot call a tool at all.

    **The record is asserted present, and that assertion carries two meanings.** It is still the
    contrast that makes this the other half rather than a copy of the first - preflight passed, so
    the run exists and only one step of it was refused. It is now also the accepted cost written
    down where it can be checked: a capability mismatch is caught here, with a
    record written and a worktree opened, and no earlier - so this run needs an `agl clear` where
    one refused at second zero does not.
    """
    entered.clear()
    harness = _fakes(tmp_path)
    stub = _Stub(offers=CANNOT_CALL)

    with pytest.raises(DeniedError) as caught:
        await _start(harness, "replacing", agents=stub)

    said = str(caught.value)
    assert "'implement'" in said, "the refusal does not name the step the role was handed to"
    assert "tool_calling" in said
    assert "tools" in said
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
    because that is the value `api.run` pins into `RunSpec.base_sha` and hands `Run`.
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

    Four steps over two models in two namespaces, and two calls. The port contracts it stable
    for the duration of a run, so a table per namespace would be asking a second time for an answer
    that cannot have changed - and the child is in this test because a per-namespace table passes
    every version of it that only steps in the root.

    **Two models rather than one.** The claim that two answers to a question contracted to have
    one would let a run admit a role and refuse its twin used to be measured at second zero, over
    the declared tuple; there is no such moment now, so it is measured here, where the calls are.
    Order is asserted with the count for the same reason it is in half one.

    Three calls on one role, since the call carries no name: the first two share an address and are
    separated by the counter, and the third is in a namespace of its own. What is counted
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
async def test_the_capability_cache_keeps_one_entry_for_one_model_at_two_efforts() -> None:
    """`Capabilities` is keyed by the bare model, so a second level is a hit and not a question.

    Keyed on the whole choice, the second `require` would miss and ask again - and, worse, a table
    keyed on a union that answered `.get` with the bare model would type-check and miss every time.
    The entry is read directly, because the count of questions alone cannot tell one entry from two
    entries filled by two calls that happened to be de-duplicated somewhere else.
    """
    stub = _Stub()
    capabilities = preflight.Capabilities()

    @role(model=Claude.OPUS(effort=ClaudeEffort.MAX))
    def thorough() -> Role:
        return Role(name="thorough", instructions="read all of it")

    @role(model=Claude.OPUS(effort=ClaudeEffort.LOW))
    def brief() -> Role:
        return Role(name="brief", instructions="read the summary")

    await capabilities.require(stub, thorough(), step="thorough")
    await capabilities.require(stub, brief(), step="brief")

    assert stub.asked_offers == [Claude.OPUS]
    assert capabilities._known == {Claude.OPUS: EVERYTHING}

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
    stub = _Stub(offers=CANNOT_CALL)
    run = await _direct(harness, stub)

    with pytest.raises(DeniedError):
        await run.step(implementer(ask=_asking()))

    assert not (tmp_path / "trees" / str(LABEL)).exists()
    assert stub.ran == []

# --- the module's own surface --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_takes_two_ports_a_workflow_function_and_a_reporter_and_no_bundle() -> None:
    """`preflight.check` is callable with two ports, one function and a sink, which is the
    signature decision.

    It takes the ports it asks and never a `Services`: an `AgentRunner`, which answers all three of
    preflight's questions about a backend, and a `History`, which answers the one about the
    repository. The bundle would hand it eight, and six more readers would then be one field access
    away in the module whose whole job is to refuse before anything has happened. The third argument
    is the workflow's own `async def` and not a `Workflow` - which this module could not import
    without a cycle, `sdk/_workflow.py` importing `Capabilities` from here - and it is the smallest
    thing that names the registry, since a function knows the module its `def` ran in.

    **The fourth is where a warning goes, and it is a callback rather than a return** for
    `sdk/_engine/teardown.py`'s reason one layer over: `sdk/` may not import `api`, so the engine
    builds the sentence and `api.py`'s `_warn` is what writes it to a stream. Returning the notes
    instead would tie them to a call that is allowed to raise - and a readiness probe refusing is
    exactly the case where the version that was reported is the thing worth having read.

    So the composition root passes what it already holds and learns nothing about how a role is
    found. The call below is the whole assertion - it compiles and it runs with no bundle in sight -
    and the second half of it is that what got walked was this module's namespace: two models,
    cheapest probe first, and no capability asked about either.
    """
    stub = _Stub()
    notes: list[str] = []

    await preflight.check(stub, _Repository(), two_providers.fn, notes.append)

    assert (stub.asked_ready, stub.asked_offers) == ([OpenAI.SOL, Claude.OPUS], [])
    assert notes == [], "a backend inside its tested range was warned about"
