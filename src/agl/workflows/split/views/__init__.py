"""What `split` puts in front of a person: a live board over N chunks, and one decision per landing.

Two pure functions, each in its own module, re-exported here so that the workflow writes
`views.board` and `views.conflict` - which is how §3.7 and §3.4 spell their own examples
(`term.show(views.conflict, conflict=out.conflict, priority=10)`). The package is the namespace;
nothing here holds state, and nothing here is a class.

## Why a view is a function and not a value

`show` registers **the view function and its arguments**, never the `Screen` they produce. The
adapter's redraw loop invokes the registered function again every frame (~10 Hz), compares the
`Screen` it got against the last one and writes only when they differ, which is what makes
re-invocation cheap: the expensive part is the terminal write, and the diff skips it. So a view is
called many times a second for as long as it is on screen, and everything below follows from that:

* **Arguments need not be values.** `board` is handed the workflow's own `dict[str, Run]` of
  children and reads `runs[id].activity` out of it on every invocation, so N activity lines are
  live with no component of their own and no second `show` (§3.7: "passing `runs` - the live dict
  of child Runs - works because `runs[id].activity` is evaluated again each invocation"). This is
  the workflow that argument was written about, and `board.py` says what a board handed values
  instead would look like: an empty table, for the whole run, passing every other test.
* **Purity is a requirement and nothing enforces it.** No I/O, no store reads, no sorting a
  thousand items - ten times a second is forgiving, not free. Neither function below reads a clock,
  a file, or anything but its own arguments, and `board.py` spends a paragraph on the elapsed-time
  column that requirement costs this workflow.
* **Value equality is the mechanism.** Every component compares by value, `TextInput.maps`
  excepted. Neither screen here has a `TextInput`, so neither leans on that exclusion: two frames
  of an unchanged board or an unchanged conflict are equal outright.

## What each of them is for

* **`board`** - the run's chunks, one row each, and what that chunk's agent is doing right now.
  Passive, shown once before the `TaskGroup` opens, and it keeps updating behind every conflict
  screen this run puts up. Unlike `fix`'s board it has a genuine table to draw: N chunks is N rows,
  and which of them moved is the question a person watching this run actually has.
* **`conflict`** - what stopped a landing, and the one thing this workflow asks a human. Shown at
  `priority=10`, because `integrate()` holds the target's lease and step lock while a conflict is
  unresolved, so every other chunk's landing is stopped behind this screen. It renders both kinds
  of conflict - the work would not combine, or it combined and failed the build gate - and
  `conflict.py` argues why that is one view with two bodies rather than two views.

## Where these two are written against, and the one place that is not the SDK

`Screen`, `Rows`, `Row`, `Choice` and `Run` come through the SDK's front door. `Conflict` and
`VerifierOutcome` do not: they are not on `agl.sdk`, so `conflict.py` imports them from
`agl.ports`, which contract 6 permits and `ARCHITECTURE.md` §5's stronger convention does not
like. That is the same tripwire `chunks.py` reports for `Namespace`, firing a second time, and it
is reported as a missing re-export rather than closed here - widening `sdk/__init__.py` is a diff
outside this package, which is exactly what stage 18 measures.

**No default view.** §3.7: a workflow that shows nothing renders nothing, and duplicated screens
between workflows are accepted for the same reason as duplicated prompts. Neither function here is
general and neither is reusable by `fix` or by `tickets` - a board is a statement about one
workflow's business, and `split`'s business is N chunks cut from one commit landing one at a time.
"""

from agl.workflows.split.views.board import board
from agl.workflows.split.views.conflict import conflict

__all__ = ["board", "conflict"]
