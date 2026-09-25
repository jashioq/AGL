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
    """Text shown on a [`Screen`][agl.sdk.Screen]."""

    value: str
    """The text to show, as one string."""

@dataclass(frozen=True, slots=True, init=False)
class Row:
    """One line of cells on a [`Screen`][agl.sdk.Screen]."""

    cells: tuple[Text, ...]
    """The cells, in the order given. A plain string becomes a [`Text`][agl.sdk.Text]."""

    def __init__(self, *cells: str | Text) -> None:
        object.__setattr__(self, "cells", tuple(_coerced(cell) for cell in cells))

@dataclass(frozen=True, slots=True, init=False)
class Rows:
    """Several rows shown together, in the order given."""

    rows: tuple[Row, ...]
    """The rows to show, top to bottom."""

    def __init__(self, rows: Sequence[Row]) -> None:
        object.__setattr__(self, "rows", tuple(rows))

type Component = Text | Row | Rows
"""Anything that can stand as a [`Screen`][agl.sdk.Screen]'s body."""

@dataclass(frozen=True, slots=True)
class Choice[T]:
    """An answer picked by its number, with the value it returns."""

    label: str
    """The text shown for this answer."""

    value: T
    """What [`Terminal.show`][agl.sdk.Terminal.show] returns when this answer is picked."""

@dataclass(frozen=True, slots=True)
class TextInput[T]:
    """An answer typed as a line, with the function that turns it into a value."""

    label: str
    """The text shown for this answer, and again where its line is typed."""

    maps: Callable[[str], T] = field(compare=False, repr=False)
    """Called with the typed line; what it returns is the answer."""

type Response[T] = Choice[T] | TextInput[T]
"""One answer a [`Screen`][agl.sdk.Screen] offers."""

@dataclass(frozen=True, slots=True, init=False)
class Screen[T = None]:
    """What the terminal shows, and the answers it takes."""

    body: Component
    """What the screen shows. A plain string becomes a [`Text`][agl.sdk.Text]."""

    responses: tuple[Response[T], ...]
    """The answers on offer. With none, the screen is a board and nothing waits for an answer."""

    def __init__(self, body: str | Component, responses: Sequence[Response[T]] = ()) -> None:
        object.__setattr__(self, "body", _coerced(body))
        object.__setattr__(self, "responses", tuple(responses))

def _coerced[C: Component](value: str | C) -> Text | C:
    return Text(value) if isinstance(value, str) else value

class Terminal(ABC):
    """How a workflow shows screens and asks questions in the terminal."""

    @abstractmethod
    async def show[T](
        self,
        view: Callable[..., Screen[T]],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        """Shows a [`Screen`][agl.sdk.Screen] in the terminal and returns the answer.

        Args:
            view: The function returning the `Screen`. It runs every frame, so keep it short
                and free of side effects.
            priority: The place a question takes in the queue. The highest waiting is shown
                first, and questions at one priority in the order they were asked. If omitted, 0.
            params: The arguments passed to `view` every frame.

        Returns:
            The value of the answer given, or `None` where the screen offered none.

        Raises:
            agl.sdk.UpstreamUnavailable: A screen with answers reached a terminal that takes no
                input.
        """
        ...

    @property
    @abstractmethod
    def pending(self) -> Mapping[int, int]:
        """How many screens are waiting at each priority.

        Returns:
            The count of waiting screens at each priority, without the one on screen now.
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
