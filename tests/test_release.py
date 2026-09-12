"""What a finished run gives back, what a failed one keeps, and the one branch that outlives both.

A run cuts one checkout per namespace plus its own `_base`, and until now it left every one of them
standing. That cost two things an operator pays for by hand: `git checkout agl/<label>` refuses
while a worktree holds that branch, so the deliverable could not be checked out where it was
wanted; and a machine that ran a hundred runs held a hundred dead trees. So a run that **finished**
- returned, or ended on a `Stop` - hands every checkout back and deletes the child branches whose
work reached `agl/<label>`, and a run that **failed or was cancelled** keeps all of it, because that
is precisely the run somebody is about to resume or go and look at. Having given the checkout back,
it says so: the last section here is the one line that names `agl/<label>` on stderr, and the two
endings that keep the checkout are asserted not to write it, because the branch is not takeable
then and a line saying otherwise sends an operator at git's refusal.

## Why the question asked about a child branch is not `git branch -d`

`-d` is the non-forcing delete and looks like exactly the right instrument: it refuses a branch
whose work would be lost. What it measures is the branch against the repository's **own HEAD** -
whichever branch the operator has checked out - and a child of this run landed into `agl/<label>`,
which is not that. Measured against git 2.50, in a repository on `main` with a child merged into
`agl/T`:

    $ git branch -d agl/_work/T/alpha
    error: the branch 'agl/_work/T/alpha' is not fully merged

So `-d` would refuse every child branch there is, on a perfect run, and the release would print a
paragraph about each of them. `sdk/_engine/teardown.py` asks the deliverable directly instead -
`History.contains(child, agl/<label>)`, which is `git merge-base --is-ancestor` - and the two tests
below are the two answers that question has: `test_a_child_branch_whose_work_landed_goes...` is the
case `-d` would have got wrong, and `test_a_child_branch_that_never_landed_is_kept...` is the case
it was reaching for.

## Where each half is asserted, and why the split is not arbitrary

**Real git for reachability and for deletion.** "The commits are still there" is a claim about git
objects and refs, and a `FakeRepository` keeps every state it was ever handed in a dict - so it
cannot fail the way a repository can. `merge-base --is-ancestor` against a branch a worktree no
longer holds is likewise a question only git can be asked.

**The fakes for the outcomes and the failures.** Which endings release and which do not is a
decision `sdk/_engine/teardown.py` takes about an exception, and a provider that refuses to hand a
checkout back is a state no real git would reach on demand. Both are cheaper and sharper on fakes.

## What a checkout is read through here

Nothing below reads a run's checkout after the run. It is not there any more, and a *reopen* is not
the same reading - `WorkspaceProvider.open` would put back whatever it was asked about, so every
answer it gave would be yes. Where a test needs one, the workflow reads it and records what it saw,
which is what `tests/sdk/test_terminal_priorities.py` does one file over and for the same reason.
"""

import subprocess
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.config import container, registry
from agl.ports.agent import AgentOutcome, Claude, StopReason
from agl.ports.errors import DeniedError, Stop, UpstreamUnavailable, exit_code_for
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.tree_layout import (
    TreesRoot,
    base_worktree,
    run_branch,
    worktree_branch,
    worktree_dir,
)
from agl.ports.workspace import Workspace, WorkspaceProvider
from agl.sdk.roles import Role, role
from agl.sdk.workflow import Run, workflow

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

CHILD: Final = Namespace("T-01")

# The sentence the release must not write while anything still holds `agl/auth`. It is what an
# operator types next, and git answers `fatal: 'agl/auth' is already used by worktree at ...` for as
# long as one worktree holds that branch - so a run that offered it anyway would be sending somebody
# at that refusal with a line that reads like an invitation.
OFFERED: Final = f"git checkout {run_branch(LABEL)}"

SEEDED: Final = "src/a.txt"

# A file per role, so that every step commits something a previous one did not - `commit_all` makes
# no commit where nothing is dirty - and so that a child lands into its parent without argument.
PARENT_FILE: Final = "src/parent.py"
CHILD_FILE: Final = "src/child.py"
LATER_FILE: Final = "src/later.py"
PARENT_WORK: Final = b"what the parent wrote\n"

# The two bodies of one file that no honest merge combines: neither line of work has seen the
# other's version and they share not a line, which is the shape `tests/contracts/`'s integration
# suite requires of a conflict caused on purpose. Only `holding` writes them.
CONTESTED: Final = "src/contested.py"
PARENT_BODY: Final = b"parent\nparent\nparent\n"
CHILD_BODY: Final = b"child\nchild\nchild\n"

@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""

@role(model=Claude.SONNET)
def parent_work() -> Role:
    """An effect role for the run's own checkout: no reporting tool, so a step over it is `null`."""
    return Role(name="parent", instructions="write the parent's own file")

@role(model=Claude.SONNET)
def child_work() -> Role:
    """The same, in a child's checkout, and a second name so the two are two dispatches."""
    return Role(name="child", instructions="write the child's own file")

@role(model=Claude.SONNET)
def later_work() -> Role:
    """The step that only the second walk reaches, which is what a released checkout is cut for."""
    return Role(name="later", instructions="write what the second walk leaves behind")

@role(model=Claude.SONNET)
def parent_version() -> Role:
    """One half of the collision: the parent's own version of the file both of them write."""
    return Role(name="parent-version", instructions="write the parent's version of the same file")

@role(model=Claude.SONNET)
def child_version() -> Role:
    """The other half, sharing not a line with it, so no merge combines the two."""
    return Role(name="child-version", instructions="write the child's version of the same file")

# What each workflow saw of the world while it was still standing, at module level because the
# workflows have to be: `EntryPoint.load` imports a module and reads an attribute in it.
heads: Final[dict[str, str]] = {}
dispatched: Final[list[str]] = []
stopping: Final[list[bool]] = []
raised: Final[list[Stop]] = []

class Enough(Stop):
    """A workflow's own reason to stop, so the release is asked about the class AGL never sees."""

@workflow
async def landing(run: Run[NoParams]) -> None:
    """A child that works and lands, which is the ordinary shape of a finished run."""
    child = run.worktree(str(CHILD))
    await run.step(parent_work(), commit="the parent's own work")
    await child.step(child_work(), commit="the child's work")
    await _noted(child, CHILD)
    await child.integrate()
    await _noted(run, None)

@workflow
async def stranded(run: Run[NoParams]) -> None:
    """A child that works and never lands: the branch whose commits reached nothing else."""
    child = run.worktree(str(CHILD))
    await run.step(parent_work(), commit="the parent's own work")
    await child.step(child_work(), commit="work nobody ever landed")
    await _noted(child, CHILD)

@workflow
async def halting(run: Run[NoParams]) -> None:
    """`landing`, and then a `Stop` of the workflow's own - which ends a run on purpose."""
    await landing.fn(run)
    stop = Enough("two rounds and no convergence")
    raised.append(stop)
    raise stop

@workflow
async def breaking(run: Run[NoParams]) -> None:
    """`stranded`, and then a failure - the run whose checkouts are worth keeping."""
    await stranded.fn(run)
    raise UpstreamUnavailable("this run broke before it finished, which is what leaves a mess")

@workflow
async def unrecorded(run: Run[NoParams]) -> None:
    """Opens a child, lands it without ever stepping it, and so writes nothing under its name.

    A checkout is cut before any entry is written, and `Store.namespaces` answers out of the
    entries - so this is the namespace the ledger has never heard of and the trees root has.
    Landing a child that has taken no step is a merge git calls already up to date, which the
    engine concludes exactly as it concludes any other.
    """
    await run.step(parent_work(), commit="the parent's own work")
    child = run.worktree(str(CHILD))
    await child.integrate()

@workflow
async def resuming(run: Run[NoParams]) -> None:
    """One step, a `Stop` the first walk takes, and a second step only the resume reaches.

    Branching on a module-level flag is the one thing `ARCHITECTURE.md` tells a workflow author
    never to do, and it is deliberate here: what has to be arranged is a walk that ends - releasing
    its checkout - with work still to come, and a workflow cannot ask for that any other way. The
    first step is recorded on the first walk and replayed on the second, which is what makes "the
    second walk ran in a checkout that had been handed back" the thing being measured.
    """
    await run.step(parent_work(), commit="the parent's own work")
    if stopping and stopping[-1]:
        raise Enough("that is as far as this walk goes")
    await run.step(later_work(), commit="what the second walk left behind")

@workflow
async def holding(run: Run[NoParams]) -> None:
    """Lands a child that collides with the parent, and returns without settling the conflict.

    A workflow is meant to `retry()` or `abort()` every hold it takes; one that returns instead
    leaves git's own merge state in the run's checkout, and that state is in no commit and on no
    branch. The run below is the run AGL must not tidy up after.
    """
    child = run.worktree(str(CHILD))
    await child.step(child_version(), commit="the child's version")
    await run.step(parent_version(), commit="the parent's version")
    await child.integrate()

async def _noted(run: Run[NoParams], namespace: Namespace | None) -> None:
    """Write down where a checkout's line of work is, while there is still a checkout to ask.

    Through `WorkspaceProvider.open`, which is idempotent by contract and so hands back the place
    the step already cut. What the tests spend afterwards is the commit id, and a commit id outlives
    the branch it was on - which is the whole of what "still reachable by sha" means.
    """
    place = await run.services.workspaces.open(run.scope.label, namespace, run.base)
    heads["run" if namespace is None else str(namespace)] = await place.head()

def _point(name: str) -> EntryPoint:
    """A `probe = "agl.workflows.probe:probe"` line, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{name}", group=registry.GROUP)

POINTS: Final = tuple(
    _point(name)
    for name in (
        "landing", "stranded", "halting", "breaking", "resuming", "holding", "unrecorded"
    )
)

# --- the two deployments --------------------------------------------------------------------------

_WRITTEN: Final[Mapping[str, Mapping[str, bytes]]] = {
    "write the parent's own file": {PARENT_FILE: PARENT_WORK},
    "write the child's own file": {CHILD_FILE: b"what the child wrote\n"},
    "write what the second walk leaves behind": {LATER_FILE: b"the second walk\n"},
    "write the parent's version of the same file": {CONTESTED: PARENT_BODY},
    "write the child's version of the same file": {CONTESTED: CHILD_BODY},
}
"""What an agent writes, keyed on the instructions it was handed.

A file of its own for the three roles that must not argue with each other, so that every step
commits something - `commit_all` makes no commit where nothing is dirty - and a landing goes in
without a word. The last two share one file and no line of it, which is what makes `holding`
collide."""

def _agent() -> Script:
    """An agent that writes what `_WRITTEN` says and reports nothing at all."""

    async def _script(conversation: Conversation) -> AgentOutcome:
        dispatched.append(conversation.task.instructions)
        for name, body in _WRITTEN.get(conversation.task.instructions, {}).items():
            target = conversation.task.workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script

def _fakes(tmp_path: Path) -> container.FakeServices:
    """The all-fakes bundle, which is what the outcome and failure tests are driven over."""
    return container.fakes(_trees(tmp_path), files={SEEDED: b"one\n"}, claude=_agent())

def _trees(tmp_path: Path) -> TreesRoot:
    """Where this run's checkouts live, spelled once."""
    return TreesRoot(tmp_path / "trees")

def _git(where: Path, *argv: str) -> str:
    """One git command, refusing to be wrong quietly: a non-zero exit raises here."""
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout

def _asked(where: Path, *argv: str) -> bool:
    """One git command asked as a question: whether it exited zero, with nothing raised."""
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=False)
    return done.returncode == 0

@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit on `main`, and no configuration from this machine.

    The `GIT_CONFIG_*` variables are what make these tests the same tests everywhere - a developer
    with `commit.gpgsign` on or a template directory of their own would otherwise be running
    different ones - and they go through `monkeypatch` so the adapters, which inherit the
    environment, see them too. **`main` stays checked out here on purpose**: it is what makes the
    `git branch -d` measurement in the module docstring a fact about this arrangement rather than
    about some other one.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL release")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    seeded = work / SEEDED
    seeded.parent.mkdir(parents=True)
    seeded.write_bytes(b"one\n")
    _git(work, "add", SEEDED)
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work

def _over(repository: Path, tmp_path: Path) -> container.FakeServices:
    """The fakes bundle with its three git ports made real, which is the smallest arrangement in
    which a landing is an actual merge and a branch an actual ref.

    `integrator` joins `workspaces` and `history` here where `tests/test_api.py` replaces only the
    two: a `FakeIntegrator` reads a `FakeRepository` that has never heard of these commits, and a
    child that cannot land is a child whose branch would be kept for the wrong reason. The verifier
    stays the fake one - the merge gate is not what is being measured and `FAKE_BUILD` runs nothing.
    """
    trees = _trees(tmp_path)
    harness = container.fakes(trees, files={SEEDED: b"one\n"}, claude=_agent())
    return replace(
        harness,
        services=replace(
            harness.services,
            workspaces=GitWorkspaceProvider(repository, trees),
            history=GitHistory(repository),
            integrator=GitIntegrator(repository),
        ),
    )

async def _run(
    harness: container.FakeServices, name: str, *, points: Sequence[EntryPoint] = POINTS
) -> api.Replayed:
    """One invocation: `agl run <name> -n auth`, with this module's entry points."""
    return await api.run(harness.services, PROJECT, name, LABEL, (), points=points)

@pytest.fixture(autouse=True)
def _nothing_carried_over() -> None:
    """The module-level records, emptied before each test rather than after, so that a test which
    fails leaves its evidence behind for the next reader."""
    heads.clear()
    for record in (dispatched, stopping, raised):
        record.clear()

# --- what survives, asked of git ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_commits_a_finished_run_made_are_still_reachable_from_its_own_branch(
    repository: Path, tmp_path: Path
) -> None:
    """The criterion, and the one thing a release may never cost: the work.

    Both heads are read by the workflow while its checkouts stand, and both are asked about
    afterwards by **sha** rather than by branch - which is the only reading that means anything once
    `agl/_work/auth/T-01` has been deleted. Two questions per sha, because they fail differently: an
    object that git no longer holds fails `cat-file`, and an object git holds but no ref reaches
    fails the ancestry - and the second is the one a wrong release produces, since git prunes on its
    own schedule and a commit reachable from nothing survives right up until it does not.
    """
    harness = _over(repository, tmp_path)

    await _run(harness, "landing")

    assert set(heads) == {"run", str(CHILD)}, "the workflow did not write down both heads"
    for where, sha in heads.items():
        assert _asked(repository, "cat-file", "-e", f"{sha}^{{commit}}"), (
            f"the commit {where}'s line of work ended at, {sha!r}, is not in the repository any "
            f"more - so the release did not merely take a checkout back, it took the work"
        )
        assert _asked(repository, "merge-base", "--is-ancestor", sha, run_branch(LABEL)), (
            f"{sha!r} is still an object but no longer reachable from {run_branch(LABEL)!r}, so "
            f"the run's deliverable does not carry what {where} did and git will collect it"
        )

@pytest.mark.asyncio
async def test_a_child_branch_whose_work_landed_goes_and_the_run_branch_can_be_checked_out(
    repository: Path, tmp_path: Path
) -> None:
    """The case `git branch -d` would have got wrong, and the deliverable it is in aid of.

    The child landed, so its name carries nothing the run's own branch does not, and it goes. Then
    the sentence the whole deliverable exists for: `git checkout agl/auth` in the operator's own
    repository, which git refuses outright - `fatal: 'agl/auth' is already used by worktree at ...`
    - for as long as any worktree holds that branch. It is asserted as a command that succeeds
    rather than as a directory that is absent, because the absent directory is the mechanism and
    this is the thing somebody wanted.
    """
    harness = _over(repository, tmp_path)

    await _run(harness, "landing")

    assert _git(repository, "branch", "--list", worktree_branch(LABEL, CHILD)).strip() == "", (
        f"{worktree_branch(LABEL, CHILD)!r} is still a branch in this repository. Its work is on "
        f"{run_branch(LABEL)!r}, so the name carries nothing and is litter"
    )
    assert _asked(repository, "checkout", "--quiet", run_branch(LABEL)), (
        f"git refused to check out {run_branch(LABEL)!r}, which is the one thing a finished run is "
        f"for. Something is still holding it - a worktree the release did not take back"
    )

@pytest.mark.asyncio
async def test_a_child_branch_that_never_landed_is_kept_and_named_on_the_terminal(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other answer, and the refusal `-d` was reaching for when it was the wrong instrument.

    Nothing on the child's branch reached `agl/auth`, so deleting the name would leave its commits
    reachable from nothing - which is work destroyed by a tidy-up. It is kept, and the operator is
    told, because a branch kept silently is a branch nobody ever looks at. The checkout still goes:
    what is worth keeping is the line of work, and the working tree under it held nothing that was
    not committed.

    On stderr and not on stdout, for `cli/commands/__init__.py`'s reason - this is a note to
    whoever is reading the terminal, and what a machine consumes goes to the other stream.
    """
    harness = _over(repository, tmp_path)

    await _run(harness, "stranded")

    branch = worktree_branch(LABEL, CHILD)
    assert _git(repository, "branch", "--list", branch).strip() != "", (
        f"{branch!r} was deleted although nothing on it had reached {run_branch(LABEL)!r}. Its "
        f"commits are now reachable from no ref at all, which is a tidy-up that destroys work"
    )
    assert not worktree_dir(_trees(tmp_path), LABEL, CHILD).exists(), (
        "the child's checkout was kept along with its branch. The branch is what carries the work "
        "nobody landed; the checkout carries nothing that is not in it"
    )
    printed = capsys.readouterr()
    assert branch in printed.err and run_branch(LABEL) in printed.err, (
        f"the run kept {branch!r} and said nothing about it on stderr: {printed.err!r}. A branch "
        f"kept quietly is one nobody goes back to"
    )
    assert printed.out == "", "a note about a teardown went to the stream a machine reads"

# --- which endings release, asked of the fakes ----------------------------------------------------

@pytest.mark.asyncio
async def test_a_run_that_failed_keeps_every_checkout_it_cut_for_a_resume_to_find(
    tmp_path: Path,
) -> None:
    """The half that is not tidiness. A run that broke is the run somebody resumes, and the run
    whose checkouts are worth opening: a half-written file, the build gate's leavings and anything
    an agent left uncommitted are in the working tree and in no commit anywhere.

    Both addresses are asserted, because a release that ran over the children and stopped at
    `_base` - or the other way about - would be half a decision rather than none.
    """
    harness = _fakes(tmp_path)

    with pytest.raises(UpstreamUnavailable):
        await _run(harness, "breaking")

    trees = _trees(tmp_path)
    assert base_worktree(trees, LABEL).is_dir(), "a failed run's own checkout was taken back"
    assert worktree_dir(trees, LABEL, CHILD).is_dir(), (
        "a failed run's child checkout was taken back"
    )
    assert harness.repository.tip(worktree_branch(LABEL, CHILD)) is not None

@pytest.mark.asyncio
async def test_a_workflow_that_stops_hands_its_checkouts_back_as_one_that_returns_does(
    tmp_path: Path,
) -> None:
    """A `Stop` is a workflow saying it has finished, so it releases exactly as a return does.

    The subclass is the workflow's own and AGL has never heard of it, which is the case worth
    arranging: what decides here is the class tree and not a name in a table, the same resolution
    `ports/errors.py` makes for the exit code. And the `Stop` has to come out of `api.run`
    unwrapped - asserted by identity, because an `isinstance` passes against a release that caught
    the workflow's own and raised a fresh one, which is the shape that would cost the exit code.
    """
    harness = _fakes(tmp_path)

    with pytest.raises(Stop) as caught:
        await _run(harness, "halting")

    assert caught.value is raised[0], "the `Stop` the workflow raised is not the one that came out"
    assert exit_code_for(caught.value) == 7
    trees = _trees(tmp_path)
    assert not base_worktree(trees, LABEL).exists(), "a stopped run kept its own checkout"
    assert not worktree_dir(trees, LABEL, CHILD).exists(), "a stopped run kept a child checkout"
    assert harness.repository.tip(worktree_branch(LABEL, CHILD)) is None, (
        "the child landed before the stop, so its branch carries nothing the run's own does not"
    )
    assert harness.repository.tip(run_branch(LABEL)) is not None, "the deliverable went with it"

@pytest.mark.asyncio
async def test_a_namespace_the_ledger_never_heard_of_is_released_with_the_rest_of_them(
    tmp_path: Path,
) -> None:
    """The enumeration is two lists and not one, because neither alone is every checkout a run cut.

    `Store.namespaces` answers out of the entries a run recorded, and a checkout is cut before the
    first of them is written - so a namespace that opened one and recorded nothing is in the walk's
    own registry and nowhere else. `unrecorded` is the smallest way to reach that state: a child
    landed without ever being stepped. The ledger is asserted empty first, because a test whose
    premise is a gap has to show the gap.

    The other side of the union is not written down as a test of its own: every other run in this
    file is a walk whose registry and ledger agree, and the ledger's half is what `api.clear` has
    always spent.
    """
    harness = _fakes(tmp_path)

    await _run(harness, "unrecorded")

    assert await harness.store.namespaces(SCOPE) == (), (
        "the child recorded an entry after all, so this run does not reach the case it is for"
    )
    assert not worktree_dir(_trees(tmp_path), LABEL, CHILD).exists(), (
        "the child's checkout outlived the run because nothing in the ledger named it. A run's own "
        "registry is what knows it was cut, and the release has to ask both"
    )
    assert harness.repository.tip(worktree_branch(LABEL, CHILD)) is None, (
        "the child's branch outlived the run. It landed - trivially, being an ancestor - so it "
        "carries nothing the run's own branch does not"
    )

@pytest.mark.asyncio
async def test_a_resume_after_a_release_replays_what_it_had_and_runs_the_rest(
    repository: Path, tmp_path: Path
) -> None:
    """The claim the whole release rests on: a checkout is rebuilt from its branch, so giving one
    back costs a resume nothing.

    The first walk records a step and stops, which hands the checkout back; the second finds no
    directory at all and `GitWorkspaceProvider.open` takes its **attaching** path -
    `worktree add <path> <branch>`, no `-b` - because the branch is still there. The step already
    recorded replays without reaching an agent, and the one below it runs in a tree that carries
    the first one's work.

    Three assertions and each one fails differently. The dispatch list is the replay: a second
    `parent` in it is a run that paid for the same step twice. The file is the attach: a checkout
    cut fresh from the base ref would not hold it. And the branch has moved, which is the second
    walk's own commit landing on the deliverable rather than on something nobody can name.
    """
    harness = _over(repository, tmp_path)
    stopping.append(True)
    with pytest.raises(Stop):
        await _run(harness, "resuming")
    after_stopping = _git(repository, "rev-parse", run_branch(LABEL)).strip()
    assert not base_worktree(_trees(tmp_path), LABEL).exists(), (
        "the stopped walk kept its checkout, so the walk below would reopen rather than attach"
    )
    dispatched.clear()
    stopping.append(False)

    replayed = await api.resume(harness.services, PROJECT, LABEL, points=POINTS)

    assert dispatched == ["write what the second walk leaves behind"], (
        f"the second walk dispatched {dispatched}. The first step was recorded on the first walk, "
        f"so a resume that runs it again is a resume paying for work it already has"
    )
    assert replayed.steps == 1
    assert _git(repository, "show", f"{run_branch(LABEL)}:{PARENT_FILE}").encode() == PARENT_WORK, (
        "the recreated checkout does not carry the first walk's work, so it was cut from the base "
        "rather than attached to the branch the run had already put that work on"
    )
    assert _git(repository, "rev-parse", run_branch(LABEL)).strip() != after_stopping, (
        "the second walk's commit did not reach the deliverable"
    )

# --- a release that cannot finish, and a landing nobody settled -----------------------------------

class _Immovable(WorkspaceProvider):
    """The bundle's own provider, except that nothing may be taken back.

    A delegating wrapper rather than a stub, because everything but `remove` has to go on working
    for the run to reach the point where the release is attempted at all. `DeniedError` is what
    `adapters/git/_trees.py` translates a `PermissionError` into, so the refusal is one an operator
    could actually meet - a checkout under a directory their user cannot write to.

    `check_removable` delegates and therefore answers "this will go" for a place that will not,
    which is honest twice over: a release asks it nowhere, and a filesystem that refuses at the
    moment of the `rmtree` is exactly what no check ahead of one can promise about.
    """

    def __init__(self, provider: WorkspaceProvider) -> None:
        self._provider = provider

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        return await self._provider.open(label, namespace, base)

    async def residue(self, label: RunLabel) -> tuple[Namespace, ...]:
        return await self._provider.residue(label)

    async def check_removable(self, label: RunLabel, namespace: Namespace | None) -> None:
        await self._provider.check_removable(label, namespace)

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise DeniedError("the filesystem refused this checkout, deliberately")

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        await self._provider.discard(label, namespace)

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        return self._provider.hold(label)

@pytest.mark.asyncio
async def test_a_checkout_that_will_not_go_is_named_and_the_run_still_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A teardown is not a result, and it may not change one.

    The run's work is committed and on its branch by the time any of this happens, so a checkout
    that will not go is a note and not an outcome: `api.run` returns its `Replayed` exactly as it
    would have, which is what makes `cli/commands/run.py` exit 0. A release that raised instead
    would turn a run that produced everything it was asked for into exit 5, and an operator would
    go looking for work that is already there.

    Every address is attempted rather than the loop stopping at the first refusal - both are named
    below - because one checkout a release cannot take back says nothing about the next.
    """
    harness = _fakes(tmp_path)
    services = replace(harness.services, workspaces=_Immovable(harness.services.workspaces))

    replayed = await api.run(services, PROJECT, "landing", LABEL, (), points=POINTS)

    assert replayed == api.Replayed(steps=0)
    printed = capsys.readouterr()
    assert str(CHILD) in printed.err and "_base" in printed.err, (
        f"the release met a refusal at both addresses and named neither of them: {printed.err!r}"
    )
    assert printed.out == "", "a note about a teardown went to the stream a machine reads"

@pytest.mark.asyncio
async def test_a_run_ending_with_a_landing_nobody_settled_keeps_every_checkout_it_cut(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one ending that returns and still keeps its checkouts, and the reason is what a hold is.

    A conflicted landing is recorded in the target's own checkout and nowhere else - git writes it
    into that worktree's git directory - and so is anything a person typed into the files it stopped
    on. `WorkspaceProvider.remove` is a `shutil.rmtree`, which carries both off without a word and
    without git's own refusal to help, so a run that ends holding one keeps everything.

    What makes it readable from outside is the lease: `Integration` releases one on every path that
    settles, so a lease still live where `api._walk` ends *is* a landing nobody settled. The
    workflow below takes the hold and returns without either verb, which is the mistake
    `ARCHITECTURE.md` writes down rather than the case the framework expects.
    """
    harness = _fakes(tmp_path)

    await _run(harness, "holding")

    trees = _trees(tmp_path)
    assert base_worktree(trees, LABEL).is_dir(), (
        "the run ended holding a landing and its own checkout was taken back anyway - which is "
        "where the merge state and anybody's half-typed resolution were"
    )
    assert worktree_dir(trees, LABEL, CHILD).is_dir(), "the child's checkout went with it"
    assert str(LABEL) in capsys.readouterr().err, (
        "the run kept its checkouts and said nothing, so an operator sees only that the disk has "
        "not been tidied up"
    )

# --- what the operator is told about the branch ---------------------------------------------------

@pytest.mark.asyncio
async def test_a_finished_run_names_on_stderr_the_branch_its_work_can_be_taken_from(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The deliverable's other half: the branch is there, and somebody is told which one it is.

    On stderr, for `cli/commands/__init__.py`'s reason. `run_branch` is a pure function of the
    label, and `agl run -h` spells the rule out where the label is typed - so a script that started
    this run already holds the answer and nothing here is a name a machine reads. It is a note to
    whoever does not know AGL's naming rule, and it goes beside the rest of what the release has to
    say rather than onto the stream `run 'auth' finished` is written to.

    The promise and the fact are asserted together, because the failure worth catching is not a
    missing line: it is a line saying `git checkout agl/auth` in a world where git would answer
    `fatal: 'agl/auth' is already used by worktree at ...`.
    """
    harness = _over(repository, tmp_path)

    await _run(harness, "landing")

    printed = capsys.readouterr()
    assert OFFERED in printed.err, (
        f"the run finished and said nothing about where its work went: {printed.err!r}. The label "
        f"is what an operator typed and the branch is what they are left to work out"
    )
    assert printed.out == "", "a note about a teardown went to the stream a machine reads"
    assert _asked(repository, "checkout", "--quiet", run_branch(LABEL)), (
        f"the release printed {OFFERED!r} and git refuses it, so the one line telling an operator "
        f"where their work is sends them at a `fatal:` instead"
    )

@pytest.mark.asyncio
async def test_a_stop_says_where_the_work_landed_exactly_as_a_return_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The half no return value can carry, which is why this line is written where it is decided.

    A run ending on a `Stop` hands nothing back - the workflow's own exception is what leaves
    `api.run` - so a field on `api.Replayed` would say where the work landed for a run that
    returned and say nothing for the one somebody ended on purpose, which is the run they are most
    likely to go and look at. Both are driven here and their stderr compared rather than matched
    against a sentence: two tests each asserting one line would go on passing in a world where the
    two had drifted into saying it differently.
    """
    stopped = _fakes(tmp_path / "stopped")
    with pytest.raises(Stop):
        await _run(stopped, "halting")
    after_stopping = capsys.readouterr()

    await _run(_fakes(tmp_path / "returned"), "landing")

    after_returning = capsys.readouterr()
    assert after_stopping.err == after_returning.err != "", (
        f"a run that stopped and a run that returned do not say the same thing about where the "
        f"work is: {after_stopping.err!r} against {after_returning.err!r}"
    )
    assert OFFERED in after_stopping.err

@pytest.mark.asyncio
async def test_a_run_that_could_not_give_its_own_checkout_back_offers_no_branch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The trap this line is written around: `agl/auth` is the deliverable either way, and it is
    only takeable once the checkout that held it has gone.

    `_Immovable` refuses every address, the run's own among them, so git would answer
    `fatal: 'agl/auth' is already used by worktree at ...` to anybody who typed what a released run
    is told to type. The line's presence is the whole of the report - it is absent here, and the
    warning naming what still stands is what an operator gets instead - so what is asserted is that
    no offer is made rather than that some other wording was chosen for it.
    """
    harness = _fakes(tmp_path)
    services = replace(harness.services, workspaces=_Immovable(harness.services.workspaces))

    await api.run(services, PROJECT, "landing", LABEL, (), points=POINTS)

    printed = capsys.readouterr()
    assert OFFERED not in printed.err, (
        f"the run could not take its own checkout back and invited an operator to check the branch "
        f"out anyway: {printed.err!r}. git refuses that outright while a worktree holds it"
    )
    assert str(LABEL) in printed.err, "the run said nothing at all about what it left standing"

@pytest.mark.asyncio
async def test_a_run_holding_an_unsettled_landing_is_offered_no_branch_it_cannot_take(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other ending that keeps everything, and so the other place the offer would be a lie.

    A live lease keeps every checkout the run cut, its own among them, so `agl/auth` is held
    exactly as it is in the test above and for a different reason. What an operator gets here is
    the warning naming the landing nobody settled and the two commands that address it, and no
    invitation to check out a branch git would refuse them.
    """
    harness = _fakes(tmp_path)

    await _run(harness, "holding")

    printed = capsys.readouterr()
    assert OFFERED not in printed.err, (
        f"the run kept every checkout it cut and invited an operator to check the branch out: "
        f"{printed.err!r}"
    )
    assert f"agl resume {LABEL}" in printed.err, (
        "the run that kept everything named neither of the two commands that address it"
    )

@pytest.mark.asyncio
async def test_a_child_branch_kept_behind_does_not_withhold_the_run_branch_from_the_operator(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Which refusal decides, asked where the two possible answers differ.

    `worktree_branch` spells a child's name with an infix, so no child checkout can ever hold
    `agl/auth` and no child's refusal says anything about whether it can be taken. `stranded` keeps
    a child branch and gives every checkout back, which is the run where a release reading one kept
    list for both questions would withhold the offer for a reason that is not about the deliverable
    at all - so both lines are asserted here, and the checkout that proves the offer beside them.
    """
    harness = _over(repository, tmp_path)

    await _run(harness, "stranded")

    printed = capsys.readouterr()
    assert OFFERED in printed.err and worktree_branch(LABEL, CHILD) in printed.err, (
        f"a child branch nobody landed cost the operator the line saying where the run's own work "
        f"is: {printed.err!r}. The two answers are about two different branches"
    )
    assert _asked(repository, "checkout", "--quiet", run_branch(LABEL))
