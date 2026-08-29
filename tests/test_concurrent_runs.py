"""Three runs, one repository, at once - `tests/test_measurable_targets.py`'s target #9, against
real git.

    Three runs, one repo, concurrently - two `split` and one `fix`, different base refs -
    complete without contention and leave three independent local branches.

The design that sentence measures is the source of every claim below.

Two `split` and one `fix`, three labels, three different base refs, one repository and one trees
root. The claim is about worktrees and refs rather than about model behaviour, so **this file
spends nothing**: every agent below is a function in this module, the fakes bundle is what serves
them, and the only processes anything here starts are `git`.

## What is real, and the one substitution the deliverable did not list

`container.fakes()` builds each bundle and three of its ports are replaced: `workspaces`,
`history` **and `integrator`**. The third is not optional and is worth stating rather than
slipping in. `FakeIntegrator.land` asks a `FakeRepository` for `tip(source.branch)`, and a branch
that a real `git worktree add -b` created is a branch that in-memory repository has never heard
of - so the first `integrate()` of the first chunk raises `UpstreamUnexpected` before anything
here could assert a thing. A `split` run over real worktrees needs a real integrator, and there is
no arrangement in which it does not.

Everything else stays a fake, and each for its own reason. The **verifier** stays fake so that the
merge gate is a dict lookup: this file starts no build, and a real `ShellVerifier` would be the one
thing here that could spend a machine. The **agents** are fakes because that is the whole economy
of the file. The **store**, the **clock** and the **terminal** are fakes because none of the claims
below is about `AGL_HOME`, about time, or about a screen - `split` and `fix` both show only passive
boards, which a `HeadlessTerminal` drops, so no gesture is scripted anywhere. `fakes.repository` is
left in each bundle naming an in-memory repository these runs never touch, exactly as
`tests/test_api.py::_over` leaves it.

## Three bundles and not one, which is the arrangement rather than a convenience

Each run gets its own `container.fakes()` over **the same repository and the same trees root**,
which is what three `agl run` invocations are: `GitWorkspaceProvider`'s own docstring says two of
these over one repository *are* the same provider, and the file lock in `_trees.py` is what makes
that safe rather than an arrangement between them. A single shared bundle would have been shorter
and would have cost the sharpest assertion here. Each run's agent is reachable only through its own
bundle's `agents` port, so **what a checkout ends up holding was decided by which agent was
dispatched and never by where it was pointed**; one shared agent keying on `task.workspace` would
write the right file into the wrong tree and nothing below could tell.

## The rendezvous

`tests/workflows/test_split_runs.py` makes the argument this file inherits whole: a test that
starts three runs and afterwards finds three ledgers proves nothing, because a framework that ran
them strictly in order leaves exactly that ledger. The only arrangement that distinguishes them is
one where **none can finish until all of them have started** - a barrier reached from inside each
run's agent.

It is reached from the **implementers** and not from each run's first step, and the extra parties
are the point: two chunks of `alpha`, two of `beta` and `gamma`'s implementer are five agents that
cannot get past one another, so at that instant **seven git worktrees - three `_base` and four
children, across three runs - exist at once on one registry**, and every one of the five looks at
the user's own checkout from there. Under a lock spanning runs, or spanning namespaces inside one,
the barrier is never reached, all three runs wait forever, and the bound below expires. **Every
await is bounded and the expiry is the failure.** Nothing here sleeps against a scheduler: a
rendezvous five coroutines can reach is reached in microseconds whatever the machine is doing, and
one they cannot reach is not reached in an hour.

**`asyncio.gather` in one event loop still exercises the `flock`.** `flock(2)` is per open file
description and `_trees.registry_lock` opens the file per call, so three coroutines each taking it
exclude one another exactly as three processes would - and `_held` waits with a non-blocking
attempt and an `await`, never by parking a thread, so the waiter yields and the holder gets to
finish. What one process cannot show is that the lock is cross-process *at all*;
`tests/adapters/test_git_workspace.py` provokes it from a real second process, and that claim is
cited here rather than re-proved.

## Three base refs that are three different commits, arranged rather than hoped for

The fixture builds `main` and two side branches that all diverge from one seed commit, each
carrying a marker file no other carries. Divergent and not linear, and that is the assertion's
shape: on a linear history the oldest base is an ancestor of every branch, so "this run descends
from its own base" would be true of all three for all three and would separate nothing. Here
`contains(base, tip)` is true for a run's own base and false for both of the others, and the
marker file says the same thing a second way by being in the tree that was checked out.

Both `split` runs report **the same two chunk ids**, deliberately. A namespace is unique
*within a run*, and two runs each holding a `parser` is the case that has to work: two directories
under two labels, two refs under `agl/_work/`, and one object store between them.

## What the design does not promise, and is therefore not asserted

**There is no build concurrency limit**, and the merge queue serialises per *target* rather than
per run - "a grandchild landing into `T-01` and `T-01` landing into the root are two locks and two
builds, concurrently, in one process". So nothing below counts builds, times them, or asserts that
two gates never overlap. A test that did would be pinning a global serialisation the design
explicitly declines, and it would pass today only because these three runs happen to have one
integration target each.

## What is asserted weakly, and said here rather than left to be discovered

**"Without contention" is read as "nothing refused and nothing deadlocked".** A run that waited
milliseconds for the registry lock and got it is indistinguishable from one that never contended,
and deliberately so: elapsed time is not measured anywhere below, because a machine under load
makes any upper bound a lie and only "it never finished" is evidence of the bug. What is asserted
is that no `ConflictError` came out of any of the three - the class `run_lock`, `registry_lock` and
`WorkspaceProvider.open` all refuse with - and that all three returned inside the bound.

**"Throughout" is five samples and an afterwards, not every instant.** The user's checkout is read
from inside the runs at the one moment all seven checkouts provably exist, and again once the runs
have ended. A `git status` that went dirty and clean again between two samples would not be seen.

This file builds its own repository fixture, its own `_git` and its own `_worktrees` rather than
importing `tests/test_api.py`'s: `tests/` carries no `__init__.py` - see `tests/conftest.py` for
why it must not - so pytest's module names are the bare filenames, nothing there is importable
under a package name, and the shapes are copied with the precedent cited instead.
"""

import asyncio
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

import pytest

from agl import testing
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.config import container
from agl.ports.ids import Namespace, RunLabel
from agl.ports.run import JsonValue
from agl.ports.tree_layout import TreesRoot, base_worktree, worktree_dir
from agl.workflows.fix import fix
from agl.workflows.fix.findings import report_findings
from agl.workflows.split import split
from agl.workflows.split.chunks import report_chunks

# `asyncio_mode = "strict"`, so the async test below carries its own marker.

TRUNK: Final = "main"
"""The branch the user has checked out in `repo/`, and the third run's base ref.

That one of the three runs is cut from the very ref the user is standing on is the case two
preflight checks were deleted for: `git worktree add -b agl/gamma <path> main` succeeds while `main`
is checked out elsewhere, because a branch may be *started from* anywhere and only checking it out
twice is refused."""

ALPHA: Final = "alpha"
BETA: Final = "beta"
GAMMA: Final = "gamma"
LABELS: Final = (ALPHA, BETA, GAMMA)
"""Three runs, three `RunLabel`s, and therefore three deliverable branches and three directories
under the trees root. `alpha` and `beta` are the two `split` runs; `gamma` is `fix`."""

BASES: Final[Mapping[str, str]] = {ALPHA: "side-one", BETA: "side-two", GAMMA: TRUNK}
"""What each run is cut from - `--from <ref>`, the framework-level run parameter.

Three refs at three commits, none of them an ancestor of another. The module docstring argues why
divergent rather than linear is what makes the ancestry assertion able to fail."""

SEEDED: Final = "src/a.txt"
MARKERS: Final[Mapping[str, str]] = {
    ALPHA: "src/one.txt", BETA: "src/two.txt", GAMMA: "src/three.txt"
}
"""The one file every base carries, and the one file each base carries alone.

A marker is how "this checkout was cut from *that* ref" is read out of a tree afterwards, without
resolving anything: a run whose `_base` was cut from the wrong ref has somebody else's marker in
its branch, which is a fact about content rather than about a commit id."""

PLAN: Final = ("parser", "api")
"""The chunk ids both `split` runs report, deliberately the same two in each.

A namespace is unique *within a run* and not across the trees root, so two runs each holding a
`parser` is the case that has to work: two directories under two labels, two refs under
`agl/_work/`, and one object store between them. Two chunks and not three, because what the count
buys here is barrier parties, and seven checkouts is already the arrangement's whole point."""

CHILDREN: Final = tuple((label, chunk) for label in (ALPHA, BETA) for chunk in PLAN)
"""Every child worktree three runs of this shape make: one per chunk of each `split` run.

Four of them, and `gamma` contributes none - which is why this is a pair per child rather than a
product taken again at each of the three places below that has to name them."""

REQUEST: Final = "pull the importer apart"
"""What an operator asked for. Every run is given the same one; nothing below reads it."""

_PARTIES: Final = 2 * len(PLAN) + 1
"""How many agents meet at the barrier: every chunk of both `split` runs, and `fix`'s implementer.

The count is what makes the rendezvous say something about three runs rather than about one - and
what puts seven checkouts on one registry at the moment the samples below are taken."""

_LIVENESS: Final = 30.0
"""How long three runs that should not be waiting on anything are given before this file calls it a
deadlock. **Never spent on a green run** - the rendezvous is reached in microseconds - so all it
trades away is how long a broken build takes to say so. Generous, because a bound tight enough to
fire on a loaded machine would report a flake as a deadlock, and seven `git worktree add`s of a
source tree is the one thing here that is genuinely slow."""


# --- git, for arranging and for observing. Never for the thing under test -------------------------


def _git(where: Path, *argv: str) -> str:
    """One git command, for arranging and observing. `tests/test_api.py`'s helper and its argument:
    a test that built its repository through the adapter would be resting its arrangement on the
    behaviour it is about to check."""
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout


def _refused(where: Path, *argv: str) -> str:
    """One git command that must fail, and what git said about it. The mirror of `_git`.

    The returncode is asserted here rather than at the call site, because a refusal that quietly
    succeeded would otherwise arrive at an assertion about git's *wording* and fail there - which
    reads as git having changed its message rather than as git having done the thing.
    """
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=False)
    assert done.returncode != 0, (
        f"`git {' '.join(argv)}` in {where} succeeded, where git is supposed to refuse it. "
        f"It printed {done.stdout!r}"
    )
    return done.stderr


def _worktrees(repository: Path) -> frozenset[Path]:
    """Every checkout git has registered against this repository, resolved.

    Resolved on both sides wherever this is compared, because git records a worktree's real path
    and `/tmp` is a symlink on macOS - the same trap `GitWorkspaceProvider._branch_at` documents.
    A set rather than a tuple: git's order is git's, and what is asserted is which checkouts exist.
    """
    listing = _git(repository, "worktree", "list", "--porcelain")
    at = "worktree "
    return frozenset(
        Path(line[len(at) :]).resolve() for line in listing.splitlines() if line.startswith(at)
    )


def _tree(repository: Path, branch: str) -> frozenset[str]:
    """Every path a branch's tip holds, read out of the repository rather than off a checkout."""
    return frozenset(_git(repository, "ls-tree", "-r", "--name-only", branch).split())


def _committed(work: Path, path: str, message: str) -> None:
    """One file, added and committed on whatever `work` currently has checked out."""
    place = work / path
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_bytes(f"{path}\n".encode())
    _git(work, "add", path)
    _git(work, "commit", "-q", "-m", message)


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with three divergent refs, and no configuration from this machine.

    `tests/test_api.py`'s fixture, with two more branches on it. The `GIT_CONFIG_*` variables are
    what make this the same test everywhere - a developer with `commit.gpgsign` on, a
    `core.hooksPath` of their own or a template directory would otherwise be running a different
    one - and they go through `monkeypatch` so the adapters, which inherit the environment, see
    them too.

    It sits at `tmp_path/repo` and the trees root is its sibling, which is the layout a run uses: a
    trees root inside the working tree would put every checkout AGL makes into the user's own `git
    status`, and one of the claims below is that there is nothing in it.

    The three refs are built by checking out and coming back, so the fixture leaves `repo/` where
    the user left it: on `TRUNK`, clean, and holding the seed plus its own marker.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL concurrent")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", TRUNK)
    _committed(work, SEEDED, "the state all three runs share")
    for label in (ALPHA, BETA):
        _git(work, "checkout", "-q", "-b", BASES[label], TRUNK)
        _committed(work, MARKERS[label], f"work only {BASES[label]} carries")
        _git(work, "checkout", "-q", TRUNK)
    _committed(work, MARKERS[GAMMA], f"work only {TRUNK} carries")
    return work


# --- the agents, and the one moment all three runs are provably live ------------------------------


@dataclass(frozen=True, slots=True)
class _Sample:
    """One reading of the user's own checkout, taken from inside a run that is holding a step."""

    who: str
    """Which run's agent took it, as `<label>/<namespace>`, so a failure names the run."""

    status: str
    """`git status --porcelain` in `repo/`. It stays empty for the whole of a run."""

    head: str
    """`git rev-parse --abbrev-ref HEAD` in `repo/`. The user is still on the branch they were."""


@dataclass(slots=True)
class _Watch:
    """Which agents were dispatched, which of them got through, and what they saw. One per test.

    Shared by all three runs on purpose: `entered` and `left` are what the bound's failure message
    is written out of, and a hang is diagnosed by which of the five agents arrived at the barrier
    and which did not - a question that has no answer inside one run.
    """

    entered: list[str] = field(default_factory=list[str])
    left: list[str] = field(default_factory=list[str])
    samples: list[_Sample] = field(default_factory=list[_Sample])


async def _rendezvous(who: str, watch: _Watch, barrier: asyncio.Barrier, repository: Path) -> None:
    """Wait for every implementer of every run, then look at the directory AGL promised not to
    touch.

    The sample is taken **after** the barrier and therefore at a moment that is a fact rather than
    a hope: an `asyncio.Barrier` releases nobody until every party has arrived, so each of these
    readings is taken while all three runs are inside a step and all seven checkouts exist.
    """
    await barrier.wait()
    watch.samples.append(
        _Sample(
            who=who,
            status=_git(repository, "status", "--porcelain"),
            head=_git(repository, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        )
    )


def _work(label: str, name: str) -> str:
    """Where one agent of one run writes. Named after the run, which is the whole instrument.

    Two runs of `split` reporting the same chunk ids write different paths, so a file appearing in
    a branch says which *run's* agent put it there and not merely which chunk did.
    """
    return f"src/{label}-{name}.py"


def _wrote(task: testing.AgentTask, label: str, name: str) -> None:
    """Put this agent's work into the checkout it was handed.

    `agl/testing.py`'s single biggest documented trap, avoided in one line: no field on a `Reply`
    touches the worktree and `commit_all` is a no-op on a clean one, so an agent that only reports
    leaves an empty branch - every `commit=` records the head it started from, and there is nothing
    for a landing, a ref or an `ls-tree` to be about.
    """
    place = task.workspace / _work(label, name)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_bytes(f"{label}/{name}\n".encode())


def _whose(task: testing.AgentTask) -> str:
    """Which chunk this dispatch is for, read off the prompt the framework composed.

    `tests/workflows/test_split_runs.py`'s handle and its argument: `AgentTask` carries no
    namespace and no step name, the implementers of one run share a role, a model and an empty
    tools tuple, and what differs is `chunk=`, appended as canonical JSON under `## Inputs`. Keying
    on `task.workspace.name` would work and would make every assertion about which checkout a chunk
    ran in circular.
    """
    for chunk in PLAN:
        if f'"id":"{chunk}"' in task.instructions:
            return chunk
    raise AssertionError(  # pragma: no cover - a dispatch this file did not arrange
        f"an implementer was dispatched with no chunk of this plan in its inputs:\n"
        f"{task.instructions!r}"
    )


def _splitting(
    label: str, watch: _Watch, barrier: asyncio.Barrier, repository: Path
) -> testing.Agent:
    """One `split` run's agent: report the plan, or implement one chunk and meet the others.

    The planner does not rendezvous and the implementers do. That is what puts the barrier after
    every child worktree has been cut rather than before the first one, and it is what makes the
    five parties five.
    """

    async def agent(task: testing.AgentTask) -> testing.Reply:
        if any(tool.name == report_chunks.name for tool in task.tools):
            watch.entered.append(f"{label}/plan")
            watch.left.append(f"{label}/plan")
            return testing.Reply(
                calls=[testing.Call(report_chunks.name, _planned(label))], says="divided it up"
            )
        mine = _whose(task)
        watch.entered.append(f"{label}/{mine}")
        await _rendezvous(f"{label}/{mine}", watch, barrier, repository)
        _wrote(task, label, mine)
        watch.left.append(f"{label}/{mine}")
        return testing.Reply(says=f"implemented {mine}")

    return agent


def _planned(label: str) -> dict[str, JsonValue]:
    """This run's plan, as the call a planner makes: the JSON a model sends, not a `Chunks`.

    `files` is reported honestly as what this run's agents really will write, though nothing reads
    it: `Chunk.files` is a boundary and not a contract, and the two chunks of each run touch
    nothing in common, which is what keeps the merge train below free of conflicts to decide.
    """
    return {
        "items": [
            {"id": chunk, "work": f"do the {chunk} part", "files": [_work(label, chunk)]}
            for chunk in PLAN
        ]
    }


def _fixing(
    label: str, watch: _Watch, barrier: asyncio.Barrier, repository: Path
) -> testing.Agent:
    """The `fix` run's agent: implement and meet the others, then review and find nothing.

    An empty findings list is what keeps this run to two steps: `findings.high()` is empty, so the
    workflow's one branch is not taken and no `repair` is dispatched. Nothing here is a claim about
    `fix` - `tests/workflows/test_fix.py` owns all of those. It is the third concurrent run, it is
    a `fix` because target #9 names one, and what it contributes is the shape neither `split` run
    has: a run that opens no child worktree at all, holding one directory and one branch under the
    same trees root as two runs that hold three each.
    """

    async def agent(task: testing.AgentTask) -> testing.Reply:
        if any(tool.name == report_findings.name for tool in task.tools):
            watch.entered.append(f"{label}/review")
            watch.left.append(f"{label}/review")
            return testing.Reply(
                calls=[testing.Call(report_findings.name, {"findings": []})], says="reviewed it"
            )
        watch.entered.append(f"{label}/implement")
        await _rendezvous(f"{label}/implement", watch, barrier, repository)
        _wrote(task, label, "fix")
        watch.left.append(f"{label}/implement")
        return testing.Reply(says="implemented it")

    return agent


# --- one bundle per run, over one repository and one trees root -----------------------------------


def _over(
    repository: Path, trees: TreesRoot, label: str, agent: testing.Agent
) -> testing.Harness:
    """One run's harness: the fakes bundle with its three git ports made real.

    `tests/test_api.py::_over`'s shape with `integrator` added, and the module docstring argues why
    the third is not optional. Every run built here shares the repository and the trees root and
    shares nothing else - its own provider, its own history, its own integrator, its own store and
    its own agent - which is what three `agl run` processes are.
    """
    fakes = container.fakes(trees, agent=agent)
    return testing.over(
        replace(
            fakes,
            services=replace(
                fakes.services,
                workspaces=GitWorkspaceProvider(repository, trees),
                history=GitHistory(repository),
                integrator=GitIntegrator(repository),
            ),
        ),
        label=label,
    )


async def _base_sha(harness: testing.Harness) -> str:
    """The commit this run was pinned to, out of its own `run.json`.

    `agl/testing.py` sanctions the read - the harness's store is the recording one it wrapped,
    which delegates every call - and it is where the pin comes from. Recomputing it here would mean
    this file resolving a ref and then agreeing with itself about what the run had resolved.
    """
    record = await harness.fakes.store.read_record(harness.scope)
    assert record is not None, "the run wrote no run.json, so it never started"
    pinned = record["base_sha"]
    assert isinstance(pinned, str), "run.json holds something that is not a string at 'base_sha'"
    return pinned


async def _ended(started: list[asyncio.Task[None]], watch: _Watch) -> None:
    """Wait for all three runs under `_LIVENESS`, and make the expiry the failure.

    `return_when=FIRST_EXCEPTION` and not the default, and that is not a tidiness. A run that
    raises before the barrier leaves the other two waiting for a party that is never coming, so
    under `ALL_COMPLETED` this would sit out the whole bound and then report a deadlock - burying
    the real failure under a diagnosis of something that was only its consequence. This way the
    exception is re-raised as itself, in the first `result()` below, and the barrier's diagnosis is
    reached only when nothing raised and nothing finished.

    **`watch` is read here rather than interpolated by the caller**, which
    `tests/workflows/test_split_runs.py` argues at length: an f-string at the call site is
    evaluated before the runs have taken a single turn, so every failure message would report that
    no agent had been dispatched. Where a hang is the failure, which of the five agents arrived is
    the whole of the diagnosis.
    """
    done, pending = await asyncio.wait(
        started, timeout=_LIVENESS, return_when=asyncio.FIRST_EXCEPTION
    )
    for stalled in pending:
        stalled.cancel()
    for finished in done:
        finished.result()
    if pending:  # pragma: no cover - the failure this bound exists to produce
        pytest.fail(
            f"{len(pending)} of {len(started)} concurrent runs never finished. After "
            f"{_LIVENESS:g}s the agents dispatched were {watch.entered} and the ones that finished "
            f"were {watch.left}, where {_PARTIES} implementers have to be inside a step at once "
            f"before any of them may leave. Concurrent runs have one contention point - a "
            f"millisecond `flock` around `worktree add` and `prune` - so a rendezvous that cannot "
            f"be reached means something is held across a step, a landing or a whole run."
        )


@pytest.mark.asyncio
async def test_three_runs_on_one_repository_overlap_and_leave_three_independent_branches(
    repository: Path, tmp_path: Path
) -> None:
    """Target #9, whole: three runs, one repo, different base refs, at once.

    The rendezvous is the arrangement and the module docstring argues it; everything after it is
    what the design promises, and each part fails on its own:

    * **all three completed, and nothing refused.** `ConflictError` is what `run_lock`,
      `registry_lock` and `WorkspaceProvider.open` all raise, so a second run that found the
      registry mutated under it, a place another run held, or a lock it could not get arrives out
      of `_ended`'s `result()` as itself. The ledgers are asserted too: three runs that returned
      having skipped their own steps would be three runs that did nothing;
    * **three deliverable branches and four child branches coexist as refs**, asserted against
      `git for-each-ref` and compared to names spelled out here rather than composed from
      `tree_layout`. That is the whole of the branch scheme: `agl/alpha` beside `agl/alpha/parser`,
      cannot exist in git in either creation order, and this is the test that the scheme AGL chose
      can - three times over, concurrently, with both `split` runs using the same two chunk ids.
      The worktree registry is asserted as a set for the same reason: eight entries is what three
      uncontended runs leave, and a registry two `worktree add`s raced over is the failure the
      `flock` exists to prevent;
    * **independent, and not merely present.** Each branch descends from its own base and from
      neither of the others - which needs the divergent refs the fixture builds - and its tree
      holds its own base's marker file and its own agents' work and nobody else's. A run cut from
      the wrong ref, or an agent dispatched into another run's checkout, arrives here;
    * **the user's working directory is untouched**, sampled from inside the runs at the one
      instant all seven checkouts provably exist, and again afterwards. The dirty-repository and
      trunk-branch preflight checks were deleted precisely because a worktree is cut from a
      *ref*: one of these three runs is cut from the very branch the user is standing on;
    * **and git refuses a direct checkout of a branch `_base` holds**, which is the correct
      guardrail - so it is asserted as a guarantee. It is asserted last, because a `checkout` that
      was *not* refused would move the user's HEAD and quietly falsify the claim above it.
    """
    watch = _Watch()
    barrier = asyncio.Barrier(_PARTIES)
    trees = TreesRoot(tmp_path / "trees")
    runs = {
        ALPHA: _over(repository, trees, ALPHA, _splitting(ALPHA, watch, barrier, repository)),
        BETA: _over(repository, trees, BETA, _splitting(BETA, watch, barrier, repository)),
        GAMMA: _over(repository, trees, GAMMA, _fixing(GAMMA, watch, barrier, repository)),
    }
    chunks = str(len(PLAN))

    await _ended(
        [
            asyncio.create_task(
                runs[ALPHA].run(split, "-r", REQUEST, "-c", chunks, base_ref=BASES[ALPHA])
            ),
            asyncio.create_task(
                runs[BETA].run(split, "-r", REQUEST, "-c", chunks, base_ref=BASES[BETA])
            ),
            asyncio.create_task(runs[GAMMA].run(fix, "-r", REQUEST, base_ref=BASES[GAMMA])),
        ],
        watch,
    )

    # 1. All three ran their whole programme. `_ended` is what says none of them refused.
    for label in (ALPHA, BETA):
        assert [entry.step for entry in runs[label].recorded] == ["plan", "implement", "implement"]
    assert [entry.step for entry in runs[GAMMA].recorded] == ["implement", "review"]
    assert sorted(watch.left) == sorted(watch.entered), (
        f"agents were dispatched and did not finish: {sorted(set(watch.entered) - set(watch.left))}"
    )

    # 2. Three deliverable branches, four child branches, and seven checkouts on one registry
    # beside the user's own.
    assert frozenset(
        _git(repository, "for-each-ref", "--format=%(refname)", "refs/heads/agl/").split()
    ) == frozenset(
        [f"refs/heads/agl/{label}" for label in LABELS]
        + [f"refs/heads/agl/_work/{label}/{chunk}" for label, chunk in CHILDREN]
    ), (
        "the refs three concurrent runs left are not `agl/<label>` and `agl/_work/<label>/<ns>`. "
        "children are routed under `_work` because `refs/heads/agl/alpha` cannot be a file and a "
        "directory at once, so the obvious scheme collides in either creation order - and "
        "`git check-ref-format` passes each of those names on its own, which is why nothing in "
        "`ids.py` could ever catch it"
    )
    assert _worktrees(repository) == frozenset(
        [repository.resolve()]
        + [base_worktree(trees, RunLabel(label)).resolve() for label in LABELS]
        + [
            worktree_dir(trees, RunLabel(label), Namespace(chunk)).resolve()
            for label, chunk in CHILDREN
        ]
    ), (
        "git's own worktree registry does not hold the seven checkouts three runs of this shape "
        "make, beside the user's own. `worktree add` and `prune` mutate `.git/worktrees/` and are "
        "the one thing a cross-process lock is put around, so a registry missing an entry is "
        "two runs that raced over it"
    )

    # 3. Each branch descends from its own base, and carries its own run's work.
    history = runs[ALPHA].fakes.services.history
    pinned = {label: await _base_sha(runs[label]) for label in LABELS}
    assert len(frozenset(pinned.values())) == len(LABELS), (
        f"the three runs pinned {pinned}, where the target says three different base refs. "
        f"Three runs resolving to one commit would satisfy every assertion below without any of "
        f"them meaning anything"
    )
    for label in LABELS:
        tip = _git(repository, "rev-parse", "--verify", f"refs/heads/agl/{label}").strip()
        for other, base in pinned.items():
            assert await history.contains(base, tip) is (other == label), (
                f"`agl/{label}` {'does not descend' if other == label else 'descends'} from "
                f"{other}'s base commit. Concurrent runs share an object store and nothing else, "
                f"so each branch starts at the ref its own `--from` named and at no other"
            )
        work = (
            {_work(label, chunk) for chunk in PLAN}
            if label in (ALPHA, BETA)
            else {_work(label, "fix")}
        )
        assert _tree(repository, f"refs/heads/agl/{label}") == frozenset(
            {SEEDED, MARKERS[label]} | work
        ), (
            f"`agl/{label}` holds {sorted(_tree(repository, f'refs/heads/agl/{label}'))}, where it "
            f"holds its own base's marker and its own agents' work. Another run's marker means "
            f"this checkout was cut from the wrong ref; another run's work means an agent was "
            f"dispatched into a checkout belonging to a run that is not the one serving it"
        )

    # 4. The user's own directory, from inside the runs and afterwards.
    assert sorted(sample.who for sample in watch.samples) == sorted(
        [f"{label}/{chunk}" for label, chunk in CHILDREN] + [f"{GAMMA}/implement"]
    ), (
        f"the readings of `repo/` were taken by {sorted(s.who for s in watch.samples)}, where all "
        f"{_PARTIES} implementers take one. A sample missing is a run that never reached the "
        f"rendezvous, so the ones that were taken were not taken while all three runs were live"
    )
    for sample in watch.samples:
        assert (sample.status, sample.head) == ("", TRUNK), (
            f"while {sample.who} was working, `git status` in the user's own checkout reported "
            f"{sample.status!r} on {sample.head!r}. AGL never touches the user's working "
            f"directory, which is the whole reason the trees root is not inside it - and it is why "
            f"the dirty-repository and trunk-branch preflight checks were deleted rather than made "
            f"configurable"
        )
    assert _git(repository, "status", "--porcelain") == ""
    assert _git(repository, "rev-parse", "--abbrev-ref", "HEAD").strip() == TRUNK

    # 5. `_base` holds the deliverable branch, and git will not let it be checked out twice.
    for label in LABELS:
        place = base_worktree(trees, RunLabel(label))
        assert _git(place, "rev-parse", "--abbrev-ref", "HEAD").strip() == f"agl/{label}"
        refusal = _refused(repository, "checkout", f"agl/{label}")
        assert f"agl/{label}" in refusal and str(place.resolve()) in refusal, (
            f"git let go of `agl/{label}`, or refused without saying who has it: {refusal!r}. "
            f"this is the correct guardrail - `agl/<label>` is a real ref from run start "
            f"and advances with every `integrate()`, so `git log` and `git diff` on it are live, "
            f"and the one thing a person may not do is check out a branch `_base` is standing on"
        )
