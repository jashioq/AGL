
import string
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Final

from agl.ports.errors import InputError

__all__ = ["Namespace", "ProjectName", "RunLabel", "StepName"]


_ALLOWED_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "._-")

# `\` is a separator on Windows and illegal in a git ref component; `/` is both at once.
_PATH_SEPARATORS: Final = frozenset("/\\")

# Unicode's top-level categories for what renders as nothing or as a space: `Cc` control, `Cf`
# format, `Cs` surrogate, `Co` private use, `Cn` unassigned, and every `Z`.
_INVISIBLE_CATEGORIES: Final = frozenset("CZ")

# NAME_MAX: the longest single path segment every filesystem AGL runs on will take, in bytes.
_MAX_BYTES: Final = 255

# `con.toml` and `NUL.txt` are the devices too - whatever the extension, whatever the case.
_RESERVED_DEVICE_NAMES: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)

_BASE_WORKTREE_DIRNAME: Final = "_base"
_CHILD_BRANCH_INFIX: Final = "_work"


def _describe(character: str) -> str:
    name = unicodedata.name(character, "")
    return f"{character!r} ({name})" if name else f"{character!r} (U+{ord(character):04X})"


# Casefold then NFC: the two ways a filesystem merges names that git keeps apart.
def _collision_key(value: str) -> str:
    return unicodedata.normalize("NFC", value.casefold())


def _unusable(value: str) -> str | None:
    if not value:
        return "it is empty"
    if value in {".", ".."}:
        return "it is a path traversal segment, not a name"

    for index, character in enumerate(value):
        if character in _PATH_SEPARATORS:
            return (
                f"it contains {character!r} at position {index}, and a name is one path "
                f"segment and one git ref component - never a path"
            )
        if unicodedata.category(character)[0] in _INVISIBLE_CATEGORIES:
            return (
                f"it contains {_describe(character)} at position {index}, and a name carries "
                f"no spaces, control characters or other invisible characters"
            )
        if character not in _ALLOWED_CHARACTERS:
            return (
                f"it contains {_describe(character)} at position {index}, and a name may hold "
                f"only letters A-Z a-z, digits, and '.', '_' or '-'"
            )

    length = len(value.encode("utf-8"))
    if length > _MAX_BYTES:
        return f"it is {length} bytes long, and a path segment may not exceed {_MAX_BYTES}"

    if value.startswith("-"):
        return "it starts with '-', which any command taking it as an argument reads as a flag"
    if value.endswith("-"):
        return "it ends with '-', which reads as a truncated name and is no use to anyone"
    if ".." in value:
        return "it contains '..', which git ref names may not, and which means a parent directory"
    if value.startswith("."):
        return "it starts with '.', which git ref components may not, and which hides it on disk"
    if value.endswith("."):
        return "it ends with '.', which git ref names may not, and which Windows silently strips"
    if value.lower().endswith(".lock"):
        return "it ends with '.lock', which git reserves for its own lock files"

    stem = value.split(".", 1)[0]
    if stem.upper() in _RESERVED_DEVICE_NAMES:
        return (
            f"its first component {stem!r} is a reserved device name on Windows, where opening "
            f"the file opens the device instead"
        )
    return None


@dataclass(frozen=True, slots=True)
class _Name:

    _KIND: ClassVar[str] = "name"
    _RESERVED: ClassVar[Mapping[str, str]] = {}

    value: str

    def __post_init__(self) -> None:
        reason = _unusable(self.value) or self._RESERVED.get(self.collision_key)
        if reason is not None:
            raise InputError(f"{self._KIND} {self.value!r} cannot be used: {reason}")

    def __str__(self) -> str:
        return self.value

    @property
    def collision_key(self) -> str:
        return _collision_key(self.value)


@dataclass(frozen=True, slots=True)
class RunLabel(_Name):

    _KIND: ClassVar[str] = "run label"
    _RESERVED: ClassVar[Mapping[str, str]] = {
        _collision_key(_CHILD_BRANCH_INFIX): (
            f"{_CHILD_BRANCH_INFIX!r} is the infix every child branch is created under, so a "
            f"run of that name would need refs/heads/agl/{_CHILD_BRANCH_INFIX} to be its own "
            f"branch and the directory holding every run's children at once - and on a "
            f"case-insensitive filesystem, so would any spelling of it"
        ),
    }


@dataclass(frozen=True, slots=True)
class Namespace(_Name):

    _KIND: ClassVar[str] = "namespace"
    _RESERVED: ClassVar[Mapping[str, str]] = {
        _collision_key(_BASE_WORKTREE_DIRNAME): (
            f"{_BASE_WORKTREE_DIRNAME!r} is the run's own base worktree in the trees layout, so "
            f"a child worktree of that name would be the same directory - and on a "
            f"case-insensitive filesystem, so is any spelling of it"
        ),
    }


@dataclass(frozen=True, slots=True)
class ProjectName(_Name):

    _KIND: ClassVar[str] = "project name"


@dataclass(frozen=True, slots=True)
class StepName(_Name):

    _KIND: ClassVar[str] = "step name"
