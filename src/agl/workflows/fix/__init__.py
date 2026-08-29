
from dataclasses import dataclass

from agl.sdk import Answer, Question, Run, arg, workflow
from agl.workflows.fix import views
from agl.workflows.fix.roles import implementer, reviewer

__all__ = ["FixParams", "fix"]


@dataclass(frozen=True)
class FixParams:

    request: str = arg("-r", "--request", help="what to fix, in your own words")


@workflow(version="1.1")
async def fix(run: Run[FixParams]) -> None:

    async def answer(question: Question) -> Answer:
        return await run.terminal.show(views.agent_question, question=question)

    asking = implementer(on_question=answer)
    await run.terminal.show(views.board, run=run, request=run.params.request)
    await run.step(asking, request=run.params.request, commit="implement fix")
    findings = await run.step(reviewer())
    if findings.high():
        await run.step(asking, findings=findings.high(), commit="address review findings")
