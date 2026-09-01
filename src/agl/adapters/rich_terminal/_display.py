from abc import ABC, abstractmethod
from typing import Final
from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text as RichText

__all__ = ["Display", "display_for"]

_NOTHING: Final[RenderableType] = RichText("")

class Display(ABC):
    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def write(self, frame: RenderableType | None) -> None:
        ...

    @abstractmethod
    def release(self) -> None:
        ...

    @abstractmethod
    def resume(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

class Animating(Display):
    __slots__ = ("_live",)

    def __init__(self, console: Console) -> None:
        # `Live` replaces the process-global `sys.stdout` and `sys.stderr` while it is up and only
        # `stop()` puts them back; `transient=True` would erase the region, taking the final board
        # with it.
        self._live = Live(console=console, auto_refresh=False, transient=False)

    def start(self) -> None:
        self._live.start(refresh=False)

    def write(self, frame: RenderableType | None) -> None:
        self._live.update(_NOTHING if frame is None else frame, refresh=True)

    def release(self) -> None:
        self._live.stop()

    def resume(self) -> None:
        self._live.start(refresh=False)

    def stop(self) -> None:
        self._live.stop()

class Appending(Display):
    __slots__ = ("_console",)

    def __init__(self, console: Console) -> None:
        self._console = console

    def start(self) -> None:
        ...

    def write(self, frame: RenderableType | None) -> None:
        if frame is not None:
            self._console.print(frame)

    def release(self) -> None:
        ...

    def resume(self) -> None:
        ...

    def stop(self) -> None:
        ...

def display_for(console: Console) -> Display:
    if console.is_terminal and not console.is_dumb_terminal:
        return Animating(console)
    return Appending(console)
