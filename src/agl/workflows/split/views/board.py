"""`split`'s board: one row per chunk, and what that chunk's agent is doing right now.

§3.7's own board is a table of tickets with the activity of the child `Run` working each one, and
this is the workflow that shape was written for: N agents at once, in N worktrees, and the question
a person watching has is which of them moved. `fix`'s board argues at length why *its* two rows are
not a table - one worktree, one agent, three steps in a fixed order, so a table would be one
interesting row dressed as a fleet. This is the other side of that argument, and the row count is
`len(plan.items)` rather than a constant.

## Two cells, and it is a table without a header row

`Row(chunk.id, activity)`. The id first because it is what the planner was asked to make readable -
`chunks.py` asks for "a short slug of the work rather than a number", precisely so that
`agl/_work/<label>/<id>` and `.trees/<label>/<id>/` are legible afterwards - and the activity line
second because it is the only cell that moves.

**No header.** `Rows` has no field for one and says why: "a caller that wants one puts it first",
which here would mean `Row("chunk", "doing")` - a row indistinguishable from a chunk named `chunk`,
since nothing below this view knows one line is a heading and `Text` carries no emphasis by design.
Two cells whose first is a slug and whose second is `Edit: src/api.py` do not need labelling.

## Three things a board of N agents could show, and why none of them is here

* **`chunk.work` as a second cell.** It is the whole assignment, written for an agent that will
  never see the rest of the plan - paragraphs, not a caption. A cell holding a paragraph wrecks
  every row beside it, and shortening one here would be this view deciding how wide a cell is,
  which `ports/terminal.py` puts in `adapters/` in as many words ("Nothing here says how a cell is
  sized, how it aligns, or where the line ends"). The id is `work`'s short name already, by the
  planner's own instruction, so the cell that would carry it is the cell that is here.

* **Elapsed time, which §3.7's own example has.** That example reads `t.started_at` off
  workflow-owned data, and stage 17 recorded that neither a `Run` nor anything else in the
  framework carries a start time. Reading one off the `Chunk` is not open either: a chunk is
  planner output, journalled and replayed, and a clock reading has no business in it. What is left
  is a clock read **inside this function**, and that is the one thing a view may not do - not for
  its cost, which is trivial, but because the property purity actually buys is *equal arguments,
  equal `Screen`*, and that is what makes the redraw loop's diff a decision rather than a guess
  (`ports/terminal.py` rests `TextInput.maps`' exclusion from comparison on exactly it). So there
  is no elapsed column, and the cost is real and worth naming: a chunk stuck for twenty minutes and
  a chunk that started thirty seconds ago look the same here, and the only thing distinguishing
  them is the activity line itself.

* **Which chunks have already landed.** Nothing in this view's arguments knows: a landing is a
  local of `_implement`, and putting a "landed" cell here means the workflow keeping a mutable map
  of statuses and writing it as each child finishes. §3.7 blesses exactly that - "mutating a
  `Ticket` in place shows up for the same reason" - so it is workflow-owned state and not a
  framework gap, and it is left out because it is bookkeeping maintained by hand for a screen's
  benefit in a workflow whose whole point is that it is four things and no more (§3.3). It is the
  first thing a v1.2 of this board should grow.

**And nothing rendering `terminal.pending`.** `fix` leaves it out because its queue holds at most
one question, so the map is zeroes; here it is not - N chunks can conflict, the screens queue at
priority 10 and two of them wait invisibly while a person answers the first. Showing it would mean
handing this view `run.terminal` so it re-reads the mapping every frame, which is a third argument
to the one-line `show` this board is composed by, and a decision about a second workflow's screen
that 18.2 declined to make on `split`'s behalf. It is reported rather than invented.

## Why `runs` is the live dict, and what would be wrong with anything else

`show` registers this function and its arguments and invokes them again every frame, so
`runs[id].activity` is a fresh read ten times a second and the whole table is live with no component
of its own, no `Timer` and no second `show` (§3.7: "passing `runs` - the live dict of child Runs -
works because `runs[id].activity` is evaluated again each invocation"). A board handed a
`dict[str, str]` of activity lines would be frozen at the moment of the `show` - the moment before
the `TaskGroup` opens, when every line is `None` - and would render an empty table for the whole
run while passing every other test in this file.

`chunks` is passed by value for `fix`'s reason, and the asymmetry is not an oversight: `plan.items`
is a tuple of frozen dataclasses that came out of a journalled step and cannot change while this
board is up, so passing it says exactly that, where passing `runs` says the opposite about activity.

## The guard, and why it is here for a thing that cannot happen

`runs.get(chunk.id)` and never `runs[chunk.id]`. §3.7: "A view may be composed before every child
exists, so the workflow guards its own lookups." In `split` every key is present from the first
frame - `children` is built by comprehension over the same `plan.items` this view iterates, before
any concurrency starts - so the guard is never taken.

It is written anyway because **the guarantee is the workflow's and the view is a separate value**.
The dict comprehension is one line in a function that may be edited by someone reading §3.3's own
sketch, which builds children *inside* the tasks; the day it is, the board becomes the first thing
to run and a `KeyError` inside the redraw loop is the failure, on a frame, against a screen already
displayed, where `ports/terminal.py` says there is no caller left to hand an error to. A guard
costs a method call per row and turns that into an empty cell.

An empty cell is what it renders, which is the same cell a chunk whose agent is between steps gets.
The two are deliberately indistinguishable: a person cannot act on the difference, and inventing
"not started" would have this view assert a state the framework never reported - `fix`'s argument
for `Text(run.activity or "")`, and §3.7's own board does the same for a ticket with no run behind
it yet.

## What it costs, ten times a second

Per frame, per chunk: one `Mapping.get`, one attribute read behind a property, one `or`, and three
frozen objects (two `Text`, one `Row`); then one `Rows` and one `Screen` for the table. No I/O, no
store read, no clock, no `str` formatting, and **no sort** - the order is `plan.items`' own, which
`Chunks.items` says means nothing and is kept, and sorting it here would be both the thing §3.7's
purity rule names first and a board whose rows moved under the eye of the person reading them as
agents finished.

At the `--chunks` ceiling a person is likely to run this at, that is a few dozen small allocations
per frame, and the terminal then compares the result against the last one and writes nothing at all
unless a line moved.
"""

from collections.abc import Mapping, Sequence

from agl.sdk import Row, Rows, Run, Screen
from agl.workflows.split.chunks import Chunk

__all__ = ["board"]


def board(chunks: Sequence[Chunk], runs: Mapping[str, Run]) -> Screen:
    """The board, as a value: every chunk in the plan, and its agent's current line beside it.

        await run.terminal.show(views.board, chunks=plan.items, runs=children)

    Both arguments are already locals at that point in the workflow function, which is what
    18.1's dict comprehension buys a second time over - it is there so that every namespace is
    taken before any concurrency starts, and it is also exactly what this view is a view of.

    `Sequence` and `Mapping` rather than `tuple` and `dict`, because a view reads and this is what
    reading needs; `Run` bare is `Run[object]`, `Run` being covariant in its params type, so a
    `dict[str, Run[SplitParams]]` is accepted and this function is honest about never touching
    `params`. Annotating it `Run[SplitParams]` would close an import cycle between this package and
    the module that declares `SplitParams` beside the workflow function - `fix`'s board makes the
    same argument about `FixParams`.

    Passive, because `responses` is empty - which is what the terminal dispatches on, the
    `-> Screen` annotation being invisible at run time. So this `show` goes to the slot, replaces
    whatever was there, returns `None` immediately, and keeps updating behind every conflict screen
    this run puts up.
    """
    return Screen(Rows([Row(chunk.id, _line(runs.get(chunk.id))) for chunk in chunks]))


def _line(run: Run | None) -> str:
    """What one chunk's cell says: the adapter's current line, or nothing at all.

    Two ways to reach the empty string and one cell for both, which the module docstring argues:
    no run behind this chunk yet (impossible in `split`, guarded anyway), and a run with nothing
    in flight - between steps, before an adapter's first line, and for the whole of a step replayed
    from the journal, where nothing is running and reporting anything would be a lie.
    """
    return "" if run is None else run.activity or ""
