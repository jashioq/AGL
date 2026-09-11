import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.config.inspection import Inspection, PlaceableWorkflow
from agl.config.questions import Answer, ApprovedWorkflow, DeclinedWorkflow
from agl.config.toml_file import make_workspace
from agl.ports.errors import ConflictError, InputError
from agl.ports.fetch import FetchAnswer, FetchedFile, RefusedWorkflow
from agl.ports.get_request import RequestedWorkflow
from agl.ports.home_layout import AglHome, workflow_dir, workflows_dir

__all__ = ["Got", "PlacedWorkflow", "placed"]

# In workflows/ itself, because `os.rename` raises `EXDEV` between two filesystems, and led by a dot
# so no import resolves it. Nothing is written at its own root, which is where uv 0.11 and the
# registry each look for a member's pyproject.toml - `tests/config/test_placement.py` holds both.
_STAGING: Final = ".agl-get-"
_PLACING: Final = "placing"
_REPLACED: Final = "replaced"

# The modes git checks a file out with, before the umask takes its share.
_REGULAR: Final = 0o666
_EXECUTABLE: Final = 0o777

_CREATED: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL

@dataclass(frozen=True, slots=True)
class PlacedWorkflow:
    """A download written into the workspace: what was asked for, and the directory it now is."""

    workflow: RequestedWorkflow

    directory: Path

@dataclass(frozen=True, slots=True)
class Got:
    """What one `agl get` made of every workflow it asked for, by what became of each of them."""

    placed: tuple[PlacedWorkflow, ...]

    declined: tuple[DeclinedWorkflow, ...]

    unfetched: tuple[RefusedWorkflow, ...]
    """Refused by the download itself: its repository, its ref, its directory or what that held."""

    unplaceable: tuple[RefusedWorkflow, ...]
    """Downloaded, and refused before the operator was asked anything about it."""

    unwritten: tuple[RefusedWorkflow, ...]
    """Approved, and refused when it could not be written into the workspace."""

    @property
    def refused(self) -> tuple[RefusedWorkflow, ...]:
        """Every refusal, whichever phase made it: what the command's exit status is read from."""
        return (*self.unfetched, *self.unplaceable, *self.unwritten)

def placed(
    home: AglHome,
    fetched: Sequence[FetchAnswer],
    inspections: Sequence[Inspection],
    answers: Sequence[Answer],
) -> Got:
    """Every approved download placed, the workspace made first, and what became of the rest."""
    approved = [answer.placeable for answer in answers if isinstance(answer, ApprovedWorkflow)]
    if approved:
        make_workspace(home)
    placements = [_placement(home, placeable) for placeable in approved]
    return Got(
        placed=tuple(one for one in placements if isinstance(one, PlacedWorkflow)),
        declined=tuple(one for one in answers if isinstance(one, DeclinedWorkflow)),
        unfetched=tuple(one for one in fetched if isinstance(one, RefusedWorkflow)),
        # `inspected` answers once per download in the downloads' own order, and hands a refusal
        # the fetcher made back as the very object it was given.
        unplaceable=tuple(
            one
            for one, answer in zip(inspections, fetched, strict=True)
            if isinstance(one, RefusedWorkflow) and not isinstance(answer, RefusedWorkflow)
        ),
        unwritten=tuple(one for one in placements if isinstance(one, RefusedWorkflow)),
    )

def _placement(home: AglHome, placeable: PlaceableWorkflow) -> PlacedWorkflow | RefusedWorkflow:
    workflow = placeable.workflow
    destination = workflow_dir(home, workflow.name)
    # `existing` was read before any question was asked, and the workspace can change meanwhile.
    if placeable.existing is None and destination.exists(follow_symlinks=False):
        return RefusedWorkflow(workflow, ConflictError(_appeared(workflow, destination)))
    try:
        with tempfile.TemporaryDirectory(
            prefix=_STAGING, dir=workflows_dir(home), ignore_cleanup_errors=True
        ) as staging:
            _swap(Path(staging), placeable, destination)
    except OSError as error:
        return RefusedWorkflow(workflow, InputError(_unwritten(workflow, destination, error)))
    return PlacedWorkflow(workflow, destination)

def _swap(staging: Path, placeable: PlaceableWorkflow, destination: Path) -> None:
    placing = staging / _PLACING
    _write(placing, placeable.files)
    replaced = staging / _REPLACED
    # Moved aside rather than removed: a rename moves a link or a file as itself and never walks
    # into what it names, and removing the staging directory disposes of it afterwards.
    if placeable.existing is not None:
        os.rename(placeable.existing, replaced)
    try:
        os.rename(placing, destination)
    except OSError:
        if placeable.existing is not None:
            os.rename(replaced, placeable.existing)
        raise

def _write(directory: Path, files: Mapping[str, FetchedFile]) -> None:
    directory.mkdir()
    for name, file in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, _CREATED, _EXECUTABLE if file.executable else _REGULAR)
        with open(descriptor, "wb") as handle:
            handle.write(file.content)

def _appeared(workflow: RequestedWorkflow, destination: Path) -> str:
    return (
        f"{destination} was made while the questions were being asked: nothing stood there when "
        f"{workflow} was inspected, so nobody was asked about replacing it and nothing is placed "
        f"over it"
    )

def _unwritten(workflow: RequestedWorkflow, destination: Path, error: OSError) -> str:
    return (
        f"{workflow} could not be placed at {destination}: {error}. Nothing of it is left where uv "
        f"or `agl workflows` would read it"
    )
