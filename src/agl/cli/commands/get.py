import argparse
from functools import partial
from typing import Final
from agl import api
from agl.cli.commands import (
    _PLACED,
    _declined,
    _print_summary,
    _refused,
    _Row,
    _status_after_summary,
)
from agl.config.placement import Got
from agl.config.questions import Confirm
from agl.ports.errors import AglError, InternalError
from agl.ports.fetch import Fetcher
from agl.ports.get_request import GetRequest
from agl.ports.home_layout import AglHome
from agl.ports.sync import Syncer
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "get"

_SPECS: Final = "specs"

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="Download workflows from GitHub.",
        description="Download workflows from public GitHub repositories.",
        allow_abbrev=False,
    )
    parser.add_argument(
        _SPECS,
        metavar="<owner/repo/path[@ref]>",
        nargs="+",
        help=(
            "Path to a workflow's directory in a GitHub repository. Separate several workflows in "
            "one directory with commas: acme/flows/triage,review. If @ref is omitted, uses the "
            "default branch."
        ),
    )
    return parser

def execute(
    home: AglHome,
    parsed: argparse.Namespace,
    *,
    fetcher: Fetcher,
    syncer: Syncer,
    confirm: Confirm,
) -> int:
    request = GetRequest.parsed(_specs(parsed))
    return _status_after_summary(
        partial(api.get, fetcher, syncer, home, request, confirm), _summarise, _refusals
    )

# A decline is the operator's answer, so only a refusal moves the status.
def _refusals(got: Got) -> tuple[AglError, ...]:
    return tuple(one.refusal for one in got.refused)

# Handed to `api.get` rather than printed after it returns, because a sync that raises leaves
# nothing returned to print.
def _summarise(got: Got) -> None:
    placed = [_Row(_PLACED, str(one.workflow.name), str(one.workflow)) for one in got.placed]
    _print_summary([*placed, *_declined(got), *_refused(got)])

def _specs(parsed: argparse.Namespace) -> list[str]:
    value = getattr(parsed, _SPECS)
    if isinstance(value, list) and all(isinstance(one, str) for one in value):
        return value
    raise InternalError(
        f"the `{NAME}` parser produced {value!r} for {_SPECS!r}, and the one argument this module "
        f"declares is one or more strings it took off the command line. That is AGL's own bug: "
        f"the parser and the reader are in one file and they disagree"
    )
