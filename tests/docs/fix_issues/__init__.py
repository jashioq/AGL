import asyncio
from dataclasses import dataclass
from agl.sdk import Choice, Conflict, Run, Screen, arg, workflow
from .roles import Issue, fixer, triager

@dataclass(frozen=True, slots=True)
class Parameters:
    issues: str = arg("-i", "--issues", help="the issues to fix, one per line")

triaging = triager()
fixing = fixer()

@workflow
async def fix_issues(run: Run[Parameters]) -> None:
    # --8<-- [start:triage]
    triage = await run.step(triaging, run.params.issues)  # (1)!
    # --8<-- [end:triage]
    # --8<-- [start:parallel]
    async with asyncio.TaskGroup() as group:  # (1)!
        for number, issue in enumerate(triage.issues, start=1):
            group.create_task(fix(run.worktree(f"issue-{number}"), issue))  # (2)!
    # --8<-- [end:parallel]

# --8<-- [start:fix]
async def fix(child: Run[Parameters], issue: Issue) -> None:  # (1)!
    await child.step(fixing, issue, commit=f"fix {issue.title}")  # (2)!
    await land(child, issue)  # (3)!
# --8<-- [end:fix]

# --8<-- [start:land]
async def land(child: Run[Parameters], issue: Issue) -> None:
    landing = await child.integrate()  # (1)!
    while landing.conflicted:  # (2)!
        if landing.refused_by_the_gate:  # (3)!
            await child.step(fixing, issue, landing.verdict, commit="make the build pass")  # (4)!
        elif not await child.terminal.show(resolving, conflict=landing.conflict):  # (5)!
            await landing.abort()  # (6)!
            return
        await landing.retry()  # (7)!
# --8<-- [end:land]

def resolving(conflict: Conflict) -> Screen[bool]:
    return Screen(
        f"{conflict.summary}\nResolve the files there and stage them with git add.",
        [Choice("Land it again", True), Choice("Leave it on its branch", False)],
    )
