"""The two teardown verbs, why they are two, and the ordering `clear` calls them in.

Split out of `workspace.py` along a line the port draws itself. `remove` takes the isolated place
back and leaves the line of work it carried; `discard` deletes the line of work itself. They are
separate because `clear` needs them apart (§3.10): it takes back every isolated place a run holds
unconditionally, deletes the child lines of work unconditionally, and deletes the run's own line of
work **only if** `History` says it is already contained in the base ref. A single teardown verb
could not express that, and this port holds no policy about which of the two is right when.

## How two verbs are told apart from outside

Nothing here counts directories or measures disk. What separates the two through the interface is
what a *reopen* afterwards hands back, and the port says both halves of it:

* After `remove`, the line of work still exists, so opening again gives back a checkout cut from a
  name that is still there - at the head it was last committed to, and without the previous
  checkout's uncommitted work, because the place itself was taken back.
* After `discard`, the name is gone, so opening again provisions afresh from `base` - at the head a
  new workspace starts at, with the committed work no longer in it.

An implementation where those two look the same has one teardown verb wearing two names, and
`clear`'s conditional deletion means nothing.

**Tolerance of absence is pinned twice**, because `clear` after a crash is the ordinary case rather
than the exceptional one, and a teardown that raises on a half-finished setup is a teardown every
caller learns to wrap in a bare `except` - which is how the next bug gets hidden.

`WorkspaceContract` in `workspace.py` inherits this class. Implementers subclass that one, never
this one, and the `provider` and `base` fixtures these tests take are declared there.
"""

import pytest

from agl.ports.workspace import WorkspaceProvider

from ._workspace_files import (
    CHILD,
    LABEL,
    SCRATCH,
    SIBLING,
    TRACKED,
    body,
    read,
    record,
    write,
)


class WorkspaceTeardownContract:
    """`remove` then `discard`: what each one takes, what survives it, and neither one raising.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_remove_takes_the_place_back_and_leaves_the_line_of_work_to_be_cut_again(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """The half `clear` runs unconditionally, and the half that is not destructive.

        Both directions are asserted, because either one alone admits a wrong implementation. The
        committed work has to survive - `remove` gives back a checkout that can be cut again from
        a name that still exists, and an implementation that deleted the name here would make
        `discard` a second word for the same verb and `clear`'s conditional deletion a fiction.
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
            f"is `discard`, and §3.10 has `clear` call it only under a condition this one ignores"
        )
        assert read(again, TRACKED) == body("work that outlives its checkout"), (
            "the committed work is not in the reopened checkout, so it was cut from somewhere "
            "other than the line of work that still carries it"
        )
        assert read(again, SCRATCH) is None, (
            f"{SCRATCH} was never committed and is still there after the place was taken back and "
            f"handed out again. `remove` takes the isolated place back; one that left the working "
            f"tree exactly as it stood took nothing back, and `clear` frees nothing"
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
        """`clear` after a crash is the ordinary case, not the exceptional one.

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
