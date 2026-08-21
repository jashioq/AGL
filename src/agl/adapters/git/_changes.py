""""What happened to this file", out of the letter git spells it with - and the only place in AGL
where that letter exists.

§1.3's clearest instance of a vendor's vocabulary crossing a port was `FileStatus.code: str`, which
carried git's raw status codes through the boundary so that every consumer of a changed file was
reading a status letter out of one program's output. `ChangeKind` is the type that refuses it, and a
type refuses only what nothing routes around: the refusal is worth exactly as much as the narrowness
of the place those letters are allowed to exist in. This module is that place, and it is the whole
of it - nothing above here, not `history.py` and not any port, ever sees one.

The seam between this module and `history.py` is the one 5.2 drew between `workspace.py` and
`_trees.py`, restated for this half of the package: **nothing here starts a process and nothing here
asks git anything.** What arrives is a string already read off a finished command; what leaves is
the port's own vocabulary. So the whole mapping is answerable without a repository, which is what a
table of one program's codes deserves, and the containment is something a reader checks by looking
at one import list rather than by reading a function to the end.

## The form being read, and why it is that one

`git diff-tree --name-status -z` writes one record per file - the status, then the path, then the
path it came *from* as well when the status is a pairing - with every field ended by a NUL.
`history.py` argues why the command is plumbing; what matters here is the `-z`, and it matters
because a NUL is the one byte a repository path cannot hold. So the parse below needs no unescaping
and makes no guess about where a name ends. The newline form quotes any path holding a space or a
character outside ASCII and hands the quoting back for somebody to undo, which is how a repository
with a Japanese filename in it becomes a bug in a program that never meant to have an opinion about
filenames.

## A letter this module has no meaning for is refused, never guessed

Six are mapped. `A`, `D` and `M` are the port's own three; `T` is a file whose *type* changed, a
regular file that became a symlink, which is one path present in both states with different content
behind it and so is a modification in every word the port has. `R` is the rename, the one status
carrying two paths. `C` is a copy: its destination is a file that was not there before and its
source is untouched and does not appear at all, so `ADDED` is not merely the closest answer, it is
the true one - what is lost is the provenance, and the port has no vocabulary for provenance.

Everything else raises `unreadable`, which is `UpstreamUnexpected` and says so: git answered, the
answer is not something we can act on, and the same call will answer the same way. Two of them are
worth naming.

  * **`U`, unmerged, is refused rather than mapped**, and the port is explicit about why: a file
    with an unresolved conflict in it "is not a kind of change - it is a state of an operation in
    flight", which `integration.py` reports as a `Conflict`. It also cannot arrive here, comparing
    two recorded states as this does, because an unmerged entry lives only in an index. Mapping it
    to anything would be putting the merge state machine §1.3 spent 27 methods on back into the
    answer to a question about the past.
  * **`B`, a broken pairing, and `X`** need `--break-rewrites`, which is not passed, and a git that
    says one anyway is a git this module has not been read against. A wrong `ChangeKind` is worse
    than a refusal here: it goes into a step's stored result and is read back by a workflow that has
    no way left to tell it was a guess.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from agl.adapters.git._runner import unreadable
from agl.ports.history import ChangeKind, FileChange

__all__ = ["changes"]

# What ends every field of the `-z` form, and the byte a path cannot contain. The record itself has
# no terminator of its own: how many paths follow a status is decided by the status.
_FIELD_END: Final = "\0"

# git's letter to the port's word. The module docstring argues each of the two that are not
# one-to-one, and argues the absences.
_KINDS: Final[Mapping[str, ChangeKind]] = MappingProxyType(
    {
        "A": ChangeKind.ADDED,
        "C": ChangeKind.ADDED,
        "D": ChangeKind.DELETED,
        "M": ChangeKind.MODIFIED,
        "R": ChangeKind.RENAMED,
        "T": ChangeKind.MODIFIED,
    }
)

# The two statuses whose record carries the path it came from as well as the path it is now. Both
# are pairings - one file in the old state paired with one in the new - which is the only reason a
# record here is ever three fields long.
_PAIRED: Final = frozenset("CR")

# What may follow the letter: a similarity percentage, `R100` for a file moved untouched. It is a
# heuristic's confidence in its own answer and nothing above this module has anywhere to put it, so
# it is checked for shape and dropped.
_SCORE: Final = frozenset("0123456789")

# What this is, in AGL's words, for the one error message that quotes what would not read.
_WHAT: Final = "a list of changed files"


def changes(output: str) -> tuple[FileChange, ...]:
    """`--name-status -z` output as the port's own answer. The whole of the vendor containment.

    A tuple because `changed_files` promises one, and in git's order because the port declines to
    promise any - "consumers filter and count, and a port that promised an ordering would be
    promising one tool's sort".

    Empty output is an empty answer rather than an error, which is the case two identical states
    produce and which the port is explicit is not an error anywhere in this plan.

    Every field is read positionally out of one flat stream, because that is what the stream is:
    the trailing NUL that ends the last field is dropped first, and after that a status says how
    many paths belong to it. A stream that runs out mid-record, or that holds an empty field where
    a name belongs, is `unreadable` rather than a shorter answer - a changed file this adapter
    quietly dropped is a file a review step never sees.
    """
    fields = output.split(_FIELD_END)
    if fields and not fields[-1]:
        del fields[-1]
    found: list[FileChange] = []
    index = 0
    while index < len(fields):
        code = fields[index]
        kind = _kind(code, output)
        names = 2 if code[:1] in _PAIRED else 1
        if len(fields) - index <= names:
            raise unreadable(_WHAT, output)
        came_from, path = fields[index + 1], fields[index + names]
        if not came_from or not path:
            raise unreadable(_WHAT, output)
        # `previous_path` is paired to `RENAMED` in both directions by `FileChange.__post_init__`,
        # so a copy - which arrives in the same three-field shape - must hand back `None` and lose
        # the name it was copied from. That is the port's rule and not a limit of this parse.
        found.append(FileChange(path, kind, came_from if kind is ChangeKind.RENAMED else None))
        index += 1 + names
    return tuple(found)


def _kind(code: str, output: str) -> ChangeKind:
    """One status field as a `ChangeKind`, or the error for a letter this module has no word for.

    The score is validated rather than ignored: `R100` is a status and `Rabc` is this module having
    misread where a record begins, which is worth catching at the field it went wrong in rather
    than three files later when a path turns up where a letter should be.

    `output` is carried in only so that the message quotes what would not read. It is the whole
    answer rather than the field, because a parse that lost its place says nothing useful about the
    field it stopped on.
    """
    kind = _KINDS.get(code[:1])
    if kind is None or not _SCORE.issuperset(code[1:]):
        raise unreadable(_WHAT, output)
    return kind
