import argparse
import asyncio
from typing import Final
from agl import api
from agl.cli.commands import _PLACED, _declined, _print_summary, _refusal_status, _refused, _Row
from agl.config.placement import Got
from agl.config.questions import Confirm
from agl.ports.errors import InternalError
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
        help="download workflows from public GitHub repositories into your workspace",
        description=(
            "Download workflows from public GitHub repositories into your AGL workspace. Each "
            "argument is owner/repo/path/to/workflow[@ref]: the path runs from the repository's "
            "root to the workflow's own directory, whose name is the one it is placed under, and "
            "its last segment may be a comma list of siblings. Everything after the @ is the ref, "
            "release/1.0 included, and with no @ref the default branch is fetched. A repository is "
            "downloaded once, however many workflows are asked of it. Every workflow is checked "
            "and every question asked before anything is placed - whether to replace a workflow "
            "the workspace already holds, and whether to install the third-party packages one "
            "declares - and one stdin cannot answer, at its end or closed, is answered no. What is "
            "placed is then installed, the way `agl new` installs what it writes."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _SPECS,
        metavar="<owner/repo/path[@ref]>",
        nargs="+",
        help="a workflow to download, its siblings named as a comma list in the last segment",
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
    got = asyncio.run(api.get(fetcher, syncer, home, request, confirm, _summarise))
    # A decline is the operator's answer, so only a refusal moves the status.
    return _refusal_status(one.refusal for one in got.refused)

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
