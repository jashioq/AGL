"""The one decision `split` asks a person for: this landing will not go through - try again, or
give up on it?

§3.4 writes the call site and this is the other end of it:

    while outcome.conflicted:
        if await run.terminal.show(views.conflict, conflict=outcome.conflict,
                                   build=outcome.verdict, priority=10):

**`priority=10`, and preemption is not cosmetic.** `integrate()` holds the target's lease and the
target's step lock until the outcome settles, so every other chunk's landing is stopped behind this
screen. A conflict queued behind an agent question would stall the merge queue on something
unrelated; that is the entire justification §3.7 gives for one level of preemption, and this is the
screen it was argued for.

## The parameters are what this screen renders, and never the outcome

`conflict=outcome.conflict` and `build=outcome.verdict`: the port's `Conflict`, plus the verifier's
output when the gate is what went red. §3.4 names passing `outcome` itself as one of the two things
the obvious spelling gets wrong - `Integration` is `sdk/_engine`'s own type, so a view annotated
against it would put a private engine class in a workflow author's signature, and the two verbs on
it would be in reach of a function whose whole job is to build a value.

**Neither type is on `agl.sdk`'s front door**, so both are imported from `agl.ports`. Contract 6
permits it - it forbids `agl.adapters` and `agl.config` - but `ARCHITECTURE.md` §5's convention is
stronger than the contract, and this is the second time `split` has had to break it: `chunks.py`
reaches for `ports.ids.Namespace` and reports the same thing. Widening `sdk/__init__.py` would be a
diff outside `workflows/split/`, which is precisely what stage 18 exists to measure, so it is
reported as a missing re-export rather than paid for here.

## One screen for both kinds of conflict, not two views

A live conflict has two causes and one shape (`Integration.verdict`): the work would not combine, or
it combined and then failed the build gate. `verdict` is `None` for the first and set for the
second, nothing in the framework branches on it, and §3.4 says a workflow that wants to route them
differently reads it. This one does read it - and routes them to two *bodies*, not two views.

The reason is that the decision is identical. Both hold the lease, both are ended by the same two
verbs, and the responses below are the same two `Choice`s either way; what differs is only what a
person has to read to choose. Two functions would duplicate those responses and, worse, would put
the routing at the call site - a second `if` in `_implement` whose entire job is picking a screen,
which is presentation logic in a workflow function §3.3 says is four things and no more. The view
is the thing that knows what a person reads, so the view is where the two cases part.

## What a red gate's body has to carry, and the bound on it

`Conflict` is a tuple of paths and one line. A failed build is neither: the reason the gate said no
is minutes of build output, and `Integration.verdict`'s docstring is explicit that "a conflict
screen showing a person one sentence about a red build is a screen they cannot act on", leaving it
to the workflow to decide how much to put up. Nothing else shows it - the output is live-only, on
the outcome, and if this screen drops it nobody ever sees it.

So it is shown, from the end, bounded by `_TAIL` **characters** rather than by lines. A bound in
lines still walks the whole string to find them, and this function runs ten times a second for as
long as the screen is up: `output[-_TAIL:]` copies a constant, `splitlines()` splits a constant, and
the per-frame cost stops depending on how much a build printed. From the end because a failing
build's reason is at its end.

The heading over it is worded so that it is true whether or not anything was dropped, which matters
exactly when the log is worth reading; and the fragment of a line the slice cut through is dropped
rather than shown as a line, because half a line of a stack trace reads as a whole one.

## Value equality, with nothing excluded from it

Every component here compares by value and there is no `TextInput`, so this screen does not even
lean on `maps`' exclusion from comparison: two frames of one unchanged conflict are equal, the diff
finds nothing, and the terminal writes once. `Choice.value` is compared, and `True` and `False`
compare by value - the docstring's warning about a `T` with no `__eq__` falling back to identity and
differing every frame is one this screen cannot trip over.
"""

from typing import Final

from agl.ports.integration import Conflict
from agl.ports.verifier import VerifierOutcome
from agl.sdk import Choice, Row, Rows, Screen

__all__ = ["ABORT", "RETRY", "conflict"]

RETRY: Final = "Try landing it again"
"""The label on the `True` response - what a person picks when they have done something about it.

Named for the consequence rather than after `Integration.retry`, because a person at this screen is
choosing what happens next and not calling a method. What happens next is that the landing is
offered again from wherever the target now stands: a collision resolved by hand is concluded,
checked for containing the source and put through the build gate exactly as a first landing would
be, and one still unresolved comes back here."""

ABORT: Final = "Give up on this chunk - its branch and worktree stay"
"""The label on the `False` response, and the second clause is the whole reason it is not one word.

Giving up releases the lease and the target's step lock so the next chunk can land, and it loses
nothing: the chunk's own branch and its worktree survive until `agl clear`, and a person merges it
by hand or re-runs. A label reading only "Abort" would have somebody choose between "try again" and
what sounds like discarding an agent's work, which is not what the verb does."""

_TAIL: Final = 2_000
"""How much of a red build's output this screen keeps, in characters, counted from the end.

About a screenful and a half at any width somebody reads at. In characters rather than lines
because the point of the bound is that this function's cost stops depending on the size of the
build log, and finding the last twenty lines of a ten-megabyte one means walking ten megabytes,
ten times a second."""


def conflict(conflict: Conflict, build: VerifierOutcome | None) -> Screen[bool]:
    """What stopped the landing, and the two ways out of it.

        if await w.terminal.show(views.conflict, conflict=outcome.conflict,
                                 build=outcome.verdict, priority=10):
            await outcome.retry()
            continue

    **`Screen[bool]`, and the alternative was a two-valued type of this workflow's own.** §3.7's
    approval screen returns a `Screen[Approval]` because that workflow's answer carries a second
    thing - a flag and some feedback - and `fix`'s question screen returns the port's own `Answer`
    because it has no second thing. This is the second case: there is no note to record, no reason
    to capture, and nothing downstream reads the decision, because the branch is `retry()` or
    `abort()` and both release the lease. A `Decision` enum would be one type spelled twice, and
    §3.4's own snippet is written as `if await ...show(...)`. What a `bool` would cost is a third
    outcome, and there is no third verb: a response that returned while still holding the lease is
    the bug §3.4 names.

    **Which chunk this is about is in `conflict.summary`, not in a parameter.** With N chunks
    landing into one target, "which one is this?" is a fair question at a screen - and the
    integrator's own sentence names the source branch, which is `agl/_work/<label>/<id>`. That is
    where a person reads it. This view is not given the `Chunk`, because §3.4's rule is that the
    view takes what it renders and the id is not a thing this screen renders; a run whose summaries
    stopped naming their source would be a finding against the integrator.

    Interactive, because `responses` is non-empty - which is what the terminal dispatches on, the
    annotation being invisible at run time. So `show` queues this at its priority, displays it ahead
    of the board, and blocks this chunk's landing until somebody answers. There are no timeouts
    anywhere (§3.7), which is what makes the two responses below load-bearing: a screen that offered
    neither would hold the lease until the run was killed.

    The list is local and built fresh on every invocation, so nothing is shared between frames and
    the purity rule holds - same conflict in, equal `Screen` out, every time.
    """
    rows = [Row(conflict.summary), *(Row(path) for path in conflict.paths)]
    if build is not None:
        rows.append(Row(f"The build exited {build.status}, and its output ended like this:"))
        rows.extend(Row(line) for line in _tail(build.output))
    return Screen(Rows(rows), [Choice(RETRY, value=True), Choice(ABORT, value=False)])


def _tail(output: str) -> list[str]:
    """The end of what the build printed, as lines, bounded by `_TAIL` characters.

    Empty output is legal and ordinary - `VerifierOutcome.output` says passing builds routinely
    print nothing - and gives no rows, so a gate that failed silently shows its heading and its
    status and stops there, which is the honest thing to render for one.

    When the slice cut into the middle of a line, that first fragment is dropped: it is not a line
    the build printed, and half of one reads as a whole one. Only then, though - a cut that landed
    exactly on a line ending took no line apart, and dropping the first line there would throw away
    a whole one for nothing, which is the case a `len(kept) < len(output)` test on its own gets
    wrong.
    """
    kept = output[-_TAIL:]
    lines = kept.splitlines()
    if lines and len(kept) < len(output) and output[-_TAIL - 1] not in "\r\n":
        del lines[0]
    return lines
