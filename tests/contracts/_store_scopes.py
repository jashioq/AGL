"""The two members that ask for more than access by address: `namespaces` and `remove`.

Split out of `store.py` along a line the port draws itself. Four of its six methods are lookups -
hand over an address, get a document or `None` - and these two are enumeration and deletion *under
a scope*, which the port's own docstring calls the one place it asks an implementation for more
than get and put by key. An implementation whose addressing enumerates gets both for nothing; one
that can only get and put has to keep an index and keep it current under concurrent writers. So
these are the tests such an implementation will fail first, and they are worth reading together.

Neither member is asserted here for anything the port did not promise. `namespaces` promises a
*stable* order and deliberately declines to say sorted by what, so what is asserted is the set and
the repeatability, never the sequence. `remove` is explicitly not required to be atomic, so nothing
here interrupts one; it *is* explicitly required to tolerate absence, so that is pinned twice.

`StoreContract` in `store.py` inherits this class. Implementers subclass that one, never this one.
"""

import pytest

from agl.ports.store import Store

from ._store_documents import (
    CHILD,
    FOREIGN_RUN,
    GRANDCHILD,
    RUN,
    SIBLING,
    SIBLING_RUN,
    STEP,
    digest,
    entry,
    record,
)


class StoreScopeContract:
    """What `namespaces` reports and what `remove` takes, which are two sides of one address.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_namespaces_reports_the_children_recorded_immediately_under_a_scope(
        self, store: Store
    ) -> None:
        """Immediate children only: a flattened answer loses which parent each name hung from.

        Order is asserted as a set, because the port promises a *stable* order and deliberately
        declines to say sorted by what - a suite that pinned sorting would be pinning a tie-break
        the port left open. Stability is asserted the only way one store can show it: the same
        question twice gets the same sequence back.
        """
        await store.write_entry(RUN.inside(CHILD), STEP, digest("a"), entry("a"))
        await store.write_entry(RUN.inside(SIBLING), STEP, digest("b"), entry("b"))
        deep = RUN.inside(CHILD).inside(GRANDCHILD)
        await store.write_entry(deep, STEP, digest("c"), entry("c"))

        under_run = await store.namespaces(RUN)
        assert set(under_run) == {CHILD, SIBLING}, f"immediate children only, got {under_run}"
        assert len(under_run) == 2, f"one name per child, and no name twice: {under_run}"
        assert under_run == await store.namespaces(RUN), "the same set answers the same way twice"
        assert set(await store.namespaces(RUN.inside(CHILD))) == {GRANDCHILD}
        assert await store.namespaces(RUN.inside(SIBLING)) == ()
        assert await store.namespaces(deep) == ()

    async def test_namespaces_reports_what_was_recorded_and_not_what_was_asked_about(
        self, store: Store
    ) -> None:
        """A namespace is here because something was recorded under it, and for no other reason.

        Four ways to be asked about one without recording anything under it: a read that misses
        inside it, a record written from inside it (namespaces are not consulted), a step recorded
        at the run itself - `steps/` and `worktrees/` are sibling subtrees, and a step is not a
        child line of work - and a removal of a scope that was never there.

        The empty answer for a run that recorded nothing is a reading the port does not spell out.
        It follows from its one consumer: `clear` walks this after a crash, and deletes a line of
        work for every name it is given.
        """
        assert await store.namespaces(RUN) == ()
        assert await store.read_entry(RUN.inside(CHILD), STEP, digest("miss")) is None
        await store.write_record(RUN.inside(SIBLING), record("auth"))
        await store.write_entry(RUN, STEP, digest("at the run"), entry("at the run"))
        await store.remove(RUN.inside(GRANDCHILD))

        assert await store.namespaces(RUN) == (), (
            "a namespace appeared under a run that recorded nothing under one - `clear` takes "
            "back a workspace and deletes a line of work for every name this answers with"
        )
        assert await store.namespaces(SIBLING_RUN) == ()

    async def test_removing_a_run_takes_its_record_its_entries_and_every_scope_below_it(
        self, store: Store
    ) -> None:
        """At depth zero `remove` is the whole run, which is what `clear` wants (§3.10).

        The survivors are chosen to be the ones a careless implementation takes with it: another
        run in the same project, and a run in another project carrying the same label.
        """
        inside = (RUN, RUN.inside(CHILD), RUN.inside(CHILD).inside(GRANDCHILD))
        for scope in inside:
            await store.write_entry(scope, STEP, digest("one"), entry("one"))
        await store.write_record(RUN, record("auth"))
        await store.write_record(SIBLING_RUN, record("payments"))
        await store.write_entry(SIBLING_RUN, STEP, digest("one"), entry("beside"))
        await store.write_entry(FOREIGN_RUN, STEP, digest("one"), entry("elsewhere"))

        await store.remove(RUN)

        assert await store.read_record(RUN) is None
        for scope in inside:
            assert await store.read_entry(scope, STEP, digest("one")) is None
        assert await store.namespaces(RUN) == ()
        assert await store.read_record(SIBLING_RUN) == record("payments")
        assert await store.read_entry(SIBLING_RUN, STEP, digest("one")) == entry("beside")
        assert await store.read_entry(FOREIGN_RUN, STEP, digest("one")) == entry("elsewhere")

    async def test_removing_a_nested_scope_takes_its_subtree_and_nothing_above_or_beside_it(
        self, store: Store
    ) -> None:
        """Deeper, `remove` is that worktree's subtree: its own entries and everything under it."""
        child = RUN.inside(CHILD)
        grandchild = child.inside(GRANDCHILD)
        sibling = RUN.inside(SIBLING)
        for scope, marker in ((RUN, "run"), (child, "child"), (grandchild, "deep"), (sibling, "b")):
            await store.write_entry(scope, STEP, digest(marker), entry(marker))
        await store.write_record(RUN, record("auth"))

        await store.remove(child)

        assert await store.read_entry(child, STEP, digest("child")) is None
        assert await store.read_entry(grandchild, STEP, digest("deep")) is None
        assert await store.read_entry(RUN, STEP, digest("run")) == entry("run")
        assert await store.read_entry(sibling, STEP, digest("b")) == entry("b")
        assert await store.read_record(RUN) == record("auth"), "the run's record is above it"
        assert set(await store.namespaces(RUN)) == {SIBLING}

    async def test_removing_what_is_not_there_succeeds_and_says_nothing(
        self, store: Store
    ) -> None:
        """`clear` after a crash is the ordinary case, not the exceptional one.

        A teardown that raised on a half-finished setup would be one every caller learns to wrap
        in a bare `except`, and a bare `except` around a delete is how the next bug gets hidden.

        Three of the calls below carry no assertion because there is nothing to assert: `remove`
        answers with nothing, and *returning at all* is the whole of what is being pinned.
        """
        await store.remove(RUN)
        await store.remove(RUN.inside(CHILD))

        await store.write_entry(RUN, STEP, digest("one"), entry("one"))
        await store.remove(RUN)
        await store.remove(RUN)
        assert await store.read_entry(RUN, STEP, digest("one")) is None

    async def test_a_scope_that_was_removed_can_be_recorded_into_again(
        self, store: Store
    ) -> None:
        """`agl clear auth` and then `agl run --label auth` is an ordinary sequence (§3.10).

        A removed address is a free one, not a tombstoned one: after the removal, a write lands
        and a read answers with it, exactly as at an address nobody had ever used.
        """
        await store.write_record(RUN, record("first"))
        await store.write_entry(RUN.inside(CHILD), STEP, digest("one"), entry("first"))
        await store.remove(RUN)

        await store.write_record(RUN, record("second"))
        await store.write_entry(RUN.inside(CHILD), STEP, digest("one"), entry("second"))
        assert await store.read_record(RUN) == record("second")
        assert await store.read_entry(RUN.inside(CHILD), STEP, digest("one")) == entry("second")
        assert set(await store.namespaces(RUN)) == {CHILD}
