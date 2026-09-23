from dataclasses import dataclass
from agl.sdk import (
    Claude,
    ClaudeEffort,
    Restriction,
    Role,
    describe,
    prompt_file,
    reporting_tool,
    role,
)

@dataclass(frozen=True, slots=True)
class Summary:
    text: str = describe("what you changed, in a sentence or two")

record_summary = reporting_tool(
    "record_summary",
    "Record what you changed. Call it exactly once, when the work is done.",
    Summary,
)

@role(model=Claude.OPUS(effort=ClaudeEffort.HIGH), accepts=(str,))
def implementer() -> Role[Summary]:
    return Role(
        name="implement",
        instructions=prompt_file("prompts/implement.md"),
        restrictions={Restriction.NO_NETWORK},
        tools=(record_summary,),
    )
