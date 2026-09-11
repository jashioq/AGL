from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.config.inspection import PlaceableWorkflow
from agl.config.removal import RemovableEntry
from agl.ports.get_request import RequestedWorkflow

__all__ = [
    "Answer",
    "ApprovedWorkflow",
    "Collision",
    "Confirm",
    "DeclinedWorkflow",
    "GainedDependencies",
    "LocalChanges",
    "Question",
    "Questions",
    "Removal",
    "ThirdPartyDependencies",
    "abbreviated",
    "answered",
    "needed",
]

_SHORT: Final = 7

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

@dataclass(frozen=True, slots=True)
class LocalChanges:
    """The question asked first of an update over a changed copy: the copy and both commits."""

    entry: Path

    recorded: str
    """The commit the copy was placed from, as its provenance file records it."""

    fetched: str
    """The commit the update would place in the copy's stead."""

    def __str__(self) -> str:
        return (
            f"{self.entry} has changed since it was placed from {abbreviated(self.recorded)}, and "
            f"updating it to {abbreviated(self.fetched)} replaces it whole, discarding those "
            f"changes. Update it?"
        )

@dataclass(frozen=True, slots=True)
class GainedDependencies:
    """The question asked of an update declaring what its copy does not: the update and each."""

    workflow: RequestedWorkflow

    fetched: str
    """The commit the update would place."""

    entry: Path

    dependencies: tuple[str, ...]
    """Each as the update declares it and in its order, and none the copy declares the same way."""

    # Each as a literal, for `ThirdPartyDependencies`' reason.
    def __str__(self) -> str:
        listed = ", ".join(repr(dependency) for dependency in self.dependencies)
        return (
            f"{self.workflow} at {abbreviated(self.fetched)} declares third-party dependencies "
            f"{self.entry} does not, which uv will install into the workspace: {listed}. Continue?"
        )

type Question = Collision | ThirdPartyDependencies | LocalChanges | GainedDependencies

type Questions = Callable[[PlaceableWorkflow], tuple[Question, ...]]

@dataclass(frozen=True, slots=True)
class Removal:
    """The question `agl remove` asks before anything goes: the entry, and what it declares."""

    removable: RemovableEntry

    # Each name as a literal, for `ThirdPartyDependencies`' reason: a TOML key's `\u` escape writes
    # any control character, and the question is printed on the operator's terminal.
    def __str__(self) -> str:
        entry = self.removable
        named = ", ".join(repr(name) for name in entry.declared)
        declares = f"declares {named}" if named else "declares no workflow"
        if entry.linked:
            return (
                f"{entry.path} is a link, and {declares}. Remove the link, leaving what it names "
                f"as it is?"
            )
        return f"{entry.path} {declares}. Remove it?"

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
    """Every question `agl get` asks of a download before it is placed, in the order asked."""
    questions: list[Question] = []
    if placeable.existing is not None:
        questions.append(Collision(placeable.workflow, placeable.existing))
    if placeable.dependencies:
        questions.append(ThirdPartyDependencies(placeable.workflow, placeable.dependencies))
    return tuple(questions)

def answered(
    placeables: Sequence[PlaceableWorkflow], confirm: Confirm, questions: Questions = needed
) -> tuple[Answer, ...]:
    """One answer per download, in order: every question is asked before any answer is returned."""
    return tuple(_answer(placeable, confirm, questions) for placeable in placeables)

def abbreviated(commit: str) -> str:
    """A commit as GitHub shows one on its own pages: its first seven characters."""
    return commit[:_SHORT]

# The first no settles a download, so a question declined ahead of its dependencies - a collision,
# or an update's local changes - asks nothing about dependencies that would never be installed.
def _answer(placeable: PlaceableWorkflow, confirm: Confirm, questions: Questions) -> Answer:
    for question in questions(placeable):
        if not confirm(str(question)):
            return DeclinedWorkflow(placeable, question)
    return ApprovedWorkflow(placeable)
