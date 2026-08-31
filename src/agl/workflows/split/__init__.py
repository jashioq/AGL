
from asyncio import TaskGroup
from dataclasses import dataclass

from agl.sdk import Run, arg, workflow
from agl.workflows.split import views
from agl.workflows.split.chunks import Chunk
from agl.workflows.split.roles import implementer, planner

__all__ = ["SplitParams", "split"]


@dataclass(frozen=True, slots=True)
class SplitParams:

    request: str = arg("-r", "--request", help="the job to divide up, in your own words")

    chunks: int = arg("-c", "--chunks", default=3, help="the most chunks to divide it into")


@workflow(version="1.1")
async def split(run: Run[SplitParams]) -> None:
    plan = await run.step(planner(), request=run.params.request, chunks=run.params.chunks)
    children = {chunk.id: run.worktree(chunk.id) for chunk in plan.items}
    await run.terminal.show(views.board, chunks=plan.items, runs=children)
    async with TaskGroup() as group:
        for chunk in plan.items:
            group.create_task(_implement(children[chunk.id], chunk))


async def _implement(child: Run[SplitParams], chunk: Chunk) -> None:
    await child.step(implementer(), chunk=chunk, commit=f"implement {chunk.id}")
    outcome = await child.integrate()
    while outcome.conflicted:
        if await child.terminal.show(
            views.conflict, conflict=outcome.conflict, build=outcome.verdict, priority=10
        ):
            await outcome.retry()
            continue
        await outcome.abort()
        break
