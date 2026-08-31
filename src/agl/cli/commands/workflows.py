
import argparse
import sys
from collections.abc import Iterable
from importlib.metadata import EntryPoint
from typing import Final

from agl import api
from agl.ports.errors import InternalError
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "workflows"

_WORKFLOW: Final = "workflow"

_NOTHING_TO_REPORT: Final = 0

_NOTHING_INSTALLED: Final = (
    "no workflow is installed: the agl.workflows entry point group is empty in this environment. A "
    "workflow arrives as a package that declares one line in that group - nothing is registered "
    "here, and there is no central list in AGL to add one to."
)

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]


def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="list installed workflows, or print one workflow's flags",
        description=(
            "List every workflow installed in this environment. Nothing is imported to answer "
            "that, so a package that will not load still appears in the list. Naming one loads it "
            "and prints the flags `agl run <workflow>` takes for it."
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


def execute(parsed: argparse.Namespace, *, points: Iterable[EntryPoint] | None = None) -> int:
    named = _perhaps(parsed, _WORKFLOW)
    if named is not None:
        print(api.workflow_help(named, points=points).rstrip("\n"))
        return _NOTHING_TO_REPORT
    installed = api.list_workflows(points=points)
    if not installed:
        print(_NOTHING_INSTALLED, file=sys.stderr)
        return _NOTHING_TO_REPORT
    for name in installed:
        print(name)
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
