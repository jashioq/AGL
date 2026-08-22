"""`MemoryStore` against the `Store` contract, plus the clauses only the fake can be asked about.

The first class is the whole of the port: `StoreContract` with its one fixture overridden and
nothing else touched, the same nineteen tests `FilesystemStore` runs. That is the mechanism §1.9
asks for - the real adapter and the fake held to one suite, written at stage 3 before either
existed - and nothing below re-asserts any of it.

**Copy-in used to be asserted here and is now three clauses of that suite**, where both stores run
it: §3.6 has the store copy any mapping it is handed, the clause needs no knowledge of what a store
is made of, and a fake proved to honour it beside a real adapter that was never asked is the drift
§1.9's Rule 3 exists to stop. The suite's own list of what it cannot see named this and no longer
does.

What is left below is what that suite still deliberately cannot see. One of the two it lists in its
own docstring as a gap, and the other is a property a store holding its state in a process has that
a store holding it in files does not:

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
