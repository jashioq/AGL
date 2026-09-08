"""What the walk promises: a step runs once, and everything after that is a lookup.

The third file over `sdk/_engine/journal.py`. `test_journal.py` holds the fingerprint and
`test_journal_entries.py` holds the file that fingerprint names; this one holds the loop, which
is the only place the two meet - and the only place a wrong answer is paid for in tokens rather
than in an exception.

**Nothing here is a mock of a workspace.** The bundle is `container.fakes()` - no network, no git,
no process - so `restore` really empties a real directory and `commit_all` really
records a real state, and every claim below about untracked leavings is a claim about files that
existed. Where a test needs to know what the walk *asked* the workspace to do rather than what came
of it, `_Recorded` wraps the fake and writes the calls down; production code gained no
observability for it.

Five of these tests exist because their failure is silent, and each is written to be the thing
that notices:

  * **`last_good` read from the physical worktree** instead of chained from recorded entries.
    Root runs `spec` at H0, children integrate and advance the run's own line to H5, and on
    resume `spec` recomputes against H5, misses, and re-runs - every step, every resume, forever,
    with the run still finishing and still right. Two tests come at it from opposite sides: one
    moves the head on behind the journal's back *during* a walk, the other lands three children
    *between* two walks.
  * **The pre-run restore guarded on HEAD.** A crashed read-only step leaves untracked files
    without moving HEAD, so the guard is false at exactly the moment the wipe is needed. The test
    asserts on the *call*, not on the outcome, because a read-only step's own ending restore
    removes the leavings either way and would make an outcome-only test pass against the bug.
  * **The counter taken after a suspension.** `test_journal.py`'s scoped counter makes `n`
    deterministic for siblings, which occupy different namespaces; it does nothing for two
    same-name steps in *one* scope, which share a `(scope, step, base)` key. Two tests again, and
    the reason there are two is worth stating: the `asyncio.gather` test below is the one that
    failure is written in, and it now catches the serialization too - two overlapping steps take
    one address and the second clobbers the first - but on its own it cannot say *when* the
    address was taken. So it is joined by
    `test_the_counter_is_taken_before_the_walk_can_suspend`, which drives one `step` coroutine by
    hand, one send at a time, against dependencies that really do suspend, and asks directly.
  * **Two steps in one namespace overlapping.** "A namespace's workspace is single-threaded".
    They share one `Workspace`, so overlapped, A's pre-run restore wipes what B's worker has just
    written, B's `commit_all` records A's changes under B's message, and A's `head()` reads B's.
    The test asserts on the *sequence of calls* the walk made, because every one of those outcomes
    is a wrong answer rather than an exception and two of the three are invisible from the ledger.
  * **A step that raised consuming a slot.** "The counter advances when an entry is written,
    not when a step is called". The retry that follows a crash **inside one run** is the only place
    the two readings differ, because a resume rebuilds the counter from nothing either way - so the
    test does its retry against the same `Fingerprints` and asserts the entry landed at `n = 0`,
    which is where the resume below it then looks.

**A sixth is here for the opposite reason: its failure is the loudest thing in this design.**
`advance` is the landing handed back to the parent's chain - one of `ARCHITECTURE.md`'s
"Invariants where a mistake is silent" - and a chain that did not follow a landing means the
parent's next fingerprint miss restores past every child that has landed and cleans the tree of it.
That is not a re-run and not an exception - it is work gone, and one of only two places in AGL
where a mistake costs that. So the test asserts on the *call*: what the walk after an advance asked
its workspace to restore to.

**A seventh is here because two loud failures disagreed with each other.** A lone surrogate in a
step's inputs was refused as malformed input and the same string in its *result* reached the store
and came back as AGL's own bug - exit 2 against exit 70, decided by which field of one step it
arrived in. Both fields are asked in one walk at the bottom of this file, because the disagreement
is only visible when the two answers are put beside each other.

**Two more sit beside it, and together the three are the whole of what `_check_result` refuses.**
A result is a value JSON has to be able to hold, and there are exactly three ways one fails to
survive the round trip: a surrogate in its text, a key that is not a string, and a float that is
not finite. The guard covered the first and passed the other two - the key **silently**, coerced
to its own text by `json.dumps` and landing on the record as something the worker never returned,
which is the only failure in this file that is both invisible and permanent; the float loudly, as
exit 70 for a number a workflow's step chose to return. `_canonical` already refuses all three on
the fingerprint side of the same module, so the pair below is that walker's mirror for the output
side. There is a *fourth* class it deliberately does not refuse - a value that is no JSON type at
all - and the argument for leaving it, together with what leaving it costs, is written out in
`test_a_steps_result_refuses_a_float_json_has_no_spelling_for`'s own docstring, because it is the
same asymmetry that test turns on.

**One last pair is here because a number leaves this loop and is read by a person.** The walk's
hit branch tallies on `Fingerprints`, `api._walk` hands the total back and the CLI prints
`replayed <n> steps from cache`, so what the branch counts is the whole meaning of that line. Both
of the ways it could lie are asserted rather than argued: `claim` runs on both branches, so a tally
sitting there would count misses too, and an entry no walk asked about would inflate the count if
the number came from the ledger instead of from the calls.

Named `test_journal_walk.py`: `tests/` carries no `__init__.py` - see `tests/conftest.py` for why
it must not - so pytest's module names are the bare filenames and every one has to be unique.
"""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final
import pytest
from agl.config import container
from agl.ports.agent import Claude, Restriction, Tool, ToolResult
from agl.ports.errors import InputError, InternalError, exit_code_for
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import Entry, Fingerprints, Journal, base_of, read_entry
from agl.sdk._engine.prompts import composed

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
    """What an agent dying mid-step looks like from here. Any exception would do; the rule is
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

    The commit and not the ref: `Journal`'s `base` is a resolved commit id, for the reason a run
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

    The role arrives spread across keywords because `Role` did not exist yet when this was
    written; this helper is the shape `Run.step` has, one layer up.

    `prompt` is composed here rather than passed, because that is what the layer above does with
    the two terms in front of it: `sdk/_engine/steps.py` builds one string, dispatches it and
    fingerprints it. A helper that spelled some other text would still walk, and every address it
    computed would be one no run has ever written to.
    """
    return await journal.step(
        name,
        instructions=instructions,
        model=Claude.SONNET,
        restrictions=RESTRICTIONS,
        tools=(TOOL,),
        inputs=inputs,
        prompt=composed(instructions, inputs),
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
    """The address `_step` writes to, computed from the arithmetic rather than by asking the
    walk. `sha256(base + ":" + str(n))` is spelled out here for `test_journal.py`'s reason: a
    suite that imported the arithmetic would be checking the module against itself."""
    base = base_of(
        instructions=instructions,
        model=Claude.SONNET,
        restrictions=RESTRICTIONS,
        tools=(TOOL,),
        inputs=inputs,
        prompt=composed(instructions, inputs),
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
    what a hit *is* - replay has no other observable difference from a re-run that happens
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
    """The loop in one test: nothing recorded means run it, and recorded means do not."""
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

# --- the tally, at the one line that tells a hit from a miss -------------------------------------
#
# `Fingerprints.replays` is what `api._walk` hands back and `cli/commands/__init__.py` turns into
# `replayed <n> steps from cache`. It is asserted here because this is the only place a replay is
# discriminated: `claim` is called on both branches, so a tally taken there would count every step
# and the line would be an operator-facing number that is never zero.

@pytest.mark.asyncio
async def test_a_miss_leaves_the_tally_at_nought_and_a_hit_moves_it_by_one(
    tmp_path: Path,
) -> None:
    """The two branches, counted, against the same call made twice.

    Each walk gets a `Fingerprints` of its own, which is what a resume gets: `n` is never
    persisted, so the second walk asks the same address the first one wrote and this time it is
    there.
    """
    harness, workspace, base = await _opened(tmp_path)
    written = Fingerprints()

    await _step(_journal(harness, workspace, base, fingerprints=written), TICKETS, _Worker("one"))

    assert written.replays == 0, "a step that paid for its worker was tallied as one that did not"

    resumed = Fingerprints()
    reached = _Worker("this must never be reached")

    assert await _step(
        _journal(harness, workspace, base, fingerprints=resumed), TICKETS, reached
    ) == "one"

    assert reached.runs == 0
    assert resumed.replays == 1

@pytest.mark.asyncio
async def test_the_tally_counts_steps_served_and_not_entries_the_ledger_happens_to_hold(
    tmp_path: Path,
) -> None:
    """Three entries on the ledger and a walk that asks for two of them: the answer is two.

    The number an operator reads is what *this* walk did not have to pay for, so an entry nothing
    asked about does not belong in it - a workflow that took a branch it did not take last time
    leaves entries behind, and counting them would report work that was never replayed.
    """
    harness, workspace, base = await _opened(tmp_path)
    written = _journal(harness, workspace, base)
    for step in (SPEC, TICKETS, REVIEW):
        await _step(written, step, _Worker(str(step)))

    resumed = Fingerprints()
    walk = _journal(harness, workspace, base, fingerprints=resumed)
    for step in (SPEC, TICKETS):
        await _step(walk, step, _Worker("this must never be reached"))

    assert resumed.replays == 2
    assert await _entry_at(harness, REVIEW, _digest(base)) is not None, (
        "the third entry is what makes this a count of steps asked for rather than of entries"
    )

# --- `last_good` is chained logically ------------------------------------------------------------

@pytest.mark.asyncio
async def test_last_good_is_chained_from_entries_and_never_read_from_the_worktree(
    tmp_path: Path,
) -> None:
    """The load-bearing failure, staged with a landing arriving mid-walk.

    A child integrating moves the parent's physical head without touching the parent's chain -
    that is precisely why this module owes an `advance`. Until it is called the physical head and
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

# --- `advance`: the third writer of the chain ----------------------------------------------------

@pytest.mark.asyncio
async def test_advance_moves_the_chain_to_a_landed_head_and_the_next_restore_keeps_it(
    tmp_path: Path,
) -> None:
    """The landing handed back to the parent's chain, and what forgetting it destroys.

    The same arrangement as the two tests above and the opposite claim, which is the pair worth
    reading together. There a landing arrives behind the journal's back and the chain must *not*
    follow it, because nothing told the journal it happened. Here the engine says so, and everything
    after has to be against the landed commit.

    Two assertions and the second is the one with money in it. The next step being fingerprinted
    from `landed` is what a reader expects; the next step's **pre-run restore** targeting `landed`
    is what keeps the landed work in the tree, because that restore is `reset --hard` and
    `clean -fd` and it runs unconditionally on every miss. Aimed one commit back, it takes every
    child that has landed with it.
    """
    harness, raw, base = await _opened(tmp_path)
    calls: list[tuple[str, str]] = []
    workspace = _Recorded(raw, calls)
    journal = _journal(harness, workspace, base)

    def _edits() -> None:
        _write(raw, "src/a.txt", b"two\n")

    await _step(journal, SPEC, _Worker(does=_edits), commit="spec")
    after_spec = await raw.head()

    # What `integrate()` does: a child's work lands in this checkout, and the engine hands the chain
    # the head the integrator reported. `IntegrationOutcome.head` is exactly this value.
    _write(raw, "src/landed.txt", b"from T-01\n")
    landed = await raw.commit_all("land T-01")
    assert landed != after_spec

    journal.advance(landed)
    assert journal.last_good == landed

    calls.clear()
    await _step(journal, TICKETS, _Worker({"tickets": []}))

    chained = await _entry_at(harness, TICKETS, _digest(landed))
    assert chained is not None, "the step after a landing was fingerprinted against the old chain"
    assert chained.head == landed
    assert calls[0] == ("restore", landed), (
        f"the pre-run restore targeted {calls[0][1]!r}, a commit from before the landing: that is "
        f"`reset --hard` and `clean -fd` over every child that had landed, which is one of the "
        f"three paths in this design that destroy work rather than costing a re-run"
    )
    assert (raw.path / "src" / "landed.txt").read_bytes() == b"from T-01\n"

@pytest.mark.asyncio
async def test_advance_writes_no_entry_and_a_second_walk_starts_from_the_ledger(
    tmp_path: Path,
) -> None:
    """Nothing journals an integration, and a resume is where that shows.

    There is no fingerprint over a landing and no file under `steps/` for one - "a resumed run must
    be able to find a hold it did not take" is the same gap named from the other side. So the chain
    this call moves lives exactly as long as the process: a second walk opens at the base it was
    given and replays forward out of the entries, and the entry written *before* the landing still
    hits, because a landing changed nothing any digest was taken over.
    """
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)

    await _step(journal, SPEC, _Worker({"spec": "oauth"}))

    _write(workspace, "src/landed.txt", b"from T-01\n")
    landed = await workspace.commit_all("land T-01")
    journal.advance(landed)

    resumed = _journal(harness, workspace, base)
    assert resumed.last_good == base, "a landing left something on the ledger for a resume to read"

    spec = _Worker()
    assert await _step(resumed, SPEC, spec) == {"spec": "oauth"}
    assert spec.runs == 0, "the entry recorded before the landing stopped replaying after it"

@pytest.mark.asyncio
async def test_advance_refuses_an_empty_head_and_leaves_the_chain_where_it_was(
    tmp_path: Path,
) -> None:
    """The constructor's refusal one moment later and in its register: an empty string names no
    commit, and this one would be handed to `restore` and hashed into every fingerprint after it.
    `IntegrationOutcome` spells "it did not land" as a conflict and never as an empty head, so
    nothing honest gets here with one."""
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)

    with pytest.raises(InternalError, match="empty head"):
        journal.advance("")

    assert journal.last_good == base

# --- the pre-run restore -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_pre_run_restore_is_unconditional_and_not_guarded_on_head(
    tmp_path: Path,
) -> None:
    """A crashed read-only step's leavings, and the guard that would let them through.

    The crashed step wrote a file and did not commit, so HEAD is exactly where it was: a
    `head() != last_good` guard is *false* here, which is the whole of the argument. The
    assertion is therefore on the call and its position, not on the outcome - the second step is
    read-only and its own ending restore removes the leavings either way, so an outcome-only test
    would pass against the bug it was written for.

    **The leavings are put back by hand, and that is not the test cheating.** The walk has a
    failure path, so the crashed step's own ending wipe takes them on the way out - which is
    asserted below, in passing. What reaches the next step is what a killed *process* leaves: a
    kill runs no `finally`, so a checkout can start a step dirty with HEAD unmoved whatever this
    walk does, and that is the state the pre-run restore exists for. Staging it explicitly is what
    keeps this test about the guard rather than about which of two wipes happened to run first.
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

    assert not (raw.path / "scratch" / "notes.md").exists(), (
        "the step that raised left its scratch file behind: the wipe runs on success and on "
        "failure alike, or a failed reviewer contaminates the checkout its own retry works in"
    )
    _write(raw, "scratch/notes.md", b"half a thought\n")
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

    The claim: "a read-only role cannot leave anything behind: not a scratch file, not a cache
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
    """The message is kept out of the fingerprint on purpose: "including it would mean editing
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
async def test_a_step_that_raised_claims_no_slot_and_its_retry_lands_at_n_zero(
    tmp_path: Path,
) -> None:
    """The rule: "the counter advances when an entry is written, not when a step is called".

    The retry here is inside **one** walk, against the `Fingerprints` the crashed attempt already
    used, and that is the only arrangement in which the two readings differ: a resume rebuilds the
    counter from nothing whatever the rule is, so a test that retried in a second walk could not
    tell them apart. Advance on the call and the retry's entry lands at `n = 1`; the resume then
    walks these same calls, asks for `n = 0`, finds nothing there, and pays for the step again -
    silently, with the run still finishing and still right.

    Both ends are asserted, because only the pair is the claim: the entry is at `n = 0`, nothing is
    at `n = 1`, and a fresh walk of the same call hits it.
    """
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)

    def _dies() -> None:
        raise _Crash("the agent died mid-spec")

    crashed = _Worker(does=_dies)
    with pytest.raises(_Crash):
        await _step(journal, SPEC, crashed)

    retried = _Worker({"spec": "oauth"})
    assert await _step(journal, SPEC, retried) == {"spec": "oauth"}
    assert (crashed.runs, retried.runs) == (1, 1), "the retry did not reach its worker"

    entry = await _entry_at(harness, SPEC, _digest(base))
    assert entry is not None, (
        "nothing is recorded at n = 0, so the attempt that raised consumed the slot - and the "
        "resume below walks the same calls, asks for n = 0 and pays for the step a second time"
    )
    assert entry.value == {"spec": "oauth"}
    assert await _entry_at(harness, SPEC, _digest(base, 1)) is None, (
        "the retry was recorded at n = 1, one slot past where any resume will look for it"
    )

    resumed = _Worker({"spec": "must never be reached"})
    assert await _step(_journal(harness, workspace, base), SPEC, resumed) == {"spec": "oauth"}
    assert resumed.runs == 0, "a resume re-ran a step whose entry was on the ledger"

@pytest.mark.asyncio
async def test_a_retry_loop_with_nothing_varying_counts_up_and_replays_in_order(
    tmp_path: Path,
) -> None:
    """Why the counter: same role, no commits, nothing varying, three times.

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
    """A `Fingerprints` that writes down when it was asked, so a test can ask *when*.

    `digest` and not `claim`: the question is when the walk takes its **address**, which is the
    call that has to happen before anything can suspend. The claim comes a whole step later by
    design, and a test that watched it would be asking about the other end of the method.
    """

    def __init__(self, taken: list[str]) -> None:
        super().__init__()
        self._taken = taken

    def digest(self, scope: RunScope, step: StepName, base: str) -> str:
        self._taken.append(str(step))
        return super().digest(scope, step, base)

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
    """`Fingerprints.digest` runs before `step`'s first suspension, asked directly.

    The coroutine is driven by hand, one `send` at a time, against a store and a workspace that
    really do yield. If anything at all is awaited before the address is taken, the first `send`
    returns with nothing recorded - and that is the precondition `Fingerprints`' own docstring
    states. Note that the walk now acquires a lock first: an *uncontended* `asyncio.Lock.acquire`
    returns without yielding, which is why this still answers in one `send`, and a lock that did
    suspend on the empty case would be caught here.

    The gather test below cannot be the only guard, because serialization already makes the order
    of two same-name steps deterministic - but by way of `asyncio`'s FIFO wake order, which is a
    property of the runtime rather than of this design. Taking the address before anything can
    suspend is what makes the order the program's own without asking the runtime for anything.
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
    """The blind spot in `test_journal.py`'s scoped counter, and what closes it.

    Siblings are deterministic because they occupy different namespaces. Two `step("review", ...)`
    calls in *one* scope with one role and one set of inputs share a `(scope, step, base)` key, so
    the scope separates nothing here at all. What separates them is that they do not overlap: the
    walk serializes steps within a namespace, so the second call takes its address only after the
    first has claimed its entry, and the two addresses fall out in the order the coroutines were
    created - which is the program's own order and is the same on every run.

    The walk is run twice with the workers released in opposite orders, and the two entries must
    hold the same two values at the same two addresses both times. Releasing the *second* worker
    first is the case worth having: under serialization that gate is opened onto a step which has
    not started, and the ledger is still the program's order rather than the release order. Without
    the serialization the two take one address between them and the second entry clobbers the
    first, which is what the `is not None` inside `_gathered` notices.
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

# --- a namespace's workspace is single-threaded --------------------------------------------------

@pytest.mark.asyncio
async def test_two_gathered_steps_in_one_namespace_do_not_overlap(tmp_path: Path) -> None:
    """The rule "the framework serializes steps within a namespace", asked of the calls themselves.

    Two steps under one `gather` over one `Journal` share one `Workspace`, and the standing
    example gathers two reviewers over one worktree. Overlapped, A's pre-run restore wipes the
    files B's worker has just written, B's `commit_all` records A's changes under B's message, and
    A's `head()` after its own commit reads B's - a wrong answer, a mislabelled commit and a
    corrupted chain, none of which raises and two of which leave no trace on the ledger at all. So
    the assertion is on the *sequence*: restore, worker, restore, and only then the second step's.

    **The dependencies really suspend**, which is what makes this able to fail. `_FakeWorkspace`
    and `MemoryStore` return without ever yielding, so two tasks over them run to completion one
    after the other whatever `Journal` does, and a test against them would pass against no lock at
    all. `_Suspending` and `_SuspendingStore` put a real suspension at every awaited dependency,
    which is where an unserialized walk hands the loop to its sibling.

    The two steps take **different inputs** on purpose: two addresses, one per step, so that this
    test is about overlap and the counter is the business of the two tests above it.
    """
    harness, raw, base = await _opened(tmp_path)
    calls: list[tuple[str, str]] = []
    workspace = _Recorded(_Suspending(raw), calls)
    journal = Journal(
        _SuspendingStore(harness.services.store),
        SCOPE,
        workspace,
        harness.services.clock,
        Fingerprints(),
        base,
    )

    def _working(which: str) -> Callable[[], Awaitable[JsonValue]]:
        async def _worker() -> JsonValue:
            await asyncio.sleep(0)
            calls.append(("worker", which))
            await asyncio.sleep(0)
            return {"by": which}

        return _worker

    await asyncio.gather(
        _step(journal, REVIEW, _working("one"), inputs={"which": "one"}),
        _step(journal, REVIEW, _working("two"), inputs={"which": "two"}),
    )

    assert calls == [
        ("restore", base),
        ("worker", "one"),
        ("restore", base),
        ("restore", base),
        ("worker", "two"),
        ("restore", base),
    ], (
        "two steps in one namespace overlapped: one step's restore landed between the other's "
        "restore and its worker, or between its worker and its ending wipe. They share a "
        "`Workspace`, so that is one step emptying the checkout another is working in"
    )

# --- concurrent siblings -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_siblings_each_write_their_own_entry_and_both_replay(
    tmp_path: Path,
) -> None:
    """The concurrent example: `T-01` and `T-02` both `step(implementer)`.

    Same role, same inputs, same parent head - so identical bases by construction, and the only
    thing separating the two entries is the namespace in the counter's key. One `Fingerprints` is
    shared by both journals, which is what makes that key mean anything: a counter per `Journal`
    would give each child its own ledger of counts and would look identical here while being the
    failure behind `test_journal.py`'s scoped counter, with that rule's fix removed.
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

# --- a step's result is stored text too -----------------------------------------------------------

@pytest.mark.asyncio
async def test_a_steps_result_answers_a_lone_surrogate_the_way_its_inputs_do(
    tmp_path: Path,
) -> None:
    """The second seam of the refusal `test_journal.py`'s surrogate test settled at the first.

    A lone surrogate is a `str` Python admits and UTF-8 cannot encode at all, and it reaches AGL
    from outside: `sys.argv` is decoded with `surrogateescape`, so one undecodable byte on a
    command line mints exactly one, and an agent's tool payload - which is what a step's result
    generally is - is the other door. That makes it malformed **input**, exit 2. Exit 70 tells
    whoever hit it to file a bug against AGL, when what is broken is their data.

    A step's inputs already answered that way: they go through `base_of` -> `_canonical` ->
    `_checked_text`, and are refused before the worker is ever called. Its **result** did not. It
    went into `Entry(value=result, ...)` untouched and on to `store.write_entry`, where `_encoded`'s
    `text.encode("utf-8")` raises `UnicodeEncodeError` - a `ValueError`, which both stores translate
    into `InternalError`. Same string, one field over, 70 instead of 2, decided by nothing but which
    argument of one `step` call it arrived in. Both fields are asked here in one walk, because that
    is the only place the two answers stand beside each other.

    The exit code is asserted against the literal 2 on each side rather than the two sides being
    compared to each other, for `test_journal.py`'s reason: equality alone stays green on the day
    both drift together.

    **The result is not passed through `_canonical`, and the second half of this test is why.** The
    fingerprint's walker also carries `_checked_key`'s reservation of `__agl_type__`, and a result
    is not fingerprinted - it is stored and handed straight back - so nothing there can collide with
    a dataclass's tag and the reservation would refuse a mapping for a reason that is not true of
    it. So a result carrying that key is recorded and replayed, and asserting it is what holds still
    the thing this refusal is not about.

    The refusal is in `Journal.step` and not in `Entry.__post_init__` or in `write_entry`, which is
    why this file holds the test rather than `test_journal_entries.py`. `Entry` is also built by
    `Entry.from_json`, from documents already on disk, and a surrogate coming back *off* a store is
    not malformed input - it is a store that wrote something it should have refused, which is a
    different verdict and a different exit code. `Journal.step` is the one place that knows a worker
    just produced this value, which is the same place its inputs are refused.

    The surrogate is buried under a key and an index rather than sitting at the top of the result: a
    check that only inspected a bare string result would pass a shallow test and admit every shape
    an agent actually returns. `chr(0xD800)` and not the escape `"\\ud800"`, and inside the function
    body - the comment above `test_journal.py`'s `_LONE_SURROGATE` records why a module-level
    `Final` holding one crashes `mypy --strict` outright, with an `INTERNAL ERROR` naming no file.
    """
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)
    lone = chr(0xD800)

    refused_early = _Worker({"this must never be reached": True})
    with pytest.raises(InputError, match="surrogate") as inputs_said:
        await _step(journal, SPEC, refused_early, inputs={"request": lone})
    assert refused_early.runs == 0, (
        "the inputs are refused before the worker is called, which is the whole value of checking "
        "them at the fingerprint - this walk paid an agent for a step it could never record"
    )

    produced = _Worker({"tickets": [{"title": lone}]})
    with pytest.raises(InputError, match="surrogate") as result_said:
        await _step(journal, TICKETS, produced)
    assert produced.runs == 1, "the result is only knowable after the worker has returned it"

    for field, caught in (("inputs", inputs_said), ("result", result_said)):
        assert exit_code_for(caught.value) == 2, (
            f"a lone surrogate in a step's {field} answered with exit "
            f"{exit_code_for(caught.value)}. Both fields answer 2: the string came from outside - "
            f"an undecodable byte on a command line, a value an agent produced - so it is bad "
            f"input, and 70 sends whoever hit it to file a bug against AGL instead of fixing it"
        )

    assert "share a fingerprint" in str(inputs_said.value), (
        "the inputs' refusal no longer says what a surrogate costs *there* - two inputs collapsing "
        "to one canonical text, and one step replaying the other's recorded result"
    )
    assert "the store refuses the write" in str(result_said.value), (
        "the result's refusal no longer says what a surrogate costs *here* - a store that cannot "
        "encode the document, refused at the call that still knows a worker handed it over"
    )
    assert "step tickets's result.tickets[0].title" in str(result_said.value), (
        "the refusal does not name the path it walked to. A result is a whole document an agent "
        "produced, and 'somewhere in it' is not a thing anyone can go and fix"
    )

    assert await _entry_at(harness, TICKETS, _digest(base)) is None, (
        "a refused result still left an entry on the ledger, so a resume would replay a value "
        "AGL had just declared unwritable"
    )

    tagged: JsonValue = {"__agl_type__": "notes.Finding", "id": "T-01"}
    assert await _step(journal, REVIEW, _Worker(tagged)) == {
        "__agl_type__": "notes.Finding",
        "id": "T-01",
    }, "a result carrying the key a dataclass is tagged with was refused or rewritten"

    never = _Worker({"this must never be reached": True})
    assert await _step(_journal(harness, workspace, base), REVIEW, never) == {
        "__agl_type__": "notes.Finding",
        "id": "T-01",
    }
    assert never.runs == 0, (
        "the reserved key did not survive the round trip through the store. `__agl_type__` is "
        "reserved in the *fingerprint*, where a mapping spelling it would canonicalise to the same "
        "text as some dataclass; a result is neither canonicalised nor compared, so that "
        "reservation has no meaning here and would refuse a document for a reason untrue of it"
    )

@pytest.mark.asyncio
async def test_a_steps_result_refuses_a_key_the_encoder_would_rename(tmp_path: Path) -> None:
    """The worst failure shape this codebase has a name for: silent, and it lands on the record.

    `json.dumps({1: "x"})` is `{"1": "x"}`. The encoder *coerces* a non-string key to its own text
    rather than refusing it, so `{None: "z"}` is written `"null"`, `{2.5: "y"}` is written `"2.5"`
    and `{True: "t"}` is written `"true"`. Nothing raises and no exit code is wrong. The ledger
    simply ends up holding a value the worker never produced - and because a hit returns the
    recorded value untouched, every resume from then on hands that one back in its place, for the
    life of the run directory.

    **The guard already visited the key and had nothing to say about it.** `_check_result` recurses
    into `_check_result(key, f"the key {key!r} in {where}")`, but the only question it asked of a
    string was whether it held a surrogate, so a key that was not a string matched no branch at all
    and fell out of the walk. Both of AGL's other two key checkers refuse one already -
    `ports/run.py::_checked_key` for a run record's params, `journal.py::_checked_key` for a step's
    fingerprint - and each says the same sentence about renaming. The result path was the third,
    and it was the one that did not, so one value reached three different verdicts depending on
    which argument of `step` it arrived in.

    `InputError`, exit 2, for the reason the surrogate test above gives at length: a result is what
    an agent produced, and a key JSON cannot spell is that data being wrong, not AGL being broken.

    The mapping is buried under a key and an index rather than sitting at the top of the result,
    for that test's reason too - a check that only inspected a bare top-level mapping would pass a
    shallow test and admit every shape an agent actually returns.
    """
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)

    assert json.dumps({1: "x"}) == '{"1": "x"}', (
        "the premise of this test: `json` renames a non-string key instead of refusing it. If "
        "this ever fails, the encoder started refusing and the guard below is arguing for nothing"
    )

    produced = _Worker({"tickets": [{1: "x"}]})  # type: ignore[dict-item]
    with pytest.raises(InputError, match="keyed by") as caught:
        await _step(journal, TICKETS, produced)
    assert produced.runs == 1, "the result is only knowable after the worker has returned it"
    assert exit_code_for(caught.value) == 2, (
        f"a key JSON has no spelling for came back with exit {exit_code_for(caught.value)}. It is "
        f"a value an agent produced, and 70 sends whoever hit it to file a bug against AGL"
    )
    assert "step tickets's result.tickets[0]" in str(caught.value), (
        "the refusal does not name the path it walked to. A result is a whole document an agent "
        "produced, and 'somewhere in it' is not a thing anyone can go and fix"
    )
    assert "rename" in str(caught.value), (
        "the refusal no longer says what happens to the key. That it would be *renamed* rather "
        "than rejected is the entire reason this is refused here instead of at the store"
    )
    assert await _entry_at(harness, TICKETS, _digest(base)) is None, (
        "a refused result still left an entry on the ledger, so a resume would replay a value "
        "AGL had just declared it could not write down"
    )

    for key in (None, 2.5, True, ()):
        rejected = _Worker({"row": {key: "v"}})  # type: ignore[dict-item]
        with pytest.raises(InputError, match="keyed by"):
            await _step(_journal(harness, workspace, base), REVIEW, rejected)

    kept: JsonValue = {"1": "x", "null": "z", "true": "t"}
    assert await _step(_journal(harness, workspace, base), SPEC, _Worker(kept)) == kept, (
        "the strings those keys would have been coerced *to* are ordinary keys and must still "
        "record - the rule is the type of the key, not its spelling"
    )

@pytest.mark.asyncio
async def test_a_steps_result_refuses_a_float_json_has_no_spelling_for(tmp_path: Path) -> None:
    """The third class, and the one the type system cannot see.

    `float` is a member of `JsonValue`, so a workflow whose step returns `float("nan")` type-checks
    clean under `mypy --strict`. It then reached `adapters/filesystem/_documents.py`'s `_encoded`,
    whose `json.dumps(..., allow_nan=False)` raises `ValueError`, which both stores translate into
    `InternalError` - **exit 70**, this codebase's "AGL's own bug" (`ports/errors.py::EXIT_CODES`),
    for a number a workflow's own step handed over. Nothing about that is AGL's bug, and 70 sends
    the wrong person looking.

    `_canonical` answers the identical value with `InputError` and exit 2 - the same `isfinite`
    call, seventy lines up the same module - because a step fingerprinted with a NaN could never
    match the entry it wrote. The output side had no clause at all. It has the same verdict now,
    for its own reason: the entry cannot be written, and the caller here still knows a worker
    produced the number.

    `allow_nan=False` is what makes this an exception rather than a silent corruption, and it is
    the store's choice rather than `json`'s default: left alone, `json` writes the bare tokens
    `NaN` and `Infinity`, which are not JSON and which no other reader accepts - so the entry would
    be a file AGL had written and could not load back. Both stores set it; `tests/adapters/
    test_store_parity.py` is where that pair is held together.

    **And the value really does arrive from outside, which is what settles the exit code.**
    `json.loads` accepts those same bare tokens *on the way in* - `json.loads('{"score": NaN}')`
    hands back `float("nan")` without complaining - and `adapters/openai/_session.py` reads the
    Codex CLI's frames with a plain `json.loads`. So a model that answers a reporting tool with
    `"score": NaN` mints one of these through a real adapter, and it lands in `_Capture._payload`,
    which is a step's result verbatim. Both port fakes round-trip their payload through
    `json.dumps(..., allow_nan=False)` and refuse it there, which is exactly why a suite driven on
    fakes could not see this seam and why this test drives the worker directly.

    **A fourth class exists, it is not refused, and this is where that is written down** so it is
    not re-proposed as an oversight. A result that is no JSON type at all - a `set`, a `datetime`,
    an arbitrary object - reaches the store too and exits 70 too. It stays unrefused, and the
    argument is this docstring's first paragraph read backwards.

    *The types cover it and did not cover NaN, which is the whole of it.* `float` is a member of
    `JsonValue`, so `mypy --strict` waves a NaN through; a `set` it refuses at the declaration. A
    runtime guard earns its place where the type checker cannot see, and here it can.

    *The only producer is a consumer nobody has written.* Every route to `Entry.value` in this
    repository is checked - `_Capture._payload` is a `dict[str, JsonValue]` built from the
    `Mapping[str, JsonValue]` a `Tool` handler is handed - so a `set` arrives here only out of a
    third-party `AgentRunner` violating its own declared port type. A clause written for a caller
    that does not exist yet is the same mistake as a clause kept for one that has gone, and this
    build removes those; the rule has to cut both ways or it is not a rule.

    *And the failure is already loud and already points the right way.* The store names the type
    and says "something above this port handed it one that is not". What it lacks is the walked
    path and the step's name - a better message, not a missed defect. Exit 70 is honest for it,
    because the thing that broke really is code violating a declared contract, and `_checked_json`
    in `ports/run.py` already gives the identical class that identical verdict for a run record's
    params.

    **The price is real and is not hidden.** `_check_result`'s branches are not exhaustive and are
    not claimed to be: `None`, a `bool` and an `int` fall out of every one of them into silence,
    deliberately, and so does everything else. Closing the fourth class means turning that chain
    into a match with an `else` that raises, which first has to let those three out by name - which
    is `_canonical`'s opening line, one walker up the same module. That is the shape to write on
    the day the argument above stops holding, and that day is the day somebody ships an
    `AgentRunner` this repository does not type-check.

    All three non-finite spellings, because `isfinite` is one call and "we tested NaN" is how
    `inf` gets through a hand-written check that compared a value with itself.
    """
    harness, workspace, base = await _opened(tmp_path)
    journal = _journal(harness, workspace, base)

    produced = _Worker({"tickets": [{"score": float("nan")}]})
    with pytest.raises(InputError, match="no spelling for") as caught:
        await _step(journal, TICKETS, produced)
    assert produced.runs == 1, "the result is only knowable after the worker has returned it"
    assert exit_code_for(caught.value) == 2, (
        f"a non-finite float in a step's result came back with exit "
        f"{exit_code_for(caught.value)}. 70 is where this started - the store refusing a document "
        f"and reporting it as AGL's own failure - and it is the number being complained about"
    )
    assert "step tickets's result.tickets[0].score" in str(caught.value), (
        "the refusal does not name the path it walked to, which is the field somebody has to go "
        "and change"
    )
    assert await _entry_at(harness, TICKETS, _digest(base)) is None, (
        "a refused result still left an entry on the ledger, so a resume would replay a value "
        "AGL had just declared it could not write down"
    )

    for spelling in (float("nan"), float("inf"), float("-inf")):
        bare = _Worker(spelling)
        with pytest.raises(InputError, match="no spelling for"):
            await _step(_journal(harness, workspace, base), REVIEW, bare)
        nested = _Worker(["ok", {"deep": [spelling]}])
        with pytest.raises(InputError, match="no spelling for"):
            await _step(_journal(harness, workspace, base), REVIEW, nested)

    finite: JsonValue = {"ratio": 0.5, "big": 1e300, "negative_zero": -0.0, "whole": 4}
    assert await _step(_journal(harness, workspace, base), SPEC, _Worker(finite)) == finite, (
        "a finite float is an ordinary result and must still record - the rule is `isfinite`, not "
        "a refusal of the float type, and a workflow reporting a score is entitled to one"
    )
