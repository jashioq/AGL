"""`config/placement.py`: writing an approved download into the workspace, and nowhere else first.

A download is written whole into a staging directory, then renamed into place in one step. The
staging directory is inside `workflows/` - `os.rename` raises `EXDEV` between two filesystems, and
the destination is a directory in there - so it has to be somewhere nothing reading that directory
can mistake for a workflow. Two readers look, and they look at the same file:

  * `config/registry.py`'s walk reads `<entry>/pyproject.toml` for each directory in `workflows/`
    and nothing below it, whatever the entry's name.
  * uv, taking `workflows/*` as its members, takes a dot-led directory as one wherever a
    `pyproject.toml` stands directly inside it, and passes over one with none. Measured with uv
    0.11.29 and `uv lock --offline` over a scratch workspace: a dot-led directory holding a
    project file joined the lock as a member, and one holding the same file a level down did not.

So the staging directory is led by a dot and nothing is ever written at its own root - the download
goes a level down - and one test below looks at `workflows/` at the instant before the rename that
places it and asserts exactly that. A failure part-way through leaves at most that directory
behind, which neither reader sees.

**An override moves what stands there aside rather than removing it.** A rename moves a symbolic
link or a file as itself and never walks into what it names, so the operator's own directory at the
far end of a link is never touched, and the staging directory's removal disposes of whatever was
moved into it. If the rename that places the download then fails, or a Ctrl-C lands before it has
finished, what stood there is put back; once the download is in place, it stays. A copy `agl
update` measured is measured again first, once the download is written, and refused - nothing of it
moved - where it no longer measures what it did before anything was asked.

**The provenance hash is the invariant an edit breaks**: a workflow measured off disk the moment it
is placed is the one its provenance file records. `tests/config/test_inspection.py` holds that for
a hand-rolled placement; this holds it for the real one.
"""

import os
import shutil
import stat
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Final
import pytest
from agl.config.inspection import PlaceableWorkflow, inspected
from agl.config.placement import Got, Removed, placed, removed
from agl.config.provenance import placed_hash, read_provenance
from agl.config.questions import ApprovedWorkflow, answered
from agl.config.registry import GROUP, discovered, names
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.fetch import FetchAnswer, FetchedFile, FetchedWorkflow, RefusedWorkflow
from agl.ports.get_request import RepositoryAtRef, RequestedWorkflow
from agl.ports.home_layout import (
    PROVENANCE_FILE,
    STAGED_PLACING,
    STAGED_REMOVED,
    STAGING_PREFIX,
    AglHome,
    workflow_dir,
    workflows_dir,
    workspace_pyproject,
)
from agl.ports.ids import WorkflowName

_SHA: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

_MODULE: Final = b"from agl.sdk import Run, workflow\n"

_TRIAGE: Final = WorkflowName("triage")

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME under `tmp_path` that is not there yet, built so that no variable is read."""
    return AglHome(tmp_path / "home")

def _requested(name: str) -> RequestedWorkflow:
    repository = RepositoryAtRef("jashioq", "myrepo", None)
    return RequestedWorkflow(repository, f"workflows/{name}", f"{repository}/workflows/{name}")

def _pyproject(name: str, dependencies: str = "") -> bytes:
    """A workflow's project file that every check `inspected` makes lets through."""
    return (
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n{dependencies}\n'
        f'[project.entry-points."{GROUP}"]\n{name} = "{name}:{name}"\n'
    ).encode()

def _download(name: str, extra: Mapping[str, FetchedFile] | None = None) -> FetchedWorkflow:
    """One workflow as a fetcher hands it over: a project file, a package module and `extra`."""
    files = {
        "pyproject.toml": FetchedFile(_pyproject(name)),
        "__init__.py": FetchedFile(_MODULE),
        **(extra or {}),
    }
    return FetchedWorkflow(_requested(name), _SHA, files)

def _approving(question: str) -> bool:
    return True

def _declining(question: str) -> bool:
    return False

def _placing(
    home: AglHome,
    *downloads: FetchAnswer,
    confirm: Callable[[str], bool] = _approving,
    measured: Mapping[RequestedWorkflow, str] | None = None,
) -> Got:
    """The three phases for `downloads`, answering every question `confirm`'s way.

    `measured` stands for what `agl update` measured of each copy it replaces, and is nothing where
    it is not given, as under `agl get`.
    """
    inspections = inspected(downloads, home)
    placeables = [one for one in inspections if isinstance(one, PlaceableWorkflow)]
    return placed(home, downloads, inspections, answered(placeables, confirm), measured or {})

def _standing(home: AglHome, name: str) -> Path:
    """A workflow directory already in the workspace, with a file only it holds."""
    directory = workflows_dir(home) / name
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_bytes(_pyproject(name.lower()))
    (directory / "__init__.py").write_bytes(_MODULE)
    (directory / "notes.md").write_bytes(b"# the operator's own notes\n")
    return directory

def _tree(directory: Path) -> dict[str, bytes]:
    """Every file under `directory` and its bytes, keyed by POSIX path relative to it."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }

@pytest.fixture
def _umask_of_022() -> Iterator[None]:
    """The commonest umask, set for one test and put back, so a mode can be asserted exactly."""
    previous = os.umask(0o022)
    yield
    os.umask(previous)

# --- what is written ----------------------------------------------------------------------------

def test_a_placed_workflow_is_every_file_it_was_handed_and_nothing_else(tmp_path: Path) -> None:
    """The directory holds exactly the files inspection handed over, byte for byte.

    Listed rather than sampled, because the defect worth catching is a file too many - a staging
    name, a marker, a second copy of the provenance file - and a sampled assertion passes it.
    """
    home = _home(tmp_path)
    download = _download("triage", {"prompts/review.md": FetchedFile(b"# review\n")})
    (placeable,) = inspected([download], home)
    assert isinstance(placeable, PlaceableWorkflow)

    got = placed(home, [download], [placeable], [ApprovedWorkflow(placeable)], {})

    assert [one.directory for one in got.placed] == [workflow_dir(home, _TRIAGE)]
    assert _tree(workflow_dir(home, _TRIAGE)) == {
        name: file.content for name, file in placeable.files.items()
    }
    assert sorted(_tree(workflow_dir(home, _TRIAGE))) == [
        PROVENANCE_FILE,
        "__init__.py",
        "prompts/review.md",
        "pyproject.toml",
    ]

def test_a_workflow_measured_off_disk_as_placed_is_the_one_its_provenance_records(
    tmp_path: Path,
) -> None:
    """`placed_hash(directory) == read_provenance(directory).content_hash` - unedited reads as such.

    This is the whole of what tells an untouched workflow from an edited one, and a placement that
    wrote one byte other than what it was handed, or one file more, would read as the operator's
    edit before they had made one.
    """
    home = _home(tmp_path)

    got = _placing(home, _download("triage", {"bin/run.sh": FetchedFile(b"#!/bin/sh\n", True)}))

    (one,) = got.placed
    recorded = read_provenance(one.directory)
    assert recorded is not None
    assert recorded.commit == _SHA
    assert placed_hash(one.directory) == recorded.content_hash

@pytest.mark.usefixtures("_umask_of_022")
def test_a_file_that_came_executable_is_placed_executable_and_no_other_file_is(
    tmp_path: Path,
) -> None:
    """The modes git would check the same tree out with: 0o777 and 0o666 before the umask.

    What arrives is the owner's execute bit alone, which is all a git tree records, so the group
    and the rest of the world get what the umask gives them - here 0o755 and 0o644.
    """
    home = _home(tmp_path)

    _placing(home, _download("triage", {"bin/run.sh": FetchedFile(b"#!/bin/sh\n", True)}))

    directory = workflow_dir(home, _TRIAGE)
    assert stat.S_IMODE((directory / "bin" / "run.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((directory / "__init__.py").stat().st_mode) == 0o644
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755

def test_nothing_is_made_at_all_where_every_download_was_declined(tmp_path: Path) -> None:
    """No workspace, no directory: a command that placed nothing leaves the home as it found it.

    The download here declares a dependency, which is what makes a question - and so a no - of it.
    """
    home = _home(tmp_path)
    download = FetchedWorkflow(
        _requested("triage"),
        _SHA,
        {
            "pyproject.toml": FetchedFile(_pyproject("triage", 'dependencies = ["httpx"]')),
            "__init__.py": FetchedFile(_MODULE),
        },
    )

    got = _placing(home, download, confirm=_declining)

    assert got.placed == ()
    assert [one.placeable.workflow for one in got.declined] == [download.workflow]
    assert not home.path.exists()

def test_the_workspace_is_made_first_when_anything_at_all_was_approved(tmp_path: Path) -> None:
    """`make_workspace` ahead of the first placement, so a missing home works as `agl new` finds."""
    home = _home(tmp_path)

    _placing(home, _download("triage"))

    assert workspace_pyproject(home).read_text(encoding="utf-8") == (
        '[tool.uv.workspace]\nmembers = ["workflows/*"]\n'
    )

# --- where it is staged -------------------------------------------------------------------------

def test_while_a_download_is_staged_nothing_the_registry_or_uv_reads_can_see_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`workflows/` looked at the instant before the rename that places the download.

    Every entry there that was not there before is led by a dot and holds no `pyproject.toml` at
    its own root - the one file the registry reads of each entry, and the one whose presence makes
    uv take a dot-led directory as a member. The registry is asked as well rather than trusted, and
    at that instant it declares only what already stood.
    """
    home = _home(tmp_path)
    _standing(home, "release")
    destination = workflow_dir(home, _TRIAGE)
    seen: list[tuple[list[Path], tuple[str, ...]]] = []
    renamed = os.rename

    def looking_first(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target) == destination:
            arrived = [entry for entry in workflows_dir(home).iterdir() if entry.name != "release"]
            seen.append((arrived, names(discovered(home).points)))
        renamed(source, target)

    monkeypatch.setattr(os, "rename", looking_first)
    _placing(home, _download("triage"))

    ((arrived, declared),) = seen
    assert len(arrived) == 1
    assert arrived[0].name.startswith(".")
    assert arrived[0].name.startswith(STAGING_PREFIX)
    assert not (arrived[0] / "pyproject.toml").exists()
    assert declared == ("release",)

def test_once_a_workflow_is_placed_the_directory_it_was_staged_in_is_gone(tmp_path: Path) -> None:
    home = _home(tmp_path)

    _placing(home, _download("triage"), _download("release"))

    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["release", "triage"]

def test_a_download_that_cannot_be_written_is_refused_and_leaves_nothing_anyone_reads(
    tmp_path: Path,
) -> None:
    """A write failing part-way: a refusal naming the destination, and `workflows/` as it was.

    Made to fail the only way a download from the real fetcher never could, which is what makes it
    a clean instrument: a file `bin` and a file under `bin/` are two paths no directory can hold.
    """
    home = _home(tmp_path)
    _standing(home, "release")
    broken = PlaceableWorkflow(
        _requested("triage"),
        _SHA,
        {"bin": FetchedFile(b"a file"), "bin/run.sh": FetchedFile(b"under it")},
        (),
        None,
    )

    got = placed(home, [], [], [ApprovedWorkflow(broken)], {})

    (refused,) = got.unwritten
    assert isinstance(refused.refusal, InputError)
    assert str(workflow_dir(home, _TRIAGE)) in str(refused.refusal)
    assert got.placed == ()
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["release"]
    assert names(discovered(home).points) == ("release",)

# --- what stands there already ------------------------------------------------------------------

def test_an_approved_override_replaces_what_stood_there_whole(tmp_path: Path) -> None:
    """The old directory's own file goes with it: an override is a replacement, not a merge."""
    home = _home(tmp_path)
    _standing(home, "triage")

    got = _placing(home, _download("triage"))

    assert [one.directory for one in got.placed] == [workflow_dir(home, _TRIAGE)]
    assert "notes.md" not in _tree(workflow_dir(home, _TRIAGE))
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

def test_a_directory_differing_only_in_case_is_the_one_an_override_replaces(
    tmp_path: Path,
) -> None:
    """`Triage` stood, `triage` was asked for: one directory afterwards, spelled as asked.

    On a case-insensitive volume the two names are one entry, and on a case-sensitive one placing
    beside it would leave two entries that fold to one name - which inspection refuses from then on.
    Either way it is the entry inspection named that goes.
    """
    home = _home(tmp_path)
    _standing(home, "Triage")

    got = _placing(home, _download("triage"))

    assert len(got.placed) == 1
    assert [entry.name for entry in workflows_dir(home).iterdir()] == ["triage"]
    assert "notes.md" not in _tree(workflow_dir(home, _TRIAGE))

def test_an_override_of_a_link_replaces_the_link_and_never_touches_what_it_named(
    tmp_path: Path,
) -> None:
    """The operator's own directory at the far end of a link is left exactly as it was.

    A removal that followed the link would take a checkout the operator keeps elsewhere, which is
    the one outcome of `agl get` nobody could undo.
    """
    home = _home(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "triage"
    elsewhere.mkdir(parents=True)
    (elsewhere / "pyproject.toml").write_bytes(_pyproject("triage"))
    (elsewhere / "__init__.py").write_bytes(_MODULE)
    (elsewhere / "notes.md").write_bytes(b"# kept elsewhere\n")
    before = _tree(elsewhere)
    workflows_dir(home).mkdir(parents=True)
    workflow_dir(home, _TRIAGE).symlink_to(elsewhere, target_is_directory=True)

    got = _placing(home, _download("triage"))

    assert len(got.placed) == 1
    assert not workflow_dir(home, _TRIAGE).is_symlink()
    assert workflow_dir(home, _TRIAGE).is_dir()
    assert _tree(elsewhere) == before

def test_an_override_of_a_plain_file_replaces_the_file(tmp_path: Path) -> None:
    home = _home(tmp_path)
    workflows_dir(home).mkdir(parents=True)
    workflow_dir(home, _TRIAGE).write_bytes(b"not a workflow at all\n")

    got = _placing(home, _download("triage"))

    assert len(got.placed) == 1
    assert (workflow_dir(home, _TRIAGE) / "__init__.py").read_bytes() == _MODULE

def test_an_override_that_cannot_be_written_leaves_what_stood_there_as_it_was(
    tmp_path: Path,
) -> None:
    """The download is written out before what stands is moved, so a failed write moves nothing."""
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    before = _tree(standing)
    broken = PlaceableWorkflow(
        _requested("triage"),
        _SHA,
        {"bin": FetchedFile(b"a file"), "bin/run.sh": FetchedFile(b"under it")},
        (),
        standing,
    )

    got = placed(home, [], [], [ApprovedWorkflow(broken)], {})

    assert len(got.unwritten) == 1
    assert _tree(standing) == before
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

def test_a_rename_into_place_that_fails_puts_what_stood_there_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one step after the old directory has moved: if it fails, the old directory moves back.

    Otherwise the staging directory's removal would take it, and the operator who approved a
    replacement would be left with neither the workflow they had nor the one they asked for.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    before = _tree(standing)
    renamed = os.rename
    refused_already: list[Path] = []

    # The first rename onto that path is the download's own, the old directory having gone aside
    # under another name; the second is the old one coming back.
    def refusing_the_first(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target) == standing and not refused_already:
            refused_already.append(Path(source))
            raise OSError("the volume went read-only")
        renamed(source, target)

    monkeypatch.setattr(os, "rename", refusing_the_first)
    got = _placing(home, _download("triage"))

    (refused,) = got.unwritten
    assert "the volume went read-only" in str(refused.refusal)
    assert _tree(standing) == before
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

# --- a Ctrl-C between an override's two renames -------------------------------------------------
#
# An override is two renames - what stands, aside into the staging directory, then the download into
# its place - and the staging directory is removed on the way out however the way out is taken. So
# anything that leaves between the two would take what was moved aside with it, and CPython raises a
# Ctrl-C between two bytecodes, as readily just after a rename returns as just before one starts.
# The tests below raise one at each of those points: what stands is always the old entry or the new.

def test_a_ctrl_c_at_the_rename_into_place_puts_what_stood_there_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raised as the download's own rename is called: the old directory back, whole.

    Only the first rename onto that path raises, as it would have to: the second is the old entry
    coming back.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    before = _tree(standing)
    renamed = os.rename
    interrupted: list[Path] = []

    def interrupting_the_first(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        if Path(target) == standing and not interrupted:
            interrupted.append(Path(source))
            raise KeyboardInterrupt
        renamed(source, target)

    monkeypatch.setattr(os, "rename", interrupting_the_first)
    with pytest.raises(KeyboardInterrupt):
        _placing(home, _download("triage"))

    assert _tree(standing) == before
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

def test_a_ctrl_c_at_the_rename_into_place_puts_back_a_link_that_names_nothing_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What stood there is a link to nowhere, and it is still what stood there: back it comes."""
    home = _home(tmp_path)
    workflows_dir(home).mkdir(parents=True)
    link = workflows_dir(home) / "triage"
    link.symlink_to(tmp_path / "gone")
    renamed = os.rename
    interrupted: list[Path] = []

    def interrupting_the_first(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        if Path(target) == link and not interrupted:
            interrupted.append(Path(source))
            raise KeyboardInterrupt
        renamed(source, target)

    monkeypatch.setattr(os, "rename", interrupting_the_first)
    with pytest.raises(KeyboardInterrupt):
        _placing(home, _download("triage"))

    assert os.readlink(link) == str(tmp_path / "gone")
    assert [entry.name for entry in workflows_dir(home).iterdir()] == ["triage"]

def test_a_ctrl_c_as_what_stood_there_lands_aside_puts_it_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raised as the rename that moved it aside returns, before anything else has run."""
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    before = _tree(standing)
    renamed = os.rename

    def interrupting_once_it_moved(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        renamed(source, target)
        if Path(source) == standing:
            raise KeyboardInterrupt

    monkeypatch.setattr(os, "rename", interrupting_once_it_moved)
    with pytest.raises(KeyboardInterrupt):
        _placing(home, _download("triage"))

    assert _tree(standing) == before
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

def test_a_ctrl_c_as_the_download_lands_leaves_the_download_standing_and_still_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raised as the rename into place returns: that replacement is done, and the Ctrl-C is kept.

    Putting the old entry back now would mean renaming it onto the download, which fails - and a
    failure there would stand in for the Ctrl-C and report a workflow placed as one never written.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    download = _download("triage")
    (placeable,) = inspected([download], home)
    assert isinstance(placeable, PlaceableWorkflow)
    renamed = os.rename

    def interrupting_once_it_landed(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        renamed(source, target)
        if Path(target) == standing:
            raise KeyboardInterrupt

    monkeypatch.setattr(os, "rename", interrupting_once_it_landed)
    with pytest.raises(KeyboardInterrupt):
        placed(home, [download], [placeable], [ApprovedWorkflow(placeable)], {})

    assert _tree(standing) == {name: file.content for name, file in placeable.files.items()}
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

def test_a_placed_workflow_names_the_commit_its_files_were_taken_from(tmp_path: Path) -> None:
    home = _home(tmp_path)

    (one,) = _placing(home, _download("triage")).placed

    assert one.commit == _SHA

def test_something_made_there_while_the_questions_were_asked_is_never_placed_over(
    tmp_path: Path,
) -> None:
    """Nothing stood there at inspection, so the operator was asked nothing about replacing it.

    The directory is made from inside the one question the download raises - its dependencies -
    which is exactly the window an `agl new` in another terminal would use.
    """
    home = _home(tmp_path)
    download = FetchedWorkflow(
        _requested("triage"),
        _SHA,
        {
            "pyproject.toml": FetchedFile(_pyproject("triage", 'dependencies = ["httpx"]')),
            "__init__.py": FetchedFile(_MODULE),
        },
    )

    def meanwhile(question: str) -> bool:
        workflow_dir(home, _TRIAGE).mkdir(parents=True)
        (workflow_dir(home, _TRIAGE) / "mine.py").write_bytes(b"# written meanwhile\n")
        return True

    got = _placing(home, download, confirm=meanwhile)

    (refused,) = got.unwritten
    assert isinstance(refused.refusal, ConflictError)
    assert _tree(workflow_dir(home, _TRIAGE)) == {"mine.py": b"# written meanwhile\n"}

# --- a copy `agl update` measured, measured again as it is replaced ------------------------------
#
# `agl update` measures each copy it may replace before anything is downloaded or asked, and hands
# the hash on through `placed`: the copy is replaced only while it still measures that. Here the
# hash is taken by hand where `config/comparison.py` takes it, and each test changes the copy at the
# moment its name says - through `confirm`, since the collision question is put while the operator
# could be editing, or as the download is staged.

def _as_measured(directory: Path) -> dict[RequestedWorkflow, str]:
    """What `agl update` hands on for `triage` standing at `directory`: the hash it measures now."""
    return {_requested("triage"): placed_hash(directory)}

def _appending(module: Path, line: bytes) -> None:
    """The operator's edit, saved: a line added to the end of a file of the copy."""
    with module.open("ab") as handle:
        handle.write(line)

def test_a_copy_still_measuring_what_it_measured_is_replaced_like_any_override(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    standing = _standing(home, "triage")

    got = _placing(home, _download("triage"), measured=_as_measured(standing))

    assert [one.directory for one in got.placed] == [standing]
    assert "notes.md" not in _tree(standing)
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

def test_a_copy_edited_since_it_was_measured_is_refused_and_keeps_every_byte(
    tmp_path: Path,
) -> None:
    """Edited while its question was up: a conflict naming it, the copy as left, and no leftover."""
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    measured = _as_measured(standing)
    kept: dict[str, bytes] = {}

    def editing(question: str) -> bool:
        _appending(standing / "__init__.py", b"# saved while the question was on screen\n")
        kept.update(_tree(standing))
        return True

    got = _placing(home, _download("triage"), confirm=editing, measured=measured)

    (refused,) = got.unwritten
    assert isinstance(refused.refusal, ConflictError)
    assert str(refused.refusal).startswith(f"{standing} changed after `agl update` measured it")
    assert got.placed == ()
    assert _tree(standing) == kept
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

def test_an_edit_saved_while_the_download_is_being_staged_is_caught_before_any_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The copy is measured again after the staged write, and not ahead of it.

    The edit lands as the first staged file is created - after every question, and before the first
    rename - so a check made before the write would pass the copy, and the rename would take the
    edit away with it.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    measured = _as_measured(standing)
    opened = os.open
    kept: dict[str, bytes] = {}

    def editing_as_it_is_staged(
        path: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if STAGED_PLACING in Path(path).parts and not kept:
            _appending(standing / "__init__.py", b"# saved as the download was being staged\n")
            kept.update(_tree(standing))
        return opened(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", editing_as_it_is_staged)
    got = _placing(home, _download("triage"), measured=measured)

    (refused,) = got.unwritten
    assert isinstance(refused.refusal, ConflictError)
    assert kept
    assert _tree(standing) == kept

@pytest.mark.parametrize("made", ["gone", "a link", "not a directory"])
def test_a_copy_gone_linked_or_no_directory_since_it_was_measured_is_refused_saying_so(
    tmp_path: Path, made: str
) -> None:
    """Made so while the question was up, and whatever stands there then is left as it stands.

    The link names the very directory that was measured, moved aside, and is still refused: a hash
    read through it would match, and replacing it would change which directory `agl run` runs - the
    reason `config/comparison.py` refuses a copy that is a link before anything is asked.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    measured = _as_measured(standing)
    elsewhere = tmp_path / "elsewhere"
    original = _tree(standing)

    def meanwhile(question: str) -> bool:
        if made == "a link":
            standing.rename(elsewhere)
            standing.symlink_to(elsewhere, target_is_directory=True)
        else:
            shutil.rmtree(standing)
        if made == "not a directory":
            standing.write_bytes(b"not a directory\n")
        return True

    got = _placing(home, _download("triage"), confirm=meanwhile, measured=measured)

    (refused,) = got.unwritten
    assert isinstance(refused.refusal, ConflictError)
    assert str(refused.refusal).startswith(f"{standing} is {made}")
    assert got.placed == ()
    if made == "gone":
        assert list(workflows_dir(home).iterdir()) == []
    elif made == "a link":
        assert os.readlink(standing) == str(elsewhere)
        assert _tree(elsewhere) == original
    else:
        assert standing.read_bytes() == b"not a directory\n"

def test_a_copy_gone_before_its_download_was_inspected_is_refused_rather_than_placed(
    tmp_path: Path,
) -> None:
    """Deleted while the downloads were fetched, so inspection found nothing standing there.

    The copy the update measured is not there to replace, and placing the download in its stead
    would put back what was just taken away, with nothing asked about either.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    measured = _as_measured(standing)
    shutil.rmtree(standing)

    got = _placing(home, _download("triage"), measured=measured)

    (refused,) = got.unwritten
    assert isinstance(refused.refusal, ConflictError)
    assert str(refused.refusal).startswith(f"{standing} is gone")
    assert list(workflows_dir(home).iterdir()) == []

def test_a_copy_that_cannot_be_measured_again_is_refused_as_what_cannot_be_read(
    tmp_path: Path,
) -> None:
    """Whether it changed cannot be told, so it is not replaced: an update's refusal from before."""
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    measured = _as_measured(standing)
    unreadable = standing / "notes.md"
    unreadable.chmod(0)
    readable = os.access(unreadable, os.R_OK)
    unreadable.chmod(0o644)
    if readable:
        pytest.skip("this user reads a file whatever its mode says, as root does")

    def closing(question: str) -> bool:
        unreadable.chmod(0)
        return True

    try:
        got = _placing(home, _download("triage"), confirm=closing, measured=measured)
    finally:
        unreadable.chmod(0o644)

    (refused,) = got.unwritten
    assert isinstance(refused.refusal, InputError)
    assert str(refused.refusal).startswith(f"{standing} cannot be measured again")
    assert f"{unreadable} cannot be read" in str(refused.refusal)
    assert "notes.md" in _tree(standing)

def test_a_download_nothing_measured_overrides_a_copy_it_could_not_even_read(
    tmp_path: Path,
) -> None:
    """`agl get` measures nothing it overrides: its one question claims only that something stands.

    So a directory no hash could be taken of is overridden as any other is, with nothing refused.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    unreadable = standing / "notes.md"
    unreadable.chmod(0)
    try:
        if os.access(unreadable, os.R_OK):
            pytest.skip("this user reads a file whatever its mode says, as root does")
        got = _placing(home, _download("triage"))
    finally:
        if unreadable.exists():
            unreadable.chmod(0o644)

    assert [one.directory for one in got.placed] == [standing]
    assert "notes.md" not in _tree(standing)
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]

# --- what became of each ------------------------------------------------------------------------

def test_every_workflow_is_filed_under_the_one_phase_that_settled_it(tmp_path: Path) -> None:
    """Placed, declined, and refused by the download, by inspection or by the write - each once.

    The two refusals before any question look alike, both being `RefusedWorkflow`; what tells them
    apart is that inspection hands a fetcher's refusal back as the very object it was given.
    """
    home = _home(tmp_path)
    _standing(home, "release")
    unfetched = RefusedWorkflow(_requested("absent"), NotFoundError("no directory 'absent'"))
    unplaceable = FetchedWorkflow(_requested("hollow"), _SHA, {"__init__.py": FetchedFile(b"")})
    declined = _download("release")
    wanted = _download("triage")

    got = _placing(home, unfetched, unplaceable, declined, wanted, confirm=_declining)

    assert [one.workflow for one in got.placed] == [wanted.workflow]
    assert [one.placeable.workflow for one in got.declined] == [declined.workflow]
    assert got.unfetched == (unfetched,)
    assert [one.workflow for one in got.unplaceable] == [unplaceable.workflow]
    assert got.unwritten == ()
    assert [one.workflow for one in got.refused] == [unfetched.workflow, unplaceable.workflow]

# --- what a removal takes -----------------------------------------------------------------------
#
# `agl remove` takes an entry out through the same staging directory a placement uses: renamed into
# it whole, a level down and under a name of its own, and only then deleted. uv 0.11.29 refuses
# every sync of the workspace over a non-dot directory holding any file and no project file - which
# is what a delete made in place leaves if it stops part-way - and over a dangling link; it passes
# over a dot-led directory with no project file at its root, whatever is below. Measured with `uv
# sync --offline --no-install-workspace` over a scratch workspace, as the staging above was.

def test_a_removed_directory_goes_whole_and_leaves_no_staging_directory_behind(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    (standing / "prompts").mkdir()
    (standing / "prompts" / "review.md").write_bytes(b"# review\n")
    _standing(home, "release")

    assert removed(home, standing) == Removed(standing, None)

    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["release"]

def test_a_removed_link_goes_as_the_link_and_never_touches_what_it_named(
    tmp_path: Path,
) -> None:
    """A delete that followed the link would take a checkout the operator keeps elsewhere."""
    home = _home(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "triage"
    elsewhere.mkdir(parents=True)
    (elsewhere / "pyproject.toml").write_bytes(_pyproject("triage"))
    (elsewhere / "notes.md").write_bytes(b"# kept elsewhere\n")
    before = _tree(elsewhere)
    workflows_dir(home).mkdir(parents=True)
    link = workflow_dir(home, _TRIAGE)
    link.symlink_to(elsewhere, target_is_directory=True)

    assert removed(home, link) == Removed(link, None)

    assert list(workflows_dir(home).iterdir()) == []
    assert _tree(elsewhere) == before

@pytest.mark.parametrize("kind", ["file", "dangling link"])
def test_a_plain_file_or_a_dangling_link_is_removed_like_any_other_entry(
    tmp_path: Path, kind: str
) -> None:
    home = _home(tmp_path)
    workflows_dir(home).mkdir(parents=True)
    entry = workflows_dir(home) / "stray"
    if kind == "file":
        entry.write_bytes(b"not a workflow\n")
    else:
        entry.symlink_to(tmp_path / "gone")

    assert removed(home, entry) == Removed(entry, None)

    assert list(workflows_dir(home).iterdir()) == []

@pytest.mark.parametrize("name", ["triage", "pyproject.toml"])
def test_between_the_rename_and_the_delete_nothing_the_registry_or_uv_reads_can_see_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """`workflows/` looked at the instant after the rename that takes the entry out of it.

    Whatever came is led by a dot and holds no `pyproject.toml` at its own root - so neither an
    entry named `pyproject.toml`, a stray file in the one place a project file would be read, nor
    anything else can land where uv would take the staging directory as a member. The registry is
    asked as well rather than trusted, and at that instant declares only what is staying.
    """
    home = _home(tmp_path)
    _standing(home, "release")
    entry = workflows_dir(home) / name
    if name == "triage":
        _standing(home, name)
    else:
        entry.write_bytes(_pyproject("stray"))
    seen: list[tuple[list[Path], tuple[str, ...]]] = []
    renamed = os.rename

    def looking_after(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        renamed(source, target)
        if Path(source) == entry:
            arrived = [one for one in workflows_dir(home).iterdir() if one.name != "release"]
            seen.append((arrived, names(discovered(home).points)))

    monkeypatch.setattr(os, "rename", looking_after)
    removed(home, entry)

    ((arrived, declared),) = seen
    assert len(arrived) == 1
    assert arrived[0].name.startswith(".")
    assert not (arrived[0] / "pyproject.toml").exists(follow_symlinks=False)
    assert declared == ("release",)

def test_a_delete_that_stops_part_way_leaves_only_what_no_reader_of_workflows_sees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rename took it out of the workspace; what the delete could not take is handed back.

    `shutil.rmtree` doing nothing stands in for a delete refused everywhere - a root-owned tree, an
    immutable file - and `tempfile` ignores what it cannot delete, so this is the one account of it.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    _standing(home, "release")
    monkeypatch.setattr(shutil, "rmtree", lambda path, *args, **kwargs: None)

    left = removed(home, standing).leftover

    assert left is not None
    assert left.parent == workflows_dir(home)
    assert left.name.startswith(".")
    assert [one.name for one in left.iterdir()] == [STAGED_REMOVED]
    assert not (left / "pyproject.toml").exists()
    assert not standing.exists()
    assert names(discovered(home).points) == ("release",)

def test_a_rename_that_fails_refuses_the_removal_and_leaves_the_entry_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    before = _tree(standing)

    def refusing(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        raise OSError("the volume went read-only")

    monkeypatch.setattr(os, "rename", refusing)

    with pytest.raises(InputError) as refused:
        removed(home, standing)

    assert str(standing) in str(refused.value)
    assert "the volume went read-only" in str(refused.value)
    assert _tree(standing) == before
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["triage"]
