import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.config.inspection import Inspection, PlaceableWorkflow
from agl.config.questions import Answer, ApprovedWorkflow, DeclinedWorkflow
from agl.config.toml_file import make_workspace
from agl.ports.errors import ConflictError, InputError
from agl.ports.fetch import FetchAnswer, FetchedFile, RefusedWorkflow
from agl.ports.get_request import RequestedWorkflow
from agl.ports.home_layout import (
    STAGED_PLACING,
    STAGED_REMOVED,
    STAGED_REPLACED,
    STAGING_PREFIX,
    AglHome,
    workflow_dir,
    workflows_dir,
)

__all__ = ["Got", "PlacedWorkflow", "Removed", "placed", "removed"]

# The modes git checks a file out with, before the umask takes its share.
_REGULAR: Final = 0o666
_EXECUTABLE: Final = 0o777

_CREATED: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL

@dataclass(frozen=True, slots=True)
class PlacedWorkflow:
    """A download written into the workspace: what was asked for, and the directory it now is."""

    workflow: RequestedWorkflow

    directory: Path

    commit: str
    """The full object id of the commit its files were taken from, which its provenance records."""

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

@dataclass(frozen=True, slots=True)
class Removed:
    """An entry taken out of workflows/: where it stood, and whatever of it the delete left."""

    entry: Path

    leftover: Path | None
    """The dot-led directory holding what could not be deleted, `None` where nothing was left."""

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
        with _staged(home) as staging:
            _swap(staging, placeable, destination)
    except OSError as error:
        return RefusedWorkflow(workflow, InputError(_unwritten(workflow, destination, error)))
    return PlacedWorkflow(workflow, destination, placeable.commit)

# One rename takes the entry out of every reader's sight at once, a link as the link and never what
# it names. A delete made in place and stopped part-way leaves a directory with files in it and no
# project file, and uv 0.11 refuses every sync of the workspace over one of those.
def removed(home: AglHome, entry: Path) -> Removed:
    """`entry` moved out of workflows/ in one rename and then deleted, as far as it would go."""
    try:
        with _staged(home) as staging:
            os.rename(entry, staging / STAGED_REMOVED)
    except OSError as error:
        raise InputError(_unremoved(entry, error)) from error
    return Removed(entry, staging if staging.exists() else None)

@contextmanager
def _staged(home: AglHome) -> Iterator[Path]:
    # In workflows/ itself, because `os.rename` raises `EXDEV` between two filesystems.
    with tempfile.TemporaryDirectory(
        prefix=STAGING_PREFIX, dir=workflows_dir(home), ignore_cleanup_errors=True
    ) as staging:
        yield Path(staging)

def _swap(staging: Path, placeable: PlaceableWorkflow, destination: Path) -> None:
    placing = staging / STAGED_PLACING
    _write(placing, placeable.files)
    existing = placeable.existing
    if existing is None:
        os.rename(placing, destination)
        return
    replaced = staging / STAGED_REPLACED
    # Moved aside rather than removed: a rename moves a link or a file as itself and never walks
    # into what it names, and removing the staging directory disposes of it afterwards.
    try:
        os.rename(existing, replaced)
        os.rename(placing, destination)
    # Anything at all, a Ctrl-C included: whatever leaves here unhandled takes what was moved aside
    # with it, the staging directory being removed on the way out. Which renames happened is read
    # off disk rather than remembered, because CPython raises a Ctrl-C between any two bytecodes -
    # as readily just after a rename returns as just before one starts.
    except BaseException:
        if placing.exists(follow_symlinks=False) and replaced.exists(follow_symlinks=False):
            os.rename(replaced, existing)
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

def _unremoved(entry: Path, error: OSError) -> str:
    return f"{entry} could not be removed: {error}. It stands where it stood, and none of it moved"
