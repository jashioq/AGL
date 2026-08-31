
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from agl.adapters.git._snapshots import Tree

__all__ = ["Combination", "combined", "contested"]


_OPENED: Final = b"<<<<<<< "
_SPLIT: Final = b"=======\n"
_CLOSED: Final = b">>>>>>> "
_NEWLINE: Final = b"\n"

# git's own rule for a file that is not text: a NUL is the byte a line-oriented format cannot hold.
_NOT_TEXT: Final = b"\0"


@dataclass(frozen=True, slots=True)
class Combination:

    tree: Tree

    contested: Mapping[str, bytes]

    collisions: tuple[str, ...]


def combined(base: Tree, ours: Tree, theirs: Tree, ours_at: str, theirs_at: str) -> Combination:
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
    if content is None:
        return False
    return any(line.startswith(_OPENED) for line in content.splitlines())


def _both(mine: bytes | None, yours: bytes | None, ours_at: str, theirs_at: str) -> bytes:
    return _markers(_terminated(mine or b""), _terminated(yours or b""), ours_at, theirs_at)


def _lines(
    was: bytes, mine: bytes, yours: bytes, ours_at: str, theirs_at: str
) -> tuple[bytes, bool]:
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
    if mine == yours:
        return mine, False
    if mine == was:
        return yours, False
    if yours == was:
        return mine, False
    return [_markers(b"".join(mine), b"".join(yours), ours_at, theirs_at)], True


def _markers(mine: bytes, yours: bytes, ours_at: str, theirs_at: str) -> bytes:
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
    if not content or content.endswith(_NEWLINE):
        return content
    return content + _NEWLINE


def _in_step(
    base: Sequence[bytes], ours: Sequence[bytes], theirs: Sequence[bytes]
) -> list[tuple[int, int, int, int]]:
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
    mapping: dict[int, int] = {}
    for block in SequenceMatcher(None, base, other, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    return mapping
