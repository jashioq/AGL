
from collections.abc import Mapping, Sequence

from agl.sdk import Row, Rows, Run, Screen
from agl.workflows.split.chunks import Chunk

__all__ = ["board"]


def board(chunks: Sequence[Chunk], runs: Mapping[str, Run]) -> Screen:
    return Screen(Rows([Row(chunk.id, _line(runs.get(chunk.id))) for chunk in chunks]))


def _line(run: Run | None) -> str:
    return "" if run is None else run.activity or ""
