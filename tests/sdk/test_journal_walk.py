"""What the walk promises: a step runs once, and everything after that is a lookup.

The third file over `sdk/_engine/journal.py`. `test_journal.py` holds the fingerprint and
`test_journal_entries.py` holds the file that fingerprint names; this one holds §3.6's loop, which
is the only place the two meet - and the only place a wrong answer is paid for in tokens rather
than in an exception.

**Nothing here is a mock of a workspace.** The bundle is `container.fakes()` - target #8's no
network, no git, no process - so `restore` really empties a real directory and `commit_all` really
records a real state, and every claim below about untracked leavings is a claim about files that
existed. Where a test needs to know what the walk *asked* the workspace to do rather than what came
of it, `_Recorded` wraps the fake and writes the calls down; production code gained no
observability for it.

Three of these tests exist because their failure is silent, and each is written to be the thing
that notices:

  * **`last_good` read from the physical worktree** instead of chained from recorded entries.
    §3.6: root runs `spec` at H0, children integrate and advance the run's own line to H5, and on
    resume `spec` recomputes against H5, misses, and re-runs - every step, every resume, forever,
    with the run still finishing and still right. Two tests come at it from opposite sides: one
    moves the head on behind the journal's back *during* a walk, the other lands three children
    *between* two walks.
  * **The pre-run restore guarded on HEAD.** A crashed read-only step leaves untracked files
    without moving HEAD, so the guard is false at exactly the moment the wipe is needed. The test
    asserts on the *call*, not on the outcome, because a read-only step's own ending restore
    removes the leavings either way and would make an outcome-only test pass against the bug.
  * **The counter taken after a suspension.** Rule 1 makes `n` deterministic for siblings, which
    occupy different namespaces; it does nothing for two same-name steps in *one* scope, which
    share a `(scope, step, base)` key. Two tests again, and the reason there are two is worth
    stating: the `asyncio.gather` test below is the one §3.6's failure is written in, but on its
    own it **cannot fail**, because `asyncio` resumes waiters in FIFO order and FIFO order is
    creation order - a suspension inserted before the counter is taken hands `n = 0` back to the
    same coroutine anyway. So it is joined by `test_the_counter_is_taken_before_the_walk_can_
    suspend`, which drives one `step` coroutine by hand, one send at a time, against dependencies
    that really do suspend, and asks the question directly.

Named `test_journal_walk.py`: `tests/` carries no `__init__.py` - see `tests/conftest.py` for why
it must not - so pytest's module names are the bare filenames and every one has to be unique.
"""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from agl.config import container
from agl.ports.agent import Claude, Restriction, Tool, ToolResult
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import Entry, Fingerprints, Journal, base_of, read_entry

# Every test below is async and marked one by one rather than through a module-level `pytestmark`,
# matching `test_journal_entries.py`: `asyncio_mode = "strict"` turns a missing marker into a test
# pytest silently *skips*, which is how a file like this passes without having awaited anything.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# Three step names, so that a test needing two steps in sequence is not also testing the counter.
SPEC: Final = StepName("spec")
TICKETS: Final = StepName("tickets")
REVIEW: Final = StepName("review")

# The ref the fake repository's seeded state is on, and the file it holds.
MAIN: Final = "main"
SEED: Final[Mapping[str, bytes]] = MappingProxyType({"src/a.txt": b"one\n"})

INSTRUCTIONS: Final = "implement the ticket and leave the tree building"
INPUTS: Final[Mapping[str, object]] = MappingProxyType({"request": "add oauth"})
RESTRICTIONS: Final = frozenset({Restriction.NO_VCS_WRITES})


class _Crash(Exception):
    """What an agent dying mid-step looks like from here. Any exception would do; §3.6's rule is
    that the walk has no opinion about which, and lets it out untouched."""


async def _unused(payload: Mapping[str, JsonValue]) -> ToolResult:
    """No agent runs in this file, so no tool handler is ever called. A `Tool` needs one all the
    same, and `base_of` must keep it out of the fingerprint - `test_journal.py` pins that."""
    return ToolResult(text="")


TOOL: Final = Tool(
    name="report_findings",
    description="report what you found",
    payload_schema=MappingProxyType({"type": "object"}),
    handler=_unused,
)


# --- the harness -------------------------------------------------------------------------------


_Opened = tuple[container.FakeServices, Workspace, str]


async def _opened(root: Path, namespace: Namespace | None = None) -> _Opened:
    """A bundle, one checkout provisioned from `main`, and the commit it starts at.

    The commit and not the ref: `Journal`'s `base` is a resolved commit id, for the reason §3.6
    pins `base_sha` rather than storing a ref name, and `head()` is where a resolved one comes
    from.
    """
    harness = container.fakes(TreesRoot(root / "trees"), files=dict(SEED))
    workspace = await harness.services.workspaces.open(LABEL, namespace, MAIN)
    return harness, workspace, await workspace.head()


def _journal(
    harness: container.FakeServices,
    workspace: Workspace,
    base: str,
    *,
    scope: RunScope = SCOPE,
    fingerprints: Fingerprints | None = None,
) -> Journal:
    """One journal over one namespace. A fresh `Fingerprints` unless a test is sharing one, which
    is what a resume gets: `n` is never persisted, and replay reproduces it by walking the same
    calls in the same order."""
    return Journal(
        harness.services.store,
        scope,
        workspace,
        harness.services.clock,
        Fingerprints() if fingerprints is None else fingerprints,
        base,
    )


async def _step(
    journal: Journal,
    name: StepName,
    worker: Callable[[], Awaitable[JsonValue]],
    *,
    instructions: str = INSTRUCTIONS,
    inputs: Mapping[str, object] = INPUTS,
    commit: str | None = None,
) -> JsonValue:
    """One `Journal.step`, with the role's constituents at a baseline and any of them overridable.

    The role arrives spread across keywords because `Role` does not exist until 12.2; this helper
    is the shape stage 12's `Run.step` will have, one layer up.
    """
    return await journal.step(
        name,
        instructions=instructions,
        model=Claude.SONNET,
        restrictions=RESTRICTIONS,
        tools=(TOOL,),
        inputs=inputs,
        worker=worker,
        commit=commit,
    )


def _digest(
    head: str,
    count: int = 0,
    *,
    instructions: str = INSTRUCTIONS,
    inputs: Mapping[str, object] = INPUTS,
) -> str:
    """The address `_step` writes to, computed the way §3.6 writes it rather than by asking the
    walk. `sha256(base + ":" + str(n))` is spelled out here for `test_journal.py`'s reason: a
    suite that imported the arithmetic would be checking the module against itself."""
    base = base_of(
        instructions=instructions,
        model=Claude.SONNET,
        restrictions=RESTRICTIONS,
        tools=(TOOL,),
        inputs=inputs,
        head=head,
    )
    return hashlib.sha256(f"{base}:{count}".encode()).hexdigest()


async def _entry_at(
    harness: container.FakeServices,
    name: StepName,
    digest: str,
    scope: RunScope = SCOPE,
) -> Entry | None:
    """The entry recorded at this address, or `None`. A thin name for a long expression."""
    return await read_entry(harness.services.store, scope, name, digest)


def _write(workspace: Workspace, name: str, content: bytes) -> None:
    """What an agent does: put a file in the checkout. Nothing here stages or commits anything."""
    target = workspace.path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


class _Worker:
    """A step's worker: counts its runs, does whatever it was given to do, hands back a value.

    `runs` is the whole of what most tests below assert, because "the worker was not called" is
    what a hit *is* - §3.6's replay has no other observable difference from a re-run that happens
    to produce the same answer.
    """

    def __init__(self, value: JsonValue = None, *, does: Callable[[], None] | None = None) -> None:
        self.runs = 0
        self._value = value
        self._does = does

    async def __call__(self) -> JsonValue:
        self.runs += 1
        if self._does is not None:
            self._does()
        return self._value


class _Recorded(Workspace):
    """A `Workspace` that writes down what it was asked to do and delegates the doing.

    In the test suite and not in `Journal`, deliberately: what the walk asks its workspace for is
    a thing to *observe* rather than a thing to expose, and a production hook for it would be a
    surface every future implementation has to keep honest. `head` is not recorded - it is read
    once per step and carries no argument, so recording it would be noise in the one list a test
    reads for ordering.
    """

    def __init__(self, inner: Workspace, calls: list[tuple[str, str]]) -> None:
        self._inner = inner
        self.calls = calls

    @property
    def path(self) -> Path:
        return self._inner.path

    @property
    def branch(self) -> str:
        return self._inner.branch

    async def head(self) -> str:
        return await self._inner.head()

    async def commit_all(self, message: str) -> str:
        self.calls.append(("commit_all", message))
        return await self._inner.commit_all(message)

    async def restore(self, head: str) -> None:
        self.calls.append(("restore", head))
        await self._inner.restore(head)


# --- a miss, and then a hit ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_miss_runs_the_worker_writes_one_entry_and_a_second_walk_hits(
    tmp_path: Path,
) -> None:
    """§3.6's loop in one test: nothing recorded means run it, and recorded means do not."""
    harness, workspace, base = await _opened(tmp_path)
    first = _Worker({"tickets": ["T-01"]})

    value = await _step(_journal(harness, workspace, base), TICKETS, first)

    assert first.runs == 1
    assert value == {"tickets": ["T-01"]}
    assert await _entry_at(harness, TICKETS, _digest(base)) is not None
    # One entry and not two: the counter ticked once, so nothing was written at `n = 1`.
    assert await _entry_at(harness, TICKETS, _digest(base, 1)) is None

    second = _Worker({"tickets": ["this must never be reached"]})
    replayed = await _step(_journal(harness, workspace, base), TICKETS, second)

    assert second.runs == 0, "the entry was on the ledger and the agent was paid for again anyway"
    assert replayed == {"tickets": ["T-01"]}


# --- `last_good` is chained logically ------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_good_is_chained_from_entries_and_never_read_from_the_worktree(
    tmp_path: Path,
) -> None:
    """The failure §3.6 calls load-bearing, staged with a landing arriving mid-walk.

    A child integrating moves the parent's physical head without touching the parent's chain -
    that is precisely why 14.1 owes this module an `advance`. Until then the physical head and
    `last_good` disagree, and a walk that asked the worktree where it was would fingerprint every
    following step against a commit no entry mentions.
    """
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)

    def _edits() -> None:
        _write(workspace, "src/a.txt", b"two\n")

    await _step(journal, SPEC, _Worker(does=_edits), commit="spec")
    after_spec = await workspace.head()
    assert after_spec != base

    # A child lands, behind the journal's back, exactly as `integrate()` will.
    _write(workspace, "src/landed.txt", b"from T-01\n")
    landed = await workspace.commit_all("land T-01")
    assert landed != after_spec

    await _step(journal, TICKETS, _Worker({"tickets": []}))

    chained = await _entry_at(harness, TICKETS, _digest(after_spec))
    assert chained is not None, "`tickets` was fingerprinted against the landing, not the chain"
    assert chained.head == after_spec
    assert await _entry_at(harness, TICKETS, _digest(landed)) is None

    # Another landing, this one between the two walks - so that on the resume below the physical
    # head is a commit that appears in no entry at all.
    _write(workspace, "src/landed-again.txt", b"from T-02\n")
    await workspace.commit_all("land T-02")

    resumed = _journal(harness, workspace, base)
    spec, tickets = _Worker(), _Worker()
    await _step(resumed, SPEC, spec, commit="spec")
    await _step(resumed, TICKETS, tickets)

    assert (spec.runs, tickets.runs) == (0, 0), "a resume re-ran steps that were on the ledger"


@pytest.mark.asyncio
async def test_a_base_that_advanced_between_runs_does_not_invalidate_earlier_steps(
    tmp_path: Path,
) -> None:
    """The same claim from the other side: the world moved, the ledger did not, and neither did
    the answer. Three children land between the two walks and every step still replays."""
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)

    await _step(journal, SPEC, _Worker({"spec": "oauth"}))
    await _step(journal, TICKETS, _Worker({"tickets": ["T-01", "T-02", "T-03"]}))

    for index in range(3):
        _write(workspace, f"src/T-0{index}.txt", b"landed\n")
        await workspace.commit_all(f"land T-0{index}")
    assert await workspace.head() != base

    resumed = _journal(harness, workspace, base)
    spec, tickets = _Worker(), _Worker()

    assert await _step(resumed, SPEC, spec) == {"spec": "oauth"}
    assert await _step(resumed, TICKETS, tickets) == {"tickets": ["T-01", "T-02", "T-03"]}
    assert (spec.runs, tickets.runs) == (0, 0)


# --- the pre-run restore -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_pre_run_restore_is_unconditional_and_not_guarded_on_head(
    tmp_path: Path,
) -> None:
    """A crashed read-only step's leavings, and the guard that would let them through.

    The crashed step wrote a file and did not commit, so HEAD is exactly where it was: a
    `head() != last_good` guard is *false* here, which is the whole of §3.6's argument. The
    assertion is therefore on the call and its position, not on the outcome - the second step is
    read-only and its own ending restore removes the leavings either way, so an outcome-only test
    would pass against the bug it was written for.
    """
    harness, raw, base = await _opened(tmp_path)
    calls: list[tuple[str, str]] = []
    workspace = _Recorded(raw, calls)
    journal = _journal(harness, workspace, base)

    def _leaves_a_mess_and_dies() -> None:
        _write(raw, "scratch/notes.md", b"half a thought\n")
        raise _Crash("the agent died mid-review")

    with pytest.raises(_Crash):
        await _step(journal, REVIEW, _Worker(does=_leaves_a_mess_and_dies))

    # Nothing cleaned up on the way out, and nothing was meant to: the walk has no failure path,
    # 12.1 owns commit-or-wipe "on success and on failure alike", and 12.4 owns the shield a
    # cancelling task needs. What makes the leavings harmless is the *next* step's restore.
    assert (raw.path / "scratch" / "notes.md").is_file()
    assert await raw.head() == base, "the trap only springs when the crashed step left HEAD alone"

    def _marks() -> None:
        calls.append(("worker", "tickets"))

    calls.clear()
    await _step(journal, TICKETS, _Worker({"tickets": []}, does=_marks))

    assert calls == [("restore", base), ("worker", "tickets"), ("restore", base)]
    assert not (raw.path / "scratch" / "notes.md").exists()


# --- the two endings -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_read_only_step_leaves_the_worktree_at_last_good(tmp_path: Path) -> None:
    """`commit=None` is the wipe: a tracked edit reverted, an untracked file gone, HEAD unmoved.

    §3.6 - "a read-only role cannot leave anything behind: not a scratch file, not a cache
    directory, not a partial edit" - and the entry's `head` records that nothing moved.
    """
    harness, workspace, base = await _opened(tmp_path)

    def _edits_and_scribbles() -> None:
        _write(workspace, "src/a.txt", b"two\n")
        _write(workspace, "src/scratch.txt", b"notes\n")

    await _step(
        _journal(harness, workspace, base),
        REVIEW,
        _Worker({"findings": []}, does=_edits_and_scribbles),
    )

    assert (workspace.path / "src" / "a.txt").read_bytes() == b"one\n"
    assert not (workspace.path / "src" / "scratch.txt").exists()
    assert await workspace.head() == base

    entry = await _entry_at(harness, REVIEW, _digest(base))
    assert entry is not None
    assert entry.head == base


@pytest.mark.asyncio
async def test_an_effect_step_records_a_head_that_holds_the_workers_changes(
    tmp_path: Path,
) -> None:
    """`commit=` is the other ending, and the head it produces becomes the chain's next link."""
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)

    def _edits() -> None:
        _write(workspace, "src/a.txt", b"two\n")

    await _step(journal, SPEC, _Worker(does=_edits), commit="implement T-01")

    after = await workspace.head()
    assert after != base
    assert (workspace.path / "src" / "a.txt").read_bytes() == b"two\n"

    effect = await _entry_at(harness, SPEC, _digest(base))
    assert effect is not None
    assert effect.head == after

    # And `last_good` became it: the next step is fingerprinted against `after` and records it.
    await _step(journal, TICKETS, _Worker({"tickets": []}))
    follower = await _entry_at(harness, TICKETS, _digest(after))
    assert follower is not None
    assert follower.head == after


@pytest.mark.asyncio
async def test_changing_only_the_commit_message_does_not_invalidate_the_entry(
    tmp_path: Path,
) -> None:
    """§3.6 keeps the message out of the fingerprint on purpose: "including it would mean editing
    the wording re-runs the agent, which is the opposite of what fingerprinting is for". The trade
    is that the replayed step keeps the commit it already made, message and all."""
    harness, workspace, base = await _opened(tmp_path)

    def edit() -> None:
        _write(workspace, "src/a.txt", b"two\n")

    first = _Worker(does=edit)
    await _step(_journal(harness, workspace, base), SPEC, first, commit="implement T-01")

    second = _Worker(does=edit)
    await _step(
        _journal(harness, workspace, base),
        SPEC,
        second,
        commit="implement T-01: add the oauth callback route",
    )

    assert first.runs == 1
    assert second.runs == 0, "editing a commit message re-ran the agent"


# --- a crash, and the counter --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_crashed_step_leaves_no_entry_and_the_next_attempt_re_runs_it(
    tmp_path: Path,
) -> None:
    """The exception comes out untouched and the ledger is unchanged - "a step is done when its
    file is there", so a step that raised is not done and nothing anywhere says otherwise."""
    harness, workspace, base = await _opened(tmp_path)

    def _dies() -> None:
        raise _Crash("the agent died")

    with pytest.raises(_Crash, match="the agent died"):
        await _step(_journal(harness, workspace, base), SPEC, _Worker(does=_dies))

    assert await _entry_at(harness, SPEC, _digest(base)) is None

    # A resume: a fresh `Fingerprints`, so the same call is `n = 0` again and lands at the same
    # address the crashed attempt would have.
    again = _Worker({"spec": "oauth"})
    assert await _step(_journal(harness, workspace, base), SPEC, again) == {"spec": "oauth"}
    assert again.runs == 1

    entry = await _entry_at(harness, SPEC, _digest(base))
    assert entry is not None
    assert entry.value == {"spec": "oauth"}


@pytest.mark.asyncio
async def test_a_retry_loop_with_nothing_varying_counts_up_and_replays_in_order(
    tmp_path: Path,
) -> None:
    """§3.6's "why the counter": same role, no commits, nothing varying, three times.

    Without `n` the three calls share one digest and the second hits the first's entry forever.
    With it they are `n = 0, 1, 2`, and a resume walking the same three calls in the same order
    reproduces the same three addresses - which is the whole of what "never persisted" buys.
    """
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)
    attempts = [_Worker({"attempt": count}) for count in range(3)]

    for worker in attempts:
        await _step(journal, REVIEW, worker)

    assert [worker.runs for worker in attempts] == [1, 1, 1]
    for count in range(3):
        entry = await _entry_at(harness, REVIEW, _digest(base, count))
        assert entry is not None, f"nothing was recorded at n = {count}"
        assert entry.value == {"attempt": count}

    resumed = _journal(harness, workspace, base)
    replays = [_Worker({"attempt": "must never be reached"}) for _ in range(3)]
    values = [await _step(resumed, REVIEW, worker) for worker in replays]

    assert values == [{"attempt": 0}, {"attempt": 1}, {"attempt": 2}]
    assert [worker.runs for worker in replays] == [0, 0, 0]


# --- the counter is taken before the walk can suspend --------------------------------------------


class _Watching(Fingerprints):
    """A `Fingerprints` that writes down when it was asked, so a test can ask *when*."""

    def __init__(self, taken: list[str]) -> None:
        super().__init__()
        self._taken = taken

    def next(self, scope: RunScope, step: StepName, base: str) -> str:
        self._taken.append(str(step))
        return super().next(scope, step, base)


class _Suspending(Workspace):
    """A workspace whose every awaited member really suspends before it does anything.

    `_FakeWorkspace`'s members do not: they touch a dict and a directory and return without ever
    yielding to the loop, so a walk that awaited one before taking its counter would run straight
    through it and a test driving the coroutine by hand would see nothing. This makes each `await`
    on a workspace a real suspension point, which is what turns the question "is the counter taken
    before the first await" into one a single `send` can answer.
    """

    def __init__(self, inner: Workspace) -> None:
        self._inner = inner

    @property
    def path(self) -> Path:
        return self._inner.path

    @property
    def branch(self) -> str:
        return self._inner.branch

    async def head(self) -> str:
        await asyncio.sleep(0)
        return await self._inner.head()

    async def commit_all(self, message: str) -> str:
        await asyncio.sleep(0)
        return await self._inner.commit_all(message)

    async def restore(self, head: str) -> None:
        await asyncio.sleep(0)
        await self._inner.restore(head)


class _SuspendingStore(Store):
    """The same trick over the ledger, for the same reason: `MemoryStore` never yields either."""

    def __init__(self, inner: Store) -> None:
        self._inner = inner

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        await asyncio.sleep(0)
        return await self._inner.read_record(scope)

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        await asyncio.sleep(0)
        await self._inner.write_record(scope, value)

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        await asyncio.sleep(0)
        return await self._inner.read_entry(scope, step, digest)

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        await asyncio.sleep(0)
        await self._inner.write_entry(scope, step, digest, value)

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        await asyncio.sleep(0)
        return await self._inner.namespaces(scope)

    async def remove(self, scope: RunScope) -> None:
        await asyncio.sleep(0)
        await self._inner.remove(scope)


@pytest.mark.asyncio
async def test_the_counter_is_taken_before_the_walk_can_suspend(tmp_path: Path) -> None:
    """`Fingerprints.next` runs before `step`'s first suspension, asked directly.

    The coroutine is driven by hand, one `send` at a time, against a store and a workspace that
    really do yield. If anything at all is awaited before the counter is taken, the first `send`
    returns with nothing recorded - and that is the precondition `Fingerprints`' own docstring
    states and the reason the gather test below cannot be the only guard: `asyncio` resumes
    waiters in the order they queued, which is creation order, so an inserted suspension hands
    `n = 0` back to the same coroutine and the gather test stays green.
    """
    harness, raw, base = await _opened(tmp_path)
    taken: list[str] = []
    journal = Journal(
        _SuspendingStore(harness.services.store),
        SCOPE,
        _Suspending(raw),
        harness.services.clock,
        _Watching(taken),
        base,
    )

    walking = _step(journal, REVIEW, _Worker({"findings": []}))
    try:
        walking.send(None)
    except StopIteration:  # pragma: no cover - the store suspends, so this cannot complete
        pass
    finally:
        walking.close()

    assert taken == [str(REVIEW)], (
        "the walk suspended before taking its counter, so two same-name steps in one scope have "
        "their `n` decided by the interleaving - and the interleaving differs on resume"
    )


@pytest.mark.asyncio
async def test_two_same_name_steps_in_one_scope_land_at_the_same_digests_either_way(
    tmp_path: Path,
) -> None:
    """Rule 1's blind spot, and what closes it.

    Siblings are deterministic because they occupy different namespaces. Two `step("review", ...)`
    calls in *one* scope with one role and one set of inputs share a `(scope, step, base)` key, so
    only the order the coroutines were created in can decide which gets `n = 0`. The walk is run
    twice with the workers released in opposite orders, and the two entries must hold the same two
    values at the same two addresses both times.
    """
    assert await _gathered(tmp_path / "a", "one") == {0: {"by": "one"}, 1: {"by": "two"}}
    assert await _gathered(tmp_path / "b", "two") == {0: {"by": "one"}, 1: {"by": "two"}}


async def _gathered(root: Path, first: str) -> dict[int, JsonValue]:
    """Two same-name steps under one `gather`, with `first`'s worker released first."""
    harness, workspace, base = await _opened(root)
    journal = _journal(harness, workspace, base)
    gates = {"one": asyncio.Event(), "two": asyncio.Event()}

    def _gated(which: str) -> Callable[[], Awaitable[JsonValue]]:
        async def _worker() -> JsonValue:
            await gates[which].wait()
            return {"by": which}

        return _worker

    walking = asyncio.gather(
        _step(journal, REVIEW, _gated("one")),
        _step(journal, REVIEW, _gated("two")),
    )
    await _settled()
    gates[first].set()
    await _settled()
    gates["two" if first == "one" else "one"].set()
    await walking

    recorded: dict[int, JsonValue] = {}
    for count in (0, 1):
        entry = await _entry_at(harness, REVIEW, _digest(base, count))
        assert entry is not None, f"nothing was recorded at n = {count}"
        recorded[count] = entry.value
    return recorded


async def _settled() -> None:
    """Let every runnable task reach its next suspension. Ten turns is arbitrary and generous;
    the walk suspends once per awaited dependency and there are four of them per step."""
    for _ in range(10):
        await asyncio.sleep(0)


# --- concurrent siblings -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_siblings_each_write_their_own_entry_and_both_replay(
    tmp_path: Path,
) -> None:
    """§3.6's own example: `T-01` and `T-02` both `step("implement", implementer)`.

    Same role, same inputs, same parent head - so identical bases by construction, and the only
    thing separating the two entries is the namespace in the counter's key. One `Fingerprints` is
    shared by both journals, which is what makes that key mean anything: a counter per `Journal`
    would give each child its own ledger of counts and would look identical here while being rule
    1's failure with rule 1's fix removed.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"), files=dict(SEED))
    children = (Namespace("T-01"), Namespace("T-02"))
    workspaces = [
        await harness.services.workspaces.open(LABEL, child, MAIN) for child in children
    ]
    base = await workspaces[0].head()
    assert base == await workspaces[1].head()

    first = await _siblings(harness, children, workspaces, base, order=(0, 1))
    assert first == [{"by": "T-01"}, {"by": "T-02"}]

    for child in children:
        entry = await _entry_at(harness, REVIEW, _digest(base), SCOPE.inside(child))
        assert entry is not None, f"{child} recorded nothing at n = 0 in its own namespace"
        assert entry.value == {"by": str(child)}

    replayed = await _siblings(harness, children, workspaces, base, order=(1, 0), replay=True)
    assert replayed == [{"by": "T-01"}, {"by": "T-02"}]


async def _siblings(
    harness: container.FakeServices,
    children: tuple[Namespace, ...],
    workspaces: list[Workspace],
    base: str,
    *,
    order: tuple[int, int],
    replay: bool = False,
) -> list[JsonValue]:
    """One `gather` over two child journals sharing one counter, released in `order`."""
    counter = Fingerprints()
    journals = [
        _journal(harness, workspace, base, scope=SCOPE.inside(child), fingerprints=counter)
        for child, workspace in zip(children, workspaces, strict=True)
    ]
    gates = [asyncio.Event() for _ in children]
    workers = [_Worker({"by": str(child)}) for child in children]

    def _gated(index: int) -> Callable[[], Awaitable[JsonValue]]:
        async def _worker() -> JsonValue:
            await gates[index].wait()
            return await workers[index]()

        return _worker

    walking = asyncio.gather(*(_step(journals[i], REVIEW, _gated(i)) for i in range(len(children))))
    for index in order:
        await _settled()
        gates[index].set()
    values = await walking

    if replay:
        assert [worker.runs for worker in workers] == [0, 0], "a sibling re-ran on resume"
    return list(values)
