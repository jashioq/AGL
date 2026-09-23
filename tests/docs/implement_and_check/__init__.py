from dataclasses import dataclass
from agl.sdk import Run, Screen, arg, workflow
from .roles import implementer, reviewer

@dataclass(frozen=True, slots=True)
class Parameters:
    request: str = arg("-r", "--request", help="what you want done")

implementing = implementer()
reviewing = reviewer()

def heading(label: str) -> Screen:
    return Screen(f"implement_and_check: {label}")

# --8<-- [start:workflow]
@workflow  # (1)!
async def implement_and_check(run: Run[Parameters]) -> None:
    await run.terminal.show(heading, label=run.label)  # (2)!
    request = run.params.request  # (3)!
    await run.step(implementing, request, commit="do what was asked")  # (4)!
    checked = await run.verify(run.config["build"])  # (5)!
    review = await run.step(reviewing, request, checked)  # (6)!
    if review.findings:
        await run.step(implementing, request, review, commit="fix what the review found")  # (7)!
# --8<-- [end:workflow]
