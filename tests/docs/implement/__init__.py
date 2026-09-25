from dataclasses import dataclass
from agl.sdk import Run, arg, workflow
from .roles import builder

# --8<-- [start:definitions]
@dataclass(frozen=True)
class Params:
    request: str = arg("-r", "--request", help="What to do.")

@workflow
async def implement(run: Run[Params]) -> None:
    await run.step(builder, run.params.request, commit="Do what the run was asked")
# --8<-- [end:definitions]
