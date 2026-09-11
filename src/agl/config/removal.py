from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.config.inspection import StandingEntry, folded, listed
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.home_layout import AglHome, workflows_dir

__all__ = ["RemovableEntry", "entries_named", "removable"]

_PATH_SEPARATORS: Final = frozenset("/\\")
_TRAVERSALS: Final = frozenset({".", ".."})
_HIDDEN: Final = "."

@dataclass(frozen=True, slots=True)
class RemovableEntry:
    """What `agl remove` may take out of workflows/: the entry, and what goes with it."""

    path: Path

    declared: tuple[str, ...]
    """Every name `agl run` takes that it declares, sorted; empty where it declares none."""

    linked: bool
    """A link, so the link alone goes and what it names stays."""

def removable(home: AglHome, name: str) -> RemovableEntry:
    """The entry of workflows/ that `name` is, refused where a removal may not take it."""
    _check_removable(name)
    entries = listed(home)
    entry = _entry_named(entries, name, workflows_dir(home))
    linked = entry.path.is_symlink()
    if entry.member is None:
        return RemovableEntry(entry.path, (), linked)
    distribution = entry.member.distribution
    dependents = [
        other.member.where
        for other in entries
        if other is not entry and other.member is not None and distribution in other.member.required
    ]
    if distribution is not None and dependents:
        raise ConflictError(_depended_on(entry.path, distribution, dependents))
    return RemovableEntry(entry.path, tuple(sorted(entry.member.declared)), linked)

def _check_removable(name: str) -> None:
    if not name or name in _TRAVERSALS:
        raise InputError(_unnamed(name))
    separator = next((character for character in name if character in _PATH_SEPARATORS), None)
    if separator is not None:
        raise InputError(_pathlike(name, separator))
    if name.startswith(_HIDDEN):
        raise InputError(_dot_led(name))

# A case-insensitive volume answers to every spelling of a name, so the fold finds what it holds;
# on a case-sensitive one two spellings can stand side by side, and the one typed is the one meant.
def entries_named(entries: Sequence[StandingEntry], name: str) -> tuple[StandingEntry, ...]:
    """The entry spelled exactly `name`, or failing that every entry its fold reaches."""
    exact = tuple(entry for entry in entries if entry.path.name == name)
    if exact:
        return exact
    return tuple(entry for entry in entries if entry.folded == folded(name))

def _entry_named(entries: Sequence[StandingEntry], name: str, directory: Path) -> StandingEntry:
    spellings = entries_named(entries, name)
    if len(spellings) > 1:
        raise ConflictError(_ambiguous(name, spellings))
    if not spellings:
        raise NotFoundError(_unlisted(name, entries, directory))
    return spellings[0]

def _unnamed(name: str) -> str:
    return (
        f"{name!r} is not the name of anything `agl remove` could take: it takes the name of one "
        f"entry in the workspace's workflows/ directory, as a listing of that directory shows it"
    )

def _pathlike(name: str, separator: str) -> str:
    return (
        f"{name!r} holds {separator!r}, and `agl remove` takes the name of one entry in the "
        f"workspace's workflows/ directory rather than a path - so nothing outside it, and "
        f"nothing below one of its entries, is anything this command can reach"
    )

def _dot_led(name: str) -> str:
    return (
        f"{name!r} starts with '.', and `agl remove` never takes a dot-led entry: AGL stages what "
        f"it places or removes in one inside workflows/, and one a crash left behind can hold the "
        f"only copy of a workflow an override was replacing, with nothing in it saying whose. Look "
        f"inside it, and delete it by hand once you know nothing in it is wanted"
    )

def _ambiguous(name: str, spellings: Sequence[StandingEntry]) -> str:
    return (
        f"{name!r} is not the name of any entry as it is spelled, and {len(spellings)} entries "
        f"differ from it only in case: {', '.join(str(entry.path) for entry in spellings)}. AGL "
        f"will not choose which of them goes - ask for one by its name exactly as it is spelled"
    )

def _unlisted(name: str, entries: Sequence[StandingEntry], directory: Path) -> str:
    declaring = [
        entry.path.name
        for entry in entries
        if entry.member is not None and name in entry.member.declared
    ]
    if declaring:
        return (
            f"nothing in {directory} is named {name!r}, which is a workflow declared in "
            f"{_quoted(declaring)}. `agl remove` takes the name of the entry a declaration is "
            f"written in rather than the name it declares, and removing that entry removes every "
            f"workflow it declares with it - the question names each of them before anything goes"
        )
    held = [entry.path.name for entry in entries if not entry.path.name.startswith(_HIDDEN)]
    if not held:
        return (
            f"nothing in {directory} is named {name!r}, and nothing there is an entry `agl remove` "
            f"could take"
        )
    return (
        f"nothing in {directory} is named {name!r}. What it holds: {_quoted(held)}. `agl remove` "
        f"takes one of those - an entry's own name, which need not be any name `agl run` takes"
    )

def _depended_on(path: Path, distribution: str, dependents: Sequence[str]) -> str:
    return (
        f"{path} is not removed: it is the workspace member uv knows as {distribution!r}, and "
        f"{distribution!r} is in the [project] dependencies of {', '.join(dependents)}. uv reads a "
        f"dependency on a member's name as a dependency on that member, so removing it would "
        f"change what theirs resolves to - to nothing, refusing every later sync, where a "
        f"[tool.uv.sources] entry names it as a workspace member, and to whatever a package index "
        f"holds under that name where none does. Take the dependency out of theirs first, or "
        f"remove them before this one"
    )

def _quoted(names: Sequence[str]) -> str:
    return ", ".join(repr(name) for name in names)
