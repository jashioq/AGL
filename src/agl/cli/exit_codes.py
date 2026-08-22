"""Re-exports `EXIT_CODES` and `exit_code_for` from `ports/errors.py`, and decides one thing.

The one exception-to-exit-code table in the codebase is in `ports/errors.py`, beside the classes it
maps, so a class and its code cannot drift apart (§3.1). This module consumes that table and adds
nothing to it. **What to do with an exception that is not an `AglError` is this module's only
decision**, and everything below is that decision and the argument for it.

The re-export is not ceremony. `ARCHITECTURE.md` §6 gives `cli/` the row "it parses argv or maps an
exception to an exit code", so a reader looking for how `agl` chooses its exit status comes here
first; what they find is two names pointing straight at `ports/errors.py` and one function, which is
a shorter answer than a comment saying the table is elsewhere. `cli/main.py` imports these three
from here and never reaches past them.

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
"""

from agl.ports.errors import EXIT_CODES, AglError, InternalError, exit_code_for

__all__ = ["EXIT_CODES", "exit_code_for", "exit_status"]


def exit_status(error: Exception) -> int:
    """The process exit status for any exception the CLI is left holding.

    An `AglError` resolves through the one table, subclasses included. Anything else is a
    translation an adapter did not perform, which is AGL's bug, which is `InternalError`'s code -
    the module docstring argues both halves, and neither number is typed here.

    Takes `Exception` on purpose: `KeyboardInterrupt` and `SystemExit` are `BaseException` and are
    deliberately not this function's to answer for. See the module docstring.
    """
    if isinstance(error, AglError):
        return exit_code_for(error)
    return exit_code_for(InternalError)
