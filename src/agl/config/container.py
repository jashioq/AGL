from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from inspect import isawaitable
from pathlib import Path
from typing import Final
from agl.adapters.claude_code import fake as claude_fake
from agl.adapters.filesystem.memory_store import MemoryStore
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.fake import (
    FakeHistory,
    FakeIntegrator,
    FakeRepository,
    FakeWorkspaceProvider,
)
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.openai import fake as openai_fake
from agl.adapters.openai.runner import OpenAiRunner
from agl.adapters.rich_terminal.headless import HeadlessTerminal
from agl.adapters.rich_terminal.scripted import Press, ScriptedTerminal
from agl.adapters.routing import RoutingAgentRunner
from agl.adapters.shell.fake import FakeVerifier
from agl.adapters.shell.verifier import ShellVerifier
from agl.adapters.system_clock import ManualClock, SystemClock
from agl.adapters.uv.fake import FakeSyncer
from agl.adapters.uv.syncer import UvSyncer
from agl.config.schema import AgentSettings, Project, Settings
from agl.ports.agent import AgentOutcome, AgentRunner, Provider, ToolResult
from agl.ports.errors import UpstreamUnavailable
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.sync import Syncer
from agl.ports.terminal import Terminal
from agl.ports.tree_layout import TreesRoot
from agl.sdk._engine.services import Services
from agl.sdk.testing import Agent, Reply

__all__ = [
    "FAKE_BUILD",
    "FakeServices",
    "Press",
    "ScriptedTerminal",
    "Services",
    "answering",
    "fake_syncer",
    "fakes",
    "real",
    "real_syncer",
]

FAKE_BUILD: Final = "agl-fake-build"

@dataclass(frozen=True, slots=True)
class FakeServices:
    services: Services

    repository: FakeRepository

    store: Store

    verifier: FakeVerifier

    terminal: Terminal

    clock: ManualClock

    def with_terminal(self, terminal: Terminal) -> FakeServices:
        return replace(self, services=replace(self.services, terminal=terminal), terminal=terminal)

    def with_store(self, store: Store) -> FakeServices:
        return replace(self, services=replace(self.services, store=store), store=store)

    def with_verifier(self, verifier: FakeVerifier) -> FakeServices:
        return replace(self, services=replace(self.services, verifier=verifier), verifier=verifier)

def real(settings: Settings, project: Project) -> Services:
    return Services(
        store=FilesystemStore(settings.home),
        workspaces=GitWorkspaceProvider(project.repo, project.trees),
        history=GitHistory(project.repo),
        integrator=GitIntegrator(project.repo),
        verifier=ShellVerifier(build_timeout=project.build_timeout),
        terminal=_terminal(),
        clock=SystemClock(),
        agents=_agents(settings.agents),
        build=project.build,
    )

def fakes(
    trees: TreesRoot,
    *,
    files: Mapping[str, bytes] | None = None,
    build: str = FAKE_BUILD,
    agent: Agent | None = None,
    claude: claude_fake.Script | None = None,
    openai: openai_fake.Script | None = None,
) -> FakeServices:
    repository = FakeRepository(files)
    store = MemoryStore()
    verifier = FakeVerifier()
    terminal = HeadlessTerminal()
    clock = ManualClock()
    return FakeServices(
        services=Services(
            store=store,
            workspaces=FakeWorkspaceProvider(repository, trees),
            history=FakeHistory(repository),
            integrator=FakeIntegrator(repository),
            verifier=verifier,
            terminal=terminal,
            clock=clock,
            agents=RoutingAgentRunner(
                {
                    Provider.CLAUDE: claude_fake.FakeAgentRunner(
                        claude if claude is not None else _claude_script(agent)
                    ),
                    Provider.OPENAI: openai_fake.FakeAgentRunner(
                        openai if openai is not None else _openai_script(agent)
                    ),
                }
            ),
            build=build,
        ),
        repository=repository,
        store=store,
        verifier=verifier,
        terminal=terminal,
        clock=clock,
    )

def answering(responses: Sequence[Press | int] = ()) -> ScriptedTerminal:
    return ScriptedTerminal(responses)

# Outside both bundles, and beside `answering` for the same reason: a sync addresses the operator's
# workspace rather than a run, so there is no project, no repository and no trees root in scope -
# exactly as there is none for `agl new` or `agl workflows`.
def real_syncer() -> Syncer:
    return UvSyncer()

def fake_syncer() -> FakeSyncer:
    return FakeSyncer()

def _claude_script(agent: Agent | None) -> claude_fake.Script | None:
    if agent is None:
        return None

    async def script(conversation: claude_fake.Conversation) -> AgentOutcome:
        return await _performs(
            agent(conversation.task), call=conversation.call, report=conversation.report
        )

    return script

def _openai_script(agent: Agent | None) -> openai_fake.Script | None:
    if agent is None:
        return None

    async def script(conversation: openai_fake.Conversation) -> AgentOutcome:
        return await _performs(
            agent(conversation.task), call=conversation.call, report=conversation.report
        )

    return script

async def _performs(
    produced: Reply | Awaitable[Reply],
    *,
    call: Callable[[str, Mapping[str, JsonValue]], Awaitable[ToolResult]],
    report: Callable[[str], None],
) -> AgentOutcome:
    reply = await produced if isawaitable(produced) else produced
    for line in reply.activity:
        report(line)
    for made in reply.calls:
        await call(made.tool, made.payload)
    return AgentOutcome(stop_reason=reply.stop_reason, text=reply.says)

def _agents(agents: AgentSettings) -> AgentRunner:
    connectors: tuple[tuple[Provider, bool, Callable[[], AgentRunner]], ...] = (
        (Provider.CLAUDE, agents.claude.enabled, partial(_claude, agents.claude.cli_path)),
        (Provider.OPENAI, agents.openai.enabled, partial(OpenAiRunner, agents.openai.cli_path)),
    )
    return RoutingAgentRunner({name: build() for name, enabled, build in connectors if enabled})

def _claude(cli_path: Path | None) -> AgentRunner:
    try:
        from agl.adapters.claude_code.runner import ClaudeCodeRunner
    except ImportError as error:
        raise UpstreamUnavailable(
            "the Claude connector is enabled, but its harness cannot be loaded in this "
            "environment: the adapter needs the claude-agent-sdk package and nothing here can "
            "import it. Every install of AGL carries that package - it is a base dependency of "
            "the agents-gl distribution and not an extra anybody has to ask for - so this is an "
            "environment something was taken out of rather than one that was installed short: a "
            "`--no-deps` install, an uninstall that took it, or an image trimmed after the fact. "
            "Reinstalling the distribution puts it back - `pip install --force-reinstall "
            "agents-gl` - and so does installing claude-agent-sdk on its own. Or turn the "
            "connector off - AGL_AGENT_CLAUDE_ENABLED=false, or enabled = false under "
            "[agent.claude] in the settings file - and run a workflow whose roles name no Claude "
            "model"
        ) from error
    return ClaudeCodeRunner(cli_path)

def _terminal() -> Terminal:
    try:
        from agl.adapters.rich_terminal.terminal import RichTerminal
    except ImportError as error:
        raise UpstreamUnavailable(
            "AGL cannot build a terminal in this environment: the display adapter needs the rich "
            "package and nothing here can import it. Every install of AGL carries rich - it is a "
            "base dependency of the agents-gl distribution and not an extra anybody has to ask "
            "for - so this is an environment something was taken out of rather than one that was "
            "installed short: a `--no-deps` install, an uninstall that took it, or an image "
            "trimmed after the fact. Reinstalling the distribution puts it back - `pip install "
            "--force-reinstall agents-gl` - and so does installing rich on its own. There is no "
            "headless mode to fall back to - a workflow shows screens and some of them ask a "
            "person a question, so a run started without a display would fail at the first one "
            "instead of here"
        ) from error
    return RichTerminal()
