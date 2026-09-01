"""The composition root: both bundles build, both are port-typed, and neither asks the world.

Four properties, and each is a thing that would be expensive to discover later.

**Every field of `Services` that is a port is declared as a port ABC.** Asserted against
`get_type_hints`, not against the runtime types, because the runtime types are right by accident on
any bundle that happens to have been built correctly - what matters is the *declaration*, since that
is what every consumer above sees and what would let a module branch on which implementation it got.
One comparison covers all nine fields, and a tenth added without being written down breaks it. The
ninth is `build`, which is not a port and is kept in a list of its own for that reason: a `str` on
this class has to be a deliberate act, and the argument for the one there is that `Verifier.verify`
takes the build command as a parameter and its only caller is above the edge.

**Construction is eager but inert.** The real bundle below is built with a home, a repository and a
trees root that do not exist, and every one of the paths handed in is a directory nothing has
created. It builds anyway. That is the property that put `check_ready` on the agent port - a
container cannot `await`, so it cannot ask whether a harness is installed or whether a directory is
a git repository, and preflight is where a run finds out. No test here starts a process, opens a
socket or runs git, and none of them needs a `.git` anywhere.

**The three git fakes are one repository**, asserted by making a change through one and reading it
back through the others. Identity would pass against three fakes wired to three repositories the
day somebody adds a caching layer; a commit that a second fake cannot see would not.

**A missing pip extra is a refusal and not a fallback.** Both extras are installed in this repo's
virtualenv, so their absence is simulated where it actually bites - `None` in `sys.modules` for the
adapter module that imports the vendor package, which raises the same `ImportError` subclass a
genuinely missing extra raises, from the same statement. Those tests are also what pin the deferred
import: a bundle with the Claude connector disabled builds while that module is unimportable, which
is only true if nothing on that path imports it.
"""

import asyncio
import sys
from collections.abc import Callable, Mapping
from dataclasses import fields, replace
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Final, Self, get_type_hints
import pytest
from agl.adapters.claude_code import fake as claude_fake
from agl.adapters.filesystem.memory_store import MemoryStore
from agl.adapters.openai import fake as openai_fake
from agl.adapters.shell.fake import FakeVerifier
from agl.config import container
from agl.config.schema import AgentSettings, ClaudeSettings, OpenAiSettings, Project, Settings
from agl.ports.agent import (
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Claude,
    ModelId,
    OpenAI,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.clock import Clock
from agl.ports.errors import InputError, UpstreamUnavailable
from agl.ports.history import History
from agl.ports.home_layout import AglHome
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.integration import Integrator
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.terminal import Screen, Terminal
from agl.ports.tree_layout import TreesRoot
from agl.ports.verifier import Verifier, VerifierOutcome
from agl.ports.workspace import WorkspaceProvider
from agl.sdk.testing import Call, Reply

# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips, so every
# async test below carries `@pytest.mark.asyncio` of its own. Not a module-level `pytestmark`:
# most of this file is synchronous - construction is - and marking those would be a warning per
# test saying so.

# The bundle's eight ports and the ABC each one is declared as. Written out here rather than read
# off the class, so that a field quietly retyped to an adapter fails against a list somebody wrote
# on purpose instead of agreeing with itself.
_PORTS: Final = {
    "store": Store,
    "workspaces": WorkspaceProvider,
    "history": History,
    "integrator": Integrator,
    "verifier": Verifier,
    "terminal": Terminal,
    "clock": Clock,
    "agents": AgentRunner,
}

# The ninth field, which is not a port and is the only one that is not. `Verifier.verify` takes the
# build command as a parameter and its one call site is the merge gate inside `integrate()`, above
# the edge - so the bundle is what carries it (`sdk/_engine/services.py` argues the alternatives).
# A second list rather than a row in the first: the two say different things, and a tenth field
# arriving as a `str` should have to be added here by somebody who meant it.
_CONFIGURED: Final = {"build": str}

# The two adapter modules that import a vendor package at module level, and so the two that must
# not be reachable from a path that has not been told to construct them.
_CLAUDE_RUNNER: Final = "agl.adapters.claude_code.runner"
_RICH_TERMINAL: Final = "agl.adapters.rich_terminal.terminal"

_MEETS: Final = 5.0
"""How long the one rendezvous in this file waits before calling a widening that did not land.

Spent only on a failure: a barrier two coroutines can reach is reached in microseconds. Bounded
because of what the failure looks like - an agent whose coroutine nothing ever runs never arrives,
so this side of the rendezvous waits alone and the test hangs instead of failing."""

LABEL: Final = RunLabel("acceptance")
CHILD: Final = Namespace("T-01")

def _settings(tmp_path: Path, *, claude: bool = True, openai: bool = True) -> Settings:
    """An installation, with either connector switchable. No path below is created."""
    return Settings(
        home=AglHome(tmp_path / "agl-home"),
        agents=AgentSettings(
            claude=ClaudeSettings(enabled=claude, cli_path=None),
            openai=OpenAiSettings(enabled=openai, cli_path=None),
        ),
    )

def _project(tmp_path: Path) -> Project:
    """A registered project pointing at a repository that does not exist and never will."""
    return Project(
        name=ProjectName("myapp"),
        repo=tmp_path / "repo",
        trees=TreesRoot(tmp_path / "trees"),
        build="make check",
        build_timeout=600.0,
    )

def _ports_are_filled(services: container.Services) -> None:
    """Every port field holds an instance of the port it is declared as, and the ninth is there.

    `build` has no ABC to be an instance of, so what is asserted about it here is only that the
    bundle's fields are exactly the two lists above - a field on neither breaks this - and that a
    built bundle carries something in it. What it carries is two tests further down.
    """
    assert {field.name for field in fields(services)} == set(_PORTS) | set(_CONFIGURED)
    for name, port in _PORTS.items():
        assert isinstance(getattr(services, name), port), name
    assert services.build

def test_every_field_of_the_bundle_is_declared_as_a_port_and_never_as_an_adapter() -> None:
    """The one static assertion in this file, and the reason `Services` is worth having.

    A field declared `FilesystemStore` would type-check everywhere and put an adapter's name into
    every module that reads a bundle - which is contract 5's rule broken by a type annotation
    rather than by an import, and import-linter would not see it.

    `build` is compared just as exactly, in a list of its own. It is project configuration rather
    than a capability, so there is no adapter it could name - and folding it into the same
    comparison is what keeps "a field arrived without anybody writing it down" a failure here.
    """
    assert get_type_hints(container.Services) == _PORTS | _CONFIGURED

def test_the_real_bundle_builds_and_fills_every_port(tmp_path: Path) -> None:
    """The all-real bundle, on a machine where nothing it names exists yet.

    Nothing under `tmp_path` is created by this test. If any constructor below resolved a binary,
    opened a repository or checked that a directory was there, this would fail - which is what
    makes it the test that pins construction as inert rather than merely fast.
    """
    services = container.real(_settings(tmp_path), _project(tmp_path))
    _ports_are_filled(services)
    assert not (tmp_path / "repo").exists()

def test_the_fakes_bundle_builds_and_fills_every_port(tmp_path: Path) -> None:
    """The all-fakes bundle - target #8's deployment - and its port-typed half."""
    harness = container.fakes(TreesRoot(tmp_path / "trees"))
    _ports_are_filled(harness.services)

def test_the_fakes_bundle_needs_no_extra_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare `pip install agl`, simulated: both extra-bearing adapter modules unimportable.

    This is the claim that makes the fakes bundle a deployment rather than a convenience - every
    command runs on it, and an operator who installed no extras is exactly who runs a `--dry-run`.
    """
    monkeypatch.setitem(sys.modules, _CLAUDE_RUNNER, None)
    monkeypatch.setitem(sys.modules, _RICH_TERMINAL, None)
    harness = container.fakes(TreesRoot(tmp_path / "trees"))
    _ports_are_filled(harness.services)

def test_the_real_bundle_carries_the_projects_configured_build_command(tmp_path: Path) -> None:
    """The route nothing else can close, closed at the one place both ends are in scope.

    `Verifier.verify` takes the command, its only caller is the merge gate inside `integrate()`, and
    `Project.build` is where the command is written down - so something has to carry it across, and
    the container is the only thing holding a `Project` *and* building the bundle a `Run` gets.
    Asserted as the project's own string rather than as "not empty", because the failure this
    catches is a plausible one: a bundle that carried a placeholder would gate every merge on a
    build nobody configured.
    """
    assert container.real(_settings(tmp_path), _project(tmp_path)).build == "make check"

@pytest.mark.asyncio
async def test_the_fakes_bundle_carries_a_build_command_the_gate_answers_to(
    tmp_path: Path,
) -> None:
    """The two halves that have to be one string, driven rather than compared.

    `FakeVerifier` scripts its verdicts **by command** - "scripting by the thing a test can name in
    advance and hold still" - so a test that wants a red gate has to name the command the bundle is
    carrying. A literal here and a literal in the container would agree until one of them changed,
    and the failure is silent in the worst direction: an unscripted command *passes*, so the script
    stops matching and every landing sails through the gate the test thought it had closed.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"))
    assert harness.services.build == container.FAKE_BUILD

    harness.verifier.answers(container.FAKE_BUILD, passed=False, status=2, output="2 failing")
    outcome = await harness.services.verifier.verify(harness.services.build, tmp_path)

    assert (outcome.passed, outcome.status, outcome.output) == (False, 2, "2 failing")

def test_the_fakes_bundle_takes_a_build_command_of_its_own(tmp_path: Path) -> None:
    """A test about a *particular* command reaching the gate has to choose it, so `fakes()` takes
    one - keyword-only, beside the scripts, for the reason those are keyword-only."""
    harness = container.fakes(TreesRoot(tmp_path / "trees"), build="./gradlew check")
    assert harness.services.build == "./gradlew check"

def test_the_concrete_fakes_are_the_same_objects_as_the_ports_in_the_bundle(
    tmp_path: Path,
) -> None:
    """`FakeServices` is two views of one set of instances, not two sets that happen to agree."""
    harness = container.fakes(TreesRoot(tmp_path / "trees"))
    assert harness.store is harness.services.store
    assert harness.verifier is harness.services.verifier
    assert harness.terminal is harness.services.terminal
    assert harness.clock is harness.services.clock

@pytest.mark.asyncio
async def test_a_change_through_one_git_fake_is_visible_through_the_others(
    tmp_path: Path,
) -> None:
    """The shared `FakeRepository`, asserted the way three separate ones would have been caught.

    A commit is made through a workspace the *provider* handed out, and then read back through the
    *history* fake and landed through the *integrator* fake. Three separately constructed fakes
    would be three unrelated repositories: the history lookup would raise `NotFoundError` for a
    branch it has never heard of, long before the landing.

    The last assertion is the identity half, made behaviourally: the `FakeRepository` this class
    exposes answers about the branch the provider moved, so it is the same instance and not a
    fourth one built for the caller.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})
    services = harness.services

    base = await services.history.default_ref()
    run = await services.workspaces.open(LABEL, None, base)
    child = await services.workspaces.open(LABEL, CHILD, run.branch)
    (child.path / "new.txt").write_bytes(b"what the child wrote\n")
    committed = await child.commit_all("child work")

    # Made through the provider's workspace; read through the history fake.
    assert await services.history.resolve(child.branch) == committed

    # Landed through the integrator fake; the result is reachable through the history fake again.
    outcome = await services.integrator.land(child, run)
    assert outcome.head is not None
    assert await services.history.contains(committed, outcome.head)

    # And the repository this bundle hands back is the one all three were built over.
    assert harness.repository.tip(run.branch) == outcome.head

@pytest.mark.asyncio
async def test_two_fakes_bundles_share_no_repository(tmp_path: Path) -> None:
    """One bundle is one repository, and the shared instance is shared no further than that.

    The honest analogue of two directories on disk, and what keeps a test that seeded a file from
    leaking it into the next one.
    """
    first = container.fakes(TreesRoot(tmp_path / "one"), files={"src/a.txt": b"one\n"})
    second = container.fakes(TreesRoot(tmp_path / "two"))
    assert first.repository is not second.repository

    base = await first.services.history.default_ref()
    run = await first.services.workspaces.open(LABEL, None, base)
    assert second.repository.tip(run.branch) is None

@pytest.mark.asyncio
async def test_the_routing_runner_holds_both_connectors_when_both_are_enabled(
    tmp_path: Path,
) -> None:
    """Both providers served, addressed through the port and never through a mapping nobody has.

    `capabilities` is what asks - it is the one member that reaches the adapter without starting
    anything, since both real runners answer it from a constant after checking the model.
    """
    services = container.real(_settings(tmp_path), _project(tmp_path))
    assert await services.agents.capabilities(Claude.OPUS)
    assert await services.agents.capabilities(OpenAI.SOL)

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claude", "openai", "served", "absent", "held"),
    [
        (True, False, Claude.OPUS, OpenAI.SOL, "['claude']"),
        (False, True, OpenAI.SOL, Claude.OPUS, "['openai']"),
    ],
)
async def test_a_disabled_connector_is_absent_from_the_routing_runner(
    tmp_path: Path,
    claude: bool,
    openai: bool,
    served: ModelId,
    absent: ModelId,
    held: str,
) -> None:
    """One entry per *enabled* connector: the other provider is not there to be dispatched to.

    The refusal is `RoutingAgentRunner`'s and it names what the run was assembled with, which is
    the assertion below - "it raised" would also be satisfied by a runner that held the wrong one.
    """
    services = container.real(_settings(tmp_path, claude=claude, openai=openai), _project(tmp_path))
    assert await services.agents.capabilities(served)
    with pytest.raises(InputError) as refused:
        await services.agents.capabilities(absent)
    assert held in str(refused.value)

def test_both_connectors_disabled_is_the_routing_runners_own_refusal(tmp_path: Path) -> None:
    """Not pre-empted here, and not duplicated: the message is the one written where the facts are.

    `schema.AgentSettings` allows both sections disabled deliberately - `agl workflows` has no
    business failing over it - so the refusal belongs to the object that would have had to serve
    the run, and this test pins that it is still that object's.
    """
    with pytest.raises(InputError) as refused:
        container.real(_settings(tmp_path, claude=False, openai=False), _project(tmp_path))
    assert "no adapters at all" in str(refused.value)

@pytest.mark.asyncio
async def test_a_scripted_fake_agent_answers_through_the_bundles_agent_runner(
    tmp_path: Path,
) -> None:
    """The hand-off, end to end: a script goes in as an argument and comes back through the port.

    Two scripts and two models, because both providers' fakes are called `FakeAgentRunner` and
    both scripting types are called `Script`. A container that imported the names rather than the
    modules would serve one vendor's fake under both keys, and the only way to see that is to ask
    each provider for something only its own script says.
    """

    async def claude_script(conversation: claude_fake.Conversation) -> AgentOutcome:
        return AgentOutcome(
            stop_reason=StopReason.COMPLETED, text=f"claude: {conversation.task.instructions}"
        )

    async def openai_script(conversation: openai_fake.Conversation) -> AgentOutcome:
        return AgentOutcome(
            stop_reason=StopReason.COMPLETED, text=f"openai: {conversation.task.instructions}"
        )

    harness = container.fakes(
        TreesRoot(tmp_path / "trees"), claude=claude_script, openai=openai_script
    )
    agents: AgentRunner = harness.services.agents

    assert (await agents.run(_task(tmp_path, Claude.OPUS))).text == "claude: implement it"
    assert (await agents.run(_task(tmp_path, OpenAI.SOL))).text == "openai: implement it"

def _task(workspace: Path, model: ModelId) -> AgentTask:
    """One task, addressed to whichever provider's model is named. Nothing here runs it."""
    return AgentTask(
        instructions="implement it",
        workspace=workspace,
        model=model,
        restrictions=frozenset(),
        tools=(),
    )

def test_a_missing_claude_extra_refuses_and_names_the_pip_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`UpstreamUnavailable`, because `src/agl/ports/agent.py` settles the class: a missing harness
    is not an input.

    The operator's configuration is correct - they enabled a backend they meant to enable - so an
    `InputError` would send them to edit a setting that is already right. What is absent is the
    harness, and the message says which command installs it.
    """
    monkeypatch.setitem(sys.modules, _CLAUDE_RUNNER, None)
    with pytest.raises(UpstreamUnavailable) as refused:
        container.real(_settings(tmp_path), _project(tmp_path))
    assert "agl[claude]" in str(refused.value)

def test_a_disabled_claude_connector_never_imports_the_adapter_that_needs_the_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deferred import, pinned by behaviour: unimportable and unreached at the same time.

    A module-level import of `ClaudeCodeRunner` would fail this, which is the whole reason that
    import sits inside the function that constructs it. An operator who uses one backend must not
    be unable to start AGL because the other one's extra is missing.
    """
    monkeypatch.setitem(sys.modules, _CLAUDE_RUNNER, None)
    services = container.real(_settings(tmp_path, claude=False), _project(tmp_path))
    _ports_are_filled(services)

def test_a_missing_terminal_extra_refuses_rather_than_falling_back_to_headless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ARCHITECTURE.md`'s "Deliberately not built" refuses a `Display` port, so there is no
    second surface here to fall back to.

    The fallback is the plausible bug and this is what forbids it: `HeadlessTerminal` would build
    happily and then raise `UpstreamUnavailable` at the first screen carrying a question, turning
    a missing extra into a failure an hour into a run and nowhere near its cause.
    """
    monkeypatch.setitem(sys.modules, _RICH_TERMINAL, None)
    with pytest.raises(UpstreamUnavailable) as refused:
        container.real(_settings(tmp_path), _project(tmp_path))
    assert "agl[terminal]" in str(refused.value)

# --- Substituting through the bundle, and compiling the workflow-facing vocabulary ---------------

class _Recording(Terminal):
    """A `Terminal` that draws nothing and is not the headless one. Two lines is the whole of it.

    It exists so that `with_terminal` can be handed something distinguishable from what `fakes()`
    built; `tests/contracts/terminal.py` is what says how a `Terminal` behaves and this makes no
    claim to. Every member refuses, because no test below shows anything on it.
    """

    async def show[T](
        self, view: Callable[..., Screen[T]], /, *, priority: int = 0, **params: object
    ) -> T:
        raise AssertionError("nothing in this file shows a screen")

    @property
    def pending(self) -> Mapping[int, int]:
        raise AssertionError("nothing in this file reads a queue")

    async def __aenter__(self) -> Self:
        raise AssertionError("nothing in this file enters a terminal")

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        raised: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        raise AssertionError("nothing in this file enters a terminal")

class _Watching(FakeVerifier):
    """A gate that records the checkout it was pointed at, and otherwise is the fake it extends.

    What `with_verifier` is for, in its smallest honest form: something distinguishable from what
    `fakes()` built, which is `_Recording`'s reason one field over. `super().verify` rather than an
    invented outcome, because that is the whole argument for the verb taking a `FakeVerifier` - an
    instrument that replaced the fake outright could not be told what to answer.
    """

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[Path] = []

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        self.asked.append(workdir)
        return await super().verify(command, workdir)

def test_with_terminal_moves_both_views_of_the_bundle_at_once(tmp_path: Path) -> None:
    """The first of the two findings these verbs answer, as the regression test for it.

    `FakeServices` holds one terminal under two names, and the substitution this replaced -
    `dataclasses.replace(harness.services, terminal=...)` - moved only `services.terminal`, leaving
    the sibling field pointing at the object that had just been discarded. Nothing reported that.
    Both assertions are needed: the first is what the old spelling already satisfied, and the second
    is the one it failed.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"))
    recorder = _Recording()

    substituted = harness.with_terminal(recorder)

    assert substituted.services.terminal is recorder
    assert substituted.terminal is recorder
    assert substituted.terminal is substituted.services.terminal

def test_with_store_moves_both_views_of_the_bundle_at_once(tmp_path: Path) -> None:
    """The same, one field over, and the one `agl/testing.py` is built on.

    That module wraps the ledger to record what a run wrote and to stop it at a step boundary, so a
    wrapper that left `store` naming the object underneath it would make `harness.store` a different
    ledger from the one the run used - and `agl/testing.py::over` states the agreement as a promise
    to its caller: "`fakes.store` on the returned `Harness` is that wrapper".

    **A second `MemoryStore` and never `harness.store` itself.** Substituting the object the bundle
    already holds satisfies both assertions whatever `with_store` does, since the incumbent is the
    substitute - a test that reads as coverage and measures nothing. `_Recording` above is the same
    arrangement one field over: something distinguishable from what `fakes()` built. A second
    `MemoryStore` is enough to be that, and costs nothing to construct.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"))
    wrapper = MemoryStore()

    substituted = harness.with_store(wrapper)

    assert substituted.services.store is wrapper
    assert substituted.store is wrapper

def test_with_verifier_moves_both_views_of_the_bundle_at_once(tmp_path: Path) -> None:
    """The third of these verbs, and the finding that bought it.

    The merge gate is the only hook a workflow's own test has *inside* a landing - the lease and the
    target's step lock are held from `integrate()` to settlement, and `Verifier.verify` is the one
    framework call in that window - so a test that wants to see two landings serialised, or to
    drive the conflict loop off a red gate that `ARCHITECTURE.md`'s "Invariants where a mistake is
    silent" names as work-destroying, substitutes a verifier. Until this verb existed the only way
    was `replace(fakes, services=replace(fakes.services, verifier=...))`, which is exactly the
    two-views defect the two tests above are about, written out by hand at every call site that
    needed it. The second assertion is the one that spelling failed.

    A `FakeVerifier` subclass rather than a bare `Verifier`, because that is the parameter's type
    and the field's: `answers` is what the field is for, so an instrument extends the fake instead
    of replacing it and stays scriptable while it is at it.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"))
    instrumented = _Watching()

    substituted = harness.with_verifier(instrumented)

    assert substituted.services.verifier is instrumented
    assert substituted.verifier is instrumented
    assert substituted.verifier is substituted.services.verifier

@pytest.mark.asyncio
async def test_a_substituted_verifier_is_the_one_a_landing_asks(tmp_path: Path) -> None:
    """And the verb is not only two assignments: what the bundle runs on is the substitute.

    `with_terminal`'s own claim, one field over - a substitution nothing downstream honoured would
    satisfy the identity test above and change no behaviour at all. Asked through `services`, which
    is what a `Run` receives, and answered by the subclass, which is what proves the instrument is
    in the path a landing takes rather than merely in a field beside it.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees")).with_verifier(_Watching())
    harness.verifier.answers(container.FAKE_BUILD, passed=False, status=3, output="2 failing")

    outcome = await harness.services.verifier.verify(container.FAKE_BUILD, tmp_path)

    assert isinstance(harness.verifier, _Watching) and harness.verifier.asked == [tmp_path]
    assert (outcome.passed, outcome.status) == (False, 3), (
        "a substituted gate that extends `FakeVerifier` still answers what the test scripted - "
        "which is what taking the fake's own type rather than the port buys, and why an instrument "
        "here does not have to invent a verdict of its own"
    )

def test_a_substitution_carries_every_other_object_across_by_identity(tmp_path: Path) -> None:
    """A substituted bundle is still *this* bundle, and the git fakes are the sharpest case.

    Three of the ports are views of one `FakeRepository`, so a `with_terminal` that rebuilt anything
    would hand back a bundle whose repository nothing else in it could see - and the caller's
    `harness.repository` would be answering about a repository the run never touched.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})

    substituted = harness.with_terminal(_Recording())

    assert substituted.repository is harness.repository
    assert substituted.store is harness.store
    assert substituted.verifier is harness.verifier
    assert substituted.clock is harness.clock
    assert substituted.services.workspaces is harness.services.workspaces
    assert substituted.services.agents is harness.services.agents
    assert substituted.services.build == harness.services.build

@pytest.mark.asyncio
async def test_one_agent_serves_both_providers(tmp_path: Path) -> None:
    """One callable behind both fakes, and the reason `agent=` is one parameter and not two.

    A `sdk.testing.Agent` is written in ports vocabulary and names no vendor, so the same function
    has to reach both fakes - which is what lets a workflow author write one agent for a run that
    addresses two providers, as `fix` does. It dispatches on `task.model`, which is the
    handle `sdk/testing.py` names, and each answer is one only that provider's dispatch produces.
    """

    def agent(task: AgentTask) -> Reply:
        return Reply(says=f"served {task.model}")

    harness = container.fakes(TreesRoot(tmp_path / "trees"), agent=agent)
    agents: AgentRunner = harness.services.agents

    assert (await agents.run(_task(tmp_path, Claude.OPUS))).text == f"served {Claude.OPUS}"
    assert (await agents.run(_task(tmp_path, OpenAI.SOL))).text == f"served {OpenAI.SOL}"

@pytest.mark.asyncio
async def test_a_raw_script_replaces_the_compiled_agent_for_its_own_provider(
    tmp_path: Path,
) -> None:
    """The one rule about the three parameters: the more specific wins, per provider.

    That is what makes the escape hatch usable a provider at a time - a negotiation written as a
    raw `Script` on the backend that negotiates, and the declarative agent everywhere else - and
    the second assertion is what says it is per provider rather than global.
    """

    async def claude_script(conversation: claude_fake.Conversation) -> AgentOutcome:
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="the raw script")

    def agent(task: AgentTask) -> Reply:
        return Reply(says="the compiled agent")

    harness = container.fakes(TreesRoot(tmp_path / "trees"), agent=agent, claude=claude_script)
    agents: AgentRunner = harness.services.agents

    assert (await agents.run(_task(tmp_path, Claude.OPUS))).text == "the raw script"
    assert (await agents.run(_task(tmp_path, OpenAI.SOL))).text == "the compiled agent"

@pytest.mark.asyncio
async def test_a_reply_is_performed_as_activity_then_calls(tmp_path: Path) -> None:
    """The whole of what a `Reply` means, in the order `sdk/testing.py` documents.

    One recorder across both channels, because the claim is about their order relative to each
    other and two separate lists could not state it. The `stop_reason` and the closing text come
    back on the outcome, which is the other half of what a `Reply` carries.

    **There were three channels and there are two.** `Reply.asks` sat between them and was performed
    through `Conversation.ask`, which reached a `QuestionHandler` on the `Role`. That whole path is
    gone: a question is an ordinary tool a workflow supplies, so a scripted agent asks one the way
    it calls anything else - a `Call` naming the workflow's own asking tool, in the `calls` list,
    with the payload that tool's schema asks for. Nothing was lost with the field, because there is
    no longer any question a *framework* could have performed.
    """
    seen: list[str] = []

    async def tool(payload: Mapping[str, JsonValue]) -> ToolResult:
        seen.append(f"called: {payload['note']}")
        return ToolResult(text="recorded")

    def agent(task: AgentTask) -> Reply:
        return Reply(
            activity=["first", "second"],
            calls=[Call("report", {"note": "the payload"})],
            says="done",
            stop_reason=StopReason.LIMIT,
        )

    harness = container.fakes(TreesRoot(tmp_path / "trees"), agent=agent)
    declared = Tool(
        name="report",
        description="report what happened",
        payload_schema=MappingProxyType({"type": "object"}),
        handler=tool,
    )
    task = replace(_task(tmp_path, Claude.OPUS), tools=(declared,))

    outcome = await harness.services.agents.run(task, on_activity=seen.append)

    assert seen == ["first", "second", "called: the payload"]
    assert (outcome.text, outcome.stop_reason) == ("done", StopReason.LIMIT)

@pytest.mark.asyncio
async def test_an_async_agent_is_awaited_and_a_sync_one_is_not(tmp_path: Path) -> None:
    """`Agent` is `(AgentTask) -> Reply | Awaitable[Reply]`, and both arms work.

    **The awaitable arm is not a convenience.** A rendezvous - two agents that each wait until the
    other has arrived - is the only arrangement that can distinguish real concurrency from a
    framework that ran everything in order, and it is the property `split` exists to demonstrate. A
    synchronous callable cannot await a barrier, and a threading primitive on one event loop
    deadlocks rather than waits, so a concurrency test written against a synchronous `agent=` fell
    out of it and into the raw per-provider escape hatch. The barrier below is the smallest form of
    that: two parties, one of them the test, so the agent cannot return until this function has
    arrived.

    **The synchronous arm has to survive it**, which is the second assertion and the reason the type
    is a union rather than a coroutine: `sdk/testing.py` argues that `lambda task: Reply(...)` being
    writable on one line is the whole point of a value-returning agent, and a widening that quietly
    required an `async def` would have taken that back.
    """
    barrier = asyncio.Barrier(2)

    async def waiting(task: AgentTask) -> Reply:
        await barrier.wait()
        return Reply(says="met the other one")

    harness = container.fakes(TreesRoot(tmp_path / "trees"), agent=waiting)
    dispatched = asyncio.create_task(harness.services.agents.run(_task(tmp_path, Claude.OPUS)))
    async with asyncio.timeout(_MEETS):
        await barrier.wait()
        assert (await dispatched).text == "met the other one"

    immediate = container.fakes(TreesRoot(tmp_path / "sync"), agent=lambda task: Reply(says="done"))

    assert (await immediate.services.agents.run(_task(tmp_path, Claude.OPUS))).text == "done"

@pytest.mark.asyncio
async def test_no_agent_and_no_script_is_still_each_providers_own_default(tmp_path: Path) -> None:
    """`agent=None` changes nothing: `fakes()` with nothing scripted is what it always was.

    Target #8 rests on it - a whole workflow runs on fakes without anybody writing an agent first -
    and the compilation must not have quietly replaced `unscripted` with an empty `Reply`, which
    would report nothing and fail every reporting step.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"))

    outcome = await harness.services.agents.run(_task(tmp_path, Claude.OPUS))

    assert "fake" in outcome.text and outcome.stop_reason is StopReason.COMPLETED
