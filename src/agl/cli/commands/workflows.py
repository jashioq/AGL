import argparse
import sys
from collections.abc import Iterable
from importlib.metadata import EntryPoint
from typing import Final
from agl import api
from agl.ports.errors import InternalError
from agl.ports.home_layout import AglHome
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "workflows"

_WORKFLOW: Final = "workflow"

_NOTHING_TO_REPORT: Final = 0

_NOTHING_DECLARED: Final = (
    'no workflow is declared: nothing in the workflows/ directory of your AGL workspace declares '
    'an agl.workflows entry point. A workflow is a directory you write there, holding its code, '
    'its prompts, and a pyproject.toml with one `<name> = "<module>:<attribute>"` line under '
    '[project.entry-points."agl.workflows"]. That line is the whole of registering it: there is '
    'nothing to install, and no central list in AGL to add it to.'
)

_BROKEN_PREAMBLE: Final = (
    "these workspace directories hold a pyproject.toml that declares no workflow, so no name in "
    "them is one `agl run` takes. Each answers only for itself, and no other directory in the "
    "workspace is affected by it:"
)

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="list the workflows your workspace declares, or print one workflow's flags",
        description=(
            "List every workflow declared in your AGL workspace. Nothing is imported to answer "
            "that, so a workflow whose own code will not load still appears in the list, and a "
            "directory that declares none is reported beside it. Naming one loads it and prints "
            "the flags `agl run <workflow>` takes for it."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _WORKFLOW,
        metavar="<workflow>",
        nargs="?",
        help="a workflow to describe: prints the flags it declares, and loads it to read them",
    )
    return parser

def execute(
    home: AglHome, parsed: argparse.Namespace, *, points: Iterable[EntryPoint] | None = None
) -> int:
    named = _perhaps(parsed, _WORKFLOW)
    if named is not None:
        print(api.workflow_help(named, home=home, points=points).rstrip("\n"))
        return _NOTHING_TO_REPORT
    listing = api.list_workflows(home=home, points=points)
    if not listing.names and not listing.broken:
        print(_NOTHING_DECLARED, file=sys.stderr)
        return _NOTHING_TO_REPORT
    for name in listing.names:
        print(name)
    # Never on stdout: a name printed there is a name `agl run` takes, and these are directories
    # that declare none - `agl workflows | while read` would be handed one to run.
    if listing.broken:
        print(_BROKEN_PREAMBLE, file=sys.stderr)
        for entry in listing.broken:
            print(f"  {entry.directory}: {entry.reason}", file=sys.stderr)
    return _NOTHING_TO_REPORT

def _perhaps(parsed: argparse.Namespace, dest: str) -> str | None:
    value = getattr(parsed, dest)
    if value is None or isinstance(value, str):
        return value
    raise InternalError(
        f"the `{NAME}` parser produced {value!r} for {dest!r}, and the one argument this module "
        f"declares is a string it took off the command line or nothing at all. That is AGL's own "
        f"bug: the parser and the reader are in one file and they disagree"
    )
