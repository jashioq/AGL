"""`UvSyncer` and `FakeSyncer` against the `Syncer` contract, plus the clauses that suite says it
cannot assert - here, where the command line is in scope.

The first two classes are the port in full: `SyncContract` with its three fixtures overridden and
nothing else touched, run once against the real adapter and once against the fake. That suite was
written against the port's docstrings, which is the inversion `tests/contracts/` rests on and the
reason nothing below re-asserts any of it.

**No test here runs a real `uv sync`.** The adapter is pointed at a stub written into `tmp_path` -
a script that records the command line it was given, prints what it was told to print and exits
with the status it was told to exit with. That covers everything the adapter is: the arguments it
composes, the streams it keeps, the status it carries and the two refusals it raises. What it
cannot cover is uv's own behaviour, and the flags below are commented where they are chosen with
what was measured against a real one.

What follows the two classes is what the suite lists as beyond it:

  * **The flags that decide what a sync installs** (gaps 1 and 2). The suite sees one outcome
    whether a workspace's dependencies landed or nothing did, so the command line is read instead -
    and `--no-install-workspace` is the whole of the port's "what the workflows declare and never
    the workflows themselves".
  * **That the status is carried as it stands** (gap 3). The suite refuses every number; this file
    is allowed one, because the adapter's job is to pass uv's own through.
  * **`UpstreamUnavailable` when uv cannot be started** (gap 4). "Provoking it means breaking the
    installer itself", which from out here is a path with no binary at the end of it.
  * **The refusal that has nothing to do with the port**: a directory with no project file in it,
    which uv would answer by syncing an ancestor's project instead.

Named `test_uv_syncer.py`, for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import json
import sys
from pathlib import Path
from typing import Final
import pytest
from agl.adapters.uv.fake import FakeSyncer
from agl.adapters.uv.syncer import UvSyncer
from agl.ports.errors import NotFoundError, UpstreamUnavailable
from agl.ports.sync import Syncer
from contracts.sync import ANNOUNCEMENT, SyncContract

# What every workspace here holds, because a directory without one is refused before uv is reached.
_PROJECT_FILE: Final = "pyproject.toml"

# The workspace's own project file as AGL writes it: a uv workspace root with no `[project]` table.
_WORKSPACE_DOCUMENT: Final = '[tool.uv.workspace]\nmembers = ["workflows/*"]\n'

# What the stub reads to decide what to print and what to exit with, written into the workspace it
# is asked about - which is how one stub answers differently for the two workspaces the suite needs.
_PLAN_FILE: Final = "stub-plan.json"

_RECORD_FILE: Final = "command-lines.jsonl"

_STUB_FILE: Final = "uv-stub.py"

# The stub, written to disk and handed to the adapter as its uv. It records, it prints, it exits -
# and it reads the directory it was told to work in off its own command line, which is also what
# makes it useless as a stand-in for uv's discovery: the adapter's own guard is what stops that
# argument from ever naming a directory with no project file in it.
_STUB: Final = '''#!{python}
"""A stand-in for uv, written by tests/adapters/test_uv_syncer.py."""

import json
import pathlib
import sys

RECORD = pathlib.Path({record!r})
PLAN = {plan!r}


def main():
    argv = sys.argv[1:]
    with RECORD.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(argv) + "\\n")
    plan = pathlib.Path(argv[argv.index("--directory") + 1]) / PLAN
    if not plan.is_file():
        return 0
    said = json.loads(plan.read_text(encoding="utf-8"))
    if said["out"]:
        print(said["out"])
    if said["err"]:
        print(said["err"], file=sys.stderr)
    return said["status"]


sys.exit(main())
'''

def _workspace(root: Path, name: str) -> Path:
    """A workspace directory holding the project file AGL writes into one."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / _PROJECT_FILE).write_text(_WORKSPACE_DOCUMENT, encoding="utf-8")
    return directory

def _plans(workspace: Path, *, out: str = "", err: str = "", status: int = 0) -> Path:
    """What the stub does when it is pointed at `workspace`: two streams and an exit status."""
    (workspace / _PLAN_FILE).write_text(
        json.dumps({"out": out, "err": err, "status": status}), encoding="utf-8"
    )
    return workspace

def _stub(root: Path) -> Path:
    """The stand-in binary, and the file it appends every command line it was given to.

    Written per test into that test's own temporary directory, so two tests can never read each
    other's record and no state survives a run.
    """
    path = root / _STUB_FILE
    path.write_text(
        _STUB.format(python=sys.executable, record=str(root / _RECORD_FILE), plan=_PLAN_FILE),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path

def _given(root: Path) -> list[list[str]]:
    """Every command line the stub was given, in the order it was given them."""
    record = root / _RECORD_FILE
    if not record.is_file():
        return []
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]

# --- The port, asserted of both -----------------------------------------------------------------

class TestTheUvSyncer(SyncContract):
    """The real adapter against the `Syncer` contract, with a stub where uv would be.

    Three fixtures and nothing else touched. The stub is what makes this hermetic: no index is
    reached, no environment is built, and the suite's two workspaces differ by the plan file
    written into each of them rather than by anything a resolver would have to work out.
    """

    @pytest.fixture
    def syncer(self, tmp_path: Path) -> Syncer:
        return UvSyncer(_stub(tmp_path))

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return _workspace(tmp_path, "synced")

    @pytest.fixture
    def refused_workspace(self, tmp_path: Path) -> Path:
        return _plans(_workspace(tmp_path, "refused"), err=ANNOUNCEMENT, status=1)

class TestTheFakeSyncer(SyncContract):
    """The fake against the same three tests, which is the whole reason the suite exists.

    Its two workspaces are directories that need not hold anything at all: the fake is scripted by
    path, and a fake that read a project file to decide its answer would be faking uv rather than
    faking the port.
    """

    @pytest.fixture
    def syncer(self, tmp_path: Path) -> Syncer:
        fake = FakeSyncer()
        fake.answers(tmp_path / "refused", synced=False, output=ANNOUNCEMENT)
        return fake

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path / "synced"

    @pytest.fixture
    def refused_workspace(self, tmp_path: Path) -> Path:
        return tmp_path / "refused"

# --- The command line, which is where what a sync installs is actually decided ------------------

@pytest.mark.asyncio
async def test_the_command_line_installs_what_the_workflows_declare_and_no_workflow(
    tmp_path: Path,
) -> None:
    """`--no-install-workspace`, asserted as a token on the line uv is actually given.

    It is the port's own clause - what a sync installs is what the workflows declare and never the
    workflows themselves - and the contract suite cannot see it, because a workspace whose
    dependencies were installed and one whose workflows were installed as well hand back the same
    outcome. So it is asserted here, where the arguments are, and it is asserted as the whole line
    rather than as a membership test: a flag arriving in another position, or another flag arriving
    beside it, is a different request made of uv and this test is the only thing that would notice.

    The interpreter is on the line for a reason `config/workspace_path.py` holds: it composes the
    site-packages directory from the running interpreter's own `lib/` name, so a venv uv chose an
    interpreter for on its own is one this process cannot import from, with the packages installed
    and nothing anywhere to say so.
    """
    workspace = _workspace(tmp_path, "workspace")
    syncer = UvSyncer(_stub(tmp_path))

    outcome = await syncer.sync(workspace)

    assert outcome.synced is True
    assert _given(tmp_path) == [
        [
            "sync",
            "--no-install-workspace",
            "--python",
            sys.executable,
            "--directory",
            str(workspace),
        ]
    ]

@pytest.mark.asyncio
async def test_the_status_uv_reported_is_carried_as_it_stands_and_never_recomputed(
    tmp_path: Path,
) -> None:
    """The number a person reads off a failure, which the contract suite refuses to look at.

    The suite promises no numeric convention and so compares `status` to nothing; this adapter has
    one, and it is uv's rather than its own. A status the adapter derived from its own verdict
    would be a second copy of the verdict wearing a number's name, and the way to catch that is a
    number no verdict could have produced.
    """
    workspace = _plans(_workspace(tmp_path, "workspace"), err="no solution found", status=7)
    syncer = UvSyncer(_stub(tmp_path))

    outcome = await syncer.sync(workspace)

    assert outcome.synced is False
    assert outcome.status == 7, "the status uv exited with is not the status that came back"

@pytest.mark.asyncio
async def test_everything_uv_printed_arrives_whichever_stream_it_was_written_to(
    tmp_path: Path,
) -> None:
    """One body of text out of two streams, because uv talks on both and this port has one.

    uv writes its resolution to stderr and its answers to stdout, and a refusal is the moment a
    person needs whichever half explains itself. An adapter keeping only the tidy stream passes
    every other test in this file and hands that person half an account.
    """
    workspace = _plans(
        _workspace(tmp_path, "workspace"), out="Resolved 2 packages", err="Installed 1 package"
    )
    syncer = UvSyncer(_stub(tmp_path))

    outcome = await syncer.sync(workspace)

    assert "Resolved 2 packages" in outcome.output
    assert "Installed 1 package" in outcome.output

# --- The two refusals, neither of which is an outcome -------------------------------------------

@pytest.mark.asyncio
async def test_a_uv_that_is_not_there_refuses_and_names_the_installs_that_put_it_there(
    tmp_path: Path,
) -> None:
    """uv is a binary AGL shells out to and ships no copy of, so its absence is a state to expect.

    `UpstreamUnavailable` and not a refused sync: nothing was attempted, so this is not an answer
    about the workspace, and the same call may well succeed once uv is installed. The message is
    asserted for the three ways of installing it, because a refusal that names none of them leaves
    the reader to search for a tool they have just been told they need.
    """
    workspace = _workspace(tmp_path, "workspace")
    syncer = UvSyncer(tmp_path / "no-uv-here")

    with pytest.raises(UpstreamUnavailable) as refusal:
        await syncer.sync(workspace)

    said = str(refusal.value)
    assert "brew install uv" in said
    assert "pipx install uv" in said
    assert "astral.sh/uv/install.sh" in said

@pytest.mark.asyncio
async def test_a_directory_with_no_project_file_is_refused_before_uv_is_started(
    tmp_path: Path,
) -> None:
    """uv walks *up* for a project file, so this guard is the difference between two directories.

    Pointed at a workspace that is not one, uv syncs the first project it finds above it - the
    checkout AGL's home happens to sit inside, or the operator's own `$HOME` - and builds that
    project's environment. Measured against uv 0.11.29, which reports what it is doing about a
    directory nobody named. So the refusal is AGL's, it is raised before anything is started, and
    the record being empty is the half of this test that says so.
    """
    directory = tmp_path / "not-a-workspace"
    directory.mkdir()
    syncer = UvSyncer(_stub(tmp_path))

    with pytest.raises(NotFoundError, match="no workspace to sync"):
        await syncer.sync(directory)

    assert _given(tmp_path) == [], "uv was started for a directory AGL had already refused"

# --- The fake, and what only it can be asked ----------------------------------------------------

@pytest.mark.asyncio
async def test_the_fake_answers_an_unscripted_workspace_the_way_it_was_built_to(
    tmp_path: Path,
) -> None:
    """The default is that a sync succeeds, because that is the state every other test wants.

    A bundle built for a test of something else should not have to script a syncer to get past it,
    and the one knob is there for the test that wants the opposite without naming a path.
    """
    permissive = await FakeSyncer().sync(tmp_path)
    strict = await FakeSyncer(unscripted_syncs=False).sync(tmp_path)

    assert permissive.synced is True
    assert strict.synced is False

@pytest.mark.asyncio
async def test_the_fake_answers_by_the_workspace_it_was_scripted_against_and_no_other(
    tmp_path: Path,
) -> None:
    """Scripted by path, so one fake can be a syncer that works and one that does not at once.

    The unscripted answer is what every other path gets, which is what keeps a test that scripts
    one workspace from silently deciding the answer for a second one it forgot about.
    """
    fake = FakeSyncer()
    fake.answers(tmp_path / "refused", synced=False, status=2, output="no solution found")

    refused = await fake.sync(tmp_path / "refused")
    other = await fake.sync(tmp_path / "other")

    assert (refused.synced, refused.status, refused.output) == (False, 2, "no solution found")
    assert other.synced is True

def test_both_are_syncers_and_the_port_itself_cannot_be_constructed() -> None:
    """The ABC is one abstract method, and an ABC with an abstract method is not instantiable."""
    assert isinstance(UvSyncer(), Syncer)
    assert isinstance(FakeSyncer(), Syncer)
    assert Syncer.__abstractmethods__ == frozenset({"sync"})

    with pytest.raises(TypeError):
        Syncer()  # type: ignore[abstract]
