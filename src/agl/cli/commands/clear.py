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
        help="Delete a run with its worktrees and branches.",
        description=(
            "Delete a run with its worktrees, its branches and any uncommitted "
            "changes, merged or not. To get the work back later, note its branch's sha first; "
            "otherwise `git fsck --unreachable` finds its commits until git prunes them."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _LABEL,
        metavar="<label>",
        help="Name of the run to delete, as given to `agl run -n`.",
    )
    return parser

def execute(registered: Registered, parsed: argparse.Namespace) -> int:
    label = RunLabel(_said(parsed, _LABEL, command=NAME))
    project, services = registered()
    cleared = asyncio.run(api.clear(services, project, label))
    print(f'Run "{label}" cleared')
    print(f"Deleted branches: {_SEPARATOR.join(cleared.branches)}")
    print(f"Deleted worktrees: {_SEPARATOR.join(cleared.worktrees)}")
    return _NOTHING_TO_REPORT
