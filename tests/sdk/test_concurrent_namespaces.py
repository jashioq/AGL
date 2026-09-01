"""Two namespaces running at once: no lock between them, one lock inside each, one file per step.

The three claims the design makes about a run that has more than one namespace in flight. Every
one of them was already argued and already implemented; what was missing was the evidence, and each
of the three fails in a way no existing test could see.

  * **Concurrent siblings write with no lock and no coordination.** "`T-01/implement/…json`
    and `T-02/implement/…json` are written by two concurrent children. Separate paths mean each
    write is one `os.replace` - atomic, no lock, no coordination." The failure a lock spanning
    namespaces produces is not a wrong answer, it is *no answer*: two children that cannot both be
    inside a step at once are two children that deadlock the moment either one waits on the other.
  * **Serialization is per namespace and stops there.** "A namespace's workspace is
    single-threaded" is a statement about one checkout, and reading it as a statement about the run
    would cost the only real concurrency AGL has - the trees root is flat and cuts a checkout
    per child precisely so that two agents can run at once.
  * **`last_good` is chained from recorded entries and never read from the worktree.** "Root
    runs `spec` at H0, children integrate and advance `_base` to H5, and on resume `spec` recomputes
    against H5, mismatches, and re-runs."

## The rendezvous, and why the two headline tests are one arrangement used twice

A test that starts two children under an `asyncio.gather` and finds two entries afterwards proves
nothing about overlap: a framework that ran them strictly one after the other produces exactly that
ledger, and so does one holding a mutex across the whole run. The only arrangement that can tell
the two apart is one in which **neither agent can finish until the other has started** - an
`asyncio.Barrier` reached from inside each scripted agent. Under the design it is passed at once.
Under any lock that spans namespaces the second child never reaches it, the first waits at it
forever, and the test hangs; so both tests below are bounded, and a bound that expires is the
failure rather than a flake.

The mirror uses the same barrier over **one** `Run`, where the answer must be the opposite: two
steps in one namespace share one `Workspace`, so they are serialized, so the rendezvous is
unreachable and must stay unreachable. That is the sharpest available statement of "per namespace
and no further" - one arrangement, two namespaces' worth of children pass it, two steps of one
namespace cannot - and it is why the two tests sit next to each other rather than in two files.

**Nothing here sleeps against a scheduler.** A bound is not a race: a rendezvous that two coroutines
can reach is reached in microseconds whatever the machine is doing, and one they cannot reach is
never reached however long the wait. The bounds below therefore decide only how long a *failing*
run takes to say so, and in the serialized mirror how long a passing one spends proving a negative.

## What this file does not restate

`tests/sdk/test_journal_walk.py` holds the same two properties one layer down, against a hand-built
`Journal` and workspaces that suspend on every call: `test_two_gathered_steps_in_one_namespace_do_
not_overlap` pins the serialized *sequence* of workspace calls, and `test_concurrent_siblings_each_
write_their_own_entry_and_both_replay` pins the counter's arithmetic across two scopes. Neither can
see a lock that spans namespaces, because neither ever asks two coroutines to be inside a step at
the same moment - each releases its siblings one at a time, which a global mutex satisfies
perfectly. `tests/sdk/test_run_worktree.py::test_a_second_walk_over_a_nested_run_replays_every_
namespace` is the "replay reproduces every namespace" claim and is not repeated here.

The repository is real git and the ledger is a real `FilesystemStore`, for `test_run_step.py`'s
reasons: "the entries are two files at two paths" is a directory listing, and the checkouts a
sibling must not be able to see into are working trees on disk.
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.history import GitHistory
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.config import container
from agl.ports.agent import AgentTask, Claude, Restriction
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.run import JsonValue
from agl.ports.tree_layout import TreesRoot
from agl.sdk.roles import Role, role
from agl.sdk.testing import Agent, Call, Reply
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# The standing example, by name: "`T-01` and `T-02` both call `step(implementer)` with
# the same role, no inputs, and the same parent head".
SIBLINGS: Final = ("T-01", "T-02")

# The file the repository is seeded with, and the one a raw-git landing adds to the run's own
# checkout without the framework hearing about it.
SEEDED: Final = "src/a.txt"
SEED: Final = b"the user's own work\n"
LANDED: Final = "src/landed.py"

# How long the two-child rendezvous is given before the test calls it a deadlock. **Never waited
# for on a green run**: the barrier is passed as soon as the second agent reaches it, which is
# microseconds after it is dispatched, and the whole of the test that spends this bound takes under
# a second. It is generous by a factor of thirty because the only thing it trades away is how long
# a broken build takes to say so, and a bound tight enough to fire on a loaded machine would report
# a flake as a deadlock - the one failure in this file that must mean exactly what it says.
_LIVENESS: Final = 30.0

# How long the serialized mirror waits before concluding that the rendezvous cannot be reached.
# This one **is** spent on every green run, because the assertion is a negative: the wait is the
# proof. It is short because the thing it has to outlast is small - under a `Journal` with no lock
# both steps are dispatched within a few hundred milliseconds of each other, every one of those
# milliseconds being a `git` subprocess - and long because a bound that fires before the *second*
# step could have been dispatched would pass against exactly the implementation it is written to
# catch. Two seconds is two orders of magnitude of margin over the first and a fiftieth of what
# this file's own real-git tests already cost.
_SERIALIZED: Final = 2.0


@dataclass(frozen=True)
class Summary:
    """A reporting payload: one string, which is the whole of what these agents have to say."""

    text: str


REPORT: Final = reporting_tool("report", "report what you did", Summary)


@role(model=Claude.SONNET)
def _role(name: str, instructions: str, *, read_only: bool = False) -> Role[Summary]:
    """A reporting role: its result is `REPORT`'s payload, read back as a `Summary`. `name` is what
    its entries are recorded under, `run.step` carrying none of its own.

    The three parameters are this file's whole override surface, which is what a `@role` factory
    buys: the model is on the decorator and unreachable from any call below."""
    restrictions = {Restriction.NO_VCS_WRITES} if read_only else set[Restriction]()
    return Role(
        name=name,
        instructions=instructions,
        restrictions=restrictions,
        tools=(REPORT,),
    )


# Module-level, which is what a `Role` is - "a module-level value shared across steps and across
# concurrent runs" - and load-bearing for every "identical `base`" claim below: two children
# calling `step(IMPLEMENT)` with no inputs are hashing the same object's fields - and, since the
# call carries no name of its own, addressing the same `steps/implement/` inside their own
# namespaces.
PLAN: Final = _role("plan", "plan the ticket", read_only=True)
IMPLEMENT: Final = _role("implement", "implement the ticket")
REVIEW: Final = _role("review", "review the worktree", read_only=True)


# --- the repository, the bundle, and the run -----------------------------------------------------


def _git(where: Path, *argv: str) -> str:
    """One git command, for arranging and observing. Never for the thing under test."""
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit, and no configuration from this machine.

    `test_run_step.py`'s fixture, duplicated for the reason `test_run_worktree.py` gives: nothing
    under `tests/` imports another test module, so a shared fixture would have to become a module
    of its own that one file's arrangement made another file's dependency.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL contract")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    seeded = work / SEEDED
    seeded.parent.mkdir(parents=True)
    seeded.write_bytes(SEED)
    _git(work, "add", SEEDED)
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work


@pytest.fixture
def base(repository: Path) -> str:
    """The commit the run is cut from, resolved - the pinned `RunSpec.base_sha` shape of a base."""
    return _git(repository, "rev-parse", "HEAD").strip()


def _run(repository: Path, tmp_path: Path, base: str, agent: Agent) -> Run[None]:
    """A `Run` over one real repository, one real ledger, one real history and one scripted agent.

    `test_run_worktree.py::_run`, and called twice with the same arguments it is a resume: the same
    ledger on disk, the same worktrees reopened, and a fresh counter and a fresh namespace table,
    which is what "`n` is never persisted" means.

    `agent=` and not `claude=`: every agent below is an `async def` in `sdk/testing.py`'s own
    vocabulary, which this file is one of the reasons for. Before that
    an `Agent` could not await, so a barrier - the only instrument that can tell two children
    overlapping from a framework that ran them in order - had to be reached from a raw per-provider
    `Script`, and every arrangement in this file was written on one.
    """
    trees = TreesRoot(tmp_path / "trees")
    harness = container.fakes(trees, agent=agent)
    services = replace(
        harness.services,
        store=FilesystemStore(AglHome(tmp_path / "home")),
        workspaces=GitWorkspaceProvider(repository, trees),
        history=GitHistory(repository),
    )
    return Run(params=None, services=services, scope=SCOPE, base=base)


# --- the ledger and the trees root, read off disk ------------------------------------------------
#
# Spelled out rather than composed through `home_layout` or `tree_layout`, for `test_run_worktree.
# py`'s reason: a test that asked the layout where an entry should be and then looked there would
# agree with the layout whatever either of them said, and "two children wrote two files at two
# paths" is a claim about two literal shapes on disk.


def _run_dir(tmp_path: Path) -> Path:
    """`<home>/projects/myapp/runs/auth/` - depth zero, the run itself."""
    return tmp_path / "home" / "projects" / "myapp" / "runs" / "auth"


def _steps_dir(tmp_path: Path, step: str, *namespaces: str) -> Path:
    """`<run>/worktrees/<n>/.../steps/<step>/` - the layout, written out rather than computed."""
    where = _run_dir(tmp_path)
    for namespace in namespaces:
        where = where / "worktrees" / namespace
    return where / "steps" / step


def _entries(tmp_path: Path, step: str, *namespaces: str) -> list[Path]:
    """Every entry file recorded for one step in one namespace, in filename order."""
    return sorted(_steps_dir(tmp_path, step, *namespaces).glob("*.json"))


def _only(tmp_path: Path, step: str, *namespaces: str) -> Path:
    """The one entry file that step left there. Two would mean it ran twice."""
    found = _entries(tmp_path, step, *namespaces)
    assert len(found) == 1, f"{_steps_dir(tmp_path, step, *namespaces)} holds {len(found)} entries"
    return found[0]


def _read(entry: Path) -> dict[str, JsonValue]:
    """One entry file, parsed. `json.loads` answers `Any`, and mypy is right to insist."""
    parsed: dict[str, JsonValue] = json.loads(entry.read_text(encoding="utf-8"))
    return parsed


def _field(entry: Path, key: str) -> str:
    """One string off one entry file, narrowed."""
    value = _read(entry)[key]
    assert isinstance(value, str), f"{entry}'s {key} is {value!r}, which is not a string"
    return value


def _trees_dir(tmp_path: Path) -> Path:
    """`.trees/auth/` - every checkout belonging to this run, and nothing else."""
    return tmp_path / "trees" / "auth"


# --- the agents: one that must meet another, and one that must wait its turn ----------------------


class _Dispatches:
    """Which namespace's agent was dispatched, and which of them got all the way through.

    `entered` is the list a replay's whole observable difference from a re-run is read off - a
    hit "returns the stored value without running anything" - and `left` is what separates an agent
    that was paid for from one that was dispatched and then torn down when a bound expired.
    """

    def __init__(self) -> None:
        self.entered: list[str] = []
        self.left: list[str] = []


def _rendezvous(record: _Dispatches, barrier: asyncio.Barrier) -> Agent:
    """An agent that cannot finish until another agent has started.

    The whole of the arrangement, and the only shape that can tell overlap from a well-behaved
    sequence. Every scripted agent in this file is dispatched with `task.workspace` pointing at its
    own namespace's checkout, so `workspace.name` is `_base`, `T-01` or `T-02` - the one thing
    reaching a script that says which namespace it is serving, and deliberately not a fingerprint
    term, so two children can be told apart here while hashing identically - the terms are the
    role, the inputs and the starting head, and the namespace is none of them.

    The file each agent writes is named after its own namespace, which is what makes "neither
    child's checkout contains the other's file" answerable: two children sharing a working tree
    would each see both.
    """

    async def _agent(task: AgentTask) -> Reply:
        where = task.workspace.name
        record.entered.append(where)
        await barrier.wait()
        written = task.workspace / "src" / f"{where}.py"
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(f"by {where}\n", encoding="utf-8")
        record.left.append(where)
        return Reply(calls=[Call(REPORT.name, {"text": where})])

    return _agent


def _alone(record: _Dispatches) -> Agent:
    """The same agent with nobody to meet: a barrier of one party is passed by whoever reaches it.

    One script in this file rather than two, so that the chain test below records its dispatches
    through the same object every other test reads, and so that "the agent wrote a file" means the
    same thing everywhere. A rendezvous of one is not a degenerate case being smuggled in - it is
    the arrangement with the second party removed, which is exactly what a test about one namespace
    at a time wants.
    """
    return _rendezvous(record, asyncio.Barrier(1))


class _Relay:
    """Two siblings dispatched at once and **completed** in an order the test chooses.

    The other half of the evidence, and the half a barrier cannot give. A rendezvous proves the two
    children overlap; it says nothing about which of them finishes first, and `test_journal.py`'s
    scoped counter is entirely about that: "a per-invocation counter lets the interleaving decide
    who gets `n = 0`, and the interleaving differs on resume". So the two walks of the replay test
    below are driven through two of these with opposite orders, and the second walk's interleaving
    is provably not the first's rather than being whatever git happened to do twice.

    **The gate is inside the agent and the release is at the call site.** Holding the *worker* is
    what makes a held sibling a step genuinely in flight - its counter is taken, its entry has been
    looked up, its checkout has been restored - rather than one that has not started; and opening
    the next gate only once the previous sibling's `step` has *returned* is what makes the
    completion order a chain rather than a timing. A fixed number of loop turns would not survive
    contact with real git, where one step is half a dozen subprocesses.

    **Only `IMPLEMENT` is gated**, because the priming step below must not be: it runs before the
    gather, sequentially, and a gate on it would hold the second child's priming behind a release
    that only the gather can produce.
    """

    def __init__(self, order: tuple[str, ...]) -> None:
        self.order = order
        self.dispatched: list[str] = []
        """Every dispatch this walk paid for, priming included. Empty is what a replay looks
        like."""

        self.implemented: list[str] = []
        """The gated dispatches only, in the order the loop let them start - which is the order
        they were *dispatched* and not the order they completed."""

        self._gates = {name: asyncio.Event() for name in order}
        self._gates[order[0]].set()

    def script(self) -> Agent:
        """One agent's conduct for both siblings, dispatching on the checkout it was handed."""

        async def _agent(task: AgentTask) -> Reply:
            where = task.workspace.name
            self.dispatched.append(where)
            if task.instructions == IMPLEMENT.instructions:
                self.implemented.append(where)
                await self._gates[where].wait()
                written = task.workspace / "src" / f"{where}.py"
                written.parent.mkdir(parents=True, exist_ok=True)
                written.write_text(f"by {where}\n", encoding="utf-8")
            return Reply(calls=[Call(REPORT.name, {"text": where})])

        return _agent

    def released(self, name: str) -> None:
        """`name`'s step has returned, so let the next sibling's worker go. The last is a no-op."""
        position = self.order.index(name)
        if position + 1 < len(self.order):
            self._gates[self.order[position + 1]].set()


# --- two children that genuinely overlap ---------------------------------------------------------


@pytest.mark.asyncio
async def test_two_children_neither_of_which_can_finish_until_the_other_starts_both_finish(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """Concurrent siblings, arranged so that a lock spanning namespaces cannot pass.

    Two children of one run, cut from one head, running one step each, with an `asyncio.Barrier`
    reached from **inside** each scripted agent: neither returns until the other has been
    dispatched. Under the design both are dispatched at once and the barrier is passed immediately.
    Under a `Journal._running` hoisted to something the whole run shares - or any other lock held
    across a step and not scoped to one namespace - the first child holds it while waiting for a
    second child that is waiting for the lock, and neither ever moves. The failure is a hang, so
    the gather is bounded and the bound expiring *is* the assertion; nothing else in this test can
    tell the two designs apart, which is why every other sibling test in the suite is blind to it.

    **The rest of the assertions are "one file per step, and why".** The two entries are two
    files at two paths, each named by the digest it claims, so "each write is one `os.replace` -
    atomic, no lock, no coordination" is visible as two independent addresses rather than inferred.
    A single `steps.json` would be one path both children had to read, modify and write back under
    a mutex, so the run directory is checked for one. And the two checkouts are asked whether they
    can see each other's work: a working tree is cut per child precisely so that they cannot,
    and two agents sharing one would each be editing the other's files with nothing raising.
    """
    record = _Dispatches()
    run = _run(repository, tmp_path, base, _rendezvous(record, asyncio.Barrier(len(SIBLINGS))))
    children = [run.worktree(name) for name in SIBLINGS]

    try:
        async with asyncio.timeout(_LIVENESS):
            both = await asyncio.gather(
                *(
                    child.step(IMPLEMENT, commit="implement the ticket")
                    for child in children
                )
            )
    except TimeoutError:  # pragma: no cover - the failure this test exists to produce
        pytest.fail(
            f"two children of one run could not both be inside a step at once: after "
            f"{_LIVENESS:g}s the agents dispatched were {record.entered} and the ones that "
            f"finished were {record.left}. Steps serialize **within a namespace** and "
            f"nothing across them - a lock spanning namespaces leaves the second child waiting "
            f"for a first child that is waiting for the second, which is the only real "
            f"concurrency AGL has, deadlocked"
        )

    assert list(both) == [Summary(name) for name in SIBLINGS]
    assert sorted(record.left) == list(SIBLINGS)

    one, two = (_only(tmp_path, "implement", name) for name in SIBLINGS)
    assert one != two, "two concurrent children recorded their step at one path"
    for entry in (one, two):
        assert _field(entry, "fingerprint") == entry.stem, (
            f"{entry} is not named by the digest it claims. The filename **is** the address "
            f"and an entry filed anywhere else is one every future read misses"
        )
    assert _field(one, "head") != _field(two, "head"), (
        "both children recorded the same head, so they did not commit into separate checkouts"
    )
    assert list(_run_dir(tmp_path).rglob("steps.json")) == [], (
        "a shared per-run entry file has appeared: one steps.json 'would need "
        "read-modify-write under a mutex on every completion, serializing something with no reason "
        "to be serial'"
    )

    for name, other in ((SIBLINGS[0], SIBLINGS[1]), (SIBLINGS[1], SIBLINGS[0])):
        checkout = _trees_dir(tmp_path) / name
        assert (checkout / "src" / f"{name}.py").is_file()
        assert not (checkout / "src" / f"{other}.py").exists(), (
            f"{name}'s checkout holds {other}'s file, so the two children are working in one tree "
            f"and every commit either of them makes carries the other's edits"
        )


# --- and the mirror: within one namespace they still serialize ------------------------------------


@pytest.mark.asyncio
async def test_the_rendezvous_two_children_pass_is_one_two_steps_of_a_namespace_cannot_reach(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """"A namespace's workspace is single-threaded", asked with the test above's own barrier.

    The same arrangement over **one** `Run`, where the required answer is the opposite one. The
    standing example gathers two reviewers over one worktree, and what overlapping them costs is
    spelled out: "A's pre-run restore wipes the files B's worker just wrote, B's `commit_all`
    records A's changes under B's message, and A's `head()` after its own commit can read B's" - a
    wrong answer, a mislabelled commit and a corrupted chain, none of which raises and two of which
    leave no trace on the ledger at all. So the two steps must not overlap, so the rendezvous must
    be unreachable, so this test asserts a negative and the wait is how it is proved.

    **Why the negative rather than a recorded sequence.** `test_journal_walk.py::test_two_gathered_
    steps_in_one_namespace_do_not_overlap` already pins the ordered list of workspace calls one
    layer down, and repeating it here would be a second copy of one claim. What this adds is the
    half that list cannot express: the lock is held **across the dispatch**, not merely across the
    restore and the ending, so the second step is not merely ordered after the first - it has not
    started. That is exactly what a rendezvous asks, and it is what makes this the mirror of the
    test above rather than a variation on it: one barrier, two children pass it, two steps of one
    namespace never can.

    `_SERIALIZED` is spent on every green run and its constant says why that is the price of a
    negative. What it is **not** is a race: a barrier two coroutines can reach is reached in
    microseconds, and one they cannot reach is not reached in an hour.
    """
    record = _Dispatches()
    run = _run(repository, tmp_path, base, _rendezvous(record, asyncio.Barrier(2)))

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(_SERIALIZED):
            await asyncio.gather(run.step(REVIEW), run.step(REVIEW))

    assert record.entered == ["_base"], (
        f"the agents dispatched into one namespace were {record.entered}, so both steps were in "
        f"flight at once and the rendezvous was reachable after all. A namespace's "
        f"workspace single-threaded, and two steps overlapping over one checkout is one step "
        f"emptying the working tree the other's agent is editing"
    )
    assert record.left == []
    assert _entries(tmp_path, "review") == [], (
        "a step that was torn down before its worker returned recorded an entry anyway - and a "
        "step is done when its file is there, so a resume would replay a result nobody "
        "produced"
    )


# --- the replay of the concurrent case ------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_siblings_at_one_head_replay_when_the_second_walk_completes_them_the_other_way(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The scoped counter, in the one shape that can fail: two siblings, interleaved twice.

    Both children call `step(IMPLEMENT)` with the same role, no inputs and the same
    parent head, so their `base` values are **identical by construction** - and that is asserted
    rather than assumed, as the sharpest thing available: the two entry files carry the same name.
    A digest is `sha256(base + ":" + n)`, so one filename in two namespaces' directories is one
    `base` and one `n = 0`, and the only thing keeping the two entries apart is the namespace in
    the *path*.

    **The two walks complete the siblings in opposite orders, and that is the whole test.**
    A per-invocation counter "lets the interleaving decide who gets `n = 0`, and the interleaving
    differs on resume, so each child looks in its own scope for a digest that is not there and
    **both re-run, forever, silently**". A counter keyed per `(namespace, step name)` gives both
    children `n = 0` whichever way round they run; a counter keyed per invocation gives the first
    arrival `0` and the second `1`, and reversing the order on the second walk sends each child to
    the address the *other* one used. So the first walk finishes `T-01` then `T-02` and the second
    finishes `T-02` then `T-01`, and a test that always interleaved the same way would be green
    against exactly the design the per-invocation counter was refused for being.

    **The priming step is what makes the order the program's rather than git's.** A counter is taken
    inside `Journal.step` with nothing suspending before it, but the *first* step in a namespace
    reaches that walk through `History.resolve` and `WorkspaceProvider.open` - two subprocesses and
    a cross-process lock - so two first-steps under a `gather` take their addresses in whatever
    order git finished in. Opening both checkouts before the gather - `instruments/replay.py`'s
    siblings programme carries the same paragraph - leaves each
    sibling's `step` running from `gather` to `digest` without a suspension, which makes the
    address order the order the coroutines were created in - the program's own order, and therefore
    reversible on purpose.

    `plan` is read-only, so neither child's head moves and `implement`'s starting head is still the
    parent's for both. That is asserted too: "the same parent head" is half of "identical `base`".
    """
    first = _Relay(SIBLINGS)
    made = await _walk(_run(repository, tmp_path, base, first.script()), first)

    assert made == {name: Summary(name) for name in SIBLINGS}
    assert sorted(first.implemented) == list(SIBLINGS), (
        f"only {first.implemented} reached the gated worker, so the two siblings never overlapped "
        f"and this is a sequence with an `asyncio.gather` around it"
    )
    for name in SIBLINGS:
        assert _field(_only(tmp_path, "plan", name), "head") == base, (
            f"{name}'s read-only priming step moved its chain, so the two children no longer share "
            f"a starting head and `implement`'s bases are not identical for the reason claimed"
        )
    one, two = (_only(tmp_path, "implement", name) for name in SIBLINGS)
    assert one.name == two.name, (
        f"the two siblings recorded `implement` under {one.name} and {two.name}. Same role, no "
        f"inputs, same parent head is one `base` by the fingerprint's own terms, and both are "
        f"the first use of it in their own namespace, so both are `n = 0` and the digests are "
        f"one string"
    )

    second = _Relay(tuple(reversed(SIBLINGS)))
    replayed = await _walk(_run(repository, tmp_path, base, second.script()), second)

    assert replayed == made, (
        "a sibling handed back a different value on the second walk. With the counter keyed per "
        "invocation the reversed order sends each child to the address the other one wrote, which "
        "is a false cache hit rather than a re-run"
    )
    assert second.dispatched == [], (
        f"the second walk paid for {second.dispatched}: each child 'looks in its own scope "
        f"for a digest that is not there and both re-run, forever, silently' - the run still "
        f"finishes and is still right, and the only symptoms are the bill and the wait"
    )
    for step in ("plan", "implement"):
        for name in SIBLINGS:
            assert len(_entries(tmp_path, step, name)) == 1, (
                f"{name}/{step} holds a second entry, so the resume computed an address the first "
                f"walk never wrote to"
            )


async def _walk(run: Run[None], relay: _Relay) -> dict[str, Summary]:
    """One walk of the two-sibling programme, in `relay`'s order, with both checkouts pre-opened.

    Returned keyed by namespace rather than positionally, because the two walks run the siblings in
    opposite orders and a list would compare the first walk's `T-01` against the second's `T-02`.
    """
    children = {name: run.worktree(name) for name in relay.order}
    for name in relay.order:
        # Sequential, awaited, and before the gather - the class docstring and the test's say why.
        await children[name].step(PLAN)

    async def _sibling(name: str) -> tuple[str, Summary]:
        made = await children[name].step(IMPLEMENT, commit="implement the ticket")
        relay.released(name)
        return name, made

    async with asyncio.timeout(_LIVENESS):
        done = await asyncio.gather(*(_sibling(name) for name in relay.order))
    return dict(done)


# --- the chain is not the worktree ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_head_advanced_behind_the_frameworks_back_does_not_move_the_chain(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The load-bearing sentence, provoked with raw git in one process.

    "The starting head is chained logically, not read from disk. It comes from the previous step's
    recorded `head` in that namespace, never from the physical worktree. Otherwise: root runs `spec`
    at H0, children integrate and advance `_base` to H5, and on resume `spec` recomputes against H5,
    mismatches, and re-runs."

    **`integrate()` is the real producer of this state**, and it produces it on every landing
    rather than as an accident: a child merging into the run's branch moves `_base`'s head with no
    step having run and so with nothing journalled. An obligation is attached to that which nothing
    here can discharge - "`IntegrationOutcome.head` carries the value; the engine must write it into
    the parent's chain" - because `integrate()` is not a step, and a parent whose chain still points
    before its landed children would `restore()` past all of them on its next fingerprint miss,
    which is "one of the three paths in the design that destroy work rather than costing a re-run".
    The commit made below with `_git` is that state, arranged by hand where there is no
    `integrate()` to make it for real.

    **The child is the second half and the sharper one.** A run's own step replaying is a claim
    about `Journal._last_good`; a child cut on the *second* walk landing at the same base is a claim
    about `Steps.last_good`, which `run.worktree()` reads synchronously and which could just as
    easily have answered `await workspace.head()`. Cut from the advanced head, the child's first
    fingerprint moves with it and everything under that namespace re-runs - a cascade that starts
    one call away from the thing that moved and looks nothing like it.

    `_git` is for arranging and observing and never for the thing under test, which is why the
    landing is made with it and the replay is asked of `Run`.
    """
    record = _Dispatches()
    run = _run(repository, tmp_path, base, _alone(record))

    await run.step(REVIEW)
    await run.worktree("T-01").step(IMPLEMENT, commit="implement the ticket")
    assert sorted(record.left) == ["T-01", "_base"]
    chained = _field(_only(tmp_path, "review"), "head")
    assert chained == base, "a read-only step moved the run's chain"

    checkout = _trees_dir(tmp_path) / "_base"
    (checkout / LANDED).write_text("from a child that landed\n", encoding="utf-8")
    _git(checkout, "add", "--all")
    _git(checkout, "commit", "-q", "-m", "land T-01")
    advanced = _git(checkout, "rev-parse", "HEAD").strip()
    assert advanced != chained

    resumed = _run(repository, tmp_path, base, _alone(record))
    replayed = await resumed.step(REVIEW)
    child = await resumed.worktree("T-01").step(IMPLEMENT, commit="implement the ticket")

    assert (replayed, child) == (Summary("_base"), Summary("T-01"))
    assert sorted(record.left) == ["T-01", "_base"], (
        "the resume paid for an agent after the run's physical head moved with nothing journalled. "
        "That is the standing example: every step, every resume, forever, with the run still "
        "finishing and still right"
    )
    assert len(_entries(tmp_path, "review")) == 1
    assert len(_entries(tmp_path, "implement", "T-01")) == 1, (
        "the child re-ran, so it was cut from where the run's checkout physically is rather than "
        "from the chain - and every step under that namespace re-fingerprints with it"
    )
    assert _git(checkout, "rev-parse", "HEAD").strip() == advanced, (
        "the landed commit is gone: a step missed its fingerprint and restored the checkout to a "
        "head from before the landing, which is the one path in the design that destroys "
        "work rather than costing a re-run"
    )
