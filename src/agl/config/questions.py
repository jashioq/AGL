from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from agl.config.inspection import PlaceableWorkflow
from agl.ports.get_request import RequestedWorkflow

__all__ = [
    "Answer",
    "ApprovedWorkflow",
    "Collision",
    "Confirm",
    "DeclinedWorkflow",
    "Question",
    "ThirdPartyDependencies",
    "answered",
    "needed",
]

type Confirm = Callable[[str], bool]

@dataclass(frozen=True, slots=True)
class Collision:
    """The question asked first, where something already stands: the download and what stands."""

    workflow: RequestedWorkflow

    existing: Path

    def __str__(self) -> str:
        return f"{self.existing} already exists. Override it with {self.workflow}?"

@dataclass(frozen=True, slots=True)
class ThirdPartyDependencies:
    """The question asked of a download declaring dependencies: the download and each of them."""

    workflow: RequestedWorkflow

    dependencies: tuple[str, ...]

    # `packaging` accepts ESC, BEL and DEL in a requirement's URL or quoted marker value, and CR and
    # LF in its URL, and a TOML `\u` escape writes any of them. So each is shown as a literal, which
    # no terminal acts on: a download cannot redraw the line that names what it installs.
    def __str__(self) -> str:
        listed = ", ".join(repr(dependency) for dependency in self.dependencies)
        return (
            f"{self.workflow} depends on third-party packages uv will install into the "
            f"workspace: {listed}. Continue?"
        )

type Question = Collision | ThirdPartyDependencies

@dataclass(frozen=True, slots=True)
class ApprovedWorkflow:
    """A download to place: every question about it was answered yes, or none was needed."""

    placeable: PlaceableWorkflow

@dataclass(frozen=True, slots=True)
class DeclinedWorkflow:
    """A download skipped and never placed: the question the operator answered no to."""

    placeable: PlaceableWorkflow

    question: Question

type Answer = ApprovedWorkflow | DeclinedWorkflow

def needed(placeable: PlaceableWorkflow) -> tuple[Question, ...]:
    """Every question a download is asked before it is placed, in the order asked."""
    questions: list[Question] = []
    if placeable.existing is not None:
        questions.append(Collision(placeable.workflow, placeable.existing))
    if placeable.dependencies:
        questions.append(ThirdPartyDependencies(placeable.workflow, placeable.dependencies))
    return tuple(questions)

def answered(placeables: Sequence[PlaceableWorkflow], confirm: Confirm) -> tuple[Answer, ...]:
    """One answer per download, in order: every question is asked before any answer is returned."""
    return tuple(_answer(placeable, confirm) for placeable in placeables)

# The first no settles a download, so a collision declined asks nothing about dependencies that
# would never be installed.
def _answer(placeable: PlaceableWorkflow, confirm: Confirm) -> Answer:
    for question in needed(placeable):
        if not confirm(str(question)):
            return DeclinedWorkflow(placeable, question)
    return ApprovedWorkflow(placeable)
