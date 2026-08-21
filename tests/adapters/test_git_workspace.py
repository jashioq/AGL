"""`GitWorkspaceProvider` against the `Workspace` contract, plus what only real git can show.

The first class is the whole of both ports: `WorkspaceContract` with its two fixtures overridden
and nothing else touched. Everything `WorkspaceProvider` and `Workspace` promise is asserted
there, by a suite written at stage 3 against the ports' docstrings and before this adapter
existed - which is the inversion the build rests on (§1.9), and the reason nothing below
re-asserts any of it.

What is below is what that suite says it deliberately cannot see, because it is written against a
port and a port has no git in it. Its own docstring lists the gaps; these are the ones a real
repository can close:

  * **The branch names that actually get created.** The suite treats a branch as an opaque string
    and compares it only to other branches, on purpose - a workspace reports the name it carries
    rather than the name today's scheme would compute. So the one thing it cannot see is the thing
    §3.9 spent a paragraph on: `agl/<label>` and `agl/_work/<label>/<ns>` coexisting as refs in one
    repository, in either creation order, where the obvious scheme cannot exist at all.
  * **That the user's own checkout is untouched.** Gap 7 in the suite: "§3.9's 'AGL never touches
    the user's working directory' is a promise about a directory this suite has no handle on."
    This file has the handle.
  * **The lock.** Gap 2: the suite drives one provider in one process and cannot start a second.
    A `threading.Lock` would satisfy every test it can write and protect nothing, so the lock is
    provoked here by a real second process taking it.
  * **The worktree edge cases underneath the port's clauses** - a registration left standing by a
    crash, a place another line of work already holds - which are refusals git states and which
    the port describes only in its own vocabulary.

Named `test_git_workspace.py`, for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import asyncio
import fcntl
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.ports.errors import ConflictError
from agl.ports.ids import Namespace, RunLabel
from agl.ports.tree_layout import TreesRoot, run_branch, worktree_branch
from agl.ports.workspace import WorkspaceProvider
from contracts.workspace import WorkspaceContract

# Module-level tests do not inherit the marker the contract classes set on themselves, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is
# how a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

# This file builds its own names rather than importing the contract suite's: only
# `WorkspaceContract` is public there, the three `_workspace_*` modules being its private assembly.
LABEL: Final = RunLabel("acceptance")
OTHER: Final = RunLabel("reversed")
CHILD: Final = Namespace("T-01")

# A directory the fixture repository does not carry, so that a file appearing under it appeared
# because a workspace put it there.
WORK: Final = "agl-acceptance.txt"

# What the fixture repository tells git to ignore, and a file under it. `restore` deliberately
# leaves this alone; every other untracked leaving it takes away.
IGNORED_DIR: Final = "build-output"
IGNORED: Final = f"{IGNORED_DIR}/artifact.bin"

# §3.9's lock file, named here so that this file asserts *where* it is rather than reading the
# implementation's constant back to itself. A test importing that constant would agree with the
# adapter whatever either of them said.
LOCK: Final = "worktrees.lock"

# Takes the lock the way another `agl` invocation would - a second process, not a second thread -
# announces that it has it, and holds it for as long as it was told to. Written as a script and
# not a thread on purpose: an in-process lock would pass against a `threading.Lock` and prove
# nothing, and this is the one claim §3.9 makes that the contract suite cannot reach.
HOLDER: Final = """
import fcntl, os, sys, time
lock, announcement, seconds = sys.argv[1], sys.argv[2], float(sys.argv[3])
handle = os.open(lock, os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(handle, fcntl.LOCK_EX)
os.close(os.open(announcement, os.O_CREAT | os.O_WRONLY))
time.sleep(seconds)
os.close(handle)
"""

# How long that process holds it, and how long a waiter has to have waited for the wait to have
# been real. Well above what an uncontended provisioning takes and well under the hold, so neither
# a slow machine nor a fast one turns this into a different assertion.
HELD: Final = 0.6
WAITED: Final = 0.3


def _git(repository: Path, *argv: str) -> str:
    """Run git for the fixtures and the assertions. Synchronous on purpose: this is arrangement
    and observation, not the thing under test, and a test that built its repository through the
    adapter would be resting the arrangement on the behaviour it is about to check."""
    done = subprocess.run(
        ["git", *argv], cwd=repository, capture_output=True, text=True, check=True
    )
    return done.stdout


def _taken(lock: Path) -> bool:
    """Whether another process can take the lock right now - asked by actually being one.

    `flock` treats two descriptors on one file independently even inside one process, so this
    would answer correctly from here; it is a subprocess anyway, because what is being asked about
    is a cross-process guarantee and asking it in-process is how that distinction gets lost.
    """
    taking = "import fcntl, os, sys; " + (
        "handle = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644); "
        "fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)"
    )
    return subprocess.run([sys.executable, "-c", taking, str(lock)]).returncode == 0


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with two commits and a `.gitignore`, and no configuration from this
    machine.

    The `GIT_CONFIG_*` variables are what make this suite the same suite everywhere: a developer
    with `commit.gpgsign` on, a `core.hooksPath` of their own, or a template directory would
    otherwise be running different tests. They are set through `monkeypatch` so that the adapter -
    which inherits the environment, and says so - sees them too, and the identity variables are
    set because `commit_all` deliberately does not invent one.

    It is at `tmp_path/repo` and the trees root is its sibling, which is the layout §3.9 draws.
    Nesting the trees root inside the working tree would make every worktree AGL creates show up
    in the user's own `git status`, and one of the tests below is that it does not.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "AGL contract")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "source.txt").write_text("the user's own work\n", encoding="utf-8")
    (work / ".gitignore").write_text(f"{IGNORED_DIR}/\n", encoding="utf-8")
    _git(work, "add", "source.txt", ".gitignore")
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work


@pytest.fixture
def trees(tmp_path: Path) -> TreesRoot:
    """The trees root, beside the repository and empty. Absolute, which is all `TreesRoot` asks."""
    return TreesRoot(tmp_path / "trees")


@pytest.fixture
def provider(repository: Path, trees: TreesRoot) -> WorkspaceProvider:
    """The provider the module-level tests drive. The contract suite has its own, on the class."""
    return GitWorkspaceProvider(repository, trees)


@pytest.fixture
def base(repository: Path) -> str:
    """The commit a run is cut from, resolved - the pinned `RunSpec.base_sha` shape of a base."""
    return _git(repository, "rev-parse", "HEAD").strip()


class TestGitWorkspace(WorkspaceContract):
    """Both ports, in full, against real git.

    Two overrides and nothing else, which is what the suite asks for: every label, namespace, file
    and message it needs it builds itself out of the ports' own types, so this is the only place it
    is pointed at an implementation. Both fixtures depend on `repository`, which is how the base
    and the provider are guaranteed to be talking about one repository.
    """

    @pytest.fixture
    def provider(self, repository: Path, trees: TreesRoot) -> WorkspaceProvider:
        """A provider over a fresh repository and an empty trees root per test.

        The suite's own fixture is annotated `WorkspaceProvider | Iterator[WorkspaceProvider]` so
        that either shape of override typechecks; narrowing the return is the first of the two, and
        the repository is `tmp_path`'s to tear down.
        """
        return GitWorkspaceProvider(repository, trees)

    @pytest.fixture
    def base(self, repository: Path) -> str:
        """A resolved commit id, which is one of the two forms the port takes."""
        return _git(repository, "rev-parse", "HEAD").strip()


# --- The branch scheme, which the suite treats as an opaque string ------------------------------


async def test_the_run_branch_and_a_child_branch_coexist_as_refs_in_either_creation_order(
    provider: WorkspaceProvider, repository: Path, base: str
) -> None:
    """§3.9's paragraph, and stage 5's acceptance criterion, asserted through the adapter.

    `agl/<label>` and `agl/<label>/<ns>` cannot both exist in git - `refs/heads/agl/auth` would
    have to be a file and a directory at once - and `git check-ref-format` passes each name on its
    own, which is why nothing in `ids.py` could have caught it and why `tree_layout` routes
    children under `agl/_work/`. `tests/ports/test_tree_layout.py` pins that against raw git; what
    is pinned here is that this adapter creates exactly those names and that the pair really does
    survive in a repository, in whichever order a run happens to ask for it.

    The two checkouts being siblings is the other half of §3.9 in the same observation: worktree
    directories are flat however deep the namespaces nest, because a worktree inside another
    worktree's working tree shows up in that one's `git status` and in its build gate.
    """
    run = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)

    assert run.branch == run_branch(LABEL)
    assert child.branch == worktree_branch(LABEL, CHILD)
    assert child.path.parent == run.path.parent, (
        "the run's own checkout and its child are not siblings, so one of them is inside the "
        "other's working tree - which §3.9 flattens the trees root specifically to prevent"
    )

    reversed_child = await provider.open(OTHER, CHILD, base)
    reversed_run = await provider.open(OTHER, None, base)

    refs = _git(repository, "for-each-ref", "--format=%(refname)", "refs/heads/").split()
    for branch in (run.branch, child.branch, reversed_child.branch, reversed_run.branch):
        assert f"refs/heads/{branch}" in refs, (
            f"{branch!r} is not a ref in the repository, so the checkout carrying it is on a name "
            f"nothing can push, log or merge"
        )


# --- The user's own checkout, which the suite has no handle on ----------------------------------


async def test_the_users_own_checkout_is_untouched_and_stays_clean_while_a_run_works(
    provider: WorkspaceProvider, repository: Path, base: str
) -> None:
    """§3.9's promise: AGL never writes into the target repository except through a workspace.

    Including its own integration branch, which lives in `_base` rather than in the user's
    checkout - so a run provisions two places, commits in both, and the directory the user has
    open is on the same branch at the same commit with nothing to report. The two preflight checks
    the old implementation had, a trunk-branch check and a dirty-repository refusal, are deleted
    rather than made configurable for exactly this reason: a worktree is cut from a *ref*, so what
    the user has checked out is not this adapter's business either way.
    """
    before = _git(repository, "rev-parse", "HEAD").strip()

    run = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)
    for workspace in (run, child):
        (workspace.path / WORK).write_text("work done in a worktree\n", encoding="utf-8")
        await workspace.commit_all("work done in a worktree")

    assert _git(repository, "status", "--porcelain") == "", (
        "the user's working directory has something to report while a run is going. AGL is "
        "supposed to be invisible in it - `git status` in `repo/` stays clean, which is the "
        "whole reason the trees root is not inside it"
    )
    assert _git(repository, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert _git(repository, "rev-parse", "HEAD").strip() == before
    assert not (repository / WORK).exists(), "a workspace's work landed in the user's own checkout"


# --- The lock, which the suite cannot start a second process to see -----------------------------


async def test_the_registry_lock_is_a_file_in_the_trees_root_and_is_let_go_of_afterwards(
    provider: WorkspaceProvider, trees: TreesRoot, base: str
) -> None:
    """Where §3.9 says it goes, and held for no longer than the two operations it guards.

    A lock still held once `open` has returned would be a lock spanning a merge, a build or a
    person deciding something - the thing §3.9 says it must never be - and nothing about the
    provider's return value would show it. Asked by another process actually taking it.
    """
    await provider.open(LABEL, CHILD, base)

    lock = trees.path / LOCK
    assert lock.is_file(), (
        f"there is no lock file at {lock}. §3.9 puts it in the trees root, which is the root this "
        f"provider was built with, so that nothing has to resolve the repository to find it"
    )
    assert _taken(lock), (
        "the worktree lock is still held after provisioning returned. It guards `worktree add` "
        "and `worktree prune` and nothing else - milliseconds, never across a merge or a human "
        "decision"
    )


async def test_a_second_process_holding_the_registry_lock_makes_provisioning_wait_for_it(
    provider: WorkspaceProvider, trees: TreesRoot, base: str
) -> None:
    """The one claim a thread lock would pass and a run would still be wrong about.

    Two `agl run` invocations are two processes, so the mutex on `.git/worktrees/` has to be
    cross-process; a `threading.Lock` serialises the coroutines of one process, passes every test
    that can be written from inside it, and leaves two concurrent runs corrupting one registry.
    So the holder here is a real second process, taking `flock(2)` on the same file exactly as
    another AGL would, and what is asserted is that provisioning waited for it rather than walking
    straight past.

    It is asserted as a lower bound on elapsed time and never as an upper one: a machine under
    load can make anything slow, and only "it did not wait at all" is evidence of the bug.
    """
    trees.path.mkdir(parents=True, exist_ok=True)
    lock = trees.path / LOCK
    announcement = trees.path / "held"
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(lock), str(announcement), str(HELD)]
    )
    try:
        for _ in range(500):
            if announcement.exists():
                break
            await asyncio.sleep(0.01)
        assert announcement.exists(), "the holding process never reported taking the lock"

        started = time.monotonic()
        workspace = await provider.open(LABEL, CHILD, base)
        waited = time.monotonic() - started
    finally:
        holder.wait(timeout=30)

    assert waited > WAITED, (
        f"provisioning took {waited:.3f}s while another process held the worktree lock for "
        f"{HELD:g}s, so it did not wait for it. §3.9's mutex is cross-process - a lock that only "
        f"holds within one process protects nothing about two `agl run` invocations"
    )
    assert workspace.path.is_dir(), "and it did provision once the lock came free"


# --- Worktree edge cases the port describes only in its own vocabulary --------------------------


async def test_a_registration_left_standing_by_a_crash_does_not_block_reprovisioning(
    provider: WorkspaceProvider, repository: Path, base: str
) -> None:
    """The state git refuses on, and the reason `prune` is one of the two locked operations.

    A checkout whose directory is gone while its registration stands is what a crash - or a person
    tidying up by hand - leaves behind, and git will not add over it: *"is a missing but already
    registered worktree; use 'add -f' to override, or 'prune' or 'remove' to clear"*. A provider
    that only ever called `add` would fail there for the rest of the run's life, on a repository
    nothing is actually wrong with.

    The line of work survives the crash, so what comes back is the work that was committed - the
    same reading the suite makes of an `open` after a `remove`, arrived at by a different accident.
    """
    workspace = await provider.open(LABEL, CHILD, base)
    (workspace.path / WORK).write_text("committed before the crash\n", encoding="utf-8")
    await workspace.commit_all("committed before the crash")
    shutil.rmtree(workspace.path)
    assert str(workspace.path) in _git(repository, "worktree", "list", "--porcelain")

    again = await provider.open(LABEL, CHILD, base)

    assert again.path.is_dir(), "provisioning did not recover from a registration nothing backs"
    assert (again.path / WORK).read_text(encoding="utf-8") == "committed before the crash\n"


async def test_open_refuses_a_place_or_a_name_another_line_of_work_already_holds(
    provider: WorkspaceProvider, repository: Path, trees: TreesRoot, base: str
) -> None:
    """The port's `ConflictError` clause, which the contract suite says outright it cannot provoke.

    It cannot, and it says why: reaching the state needs a line of work under this name that is
    not this workspace's, and the only thing making lines of work in that suite is the provider
    under test, under an address it is required to hand back. From out here it takes one raw git
    command, and both shapes of it are worth pinning - somebody else's checkout standing in this
    run's place, and this run's branch checked out somewhere it did not put it. Git refuses the
    second on its own; the first is refused before git is asked, because "already exists" would
    tell a person nothing about what is there.

    `errors.py`'s sentence for this class is that nothing has been changed when it is raised, and
    exit 4 tells a script to pick another name or clear the old run.
    """
    intruder = trees.path / str(LABEL) / str(CHILD)
    _git(repository, "worktree", "add", "-q", "-b", "somebody-else", str(intruder), "main")

    with pytest.raises(ConflictError) as refused:
        await provider.open(LABEL, CHILD, base)
    assert "somebody-else" in str(refused.value), (
        "the refusal does not say what is in the way, which is the one thing a person needs in "
        "order to decide whether to clear it"
    )

    _git(repository, "worktree", "remove", "--force", str(intruder))
    elsewhere = trees.path / "elsewhere"
    _git(repository, "branch", worktree_branch(LABEL, CHILD), "main")
    _git(repository, "worktree", "add", "-q", str(elsewhere), worktree_branch(LABEL, CHILD))

    with pytest.raises(ConflictError):
        await provider.open(LABEL, CHILD, base)


# --- What a restore takes away, and the one thing it deliberately leaves ------------------------


async def test_restore_takes_away_a_nested_repository_and_leaves_what_gitignore_covers(
    provider: WorkspaceProvider, base: str
) -> None:
    """The two ends of "everything that was not in `head`", where this adapter had to choose.

    The contract suite asserts the ordinary leavings - a scratch file, a file in a directory that
    was not there - and cannot see either of these, both being about what git considers a working
    tree to contain. A directory holding a repository of its own is skipped by a single `-f`, and
    an agent that cloned something into its workspace left it there exactly as it left the scratch
    file; the second `-f` is what takes it.

    What `.gitignore` covers is deliberately kept. Those files can never reach a commit - staging
    everything will not stage them - so they cannot contaminate the ledger this method protects,
    and what they usually are is the build cache that makes the next step's own tests take seconds
    rather than minutes. `restore` runs on the way out of every step that recorded nothing, so
    deleting them would buy nothing the port asks for and charge a cold build for it.
    """
    workspace = await provider.open(LABEL, CHILD, base)
    (workspace.path / WORK).write_text("the recorded state\n", encoding="utf-8")
    head = await workspace.commit_all("the recorded state")

    nested = workspace.path / "vendored"
    _git(workspace.path, "init", "-q", str(nested))
    (nested / "cloned.txt").write_text("somebody else's repository\n", encoding="utf-8")
    (workspace.path / IGNORED_DIR).mkdir()
    (workspace.path / IGNORED).write_text("an expensive build\n", encoding="utf-8")

    await workspace.restore(head)

    assert not nested.exists(), (
        "a nested repository survived a restore. It was never in the recorded state and nothing "
        "here is going to look inside it first - `restore` does not care what it is throwing away"
    )
    assert (workspace.path / IGNORED).is_file(), (
        "a file .gitignore covers was taken away by a restore. git has already been told it is "
        "not part of the state, and it is the build cache the next step would have to make again"
    )
    assert await workspace.head() == head


# --- The lock file is a file, and the tests above have been holding it --------------------------


async def test_the_lock_survives_being_taken_and_released_many_times_over(
    provider: WorkspaceProvider, trees: TreesRoot, base: str
) -> None:
    """Never unlinked, which is how two processes would end up holding two files of one name.

    A lock file that is deleted on release is a lock file a second process can be holding by
    inode while a third creates a new one and takes that - two holders, both correct, of a mutex
    that has quietly become two. So the file is created once and left, and provisioning and
    teardown both go through it repeatedly. `os.stat` identity is what says it is the same file
    rather than a new one wearing the same path.
    """
    lock = trees.path / LOCK
    await provider.open(LABEL, CHILD, base)
    first = os.stat(lock).st_ino

    await provider.remove(LABEL, CHILD)
    await provider.open(LABEL, CHILD, base)
    await provider.open(LABEL, None, base)

    assert os.stat(lock).st_ino == first, "the lock file was replaced, so it is not one lock"
    assert _taken(lock)
    with open(lock, "rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert handle.read() == b"", "something is writing to the lock file; only the name is used"
