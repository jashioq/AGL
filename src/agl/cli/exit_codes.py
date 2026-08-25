"""Re-exports `EXIT_CODES` and `exit_code_for` from `ports/errors.py`, and decides one thing.

The one exception-to-exit-code table in the codebase is in `ports/errors.py`, beside the classes it
maps, so a class and its code cannot drift apart (§3.1). This module consumes that table and adds
nothing to it. **What to do with an exception that is not an `AglError` is this module's only
decision**, and everything below is that decision and the argument for it.

The re-export is not ceremony. `ARCHITECTURE.md` §1 admits a module to `cli/` if "it parses argv or
maps an exception to an exit code", so a reader looking for how `agl` chooses its exit status comes
here first; what they find is two names pointing straight at `ports/errors.py`, the function that
answers the question and the walk that flattens a group for it, which is a shorter answer than a
comment saying the table is elsewhere. `cli/main.py` imports these four from here and never reaches
past them.

## The decision: anything that is not an `AglError` is our bug, and exits 70

`errors.py` states the invariant this rests on - adapters translate what they catch at their
boundary, "so nothing above an adapter ever handles anything else". A `CalledProcessError`, an
`OSError` or a vendor exception arriving at the top of the CLI is therefore not a case to classify:
it is a translation that did not happen, in our code, which is exactly what `InternalError` means
and exactly what 70 tells the reader to do about it - file a bug.

It is also the answer that keeps 70 meaning one thing. `exit_code_for` already resolves an
`AglError` on an unmapped branch to `InternalError`'s code, for the same reason in the same words:
arriving at the top with no decided meaning is our bug. An untranslated exception and an unmapped
branch are the same fault seen from two sides, and giving them two numbers would ask a script to
tell apart two things nobody can act on differently.

**No number is written in this file.** The answer is read out of the same table as everything else -
`exit_code_for(InternalError)` - so "holds no table of its own" is literal rather than a promise: an
integer literal appearing here would be the second table starting, and this module's own source is
scanned for one in `tests/cli/test_exit_codes.py`.

## A `TaskGroup` hands back several answers at once, and §3.1 gives that its own rule

An `ExceptionGroup` is not an `AglError`, so the decision above would answer 70 for every one of
them - and structured concurrency is the shape the plan itself gives `split` and tickets, so that is
the normal path for every concurrent workflow rather than an edge. Without a rule an `UpstreamError`
raised inside a `split` chunk exits 70 where the identical failure in `fix` exits 6, and a
workflow's `Stop` raised inside one exits 70 where the contract promises 7. §3.1 states the rule and
it is worth quoting rather than paraphrasing: "unwrap a single-exception group and map its leaf; for
several leaves that agree, use that code; for leaves that disagree, 70, naming all of them."

**Leaves, and not children.** A `TaskGroup`'s child may open a `TaskGroup` of its own - §3.3's
`split` is written that way and tickets will be - so groups nest, and a group whose one leaf arrives
wrapped in another group is still a single-leaf group. `leaves` flattens recursively, which is what
makes "one leaf" a fact about what the run did rather than about how deeply the workflow nested its
concurrency.

**Agreement is about the resolved code, never about the class.** `UpstreamUnavailable` and
`UpstreamUnexpected` are two classes and one answer - both resolve to 6, deliberately, so that "a
caller that does not care which it was catches this and a script still sees one code" - and a group
holding one of each therefore agrees. Resolving every leaf first and comparing the *results* is what
makes that true with no second rule to keep in step with the table.

**Disagreement is 70 because 70 is honest, not because it is a fallback.** §3.1: "a run that failed
several different ways is genuinely not attributable to one code, and `InternalError` is the honest
answer rather than a guess." Taking the first leaf, or the lowest code, or the most frequent one
would be this module inventing a precedence over `ports/errors.py`'s table that nothing in the plan
supports, and a script would then branch on a number that named one of several failures for a reason
it could not see. The other half of that clause - "naming all of them" - is a message and not a
number, and a function answering with an `int` cannot print one: it surfaces on stderr, and
`cli/main.py`'s handler section argues why it is an arm of its own there rather than the arm a group
used to land in.

**A group with no leaves is not a case.** `BaseExceptionGroup` refuses an empty sequence at
construction, so there is nothing here to write a branch for and none is written - the set below
cannot be empty, and a defensive clause would be this module claiming a state that does not exist.

## Why this is a function and not a chain of `except` clauses

§3.1 makes the ordering hazard a stage-10 acceptance criterion: `Stop` descends from `AglError`, so
a handler written as `except AglError` before `except Stop` swallows a deliberate end and reports 6
or 70 where the contract promises 7. The shape below removes the hazard rather than documenting it.
A handler that catches once and asks this function branches on no class at all - resolution walks
the MRO inside `exit_code_for` - so there is no clause order to get wrong, and a workflow's own
`ReviewNotConverging(Stop)` resolves to 7 without appearing anywhere.

## `KeyboardInterrupt` gets no answer of its own, and the signature is how that is enforced

Decided, rather than left implicit: a Ctrl-C is not an outcome to report and does not belong in an
exit-code table.

An exit status is what a run *produced*. `KeyboardInterrupt` is the operator taking the process
back, and the faithful way to end on one is to die of the signal - which is what CPython already
does when nothing catches it: it restores `SIG_DFL` for `SIGINT` and re-raises, so the process is
killed by the signal rather than exiting with a number that resembles it. The two are not the same
fact even though `$?` shows 130 for both: a shell reading a child that *died of* `SIGINT` stops the
enclosing loop, and one reading a child that merely exited 130 runs the next iteration. A handler
here returning 130 would therefore make `for label in a b c; do agl run ...; done` unstoppable by
the key the user pressed to stop it.

So the parameter below is annotated `Exception`, not `BaseException`. `KeyboardInterrupt` and
`SystemExit` descend from `BaseException` precisely so that a broad handler does not catch them, and
`except BaseException as error: return exit_status(error)` in `cli/main.py` (10.4) will not
typecheck under `mypy --strict`. The decision is mechanical rather than a sentence somebody has to
remember, which is the same trade `ports/errors.py` makes when it puts the codes in data.

**The group rule inherits that enforcement whole**, which is why `leaves` is written against
`ExceptionGroup` and not against `BaseExceptionGroup`. A `TaskGroup` whose children all raised
`Exception`s hands back an `ExceptionGroup`, which is an `Exception`; one whose child took a Ctrl-C
hands back a `BaseExceptionGroup`, which is not, and which therefore cannot be passed here at all.
So a Ctrl-C in a chunk ends the process exactly as a Ctrl-C in a sequential run does - by the
interpreter's own path - rather than being flattened into a leaf and given a number.
"""

from collections.abc import Iterator

from agl.ports.errors import EXIT_CODES, AglError, InternalError, exit_code_for

__all__ = ["EXIT_CODES", "exit_code_for", "exit_status", "leaves"]


def exit_status(error: Exception) -> int:
    """The process exit status for any exception the CLI is left holding, group or not.

    An `AglError` resolves through the one table, subclasses included. Anything else is a
    translation an adapter did not perform, which is AGL's bug, which is `InternalError`'s code. A
    group is neither of those - it is several of them at once - so §3.1 gives it its own rule: the
    leaves' codes if they agree, and `InternalError`'s if they do not. The module docstring argues
    every half, and no number is typed here.

    **One shape and not two.** An exception that is not a group is a group of one as far as the set
    below can tell, so there is no clause distinguishing them and no way for the two paths to
    disagree about a leaf they both hold. The set cannot be empty - `BaseExceptionGroup` refuses an
    empty sequence at construction - so the unpacking is total rather than lucky.

    Takes `Exception` on purpose: `KeyboardInterrupt` and `SystemExit` are `BaseException` and are
    deliberately not this function's to answer for, and neither is the `BaseExceptionGroup` a Ctrl-C
    in one child makes of a `TaskGroup`'s group. See the module docstring.
    """
    agreed, *disagreeing = {_resolved(leaf) for leaf in leaves(error)}
    return exit_code_for(InternalError) if disagreeing else agreed


def leaves(error: Exception) -> Iterator[Exception]:
    """Everything `error` is actually holding: a group's leaves, flattened, or `error` itself.

    Recursive because groups nest. §3.3's `split` opens a `TaskGroup` and a chunk may open its own,
    so a leaf can arrive several groups deep and is the same leaf at every depth - which is what
    keeps "a single-exception group" a statement about the run rather than about the nesting.

    Public because "naming all of them" is the half of §3.1's group rule that is a message rather
    than a number, and `cli/main.py` is where a message is written. A second walk over there would
    be this one copied, free to disagree with it about what a leaf is on the day a nested group
    appears - and the two halves of one rule disagreeing is worse than either being wrong alone.

    `ExceptionGroup` and not `BaseExceptionGroup`: the `KeyboardInterrupt` decision, holding one
    level down. See the module docstring.
    """
    if not isinstance(error, ExceptionGroup):
        yield error
        return
    for held in error.exceptions:
        yield from leaves(held)


def _resolved(leaf: Exception) -> int:
    """One leaf's code: the one table for an `AglError`, and `InternalError`'s for anything else.

    The module's own decision, applied to something that is certainly not a group. A leaf that
    nobody translated therefore takes part in agreement exactly as a translated one does, because
    an untranslated exception is our bug whether it arrived alone or beside three siblings - and a
    leaf excused from the comparison would let a run holding one report its well-worded sibling
    instead, which is 70's whole job hidden by whichever chunk failed more legibly.
    """
    if isinstance(leaf, AglError):
        return exit_code_for(leaf)
    return exit_code_for(InternalError)
