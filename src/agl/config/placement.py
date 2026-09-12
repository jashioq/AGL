import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.config.inspection import Inspection, PlaceableWorkflow
from agl.config.provenance import placed_hash
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
    """Approved, and refused as it came to be written into the workspace."""

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

# `measured` is what `agl update` measured of each copy it replaces, before anything was downloaded
# or asked, by the workflow downloaded for it. `agl get` measures nothing: its one question about
# what stands where a download goes claims only that something does.
def placed(
    home: AglHome,
    fetched: Sequence[FetchAnswer],
    inspections: Sequence[Inspection],
    answers: Sequence[Answer],
    measured: Mapping[RequestedWorkflow, str],
) -> Got:
    """Every approved download placed, the workspace made first, and what became of the rest."""
    approved = [answer.placeable for answer in answers if isinstance(answer, ApprovedWorkflow)]
    if approved:
        make_workspace(home)
    placements = [
        _placement(home, placeable, measured.get(placeable.workflow)) for placeable in approved
    ]
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

def _placement(
    home: AglHome, placeable: PlaceableWorkflow, measured: str | None
) -> PlacedWorkflow | RefusedWorkflow:
    workflow = placeable.workflow
    destination = workflow_dir(home, workflow.name)
    # `existing` was read before any question was asked, and the workspace can change meanwhile.
    if placeable.existing is None and destination.exists(follow_symlinks=False):
        return RefusedWorkflow(workflow, ConflictError(_appeared(workflow, destination)))
    try:
        with _staged(home) as staging:
            _swap(staging, placeable, destination, measured)
    except OSError as error:
        return RefusedWorkflow(workflow, InputError(_unwritten(workflow, destination, error)))
    except (ConflictError, InputError) as refused:
        return RefusedWorkflow(workflow, refused)
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

def _swap(
    staging: Path, placeable: PlaceableWorkflow, destination: Path, measured: str | None
) -> None:
    placing = staging / STAGED_PLACING
    _write(placing, placeable.files)
    # Measured again once the download is written and not before, so what stays unguarded is this
    # hash and the first rename below: a file saved after the hash has read it is still replaced
    # unasked, and the filesystem offers no lock an editor would honour.
    if measured is not None:
        _check_as_measured(placeable, destination, measured)
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

# Refused in so many words rather than left to the walk or the rename to fail over. A link is
# refused whatever it names, for `comparison.py`'s `_linked` reason: the hash would be read through
# it, and replacing it would change which directory `agl run` runs with nobody asked.
def _check_as_measured(placeable: PlaceableWorkflow, destination: Path, measured: str) -> None:
    existing = placeable.existing
    if existing is None or not existing.exists(follow_symlinks=False):
        raise ConflictError(_vanished(existing or destination, placeable.workflow))
    if existing.is_symlink() or not existing.is_dir():
        raise ConflictError(_no_longer_a_directory(existing))
    try:
        now = placed_hash(existing)
    except InputError as unmeasured:
        raise InputError(_unmeasurable(existing, unmeasured)) from unmeasured
    if now != measured:
        raise ConflictError(_changed_meanwhile(existing))

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

def _vanished(entry: Path, workflow: RequestedWorkflow) -> str:
    return (
        f"{entry} is gone: it stood there when `agl update` measured it, before anything was "
        f"downloaded or asked, and nothing is placed where it stood. Whatever became of it is left "
        f"as it is - `agl get {workflow}` places the download there if it is still wanted"
    )

def _no_longer_a_directory(entry: Path) -> str:
    now = "a link" if entry.is_symlink() else "not a directory"
    return (
        f"{entry} is {now} now, and `agl update` measured a directory there before anything was "
        f"downloaded or asked, so what stands there is not what was decided about. It is left "
        f"exactly as it stands, and nothing is placed over it"
    )

def _unmeasurable(entry: Path, refused: InputError) -> str:
    return (
        f"{entry} cannot be measured again before it is replaced, so nothing tells whether it "
        f"changed since `agl update` measured it, and an update replaces nothing it cannot tell "
        f"that of: {refused}"
    )

def _changed_meanwhile(entry: Path) -> str:
    return (
        f"{entry} changed after `agl update` measured it, while the downloads were fetched or the "
        f"questions were on screen, and replacing it now could discard a change nobody was asked "
        f"about. It is left exactly as it stands, and nothing is placed over it: `agl update` "
        f"again measures it afresh, and asks before it discards any change it finds"
    )

def _unwritten(workflow: RequestedWorkflow, destination: Path, error: OSError) -> str:
    return (
        f"{workflow} could not be placed at {destination}: {error}. Nothing of it is left where uv "
        f"or `agl workflows` would read it"
    )

def _unremoved(entry: Path, error: OSError) -> str:
    return f"{entry} could not be removed: {error}. It stands where it stood, and none of it moved"
