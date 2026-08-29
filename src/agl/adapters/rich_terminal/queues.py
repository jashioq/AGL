
import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from agl.ports.errors import InternalError, UpstreamUnavailable
from agl.ports.terminal import Choice, Response, Screen, TextInput

__all__ = ["Entry", "Registration", "Screens", "View"]


type View[T] = Callable[..., Screen[T]]


@dataclass(frozen=True, slots=True, eq=False)
class Registration:

    view: View[object]

    params: Mapping[str, object]

    def screen(self) -> Screen[object]:
        return self.view(**self.params)


@dataclass(frozen=True, slots=True, eq=False)
class Entry(Registration):

    priority: int

    answered: asyncio.Future[object]


class Screens:

    __slots__ = ("_queues", "_slot")

    def __init__(self) -> None:
        self._slot: Registration | None = None
        self._queues: dict[int, list[Entry]] = {}

    def hold(self, view: View[object], /, **params: object) -> None:
        self._slot = Registration(view, params)

    def queue[T](self, view: View[T], /, *, priority: int = 0, **params: object) -> Awaitable[T]:
        answered: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        entry = Entry(view, params, priority, answered)
        self._queues.setdefault(priority, []).append(entry)
        answered.add_done_callback(lambda _: self._retire(entry))
        return cast("Awaitable[T]", answered)

    @property
    def slot(self) -> Registration | None:
        return self._slot

    @property
    def current(self) -> Entry | None:
        busy = (priority for priority, entries in self._queues.items() if entries)
        busiest = max(busy, default=None)
        return None if busiest is None else self._queues[busiest][0]

    @property
    def displayed(self) -> Registration | None:
        current = self.current
        return self._slot if current is None else current

    @property
    def pending(self) -> Mapping[int, int]:
        counts = {priority: len(entries) for priority, entries in self._queues.items()}
        current = self.current
        if current is not None:
            counts[current.priority] -= 1
        return MappingProxyType(counts)

    def answer(self, response: int, typed: str = "") -> None:
        entry = self.current
        if entry is None:
            raise InternalError(
                f"answered with response {response} while no question was displayed. Only the "
                f"displayed screen can be answered and the terminal knows which one that is, "
                f"so an answer arriving with nothing to answer is AGL's own ordering rather "
                f"than anything a workflow author did"
            )
        offered = entry.screen().responses
        if not 0 <= response < len(offered):
            raise InternalError(
                f"answered with response {response} on a screen offering {len(offered)}. A "
                f"response is named by its position in the order the view offered them, and the "
                f"only thing that names one is the terminal drawing that same screen"
            )
        self._retire(entry)
        if entry.answered.done():
            return
        try:
            given = _given(offered[response], typed)
        except Exception as failed:
            entry.answered.set_exception(failed)
        else:
            entry.answered.set_result(given)

    def close(self) -> None:
        for entries in self._queues.values():
            for entry in tuple(entries):
                if not entry.answered.done():
                    entry.answered.set_exception(
                        UpstreamUnavailable(
                            "the terminal shut down with this question still waiting for an "
                            "answer, so nobody can ever give one"
                        )
                    )
            entries.clear()
        self._slot = None

    def _retire(self, entry: Entry) -> None:
        entries = self._queues.get(entry.priority)
        if entries is not None and entry in entries:
            entries.remove(entry)


def _given(chosen: Response[object], typed: str) -> object:
    match chosen:
        case Choice():
            return chosen.value
        case TextInput():
            return chosen.maps(typed)
