import argparse
import asyncio
import sys
from pathlib import Path
from typing import Final
from agl import api
from agl.cli.commands import _said
from agl.ports.home_layout import AglHome, workspace_dir
from agl.ports.ids import WorkflowName
from agl.ports.sync import Syncer
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "new"

_WORKFLOW: Final = "workflow"

_NOTHING_TO_REPORT: Final = 0

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="write a new workflow into your workspace",
        description=(
            "Write a new workflow: a directory under your AGL workspace holding a module, and a "
            "pyproject.toml declaring it under the name you give here. The workspace is made if "
            "it is not there yet. What is written runs as it stands - `agl run <workflow>` "
            "against it does nothing and succeeds - so the first edit is yours to make rather "
            "than a stub to fill in. There is no list in AGL to add it to: the directory is the "
            "whole of it, and what the workspace's workflows declare is installed on the way out."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _WORKFLOW,
        metavar="<workflow>",
        help="the workflow to write: its directory, its module, and the name `agl run` takes",
    )
    return parser

def execute(home: AglHome, parsed: argparse.Namespace, *, syncer: Syncer) -> int:
    name = WorkflowName(_said(parsed, _WORKFLOW, command=NAME))
    written = asyncio.run(api.new_workflow(syncer, home, name))
    print(f"new wrote {written}")
    # Never on stdout, for `cli/commands/__init__.py`'s reason: what a machine consumes goes there
    # and this is a note about it. The workspace is composed from `ports/home_layout.py` rather
    # than walked up to from `written`, which would be this command deriving a layout it is handed.
    print(_where_to_open(workspace_dir(home)), file=sys.stderr)
    return _NOTHING_TO_REPORT

# The two editors an operator writes a workflow in both look for an interpreter at the root of what
# is open, and the workspace venv sits at the workspace root - so an editor opened on the workflow
# directory finds no interpreter carrying AGL. That is measured PyCharm and VS Code behaviour, and
# the directory just written is the one an operator's instinct reaches for.
def _where_to_open(workspace: Path) -> str:
    return (
        f"open {workspace} in your editor - not the workflow directory, or `agl` will not resolve."
    )
