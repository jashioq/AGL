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
class Review:
    findings: list[str] = describe("what is wrong, one item per finding, each naming its file")

record_review = reporting_tool(
    "record_review",
    "Record what the review found. Call it exactly once, at the end, even with no findings.",
    Review,
)

@role(model=Claude.OPUS, accepts=(str, Review))
def implementer() -> Role[None]:
    return Role(name="implement", instructions=prompt_file("prompts/implement.md"))

@role(model=Claude.OPUS, accepts=(str, VerifierOutcome))
def reviewer() -> Role[Review]:
    return Role(
        name="review",
        instructions=prompt_file("prompts/review.md"),
        restrictions={Restriction.NO_FILE_WRITES, Restriction.NO_VCS_WRITES},
        tools=(record_review,),
    )
