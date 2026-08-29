
import argparse
import asyncio
from collections.abc import Iterable
from importlib.metadata import EntryPoint
from typing import Final

from agl import api
from agl.cli.commands import Registered
from agl.ports.errors import InternalError
from agl.ports.ids import RunLabel
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "resume"

_LABEL: Final = "label"

_NOTHING_TO_REPORT: Final = 0

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
    points: Iterable[EntryPoint] | None = None,
) -> int:
    label = RunLabel(_said(parsed, _LABEL))
    project, services = registered()
    asyncio.run(api.resume(services, project, label, points=points))
    print(f"resume {str(label)!r} finished")
    return _NOTHING_TO_REPORT


def _said(parsed: argparse.Namespace, dest: str) -> str:
    value = getattr(parsed, dest)
    if isinstance(value, str):
        return value
    raise InternalError(
        f"the `{NAME}` parser produced {value!r} for {dest!r}, and every argument this module "
        f"declares is a string it took off the command line. That is AGL's own bug: the parser and "
        f"the reader are in one file and they disagree"
    )
