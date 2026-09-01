import asyncio
import contextlib
import json
import os
import signal
from collections import deque
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Final
from agl.adapters.openai._tools import Caller
from agl.adapters.openai.translate import activity, failure, launch_failure, unreadable
from agl.ports.agent import ActivityReporter, AgentOutcome, StopReason
from agl.ports.run import JsonValue

__all__ = ["outcome_of"]

_STDERR_LINES: Final = 50

_FRAME_BYTES: Final = 8 << 20

# `create_subprocess_exec`'s own `limit=` default is 64 KiB, smaller than one frame carrying a
# build's output; a longer line is recovered rather than refused, so this costs round trips only.
_BUFFER_BYTES: Final = 1 << 20

# The agent's own subprocesses hold locks - a build daemon's pid file, a package manager's cache -
# and unlink them on being asked to stop.
_GRACE: Final = 5.0

class Tail:
    def __init__(self) -> None:
        self._lines: deque[str] = deque(maxlen=_STDERR_LINES)

    def add(self, line: str) -> None:
        self._lines.append(line.rstrip("\n"))

    def text(self) -> str:
        return "\n".join(self._lines)

class _Read:
    def __init__(self) -> None:
        self.said = ""

        self.reported: str | None = None

        self.completed = False

        self.shown = ""

async def outcome_of(
    argv: Sequence[str],
    *,
    prompt: str,
    workspace: Path,
    caller: Caller,
    on_activity: ActivityReporter | None,
) -> AgentOutcome:
    try:
        child = await asyncio.create_subprocess_exec(
            *argv,
            # All three piped and all three read: a child whose output pipe fills while nobody reads
            # it blocks forever, and a prompt larger than a pipe buffer written before anything
            # reads stdout deadlocks both.
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
            limit=_BUFFER_BYTES,
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
            if caller.failure is not None:
                break
    except BaseException:
        _signal(child, signal.SIGTERM)
        for task in aside:
            task.cancel()
        raise

    status = await _closed(child, aside, early=caller.failure is not None)
    if caller.failure is not None:
        raise caller.failure
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
    if not isinstance(payload, dict):
        return None
    said = payload.get("message")
    return said if isinstance(said, str) and said.strip() else None

async def _lines(child: asyncio.subprocess.Process) -> AsyncIterator[bytes]:
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
    stream = child.stdin
    assert stream is not None, "the child was started without a pipe on its standard input"
    try:
        stream.write(prompt.encode("utf-8"))
        await stream.drain()
    except (ConnectionError, BrokenPipeError):
        pass
    finally:
        with contextlib.suppress(ConnectionError, BrokenPipeError):
            stream.close()

async def _drain(child: asyncio.subprocess.Process, tail: Tail) -> None:
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
    if early:
        await _halt(child)
    status = await child.wait()
    for task in aside:
        task.cancel()
    await asyncio.gather(*aside, return_exceptions=True)
    return status

async def _halt(child: asyncio.subprocess.Process) -> None:
    _signal(child, signal.SIGTERM)
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(_GRACE):
            await child.wait()
    _signal(child, signal.SIGKILL)

def _signal(child: asyncio.subprocess.Process, number: int) -> None:
    if child.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(child.pid), number)
    except (ProcessLookupError, PermissionError):
        with contextlib.suppress(ProcessLookupError):
            child.send_signal(number)
