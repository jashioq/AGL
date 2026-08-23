"""§3.6's own acceptance criterion: kill at every step boundary, resume, and nothing moved.

The plan states this test rather than leaving it to a stage, and states it as the *one rule*
fingerprinting places on workflow authors: "Branch only on step results. `if findings.high()` is
fine; `if datetime.now().hour < 18` breaks replay. **Enforced by an SDK contract test: run to
completion, kill at every step boundary, resume, assert identical final state.**" This file is that
sentence. It is a property test and not an example test: for a programme of N steps it sweeps every
k in `0..N`, kills the process after the k-th step's entry reaches disk, resumes in a *second*
process, and compares the whole of the result against a run that was never interrupted.

**What "identical" means here, and the one field left out of it.** Every entry path under
`AGL_HOME`, every entry's `fingerprint`, `value` and `head`, every branch tip in the repository,
and the user's own HEAD - all of them compared against the uninterrupted run. `at` is not, because
`at` is a clock reading and an interrupted run legitimately takes longer than a straight one. That
exclusion is not a gap being papered over: comparing everything else and passing is itself the
proof of §3.6's "`at` is never read for control flow", since a walk that branched on a timestamp
could not produce a byte-identical ledger from two runs whose timestamps differ. The field is still
examined - `_assert_well_formed_at` parses every one of them against the wire format and checks it
falls inside this session - because dropping a field unexamined and excluding a field for a stated
reason are different things.

**The kill is a real one, in a real process.** `tests/instruments/replay.py` is the driver and its
docstring carries the argument in full; the short version is that an exception would run `finally`
blocks and a killed agent does not, so the driver calls `os._exit(0)` at the boundary. Every sweep
below asserts that the killed process left **neither** of the two end-of-process markers the driver
writes - one from a `finally`, one from an `atexit` hook - and that the process which was allowed to
finish left both. That is the difference between a kill and an unwind, measured rather than claimed.

**And it is a real repository, which is the one place the fakes cannot go.** The git fakes hold
their commits in memory and re-seed per process, so a commit made before the kill would not exist
after it and every claim about a chained `head` would be a claim about nothing. Commits are made
reproducible instead - fixed identity, fixed author and committer dates, no global or system config
- so "the run branch's tip is identical" is an assertion about a commit id and not about a tree.

**Which assertions here are unfalsifiable inside one process.** Four, and they are the reason this
file spends processes at all:

  * *Rule 2, sort every set.* A `frozenset[Restriction]`'s iteration order is fixed for the life of
    one interpreter, so a same-process resume recomputes the digest it wrote and hits whether the
    journal sorted or iterated. The programmes below declare `frozenset(Restriction)` - all four
    members - and the two processes run under **different `PYTHONHASHSEED` values**, which is what
    makes "the worker ran exactly once in total" able to fail.
  * *Rule 3, walk the fields and never `repr`.* Same argument: an object's id does not move while
    it is alive. The first step of every programme takes a list of the workflow's own dataclasses
    with a `frozenset[str]` field inside, whose `repr` renders in hash order - so the shortcut
    renders differently in the second process and the digest with it.
  * *`n` is never persisted.* A same-process resume is free to reuse the `Fingerprints` object it
    already had; a second process has to rebuild the counter from nothing by walking the same calls
    in the same order, which is the whole of what §3.6 means by the phrase.
  * *A commit made before the kill is still there after it.* Only a real repository can be asked.

**And two that are falsifiable in one process but are stated here in the form they are actually
paid in.** `test_journal_walk.py` and `test_journal.py` pin both as arithmetic; what the two
two-process tests at the bottom add is that the value being handed back came off a real ledger
written by a process that no longer exists, which is what a replay *is*.

  * *A step that raised claims no slot* (§3.6, "the counter advances when an entry is written, not
    when a step is called"). The `crash` programme raises inside a step and retries it within one
    run; the second process walks the same calls and must hit the retry's entry without running
    anything. Advance on the call instead and the retry sits one slot past where the resume looks.
  * *Rule 6, a dataclass contributes its qualified type name.* The `retyped` and `renested`
    variants pass the same field names and the same values under a different type - the outer one
    and, separately, one nested inside it. The second process must **re-run**. This is the one
    correction whose failure is a false cache hit: an entry found, a recorded value handed back,
    and inputs that were never those.

`test_journal_walk.py` already pins several of these claims **in-process** - the retry loop's
`n = 0, 1, 2`, the commit message staying out of the fingerprint, a `_base` that advanced. Nothing
here duplicates the arithmetic those tests check; what is added is that the same claims survive a
kill and a process boundary, which a unit test in one interpreter cannot fail on.

**Cost, and what is capped.** Real git plus a process per kill point per variant multiplies fast.
The full sweep - every k in `0..N` - is run for the three programmes that have kill points, which is
28 child processes (6 + 4 + 4 kill points, two processes each); the uninterrupted reference for each
programme is computed **once** per session and compared against by every kill point, since it does
not depend on k. The six tests that are not sweeps (a changed prompt, an advanced base, a reworded
commit, a swapped input type, a swapped *nested* input type, and a step that raised and was retried)
are two processes each by their nature: they are "run to completion, change one thing, run again",
and a kill adds nothing to what they assert. The `crash` programme has no sweep at all, and its own
docstring in the instrument says why: a step that raised writes no entry, so the boundary after it
is the same ledger state as the boundary before it. Nothing else is capped, and the measured wall
clock is in the report for this deliverable.

No test in this file is async, and that is not an oversight: everything asynchronous happens inside
the child processes, and the parent only starts them, waits, and reads files.

Named `test_kill_and_resume.py`: `tests/` carries no `__init__.py` - see `tests/conftest.py` for why
it must not - so pytest's module names are the bare filenames and every one has to be unique.
"""

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from agl.ports.ids import Namespace, RunLabel
from agl.ports.tree_layout import TreesRoot, base_worktree, run_branch, worktree_branch
from instruments.replay import PROGRAMMES, SIBLINGS, Config, driver_path

PROJECT: Final = "myapp"
LABEL: Final = "auth"

# Three pairwise-distinct hash seeds, measured on this machine while this was written: each pair
# produces a different iteration order for `frozenset(Restriction)` *and* for the `frozenset[str]`
# inside the dataclass input. `test_the_seeds_still_vary_what_the_cross_process_half_rests_on`
# re-measures that on every run, because a day when they stop differing is a day the cross-process
# assertions hold for free and prove nothing while staying green.
KILLED_SEED: Final = "1"
RESUMED_SEED: Final = "31337"
REFERENCE_SEED: Final = "11"

# `journal.py`'s stored timestamp format, spelled out rather than imported: a suite that read the
# module's own constant back would agree with it whatever either of them said.
WIRE_TIME: Final = "%Y-%m-%dT%H:%M:%SZ"

# The run's own subtree under AGL_HOME, stripped off entry paths so that an assertion prints
# `steps/spec` and `worktrees/T-01/steps/implement` rather than the same prefix six times.
RUN_PREFIX: Final = f"projects/{PROJECT}/runs/{LABEL}/"

# Where `tests/` is, for the two probe interpreters at the bottom that import the instrument.
TESTS_DIR: Final = driver_path().parent.parent

# The moment this module was imported: the lower bound every entry's `at` is checked against.
STARTED: Final = datetime.now(UTC)

# Fixed to the second, so that a commit's object id is a function of its tree, its parent and its
# message and of nothing else. Without this the resuming process would make a commit that differed
# from the reference's by a timestamp, and "the run branch's tip is identical" could only ever have
# been asserted about a tree.
MOMENT: Final = "2026-08-18T09:14:02+00:00"

# The seed commit every world is cut from. Identical content and identical message under identical
# dates means an identical base commit id in every world, which is what lets one reference run be
# compared against a sweep that happens in a different temporary directory.
SEED_FILE: Final = "src/a.txt"
SEED_TEXT: Final = "the user's own work\n"
SEED_MESSAGE: Final = "the state a run is cut from"

# The kill-point sweeps, one per programme: every boundary from "nothing has run" to "everything
# has". `0` is a real kill point - a run can die before its first step - and `N` is the other end,
# where the killed process did all the work and the resume must hit every entry it left.
CORE_KILL_POINTS: Final = tuple(range(len(PROGRAMMES["core"].labels) + 1))
RETRY_KILL_POINTS: Final = tuple(range(len(PROGRAMMES["retry"].labels) + 1))
SIBLING_KILL_POINTS: Final = tuple(range(len(PROGRAMMES["siblings"].labels) + 1))

# What a process that was allowed to finish leaves behind, and what a killed one does not.
FINISHED: Final = frozenset({"finally", "atexit"})


# --- a world: one repository, one AGL_HOME, one trees root, one log ------------------------------


@dataclass(frozen=True, slots=True)
class _World:
    """The four directories one scenario happens in, all under one root.

    The trees root is a *sibling* of the repository rather than a directory inside it, which is the
    layout §3.9 draws and which `tests/adapters/test_git_workspace.py` gives the reason for: a
    worktree inside the user's working tree shows up in their `git status`.
    """

    root: Path

    @property
    def home(self) -> Path:
        return self.root / "home"

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def trees(self) -> Path:
        return self.root / "trees"

    @property
    def log(self) -> Path:
        return self.root / "workers.jsonl"


def _git_settings(world: _World) -> dict[str, str]:
    """The git environment every process in this file runs under - the parent and its children.

    The `GIT_CONFIG_*` variables are what make this the same test everywhere: a developer with
    `commit.gpgsign` on, a `core.hooksPath` of their own or a template directory would otherwise be
    running a different one. The identity is set because `commit_all` deliberately invents none, and
    the two dates are set because this file compares commit *ids* across processes and a commit id
    is a function of its author and committer lines.

    Passed explicitly as an environment rather than through `monkeypatch`, because the reference
    runs are computed once at session scope and a function-scoped fixture cannot reach them.
    """
    absent = str(world.root / "no-git-config")
    return {
        "GIT_CONFIG_GLOBAL": absent,
        "GIT_CONFIG_SYSTEM": absent,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "AGL replay",
        "GIT_AUTHOR_EMAIL": "agl@example.invalid",
        "GIT_COMMITTER_NAME": "AGL replay",
        "GIT_COMMITTER_EMAIL": "agl@example.invalid",
        "GIT_AUTHOR_DATE": MOMENT,
        "GIT_COMMITTER_DATE": MOMENT,
    }


def _environment(world: _World, seed: str) -> dict[str, str]:
    """A child's environment: this process's, plus reproducible git, plus one hash seed.

    Everything the repo-wide paid-endpoint guard puts in the environment is passed straight through
    untouched - a child of this suite is pointed at `instruments.loopback` exactly as its parent is.
    """
    return {**os.environ, **_git_settings(world), "PYTHONHASHSEED": seed}


def _git(world: _World, cwd: Path, *argv: str) -> str:
    """Run git for the fixtures and the assertions.

    Synchronous and raw, on purpose: this is arrangement and observation, not the thing under test,
    and a test that built its repository through the adapter would be resting the arrangement on the
    behaviour it is about to check. `tests/adapters/test_git_workspace.py` makes the same choice.
    """
    done = subprocess.run(
        ["git", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **_git_settings(world)},
    )
    return done.stdout


def _new_world(root: Path) -> _World:
    """A world with one commit in it, and nothing of this machine's configuration anywhere."""
    world = _World(root)
    world.home.mkdir(parents=True, exist_ok=True)
    world.repo.mkdir(parents=True, exist_ok=True)
    _git(world, world.repo, "init", "-q", "-b", "main")
    seed = world.repo / SEED_FILE
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text(SEED_TEXT, encoding="utf-8")
    _git(world, world.repo, "add", "--all")
    _git(world, world.repo, "commit", "-q", "--no-gpg-sign", "-m", SEED_MESSAGE)
    return world


def _base(world: _World) -> str:
    """The resolved commit a run is cut from - the pinned `RunSpec.base_sha` shape of a base."""
    return _git(world, world.repo, "rev-parse", "HEAD").strip()


# --- running one child process -------------------------------------------------------------------


def _spawn(
    world: _World,
    *,
    programme: str,
    tag: str,
    seed: str,
    variant: str = "plain",
    kill_after: int | None = None,
    order: Sequence[str] = SIBLINGS,
) -> None:
    """One child process, run to whichever of its two endings it was configured for.

    A non-zero status is a failure of the instrument rather than of the property, so the whole of
    stderr goes into the message: a child that died of a `TypeError` two frames inside the adapter
    would otherwise present as a step that mysteriously never ran.
    """
    config = Config(
        home=str(world.home),
        repo=str(world.repo),
        trees=str(world.trees),
        project=PROJECT,
        label=LABEL,
        base=_base(world),
        programme=programme,
        variant=variant,
        kill_after=kill_after,
        order=tuple(order),
        log=str(world.log),
        tag=tag,
    )
    finished = subprocess.run(
        [sys.executable, str(driver_path()), config.to_json()],
        capture_output=True,
        text=True,
        check=False,
        env=_environment(world, seed),
    )
    assert finished.returncode == 0, (
        f"the {tag!r} child exited {finished.returncode}. Re-run it with:\n"
        f"  {sys.executable} {driver_path()} {config.to_json()!r}\n"
        f"--- stderr ---\n{finished.stderr}"
    )


# --- what a world looks like afterwards ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Entry:
    """One step file as this suite reads it: §3.6's four fields, with `value` as canonical text.

    The value is held as sorted-key JSON rather than as a parsed object so that two entries compare
    by content and print legibly when they do not - and so that a mapping whose keys arrived in a
    different order is not mistaken for a different value.
    """

    fingerprint: str
    value: str
    head: str
    at: str


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """Everything a run leaves behind, addressed the way a comparison needs it.

    Entry paths are relative to `AGL_HOME` and branch names are git's own, so a snapshot taken in
    one temporary directory is comparable with one taken in another. That is what lets the
    uninterrupted reference be computed once per session and compared against every kill point.
    """

    entries: Mapping[str, _Entry]
    branches: Mapping[str, str]
    repo_head: str

    @property
    def replayable(self) -> dict[str, tuple[str, str, str]]:
        """Every entry, minus `at`: the part a resume has to reproduce exactly.

        The exclusion is argued in the module docstring and is the whole point of the comparison:
        `at` differs between an interrupted run and a straight one, and everything else not
        differing is what "never read for control flow" looks like from outside.
        """
        return {
            path: (entry.fingerprint, entry.value, entry.head)
            for path, entry in self.entries.items()
        }

    @property
    def per_step(self) -> dict[str, int]:
        """How many entries each step directory holds - one per time that step actually ran.

        Superseded entries stay on disk (§3.6), so this is the ledger's answer to "what re-ran":
        a step that was invalidated has two files under its name and a step that replayed has one.
        """
        counts: dict[str, int] = {}
        for path in self.entries:
            directory = path.removeprefix(RUN_PREFIX).rsplit("/", 1)[0]
            counts[directory] = counts.get(directory, 0) + 1
        return counts


def _snapshot(world: _World) -> _Snapshot:
    """Read the ledger and the repository back. Opens nothing that AGL owns."""
    entries: dict[str, _Entry] = {}
    for path in sorted(world.home.rglob("*.json")):
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict), f"{path} is not a JSON object"
        data: Mapping[str, object] = parsed
        entries[path.relative_to(world.home).as_posix()] = _Entry(
            fingerprint=_string(data, "fingerprint", path),
            value=json.dumps(data["value"], sort_keys=True),
            head=_string(data, "head", path),
            at=_string(data, "at", path),
        )
    branches: dict[str, str] = {}
    listing = _git(
        world, world.repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/"
    )
    for line in listing.splitlines():
        name, sha = line.split()
        branches[name] = sha
    return _Snapshot(entries, branches, _git(world, world.repo, "rev-parse", "HEAD").strip())


def _string(data: Mapping[str, object], key: str, path: Path) -> str:
    value = data[key]
    assert isinstance(value, str), f"{path} holds a {type(value).__name__} at {key!r}"
    return value


def _records(world: _World) -> list[Mapping[str, object]]:
    """Every line every process in this world wrote, in the order they were written."""
    if not world.log.exists():
        return []
    found: list[Mapping[str, object]] = []
    for line in world.log.read_text(encoding="utf-8").splitlines():
        parsed: object = json.loads(line)
        assert isinstance(parsed, dict), f"the log holds a line that is not an object: {line!r}"
        found.append(parsed)
    return found


def _workers(records: Sequence[Mapping[str, object]], tag: str | None = None) -> list[str]:
    """The labels of every worker invocation, optionally only one process's.

    "The worker was not called" is the whole of what a replay hit *is* - §3.6's replay has no other
    observable difference from a re-run that happens to produce the same answer - so this list, and
    the fact that it holds each label exactly once, is the headline property of this file.
    """
    return [
        str(record["worker"])
        for record in records
        if "worker" in record and (tag is None or record.get("tag") == tag)
    ]


def _reached(records: Sequence[Mapping[str, object]], tag: str) -> set[str]:
    """The steps one process got *in flight* - counter taken, entry looked up, worktree restored.

    A superset of what ran: a gated sibling is reached and then held, so the difference between
    this and `_workers` is the evidence that two concurrent steps really did overlap rather than
    being a sequence with an `asyncio.gather` around it.
    """
    return {
        str(record["reached"])
        for record in records
        if "reached" in record and record.get("tag") == tag
    }


def _markers(records: Sequence[Mapping[str, object]], tag: str) -> set[str]:
    """Which end-of-process markers one process left: `finally`, `atexit`, both, or neither."""
    return {
        str(record["marker"])
        for record in records
        if "marker" in record and record.get("tag") == tag
    }


# --- the reference: one uninterrupted run per programme, computed once --------------------------


class _References:
    """The straight run each sweep is compared against, memoised for the session.

    It does not depend on the kill point, so computing it per parametrised case would be six
    identical child processes for the core programme alone. Each reference gets a world of its own
    under the session's temporary directory; the snapshot is comparable across worlds because entry
    paths are relative and commit ids are reproducible.
    """

    def __init__(self, factory: pytest.TempPathFactory) -> None:
        self._factory = factory
        self._known: dict[str, _Snapshot] = {}

    def of(self, programme: str) -> _Snapshot:
        if programme not in self._known:
            world = _new_world(self._factory.mktemp(f"reference-{programme}"))
            _spawn(world, programme=programme, tag="reference", seed=REFERENCE_SEED)
            records = _records(world)
            assert _markers(records, "reference") == FINISHED, (
                "the uninterrupted reference run did not leave both end-of-process markers, so "
                "either it was killed after all or the markers stopped being written - and the "
                "sweeps' proof that a kill skips them would be comparing nothing with nothing"
            )
            assert sorted(_workers(records)) == sorted(PROGRAMMES[programme].labels)
            self._known[programme] = _snapshot(world)
        return self._known[programme]


@pytest.fixture(scope="session")
def references(tmp_path_factory: pytest.TempPathFactory) -> _References:
    """One straight run of each programme, shared by every kill point that compares against it."""
    return _References(tmp_path_factory)


@pytest.fixture
def world(tmp_path: Path) -> _World:
    """A fresh repository, AGL_HOME, trees root and log for one scenario."""
    return _new_world(tmp_path)


# --- the headline property ------------------------------------------------------------------------


def _assert_identical(actual: _Snapshot, reference: _Snapshot) -> None:
    """Everything except `at`, against the run that was never interrupted."""
    assert set(actual.entries) == set(reference.entries), (
        "the ledger a killed-and-resumed run left is not the one a straight run leaves. Extra "
        "paths are steps that re-ran under a digest the resume computed differently; missing "
        "paths are steps a resume skipped"
    )
    assert actual.replayable == reference.replayable, (
        "an entry's fingerprint, value or head differs from the uninterrupted run's, so what the "
        "resume recorded is not what the straight run recorded at the same address"
    )
    assert actual.branches == reference.branches, (
        "a branch tip differs from the uninterrupted run's. The run's own line and every child's "
        "are commits AGL made, and a resume that made a different one made different work"
    )
    assert actual.repo_head == reference.repo_head, (
        "the user's own checkout moved. §3.9: AGL never touches the target repository except "
        "through a workspace"
    )


def _assert_well_formed_at(snapshot: _Snapshot) -> None:
    """Every `at` is a timestamp, in the format the ledger stores, from inside this session.

    Excluded from the comparison above and examined here instead - a field dropped unexamined and a
    field excluded for a stated reason are different things. What is checked is exactly what §3.6
    says the field is for: it is a readable moment for debugging and the view, and nothing else.
    """
    upper = datetime.now(UTC) + timedelta(seconds=1)
    lower = STARTED - timedelta(seconds=1)
    for path, entry in snapshot.entries.items():
        moment = datetime.strptime(entry.at, WIRE_TIME).replace(tzinfo=UTC)
        assert lower <= moment <= upper, (
            f"{path} carries an 'at' of {entry.at}, which is outside this test session "
            f"({lower:{WIRE_TIME}} to {upper:{WIRE_TIME}}) - so it was not written by this run"
        )


def _sweep(
    world: _World,
    references: _References,
    programme: str,
    *,
    kill_after: int,
    killed_order: Sequence[str] = SIBLINGS,
    resumed_order: Sequence[str] = SIBLINGS,
) -> None:
    """Kill after `kill_after` steps, resume in a second process, compare against a straight run.

    The two processes run under different hash seeds, which is what the module docstring calls the
    other half of the deliverable: the resume has to arrive at the same digests without any of the
    iteration orders the first process happened to have.
    """
    _spawn(
        world,
        programme=programme,
        tag="killed",
        seed=KILLED_SEED,
        kill_after=kill_after,
        order=killed_order,
    )
    _spawn(world, programme=programme, tag="resumed", seed=RESUMED_SEED, order=resumed_order)

    records = _records(world)
    assert _markers(records, "killed") == set(), (
        "the killed process ran a `finally` clause or an `atexit` hook on its way out, so it was "
        "unwound rather than killed - and an unwound run is the one case §3.6 does not have to "
        "survive. The driver's exit is `os._exit`; something is catching it"
    )
    assert _markers(records, "resumed") == FINISHED, (
        "the resuming process left no end-of-process markers, so the assertion above - that a "
        "killed process leaves none - is comparing against nothing"
    )
    assert sorted(_workers(records)) == sorted(PROGRAMMES[programme].labels), (
        f"across both processes the workers that ran were {sorted(_workers(records))}, and a "
        f"complete run of {programme!r} is {sorted(PROGRAMMES[programme].labels)} exactly once "
        f"each. A repeat is a step that re-ran because the resume computed a different digest for "
        f"it; an absence is a step the resume skipped. Both are paid for in tokens and neither "
        f"raises"
    )
    # Where the kill landed, pinned rather than assumed. The killed process starts against an empty
    # ledger, so every step it reaches is a miss and runs its worker: after k boundaries it has run
    # exactly k of them, and the resume runs exactly the rest. A `kill_after` that counted anything
    # other than returned steps would still satisfy the assertion above while sweeping the same two
    # or three places over and over.
    total = len(PROGRAMMES[programme].labels)
    assert len(_workers(records, "killed")) == kill_after, (
        f"the killed process ran {len(_workers(records, 'killed'))} workers before it died and it "
        f"was told to die at boundary {kill_after}, so the kill is not landing at a step boundary"
    )
    assert len(_workers(records, "resumed")) == total - kill_after, (
        f"the resuming process ran {len(_workers(records, 'resumed'))} workers where {total} steps "
        f"minus the {kill_after} already recorded leaves {total - kill_after}"
    )

    snapshot = _snapshot(world)
    _assert_identical(snapshot, references.of(programme))
    _assert_well_formed_at(snapshot)


@pytest.mark.parametrize("kill_after", CORE_KILL_POINTS)
def test_the_core_programme_is_identical_however_far_it_got_before_it_was_killed(
    kill_after: int, world: _World, references: _References
) -> None:
    """The acceptance criterion, swept over every boundary of a five-step, two-namespace run.

    `spec` and `decompose` are read-only, `plan` and `T-01/implement` commit, `report` is read-only
    and scribbles - so the sweep crosses both of §3.6's endings, both of its namespaces, and the
    boundary either side of every one of them. `k = 0` is the run that died before it started and
    `k = 5` is the run that finished everything and died before it could say so.
    """
    _sweep(world, references, "core", kill_after=kill_after)


@pytest.mark.parametrize("kill_after", RETRY_KILL_POINTS)
def test_a_retry_loop_of_three_identical_calls_replays_all_three_in_order(
    kill_after: int, world: _World, references: _References
) -> None:
    """§3.6's "why the counter", across a kill and across a process.

    Three `step("review", ...)` calls in one namespace with the same role, the same inputs and the
    same head: one `base`, three entries, `n = 0, 1, 2`. A per-`base`-only cache collapses them to
    one and loops forever. `test_journal_walk.py` pins the arithmetic in-process and nothing here
    restates it - what this adds is that the second process rebuilds `n` from nothing (it is never
    persisted) and lands the three values back at the three addresses the first process used, which
    the comparison against the reference is exactly what checks.
    """
    _sweep(world, references, "retry", kill_after=kill_after)
    assert _snapshot(world).per_step["steps/review"] == 3, (
        "three identical calls did not leave three entries, so either the counter collapsed them "
        "onto one address or the resume wrote a fourth"
    )


@pytest.mark.parametrize("kill_after", SIBLING_KILL_POINTS)
def test_concurrent_siblings_replay_when_the_resume_completes_them_the_other_way_round(
    kill_after: int, world: _World, references: _References
) -> None:
    """§3.6's `T-01`/`T-02`, with the interleaving deliberately reversed on the resume.

    Both children call `step("implement", ...)` with the same role, no inputs and the same parent
    head, so their `base` values are identical by construction and only the namespace in the
    counter's key separates their entries. Rule 1's whole point is that the interleaving must not
    decide who gets `n = 0` - "the interleaving differs on resume, so each child looks in its own
    scope for a digest that is not there and **both re-run, forever, silently**" - and a test that
    always released them in the same order could not see it. So the killed process completes them
    `T-01` then `T-02` and the resume completes them the other way round.
    """
    _sweep(
        world,
        references,
        "siblings",
        kill_after=kill_after,
        killed_order=SIBLINGS,
        resumed_order=tuple(reversed(SIBLINGS)),
    )
    if kill_after >= 2:
        # The gather has been entered, so **both** siblings are in flight - each has taken its
        # counter, looked its entry up and restored its own checkout - even at the boundary where
        # only one of them has run its worker. Without this the programme could be a sequence with
        # an `asyncio.gather` around it and every assertion above would still hold.
        both = {f"{name}/implement" for name in SIBLINGS}
        assert _reached(_records(world), "killed") == {"spec", *both}, (
            "only one sibling was in flight when the process was killed, so the two never "
            "overlapped and this is not the `T-01`/`T-02` shape §3.6 describes"
        )


# --- the six tests that are a second run rather than a kill --------------------------------------


def test_a_changed_prompt_re_runs_that_step_and_everything_that_took_its_value(
    world: _World,
) -> None:
    """§3.6's build-system cascade: edit `decompose`'s prompt, and watch how far the edit reaches.

    "Halt, edit the implement prompt, resume - without this you replay results produced by the old
    prompt, which is exactly when you are iterating and least want stale output." The edited step is
    deliberately a **read-only** one, so its head does not move and the two steps that re-run below
    re-ran because their *inputs* changed and for no other reason. `T-01/implement` is the cleanest
    of the two: it lives in a child namespace whose chain the root's commits cannot reach at all.

    A kill adds nothing here. What is being asserted is which fingerprints changed, and that is a
    property of the two runs' inputs rather than of where either of them stopped.
    """
    _spawn(world, programme="core", tag="first", seed=KILLED_SEED)
    before = _snapshot(world)

    _spawn(world, programme="core", variant="edited", tag="second", seed=RESUMED_SEED)
    after = _snapshot(world)
    edited_run = _workers(_records(world), "second")

    assert sorted(edited_run) == ["T-01/implement", "decompose", "plan", "report"], (
        f"the edited run's workers were {sorted(edited_run)}. `decompose` must re-run because its "
        f"role changed, and each step downstream of it because its inputs did - and `spec`, which "
        f"is upstream of the edit, must not"
    )
    assert after.per_step["steps/spec"] == 1, (
        "the step upstream of the edit acquired a second entry, so it re-ran. An edit that "
        "invalidates what came *before* it is not a cascade, it is a cache that does not work"
    )
    for step in ("steps/decompose", "steps/plan", "worktrees/T-01/steps/implement", "steps/report"):
        assert after.per_step[step] == 2, (
            f"{step} still holds one entry, so the edit did not reach it and this run replayed a "
            f"result produced under the old prompt"
        )

    fresh = set(after.entries) - set(before.entries)
    values = {after.entries[path].value for path in fresh if "/steps/decompose/" in path}
    old = {before.entries[path].value for path in before.entries if "/steps/decompose/" in path}
    assert values and old and values != old, (
        f"`decompose` wrote a second entry holding the value it already had ({old}), so the prompt "
        f"edit changed the fingerprint without changing the answer - and the two steps below it "
        f"re-ran for a reason this test cannot see"
    )


def test_a_base_that_advanced_behind_the_journals_back_does_not_invalidate_earlier_steps(
    world: _World,
) -> None:
    """The sentence §3.6 calls load-bearing, provoked between two processes.

    "The starting head is chained logically, not read from disk. It comes from the previous step's
    recorded `head` in that namespace, never from the physical worktree. Otherwise: root runs `spec`
    at H0, children integrate and advance `_base` to H5, and on resume `spec` recomputes against H5,
    mismatches, and re-runs." The advance here is a commit made directly on the run's own checkout,
    which is what a landed child produces and what `integrate()` will do at stage 14.

    The second half is the expensive one and is asserted separately: because every step hits, no
    step restores, and the advanced commit is still the run branch's tip afterwards. §3.6 calls a
    parent restoring past its landed children "the one path in the design that destroys work".
    """
    _spawn(world, programme="core", tag="first", seed=KILLED_SEED)
    before = _snapshot(world)

    checkout = base_worktree(TreesRoot(world.trees), RunLabel(LABEL))
    (checkout / "landed.txt").write_text("from a child that landed\n", encoding="utf-8")
    _git(world, checkout, "add", "--all")
    _git(world, checkout, "commit", "-q", "--no-gpg-sign", "-m", "land T-01")
    advanced = _git(world, checkout, "rev-parse", "HEAD").strip()
    assert advanced != before.branches[run_branch(RunLabel(LABEL))]

    _spawn(world, programme="core", tag="second", seed=RESUMED_SEED)
    after = _snapshot(world)

    assert _workers(_records(world), "second") == [], (
        "a resume after the run's physical head advanced re-ran steps that were on the ledger. "
        "That is §3.6's own example: every step, every resume, forever, with the run still "
        "finishing and still right - the only symptoms being the bill and the wait"
    )
    assert after.entries == before.entries, "a resume that hit everything wrote something anyway"
    assert after.branches[run_branch(RunLabel(LABEL))] == advanced, (
        "the landed commit is gone: a step missed its fingerprint and restored the worktree to a "
        "head from before the landing, which §3.6 calls the one path in the design that destroys "
        "work rather than costing a re-run"
    )


def test_changing_only_the_commit_wording_replays_every_step_and_runs_no_worker(
    world: _World,
) -> None:
    """§3.6 keeps the message out of the fingerprint, and states the trade it is making.

    "A message is cosmetic. Including it would mean editing the wording re-runs the agent, which is
    the opposite of what fingerprinting is for. The trade is that a replayed step keeps the commit
    it already made, message and all." Both halves are asserted: nothing re-runs, and the commit
    still carries the wording the first run gave it.

    `test_journal_walk.py` pins the first half in-process for one step. What is added here is that
    it holds for a whole programme, across a process boundary, and that the *stated cost* - the old
    message surviving - is real rather than a caveat nobody checked.
    """
    _spawn(world, programme="core", tag="first", seed=KILLED_SEED)
    before = _snapshot(world)

    _spawn(world, programme="core", variant="reworded", tag="second", seed=RESUMED_SEED)
    after = _snapshot(world)

    assert _workers(_records(world), "second") == [], (
        "editing a commit message re-ran the agent, which §3.6 calls the opposite of what "
        "fingerprinting is for"
    )
    assert after.entries == before.entries, (
        "a run that hit every step wrote an entry anyway - and every field, `at` included, should "
        "be untouched, because nothing was written at all"
    )
    label = RunLabel(LABEL)
    for branch in (run_branch(label), worktree_branch(label, Namespace("T-01"))):
        assert after.branches[branch] == before.branches[branch]
        message = _git(world, world.repo, "log", "-1", "--format=%s", branch).strip()
        assert "oauth callback route" not in message, (
            f"{branch} carries the reworded message {message!r}, so the second run did make a "
            f"commit - the replayed step is supposed to keep the one it already made"
        )


def _swapped_types(world: _World, variant: str, what: str) -> None:
    """Run `core` plain, then again with `spec`'s dataclass inputs under other types.

    Only `spec` carries the constraints, and `spec`'s recorded value does not depend on them, so
    nothing downstream sees a changed input and the cascade stops at one step. That is a sharper
    claim than a cascade would be: a step that re-ran because something upstream moved proves
    nothing about types, and here exactly one fingerprint is allowed to have moved.
    """
    _spawn(world, programme="core", tag="first", seed=KILLED_SEED)
    before = _snapshot(world)

    _spawn(world, programme="core", variant=variant, tag="second", seed=RESUMED_SEED)
    after = _snapshot(world)
    second = _workers(_records(world), "second")

    assert second == ["spec"], (
        f"the {variant!r} run's workers were {second}. `spec` takes a list of the workflow's own "
        f"dataclasses and this run passed {what} - the same field names and the same values under "
        f"a different type - so its fingerprint had to move and the step had to re-run. Replaying "
        f"instead is the one failure in this family that returns a wrong answer rather than a "
        f"bill: an entry found and handed back whose inputs were never these"
    )
    assert after.per_step["steps/spec"] == 2, (
        "`spec` ran its worker and recorded no second entry, so the ledger and the log disagree"
    )
    for step in ("steps/decompose", "steps/plan", "worktrees/T-01/steps/implement", "steps/report"):
        assert after.per_step[step] == 1, (
            f"{step} acquired a second entry, so the swap reached past the one step that carries "
            f"these inputs - and this test can no longer tell a type term from a cascade"
        )
    assert set(before.entries) < set(after.entries), "the second run recorded nothing at all"


def test_an_input_dataclass_of_another_type_re_runs_the_step_rather_than_replaying_it(
    world: _World,
) -> None:
    """§3.6's rule 6, the outer half: `Finding("T-01", 3)` and `Ticket("T-01", 3)`.

    "`asdict` erases the type, so `Finding("T-01", 3)` and `Ticket("T-01", 3)` fingerprint
    identically and changing an input's type while keeping its shape replays the old result." The
    instrument's `Constraint` and `Requirement` are that pair, built from one list of values so
    that "identical field names and identical values" is structural rather than a thing a reader
    has to check character by character.
    """
    _swapped_types(world, "retyped", "a `Requirement` where the first run passed a `Constraint`")


def test_a_nested_input_dataclass_of_another_type_re_runs_the_step_too(world: _World) -> None:
    """Rule 6's nested half, which is where the obvious implementation of it fails.

    `dataclasses.asdict` recurses: it turns a nested dataclass into a plain `dict` before any
    walker sees it, so a type name attached to what `asdict` returned names the outer type and
    erases every one below. Here the outer type is held identical on purpose - the `Constraint` is
    a `Constraint` in both runs - and only its `budget` moves, from a `Budget` to a `Ceiling` of
    the same one field and the same value. A walker that tagged only the top level passes the test
    above and fails this one, which is why they are two tests and not one.
    """
    _swapped_types(world, "renested", "a `Ceiling` nested where the first run nested a `Budget`")


def test_a_step_that_raised_and_was_retried_in_one_run_replays_where_a_resume_looks(
    world: _World,
) -> None:
    """§3.6: "the counter advances when an entry is written, not when a step is called".

    "A step that crashes and is retried within one run must not consume a slot - the crash is not
    journalled, so a retry landing at `n = 1` is a slot a later resume asks for at `n = 0`, misses,
    and pays an agent for again." The `crash` programme is that sentence: one `step` call whose
    worker raises, and a retry of the same call - same name, same role, same inputs, same head, so
    the same `base` - inside the `except`.

    The second process is the whole assertion. It walks the same code, so its first `implement`
    asks for `n = 0`; if the retry's entry is there it hits, returns, raises nothing, and never
    enters the `except` at all - one call, one hit, no worker. Advance the counter on the call
    instead and the entry sits at `n = 1`: the resume misses, pays for the failing attempt a second
    time, and only then falls into the retry and hits. One worker line, silently, per resume.
    """
    _spawn(world, programme="crash", tag="first", seed=KILLED_SEED)
    before = _snapshot(world)
    first = _workers(_records(world), "first")

    assert first == list(PROGRAMMES["crash"].labels), (
        f"the first process ran {first} where a complete run of `crash` is "
        f"{list(PROGRAMMES['crash'].labels)} in that order - the attempt that raises, and then "
        f"the retry that the `except` around it makes"
    )
    assert before.per_step["steps/implement"] == 1, (
        "two entries under one step name after one crash and one retry: a step that raised wrote "
        "a file, and §3.6's whole ledger is `a step is done when its file is there`"
    )

    _spawn(world, programme="crash", tag="second", seed=RESUMED_SEED)
    after = _snapshot(world)
    second = _workers(_records(world), "second")

    assert second == [], (
        f"the resuming process ran {second}. It walks the same calls the first one did, so its "
        f"first `implement` asks for n = 0 - and the retry's entry is only there if the attempt "
        f"that raised claimed no slot. Recorded at n = 1 instead, this resume misses, pays the "
        f"agent for the failing attempt all over again, and only then hits the retry"
    )
    assert after.entries == before.entries, "a resume that hit everything wrote something anyway"
    assert after.branches == before.branches, (
        "the retry's commit moved or was made again, so the replayed step did not keep the commit "
        "it already made"
    )
    _assert_well_formed_at(after)


# --- the kill, and the seeds, both asked directly -------------------------------------------------


def test_the_kill_runs_no_finally_and_no_atexit_where_a_clean_finish_runs_both(
    world: _World,
) -> None:
    """The claim every sweep above rests on, asked on its own so a failure says which thing broke.

    An exception would run `finally` blocks, `atexit` handlers and asyncio's cancellation path; a
    killed agent runs none of them, and §3.6's design is built on that - "a crashed step leaves no
    entry, so the next run resets to the last good head and starts clean" is a claim about a process
    that got no chance to tidy up. The driver registers both an `atexit` hook and a `finally`
    clause; `os._exit` skips both, and the same process completing normally leaves both.
    """
    _spawn(world, programme="core", tag="killed", seed=KILLED_SEED, kill_after=2)
    _spawn(world, programme="core", tag="resumed", seed=RESUMED_SEED)

    records = _records(world)
    assert _markers(records, "killed") == set()
    assert _markers(records, "resumed") == FINISHED
    assert _workers(records, "killed") == ["spec", "decompose"], (
        "the killed process did not stop at the second step boundary, so `kill_after` is not "
        "counting what it says it counts and every sweep above is killing somewhere else"
    )


# Two probes, run under the file's own seeds, asking whether those seeds still vary the two things
# the cross-process assertions rest on. `test_journal.py` makes the same move for the same reason:
# without this, a day when the seeds stop differing is a day the sweeps hold for free.
_ORDERS: Final = """
import json, sys
sys.path.insert(0, sys.argv[1])
from agl.ports.agent import Restriction
from instruments.replay import CONSTRAINTS
print(json.dumps([str(restriction) for restriction in frozenset(Restriction)]))
print(repr(CONSTRAINTS[0]))
"""


def test_the_seeds_still_vary_what_the_cross_process_half_rests_on() -> None:
    """The non-vacuous half: these three seeds really do produce three different orders.

    Rule 2 is only falsifiable across processes if `frozenset(Restriction)` iterates differently in
    them, and rule 3 only if the `frozenset[str]` inside the dataclass input renders differently in
    its `repr` - which is what the one-line `repr()` shortcut would put into the canonical text.
    If either stops varying, every cross-process assertion in this file keeps passing while proving
    nothing, so the seeds are re-measured on every run rather than trusted from the day they were
    chosen.
    """
    seeds = (KILLED_SEED, RESUMED_SEED, REFERENCE_SEED)
    restrictions: dict[str, str] = {}
    reprs: dict[str, str] = {}
    for seed in seeds:
        finished = subprocess.run(
            [sys.executable, "-c", _ORDERS, str(TESTS_DIR)],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        assert finished.returncode == 0, f"PYTHONHASHSEED={seed} probe failed:\n{finished.stderr}"
        first, second = finished.stdout.splitlines()
        restrictions[seed] = first
        reprs[seed] = second

    assert len(set(restrictions.values())) == len(seeds), (
        f"the seeds no longer give one iteration order of frozenset(Restriction) each - they gave "
        f"{restrictions} - so a journal that iterated the set instead of sorting it would compute "
        f"the same digest in both of a sweep's processes and every sweep in this file would pass "
        f"against rule 2's bug. Pick new seeds: `test_journal.py` lists six that were measured"
    )
    assert len(set(reprs.values())) == len(seeds), (
        f"the seeds no longer render the dataclass input's frozenset field one way each - they "
        f"gave {reprs} - so a repr() shortcut where dataclasses.asdict belongs would be invisible "
        f"to this file. Pick new seeds, or a `tags` set with more members: a set of n elements has "
        f"only so many orders, and the check cannot ask for more than that"
    )
