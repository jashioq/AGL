
import asyncio
import select
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import Final, Self, cast

from rich.console import Console
from rich.text import Text as RichText

from agl.adapters.rich_terminal._display import Display, display_for
from agl.adapters.rich_terminal._render import frame
from agl.adapters.rich_terminal.queues import Registration, Screens, View
from agl.ports.errors import InternalError
from agl.ports.terminal import Screen, Terminal, Text, TextInput

__all__ = ["Keys", "RichTerminal", "StdinKeys"]

FRAMES_PER_SECOND: Final = 10.0

_POLL: Final = 0.05


class Keys(ABC):

    @abstractmethod
    def read(self) -> str | None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...


class StdinKeys(Keys):

    __slots__ = ("_stopped",)

    def __init__(self) -> None:
        self._stopped = threading.Event()

    def read(self) -> str | None:
        while not self._stopped.is_set():
            stream = sys.stdin
            try:
                ready, _, _ = select.select([stream], [], [], _POLL)
            # A closed stdin, or one replaced by something with no file descriptor. Windows lands
            # here too: its `select` cannot poll a console handle.
            except (OSError, ValueError):
                return None
            if not ready:
                continue
            typed = stream.readline()
            if not typed:
                return None
            return typed.rstrip("\r\n")
        return None

    def stop(self) -> None:
        self._stopped.set()


class RichTerminal(Terminal):

    __slots__ = (
        "_console",
        "_display",
        "_keys",
        "_open",
        "_period",
        "_reads",
        "_screens",
        "_taken",
        "_tasks",
        "_written",
    )

    def __init__(
        self,
        console: Console | None = None,
        keys: Keys | None = None,
        *,
        frames_per_second: float = FRAMES_PER_SECOND,
    ) -> None:
        self._console = Console() if console is None else console
        self._keys = StdinKeys() if keys is None else keys
        self._period = 1.0 / frames_per_second
        self._screens = Screens()
        self._display: Display = display_for(self._console)
        self._written: Screen[object] | None = None
        self._open = False
        self._taken = False
        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._reads: ThreadPoolExecutor | None = None

    @property
    def written(self) -> Screen[object] | None:
        return self._written

    async def show[T](
        self,
        view: View[T],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        if not self._open:
            raise InternalError(
                "`show` was called on a terminal that is not inside its context. The framework "
                "opens the terminal and hands the open one to a workflow, so a call from outside "
                "it - before it was entered, or after the display was handed back - is AGL's own "
                "ordering rather than anything a workflow author did"
            )
        if view(**params).responses:
            return await self._screens.queue(view, priority=priority, **params)
        self._screens.hold(view, **params)
        return cast("T", None)

    @property
    def pending(self) -> Mapping[int, int]:
        return self._screens.pending

    async def __aenter__(self) -> Self:
        if self._open:
            raise InternalError(
                "this terminal is already inside its context. Entering twice would start a second "
                "redraw loop and a second reader over the same queues, and the first pair would "
                "keep drawing after the terminal was handed back - the framework opens a terminal "
                "once, so arriving here twice is AGL's own ordering bug"
            )
        self._display.start()
        # Its own executor and not the default one: `asyncio.run` waits for the default executor's
        # threads on the way out, so a read nobody answers would hold the process open after the
        # terminal is back.
        self._reads = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agl-terminal-keys")
        self._open = True
        self._tasks = (
            asyncio.create_task(self._redrawing()),
            asyncio.create_task(self._answering()),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._open = False
        try:
            self._keys.stop()
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks = ()
            if self._reads is not None:
                self._reads.shutdown(wait=False, cancel_futures=True)
                self._reads = None
            self._screens.close()
        finally:
            self._display.stop()
            self._written = None

    async def _redrawing(self) -> None:
        while True:
            self._draw()
            await asyncio.sleep(self._period)

    def _draw(self) -> None:
        if self._taken:
            return
        registration = self._screens.displayed
        screen = None if registration is None else self._screen_of(registration)
        if screen == self._written:
            return
        self._display.write(None if screen is None else frame(screen))
        self._written = screen

    def _screen_of(self, registration: Registration) -> Screen[object]:
        try:
            return registration.screen()
        except Exception as failed:
            named = getattr(registration.view, "__name__", repr(registration.view))
            return Screen(Text(f"the view {named} could not be drawn: {failed!r}"))

    async def _answering(self) -> None:
        while True:
            if self._screens.current is None:
                await asyncio.sleep(self._period)
                continue
            line = await self._read()
            if line is None:
                return
            await self._answer(line)

    async def _answer(self, line: str) -> None:
        entry = self._screens.current
        if entry is None:
            return
        offered = self._screen_of(entry).responses
        position = _position(line, len(offered))
        if position is None:
            return
        typed = ""
        picked = offered[position]
        if isinstance(picked, TextInput):
            read = await self._typed(picked)
            if read is None:
                return
            typed = read
        if self._screens.current is entry:
            self._screens.answer(position, typed)

    async def _typed(self, field: TextInput[object]) -> str | None:
        self._taken = True
        self._display.release()
        try:
            self._console.print(RichText(f"{field.label}:"))
            return await self._read()
        finally:
            self._written = None
            self._display.resume()
            self._taken = False

    async def _read(self) -> str | None:
        reads = self._reads
        if reads is None:
            return None
        try:
            return await asyncio.get_running_loop().run_in_executor(reads, self._keys.read)
        except RuntimeError:
            return None


def _position(line: str, offered: int) -> int | None:
    picked = line.strip()
    if not picked.isdigit():
        return None
    position = int(picked) - 1
    return position if 0 <= position < offered else None
