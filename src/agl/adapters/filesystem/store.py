
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Final

from agl.adapters.filesystem._documents import (
    _ENCODING,
    _encoded,
    _entry_address,
    _record_address,
    _scope_address,
)
from agl.ports.errors import (
    AglError,
    DeniedError,
    InputError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)
from agl.ports.home_layout import AglHome, RunScope, run_record, scope_dir, step_entry
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store

__all__ = ["FilesystemStore"]


_PARTIAL_PREFIX: Final = "partial-"

_INDENT: Final = 2

_PROBE: Final = Namespace("probe")


class FilesystemStore(Store):

    def __init__(self, home: AglHome) -> None:
        self._home = home

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        return _read(run_record(self._home, scope), _record_address(scope))

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        address = _record_address(scope)
        payload = _encoded(value, address, indent=_INDENT)
        _write_atomically(run_record(self._home, scope), payload, address)

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        address = _entry_address(scope, step, digest)
        return _read(step_entry(self._home, scope, step, digest), address)

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        address = _entry_address(scope, step, digest)
        payload = _encoded(value, address, indent=_INDENT)
        _write_atomically(step_entry(self._home, scope, step, digest), payload, address)

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        container = _worktrees_container(self._home, scope)
        try:
            names = sorted(child.name for child in container.iterdir() if child.is_dir())
        except (FileNotFoundError, NotADirectoryError):
            return ()
        except OSError as error:
            raise _translated(error, f"the namespaces of {_scope_address(scope)}") from error
        found: list[Namespace] = []
        for name in names:
            try:
                found.append(Namespace(name))
            except InputError:
                continue
        return tuple(found)

    async def remove(self, scope: RunScope) -> None:
        try:
            shutil.rmtree(scope_dir(self._home, scope))
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError as error:
            raise _translated(error, f"the removal of {_scope_address(scope)}") from error


def _worktrees_container(home: AglHome, scope: RunScope) -> Path:
    return scope_dir(home, scope.inside(_PROBE)).parent


def _write_atomically(destination: Path, payload: bytes, address: str) -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # `dir=` is load-bearing: `os.replace` is atomic within one filesystem and raises `EXDEV`
        # across two, and the system temp directory is its own mount on plenty of machines.
        handle, partial = tempfile.mkstemp(dir=destination.parent, prefix=_PARTIAL_PREFIX)
    except OSError as error:
        raise _translated(error, address) from error
    try:
        with os.fdopen(handle, "wb") as opened:
            opened.write(payload)
            opened.flush()
            # The file and never the parent directory: this stops a crash publishing a name over
            # unwritten content, where the directory's would only make the rename itself survive
            # one.
            os.fsync(opened.fileno())
        os.replace(partial, destination)
    except OSError as error:
        with suppress(OSError):
            os.unlink(partial)
        raise _translated(error, address) from error


def _read(path: Path, address: str) -> dict[str, JsonValue] | None:
    try:
        text = path.read_text(encoding=_ENCODING)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except UnicodeDecodeError as error:
        raise UpstreamUnexpected(
            f"{address} is not {_ENCODING}: AGL writes these files whole and writes them as "
            f"{_ENCODING}, so this one did not come from AGL. {error}"
        ) from error
    except OSError as error:
        raise _translated(error, address) from error
    try:
        document: object = json.loads(text)
    except json.JSONDecodeError as error:
        raise UpstreamUnexpected(
            f"{address} is not JSON: {error}. AGL publishes these files with one atomic rename, "
            f"so a half-written one is not a state this store can produce"
        ) from error
    if not isinstance(document, dict):
        raise UpstreamUnexpected(
            f"{address} holds a {type(document).__name__}, and both kinds of document AGL stores "
            f"are JSON objects"
        )
    return document


def _translated(error: OSError, address: str) -> AglError:
    # `PermissionError` is `EACCES` and `EPERM`, and nothing of AGL's own.
    if isinstance(error, PermissionError):
        return DeniedError(f"the filesystem refused {address}: {error}")
    return UpstreamUnavailable(f"the filesystem could not reach {address}: {error}")
