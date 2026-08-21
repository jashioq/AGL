"""The three fakes against the three contract suites, plus what only a fake can be asked.

The first three classes are the ports in full: `WorkspaceContract`, `HistoryContract` and
`IntegratorContract` with their fixtures overridden and nothing else touched, the same tests the
real adapters run in `test_git_workspace.py`, `test_git_history.py` and `test_git_integrator.py`.
That is the mechanism §1.9 asks for - the real adapter and the fake held to one suite, written at
stage 3 before either existed - and nothing below re-asserts any of it.

Where the two implementations *differ* is not here either. A divergence is a fact about the pair,
so it belongs in `test_git_parity.py` beside the assertions that they otherwise answer alike, and
that file holds the list closed.

What is below is the third thing: clauses that are true of this implementation and have nowhere
else to be asserted, because the contract suites drive one instance in one process and the parity
file needs an answer both implementations can give.

  * **Two repositories share nothing.** The suites build one per test and cannot ask. It is what
    makes an all-fakes bundle built twice two repositories rather than one, and it is the fake's
    answer to two `agl` invocations over one `.git/`.
  * **One repository is one repository, however many adapters are built over it.** The real three
    reach one shared object through the filesystem, so two `GitIntegrator`s over one path are the
    same integrator; the fake has to make that true by holding nothing itself, and the hold §3.4
    argues about is the case where it matters most.
  * **The lock that is deliberately not taken.** §3.9's `flock` guards git's worktree registry
    across processes. This registry is a dict in one process, so a second process would contend
    over nothing - and a lock file appearing in the trees root would say otherwise.
  * **What a crash leaves on disk.** A `FakeRepository` dies with its process and the checkouts it
    made do not, so the next invocation meets a directory full of files that nothing has
    registered. That is the one half of §3.4's durability question a fake still has to answer.

Named `test_git_fake.py`, for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

from pathlib import Path
from typing import Final

import pytest

from agl.adapters.git.fake import (
    FakeHistory,
    FakeIntegrator,
    FakeRepository,
    FakeWorkspaceProvider,
)
from agl.ports.errors import ConflictError, InternalError, NotFoundError
from agl.ports.history import History
from agl.ports.ids import Namespace, RunLabel
from agl.ports.integration import Integrator
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import WorkspaceProvider
from contracts.history import HistoryContract
from contracts.integration import IntegratorContract
from contracts.workspace import WorkspaceContract

# Module-level tests do not inherit the marker the contract classes set on themselves, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is how
# a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

# This file builds its own names rather than importing the contract suites': only the three
# contract classes are public there, the `_workspace_*`, `_history_*` and `_integration_*` modules
# being their private assembly.
LABEL: Final = RunLabel("acceptance")
CHILD: Final = Namespace("T-01")
SIBLING: Final = Namespace("T-02")

# What a fresh repository is seeded with, so that a run has something to be cut from - one file,
# under a name nobody's real project would collide with in a test.
SOURCE: Final = "agl-acceptance/source.txt"
BODY: Final = b"the state a run is cut from\n"

# A file two children collide over, and two contents that share not one line.
CONTESTED: Final = "agl-acceptance/contested.txt"
MINE: Final = b"what the child wrote\n"
YOURS: Final = b"what the sibling wrote instead\n"

# §3.9's lock file, named here so that this file asserts *where* one would be rather than reading
# a constant back out of the implementation that would then agree with itself.
LOCK: Final = "worktrees.lock"


@pytest.fixture
def repository() -> FakeRepository:
    """A fresh in-memory repository, seeded with one file and on its default branch.

    The substitution for the directory the real adapters are handed: the container builds one of
    these and gives the same instance to all three fakes, which is what makes them three ports over
    one repository rather than three that happen to agree.
    """
    return FakeRepository({SOURCE: BODY})


@pytest.fixture
def trees(tmp_path: Path) -> TreesRoot:
    """The trees root, empty. Absolute, which is all `TreesRoot` asks."""
    return TreesRoot(tmp_path / "trees")


@pytest.fixture
def provider(repository: FakeRepository, trees: TreesRoot) -> WorkspaceProvider:
    """The provider the module-level tests drive. The contract suites have their own overrides."""
    return FakeWorkspaceProvider(repository, trees)


@pytest.fixture
def integrator(repository: FakeRepository) -> Integrator:
    """The integrator those tests land with - over the same repository as the provider above."""
    return FakeIntegrator(repository)


@pytest.fixture
def base(repository: FakeRepository) -> str:
    """The state a run is cut from, resolved - the pinned `RunSpec.base_sha` shape of a base."""
    return repository.resolve(repository.default_ref)


class TestFakeWorkspaceProvider(WorkspaceContract):
    """Both workspace ports in full, against no git at all.

    Two overrides and nothing else, which is what the suite asks for. Both depend on `repository`,
    which is how the provider and the base are guaranteed to be talking about one repository.
    """

    @pytest.fixture
    def provider(self, repository: FakeRepository, trees: TreesRoot) -> WorkspaceProvider:
        """The fake, over a repository nothing has provisioned into yet."""
        return FakeWorkspaceProvider(repository, trees)

    @pytest.fixture
    def base(self, repository: FakeRepository) -> str:
        """A resolved commit id, which is the shape a run's own workspace is cut from (§3.6)."""
        return repository.resolve(repository.default_ref)


class TestFakeHistory(HistoryContract):
    """The `History` port in full. Three overrides, all over one repository."""

    @pytest.fixture
    def history(self, repository: FakeRepository) -> History:
        """The fake, bound to that repository by construction, as the port requires."""
        return FakeHistory(repository)

    @pytest.fixture
    def provider(self, repository: FakeRepository, trees: TreesRoot) -> WorkspaceProvider:
        """`commit_all` is the only member across both ports that records a state to ask about."""
        return FakeWorkspaceProvider(repository, trees)

    @pytest.fixture
    def base(self, repository: FakeRepository) -> str:
        """A state of that same repository for the workspaces this suite records into."""
        return repository.resolve(repository.default_ref)


class TestFakeIntegrator(IntegratorContract):
    """The `Integrator` port in full, including the conflict protocol. Three overrides."""

    @pytest.fixture
    def integrator(self, repository: FakeRepository) -> Integrator:
        """The fake, bound to that repository by construction, as the port requires."""
        return FakeIntegrator(repository)

    @pytest.fixture
    def provider(self, repository: FakeRepository, trees: TreesRoot) -> WorkspaceProvider:
        """The workspaces this suite lands between - over the same repository as the integrator."""
        return FakeWorkspaceProvider(repository, trees)

    @pytest.fixture
    def base(self, repository: FakeRepository) -> str:
        """One base for all three workspaces, which is what a run's own place and its children
        are."""
        return repository.resolve(repository.default_ref)


async def test_two_repositories_share_nothing(tmp_path: Path) -> None:
    """A bundle built twice is two repositories, which is two `.git/` directories' worth of
    apart.

    The contract suites drive one repository per test and so cannot ask this at all, and it is the
    property that makes `--dry-run` runs independent of each other: a line of work recorded in one
    is not a line of work in the other, and a `resolve` of the first's state is a refusal in the
    second.
    """
    first, second = FakeRepository({SOURCE: BODY}), FakeRepository({SOURCE: BODY})
    provider = FakeWorkspaceProvider(first, TreesRoot(tmp_path / "first"))

    workspace = await provider.open(LABEL, CHILD, first.resolve(first.default_ref))
    _put(workspace.path, CONTESTED, MINE)
    recorded = await workspace.commit_all("work that is only in the first repository")

    assert await FakeHistory(first).contains(recorded, recorded) is True
    with pytest.raises(NotFoundError):
        await FakeHistory(second).resolve(recorded)


async def test_one_repository_is_one_integrator_however_many_are_built_over_it(
    repository: FakeRepository, trees: TreesRoot, base: str
) -> None:
    """§3.4's durable hold, in the strongest form one process admits.

    The plan requires a conflicted landing's hold to be readable from the repository rather than
    kept in the object that took it, because a run that dies holding a target can only be released
    by a later invocation - and it says a contract suite cannot catch this, which 5.4 confirmed by
    passing the whole of one with an in-memory hold. A `FakeRepository` dies with its process, so
    the crash that clause is about leaves nothing behind to be released; what remains true, and is
    asserted here, is the structural half: an integrator built *afterwards* over the same
    repository sees the hold and can end it. An implementation keeping the hold in an attribute
    passes every test in `IntegratorContract` and fails this one.
    """
    provider = FakeWorkspaceProvider(repository, trees)
    target = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)
    sibling = await provider.open(LABEL, SIBLING, base)
    _put(child.path, CONTESTED, MINE)
    await child.commit_all("the child's own work")
    _put(sibling.path, CONTESTED, YOURS)
    await sibling.commit_all("the sibling's own work")

    took = FakeIntegrator(repository)
    assert (await took.land(child, target)).conflicted is False
    settled = await target.head()
    assert (await took.land(sibling, target)).conflicted is True

    found = FakeIntegrator(repository)
    assert (await found.retry(target)).conflicted is True, (
        "an integrator built after the hold was taken cannot see it, so the hold is being kept "
        "in whichever object happened to take it - which is the shape §3.4 forbids"
    )
    await found.abort(target)
    assert await target.head() == settled
    with pytest.raises(InternalError):
        await took.retry(target)


async def test_the_registry_lock_is_deliberately_not_taken(
    provider: WorkspaceProvider, trees: TreesRoot, base: str
) -> None:
    """§3.9's `flock` guards git's worktree registry across processes. There is nothing to guard.

    A second process gets a different `FakeRepository`, with different states, different lines of
    work and a different registry, so a lock in the trees root would serialise nothing and would
    let the fake claim a guarantee it cannot offer. The absence is asserted rather than described,
    because a lock file appearing there is exactly how that claim would creep back in.
    """
    await provider.open(LABEL, None, base)
    await provider.open(LABEL, CHILD, base)

    assert not (trees.path / LOCK).exists(), (
        f"the fake created {LOCK} in the trees root. §3.9's lock is cross-process, and two "
        f"processes running on fakes share no repository at all - so a lock here excludes nothing"
    )


async def test_a_checkout_left_by_a_dead_process_is_refused_rather_than_adopted(
    repository: FakeRepository, trees: TreesRoot, base: str
) -> None:
    """The one half of §3.4's durability question a fake still has to answer.

    The repository dies with the process; the directories it made do not. So a later invocation
    meets a checkout full of files that nothing in its repository has ever heard of, and the
    choice is between provisioning over it - which silently merges a dead run's leavings into a
    fresh line of work - and refusing. git refuses, in as many words, and so does this: a place
    that already holds files and that nothing has open is somebody else's, and `remove` is the verb
    that clears it.
    """
    provider = FakeWorkspaceProvider(repository, trees)
    workspace = await provider.open(LABEL, CHILD, base)
    _put(workspace.path, "agl-acceptance/left-by-a-crash.txt", MINE)

    fresh = FakeRepository({SOURCE: BODY})
    later = FakeWorkspaceProvider(fresh, trees)

    with pytest.raises(ConflictError):
        await later.open(LABEL, CHILD, fresh.resolve(fresh.default_ref))

    await later.remove(LABEL, CHILD)
    reopened = await later.open(LABEL, CHILD, fresh.resolve(fresh.default_ref))
    assert not (reopened.path / "agl-acceptance" / "left-by-a-crash.txt").is_file(), (
        "the dead run's leavings are in a checkout provisioned after it was taken back"
    )


def _put(directory: Path, name: str, content: bytes) -> None:
    """Put `content` at a repository-relative, forward-slash separated `name` in a checkout.

    Split rather than pasted on, because a `str` holding `/` is a path only on the platforms that
    spell it that way - and these names keep one spelling on every platform by design.
    """
    at = directory.joinpath(*name.split("/"))
    at.parent.mkdir(parents=True, exist_ok=True)
    at.write_bytes(content)
