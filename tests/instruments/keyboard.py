"""A keyboard a test types on: the injectable half of `Keys`, with a queue where a tty would be.

`RichTerminal` reads keystrokes through `Keys` rather than through `sys.stdin` directly, and
`terminal.py` says why in one sentence: "a terminal whose input can only come from a tty is a
terminal no test can drive and no other front end can reuse". This is what that seam is for. It is
a **real implementation of that port**, not a stub - the terminal reads it through
`run_in_executor` exactly as it reads a person's keyboard, so a test typing on this goes through
the same parse, the same numbering, the same "take the screen to read a line" and the same worker
thread that a person's keystrokes go through.

**Why it is here rather than in the file that first needed it.** It was written for
`tests/adapters/test_rich_terminal.py` and promoted unchanged when a second caller arrived:
the mid-run question path ends at `run.terminal.show`, and a test of that path has to answer an
interactive screen, which needs somebody at a keyboard. The alternative was a second terminal
implementation living in a test - which `adapters/rich_terminal/headless.py` argues against at
length, because a hand-rolled queueing terminal would be under no contract suite and so free to
agree with nothing. Driving the real adapter through its own input port is the arrangement that
keeps `tests/contracts/terminal.py` the only thing that says what a `Terminal` does.

**It belongs to this package by the same reading `landing.py` does.** The package holds stand-ins
for things *outside* AGL that a test would otherwise have to do without: `loopback.py` stands in
for a vendor's endpoint, `landing.py` for a second process, and this for a person at a keyboard.
The two rules in `__init__.py` are satisfied trivially and it is worth saying which way: nothing
here opens a socket of any kind, and the only thing it records is what a test itself typed, so
there is no credential for it to redact.

**It owns its own bound rather than importing one.** `DEADLINE` and `TICK` below are this module's,
and a caller with waits of its own keeps its own - an instrument that read a timeout out of one of
its callers would be an instrument that belongs to that caller. Neither is a performance
assertion: a keystroke the terminal is going to read is read in microseconds, so the bound only
decides how long a *failing* test takes to say so.
"""

import asyncio
import queue
import threading
from collections.abc import Callable
from typing import Final
from agl.adapters.rich_terminal.terminal import Keys

__all__ = ["DEADLINE", "TICK", "Typing"]

DEADLINE: Final = 10.0
"""How long anything here waits before calling it a hang.

The question path has no timeouts anywhere - an unanswered question blocks its step indefinitely -
so a test that drives a question and gets it wrong hangs by design. This is what turns that into a
failure with a message on it, and it is deliberately enormous against the microseconds the wait
really takes."""

TICK: Final = 0.005
"""How often a wait looks again. Small against a redraw loop, large enough not to spin the loop
flat out."""

_POLL: Final = 0.01
"""What `read` does between looking at whether it has been stopped. Short, because
`tests/adapters/test_rich_terminal.py` measures how long a shutdown takes with a read in flight."""

class Typing(Keys):
    """A keyboard a test types on: lines in from the loop's thread, lines out on a worker thread.

    The injectable half of `Keys` doing the job it exists for - a terminal whose input could only
    come from a tty is a terminal no test can drive without one. It is a real implementation of
    that port rather than a stub: the terminal reads it through `run_in_executor` exactly as it
    reads a keyboard, so every test here goes through the same parse, the same numbering and the
    same "take the screen to read a line" that a person's keystrokes go through.

    **It polls rather than blocking outright**, for the reason `StdinKeys` does: `stop` has to end
    a read nobody is ever going to satisfy, and a `Queue.get()` with no timeout could not be
    interrupted. Ten milliseconds, because one test measures a shutdown against a read in flight.

    `given` is appended to from the worker thread and read from the event loop with no lock, which
    is sound for the one thing it is used for: `list.append` and `len` are each a single bytecode
    under the GIL, and no test does anything but wait for the count to reach a number.
    """

    __slots__ = ("_lines", "_stopped", "_waiting", "given")

    def __init__(self) -> None:
        self._lines: queue.Queue[str] = queue.Queue()
        self._stopped = threading.Event()
        self._waiting = threading.Event()
        self.given: list[str] = []

    def read(self) -> str | None:
        self._waiting.set()
        try:
            while not self._stopped.is_set():
                try:
                    line = self._lines.get(timeout=_POLL)
                except queue.Empty:
                    continue
                self.given.append(line)
                return line
            return None
        finally:
            self._waiting.clear()

    def stop(self) -> None:
        self._stopped.set()

    def enter(self, *lines: str) -> None:
        """Type some lines and carry on. They are read in the order they were typed, whenever the
        terminal gets to them - which is what a keyboard buffer does."""
        for line in lines:
            self._lines.put(line)

    async def entered(self, *lines: str) -> None:
        """Type them and wait until the terminal has taken every one.

        The count is taken **before** the lines go in, because the reader is on another thread and
        may have one of them before this coroutine gets its next line of execution - a target
        computed afterwards would be a target one line too far away, and this would wait out its
        deadline against a terminal doing everything right.
        """
        wanted = len(self.given) + len(lines)
        self.enter(*lines)
        await self._until(lambda: len(self.given) >= wanted, f"the terminal to read {lines}")

    async def waiting_for_a_key(self) -> None:
        """Wait until a read is genuinely in flight - the state a shutdown has to survive."""
        await self._until(self._waiting.is_set, "the terminal to start reading the keyboard")

    async def _until(self, ready: Callable[[], bool], what: str) -> None:
        loop = asyncio.get_running_loop()
        expires = loop.time() + DEADLINE
        while loop.time() < expires:
            if ready():
                return
            await asyncio.sleep(TICK)
        raise AssertionError(
            f"{what} was still waiting after {DEADLINE:.0f}s. This terminal reads while a question "
            f"is on screen, so nothing happening here means either that no question is up or that "
            f"the reader is not running at all. It has taken {self.given!r}"
        )
