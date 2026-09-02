import argparse
import asyncio
from typing import Final
from agl import api
from agl.cli.commands import Registered, _said
from agl.ports.ids import RunLabel
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "clear"

_LABEL: Final = "label"

_NOTHING_TO_REPORT: Final = 0

_SEPARATOR: Final = ", "

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="take a run away",
        description=(
            "Take a run away, whole: its checkouts, its branches - the run's own included, "
            "whether or not its work is in the base ref yet - and its records. Nothing is "
            "asked first and no flag changes it. Committed work is reachable afterwards only "
            "through `git reflog`; what a checkout was holding uncommitted is not reachable "
            "at all. What went is listed on stdout."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _LABEL,
        metavar="<label>",
        help="the run to take away: the name `agl run -n <label>` gave it",
    )
    return parser

def execute(registered: Registered, parsed: argparse.Namespace) -> int:
    label = RunLabel(_said(parsed, _LABEL, command=NAME))
    project, services = registered()
    cleared = asyncio.run(api.clear(services, project, label))
    print(f"clear {str(label)!r} finished")
    print(f"branches gone: {_SEPARATOR.join(cleared.branches)}")
    print(f"worktrees gone: {_SEPARATOR.join(cleared.worktrees)}")
    return _NOTHING_TO_REPORT
