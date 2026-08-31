
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from agl.adapters.git._trees import _translated

__all__ = ["apply", "restore", "snapshot"]


def snapshot(directory: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    _gather(directory, "", found)
    return found


def restore(directory: Path, tree: Mapping[str, bytes]) -> None:
    _empty(directory)
    for path, content in tree.items():
        _write(directory, path, content)


def apply(directory: Path, tree: Mapping[str, bytes], paths: Iterable[str]) -> None:
    for path in paths:
        content = tree.get(path)
        if content is None:
            _remove(directory, path)
        else:
            _write(directory, path, content)


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


def _empty(directory: Path) -> None:
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


def _write(directory: Path, path: str, content: bytes) -> None:
    at = _at(directory, path)
    try:
        at.parent.mkdir(parents=True, exist_ok=True)
        at.write_bytes(content)
    except OSError as error:
        raise _translated(error, f"the file at {at}") from error


def _remove(directory: Path, path: str) -> None:
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
