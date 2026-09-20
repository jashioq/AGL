import asyncio
import contextlib
import tempfile
from pathlib import Path
from typing import Final
from claude_agent_sdk import ClaudeAgentOptions
from agl.ports.agent import Installation, VersionRange

__all__ = ["TESTED", "TOOL", "probed"]

TOOL: Final = "the Claude Code CLI"

# What the binary `claude_agent_sdk` 0.2.157 bundles reports for itself, and the release this
# adapter's sessions were exercised against. `ports/agent.py`'s `ClaudeEffort` names the same one
# as the source of its members, and the two move together.
#
# A point and not a span, although two releases have been run against: this binary is not
# separately installable, so upgrading the package replaces it and the earlier one is gone from the
# machine that would have to re-exercise it. A span whose lower end nothing can reach again claims
# a release was tested where all that is left is that it once was.
TESTED: Final = VersionRange(lowest="2.1.277", highest="2.1.277")

_VERSION: Final = ("-v",)

# Measured at 0.1s against the bundled binary, so ten seconds is a process that is not coming back
# rather than a machine under load.
_SECONDS: Final = 10.0

async def probed(cli_path: Path | None) -> Installation:
    """What the binary this adapter would start reports of itself, or nothing where none was."""
    where = _resolved(cli_path)
    return Installation(
        tool=TOOL,
        version=None if where is None else await _reported(where),
        tested=TESTED,
        efforts={},
        where=where,
    )

# `SubprocessCLITransport.__init__` takes `options.cli_path` as the binary outright and calls
# `_find_cli` only where that is `None`; `_find_cli` prefers the bundled binary over a `claude` on
# PATH. Asking the SDK's own resolver rather than copying its order is what keeps the version this
# reports to the binary a session would actually start.
def _resolved(cli_path: Path | None) -> str | None:
    if cli_path is not None:
        return str(cli_path)
    try:
        # Off the SDK's public surface, so it is imported here rather than above and every
        # failure of it caught: a resolver that has moved, or that found nothing, costs a version
        # nobody could read, where a module-level import would cost an AGL that will not start at
        # all - over a question that only ever warns.
        from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

        # Options because that is where the resolver reads a configured path from, and this one
        # carries none by the branch above. Built closed all the same: every `ClaudeAgentOptions`
        # in this package is held to the three settings that shut the target repository out, by
        # `tests/adapters/test_claude_code_runner.py`'s scan of the package's own source.
        options = ClaudeAgentOptions(setting_sources=[], strict_mcp_config=True, settings=None)
        return SubprocessCLITransport(prompt="", options=options)._find_cli()
    except Exception:
        return None

async def _reported(binary: str) -> str | None:
    with tempfile.TemporaryDirectory(prefix="agl-version-") as elsewhere:
        try:
            child = await asyncio.create_subprocess_exec(
                binary,
                *_VERSION,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=elsewhere,
            )
        except OSError:
            return None
        try:
            async with asyncio.timeout(_SECONDS):
                said, _ = await child.communicate()
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                child.kill()
            await child.wait()
            return None
        if child.returncode != 0:
            return None
    # Measured output is `2.1.277 (Claude Code)`: the version is the first word, and the
    # parenthetical after it is the product's name rather than any part of one.
    words = said.decode("utf-8", errors="replace").split()
    return words[0] if words else None
