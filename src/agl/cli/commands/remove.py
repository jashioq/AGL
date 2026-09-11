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

_REMOVED: Final = "removed"

_NOTHING_TO_REPORT: Final = 0

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="take a workflow out of your workspace",
        description=(
            "Take one entry out of your AGL workspace's workflows/ directory: a workflow's "
            "directory and everything under it, or a link, of which the link alone goes and never "
            "what it names. The name is the entry's own - the directory `agl get` placed or `agl "
            "new` wrote - which need not be a name `agl run` takes, and the question put before "
            "anything goes names every workflow it declares: y removes it, n or a stdin at its end "
            "or closed keeps it, and anything else asks again. An entry another workflow depends "
            "on is refused, and so is a dot-led one. Nothing is installed or uninstalled here - "
            "the next install, which `agl run` and `agl resume` each begin with, brings the "
            "environment up to date. A run started by a workflow that is gone cannot be resumed, "
            "and `agl clear <label>` still takes it away."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _WORKFLOW,
        metavar="<workflow>",
        help="the workflow to remove, by the name of its own entry in workflows/",
    )
    return parser

def execute(home: AglHome, parsed: argparse.Namespace, *, confirm: Confirm) -> int:
    removed = api.remove(home, _said(parsed, _WORKFLOW, command=NAME), confirm)
    # A decline is the operator's answer, so it moves no status, and stdout stays empty to say so.
    if removed is None:
        return _NOTHING_TO_REPORT
    # Flushed, because a piped stdout is block-buffered and the note below would otherwise land
    # ahead of it in a merged log.
    print(f"{_REMOVED} {removed.entry.name}", flush=True)
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
