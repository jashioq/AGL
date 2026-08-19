"""RunLabel, Namespace, ProjectName, StepName - validated filesystem- and git-ref-safe names.

These are the names a user types that AGL then hands to the operating system and to git
without asking again. A `RunLabel` becomes the branch `agl/<label>` and a directory; a
`Namespace` becomes a path segment *and* a ref component, so `agl/auth/T-01` has to be a legal
ref and a legal directory name; a `ProjectName` becomes `AGL_HOME/projects/<project>.toml` and
the directory beside it; a `StepName` becomes the directory `steps/<step>/` a step's entries
are recorded in. **Validation happens here, on the way in, so that nothing downstream
re-checks**: the path layouts join these into paths without a second opinion, and the git
adapter passes them to `git worktree add` unexamined. Anything that gets past this module is
something we have promised the rest of the codebase it may use.

They are opaque to the framework. Nothing here knows what a ticket, a run, a project or a step
*is* - rename `T-01` to `banana` and every answer this module gives is identical. All four
accept exactly the same language, from one validator, for the same reason a second rule set
would be a second thing to get wrong.

Each is a frozen dataclass wrapping a `str`, not a `str` subclass and not a `NewType`. A `str`
subclass is silently accepted everywhere a `str` is, which is precisely the hole that lets an
unvalidated name reach disk; `NewType` carries no validation at all. Having to write `str(ns)`
at the path-join site, and having `mypy --strict` insist on it, is the feature. There is
deliberately no `__fspath__`: these are names, not paths, and `worktree()` is the only thing
that creates path depth.

The rules come from `git check-ref-format` (see its man page - the numbered list there is the
source), plus what a path segment needs, plus two additions this module makes:

  * **A leading `-` is rejected**, though git permits it in a ref component. A name starting
    with `-` is read as a flag by everything that takes it as an argument - including
    `git check-ref-format` itself, which has no `--` and so cannot even be asked about such a
    name. The only cost is that nobody may name a run `-fix`.
  * **Reserved Windows device names are rejected**, matched case-insensitively on the stem
    before the first dot, because `CON.toml` is the `CON` device on Windows just as `CON` is.
    v1.1 targets POSIX; the cost is a frozenset and the failure mode is otherwise silent and
    remote.

Two of git's own rules are read one notch stricter than git reads them, both for the same
reason - the filesystem underneath is usually case-insensitive, and git's rule is not. A `.lock`
suffix is matched in any case, so `T-01.LOCK` is refused although `git check-ref-format` allows
it; and a device name is matched in any case for the same reason. Over-refusing costs a user one
rename. Under-refusing costs a collision nobody can see.

Two rules are stated once and cover more than their name suggests. "No path separators" covers
git's ban on `\\` and on `//` runs, since a name that cannot contain `/` cannot contain two.
"No invisible characters" - anything Unicode categorises as `C*` (control, format, surrogate,
private-use, unassigned) or `Z*` (space and line separators) - covers git's ban on ASCII
controls, DEL and space, and the ban on leading or trailing whitespace, and additionally keeps
out the non-ASCII invisibles that are legal in a ref and on disk but unreadable in a bug
report: no-break space, zero-width joiners, the bidi overrides. Everything visible that git
allows is allowed, `banana` and `T-01` and `chapitre-un` alike; this module invents no
character set of its own beyond that.

Two hazards are *not* solved here, because they need state this module does not have, and both
are recorded so the stage that does have it can act:

  * **Collisions that only the filesystem sees.** `T-01` and `t-01` are distinct names to git
    and to the framework and the same directory on a case-insensitive volume, as are the NFC
    and NFD spellings of `café`. `collision_key` is what a sibling-uniqueness check compares.
  * **Shell metacharacters.** `$`, backtick, `;`, `|` and friends are legal in a ref and on
    disk, so they are accepted here. That is safe exactly as long as every subprocess is given
    an argv list rather than a shell string.
"""

import unicodedata
from dataclasses import dataclass
from typing import ClassVar, Final

from agl.ports.errors import InputError

__all__ = ["Namespace", "ProjectName", "RunLabel", "StepName"]


# A name is one path segment and one ref component. `\` is both a Windows separator and git's
# rule 10; banning `/` outright subsumes git's rule 6 about runs of consecutive slashes.
_PATH_SEPARATORS: Final = frozenset("/\\")

# git's rules 4 and 5, minus the characters the invisibility rule below already covers.
_RESERVED_PUNCTUATION: Final = frozenset("~^:?*[")

# Unicode's top-level categories for characters that render as nothing, or as a space: `Cc`
# control, `Cf` format, `Cs` surrogate, `Co` private use, `Cn` unassigned, and every `Z*`.
_INVISIBLE_CATEGORIES: Final = frozenset("CZ")

# NAME_MAX on every filesystem AGL runs on, in bytes rather than characters because that is
# what the limit counts. A name that composes into a longer path is still the caller's problem.
_MAX_BYTES: Final = 255

# Windows opens these as devices no matter which directory is named and no matter what
# extension follows, so `CON`, `con.toml` and `NUL.txt` are all the device.
_RESERVED_DEVICE_NAMES: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)


def _describe(character: str) -> str:
    """A character in a form a bug report can carry - `'\\x07'` alone teaches nobody."""
    name = unicodedata.name(character, "")
    return f"{character!r} ({name})" if name else f"{character!r} (U+{ord(character):04X})"


def _unusable(value: str) -> str | None:
    """Why `value` may not be used as a name, or `None` if it may.

    Returns the reason rather than raising so that the three types can raise one shaped
    message, and so the checks stay a plain readable list. Order is chosen for the message a
    user gets: the specific complaint before the general one that would also have caught it.
    """
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
        if character in _RESERVED_PUNCTUATION:
            return (
                f"it contains {character!r} at position {index}, and git ref names reserve "
                f"~ ^ : ? * and ["
            )
        if unicodedata.category(character)[0] in _INVISIBLE_CATEGORIES:
            return (
                f"it contains {_describe(character)} at position {index}, and a name carries "
                f"no spaces, control characters or other invisible characters"
            )

    # Measured after the scan and not before, because a `str` may hold a lone surrogate that
    # `encode` refuses - and refuses by raising `UnicodeEncodeError`, which is not the error
    # this module promises. The scan has already turned those away: a surrogate is `Cs`.
    length = len(value.encode("utf-8"))
    if length > _MAX_BYTES:
        return f"it is {length} bytes long, and a path segment may not exceed {_MAX_BYTES}"

    if value.startswith("-"):
        return "it starts with '-', which any command taking it as an argument reads as a flag"
    if ".." in value:
        return "it contains '..', which git ref names may not, and which means a parent directory"
    if value.startswith("."):
        return "it starts with '.', which git ref components may not, and which hides it on disk"
    if value.endswith("."):
        return "it ends with '.', which git ref names may not, and which Windows silently strips"
    if value.lower().endswith(".lock"):
        return "it ends with '.lock', which git reserves for its own lock files"
    if "@{" in value:
        return "it contains '@{', which is git's reflog notation"
    if value == "@":
        return "it is '@', which is how git spells HEAD"

    stem = value.split(".", 1)[0]
    if stem.upper() in _RESERVED_DEVICE_NAMES:
        return (
            f"its first component {stem!r} is a reserved device name on Windows, where opening "
            f"the file opens the device instead"
        )
    return None


@dataclass(frozen=True, slots=True)
class _Name:
    """The shared body of the three name types: one validated string, and nothing else.

    Private, because the point of the module is that a run label is not a namespace is not a
    project name. They share an implementation, not an identity: the generated `__eq__`
    compares classes, so `RunLabel("x") != Namespace("x")` and no `dict` keyed on one type can
    be reached with the other.
    """

    _KIND: ClassVar[str] = "name"

    value: str
    """The string itself. Prefer `str(name)` at call sites; this is what it returns."""

    def __post_init__(self) -> None:
        reason = _unusable(self.value)
        if reason is not None:
            raise InputError(f"{self._KIND} {self.value!r} cannot be used: {reason}")

    def __str__(self) -> str:
        return self.value

    @property
    def collision_key(self) -> str:
        """What two names are compared by when the question is "would these collide on disk?".

        Not equality, and not a substitute for it: `RunLabel("T-01") != RunLabel("t-01")`, and
        the two are different branches to git. They are one directory on a case-insensitive
        volume, which is macOS by default - and so are the NFC and NFD spellings of `café`,
        which are also one ref to nobody. This folds both, so a uniqueness check that compares
        collision keys rejects the second sibling on the machine where creating it would
        clobber the first, rather than on whichever machine happens to be running.

        The sibling-uniqueness check itself is not here: it needs to know what the siblings
        are, and this type knows only itself.
        """
        return unicodedata.normalize("NFC", self.value.casefold())


@dataclass(frozen=True, slots=True)
class RunLabel(_Name):
    """A run's name: the branch `agl/<label>`, and the run's directory under `AGL_HOME`."""

    _KIND: ClassVar[str] = "run label"


@dataclass(frozen=True, slots=True)
class Namespace(_Name):
    """A worktree's name within a run: a path segment, and a ref component under `agl/<label>`.

    The framework has no idea what it means. It is `T-01` because a workflow passed a ticket
    id, and it would behave identically if the workflow passed `banana`.
    """

    _KIND: ClassVar[str] = "namespace"


@dataclass(frozen=True, slots=True)
class ProjectName(_Name):
    """A project's name: `AGL_HOME/projects/<project>.toml`, and the directory beside it.

    Never becomes a git ref, and validated by the same rules anyway - uniform rules cost
    nothing here, and the `.toml` it gains on disk is exactly why the device-name check looks
    at the stem. The five bytes that suffix adds are `home_layout`'s to account for: the cap
    below governs a name, and only the module that composes a name into a filename knows what
    it is composing it into.
    """

    _KIND: ClassVar[str] = "project name"


@dataclass(frozen=True, slots=True)
class StepName(_Name):
    """A step's name within a run: the directory `steps/<step>/` holding its recorded entries.

    A distinct type rather than a reused `Namespace`, though the rules are identical, because
    the two are siblings on disk and mean opposite things: `steps/review/` is what a step
    recorded and `worktrees/review/` is where a worktree checked out. Sharing one type would
    make the layout's own defence against that collision - two subtrees - the only thing left
    keeping them apart, and would let a step name be passed to `worktree()` with nothing
    complaining. `spec`, `implement` and `review_quality` are what the shipped workflows happen
    to pass; the framework has no opinion.
    """

    _KIND: ClassVar[str] = "step name"
