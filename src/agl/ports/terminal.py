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
    """Text shown on a :class:`Screen`."""

    value: str

@dataclass(frozen=True, slots=True, init=False)
class Row:
    """One line of cells on a :class:`Screen`."""

    cells: tuple[Text, ...]

    def __init__(self, *cells: str | Text) -> None:
        object.__setattr__(self, "cells", tuple(_coerced(cell) for cell in cells))

@dataclass(frozen=True, slots=True, init=False)
class Rows:
    """Several rows shown together, in the order given."""

    rows: tuple[Row, ...]

    def __init__(self, rows: Sequence[Row]) -> None:
        object.__setattr__(self, "rows", tuple(rows))

type Component = Text | Row | Rows

@dataclass(frozen=True, slots=True)
class Choice[T]:
    """An answer a person can pick, with the value it returns."""

    label: str

    value: T

@dataclass(frozen=True, slots=True)
class TextInput[T]:
    """An answer a person types, with the function that turns it into a value."""

    label: str

    maps: Callable[[str], T] = field(compare=False, repr=False)

type Response[T] = Choice[T] | TextInput[T]

@dataclass(frozen=True, slots=True, init=False)
class Screen[T = None]:
    """What a person is shown, and the answers they can give."""

    body: Component

    responses: tuple[Response[T], ...]

    def __init__(self, body: str | Component, responses: Sequence[Response[T]] = ()) -> None:
        object.__setattr__(self, "body", _coerced(body))
        object.__setattr__(self, "responses", tuple(responses))

def _coerced[C: Component](value: str | C) -> Text | C:
    return Text(value) if isinstance(value, str) else value

class Terminal(ABC):
    """How a workflow talks to a person."""

    @abstractmethod
    async def show[T](
        self,
        view: Callable[..., Screen[T]],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        """Show a :class:`Screen` to a person and return their answer.

        :param view: Function returning the :class:`Screen`. It runs every frame, so keep it fast
            and free of side effects.
        :param priority: A question's place in the queue; higher is shown first.
        :param params: Arguments passed to `view` every frame.
        :return: The value of the chosen answer, or `None` if the screen has no answers.
        """
        ...

    @property
    @abstractmethod
    def pending(self) -> Mapping[int, int]:
        """How many screens are waiting at each priority.

        :return: Waiting screens per priority, not counting the one on screen now.
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
