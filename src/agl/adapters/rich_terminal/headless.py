
from collections.abc import Callable, Mapping
from types import MappingProxyType, TracebackType
from typing import Final, Self, cast

from agl.ports.errors import InternalError, UpstreamUnavailable
from agl.ports.terminal import Screen, Terminal

__all__ = ["HeadlessTerminal"]

_NOTHING_PENDING: Final[Mapping[int, int]] = MappingProxyType({})


class HeadlessTerminal(Terminal):

    __slots__ = ("_open",)

    def __init__(self) -> None:
        self._open = False

    async def show[T](
        self,
        view: Callable[..., Screen[T]],
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
                "a dashboard: this terminal could not have answered one either way"
            )
        if view(**params).responses:
            named = getattr(view, "__name__", repr(view))
            raise UpstreamUnavailable(
                f"the view {named} asks a question at priority {priority} and this terminal cannot "
                f"take input, so there is nobody to answer it and no display it could be put on. A "
                f"workflow that needs a person genuinely cannot run this way; there are no "
                f"timeouts anywhere on this port, so the alternative to saying so now is a step "
                f"that blocks forever and a run that looks like work for as long as anybody waits"
            )
        return cast("T", None)

    @property
    def pending(self) -> Mapping[int, int]:
        return _NOTHING_PENDING

    async def __aenter__(self) -> Self:
        if self._open:
            raise InternalError(
                "this terminal is already inside its context. The framework opens a terminal once, "
                "so arriving here twice is AGL's own ordering bug - and it is refused here, where "
                "there is nothing to start twice, so that a run on fakes fails it exactly where a "
                "run on a real terminal would"
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
