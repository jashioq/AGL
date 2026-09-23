from dataclasses import dataclass
from agl.sdk import (
    Claude,
    Restriction,
    Role,
    VerifierOutcome,
    describe,
    prompt_file,
    reporting_tool,
    role,
)

@dataclass(frozen=True, slots=True)
class Issue:
    title: str = describe("the fix in a few words, the way a commit message starts")
    change: str = describe("what has to change, and in which files")

@dataclass(frozen=True, slots=True)
class Triage:
    issues: list[Issue] = describe("the fixes, each changing files no other fix changes")

record_triage = reporting_tool(
    "record_triage",
    "Record the fixes. Call it exactly once, when the triage is done.",
    Triage,
)

@role(model=Claude.OPUS, accepts=(str,))
def triager() -> Role[Triage]:
    return Role(
        name="triage",
        instructions=prompt_file("prompts/triage.md"),
        restrictions={Restriction.NO_FILE_WRITES, Restriction.NO_VCS_WRITES},
        tools=(record_triage,),
    )

@role(model=Claude.OPUS, accepts=(Issue, VerifierOutcome))
def fixer() -> Role[None]:
    return Role(name="fix", instructions=prompt_file("prompts/fix.md"))
