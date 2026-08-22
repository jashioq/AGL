"""The composition root: both bundles build, both are port-typed, and neither asks the world.

Four properties, and each is a thing that would be expensive to discover later.

**Every field of `Services` is declared as a port ABC.** Asserted against `get_type_hints`, not
against the runtime types, because the runtime types are right by accident on any bundle that
happens to have been built correctly - what matters is the *declaration*, since that is what every
consumer above sees and what would let a module branch on which implementation it got. One
comparison covers all eight fields and a ninth field added without a port breaks it.

**Construction is eager but inert.** The real bundle below is built with a home, a repository and a
trees root that do not exist, and every one of the paths handed in is a directory nothing has
created. It builds anyway. That is the property stage 7 leaned on when it argued `check_ready` onto
the agent port - a container cannot `await`, so it cannot ask whether a harness is installed or
whether a directory is a git repository, and preflight is where a run finds out. No test here
starts a process, opens a socket or runs git, and none of them needs a `.git` anywhere.

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

import sys
from dataclasses import fields
from pathlib import Path
from typing import Final, get_type_hints

import pytest

from agl.adapters.claude_code import fake as claude_fake
from agl.adapters.openai import fake as openai_fake
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
)
from agl.ports.clock import Clock
from agl.ports.errors import InputError, UpstreamUnavailable
from agl.ports.history import History
from agl.ports.home_layout import AglHome
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.integration import Integrator
from agl.ports.store import Store
from agl.ports.terminal import Terminal
from agl.ports.tree_layout import TreesRoot
from agl.ports.verifier import Verifier
from agl.ports.workspace import WorkspaceProvider

# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips, so every
# async test below carries `@pytest.mark.asyncio` of its own. Not a module-level `pytestmark`:
# most of this file is synchronous - construction is - and marking those would be a warning per
# test saying so.

# The bundle's eight fields and the port each one is declared as. Written out here rather than read
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

# The two adapter modules that import a vendor package at module level, and so the two that must
# not be reachable from a path that has not been told to construct them.
_CLAUDE_RUNNER: Final = "agl.adapters.claude_code.runner"
_RICH_TERMINAL: Final = "agl.adapters.rich_terminal.terminal"

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
    """Every declared field holds an instance of the port it is declared as."""
    assert {field.name for field in fields(services)} == set(_PORTS)
    for name, port in _PORTS.items():
        assert isinstance(getattr(services, name), port), name


def test_every_field_of_the_bundle_is_declared_as_a_port_and_never_as_an_adapter() -> None:
    """The one static assertion in this file, and the reason `Services` is worth having.

    A field declared `FilesystemStore` would type-check everywhere and put an adapter's name into
    every module that reads a bundle - which is contract 5's rule broken by a type annotation
    rather than by an import, and import-linter would not see it.
    """
    assert get_type_hints(container.Services) == _PORTS


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
    """`UpstreamUnavailable`, because §3.2.1 settles the class: a missing harness is not an input.

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
    """§3.11 refuses display selection, so there is no second branch here to take.

    The fallback is the plausible bug and this is what forbids it: `HeadlessTerminal` would build
    happily and then raise `UpstreamUnavailable` at the first screen carrying a question, turning
    a missing extra into a failure an hour into a run and nowhere near its cause.
    """
    monkeypatch.setitem(sys.modules, _RICH_TERMINAL, None)
    with pytest.raises(UpstreamUnavailable) as refused:
        container.real(_settings(tmp_path), _project(tmp_path))
    assert "agl[terminal]" in str(refused.value)
