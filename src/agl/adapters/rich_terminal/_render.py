
from collections.abc import Sequence
from typing import Final

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text as RichText

from agl.ports.terminal import Choice, Component, Response, Row, Rows, Screen, Text, TextInput

__all__ = ["frame"]

_GAP: Final = (0, 2)

_TYPE_A_LINE: Final = "type a line"


def frame(screen: Screen[object]) -> RenderableType:
    body = drawn(screen.body)
    if not screen.responses:
        return body
    return Group(body, RichText(""), _offered(screen.responses), RichText(""), _prompt(screen))


def drawn(component: Component) -> RenderableType:
    match component:
        case Text():
            return RichText(component.value)
        case Row():
            return _grid([component])
        case Rows():
            return _grid(component.rows)


def _grid(rows: Sequence[Row]) -> Table:
    grid = Table.grid(padding=_GAP)
    for row in rows:
        grid.add_row(*(RichText(cell.value) for cell in row.cells))
    return grid


def _offered(responses: tuple[Response[object], ...]) -> Table:
    listing = Table.grid(padding=_GAP)
    for position, response in enumerate(responses, start=1):
        listing.add_row(RichText(f"{position}."), RichText(_label(response)))
    return listing


def _label(response: Response[object]) -> str:
    match response:
        case Choice():
            return response.label
        case TextInput():
            return f"{response.label} ({_TYPE_A_LINE})"


def _prompt(screen: Screen[object]) -> RichText:
    return RichText(f"[1-{len(screen.responses)}] and Enter:")
