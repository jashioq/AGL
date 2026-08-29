
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from agl.ports.errors import AglError, DeniedError, UpstreamUnavailable

__all__ = ["applied", "restored", "snapshot"]


def snapshot(directory: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    _gather(directory, "", found)
    return found


def restored(directory: Path, tree: Mapping[str, bytes]) -> None:
    _emptied(directory)
    for path, content in tree.items():
        _written(directory, path, content)


def applied(directory: Path, tree: Mapping[str, bytes], paths: Iterable[str]) -> None:
    for path in paths:
        content = tree.get(path)
        if content is None:
            _removed(directory, path)
        else:
            _written(directory, path, content)


def _gather(at: Path, under: str, found: dict[str, bytes]) -> None:
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
    at = _at(directory, path)
    try:
        at.parent.mkdir(parents=True, exist_ok=True)
        at.write_bytes(content)
    except OSError as error:
        raise _translated(error, f"the file at {at}") from error


def _removed(directory: Path, path: str) -> None:
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
    return directory.joinpath(*path.split("/"))


def _translated(error: OSError, what: str) -> AglError:
    if isinstance(error, PermissionError):
        return DeniedError(f"the filesystem refused {what}: {error}")
    return UpstreamUnavailable(f"the filesystem could not reach {what}: {error}")
