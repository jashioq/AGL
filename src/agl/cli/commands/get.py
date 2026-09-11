import argparse
import asyncio
import sys
from collections.abc import Mapping, Sequence
from typing import Final
from agl import api
from agl.cli.exit_codes import exit_code_for, exit_status
from agl.config.placement import Got
from agl.config.questions import Collision, Confirm, DeclinedWorkflow
from agl.ports.errors import AglError, InternalError
from agl.ports.fetch import Fetcher, RefusedWorkflow
from agl.ports.get_request import GetRequest
from agl.ports.home_layout import AglHome
from agl.ports.sync import Syncer
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "get"

_SPECS: Final = "specs"

_NOTHING_TO_REPORT: Final = 0

# A word in the first column where a colour might have been: the terminal port carries no styling,
# and nothing outside `adapters/rich_terminal/` may import `rich` to add any.
_PLACED: Final = "placed"
_DECLINED: Final = "declined"
_REFUSED: Final = "refused"
_MARKER_WIDTH: Final = max(len(_PLACED), len(_DECLINED), len(_REFUSED))

_NOT_OVERRIDDEN: Final = "not overridden"
_DEPENDENCIES: Final = "third-party dependencies"
_NOT_FETCHED: Final = "not fetched"
_NOT_PLACEABLE: Final = "not placeable"
_NOT_WRITTEN: Final = "not written"

_REFUSED_TOGETHER: Final = "the workflows this command was asked for and refused"

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="download workflows from public GitHub repositories into your workspace",
        description=(
            "Download workflows from public GitHub repositories into your AGL workspace. Each "
            "argument is owner/repo[@ref]/path/to/workflow, at the default branch where no @ref "
            "is given: the path runs from the repository's root to the workflow's own directory, "
            "whose name is the one it is placed under, and its last segment may be a comma list "
            "of siblings. A repository is downloaded once, "
            "however many workflows are asked of it. Every workflow is checked and every question "
            "asked before anything is placed - whether to replace a workflow the workspace already "
            "holds, and whether to install the third-party packages one declares - and with no "
            "terminal to answer on, each is answered no. What is placed is then installed, the "
            "way `agl new` installs what it writes."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _SPECS,
        metavar="<owner/repo[@ref]/path>",
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
    if not got.refused:
        return _NOTHING_TO_REPORT
    # A decline is the operator's answer, so only a refusal moves the status, and several resolve
    # by `exit_status`'s leaf agreement exactly as a `TaskGroup`'s failures do.
    refusals = list(_shared(got.refused))
    status = exit_status(ExceptionGroup(_REFUSED_TOGETHER, refusals))
    if len({exit_code_for(refusal) for refusal in refusals}) > 1:
        print(_disagreeing(status), file=sys.stderr)
    return status

# Grouped by what became of each workflow rather than in the order asked, so the lines on stdout
# arrive together and ahead of every note. Handed to `api.get` rather than printed after it returns,
# because a sync that raises leaves nothing returned to print.
def _summarise(got: Got) -> None:
    rows = [
        *((_PLACED, one.workflow, "") for one in got.placed),
        *((_DECLINED, one.placeable.workflow, _reason(one)) for one in got.declined),
        *((_REFUSED, one.workflow, _NOT_FETCHED) for one in got.unfetched),
        *((_REFUSED, one.workflow, _NOT_PLACEABLE) for one in got.unplaceable),
        *((_REFUSED, one.workflow, _NOT_WRITTEN) for one in got.unwritten),
    ]
    width = max((len(str(workflow.name)) for _, workflow, _ in rows), default=0)
    for marker, workflow, why in rows:
        line = f"{marker:<{_MARKER_WIDTH}}  {str(workflow.name):<{width}}  {workflow}"
        # Never on stdout, for `cli/commands/workflows.py`'s reason: a line there names a workflow
        # the workspace now holds, and these are notes about ones it does not. Flushed, because a
        # piped stdout is block-buffered and would land after the sync's own stderr in a merged log.
        if marker == _PLACED:
            print(line, flush=True)
        else:
            print(f"{line}  ({why})", file=sys.stderr)
    for refusal, names in _shared(got.refused).items():
        print(f"{', '.join(names)}: {refusal}", file=sys.stderr)

def _reason(declined: DeclinedWorkflow) -> str:
    return _NOT_OVERRIDDEN if isinstance(declined.question, Collision) else _DEPENDENCIES

# A download that failed refuses every workflow asked of it with the one error, so that reason is
# printed once, naming each of them.
def _shared(refused: Sequence[RefusedWorkflow]) -> Mapping[AglError, list[str]]:
    shared: dict[AglError, list[str]] = {}
    for one in refused:
        shared.setdefault(one.refusal, []).append(str(one.workflow.name))
    return shared

def _specs(parsed: argparse.Namespace) -> list[str]:
    value = getattr(parsed, _SPECS)
    if isinstance(value, list) and all(isinstance(one, str) for one in value):
        return value
    raise InternalError(
        f"the `{NAME}` parser produced {value!r} for {_SPECS!r}, and the one argument this module "
        f"declares is one or more strings it took off the command line. That is AGL's own bug: "
        f"the parser and the reader are in one file and they disagree"
    )

def _disagreeing(status: int) -> str:
    return (
        f"the refusals above do not resolve to one exit status, so `agl {NAME}` exits {status} - "
        f"read it as 'these disagreed' rather than as its usual 'file a bug'"
    )
