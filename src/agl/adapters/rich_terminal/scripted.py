from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Self, cast
from agl.adapters.rich_terminal.queues import Screens, View
from agl.ports.errors import InternalError
from agl.ports.terminal import Screen, Terminal

__all__ = ["Press", "ScriptedTerminal"]

@dataclass(frozen=True, slots=True)
class Press:
    response: int = 0

    typed: str = ""

class ScriptedTerminal(Terminal):
    __slots__ = ("_open", "_screens", "_script")

    def __init__(self, responses: Sequence[Press | int] = ()) -> None:
        self._screens = Screens()
        self._script: deque[Press] = deque(_pressed(response) for response in responses)
        self._open = False

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
                "it - before it was entered, or after it was left - is AGL's own ordering rather "
                "than anything a workflow author did, and that is true of a question as much as of "
                "a dashboard: a script cannot be spent on a terminal nobody opened"
            )
        if view(**params).responses:
            answered = self._screens.queue(view, priority=priority, **params)
            self._spend()
            return await answered
        self._screens.hold(view, **params)
        return cast("T", None)

    @property
    def pending(self) -> Mapping[int, int]:
        return self._screens.pending

    def displayed(self) -> Screen[object] | None:
        registration = self._screens.displayed
        return None if registration is None else registration.screen()

    def slot(self) -> Screen[object] | None:
        slot = self._screens.slot
        return None if slot is None else slot.screen()

    @property
    def remaining(self) -> tuple[Press, ...]:
        return tuple(self._script)

    def respond(self, response: int = 0, typed: str = "") -> None:
        self._script.append(Press(response, typed))
        self._spend()

    async def __aenter__(self) -> Self:
        if self._open:
            raise InternalError(
                "this terminal is already inside its context. The framework opens a terminal once, "
                "so arriving here twice is AGL's own ordering bug - and it is refused here, where "
                "there is nothing to start twice, so that a workflow tested on a script fails it "
                "exactly where a run on a real terminal would"
            )
        self._open = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._open = False
        self._screens.close()

    def _spend(self) -> None:
        while self._script and self._screens.current is not None:
            press = self._script.popleft()
            self._screens.answer(press.response, press.typed)

def _pressed(response: Press | int) -> Press:
    return Press(response) if isinstance(response, int) else response
