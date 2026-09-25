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

# --8<-- [start:definitions]
@dataclass(frozen=True)
class Summary:
    text: str = describe("What you changed.")

@role(model=Claude.OPUS(effort=ClaudeEffort.HIGH), accepts=(str,))
def builder_role() -> Role[Summary]:
    return Role(
        name="builder",
        instructions=prompt_file("prompts/builder.md"),
        restrictions={Restriction.NO_NETWORK},
        tools=[reporting_tool("report", "Say what you changed.", Summary)],
    )

builder = builder_role()
# --8<-- [end:definitions]
