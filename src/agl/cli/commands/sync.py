import argparse
import asyncio
from typing import Final
from agl import api
from agl.ports.errors import UpstreamError
from agl.ports.home_layout import AglHome
from agl.ports.sync import Syncer, SyncOutcome
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "sync"

_NOTHING_TO_REPORT: Final = 0

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    return commands.add_parser(
        NAME,
        help="install what your workspace's workflows declare",
        description=(
            "Install the dependencies the workflows in your AGL workspace declare, into an "
            "environment beside them that AGL adds to a run's import path. The workspace is made "
            "if it is not there yet. Nothing about a repository is read: a sync addresses the "
            "workflows you wrote and no project."
        ),
        allow_abbrev=False,
    )

def execute(home: AglHome, syncer: Syncer) -> int:
    outcome = asyncio.run(api.sync_workspace(syncer, home))
    if not outcome.synced:
        raise UpstreamError(_refused(outcome))
    if outcome.output:
        print(outcome.output.rstrip("\n"))
    print(f"{NAME} finished")
    return _NOTHING_TO_REPORT

def _refused(outcome: SyncOutcome) -> str:
    return (
        f"the sync was refused: uv exited {outcome.status} rather than 0, so what the workflows in "
        f"your workspace declare is not installed and a run that imports one of those packages "
        f"will not find it. Nothing above uv decided this and nothing above it can explain it - a "
        f"resolution that cannot be satisfied, an index that could not be reached and a package "
        f"that will not build all arrive here as the same non-zero exit - so what uv said is "
        f"printed whole below rather than summarised:\n\n{outcome.output.rstrip()}"
    )
