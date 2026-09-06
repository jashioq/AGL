import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final
from agl.ports.errors import NotFoundError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.sync import Syncer, SyncOutcome

__all__ = ["UvSyncer"]

_UV: Final = "uv"
_SYNC: Final = "sync"

# Measured against uv 0.11.29. Without it, a member of the workspace is built and installed into
# the venv, and both outcomes are wrong here: a workflow written as `agl new` writes one carries no
# build system, so building it fails and takes the resolution of every other member's dependencies
# down with it; one an operator gave a build system to installs as an editable `.pth`, which is
# inert because AGL appends site-packages to `sys.path` rather than running inside that venv, or as
# a real copy, which then shadows the source in `workflows/`. The dependencies are resolved and
# installed either way, which is the whole of what a workspace venv is for.
_NO_INSTALL_WORKSPACE: Final = "--no-install-workspace"

# The interpreter the venv is built for, and it is this process's own rather than a setting. uv
# picks one otherwise, and a venv built for another interpreter is invisible:
# `config/workspace_path.py` composes the site-packages directory from the running interpreter's
# `lib/` name, so a workflow's imports would fail with the packages installed and nothing to say so.
_PYTHON: Final = "--python"

# Where the workspace is, passed rather than set as the child's `cwd`: an unreadable `cwd` raises
# the same `FileNotFoundError` a missing binary does, and the two would be reported as one.
_DIRECTORY: Final = "--directory"

# uv discovers a project by walking *up* from the directory it is given, so a workspace with no
# project file of its own would sync whichever ancestor has one - `$HOME/pyproject.toml`, a
# checkout the home happens to sit inside - and build that project's venv. Named here rather than
# reached from `ports/home_layout.py` because what it spells is uv's discovery rule.
_PROJECT_FILE: Final = "pyproject.toml"

_SYNCED: Final = 0

# uv's output is not promised to be UTF-8 - it quotes filenames, and a filename on POSIX is bytes -
# and `surrogateescape` would mint exactly the lone surrogates `ports/run.py` and the store refuse.
_ENCODING: Final = "utf-8"
_UNDECODABLE: Final = "replace"

_CHUNK: Final = 65536

class UvSyncer(Syncer):
    def __init__(self, uv_path: Path | None = None) -> None:
        self._uv = str(uv_path) if uv_path is not None else _UV

    async def sync(self, workspace: Path) -> SyncOutcome:
        _check_project_file(workspace)
        process = await self._started(workspace)
        captured: list[bytes] = []
        await _drain(process, captured)
        finished = await process.wait()
        return SyncOutcome(synced=finished == _SYNCED, status=finished, output=_text(captured))

    # No deadline, unlike the build gate: this is a command an operator is waiting at, the child is
    # left in this process group so a Ctrl-C at that terminal reaches uv itself, and a resolution
    # that takes minutes against a cold cache is the ordinary case rather than a hang.
    async def _started(self, workspace: Path) -> asyncio.subprocess.Process:
        try:
            return await asyncio.create_subprocess_exec(
                self._uv,
                _SYNC,
                _NO_INSTALL_WORKSPACE,
                _PYTHON,
                sys.executable,
                _DIRECTORY,
                str(workspace),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as error:
            raise UpstreamUnavailable(_unstartable(self._uv, error)) from error

def _check_project_file(workspace: Path) -> None:
    if not (workspace / _PROJECT_FILE).is_file():
        raise NotFoundError(
            f"there is no workspace to sync at {workspace}: a workspace is a directory holding a "
            f"{_PROJECT_FILE} that names its workflows, and that file is not there. Nothing was "
            f"run, deliberately - uv reads the first {_PROJECT_FILE} it finds walking up from the "
            f"directory it is given, so a sync started here would install some enclosing "
            f"project's dependencies and build that project's environment instead. `agl new` "
            f"writes the workspace along with the first workflow in it"
        )

async def _drain(process: asyncio.subprocess.Process, captured: list[bytes]) -> None:
    if process.stdout is None:
        raise UpstreamUnexpected(
            "uv was started with its output on a pipe and there is no pipe to read. Nothing can "
            "be reported about a sync whose output cannot be reached, and the same call would "
            "answer the same way"
        )
    while chunk := await process.stdout.read(_CHUNK):
        captured.append(chunk)

def _text(captured: Sequence[bytes]) -> str:
    return b"".join(captured).decode(_ENCODING, errors=_UNDECODABLE)

def _unstartable(uv: str, error: OSError) -> str:
    if isinstance(error, FileNotFoundError):
        return (
            f"uv is not installed, or {uv!r} is not on PATH: {error.strerror}. AGL installs a "
            f"workspace's dependencies with uv and ships none of its own - so until uv is there, "
            f"a workflow that imports anything past `agl` has nothing to import it from. Install "
            f"it and run this again: `brew install uv`, `pipx install uv`, or `curl -LsSf "
            f"https://astral.sh/uv/install.sh | sh`. Nothing was attempted, so nothing in the "
            f"workspace has changed"
        )
    if isinstance(error, PermissionError):
        return (
            f"uv was found at {uv!r} and could not be executed: {error.strerror}. That is a file "
            f"mode or a quarantine attribute on the binary rather than anything about this "
            f"workspace, and nothing in it has changed"
        )
    return (
        f"AGL could not start uv at {uv!r}: {error}. Nothing was installed, so the same call may "
        f"well succeed once whatever stopped the process from starting is fixed"
    )
