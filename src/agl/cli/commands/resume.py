import argparse
import asyncio
from collections.abc import Iterable
from importlib.metadata import EntryPoint
from typing import Final
from agl import api
from agl.cli.commands import Registered, _print_replays, _said
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
        help="continue a run from its record",
        description=(
            "Continue a run that already exists. It takes the label and nothing else: the "
            "workflow, the base ref and the parameters are read back from the run's own record, "
            "which is what `agl run` wrote them there for."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _LABEL,
        metavar="<label>",
        help="the run to continue: the name `agl run -n <label>` gave it",
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
    replayed = asyncio.run(
        api.resume(services, project, label, syncer=syncer, home=home, points=points)
    )
    _print_replays(label, replayed)
    print(f"resume {str(label)!r} finished")
    return _NOTHING_TO_REPORT
