"""The lease, driven directly, because through `run.integrate()` it cannot be seen at all.

`Leases.claim` takes two locks of identical granularity and holds them for exactly the same span:
the lease, keyed by the target's `RunScope`, and the target namespace's step lock, taken through
`Journal.exclude_steps()`. One namespace has one `Journal`, so per-target and per-journal are the
same partition of the world - and every exclusion `test_run_integrate.py` and
`test_integrate_acceptance.py` assert is therefore provided **by either lock alone**. Replace the
per-target lookup in `claim` with a fresh `asyncio.Lock()` built on every call, so that the lease
serialises nothing whatever, and both of those files stay green.

**So this file is the one arrangement that separates them**, and it is not a `Run` arrangement:
one `Leases`, and two *different* `Journal` objects over one `RunScope`. `Steps` cannot produce
that - it opens a namespace once under `_opening` and hands the same pair back forever, and
`Journal.__init__` says in as many words that two journals over one scope would be "two locks over
one namespace, which is not a lock at all". That is exactly why it isolates the lease: with two step
locks in play the step lock excludes nothing, so a second claim that waits is a second claim the
*lease* is holding, and a second claim that completes is a lease that is not there.

**Its own module rather than a section of `test_run_integrate.py`**, for that file's own stated
subject: it is "the suite over `sdk/_engine/integration.py` and over the half of `sdk/workflow.py`
that reaches it", and every arrangement in it is a workflow calling `run.integrate()`. Everything
below constructs `Leases`, `Journal` and `RunScope` by hand and never opens a `Run` - except the
last test, which needs a landing and says why. A section carrying two invented `Journal`s inside a
file whose premise is that a namespace has one would read as an inconsistency rather than as the
instrument it is.

The rest of what `Leases`' docstrings argue is pinned here too, none of it having had a test before:
one lock per target, kept for the life of the run; a released lease evicted from the live table;
`release_all` giving back every live lease; and claims into different targets not blocking each
other, which is "a human deliberating in one run never blocks another" at the smallest scale
it has.
"""

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Final
import pytest
from agl.config import container
from agl.ports.agent import AgentTask, Claude, Restriction
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace
from agl.sdk._engine.integration import Integration, Leases
from agl.sdk._engine.journal import Fingerprints, Journal
from agl.sdk.roles import Role, role
from agl.sdk.testing import Agent, Reply
from agl.sdk.workflow import Run

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")

# The two targets. A lease is keyed by a `RunScope`, and these are the two shapes one run holds:
# the run's own namespace, which is what every child lands into, and a nested one, which is what a
# child that has children of its own is. Equal scopes are the same target and nothing else is, so
# these two are as different as any two targets in AGL ever get.
SCOPE: Final = RunScope(PROJECT, LABEL)
NESTED: Final = SCOPE.inside(Namespace("T-01"))

TICKET: Final = "T-01"
SEEDED: Final = "src/a.txt"
SEED: Final = b"the user's own work\n"
LANDED: Final = "src/first.py"

# How long something that should not be waiting is given before the test calls it a lease nobody
# gave back. Never spent on a green run - every claim below that should complete completes in
# microseconds - so all it trades away is how long a stranded lease takes to say so.
_LIVENESS: Final = 30.0

# How long a claim that should be queued is watched before the test concludes that it really is
# waiting. Spent on every green run, because the wait is the proof. Short, because what it has to
# outlast is a handful of dispatches against in-memory fakes, and long, because a bound that fired
# before a claim could reach its first `await` would pass against the very implementation it is
# written to catch.
_SERIALIZED: Final = 1.0

# --- the instrument: a bundle, a checkout, and journals built by hand over one scope --------------

async def _opened(tmp_path: Path) -> tuple[container.FakeServices, Workspace, str]:
    """A fakes bundle, the run's own checkout, and the resolved commit it starts at.

    The commit and not the ref, for `Journal`'s reason: a base is hashed into every first
    fingerprint in the namespace and handed to `restore`, so the class takes only the resolved form.
    Nothing below walks a step, but building the journals honestly costs one line.
    """
    harness = container.fakes(TreesRoot(tmp_path / "trees"), files={SEEDED: SEED})
    workspace = await harness.services.workspaces.open(LABEL, None, "main")
    return harness, workspace, await workspace.head()

def _journal(harness: container.FakeServices, workspace: Workspace, base: str) -> Journal:
    """One journal over one checkout. Called twice in most tests here, which is the whole point.

    Two of these over one `RunScope` is a state the engine cannot reach and this file needs: it
    leaves the step lock excluding nothing, so what a second claim waits on can only be the lease.
    """
    return Journal(
        harness.services.store,
        SCOPE,
        workspace,
        harness.services.clock,
        Fingerprints(),
        base,
    )

# --- the lease as a mechanism distinct from the step lock -----------------------------------------

@pytest.mark.asyncio
async def test_a_second_claim_on_one_target_waits_although_the_step_lock_cannot_stop_it(
    tmp_path: Path,
) -> None:
    """The lease, asked about on its own - the one claim no arrangement built on `Run` can make.

    Every serialization test in this package holds through the step lock as well as through the
    lease, because `Leases.claim` takes both at once and one namespace has one `Journal`. Build the
    lease lock fresh on every call - `lock = asyncio.Lock()` instead of the per-target lookup - and
    the lease excludes nothing at all, while `test_run_integrate.py` and
    `test_integrate_acceptance.py` stay green from end to end.

    So the second claim below is handed a **different** `Journal` over the **same** `RunScope`. Its
    step lock is a lock nobody else holds, so if this claim waits, the lease is what it is waiting
    for; if it completes, the lease is not a mechanism. That pair of journals is not a state
    `Steps` can produce, and that is the reason it is built here by hand rather than looked for.

    Letting the first lease go and requiring the second to arrive is what makes the wait a queue
    rather than a deadlock - a lease that never came back would fail the negative assertion above
    for the right reason and the whole test for the wrong one.
    """
    harness, workspace, base = await _opened(tmp_path)
    leases = Leases()
    first = await leases.claim(SCOPE, _journal(harness, workspace, base))

    queued = asyncio.create_task(leases.claim(SCOPE, _journal(harness, workspace, base)))
    finished, _ = await asyncio.wait({queued}, timeout=_SERIALIZED)

    assert not finished, (
        "a second claim on a target whose lease is held completed anyway, so the lease serialises "
        "nothing: it was taken on a lock this claim is the only holder of. The step lock cannot "
        "cover for it here - the two claims were handed different `Journal` objects - and it "
        "cannot cover for it in a run either, because it is released at the same moment"
    )

    first.release()
    second = await asyncio.wait_for(queued, timeout=_LIVENESS)

    assert second.target == SCOPE, (
        f"the queued claim came back holding a lease on {second.target}, and it asked for {SCOPE}"
    )
    second.release()

@pytest.mark.asyncio
async def test_one_lock_per_target_is_kept_for_the_life_of_the_run(tmp_path: Path) -> None:
    """"Locks are kept forever and leases are not" - `Leases.__init__`'s comment, as a claim.

    A lock built per claim would be a lock two claims never share, which is the mutation the test
    above is written against; this is the same sentence from the table's side, and it is the half a
    reader can check in one line. The identity is the assertion and not the count: a `_locks` that
    held one entry per target but replaced it on every claim would pass a length check and serialise
    nothing.

    The other half - that nothing prunes it - is why the run's own target is still in the table
    after its lease has come back. `_live` is the dict that would grow without bound, and a lease
    removes itself from that one.
    """
    harness, workspace, base = await _opened(tmp_path)
    leases = Leases()

    first = await leases.claim(SCOPE, _journal(harness, workspace, base))
    kept = leases._locks[SCOPE]
    first.release()
    second = await leases.claim(SCOPE, _journal(harness, workspace, base))
    second.release()

    assert leases._locks[SCOPE] is kept, (
        "the second claim on one target took a different lock object from the first, so two "
        "landings into that target hold two locks and neither of them waits for the other. A lease "
        "is keyed by the target because equal scopes are the same target, and a table that answers "
        "a fresh lock every time is that key doing nothing"
    )
    assert set(leases._locks) == {SCOPE}, (
        f"the lock table holds {sorted(str(scope) for scope in leases._locks)} after two claims on "
        f"one target, and a run has one lock per target it ever lands into"
    )

@pytest.mark.asyncio
async def test_a_released_lease_leaves_the_live_table_and_run_exit_then_says_nothing(
    tmp_path: Path,
) -> None:
    """`_live` holds a lease exactly while it is unreleased, which is what makes run exit safe.

    `Leases.release_all` iterates that table over whatever exception is already ending the run, and
    `Lease.release` evicts through `_forget` - so a lease that stayed in the table after being
    released would be released a second time from `api.run`'s `finally`, and an `asyncio.Lock`
    released twice raises `RuntimeError`. That would replace the workflow's real failure with an
    error about a lock, on the way out.

    Asserted on the table rather than on a second release, because the eviction is the mechanism
    and the idempotence in `Lease.release` is the belt beside the braces.
    """
    harness, workspace, base = await _opened(tmp_path)
    leases = Leases()

    lease = await leases.claim(SCOPE, _journal(harness, workspace, base))

    assert leases._live == {SCOPE: lease}, (
        f"a live lease on {SCOPE} is not the whole of the live table: {leases._live}. Run exit "
        f"releases what is in here and nothing else, so a lease that never arrived is one nothing "
        f"gives back"
    )

    lease.release()

    assert leases._live == {}, (
        f"a released lease is still in the live table as {leases._live}, so run exit will release "
        f"it a second time - and `asyncio.Lock.release` raises `RuntimeError` on a lock nobody "
        f"holds, from a `finally`, over whatever the run was already failing with"
    )
    leases.release_all()

@pytest.mark.asyncio
async def test_release_all_gives_back_every_live_lease_and_not_merely_one(tmp_path: Path) -> None:
    """The sweeper - run exit gives back every live lease - all of them, in one call.

    A run holds one lease per target it is mid-landing into, and a workflow that walked away from
    two conflicts at once leaves two. `api.run`'s `finally` is the only caller, it takes no
    argument, and it cannot ask an `Integration` whether it settled - so "everything this run is
    still holding" has to be what it means. A `release_all` that stopped after the first would leave
    the second target leased for the life of the process, with nothing raised and no predicate to
    ask.

    Both targets are then taken again, which is the only way a lease can be observed coming back:
    there is no `held()`, deliberately, because one would be answerable only in the instant between
    two `await`s.
    """
    harness, workspace, base = await _opened(tmp_path)
    leases = Leases()
    await leases.claim(SCOPE, _journal(harness, workspace, base))
    await leases.claim(NESTED, _journal(harness, workspace, base))

    leases.release_all()

    assert leases._live == {}, (
        f"run exit left {sorted(str(scope) for scope in leases._live)} leased. Every live lease "
        f"goes back in that one call, because the objects they are reachable from are going away "
        f"with the workflow and nothing will ever ask again"
    )
    for target in (SCOPE, NESTED):
        retaken = await asyncio.wait_for(
            leases.claim(target, _journal(harness, workspace, base)), timeout=_LIVENESS
        )
        assert retaken.target == target
        retaken.release()

@pytest.mark.asyncio
async def test_a_lease_on_one_target_does_not_stop_a_claim_into_another(tmp_path: Path) -> None:
    """Why "a human deliberating in one run never blocks another" - the granularity that buys it.

    The lease is per **target** and not per run and not per table, which is what lets a conflict
    screen stay up over one parent while another parent's queue keeps moving. A single lock over the
    whole of `Leases` would pass every serialization test in this package - landings into one target
    would still be one at a time - and would stall every landing in the tree behind one afternoon's
    deliberation.

    Nothing here can hang and pass: the second claim is awaited under a bound, so a lease that
    excluded too much would fail rather than take the run's latency with it.
    """
    harness, workspace, base = await _opened(tmp_path)
    leases = Leases()
    held = await leases.claim(SCOPE, _journal(harness, workspace, base))

    other = await asyncio.wait_for(
        leases.claim(NESTED, _journal(harness, workspace, base)), timeout=_LIVENESS
    )

    assert other.target == NESTED, (
        f"the claim on {NESTED} came back holding {other.target}"
    )
    assert held.target == SCOPE
    other.release()
    held.release()

# --- cancellation between the lease and the step lock ---------------------------------------------

class _Pause:
    """A rendezvous a scripted agent parks on, so a test can hold one namespace's step open.

    Two events rather than a sleep: `started` says the step is genuinely inside its worker, and
    `release` is the test deciding when it ends. Nothing here waits on a scheduler.
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

@role(model=Claude.SONNET)
def _role(name: str, instructions: str) -> Role[None]:
    """An effect role: it writes files and commits, and reports nothing.

    No reporting tool, because nothing below reads a step's value - what these two roles are for is
    a commit in the child and a suspension in the parent.
    """
    return Role(name=name, instructions=instructions, restrictions=set[Restriction]())

IMPLEMENT: Final = _role("implement", "implement T-01")
HOLDING: Final = _role("review", "review the parent's worktree, slowly")

_WRITES: Final[Mapping[str, Mapping[str, bytes]]] = {
    IMPLEMENT.instructions: {LANDED: b"the child's work\n"},
    HOLDING.instructions: {},
}

def _agent(pause: _Pause) -> Agent:
    """Write what this prompt is meant to write, and park if this is the holding role.

    Keyed on the prompt because that is the only thing the port hands an agent that says which step
    this is - `AgentTask` carries no namespace and no step name, deliberately.

    An `async def` in `sdk/testing.py`'s own vocabulary, which is what `container.fakes(agent=...)`
    takes. Before a `testing.Agent` could await, parking on an event - which is the whole of the
    arrangement below - had to be written on a raw per-provider `Script`.
    """

    async def _one(task: AgentTask) -> Reply:
        said = task.instructions
        if said == HOLDING.instructions:
            pause.started.set()
            await pause.release.wait()
        for name, content in _WRITES.get(said, {}).items():
            where = task.workspace / name
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_bytes(content)
        return Reply()

    return _one

@pytest.mark.asyncio
async def test_a_landing_cancelled_waiting_for_the_step_lock_gives_the_targets_lease_back(
    tmp_path: Path,
) -> None:
    """`claim`'s `except BaseException: lock.release(); raise`, at the suspension it is written for.

    **This test depends on the ones above it**, and not only by neighbourhood: what it produces is a
    lease held by nobody, and a lease that serialises nothing cannot be observed being held by
    anybody. Apply the mutation the first test in this file is written against - a fresh
    `asyncio.Lock()` per claim - and the stranded lock below is a lock the next landing never asks
    for, so this passes. The two mutations are only separately fatal because the lease is
    per-target, and that is what the tests above hold.

    **`claim` suspends twice and the existing cancellation test only ever meets the first.**
    `test_integrate_acceptance.py::test_cancelling_a_queued_landing_does_not_strand_the_target`
    cancels a landing queued *on the lease*, where `asyncio.Lock.acquire` does its own cleanup and
    nothing in AGL has to. The window this covers is the other one: the lease is already held, and
    the landing is waiting for the target namespace's step lock behind a step that is still running.
    A cancellation there, with the release removed, leaves the lease held for the life of the
    process.

    **And it is the worst failure this module has**, which is why it is worth an arrangement of its
    own. The `Lease` object is constructed *after* the step lock is taken, so nothing ever entered
    `_live`: `release_all()` at run exit iterates an empty table and cannot recover it, no predicate
    exists to ask, and every later landing into that parent - and every later step in it - waits
    forever with nothing raised.

    The arrangement is `test_run_integrate.py`'s own
    `test_a_landing_waits_for_a_step_already_running_in_the_target_namespace`: the landing parks
    behind a **running step** rather than behind an undecided conflict, which is what puts the
    cancellation at the second suspension rather than the first.
    """
    pause = _Pause()
    harness = container.fakes(
        TreesRoot(tmp_path / "trees"), files={SEEDED: SEED}, agent=_agent(pause)
    )
    history = harness.services.history
    run: Run[None] = Run(
        params=None,
        services=harness.services,
        scope=SCOPE,
        base=await history.resolve(await history.default_ref()),
    )
    ticket = run.worktree(TICKET)
    await ticket.step(IMPLEMENT, commit="implement T-01")

    step = asyncio.create_task(run.step(HOLDING))
    await asyncio.wait_for(pause.started.wait(), timeout=_LIVENESS)
    queued = asyncio.create_task(ticket.integrate())
    running, _ = await asyncio.wait({queued}, timeout=_SERIALIZED)

    assert not running, (
        "the landing completed while a step in the target namespace was still inside its worker, "
        "so it never waited for the step lock and this test cannot cancel it there"
    )

    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued

    pause.release.set()
    await asyncio.wait_for(step, timeout=_LIVENESS)
    landing = asyncio.create_task(ticket.integrate())
    landed, pending = await asyncio.wait({landing}, timeout=_LIVENESS)
    for stalled in pending:
        stalled.cancel()

    assert landed, (
        f"a landing offered into the target after a queued one was cancelled did not finish within "
        f"{_LIVENESS} seconds, so the cancelled claim gave nothing back: it held the target's "
        f"lease and was suspended taking the step lock, and the release between the two is what "
        f"a cancellation arriving there needs. Nothing recovers this one - the `Lease` is built "
        f"after that point, so `release_all()` has nothing to iterate - and every later "
        f"landing into this parent waits for the life of the process, with nothing raised and no "
        f"predicate to ask"
    )
    outcome: Integration = landing.result()
    assert outcome.conflicted is False, (
        f"the landing after a cancelled one did not go in: {outcome.conflict}. The cancelled claim "
        f"held nothing by the time it was over, so nothing it did may reach the next one"
    )
    assert (tmp_path / "trees" / "auth" / "_base" / LANDED).is_file(), (
        "the child's work is not in the target's checkout, so what landed was not what was offered"
    )
