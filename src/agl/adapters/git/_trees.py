
import asyncio
import fcntl
import os
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.ports.errors import AglError, ConflictError, DeniedError, UpstreamUnavailable
from agl.ports.ids import Namespace, RunLabel
from agl.ports.tree_layout import (
    TreesRoot,
    base_worktree,
    run_branch,
    worktree_branch,
    worktree_dir,
)

__all__ = ["delete", "make", "registry_lock", "run_lock", "tidy"]


# Never unlinked. A lock file deleted on release is one a second process can still hold by inode
# while a third creates a new file at the same path and takes that - two holders of one mutex.
_LOCK_FILENAME: Final = "worktrees.lock"

_LOCK_TIMEOUT: Final = 600.0

_LOCK_POLL: Final = 0.05

_LOCK_MODE: Final = 0o644


@asynccontextmanager
async def registry_lock(trees: TreesRoot) -> AsyncIterator[None]:
    lock = trees.path / _LOCK_FILENAME
    handle = _opened(lock)
    try:
        await _hold(handle, lock)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


@asynccontextmanager
async def run_lock(directory: Path, label: str) -> AsyncIterator[None]:
    make(directory)
    handle = _opened_run(directory)
    try:
        _claim(handle, directory, label)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def make(directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _translated(error, f"the run directory at {directory}") from error


def delete(checkout: Path) -> None:
    try:
        shutil.rmtree(checkout)
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as error:
        raise _translated(error, f"the checkout at {checkout}") from error


def tidy(directory: Path) -> None:
    try:
        directory.rmdir()
    except OSError:
        return


@dataclass(frozen=True, slots=True)
class _Place:

    path: Path
    branch: str


def _place(trees: TreesRoot, label: RunLabel, namespace: Namespace | None) -> _Place:
    if namespace is None:
        return _Place(base_worktree(trees, label), run_branch(label))
    return _Place(worktree_dir(trees, label, namespace), worktree_branch(label, namespace))


def _opened(lock: Path) -> int:
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        return os.open(lock, os.O_CREAT | os.O_RDWR, _LOCK_MODE)
    except OSError as error:
        raise _translated(error, f"the worktree lock at {lock}") from error


def _opened_run(directory: Path) -> int:
    try:
        # `flock(2)` excludes on the inode behind a descriptor rather than on a path, and takes one
        # on a directory as readily as on a file - so nothing is ever read or written through this
        # one.
        return os.open(directory, os.O_RDONLY)
    except OSError as error:
        raise _translated(error, f"the run directory at {directory}") from error


def _claim(handle: int, directory: Path, label: str) -> None:
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ConflictError(
            f"the run {label!r} is already live: something else is holding {directory}, and one "
            f"run cannot be walked twice at once. AGL takes that lock for the whole of an `agl "
            f"run` or `agl resume` and lets go of it when that ends, so wait for the invocation "
            f"that has it or stop it. Nothing here has been changed"
        ) from None
    except OSError as error:
        raise _translated(error, f"the run directory at {directory}") from error


async def _hold(handle: int, lock: Path) -> None:
    deadline = time.monotonic() + _LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise ConflictError(
                    f"another process has held the worktree lock at {lock} for more than "
                    f"{_LOCK_TIMEOUT:g}s. It is taken only around adding and pruning worktrees, so "
                    f"either several runs are checking out large trees ahead of this one or the "
                    f"process holding it is wedged; nothing here has been changed"
                ) from None
        except OSError as error:
            raise _translated(error, f"the worktree lock at {lock}") from error
        await asyncio.sleep(_LOCK_POLL)


def _translated(error: OSError, what: str) -> AglError:
    if isinstance(error, PermissionError):
        return DeniedError(f"the filesystem refused {what}: {error}")
    return UpstreamUnavailable(f"the filesystem could not reach {what}: {error}")
