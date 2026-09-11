import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Final
from agl import api
from agl.cli.exit_codes import exit_code_for
from agl.config.placement import Got
from agl.config.questions import (
    Collision,
    DeclinedWorkflow,
    GainedDependencies,
    LocalChanges,
    Question,
    ThirdPartyDependencies,
)
from agl.ports.errors import AglError, DisagreeingRefusals, InternalError
from agl.ports.fetch import RefusedWorkflow
from agl.ports.ids import ProjectName, RunLabel
from agl.sdk._engine.services import Services

__all__ = ["Registered"]

type Registered = Callable[[], tuple[ProjectName, Services]]

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

# `exit_status` answers a disagreement with `InternalError`'s code, which says AGL broke, and a
# command that goes on past each refusal disagrees as a matter of course. ARCHITECTURE.md's "Errors
# at the boundary" says why the answer here is a code of its own rather than a precedence.
def _refusal_status(refusals: Iterable[AglError]) -> int:
    codes = {exit_code_for(refusal) for refusal in refusals}
    if not codes:
        return _NOTHING_TO_REPORT
    agreed, *disagreeing = codes
    return exit_code_for(DisagreeingRefusals) if disagreeing else agreed

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
