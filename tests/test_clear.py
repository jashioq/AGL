"""`agl clear <label> [-f]` from the library side: `git branch -d` semantics, and the order.

The acceptance criterion is one sentence - "`clear` on an unmerged branch warns and keeps it; `-f`
deletes" - and both halves are asked of `FakeServices.repository`, which is the shared
`FakeRepository` behind all three git fakes. "The branch is still there" and "the branch is gone"
are therefore questions about the same object `api.clear` acted on through the ports, rather than
about a note some test double took.

**Everything is `container.fakes()`** - no network, no git, no process - which is target #8, and it
is what lets a run with a child and a grandchild in it be built, cleared and asserted in
milliseconds. The workflows are declared in this module and reached through hand-constructed
`EntryPoint` values, exactly as `tests/test_api.py` and `tests/test_resume.py` do.

**The runs are real runs.** Nothing below writes a namespace into the store by hand: `nesting`
takes a worktree and a worktree inside that one and steps in each, so the scopes `clear` traverses
are the ones the run recorded, at the depths it recorded them at. That matters because the
traversal is the one real algorithm here - `Store.namespaces` answers about immediate children and
the caller recurses - and a test that arranged a flat pair of entries would never walk it.

## Three claims are worth naming, because each fails silently

**The order.** `Store.namespaces` is the only enumeration of what a run used, so removing the
records before the checkouts strands every checkout they name - and a `clear` written that way
returns cleanly, having quietly left a directory tree and a set of branches behind. It is pinned
twice: once as the whole call sequence, and once by asserting that a run with a child and a
grandchild really does come away at every depth, which is the assertion that goes red if the
enumeration is spent after it has been deleted.

**`remove` before `discard`.** `ports/workspace.py` gives the reason - "an implementation is within
its rights to refuse to delete a line of work that something still has open" - and the fakes are
one such implementation, so a `clear` written the other way round would raise here. The sequence
test states it anyway rather than resting on that, because the fake is free to stop being strict.

**`base_ref` and not `base_sha`.** The pin cannot have moved, so a containment question asked about
it answers "merged" exactly when the run committed nothing - the branch decision inverted. The
unmerged and merged tests below are the same run with `main` moved between them, so a `clear` that
asked about `base_sha` would fail the second and pass the first.

## Two locks, and the two tests that are about them

**AGL's own, which the fakes can answer.** "`clear` refuses while a run holds a lock" had nothing
behind it for a long time: no durable "this run is live" record, `ARCHITECTURE.md`'s "Deliberately
not built" refusing stored status by name, and leases in-process. `WorkspaceProvider.hold` is the
mechanism now - `api.run` and `api.resume` take it across everything durable they do and
`api.clear` takes it around its removals - and the two tests that drive it issue the `clear` **from
inside the workflow**, which is the only way one process can be two invocations. The fakes can
answer that because their claim is a process-wide set; what they cannot answer is release-on-death,
and `adapters/git/fake.py` says which half is which.

**git's own `worktree lock`, which no fake can grow honestly.** `worktree prune` silently skips a
locked entry even after its directory has gone, so the registration survives `remove`, and `git
branch -D` then refuses a branch "used by worktree at ...". The lock is a file inside
`.git/worktrees/<name>/`, which is the half of a worktree a `FakeRepository` does not have at all.
So the last test below puts `GitWorkspaceProvider` and `GitHistory` under `api.clear` and asks git
itself, exactly as `tests/test_api.py` does for the two claims about a real ref, and it asserts the
same clear succeeding once the lock is off, so that it is a test about a lock rather than about
`clear` refusing.
"""

import subprocess
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

import pytest

from agl import api
from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.git.history import GitHistory
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.config import container, registry
from agl.ports.agent import AgentOutcome, Claude, StopReason
from agl.ports.errors import ConflictError, NotFoundError, exit_code_for
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue, RunSpec
from agl.ports.store import Store
from agl.ports.tree_layout import (
    TreesRoot,
    base_worktree,
    run_branch,
    run_trees_dir,
    worktree_branch,
    worktree_dir,
)
from agl.ports.workspace import Workspace, WorkspaceProvider
from agl.sdk.roles import Role, role
from agl.sdk.workflow import Run, workflow

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# The run's two lines of work below `_base`, at two depths: `sub-b` is `T-01`'s child in the store
# and `T-01`'s sibling in the trees root, which is the asymmetry that makes the traversal below a
# traversal. `_BASE` is the trees layout's own word for the run's own checkout, written out because
# these tests read the call sequence and `namespace=None` has to appear in it as something.
CHILD: Final = Namespace("T-01")
GRANDCHILD: Final = Namespace("sub-b")
_BASE: Final = "_base"

# The file the repository is seeded with.
SEEDED: Final = "src/a.txt"


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""


@role(model=Claude.SONNET)
def writing() -> Role:
    """An effect role: no reporting tool, so a step over it results in `null` and its whole purpose
    is that an agent wrote a file the step then commits.

    `Claude.SONNET` because a role has to name a model and the fakes bundle serves both providers;
    nothing below depends on which. A zero-argument factory because nothing about it is decided at
    a call site - three steps below run it and none of them varies anything."""
    return Role(name="work", instructions="leave some work behind")


@workflow(version="1.0")
async def nesting(run: Run[NoParams]) -> None:
    """A run with something at every depth: its own work, a child's, and the child's child's.

    Each step commits, so all three lines of work end up ahead of the base ref - which is what
    makes `agl/auth` unmerged without any arrangement, and what makes "the child branches were
    deleted" a claim about names that really exist.

    One role serves all three, which is now also one step name: what separates the three entries is
    the namespace each runs in, and `steps/` sits under every scope. The depth is the claim here,
    and a role per level would only be three copies of one declaration saying so twice.
    """
    await run.step(writing(), commit="the run's own work")
    child = run.worktree(str(CHILD))
    await child.step(writing(), commit="the child's work")
    grandchild = child.worktree(str(GRANDCHILD))
    await grandchild.step(writing(), commit="the grandchild's work")


@workflow(version="1.0")
async def quiet(run: Run[NoParams]) -> None:
    """Takes no step at all, so `agl/auth` never leaves the commit the run was cut from.

    The one run whose branch is contained in its base ref without anything being moved - which is
    also the run that has a `_base` checkout and no namespaces at all, and so the shortest walk
    `clear` can take.
    """


# What a `clear` issued from inside a live run raised, at module level because the workflow that
# issues it has to be: `EntryPoint.load` imports a module and reads an attribute in it.
refused: Final[list[ConflictError]] = []


@workflow(version="1.0")
async def clearing(run: Run[NoParams]) -> None:
    """Clears itself, from inside itself, which is the one way one process can be two invocations.

    The sentence is about a `clear` in a second `agl` while a run is live in a first, and a suite
    cannot start a second process and drive `api` in it. What it can do is call `api.clear` at a
    moment when `api.run` is demonstrably still inside its own claim - which is exactly here, since
    this function is what `api.run` awaits inside it - and assert that the claim is what refused.
    The `except` is the test's, not AGL's: `api` catches nothing, so the refusal has to be caught
    by whoever wants to look at it afterwards.
    """
    try:
        await api.clear(run.services, PROJECT, LABEL)
    except ConflictError as conflict:
        refused.append(conflict)


def _point(name: str, attribute: str) -> EntryPoint:
    """A `probe = "agl.workflows.probe:probe"` line, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)


POINTS: Final = (
    _point("nesting", "nesting"), _point("quiet", "quiet"), _point("clearing", "clearing")
)


def _writing(dispatched: list[str]) -> Script:
    """An agent that leaves one file behind per dispatch and reports nothing.

    A distinct filename per step, so every `commit=` records a state the previous one did not:
    `commit_all` is a no-op when nothing is dirty, and three steps writing one identical file would
    leave two of the three lines of work exactly where they started.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        dispatched.append(conversation.task.instructions)
        target = conversation.task.workspace / f"src/step-{len(dispatched)}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"work an agent left behind\n")
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script


def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment: one repository seeded with a file, one store, one frozen clock."""
    return container.fakes(
        _trees(tmp_path), files={SEEDED: b"one\n"}, claude=_writing([])
    )


def _trees(tmp_path: Path) -> TreesRoot:
    """Where `container.fakes` puts this run's checkouts, spelled once."""
    return TreesRoot(tmp_path / "trees")


async def _start(
    harness: container.FakeServices,
    name: str = "nesting",
    *,
    points: Sequence[EntryPoint] = POINTS,
) -> None:
    """The first invocation: `agl run <name> -n auth`, with this module's entry points."""
    await api.run(harness.services, PROJECT, name, LABEL, (), points=points)


async def _clear(harness: container.FakeServices, *, force: bool = False) -> str | None:
    """`agl clear auth [-f]`, and the warning it answers with."""
    return await api.clear(harness.services, PROJECT, LABEL, force=force)


def _merged(harness: container.FakeServices) -> None:
    """Move the base ref up to the run's own branch: the world in which the work has landed.

    Through the repository rather than through a landing, because what `clear` asks is an ancestry
    question and `Integrator` is not in this deliverable. `main` is the branch `FakeHistory
    .default_ref` names, and `RunSpec.base_ref` recorded its full spelling.
    """
    tip = harness.repository.tip(run_branch(LABEL))
    assert tip is not None, "the run left no branch, so there is nothing to move the base ref to"
    harness.repository.move("main", tip)


# --- the acceptance criterion ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_on_an_unmerged_branch_warns_and_keeps_it(tmp_path: Path) -> None:
    """Half one of the criterion, and the asymmetry: "a retained branch costs a stale ref, a
    deleted one costs the entire run".

    The warning is asserted to *be* the answer rather than to have been printed - `api.clear`
    returns it, because a library caller and a CLI both have to see it and `api.py` starts no
    output. Everything else is asserted gone in the same breath: the point of the sentence is that
    this run was cleared and one name was kept, not that the command declined to do anything.
    """
    harness = _fakes(tmp_path)
    await _start(harness)
    branch = run_branch(LABEL)
    assert harness.repository.tip(branch) != await harness.services.history.resolve("main"), (
        "the run committed nothing, so its branch is already contained and this test is vacuous"
    )

    kept = await _clear(harness)

    assert harness.repository.tip(branch) is not None, (
        "the run's own branch was deleted although the base ref does not contain it yet. A clear "
        "deletes `agl/<label>` only if merged into the base ref, and the cost of getting this "
        "wrong is the entire run"
    )
    assert kept is not None, "the branch was kept and nothing said so"
    assert branch in kept and "-f" in kept
    assert await harness.services.store.read_record(SCOPE) is None, (
        "the run's records survived a clear that kept only its branch"
    )
    assert not run_trees_dir(_trees(tmp_path), LABEL).exists()


@pytest.mark.asyncio
async def test_force_deletes_the_unmerged_branch(tmp_path: Path) -> None:
    """Half two: `-f` is `git branch -D`, and it asks nothing at all.

    The same run as above, so the only difference between the two outcomes is the flag - which is
    what makes this a test about `force` rather than about whichever branch happened to be
    contained.
    """
    harness = _fakes(tmp_path)
    await _start(harness)

    kept = await _clear(harness, force=True)

    assert harness.repository.tip(run_branch(LABEL)) is None, (
        "`-f` is `git branch -D` and left the branch standing"
    )
    assert kept is None, "a forced clear kept nothing and warned about it anyway"


@pytest.mark.asyncio
async def test_a_merged_branch_is_deleted_without_force(tmp_path: Path) -> None:
    """The other side of the containment question, so that the two above are about an *answer*.

    A `clear` that never deleted anything unforced would satisfy the warning test word for word,
    and a `contains` wired backwards would satisfy this one. They are the same run with the base
    ref moved on top of the run's branch in between, which is also what makes the choice of ref
    visible: `base_sha` is the commit the run was cut from and cannot move, so a `clear` asking
    about the pin would answer "not merged" here and keep the branch.
    """
    harness = _fakes(tmp_path)
    await _start(harness)
    _merged(harness)

    kept = await _clear(harness)

    assert harness.repository.tip(run_branch(LABEL)) is None, (
        "the base ref contains this run's work and its branch was kept anyway, which is `git "
        "branch -d` refusing to tidy up the one case it exists for"
    )
    assert kept is None


@pytest.mark.asyncio
async def test_a_run_that_committed_nothing_is_contained_and_goes_quietly(tmp_path: Path) -> None:
    """The ordinary end of an ordinary run: nothing was recorded, so nothing is at risk.

    `FakeRepository.contains` is reflexive and `ports/history.py` says both implementations agree
    there, so a run whose workflow took no step sits exactly at its base and `clear` tidies it with
    no flag and no warning. Worth its own line because it is the case an operator meets most often
    and the one a containment check written with a strict "ahead of" would get wrong.
    """
    harness = _fakes(tmp_path)
    await _start(harness, "quiet")

    kept = await _clear(harness)

    assert kept is None
    assert harness.repository.tip(run_branch(LABEL)) is None
    assert await harness.services.store.read_record(SCOPE) is None


# --- the traversal, and the order it happens in ---------------------------------------------------


@pytest.mark.asyncio
async def test_every_namespace_at_every_depth_comes_away(tmp_path: Path) -> None:
    """A run nests arbitrarily, so `clear` recurses through `RunScope.inside` (`ports/store.py`).

    A child and a grandchild, asserted as three things each: the checkout is gone, the line of work
    is gone, and - because the trees root is flat and every checkout in a run is a sibling -
    `.trees/auth/` itself is gone, which is the `rmdir` `_trees.tidy` does once the last one has
    been taken away. That directory is asked for by name.

    **This is also where "the records go last" is falsifiable.** `Store.namespaces` is the only
    enumeration of what a run used, and `MemoryStore.remove` at depth zero deletes the entries it
    derives that answer from - so a `clear` that removed the records first would walk an empty list,
    return cleanly, and leave both child checkouts and both child branches exactly where they are.
    """
    harness = _fakes(tmp_path)
    await _start(harness)
    trees = _trees(tmp_path)
    for namespace in (CHILD, GRANDCHILD):
        assert worktree_dir(trees, LABEL, namespace).is_dir(), "the run never cut this checkout"
        assert harness.repository.tip(worktree_branch(LABEL, namespace)) is not None

    await _clear(harness, force=True)

    for namespace in (CHILD, GRANDCHILD):
        assert not worktree_dir(trees, LABEL, namespace).exists(), (
            f"the checkout for {str(namespace)!r} survived the clear. `Store.namespaces` is the "
            f"only place the set of namespaces a run used is written down, so a clear that spent "
            f"it after removing the records would find nothing to take back"
        )
        assert harness.repository.tip(worktree_branch(LABEL, namespace)) is None, (
            f"the line of work under {str(namespace)!r} survived. A clear removes the "
            f"`agl/_work/<label>/*` child branches unconditionally - their work has either been "
            f"landed into the run's own line or deliberately abandoned"
        )
    assert not base_worktree(trees, LABEL).exists()
    assert not run_trees_dir(trees, LABEL).exists(), (
        "`.trees/auth/` is still there, and it is asked for by name. It goes when the last "
        "checkout in it does, which is one `rmdir` inside `WorkspaceProvider.remove`"
    )
    assert await harness.store.namespaces(SCOPE) == ()


class _Recording(WorkspaceProvider):
    """The bundle's own provider with every call written into a shared list.

    Substituted with `dataclasses.replace`, which is what `tests/test_api.py` and
    `tests/test_resume.py` do: the port-typed field is the seam, and `container.fakes()` has no
    `workspaces=` parameter to reach for instead. It delegates rather than pretends - what is under
    test is the order `api.clear` calls these in, and everything else has to go on working, up to
    and including the fakes' own refusal to discard a line of work something still has open.
    """

    def __init__(self, provider: WorkspaceProvider, events: list[str]) -> None:
        self._provider = provider
        self._events = events

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        self._events.append(f"open {_named(namespace)}")
        return await self._provider.open(label, namespace, base)

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        self._events.append(f"remove {_named(namespace)}")
        await self._provider.remove(label, namespace)

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        self._events.append(f"discard {_named(namespace)}")
        await self._provider.discard(label, namespace)

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        """Both edges of the run claim, because both are ordering claims about `clear`.

        Taking it late would leave the removals it exists to guard outside it, and letting go of it
        early would leave the last of them outside; neither shows up in a list that only records
        the acquisition. So the sequence below carries a `hold` and a `release`, and they are the
        first and last lines of it.
        """
        return _noted(self._provider.hold(label), self._events)


@asynccontextmanager
async def _noted(
    claim: AbstractAsyncContextManager[None], events: list[str]
) -> AsyncIterator[None]:
    """`claim`, with a line written down on the way in and on the way out."""
    async with claim:
        events.append("hold")
        try:
            yield
        finally:
            events.append("release")


class _RecordingStore(Store):
    """The bundle's own store, with the two members `clear` uses written into the same list.

    The four lookups delegate silently: a `read_record` is how `clear` finds out whether the run
    exists at all and says nothing about the order the teardown happens in, and the entry members
    are here because `Store` has six and a partial implementation is not one.
    """

    def __init__(self, store: Store, events: list[str]) -> None:
        self._store = store
        self._events = events

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        return await self._store.read_record(scope)

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        await self._store.write_record(scope, value)

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        return await self._store.read_entry(scope, step, digest)

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        await self._store.write_entry(scope, step, digest, value)

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        self._events.append(f"namespaces under {[str(name) for name in scope.namespaces]}")
        return await self._store.namespaces(scope)

    async def remove(self, scope: RunScope) -> None:
        self._events.append("remove the records")
        await self._store.remove(scope)


def _named(namespace: Namespace | None) -> str:
    """How a namespace appears in the call sequence. `None` is the run's own place, which the
    trees layout calls `_base` and which `ids.py` refuses as a `Namespace` in every spelling."""
    return _BASE if namespace is None else str(namespace)


@pytest.mark.asyncio
async def test_the_order_is_enumerate_then_the_checkouts_then_the_records(tmp_path: Path) -> None:
    """The whole call sequence, in one assertion, for a run with something at every depth.

    Four separate claims live in this list and each one fails silently on its own:

      * **The enumeration recurses.** `Store.namespaces` is asked at depth 0, then under `T-01`,
        then under `T-01/sub-b` - which is the port's "immediate children only, and the caller
        recurses through `RunScope.inside`". A flat `clear` would ask once.
      * **`remove` comes before `discard`, per namespace.** `ports/workspace.py`: "an
        implementation is within its rights to refuse to delete a line of work that something still
        has open, and calling these in this order means no caller has to know whether it does".
      * **The run's own place is last of the checkouts**, and is addressed by the absence of a
        namespace rather than by a name, because `_base` is not a `Namespace` anything can build.
      * **The records go last**, because they are the enumeration this whole sequence was read out
        of. Removing them first strands every checkout they name.
      * **The run claim is around all of it.** `hold` is first and `release` is last, so a
        `clear` racing a live run refuses before it has taken anything and does not let go until
        the last removal is done - the two halves of the sentence that had no mechanism for years.

    The run is arranged as merged first, so the sequence below is the ordinary unforced path with
    the containment question answered "yes" - rather than the shorter one `-f` takes.
    """
    events: list[str] = []
    harness = _fakes(tmp_path)
    services = replace(
        harness.services,
        workspaces=_Recording(harness.services.workspaces, events),
        store=_RecordingStore(harness.services.store, events),
    )
    await api.run(services, PROJECT, "nesting", LABEL, (), points=POINTS)
    _merged(harness)
    events.clear()

    await api.clear(services, PROJECT, LABEL)

    assert events == [
        "hold",
        "namespaces under []",
        "namespaces under ['T-01']",
        "namespaces under ['T-01', 'sub-b']",
        "remove T-01",
        "discard T-01",
        "remove sub-b",
        "discard sub-b",
        "remove _base",
        "discard _base",
        "remove the records",
        "release",
    ]


# --- what the retained branch now costs, and the claim that makes `clear` refuse -----------------


@pytest.mark.asyncio
async def test_a_kept_branch_refuses_the_next_run_until_the_branch_goes(tmp_path: Path) -> None:
    """The defect, closed end to end: the retained side of the asymmetry, and its real price.

    "A retained branch costs a stale ref" is what the `git branch -d` decision is argued on, and
    the retained side is worse than that - a later `agl run ... -n auth --from main` takes `open`'s
    attaching path and starts from the old tip with `--from` silently ignored, because "`base` is
    consulted only when provisioning". The fix is `api.run` refusing the label outright, and this
    is the whole loop: an unmerged clear keeps the branch, the next run under that label is refused
    rather than misdirected, `-f` deletes it, and the label works again.

    The last three lines are what make this a test about the branch. Without them a `run` that
    refused every second invocation for any reason at all would pass, and the sentence being
    asserted is that the *branch* is what took the label and that removing it gives it back.

    **And what removes it is not `agl clear -f`**, which is worth pinning because both messages
    used to say so: the same `clear` that keeps the branch removes the run's records, so a second
    `agl clear auth -f` finds no run and answers `NotFoundError`. That refusal is asserted below,
    beside the warning that no longer promises otherwise.
    """
    harness = _fakes(tmp_path)
    await _start(harness)
    branch = run_branch(LABEL)

    kept = await _clear(harness)

    assert kept is not None and branch in kept
    assert f"-n {LABEL}" in kept, (
        "the warning does not say that the label is now taken. This branch was priced as a stale "
        "ref; what it actually costs is the next run under this label, and that is what an "
        "operator has to be able to act on"
    )
    with pytest.raises(NotFoundError):
        await _clear(harness, force=True)

    with pytest.raises(ConflictError) as caught:
        await _start(harness)
    assert exit_code_for(caught.value) == 4
    assert branch in str(caught.value)
    assert await harness.services.store.read_record(SCOPE) is None, (
        "the refused run wrote a record, so the operator now has two things to clear"
    )

    harness.repository.drop(branch)
    await _start(harness, "quiet")
    assert await harness.services.store.read_record(SCOPE) is not None, (
        "the label was still refused once the branch it was taken by had gone, so the refusal "
        "above was about something other than the branch"
    )


@pytest.mark.asyncio
async def test_a_clear_aimed_at_a_live_run_refuses_and_takes_nothing(tmp_path: Path) -> None:
    """The last sentence, which had no mechanism behind it for a long time.

    "It refuses while a run holds a lock" - and there was nothing to refuse with: no durable "this
    run is live" record, `ARCHITECTURE.md`'s "Deliberately not built" refusing stored status by
    name, and leases in-process. So a `clear` aimed at a run live in another `agl` took its
    checkouts away underneath it and said nothing. What closes it is `WorkspaceProvider.hold`,
    taken by `api.run` across everything durable it does and by `api.clear` around its removals.

    The `clear` is issued from inside the workflow, which is the only way one process can be two
    invocations - `api.run` is demonstrably still inside its own claim while it is awaiting this.
    That is also why the fakes can answer it at all: their claim is a process-wide set, which is
    the exclusion and not the release-on-death, and `adapters/git/fake.py` says which half is which.

    Two assertions carry it. The refusal is `ConflictError` at exit 4, naming the run - not some
    other failure the timing happened to produce - and everything the run held is **still there**
    afterwards, which is the half that actually matters: a `clear` that refused after removing two
    of three checkouts would satisfy the first assertion and destroy the run.

    The last two lines are what make it a test about the claim rather than about `clear` refusing:
    the same `clear`, over the same run, succeeds once the run has ended and let go.
    """
    refused.clear()
    harness = _fakes(tmp_path)

    await _start(harness, "clearing")

    assert len(refused) == 1, (
        "a `clear` issued while the run was live did not refuse. The sentence is that it "
        "refuses; without the claim it takes the run's checkouts away underneath it and says "
        "nothing, which is the failure this test exists for"
    )
    assert exit_code_for(refused[0]) == 4
    assert str(LABEL) in str(refused[0])
    assert await harness.services.store.read_record(SCOPE) is not None, (
        "the refused `clear` removed the live run's records anyway"
    )
    assert harness.repository.tip(run_branch(LABEL)) is not None, (
        "the refused `clear` deleted the live run's line of work anyway"
    )
    assert base_worktree(_trees(tmp_path), LABEL).is_dir(), (
        "the refused `clear` took the live run's own checkout away anyway - which is exactly the "
        "sentence that had no mechanism behind it"
    )

    assert await _clear(harness) is None
    assert await harness.services.store.read_record(SCOPE) is None


@pytest.mark.asyncio
async def test_a_clear_aimed_at_a_live_resume_refuses_too(tmp_path: Path) -> None:
    """The same claim, taken by the other verb that walks a run.

    `api.resume` is a run being walked again, so it is live in exactly the sense the sentence is
    about - and it is the invocation the sentence matters most for, because a resume is what
    somebody starts hours later on a run they have half forgotten, which is also when somebody else
    is most likely to try to tidy it up. Without a claim here, `run` would hold one and `resume`
    would not, and the same `clear` would be refused or destructive depending on which verb was
    running.

    The workflow is the one that clears itself, so a resume replays it: the record survived the
    first refusal, `resume` reads it, loads `clearing` again, and awaits it inside its own claim.
    `refused` therefore carries one entry per invocation, which is what the count below reads.
    """
    refused.clear()
    harness = _fakes(tmp_path)
    await _start(harness, "clearing")
    assert len(refused) == 1, "the run's own claim is what the other test is about"

    await api.resume(harness.services, PROJECT, LABEL, points=POINTS)

    assert len(refused) == 2, (
        "a `clear` issued while a resume was live did not refuse, so a resumed run has its "
        "checkouts taken away underneath it where a fresh one does not"
    )
    assert exit_code_for(refused[1]) == 4
    assert await harness.services.store.read_record(SCOPE) is not None, (
        "the refused `clear` removed the resumed run's records anyway"
    )
    assert base_worktree(_trees(tmp_path), LABEL).is_dir(), (
        "the refused `clear` took the resumed run's own checkout away anyway"
    )


# --- absence, which is the ordinary case ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_label_with_no_record_is_a_not_found_and_reads_as_the_third_of_three(
    tmp_path: Path,
) -> None:
    """The three refusals, read as the set they are: `run` says the label is taken and names the
    two verbs that free it, `resume` says it is free and names the verb that takes it, and `clear`
    says it is free and there is therefore nothing to take away.

    All three messages are asserted here, in one test, because the claim is about the vocabulary
    rather than about any one sentence. A change to one of them that stopped them reading as one
    family fails here rather than being noticed by an operator holding three terminals.
    """
    harness = _fakes(tmp_path)

    with pytest.raises(NotFoundError) as caught:
        await _clear(harness)

    assert str(caught.value) == "run 'auth' does not exist - there is nothing to clear."
    assert exit_code_for(caught.value) == 3

    await _start(harness, "quiet")
    with pytest.raises(NotFoundError) as absent:
        await api.resume(harness.services, PROJECT, RunLabel("other"), points=POINTS)
    assert str(absent.value) == (
        "run 'other' does not exist - `agl run <workflow> -n other` starts one."
    )


@pytest.mark.asyncio
async def test_clearing_the_same_run_twice_refuses_the_second_time(tmp_path: Path) -> None:
    """`clear` twice in a row, which is what an operator does when the first one printed something.

    The second is the same `NotFoundError` a label nobody ever used gets, and that is the honest
    answer rather than a tolerance: the run's record is what says a run exists, and the first clear
    took it. What the port-level tolerance buys is one layer down - `remove` and `discard` are
    called over things that are already gone in the test below - and it would be wrong to spend it
    here, where saying nothing would mean a typo'd label cleared silently.
    """
    harness = _fakes(tmp_path)
    await _start(harness)

    await _clear(harness, force=True)

    with pytest.raises(NotFoundError) as caught:
        await _clear(harness, force=True)
    assert exit_code_for(caught.value) == 3


@pytest.mark.asyncio
async def test_a_run_whose_checkouts_were_never_cut_is_cleared_without_raising(
    tmp_path: Path,
) -> None:
    """`clear` after a crash is the ordinary case rather than the exceptional one.

    The state is the one `api.run` writes its two durable lines in a particular order to guarantee:
    a record naming a run whose `_base` was never provisioned, which is what a crash between
    `write_record` and `workspaces.open` leaves. Every teardown verb `clear` then calls is called
    over something that is not there, and each has to succeed and say nothing - "a teardown that
    raises on a half-finished setup is a teardown callers learn to wrap in a bare `except`".

    **`-f` is what reaches it**, and that is a consequence worth pinning rather than hiding. The
    containment question is asked about `agl/auth`, this run never created one, and both `History`
    implementations raise `NotFoundError` for a ref that names nothing rather than answering "no" -
    `ports/history.py` argues why that refusal is the right one. So the unforced clear of a run
    that never provisioned anything reports that its branch is missing, and `-f`, which asks
    nothing, is the way such a record is taken away.
    """
    harness = _fakes(tmp_path)
    history = harness.services.history
    ref = await history.default_ref()
    spec = RunSpec(
        workflow="quiet",
        workflow_version="1.0",
        label=LABEL,
        base_ref=ref,
        base_sha=await history.resolve(ref),
        branch=run_branch(LABEL),
        params={},
        created_at=harness.services.clock.now(),
    )
    await harness.services.store.write_record(SCOPE, spec.to_json())

    with pytest.raises(NotFoundError):
        await _clear(harness)

    assert await _clear(harness, force=True) is None
    assert await harness.services.store.read_record(SCOPE) is None
    assert not run_trees_dir(_trees(tmp_path), LABEL).exists()


@pytest.mark.asyncio
async def test_a_clear_over_checkouts_something_already_took_back_succeeds(tmp_path: Path) -> None:
    """The other shape of absence: the run happened, and its places were given back by hand first.

    This is a crash between the teardown and the record removal, and the recovery `clear` relies on
    - both verbs, on both kinds of address, over what is already gone. The assertion at the end is
    what makes it non-vacuous: the clear really did finish, so the second pass over the absent
    checkouts was tolerated rather than skipped.
    """
    harness = _fakes(tmp_path)
    await _start(harness)
    for namespace in (CHILD, GRANDCHILD, None):
        await harness.services.workspaces.remove(LABEL, namespace)
        await harness.services.workspaces.discard(LABEL, namespace)

    assert await _clear(harness, force=True) is None

    assert await harness.services.store.read_record(SCOPE) is None
    assert not run_trees_dir(_trees(tmp_path), LABEL).exists()


# --- the one sentence that needs real git ---------------------------------------------------------


def _git(where: Path, *argv: str) -> str:
    """One git command, for arranging and observing. Never for the thing under test.

    `tests/test_api.py`'s helper and its argument: a test that arranged through the adapter would be
    resting its arrangement on the behaviour it is about to check.
    """
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit on `main`, and no configuration from this machine.

    The `GIT_CONFIG_*` variables are what make this the same test everywhere - a developer with
    `commit.gpgsign` on, a `core.hooksPath` of their own or a template directory would otherwise be
    running a different one - and they go through `monkeypatch` so the adapters, which inherit the
    environment, see them too. It sits beside `tmp_path/trees` rather than under it: the trees root
    is not the repository.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL clear")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    seeded = work / SEEDED
    seeded.parent.mkdir(parents=True)
    seeded.write_bytes(b"one\n")
    _git(work, "add", SEEDED)
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work


def _over(repository: Path, tmp_path: Path) -> container.FakeServices:
    """The fakes bundle with its two git ports made real - the smallest arrangement that puts
    `api.clear` over an actual repository.

    Two of nine fields replaced, and both are needed: `workspaces` because the claim is about a git
    worktree registration and a git ref, and `history` because `clear`'s one question is asked
    through it and a `FakeHistory` answers about a repository that has never heard of these commits.
    The store stays the in-memory one - nothing here is a claim about a file under `AGL_HOME`.
    """
    trees = _trees(tmp_path)
    harness = container.fakes(trees, files={SEEDED: b"one\n"})
    return replace(
        harness,
        services=replace(
            harness.services,
            workspaces=GitWorkspaceProvider(repository, trees),
            history=GitHistory(repository),
        ),
    )


def _branch_exists(repository: Path, branch: str) -> bool:
    """Whether git still has this name, asked of the fully qualified ref."""
    done = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode == 0


@pytest.mark.asyncio
async def test_a_locked_worktree_is_what_refuses_a_clear(
    repository: Path, tmp_path: Path
) -> None:
    """The last sentence - "It refuses while a run holds a lock" - and the only mechanism in v1.1
    that makes it true.

    There is no durable "this run is live" record in AGL: `ARCHITECTURE.md`'s "Deliberately not
    built" refuses stored status by name, and leases are in-process, so a second `agl` invocation
    cannot see one. The registry mutex is cross-process but is held for milliseconds around
    `worktree prune` and refuses only on a deadline. What is left is git's own `worktree lock`, and
    it really does refuse: `prune` skips a locked entry even after its directory has gone, so the
    registration survives `remove`, and `git branch -D` then refuses the branch that registration
    holds - which `GitWorkspaceProvider.discard` re-raises as `ConflictError` after asking whether
    the branch is still there.

    A fake cannot be asked any of this, which is why this one test builds a repository; the module
    docstring argues the exception. The second half is what makes it a test about a lock: the same
    `clear`, over the same run, succeeds once the lock is off - so a `clear` that refused for any
    other reason would fail here rather than pass twice.

    `quiet` is the workflow because the branch has to be *deletable* for the refusal to be about the
    lock: a run that committed nothing sits at its base, so `contains` says yes and `clear` really
    does try to delete the name.
    """
    harness = _over(repository, tmp_path)
    await api.run(harness.services, PROJECT, "quiet", LABEL, (), points=POINTS)
    place = base_worktree(_trees(tmp_path), LABEL)
    _git(repository, "worktree", "lock", str(place))

    with pytest.raises(ConflictError) as caught:
        await _clear(harness)

    assert run_branch(LABEL) in str(caught.value)
    assert _branch_exists(repository, run_branch(LABEL)), (
        "the refusal was raised and the branch went anyway"
    )
    assert await harness.services.store.read_record(SCOPE) is not None, (
        "`store.remove` is the last line of `clear` and ran although the line above it refused"
    )

    _git(repository, "worktree", "unlock", str(place))

    assert await _clear(harness) is None
    assert not _branch_exists(repository, run_branch(LABEL)), (
        "the clear that was refused only by the lock still did not delete the branch once the lock "
        "was off, so the refusal above was about something else"
    )
    assert await harness.services.store.read_record(SCOPE) is None
