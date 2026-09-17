import asyncio
import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final
from agl.adapters.openai.translate import model_slug
from agl.ports.agent import Installation, ModelEfforts, ModelId, OpenAI, VersionRange

__all__ = ["TESTED", "TOOL", "probed"]

TOOL: Final = "the Codex CLI"

# The release this adapter's command line and its event reading were exercised against, and the one
# `ports/agent.py`'s `OpenAIEffort` names as the source of its members.
TESTED: Final = VersionRange(lowest="0.152.0", highest="0.152.0")

_VERSION: Final = ("--version",)

# A second spawn, and it is the only place a per-model level set is derivable without a paid call.
# It asks for no credential: against a home holding none it prints the same catalogue the binary
# carries, over no connection, and the three models below list the same levels and defaults there
# as against an authenticated one.
_CATALOGUE: Final = ("debug", "models")

# `--version` writes `$CODEX_HOME/tmp/arg0/…` before it answers, and AGL sets no `CODEX_HOME`, so a
# probe on every run would churn the operator's own. A fresh directory is what keeps a question
# that only reads from writing, and it must be a real one: an empty value is not a redirect but a
# fall back to the home it was meant to replace.
_HOME: Final = "CODEX_HOME"

# Measured at 11ms for the version and 18ms for the catalogue, so ten seconds is a process that is
# not coming back rather than a machine under load.
_SECONDS: Final = 10.0

_MODELS: Final = "models"
_SLUG: Final = "slug"
_LEVELS: Final = "supported_reasoning_levels"
_LEVEL: Final = "effort"
_DEFAULT: Final = "default_reasoning_level"

_MODELS_BY_SLUG: Final[Mapping[str, ModelId]] = MappingProxyType(
    {model_slug(model): model for model in OpenAI}
)

async def probed(cli: str) -> Installation:
    """Both answers the tool gives about itself: its version, and what each model reasons at."""
    with tempfile.TemporaryDirectory(prefix="agl-version-") as elsewhere:
        environment = {**os.environ, _HOME: elsewhere}
        version = _spelled(await _output(cli, _VERSION, elsewhere, environment))
        efforts = _catalogued(await _output(cli, _CATALOGUE, elsewhere, environment))
    return Installation(tool=TOOL, version=version, tested=TESTED, efforts=efforts, where=cli)

async def _output(
    cli: str, arguments: tuple[str, ...], elsewhere: str, environment: Mapping[str, str]
) -> bytes | None:
    try:
        child = await asyncio.create_subprocess_exec(
            cli,
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=elsewhere,
            env=dict(environment),
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
    return said if child.returncode == 0 else None

# Measured output is exactly `codex-cli 0.152.0`: the tool's own name, then the version. Anything
# else is a spelling this reading was not written for, and reports nothing rather than a guess.
def _spelled(said: bytes | None) -> str | None:
    if said is None:
        return None
    words = said.decode("utf-8", errors="replace").split()
    return words[1] if len(words) == 2 else None

def _catalogued(said: bytes | None) -> dict[ModelId, ModelEfforts]:
    found: dict[ModelId, ModelEfforts] = {}
    if said is None:
        return found
    try:
        listing = json.loads(said)
    except ValueError:
        return found
    if not isinstance(listing, dict):
        return found
    models = listing.get(_MODELS)
    if not isinstance(models, list):
        return found
    for entry in models:
        if not isinstance(entry, dict):
            continue
        slug = entry.get(_SLUG)
        model = _MODELS_BY_SLUG.get(slug) if isinstance(slug, str) else None
        levels = _offered(entry.get(_LEVELS))
        # An entry naming no level at all is left out rather than kept as an empty set: a set says
        # what a model offers, and an empty one claims it offers nothing, which no listing said.
        if model is not None and levels:
            found[model] = ModelEfforts(levels=levels, default=_text(entry.get(_DEFAULT)))
    return found

# Each entry is an object and not a bare level: the level is under `effort` beside a description
# the tool writes for its own menu, and nothing here reports that description.
#
# The listing's order is kept rather than sorted, for the reason `ports/agent.py` gives beside
# `ModelEfforts.levels`. Measured over 0.152.0's whole catalogue: each of its ten models lists an
# ascending prefix of `low, medium, high, xhigh, max, ultra` - four stopping at `xhigh` and two at
# `max` - and each level carries a description that ascends with it.
def _offered(levels: object) -> tuple[str, ...]:
    if not isinstance(levels, list):
        return ()
    found: list[str] = []
    for entry in levels:
        if isinstance(entry, dict):
            level = entry.get(_LEVEL)
            if isinstance(level, str) and level and level not in found:
                found.append(level)
    return tuple(found)

def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
