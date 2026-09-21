import argparse
import asyncio
from collections.abc import Iterable
from importlib.metadata import EntryPoint
from typing import Final
from agl import api
from agl.cli.commands import Registered, _print_finished, _print_replays, _said
from agl.ports.home_layout import AglHome
from agl.ports.ids import RunLabel
from agl.ports.sync import Syncer
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "resume"

_LABEL: Final = "label"

_NOTHING_TO_REPORT: Final = 0

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="Continue a run.",
        description="Continue a run with the workflow, ref and params it was started with.",
        allow_abbrev=False,
    )
    parser.add_argument(
        _LABEL,
        metavar="<label>",
        help="Name of the run to continue, as given to `agl run -n`.",
    )
    return parser

def execute(
    registered: Registered,
    parsed: argparse.Namespace,
    *,
    syncer: Syncer,
    home: AglHome,
    points: Iterable[EntryPoint] | None = None,
) -> int:
    label = RunLabel(_said(parsed, _LABEL, command=NAME))
    project, services = registered()
    finished = asyncio.run(
        api.resume(services, project, label, syncer=syncer, home=home, points=points)
    )
    _print_replays(label, finished)
    _print_finished(label, finished)
    return _NOTHING_TO_REPORT
