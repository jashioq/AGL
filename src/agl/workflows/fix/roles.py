from agl.sdk import Capability, Claude, OpenAI, Restriction, Role, Tool, prompt_file, role
from agl.workflows.fix.findings import Findings, report_findings

__all__ = ["implementer", "reviewer"]

@role(model=Claude.OPUS)
def implementer(*, ask: Tool | None = None) -> Role:
    return Role(
        name="implement",
        instructions=prompt_file("prompts/implement.md"),
        restrictions={Restriction.NO_VCS_WRITES},
        tools=() if ask is None else (ask,),
        requires={Capability.FILE_EDIT, Capability.SHELL},
    )

@role(model=OpenAI.SOL)
def reviewer() -> Role[Findings]:
    return Role(
        name="review",
        instructions=prompt_file("prompts/review.md"),
        restrictions={Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES},
        tools=[report_findings],
        requires={Capability.SHELL, Capability.TOOL_CALLING},
    )
