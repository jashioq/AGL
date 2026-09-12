import argparse
import asyncio
import sys
from collections.abc import Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass
from typing import Final
from agl import api
from agl.cli.exit_codes import exit_code_for, joint_status
from agl.config.placement import Got
from agl.config.questions import (
    Collision,
    DeclinedWorkflow,
    GainedDependencies,
    LocalChanges,
    Question,
    ThirdPartyDependencies,
)
from agl.ports.errors import AglError, InternalError
from agl.ports.fetch import RefusedWorkflow
from agl.ports.ids import ProjectName, RunLabel
from agl.sdk._engine.services import Services

__all__ = ["Registered"]

type Registered = Callable[[], tuple[ProjectName, Services]]

type _Report[T] = Callable[[T], None]

_NOTHING_TO_REPORT: Final = 0

# A word in the first column where a colour might have been: the terminal port carries no styling,
# and nothing outside `adapters/rich_terminal/` may import `rich` to add any.
_PLACED: Final = "placed"
_UPDATED: Final = "updated"
_DECLINED: Final = "declined"
_REFUSED: Final = "refused"
_MARKER_WIDTH: Final = max(len(_PLACED), len(_UPDATED), len(_DECLINED), len(_REFUSED))
_HELD: Final = frozenset({_PLACED, _UPDATED})

_NOT_OVERRIDDEN: Final = "not overridden"
_DEPENDENCIES: Final = "third-party dependencies"
_CHANGES_KEPT: Final = "local changes kept"
_GAINED: Final = "new third-party dependencies"
_NOT_FETCHED: Final = "not fetched"
_NOT_PLACEABLE: Final = "not placeable"
_NOT_WRITTEN: Final = "not written"

@dataclass(frozen=True, slots=True)
class _Row:
    """One workflow's line in a summary, and the refusal whose reason follows every line, if any."""

    marker: str

    name: str

    spec: str

    note: str = ""
    """Written after the spec: a few words saying why, or on a held line, which commits."""

    refusal: AglError | None = None

def _said(parsed: argparse.Namespace, dest: str, *, command: str) -> str:
    value = getattr(parsed, dest)
    if isinstance(value, str):
        return value
    raise InternalError(
        f"the `{command}` parser produced {value!r} for {dest!r}, and every argument this module "
        f"declares is a string it took off the command line. That is AGL's own bug: the parser and "
        f"the reader are in one file and they disagree"
    )

# Never on stdout, for `cli/commands/workflows.py`'s reason: what a machine consumes goes there and
# this is a note to whoever is reading the terminal. Silent at zero, so the line's presence is the
# signal - every first run replays nothing, and a run that says so every time says nothing.
def _print_replays(label: RunLabel, replayed: api.Replayed) -> None:
    if not replayed.steps:
        return
    counted = "step" if replayed.steps == 1 else "steps"
    print(
        f"replayed {replayed.steps} {counted} from cache - `agl clear {label}` removes it.",
        file=sys.stderr,
    )

# `joint_status` is the rule a run's concurrent failures are answered by too, so the two cannot
# drift apart. The 0 is this module's: nothing refused is a command's answer, not a table row.
def _refusal_status(refusals: Iterable[AglError]) -> int:
    codes = {exit_code_for(refusal) for refusal in refusals}
    if not codes:
        return _NOTHING_TO_REPORT
    return joint_status(codes)

# The line `cli/main.py` prints for a refusal that reaches it. It lives here because `main` imports
# this package and not the reverse, so a command that answers a refusal itself prints the same line.
def _print_refusal(refusal: AglError) -> None:
    print(f"agl: {refusal}", file=sys.stderr)

# `api.get` and `api.update` hand the summary to `report` before they sync, so a named failure once
# it is out finds every refusal's reason above it, and joins them by `_refusal_status` rather than
# standing in for them by reaching `main`. One raised before the summary is re-raised untouched, and
# one AGL has no name for is never caught: `main` answers both, the second with its traceback.
def _status_after_summary[T](
    operation: Callable[[_Report[T]], Coroutine[object, object, T]],
    summarise: _Report[T],
    refusals: Callable[[T], Iterable[AglError]],
) -> int:
    summarised: list[T] = []

    def report(value: T) -> None:
        summarise(value)
        summarised.append(value)

    try:
        value = asyncio.run(operation(report))
    except AglError as refusal:
        if not summarised:
            raise
        _print_refusal(refusal)
        return _refusal_status([*refusals(summarised[0]), refusal])
    return _refusal_status(refusals(value))

# Handed rows grouped by what became of each workflow rather than in the order asked, so the lines
# on stdout arrive together and ahead of every note. One failure can refuse several workflows with
# one error - a download, or one question about a ref - so each reason is printed once, naming all.
def _print_summary(rows: Sequence[_Row]) -> None:
    width = max((len(row.name) for row in rows), default=0)
    for row in rows:
        line = f"{row.marker:<{_MARKER_WIDTH}}  {row.name:<{width}}  {row.spec}"
        noted = f"{line}  {row.note}" if row.note else line
        # Never on stdout, for `cli/commands/workflows.py`'s reason: a line there names a workflow
        # the workspace now holds, and these are notes about ones it does not. Flushed, because a
        # piped stdout is block-buffered and would land after the sync's own stderr in a merged log.
        if row.marker in _HELD:
            print(noted, flush=True)
        else:
            print(noted, file=sys.stderr)
    shared: dict[AglError, list[str]] = {}
    for row in rows:
        if row.refusal is not None:
            shared.setdefault(row.refusal, []).append(row.name)
    for refusal, names in shared.items():
        print(f"{', '.join(names)}: {refusal}", file=sys.stderr)

def _declined(got: Got) -> list[_Row]:
    return [_decline(one) for one in got.declined]

def _refused(got: Got) -> list[_Row]:
    return [
        *(_refusal(one, _NOT_FETCHED) for one in got.unfetched),
        *(_refusal(one, _NOT_PLACEABLE) for one in got.unplaceable),
        *(_refusal(one, _NOT_WRITTEN) for one in got.unwritten),
    ]

def _decline(declined: DeclinedWorkflow) -> _Row:
    workflow = declined.placeable.workflow
    return _Row(_DECLINED, str(workflow.name), str(workflow), f"({_reason(declined.question)})")

def _refusal(refused: RefusedWorkflow, why: str) -> _Row:
    workflow = refused.workflow
    return _Row(_REFUSED, str(workflow.name), str(workflow), f"({why})", refused.refusal)

def _reason(question: Question) -> str:
    match question:
        case Collision():
            return _NOT_OVERRIDDEN
        case ThirdPartyDependencies():
            return _DEPENDENCIES
        case LocalChanges():
            return _CHANGES_KEPT
        case GainedDependencies():
            return _GAINED
