"""One run, from the first message off the CLI's stream to the `AgentOutcome` that answers for it.

`runner.py` decides what a session *is* - the options, the tools, the prompt - and this module
drives the one it was given. Everything below is about reading a stream: what to report while it
runs, what to keep, when to stop, and how to say why it stopped without inventing a reason.

## Why the stream is drained rather than stopped at the result

`ResultMessage` is not the last thing that can happen. The SDK yields it and *then*, if the CLI
exits non-zero, raises - and that exception is where the actionable text lives: a logged-out
session arrives as `ResultError("Claude Code returned an error result: Failed to authenticate:
OAuth session expired and could not be refreshed")`, observed against the installed CLI. A loop
that broke on the result would report that run as an ordinary outcome whose text happens to be an
error message, which is the port's `text` field carrying a failure in the one field a workflow
reads as the agent's answer.

So the result is *kept* and the loop runs on. For a string prompt the SDK ends the input as soon as
the first result arrives, so the stream ends on its own; nothing here waits for anything.

## Why a limit reached is an outcome and an error result is not

Draining has one consequence worth stating, because it is the only place this module overrides what
the SDK says. Claude Code exits non-zero for **every** error result, including the one that means
"I ran out of turns" - so `error_max_turns` would arrive as an exception and be translated into
`UpstreamUnavailable`, telling a person their backend was unreachable when in fact their agent was
stopped against its will. `ports/agent.py` settles what that is: "A backend that imposes its own
limit reports having done so through `StopReason.LIMIT` - a fact about what happened". So when the
kept result reads as `LIMIT`, this module answers with an outcome and the exception is dropped;
every other error result raises. The two are not close: one says the agent had more to say, the
other says nothing usable came back.

## Why `stop_reason` is read from three fields and may still be `None`

`ResultMessage` carries three statements about why a run ended, and they answer different
questions, so they are consulted in the order of how much each one knows:

1. **`terminal_reason`** - why the CLI's own query loop ended. The SDK documents `"completed"`,
   `"max_turns"`, `"aborted_streaming"` and `"aborted_tools"`, and says it is `None` on older CLIs
   or for a result that bypassed the loop. It is the most direct answer to the question the port
   asks, so it is asked first.
2. **`subtype`** - the CLI's classification of the result. `"error_max_turns"` is the same fact one
   layer out, and is here because a CLI that reports the limit in the subtype and nothing in
   `terminal_reason` still gets a true answer.
3. **`stop_reason`** - the *model's* own stop reason for its last turn, which is a different
   question: `"end_turn"` is the model finishing its turn, `"max_tokens"` is the model being cut
   off mid-sentence. It answers last, and only when neither of the two above recognised anything.

**Anything not in the tables below answers `None`, and that is not a gap.** `"aborted_streaming"`
and `"aborted_tools"` mean a turn was cancelled by an interrupt, which is neither of the port's two
members - the agent did not end its own turn and no limit was reached - and inventing `COMPLETED`
for it would be reporting that a cancelled run finished. `"refusal"`, `"pause_turn"`, and whatever
a later CLI adds are the same case. The port made `None` a legal answer precisely so that "this
backend did not say anything this port can read" has a spelling that is not a lie, and the contract
suite pins that a `stop_reason` may be `None` without asserting any value is true.
"""

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

from agl.adapters.claude_code._tools import Asking
from agl.adapters.claude_code.translate import activity, translated
from agl.ports.agent import ActivityReporter, AgentOutcome, AgentTask, StopReason
from agl.ports.errors import UpstreamUnavailable, UpstreamUnexpected

__all__ = ["Stderr", "outcome_of"]

# See the module docstring. Three tables rather than one, because a string means different things
# in different fields - `"completed"` is a query loop that ran to the end, and a hypothetical
# `stop_reason` of the same spelling would be a model's turn ending - and one table would have to
# pretend the three fields spoke one language.
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

# How many lines of the CLI's standard error are kept for a failure message. A bound rather than
# everything, because a chatty CLI would otherwise grow a list for the length of a run that may
# last an hour; the tail is the half that says what went wrong.
_STDERR_LINES: Final = 50


class Stderr:
    """A bounded sink for the CLI's standard error, and the reason one is installed at all.

    Without a callback the SDK does not pipe the child's standard error - it is *inherited*, so the
    CLI writes straight onto whatever AGL's own process is writing to. §3.7 has a terminal redrawing
    a screen ten times a second on that same file descriptor, and a harness's diagnostics landing
    in the middle of it is a corrupted display with no way to tell where it came from. So a sink is
    always installed, and installing one is what makes the stream a pipe.

    What is kept is then used for one thing: naming a cause when a run ends with no result at all.
    That is the case where AGL has nothing else to report and the CLI's own last words are the only
    evidence there is.
    """

    def __init__(self) -> None:
        self._lines: deque[str] = deque(maxlen=_STDERR_LINES)

    def __call__(self, line: str) -> None:
        self._lines.append(line.rstrip("\n"))

    def tail(self) -> str:
        """The last lines the CLI printed, as one string, or `""` when it printed nothing."""
        return "\n".join(self._lines)


async def outcome_of(
    task: AgentTask,
    prompt: str,
    options: ClaudeAgentOptions,
    *,
    asking: Asking,
    on_activity: ActivityReporter | None,
    stderr: Stderr,
) -> AgentOutcome:
    """Run one session to its end and answer for it. Raises only from `errors.py`.

    `prompt` is passed rather than read off `task` because `runner.py` composes it - the standing
    context and the restrictions in words go into it, and how a session is composed is that
    module's decision and not this one's.

    The loop reports activity as it goes, keeps the last thing the agent said, keeps the result,
    and stops early for exactly one reason: `asking.failure`, a question handler that raised. That
    is checked after every message rather than only at the end, because the alternative is an hour
    of agent time spent on a run whose asker has already failed - and breaking here closes the
    generator, which is what terminates the CLI.
    """
    said = ""
    reported: ResultMessage | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                said = _read(message, task, said, on_activity)
            elif isinstance(message, ResultMessage):
                reported = message
            if asking.failure is not None:
                break
    except ClaudeSDKError as error:
        limited = _limited(reported, said)
        if limited is not None:
            return limited
        raise translated(error) from error
    if asking.failure is not None:
        raise asking.failure
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
        # Belt to the exception's braces. Claude Code exits non-zero after an error result, so
        # this is normally reached through the branch above; a CLI that reported an error and
        # exited 0 would otherwise have its error text returned as the agent's answer, in the one
        # field a workflow reads as what the agent said.
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
    """Report what this message is doing, and hand back what the agent has last said.

    **Activity covers every tool call, including a subagent's; text is taken only from the top
    level.** They differ because they answer different questions. Activity is "what is happening
    right now" (§3.7), and a subagent grepping a file is as much what is happening as the parent
    doing it - the port passes the line through untouched and imposes no shape on it. `text` is
    "the agent's closing message", and a subagent's reply is a message to its parent: reading it as
    the run's answer would report a nested conversation's last line as the outcome of the step.
    `parent_tool_use_id` is what tells them apart, and it is `None` exactly at the top level.

    The activity callback is called and not guarded. The port puts the obligations on the caller -
    it must not block, and it may be called never - and says nothing about an exception out of one;
    swallowing it here would hide a broken reporter for the length of a run, and the contract suite
    makes the same choice for the same reason.
    """
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
    """The outcome for a run the backend stopped against its will, or `None` if that is not this.

    The one place this module answers where the SDK would have raised, and the module docstring
    argues it: Claude Code exits non-zero for every error result, so "it ran out of turns" and "it
    could not authenticate" arrive as the same class of exception, and only the first of the two is
    something the port has a member for. Returning here drops that exception, which is deliberate -
    a `LIMIT` outcome says everything it carried.
    """
    if reported is None or _stopped(reported) is not StopReason.LIMIT:
        return None
    return _answered(reported, said)


def _answered(reported: ResultMessage, said: str) -> AgentOutcome:
    """The result and the agent's last words, as the port's two fields.

    `result` first and the last text block second, because they are the same thing from two
    distances: `result` is what the CLI decided the run's answer was, and the text block is what
    this module watched go past. They agree in the ordinary case; where they do not, the CLI's is
    the one a person reading a transcript would call the answer. `""` when neither has anything,
    which is the port's spelling for an agent that said nothing - never `None`, which would give
    the one member that reports what an agent said a second way of saying nothing.
    """
    return AgentOutcome(stop_reason=_stopped(reported), text=reported.result or said)


def _stopped(reported: ResultMessage) -> StopReason | None:
    """Why the run ended, read off three fields in order, or `None` when none of them says.

    Written as three lookups and not as a chain of conditions so that what this adapter recognises
    is a table a reader can check against the CLI, rather than a paragraph of branches. A key that
    is present with the value `None` is a string this module *has* read and decided is neither of
    the port's two members - see the module docstring on the aborted pair - and it stops the search
    rather than falling through to a field that knows less.
    """
    for value, table in (
        (reported.terminal_reason, _TERMINAL_REASONS),
        (reported.subtype, _SUBTYPES),
        (reported.stop_reason, _STOP_REASONS),
    ):
        if value is not None and value in table:
            return table[value]
    return None
