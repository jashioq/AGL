from dataclasses import dataclass
from agl.sdk import Run, arg, workflow
from agl.workflows.fix import views
from agl.workflows.fix.asking import asking
from agl.workflows.fix.roles import implementer, reviewer

__all__ = ["FixParams", "fix"]

@dataclass(frozen=True)
class FixParams:
    request: str = arg("-r", "--request", help="what to fix, in your own words")

@workflow(version="4")
async def fix(run: Run[FixParams]) -> None:
    implement = implementer(ask=asking(run.terminal))
    await run.terminal.show(views.board, run=run, request=run.params.request)
    await run.step(implement, request=run.params.request, commit="implement fix")
    findings = await run.step(reviewer())
    if findings.high():
        await run.step(implement, findings=findings.high(), commit="address review findings")
