"""A run whose workflow returns with a landing unsettled is not finished, and a resume finishes it.

A landing is unsettled from `integrate()` until the work lands, `abort` gives it up or a `retry`
raises, and a lease still live when the workflow returns is one. Three shapes leave one behind:

- **a merge that collided**, which git holds in the target's checkout;
- **the same merge, left for later by a person** at the workflow's own conflict screen;
- **a merge the build gate refused**, which git no longer holds and which holds the target still.

Several can be left at once, one per target, such as a grandchild's into a child and the child's
into the run's own checkout.

Such a run keeps every checkout, its record says it is not finished, and the teardown names
`agl resume`. The resumed walk replays its steps up to the landings and lands each one again. A
merge git still holds answers that as a conflict, so what finishes it is the workflow's own `retry`
after a person resolved and staged the files, or a commit the person made, which the landing then
finds already in. Either way the build gate runs and the parent's chain moves to the merge, and a
run whose landings have all settled is recorded finished and refused a further resume.

Real git throughout, because a held merge is a `MERGE_HEAD` in the checkout's own git directory and
outlives the process that left it.
"""

import subprocess
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.uv.fake import FakeSyncer
from agl.cli import main
from agl.config import container, registry, sources
from agl.ports.agent import AgentTask, Claude
from agl.ports.errors import ConflictError, exit_code_for
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.run import JsonValue
from agl.ports.terminal import Choice, Screen
from agl.ports.tree_layout import TreesRoot
from agl.sdk._workflow import Conflict, Run, workflow
from agl.sdk.roles import Role, role
from agl.sdk.testing import Reply

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)
BRANCH: Final = "agl/auth"
CHILD: Final = "T-01"
GRANDCHILD: Final = "T-01a"

# `tests/cli/test_resume_command.py`'s home: absolute, and nothing under it is ever opened.
ELSEWHERE: Final = Path("/nowhere")
SETTINGS: Final = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(ELSEWHERE)})

# One file three lines of work write with no line in common, so no two of them merge cleanly.
CONTESTED: Final = "contested.txt"
PARENT_BODY: Final = b"parent\nparent\nparent\n"
CHILD_BODY: Final = b"child\nchild\nchild\n"
GRANDCHILD_BODY: Final = b"grandchild\ngrandchild\ngrandchild\n"
RESOLVED: Final = b"what a person decided\n"
OWN: Final = "own.txt"
AFTER: Final = "after.txt"

HOLDING: Final = (
    'WARNING: Run "auth" ended in the middle of a merge, so its worktrees were kept. '
    "Run `agl resume auth` to finish the merge.\n"
)
REFUSED: Final = (
    'Run "auth" finished, and its work is on branch "agl/auth". To free the label, run '
    "`agl clear auth`, which deletes that branch."
)
TAKEN_UNFINISHED: Final = (
    'Run "auth" already exists and has not finished. To continue it, run `agl resume auth`, or to '
    "free the label, run `agl clear auth`, which deletes the run, its worktrees and branches, and "
    "any uncommitted work in them."
)
TAKEN_FINISHED: Final = (
    'Run "auth" already exists and has finished, with its work on branch "agl/auth". To free the '
    "label, run `agl clear auth`, which deletes that branch."
)

@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""

@role(model=Claude.SONNET)
def parent_version() -> Role:
    """The run's own version of the contested file."""
    return Role(name="parent-version", instructions="write the parent's version")

@role(model=Claude.SONNET)
def child_version() -> Role:
    """The child's version, sharing no line with the parent's."""
    return Role(name="child-version", instructions="write the child's version")

@role(model=Claude.SONNET)
def grandchild_version() -> Role:
    """The grandchild's version, sharing no line with the child's."""
    return Role(name="grandchild-version", instructions="write the grandchild's version")

@role(model=Claude.SONNET)
def own_file() -> Role:
    """A file nobody else writes, so its landing merges cleanly."""
    return Role(name="own", instructions="write a file of its own")

@role(model=Claude.SONNET)
def after_landing() -> Role:
    """The run's own step once the landing has settled."""
    return Role(name="after", instructions="write what comes after the landing")

_WRITTEN: Final = {
    "write the parent's version": (CONTESTED, PARENT_BODY),
    "write the child's version": (CONTESTED, CHILD_BODY),
    "write the grandchild's version": (CONTESTED, GRANDCHILD_BODY),
    "write a file of its own": (OWN, b"own\n"),
    "write what comes after the landing": (AFTER, b"after\n"),
}

def _agent(task: AgentTask) -> Reply:
    """Writes the one file its instructions name, and reports nothing."""
    name, body = _WRITTEN[task.instructions]
    (task.workspace / name).write_bytes(body)
    return Reply(says="done")

@workflow
async def holding(run: Run[NoParams]) -> None:
    """Lands a child that collides with the run's own work, and returns without settling it."""
    child = run.worktree(CHILD)
    await child.step(child_version(), commit="the child's version")
    await run.step(parent_version(), commit="the parent's version")
    await child.integrate()

def _resolving(conflict: Conflict | None) -> Screen[bool]:
    """The workflow's conflict screen: land it again, or leave it held for later."""
    return Screen(
        f"{conflict}", [Choice("Land it again", True), Choice("Leave it held", False)]
    )

@workflow
async def deferring(run: Run[NoParams]) -> None:
    """`holding`, with a conflict screen whose second answer returns while the merge is held."""
    child = run.worktree(CHILD)
    await child.step(child_version(), commit="the child's version")
    await run.step(parent_version(), commit="the parent's version")
    landing = await child.integrate()
    while landing.conflicted:
        if not await run.terminal.show(_resolving, conflict=landing.conflict):
            return
        await landing.retry()
    await run.step(after_landing(), commit="after the landing")

@workflow
async def gated(run: Run[NoParams]) -> None:
    """Lands a child that merges cleanly, and returns whatever the build gate said."""
    child = run.worktree(CHILD)
    await child.step(own_file(), commit="the child's own file")
    await child.integrate()

@workflow
async def nested(run: Run[NoParams]) -> None:
    """Leaves two landings unsettled at once: a grandchild's into the child, and the child's into
    the run's own checkout."""
    child = run.worktree(CHILD)
    await child.step(child_version(), commit="the child's version")
    grandchild = child.worktree(GRANDCHILD, base=run)
    await grandchild.step(grandchild_version(), commit="the grandchild's version")
    await run.step(parent_version(), commit="the parent's version")
    await grandchild.integrate()
    await child.integrate()

def _point(name: str) -> EntryPoint:
    """A registration line, pointed at this module."""
    return EntryPoint(name=name, value=f"{__name__}:{name}", group=registry.GROUP)

POINTS: Final = tuple(_point(name) for name in ("holding", "deferring", "gated", "nested"))

@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit on `main`, and no configuration from this machine."""
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL unsettled")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "README.md").write_bytes(b"seed\n")
    _git(work, "add", "README.md")
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work

def _over(repository: Path, tmp_path: Path) -> container.FakeServices:
    """The fakes bundle with its three git ports real, and the gate `FakeVerifier`'s to script."""
    trees = TreesRoot(tmp_path / "trees")
    fakes = container.fakes(trees, agent=_agent)
    return replace(
        fakes,
        services=replace(
            fakes.services,
            workspaces=GitWorkspaceProvider(repository, trees),
            history=GitHistory(repository),
            integrator=GitIntegrator(repository),
        ),
    )

async def _run(harness: container.FakeServices, name: str) -> api.Finished:
    """`agl run <name> -n auth`, with this module's entry points."""
    return await api.run(harness.services, PROJECT, name, LABEL, (), points=POINTS)

async def _resume(harness: container.FakeServices) -> api.Finished:
    """`agl resume auth`."""
    return await api.resume(harness.services, PROJECT, LABEL, points=POINTS)

def _answering(harness: container.FakeServices, *answers: int) -> container.FakeServices:
    """The same bundle with a person who gives these answers, in order."""
    return harness.with_terminal(container.answering(answers))

async def _finished(harness: container.FakeServices) -> JsonValue:
    """What the run's record says about whether it finished."""
    record = await harness.services.store.read_record(SCOPE)
    assert record is not None, "no run.json was written for this run"
    return record["finished"]

def _checkout(tmp_path: Path, namespace: str | None = None) -> Path:
    """A checkout of this run: the run's own `_base`, or a child's."""
    return tmp_path / "trees" / "auth" / ("_base" if namespace is None else namespace)

def _resolve(checkout: Path, *, commit: bool) -> None:
    """What a person does in a held checkout: resolve the file and stage it, and perhaps commit."""
    (checkout / CONTESTED).write_bytes(RESOLVED)
    _git(checkout, "add", CONTESTED)
    if commit:
        _git(checkout, "commit", "-q", "--no-edit")

def _merging(checkout: Path) -> bool:
    """Whether git holds a merge in this checkout."""
    return _answers(checkout, "rev-parse", "--verify", "--quiet", "MERGE_HEAD")

def _shown(repository: Path, revision: str, name: str) -> bytes:
    """A file's bytes as a commit holds them."""
    return subprocess.run(
        ["git", "show", f"{revision}:{name}"], cwd=repository, capture_output=True, check=True
    ).stdout

def _git(cwd: Path, *argv: str) -> str:
    """One git command, refusing to be wrong quietly: a non-zero exit raises here."""
    return subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()

def _answers(cwd: Path, *argv: str) -> bool:
    """One git command asked as a question: whether it exited zero."""
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, check=False).returncode == 0

async def _refused_again(harness: container.FakeServices) -> None:
    """A finished run's resume, refused with exit 4 and the finished-run text."""
    with pytest.raises(ConflictError) as caught:
        await _resume(harness)
    assert str(caught.value) == REFUSED
    assert exit_code_for(caught.value) == 4

def _main(harness: container.FakeServices, *argv: str) -> int:
    """One `agl` invocation over this bundle, as `tests/cli/test_resume_command.py` makes one."""
    installer = FakeSyncer()
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=lambda: (PROJECT, harness.services),
            settings=SETTINGS,
            cwd=ELSEWHERE,
            points=POINTS,
            syncer=lambda: installer,
        ),
    )

# --- not finished, and the resume walks it back to its landing -----------------------------------

@pytest.mark.asyncio
async def test_a_workflow_returning_with_a_collided_landing_leaves_its_run_unfinished_and_resumable(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The teardown names `agl resume`, and the resume it names is accepted.

    Nobody has touched the merge, so the resumed `integrate()` meets it held and comes back
    conflicted, and the workflow returns as it did the first time. The merge git holds is the same
    one, untouched by the steps the resume replayed on the way.
    """
    harness = _over(repository, tmp_path)

    first = await _run(harness, "holding")

    assert first == api.Finished(steps=0, branch=None, settled=False)
    assert await _finished(harness) is False, "a run left holding a landing reads as finished"
    assert capsys.readouterr().err == HOLDING
    held = _git(_checkout(tmp_path), "rev-parse", "MERGE_HEAD")

    again = await _resume(harness)

    assert again == api.Finished(steps=2, branch=None, settled=False)
    assert await _finished(harness) is False
    assert _git(_checkout(tmp_path), "rev-parse", "MERGE_HEAD") == held, (
        "the resume took the held merge away on its way back to the landing"
    )
    assert _git(_checkout(tmp_path), "status", "--porcelain") == f"AA {CONTESTED}"

@pytest.mark.asyncio
async def test_a_resume_after_the_person_commits_the_merge_lands_it_and_finishes_the_run(
    repository: Path, tmp_path: Path
) -> None:
    """The workflow never settles a landing, so the person concludes the merge with a commit.

    The resumed landing finds the child's work already in and the gate passes, so the landing
    settles on the person's merge: the run finishes, gives its checkouts back and hands
    `agl/auth` over with the resolution on it.
    """
    harness = _over(repository, tmp_path)
    await _run(harness, "holding")
    _resolve(_checkout(tmp_path), commit=True)

    finished = await _resume(harness)

    assert finished == api.Finished(steps=2, branch=BRANCH, settled=True)
    assert await _finished(harness) is True
    assert _shown(repository, BRANCH, CONTESTED) == RESOLVED
    assert _git(repository, "branch", "--list", f"agl/_work/auth/{CHILD}") == "", (
        "the child's branch was kept, so the release found its work outside agl/auth"
    )
    assert not _checkout(tmp_path).exists()
    await _refused_again(harness)

@pytest.mark.asyncio
async def test_a_workflow_that_retries_on_resume_finishes_the_merge_the_person_staged(
    repository: Path, tmp_path: Path
) -> None:
    """The person leaves the conflict for later, resolves and stages it, then picks "Land it again".

    The resumed `integrate()` meets the held merge as a conflict, and `retry` concludes what the
    person staged. The gate passes, the chain moves to the merge, and the run's next step commits
    on top of it.
    """
    harness = _over(repository, tmp_path)
    left = _answering(harness, 1)
    await _run(left, "deferring")
    assert await _finished(harness) is False
    _resolve(_checkout(tmp_path), commit=False)
    landing = _answering(harness, 0)

    finished = await _resume(landing)

    assert finished.settled is True
    assert await _finished(harness) is True
    assert _git(repository, "log", "-1", "--format=%s", BRANCH) == "after the landing"
    assert _shown(repository, f"{BRANCH}~1", CONTESTED) == RESOLVED
    assert _git(repository, "rev-list", "--parents", "-n", "1", f"{BRANCH}~1").count(" ") == 2, (
        "the step after the landing did not start from the merge the person resolved"
    )
    assert isinstance(landing.terminal, container.ScriptedTerminal)
    assert landing.terminal.remaining == ()
    await _refused_again(harness)

@pytest.mark.asyncio
async def test_a_landing_the_build_gate_refused_keeps_the_run_unfinished_until_it_passes(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate undoes the merge and holds the target, so no merge is in git and the run is not
    finished. A resume lands the child again and runs the gate again: still red, still unfinished;
    once the build passes, the landing settles and the run finishes."""
    harness = _over(repository, tmp_path)
    harness.verifier.answers(container.FAKE_BUILD, passed=False)

    await _run(harness, "gated")

    assert await _finished(harness) is False
    assert not _merging(_checkout(tmp_path))
    assert capsys.readouterr().err == HOLDING

    assert (await _resume(harness)).settled is False
    assert await _finished(harness) is False

    harness.verifier.answers(container.FAKE_BUILD, passed=True)
    finished = await _resume(harness)

    assert finished == api.Finished(steps=1, branch=BRANCH, settled=True)
    assert await _finished(harness) is True
    assert _shown(repository, BRANCH, OWN) == b"own\n"
    await _refused_again(harness)

@pytest.mark.asyncio
async def test_two_landings_left_unsettled_at_once_keep_the_run_unfinished_until_both_settle(
    repository: Path, tmp_path: Path
) -> None:
    """A grandchild's merge held in the child's checkout and the child's in the run's own.

    The person commits the run's merge first, and the resume settles that landing and not the
    other, so the run is still not finished. Once the child's merge is committed too, the next
    resume settles both and the grandchild's work reaches `agl/auth` through the child.
    """
    harness = _over(repository, tmp_path)
    await _run(harness, "nested")
    assert _merging(_checkout(tmp_path)) and _merging(_checkout(tmp_path, CHILD))
    assert await _finished(harness) is False

    _resolve(_checkout(tmp_path), commit=True)
    one = await _resume(harness)

    assert one.settled is False, "the run finished with the child's checkout still holding a merge"
    assert await _finished(harness) is False
    assert _merging(_checkout(tmp_path, CHILD))

    _resolve(_checkout(tmp_path, CHILD), commit=True)
    both = await _resume(harness)

    assert both == api.Finished(steps=3, branch=BRANCH, settled=True)
    assert await _finished(harness) is True
    assert _shown(repository, BRANCH, CONTESTED) == RESOLVED
    assert _git(repository, "log", "--format=%s", BRANCH).count("the grandchild's version") == 1
    await _refused_again(harness)

# --- a run whose landings all settled is still finished -----------------------------------------

@pytest.mark.asyncio
async def test_a_run_whose_landings_all_settled_is_finished_and_refused_a_resume(
    repository: Path, tmp_path: Path
) -> None:
    """A clean landing the gate passes settles inside `integrate()`, so the workflow returns with
    nothing left to settle: the run is finished, and its resume is refused before anything runs."""
    harness = _over(repository, tmp_path)

    finished = await _run(harness, "gated")

    assert finished == api.Finished(steps=0, branch=BRANCH, settled=True)
    assert await _finished(harness) is True
    await _refused_again(harness)

# --- what the commands say ----------------------------------------------------------------------

def test_agl_run_prints_no_finished_line_for_a_run_left_holding_a_landing(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`agl run` exits 0 with the teardown's warning and nothing on stdout, because the run did
    not finish. The resume the warning names is accepted, and once it lands the merge it prints
    the finished line; the next one is refused with exit 4."""
    harness = _over(repository, tmp_path)

    assert _main(harness, "run", "holding", "-n", "auth") == 0

    ran = capsys.readouterr()
    assert (ran.out, ran.err) == ("", HOLDING)

    _resolve(_checkout(tmp_path), commit=True)
    assert _main(harness, "resume", "auth") == 0

    resumed = capsys.readouterr()
    assert resumed.out == 'Run "auth" finished and left its changes on branch: agl/auth\n'
    assert _main(harness, "resume", "auth") == 4
    assert capsys.readouterr().err == f"agl: {REFUSED}\n"

def test_agl_run_again_on_a_run_left_holding_a_landing_names_agl_resume(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The label is taken by a run that has not finished, so a second `agl run` names the resume
    the teardown named, beside `agl clear`. Once that resume lands the merge the run is finished,
    and `agl run` names `agl clear` alone."""
    harness = _over(repository, tmp_path)
    assert _main(harness, "run", "holding", "-n", "auth") == 0
    capsys.readouterr()

    assert _main(harness, "run", "holding", "-n", "auth") == 4
    assert capsys.readouterr().err == f"agl: {TAKEN_UNFINISHED}\n"

    _resolve(_checkout(tmp_path), commit=True)
    assert _main(harness, "resume", "auth") == 0
    capsys.readouterr()

    assert _main(harness, "run", "holding", "-n", "auth") == 4
    assert capsys.readouterr().err == f"agl: {TAKEN_FINISHED}\n"
