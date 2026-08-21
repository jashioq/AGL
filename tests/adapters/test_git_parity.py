"""The anti-drift guard: the three git adapters and the three fakes held to each other, not to the
ports.

`tests/contracts/` holds both implementations to everything the three ports *say*. This file holds
them to everything the ports leave open - and that is where a fake drifts, because a clause nobody
wrote down is a clause no suite can assert. §1.9's rule is that a fake is a product feature:
`--dry-run` and plan target #8 ("every command runs end-to-end on fakes alone - no network, no
git") run on `FakeWorkspaceProvider`, `FakeHistory` and `FakeIntegrator`, so a fake that combines
what git would reject turns a green all-fakes run into a real run that stops at a conflict screen,
with the difference invisible until the day somebody drops the `--dry-run`.

Every test below asks both implementations the same question, in the same order, over two
repositories seeded with the same files, and asserts they answered alike. `_alike` is what makes
that one line: it runs a scenario against each bundle, compares the answers, and hands them both
back so a test can go on to check something the comparison cannot see - two implementations
agreeing is not by itself two implementations being right.

**Commit ids are deliberately never compared.** git's are forty characters of sha1 over its own
object format and the fake's are sixty-four of sha256 over its own, and the ports are explicit that
an id is opaque and produced by the implementation that consumes it. What is compared is the shape
both must have, and everything an id is *used* for: ancestry, what changed between two of them,
whether work landed.

## Conflict detection is the reason this file exists

A fake that never conflicts makes a merge train look clean that git will reject. A fake that
conflicts on any two changes to one file makes a workflow's conflict screen fire on work that
would have combined. Both are worse than useless, so four tests hold the two implementations to one
answer over the same four situations: two children touching different files, two children editing
opposite ends of one file, two children editing *neighbouring lines* of one file, and two children
writing incompatible content to one file. The first three separate a three-way merge from a
file-level comparison, and the third separates one from a merge that has the right verdict at the
wrong granularity - which is the failure a hand-rolled merge actually has.

## Where the two deliberately disagree

A divergence papered over is a divergence discovered later, at the worst moment, so each one below
is pinned as a test of its own. **The list is closed**: a seventh divergence appearing is a failing
test here rather than a discovery in production.

  1. **What `.gitignore` covers.** The real adapter stages with `add --all`, which git filters
     through the repository's ignore rules, and cleans with `-ffd` and no `-x`, which leaves them
     alone; the fake records a checkout's files and lays a state back out over them, and has no
     ignore rules because ignore rules are one program's file format. Parsing one would put that
     program back inside the module whose whole claim is that there is none of it.
  2. **A move that also edits.** 5.3 chose rename detection and pays git's default fifty-percent
     similarity for it. The fake detects a move whose contents are byte-identical and nothing
     else, because a second similarity heuristic beside git's would agree in the easy cases and
     disagree near a boundary that moves with the file. Both ends of the band are asserted to
     agree - a pure move is a `RENAMED` from both, a move that rewrites past the threshold is the
     `DELETED` and `ADDED` pair from both - and the band between them is this divergence.
  3. **What counts as resolving a collision.** git records unresolvedness in its index and takes
     `git add` as the word that it is over, so an edited-but-unstaged file is still a conflict.
     There is no index here and no staging verb on the `Integrator` port, so the fake asks the
     file whether the markers it wrote are still in it. A person editing the file and not staging
     it is landed by one and refused by the other.
  4. **A file one side moved and the other edited.** git's `ort` strategy detects renames during
     the merge and applies the edit to the moved path; the fake merges path by path, so it sees
     one side delete a file the other changed and reports the collision. It is the conservative
     direction - the fake conflicts where git combines - and closing it would mean rename
     detection inside the merge, which is the same heuristic as divergence 2 in a harder place.
  5. **One state, one identity.** The fake addresses a state by the hash of its contents, its
     parents and its message, which is what `HistoryContract` says an implementation built on
     content hashes gets for free; git's commit object also carries a timestamp, so recording the
     same content twice from one parent gives one id here and two there.
  6. **A file's mode, and a symlink.** The fake records a regular file's bytes. git records the
     executable bit and records a symlink as a thing of its own, so `chmod +x` is a modification
     to one implementation and nothing at all to the other.

Divergences 1, 4 and 6 are one family - git's model of a working tree is richer than "the bytes of
the regular files in it" - and 2, 3 and 5 are the three places the fake declines to reproduce a
heuristic, an index or a clock it does not have.

Resource limits are out of scope for the word "divergence" here: a full disk, a path longer than
PATH_MAX, a repository the user may not write to. Those are the world's answers rather than the
implementations', and only one of the two is standing in the world at all.

Named `test_git_parity.py`: `tests/` carries no `__init__.py` - see `tests/conftest.py` for why -
so pytest's module names are the bare filenames and every one of them has to be unique.
"""

import subprocess
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.git.fake import (
    FakeHistory,
    FakeIntegrator,
    FakeRepository,
    FakeWorkspaceProvider,
)
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.ports.errors import (
    AglError,
    ConflictError,
    InternalError,
    NotFoundError,
    UpstreamUnexpected,
)
from agl.ports.history import ChangeKind, FileChange, History
from agl.ports.ids import Namespace, RunLabel
from agl.ports.integration import Integrator
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace, WorkspaceProvider

# Module-level tests inherit no marker from anywhere, and `asyncio_mode = "strict"` turns a missing
# one into a test pytest silently skips - which is how a parity file passes against one adapter.
pytestmark = pytest.mark.asyncio

# The two implementations, by name, so a failure says which one answered differently and so the
# six divergence tests can address one of them without unpacking a tuple in the right order.
_GIT: Final = "git"
_FAKE: Final = "fake"

# This file builds its own names rather than importing the contract suites': only the three
# contract classes are public there, the `_workspace_*` and `_integration_*` modules being their
# private assembly.
LABEL: Final = RunLabel("parity")
CHILD: Final = Namespace("T-01")
SIBLING: Final = Namespace("T-02")
TRUNK: Final = "main"

# One directory of this file's own, so that a file appearing under it appeared because a test put
# it there rather than because a repository already held it.
UNDER: Final = "agl-parity"
SOURCE: Final = f"{UNDER}/source.txt"
ALPHA: Final = f"{UNDER}/alpha.txt"
BETA: Final = f"{UNDER}/beta.txt"
GAMMA: Final = f"{UNDER}/gamma.txt"
CONTESTED: Final = f"{UNDER}/contested.txt"
SCRATCH: Final = f"{UNDER}/scratch.txt"
CACHED: Final = f"{UNDER}/cache/notes.txt"
MOVED_TO: Final = f"{UNDER}/moved.txt"

# What `.gitignore` covers, and a file under it. Divergence 1 is the only test that touches these.
IGNORE_FILE: Final = ".gitignore"
IGNORED_DIR: Final = "build-output"
IGNORED: Final = f"{IGNORED_DIR}/artifact.bin"

# How many lines a file this file writes has. Long, because rename detection is a similarity
# heuristic wherever it exists, and a three-line file moved unchanged is one any heuristic is
# entitled to be unsure about - and because two edits far apart in one file is the situation
# divergence-free merging has to get right.
_LINES: Final = 24

# Something well-formed that neither repository holds, in both of the shapes a member takes.
ABSENT_REF: Final = "agl-parity-names-no-such-thing"
ABSENT_ID: Final = "dead" * 10


def _body(marker: str) -> bytes:
    """A file's contents, derived from `marker` so that two files differ on every line."""
    return "".join(f"{marker}: line {index} of {_LINES}.\n" for index in range(_LINES)).encode()


def _edited(marker: str, at: int, replacement: str) -> bytes:
    """`_body(marker)` with one line replaced - one small change in a long file."""
    lines = _body(marker).decode().splitlines()
    lines[at] = replacement
    return ("\n".join(lines) + "\n").encode()


# What both repositories start holding, so that every scenario below begins from one state.
SEED: Final[Mapping[str, bytes]] = {
    SOURCE: _body("the state a run is cut from"),
    IGNORE_FILE: f"{IGNORED_DIR}/\n".encode(),
}


@dataclass(frozen=True, slots=True)
class _Bundle:
    """The three ports over one repository, and the state a run in it is cut from.

    What `config/container.py` assembles, in miniature and twice over: the point of this file is
    that a scenario written against these four names runs unchanged against either.
    """

    provider: WorkspaceProvider
    history: History
    integrator: Integrator
    base: str


def _git(repository: Path, *argv: str) -> str:
    """Run git for the fixtures and for the two assertions only git can settle.

    Synchronous on purpose: this is arrangement and observation rather than the thing under test,
    and a fixture built through the adapter would rest the arrangement on the behaviour it is
    about to check.
    """
    done = subprocess.run(
        ["git", *argv], cwd=repository, capture_output=True, text=True, check=True
    )
    return done.stdout


@pytest.fixture
def pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mapping[str, _Bundle]:
    """Both implementations, over two repositories seeded with the same files, on the same base.

    The `GIT_CONFIG_*` variables are what make this file the same file everywhere: a developer with
    `diff.renames`, `merge.verifySignatures`, `commit.gpgsign` or `core.hooksPath` of their own
    would otherwise be comparing the fake against a differently configured git. They are set
    through `monkeypatch` so that the adapter, which inherits the environment and says so, sees
    them too, and the identity variables are set because a commit needs an author and this package
    invents none.

    The two roots are siblings under one `tmp_path` and the layout is §3.9's - a repository, and a
    trees root beside it - for each. The two bases are two different strings naming two states with
    identical contents, which is exactly the relationship the ports promise and the reason nothing
    below compares them.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "AGL parity")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "agl@example.invalid")

    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", TRUNK)
    for name, content in SEED.items():
        at = work.joinpath(*name.split("/"))
        at.parent.mkdir(parents=True, exist_ok=True)
        at.write_bytes(content)
    _git(work, "add", "--all")
    _git(work, "commit", "-q", "-m", "the state a run is cut from")

    memory = FakeRepository(SEED, default_branch=TRUNK)
    return {
        _GIT: _Bundle(
            GitWorkspaceProvider(work, TreesRoot(tmp_path / "git-trees")),
            GitHistory(work),
            GitIntegrator(work),
            _git(work, "rev-parse", "HEAD").strip(),
        ),
        _FAKE: _Bundle(
            FakeWorkspaceProvider(memory, TreesRoot(tmp_path / "fake-trees")),
            FakeHistory(memory),
            FakeIntegrator(memory),
            memory.resolve(memory.default_ref),
        ),
    }


async def _alike[T](
    pair: Mapping[str, _Bundle], ask: Callable[[_Bundle], Awaitable[T]]
) -> dict[str, T]:
    """Run one scenario against both bundles, assert they answered alike, and hand both back.

    Both answers and not one, because equality is where this helper stops being able to see: a
    caller that cares about the type of what came back, or about a value the comparison could not
    reach, checks each answer itself.
    """
    answers = {name: await ask(bundle) for name, bundle in pair.items()}
    reference = answers[_GIT]
    for name, answer in answers.items():
        assert answer == reference, (
            f"the {name} implementation answered {answer!r} where git answered {reference!r}: the "
            f"two implementations of these ports have drifted apart somewhere the ports are silent"
        )
    return answers


async def _refused[T](
    pair: Mapping[str, _Bundle], ask: Callable[[_Bundle], Awaitable[T]]
) -> type[AglError]:
    """Assert both refuse the same call with the same `AglError` subclass, and name it.

    Only `AglError` is caught, on purpose: an adapter translates at its boundary and nothing that
    is not an `AglError` may leave one, so anything else propagating out of here is the failure it
    looks like rather than a refusal this helper should be comparing.
    """
    raised: dict[str, type[AglError] | None] = {}
    for name, bundle in pair.items():
        try:
            await ask(bundle)
        except AglError as error:
            raised[name] = type(error)
        else:
            raised[name] = None
    distinct = set(raised.values())
    assert len(distinct) == 1, (
        f"the two implementations disagreed about this call: {raised} - a fake that accepts what "
        f"git refuses turns a green --dry-run into a real run that stops"
    )
    refusal = distinct.pop()
    assert refusal is not None, "both implementations accepted a call this test expected refused"
    return refusal


def _put(workspace: Workspace, name: str, content: bytes) -> None:
    """Put `content` at a repository-relative, forward-slash separated `name` in a checkout.

    Split rather than pasted on, because a `str` holding `/` is a path only on the platforms that
    spell it that way - and these names keep one spelling on every platform by design.
    """
    at = workspace.path.joinpath(*name.split("/"))
    at.parent.mkdir(parents=True, exist_ok=True)
    at.write_bytes(content)


def _get(workspace: Workspace, name: str) -> bytes | None:
    """What is at `name`, or `None` if nothing is - which is what "it was removed" looks like."""
    at = workspace.path.joinpath(*name.split("/"))
    return at.read_bytes() if at.is_file() else None


def _drop(workspace: Workspace, name: str) -> None:
    """Take `name` away, which is how a `DELETED` change gets made."""
    workspace.path.joinpath(*name.split("/")).unlink()


async def _three(bundle: _Bundle) -> tuple[Workspace, Workspace, Workspace]:
    """§3.4's merge train: a run's own workspace, and two children of it cut from one base."""
    return (
        await bundle.provider.open(LABEL, None, bundle.base),
        await bundle.provider.open(LABEL, CHILD, bundle.base),
        await bundle.provider.open(LABEL, SIBLING, bundle.base),
    )


def _reported(changes: tuple[FileChange, ...]) -> tuple[tuple[str, str, str | None], ...]:
    """`changed_files`' answer as something two implementations can be compared on.

    Sorted, because the port declines to promise an order and a file that compared sequences would
    be comparing one tool's sort against another's rather than comparing the two answers.
    """
    return tuple(
        sorted((change.path, str(change.kind), change.previous_path) for change in changes)
    )


# --- Conflict detection: the three situations that have to be told apart ------------------------


async def test_two_children_that_changed_different_files_combine_on_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """The case a fake must never get wrong in the direction of conflicting.

    Two agents editing two files is the ordinary afternoon the whole worktree design exists for,
    and an implementation that reported a collision here would put a workflow's conflict screen in
    front of a person on every run of `split`. Both landings are asserted, and so is what the
    target's checkout holds afterwards: the build gate runs in that tree, and a landing that moved
    a ref without combining the files is a gate deciding about nothing.
    """

    async def scenario(bundle: _Bundle) -> tuple[bool, bool, bytes | None, bytes | None]:
        target, child, sibling = await _three(bundle)
        _put(child, ALPHA, _body("the child's own work"))
        await child.commit_all("the child's own work")
        _put(sibling, BETA, _body("the sibling's own work"))
        await sibling.commit_all("the sibling's own work")
        first = await bundle.integrator.land(child, target)
        second = await bundle.integrator.land(sibling, target)
        return second.conflicted, first.conflicted, _get(target, ALPHA), _get(target, BETA)

    for answer in (await _alike(pair, scenario)).values():
        assert answer == (
            False,
            False,
            _body("the child's own work"),
            _body("the sibling's own work"),
        ), "two children that touched different files did not both land, with both files in"


async def test_two_children_that_edited_opposite_ends_of_one_file_combine_on_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """The case that separates a three-way merge from a file-level comparison.

    One file, two edits twenty lines apart, neither of them anywhere near the other. An
    implementation that treats "both sides changed this file" as a collision passes every test
    where the two children touched different files and fails this one - and it is the failure that
    makes a fake's conflict screen fire on work git would have combined without comment.

    The combined file is compared as a whole rather than searched for each edit, because an
    implementation that took one side wholesale would satisfy a search for that side's line.
    """
    first_line = "the first line, as the child rewrote it"
    last_line = "the last line, as the sibling rewrote it"

    async def scenario(bundle: _Bundle) -> tuple[bool, bytes | None]:
        target, child, sibling = await _three(bundle)
        _put(child, SOURCE, _edited("the state a run is cut from", 0, first_line))
        await child.commit_all("the child's own work")
        _put(sibling, SOURCE, _edited("the state a run is cut from", _LINES - 1, last_line))
        await sibling.commit_all("the sibling's own work")
        await bundle.integrator.land(child, target)
        second = await bundle.integrator.land(sibling, target)
        return second.conflicted, _get(target, SOURCE)

    both = _body("the state a run is cut from").decode().splitlines()
    both[0], both[-1] = first_line, last_line
    for answer in (await _alike(pair, scenario)).values():
        assert answer == (False, ("\n".join(both) + "\n").encode()), (
            "two edits twenty lines apart in one file did not combine into one file holding both"
        )


async def test_two_children_that_wrote_incompatible_content_to_one_file_collide_on_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """The case a fake must never get wrong in the direction of combining.

    Two children each create one path, with contents sharing not one line, and neither of them
    existed in the state both were cut from. There is no combination of those two states that is
    anybody's answer, so an implementation that produced one resolved by guessing - which is the
    one thing §3.4 says a conflict may never be, and the way a merge train looks clean on fakes and
    is rejected in anger.

    `Conflict.paths` is compared whole rather than searched. The port lets an implementation report
    `()` when it cannot enumerate, and both of these can, so what is pinned is that they enumerate
    the same thing: a workflow's conflict screen sends a person to those files.
    """

    async def scenario(bundle: _Bundle) -> tuple[bool, bool, tuple[str, ...], bytes | None]:
        target, child, sibling = await _three(bundle)
        _put(child, CONTESTED, _body("the child's own work"))
        await child.commit_all("the child's own work")
        _put(sibling, CONTESTED, _body("the sibling's own work, sharing not one line"))
        await sibling.commit_all("the sibling's own work")
        first = await bundle.integrator.land(child, target)
        second = await bundle.integrator.land(sibling, target)
        conflict = second.conflict
        paths = conflict.paths if conflict is not None else ()
        await bundle.integrator.abort(target)
        return first.conflicted, second.conflicted, paths, _get(target, CONTESTED)

    for answer in (await _alike(pair, scenario)).values():
        assert answer == (False, True, (CONTESTED,), _body("the child's own work")), (
            "two children creating one file with contents that agree nowhere did not collide over "
            "exactly that file and leave the first child's work standing after the release"
        )


async def test_two_children_that_edited_neighbouring_lines_of_one_file_collide_on_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """The granularity of a collision, which is the half a right verdict can still get wrong.

    One line apart the two edits combine, which the test above asserts; with nothing at all
    between them there is one stretch of the original that both sides rewrote, and neither side
    can be given way to without discarding the other's line. git says so and so does this, and the
    agreement is worth pinning separately: an implementation that got the verdict right at the
    wrong granularity - one that conflicted on the whole file, or one that stitched both edits
    together and called it a merge - would pass every test above and put a `--dry-run` and a real
    run on two different sides of the ordinary case.
    """

    async def scenario(bundle: _Bundle) -> bool:
        target, child, sibling = await _three(bundle)
        _put(child, SOURCE, _edited("the state a run is cut from", 3, "the child's line"))
        await child.commit_all("the child's own work")
        _put(sibling, SOURCE, _edited("the state a run is cut from", 4, "the sibling's line"))
        await sibling.commit_all("the sibling's own work")
        await bundle.integrator.land(child, target)
        collided = (await bundle.integrator.land(sibling, target)).conflicted
        await bundle.integrator.abort(target)
        return collided

    for answer in (await _alike(pair, scenario)).values():
        assert answer is True, (
            "two edits with not one line between them did not collide. There is one stretch of "
            "the original that both sides rewrote, and combining it means choosing whose line to "
            "throw away - which is the guess §3.4 says a conflict may never be"
        )


# --- What both answer alike ----------------------------------------------------------------------


async def test_changed_files_reports_the_same_kinds_for_the_same_edits(
    pair: Mapping[str, _Bundle],
) -> None:
    """Three of the four kinds, in one answer, out of both implementations.

    Asserted as a whole rather than one at a time, because the failures worth catching are
    omissions and blurrings: an implementation reporting the deleted file as modified, or
    answering only about files that still exist, produces an answer whose every entry looks
    reasonable on its own. The reverse direction is asked as well, since `ADDED` and `DELETED` are
    not properties of a file but of a direction, and an implementation that normalised its two
    arguments would answer the same thing twice.
    """

    async def scenario(bundle: _Bundle) -> tuple[tuple[tuple[str, str, str | None], ...], ...]:
        workspace = await bundle.provider.open(LABEL, CHILD, bundle.base)
        _put(workspace, ALPHA, _body("alpha, as first recorded"))
        _put(workspace, GAMMA, _body("gamma, which does not survive"))
        before = await workspace.commit_all("the state to be asked about from")
        _put(workspace, ALPHA, _body("alpha, edited"))
        _drop(workspace, GAMMA)
        _put(workspace, BETA, _body("beta, which was not there before"))
        after = await workspace.commit_all("the state to be asked about to")
        return (
            _reported(await bundle.history.changed_files(before, after)),
            _reported(await bundle.history.changed_files(after, before)),
        )

    for answer in (await _alike(pair, scenario)).values():
        assert answer == (
            (
                (ALPHA, ChangeKind.MODIFIED, None),
                (BETA, ChangeKind.ADDED, None),
                (GAMMA, ChangeKind.DELETED, None),
            ),
            (
                (ALPHA, ChangeKind.MODIFIED, None),
                (BETA, ChangeKind.DELETED, None),
                (GAMMA, ChangeKind.ADDED, None),
            ),
        )


async def test_a_move_is_a_rename_from_both_and_a_rewritten_move_is_a_pair_from_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """Both ends of the rename band, which is what makes divergence 2 the narrow thing it is.

    5.3 chose detection, so a byte-identical move comes back as one `RENAMED` carrying the name it
    came from, and a move that also rewrites the file past git's default fifty-percent similarity
    comes back as the `DELETED` and `ADDED` pair it has become. Those are the two answers the
    framework will actually meet, and they have to be the same answer from both implementations or
    a workflow branching on `changed_files` branches differently on fakes.

    The band between them - a move that edits a little - is where the two part company, and it is
    pinned as a divergence of its own below rather than smuggled in here.
    """

    async def scenario(bundle: _Bundle) -> tuple[tuple[tuple[str, str, str | None], ...], ...]:
        workspace = await bundle.provider.open(LABEL, CHILD, bundle.base)
        _put(workspace, ALPHA, _body("a file that is about to be moved"))
        before = await workspace.commit_all("the state before the move")
        _drop(workspace, ALPHA)
        _put(workspace, MOVED_TO, _body("a file that is about to be moved"))
        moved = await workspace.commit_all("the state after the move")
        await workspace.restore(before)
        _drop(workspace, ALPHA)
        _put(workspace, MOVED_TO, _body("nothing whatever of what was in it before"))
        rewritten = await workspace.commit_all("the state after the move and the rewrite")
        return (
            _reported(await bundle.history.changed_files(before, moved)),
            _reported(await bundle.history.changed_files(before, rewritten)),
        )

    for answer in (await _alike(pair, scenario)).values():
        assert answer == (
            ((MOVED_TO, ChangeKind.RENAMED, ALPHA),),
            ((ALPHA, ChangeKind.DELETED, None), (MOVED_TO, ChangeKind.ADDED, None)),
        ), "the two ends of the rename band are not the same answer from both implementations"


async def test_contains_agrees_including_the_reflexive_case(
    pair: Mapping[str, _Bundle],
) -> None:
    """`clear`'s one question, in the four shapes it meets (§3.10).

    The costs are asymmetric - a retained name is a stale ref, a deleted one is the entire run - so
    an implementation answering differently from the other decides differently between tidying up
    and destroying work. The reflexive case is the port's own reading rather than a fact borrowed
    from git: a run whose workflow committed nothing sits exactly at its base, and `clear` tidies
    it only if a state is already inside itself.

    `is True` and `is False` are not spelled here because the answers are compared as a tuple; the
    contract suite pins the type of each one against each implementation separately.
    """

    async def scenario(bundle: _Bundle) -> tuple[bool, ...]:
        child = await bundle.provider.open(LABEL, CHILD, bundle.base)
        sibling = await bundle.provider.open(LABEL, SIBLING, bundle.base)
        start = await child.head()
        _put(child, ALPHA, _body("the child's own work"))
        first = await child.commit_all("the child's own work")
        _put(sibling, BETA, _body("the sibling's own work"))
        second = await sibling.commit_all("the sibling's own work")
        return (
            await bundle.history.contains(start, first),
            await bundle.history.contains(first, start),
            await bundle.history.contains(first, second),
            await bundle.history.contains(second, first),
            await bundle.history.contains(first, first),
            await bundle.history.contains(start, start),
        )

    for answer in (await _alike(pair, scenario)).values():
        assert answer == (True, False, False, False, True, True)


async def test_restore_removes_untracked_leavings_on_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """§3.3's "moving the head alone is not enough", asked of both.

    The two leavings are different shapes on purpose - one beside the recorded files and one
    inside a directory that was not there either - because an implementation that removes
    untracked files without descending into new directories leaves the second behind, which is the
    whole difference between one tool's `clean -f` and `clean -fd`. The directory itself is asked
    about too, since a directory nothing recorded is something that was not in the head.
    """

    async def scenario(bundle: _Bundle) -> tuple[bytes | None, bytes | None, bool, bool]:
        workspace = await bundle.provider.open(LABEL, CHILD, bundle.base)
        _put(workspace, ALPHA, _body("as recorded"))
        head = await workspace.commit_all("the state to come back to")
        _put(workspace, ALPHA, _body("edited by a step that then crashed"))
        _put(workspace, SCRATCH, _body("a reviewer's scratch file"))
        _put(workspace, CACHED, _body("an agent's cache directory"))
        await workspace.restore(head)
        return (
            _get(workspace, ALPHA),
            _get(workspace, SCRATCH),
            workspace.path.joinpath(UNDER, "cache").is_dir(),
            await workspace.head() == head,
        )

    for answer in (await _alike(pair, scenario)).values():
        assert answer == (_body("as recorded"), None, False, True)


async def test_reopening_carries_uncommitted_work_on_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """The clause §3.6's replay is built on, and the one a careless implementation passes weakly.

    An implementation that quietly re-provisions a clean checkout passes "opening twice does not
    raise", passes a comparison of paths, and destroys a resume: replay would find no entry for
    the crashed step, reset to the last recorded head, and everything the crashed attempt had done
    would already be gone. So what is compared is a file nobody committed.

    The branch and the path are compared too, and they are compared *between* the two
    implementations rather than to a name recomputed here. Both derive every name from
    `tree_layout`, which is what makes a workflow's `--dry-run` and its real run put their work in
    the same place under the same name.
    """

    async def scenario(bundle: _Bundle) -> tuple[str, str, bytes | None, bytes | None, bool]:
        first = await bundle.provider.open(LABEL, CHILD, bundle.base)
        _put(first, ALPHA, _body("committed by the first attempt"))
        committed = await first.commit_all("the first attempt")
        _put(first, ALPHA, _body("edited by the attempt that then crashed"))
        _put(first, SCRATCH, _body("left behind by the attempt that then crashed"))
        again = await bundle.provider.open(LABEL, CHILD, bundle.base)
        root = first.path.parent.parent
        return (
            again.branch,
            str(again.path.relative_to(root)),
            _get(again, ALPHA),
            _get(again, SCRATCH),
            await again.head() == committed,
        )

    for answer in (await _alike(pair, scenario)).values():
        assert answer == (
            "agl/_work/parity/T-01",
            str(Path(str(LABEL), str(CHILD))),
            _body("edited by the attempt that then crashed"),
            _body("left behind by the attempt that then crashed"),
            True,
        )


async def test_default_ref_and_the_shape_of_a_resolved_id_agree(
    pair: Mapping[str, _Bundle],
) -> None:
    """The one shape the ports do constrain, and the one name both must answer with.

    `HistoryContract` pins that `resolve` answers forty or sixty-four characters of lowercase
    hexadecimal, because `RunSpec._check_sha` refuses an abbreviation. The two implementations
    answer with different lengths - a sha1 object name and a sha256 content hash - so what is
    compared is the shape rather than the value, and the value is deliberately compared nowhere in
    this file.

    `default_ref` *is* compared, and in full: the real adapter answers `refs/heads/main` rather
    than `main` because `rev-parse` would otherwise resolve a tag of that name first, and a fake
    answering the short form would give a `--dry-run` a different starting point from the run.
    """
    for answer in (await _alike(pair, lambda bundle: bundle.history.default_ref())).values():
        assert answer == f"refs/heads/{TRUNK}"

    for name, bundle in pair.items():
        resolved = await bundle.history.resolve(await bundle.history.default_ref())
        assert len(resolved) in {40, 64}, f"the {name} implementation answered {resolved!r}"
        assert set(resolved) <= set("0123456789abcdef"), f"{name} answered {resolved!r}"
        assert resolved == bundle.base, f"{name} resolved its default to something else"


# --- What both refuse, and with which class -------------------------------------------------------


async def test_a_ref_or_an_id_neither_repository_holds_is_refused_alike(
    pair: Mapping[str, _Bundle],
) -> None:
    """`NotFoundError` from every member that takes a name, which is the port's own clause.

    `changed_files` is the sharp one: "nothing differs from a state that does not exist" is a
    plausible-looking answer and a lie, and an implementation that gave it would let a workflow
    branch on an empty answer to a question nobody asked. The id is well-formed on purpose - an
    implementation refusing it for its shape rather than for its absence would pass a test built
    on a malformed one without ever looking.
    """

    async def head(bundle: _Bundle) -> str:
        return await (await bundle.provider.open(LABEL, CHILD, bundle.base)).head()

    assert await _refused(pair, lambda b: b.history.resolve(ABSENT_REF)) is NotFoundError
    assert await _refused(pair, lambda b: b.history.resolve(ABSENT_ID)) is NotFoundError
    assert (
        await _refused(pair, lambda b: b.history.contains(ABSENT_ID, ABSENT_ID)) is NotFoundError
    )

    async def compared(bundle: _Bundle) -> object:
        return await bundle.history.changed_files(ABSENT_ID, await head(bundle))

    async def read(bundle: _Bundle) -> str:
        return await bundle.history.diff(await head(bundle), ABSENT_ID)

    assert await _refused(pair, compared) is NotFoundError
    assert await _refused(pair, read) is NotFoundError


async def test_the_same_bad_provisioning_is_refused_with_the_same_class_by_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """Three refusals `WorkspaceProvider` describes only in its own vocabulary.

    A base that names nothing is `ConflictError` and not `NotFoundError`, which is not this file's
    taste: `GitWorkspaceProvider` hands `worktree add` a `refusal` of `ConflictError`, so every way
    that command can say no arrives as exit 4, and a fake answering exit 3 would send a person
    looking for a different problem. A place that already holds files and that nothing has open is
    the state a crash leaves, and adopting it is how one run silently continues another's. And a
    line of work something still has open is not one to delete, which is why the port says to call
    `remove` first.
    """

    async def cut_from_nothing(bundle: _Bundle) -> Workspace:
        return await bundle.provider.open(LABEL, CHILD, ABSENT_REF)

    async def over_a_crash(bundle: _Bundle) -> Workspace:
        stale = await bundle.provider.open(LABEL, SIBLING, bundle.base)
        where = stale.path
        await bundle.provider.remove(LABEL, SIBLING)
        where.mkdir(parents=True, exist_ok=True)
        (where / "left-by-a-dead-run.txt").write_bytes(b"nothing registered this\n")
        return await bundle.provider.open(LABEL, SIBLING, bundle.base)

    async def while_open(bundle: _Bundle) -> None:
        await bundle.provider.open(LABEL, CHILD, bundle.base)
        await bundle.provider.discard(LABEL, CHILD)

    assert await _refused(pair, cut_from_nothing) is ConflictError
    assert await _refused(pair, over_a_crash) is ConflictError
    assert await _refused(pair, while_open) is ConflictError


async def test_landing_over_a_hold_nobody_released_is_the_same_error_from_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """`InternalError`, because the framework calls `land` only with the target free.

    Every path out of a conflicted landing owes the target a `retry` or an `abort`, so reaching
    this one means AGL lost track of a hold it took - and merging over the hold would report the
    old collision as this landing's. A test of its own rather than one of three scenarios in one,
    because it deliberately leaves the target held and a second scenario over the same bundle
    would inherit it.
    """

    async def over_a_hold(bundle: _Bundle) -> object:
        target, child, sibling = await _three(bundle)
        _put(child, CONTESTED, _body("the child's own work"))
        await child.commit_all("the child's own work")
        _put(sibling, CONTESTED, _body("the sibling's own work, sharing not one line"))
        await sibling.commit_all("the sibling's own work")
        await bundle.integrator.land(child, target)
        await bundle.integrator.land(sibling, target)
        return await bundle.integrator.land(child, target)

    assert await _refused(pair, over_a_hold) is InternalError


async def test_retrying_with_nothing_pending_is_the_same_error_from_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """`InternalError` where `abort` says nothing at all, which the port pins as an asymmetry.

    The two-case outcome has no honest spelling for "there was nothing to do": a head would claim
    a landing that never happened, and a `Conflict` would send a workflow to a screen about a
    collision nobody had. Both implementations have to pick the same one of those refusals, or a
    workflow's error path is a different path on fakes.
    """

    async def nothing_pending(bundle: _Bundle) -> object:
        target, _, _ = await _three(bundle)
        return await bundle.integrator.retry(target)

    assert await _refused(pair, nothing_pending) is InternalError


async def test_landing_over_unrecorded_work_in_the_target_is_refused_by_both(
    pair: Mapping[str, _Bundle],
) -> None:
    """git's own refusal, and the one worth having in a fake even though no port names it.

    A merge that would write over a file the target's checkout holds and has never recorded is
    refused before anything is touched. Without it a `--dry-run` would quietly destroy an agent's
    uncommitted work at exactly the moment a real run would have stopped and said so - which is
    §1.9's drift with the sides swapped, and the reason `fake.py` implements the refusal rather
    than pinning it as a seventh divergence.
    """

    async def over_unrecorded_work(bundle: _Bundle) -> object:
        target, child, _ = await _three(bundle)
        _put(child, ALPHA, _body("the child's own work"))
        await child.commit_all("the child's own work")
        _put(target, ALPHA, _body("what an agent is in the middle of writing"))
        return await bundle.integrator.land(child, target)

    assert await _refused(pair, over_unrecorded_work) is UpstreamUnexpected


# --- Where the two deliberately disagree ----------------------------------------------------------


async def test_what_gitignore_covers_is_recorded_by_the_fake_and_not_by_git(
    pair: Mapping[str, _Bundle],
) -> None:
    """Divergence 1 of 6, and the one with the widest reach.

    `add --all` filters through the repository's ignore rules and `clean -ffd` without `-x` leaves
    what they cover alone, so a build directory is neither recorded nor swept away by the real
    adapter. The fake records the regular files in a checkout and lays a state back out over them,
    and has no ignore rules at all - parsing one program's ignore format would put that program
    back inside the module whose whole claim is that there is none of it.

    Both halves are asserted, because they are the two moments it shows: a commit that moves the
    head where git's would not, and a restore that takes away a build cache git would have kept.
    """
    heads: dict[str, tuple[bool, bytes | None]] = {}
    for name, bundle in pair.items():
        workspace = await bundle.provider.open(LABEL, CHILD, bundle.base)
        start = await workspace.head()
        _put(workspace, IGNORED, b"a build artifact\n")
        recorded = await workspace.commit_all("whatever the agent left behind")
        await workspace.restore(start)
        heads[name] = (recorded != start, _get(workspace, IGNORED))

    assert heads[_GIT] == (False, b"a build artifact\n"), (
        "git recorded a file its own ignore rules cover, or its restore took one away"
    )
    assert heads[_FAKE] == (True, None), (
        "the fake has grown ignore rules. That is not an improvement to make quietly: it means "
        "one program's file format is being parsed inside the package that has none of it"
    )


async def test_a_move_that_also_edits_is_a_rename_to_git_and_a_pair_to_the_fake(
    pair: Mapping[str, _Bundle],
) -> None:
    """Divergence 2 of 6: the band between the two ends the test above pins.

    git's `--find-renames` is a similarity heuristic with a default of fifty percent, so a file
    moved and edited a little is one rename. The fake detects a move whose contents are identical
    and nothing else, because a second heuristic beside git's would agree in the easy cases and
    disagree near a boundary that moves with the file - and a divergence that depends on how much
    of a file changed is one nobody can hold in their head.

    Not on the list of things the fake should learn. Reproducing git's similarity metric means
    reproducing git's similarity metric, and an approximation of it would be a third answer.
    """
    answers: dict[str, tuple[tuple[str, str, str | None], ...]] = {}
    for name, bundle in pair.items():
        workspace = await bundle.provider.open(LABEL, CHILD, bundle.base)
        _put(workspace, ALPHA, _body("a file that is about to be moved"))
        before = await workspace.commit_all("the state before the move")
        _drop(workspace, ALPHA)
        _put(workspace, MOVED_TO, _edited("a file that is about to be moved", 0, "one line moved"))
        after = await workspace.commit_all("the state after the move and one edit")
        answers[name] = _reported(await bundle.history.changed_files(before, after))

    assert answers[_GIT] == ((MOVED_TO, ChangeKind.RENAMED, ALPHA),)
    assert answers[_FAKE] == (
        (ALPHA, ChangeKind.DELETED, None),
        (MOVED_TO, ChangeKind.ADDED, None),
    )


async def test_an_edited_but_unstaged_resolution_lands_on_the_fake_and_not_on_git(
    pair: Mapping[str, _Bundle],
) -> None:
    """Divergence 3 of 6, and the one that is about a thing the fake does not have.

    git records which paths are unresolved in its index and takes `git add` as the word that a
    person is finished with one, so a file edited and not staged is still a conflict. There is no
    index here, and the `Integrator` port has no staging verb - deliberately, since §1.3's charge
    was one tool's merge state machine written out as method names - so the only place outside
    this package where a person's answer can be is the file, and the fake asks whether the markers
    it wrote are still in it.

    The direction matters and is stated: the fake is the permissive one here, which is the shape
    §1.9 warns about. What bounds it is that both implementations reach this only through a
    `Conflict` a workflow put on a screen, and §3.4's build gate is what decides whether the
    resolution was any good either way.
    """
    answers: dict[str, bool] = {}
    for name, bundle in pair.items():
        target, child, sibling = await _three(bundle)
        _put(child, CONTESTED, _body("the child's own work"))
        await child.commit_all("the child's own work")
        _put(sibling, CONTESTED, _body("the sibling's own work, sharing not one line"))
        await sibling.commit_all("the sibling's own work")
        await bundle.integrator.land(child, target)
        assert (await bundle.integrator.land(sibling, target)).conflicted is True
        _put(target, CONTESTED, _body("what a person decided the answer was"))
        answers[name] = (await bundle.integrator.retry(target)).conflicted
        await bundle.integrator.abort(target)

    assert answers[_GIT] is True, "git concluded a landing whose index still holds it unresolved"
    assert answers[_FAKE] is False, (
        "the fake has stopped reading the file it wrote the collision into, and there is nothing "
        "else here for a person's resolution to reach it through"
    )


async def test_a_file_one_side_moved_and_the_other_edited_combines_on_git_and_collides_on_the_fake(
    pair: Mapping[str, _Bundle],
) -> None:
    """Divergence 4 of 6, and the conservative direction of the two.

    git's `ort` strategy detects renames while it merges, so an edit to a file the other side
    moved is applied to the moved path and the landing is clean. The fake merges path by path
    against the common ancestor, so it sees one side remove a file the other changed and reports
    the collision that is - which is a conflict screen for work that would have combined, and the
    reason this is pinned rather than left to be met.

    Closing it means rename detection inside the merge, which is divergence 2's heuristic in a
    harder place: a wrong pairing there does not mislabel a change, it silently applies somebody's
    edit to the wrong file.
    """
    answers: dict[str, bool] = {}
    for name, bundle in pair.items():
        target, child, sibling = await _three(bundle)
        _drop(child, SOURCE)
        _put(child, MOVED_TO, _body("the state a run is cut from"))
        await child.commit_all("the child moved it")
        _put(sibling, SOURCE, _edited("the state a run is cut from", 0, "the sibling edited it"))
        await sibling.commit_all("the sibling edited it")
        await bundle.integrator.land(child, target)
        answers[name] = (await bundle.integrator.land(sibling, target)).conflicted
        await bundle.integrator.abort(target)

    assert answers[_GIT] is False, "git stopped detecting renames while merging"
    assert answers[_FAKE] is True


async def test_one_state_has_one_identity_on_the_fake_and_one_per_recording_on_git(
    pair: Mapping[str, _Bundle], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Divergence 5 of 6: content addressing against a commit object that carries a clock.

    `HistoryContract` says an implementation built on content hashes gets `resolve`'s forty-or-
    sixty-four characters for free, and the fake is that implementation - a state is named by its
    contents, its parents and its message, so recording one twice records it once. git's commit
    object also carries an author and a committer date, so the same contents recorded a second
    later is a second commit.

    The two recordings are put in two different seconds deliberately, because otherwise git agrees
    by accident and the difference is invisible - which is the whole reason it is worth pinning:
    an implementation whose answer depends on the clock and one whose answer does not are two
    different things even where they happen to coincide.

    Nothing in AGL is known to depend on either answer - a head is opaque and §3.6 chains entries
    off the value it recorded - which is why this is a divergence to know about rather than one to
    close. Closing it would mean putting a counter into a content hash.
    """
    answers: dict[str, bool] = {}
    for name, bundle in pair.items():
        workspace = await bundle.provider.open(LABEL, CHILD, bundle.base)
        start = await workspace.head()
        recorded: list[str] = []
        for when in ("2001-02-03T04:05:06+00:00", "2001-02-03T04:05:07+00:00"):
            for role in ("AUTHOR", "COMMITTER"):
                monkeypatch.setenv(f"GIT_{role}_DATE", when)
            await workspace.restore(start)
            _put(workspace, ALPHA, _body("the same work, recorded twice"))
            recorded.append(await workspace.commit_all("the same message, twice"))
        answers[name] = recorded[0] == recorded[1]

    assert answers[_GIT] is False, "git stopped putting a clock in a commit object"
    assert answers[_FAKE] is True, (
        "the fake gave two identities to one state, so it is no longer addressing by content - "
        "which is what `HistoryContract` says buys `resolve`'s shape without a rule of its own"
    )


async def test_the_executable_bit_and_a_symlink_are_recorded_by_git_and_not_by_the_fake(
    pair: Mapping[str, _Bundle],
) -> None:
    """Divergence 6 of 6, and the last of the family where git's model of a tree is the richer one.

    git records a file's mode and records a symlink as a thing of its own; the fake records the
    bytes of the regular files in a checkout, so `chmod +x` is a modification to one and nothing
    whatever to the other, and a link is a change to one and invisible to the other.

    Not on the list of things the fake should learn, and the reason is the same as divergence 1's:
    the fake's state is "what is in these files", which is what makes a merge and a diff over it
    something a person can reason about. Modes would have to be merged, diffed and conflicted too,
    and every one of those is a second answer to keep in step for a property no workflow reads.
    """
    answers: dict[str, tuple[bool, bool]] = {}
    for name, bundle in pair.items():
        workspace = await bundle.provider.open(LABEL, CHILD, bundle.base)
        _put(workspace, ALPHA, _body("a file that is about to become runnable"))
        before = await workspace.commit_all("the state before the mode changed")
        workspace.path.joinpath(*ALPHA.split("/")).chmod(0o755)
        after = await workspace.commit_all("the state after the mode changed")
        workspace.path.joinpath(UNDER, "link.txt").symlink_to(Path("source.txt"))
        linked = await workspace.commit_all("the state after a link arrived")
        answers[name] = (after != before, linked != after)

    assert answers[_GIT] == (True, True), "git stopped recording a mode or a symlink"
    assert answers[_FAKE] == (False, False), (
        "the fake has started looking at something other than a regular file's bytes"
    )
