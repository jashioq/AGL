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
from agl.adapters.claude_code.translate import activity, last_words, translated
from agl.ports.agent import ActivityReporter, AgentOutcome, AgentTask, StopReason
from agl.ports.errors import UpstreamUnavailable, UpstreamUnexpected

__all__ = ["Stderr", "outcome_of"]

# The 2.1.277 bundle's result schema declares nineteen `terminal_reason` values, and these five are
# the ones AGL's two stop reasons answer for without inventing anything; a value missing here is
# refused in `outcome_of` rather than read off a weaker field. `budget_exhausted` is
# `--max-budget-usd` reached, a cap a caller set, which is `max_turns`'s sibling and not a failure.
_TERMINAL_REASONS: Final[dict[str, StopReason | None]] = {
    "completed": StopReason.COMPLETED,
    "max_turns": StopReason.LIMIT,
    "budget_exhausted": StopReason.LIMIT,
    "aborted_streaming": None,
    "aborted_tools": None,
}

# That schema declares five result subtypes, `success` and four `error_*`, and these two name the
# caps above. They answer only where the CLI sent no `terminal_reason` at all; the other two error
# subtypes are failures rather than caps, and `outcome_of` reports those off `is_error` instead.
_SUBTYPES: Final[dict[str, StopReason | None]] = {
    "error_max_turns": StopReason.LIMIT,
    "error_max_budget_usd": StopReason.LIMIT,
}

# `stop_reason` is the model's own, and the schema declares it a nullable string rather than an
# enum - the API's eight values, plus two the CLI writes there itself. So a value missing from this
# table is read as nothing said, where one missing from `_TERMINAL_REASONS` is refused.
_STOP_REASONS: Final[dict[str, StopReason | None]] = {
    "end_turn": StopReason.COMPLETED,
    "stop_sequence": StopReason.COMPLETED,
    "tool_use": StopReason.COMPLETED,
    "max_tokens": StopReason.LIMIT,
}

# The kind an SDK host stamps on its own prompt, and the only one the CLI honours from one. `query`
# stamps nothing, so AGL's own results arrive with no origin at all; every other kind is a turn
# something else put into this session, and `translate.CROSS_SESSION_DENIED` is what it can be
# denied the tools for.
_OWN_ORIGIN: Final = "human"

_STDERR_LINES: Final = 50

# The SDK's stderr framer flushes a partial line only once it passes `max_buffer_size`, a megabyte
# in 0.2.157, so a count of lines bounds nothing an error message can afford to carry. Characters
# are the second bound, and both are taken off the end because a CLI's fatal line is its last.
_STDERR_CHARACTERS: Final = 2_000

# Registering this callback is what makes the SDK pipe the CLI's stderr at all: with
# `options.stderr` unset, `subprocess_cli` leaves the stream on the operator's own terminal. So
# everything arriving here has been taken away from them, and every message below hands it back.
class Stderr:
    def __init__(self) -> None:
        self._lines: deque[str] = deque(maxlen=_STDERR_LINES)

    def __call__(self, line: str) -> None:
        self._lines.append(line.rstrip("\n"))

    def tail(self) -> str:
        return "\n".join(self._lines)[-_STDERR_CHARACTERS:]

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
            elif isinstance(message, ResultMessage) and not _injected(message):
                reported = message
            if caller.failure is not None:
                break
    except ClaudeSDKError as error:
        limited = _limited(reported, said)
        if limited is not None:
            return limited
        raise translated(error, stderr.tail()) from error
    if caller.failure is not None:
        raise caller.failure
    if reported is None:
        raise UpstreamUnexpected(
            f"the Claude Code CLI ran and never said how the run ended, so AGL has no outcome to "
            f"report for it. The same call would answer the same way - this is a version mismatch "
            f"or an AGL bug, not a busy backend. {last_words(stderr.tail())}"
        )
    limited = _limited(reported, said)
    if limited is not None:
        return limited
    if reported.is_error:
        raise UpstreamUnavailable(
            f"the Claude Code CLI ended the run with an error instead of a result: "
            f"{reported.result or reported.subtype}. Nothing usable came back from the far side, "
            f"so the same call may well succeed once whatever stopped it is fixed. "
            f"{last_words(stderr.tail())}"
        )
    unreadable = _unreadable_reason(reported)
    if unreadable is not None:
        raise UpstreamUnexpected(
            f"the Claude Code CLI ended the run for a reason AGL has no reading of: "
            f"{unreadable!r}. Answering with it would hand back a turn that stopped for a reason "
            f"nothing here can weigh as one the agent finished, and a step recorded on that "
            f"answer replays as work that was done. The same call would answer the same way - "
            f"this is a version mismatch or an AGL bug, not a busy backend. "
            f"{last_words(stderr.tail())}"
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
    # A reason the walk cannot read is not passed over on the way to the two weaker fields: the
    # CLI's own word for how its loop ended outranks the model's, so a turn it cut short would
    # otherwise come back under the `end_turn` the model had already reported. `outcome_of` refuses
    # it rather than this answering `None`, which is what a CLI that said nothing answers with.
    if _unreadable_reason(reported) is not None:
        return None
    for value, table in (
        (reported.terminal_reason, _TERMINAL_REASONS),
        (reported.subtype, _SUBTYPES),
        (reported.stop_reason, _STOP_REASONS),
    ):
        if value is not None and value in table:
            return table[value]
    return None

def _unreadable_reason(reported: ResultMessage) -> str | None:
    reason = reported.terminal_reason
    return reason if reason is not None and reason not in _TERMINAL_REASONS else None

# Passed over rather than refused, which is where this parts from the unreadable reason above: that
# one is this run's own answer in a word nothing can weigh, and an injected turn's result is not
# this run's answer at all. So the walk keeps the last result that *is* one, and a run holding
# nothing but injected results ends at the refusal for a CLI that never said how the run ended.
def _injected(reported: ResultMessage) -> bool:
    origin = reported.origin
    return origin is not None and origin["kind"] != _OWN_ORIGIN
