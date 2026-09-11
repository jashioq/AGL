"""`config/removal.py`: which entry of `workflows/` a name reaches, and what may not be taken out.

Everything here is decided before the operator is asked and before anything moves, so every case
hands `removable` a workspace built under `tmp_path` and reads back a value or a refusal. It reads
the listing `config/inspection.py` measures a download against - every entry of `workflows/`, folded
as a case-insensitive volume folds it, with what each declares and depends on - rather than a second
walk of its own that could come to disagree with it.

**The name is an entry's own and never a declared one.** A directory is free to declare names
unlike its own, and removing by one of those would take every other name it declares along with it;
so the entry's own name is what reaches it, a declared one is refused naming the entry, and the
question `config/questions.py` puts lists everything declared.

**A name is typed, then folded.** An exact spelling reaches its entry outright; failing that, the
fold a case-insensitive volume applies finds the one entry it answers to, and two it answers to
equally are refused rather than chosen between.

**What can never be reached**: a dot-led entry, which is where AGL stages what it places or removes
and which a crash can leave holding the only copy of an overridden workflow; and anything that is
not one name in `workflows/` - a traversal, a separator, an empty string. Each is refused as a name,
before the workspace is listed at all.

**What may not be taken out**: an entry another member depends on. uv reads a dependency on a
member's name as a dependency on that member, so with it gone every sync is refused where a
`[tool.uv.sources]` entry names it as a member - measured with uv 0.11.29 over a scratch workspace -
and the dependency goes to a package index where none does.
"""

from pathlib import Path
import pytest
from agl.config.inspection import listed
from agl.config.registry import GROUP
from agl.config.removal import RemovableEntry, entries_named, removable
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.home_layout import STAGING_PREFIX, AglHome, workflows_dir

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _pyproject(name: str, *, project: str = "", declares: str | None = None) -> bytes:
    """A workflow's project file: its name and version, `project` lines and its declarations."""
    declaration = f'{name} = "{name}:{name}"' if declares is None else declares
    return (
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n{project}\n'
        f'[project.entry-points."{GROUP}"]\n{declaration}\n'
    ).encode()

def _standing(home: AglHome, directory: str, pyproject: bytes) -> Path:
    """A directory already in the workspace, holding the project file it is handed."""
    path = workflows_dir(home) / directory
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_bytes(pyproject)
    return path

def _both_spellings(
    home: AglHome, monkeypatch: pytest.MonkeyPatch, first: str, second: str
) -> Path:
    """Two entries differing only in case, side by side as a case-sensitive volume holds them.

    Made for real where the volume can hold both, and reported by the listing where it cannot -
    which is the whole of what a case-sensitive volume would show.
    """
    _standing(home, first, _pyproject("one"))
    container = workflows_dir(home)
    if (container / second).exists():
        listing = Path.iterdir
        spellings = [container / second, container / first]
        monkeypatch.setattr(
            Path, "iterdir", lambda path: iter(spellings) if path == container else listing(path)
        )
    else:
        _standing(home, second, _pyproject("two"))
    return container

# --- the entry a name reaches -------------------------------------------------------------------

def test_a_removal_reaches_the_entry_by_its_own_name_and_every_name_it_declares(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    standing = _standing(
        home,
        "triage_dir",
        _pyproject(
            "triage_dir",
            declares='sort-issues = "triage_dir:sort"\nlabel_prs = "triage_dir:label"',
        ),
    )

    assert removable(home, "triage_dir") == RemovableEntry(
        standing, ("label_prs", "sort-issues"), linked=False
    )

@pytest.mark.parametrize("spelled", ["Triage", "TRIAGE"])
def test_a_name_matched_only_by_its_case_reaches_the_entry_as_it_is_spelled_on_disk(
    tmp_path: Path, spelled: str
) -> None:
    home = _home(tmp_path)
    standing = _standing(home, spelled, _pyproject("triage"))

    assert removable(home, "triage").path == standing

def test_a_name_typed_exactly_reaches_that_entry_beside_one_differing_only_in_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spelling typed is the one meant, so no fold is asked of a name that matches outright."""
    home = _home(tmp_path)
    container = _both_spellings(home, monkeypatch, "Triage", "triage")

    assert removable(home, "triage").path == container / "triage"

def test_entries_differing_from_the_name_only_in_case_refuse_it_rather_than_choosing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path)
    _both_spellings(home, monkeypatch, "Triage", "TRIAGE")

    with pytest.raises(ConflictError) as refused:
        removable(home, "triage")

    assert "Triage" in str(refused.value)
    assert "TRIAGE" in str(refused.value)

def test_the_rule_update_shares_answers_an_exact_spelling_alone_or_else_every_fold_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The matching `agl update` reaches an entry by too, each command wording its own refusals."""
    home = _home(tmp_path)
    container = _both_spellings(home, monkeypatch, "Triage", "TRIAGE")
    entries = listed(home)

    assert [entry.path for entry in entries_named(entries, "Triage")] == [container / "Triage"]
    assert sorted(entry.path.name for entry in entries_named(entries, "triage")) == [
        "TRIAGE",
        "Triage",
    ]
    assert entries_named(entries, "lint") == ()

def test_a_link_is_said_to_be_one_and_declares_whatever_its_target_declares(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    target = tmp_path / "elsewhere" / "triage"
    target.mkdir(parents=True)
    (target / "pyproject.toml").write_bytes(_pyproject("triage"))
    workflows_dir(home).mkdir(parents=True)
    (workflows_dir(home) / "triage").symlink_to(target, target_is_directory=True)

    assert removable(home, "triage") == RemovableEntry(
        workflows_dir(home) / "triage", ("triage",), linked=True
    )

@pytest.mark.parametrize("kind", ["file", "bare directory", "unreadable", "dangling link"])
def test_an_entry_declaring_nothing_is_still_one_a_removal_can_take(
    tmp_path: Path, kind: str
) -> None:
    """A directory with no project file and a dangling link each fail every later sync.

    So they are exactly what an operator most needs to be able to take out, and nothing about
    declaring no workflow puts one out of reach.
    """
    home = _home(tmp_path)
    entry = workflows_dir(home) / "stray"
    workflows_dir(home).mkdir(parents=True)
    if kind == "file":
        entry.write_bytes(b"not a workflow\n")
    elif kind == "bare directory":
        entry.mkdir()
        (entry / ".DS_Store").write_bytes(b"\x00")
    elif kind == "unreadable":
        entry.mkdir()
        (entry / "pyproject.toml").write_bytes(b"[project\n")
    else:
        entry.symlink_to(tmp_path / "gone", target_is_directory=True)

    assert removable(home, "stray") == RemovableEntry(entry, (), linked=kind == "dangling link")

# --- a name that reaches nothing ----------------------------------------------------------------

def test_a_name_nothing_holds_is_not_found_and_every_entry_it_could_take_is_named(
    tmp_path: Path,
) -> None:
    """A plain file is an entry like any other; a dot-led directory is one no removal takes."""
    home = _home(tmp_path)
    _standing(home, "lint", _pyproject("lint"))
    (workflows_dir(home) / "notes.md").write_bytes(b"what is in here\n")
    (workflows_dir(home) / f"{STAGING_PREFIX}1t3p5p_r").mkdir()

    with pytest.raises(NotFoundError) as refused:
        removable(home, "triage")

    assert "What it holds: 'lint', 'notes.md'." in str(refused.value)
    assert STAGING_PREFIX not in str(refused.value)

def test_a_name_only_a_declaration_uses_is_not_found_naming_the_entry_declaring_it(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _standing(home, "triage_dir", _pyproject("triage_dir", declares='sort = "triage_dir:sort"'))

    with pytest.raises(NotFoundError) as refused:
        removable(home, "sort")

    assert "a workflow declared in 'triage_dir'" in str(refused.value)

def test_a_workspace_not_made_yet_holds_nothing_a_removal_could_take(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError) as refused:
        removable(_home(tmp_path), "triage")

    assert "nothing there is an entry `agl remove` could take" in str(refused.value)

@pytest.mark.parametrize(
    "named", [f"{STAGING_PREFIX}1t3p5p_r", ".hidden", ".", "..", "", "a/b", "a\\b"]
)
def test_a_dot_led_name_a_traversal_or_a_path_is_refused_before_the_workspace_is_read(
    tmp_path: Path, named: str
) -> None:
    """`workflows/` is a plain file here, so any refusal but the name's would be the listing's."""
    home = _home(tmp_path)
    workflows_dir(home).parent.mkdir(parents=True)
    workflows_dir(home).write_bytes(b"not a directory")

    with pytest.raises(InputError) as refused:
        removable(home, named)

    assert repr(named) in str(refused.value)
    assert "cannot be listed" not in str(refused.value)

def test_a_workflows_directory_that_cannot_be_listed_refuses_the_removal(
    tmp_path: Path,
) -> None:
    """Refused in the listing's words, which name the directory rather than what was asked for."""
    home = _home(tmp_path)
    workflows_dir(home).parent.mkdir(parents=True)
    workflows_dir(home).write_bytes(b"not a directory")

    with pytest.raises(InputError) as refused:
        removable(home, "triage")

    assert f"{workflows_dir(home)} cannot be listed" in str(refused.value)

# --- what may not be taken out ------------------------------------------------------------------

def test_an_entry_another_member_depends_on_is_refused_naming_every_member_that_does(
    tmp_path: Path,
) -> None:
    """Named as uv compares names, so `Helper>=1` and `HELPER` both reach `helper`'s member."""
    home = _home(tmp_path)
    helper = _standing(home, "helper", _pyproject("helper"))
    first = _standing(home, "first", _pyproject("first", project='dependencies = ["Helper>=1"]'))
    second = _standing(home, "second", _pyproject("second", project='dependencies = ["HELPER"]'))
    other = _standing(home, "other", _pyproject("other", project='dependencies = ["rich"]'))

    with pytest.raises(ConflictError) as refused:
        removable(home, "helper")

    said = str(refused.value)
    assert said.startswith(f"{helper} is not removed")
    assert str(first) in said
    assert str(second) in said
    assert str(other) not in said

def test_a_dependency_on_some_other_distribution_is_no_obstacle_to_a_removal(
    tmp_path: Path,
) -> None:
    """`helpers` is not `helper`, and neither is the entry's own dependency on `rich`."""
    home = _home(tmp_path)
    helper = _standing(home, "helper", _pyproject("helper", project='dependencies = ["rich"]'))
    _standing(home, "other", _pyproject("other", project='dependencies = ["helpers"]'))

    assert removable(home, "helper").path == helper
