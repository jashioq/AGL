import asyncio
import os
import signal
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Final
from agl.ports.errors import UpstreamUnavailable, UpstreamUnexpected
from agl.ports.verifier import Verifier, VerifierOutcome

__all__ = ["ShellVerifier"]

_DEFAULT_BUILD_TIMEOUT: Final = 1800.0

# Build tools hold locks - a daemon's pid file, a package manager's cache lock - and unlink them on
# SIGTERM, so this is the difference between a tree the next build can use and one that refuses.
_GRACE: Final = 5.0

# Build output is not promised to be UTF-8 - a filename on POSIX is bytes - and `surrogateescape`
# would mint exactly the lone surrogates `ports/run.py` and the store refuse.
_ENCODING: Final = "utf-8"
_UNDECODABLE: Final = "replace"

_CHUNK: Final = 65536

_PASSED: Final = 0

class ShellVerifier(Verifier):
    def __init__(self, build_timeout: float = _DEFAULT_BUILD_TIMEOUT) -> None:
        self._build_timeout = build_timeout

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        process = await _started(command, workdir)
        captured: list[bytes] = []
        try:
            async with asyncio.timeout(self._build_timeout):
                await _drain(process, captured)
                finished = await process.wait()
        except TimeoutError:
            stopped = await _halted(process)
            return VerifierOutcome(
                passed=False,
                status=stopped,
                output=_text(captured) + _expired(self._build_timeout),
            )
        except BaseException:
            _signal(process, signal.SIGTERM)
            raise
        return VerifierOutcome(passed=finished == _PASSED, status=finished, output=_text(captured))

async def _started(command: str, workdir: Path) -> asyncio.subprocess.Process:
    try:
        return await asyncio.create_subprocess_shell(
            command,
            cwd=workdir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        raise UpstreamUnavailable(
            f"the project's build command could not be started in {workdir}: {error}. Nothing "
            f"ran, so this is not a failed build - the same call may well succeed once that "
            f"directory is there and a shell can be started in it"
        ) from error

async def _drain(process: asyncio.subprocess.Process, captured: list[bytes]) -> None:
    if process.stdout is None:
        raise UpstreamUnexpected(
            "the build was started with its output on a pipe and there is no pipe to read. "
            "Nothing can be reported about a build whose output cannot be reached, and the same "
            "call would answer the same way"
        )
    while chunk := await process.stdout.read(_CHUNK):
        captured.append(chunk)

async def _halted(process: asyncio.subprocess.Process) -> int:
    _signal(process, signal.SIGTERM)
    with suppress(TimeoutError):
        async with asyncio.timeout(_GRACE):
            await process.wait()
    _signal(process, signal.SIGKILL)
    return await process.wait()

def _signal(process: asyncio.subprocess.Process, sign: signal.Signals) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, sign)
    except (ProcessLookupError, PermissionError):
        with suppress(ProcessLookupError):
            process.send_signal(sign)

def _text(captured: Sequence[bytes]) -> str:
    return b"".join(captured).decode(_ENCODING, errors=_UNDECODABLE)

def _expired(seconds: float) -> str:
    return (
        f"\n[agl] The build did not finish within {seconds:g}s and was stopped, along with "
        f"everything it had started. What is above is what it had printed by then.\n"
    )
