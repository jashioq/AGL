
import asyncio
import os
import signal
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.ports.errors import (
    AglError,
    InputError,
    UpstreamError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)

__all__ = ["GitRunner", "unreadable"]

_DEFAULT_TIMEOUT: Final = 120.0

# git installs handlers that unlink its own `*.lock` files on a fatal signal, so SIGTERM plus a
# moment is the difference between a usable repository and a stale `index.lock`.
_GRACE: Final = 5.0

# git does not promise UTF-8 - a path on POSIX is bytes - and `surrogateescape` would mint exactly
# the lone surrogates `ports/run.py` and the store refuse, three layers from here.
_ENCODING: Final = "utf-8"
_UNDECODABLE: Final = "replace"

# git's own convention for a question answered by the exit status: 0 is yes, 1 is no, anything else
# failed. `merge-base --is-ancestor`, `diff --quiet` and `rev-parse --verify --quiet` all spell it
# so.
_ANSWERED_NO: Final = 1

_REASON_LIMIT: Final = 500

_REPOSITORY_PROBE: Final = ("rev-parse", "--git-dir")


def unreadable(what: str, output: str) -> UpstreamUnexpected:
    return UpstreamUnexpected(
        f"git answered with something AGL cannot read as {what}: {_capped(output)!r}. The "
        f"repository is fine and this adapter's reading of it is not, so the same call will "
        f"answer the same way"
    )


class GitRunner:

    def __init__(self, repository: Path, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._repository = repository
        self._timeout = timeout

    async def run(
        self,
        *argv: str,
        cwd: Path | None = None,
        refusal: type[AglError],
        timeout: float | None = None,
    ) -> str:
        result = await self._completed(argv, cwd, timeout)
        if result.code != 0:
            raise await self._refused(result, argv, cwd, timeout, refusal)
        return result.out

    async def answers(
        self,
        *argv: str,
        cwd: Path | None = None,
        refusal: type[AglError],
        timeout: float | None = None,
    ) -> bool:
        result = await self._completed(argv, cwd, timeout)
        if result.code == 0:
            return True
        if result.code == _ANSWERED_NO:
            return False
        raise await self._refused(result, argv, cwd, timeout, refusal)

    async def _completed(
        self, argv: Sequence[str], cwd: Path | None, timeout: float | None
    ) -> _Completed:
        where = self._repository if cwd is None else cwd
        seconds = self._timeout if timeout is None else timeout
        process = await _spawned(argv, where)
        try:
            async with asyncio.timeout(seconds):
                out, err = await process.communicate()
        except TimeoutError:
            await _stop(process)
            raise UpstreamUnavailable(
                f"{_asked(argv, where)} did not finish within {seconds:g}s and was stopped. "
                f"Whatever it had already done is done, and git unlinks its own lock files when "
                f"it is asked to stop, so the same call may well succeed later"
            ) from None
        except BaseException:
            _signal(process, signal.SIGTERM)
            raise
        code = process.returncode if process.returncode is not None else 0
        return _Completed(code, _text(out), _text(err))

    async def _refused(
        self,
        result: _Completed,
        argv: Sequence[str],
        cwd: Path | None,
        timeout: float | None,
        refusal: type[AglError],
    ) -> AglError:
        where = self._repository if cwd is None else cwd
        asked = _asked(argv, where)
        if result.code < 0:
            return UpstreamUnexpected(
                f"{asked} was killed by signal {-result.code} rather than answering. git refused "
                f"nothing here - it did not get that far - so what stopped it is outside this "
                f"repository and outside AGL"
            )
        if not await self._readable(where, timeout):
            return UpstreamUnavailable(
                f"{asked} failed, and git cannot read a repository there at all. Nothing was "
                f"attempted, so the same call may well succeed once the repository is reachable: "
                f"{_reason(result)}"
            )
        return refusal(f"git refused {asked}: {_reason(result)}")

    async def _readable(self, where: Path, timeout: float | None) -> bool:
        try:
            probe = await self._completed(_REPOSITORY_PROBE, where, timeout)
        except UpstreamError:
            return False
        return probe.code == 0


@dataclass(frozen=True, slots=True)
class _Completed:

    code: int
    out: str
    err: str


async def _spawned(argv: Sequence[str], where: Path) -> asyncio.subprocess.Process:
    try:
        return await asyncio.create_subprocess_exec(
            "git",
            *argv,
            cwd=where,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # A git that stops to ask for a credential has no terminal to ask on and waits out the
            # deadline; `stdin=DEVNULL` above closes the other door, an editor.
            env=os.environ | {"GIT_TERMINAL_PROMPT": "0"},
        )
    except ValueError as error:
        raise InputError(
            f"{_asked(argv, where)} could not be started: {error}. A child process is handed its "
            f"arguments, its working directory and its environment as bytes, and something here "
            f"has no encoding at all - a lone surrogate, or a NUL inside a string. Nothing ran, "
            f"and unlike every other way a start fails this one will never succeed: the same text "
            f"encodes the same way every time, so it is the value that has to change"
        ) from error
    except OSError as error:
        raise UpstreamUnavailable(
            f"{_asked(argv, where)} could not be started: {error}. Nothing ran, so the same call "
            f"may well succeed once git is installed and the directory is there"
        ) from error


async def _stop(process: asyncio.subprocess.Process) -> None:
    _signal(process, signal.SIGTERM)
    try:
        async with asyncio.timeout(_GRACE):
            await process.wait()
    except TimeoutError:
        _signal(process, signal.SIGKILL)
        await process.wait()


def _signal(process: asyncio.subprocess.Process, sign: signal.Signals) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError, PermissionError):
        process.send_signal(sign)


def _text(raw: bytes) -> str:
    return raw.decode(_ENCODING, errors=_UNDECODABLE)


def _asked(argv: Sequence[str], where: Path) -> str:
    spelled = " ".join(
        part if part and not any(character.isspace() for character in part) else repr(part)
        for part in argv
    )
    return f"`git {spelled}` in {where}"


def _reason(result: _Completed) -> str:
    return _capped(result.err.strip()) or _capped(result.out.strip()) or f"exit {result.code}"


def _capped(text: str) -> str:
    return text if len(text) <= _REASON_LIMIT else f"{text[:_REASON_LIMIT]}..."
