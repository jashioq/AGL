"""The two teardown verbs, why they are two, the ordering every caller uses, and the two above them.

Split out of `workspace.py` along a line the port draws itself. `remove` takes the isolated place
back and leaves the line of work it carried; `discard` deletes the line of work itself. They are
separate because the second cannot be done while the first is outstanding - a branch a checkout is
sitting on is one `git branch -D` refuses - which is what "call `remove` first" on the port means
and what an implementation is within its rights to enforce. One verb would bury that ordering
inside itself, and this port holds no policy about when either half is right, which is exactly what
its two callers spend differently. `api.clear` spends both, on every address, every time.
`sdk/_engine/teardown.py`, which releases a run that finished, spends `remove` on every address and
`discard` only where the line of work it would delete has already reached `agl/<label>` - so the
run's own branch survives its checkout, and so does a child's whose work landed nowhere.

## How two verbs are told apart from outside

Nothing here counts directories or measures disk. What separates the two through the interface is
what a *reopen* afterwards hands back, and the port says both halves of it:

* After `remove`, the line of work still exists, so opening again gives back a checkout cut from a
  name that is still there - at the head it was last committed to, and without the previous
  checkout's uncommitted work, because the place itself was taken back.
* After `discard`, the name is gone, so opening again provisions afresh from `base` - at the head a
  new workspace starts at, with the committed work no longer in it.

An implementation where those two look the same has one teardown verb wearing two names, and
nothing outside it can tell whether a run's line of work is still there.

**Tolerance of absence is pinned twice**, because `agl clear` after a crash is the ordinary case
rather than the exceptional one, and a teardown that raises on a half-finished setup is one every
caller learns to wrap in a bare `except` - which is how the next bug gets hidden.

## `residue`, and why a suite with no ledger is the right place to ask it

The fourth member answers what a run has left standing, and **a provider is the only thing that can
answer it at all**: `sdk/_engine/steps.py` cuts a checkout and its branch before the journal writes
an entry, so a namespace whose first step died is in no ledger anywhere and `Store.namespaces` walks
past it. `api.clear` used to walk past it too, exiting 0 over a branch and a checkout it had left
behind, and a later run under the same label attached to that branch instead of cutting a fresh one.

Nothing in this suite keeps a ledger, which is exactly the state that has to be asked about: every
namespace below is provisioned through `open` and recorded nowhere, so a provider answering out of
something a caller told it would answer with nothing here. What the suite cannot show is the
difference between a provider that looks and one that remembers what it made - both pass, and
`tests/test_clear.py` is where a provider is asked about a checkout made by a process that is gone.

## `check_removable`, and the half of it no suite can reach

The third member is the one `api.clear` spends on every address before it spends either of the
other two, because both of them are destructive and the refusals are at the end of the walk: the
run's own place is removed last, so a `clear` that discovered a checkout it could not take back
had already deleted the child branches, which are the only copy of work that reached no other line.

**What this suite can ask of it is that it does not refuse**, which is the half a wrong
implementation gets wrong in the safe direction and the half that would otherwise make `clear`
useless: a provider answering "no" to everything passes every other test in this file. **What it
cannot ask is that a place something really is holding is refused**, for the reason gap 1 in
`workspace.py` gives about `open`'s `ConflictError` - the state needs something outside the
provider under test pinning one of its checkouts, and the only thing making checkouts here is that
provider. A provider that never raises passes this suite; where a real refusal is met is
`tests/adapters/test_git_workspace.py`, which locks a place the adapter made, and
`tests/test_clear.py`, which does the same under `api.clear` and asserts what survived it.

`WorkspaceContract` in `workspace.py` inherits this class. Implementers subclass that one, never
this one, and the `provider` and `base` fixtures these tests take are declared there.
"""

import pytest
from agl.ports.workspace import WorkspaceProvider
from ._workspace_files import (
    CHILD,
    LABEL,
    SCRATCH,
    SECOND_LABEL,
    SIBLING,
    TRACKED,
    body,
    read,
    record,
    write,
)

class WorkspaceTeardownContract:
    """`residue`, `check_removable`, `remove`, `discard`: what each takes, what survives, what goes.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_a_place_this_provider_cut_is_one_it_finds_again_with_nothing_recorded_anywhere(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """The member `api.clear` reads its walk out of, asked of a run no ledger describes.

        Two namespaces are opened and one of them is never written to, because the namespace this
        exists for is the one whose first step died: the checkout was cut, the branch was made, and
        nothing recorded either. A provider that answered out of what it had been told about would
        answer with nothing here, and a `clear` reading its walk out of that leaves a branch a later
        run under the same label attaches to.

        The run's own place is opened too and is asserted absent from the answer. It is addressed by
        the absence of a namespace everywhere else on this port, so there is no name for it to
        appear under, and a provider inventing one would hand `api.clear` a `Namespace` naming the
        place it removes last and separately.
        """
        await provider.open(LABEL, None, base)
        workspace = await provider.open(LABEL, CHILD, base)
        write(workspace, TRACKED, body("work nothing wrote down"))
        await record(workspace, "work nothing wrote down")
        await provider.open(LABEL, SIBLING, base)

        left = await provider.residue(LABEL)

        assert set(left) == {CHILD, SIBLING}, (
            f"asked what run {str(LABEL)!r} left standing, this provider answered {left!r}. Both "
            f"namespaces were cut through `open` and neither was recorded anywhere - this member "
            f"is the only thing that can see one whose first step never wrote an entry"
        )
        assert left == await provider.residue(LABEL), (
            "the same question answered differently twice, so a teardown walking this would take a "
            "different set of places each time it was run"
        )

    async def test_what_a_run_left_says_nothing_about_a_run_that_cut_no_place_at_all(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """Two runs are two answers, and a run that provisioned nothing has left nothing.

        `api.clear` walks whatever comes back, so an answer carrying another run's namespaces is a
        clear that removes checkouts and deletes branches belonging to a label nobody typed. The
        empty half matters on its own: a `clear` after a crash that got no further than the record
        meets exactly this, and it is the ordinary case rather than the exceptional one.
        """
        assert await provider.residue(LABEL) == ()

        await provider.open(LABEL, CHILD, base)

        assert await provider.residue(SECOND_LABEL) == (), (
            f"a place cut under {str(LABEL)!r} came back as something run {str(SECOND_LABEL)!r} "
            f"left, and `api.clear` removes every place this member names"
        )

    async def test_a_place_that_has_been_removed_and_discarded_is_no_longer_something_left(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """What the two verbs took stops coming back, or a second clear walks the first's ghosts.

        The pair is spent in the port's own order over one of two namespaces, and the other is
        asserted still there - so a provider that answered `()` for everything would fail on the
        half that survived rather than passing this by forgetting the whole run.
        """
        await provider.open(LABEL, CHILD, base)
        await provider.open(LABEL, SIBLING, base)

        await provider.remove(LABEL, CHILD)
        await provider.discard(LABEL, CHILD)

        left = await provider.residue(LABEL)
        assert CHILD not in left, (
            f"{str(CHILD)!r} was removed and discarded and is still named as something the run "
            f"left, so a second clear would spend both verbs on a place that is already gone and "
            f"name it in what it reports having taken"
        )
        assert SIBLING in left, (
            "the untouched namespace went missing too, so this answered about the teardown rather "
            "than about what is there"
        )

    async def test_remove_takes_the_place_back_and_leaves_the_line_of_work_to_be_cut_again(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """The half that is not destructive, and the one the other half needs run first.

        Both directions are asserted, because either one alone admits a wrong implementation. The
        committed work has to survive - `remove` gives back a checkout that can be cut again from
        a name that still exists, and an implementation that deleted the name here would make
        `discard` a second word for the same verb and the ordering the port insists on a fiction.
        The *uncommitted* work has to be gone - the isolated place was taken back, and a `remove`
        that left the working tree where it was took nothing back at all.

        Reopening after a `remove` is read as a reopen and not a fresh provisioning: the same base
        is passed, and the head that comes back is the one that was committed rather than the one
        a new workspace starts at. `workspace.py` argues that reading where the fixtures are.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        fresh = await workspace.head()
        write(workspace, TRACKED, body("work that outlives its checkout"))
        landed = await record(workspace, "work that outlives its checkout")
        write(workspace, SCRATCH, body("in flight when the place was taken back"))
        assert landed != fresh, "a commit moved the head, so the two states are distinguishable"

        await provider.remove(LABEL, CHILD)
        again = await provider.open(LABEL, CHILD, base)

        reopened = await again.head()
        assert reopened == landed, (
            f"after a remove, reopening handed back a workspace at {reopened!r} rather "
            f"than at {landed!r}, the head its line of work was committed to. `remove` takes the "
            f"place back and the line of work survives - the verb that deletes the line of work "
            f"is `discard`, and this one has to leave it something to delete"
        )
        assert read(again, TRACKED) == body("work that outlives its checkout"), (
            "the committed work is not in the reopened checkout, so it was cut from somewhere "
            "other than the line of work that still carries it"
        )
        assert read(again, SCRATCH) is None, (
            f"{SCRATCH} was never committed and is still there after the place was taken back and "
            f"handed out again. `remove` takes the isolated place back; one that left the working "
            f"tree exactly as it stood took nothing back, and freed nothing"
        )

    async def test_discard_after_remove_deletes_the_line_of_work_itself(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """Destructive in the way `remove` is not: `remove` gives back a checkout, this deletes
        the name.

        Called in the port's own order - `remove` first, then `discard` - because an implementation
        is within its rights to refuse to delete a line of work that something still has open, and
        calling them this way round means no caller has to know whether it does.

        What proves the name is gone is that opening again provisions rather than reopens: the
        head is the one a new workspace starts at, and the committed work is not in the tree. That
        is the same observation the `remove` test makes and the opposite answer, which is the whole
        of what makes these two verbs two.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        fresh = await workspace.head()
        write(workspace, TRACKED, body("work whose name is about to go"))
        landed = await record(workspace, "work whose name is about to go")
        assert landed != fresh, "a commit moved the head, so the two states are distinguishable"

        await provider.remove(LABEL, CHILD)
        await provider.discard(LABEL, CHILD)
        again = await provider.open(LABEL, CHILD, base)

        reopened = await again.head()
        assert reopened == fresh, (
            f"after a remove and a discard, reopening handed back a workspace at "
            f"{reopened!r} rather than at {fresh!r}, where a newly provisioned one "
            f"starts. `discard` deletes the line of work itself, so there is no name left to cut "
            f"from and `base` is consulted again - an implementation where this answers the same "
            f"as a plain `remove` has one teardown verb under two names"
        )
        assert read(again, TRACKED) is None, (
            "work committed to a discarded line of work is still in a freshly provisioned "
            "checkout, so the line of work was not deleted"
        )

    async def test_removing_and_discarding_what_is_not_there_succeeds_and_says_nothing(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """`agl clear` after a crash is the ordinary case, not the exceptional one.

        Both verbs, on both kinds of address - a namespace and the run's own `None` - against a run
        that never provisioned anything, and then both of them twice over one that did. A teardown
        that raised on a half-finished setup would be one every caller wraps in a bare `except`,
        and a bare `except` around a delete is how the next bug gets hidden.

        Most of the calls below carry no assertion because there is nothing to assert: these two
        members answer with nothing, and *returning at all* is the whole of what is being pinned.
        The one assertion at the end is there so that a suite cannot pass this by tearing nothing
        down - the second pair really did remove and discard what the first pair created.
        """
        await provider.remove(LABEL, CHILD)
        await provider.discard(LABEL, CHILD)
        await provider.remove(LABEL, None)
        await provider.discard(LABEL, None)

        workspace = await provider.open(LABEL, SIBLING, base)
        write(workspace, TRACKED, body("about to be torn down twice"))
        await record(workspace, "about to be torn down twice")
        await provider.remove(LABEL, SIBLING)
        await provider.remove(LABEL, SIBLING)
        await provider.discard(LABEL, SIBLING)
        await provider.discard(LABEL, SIBLING)

        again = await provider.open(LABEL, SIBLING, base)
        assert read(again, TRACKED) is None, (
            "tearing a line of work down twice left its work behind, so the second call did not "
            "tolerate the absence - it undid the first"
        )

    async def test_a_checkout_this_provider_made_is_one_it_says_can_be_taken_back(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """The ordinary answer, which is the one a wrong implementation gets wrong safely.

        Both addresses, over places this provider provisioned itself and is therefore the only
        holder of - so there is nothing for it to legitimately refuse about, and `api.clear` would
        be unable to clear anything it ever made if it refused here anyway. That is the whole claim,
        and there is no assertion under these calls because *returning at all* is it.

        Spent between an `open` and the teardown rather than after it, because the state the answer
        is about is a run standing at the moment somebody types `agl clear`: a checkout on disk,
        with a line of work under it, and nothing torn down yet.
        """
        await provider.open(LABEL, None, base)
        workspace = await provider.open(LABEL, CHILD, base)
        write(workspace, TRACKED, body("work a clear is about to be aimed at"))
        await record(workspace, "work a clear is about to be aimed at")

        await provider.check_removable(LABEL, CHILD)
        await provider.check_removable(LABEL, None)

        await provider.remove(LABEL, CHILD)
        await provider.discard(LABEL, CHILD)

    async def test_asking_whether_a_place_that_is_not_there_can_be_taken_back_says_nothing(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """The same tolerance the two verbs have, for the same reason, on the member above them.

        A `clear` after a crash meets a run whose `_base` was never cut, and a second `clear` after
        one that stopped part-way meets places its own first pass already took: a check that refused
        either would be a check nobody could get past, on exactly the runs the verb exists for.

        Both kinds of address, against a run that provisioned nothing, and then once more over a
        place this suite provisioned and tore down - which is the half that is not vacuous, since a
        provider remembering a place it deleted would answer about it here.
        """
        await provider.check_removable(LABEL, CHILD)
        await provider.check_removable(LABEL, None)

        workspace = await provider.open(LABEL, SIBLING, base)
        write(workspace, TRACKED, body("about to be torn down and then asked about"))
        await record(workspace, "about to be torn down and then asked about")
        await provider.remove(LABEL, SIBLING)
        await provider.discard(LABEL, SIBLING)

        await provider.check_removable(LABEL, SIBLING)

        again = await provider.open(LABEL, SIBLING, base)
        assert read(again, TRACKED) is None, (
            "the teardown between the two checks did not happen, so the second one was asked about "
            "a place that was never taken away and the tolerance it is about went untested"
        )
