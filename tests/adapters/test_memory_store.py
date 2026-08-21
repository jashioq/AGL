"""`MemoryStore` against the `Store` contract, plus the clauses only the fake can be asked about.

The first class is the whole of the port: `StoreContract` with its one fixture overridden and
nothing else touched, the same sixteen tests `FilesystemStore` runs. That is the mechanism §1.9
asks for - the real adapter and the fake held to one suite, written at stage 3 before either
existed - and nothing below re-asserts any of it.

What is below is what the suite deliberately cannot see. Two of the three are things it lists in
its own docstring as gaps, and the third is a property a store holding its state in a process has
that a store holding it in files does not:

  * **Copy-in.** The suite never edits a mapping it passed to a write, and says so (item 8): a
    `Mapping` on the way in means a caller need not copy what it already has, and asserting either
    answer would be inventing a clause the port does not have. §3.6 has the clause - the store
    copies any mapping it is handed - so it is asserted here, where the implementation that has to
    honour it lives. The edits reach into a nested object and a nested list, because a top-level
    copy leaves the store's own state exposed one indirection deeper.
  * **Two stores share nothing.** The suite drives one store per test, so it cannot ask this at
    all. It is what makes an all-fakes bundle built twice two stores rather than one, and it is the
    fake's answer to two `agl` invocations over one `AGL_HOME`.
  * **Nothing is retained after a `remove`.** Through the port a removed address and a tombstoned
    one are indistinguishable by construction - both read as `None` - so this is the one test that
    reaches past the port, and says why where it does it.

The digest the real store refuses and this one accepts is not here: it is a *difference between the
two*, so it belongs in `test_store_parity.py` with the rest of them, where a divergence is pinned
beside the assertions that the two otherwise answer alike.

Named `test_memory_store.py` and not `test_store.py`: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
`test_store.py` under different directories would collide at import.
"""

import hashlib
from copy import deepcopy
from typing import Final

import pytest

from agl.adapters.filesystem.memory_store import MemoryStore
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from contracts.store import StoreContract

# Module-level tests do not inherit the marker `StoreContract` sets on itself, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is
# how a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

# This file builds its own addresses rather than importing the contract suite's: only
# `StoreContract` is public there, the three `_store_*` modules being the private assembly of it.
RUN: Final = RunScope(ProjectName("myapp"), RunLabel("auth"))
CHILD: Final = Namespace("T-01")
GRANDCHILD: Final = Namespace("sub-b")
STEP: Final = StepName("implement")
DIGEST: Final = hashlib.sha256(b"one").hexdigest()


class TestMemoryStore(StoreContract):
    """The port, in full, against the fake.

    One override and nothing else, which is what the suite asks for: every address, name and
    document it needs it builds itself out of the pure types, so this is the only place it is
    pointed at an implementation. `MemoryStore()` takes no arguments, so there is not even a root
    to get wrong.
    """

    @pytest.fixture
    def store(self) -> Store:
        """A store with nothing in it per test. The suite's fixture is annotated
        `Store | Iterator[Store]` so that either shape of override typechecks; narrowing the return
        to `Store` is the first of the two, and no teardown is owed - the state goes when the
        object does."""
        return MemoryStore()


# --- Copy-in, which the contract suite deliberately does not assert ---------------------------


async def test_editing_the_mapping_a_write_was_handed_does_not_change_what_a_read_returns() -> None:
    """§3.6: the store copies any mapping it is handed, so a caller reusing a builder dict cannot
    silently edit an entry already on the ledger.

    The edits below go three deep - the top-level mapping, the nested `params` object, the list
    inside it, and an object inside *that* list - because a top-level copy passes an assertion that
    only edits the top level while still holding the caller's own nested containers. This is the
    clause the whole "hold documents serialised" decision exists for: `json.dumps` reads the
    mapping once and produces a string that shares nothing with it, in one step and at every depth,
    where a copy taken by hand is a copy somebody has to remember to take deeply enough.
    """
    store = MemoryStore()
    rows: list[JsonValue] = [{"id": "T-01", "blocked_by": []}]
    params: dict[str, JsonValue] = {"request": "add oauth", "tickets": rows}
    written: dict[str, JsonValue] = {"workflow": "tickets", "params": params}
    expected = deepcopy(written)

    await store.write_record(RUN, written)
    written["workflow"] = "edited"
    params["request"] = "edited"
    rows.append({"id": "T-99"})
    first = rows[0]
    assert isinstance(first, dict)
    first["id"] = "edited"

    assert await store.read_record(RUN) == expected, (
        "the record on the ledger followed the mapping the caller went on editing"
    )


async def test_editing_the_mapping_an_entry_was_written_from_does_not_change_the_entry() -> None:
    """The same clause on the write §3.6's ledger rests on, where getting it wrong is worse.

    A step's status is derived from whether its entry exists, so an entry that quietly changes
    after it was recorded is a completed step whose recorded result is not what the step produced,
    with nothing anywhere to disagree.
    """
    store = MemoryStore()
    tickets: list[JsonValue] = [{"id": "T-01"}]
    value: dict[str, JsonValue] = {"tickets": tickets}
    written: dict[str, JsonValue] = {"fingerprint": DIGEST, "value": value, "at": "2026-08-18"}
    expected = deepcopy(written)

    await store.write_entry(RUN, STEP, DIGEST, written)
    written["fingerprint"] = "edited"
    value["tickets"] = []
    tickets.clear()

    assert await store.read_entry(RUN, STEP, DIGEST) == expected


# --- Two stores are two stores -----------------------------------------------------------------


async def test_two_memory_stores_share_nothing_in_either_direction() -> None:
    """State is per instance, and there is no class-level dict quietly behind both.

    An all-fakes bundle built twice is two stores, which is what lets one test run beside another
    and what makes the fake's isolation the same isolation two `AGL_HOME` roots give the real one.
    A shared mutable default - the classic way to get this wrong - would make every `--dry-run` in
    a process see every other one's ledger.
    """
    one, other = MemoryStore(), MemoryStore()
    document: dict[str, JsonValue] = {"fingerprint": DIGEST, "value": None}

    await one.write_record(RUN, {"workflow": "tickets"})
    await one.write_entry(RUN.inside(CHILD), STEP, DIGEST, document)

    assert await other.read_record(RUN) is None
    assert await other.read_entry(RUN.inside(CHILD), STEP, DIGEST) is None
    assert await other.namespaces(RUN) == ()

    await other.write_record(RUN, {"workflow": "fix"})
    assert await one.read_record(RUN) == {"workflow": "tickets"}, (
        "a write to the second store reached the first, so the two share their state"
    )


# --- What a removal leaves, which only the fake can be asked ------------------------------------


async def test_a_removed_scope_leaves_no_state_behind_at_all() -> None:
    """Removed, not marked removed - asserted past the port because the port cannot show it.

    Every other assertion in these files goes through the port's own surface, and this one cannot:
    a tombstone answering `None` and a deleted key answering `None` are the same answer, which is
    precisely what makes the port unable to tell them apart. What is at stake is not correctness
    but growth - `clear` is a command a long-running process runs repeatedly, and a store that kept
    a marker per removed address would hold every run a session ever cleared. So the port's answers
    are asserted first, and then the two dicts are looked at, once, here.
    """
    store = MemoryStore()
    deep = RUN.inside(CHILD).inside(GRANDCHILD)
    await store.write_record(RUN, {"workflow": "tickets"})
    for scope in (RUN, RUN.inside(CHILD), deep):
        await store.write_entry(scope, STEP, DIGEST, {"fingerprint": DIGEST})

    await store.remove(RUN)

    assert await store.read_record(RUN) is None
    assert await store.read_entry(deep, STEP, DIGEST) is None
    assert await store.namespaces(RUN) == ()
    assert not store._records and not store._entries, (
        f"the run was removed and this store still holds {len(store._records)} record(s) and "
        f"{len(store._entries)} entry(s): a removed address is freed, not tombstoned"
    )
