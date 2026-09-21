import argparse
import sys
from typing import Final
from agl import api
from agl.cli.commands import _said
from agl.config.placement import Removed
from agl.config.questions import Confirm
from agl.ports.home_layout import AglHome
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "remove"

_WORKFLOW: Final = "workflow"

_REMOVED: Final = "Removed"

_NOTHING_TO_REPORT: Final = 0

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="Remove a workflow.",
        description=(
            "Remove a workflow's directory from your AGL workspace, after asking first. Runs it "
            "started can no longer be resumed, only cleared."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _WORKFLOW,
        metavar="<workflow>",
        help="Name of the workflow's directory in your AGL workspace.",
    )
    return parser

def execute(home: AglHome, parsed: argparse.Namespace, *, confirm: Confirm) -> int:
    removed = api.remove(home, _said(parsed, _WORKFLOW, command=NAME), confirm)
    # A decline is the operator's answer, so it moves no status, and stdout stays empty to say so.
    if removed is None:
        return _NOTHING_TO_REPORT
    # Flushed, because a piped stdout is block-buffered and the note below would otherwise land
    # ahead of it in a merged log.
    print(f'{_REMOVED} "{removed.entry.name}"', flush=True)
    # Never on stdout, for `cli/commands/workflows.py`'s reason: a line there is a name a script
    # reads, and this is a note about what the delete could not take.
    if removed.leftover is not None:
        print(_left_behind(removed), file=sys.stderr)
    return _NOTHING_TO_REPORT

def _left_behind(removed: Removed) -> str:
    return (
        f"{removed.entry.name} is out of the workspace, but not all of it could be deleted: what "
        f"is left is in {removed.leftover}, a dot-led directory neither uv nor `agl workflows` "
        f"reads. Delete it by hand"
    )
