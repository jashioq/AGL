"""What a `Conflict` is made of: the files git's index holds unresolved, and the line a person
reads at a workflow's own conflict screen.

The seam 5.2 drew between `workspace.py` and `_trees.py`, and 5.3 between `history.py` and
`_changes.py`, restated for the third pair: **nothing here starts a process and nothing here asks
git anything.** What arrives is a string already read off a finished command; what leaves is the
port's own value. So both halves of a `Conflict` - the paths and the sentence - are answerable
without a repository, and `integrator.py` next door is left holding one thing, which is git's merge
state machine.

Private by its leading underscore, like `_runner.py`, `_trees.py` and `_changes.py`: it is one
program's plumbing rather than a capability anything could implement.

## The form being read, and why it is that one

`git ls-files --unmerged --full-name -z` writes one record per *stage* of every path the index
holds unresolved - up to three for one file, the state it came from and the two states being
combined - as `<mode> <object> <stage>\\t<path>`, with every record ended by a NUL. Three things
make it the right question.

It is plumbing, so nothing a person configured decides the answer. `history.py` argues that at
length for `diff-tree`, and the same argument binds here: the obvious alternative is `git diff
--name-only --diff-filter=U`, which is the porcelain a person configures for their own reading, and
a repository with `diff.external` set turns it into a program AGL has never heard of.

It reads the *index*, which is where git records that a path is unresolved. That is the same fact
`retry` acts on, so the paths a workflow is shown and the state that decides whether a landing can
be concluded are one reading rather than two that can disagree.

And `-z` means the answer needs no unescaping: a NUL is the one byte a repository path cannot hold,
where the default form quotes any path with a space or a character outside ASCII and hands the
quoting back for somebody to undo. `--full-name` fixes the spelling to repository-relative, which
is what `Conflict.paths` promises, rather than relative to wherever the command was run.

**The stages are collapsed, and the count that matters is files.** A person at a conflict screen is
being asked which of `retry` and `abort` to call, and "three entries for one file" is an index's
bookkeeping rather than an answer to that. First appearance wins, so the order is git's own, which
the port declines to promise anything about.

## The sentence is AGL's own words, not git's conflict report

`Conflict.summary` is "written for that screen and not for a log", and git's own account of a
conflicted merge is neither one line nor written for this reader: it is several, it names the
strategy, and it ends by telling the reader to fix the conflicts and commit - which is advice about
a program AGL is deliberately not asking anybody to drive. §1.3's charge was one tool's vocabulary
crossing a boundary, and a summary quoting `CONFLICT (add/add)` would carry a porcelain code
through it in prose.

So the two lead-ins below say what happened in the port's words, and they differ because the two
moments do: `land` knows which line of work would not go in, and `retry` is looking again at a
landing whose source it deliberately does not re-supply.

Three paths are named and the rest are counted. A screen row is finite, the tuple beside it carries
every path in full, and a summary that named forty files would push the one thing it is guaranteed
to say off the edge.

**Where the landing is held is in the sentence**, because it is the most useful thing this
implementation has for the person deciding: resolving a collision means opening the files, and
these are in a checkout of AGL's own that they have never had a reason to know about. An integrator
whose far side is elsewhere would put whatever it has there instead - which is exactly why the port
says `summary` is "in whatever detail this implementation has".
"""

from pathlib import Path
from typing import Final

from agl.adapters.git._runner import unreadable
from agl.ports.integration import Conflict

__all__ = ["collided", "unmerged", "unresolved"]

# What ends every record of the `-z` form, and the byte a path cannot contain. The path is the tail
# of a record, after the one tab that the mode, the object and the stage in front of it cannot hold
# - so a filename holding a tab of its own survives this parse intact.
_RECORD_END: Final = "\0"
_NAME_START: Final = "\t"

# How many paths the summary names before it counts the remainder. See the module docstring.
_NAMED: Final = 3

# What this is, in AGL's words, for the one error message that quotes what would not read.
_WHAT: Final = "a list of unresolved files"


def unmerged(listing: str) -> tuple[str, ...]:
    """`ls-files --unmerged -z` output as the paths that would not combine, each named once.

    Empty output is an empty answer rather than an error. It is a real state and the module
    docstring's neighbour argues it: a merge stopped by something the index cannot represent leaves
    a landing held with nothing unresolved in it, and `Conflict.paths` has `()` for exactly that.

    A record with no path in it is `unreadable` rather than a shorter answer, for `_changes.py`'s
    reason: a colliding file this adapter quietly dropped is a file the person resolving the
    conflict never opens.
    """
    records = listing.split(_RECORD_END)
    if records and not records[-1]:
        del records[-1]
    # A dict rather than a list, because the three stages of one path arrive as three records and
    # the port's answer is files. Insertion order is preserved, so the order is still git's.
    found: dict[str, None] = {}
    for record in records:
        _, tab, path = record.partition(_NAME_START)
        if not tab or not path:
            raise unreadable(_WHAT, listing)
        found[path] = None
    return tuple(found)


def collided(paths: tuple[str, ...], source: str, target: str, where: Path) -> Conflict:
    """What `land` reports: this line of work will not go into that one, and what stopped it.

    Both names are `Workspace.branch` values, which this module neither parses nor composes - it
    prints them, which is what the port says the framework does with one.
    """
    return _conflict(paths, f"{source} will not combine into {target}", where)


def unresolved(paths: tuple[str, ...], target: str, where: Path) -> Conflict:
    """What `retry` reports: the landing already pending still will not combine.

    The source is not named because `retry` is not given one - "the pending landing already knows
    what it was landing", and a re-supplied source would be a second chance to supply a different
    one. What the sentence names instead is the target, which is the thing the person is looking
    at.
    """
    return _conflict(paths, f"the landing {target} is holding still will not combine", where)


def _conflict(paths: tuple[str, ...], lead: str, where: Path) -> Conflict:
    """One lead-in, the files, and where to go and look. The whole of the prose.

    The no-paths branch says so rather than reading as though nothing collided: `Conflict.paths`
    is explicit that `()` means "I cannot tell you which" and never "nothing collided", and a
    summary that left the case unmentioned would be the only thing a person had, saying nothing.
    """
    if not paths:
        return Conflict(
            paths,
            f"{lead}, and git left no unresolved file to name. The landing is held in {where}",
        )
    rest = len(paths) - _NAMED
    named = ", ".join(paths[:_NAMED]) + (f" and {rest} more" if rest > 0 else "")
    return Conflict(paths, f"{lead}: {named}. The landing is held in {where}")
