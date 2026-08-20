"""RunLabel, Namespace, ProjectName, StepName - validated filesystem- and git-ref-safe names.

These are the names a user types that AGL then hands to the operating system and to git
without asking again. A `RunLabel` becomes the branch `agl/<label>` and a directory; a
`Namespace` becomes a path segment *and* a ref component, so `agl/_work/auth/T-01` has to be a
legal ref and a legal directory name; a `ProjectName` becomes `AGL_HOME/projects/<project>.toml`
and the directory beside it; a `StepName` becomes the directory `steps/<step>/` a step's entries
are recorded in. **Validation happens here, on the way in, so that nothing downstream
re-checks**: the path layouts join these into paths without a second opinion, and the git
adapter passes them to `git worktree add` unexamined. Anything that gets past this module is
something we have promised the rest of the codebase it may use.

They are opaque to the framework. Nothing here knows what a ticket, a run, a project or a step
*is* - rename `T-01` to `banana` and every answer this module gives is identical. All four
accept exactly the same language, from one validator, for the same reason a second rule set
would be a second thing to get wrong. They differ in exactly one respect and it is not the
language: two words are *reserved*, one per type, because the trees layout has already spent
them on itself (below).

Each is a frozen dataclass wrapping a `str`, not a `str` subclass and not a `NewType`. A `str`
subclass is silently accepted everywhere a `str` is, which is precisely the hole that lets an
unvalidated name reach disk; `NewType` carries no validation at all. Having to write `str(ns)`
at the path-join site, and having `mypy --strict` insist on it, is the feature. There is
deliberately no `__fspath__`: these are names, not paths, and `worktree()` is the only thing
that creates path depth.

**The character set is an allowlist** (plan §3.3): `[A-Za-z0-9._-]`, non-empty, no leading or
trailing `.` or `-`, capped at `NAME_MAX`. Not a list of what is dangerous - a list of what is
permitted, which is the difference between having to think of everything and having to think of
nothing. These names are frequently *agent output*: `decompose` invents the ticket ids that
become namespaces, and `$`, backtick, `;` and `|` are every one of them legal in a git ref and
in a POSIX filename. `$(whoami)` is a name git and the filesystem would both happily take.

The cost of that is paid by people and not by attackers, so it is written down here rather than
discovered: **nobody may name a run `café`**, or `v1.0+build`, or `fix(auth)`. Non-ASCII is
refused wholesale, which is a genuine loss for anyone whose alphabet is not this one. What it
buys is that no name AGL holds can carry a shell metacharacter into anything that later grows a
shell. Argv lists remain the discipline everywhere AGL spawns a process - that has not changed
and is not negotiable - but they are no longer the only thing standing between a name an agent
invented and a command line.

Inside the allowlist, git's rules and the filesystem's still have things to say, because `..`,
`.lock`, `CON` and a 256-byte name are all spelled in permitted characters. Two of the rules
are additions this module makes:

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

Two more rules survive the allowlist for what they *say* rather than for what they catch. "No
path separators" is redundant against a set with no `/` in it, but `agl run fix -n my/label`
deserves to be told that it wrote a path rather than that `/` is an unusual character. "No
invisible characters" - anything Unicode categorises as `C*` or `Z*` - names the character it
found, which is something an invisible character has to be before anyone can remove it.

**Two names are reserved, one per type**, because the trees layout has already spent them
(§3.9): `_base` is refused as a `Namespace`, being the run's own worktree directory, and `_work`
is refused as a `RunLabel`, being the infix under which every child branch is created. The two
reservations deliberately do not cross - `agl/_base` is a branch that collides with nothing, and
`agl/_work/<label>/_work` is a ref like any other - so `RunLabel("_base")` and
`Namespace("_work")` are good names and stay accepted. This is the one place the four types
differ, and it is a difference of reserved words rather than of language. Both comparisons are
case- and normalisation-insensitive, by `collision_key` below, because `_BASE` and `_base` are
one directory on the volume most of this is developed on. They are refused here rather than at
the layout that owns the word, so that the name cannot be constructed in the first place;
`tests/ports/test_tree_layout.py` pins each word against the layout that spends it.

One hazard is *not* solved here, because it needs state this module does not have, and it is
recorded so the stage that does have it can act:

  * **Collisions that only the filesystem sees.** `T-01` and `t-01` are distinct names to git
    and to the framework and the same directory on a case-insensitive volume. `collision_key`
    is what a uniqueness check compares, and §3.9 makes that check run-wide rather than
    sibling-wide, because the trees root is flat.
"""

import string
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Final

from agl.ports.errors import InputError

__all__ = ["Namespace", "ProjectName", "RunLabel", "StepName"]


# §3.3's allowlist, `[A-Za-z0-9._-]`, and the whole of what a name may be spelled with. Every
# other rule in this module narrows this set; none of them widens it.
_ALLOWED_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "._-")

# A name is one path segment and one ref component. `\` is both a Windows separator and git's
# rule 10; banning `/` outright subsumes git's rule 6 about runs of consecutive slashes.
_PATH_SEPARATORS: Final = frozenset("/\\")

# Unicode's top-level categories for characters that render as nothing, or as a space: `Cc`
# control, `Cf` format, `Cs` surrogate, `Co` private use, `Cn` unassigned, and every `Z*`.
_INVISIBLE_CATEGORIES: Final = frozenset("CZ")

# NAME_MAX on every filesystem AGL runs on, in bytes rather than characters because that is
# what the limit counts. The allowlist happens to make the two counts identical today; the
# limit is still the filesystem's, and it still counts bytes. A name that composes into a
# longer path is the caller's problem - `home_layout` accounts for the `.toml` it adds.
_MAX_BYTES: Final = 255

# Windows opens these as devices no matter which directory is named and no matter what
# extension follows, so `CON`, `con.toml` and `NUL.txt` are all the device.
_RESERVED_DEVICE_NAMES: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)

# The two words the trees layout spends on itself, spelled here because `tree_layout` imports
# this module and not the other way round. `test_tree_layout.py` pins each against the layout
# constant it mirrors, so the copy cannot drift unnoticed.
_BASE_WORKTREE_DIRNAME: Final = "_base"
_CHILD_BRANCH_INFIX: Final = "_work"


def _describe(character: str) -> str:
    """A character in a form a bug report can carry - `'\\x07'` alone teaches nobody."""
    name = unicodedata.name(character, "")
    return f"{character!r} ({name})" if name else f"{character!r} (U+{ord(character):04X})"


def _collision_key(value: str) -> str:
    """Casefold, then NFC: the two ways a filesystem merges names that git keeps apart."""
    return unicodedata.normalize("NFC", value.casefold())


def _unusable(value: str) -> str | None:
    """Why `value` may not be used as a name, or `None` if it may.

    Returns the reason rather than raising so that the four types can raise one shaped message,
    and so the checks stay a plain readable list. Order is chosen for the message a user gets:
    the specific complaint before the general one that would also have caught it.

    Most of what a blocklist had to enumerate is the allowlist's job now, and a rule survives it
    for one of exactly two reasons. Either the allowlist cannot see the problem - `..`, `.lock`,
    a leading `-`, a 256-byte name and `CON` are all spelled in permitted characters - or the
    sentence it produces teaches more than "that character is not allowed", which is why a
    separator and an invisible character still get a rule apiece. The rules that survived for
    neither reason are gone: `~ ^ : ? * [` are refused because AGL's set is narrower than git's,
    not because git reserves them, and `@{` and `@` stopped needing a rule each the moment `@`
    itself left the language.
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

    # Measured after the scan and not before, because a `str` may hold a lone surrogate that
    # `encode` refuses - and refuses by raising `UnicodeEncodeError`, which is not the error
    # this module promises. The scan has already turned those away: a surrogate is `Cs`.
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
    """The shared body of the four name types: one validated string, and nothing else.

    Private, because the point of the module is that a run label is not a namespace is not a
    project name. They share an implementation, not an identity: the generated `__eq__`
    compares classes, so `RunLabel("x") != Namespace("x")` and no `dict` keyed on one type can
    be reached with the other.

    `_RESERVED` is the one thing a subclass may say that the shared validator does not: words
    this kind of name may not spell, keyed by `collision_key` so every spelling is refused at
    once, and valued by the sentence explaining which layout already spent the word. It is
    empty for a type that has spent nothing.
    """

    _KIND: ClassVar[str] = "name"
    _RESERVED: ClassVar[Mapping[str, str]] = {}

    value: str
    """The string itself. Prefer `str(name)` at call sites; this is what it returns."""

    def __post_init__(self) -> None:
        reason = _unusable(self.value) or self._RESERVED.get(self.collision_key)
        if reason is not None:
            raise InputError(f"{self._KIND} {self.value!r} cannot be used: {reason}")

    def __str__(self) -> str:
        return self.value

    @property
    def collision_key(self) -> str:
        """What two names are compared by when the question is "would these collide on disk?".

        Not equality, and not a substitute for it: `RunLabel("T-01") != RunLabel("t-01")`, and
        the two are different branches to git. They are one directory on a case-insensitive
        volume, which is macOS by default. This folds that, so a uniqueness check that compares
        collision keys rejects the second sibling on the machine where creating it would
        clobber the first, rather than on whichever machine happens to be running. It is also
        what the reserved words above are matched by, which is how `_BASE` is refused too.

        The NFC half of the fold is, since §3.3's allowlist, unreachable through a constructor:
        no accepted name holds a character with two spellings, so no two accepted names differ
        by normalisation alone. It stays because the fold is one expression either way, and
        because a name having only one spelling is a property of the character set rather than
        of this comparison - widen the set and the fold is already correct.

        The uniqueness check itself is not here: it needs to know what the other names are, and
        this type knows only itself.
        """
        return _collision_key(self.value)


@dataclass(frozen=True, slots=True)
class RunLabel(_Name):
    """A run's name: the branch `agl/<label>`, and the run's directory under `AGL_HOME`.

    Reserves `_work`, and only `_work`: that is the infix every *child* branch is created
    under, and nothing else in the layout is a label's to collide with.
    """

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
    """A worktree's name within a run: a path segment, and a ref component of a child branch.

    The framework has no idea what it means. It is `T-01` because a workflow passed a ticket
    id, and it would behave identically if the workflow passed `banana`.

    Reserves `_base`, and only `_base`: that is the run's own checkout in the trees layout. A
    `RunLabel` of that name collides with nothing, which is why the reservation is here and not
    in the shared validator.
    """

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
    """A project's name: `AGL_HOME/projects/<project>.toml`, and the directory beside it.

    Never becomes a git ref, and validated by the same rules anyway - uniform rules cost
    nothing here, and the `.toml` it gains on disk is exactly why the device-name check looks
    at the stem. The five bytes that suffix adds are `home_layout`'s to account for: the cap
    above governs a name, and only the module that composes a name into a filename knows what
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
