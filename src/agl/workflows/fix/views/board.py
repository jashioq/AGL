"""`fix`'s board: what was asked for, and what the agent is doing about it right now.

Two rows, and the argument for this module is mostly an argument about what is *not* in them.

## Why it is this small

§3.7's own board is `tickets`': a table of tickets, each with the activity of the child `Run`
working it and the time since it started. That board is a table because that workflow has many
things happening at once and a person watching it needs to know which one moved. `fix` has one
worktree, one agent at a time and three steps in a fixed order, so the same shape here would be a
table with one interesting row in it, dressed to look like a fleet.

What a person watching this run actually wants to know is the two things below: **that AGL is
working on the request they typed** - because the run outlives the shell they typed it into, and a
board naming somebody else's request is the first thing they would want to catch - and **that
something is happening right now**. There is no third thing this workflow knows and the framework
does not, so there is no third row.

## The activity cell is the live one, and it is live because of the argument, not the component

`run` is this workflow's own `Run`, passed to `show` as an argument and read again on every
invocation of this function. So `run.activity` is a fresh read ten times a second and the cell
tracks the adapter's line - `Edit: src/retry.py`, `Bash: pytest -q` - with no `Timer`, no observable
wrapper and no second `show`. That is §3.7's "`Text(run.activity)` is live with no special
component", and it is the whole reason `show` registers a function and its arguments rather than a
`Screen`.

**`request` is passed by value on purpose**, and the asymmetry with `run` is not an oversight. It is
a frozen field of a frozen params object that was parsed before the run started and cannot change
while this board is up, so passing the string says exactly that, where passing `run` says the
opposite about activity. `run.params.request` is the spelling this view cannot use: `FixParams` is
declared in `agl/workflows/fix/__init__.py` beside the workflow function that imports this package
(§3.3 puts them there), so a view annotated `Run[FixParams]` would close an import cycle between the
package and its own `views/`. Typed as a plain `Run` - which is `Run[object]`, `Run` being covariant
in its params type - this function is honest about reading nothing out of `params` itself.

**An empty activity cell is the honest cell.** `run.activity` is `None` whenever nothing is running:
between steps, for the seconds before an adapter reports its first line, and for the whole of a step
that was replayed from the journal, where nothing is running by definition and reporting anything
would be a lie. `Text(run.activity or "")` is `sdk/workflow.py`'s own spelling of this and §3.7's
board does the same for a ticket with no run behind it yet. The alternative - inventing "idle", or
"waiting" - would have this view assert a state the framework never reported, on the two occasions
(a replay, and a step whose adapter says nothing) where it would be wrong.

## Passive, and that is a property of the value rather than of the call

`Screen` with no `responses` is a passive screen: it goes to the terminal's slot, replaces whatever
was there, and `show` answers `None` immediately without waiting for anybody. Nothing at run time
can see the `-> Screen` annotation - what the terminal dispatches on is whether `responses` is empty
- so the annotation and the value have to agree, and here they trivially do because this function
has no way to build a response. A board that grew one would silently start blocking the workflow at
its first `show`, which is a thing worth knowing about the port and not a thing worth guarding
against here.
"""

from agl.sdk import Row, Rows, Run, Screen

__all__ = ["board"]


def board(run: Run, request: str) -> Screen:
    """The board, as a value: the request on one row, the live activity line on the next.

        await run.terminal.show(views.board, run=run, request=run.params.request)

    Labelled rows rather than a header and a table, because two rows of two cells is not a table
    and a header row over one data row is furniture. `Rows` has no header field for that reason -
    "a caller that wants one puts it first" - and this caller does not want one.

    Called ten times a second for the life of the run. It reads two attributes and builds four
    small frozen values, which is what the purity rule asks of a view; the terminal then compares
    the result against the last frame and writes nothing at all unless the activity line moved.
    """
    return Screen(Rows([Row("request", request), Row("agent", run.activity or "")]))
