"""`GitHistory` against the `History` contract, plus what only real git and a real repository show.

The first class is the port in full: `HistoryContract` with its three fixtures overridden and
nothing else touched. Everything `History` promises is asserted there, by a suite written at stage 3
against the port's docstrings and before this adapter existed - which is the inversion the build
rests on (§1.9), and the reason nothing below re-asserts any of it.

What is below is what that suite says outright it cannot see. Its own docstring lists eight gaps and
three assumptions; these are the ones a real repository can close:

  * **That renames are detected** (gap 1). The suite accepts either legal answer to a move and so
    exercises `ChangeKind.RENAMED` and `FileChange.previous_path` only against an implementation
    that produces them. This one does, so the suite's rename branch does run - but the *cost* of
    that choice is a similarity threshold, and both sides of the threshold are pinned here, along
    with the fact that a repository which has turned rename detection off in its own configuration
    does not get a different answer.
  * **That a patch is a patch** (gap 2). "A patch in a format no reviewer has seen passes all four"
    of the suite's assertions. Here it is a unified diff, and a `diff.external` in the repository's
    own configuration - an ordinary thing for a person to have - does not replace it with the output
    of some other program.
  * **`clear`'s actual question** (gap 3). §3.10 deletes a run's line of work only once the base ref
    holds it, which in life means *merged*; the suite has no way to land anything, so the ancestry
    it asserts is the kind that comes from committing in one place. Landing it takes one raw git
    command from out here.
  * **`UpstreamUnavailable`** (gap 4). "Nothing here can make a repository unreachable, and
    inventing a member that could would be inventing a port." From out here it is a directory.
  * **What `default_ref` actually names** (gap 6). The suite asserts only that it resolves, twice
    the same way, because there is no second source for what the default *is*. This file has one:
    the branch the fixture put HEAD on.

The one gap this file does *not* close is the table §1.3 exists to contain - every status letter git
spells and what each becomes. That is `test_git_changes.py`'s, next to the pure function it asserts
and away from the `pytest.mark.asyncio` this module puts on everything in it.

Named `test_git_history.py`, for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import subprocess
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.git.history import GitHistory
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.ports.errors import NotFoundError, UpstreamUnavailable
from agl.ports.history import ChangeKind, FileChange, History
from agl.ports.ids import Namespace, RunLabel
from agl.ports.tree_layout import TreesRoot, worktree_branch
from agl.ports.workspace import Workspace, WorkspaceProvider
from contracts.history import HistoryContract

# Module-level tests do not inherit the marker the contract classes set on themselves, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is how
# a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

# This file builds its own names rather than importing the contract suite's: only `HistoryContract`
# is public there, `_history_changes` and `_workspace_files` being its private assembly.
LABEL: Final = RunLabel("acceptance")
CHILD: Final = Namespace("T-01")

# What the fixture repository's HEAD is put on, and what `default_ref` therefore owes. Named here
# rather than read back out of the adapter, so that this file asserts a fact about the repository it
# built instead of agreeing with whatever the implementation happens to answer.
TRUNK: Final = "main"

# A directory the fixture repository does not carry, so that a file appearing under it appeared
# because a test put it there.
WORK: Final = "agl-acceptance"

# How many lines a file written here has. Long, because rename detection is a similarity heuristic
# and a three-line file is one any heuristic is entitled to be unsure about.
_LINES: Final = 24


def _git(repository: Path, *argv: str) -> str:
    """Run git for the fixtures and the assertions. Synchronous on purpose: this is arrangement and
    observation, not the thing under test, and a test that built its repository through the adapter
    would be resting the arrangement on the behaviour it is about to check."""
    done = subprocess.run(
        ["git", *argv], cwd=repository, capture_output=True, text=True, check=True
    )
    return done.stdout


def _body(marker: str) -> str:
    """A file's contents, derived from `marker` so that two files differ on every line."""
    return "".join(f"{marker}: line {index} of {_LINES}.\n" for index in range(_LINES))


def _write(workspace: Workspace, name: str, text: str) -> None:
    """Put `text` at a repository-relative, forward-slash separated `name` inside `workspace`.

    Split rather than pasted on, because a `str` holding `/` is a path only on the platforms that
    spell it that way - and `FileChange.path` is the forward-slash form whatever the platform is.
    """
    path = workspace.path.joinpath(*name.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with two commits, on `main`, and no configuration from this machine.

    The `GIT_CONFIG_*` variables are what make this suite the same suite everywhere: a developer
    with `commit.gpgsign` on, a `core.hooksPath` of their own, or - most to the point here - a
    `diff.renames` or a `diff.external` of their own would otherwise be running different tests.
    They are set through `monkeypatch` so that the adapter, which inherits the environment and says
    so, sees them too, and the identity variables are set because `commit_all` deliberately invents
    none.

    Two commits, so that there is a state behind HEAD for a tag to be put on and for HEAD to be
    detached onto. It is at `tmp_path/repo` with the trees root as its sibling, which is the layout
    §3.9 draws.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "AGL contract")
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
def history(repository: Path) -> History:
    """The history the module-level tests drive. The contract suite has its own, on the class."""
    return GitHistory(repository)


@pytest.fixture
def provider(repository: Path, trees: TreesRoot) -> WorkspaceProvider:
    """The provider that records the states those tests ask about - over the same repository."""
    return GitWorkspaceProvider(repository, trees)


@pytest.fixture
def base(repository: Path) -> str:
    """The commit a run is cut from, resolved - the pinned `RunSpec.base_sha` shape of a base."""
    return _git(repository, "rev-parse", "HEAD").strip()


class TestGitHistory(HistoryContract):
    """The port in full, against real git.

    Three overrides and nothing else, which is what the suite asks for. All three depend on
    `repository`, which is how the `History`, the `WorkspaceProvider` and the base are guaranteed to
    be talking about one repository - the thing the suite names as gap 7 because nothing inside it
    can check that from outside.
    """

    @pytest.fixture
    def history(self, repository: Path) -> History:
        """The adapter, bound to that repository by construction, as the port requires."""
        return GitHistory(repository)

    @pytest.fixture
    def provider(self, repository: Path, trees: TreesRoot) -> WorkspaceProvider:
        """`commit_all` is the only member across both ports that records a state to ask about."""
        return GitWorkspaceProvider(repository, trees)

    @pytest.fixture
    def base(self, repository: Path) -> str:
        """A resolved commit id, deliberately not derived from `default_ref` - which is under test
        in this very suite, and would report one broken member as every test failing at once."""
        return _git(repository, "rev-parse", "HEAD").strip()


# --- The rename decision, and both sides of the threshold it costs ------------------------------


async def test_a_move_is_a_rename_even_where_the_repository_turned_detection_off(
    history: History, provider: WorkspaceProvider, repository: Path, base: str
) -> None:
    """The choice this adapter made, asserted where the contract suite is deliberately neutral.

    `_history_changes` accepts a move reported as one `RENAMED` or as the `DELETED` and `ADDED` pair
    it is made of, and says plainly what accepting either costs: against an implementation that does
    not detect renames, `ChangeKind.RENAMED` and `FileChange.previous_path` "go unexercised by this
    suite". This adapter detects them, so the suite's own rename branch runs - and what is left for
    this file is the half the suite cannot reach, which is that the answer does not depend on the
    machine it is asked on.

    `diff.renames = false` is a setting a person has for their own reading of `git diff` and is
    nothing to do with AGL. Asking through plumbing and naming `--find-renames` is what makes it
    irrelevant here; a porcelain `git diff` would quietly answer this test with a deletion and an
    addition, on that developer's machine only.
    """
    _git(repository, "config", "diff.renames", "false")
    workspace = await provider.open(LABEL, CHILD, base)
    _write(workspace, f"{WORK}/original.txt", _body("a file about to be moved"))
    before = await workspace.commit_all("the state before the move")
    (workspace.path / WORK / "original.txt").rename(workspace.path / WORK / "renamed.txt")
    after = await workspace.commit_all("the state after the move")

    changed = await history.changed_files(before, after)

    assert changed == (
        FileChange(f"{WORK}/renamed.txt", ChangeKind.RENAMED, f"{WORK}/original.txt"),
    ), (
        f"a file moved with its contents untouched was reported as {changed}. This adapter asks "
        f"for rename detection by name, so that what a repository's own diff configuration says "
        f"about renames cannot decide what a step reports having done"
    )
    patch = await history.diff(before, after)
    assert f"{WORK}/original.txt" in patch and f"{WORK}/renamed.txt" in patch, (
        "the patch does not name both ends of the move that the structured answer named. The two "
        "answer about one change, and a reviewer handed only one of the two names is reviewing "
        "something other than what happened"
    )


async def test_a_move_that_rewrites_the_file_is_the_deletion_and_the_addition_it_has_become(
    history: History, provider: WorkspaceProvider, base: str
) -> None:
    """The far side of the threshold detection costs, stated rather than left to be discovered.

    `--find-renames` with no number is git's default of fifty percent similarity. A file moved and
    rewritten past that point is two files as far as any heuristic can tell, and reporting it as a
    rename would mean claiming to know something nothing in the two states records. So the answer
    there is the pair - which is the *other* answer `_history_changes` accepts, arrived at honestly
    rather than by declining to look.

    Both paths are still named either way, which is the part the port's consumers actually depend
    on: a workflow asking whether a step touched anything under `docs/` gets the same answer on both
    sides of a threshold it has never heard of.
    """
    workspace = await provider.open(LABEL, CHILD, base)
    _write(workspace, f"{WORK}/before.txt", _body("the original contents, entirely"))
    before = await workspace.commit_all("the state before")
    (workspace.path / WORK / "before.txt").unlink()
    _write(workspace, f"{WORK}/after.txt", _body("nothing whatsoever in common"))
    after = await workspace.commit_all("the state after")

    changed = await history.changed_files(before, after)

    assert {change.path: change.kind for change in changed} == {
        f"{WORK}/after.txt": ChangeKind.ADDED,
        f"{WORK}/before.txt": ChangeKind.DELETED,
    }, (
        f"a move that rewrote the file was reported as {changed}. Below the similarity threshold "
        f"there is no move to see, and the deletion and the addition are the accurate account"
    )
    assert all(change.previous_path is None for change in changed), (
        "a change that is not a rename carries a previous path, which FileChange pairs to RENAMED "
        "in both directions precisely because the two disagreeing means it was assembled wrong"
    )


# --- What only a real repository shows about the reading -----------------------------------------


async def test_changed_files_reads_paths_that_no_quoting_would_have_survived(
    history: History, provider: WorkspaceProvider, base: str
) -> None:
    """Why the form asked for is `-z`, asserted with the names that make it matter.

    Without it git quotes any path holding a space or a character outside ASCII and hands the
    quoting back for somebody to undo - `"d/\\346\\227\\245.txt"` - so a repository with a Japanese
    filename in it becomes a bug in a framework that never meant to have an opinion about
    filenames. A NUL is the one byte a path cannot hold, which is what makes the parse exact
    instead of careful.

    The patch is not asserted here. git spells a path needing quotes in its own quoted form inside a
    `diff --git` header, and how a patch is written is explicitly not this port's - §3.7 hands the
    text over untouched precisely so that no implementation has to render its output into a taxonomy
    this port invented.
    """
    awkward = [
        f"{WORK}/a name with spaces.txt",
        f'{WORK}/quo"te and back\\slash.txt',
        f"{WORK}/日本語のファイル.txt",
    ]
    workspace = await provider.open(LABEL, CHILD, base)
    _write(workspace, f"{WORK}/ordinary.txt", _body("something to compare from"))
    before = await workspace.commit_all("the state before")
    for name in awkward:
        _write(workspace, name, _body(name))
    after = await workspace.commit_all("the state after")

    changed = await history.changed_files(before, after)

    assert {change.path for change in changed} == set(awkward), (
        f"the awkwardly named files came back as {[change.path for change in changed]}. A path is "
        f"barely constrained in what it may hold, and every one of these is a name a repository is "
        f"allowed to carry"
    )
    assert all(change.kind is ChangeKind.ADDED for change in changed)


async def test_a_file_that_became_a_symlink_is_a_modification(
    history: History, provider: WorkspaceProvider, base: str
) -> None:
    """git's `T`, and the one status whose mapping is a reading rather than a translation.

    The path is in both states and what is behind it differs, which is `MODIFIED` in every word the
    port has - and the alternative, reporting the deletion of a file and the addition of a link at
    one path, would be inventing a second entry for one name and counting a file twice.

    A mode-only change is git's `M` as well and is not built here: whether the filesystem under a
    test records an executable bit at all is not something a gate should depend on.
    """
    workspace = await provider.open(LABEL, CHILD, base)
    _write(workspace, f"{WORK}/target.txt", _body("what the link will point at"))
    _write(workspace, f"{WORK}/becomes-a-link.txt", _body("an ordinary file, for now"))
    before = await workspace.commit_all("the state before")
    link = workspace.path / WORK / "becomes-a-link.txt"
    link.unlink()
    link.symlink_to("target.txt")
    after = await workspace.commit_all("the state after")

    changed = await history.changed_files(before, after)

    assert changed == (FileChange(f"{WORK}/becomes-a-link.txt", ChangeKind.MODIFIED),), (
        f"a file that became a symlink was reported as {changed}. One path, present in both states "
        f"with different content behind it, is one entry"
    )


async def test_the_patch_is_a_unified_diff_that_the_repositorys_own_configuration_cannot_replace(
    history: History, provider: WorkspaceProvider, repository: Path, base: str
) -> None:
    """Gap 2: "a patch in a format no reviewer has seen passes all four" of the suite's assertions.

    It is a unified diff, and the two things that would stop it being one are settings a person is
    entitled to have. `diff.external` replaces git's diff machinery with a program of their choosing
    and `git diff` obediently prints whatever that program prints, which is not a patch and is not
    anything a review step could put in front of a model. Asking through plumbing is what makes it
    irrelevant - `diff-tree` is the interface git writes for programs, and it reads none of the
    porcelain diff configuration.

    What is asserted is only what makes it a patch: the header git writes for each file, a hunk, and
    the added and removed lines themselves. Not the prefixes, not the context width, not the
    abbreviation length - those are format, and format is deliberately not this port's.
    """
    _git(repository, "config", "diff.external", "/bin/echo")
    _git(repository, "config", "color.diff", "always")
    workspace = await provider.open(LABEL, CHILD, base)
    _write(workspace, f"{WORK}/reviewed.txt", _body("the state a reviewer reads from"))
    before = await workspace.commit_all("the state before")
    _write(workspace, f"{WORK}/reviewed.txt", _body("the state a reviewer reads to"))
    after = await workspace.commit_all("the state after")

    patch = await history.diff(before, after)

    assert patch.startswith("diff --git "), (
        f"the patch begins {patch[:80]!r}. A repository whose owner prefers another diff program "
        f"still owes AGL a unified patch: this is what a review step puts in a prompt, and a "
        f"model that has seen an enormous amount of unified diffs has seen none of that"
    )
    assert "@@ " in patch, "a patch with no hunk in it shows a reviewer which files, and not what"
    assert "-the state a reviewer reads from" in patch
    assert "+the state a reviewer reads to" in patch
    assert "\x1b[" not in patch, (
        "there are terminal colour escapes in the patch. It is a string handed to a model as often "
        "as to a person, and `color.diff = always` is an ordinary thing for a person to have set"
    )


# --- What the suite says outright it cannot reach -------------------------------------------------


async def test_contains_is_true_once_a_line_of_work_has_been_merged_into_the_base(
    history: History, provider: WorkspaceProvider, repository: Path, base: str
) -> None:
    """Gap 3: the shape `clear` actually meets, which the suite has no way to build.

    §3.10 deletes a run's own line of work only if the base ref already holds it, and in life that
    means merged. The suite can only commit in one place, so the ancestry it asserts is the kind
    that comes from committing - a true case, a false case, a reflexive one and a divergence - and
    it says plainly that "the shape `clear` meets after a successful merge is not built here".
    Landing it takes one raw git command, and the costs on either side of the answer are why it is
    worth the command: a retained name is a stale ref, and a deleted one is the entire run.

    `--no-ff` on purpose. A fast-forward would leave the merged state *equal* to the line of work,
    where an implementation answering on equality rather than on reachability would pass; a merge
    commit puts the work strictly behind the base and asks the real question.
    """
    workspace = await provider.open(LABEL, CHILD, base)
    _write(workspace, f"{WORK}/landed.txt", _body("work that is about to be merged"))
    head = await workspace.commit_all("work that is about to be merged")
    assert await history.contains(head, base) is False, (
        "the base already contains work that has not been merged into it, so this test has nothing "
        "left to prove by merging it"
    )

    _git(repository, "merge", "--no-ff", "-m", "landed", worktree_branch(LABEL, CHILD))
    landed = _git(repository, "rev-parse", "HEAD").strip()

    assert landed != head, "a --no-ff merge did not make a commit of its own"
    assert await history.contains(head, landed) is True, (
        "a line of work merged into the base is reported as not contained in it, so §3.10's "
        "`clear` would keep every run's branch forever - the answer this member exists to give"
    )
    assert await history.contains(landed, head) is False, (
        "ancestry has a direction, and the merge commit is not inside the work it merged"
    )


async def test_a_repository_git_cannot_read_is_upstream_unavailable_and_not_a_missing_ref(
    tmp_path: Path
) -> None:
    """Gap 4: "nothing here can make a repository unreachable, and inventing a member that could
    would be inventing a port".

    The port names both refusals in one sentence - `NotFoundError` for a ref this repository does
    not hold, `UpstreamUnavailable` when the repository itself cannot be reached - and the
    difference is what a person does next. Exit 3 says the name was wrong; exit 6 says nothing was
    read at all and the same call may well succeed later. An adapter that reported the second as the
    first would send somebody looking for a typo in a ref that is perfectly fine.

    This is `_runner.py`'s classification arriving intact rather than anything this module does:
    every call here declares `NotFoundError` as what a *refusal* means, and a directory with no
    repository in it is not a refusal.
    """
    nowhere = tmp_path / "not-a-repository"
    nowhere.mkdir()
    history = GitHistory(nowhere)

    with pytest.raises(UpstreamUnavailable):
        await history.default_ref()
    with pytest.raises(UpstreamUnavailable):
        await history.resolve("HEAD")


async def test_default_ref_is_the_full_ref_of_the_branch_this_repositorys_head_is_on(
    history: History, repository: Path
) -> None:
    """Gap 6: "there is no second source for what the default *is*". Out here the fixture is one.

    §3.9 spells the default "the repo's default branch", and the branch HEAD names is the only
    default branch a repository records about itself - `refs/remotes/origin/HEAD` is a cached copy
    of a second repository's answer, which this port declines even the parameter to ask about.

    **In full, and that is the load-bearing half.** `rev-parse` resolves `refs/tags/<name>` before
    `refs/heads/<name>`, so a repository carrying a tag and a branch of one name answers a shortened
    `main` with the tag - and a run would silently start from a state nobody chose, days after
    somebody tagged a release. Handing on the whole ref `symbolic-ref` answered is what keeps
    `default_ref` and `resolve` agreeing about which of the two was meant, and the port anticipated
    the `/` that costs: this is a ref expression and not one of `ids.py`'s single-segment names.
    """
    assert await history.default_ref() == f"refs/heads/{TRUNK}", (
        "default_ref did not name the branch this repository's HEAD is on, in the full form that "
        "cannot be confused with anything else carrying that name"
    )

    _git(repository, "tag", TRUNK, "HEAD~1")

    assert await history.resolve(await history.default_ref()) == _git(
        repository, "rev-parse", f"refs/heads/{TRUNK}"
    ).strip(), (
        "with a tag and a branch sharing one name, the default resolved to something other than "
        "the branch HEAD is on. Every run pins this as `base_sha` and lives on the pin for hours"
    )


async def test_default_ref_refuses_a_detached_head_in_words_that_say_what_to_do_instead(
    history: History, repository: Path
) -> None:
    """A repository sitting on a state rather than on a line of work has no default to offer.

    `NotFoundError`, so the person who typed `agl run` gets exit 3 - the class for something
    well-formed this repository does not have - and a sentence naming the way out. §1.5's charge was
    that exit codes meant nothing and errors were not a hierarchy; the value of the class here is
    lost if the message is still git's fact about a data structure ("ref HEAD is not a symbolic
    ref"), which tells somebody who has never detached a HEAD on purpose exactly nothing.
    """
    _git(repository, "checkout", "-q", "--detach", "HEAD")

    with pytest.raises(NotFoundError) as refused:
        await history.default_ref()

    assert "--from" in str(refused.value), (
        "the refusal does not name the flag that gets past it, which is the one thing a person "
        "needs in order to start their run anyway"
    )
