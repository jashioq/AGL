"""`GitIntegrator` against the `Integrator` contract, plus what only real git, real repositories and
real processes show.

The first class is the port in full: `IntegratorContract` with its three fixtures overridden and
nothing else touched. Everything `Integrator` promises is asserted there, by a suite written at
stage 3 against the port's docstrings and before this adapter existed - which is the inversion the
build rests on (§1.9), and the reason nothing below re-asserts any of it.

What is below is what that suite says outright it cannot see. Its own docstring lists ten gaps;
these are the ones this adapter can close, in the order they matter:

  * **That the hold survives the process that took it** (gaps 2 and 8). "Nothing here can kill a
    process", and nothing inspects a held target, so a hold kept in an attribute passes every test
    in that suite - and §3.4 says in as many words that it must not be one: *a run that dies
    holding a target can only be released by a later invocation, so the hold has to be readable
    from the repository*. That is asserted here across three real processes, one of which is killed
    outright while holding.
  * **That a `retry` ever lands** (gap 1). "Only the conflicted case is exercised here... an
    implementation whose `retry` can only ever conflict passes." Resolving a collision needs the
    held target put into a state the contract suite is forbidden to know the shape of. From out
    here it is two raw git commands.
  * **That `Conflict.paths` names anything** (gap 4). The suite accepts `()` and asserts only that
    a non-empty tuple names the file that collided. This adapter enumerates, so what is pinned here
    is the other half: that it names the files that collided and *not* the ones that did not.
  * **That the user's own checkout is untouched.** Not in the suite's list at all, because from
    inside it there is no such thing: it holds two workspaces and knows nothing about a repository
    they were cut from. §3.9's whole premise is that `git status` in `repo/` stays clean while a run
    lands work, and a landing runs `git merge`, which is the one command in this package with an
    obvious wrong place to run it.

Two more sit beside those, and neither is a gap in the suite - they are decisions this adapter made
that nothing else would notice: that a person's own merge configuration cannot decide whether a
landing lands or what it contains, and that a branch name spelled like a git option is a value and
never an option.

Named `test_git_integrator.py`, for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.ports.errors import InternalError, UpstreamError
from agl.ports.ids import Namespace, RunLabel
from agl.ports.integration import Integrator
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace, WorkspaceProvider
from contracts.integration import IntegratorContract

# Module-level tests do not inherit the marker the contract classes set on themselves, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is how
# a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

# This file builds its own names rather than importing the contract suite's: only
# `IntegratorContract` is public there, `_integration_targets` and `_workspace_files` being its
# private assembly.
LABEL: Final = RunLabel("acceptance")
CHILD: Final = Namespace("T-01")
SIBLING: Final = Namespace("T-02")

# What the fixture repository's HEAD is put on. Named here rather than read back out of anything,
# so that the untouched-checkout test asserts a fact about the repository it built.
TRUNK: Final = "main"

# A directory the fixture repository does not carry, so that a file appearing under it appeared
# because a test put it there. The nested spelling is deliberate: `Conflict.paths` promises
# repository-relative, forward-slash separated names, and a file at the root would prove neither.
WORK: Final = "agl-acceptance"

# The file the two children collide over, and the two files only one of them touches. The last is
# written identically by both, which git combines without a word - a conflict that named it would
# be naming a file nobody disagreed about.
COLLIDING: Final = f"{WORK}/both.txt"
MINE: Final = f"{WORK}/mine.txt"
THEIRS: Final = f"{WORK}/theirs.txt"
AGREED: Final = f"{WORK}/agreed.txt"

# How many lines a file written here has, so that two versions differ on every line rather than in
# one place: a merge that combined them would be a merge that guessed.
_LINES: Final = 24

# What the subprocesses below are handed and what they hand back. One JSON argument rather than an
# argv of positions, because these are three programs sharing one situation and a mislaid position
# would read as a failure of the thing under test.
_HOLDING: Final = """
import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.ports.ids import Namespace, RunLabel
from agl.ports.tree_layout import TreesRoot


async def main() -> None:
    where = json.loads(sys.argv[1])
    repository = Path(where["repository"])
    provider = GitWorkspaceProvider(repository, TreesRoot(Path(where["trees"])))
    integrator = GitIntegrator(repository)
    label = RunLabel(where["label"])
    target = await provider.open(label, None, where["base"])
    child = await provider.open(label, Namespace(where["child"]), where["base"])
    sibling = await provider.open(label, Namespace(where["sibling"]), where["base"])
    for workspace, text in ((child, where["mine"]), (sibling, where["theirs"])):
        (workspace.path / where["file"]).write_text(text, encoding="utf-8")
        await workspace.commit_all("a child's own work")
    await integrator.land(child, target)
    settled = await target.head()
    outcome = await integrator.land(sibling, target)
    print(
        json.dumps(
            {
                "settled": settled,
                "conflicted": outcome.conflicted,
                "paths": list(outcome.conflict.paths) if outcome.conflict else [],
            }
        ),
        flush=True,
    )
    os.kill(os.getpid(), signal.SIGKILL)


asyncio.run(main())
"""

_LOOKING: Final = """
import asyncio
import json
import sys
from pathlib import Path

from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.ports.ids import RunLabel
from agl.ports.tree_layout import TreesRoot


async def main() -> None:
    where = json.loads(sys.argv[1])
    repository = Path(where["repository"])
    provider = GitWorkspaceProvider(repository, TreesRoot(Path(where["trees"])))
    integrator = GitIntegrator(repository)
    target = await provider.open(RunLabel(where["label"]), None, where["base"])
    outcome = await integrator.retry(target)
    print(
        json.dumps(
            {
                "conflicted": outcome.conflicted,
                "paths": list(outcome.conflict.paths) if outcome.conflict else [],
                "summary": outcome.conflict.summary if outcome.conflict else "",
                "head": await target.head(),
            }
        ),
        flush=True,
    )


asyncio.run(main())
"""


def _git(where: Path, *argv: str) -> str:
    """Run git for the fixtures and the assertions. Synchronous on purpose: this is arrangement and
    observation, not the thing under test, and a test that built its situation through the adapter
    would be resting the arrangement on the behaviour it is about to check."""
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout


def _git_answers(where: Path, *argv: str) -> bool:
    """One of git's exit-status questions, asked from out here. 0 is yes and 1 is no."""
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=False)
    assert done.returncode in (0, 1), f"`git {' '.join(argv)}` answered neither yes nor no: {done}"
    return done.returncode == 0


def _apart(where: Path, script: str, situation: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run one of the scripts above in a real interpreter of its own, and hand back what it did.

    The environment is inherited, which is what carries the `GIT_CONFIG_*` variables the repository
    fixture set: a child of this process is subject to the same hermeticity, or it is a different
    suite running under the developer's own git configuration.
    """
    return subprocess.run(
        [sys.executable, "-c", script, json.dumps(situation)],
        cwd=where,
        capture_output=True,
        text=True,
        check=False,
    )


def _body(marker: str) -> str:
    """A file's contents, derived from `marker` so that two versions differ on every line."""
    return "".join(f"{marker}: line {index} of {_LINES}.\n" for index in range(_LINES))


def _write(workspace: Workspace, name: str, text: str) -> None:
    """Put `text` at a repository-relative, forward-slash separated `name` inside `workspace`.

    Split rather than pasted on, because a `str` holding `/` is a path only on the platforms that
    spell it that way - and `Conflict.paths` is the forward-slash form whatever the platform is.
    """
    path = workspace.path.joinpath(*name.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read(workspace: Workspace, name: str) -> str | None:
    """What is at `name`, or `None` if nothing is - which is what "it was removed" looks like."""
    path = workspace.path.joinpath(*name.split("/"))
    return path.read_text(encoding="utf-8") if path.is_file() else None


class _Renamed(Workspace):
    """One real workspace under a branch name of this test's choosing.

    The only way to ask what an argument list does with a value spelled like a git option: every
    branch name that reaches the adapter in life comes from `tree_layout` through `Workspace.branch`
    and `ids.py` validated the parts it is made of, so the hostile value has to be introduced at the
    port, where the adapter reads it.
    """

    def __init__(self, real: Workspace, branch: str) -> None:
        self._real = real
        self._branch = branch

    @property
    def path(self) -> Path:
        return self._real.path

    @property
    def branch(self) -> str:
        return self._branch

    async def head(self) -> str:
        return await self._real.head()

    async def commit_all(self, message: str) -> str:
        return await self._real.commit_all(message)

    async def restore(self, head: str) -> None:
        await self._real.restore(head)


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with two commits, on `main`, and no configuration from this machine.

    The `GIT_CONFIG_*` variables are what make this suite the same suite everywhere: a developer
    with `commit.gpgsign` on, a `merge.ff` of their own, or - most to the point here - a
    `merge.verifySignatures` or a `pull.twohead` would otherwise be running different tests. They
    are set through `monkeypatch` so that the adapter, which inherits the environment and says so,
    sees them too, and so that the subprocesses started below inherit them in turn. The identity
    variables are set because a merge commit needs an author and this package invents none.

    It is at `tmp_path/repo` with the trees root as its sibling, which is the layout §3.9 draws.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "AGL acceptance")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", TRUNK)
    for which in ("the state before", "the state a run is cut from"):
        (work / "source.txt").write_text(_body(which), encoding="utf-8")
        _git(work, "add", "source.txt")
        _git(work, "commit", "-q", "-m", which)
    return work


@pytest.fixture
def trees(tmp_path: Path) -> TreesRoot:
    """The trees root, beside the repository and empty. Absolute, which is all `TreesRoot` asks."""
    return TreesRoot(tmp_path / "trees")


@pytest.fixture
def integrator(repository: Path) -> Integrator:
    """The integrator the module-level tests drive. The contract suite has its own, on the class."""
    return GitIntegrator(repository)


@pytest.fixture
def provider(repository: Path, trees: TreesRoot) -> WorkspaceProvider:
    """The provider making the workspaces those tests land between - over the same repository."""
    return GitWorkspaceProvider(repository, trees)


@pytest.fixture
def base(repository: Path) -> str:
    """The commit a run is cut from, resolved - the pinned `RunSpec.base_sha` shape of a base."""
    return _git(repository, "rev-parse", "HEAD").strip()


class TestGitIntegrator(IntegratorContract):
    """The port in full, against real git.

    Three overrides and nothing else, which is what the suite asks for. All three depend on
    `repository`, which is how the `Integrator`, the `WorkspaceProvider` and the base are guaranteed
    to be talking about one repository - the thing the suite names as gap 10 because nothing inside
    it can check that from outside.
    """

    @pytest.fixture
    def integrator(self, repository: Path) -> Integrator:
        """The adapter, bound to that repository by construction, as the port requires."""
        return GitIntegrator(repository)

    @pytest.fixture
    def provider(self, repository: Path, trees: TreesRoot) -> WorkspaceProvider:
        """`commit_all` is the only member across both ports that records work to land."""
        return GitWorkspaceProvider(repository, trees)

    @pytest.fixture
    def base(self, repository: Path) -> str:
        """A resolved commit id, which is the shape a run's own workspace is cut from (§3.6)."""
        return _git(repository, "rev-parse", "HEAD").strip()


async def _collide(
    integrator: Integrator, provider: WorkspaceProvider, base: str
) -> tuple[Workspace, Workspace, str]:
    """Land one child, collide the next with it, and hand back the target, the sibling and the head.

    §3.4's merge train, built the way the contract suite builds it and with this file's own names.
    The head is the one the *first* landing left, which is where `abort` promises to put the target
    back - not the state the run started in.
    """
    target = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)
    sibling = await provider.open(LABEL, SIBLING, base)
    _write(child, COLLIDING, _body("the child's own work"))
    await child.commit_all("the child's own work")
    _write(sibling, COLLIDING, _body("the sibling's own work, sharing not one line"))
    await sibling.commit_all("the sibling's own work")

    first = await integrator.land(child, target)
    assert first.conflicted is False, f"the first landing conflicted: {first.conflict}"
    settled = await target.head()

    outcome = await integrator.land(sibling, target)
    assert outcome.conflicted is True, (
        f"two children created {COLLIDING} with contents sharing not one line and the second "
        f"landing answered with head {outcome.head!r}"
    )
    return target, sibling, settled


# --- The hold, across three processes and a killed one ------------------------------------------


async def test_a_hold_taken_by_a_process_that_dies_is_found_and_released_by_later_ones(
    repository: Path, trees: TreesRoot, base: str, provider: WorkspaceProvider
) -> None:
    """§3.4's durable hold, which is the one thing in this deliverable no contract suite can catch.

    *The hold must be durable, not in-memory. A run that dies holding a target can only be released
    by a later invocation, so the hold has to be readable from the repository - an in-memory hold
    makes a resumed run's `abort()` a silent no-op and leaves the target half-combined forever.* The
    plan adds that a contract suite cannot catch this, since both implementations pass, and
    `integration.py`'s own gap list says the same twice over: nothing inspects a held target, and
    nothing there can kill a process.

    So this test is three processes. The first lands one child, collides the next with it, and is
    **killed outright while holding** - `SIGKILL`, so no finaliser, no `except`, no `abort` on the
    way out, and the assertion on its return code is that it really was killed rather than exiting.
    The second is a fresh interpreter that constructs an integrator that has never held anything and
    asks `retry`: an implementation whose hold lives in an attribute answers `InternalError` there
    and the process exits non-zero, which is why its exit status is asserted before its output is
    read. The third is this one, which releases it.

    A second `Integrator` object in *this* interpreter would prove nothing - a module-level dict
    would pass it - so nothing below constructs one until the release, and the two that matter are
    real processes with their own memory.
    """
    situation = {
        "repository": str(repository),
        "trees": str(trees.path),
        "base": base,
        "label": str(LABEL),
        "child": str(CHILD),
        "sibling": str(SIBLING),
        "file": "landed.txt",
        "mine": _body("the child's own work"),
        "theirs": _body("the sibling's own work, sharing not one line"),
    }

    took = _apart(repository, _HOLDING, situation)

    assert took.returncode == -signal.SIGKILL, (
        f"the process that was to die holding the target exited {took.returncode} instead of being "
        f"killed, so whatever it did on the way out is part of this test: {took.stderr}"
    )
    held = json.loads(took.stdout)
    assert held["conflicted"] is True, "the process that died was to die holding a conflict"

    found = _apart(repository, _LOOKING, situation)

    assert found.returncode == 0, (
        f"a fresh process asked the target it inherited to retry the landing and could not: "
        f"{found.stderr}. A hold that only the process which took it can see is the one §3.4 "
        f"refuses - the run that dies holding a target is exactly the run that cannot release it"
    )
    looked = json.loads(found.stdout)
    assert looked["conflicted"] is True, (
        "a second process retried a landing nobody resolved and was told it landed, so what it "
        "found was not the hold the first process left"
    )
    assert looked["paths"] == ["landed.txt"], (
        f"the inherited hold names {looked['paths']} as unresolved, and the file the two children "
        f"each created is landed.txt"
    )
    assert looked["summary"], "and a conflict a person is shown has to say something"
    assert looked["head"] == held["settled"], (
        "the target a later process found is not at the head the first landing left it at"
    )

    target = await provider.open(LABEL, None, base)
    integrator = GitIntegrator(repository)
    await integrator.abort(target)

    assert await target.head() == held["settled"], (
        f"releasing a hold taken by a process that has been dead for two processes left the target "
        f"at {await target.head()!r} rather than at {held['settled']!r}, where the landing that "
        f"succeeded put it"
    )
    assert _read(target, "landed.txt") == situation["mine"], (
        "the work of the child that did land is not what the target holds after the inherited hold "
        "was released"
    )
    with pytest.raises(InternalError):
        await integrator.retry(target)


# --- The half of `retry` the contract suite cannot reach ----------------------------------------


async def test_a_retry_lands_once_the_collision_is_resolved_in_the_held_target(
    integrator: Integrator, provider: WorkspaceProvider, base: str, repository: Path
) -> None:
    """Gap 1: "the landed branch of `retry` is exercised by nothing here".

    The contract suite cannot reach it, and says why: resolving a collision means putting the held
    target into a state the suite would have to know the shape of, which is the one piece of
    knowledge §3.4 removed from this port on purpose. From out here it is what a person at the
    workflow's conflict screen does - open the file, decide, and tell git the decision.

    What is asserted is that the landing actually completed rather than merely stopping conflicting:
    the head moved, the resolution is what the target holds, the sibling's work is in the target's
    past, and nothing is pending afterwards. The last one matters most - a `retry` that answered
    with a head and left the hold standing would have the next `abort` undo a landing it reported.
    """
    target, sibling, settled = await _collide(integrator, provider, base)
    landed = _git(sibling.path, "rev-parse", "HEAD").strip()
    resolution = _body("what the person at the conflict screen decided")
    _write(target, COLLIDING, resolution)
    _git(target.path, "add", "--", COLLIDING)

    outcome = await integrator.retry(target)

    assert outcome.conflicted is False, (
        f"retrying a landing whose collision was resolved and staged in the held target answered "
        f"with a conflict again: {outcome.conflict}. This port has no opinion about what they did "
        f"and looks again, and what it looks at says the collision is resolved"
    )
    assert outcome.head == await target.head() != settled, (
        f"the retry answered with {outcome.head!r}, the target is at {await target.head()!r}, and "
        f"it stood at {settled!r} before the landing. A landing that completed moved the target, "
        f"and the head it reports is the one the gate will run against"
    )
    assert _read(target, COLLIDING) == resolution, (
        "the resolution staged in the held target is not what the target holds after the landing "
        "was concluded, so what went in is not what the person decided"
    )
    assert _git_answers(repository, "merge-base", "--is-ancestor", landed, outcome.head or ""), (
        "the sibling's own commit is not in the past of the head the concluded landing reported, "
        "so what was recorded is a commit of the resolution rather than a landing of the sibling"
    )
    with pytest.raises(InternalError):
        await integrator.retry(target)


# --- What `Conflict.paths` names, and what it does not -------------------------------------------


async def test_the_conflict_names_the_files_that_collided_and_only_those(
    integrator: Integrator, provider: WorkspaceProvider, base: str
) -> None:
    """Gap 4: the suite "asserts only that a non-empty tuple names the file that actually collided".

    Empty is a claim the port protects and this implementation does not need to make, so the half
    left to assert is the one that goes wrong quietly: that the tuple is the files that collided and
    not everything the landing touched. Four files, and only one of them is a disagreement - one
    each that only one child wrote, and one both wrote identically, which git combines without a
    word. A workflow shown any of the other three sends a person to look in the wrong place, and the
    two the merge landed cleanly are the ones an implementation reading its own diff would name.

    The spelling is asserted too: repository-relative and forward-slash separated, which is what the
    port promises and what a file in a subdirectory is the only way to see.
    """
    target = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)
    sibling = await provider.open(LABEL, SIBLING, base)
    agreed = _body("what both children wrote, to the byte")
    for workspace, only, text in (
        (child, MINE, _body("the child's own work")),
        (sibling, THEIRS, _body("the sibling's own work, sharing not one line")),
    ):
        _write(workspace, COLLIDING, text)
        _write(workspace, only, text)
        _write(workspace, AGREED, agreed)
        await workspace.commit_all("a child's own work")
    first = await integrator.land(child, target)
    assert first.conflicted is False, f"the first landing conflicted: {first.conflict}"

    outcome = await integrator.land(sibling, target)

    assert outcome.conflict is not None, "the two children disagreed about one file"
    assert outcome.conflict.paths == (COLLIDING,), (
        f"the conflict names {outcome.conflict.paths}. Only {COLLIDING} was written twice with "
        f"contents sharing no line: {MINE} and {THEIRS} were each written once, {AGREED} was "
        f"written identically by both, and all three landed without anybody disagreeing"
    )
    assert COLLIDING in outcome.conflict.summary, (
        f"the line a person reads is {outcome.conflict.summary!r} and does not name the file that "
        f"collided, which is the one thing they need in order to go and resolve it"
    )
    await integrator.abort(target)


# --- The repository the user is working in -------------------------------------------------------


async def test_the_user_s_own_checkout_is_untouched_by_every_verb_on_this_port(
    integrator: Integrator, provider: WorkspaceProvider, base: str, repository: Path
) -> None:
    """§3.9's premise, asserted against the one command in this package that could break it.

    *AGL never writes into the target repo except through a `Workspace`* (§3.5), including its own
    integration branch, which lives in a `_base` worktree rather than the user's checkout - and
    `git status` in `repo/` stays clean while a run is going. A landing is `git merge`, which writes
    a commit, moves a ref and rewrites a working tree, so where it runs is load-bearing in a way
    that no other call in this package is: run in the repository, every assertion the contract suite
    makes would still pass, and the user would find their own checkout half-combined.

    Four sensors, all of them from outside the adapter: what the user has checked out, where that
    branch is, whether anything is dirty or newly untracked, and whether a landing is pending there.
    The last is the sharp one, because a hold taken in the user's checkout is the state a person
    cannot get out of without knowing what AGL did.
    """
    before = _git(repository, "status", "--porcelain").strip()
    on = _git(repository, "symbolic-ref", "HEAD").strip()

    target, _, settled = await _collide(integrator, provider, base)
    again = await integrator.retry(target)
    assert again.conflicted is True, "nothing resolved the collision, so the retry conflicts"
    await integrator.abort(target)
    assert await target.head() == settled, "and the release put the target back"

    assert _git(repository, "symbolic-ref", "HEAD").strip() == on == f"refs/heads/{TRUNK}", (
        "the user's checkout is on a different branch than the one it was on before a run landed "
        "anything, so AGL checked something out in the directory §3.9 says it never touches"
    )
    assert _git(repository, "rev-parse", "HEAD").strip() == base, (
        "the user's checkout is at a different commit than the one it was on. The run's own line "
        "of work advances with every landing, and it advances in a worktree of AGL's"
    )
    assert _git(repository, "status", "--porcelain").strip() == before == "", (
        "a landing left the user's working directory dirty. §3.9's whole premise is that they can "
        "carry on working in it while a run is going"
    )
    assert not _git_answers(repository, "rev-parse", "--verify", "--quiet", "MERGE_HEAD"), (
        "a landing is pending in the user's own checkout, which is a state they did not ask for "
        "and have no way to know the shape of"
    )


# --- Two decisions nothing else would notice -----------------------------------------------------


async def test_a_person_s_own_merge_configuration_cannot_decide_what_a_landing_contains(
    integrator: Integrator, provider: WorkspaceProvider, base: str, repository: Path
) -> None:
    """The line `history.py` draws, applied where there is no plumbing to hide behind.

    `git merge` is porcelain and has no plumbing equivalent that moves a ref, so the settings that
    would change *whether there is an answer at all* have to be refused by name. Two of them are
    ordinary things for a person to have and neither is anything to do with AGL:

      * **`pull.twohead = ours`** sets the default strategy for a two-head merge. Under it a landing
        exits 0, reports a head, and contains none of the child's work - the one misconfiguration
        on this list that loses work silently, and the reason the strategy is asked for by name.
      * **`merge.verifySignatures = true`** refuses to merge an unsigned commit, which every commit
        AGL makes is: a check that can only ever fail, against AGL's own bookkeeping on a branch it
        created minutes ago.

    Both are set in the repository the adapter is pointed at, and the assertion is that the child's
    work is in the target afterwards. A missing `--no-verify-signatures` fails this by raising; a
    missing `--strategy` fails it by landing an empty merge and reporting success, which is the
    failure that would otherwise be discovered by a person wondering where their work went.
    """
    _git(repository, "config", "pull.twohead", "ours")
    _git(repository, "config", "merge.verifySignatures", "true")
    target = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)
    mine = _body("the child's own work")
    _write(child, MINE, mine)
    await child.commit_all("the child's own work")

    outcome = await integrator.land(child, target)

    assert outcome.conflicted is False, (
        f"landing into a target that has touched nothing reported a conflict: {outcome.conflict}"
    )
    assert _read(target, MINE) == mine, (
        "the landing reported success and the child's work is not in the target. A merge strategy "
        "the repository chose decided what a landing contains, and it chose to contain nothing"
    )


async def test_a_resolution_recorded_on_this_machine_does_not_resolve_a_landing(
    integrator: Integrator, provider: WorkspaceProvider, base: str, repository: Path
) -> None:
    """`rerere`, the third setting, and the one that changes the answer rather than refusing.

    With it on, git replays a conflict resolution recorded earlier *on this machine* and stages it,
    so the same two branches conflict on one developer's machine and land on another - and the
    combination the build gate then decides about was resolved by a cache nobody in this run saw.
    §3.4 forbids exactly that: a conflict is "not resolved by guessing", and a resolution AGL cannot
    show anybody is a guess from where the workflow is standing.

    The recording is made the only way it can be, by having the collision once and resolving it
    with git directly, and then put back. What is asserted afterwards is that the landing still
    conflicts and still names the file - an adapter that let rerere run would answer with a hold
    that has nothing unresolved in it, whose `Conflict.paths` is empty and whose `retry` lands the
    recorded resolution without anybody deciding anything.
    """
    _git(repository, "config", "rerere.enabled", "true")
    _git(repository, "config", "rerere.autoUpdate", "true")
    target = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)
    sibling = await provider.open(LABEL, SIBLING, base)
    for workspace, text in (
        (child, _body("the child's own work")),
        (sibling, _body("the sibling's own work, sharing not one line")),
    ):
        _write(workspace, COLLIDING, text)
        await workspace.commit_all("a child's own work")
    first = await integrator.land(child, target)
    assert first.conflicted is False, f"the first landing conflicted: {first.conflict}"
    settled = await target.head()
    # The collision, had and resolved by hand so that rerere has something to replay. Deliberately
    # not through the adapter: the adapter is what this test says will not use it.
    subprocess.run(
        ["git", "merge", "--no-edit", "--no-gpg-sign", sibling.branch],
        cwd=target.path,
        capture_output=True,
        check=False,
    )
    _write(target, COLLIDING, _body("a resolution recorded on this machine and nowhere else"))
    _git(target.path, "add", "--", COLLIDING)
    _git(target.path, "commit", "--no-edit", "--no-gpg-sign")
    _git(target.path, "reset", "--hard", settled)

    outcome = await integrator.land(sibling, target)

    assert outcome.conflict is not None, (
        "a landing was resolved out of a resolution recorded on this machine, so the workflow was "
        "never shown a collision that two children genuinely had"
    )
    assert outcome.conflict.paths == (COLLIDING,), (
        f"the conflict names {outcome.conflict.paths} rather than {COLLIDING}, so something staged "
        f"a resolution and left the hold with nothing in it for a person to look at"
    )
    await integrator.abort(target)
    assert await target.head() == settled, "and the release puts it back where the landing did"


async def test_a_branch_name_spelled_like_a_git_option_is_a_value_and_never_an_option(
    integrator: Integrator, provider: WorkspaceProvider, base: str, repository: Path, tmp_path: Path
) -> None:
    """The audit 5.3 asked for, on the command in this package with the most to lose by it.

    Argv discipline stops a value being read as *shell* syntax and does nothing about one being read
    as a git *option*. `git merge` takes `-F <path>`, which reads a file into the commit message, so
    a branch spelled `--file=/etc/anything` is that file going into the target's history - the same
    hazard 5.3 found on `diff-tree --output=` and reproduced.

    **The condition that makes it observable is an upstream on the target's branch**, and it is set
    here on purpose rather than waited for. An option that eats itself leaves `git merge` with no
    commit named, and `merge.defaultToUpstream` - on by default - then merges the branch's upstream:
    so with one configured the misparse is a landing of *somebody else's work*, reported as success,
    with a file nobody offered as its message; without one it is an error, and the missing guard is
    invisible rather than harmless. `branch.autoSetupMerge = always` is the ordinary way a branch
    acquires an upstream, and nothing stops a person setting one by hand on a branch AGL made.

    The second half is the other shape of the same hazard and pins the other guard: `git merge` also
    takes `--abort`, so a branch named that would be a release. The port has no spelling for landing
    over a hold and the answer is `InternalError` either way - what is asserted is that the hold is
    still there afterwards, which is what a value read as that option would have taken away.
    """
    target = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)
    _write(child, MINE, _body("the child's own work"))
    await child.commit_all("the child's own work")
    _git(repository, "branch", f"--set-upstream-to={TRUNK}", target.branch)
    secret = tmp_path / "secret.txt"
    secret.write_text("what a message file would carry in\n", encoding="utf-8")
    settled = await target.head()

    with pytest.raises(UpstreamError):
        await integrator.land(_Renamed(child, f"--file={secret}"), target)

    assert await target.head() == settled, (
        "a landing whose branch was spelled like a git option moved the target, so the option ate "
        "the name AGL passed and git went and merged whatever else it could find"
    )
    assert "message file" not in _git(target.path, "log", "--format=%B"), (
        "the contents of a file named by a branch reached the target's history, so `-F` was read "
        "as an option and the value AGL passed as a branch chose what git read"
    )

    target, _, held = await _collide(integrator, provider, base)

    with pytest.raises(InternalError):
        await integrator.land(_Renamed(child, "--abort"), target)

    still = await integrator.retry(target)
    assert still.conflicted is True, (
        "landing a branch named `--abort` into a held target released the hold, so a value AGL "
        "passed as a branch was read as the option that gives up on a landing"
    )
    await integrator.abort(target)
    assert await target.head() == held, "and the release still puts it back"
