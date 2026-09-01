from pathlib import Path
from typing import Final
from agl.adapters.git._runner import unreadable
from agl.ports.integration import Conflict

__all__ = ["already_holding", "collided", "unmerged", "unresolved"]

# The `-z` form: NUL ends a record and is the one byte a path cannot hold, and the path is the tail
# after one tab - so a filename holding a tab of its own still survives this parse.
_RECORD_END: Final = "\0"
_NAME_START: Final = "\t"

_NAMED: Final = 3

_WHAT: Final = "a list of unresolved files"

def unmerged(listing: str) -> tuple[str, ...]:
    records = listing.split(_RECORD_END)
    if records and not records[-1]:
        del records[-1]
    found: dict[str, None] = {}
    for record in records:
        _, tab, path = record.partition(_NAME_START)
        if not tab or not path:
            raise unreadable(_WHAT, listing)
        found[path] = None
    return tuple(found)

def collided(paths: tuple[str, ...], source: str, target: str, where: Path) -> Conflict:
    return _conflict(paths, f"{source} will not combine into {target}", where)

def unresolved(paths: tuple[str, ...], target: str, where: Path) -> Conflict:
    return _conflict(paths, f"the landing {target} is holding still will not combine", where)

def already_holding(paths: tuple[str, ...], source: str, target: str, where: Path) -> Conflict:
    lead = (
        f"a landing into {target} was already pending when {source} was offered, and that one has "
        f"to be concluded or given up before this one can be attempted"
    )
    still = (
        f"Still unresolved in the landing already held: {_named(paths)}."
        if paths
        else "Nothing is left unresolved in the landing already held to name."
    )
    return Conflict(
        paths,
        f"{lead}. {still} Nothing was combined here and nothing was changed - the landing already "
        f"held is held in {where}",
    )

def _conflict(paths: tuple[str, ...], lead: str, where: Path) -> Conflict:
    if not paths:
        return Conflict(
            paths,
            f"{lead}, and git left no unresolved file to name. The landing is held in {where}",
        )
    return Conflict(paths, f"{lead}: {_named(paths)}. The landing is held in {where}")

def _named(paths: tuple[str, ...]) -> str:
    rest = len(paths) - _NAMED
    return ", ".join(paths[:_NAMED]) + (f" and {rest} more" if rest > 0 else "")
