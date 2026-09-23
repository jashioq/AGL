from dataclasses import dataclass
from agl.sdk import Run, arg, workflow
from .roles import implementer

@dataclass(frozen=True, slots=True)
class Parameters:
    request: str = arg("-r", "--request", help="what you want done")

implementing = implementer()

@workflow
async def implement(run: Run[Parameters]) -> None:
    await run.step(implementing, run.params.request, commit="do what was asked")
