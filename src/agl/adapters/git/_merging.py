"""Three states into one: the three-way merge the fake integrator lands with, and nothing else.

The seam `_trees.py`, `_changes.py` and `_conflicts.py` each draw, drawn once more for the fake:
**nothing here has state, touches the filesystem, or knows what a workspace is.** What arrives is
three trees and two names; what leaves is the tree they combine to and the paths that would not.
So the whole of the fake's answer to "will this work go in" is a pure function, which is what a
merge deserves to be and what makes it testable without a repository.

## Why this is a real merge and not a predicate

A fake that never conflicts makes a merge train look clean that git will reject; a fake that
conflicts on any two changes to one file makes a workflow's conflict screen fire on work that
would have combined. Both are worse than useless, and the difference between them and something
worth trusting is the *common ancestor*: with the base in hand, "both sides changed this" is
answerable, and without it every difference looks like a collision.

So this is a three-way merge in the ordinary sense, at two levels.

**Over the tree.** A path present in all three, or missing from all three, is compared three ways:
the two sides agreeing is not a collision however far they both moved, one side matching the base
means only the other side changed it, and a side matching the base is the side that gives way. Two
children that touched different files therefore combine, always, because for every path one of
them is the base.

**Over the lines of one file.** When both sides changed one text file, the file is aligned against
the base and the *regions* that both sides changed are the collisions - so two agents editing
opposite ends of one module combine, which is git's answer too and is the case a file-level
comparison would have wrongly refused. The alignment is the classic three-way one: the runs of
base lines that both sides kept, in the same order, are the fixed points, and everything between
two fixed points is one region to decide about.

**Where it is not git's answer**, and `test_git_parity.py` pins each: git's own merge detects
renames, so a file one side moved and the other edited combines there and collides here; and a
file holding a NUL byte is not text for either of them, which git resolves by taking neither side
and this one by taking the target's, with the collision reported the same way.

## The markers are this module's own record, and `retry` reads them back

A collision leaves the file holding both versions between markers, git's spelling of it, because a
person or an agent resolving one in a `--dry-run` should be looking at what they would look at in
anger. It is also the only place a resolution can be *recorded*: git writes unresolvedness into
its index and takes `git add` as the word that it is over, and the fake has neither, so the file it
wrote is the one thing outside this package that anybody can change. `contested` below is that
question asked again, and `fake.py` says where the difference from an index is pinned.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from agl.adapters.git._snapshots import Tree

__all__ = ["Combination", "combined", "contested"]


# git's own conflict markers, which is the whole reason to spell them this way: a person opening
# one of these files has seen it before, and an agent has seen an enormous amount of it.
_OPENED: Final = b"<<<<<<< "
_SPLIT: Final = b"=======\n"
_CLOSED: Final = b">>>>>>> "
_NEWLINE: Final = b"\n"

# What makes a file not text. git's own rule, and the reason both of them refuse to merge one: a
# NUL is the byte a line-oriented format cannot hold, so lines are not what the file is made of.
_NOT_TEXT: Final = b"\0"


@dataclass(frozen=True, slots=True)
class Combination:
    """What two lines of work come to, and what stopped them coming to all of it.

    `tree` and `contested` are disjoint and together cover every path either side has: a path is
    in one or the other, never both, so a caller writing `{**tree, **contested}` into a checkout
    writes each path exactly once.
    """

    tree: Tree
    """The paths that combined, at what they combined to. The whole answer when nothing collided."""

    contested: Mapping[str, bytes]
    """What to leave at each colliding path: both versions, between markers."""

    collisions: tuple[str, ...]
    """The colliding paths, sorted, which is the order a `Conflict` then reports them in."""


def combined(base: Tree, ours: Tree, theirs: Tree, ours_at: str, theirs_at: str) -> Combination:
    """Merge `theirs` into `ours` against their common ancestor `base`.

    Directional in exactly one respect and no other: `ours` is the side whose name goes on the
    first half of a marker block and whose content a binary collision keeps. Which files combine,
    and which do not, is symmetric.
    """
    tree: dict[str, bytes] = {}
    disputed: dict[str, bytes] = {}
    for path in sorted(set(base) | set(ours) | set(theirs)):
        was, mine, yours = base.get(path), ours.get(path), theirs.get(path)
        if mine == yours:
            kept = mine
        elif mine == was:
            kept = yours
        elif yours == was:
            kept = mine
        elif was is None or mine is None or yours is None:
            # One side has no content at all - two sides creating one path, or one editing what
            # the other removed. There is no third version to align against and nothing to take,
            # so the whole of both is what the person is shown.
            disputed[path] = _both(mine, yours, ours_at, theirs_at)
            continue
        elif _NOT_TEXT in mine or _NOT_TEXT in yours or _NOT_TEXT in was:
            disputed[path] = mine
            continue
        else:
            merged, collided = _lines(was, mine, yours, ours_at, theirs_at)
            if collided:
                disputed[path] = merged
                continue
            kept = merged
        if kept is not None:
            tree[path] = kept
    return Combination(tree, disputed, tuple(sorted(disputed)))


def contested(content: bytes | None) -> bool:
    """Does this file still hold a collision nobody resolved?

    The fake's counterpart of asking git's index which paths are unmerged, and it is asked of the
    file because the file is where this package wrote the question. A path that is no longer there
    at all is resolved - somebody decided the answer was to remove it.
    """
    if content is None:
        return False
    return any(line.startswith(_OPENED) for line in content.splitlines())


def _both(mine: bytes | None, yours: bytes | None, ours_at: str, theirs_at: str) -> bytes:
    """One whole file against another, between markers. Either side may be nothing."""
    return _markers(_terminated(mine or b""), _terminated(yours or b""), ours_at, theirs_at)


def _lines(
    was: bytes, mine: bytes, yours: bytes, ours_at: str, theirs_at: str
) -> tuple[bytes, bool]:
    """Both sides of one text file, region by region, and whether any region collided.

    The walk is over the runs of base lines that both sides kept in step - see the module
    docstring. Everything between two such runs is one region, decided by the same three-way
    comparison the tree walk makes, and a region neither side can give way on is written out
    between markers rather than abandoning the rest of the file.
    """
    base_lines = was.splitlines(keepends=True)
    our_lines = mine.splitlines(keepends=True)
    their_lines = yours.splitlines(keepends=True)
    out: list[bytes] = []
    collided = False
    base_at = our_at = their_at = 0
    for start, stop, ours_start, theirs_start in _in_step(base_lines, our_lines, their_lines):
        piece, region_collided = _region(
            base_lines[base_at:start],
            our_lines[our_at:ours_start],
            their_lines[their_at:theirs_start],
            ours_at,
            theirs_at,
        )
        out.extend(piece)
        collided = collided or region_collided
        out.extend(base_lines[start:stop])
        kept = stop - start
        base_at, our_at, their_at = stop, ours_start + kept, theirs_start + kept
    piece, region_collided = _region(
        base_lines[base_at:], our_lines[our_at:], their_lines[their_at:], ours_at, theirs_at
    )
    out.extend(piece)
    return b"".join(out), collided or region_collided


def _region(
    was: list[bytes], mine: list[bytes], yours: list[bytes], ours_at: str, theirs_at: str
) -> tuple[list[bytes], bool]:
    """One stretch neither side kept unchanged: whose it is, or both of them between markers."""
    if mine == yours:
        return mine, False
    if mine == was:
        return yours, False
    if yours == was:
        return mine, False
    return [_markers(b"".join(mine), b"".join(yours), ours_at, theirs_at)], True


def _markers(mine: bytes, yours: bytes, ours_at: str, theirs_at: str) -> bytes:
    """Both versions, labelled with the lines of work they came from."""
    return b"".join(
        (
            _OPENED,
            ours_at.encode(errors="replace"),
            _NEWLINE,
            _terminated(mine),
            _SPLIT,
            _terminated(yours),
            _CLOSED,
            theirs_at.encode(errors="replace"),
            _NEWLINE,
        )
    )


def _terminated(content: bytes) -> bytes:
    """`content` ending in a newline, so that the marker after it starts its own line.

    A file whose last line has no newline is ordinary, and pasting `=======` onto the end of it
    would produce a marker no reader and no later parse would recognise.
    """
    if not content or content.endswith(_NEWLINE):
        return content
    return content + _NEWLINE


def _in_step(
    base: Sequence[bytes], ours: Sequence[bytes], theirs: Sequence[bytes]
) -> list[tuple[int, int, int, int]]:
    """The runs of base lines both sides kept, as (base start, base stop, ours start, theirs start).

    A run is maximal and contiguous in all three at once, which is what makes it a fixed point: the
    lines between two of them are what the two sides did to one stretch of the original, and can
    be compared against each other and against what was there.
    """
    to_ours = _aligned(base, ours)
    to_theirs = _aligned(base, theirs)
    runs: list[tuple[int, int, int, int]] = []
    index = 0
    while index < len(base):
        if index in to_ours and index in to_theirs:
            start = index
            while (
                index + 1 < len(base)
                and to_ours.get(index + 1) == to_ours[index] + 1
                and to_theirs.get(index + 1) == to_theirs[index] + 1
            ):
                index += 1
            runs.append((start, index + 1, to_ours[start], to_theirs[start]))
        index += 1
    return runs


def _aligned(base: Sequence[bytes], other: Sequence[bytes]) -> dict[int, int]:
    """Which line of `other` each line of `base` survived as, for the lines that survived.

    `autojunk` is off because it is a heuristic for a different problem: it drops elements that
    appear in more than one percent of a long sequence, which in source code means a blank line or
    a closing brace, and the alignment those anchor is exactly the alignment a merge needs.
    """
    mapping: dict[int, int] = {}
    for block in SequenceMatcher(None, base, other, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    return mapping
