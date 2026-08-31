
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from agl.adapters.git._runner import unreadable
from agl.ports.history import ChangeKind, FileChange

__all__ = ["changes"]

# What ends every field of the `-z` form: NUL is the one byte a repository path cannot hold.
_FIELD_END: Final = "\0"

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

_PAIRED: Final = frozenset("CR")

# A rename or copy status may carry a similarity percentage: `R100` is a file moved untouched.
_SCORE: Final = frozenset("0123456789")

_WHAT: Final = "a list of changed files"


def changes(output: str) -> tuple[FileChange, ...]:
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
        found.append(FileChange(path, kind, came_from if kind is ChangeKind.RENAMED else None))
        index += 1 + names
    return tuple(found)


def _kind(code: str, output: str) -> ChangeKind:
    kind = _KINDS.get(code[:1])
    if kind is None or not _SCORE.issuperset(code[1:]):
        raise unreadable(_WHAT, output)
    return kind
