
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

__all__ = [
    "Choice",
    "Component",
    "Response",
    "Row",
    "Rows",
    "Screen",
    "Terminal",
    "Text",
    "TextInput",
]


@dataclass(frozen=True, slots=True)
class Text:

    value: str


@dataclass(frozen=True, slots=True, init=False)
class Row:

    cells: tuple[Text, ...]

    def __init__(self, *cells: str | Text) -> None:
        object.__setattr__(self, "cells", tuple(_coerced(cell) for cell in cells))


@dataclass(frozen=True, slots=True, init=False)
class Rows:

    rows: tuple[Row, ...]

    def __init__(self, rows: Sequence[Row]) -> None:
        object.__setattr__(self, "rows", tuple(rows))


type Component = Text | Row | Rows


@dataclass(frozen=True, slots=True)
class Choice[T]:

    label: str

    value: T


@dataclass(frozen=True, slots=True)
class TextInput[T]:

    label: str

    maps: Callable[[str], T] = field(compare=False, repr=False)


type Response[T] = Choice[T] | TextInput[T]


@dataclass(frozen=True, slots=True, init=False)
class Screen[T = None]:

    body: Component

    responses: tuple[Response[T], ...]

    def __init__(self, body: str | Component, responses: Sequence[Response[T]] = ()) -> None:
        object.__setattr__(self, "body", _coerced(body))
        object.__setattr__(self, "responses", tuple(responses))


def _coerced[C: Component](value: str | C) -> Text | C:
    return Text(value) if isinstance(value, str) else value


class Terminal(ABC):

    @abstractmethod
    async def show[T](
        self,
        view: Callable[..., Screen[T]],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        """Put what `view` returns in front of a person, and hand back what they answered.

        :param view: re-invoked every frame, so it must be pure and cheap; not the `Screen` itself
        :param priority: where an interactive screen joins the queue; no meaning for a passive one
        :param params: handed to `view` unchanged on every invocation, so live objects stay live
        :return: what the chosen response mapped to, or `None` where the screen carries none
        """
        ...

    @property
    @abstractmethod
    def pending(self) -> Mapping[int, int]:
        """How many screens are queued at each priority, excluding whatever is on screen now.

        :return: a snapshot keyed by every priority asked for, carrying a zero where none waits
        """
        ...

    @abstractmethod
    async def __aenter__(self) -> Self:
        ...

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        ...
