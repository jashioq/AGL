"""A `Screen` as something `rich` can draw, and the whole of what this package knows about layout.

`terminal.py` owns the loop, the diff and the input; `_display.py` owns the physical display. This
module owns the one step between them: a port value in, a rich renderable out, and nothing else. It
is split off because rendering is a genuinely separate idea from scheduling a redraw - the loop
never asks what a `Row` looks like, and nothing here knows a frame is drawn ten times a second.

## Mechanism lives here, and this is all of it

`ports/terminal.py` says it holds no styling, no colour, no sizes, no positions and no notion of a
screen having a size at all, because that is mechanism and mechanism lives in `adapters/`. This is
the module that sentence is about. What a `Row` does when it does not fit, how far apart two cells
sit, what a numbered response looks like: all of it is decided here and none of it is on the port.

## Workflow text is text, never markup

Every string that came from a workflow is wrapped in a `rich.text.Text` rather than handed to
`Console.print` as a `str`. Rich interprets square brackets in a bare string as style markup, so a
body reading `Edit: domain/usecase.kt [2]` would either vanish or raise, depending on whether the
bracketed word happened to name a style. A view's text is what a person wrote and never a
directive, so it arrives as a `Text` object, which rich renders literally. The same goes for the
highlighter: a bare string gets numbers and paths coloured by guesswork, and `Text`'s docstring on
the port is explicit that emphasis is not this vocabulary's to invent.

## The responses are numbered here because the input convention is numbers

`terminal.py`'s input convention is "type the number of the response and press Enter", and the
numbering a person reads has to be the numbering the terminal parses. Both come from one place -
the order the view offered them in, which is `Screen.responses`' own order and the same order
`TerminalDriver.respond` names a position by. They are 1-based on screen and 0-based in the port,
which is the one translation in this package and it is made twice, here and in the parse.

A `TextInput` is marked as one in its own line rather than being drawn as a field with a cursor in
it. There is no field: picking it is what opens the read, and until somebody picks it there is
nothing to type into. Drawing an empty box would promise an editor this terminal does not have.
"""

from collections.abc import Sequence
from typing import Final

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text as RichText

from agl.ports.terminal import Choice, Component, Response, Row, Rows, Screen, Text, TextInput

__all__ = ["frame"]

_GAP: Final = (0, 2)
"""Cell padding, as `(vertical, horizontal)`: two spaces between columns and no blank lines
between rows. A table of runs is meant to be read as a block, and the only alternative that reads
as well - a box - draws lines around data the port never said were columns."""

_TYPE_A_LINE: Final = "type a line"
"""What marks the response that opens a text read. The port's `TextInput.label` is the prompt
beside the field and is the workflow author's own words, so this is written beside it rather than
mixed into it."""


def frame(screen: Screen[object]) -> RenderableType:
    """One whole frame: the body, and - when there is one - how to answer it.

    The only entry point. `terminal.py` calls this once per write and never reaches past it, which
    is what keeps every layout decision inside this module.

    A passive screen renders as its body alone. Nothing is appended saying it cannot be answered,
    because a dashboard that announced its own passivity would put a line of terminal chatter into
    every board a workflow ever writes.
    """
    body = drawn(screen.body)
    if not screen.responses:
        return body
    return Group(body, RichText(""), _offered(screen.responses), RichText(""), _prompt(screen))


def drawn(component: Component) -> RenderableType:
    """A component as a renderable, matched exhaustively over the port's closed union.

    `match` rather than `isinstance`, for the reason `Component` is closed at all: a fourth
    component added to the port becomes a `mypy` error here - an unhandled case with no return -
    rather than a branch that silently falls through and draws nothing.
    """
    match component:
        case Text():
            return RichText(component.value)
        case Row():
            return _grid([component])
        case Rows():
            return _grid(component.rows)


def _grid(rows: Sequence[Row]) -> Table:
    """Rows as a table with no header, no box and no column spec, because a `Rows` has none.

    A `Table.grid` is rich's own name for exactly that: columns sized to their contents, separated
    by padding and nothing else. Columns come from whichever row has the most cells, which is what
    lets §3.7's board put a blank activity beside a busy one without the view padding its own rows.
    """
    grid = Table.grid(padding=_GAP)
    for row in rows:
        grid.add_row(*(RichText(cell.value) for cell in row.cells))
    return grid


def _offered(responses: tuple[Response[object], ...]) -> Table:
    """The ways to answer, numbered from one in the order the view offered them."""
    listing = Table.grid(padding=_GAP)
    for position, response in enumerate(responses, start=1):
        listing.add_row(RichText(f"{position}."), RichText(_label(response)))
    return listing


def _label(response: Response[object]) -> str:
    """What a person reads beside a number: the response's own label, and what picking it does.

    Matched over the closed `Response` union for `drawn`'s reason - a third kind of response is a
    type error here rather than a response drawn as though it were a choice.
    """
    match response:
        case Choice():
            return response.label
        case TextInput():
            return f"{response.label} ({_TYPE_A_LINE})"


def _prompt(screen: Screen[object]) -> RichText:
    """The line telling a person what to do with those numbers.

    It names the range rather than saying "pick one", because the range is the whole of what the
    parse accepts and a prompt that did not say so would leave a person guessing at a terminal that
    silently ignores everything else.
    """
    return RichText(f"[1-{len(screen.responses)}] and Enter:")
