
import tempfile
from pathlib import Path
from typing import Final

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    McpServerConfig,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import SystemPromptPreset

from agl.adapters.claude_code._session import Stderr, outcome_of
from agl.adapters.claude_code._tools import ASKING_MECHANISMS_DENIED, Caller, servers
from agl.adapters.claude_code.translate import Restraint, model_name, restraint, unready
from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    ModelId,
)
from agl.ports.errors import InputError, InternalError, UpstreamUnavailable

__all__ = ["ClaudeCodeRunner"]

_CAPABILITIES: Final = frozenset(
    {
        Capability.FILE_EDIT,
        Capability.SHELL,
        Capability.TOOL_CALLING,
    }
)

_PRESET: Final[SystemPromptPreset] = {"type": "preset", "preset": "claude_code"}

_READY_PROMPT: Final = "Reply with the single word: ready"

_PLAN_ONLY: Final = (
    "AGL is asking you to examine and propose, and to change nothing: work out what should be "
    "done and report it, rather than doing it. This is what is being asked of you, not a "
    "restriction placed on you - anything you are actually forbidden to do is listed separately."
)

_CONTEXT_HEADING: Final = "AGL is running this task with the following standing context:"


class ClaudeCodeRunner(AgentRunner):

    def __init__(self, cli_path: Path | None = None) -> None:
        self._cli_path = None if cli_path is None else Path(_inert(str(cli_path), "cli_path"))

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        model_name(model)
        return _CAPABILITIES

    async def check_ready(self, model: ModelId) -> None:
        name = model_name(model)
        with tempfile.TemporaryDirectory(prefix="agl-ready-") as elsewhere:
            options = ClaudeAgentOptions(
                cwd=elsewhere,
                model=name,
                system_prompt="",
                tools=[],
                setting_sources=[],
                strict_mcp_config=True,
                settings=None,
                permission_mode="bypassPermissions",
                max_turns=1,
                cli_path=self._cli_path,
                stderr=Stderr(),
            )
            try:
                async for message in query(prompt=_READY_PROMPT, options=options):
                    if isinstance(message, ResultMessage) and message.is_error:
                        raise UpstreamUnavailable(
                            f"the Claude Code CLI answered a readiness check with an error "
                            f"instead of a result: {message.result or message.subtype}. A session "
                            f"that is not authenticated, an exhausted allowance and an unusable "
                            f"request all arrive this way, so the message above is what to act on"
                        )
            except ClaudeSDKError as error:
                raise unready(error) from error

    async def run(
        self,
        task: AgentTask,
        *,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        limits = restraint(task.restrictions)
        caller = Caller()
        stderr = Stderr()
        return await outcome_of(
            task,
            _prompt(task, limits),
            _options(task, limits, servers(task.tools, caller), self._cli_path, stderr),
            caller=caller,
            on_activity=on_activity,
            stderr=stderr,
        )


def _options(
    task: AgentTask,
    limits: Restraint,
    supplied: dict[str, McpServerConfig],
    cli_path: Path | None,
    stderr: Stderr,
) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=task.workspace,
        model=_inert(model_name(task.model), "model"),
        system_prompt=_PRESET,
        setting_sources=[],
        strict_mcp_config=True,
        settings=None,
        add_dirs=[],
        extra_args={},
        mcp_servers=supplied,
        disallowed_tools=_rules(limits, ASKING_MECHANISMS_DENIED),
        permission_mode="bypassPermissions",
        cli_path=cli_path,
        stderr=stderr,
    )


def _prompt(task: AgentTask, limits: Restraint) -> str:
    standing = [
        f"{_CONTEXT_HEADING}\n\n{task.context}" if task.context else "",
        limits.in_words,
        _PLAN_ONLY if task.plan_only else "",
    ]
    return "\n\n".join([*(part for part in standing if part), task.instructions])


def _inert(value: str, what: str) -> str:
    if value.startswith("-"):
        raise InputError(
            f"the Claude Code adapter will not use {value!r} as its {what}: it begins with '-', "
            f"and this value reaches the CLI as its own argument, where a leading dash makes it a "
            f"flag rather than a value. Every value reaching a command line is hostile "
            f"regardless of where it came from"
        )
    return value


def _rules(limits: Restraint, also: tuple[str, ...]) -> list[str]:
    rules = [*limits.denied_tools, *also]
    unusable = sorted(rule for rule in rules if "," in rule or rule.startswith("-"))
    if unusable:
        raise InternalError(
            f"these deny rules cannot be passed to the Claude Code CLI: {unusable}. Deny rules "
            f"are joined on commas into one argument, so a rule holding a comma becomes two rules "
            f"and a rule beginning with '-' turns the argument into a flag - either way the "
            f"restriction stops being enforced while still appearing to be"
        )
    return rules
