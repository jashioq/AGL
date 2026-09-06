import argparse
import asyncio
from typing import Final
from agl import api
from agl.cli.commands import _said
from agl.ports.home_layout import AglHome
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
    return _NOTHING_TO_REPORT
