import argparse
import sys
from functools import partial
from typing import Final
from agl import api
from agl.cli.commands import (
    _REFUSED,
    _UPDATED,
    _declined,
    _print_summary,
    _refused,
    _Row,
    _said,
    _status_after_summary,
)
from agl.config.comparison import Updated
from agl.config.questions import Confirm, abbreviated
from agl.ports.errors import AglError
from agl.ports.fetch import Fetcher
from agl.ports.home_layout import AglHome
from agl.ports.sync import Syncer
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "update"

_WORKFLOW: Final = "workflow"

_CURRENT: Final = "Already up to date"

_NOT_CHECKED: Final = "not checked"
_NOT_REPLACEABLE: Final = "not replaceable"

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="Update workflows downloaded with `agl get`.",
        description="Update workflows downloaded with `agl get`.",
        allow_abbrev=False,
    )
    parser.add_argument(
        _WORKFLOW,
        metavar="<workflow>",
        nargs="?",
        help=(
            "Name of the workflow to update. If omitted, updates all workflows downloaded with "
            "`agl get`."
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
    named = None if getattr(parsed, _WORKFLOW) is None else _said(parsed, _WORKFLOW, command=NAME)
    return _status_after_summary(
        partial(api.update, fetcher, syncer, home, named, confirm), _summarise, _refusals
    )

# A decline is the operator's answer, so only a refusal moves the status.
def _refusals(updated: Updated) -> tuple[AglError, ...]:
    return updated.refusals

# Handed to `api.update` for `get`'s reason: a sync that raises leaves nothing returned to print.
def _summarise(updated: Updated) -> None:
    comparison, replacing, got = updated.comparison, updated.replacements, updated.got
    # Never on stdout, for `cli/commands/workflows.py`'s reason: a line there names a workflow, and
    # this is a note that there is none to name.
    if not comparison.moved and not comparison.refused:
        print(_CURRENT, file=sys.stderr)
    recorded = {one.provenance.workflow: one.provenance.commit for one in replacing.replaceable}
    updated_rows = [
        _Row(
            _UPDATED,
            str(one.workflow.name),
            str(one.workflow),
            f"{abbreviated(recorded[one.workflow])} -> {abbreviated(one.commit)}",
        )
        for one in got.placed
    ]
    unchecked = [
        _Row(
            _REFUSED,
            one.entry.name,
            "" if one.provenance is None else str(one.provenance.workflow),
            f"({_NOT_CHECKED})",
            one.refusal,
        )
        for one in comparison.refused
    ]
    unreplaceable = [
        _Row(
            _REFUSED,
            one.entry.name,
            str(one.provenance.workflow),
            f"({_NOT_REPLACEABLE})",
            one.refusal,
        )
        for one in replacing.unreplaceable
    ]
    _print_summary([*updated_rows, *_declined(got), *unchecked, *unreplaceable, *_refused(got)])
