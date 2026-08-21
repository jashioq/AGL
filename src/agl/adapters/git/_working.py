"""The working directory: the one place in the fake that reads or writes a file.

`ports/workspace.py` promises one thing about the world that a fake cannot hold in memory - "a
workspace genuinely is a directory: an agent is pointed at one and a verifier's working directory
is one" - so the fake's checkouts are real directories with real files in them, and everything
else it knows is a dict. This module is that boundary, and the seam is `_trees.py`'s, restated:
**nothing here knows what a recorded state is, and nothing in `_snapshots.py` opens a file.**

`_trees.py` next door already makes and unmakes the directories a run's checkouts sit in, and the
fake uses it unchanged - `made`, `deleted` and `tidied` are `mkdir`, `rmtree` and `rmdir` with no
git in any of them, which is exactly why 5.2 put them in a module of their own. What is here is
the part that module has no reason to have: reading a checkout into a state and laying a state
back out into one.

`_translated` is four lines this package now holds twice, for `history.py::_one`'s reason: sharing
it would mean either editing a module this deliverable does not own or a third module existing for
one function, and four repeated lines is the cheaper of the three.
"""

import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from agl.ports.errors import AglError, DeniedError, UpstreamUnavailable

__all__ = ["applied", "restored", "snapshot"]


def snapshot(directory: Path) -> dict[str, bytes]:
    """Every regular file under `directory`, keyed by its repository-relative name.

    The names are forward-slash separated whatever the platform spells a path with, because that
    is what `FileChange.path` and `Conflict.paths` promise and what `_snapshots.py` addresses by.

    **Regular files only.** A directory holding nothing is not part of a state, which is git's
    answer too and is why `restored` prunes an emptied one rather than keeping it. A symlink is
    not part of one either, and that is the fake being narrow rather than agreeing: git records a
    link, and `test_git_parity.py` pins the difference along with the executable bit, which is the
    other half of a file this module does not look at.
    """
    found: dict[str, bytes] = {}
    _gather(directory, "", found)
    return found


def restored(directory: Path, tree: Mapping[str, bytes]) -> None:
    """Make `directory` hold exactly `tree` and nothing else.

    Everything that was there and is not in `tree` goes, including a directory that only existed
    to hold something now gone - §3.3 is explicit that moving the head alone is not enough,
    "because untracked files survive it", and an agent's cache directory is the case the port
    names. There is no `.gitignore` here and so nothing survives on account of one, which is the
    first divergence `test_git_parity.py` pins.
    """
    _emptied(directory)
    for path, content in tree.items():
        _written(directory, path, content)


def applied(directory: Path, tree: Mapping[str, bytes], paths: Iterable[str]) -> None:
    """Put `paths` in `directory` at what `tree` says, deleting the ones `tree` does not hold.

    The narrow counterpart of `restored`, and the difference is the whole of what a landing and its
    release promise: what neither of them touched is left exactly as it stood, a person's scratch
    file included, because "as it was before `land`" is not "as if nothing had ever happened".
    """
    for path in paths:
        content = tree.get(path)
        if content is None:
            _removed(directory, path)
        else:
            _written(directory, path, content)


def _gather(at: Path, under: str, found: dict[str, bytes]) -> None:
    """Read one directory into `found`, descending into the directories it holds."""
    try:
        entries = sorted(at.iterdir(), key=lambda entry: entry.name)
    except OSError as error:
        raise _translated(error, f"the checkout at {at}") from error
    for entry in entries:
        name = f"{under}{entry.name}"
        if entry.is_symlink():
            continue
        if entry.is_dir():
            _gather(entry, f"{name}/", found)
        elif entry.is_file():
            try:
                found[name] = entry.read_bytes()
            except OSError as error:
                raise _translated(error, f"the file at {entry}") from error


def _emptied(directory: Path) -> None:
    """Take away everything inside `directory`, leaving the directory itself."""
    try:
        entries = list(directory.iterdir())
    except OSError as error:
        raise _translated(error, f"the checkout at {directory}") from error
    for entry in entries:
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise _translated(error, f"the leaving at {entry}") from error


def _written(directory: Path, path: str, content: bytes) -> None:
    """Put `content` at a repository-relative `path`, making the directories it needs."""
    at = _at(directory, path)
    try:
        at.parent.mkdir(parents=True, exist_ok=True)
        at.write_bytes(content)
    except OSError as error:
        raise _translated(error, f"the file at {at}") from error


def _removed(directory: Path, path: str) -> None:
    """Take `path` away, and every directory above it that held nothing else.

    Pruning the parents is what keeps a checkout looking like the state it is at: a directory that
    exists only because one file was in it is not part of any state here, so leaving it behind
    would make a restored checkout hold something the state it names does not.
    """
    at = _at(directory, path)
    try:
        at.unlink(missing_ok=True)
    except OSError as error:
        raise _translated(error, f"the file at {at}") from error
    for parent in at.parents:
        if parent == directory or directory not in parent.parents:
            return
        try:
            parent.rmdir()
        except OSError:
            return


def _at(directory: Path, path: str) -> Path:
    """Where a repository-relative, forward-slash separated name is inside `directory`.

    Split rather than pasted on, because a `str` holding `/` is a path only on the platforms that
    spell it that way, and these names keep one spelling on every platform by design.
    """
    return directory.joinpath(*path.split("/"))


def _translated(error: OSError, what: str) -> AglError:
    """The `AglError` an `OSError` means here. Returned, so call sites read as `raise ... from`.

    `_trees.py`'s split, for its reasons: a refusal is something reachable saying no, and
    everything else - a full disk, a mount that went away - left nothing behind, so the same call
    may well succeed later.
    """
    if isinstance(error, PermissionError):
        return DeniedError(f"the filesystem refused {what}: {error}")
    return UpstreamUnavailable(f"the filesystem could not reach {what}: {error}")
