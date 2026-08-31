
import argparse
import asyncio
import sys
from typing import Final

from agl import api
from agl.cli.commands import Registered
from agl.ports.errors import InternalError
from agl.ports.ids import RunLabel
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "clear"

_LABEL: Final = "label"
_FORCE: Final = "force"

_FORCE_FLAGS: Final = ("-f", "--force")

_NOTHING_TO_REPORT: Final = 0

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]


def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="take a run away",
        description=(
            "Take a run away: its checkouts, its child branches and its records. The run's own "
            "branch is deleted only if the base ref already contains it, and otherwise kept with "
            "a warning - `-f` deletes it regardless."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _LABEL,
        metavar="<label>",
        help="the run to take away: the name `agl run -n <label>` gave it",
    )
    parser.add_argument(
        *_FORCE_FLAGS,
        dest=_FORCE,
        action="store_true",
        help="delete the run's own branch even if the base ref does not contain it yet",
    )
    return parser


def execute(registered: Registered, parsed: argparse.Namespace) -> int:
    label = RunLabel(_said(parsed, _LABEL))
    force = _flagged(parsed, _FORCE)
    project, services = registered()
    kept = asyncio.run(api.clear(services, project, label, force=force))
    print(f"clear {str(label)!r} finished")
    if kept is not None:
        print(kept, file=sys.stderr)
    return _NOTHING_TO_REPORT


def _said(parsed: argparse.Namespace, dest: str) -> str:
    value = getattr(parsed, dest)
    if isinstance(value, str):
        return value
    raise InternalError(_disagreeing(value, dest))


def _flagged(parsed: argparse.Namespace, dest: str) -> bool:
    value = getattr(parsed, dest)
    if isinstance(value, bool):
        return value
    raise InternalError(_disagreeing(value, dest))


def _disagreeing(value: object, dest: str) -> str:
    return (
        f"the `{NAME}` parser produced {value!r} for {dest!r}, and every argument this module "
        f"declares is either a string it took off the command line or a flag that is on or off. "
        f"That is AGL's own bug: the parser and the reader are in one file and they disagree"
    )
