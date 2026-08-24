"""What `fix` puts in front of a person: one board, and one screen for answering the agent.

Two pure functions, each in its own module, re-exported here so that the workflow writes
`views.board` and `views.agent_question` - which is how §3.7 spells both of its own examples
(`term.show(views.agent_question, question=q, priority=5)`). The package is the namespace; nothing
here holds state, and nothing here is a class.

## Why a view is a function and not a value

`show` registers **the view function and its arguments**, never the `Screen` they produce. The
adapter's redraw loop invokes the registered function again every frame (~10 Hz), compares the
`Screen` it got against the last one and writes only when they differ, which is what makes
re-invocation cheap: the expensive part is the terminal write and the diff skips it. So a view is
called many times per second for as long as it is on screen, and everything below follows from
that:

* **Arguments need not be values.** `board` is given this run's own `Run` and reads `run.activity`
  out of it on every invocation, so the activity line is live with no component of its own and no
  second `show` (§3.7: "`Text(run.activity)` is live"). A workflow re-`show`s only to change
  *which* view is on screen, and `fix` shows its board once, before its first step.
* **Purity is a requirement and nothing enforces it.** No I/O, no store reads, no sorting a
  thousand items - ten times a second is forgiving, not free. Neither function below reads a clock,
  a file, or anything but its own arguments, and the fingerprint rule §3.6 places on the workflow
  ("branch only on step results") has the same shape here for the same reason.
* **Value equality is the mechanism, so nothing may be built out of anything unhashable-by-value.**
  Every component compares by value, `TextInput.maps` excepted - it is a fresh function object each
  frame and is excluded from comparison for exactly that reason. `question.py` leans on that
  exclusion, and says so where it does.

## Both views are written against `agl.sdk` alone

`Screen`, `Rows`, `Row`, `Choice`, `TextInput`, `Question`, `Answer` and `Run` all come through the
SDK's front door, in one import line per module. That is contract 6 as the author experiences it: a
workflow builds on the SDK and never learns which terminal it is drawing on, so these same two
functions produce the same values under `RichTerminal`, under `HeadlessTerminal` (which drops the
board and refuses the question), and under a `Terminal` nobody has written yet.

**No default view.** §3.7: a workflow that shows nothing renders nothing, and duplicated screens
between workflows are accepted for the same reason as duplicated prompts. Neither function here is
general, neither is reusable by `split` or by `tickets`, and neither should be - a board is a
statement about one workflow's business, and `fix`'s business is one request, one worktree and one
agent at a time.

## What is deliberately not here

**No `elapsed`, no timer and no count of steps done.** §3.7 retires `Timer` because a formatted
string re-rendered at 10 Hz is enough, so the only thing standing between this package and an
elapsed-time cell is a start time - and nothing on `Run` carries one. A view may not read a clock,
so it would have to be passed in, which means the workflow reading `time.monotonic()` before its
first step: a value that is not a step result, in a function §3.6 asks to branch only on step
results. It would be sugar bought with the one rule this workflow is written to keep.

**No "step 2 of 3".** `Run` exposes `activity` and nothing that says which step is running, so a
board that named the current step would need the workflow to maintain its own mirror of the
sequence it has just written out three lines below - bookkeeping in the workflow to make a view
sound better informed than the framework is. It is reported as a gap rather than papered over.

**Nothing rendering `terminal.pending`.** The count exists because three simultaneous questions
mean two of them wait invisibly (§3.7). `fix` runs one agent at a time in one worktree, so its
queue holds at most one question and `pending` is a map of zeroes; showing it would be this board
implying a concurrency this workflow does not have.
"""

from agl.workflows.fix.views.board import board
from agl.workflows.fix.views.question import agent_question

__all__ = ["agent_question", "board"]
