
from dataclasses import dataclass
from typing import Final

from agl.sdk import Namespace, describe, reporting_tool

__all__ = ["Chunk", "Chunks", "report_chunks"]


@dataclass(frozen=True, slots=True)
class Chunk:

    id: str = describe(
        "This chunk's name. It becomes a git branch and a directory, so it may hold only letters "
        "A-Z a-z, digits, '.', '_' and '-' - no spaces, no slashes, no leading or trailing '.' or "
        "'-' - it may not be '_base', and no two chunks may share one, compared without regard to "
        "case. Keep it short and descriptive: a person reads these as branch names afterwards."
    )

    work: str = describe(
        "The whole assignment for this chunk, written for an agent that will never see the rest of "
        "this plan and has no memory of the reasoning behind it."
    )

    files: tuple[str, ...] = describe(
        "The paths this chunk should touch, relative to the repository root, including ones it "
        "will create. Two chunks naming one file will collide when their work is merged back."
    )

    def __post_init__(self) -> None:
        Namespace(self.id)


@dataclass(frozen=True, slots=True)
class Chunks:

    items: tuple[Chunk, ...] = describe(
        "Every chunk this job divides into. Report at least one: a job too small to divide is a "
        "plan with one chunk in it."
    )

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError(
                "a plan with no chunks in it is not a plan: every chunk is a worktree, so this "
                "would be a run that opened nothing, ran nothing and reported success over a job "
                "nobody did. There is always at least one chunk - a job too small to divide is a "
                "plan with one chunk in it, and it runs in one worktree"
            )
        taken: dict[str, str] = {}
        for chunk in self.items:
            key = Namespace(chunk.id).collision_key
            first = taken.get(key)
            if first is not None:
                raise ValueError(
                    f"two chunks are named {first!r} and {chunk.id!r}, which are two names to git "
                    f"and one directory on a case-insensitive filesystem, so the second worktree "
                    f"would be the first one's checkout. Every chunk needs a name no other chunk "
                    f"shares, compared without regard to case"
                )
            taken[key] = chunk.id


report_chunks: Final = reporting_tool(
    "report_chunks",
    "Report the chunks this job divides into, and end the planning step. Call this exactly once, "
    "when the plan is complete: it is the only way to record a result, and a planning step that "
    "ends without calling it has produced nothing and will be run again.",
    Chunks,
)
