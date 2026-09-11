"""`api.get`, driven from the library side: three phases, in an order that is the design.

Every download is fetched and inspected, then every question is asked, and only then is anything
placed - and a sync follows only where something was. The order is asserted from inside it: the
`confirm` below looks at the workspace at the moment each question is put, and what it finds is
compared with what was there before the command started. A test reading the workspace afterwards
could not tell that ordering from one that placed each workflow as soon as its own answer was in.

**What became of each workflow is handed out before the sync starts**, through the `report`
callback, because a sync can raise - uv missing, or refusing with no environment to fall back on -
and a command whose account of what it placed arrives only on return would lose it on exactly the
runs where the operator most needs it. The syncers below record how many reports had been made by
the time they were started.

Everything runs on fakes: `FakeFetcher` for the downloads, and syncers written here that answer as
scripted and keep what they were asked, which `FakeSyncer` does not. The real fetcher runs once, in
`tests/cli/test_get_command.py`, against `instruments.codeload`'s stand-in on this machine.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.adapters.github.fake import FAKE_COMMIT, FakeFetcher
from agl.config.placement import Got
from agl.config.provenance import placed_hash, read_provenance
from agl.config.registry import GROUP
from agl.ports.errors import NotFoundError, UpstreamUnavailable
from agl.ports.fetch import FetchedFile
from agl.ports.get_request import GetRequest, RepositoryAtRef
from agl.ports.home_layout import AglHome, workflow_dir, workflows_dir, workspace_dir
from agl.ports.ids import WorkflowName
from agl.ports.sync import Syncer, SyncOutcome

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

_REPOSITORY: Final = RepositoryAtRef("jashioq", "myrepo", None)

_MODULE: Final = b"from agl.sdk import Run, workflow\n"

class _Recording(Syncer):
    """A syncer that answers yes, keeping each workspace it was handed and how much was reported.

    `reported` is read at the moment the installer is started, because what it is there to say is
    that the account of the command had already gone out.
    """

    def __init__(self, reports: list[Got], error: Exception | None = None) -> None:
        self.asked: list[Path] = []
        self.reported: list[int] = []
        self._reports = reports
        self._error = error

    async def sync(self, workspace: Path) -> SyncOutcome:
        self.asked.append(workspace)
        self.reported.append(len(self._reports))
        if self._error is not None:
            raise self._error
        return SyncOutcome(synced=True, status=0, output="")

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME under `tmp_path` that is not there yet - what a first `agl get` meets."""
    return AglHome(tmp_path / "home")

def _pyproject(name: str, dependencies: str = "") -> bytes:
    return (
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n{dependencies}\n'
        f'[project.entry-points."{GROUP}"]\n{name} = "{name}:{name}"\n'
    ).encode()

def _serving(*names: str, depending: frozenset[str] = frozenset()) -> FakeFetcher:
    """A fetcher holding each named workflow under `workflows/`, those in `depending` on httpx."""
    fetcher = FakeFetcher()
    files: dict[str, FetchedFile] = {}
    for name in names:
        dependencies = 'dependencies = ["httpx"]' if name in depending else ""
        files[f"workflows/{name}/pyproject.toml"] = FetchedFile(_pyproject(name, dependencies))
        files[f"workflows/{name}/__init__.py"] = FetchedFile(_MODULE)
    fetcher.serves(_REPOSITORY, files)
    return fetcher

def _standing(home: AglHome, name: str) -> Path:
    """A workflow already in the workspace, as `agl new` or an earlier `agl get` would leave it."""
    directory = workflows_dir(home) / name
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_bytes(_pyproject(name))
    (directory / "__init__.py").write_bytes(b"# the operator's own\n")
    return directory

def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Every entry under `root` - a directory as `None`, a file as its bytes - or nothing at all."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }

def _request(*specs: str) -> GetRequest:
    return GetRequest.parsed(specs)

def _answering(*answers: bool) -> Callable[[str], bool]:
    """A `confirm` answering each question in turn, failing the test if one more is asked."""
    remaining = list(answers)

    def confirm(question: str) -> bool:
        assert remaining, f"asked a question nobody scripted an answer to: {question}"
        return remaining.pop(0)

    return confirm

def _never(question: str) -> bool:
    raise AssertionError(f"asked a question where none should have been: {question}")

# --- the order ----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nothing_reaches_the_workspace_until_every_question_has_been_answered(
    tmp_path: Path,
) -> None:
    """Two questions, and the workspace is exactly as it was when each of them is put.

    The first is a collision over a workflow the operator already has and the second a download
    declaring a dependency, and a third download asks nothing at all - so a command that placed as
    it went would have written the third, or the approved first, by the time the second was asked.
    """
    home = _home(tmp_path)
    _standing(home, "triage")
    before = _snapshot(home.path)
    seen: list[dict[str, bytes | None]] = []

    def looking(question: str) -> bool:
        seen.append(_snapshot(home.path))
        return True

    got = await api.get(
        _serving("triage", "lint", "release", depending=frozenset({"lint"})),
        _Recording([]),
        home,
        _request("jashioq/myrepo/workflows/triage,lint,release"),
        looking,
        lambda got: None,
    )

    assert seen == [before, before]
    assert sorted(str(one.workflow.name) for one in got.placed) == ["lint", "release", "triage"]

@pytest.mark.asyncio
async def test_on_a_home_not_made_yet_every_question_is_asked_before_the_home_exists(
    tmp_path: Path,
) -> None:
    """The workspace is made in the third phase, so no question is ever put over a half-made one."""
    home = _home(tmp_path)
    existed: list[bool] = []

    def looking(question: str) -> bool:
        existed.append(home.path.exists())
        return True

    got = await api.get(
        _serving("lint", depending=frozenset({"lint"})),
        _Recording([]),
        home,
        _request("jashioq/myrepo/workflows/lint"),
        looking,
        lambda got: None,
    )

    assert existed == [False]
    assert [one.directory for one in got.placed] == [workflow_dir(home, WorkflowName("lint"))]

@pytest.mark.asyncio
async def test_every_workflow_asked_of_one_repository_is_taken_from_one_download(
    tmp_path: Path,
) -> None:
    """Four workflows from one repository, asked for across three arguments, are one fetch.

    One of the arguments spells the owner and the repository in another case, which GitHub answers
    to alike; a second repository in the same command is a second fetch, and only a second.
    """
    home = _home(tmp_path)
    fetcher = _serving("a", "b", "c", "d")
    other = RepositoryAtRef("octo", "flows", None)
    fetcher.serves(other, {"e/pyproject.toml": FetchedFile(_pyproject("e"))})

    await api.get(
        fetcher,
        _Recording([]),
        home,
        _request(
            "jashioq/myrepo/workflows/a,b", "JASHIOQ/MyRepo/workflows/c", "octo/flows/e",
            "jashioq/myrepo/workflows/d",
        ),
        _never,
        lambda got: None,
    )

    assert [str(fetch.repository) for fetch in fetcher.fetched] == ["jashioq/myrepo", "octo/flows"]
    assert [str(one.name) for one in fetcher.fetched[0].workflows] == ["a", "b", "c", "d"]

@pytest.mark.asyncio
async def test_a_declined_workflow_is_skipped_and_every_other_one_is_placed_regardless(
    tmp_path: Path,
) -> None:
    """A no is a skip and never an abort: the download after it is asked and placed as usual."""
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    kept = _snapshot(standing)

    got = await api.get(
        _serving("triage", "lint", "release", depending=frozenset({"lint"})),
        _Recording([]),
        home,
        _request("jashioq/myrepo/workflows/triage,lint,release"),
        _answering(False, True),
        lambda got: None,
    )

    assert [str(one.placeable.workflow.name) for one in got.declined] == ["triage"]
    assert sorted(str(one.workflow.name) for one in got.placed) == ["lint", "release"]
    assert _snapshot(standing) == kept

# --- the report and the sync --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_what_became_of_each_workflow_is_reported_once_before_the_sync_starts(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    reports: list[Got] = []
    syncer = _Recording(reports)

    got = await api.get(
        _serving("triage"),
        syncer,
        home,
        _request("jashioq/myrepo/workflows/triage"),
        _never,
        reports.append,
    )

    assert reports == [got]
    assert syncer.reported == [1]

@pytest.mark.asyncio
async def test_the_workspace_is_synced_once_however_many_workflows_were_placed(
    tmp_path: Path,
) -> None:
    """One install for the whole command, handed the workspace directory the placing made."""
    home = _home(tmp_path)
    syncer = _Recording([])

    got = await api.get(
        _serving("triage", "lint", "release"),
        syncer,
        home,
        _request("jashioq/myrepo/workflows/triage,lint,release"),
        _never,
        lambda got: None,
    )

    assert len(got.placed) == 3
    assert syncer.asked == [workspace_dir(home)]

@pytest.mark.asyncio
async def test_nothing_approved_makes_no_workspace_and_starts_no_sync(tmp_path: Path) -> None:
    """Every question declined: the home is still not there, and no installer was started.

    An install over a workspace nothing changed would be a sync for nothing at best, and on a home
    that was never made there would not even be a workspace to hand it.
    """
    home = _home(tmp_path)
    reports: list[Got] = []
    syncer = _Recording(reports)

    await api.get(
        _serving("lint", "flake", depending=frozenset({"lint", "flake"})),
        syncer,
        home,
        _request("jashioq/myrepo/workflows/lint,flake"),
        _answering(False, False),
        reports.append,
    )

    assert not home.path.exists()
    assert syncer.asked == []
    (got,) = reports
    assert [str(one.placeable.workflow.name) for one in got.declined] == ["lint", "flake"]

@pytest.mark.asyncio
async def test_nothing_placed_because_every_workflow_was_refused_starts_no_sync(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    fetcher = FakeFetcher()
    fetcher.refuses(_REPOSITORY, NotFoundError("no public repository jashioq/myrepo"))
    syncer = _Recording([])

    got = await api.get(
        fetcher,
        syncer,
        home,
        _request("jashioq/myrepo/workflows/triage,lint"),
        _never,
        lambda got: None,
    )

    assert [str(one.workflow.name) for one in got.unfetched] == ["triage", "lint"]
    assert syncer.asked == []
    assert not home.path.exists()

@pytest.mark.asyncio
async def test_a_sync_that_raises_has_already_reported_what_was_placed(tmp_path: Path) -> None:
    """uv missing raises out of the sync, after the placed workflow's account is out of the door."""
    home = _home(tmp_path)
    reports: list[Got] = []
    syncer = _Recording(reports, UpstreamUnavailable("uv is not installed"))

    with pytest.raises(UpstreamUnavailable):
        await api.get(
            _serving("triage"),
            syncer,
            home,
            _request("jashioq/myrepo/workflows/triage"),
            _never,
            reports.append,
        )

    (got,) = reports
    assert [str(one.workflow.name) for one in got.placed] == ["triage"]
    assert workflow_dir(home, WorkflowName("triage")).is_dir()

# --- what was placed ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_placed_workflow_measures_as_its_provenance_says_and_names_the_commit(
    tmp_path: Path,
) -> None:
    """The invariant an edit breaks, reached through the whole command and not a part.

    Unedited means the hash measured off disk is the one recorded - and the commit recorded is the
    one the fetcher said it downloaded, not the ref it was asked for.
    """
    home = _home(tmp_path)

    got = await api.get(
        _serving("triage"),
        _Recording([]),
        home,
        _request("jashioq/myrepo/workflows/triage"),
        _never,
        lambda got: None,
    )

    (one,) = got.placed
    recorded = read_provenance(one.directory)
    assert recorded is not None
    assert recorded.commit == FAKE_COMMIT
    assert recorded.workflow == one.workflow
    assert placed_hash(one.directory) == recorded.content_hash
