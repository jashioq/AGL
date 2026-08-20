"""`StoreContract` - what every `Store` owes, asserted before any implementation of one exists.

Subclass it once per implementation, override the one fixture, and add nothing:

    class TestTheStoreIWrote(StoreContract):
        @pytest.fixture
        def store(self) -> Store:
            return TheStoreIWrote(...)

The real adapter and the fake both run this class, which is the whole mechanism keeping a fake
from drifting into fiction (§1.9). It is written here, at stage 3, before either exists, because a
subagent that writes its own tests writes tests that pass.

`StoreContract` is one class assembled from three modules, and only this name is public.
`_store_documents` holds the addresses and documents every test is built from; `_store_scopes`
holds `namespaces` and `remove`, the two members that enumerate under a scope rather than fetch by
one; `_store_concurrency` holds the atomic-write clause and the machinery it takes to watch one.
The split follows seams the port draws itself and each module's docstring says which.

## Written against the port, never against a backend

Nothing here knows what a store is made of. No path, no file, no directory listing, no
serialisation format, no `tmp_path`. Addresses are built out of `RunScope`, `StepName` and sha256
digests, because those are the whole of what the port accepts; documents are JSON objects, because
those are the whole of what it keeps. The next implementation might be a dict, a database or
something across a network, and a test that would only pass against a filesystem would be a test
that refused it for the wrong reason.

The one place that rule bends is deliberate: the digests really are sha256 hexdigests rather than
short strings, because an implementation that spends a digest as a name of its own is entitled to
check it first (`_store_documents` says why at more length).

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run of
this suite does not entitle anybody to believe. Every one of these is a limit of what the port's
own surface can be made to reveal, not a test somebody forgot.

1. **Durability across a crash.** Nothing here can kill a process mid-write. "Exists complete or
   not at all" is asserted against what a concurrent reader in this process can observe, which is
   the half of the clause that has a witness. An implementation that buffers a write in memory and
   would lose it on power loss passes this suite. Proving otherwise needs a second process, and
   this suite cannot start one: the fixture hands over an already-built `Store`, and the port
   deliberately hands back no location, so nothing here can open the same state twice.

2. **Any part of a write the implementation does not yield during.** Every method is `async` and
   this suite drives one event loop, so a reader observes the store only at moments the
   implementation awaits. A write that does all of its work without awaiting is never seen
   part-way through - there is no part-way through, from this loop - and the concurrency tests
   assert against it without being able to fail. `_store_concurrency` states this where the tests
   are, and says why driving reads from a second thread was refused rather than adopted.

3. **Concurrency between two `Store` objects over one body of state.** Two `agl` invocations
   sharing one `AGL_HOME` are the case a real implementation's atomic rename is for, and this
   suite exercises one object in one process.

4. **That distinct addresses are written without a shared lock.** The tests catch an
   implementation that keeps everything in one document and loses a write to a neighbouring
   address; they cannot catch one that keeps everything in one document and serialises every write
   behind a single mutex. That one is correct and merely slow, and the difference is visible only
   as time - which a suite cannot assert on without a threshold that fails honest implementations
   on loaded machines. The clause is real and the deliverable was asked to say so plainly: through
   this interface, a global mutex is invisible.

5. **Stable order across anything but two calls in a row.** `namespaces` promises the same
   recorded set yields the same sequence *every time*, which extends across restarts. This suite
   asks one store twice; it cannot build a second store over the same state to ask again.

6. **That an implementation holds no buffer.** The port refuses to admit a flush, and a read after
   a write returning the value is equally satisfied by a buffer that answers its own reads.

7. **What a `remove` racing a write does.** The port says nothing about that ordering, so nothing
   here provokes it. `remove` is also not asserted atomic, because the port explicitly does not
   ask for it.

8. **Whether a write copies the mapping it was handed.** The suite never edits a mapping it passed
   to a write. `Mapping` on the way in says a caller need not copy what it already has; it does
   not say the store snapshots it, and asserting either answer would be inventing a clause.

9. **Non-finite floats.** `JsonValue` admits a `float`, and NaN and the infinities are floats JSON
   has no standard spelling for. An implementation may reasonably refuse them and the port has no
   opinion, so no test here writes one.

## Where the port is silent, and what this suite assumed

Three readings had to be settled to write a test at all, and each is argued at the test that
depends on it: that ownership of what a read hands back is ownership all the way down and not one
level deep; that an overwrite may not be observed as a momentary absence; and that `namespaces`
under a scope that recorded nothing answers with an empty tuple rather than raising - `clear`
after a crash is its one caller, which settles it.
"""

from collections.abc import Iterator
from copy import deepcopy

import pytest

from agl.ports.run import JsonValue
from agl.ports.store import Store

from ._store_concurrency import StoreConcurrencyContract
from ._store_documents import (
    CHILD,
    EVERY_JSON_SHAPE,
    FOREIGN_RUN,
    GRANDCHILD,
    OTHER_STEP,
    RUN,
    SIBLING,
    SIBLING_RUN,
    STEP,
    digest,
    entry,
    record,
)
from ._store_scopes import StoreScopeContract


class StoreContract(StoreScopeContract, StoreConcurrencyContract):
    """The suite. Everything a `Store` promises, and nothing an implementation gets to choose.

    Its own tests are the four lookups: what an address answers with, what a document survives
    being written as, and who owns what a read hands back. The two halves it inherits are
    `_store_scopes` - `namespaces` and `remove`, which enumerate under a scope rather than fetch
    by one - and `_store_concurrency`, the atomic-write clause and what it takes to watch it.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and
    a test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def store(self) -> Store | Iterator[Store]:
        """The implementation under test. Override this, and override nothing else.

        One knob on purpose. Every address, name and document this suite needs it builds itself
        out of the pure types, so pointing the suite at an implementation is one visible override
        and there is no second place to point it somewhere else by accident.

        The return type is a union so that `mypy --strict` accepts either shape of override:
        return a store, or `yield` one and tear it down after. pytest takes both, and an override
        narrowing a plain `-> Store` to `-> Iterator[Store]` would not typecheck. An `async def`
        fixture (`@pytest_asyncio.fixture`) is a third shape no annotation here can cover; if an
        implementation needs one, a `# type: ignore[override]` on it is the honest escape and
        costs this suite nothing.
        """
        raise NotImplementedError(
            "the Store contract suite has no implementation to run against: subclass "
            "StoreContract and override the `store` fixture to hand back the Store under test"
        )

    async def test_a_run_with_nothing_recorded_answers_none_to_every_read(
        self, store: Store
    ) -> None:
        """`None` is the whole of replay's decision (§3.6) and of what `resume` refuses on."""
        assert await store.read_record(RUN) is None
        assert await store.read_entry(RUN, STEP, digest("nothing")) is None
        assert await store.read_entry(RUN.inside(CHILD), STEP, digest("nothing")) is None
        assert await store.namespaces(RUN) == ()

    async def test_every_shape_of_json_a_document_may_hold_survives_the_round_trip(
        self, store: Store
    ) -> None:
        """Nested objects, arrays, unicode, null, booleans, ints and floats, all read back equal.

        Equality is checked and then three types are checked on top of it, because Python's
        equality is not JSON's: `True == 1` and `1 == 1.0`, so a store that turned a boolean into
        an integer, or every number into a float, would pass a comparison of whole documents. The
        oversized integer is there for the implementation that round-trips numbers through a
        double and silently edits what it was handed.
        """
        document: dict[str, JsonValue] = {**entry("zoo"), "value": EVERY_JSON_SHAPE}
        await store.write_record(RUN, EVERY_JSON_SHAPE)
        await store.write_entry(RUN, STEP, digest("zoo"), document)

        assert await store.read_record(RUN) == EVERY_JSON_SHAPE
        read = await store.read_entry(RUN, STEP, digest("zoo"))
        assert read == document

        assert read is not None
        value = read["value"]
        assert isinstance(value, dict)
        assert value["true"] is True and value["false"] is False, "a boolean is not an integer"
        assert isinstance(value["zero"], int) and not isinstance(value["zero"], bool)
        assert isinstance(value["float"], float), "a float is not an integer either"
        assert value["wider than a double"] == 2**53 + 1, "an integer is kept, not approximated"

    async def test_absence_and_a_recorded_null_never_read_alike(self, store: Store) -> None:
        """What makes the absence of an `exists` member honest: the read answers exactly.

        Three documents a careless implementation would confuse with nothing recorded - an effect
        step's entry, whose own `value` is null; an entry that is the empty object; and a record
        whose every field is null - written beside three addresses nobody wrote to. `is None` has
        to track which were written and nothing else about them.

        The empty object is a reading rather than a quotation: the port says both kinds of
        document are JSON objects and that there is none AGL wants to keep that it turns away, and
        `None` meaning "nothing recorded" and nothing else is what makes `{}` a recorded value.
        """
        effect = entry("effect")
        empty: dict[str, JsonValue] = {}
        await store.write_entry(RUN, STEP, digest("effect"), effect)
        await store.write_entry(RUN, STEP, digest("empty"), empty)
        await store.write_record(RUN, {"workflow": None, "params": None})

        recorded = await store.read_entry(RUN, STEP, digest("effect"))
        assert recorded is not None, "an entry whose value is null is a recorded entry"
        assert recorded["value"] is None and recorded == effect
        assert await store.read_entry(RUN, STEP, digest("empty")) == empty
        assert await store.read_record(RUN) == {"workflow": None, "params": None}

        assert await store.read_entry(RUN, STEP, digest("unwritten")) is None
        assert await store.read_entry(RUN.inside(CHILD), STEP, digest("effect")) is None
        assert await store.read_record(SIBLING_RUN) is None

    async def test_editing_what_a_read_returned_leaves_the_store_holding_what_was_written(
        self, store: Store
    ) -> None:
        """A read hands back something the caller owns, and the caller is going to edit it.

        The edits below reach into a nested object and a nested list, not only the top level. A
        shallow copy passes a test that edits only the top level while still handing out the
        store's own state one level down, which is the same bug one indirection further in; the
        port's reason for the clause - the first caller to edit what it read would edit the store
        - is about editing, not about the depth the edit happened at. The comparison is against a
        copy taken before the write, so an implementation that keeps the caller's mapping *and*
        hands it back cannot pass by having the edit land in both places at once.
        """
        written = record("auth")
        expected = deepcopy(written)
        await store.write_record(RUN, written)
        held_record = await store.read_record(RUN)
        assert held_record is not None
        params = held_record["params"]
        assert isinstance(params, dict)
        tickets = params["tickets"]
        assert isinstance(tickets, list)
        tickets.append("T-99")
        params["request"] = "edited"
        held_record["branch"] = "edited"
        assert await store.read_record(RUN) == expected

        recorded = entry("owned", value={"tickets": [{"id": "T-01"}]})
        unedited = deepcopy(recorded)
        await store.write_entry(RUN, STEP, digest("owned"), recorded)
        held_entry = await store.read_entry(RUN, STEP, digest("owned"))
        assert held_entry is not None
        value = held_entry["value"]
        assert isinstance(value, dict)
        rows = value["tickets"]
        assert isinstance(rows, list)
        rows.clear()
        held_entry["fingerprint"] = "edited"
        assert await store.read_entry(RUN, STEP, digest("owned")) == unedited

    async def test_the_record_belongs_to_the_run_and_is_reached_from_anywhere_inside_it(
        self, store: Store
    ) -> None:
        """Namespaces are not consulted: there is one record per run and it belongs to the run."""
        deep = RUN.inside(CHILD).inside(GRANDCHILD)
        written = record("auth")
        await store.write_record(deep, written)

        assert await store.read_record(RUN) == written
        assert await store.read_record(RUN.inside(CHILD)) == written
        assert await store.read_record(RUN.inside(SIBLING)) == written
        assert await store.read_record(deep) == written
        assert await store.read_record(SIBLING_RUN) is None, "a label is one run, not two"
        assert await store.read_record(FOREIGN_RUN) is None, "and labels are scoped per project"

    async def test_writing_where_a_value_already_sits_supersedes_it_and_nothing_beside_it(
        self, store: Store
    ) -> None:
        """A second write is not refused - §3.10 refuses a taken label long before this port sees
        it, and a refusal here would make an interrupted first write unrecoverable. Entries at
        other digests are untouched: a superseded entry is what answers "why did this re-run".
        """
        await store.write_record(RUN, record("first"))
        await store.write_record(RUN, record("second"))
        assert await store.read_record(RUN) == record("second")

        await store.write_entry(RUN, STEP, digest("kept"), entry("kept"))
        await store.write_entry(RUN, STEP, digest("replaced"), entry("replaced"))
        await store.write_entry(RUN, STEP, digest("replaced"), entry("replacement"))
        assert await store.read_entry(RUN, STEP, digest("replaced")) == entry("replacement")
        assert await store.read_entry(RUN, STEP, digest("kept")) == entry("kept")

    async def test_an_entry_is_addressed_by_its_scope_its_step_and_its_digest_together(
        self, store: Store
    ) -> None:
        """Eight addresses, each differing from the run's in exactly one part of the address.

        The same step name under two children is two entries (§3.6), which is why `steps/` is
        nested per worktree rather than pooled; a re-run against changed inputs gets its own
        digest and its own entry beside the old one; and a label means one run in one project.
        """
        addresses = {
            "the run": (RUN, STEP, digest("one")),
            "a child": (RUN.inside(CHILD), STEP, digest("one")),
            "its sibling": (RUN.inside(SIBLING), STEP, digest("one")),
            "a grandchild": (RUN.inside(CHILD).inside(GRANDCHILD), STEP, digest("one")),
            "another step": (RUN, OTHER_STEP, digest("one")),
            "another digest": (RUN, STEP, digest("two")),
            "another run": (SIBLING_RUN, STEP, digest("one")),
            "another project": (FOREIGN_RUN, STEP, digest("one")),
        }
        for marker, (scope, step, name) in addresses.items():
            await store.write_entry(scope, step, name, entry(marker))
        for marker, (scope, step, name) in addresses.items():
            assert await store.read_entry(scope, step, name) == entry(marker), (
                f"the entry at {marker!r} came back missing or as another address's entry, so "
                f"an address is not the scope, the step and the digest taken together"
            )
