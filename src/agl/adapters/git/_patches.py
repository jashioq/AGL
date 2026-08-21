""""What changed" between two recorded states: the port's own vocabulary, and the patch beside it.

`_changes.py` is this module's counterpart on the real side, and the two are the same shape of
thing at opposite ends of a boundary: that one turns one program's status letters into
`ChangeKind`, and this one produces the same answer out of two trees, with no letter anywhere in
between. The seam is the one that module draws - **nothing here starts a process, touches the
filesystem or holds state** - so both halves of `History`'s "what changed" are a pure function of
two mappings, which is what a question about the past deserves to be.

## Renames are detected, and only where detection is not a guess

5.3 chose detection, and gave two reasons that bind here rather than being git's: `ChangeKind
.RENAMED` and `FileChange.previous_path` would otherwise be vocabulary only a fake could speak,
and `changed_files` and `diff` must not describe two different changes. A fake that never renamed
would be the first of those failures with the sides swapped, which is worse - it is the real
adapter's answer the framework runs against.

**A move is detected when the contents are identical and not otherwise**, and that is the whole
rule. The alternative is a similarity threshold, and a threshold here would be a second heuristic
sitting beside git's own fifty percent, agreeing with it in the easy cases and disagreeing near
the boundary - which is a divergence that moves depending on the file. One that fires only on
certainty diverges in one direction, in a band that can be stated: a file moved *and edited* is
one rename here and two changes there. `test_git_parity.py` pins both ends of that band - a
byte-identical move is a `RENAMED` from both, a move that rewrites past git's fifty percent is the
`DELETED` and `ADDED` pair from both - and pins the band between them as a divergence.

A copy is not a rename in either implementation, and for one reason: the source is still there, so
it is not among the paths that went away, and nothing pairs with it. git says the same by not
being asked for `--find-copies`.

## The patch is a unified patch, and its format is nobody's contract

§3.7's argument is that a unified patch is the one interchange format every code-review consumer
already reads, and that handing it over untouched costs nothing. There is nothing to hand over
untouched here - no program printed one - so it is written, in the spelling git writes, because
that is the spelling a model has seen an enormous amount of. What the port promises about it is
only that it is text, that it is empty when nothing differs, and that it names every path
`changed_files` named; everything past that is format, and format is not this port's to invent.

Bytes that are not text get git's own one-line answer rather than a patch, and a file whose bytes
are not valid UTF-8 is decoded with replacements: this is the half a person reads, and a lossy
rendering of a file nobody can read anyway is better than an exception out of a member whose whole
job is to produce something to look at.
"""

from difflib import unified_diff
from typing import Final

from agl.adapters.git._snapshots import Tree
from agl.ports.history import ChangeKind, FileChange

__all__ = ["differences", "patch"]

# What makes a file not text, and the same rule `_merging.py` uses for the same reason.
_NOT_TEXT: Final = b"\0"

# How git spells the two sides of a change, and the name it gives to a side that is not there.
_BEFORE: Final = "a/"
_AFTER: Final = "b/"
_ABSENT: Final = "/dev/null"

_ENCODING: Final = "utf-8"
_UNREADABLE: Final = "replace"


def differences(before: Tree, after: Tree) -> tuple[FileChange, ...]:
    """Which files differ between two states, and how. Directional, `before` to `after`.

    Sorted by path, which the port declines to promise and this module therefore owes nobody -
    it is here because a deterministic answer is one a test can compare whole, and because the
    alternative is an order that depends on dict insertion and so on the order files were written.
    """
    arrived = sorted(path for path in after if path not in before)
    gone = sorted(path for path in before if path not in after)
    edited = sorted(path for path in before if path in after and before[path] != after[path])
    moves = _moves(before, after, arrived, gone)
    found = [
        FileChange(path, ChangeKind.RENAMED, moves[path]) for path in arrived if path in moves
    ]
    found += [FileChange(path, ChangeKind.ADDED) for path in arrived if path not in moves]
    found += [FileChange(path, ChangeKind.DELETED) for path in gone if path not in moves.values()]
    found += [FileChange(path, ChangeKind.MODIFIED) for path in edited]
    return tuple(sorted(found, key=lambda change: change.path))


def patch(before: Tree, after: Tree) -> str:
    """The same difference as a unified patch. Empty when the two states are the same.

    Built from `differences` rather than from the two trees directly, so that the two members
    cannot describe two different changes: a move is one rename in both answers or two changes in
    both, and there is no second reading of the trees for the two to disagree about.
    """
    written: list[str] = []
    for change in differences(before, after):
        was = change.previous_path or change.path
        written.append(f"diff --git {_BEFORE}{was} {_AFTER}{change.path}")
        if change.kind is ChangeKind.RENAMED:
            written += ["similarity index 100%", f"rename from {was}", f"rename to {change.path}"]
            continue
        written += _body(was, change.path, before.get(was), after.get(change.path))
    return "\n".join(written) + "\n" if written else ""


def _moves(before: Tree, after: Tree, arrived: list[str], gone: list[str]) -> dict[str, str]:
    """Which arrived path came from which departed one, for the moves that are certain.

    A path that went away is offered to at most one path that arrived, and in sorted order, so
    that a state where several identical files moved at once has one answer rather than whichever
    one a set happened to yield first.
    """
    available: dict[bytes, list[str]] = {}
    for path in gone:
        available.setdefault(before[path], []).append(path)
    paired: dict[str, str] = {}
    for path in arrived:
        candidates = available.get(after[path])
        if candidates:
            paired[path] = candidates.pop(0)
    return paired


def _body(was: str, now: str, before: bytes | None, after: bytes | None) -> list[str]:
    """The hunks for one file, or the one line git writes when a file is not text."""
    if (before is not None and _NOT_TEXT in before) or (after is not None and _NOT_TEXT in after):
        return [f"Binary files {_BEFORE}{was} and {_AFTER}{now} differ"]
    return list(
        unified_diff(
            _readable(before),
            _readable(after),
            fromfile=f"{_BEFORE}{was}" if before is not None else _ABSENT,
            tofile=f"{_AFTER}{now}" if after is not None else _ABSENT,
            lineterm="",
        )
    )


def _readable(content: bytes | None) -> list[str]:
    """One file's lines as text, without their terminators, or nothing where the file is not."""
    if content is None:
        return []
    return content.decode(_ENCODING, _UNREADABLE).splitlines()
