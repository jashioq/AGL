"""The half of the `Store` contract that needs two things happening at once.

Split out of `store.py` because everything here needs machinery nothing else in the suite does -
tasks, a reader loop, a deadline, and documents built so that a mixture of two of them is visible
rather than merely unexpected - and because "a written value exists complete or not at all" is one
clause carrying three separate obligations. `StoreContract` in `store.py` inherits this class;
implementers subclass that one and never this one.

## How a torn value is made visible

A test that wrote `{"a": 1}` and read it back could not tell a whole value from half of one: half
of a small document either parses as something else entirely or does not parse at all, and either
way the test learns only "that was unexpected". So the documents here are *woven*: every field of
one carries the same marker, across a few hundred rows, so a value assembled out of two writes
holds two markers and says so, and a value assembled out of half of one write is short and says
that. `_mixture` turns either into a sentence naming what was found - a row count for a prefix,
a per-marker count for a blend - because a failure here is the kind somebody will be reading at
the wrong end of a resume that replayed a result nobody produced.

An observation that is neither whole value fails. So does an observation of `None` where a whole
value was already recorded, and so does a read that *raises*: the clause says a reader sees the
whole of a value or nothing recorded, and an exception is neither.

## What this half cannot provoke, and says so rather than pretending

**Every method is `async` and this suite drives one event loop.** A reader therefore observes the
store only at moments the implementation yields control. An implementation whose write does all
its work without awaiting - a `os.replace` behind an `async def`, which is exactly what stage 4.1
will write - is never observed part-way through, because from this loop's point of view there is
no part-way through. The concurrency tests still run and still assert against it; they cannot
fail. That is a limit of watching an async interface from inside its own loop, not a gap the tests
could close by trying harder, and it is why `store.py`'s docstring lists it under what this suite
does not prove.

Measured when this suite was written, against two throwaway implementations: a correct one that
never awaits mid-write left 3 observations of which 0 overlapped the write, and one that yielded
between batches of rows left 51 of which 48 overlapped - and failed on every one of them. The
overlap count is in the failure message for that reason. It is the difference between a suite that
watched something and a suite that watched nothing, and it is not knowable in advance.

**Threads were considered and refused.** Driving reads from a second OS thread on a second event
loop would give real parallelism against an implementation that blocks. It would also assert a
clause `Store` does not have: nothing in that port promises an implementation is usable from a
second loop or a second thread, and a suite that required it would refuse implementations for
failing a rule nobody wrote down.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Final

import pytest

from agl.ports.home_layout import RunScope
from agl.ports.ids import StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store

from ._store_documents import (
    CHILD,
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

type _Address = tuple[RunScope, StepName, str]

# A woven document: this many rows, each holding the marker repeated this many times. Large
# enough that an implementation writing straight to the address it publishes at cannot get the
# whole of it out in one uninterruptible step, small enough that a few hundred reads of it are a
# fraction of a second.
_ROWS: Final = 256
_FILLER: Final = 48

_READERS: Final = 3
_ROUNDS: Final = 4
_PER_STEP: Final = 2

# A deadline, and not a performance assertion. It is here so that an implementation which
# deadlocks - two writes at two addresses waiting on each other - fails as a failure instead of
# hanging the suite until somebody notices. Anything correct finishes these in milliseconds.
_DEADLINE: Final = 30.0

_NOTHING: Final = "nothing recorded"

# How many kinds of wrong observation a failure spells out before summarising the rest. A torn
# write produces one kind per prefix length, and thirty of them teach nothing the first three did.
_LISTED: Final = 3


def _woven(marker: str) -> dict[str, JsonValue]:
    """A big entry whose every field agrees with every other about which write produced it."""
    rows: list[JsonValue] = [
        {"index": index, "marker": marker, "filler": marker * _FILLER} for index in range(_ROWS)
    ]
    return entry(marker, value={"marker": marker, "rows": rows})


def _mixture(document: Mapping[str, JsonValue], markers: Sequence[str]) -> str:
    """What was seen, in a sentence: a short document is a prefix, a two-marker one is a blend."""
    value = document.get("value")
    rows = value.get("rows") if isinstance(value, dict) else None
    counted = dict.fromkeys(markers, 0)
    if isinstance(rows, list):
        for row in rows:
            marker = row.get("marker") if isinstance(row, dict) else None
            if isinstance(marker, str):
                counted[marker] = counted.get(marker, 0) + 1
    length = len(rows) if isinstance(rows, list) else 0
    return f"neither whole value: {length} of {_ROWS} rows, per marker {counted}"


def _classify(
    document: Mapping[str, JsonValue] | None, whole: Mapping[str, Mapping[str, JsonValue]]
) -> str:
    """Name what a read answered with: one of the whole documents, nothing, or a description."""
    if document is None:
        return _NOTHING
    for marker, candidate in whole.items():
        if document == candidate:
            return marker
    return _mixture(document, tuple(whole))


async def _write(store: Store, address: _Address, document: Mapping[str, JsonValue]) -> None:
    """`write_entry` with the address as one value, because these tests carry it around as one."""
    scope, step, name = address
    await store.write_entry(scope, step, name, document)


async def _read(store: Store, address: _Address) -> dict[str, JsonValue] | None:
    """`read_entry`, addressed the same way."""
    scope, step, name = address
    return await store.read_entry(scope, step, name)


async def _observe(
    store: Store,
    address: _Address,
    whole: Mapping[str, Mapping[str, JsonValue]],
    seen: list[tuple[str, bool]],
    writing: asyncio.Event,
    stop: asyncio.Event,
) -> None:
    """Read one address as fast as the loop allows, classifying each answer as it arrives.

    The documents are not kept - a few hundred observations of a document this size is memory
    nothing needs - only what each one was, and whether a write was in flight around it. That
    second flag is a diagnostic and never an assertion: it is what the failure message uses to
    say how much of the run actually overlapped the write.
    """
    while not stop.is_set():
        before = writing.is_set()
        document = await _read(store, address)
        seen.append((_classify(document, whole), before or writing.is_set()))
        await asyncio.sleep(0)


def _raise_first_failure(readers: Sequence[asyncio.Task[None]]) -> None:
    """A reader only finishes early by raising, so surface that instead of waiting on it."""
    for reader in readers:
        if reader.done() and not reader.cancelled():
            failure = reader.exception()
            if failure is not None:
                raise failure


async def _observations(
    store: Store,
    address: _Address,
    whole: Mapping[str, Mapping[str, JsonValue]],
    work: Callable[[], Awaitable[object]],
) -> list[tuple[str, bool]]:
    """Run `work` while readers hammer `address`, and hand back what they saw.

    `work` is a callable rather than an awaitable so that nothing is created until the readers
    are known to be running: the loop below does not let the write start until at least one read
    has landed, so an empty result means the readers never ran rather than that the work was
    quick, and a test can assert on that difference.
    """
    seen: list[tuple[str, bool]] = []
    writing, stop = asyncio.Event(), asyncio.Event()
    readers = [
        asyncio.create_task(_observe(store, address, whole, seen, writing, stop))
        for _ in range(_READERS)
    ]
    failures: list[BaseException] = []
    try:
        async with asyncio.timeout(_DEADLINE):
            while not seen:
                _raise_first_failure(readers)
                await asyncio.sleep(0)
            writing.set()
            await work()
            writing.clear()
    finally:
        stop.set()
        gathered = await asyncio.gather(*readers, return_exceptions=True)
        failures = [outcome for outcome in gathered if isinstance(outcome, BaseException)]
    if failures:
        raise AssertionError(
            "a read beside a write raised instead of answering: a reader sees the whole of a "
            "value or sees nothing recorded, and an exception is neither of those"
        ) from failures[0]
    assert seen, "no read landed beside the write, so this test observed nothing"
    return seen


def _report(seen: Sequence[tuple[str, bool]], strange: set[str]) -> str:
    """The one failure message these tests share, because they fail for the one reason.

    The count of observations that overlapped the write is in it deliberately: it says how much
    of the reading actually happened while there was something to catch, which is the difference
    between a suite that watched something and a suite that watched an interval with nothing in
    it. See this module's docstring for why that count can legitimately be zero.
    """
    listed = sorted(strange)[:_LISTED]
    rest = f", and {len(strange) - _LISTED} other kinds" if len(strange) > _LISTED else ""
    return (
        f"{len(seen)} reads landed beside the write, {sum(flag for _, flag in seen)} of them "
        f"while it was in flight, and some saw what a reader may never see: {listed}{rest}"
    )


async def _contend(store: Store, number: int) -> None:
    """One round of two writers at one address, watched by readers throughout.

    A function rather than a loop body so that the two documents and the address are locals: a
    closure over a loop variable is a bug this file would rather not have to reason about.
    """
    alpha, beta = _woven(f"alpha-{number}"), _woven(f"beta-{number}")
    whole = {f"alpha-{number}": alpha, f"beta-{number}": beta}
    address = (RUN, STEP, digest(f"contended-{number}"))

    seen = await _observations(
        store,
        address,
        whole,
        lambda: asyncio.gather(_write(store, address, alpha), _write(store, address, beta)),
    )

    strange = {marker for marker, _ in seen} - (set(whole) | {_NOTHING})
    assert not strange, _report(seen, strange)

    settled = _classify(await _read(store, address), whole)
    assert settled in whole, (
        f"round {number} left an address that two writers wrote to holding {settled}, and one "
        f"of the two whole values is the only thing it may hold"
    )


class StoreConcurrencyContract:
    """Three clauses: a reader beside a write, two writers at one address, and writes apart.

    Inherited by `StoreContract`, which is what an implementer subclasses and where the `store`
    fixture these tests take is declared.
    """

    pytestmark = pytest.mark.asyncio

    async def test_a_reader_beside_a_large_write_sees_one_whole_value_or_the_other(
        self, store: Store
    ) -> None:
        """The atomic-write clause, watched: never a prefix, never a mixture, never a vanishing.

        `None` is counted as a failure here and the reading is deliberate. The port's sentence -
        "a reader sees either the whole of a value or nothing recorded at that address" - could be
        read as permitting an overwrite to pass through absence, but "never a mixture of two
        values" names the two outcomes it means, and §3.6 makes the existence of an entry the
        ledger: an entry that blinks out mid-supersede is a step that reads as not done while it
        is being recorded as done.
        """
        old, new = _woven("old"), _woven("new")
        whole = {"old": old, "new": new}
        address = (RUN, STEP, digest("torn"))
        await _write(store, address, old)

        seen = await _observations(store, address, whole, lambda: _write(store, address, new))

        strange = {marker for marker, _ in seen} - set(whole)
        assert not strange, _report(seen, strange)

    async def test_two_writers_at_one_address_leave_one_whole_value_and_never_a_mixture(
        self, store: Store
    ) -> None:
        """Which writer wins is unspecified and is not asserted. The third outcome is forbidden.

        `nothing recorded` is a permitted observation in this one: the address starts empty, so a
        reader that gets there before either write lands is seeing the port's `None` and not a
        torn value. Several rounds, because two writes only collide if they overlap, and whether
        they overlap is the implementation's business rather than this test's.
        """
        for number in range(_ROUNDS):
            await _contend(store, number)

    async def test_writes_at_distinct_addresses_do_not_reach_each_other(
        self, store: Store
    ) -> None:
        """Two child runs recording a step at the same moment need no coordination from anybody.

        Every address gets its own marker and every one of them is read back afterwards, so a
        write that another write swallowed is a missing document rather than a suspicion. This is
        what catches the implementation that keeps everything in one document and updates it
        without coordinating: a lost write is precisely what that produces. It does not catch the
        one that keeps everything in one document and serialises every write behind a single
        mutex - that implementation is correct and merely slow, and slowness is not something a
        suite can assert without a threshold that would refuse an implementation on a loaded
        machine for being slow rather than for being wrong.
        """
        scopes = (
            RUN,
            RUN.inside(CHILD),
            RUN.inside(SIBLING),
            RUN.inside(CHILD).inside(GRANDCHILD),
            SIBLING_RUN,
            FOREIGN_RUN,
        )
        entries: dict[_Address, dict[str, JsonValue]] = {}
        for index, scope in enumerate(scopes):
            for step in (STEP, OTHER_STEP):
                for position in range(_PER_STEP):
                    marker = f"{index}:{step}:{position}"
                    entries[(scope, step, digest(marker))] = entry(marker, value={"was": marker})
        runs = (RUN, SIBLING_RUN, FOREIGN_RUN)
        records = {run: record(f"record-{index}") for index, run in enumerate(runs)}

        async with asyncio.timeout(_DEADLINE):
            await asyncio.gather(
                *(_write(store, address, document) for address, document in entries.items()),
                *(store.write_record(run, document) for run, document in records.items()),
            )

        for address, document in entries.items():
            assert await _read(store, address) == document, (
                f"one of {len(entries)} entries written at once came back wrong or missing: "
                f"{document['fingerprint']!r} - distinct addresses are independent, so a write "
                f"here can neither lose nor be lost to a write anywhere else"
            )
        for run, document in records.items():
            assert await store.read_record(run) == document
        assert set(await store.namespaces(RUN)) == {CHILD, SIBLING}
        assert set(await store.namespaces(RUN.inside(CHILD))) == {GRANDCHILD}
