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
moved into it. If the rename that places the download then fails, what stood there is put back.

**The provenance hash is the invariant an edit breaks**: a workflow measured off disk the moment it
is placed is the one its provenance file records. `tests/config/test_inspection.py` holds that for
a hand-rolled placement; this holds it for the real one.
"""

import os
import stat
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Final
import pytest
from agl.config.inspection import PlaceableWorkflow, inspected
from agl.config.placement import Got, placed
from agl.config.provenance import PROVENANCE_FILE, placed_hash, read_provenance
from agl.config.questions import ApprovedWorkflow, answered
from agl.config.registry import GROUP, discovered, names
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.fetch import FetchAnswer, FetchedFile, FetchedWorkflow, RefusedWorkflow
from agl.ports.get_request import RepositoryAtRef, RequestedWorkflow
from agl.ports.home_layout import AglHome, workflow_dir, workflows_dir, workspace_pyproject
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
    home: AglHome, *downloads: FetchAnswer, confirm: Callable[[str], bool] = _approving
) -> Got:
    """The three phases for `downloads`, answering every question `confirm`'s way."""
    inspections = inspected(downloads, home)
    placeables = [one for one in inspections if isinstance(one, PlaceableWorkflow)]
    return placed(home, downloads, inspections, answered(placeables, confirm))

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

    got = placed(home, [download], [placeable], [ApprovedWorkflow(placeable)])

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

    got = placed(home, [], [], [ApprovedWorkflow(broken)])

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

    got = placed(home, [], [], [ApprovedWorkflow(broken)])

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
