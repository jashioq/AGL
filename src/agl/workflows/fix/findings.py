
from dataclasses import dataclass
from typing import Final

from agl.sdk import describe, reporting_tool

__all__ = ["HIGH", "SEVERITIES", "Finding", "Findings", "report_findings"]

HIGH: Final = "high"

SEVERITIES: Final = (HIGH, "medium", "low")


@dataclass(frozen=True, slots=True)
class Finding:

    severity: str = describe(
        f"One of {', '.join(SEVERITIES)}. Use {HIGH!r} only for something that must be fixed "
        f"before this change can ship: that is the one value that sends the change back to be "
        f"repaired, and every finding marked with it is another agent run."
    )

    file: str = describe("Where it is, as a path relative to the root of the repository.")

    summary: str = describe(
        "One or two sentences naming what is wrong and why it matters, written so that somebody "
        "repairing it without the diff in front of them knows what to do."
    )

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"severity is {self.severity!r}, and a finding's severity is one of "
                f"{', '.join(SEVERITIES)}. The workflow decides whether to run a repair pass by "
                f"comparing this field, so a severity outside that list is a finding it would "
                f"silently skip rather than one it would fail to understand"
            )


@dataclass(frozen=True, slots=True)
class Findings:

    findings: tuple[Finding, ...] = describe(
        "Every problem this review found, one entry per defect. Report an empty list when the "
        "change is sound: that is a result, not a failure to find anything."
    )

    def high(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == HIGH)


report_findings: Final = reporting_tool(
    "report_findings",
    "Report everything this review found, and end the review. Call this exactly once, when you "
    "have finished reading the change: it is the only way to record a result, and a review that "
    "ends without calling it has produced nothing and will be run again.",
    Findings,
)
