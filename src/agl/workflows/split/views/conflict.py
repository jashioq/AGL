from typing import Final
from agl.sdk import Choice, Conflict, Row, Rows, Screen, VerifierOutcome

__all__ = ["ABORT", "RETRY", "conflict"]

RETRY: Final = "Try landing it again"

ABORT: Final = "Give up on this chunk - its branch and worktree stay"

_TAIL: Final = 2_000

def conflict(conflict: Conflict, build: VerifierOutcome | None) -> Screen[bool]:
    rows = [Row(conflict.summary), *(Row(path) for path in conflict.paths)]
    if build is not None:
        rows.append(Row(f"The build exited {build.status}, and its output ended like this:"))
        rows.extend(Row(line) for line in _tail(build.output))
    return Screen(Rows(rows), [Choice(RETRY, value=True), Choice(ABORT, value=False)])

def _tail(output: str) -> list[str]:
    kept = output[-_TAIL:]
    lines = kept.splitlines()
    if lines and len(kept) < len(output) and output[-_TAIL - 1] not in "\r\n":
        del lines[0]
    return lines
