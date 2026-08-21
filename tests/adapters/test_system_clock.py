"""`SystemClock` and `ManualClock`: the contract suite run twice, and what only these two can be
asked.

The two classes at the top are the whole of the port: `ClockContract` with its one fixture
overridden and nothing else touched, the same two assertions against each implementation. That is
the mechanism §1.9 asks for - the real adapter and the fake held to one suite written by somebody
with no stake in either - and plan target #7 admits no exception for a port that promises little.
**Both subclasses live here**, because both clocks live in one adapter module
(`agl/adapters/system_clock.py`) and this file is named for that module: the convention in
`tests/adapters/` is one test file per adapter module, which is also why `MemoryStore` and
`FilesystemStore` are in two files and these two are in one.

What is below the subclasses is what those two assertions deliberately do not reach, and two of
them the suite now also makes. Those two stay. A contract suite is a floor, and deleting a local
assertion because a shared class currently happens to cover it would make this file's coverage
depend on a class written to be disinterested about these implementations - which is the one thing
that class is for.

**No test asserts that `SystemClock` moves between two readings, or that one is later than
another.** The port refuses that clause outright - "Nothing is promised about two readings... Nor
are they promised to increase" - so such a test would pin something the port declines to promise
and that a frozen `Clock` is entitled to fail while being an honest one. What is asserted instead
is that the *fake* moves exactly when told, which is that property where it really is promised.

**The assertion that carries this file is the `RunSpec` round trip**, not the `tzinfo` check beside
it, and it is `ClockContract`'s second assertion for the same reason. The port's "Aware, never
naive" section exists because a clock reading ends up in `run.json`, and `RunSpec` is where a value
that is not a moment is refused - so a unit test on `tzinfo` alone would still pass on a reading
that record rejects. What this file adds past the suite is the *wire* half: which text `to_json`
produces, and that `ManualClock`'s default is plan §3.6's own `created_at`.

`Clock.now()` is sync, so these tests are sync and carry no asyncio marker; there is no
`pytestmark` here for that reason and its absence is deliberate rather than forgotten. The suite
says the same of itself, and neither statement is a copy of the other: this file could hold an
async test tomorrow and that class could not.

Named `test_system_clock.py`, for the module it covers: `tests/` carries no `__init__.py` (see
`tests/conftest.py` for why it must not), so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import time
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Final

import pytest

from agl.adapters.system_clock import ManualClock, SystemClock
from agl.ports.clock import Clock
from agl.ports.errors import InputError, InternalError
from agl.ports.ids import RunLabel
from agl.ports.run import RunSpec
from contracts.clock import ClockContract

# Plan §3.6's `run.json` pin, doubled to a full sha1: `RunSpec` refuses an abbreviated one.
_SHA: Final = "8c19f7ae4d2b0913e5f6" * 2

# The plan's own `created_at`, which is also `ManualClock`'s default, spelled out here rather than
# imported: a test that reads the constant it is checking agrees with any value it happens to hold.
_MOMENT: Final = datetime(2026, 8, 18, 9, 14, 2, tzinfo=UTC)
_WIRE_MOMENT: Final = "2026-08-18T09:14:02Z"

# The same instant at another offset, with microseconds - what a clock is free to hand back and a
# record is not free to store. +05:30 is chosen because it is not a whole number of hours, so a
# reading carrying it cannot be mistaken for one that lost its offset somewhere.
_INDIA: Final = timezone(timedelta(hours=5, minutes=30))
_ELSEWHERE: Final = datetime(2026, 8, 18, 14, 44, 2, 123456, tzinfo=_INDIA)


class _Placeless(tzinfo):
    """A `tzinfo` that declines to say what the offset is - naive in every way that matters.

    `datetime.tzinfo is not None` and `datetime.utcoffset() is None`, which is the gap between the
    two halves of the awareness check - so both halves can be shown to be load bearing, here and
    in `RunSpec`, rather than one reading as belt-and-braces after the other.
    """

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return None


def _record_at(moment: datetime) -> RunSpec:
    """Plan §3.6's run record, stamped with `moment` - the one thing every reading ends up in."""
    return RunSpec(
        workflow="tickets",
        workflow_version="1.0.0",
        label=RunLabel("auth"),
        base_ref="main",
        base_sha=_SHA,
        branch="agl/auth",
        params={"request": "add oauth"},
        created_at=moment,
    )


def _public(clock: type[Clock]) -> set[str]:
    """The members a class of clock offers a caller - its own, not the ABC's."""
    return {name for name in vars(clock) if not name.startswith("_")}


# --- The port, asserted of both ----------------------------------------------------------------


class TestTheSystemClock(ClockContract):
    """The real adapter against the `Clock` contract. One fixture, and nothing else touched."""

    @pytest.fixture
    def clock(self) -> Clock:
        return SystemClock()


class TestTheManualClock(ClockContract):
    """The fake against the same two assertions, which is the whole reason the suite exists.

    Built with its default moment, because that is what an all-fakes bundle hands the framework -
    a fake configured specially for its own contract suite would be a fake nobody runs.
    """

    @pytest.fixture
    def clock(self) -> Clock:
        return ManualClock()


# --- The real clock ---------------------------------------------------------------------------


def test_a_system_clock_reading_is_aware_by_both_of_the_tests_that_decide_it() -> None:
    """`tzinfo is not None` is the cheap half; `utcoffset() is not None` is the one that decides.

    A `tzinfo` that returns `None` from `utcoffset` passes the first and is naive in every way
    that matters - `RunSpec._normalised` checks both for that reason, and a clock checked on the
    first alone could satisfy this test and still hand that record something it refuses.
    """
    reading = SystemClock().now()

    assert reading.tzinfo is not None
    assert reading.utcoffset() is not None, "a tzinfo with no offset is a naive value in disguise"


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="`TZ` and `time.tzset` are POSIX")
def test_a_system_clock_reading_carries_nothing_of_the_machines_local_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hole the port's "Aware, never naive" section is about, made visible.

    `datetime.now().astimezone()` is the obvious way to produce an aware local reading, and it
    reaches its offset by attaching the machine's local zone to a naive value - turning a hidden
    input into one the run record stores. An implementation written that way passes every other
    test in this file: its readings are aware and they round trip, and only the *offset* betrays
    where they came from. So the local zone is moved somewhere it cannot be mistaken for UTC and
    the reading is checked to be unmoved - which pins this adapter's own choice inside the freedom
    the port leaves it, that choice being what makes a reading independent of the machine.
    """
    before = time.tzname
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    try:
        if datetime.now().astimezone().utcoffset() != _INDIA.utcoffset(None):
            pytest.skip("no tz database here, so there is no local zone to be told apart from")
        assert SystemClock().now().utcoffset() == timedelta(0), (
            "the reading carries the machine's local offset, so it was built naive and then "
            "handed to `astimezone` - which is the hidden input `RunSpec` refuses to accept"
        )
    finally:
        monkeypatch.undo()
        time.tzset()
    assert time.tzname == before, "this test left the process in another timezone"


def test_a_system_clock_reading_is_a_moment_the_run_record_accepts_and_keeps() -> None:
    """The assertion the port's awareness clause is actually about.

    §3.6 stamps `created_at` from a clock, and `RunSpec` is what refuses a value that is not a
    moment - so this, and not the `tzinfo` check above, is what says the reading is usable. The
    third assertion is that the record holds *this* reading, to the precision it can hold one:
    the instant surviving the trip is how you know the record kept the clock's answer.
    """
    reading = SystemClock().now()
    spec = _record_at(reading)

    assert RunSpec.from_json(spec.to_json()) == spec
    assert spec.to_json()["created_at"] == format(spec.created_at, "%Y-%m-%dT%H:%M:%SZ")
    assert spec.created_at == reading.astimezone(UTC).replace(microsecond=0)


# --- The fake ---------------------------------------------------------------------------------


def test_the_fake_is_frozen_and_a_hundred_readings_are_one_value() -> None:
    """The port's own clause - "they may be equal, and under a frozen clock they always are".

    Not a limitation of the fake: it is what makes this an honest implementation of the port
    rather than one that merely compiles, and what lets `sdk/testing.py` produce a run twice.
    """
    clock = ManualClock(_MOMENT)

    assert [clock.now() for _ in range(100)] == [_MOMENT] * 100


def test_the_fake_moves_by_exactly_what_it_was_told_and_never_by_being_read() -> None:
    """Reading it never moves it; `advance` moves it by the delta and by nothing else.

    A clock that ticked when read would make "two readings may be equal" untestable, which is the
    one thing this class exists to pin - so the repeated readings on either side of each `advance`
    are what this is really about, and the arithmetic is the easy half.
    """
    clock = ManualClock(_MOMENT)
    assert [clock.now() for _ in range(5)] == [_MOMENT] * 5

    clock.advance(timedelta(seconds=99))
    assert clock.now() == _MOMENT + timedelta(seconds=99)

    clock.advance(timedelta(microseconds=1))
    assert clock.now() == _MOMENT + timedelta(seconds=99, microseconds=1)
    assert [clock.now() for _ in range(5)] == [_MOMENT + timedelta(seconds=99, microseconds=1)] * 5

    clock.advance(timedelta(0))
    assert clock.now() == _MOMENT + timedelta(seconds=99, microseconds=1), (
        "advancing by nothing is a request that moves nothing, not a refusal"
    )


def test_the_fake_can_be_set_outright_including_to_a_moment_earlier_than_the_last() -> None:
    """The port refuses to promise that two readings increase, and this is the fake agreeing.

    "A system clock steps backwards when something adjusts it" - so a fake that could not would be
    less honest than the thing it stands in for, and showing that nothing in AGL compares two
    readings needs an earlier second one. It lives on `set_to`, whose name promises no direction;
    `advance` refuses it in the test below, because its name does.
    """
    clock = ManualClock(_MOMENT)

    clock.set_to(_MOMENT - timedelta(days=1))
    assert clock.now() == _MOMENT - timedelta(days=1)

    clock.set_to(_ELSEWHERE)
    assert clock.now() == _ELSEWHERE


def test_the_fake_hands_back_the_moment_it_was_given_neither_normalised_nor_truncated() -> None:
    """Converting the offset and dropping the microseconds are `run.py`'s, and only `run.py`'s.

    A clock that did either would hold a second copy of a rule one module away and stop agreeing
    with `SystemClock` about what a reading is. Equality between aware datetimes compares
    instants, so the offset and the microseconds - what such a clock changes - are asserted.
    """
    clock = ManualClock(_ELSEWHERE)

    assert clock.now() == _ELSEWHERE
    assert clock.now().utcoffset() == timedelta(hours=5, minutes=30)
    assert clock.now().microsecond == 123456


def test_a_fake_reading_is_a_moment_the_run_record_accepts_too() -> None:
    """A fake usable anywhere the real clock is, or it is not a `Clock`.

    Both readings go into the same record: the default, which is plan §3.6's own `created_at` and
    so is what an all-fakes run writes, and one at another offset, which the record normalises to
    the same instant. One wire value from two is the division of labour in a line - the clock
    keeps the offset it was given, and the record is what decides UTC.
    """
    spec = _record_at(ManualClock().now())
    assert RunSpec.from_json(spec.to_json()) == spec
    assert spec.to_json()["created_at"] == _WIRE_MOMENT, "the default is not the plan's example"

    elsewhere = _record_at(ManualClock(_ELSEWHERE).now())
    assert RunSpec.from_json(elsewhere.to_json()) == elsewhere
    assert elsewhere.to_json()["created_at"] == _WIRE_MOMENT


def test_a_moment_that_is_not_aware_is_refused_at_construction_and_at_the_setter() -> None:
    """Both halves of the check, at both doors, and nothing moved by either refusal.

    The port requires aware and the record at the end of the run refuses naive, so a fake taking
    one would let a test pass on a clock the real one could never be. `InputError` because the
    value was written by hand at whatever call site built it, and nothing was attempted.

    The placeless value is the second half: `tzinfo` set, `utcoffset()` `None`. `RunSpec` refuses
    it too, which is what makes checking both halves necessary rather than thorough.
    """
    naive = datetime(2026, 8, 18, 9, 14, 2)
    placeless = datetime(2026, 8, 18, 9, 14, 2, tzinfo=_Placeless())

    for refused in (naive, placeless):
        with pytest.raises(InputError, match="no timezone"):
            ManualClock(refused)
        with pytest.raises(InternalError, match="no timezone"):
            _record_at(refused)

    clock = ManualClock(_MOMENT)
    for refused in (naive, placeless):
        with pytest.raises(InputError, match="no timezone"):
            clock.set_to(refused)
    assert clock.now() == _MOMENT, "a refused `set_to` moved the clock anyway"


def test_advance_refuses_to_go_backwards_because_that_is_what_its_name_promises() -> None:
    """`set_to` is where earlier lives. This is about the member whose name says one direction."""
    clock = ManualClock(_MOMENT)

    with pytest.raises(InputError, match="backwards"):
        clock.advance(-timedelta(seconds=1))
    assert clock.now() == _MOMENT, "a refused `advance` moved the clock anyway"


# --- What both of them are, and what neither of them grew -------------------------------------


def test_both_are_clocks_and_the_port_itself_cannot_be_constructed() -> None:
    """The ABC is one abstract method, and an ABC with an abstract method is not instantiable.

    The port argues that a class rather than an alias for `Callable[[], datetime]` is what gives
    a call site a name to read and a fake somewhere to hang its contract on - which needs both.
    """
    assert isinstance(SystemClock(), Clock)
    assert isinstance(ManualClock(), Clock)
    assert Clock.__abstractmethods__ == frozenset({"now"})

    with pytest.raises(TypeError):
        Clock()  # type: ignore[abstract]


def test_neither_clock_offers_a_member_the_port_refused_to_promise() -> None:
    """No monotonic reading, no elapsed-time helper, no ordering, no sleep, no schedule.

    The port lists the first and the last under "considered and excluded", with reasons, and §3.6
    keeps `at` out of control flow entirely - so a member of that shape would break no other test
    here and would quietly hand the framework a way to branch on the time. The fake's two extra
    members move it and read nothing back, which is why they are not of that shape.
    """
    assert _public(SystemClock) == {"now"}
    assert _public(ManualClock) == {"now", "advance", "set_to"}
