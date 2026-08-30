
from collections import deque
from typing import Final

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from agl.adapters.claude_code._tools import Caller
from agl.adapters.claude_code.translate import activity, translated
from agl.ports.agent import ActivityReporter, AgentOutcome, AgentTask, StopReason
from agl.ports.errors import UpstreamUnavailable, UpstreamUnexpected

__all__ = ["Stderr", "outcome_of"]

_TERMINAL_REASONS: Final[dict[str, StopReason | None]] = {
    "completed": StopReason.COMPLETED,
    "max_turns": StopReason.LIMIT,
    "aborted_streaming": None,
    "aborted_tools": None,
}

_SUBTYPES: Final[dict[str, StopReason | None]] = {
    "error_max_turns": StopReason.LIMIT,
}

_STOP_REASONS: Final[dict[str, StopReason | None]] = {
    "end_turn": StopReason.COMPLETED,
    "stop_sequence": StopReason.COMPLETED,
    "tool_use": StopReason.COMPLETED,
    "max_tokens": StopReason.LIMIT,
}

_STDERR_LINES: Final = 50


class Stderr:

    def __init__(self) -> None:
        self._lines: deque[str] = deque(maxlen=_STDERR_LINES)

    def __call__(self, line: str) -> None:
        self._lines.append(line.rstrip("\n"))

    def tail(self) -> str:
        return "\n".join(self._lines)


async def outcome_of(
    task: AgentTask,
    prompt: str,
    options: ClaudeAgentOptions,
    *,
    caller: Caller,
    on_activity: ActivityReporter | None,
    stderr: Stderr,
) -> AgentOutcome:
    said = ""
    reported: ResultMessage | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                said = _read(message, task, said, on_activity)
            elif isinstance(message, ResultMessage):
                reported = message
            if caller.failure is not None:
                break
    except ClaudeSDKError as error:
        limited = _limited(reported, said)
        if limited is not None:
            return limited
        raise translated(error) from error
    if caller.failure is not None:
        raise caller.failure
    if reported is None:
        raise UpstreamUnexpected(
            f"the Claude Code CLI ran and never said how the run ended, so AGL has no outcome to "
            f"report for it. The same call would answer the same way - this is a version mismatch "
            f"or an AGL bug, not a busy backend. The CLI's last words were: "
            f"{stderr.tail() or '(it printed nothing)'}"
        )
    limited = _limited(reported, said)
    if limited is not None:
        return limited
    if reported.is_error:
        raise UpstreamUnavailable(
            f"the Claude Code CLI ended the run with an error instead of a result: "
            f"{reported.result or reported.subtype}. Nothing usable came back from the far side, "
            f"so the same call may well succeed once whatever stopped it is fixed"
        )
    return _answered(reported, said)


def _read(
    message: AssistantMessage,
    task: AgentTask,
    said: str,
    on_activity: ActivityReporter | None,
) -> str:
    for block in message.content:
        if isinstance(block, ToolUseBlock):
            if on_activity is not None:
                on_activity(activity(block, task.workspace))
        elif (
            isinstance(block, TextBlock)
            and block.text.strip()
            and message.parent_tool_use_id is None
        ):
            said = block.text
    return said


def _limited(reported: ResultMessage | None, said: str) -> AgentOutcome | None:
    if reported is None or _stopped(reported) is not StopReason.LIMIT:
        return None
    return _answered(reported, said)


def _answered(reported: ResultMessage, said: str) -> AgentOutcome:
    return AgentOutcome(stop_reason=_stopped(reported), text=reported.result or said)


def _stopped(reported: ResultMessage) -> StopReason | None:
    for value, table in (
        (reported.terminal_reason, _TERMINAL_REASONS),
        (reported.subtype, _SUBTYPES),
        (reported.stop_reason, _STOP_REASONS),
    ):
        if value is not None and value in table:
            return table[value]
    return None
