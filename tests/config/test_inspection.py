"""`config/inspection.py`: which downloaded workflows may be placed, and why the others may not.

Everything here is decided before anything is placed and before the operator is asked a thing, so
every case below hands `inspected` a download held in memory and a workspace built under
`tmp_path`, and reads back values. **A refusal is a value and never a raise**: `api.py` holds no
`except`, and one workflow's refusal must leave every other workflow in the command where it was.
The one raise is a workspace that cannot be listed at all, which answers for every download at once.

## What is checked, and whose words say so

Discovery's checks are not written a second time. A download's project file is parsed by
`config/toml_file.py` and read by `config/registry.py`'s `declarations`, the function the walk
itself reads a directory through - so a download is refused over an unparseable file, a missing
table, a declaration that is not a string or an AGL bound this AGL fails in the exact words
`agl workflows` would print about the same bytes on disk. One case below compares the two.

What discovery never had to ask is asked as well, because a directory placed in the workspace
joins a uv workspace as well as a registry, and **uv refuses the whole workspace over one bad
member**. What one member's own file must be is `config/workspace_member.py`'s, and every shape of
it is in `tests/config/test_workspace_member.py`; one case here is only that a download goes
through it. What is left here is what no one file can say: two members of one PEP 503 name, and a
dependency naming another member - which uv, seen of 0.11 over a scratch workspace, reads as a
dependency on that member and refuses the sync over, for want of a `[tool.uv.sources]` line.

## What stands where a download is placed

A directory already there is not a refusal: it is the question the operator is asked, and if they
say yes it is replaced - so its own declarations and names are the one thing a download is never
measured against. Everything else is: every other directory, a directory another download in the
same command would replace included, since which of the two survives the questions is not known
yet, and every other download in the command. A name is matched the way a case-insensitive volume
matches it, on every volume, which is `WorkflowName.collision_key`'s rule and the one
`ports/get_request.py` already applies to a command's own workflows.

## The hash, and the mutation that proves its test is not vacuous

`test_a_placed_workflow_measured_back_off_disk_is_the_one_its_provenance_records` places a download
the way a caller must - every file it is handed, bytes as they are - and measures the directory
back. That is the whole of what `agl get` promises the hash: an unedited workflow reads as
unedited. The provenance file sitting in that directory holds the hash, so the hash has to leave
it out, and with `config/provenance.py`'s exclusion deleted that test fails.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final
import pytest
from agl.config.distribution import DISTRIBUTION, installed_version
from agl.config.inspection import Inspection, PlaceableWorkflow, inspected
from agl.config.provenance import parsed_provenance, placed_hash, read_provenance
from agl.config.registry import GROUP, discovered
from agl.ports.errors import AglError, ConflictError, InputError, NotFoundError
from agl.ports.fetch import FetchAnswer, FetchedFile, FetchedWorkflow, RefusedWorkflow
from agl.ports.get_request import GetRequest, RequestedWorkflow
from agl.ports.home_layout import PROVENANCE_FILE, AglHome, workflows_dir

_SHA: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

_OWNER: Final = "jashioq"
_REPO: Final = "myrepo"

_MODULE: Final = b"from agl.sdk import Run, workflow\n"

_BEYOND_REACH: Final = "99999.0.0"

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _requested(name: str, *, owner: str = _OWNER, ref: str | None = None) -> RequestedWorkflow:
    """Parsed, so that its `spec` is the one `parsed_provenance` rebuilds: the argument alone."""
    at = "" if ref is None else f"@{ref}"
    (workflow,) = GetRequest.parsed([f"{owner}/{_REPO}/workflows/mine/{name}{at}"]).workflows
    return workflow

def _pyproject(
    name: str, *, project: str = "", declares: str | None = None, tables: str = ""
) -> bytes:
    """A workflow's project file: its name and version, `project` lines, one declaration, tables."""
    declaration = f'{name} = "{name}:{name}"' if declares is None else declares
    return (
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n{project}\n'
        f'[project.entry-points."{GROUP}"]\n{declaration}\n{tables}'
    ).encode()

def _download(
    name: str,
    pyproject: bytes | None = None,
    *,
    extra: Mapping[str, FetchedFile] | None = None,
    without: str | None = None,
    workflow: RequestedWorkflow | None = None,
) -> FetchedWorkflow:
    """One workflow as a fetcher answers it: a project file, a package module and what else."""
    files = {
        "pyproject.toml": FetchedFile(_pyproject(name) if pyproject is None else pyproject),
        "__init__.py": FetchedFile(_MODULE),
        **(extra or {}),
    }
    if without is not None:
        del files[without]
    return FetchedWorkflow(_requested(name) if workflow is None else workflow, _SHA, files)

def _one(answer: FetchAnswer, home: AglHome) -> Inspection:
    (inspection,) = inspected([answer], home)
    return inspection

def _placeable(inspection: Inspection) -> PlaceableWorkflow:
    assert isinstance(inspection, PlaceableWorkflow), inspection
    return inspection

def _refused(inspection: Inspection, kind: type[AglError]) -> str:
    """The refusal's message, once it is asserted to be a refusal and of the class expected."""
    assert isinstance(inspection, RefusedWorkflow), inspection
    assert isinstance(inspection.refusal, kind), inspection.refusal
    return str(inspection.refusal)

def _standing(home: AglHome, directory: str, pyproject: bytes) -> Path:
    """A directory already in the workspace, holding the project file it is handed."""
    path = workflows_dir(home) / directory
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_bytes(pyproject)
    (path / "__init__.py").write_bytes(_MODULE)
    return path

def _placed(placeable: PlaceableWorkflow, directory: Path) -> Path:
    """What a caller placing a workflow does: every file it is handed, and nothing else."""
    for name, file in placeable.files.items():
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(file.content)
    return directory

# --- a download nothing refuses -----------------------------------------------------------------

def test_a_download_holding_a_whole_workflow_is_placeable_with_its_files_as_they_came(
    tmp_path: Path,
) -> None:
    fetched = _download("triage", extra={"prompts/review.md": FetchedFile(b"# review\n", True)})

    placeable = _placeable(_one(fetched, _home(tmp_path)))

    assert (placeable.workflow, placeable.commit, placeable.existing) == (
        fetched.workflow, _SHA, None
    )
    assert {name: file for name, file in placeable.files.items() if name != PROVENANCE_FILE} == (
        dict(fetched.files)
    )
    assert placeable.dependencies == ()

def test_its_dependencies_are_handed_over_verbatim_and_in_the_order_written(
    tmp_path: Path,
) -> None:
    """What the operator is asked about, spelled as the file spells it - a URL is not hidden.

    The AGL bound sits in the same file and is no dependency: nothing resolves it, so it is not
    something to ask about, and it is absent here although the file carries one this AGL meets.
    """
    written = ("rich", "requests >= 2.31", "probe @ https://example.invalid/probe-1.0.tar.gz")
    fetched = _download(
        "triage",
        _pyproject(
            "triage",
            project=f"dependencies = {list(written)!r}".replace("'", '"'),
            tables=f'\n[tool.agl]\nrequires = "{DISTRIBUTION}>={installed_version()}"\n',
        ),
    )

    assert _placeable(_one(fetched, _home(tmp_path))).dependencies == written

def test_a_refused_download_passes_through_as_the_very_refusal_it_arrived_as(
    tmp_path: Path,
) -> None:
    refused = RefusedWorkflow(_requested("triage"), NotFoundError("no such directory"))

    assert _one(refused, _home(tmp_path)) is refused

def test_one_refused_workflow_leaves_every_other_one_in_the_command_placeable(
    tmp_path: Path,
) -> None:
    """A skip and never an abort, and the answers come back in the order they were handed in."""
    broken = _download("broken", b"[project\n")
    fine = _download("fine")
    missing = RefusedWorkflow(_requested("missing"), NotFoundError("not there"))

    first, second, third = inspected([broken, fine, missing], _home(tmp_path))

    _refused(first, InputError)
    assert _placeable(second).workflow == fine.workflow
    assert third is missing

# --- discovery's own checks, asked of a file that is not on disk yet ------------------------------

def test_a_download_with_no_pyproject_is_refused_before_anything_else_is_read(
    tmp_path: Path,
) -> None:
    fetched = _download("triage", without="pyproject.toml")

    said = _refused(_one(fetched, _home(tmp_path)), InputError)

    assert "jashioq/myrepo/workflows/mine/triage holds no pyproject.toml" in said

def test_a_pyproject_declaring_no_workflow_is_refused_in_the_words_discovery_prints(
    tmp_path: Path,
) -> None:
    """One implementation and one sentence: the same bytes, refused on disk and in memory.

    The walk names the file it read and the download names where it was downloaded from, so the
    two paths are the one difference allowed between them.
    """
    document = b'[project]\nname = "triage"\nversion = "0.1.0"\n'
    said = _refused(_one(_download("triage", document), _home(tmp_path)), InputError)

    elsewhere = AglHome(tmp_path / "elsewhere")
    on_disk = _standing(elsewhere, "triage", document) / "pyproject.toml"
    (walked,) = discovered(elsewhere).broken

    assert said == walked.reason.replace(
        str(on_disk), "jashioq/myrepo/workflows/mine/triage/pyproject.toml"
    )

@pytest.mark.parametrize(
    ("document", "phrase"),
    [
        (b"[project\n", "is not valid TOML"),
        (b"\xff\xfe[project]\n", "cannot be read"),
        (_pyproject("triage", declares="triage = 3"), "is not a string"),
    ],
)
def test_a_project_file_discovery_would_call_broken_is_refused_before_placement(
    tmp_path: Path, document: bytes, phrase: str
) -> None:
    said = _refused(_one(_download("triage", document), _home(tmp_path)), InputError)

    assert "jashioq/myrepo/workflows/mine/triage/pyproject.toml" in said
    assert phrase in said

def test_a_file_downloaded_at_a_ref_is_named_by_its_repository_and_directory_alone(
    tmp_path: Path,
) -> None:
    """An argument writes its ref last, so a file's path spelled from one would run through the ref.

    `.../triage@release/1.0/pyproject.toml` reads as a directory `triage@release` holding one named
    `1.0`, and the repository holds neither.
    """
    asked = _requested("triage", ref="release/1.0")
    fetched = _download("triage", b"[project\n", workflow=asked)

    said = _refused(_one(fetched, _home(tmp_path)), InputError)

    assert "jashioq/myrepo/workflows/mine/triage/pyproject.toml is not valid TOML" in said
    assert "@release/1.0" not in said

def test_a_workflow_needing_an_agl_this_is_not_is_refused_naming_both_versions(
    tmp_path: Path,
) -> None:
    needing = _pyproject(
        "triage", tables=f'\n[tool.agl]\nrequires = "{DISTRIBUTION}>={_BEYOND_REACH}"\n'
    )

    said = _refused(_one(_download("triage", needing), _home(tmp_path)), InputError)

    assert f">={_BEYOND_REACH}" in said
    assert installed_version() in said

def test_a_bound_the_running_agl_meets_is_no_obstacle_to_placing_it(tmp_path: Path) -> None:
    """The control for the case above, the bound composed from the version this AGL reports."""
    meeting = _pyproject(
        "triage", tables=f'\n[tool.agl]\nrequires = "{DISTRIBUTION}>={installed_version()}"\n'
    )

    _placeable(_one(_download("triage", meeting), _home(tmp_path)))

# --- what would stop it loading ------------------------------------------------------------------

def test_a_download_without_an_init_module_is_refused_as_a_namespace_package(
    tmp_path: Path,
) -> None:
    said = _refused(_one(_download("triage", without="__init__.py"), _home(tmp_path)), InputError)

    assert "__init__.py" in said
    assert "namespace package" in said

@pytest.mark.parametrize("value", ["os:system", "other:other", "triage_two:run", "agl.sdk:Run"])
def test_a_declaration_naming_a_module_outside_its_own_package_is_refused(
    tmp_path: Path, value: str
) -> None:
    """Whatever answers to that name on the import path would run, and none of it was downloaded.

    `triage_two` shares a prefix with the package and is not inside it, which is why the top-level
    module is compared whole rather than by what it starts with.
    """
    fetched = _download("triage", _pyproject("triage", declares=f'triage = "{value}"'))

    said = _refused(_one(fetched, _home(tmp_path)), InputError)

    assert repr(value) in said
    assert "'triage'" in said

def test_a_declaration_naming_a_module_inside_its_own_package_is_placeable(
    tmp_path: Path,
) -> None:
    """The control: a submodule and a key other than the package's own name are both fine."""
    fetched = _download("triage", _pyproject("triage", declares='review = "triage.flows:review"'))

    _placeable(_one(fetched, _home(tmp_path)))

def test_a_declaration_importlib_cannot_read_as_an_entry_point_is_refused(
    tmp_path: Path,
) -> None:
    fetched = _download("triage", _pyproject("triage", declares='triage = "triage:run extra"'))

    said = _refused(_one(fetched, _home(tmp_path)), InputError)

    assert "'triage:run extra'" in said
    assert "not an entry point" in said

# --- what would stop uv syncing the workspace it joins --------------------------------------------

@pytest.mark.parametrize(
    ("document", "named"),
    [
        (_pyproject("triage").replace(b'version = "0.1.0"\n', b""), "[project] version"),
        (
            _pyproject("triage", tables='\n[tool.uv.sources]\nrich = { path = "../x" }\n'),
            "[tool.uv]",
        ),
    ],
)
def test_a_download_uv_would_not_sync_as_it_stands_is_refused_before_placement(
    tmp_path: Path, document: bytes, named: str
) -> None:
    """Only that a download goes through `config/workspace_member.py`, which refuses these.

    Every shape that module refuses is in `tests/config/test_workspace_member.py`.
    """
    said = _refused(_one(_download("triage", document), _home(tmp_path)), InputError)

    assert "jashioq/myrepo/workflows/mine/triage/pyproject.toml" in said
    assert named in said

# --- what arrives and is never placed -------------------------------------------------------------

def test_bytecode_arriving_in_a_download_is_never_placed_at_any_depth(tmp_path: Path) -> None:
    """Written again from the source at the first import, and invisible to review until then.

    A shipped `.pyc` can be one CPython runs without checking it against the source beside it, so
    placing it would place code nobody read. A file that is merely *called* `__pycache__` is not
    bytecode's directory and stays, which is where the same line of `digests` draws it.
    """
    arrived = {
        "__pycache__/__init__.cpython-314.pyc": FetchedFile(b"not the source"),
        "flows/__pycache__/review.cpython-314.pyc": FetchedFile(b"nor this"),
        "flows/review.py": FetchedFile(b"REVIEW = 1\n"),
        "notes/__pycache__": FetchedFile(b"a file, whatever its name says"),
    }

    placeable = _placeable(_one(_download("triage", extra=arrived), _home(tmp_path)))

    assert sorted(placeable.files) == sorted(
        [PROVENANCE_FILE, "__init__.py", "flows/review.py", "notes/__pycache__", "pyproject.toml"]
    )

def test_a_provenance_file_arriving_in_a_download_is_replaced_by_agls_own(
    tmp_path: Path,
) -> None:
    """Somebody's own record, committed by accident, describing another copy on another day."""
    stale = b'{"owner": "someone", "commit": "0000000000000000000000000000000000000000"}\n'
    fetched = _download("triage", extra={PROVENANCE_FILE: FetchedFile(stale)})

    placeable = _placeable(_one(fetched, _home(tmp_path)))

    written = parsed_provenance(Path(PROVENANCE_FILE), placeable.files[PROVENANCE_FILE].content)
    assert (written.workflow, written.commit) == (fetched.workflow, _SHA)

def test_a_directory_arriving_under_the_provenance_files_name_goes_with_it(
    tmp_path: Path,
) -> None:
    """That name at the root is AGL's file, and a directory of that name could not stand by it."""
    arrived = {f"{PROVENANCE_FILE}/inside.md": FetchedFile(b"not a record at all")}

    placeable = _placeable(_one(_download("triage", extra=arrived), _home(tmp_path)))

    assert [name for name in placeable.files if name.startswith(PROVENANCE_FILE)] == [
        PROVENANCE_FILE
    ]

# --- the provenance file AGL writes, and the hash inside it ---------------------------------------

def test_the_provenance_records_the_spelling_and_the_ref_it_was_asked_for_with(
    tmp_path: Path,
) -> None:
    """Owner and name as typed, whatever case a fetch was grouped under, and the ref unresolved."""
    asked = _requested("triage", owner="JasHioq", ref="v1.2.0")

    placeable = _placeable(_one(_download("triage", workflow=asked), _home(tmp_path)))

    written = parsed_provenance(Path(PROVENANCE_FILE), placeable.files[PROVENANCE_FILE].content)
    assert written.workflow == asked
    assert (written.workflow.repository.owner, written.workflow.repository.ref) == (
        "JasHioq", "v1.2.0"
    )

def test_a_placed_workflow_measured_back_off_disk_is_the_one_its_provenance_records(
    tmp_path: Path,
) -> None:
    """The one promise the hash makes: a workflow nobody touched reads as untouched.

    Placed from exactly what `inspected` handed back, and measured back off disk - so the file
    holding the hash is among what is on disk, and a hash that counted it would never match. This
    test fails with `config/provenance.py`'s exclusion of that file deleted.
    """
    fetched = _download("triage", extra={"flows/review.py": FetchedFile(b"X = 1\n")})

    directory = _placed(_placeable(_one(fetched, _home(tmp_path))), tmp_path / "placed")

    recorded = read_provenance(directory)
    assert recorded is not None
    assert placed_hash(directory) == recorded.content_hash

def test_bytecode_written_after_placement_leaves_the_measured_hash_where_it_was(
    tmp_path: Path,
) -> None:
    """The first import writes `__pycache__` into the placed directory, and that is no edit."""
    directory = _placed(_placeable(_one(_download("triage"), _home(tmp_path))), tmp_path / "placed")
    before = placed_hash(directory)

    (directory / "__pycache__").mkdir()
    (directory / "__pycache__" / "__init__.cpython-314.pyc").write_bytes(b"compiled")

    assert placed_hash(directory) == before

def test_a_downloaded_ds_store_is_placed_and_left_out_of_the_recorded_hash(
    tmp_path: Path,
) -> None:
    """Committed upstream at the top and a level down, and placed as it came, unlike bytecode.

    Nothing runs a `.DS_Store`, so placing one puts no code past what the hash measures. It is left
    out of that hash as a download is measured in memory - the answer the same download without it
    records - and as the placed copy is measured back off disk, which is that answer again.
    """
    kept = {"flows/review.py": FetchedFile(b"REVIEW = 1\n")}
    finder = FetchedFile(b"\x00\x00\x00\x01Bud1")
    arrived = {**kept, ".DS_Store": finder, "flows/.DS_Store": finder}

    placeable = _placeable(_one(_download("triage", extra=arrived), _home(tmp_path)))
    directory = _placed(placeable, tmp_path / "placed")

    without = _placeable(_one(_download("triage", extra=kept), _home(tmp_path)))
    unshipped = parsed_provenance(Path(PROVENANCE_FILE), without.files[PROVENANCE_FILE].content)
    recorded = read_provenance(directory)
    assert recorded is not None
    assert {".DS_Store", "flows/.DS_Store"} <= set(placeable.files)
    assert recorded.content_hash == unshipped.content_hash
    assert placed_hash(directory) == recorded.content_hash

def test_an_edit_to_a_placed_file_moves_the_measured_hash(tmp_path: Path) -> None:
    directory = _placed(_placeable(_one(_download("triage"), _home(tmp_path))), tmp_path / "placed")
    before = placed_hash(directory)

    (directory / "__init__.py").write_bytes(_MODULE + b"# mine\n")

    assert placed_hash(directory) != before

# --- what already stands where it would be placed -------------------------------------------------

def test_a_workflow_already_in_the_workspace_is_named_as_what_placing_it_replaces(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    standing = _standing(home, "triage", _pyproject("triage"))

    assert _placeable(_one(_download("triage"), home)).existing == standing

@pytest.mark.parametrize("spelled", ["Triage", "TRIAGE"])
def test_a_directory_differing_only_in_case_is_the_one_a_download_replaces(
    tmp_path: Path, spelled: str
) -> None:
    home = _home(tmp_path)
    standing = _standing(home, spelled, _pyproject("elsewhere"))

    assert _placeable(_one(_download("triage"), home)).existing == standing

def test_a_directory_named_as_no_workflow_could_be_still_answers_to_its_folded_name(
    tmp_path: Path,
) -> None:
    """`class` is a keyword and no workflow's name, and on a Mac it is `Class`'s directory too."""
    home = _home(tmp_path)
    standing = _standing(home, "class", b'[project]\nname = "kept"\nversion = "0.1.0"\n')

    assert _placeable(_one(_download("Class"), home)).existing == standing

def test_what_it_would_replace_is_never_counted_against_its_own_names(tmp_path: Path) -> None:
    """The workflow being fetched again: same declaration, same distribution, and no conflict."""
    home = _home(tmp_path)
    _standing(home, "triage", _pyproject("triage", project='dependencies = ["rich"]'))

    _placeable(_one(_download("triage"), home))

def test_entries_differing_only_in_case_refuse_the_download_rather_than_choosing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two spellings of one name can stand side by side only on a case-sensitive volume.

    Where this suite runs on a case-insensitive one the second directory cannot be made, so the
    listing is made to report both spellings - which is the whole of what that volume would show.
    """
    home = _home(tmp_path)
    _standing(home, "Triage", _pyproject("one"))
    container = workflows_dir(home)
    if (container / "TRIAGE").exists():
        listing = Path.iterdir
        spellings = [container / "TRIAGE", container / "Triage"]
        monkeypatch.setattr(
            Path, "iterdir", lambda path: iter(spellings) if path == container else listing(path)
        )
    else:
        _standing(home, "TRIAGE", _pyproject("two"))

    said = _refused(_one(_download("triage"), home), ConflictError)

    assert "Triage" in said
    assert "TRIAGE" in said

# --- names it may not share with the rest of the workspace ----------------------------------------

def test_a_name_another_directory_already_declares_is_refused_as_a_conflict(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    other = _standing(home, "other", _pyproject("other", declares='review = "other:review"'))
    fetched = _download("triage", _pyproject("triage", declares='review = "triage:review"'))

    said = _refused(_one(fetched, home), ConflictError)

    assert "'review'" in said
    assert str(other) in said

@pytest.mark.parametrize("spelled", ["Shared_Name", "shared.name", "SHARED--NAME"])
def test_a_distribution_name_another_member_holds_under_pep_503_is_refused(
    tmp_path: Path, spelled: str
) -> None:
    home = _home(tmp_path)
    named = _pyproject("other").replace(b'"other"', f'"{spelled}"'.encode(), 1)
    other = _standing(home, "other", named)
    fetched = _download("triage", _pyproject("triage").replace(b'"triage"', b'"shared-name"', 1))

    said = _refused(_one(fetched, home), ConflictError)

    assert "'shared-name'" in said
    assert str(other) in said

def test_a_dependency_on_another_members_distribution_name_is_refused(tmp_path: Path) -> None:
    """uv reads it as a dependency on that member, and refuses the sync with no source saying so."""
    home = _home(tmp_path)
    other = _standing(home, "helper", _pyproject("helper"))
    fetched = _download("triage", _pyproject("triage", project='dependencies = ["Helper>=1"]'))

    said = _refused(_one(fetched, home), ConflictError)

    assert "'helper'" in said
    assert str(other) in said

def test_a_download_named_as_another_members_dependency_is_refused(tmp_path: Path) -> None:
    home = _home(tmp_path)
    other = _standing(home, "other", _pyproject("other", project='dependencies = ["triage"]'))

    said = _refused(_one(_download("triage"), home), ConflictError)

    assert str(other) in said

def test_an_unreadable_neighbour_holds_no_name_a_download_could_collide_with(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _standing(home, "half-written", b"[project\n")
    (workflows_dir(home) / "notes").mkdir()
    (workflows_dir(home) / "README.md").write_bytes(b"what is in here\n")

    _placeable(_one(_download("triage"), home))

def test_two_downloads_in_one_command_declaring_one_name_are_both_refused(
    tmp_path: Path,
) -> None:
    """AGL will not choose between them, here any more than `agl workflows` would afterwards."""
    one = _download("one", _pyproject("one", declares='review = "one:review"'))
    two = _download("two", _pyproject("two", declares='review = "two:review"'))

    first, second = inspected([one, two], _home(tmp_path))

    assert "'jashioq/myrepo/workflows/mine/two'" in _refused(first, ConflictError)
    assert "'jashioq/myrepo/workflows/mine/one'" in _refused(second, ConflictError)

def test_two_downloads_in_one_command_sharing_a_distribution_name_are_both_refused(
    tmp_path: Path,
) -> None:
    one = _download("one", _pyproject("one").replace(b'"one"', b'"same"', 1))
    two = _download("two", _pyproject("two").replace(b'"two"', b'"Same"', 1))

    first, second = inspected([one, two], _home(tmp_path))

    _refused(first, ConflictError)
    _refused(second, ConflictError)

def test_a_directory_another_download_would_replace_still_counts_against_this_one(
    tmp_path: Path,
) -> None:
    """Until the operator answers, the directory `two` would replace is as real as any other.

    If they decline, it stays - declaring `review` beside the `one` this command would have placed.
    """
    home = _home(tmp_path)
    _standing(home, "two", _pyproject("two", declares='review = "two:review"'))
    one = _download("one", _pyproject("one", declares='review = "one:review"'))

    first, second = inspected([one, _download("two")], home)

    assert str(workflows_dir(home) / "two") in _refused(first, ConflictError)
    assert _placeable(second).existing == workflows_dir(home) / "two"

# --- the workspace itself ----------------------------------------------------------------------

def test_a_workspace_not_made_yet_holds_nothing_a_download_could_collide_with(
    tmp_path: Path,
) -> None:
    assert not workflows_dir(_home(tmp_path)).exists()

    _placeable(_one(_download("triage"), _home(tmp_path)))

def test_a_workflows_directory_that_cannot_be_listed_refuses_the_whole_command(
    tmp_path: Path,
) -> None:
    """Nothing can be measured against a workspace nobody can read, so no one download answers."""
    home = _home(tmp_path)
    workflows_dir(home).parent.mkdir(parents=True)
    workflows_dir(home).write_bytes(b"not a directory")

    with pytest.raises(InputError) as refused:
        inspected([_download("triage")], home)

    assert str(workflows_dir(home)) in str(refused.value)
