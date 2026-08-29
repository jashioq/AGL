
from agl.sdk import (
    Capability,
    Claude,
    OpenAI,
    QuestionHandler,
    Restriction,
    Role,
    prompt_file,
    role,
)
from agl.workflows.fix.findings import Findings, report_findings

__all__ = ["implementer", "reviewer"]


@role(model=Claude.OPUS)
def implementer(*, on_question: QuestionHandler | None = None) -> Role:
    return Role(
        name="implement",
        instructions=prompt_file("prompts/implement.md"),
        restrictions={Restriction.NO_VCS_WRITES},
        requires={Capability.FILE_EDIT, Capability.SHELL, Capability.MID_RUN_QUESTIONS},
        on_question=on_question,
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
