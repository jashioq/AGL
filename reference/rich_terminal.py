"""The Rich-backed terminal: a live display plus a question flow.

Layer: core (impl). Where the I/O lives. Nothing pushes updates: a repaint task
calls `build()` at `1/fps`, so a `Timer` ticks because the frame is rebuilt. The
builder lives on the session, so `show` can replace it mid-flight.

A question takes the whole screen — the display stops, stdin is read on a worker
thread, the display is restored — and a lock queues concurrent askers FIFO. A
console that cannot animate gets frames printed as they change. A `build()` that
raises becomes an error frame, never a dead repaint task. Only exhausted stdin
fails a question; everything else is re-prompted or taken as free text.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from rich.console import Console
from rich.live import Live
from rich.text import Text as RichText

from agl.core.terminal.api import (
    Answer,
    Color,
    LiveSession,
    Question,
    Row,
    Rows,
    Screen,
    Terminal,
    TerminalError,
    Text,
)
from agl.core.terminal.impl.render import to_renderable
from agl.core.terminal.impl.screen import to_layout

__all__ = ["RichTerminal"]

_OTHER_LABEL = "Other… (type your answer)"

_BLANK = Screen(Rows())


def _error_screen(error: Exception) -> Screen:
    """The frame shown in place of one `build()` failed to produce."""
    message = Text(f"frame failed: {type(error).__name__}: {error}", Color.BOLD_RED)
    return Screen(Rows(Row(message)))


class RichTerminal(Terminal):
    """Paints screens with Rich and reads answers from stdin."""

    def __init__(self, console: Console | None = None, stdin: Iterator[str] | None = None) -> None:
        """`stdin` overrides `input()` with a scripted iterator, for tests."""
        self._console = console if console is not None else Console()
        self._stdin = stdin

    def live(
        self, build: Callable[[], Screen] | None = None, fps: int = 4
    ) -> AbstractAsyncContextManager[LiveSession]:
        """Repaints `build()` at `fps` for as long as the context is open.

        `fps` is checked here, not in the context body, so a bad value raises at
        the call rather than on entry.
        """
        if fps <= 0:
            raise ValueError(f"fps must be positive, got {fps}")
        return self._live(build, fps)

    @asynccontextmanager
    async def _live(
        self, build: Callable[[], Screen] | None, fps: int
    ) -> AsyncIterator[LiveSession]:
        # Not transient: the last frame of a run is worth keeping on screen.
        display = Live(console=self._console, auto_refresh=False, transient=False)
        session = _RichLiveSession(display, self._console, self._read_line, build)
        display.start(refresh=False)
        session.paint()
        repaint = asyncio.create_task(self._repaint(session, fps))
        try:
            yield session
        finally:
            repaint.cancel()
            try:
                await repaint
            except asyncio.CancelledError:
                pass
            display.stop()

    async def _repaint(self, session: "_RichLiveSession", fps: int) -> None:
        """Ticks until cancelled. `paint` handles a failing frame, so nothing else ends it."""
        interval = 1 / fps
        while True:
            await asyncio.sleep(interval)
            session.paint()

    def _read_line(self) -> str:
        """Blocking read. Always called on a worker thread."""
        if self._stdin is None:
            return input()
        try:
            return next(self._stdin)
        except StopIteration:
            raise EOFError("no more scripted input") from None


class _RichLiveSession(LiveSession):
    """A running live display, and the questions that interrupt it."""

    def __init__(
        self,
        display: Live,
        console: Console,
        read_line: Callable[[], str],
        build: Callable[[], Screen] | None = None,
    ) -> None:
        self._display = display
        self._console = console
        self._read_line = read_line
        self._build = build
        self._lock = asyncio.Lock()
        self._suspended = False
        self._last_frame = ""

    def show(self, build: Callable[[], Screen]) -> None:
        """Replaces the frame source and paints it once, so a stage change is immediate.

        A no-op while a question owns the screen; the new screen returns with it.
        """
        self._build = build
        self.paint()

    def paint(self) -> None:
        """Renders one frame, unless a question owns the screen. A failing frame is shown."""
        if self._suspended:
            return
        screen = self._frame()
        now = time.monotonic()
        if self._can_animate():
            self._display.update(to_layout(screen, now), refresh=True)
        else:
            self._print_frame(screen, now)

    def _frame(self) -> Screen:
        """The screen to paint: blank before the first `show`, else `build()`."""
        if self._build is None:
            return _BLANK
        try:
            return self._build()
        except Exception as error:  # noqa: BLE001 - a bad frame is not a dead display
            return _error_screen(error)

    def _can_animate(self) -> bool:
        """Whether Rich will actually redraw in place. Matches `Live`'s own test."""
        return self._console.is_terminal and not self._console.is_dumb_terminal

    def _print_frame(self, screen: Screen, now: float) -> None:
        """Log the frame, skipping repeats so a static screen prints once."""
        with self._console.capture() as capture:
            for region in (screen.header, screen.content, screen.footer):
                if region is not None:
                    self._console.print(to_renderable(region, now))
        frame = capture.get()
        if frame == self._last_frame:
            return
        self._last_frame = frame
        # Written straight out: re-printing it would re-render text Rich has
        # already rendered.
        self._console.file.write(frame)
        self._console.file.flush()

    async def ask(self, question: Question) -> Answer:
        """Take over the screen. Concurrent callers queue behind the lock, FIFO."""
        async with self._lock:
            self._suspended = True
            self._display.stop()
            self._console.clear()
            try:
                self._print(question)
                return await self._read_answer(question)
            finally:
                self._console.clear()
                # The question took the screen with it, so the next frame is new
                # however much it looks like the one before.
                self._last_frame = ""
                self._display.start(refresh=False)
                self._suspended = False

    def _print(self, question: Question) -> None:
        self._console.print(RichText(question.header, style="bold"))
        self._console.print(RichText(question.title))
        self._console.print()
        for number, option in enumerate(question.options, start=1):
            entry = RichText(f"  {number}. ")
            entry.append(option.label, style="bold")
            entry.append(f" — {option.description}", style="grey58")
            self._console.print(entry)
        self._console.print(RichText(f"  {self._other_number(question)}. {_OTHER_LABEL}"))
        self._console.print()

    async def _read_answer(self, question: Question) -> Answer:
        """Loops until the input means something.

        Blank input and an out-of-range number re-prompt. `isdecimal`, not
        `isdigit`, which says yes to superscripts that `int` then refuses.
        """
        while True:
            reply = await self._read()
            if not reply:
                continue
            if not reply.isdecimal():
                return Answer(reply, was_free_text=True)

            number = int(reply)
            if 1 <= number <= len(question.options):
                return Answer(question.options[number - 1].label, was_free_text=False)
            if number == self._other_number(question):
                return Answer(await self._read_free_text(), was_free_text=True)
            self._console.print(
                RichText(f"Please enter a number between 1 and {self._other_number(question)}.")
            )

    async def _read_free_text(self) -> str:
        self._console.print(RichText("Your answer:"))
        while True:
            reply = await self._read()
            if reply:
                return reply

    async def _read(self) -> str:
        """Reads one line off the event loop. Raises `TerminalError` on exhausted stdin."""
        loop = asyncio.get_running_loop()
        try:
            line = await loop.run_in_executor(None, self._read_line)
        except EOFError as error:
            raise TerminalError(
                "cannot read an answer: standard input is exhausted or closed"
            ) from error
        return line.strip()

    @staticmethod
    def _other_number(question: Question) -> int:
        return len(question.options) + 1
