
from agl.sdk import Capability, Claude, Restriction, Role, prompt_file, role
from agl.workflows.split.chunks import Chunks, report_chunks

__all__ = ["implementer", "planner"]


@role(model=Claude.OPUS)
def planner() -> Role[Chunks]:
    return Role(
        name="plan",
        instructions=prompt_file("prompts/plan.md"),
        restrictions={Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES},
        tools=[report_chunks],
        requires={Capability.SHELL, Capability.TOOL_CALLING},
    )


@role(model=Claude.OPUS)
def implementer() -> Role:
    return Role(
        name="implement",
        instructions=prompt_file("prompts/implement.md"),
        restrictions={Restriction.NO_VCS_WRITES},
        requires={Capability.FILE_EDIT, Capability.SHELL},
    )
