"""One run: a child process, its event stream read as it arrives, and the outcome that answers.

`runner.py` decides what a session *is* - the command line, the prompt, the servers behind it - and
this module drives the one it was given. Everything below is about reading a stream: what to report
while it runs, what to keep, when to stop, and how to say why it stopped without inventing a
reason.

## The stream is consumed as it arrives, and that is a finding rather than a habit

The alternative was real and was considered: run the child to completion, read its whole standard
output at the end, and take the closing text from `--output-last-message`, which writes the agent's
final message to a file. It is rejected, for three reasons in increasing order of weight.

1. **`on_activity` is "what is happening right now"** (§3.7), and §3.7's consumer is a terminal
   redrawing itself while the work happens. A buffered stream reports every line at once, after the
   run is over. For a step that takes an hour that is not a degraded dashboard, it is a blank one.
2. **The buffer would grow with the agent's own console output.** A `command_execution` item
   carries `aggregated_output` - the whole of what the command printed - and an agent that runs a
   build runs a command that prints megabytes. Buffering means holding every one of those for the
   length of the run, to read four fields out of them.
3. **The file only carries one of the four things read here.** The stop reason, a `turn.failed`
   message, a top-level `error` and every activity line are on the stream and nowhere else, so
   `--output-last-message` would remove neither the parsing nor the reading - it would add a
   temporary directory this adapter has to own and clean up, and a second source for the one field
   both agree about.

So the stream is read line by line, the child's standard error is drained concurrently into a
bounded tail, and the prompt is written to its standard input by a third task. All three at once is
not tidiness: a child whose output pipe fills while nobody is reading it blocks forever, and a
prompt larger than a pipe buffer written before anything reads stdout deadlocks the pair of them.

## What is read, and what is deliberately ignored

Eight envelope types, of which this module acts on four. `turn.completed` is the only thing that
produces `StopReason.COMPLETED`; `turn.failed` and a top-level `error` carry the harness's own
words about a failure; `item.*` carries the typed items that become activity and closing text.
`thread.started`, and anything else, is ignored.

**Ignoring `thread.started` is a decision and not an omission.** It carries the session identity
this harness would let a person resume by hand - and `AgentOutcome` excludes vendor session
identity in writing (§1.1), AGL never resumes anything (§3.7 accepts that a crash re-runs the
step), and this framework has no log for an adapter to write one into. A value parsed into a
variable that nothing reads is worse than a value not parsed: it reads, to the next person, as
though something depended on it. The rollout is still on disk, because `runner.py` does not ask for
an ephemeral session, so a person debugging a failed run resumes the most recent one by hand
without needing a number this module could have told them.

**An unrecognised envelope or item type is ignored and never raised on.** An item kind exists in
this harness's own source that appears in neither its documentation nor this build's string pool,
so a tag from the future is a certainty rather than a hypothesis, and an adapter that raised on one
would turn a harness release into an outage. What *is* raised on is a line that is not JSON at all:
that is the harness having said something this adapter cannot read, which is `unreadable`'s case
and `UpstreamUnexpected`'s.

## Did it fail, and what do we say about it - two questions, answered by different things

`translate.failure` orders the *message*: what the stream said comes first, and the exit code is
consulted only when the stream said nothing, because 1 spans "the configuration would not load" and
"a turn ran and failed" while a `turn.failed` event carries the harness's own words.

Whether the run failed **at all** is decided the other way round: a non-zero exit is a failure even
when the stream looked healthy. That asymmetry is deliberate. The two ways of being wrong are not
symmetrical - a run reported as failed when it merely exited oddly costs a step that a person can
see and re-run, while a truncated answer returned as `COMPLETED` is a wrong result that looks like
a right one, and §3.6 then records it under a fingerprint saying nothing was amiss. So the safe
half of each question is taken from the side that can see it: the stream for what to say, the exit
status for whether to say it.
"""

import asyncio
import contextlib
import json
import os
import signal
from collections import deque
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Final

from agl.adapters.openai._tools import Asking
from agl.adapters.openai.translate import activity, failure, launch_failure, unreadable
from agl.ports.agent import ActivityReporter, AgentOutcome, StopReason
from agl.ports.run import JsonValue

__all__ = ["outcome_of"]

# How many lines of the child's standard error are kept for a failure message. A bound rather than
# everything, because a chatty harness would otherwise grow a list for the length of a run that may
# last an hour; the tail is the half that says what went wrong.
_STDERR_LINES: Final = 50

# The largest single event this module will hold in memory. One frame can carry a whole command's
# output, and a build that prints hundreds of megabytes would otherwise be buffered in full to read
# one field out of it. A frame over the cap is skipped rather than raised on - it costs at most one
# activity line, where treating it as a failure would let an agent's own console output end a run.
_FRAME_BYTES: Final = 8 << 20

# How much of the child's output is read at a time. Only a buffer size: a line longer than it is
# recovered rather than refused (`_lines`), so this decides how many round trips a large frame
# costs and nothing else. The default is 64 KiB, which is smaller than an ordinary build's output.
_BUFFER_BYTES: Final = 1 << 20

# How long a child that is being stopped early is given to tidy up before it is killed outright.
# The agent's own subprocesses hold locks - a build daemon's pid file, a package manager's cache -
# and unlink them on being asked to stop, so this margin is the difference between a workspace the
# next step can use and one that refuses until somebody deletes a lock file by hand.
_GRACE: Final = 5.0


class Tail:
    """A bounded sink for the child's standard error, and the reason one is installed at all.

    Two jobs, and the first is not diagnostic. A child's standard error must be *read* - a pipe
    nobody drains fills, and a harness that blocks writing a warning is a run that stops with no
    explanation anywhere. Inheriting the stream instead of piping it would avoid that and cost
    worse: §3.7 has a terminal redrawing a screen ten times a second on that same file descriptor,
    and a harness's diagnostics landing in the middle of it is a corrupted display with no way to
    tell where it came from.

    What is kept is then used for one thing: naming a cause when a run ends with nothing on its
    event stream to explain itself. That is the case where AGL has no other evidence at all.
    """

    def __init__(self) -> None:
        self._lines: deque[str] = deque(maxlen=_STDERR_LINES)

    def add(self, line: str) -> None:
        self._lines.append(line.rstrip("\n"))

    def text(self) -> str:
        """The last lines the child printed, as one string, or `""` when it printed nothing."""
        return "\n".join(self._lines)


class _Read:
    """What one stream said, accumulated as it went past.

    A small mutable record rather than four locals threaded through a loop, because three of the
    four are written from one branch each and read from one place at the end - which is a value
    with fields, not a fold.
    """

    def __init__(self) -> None:
        self.said = ""
        """The agent's most recent message text. The port's `""` when it never said anything."""

        self.reported: str | None = None
        """The first failure the stream explained, or `None` when it explained none.

        The first and not the last, for the reason `Asking` keeps the first exception: it is the
        one that explains why everything after it went the way it did."""

        self.completed = False
        """Whether a turn ended without an error, which is the only `COMPLETED` there is here."""

        self.shown = ""
        """The last activity line reported, so the same line is not reported twice running.

        An item can be updated many times while a command's output grows, and every update renders
        to the same sentence: a dashboard cell rewritten with what it already says is not activity,
        it is noise with a cost."""


async def outcome_of(
    argv: Sequence[str],
    *,
    prompt: str,
    workspace: Path,
    asking: Asking,
    on_activity: ActivityReporter | None,
) -> AgentOutcome:
    """Run one child to its end and answer for it. Raises only from `errors.py`.

    `prompt` is passed rather than composed here - how a session is composed is `runner.py`'s
    decision - and it goes to the child's standard input, never onto its command line. `workspace`
    is the child's working directory and is also what shortens the paths in activity lines.

    The loop stops early for exactly one reason: `asking.failure`, a question handler that raised.
    That is checked after every frame rather than only at the end, because the alternative is an
    hour of agent time spent on a run whose asker has already failed.
    """
    try:
        child = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
            limit=_BUFFER_BYTES,
            # A session of its own, so that stopping this run stops the commands the agent started
            # and not only the harness that started them. An agent's build outliving the step that
            # asked for it is a process nobody owns holding a lock nobody can find.
            start_new_session=True,
        )
    except OSError as error:
        raise launch_failure(error) from error

    tail = Tail()
    aside = (
        asyncio.create_task(_feed(child, prompt)),
        asyncio.create_task(_drain(child, tail)),
    )
    read = _Read()
    try:
        async for line in _lines(child):
            _frame(line, read, workspace, on_activity)
            if asking.failure is not None:
                break
    except BaseException:
        # Including a cancellation of whatever is running this step. There is nothing left to wait
        # for and something left to stop, so the child is signalled and this returns to the caller
        # rather than blocking a teardown on a harness that may take its time about exiting.
        _signal(child, signal.SIGTERM)
        for task in aside:
            task.cancel()
        raise

    status = await _closed(child, aside, early=asking.failure is not None)
    if asking.failure is not None:
        raise asking.failure
    if read.reported is not None or status != 0:
        raise failure(reported=read.reported, exit_code=status, stderr=tail.text())
    return AgentOutcome(
        stop_reason=StopReason.COMPLETED if read.completed else None,
        text=read.said,
    )


def _frame(
    line: bytes,
    read: _Read,
    workspace: Path,
    on_activity: ActivityReporter | None,
) -> None:
    """Read one line of the event stream into `read`, and report whatever it is doing.

    A blank line is nothing; a line that is not a JSON object is `unreadable`; anything else is
    matched on its own `type` and ignored when that is a type this adapter has never met.

    The activity callback is called and not guarded. The port puts the obligations on the caller -
    it must not block, and it may be called never - and says nothing about an exception out of one;
    swallowing it here would hide a broken reporter for the length of a run.
    """
    text = line.decode("utf-8", errors="replace").strip()
    if not text:
        return
    try:
        frame = json.loads(text)
    except ValueError:
        raise unreadable(text, "it is not JSON, and this stream is one JSON event a line") from None
    if not isinstance(frame, dict):
        raise unreadable(text, f"it is a JSON {type(frame).__name__} rather than an event object")

    kind = frame.get("type")
    if kind == "turn.completed":
        read.completed = True
    elif kind == "turn.failed":
        read.reported = read.reported or _message(frame.get("error"))
    elif kind == "error":
        read.reported = read.reported or _message(frame)
    elif kind in ("item.started", "item.updated", "item.completed"):
        _item(frame.get("item"), kind, read, workspace, on_activity)


def _item(
    item: JsonValue,
    kind: str,
    read: _Read,
    workspace: Path,
    on_activity: ActivityReporter | None,
) -> None:
    """One item frame: keep what the agent said, and report what it is doing.

    Activity is reported for an item that has **started or been updated** and not for one that has
    completed, which is `translate.activity`'s own reading of itself - it says what to show "while
    `item` is in flight", and a dashboard cell still reading `Running: ./gradlew build` after the
    build finished is telling a person something that is no longer true.

    The agent's text is taken from any frame that carries it, latest wins. An item is updated and
    then completed, so the last one seen is the whole message rather than a prefix of it.
    """
    if not isinstance(item, dict):
        return
    if item.get("type") == "agent_message":
        said = item.get("text")
        if isinstance(said, str) and said.strip():
            read.said = said
    if on_activity is None or kind == "item.completed":
        return
    line = activity(item, workspace)
    if line is not None and line != read.shown:
        read.shown = line
        on_activity(line)


def _message(payload: JsonValue) -> str | None:
    """The `message` of an error-shaped payload, or `None` when there is nothing readable in it.

    `None` rather than `""` so that a failure the stream announced without explaining falls through
    to the exit status and the standard-error tail, which is where the explanation would then be -
    `translate.failure` treats a blank message as nothing said, and this agrees with it.
    """
    if not isinstance(payload, dict):
        return None
    said = payload.get("message")
    return said if isinstance(said, str) and said.strip() else None


async def _lines(child: asyncio.subprocess.Process) -> AsyncIterator[bytes]:
    """The child's standard output, one event per line, without a long line ending the run.

    `readuntil` refuses a line longer than the stream's buffer, and a single event here can carry a
    whole command's output - so an overrun is drained and joined rather than being allowed to
    surface as an error about a limit nobody chose. Past `_FRAME_BYTES` the rest of the line is
    dropped and the frame is skipped: what is lost is an activity line, and what is bought is that
    an agent running a noisy build cannot exhaust this process's memory.
    """
    stream = child.stdout
    assert stream is not None, "the child was started without a pipe on its standard output"
    parts: list[bytes] = []
    held = 0
    while True:
        try:
            line = await stream.readuntil(b"\n")
        except asyncio.LimitOverrunError as overrun:
            chunk = await stream.readexactly(overrun.consumed)
            if held < _FRAME_BYTES:
                parts.append(chunk)
                held += len(chunk)
            continue
        except asyncio.IncompleteReadError as ending:
            if ending.partial and held < _FRAME_BYTES:
                yield b"".join([*parts, ending.partial])
            return
        if held < _FRAME_BYTES:
            yield b"".join([*parts, line])
        parts, held = [], 0


async def _feed(child: asyncio.subprocess.Process, prompt: str) -> None:
    """Write the prompt to the child's standard input and close it.

    Its own task because the prompt can be larger than a pipe buffer, and a write that blocks
    before anything is reading standard output deadlocks the two of them. Closing is what tells the
    harness the instructions are complete, so it is in a `finally`: a write that failed still has
    to end the input, or the child waits for a prompt that is never finishing.
    """
    stream = child.stdin
    assert stream is not None, "the child was started without a pipe on its standard input"
    try:
        stream.write(prompt.encode("utf-8"))
        await stream.drain()
    except (ConnectionError, BrokenPipeError):
        # The child exited before reading its prompt - a rejected command line, most likely. Its
        # own output says why, and this task has nothing to add.
        pass
    finally:
        with contextlib.suppress(ConnectionError, BrokenPipeError):
            stream.close()


async def _drain(child: asyncio.subprocess.Process, tail: Tail) -> None:
    """Keep the child's standard error moving, and keep the last of it. See `Tail`."""
    stream = child.stderr
    assert stream is not None, "the child was started without a pipe on its standard error"
    async for line in stream:
        tail.add(line.decode("utf-8", errors="replace"))


async def _closed(
    child: asyncio.subprocess.Process,
    aside: Sequence[asyncio.Task[None]],
    *,
    early: bool,
) -> int:
    """Wait for the child to be gone and the helper tasks with it, and answer with its status.

    `early` is the case where this module stopped reading first - a question handler raised - so
    the child is asked to stop, given a moment, and then made to. Otherwise the stream has already
    ended, which means the child is finishing on its own and there is nothing to signal.
    """
    if early:
        _signal(child, signal.SIGTERM)
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(_GRACE):
                await child.wait()
        _signal(child, signal.SIGKILL)
    status = await child.wait()
    for task in aside:
        task.cancel()
    await asyncio.gather(*aside, return_exceptions=True)
    return status


def _signal(child: asyncio.subprocess.Process, number: int) -> None:
    """Signal the child's whole process group, or the child alone if the group has already gone.

    The group, because the harness's own children are the agent's commands: a build started under a
    step that is being torn down keeps running, keeps holding whatever it locked, and belongs to
    nobody. `start_new_session=True` at spawn is what makes the group this run's alone, so nothing
    here can reach a process AGL did not start.

    A process that has already exited is left alone, and a group that has already gone falls back
    to the child - which by then is a status waiting to be collected, so signalling it does
    nothing and costs nothing. Neither case is an error worth reporting: what this is for is a run
    being stopped, and a run that stopped by itself needs no help.
    """
    if child.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(child.pid), number)
    except (ProcessLookupError, PermissionError):
        with contextlib.suppress(ProcessLookupError):
            child.send_signal(number)
