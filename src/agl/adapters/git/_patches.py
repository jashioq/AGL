from difflib import unified_diff
from typing import Final
from agl.adapters.git._snapshots import Tree
from agl.ports.history import ChangeKind, FileChange

__all__ = ["differences", "patch"]

# git's own rule for a file that is not text: a NUL is the byte a line-oriented format cannot hold.
_NOT_TEXT: Final = b"\0"

_BEFORE: Final = "a/"
_AFTER: Final = "b/"
_ABSENT: Final = "/dev/null"

_ENCODING: Final = "utf-8"
_UNREADABLE: Final = "replace"

def differences(before: Tree, after: Tree) -> tuple[FileChange, ...]:
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
    if content is None:
        return []
    return content.decode(_ENCODING, _UNREADABLE).splitlines()
