"""`api.update`, driven from the library side: `get`'s three phases over whatever moved.

Every workflow `agl get` placed is checked first, and each one whose ref names another commit now
is downloaded again at that ref, inspected, asked about and placed over the copy standing in the
workspace - fetched and inspected all at once, then every question put, and only then anything
placed. The `confirm` below looks at the workspace at the moment each question is put, as
`tests/test_get.py`'s does, so the order is asserted from inside the command.

**The questions are `update`'s own.** A copy that measures other than its provenance records has
changed since it was placed, and replacing it is the one thing in this command nothing can undo,
so it is asked about first; a dependency the new version declares and the copy does not is asked
about next. A copy that neither changed nor gains anything is replaced without a question, since
the operator asked for the update and those two are the things they could not have seen.

**What stands under another name, or is a link, is not replaced**, and neither is a copy that
cannot be measured: each is refused before anything is downloaded, and every other workflow is
updated regardless.

Everything runs on fakes: `FakeFetcher` for the questions about refs and for the downloads, and a
syncer written here that answers yes and keeps what it was handed.
"""

import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.adapters.github.fake import FakeFetcher
from agl.config.comparison import Updated
from agl.config.provenance import Provenance, fetched_hash, placed_hash, read_provenance, rendered
from agl.config.registry import GROUP
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.fetch import FetchedFile, Resolution, ResolvedRef
from agl.ports.get_request import RepositoryAtRef, RequestedWorkflow
from agl.ports.home_layout import PROVENANCE_FILE, AglHome, workflows_dir, workspace_dir
from agl.ports.sync import Syncer, SyncOutcome

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

_PLACED_FROM: Final = "0b496e91ec7ae4428c3ed2eeb4c3a40df431f2cc"
_NOW: Final = "f548e57e544e1ff5a4c46bf1e1b8685f8e4a348a"
_LATER: Final = "a5b1c2d3e4f5061728394a5b6c7d8e9f00112233"

_FLOWS: Final = RepositoryAtRef("octo", "flows", None)
_RELEASED: Final = RepositoryAtRef("octo", "flows", "release/1.0")
_NOWHERE: Final = RepositoryAtRef("octo", "nope", None)

_MODULE: Final = b"from agl.sdk import Run, workflow\n"
_MODULE_NOW: Final = b"from agl.sdk import Run, workflow\n\n# as upstream has it now\n"

class _Recording(Syncer):
    """A syncer that answers yes, keeping each workspace it was handed and how much was reported."""

    def __init__(self, reports: list[Updated] | None = None) -> None:
        self.asked: list[Path] = []
        self.reported: list[int] = []
        self._reports = [] if reports is None else reports

    async def sync(self, workspace: Path) -> SyncOutcome:
        self.asked.append(workspace)
        self.reported.append(len(self._reports))
        return SyncOutcome(synced=True, status=0, output="")

class _MovedAgain(FakeFetcher):
    """A fetcher whose refs move once more between the check and the download, as busy ones do.

    Each question about a ref is answered `_NOW`, while the download that follows it is at whatever
    commit the repository is served at - which is what the real service does when somebody pushes
    in between.
    """

    async def resolve(self, repository: RepositoryAtRef) -> Resolution:
        await super().resolve(repository)
        return ResolvedRef(repository, _NOW)

def _home(tmp_path: Path) -> AglHome:
    return AglHome(tmp_path / "home")

def _pyproject(name: str, dependencies: str = "") -> bytes:
    return (
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n{dependencies}\n'
        f'[project.entry-points."{GROUP}"]\n{name} = "{name}:{name}"\n'
    ).encode()

def _placed(
    home: AglHome,
    name: str,
    repository: RepositoryAtRef = _FLOWS,
    *,
    dependencies: str = "",
    entry_name: str | None = None,
) -> Path:
    """A workflow as `agl get` leaves one: its files, and the provenance it wrote last.

    `entry_name` stands it under another name than the one it was placed as, as a rename would.
    """
    entry = workflows_dir(home) / (entry_name or name)
    entry.mkdir(parents=True)
    (entry / "pyproject.toml").write_bytes(_pyproject(name, dependencies))
    (entry / "__init__.py").write_bytes(_MODULE)
    unspelled = RequestedWorkflow(repository, f"workflows/{name}", "")
    workflow = replace(unspelled, spec=str(unspelled))
    (entry / PROVENANCE_FILE).write_bytes(
        rendered(Provenance(workflow, _PLACED_FROM, placed_hash(entry)))
    )
    return entry

def _serving(
    fetcher: FakeFetcher,
    repository: RepositoryAtRef,
    *names: str,
    commit: str = _NOW,
    depending: dict[str, str] | None = None,
) -> FakeFetcher:
    """`repository` at `commit`, holding each named workflow as upstream has it now."""
    files: dict[str, FetchedFile] = {}
    for name in names:
        written = _pyproject(name, (depending or {}).get(name, ""))
        files[f"workflows/{name}/pyproject.toml"] = FetchedFile(written)
        files[f"workflows/{name}/__init__.py"] = FetchedFile(_MODULE_NOW)
    fetcher.serves(repository, files, commit=commit)
    return fetcher

def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Every entry under `root` - a directory as `None`, a file as its bytes - or nothing at all."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }

def _changed(entry: Path) -> None:
    """The operator's own edit to a placed copy: a line added to its module."""
    with (entry / "__init__.py").open("ab") as module:
        module.write(b"# mine\n")

class _Operator:
    """Answers each question with the next answer it was scripted with, and keeps every one."""

    def __init__(self, *answers: bool) -> None:
        self.asked: list[str] = []
        self._answers = list(answers)

    def __call__(self, question: str) -> bool:
        assert self._answers, f"asked {question!r} with no answer left to give"
        self.asked.append(question)
        return self._answers.pop(0)

def _never(question: str) -> bool:
    raise AssertionError(f"asked a question where none should have been: {question}")

async def _update(
    home: AglHome,
    fetcher: FakeFetcher,
    confirm: Callable[[str], bool] = _never,
    *,
    syncer: Syncer | None = None,
    name: str | None = None,
) -> Updated:
    return await api.update(
        fetcher, syncer or _Recording(), home, name, confirm, lambda updated: None
    )

# --- the order ----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nothing_reaches_the_workspace_until_every_update_question_has_been_answered(
    tmp_path: Path,
) -> None:
    """Two questions over two workflows, and the workspace is exactly as it was at each of them.

    `triage` changed since it was placed and `lint` gains a dependency, and `release` asks nothing
    - so an update that placed as it went would have written `release`, or the approved `triage`,
    by the time `lint` was asked about.
    """
    home = _home(tmp_path)
    _changed(_placed(home, "triage"))
    _placed(home, "lint")
    _placed(home, "release")
    before = _snapshot(home.path)
    seen: list[dict[str, bytes | None]] = []

    def looking(question: str) -> bool:
        seen.append(_snapshot(home.path))
        return True

    fetcher = _serving(
        FakeFetcher(),
        _FLOWS,
        "triage",
        "lint",
        "release",
        depending={"lint": 'dependencies = ["httpx"]'},
    )
    updated = await _update(home, fetcher, looking)

    assert seen == [before, before]
    assert sorted(str(one.workflow.name) for one in updated.got.placed) == [
        "lint",
        "release",
        "triage",
    ]

# --- the question about local changes ------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_changed_copy_asked_about_and_declined_keeps_every_byte_it_held(
    tmp_path: Path,
) -> None:
    """The operator's copy, their edit in it and its provenance, byte for byte - and no sync."""
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    _changed(entry)
    before = _snapshot(home.path)
    syncer = _Recording()

    updated = await _update(
        home, _serving(FakeFetcher(), _FLOWS, "triage"), _Operator(False), syncer=syncer
    )

    assert [str(one.placeable.workflow.name) for one in updated.got.declined] == ["triage"]
    assert updated.got.placed == ()
    assert _snapshot(home.path) == before
    assert syncer.asked == []

@pytest.mark.asyncio
async def test_a_changed_copy_asked_about_and_approved_is_replaced_whole_by_the_download(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    _changed(entry)
    (entry / "notes.md").write_bytes(b"# the operator's own notes\n")
    syncer = _Recording()

    updated = await _update(
        home, _serving(FakeFetcher(), _FLOWS, "triage"), _Operator(True), syncer=syncer
    )

    assert [one.directory for one in updated.got.placed] == [entry]
    assert sorted(path.name for path in entry.iterdir()) == [
        PROVENANCE_FILE,
        "__init__.py",
        "pyproject.toml",
    ]
    assert (entry / "__init__.py").read_bytes() == _MODULE_NOW
    assert syncer.asked == [workspace_dir(home)]

@pytest.mark.asyncio
async def test_the_local_changes_question_names_the_copy_both_commits_and_the_loss(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    _changed(entry)
    operator = _Operator(False)

    await _update(home, _serving(FakeFetcher(), _FLOWS, "triage"), operator)

    assert operator.asked == [
        f"{entry} has changed since it was placed from 0b496e9, and updating it to f548e57 "
        f"replaces it whole, discarding those changes. Update it?"
    ]

@pytest.mark.asyncio
async def test_an_unchanged_copy_whose_ref_moved_is_replaced_without_a_single_question(
    tmp_path: Path,
) -> None:
    """The operator asked for the update, and nothing here is something they could not have seen."""
    home = _home(tmp_path)
    entry = _placed(home, "triage")

    updated = await _update(home, _serving(FakeFetcher(), _FLOWS, "triage"), _never)

    assert [one.directory for one in updated.got.placed] == [entry]
    assert (entry / "__init__.py").read_bytes() == _MODULE_NOW

# --- the question about dependencies -------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_dependency_the_copy_does_not_declare_as_written_is_named_and_no_other(
    tmp_path: Path,
) -> None:
    """A new name and a changed bound are named; one kept exactly, and one dropped, are not.

    The copy declares `httpx>=0.27`, `rich` and `click`. The update declares `httpx>=0.28` - the
    same package at another bound, which installs something the copy never asked for - `rich`
    unchanged, and `pydantic>=2,<3`, and drops `click`, which installs nothing.
    """
    home = _home(tmp_path)
    _placed(home, "triage", dependencies='dependencies = ["httpx>=0.27", "rich", "click"]')
    fetcher = _serving(
        FakeFetcher(),
        _FLOWS,
        "triage",
        depending={"triage": 'dependencies = ["httpx>=0.28", "rich", "pydantic>=2,<3"]'},
    )
    operator = _Operator(False)

    await _update(home, fetcher, operator)

    (asked,) = operator.asked
    assert "'httpx>=0.28', 'pydantic>=2,<3'. Continue?" in asked
    assert "'rich'" not in asked
    assert "click" not in asked
    assert asked.startswith("octo/flows/workflows/triage at f548e57 declares third-party")

@pytest.mark.asyncio
async def test_dependencies_the_copy_already_declares_are_asked_nothing_at_all(
    tmp_path: Path,
) -> None:
    """`agl get` asks about every dependency; an update, only about what it would add."""
    home = _home(tmp_path)
    _placed(home, "triage", dependencies='dependencies = ["httpx>=0.27"]')
    fetcher = _serving(
        FakeFetcher(), _FLOWS, "triage", depending={"triage": 'dependencies = ["httpx>=0.27"]'}
    )

    updated = await _update(home, fetcher, _never)

    assert len(updated.got.placed) == 1

@pytest.mark.asyncio
async def test_a_changed_copy_declined_is_never_asked_about_the_dependencies_it_would_gain(
    tmp_path: Path,
) -> None:
    """The first no settles a workflow, and one that is not placed installs nothing."""
    home = _home(tmp_path)
    _changed(_placed(home, "triage"))
    fetcher = _serving(
        FakeFetcher(), _FLOWS, "triage", depending={"triage": 'dependencies = ["httpx"]'}
    )
    operator = _Operator(False)

    await _update(home, fetcher, operator)

    (asked,) = operator.asked
    assert "has changed since it was placed" in asked

# --- a decline, and a refusal, touch one workflow each -------------------------------------------

@pytest.mark.asyncio
async def test_a_decline_skips_only_its_own_workflow_and_every_other_one_is_updated(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    kept = _placed(home, "alpha")
    _changed(kept)
    before = _snapshot(kept)
    also_changed = _placed(home, "beta")
    _changed(also_changed)
    unchanged = _placed(home, "gamma")

    updated = await _update(
        home, _serving(FakeFetcher(), _FLOWS, "alpha", "beta", "gamma"), _Operator(False, True)
    )

    assert [str(one.placeable.workflow.name) for one in updated.got.declined] == ["alpha"]
    assert sorted(str(one.workflow.name) for one in updated.got.placed) == ["beta", "gamma"]
    assert _snapshot(kept) == before
    assert (also_changed / "__init__.py").read_bytes() == _MODULE_NOW
    assert (unchanged / "__init__.py").read_bytes() == _MODULE_NOW

@pytest.mark.asyncio
async def test_a_copy_under_another_name_than_it_was_placed_as_is_refused_and_never_fetched(
    tmp_path: Path,
) -> None:
    """Renamed from `triage` to `triage_old`: a conflict naming both, and the other one updated."""
    home = _home(tmp_path)
    renamed = _placed(home, "triage", entry_name="triage_old")
    before = _snapshot(renamed)
    _placed(home, "lint", _RELEASED)
    fetcher = _serving(FakeFetcher(), _FLOWS, "triage")
    _serving(fetcher, _RELEASED, "lint")

    updated = await _update(home, fetcher)

    (refused,) = updated.replacements.unreplaceable
    assert refused.entry == renamed
    assert isinstance(refused.refusal, ConflictError)
    assert "`agl get` placed as 'triage'" in str(refused.refusal)
    assert [fetch.repository for fetch in fetcher.fetched] == [_RELEASED]
    assert [str(one.workflow.name) for one in updated.got.placed] == ["lint"]
    assert _snapshot(renamed) == before

@pytest.mark.asyncio
async def test_a_copy_that_is_a_link_is_refused_and_what_the_link_names_is_left_as_it_is(
    tmp_path: Path,
) -> None:
    """Replacing it would swap the operator's checkout out for a download without a word said."""
    home = _home(tmp_path)
    elsewhere = _placed(AglHome(tmp_path / "elsewhere"), "triage")
    before = _snapshot(elsewhere)
    workflows_dir(home).mkdir(parents=True)
    link = workflows_dir(home) / "triage"
    link.symlink_to(elsewhere, target_is_directory=True)
    fetcher = _serving(FakeFetcher(), _FLOWS, "triage")

    updated = await _update(home, fetcher)

    (refused,) = updated.replacements.unreplaceable
    assert isinstance(refused.refusal, ConflictError)
    assert f"{link} is a link" in str(refused.refusal)
    assert link.is_symlink()
    assert _snapshot(elsewhere) == before
    assert fetcher.fetched == ()

@pytest.mark.asyncio
async def test_a_copy_that_cannot_be_measured_is_refused_rather_than_replaced(
    tmp_path: Path,
) -> None:
    """Whether it changed cannot be told, so it is not replaced, and nothing is downloaded."""
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    unreadable = entry / "secret.md"
    unreadable.write_bytes(b"# not for anyone\n")
    unreadable.chmod(0)
    if os.access(unreadable, os.R_OK):
        unreadable.chmod(0o644)
        pytest.skip("this user reads a file whatever its mode says, as root does")
    fetcher = _serving(FakeFetcher(), _FLOWS, "triage")

    try:
        updated = await _update(home, fetcher)
    finally:
        unreadable.chmod(0o644)

    (refused,) = updated.replacements.unreplaceable
    assert isinstance(refused.refusal, InputError)
    assert f"{entry} cannot be measured" in str(refused.refusal)
    assert fetcher.fetched == ()

@pytest.mark.asyncio
async def test_every_refusal_whichever_phase_made_it_is_one_of_the_updates_refusals(
    tmp_path: Path,
) -> None:
    """A ref that cannot be resolved, a renamed copy and a download that is no workflow: three."""
    home = _home(tmp_path)
    _placed(home, "gone", _NOWHERE)
    _placed(home, "triage", entry_name="triage_old")
    _placed(home, "hollow")
    fetcher = FakeFetcher()
    fetcher.serves(_FLOWS, {"workflows/hollow/__init__.py": FetchedFile(_MODULE)}, commit=_NOW)

    updated = await _update(home, fetcher)

    assert [type(one) for one in updated.refusals] == [NotFoundError, ConflictError, InputError]

# --- where it is fetched from, and what it records ------------------------------------------------

@pytest.mark.asyncio
async def test_workflows_sharing_a_repository_and_ref_are_one_download_at_the_recorded_ref(
    tmp_path: Path,
) -> None:
    """One fetch per repository at a ref, asked at the ref recorded and never at the commit."""
    home = _home(tmp_path)
    _placed(home, "alpha", _RELEASED)
    _placed(home, "beta", _RELEASED)
    _placed(home, "gamma")
    fetcher = _serving(FakeFetcher(), _RELEASED, "alpha", "beta")
    _serving(fetcher, _FLOWS, "gamma")

    await _update(home, fetcher)

    assert [(fetch.repository, len(fetch.workflows)) for fetch in fetcher.fetched] == [
        (_RELEASED, 2),
        (_FLOWS, 1),
    ]

@pytest.mark.parametrize("repository", [_FLOWS, _RELEASED], ids=["default branch", "slashed ref"])
@pytest.mark.asyncio
async def test_the_new_provenance_keeps_the_ref_records_the_downloaded_commit_and_its_hash(
    tmp_path: Path, repository: RepositoryAtRef
) -> None:
    """The ref as it was recorded - `null` staying `null` - and the commit the download names.

    The ref moves again between the check and the download here, so the commit recorded is the
    newer one the files were taken from and not the one the check was told; the hash is the one
    the directory now measures, and the one the files handed over hash to.
    """
    home = _home(tmp_path)
    entry = _placed(home, "triage", repository)
    fetcher = _serving(_MovedAgain(), repository, "triage", commit=_LATER)

    updated = await _update(home, fetcher)

    (one,) = updated.got.placed
    assert one.commit == _LATER
    recorded = read_provenance(entry)
    assert recorded is not None
    assert recorded.workflow.repository == repository
    assert recorded.commit == _LATER
    assert recorded.content_hash == placed_hash(entry)
    handed_over = {
        "pyproject.toml": FetchedFile(_pyproject("triage")),
        "__init__.py": FetchedFile(_MODULE_NOW),
    }
    assert recorded.content_hash == fetched_hash(handed_over)

# --- the report and the sync --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_what_became_of_each_workflow_is_reported_once_before_the_sync_starts(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _placed(home, "triage")
    _placed(home, "lint")
    reports: list[Updated] = []
    syncer = _Recording(reports)

    updated = await api.update(
        _serving(FakeFetcher(), _FLOWS, "triage", "lint"),
        syncer,
        home,
        None,
        _never,
        reports.append,
    )

    assert reports == [updated]
    assert syncer.reported == [1]
    assert syncer.asked == [workspace_dir(home)]

@pytest.mark.asyncio
async def test_nothing_moved_downloads_nothing_asks_nothing_and_starts_no_sync(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _placed(home, "triage")
    before = _snapshot(home.path)
    fetcher = _serving(FakeFetcher(), _FLOWS, "triage", commit=_PLACED_FROM)
    syncer = _Recording()

    updated = await _update(home, fetcher, _never, syncer=syncer)

    assert updated.got.placed == ()
    assert fetcher.fetched == ()
    assert syncer.asked == []
    assert _snapshot(home.path) == before

@pytest.mark.asyncio
async def test_a_name_updates_that_one_workflow_and_leaves_every_other_moved_one_alone(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _placed(home, "triage")
    other = _placed(home, "lint")
    before = _snapshot(other)

    updated = await _update(home, _serving(FakeFetcher(), _FLOWS, "triage", "lint"), name="triage")

    assert [str(one.workflow.name) for one in updated.got.placed] == ["triage"]
    assert _snapshot(other) == before

# --- what the hash the question rests on can and cannot see --------------------------------------
#
# Whether a copy changed is `config/provenance.py`'s `placed_hash` against the hash its provenance
# records - `config/workflow_files.py`'s scheme, which a golden test pins and `run.json`'s digests
# share - so what that scheme counts is what this question can see. Both halves are written down
# here as they stand rather than left to be discovered.

@pytest.mark.asyncio
async def test_a_file_finder_leaves_in_a_copy_reads_as_a_change_and_is_asked_about(
    tmp_path: Path,
) -> None:
    """`.DS_Store` is a file like any other to the hash, so a folder opened in Finder is asked."""
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    (entry / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    operator = _Operator(False)

    await _update(home, _serving(FakeFetcher(), _FLOWS, "triage"), operator)

    (asked,) = operator.asked
    assert asked.startswith(f"{entry} has changed since it was placed")

@pytest.mark.asyncio
async def test_a_mode_changed_or_bytecode_written_in_a_copy_is_replaced_without_a_question(
    tmp_path: Path,
) -> None:
    """Neither a file's mode nor anything under `__pycache__` is hashed, so neither is asked."""
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    (entry / "__init__.py").chmod(0o755)
    (entry / "__pycache__").mkdir()
    (entry / "__pycache__" / "triage.cpython-314.pyc").write_bytes(b"compiled")

    updated = await _update(home, _serving(FakeFetcher(), _FLOWS, "triage"), _never)

    assert len(updated.got.placed) == 1
    assert not (entry / "__pycache__").exists()
