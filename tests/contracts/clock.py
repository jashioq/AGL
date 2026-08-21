"""`ClockContract` - what every `Clock` owes, which is less than any other port here and is still
not nothing.

Subclass it once per implementation, override the one fixture, and add nothing:

    class TestTheClockIWrote(ClockContract):
        @pytest.fixture
        def clock(self) -> Clock:
            return TheClockIWrote(...)

The real adapter and the fake both run this class, which is the whole mechanism keeping a fake from
drifting into fiction (§1.9).

**Two assertions, and the value is the parity rather than the coverage.** Plan target #7 reads
"every port has a contract suite its real adapter and its fake both pass - *every* port, including
ones that promise little", and then names this one: "`Clock`'s suite is two assertions". A rule that
admitted an exception would admit it exactly here, at the port whose ABC is one sync method and
whose suite is therefore short - so writing the short suite is what keeps the rule a rule. Stage 3
built this package and wrote no clock suite; this is that omission closed, and nothing else.

One class in one module, for `verifier.py`'s reason: the port is one method and draws no seam to
split along. Every other suite in this package is assembled out of two or three modules only
because its port drew one.

## Sync, and carrying no marker

`Clock.now()` is sync - the port argues that an awaitable reading would put an `await` at every
call site and buy nothing, there being no implementation of this that does I/O - so these tests are
sync and there is **no `pytestmark` on the class**. Its absence is deliberate rather than
forgotten, and worth saying out loud in a package where every other suite sets
`pytest.mark.asyncio` precisely because `asyncio_mode = "strict"` turns a missing marker into a
test pytest quietly skips.

## Why these two, argued from the port

A `Clock` exists so that the framework's own stamping of `at` (§3.6) can be handed a different
source of the current time, and so that a run can be produced twice. That purpose decides both
tests, and there is no third that the port would license.

**A reading is aware.** It is the only promise `now()` makes about its return value, and the port
spends a section on it - "Aware, never naive" - because the promise is not for this port's own
sake: it is for the record at the far end of the run. Both halves of the check are here, because
they are not one question. A `tzinfo` that returns `None` from `utcoffset` passes the cheap half
and is naive in every way that matters, and `RunSpec._normalised` checks both for that reason.

**A reading is a moment the run record accepts and keeps.** The clause above exists because a
reading ends up in `run.json`, and `RunSpec` is the only thing in AGL that judges whether something
is a moment - so this, and not the type check, is what says a reading is *usable*. It is also
where the parity actually lands: a fake that is not usable everywhere the real clock is, is not a
`Clock`, and that failure would otherwise be found hours into a run by the record rather than here
by the implementation that caused it.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe. Every one of these is a limit of what the port's own surface can be
made to reveal, not a test somebody forgot.

1. **Anything at all about two readings.** The port refuses that clause in as many words -
   "Nothing is promised about two readings... Nor are they promised to increase" - so no assertion
   here may rest on one. A clock that never moves passes, which is the point rather than the price:
   a frozen clock is an honest implementation of this port and not one that merely compiles, and it
   is what lets `sdk/testing.py` produce a run twice. A clock that stepped backwards passes too,
   since a system clock does that whenever something adjusts it.

2. **That the reading is the current time.** Nothing here knows what time it is. Finding out needs
   a second clock, which is the same question one layer out, and a threshold, which fails honest
   implementations on a loaded machine. A clock stuck at plan §3.6's example moment passes this
   suite - and that is exactly what `ManualClock` does by default, which is why it is not a gap
   that could be closed by trying harder.

3. **Any particular offset.** The port grants every one: "any offset will do; UTC is not required
   here", because normalising is `run.py`'s job and every aware spelling denotes one instant. So
   the first test asks only whether an offset exists and the second only whether the record can
   make sense of it. Which offset an implementation chooses, and whether that choice leaks the
   machine it is running on, is a claim about one implementation and lives with that
   implementation's own tests.

4. **That anything was read at all.** A `Clock` returning a constant and a `Clock` reading a
   hardware oscillator are indistinguishable through this interface, and the port hands back
   nothing else to tell them apart.

## Where the port is silent, and what this suite assumed

**That `now()` may be called at all in a fixture-built object, once per test.** The port describes
one call and says nothing about the next; each test below takes exactly one reading, so nothing
here rests on a second one being allowed, being equal, or being different.
"""

from datetime import UTC, datetime
from typing import Final

import pytest

from agl.ports.clock import Clock
from agl.ports.ids import RunLabel
from agl.ports.run import RunSpec

# Plan §3.6's `run.json` pin, doubled to a full sha1: `RunSpec` refuses an abbreviated one, which
# is a fact about that type and about nothing this suite is asking a clock.
_SHA: Final = "8c19f7ae4d2b0913e5f6" * 2


def _record_at(moment: datetime) -> RunSpec:
    """Plan §3.6's run record, stamped with `moment` - the one thing every reading ends up in.

    Built here rather than asked of a fixture, and deliberately: every field but `created_at` is
    scenery, and an implementer given a say over the record would be given a say over whether the
    assertion that uses it means anything.
    """
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


class ClockContract:
    """The suite. One method, two assertions, and the parity that is the whole point of them.

    There is no `pytestmark` here and its absence is load bearing: `Clock.now()` is sync, so these
    tests are sync, and marking them `asyncio` would be marking a lie. See the module docstring.
    """

    @pytest.fixture
    def clock(self) -> Clock:
        """The implementation under test, already built with whatever it needs.

        One knob, and there is nothing else this suite could offer one for: the port takes no
        arguments and hands back one value, so pointing the suite at an implementation is a single
        visible override.

        Function-scoped, like every fixture in this package. A clock carried between tests would
        let one test's reading be another test's starting state, which for a fake that can be moved
        is the difference between two independent tests and two halves of one.
        """
        raise NotImplementedError(
            "the Clock contract suite has no implementation to run against: subclass "
            "ClockContract and override the `clock` fixture to hand back the Clock under test"
        )

    def test_a_reading_is_aware_by_both_of_the_tests_that_decide_it(self, clock: Clock) -> None:
        """The port's one promise about what `now()` hands back, checked the way `run.py` checks it.

        "Aware, always" is the whole of the clause, and its reason lives one module away: a naive
        value is a wall-clock reading with no place, and `RunSpec._normalised` refuses one *before*
        calling `astimezone`, because `astimezone` on a naive value quietly reads the machine's
        local timezone and so turns a hidden input into a stored one.

        Both halves, because they are not the same question. The first is cheap and a `tzinfo`
        whose `utcoffset` answers `None` passes it while being naive in every way that matters - so
        a clock checked on that half alone could satisfy this test and still hand the record
        something it refuses.
        """
        reading = clock.now()

        assert reading.tzinfo is not None, (
            "this clock hands back a naive datetime, and a wall-clock reading with no place is "
            "not a moment - the record every reading ends up in (RunSpec.created_at) refuses one, "
            "and refuses it at the far end of a run from the clock that produced it"
        )
        assert reading.utcoffset() is not None, (
            "this clock's reading carries a tzinfo that declines to say what the offset is, which "
            "is a naive value in disguise: it passes `tzinfo is not None` and is refused by "
            "RunSpec all the same, which is why both halves are checked here"
        )

    def test_a_reading_is_a_moment_the_run_record_accepts_and_keeps(self, clock: Clock) -> None:
        """What a `Clock` is for: §3.6 stamps a record from one, and this is that record.

        The awareness clause exists *because* a reading ends up in `run.json`, so the assertion
        that says a reading is usable is this one and not the type check above it. `RunSpec` is the
        only thing in AGL that judges a moment, and a suite that stopped at `tzinfo` would let its
        refusal be discovered by a run that had already done its work.

        And the record must *keep* the reading. Equality between aware datetimes compares instants,
        so the second assertion says the record holds the instant this clock handed over, to the
        precision `run.json` can hold one - which is how a reading that survived is told from one
        that merely passed through. Converting the offset and dropping the microseconds are
        `run.py`'s, and they are applied here rather than asked of the clock: the port requires
        neither, and a clock that did either would hold a copy of a rule one module away.
        """
        reading = clock.now()
        spec = _record_at(reading)

        assert RunSpec.from_json(spec.to_json()) == spec, (
            "this clock's reading went into a run record that does not read back as itself, so a "
            "run stamped from this clock could be written and not resumed"
        )
        assert spec.created_at == reading.astimezone(UTC).replace(microsecond=0), (
            "the record did not keep the instant this clock handed over - the reading and the "
            "stored moment are two different moments, and the stored one is what a resume sees"
        )
