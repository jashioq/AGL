"""`SystemClock` - the real `Clock` - and `ManualClock`, the one whose reading is set, not read.

Both in one module directly under `adapters/`, rather than a package holding two files. The port
is one method, so the pair is two classes over about a dozen lines of code; `filesystem/` is a
package because a `Store` is two substantial modules that each want a file, and `routing.py` is
the precedent for a module that sits under `adapters/` because a package around it would hold one
idea and a directory. (§3.0's tree lists no clock adapter at all - `agl-build-stages.md` 4.3 is
what asks for this module, and "real + fake, always paired" is that tree's own heading for
`adapters/`.)

## Aware at the source, never converted

`SystemClock.now()` is `datetime.now(UTC)`, and the argument for that spelling is the port's
"Aware, never naive" section read as an instruction to whoever implements it. The obvious way to
produce a *local* aware reading is `datetime.now().astimezone()` - build a naive value, then
attach an offset - and the second half of that is exactly the step `RunSpec._normalised` refuses
to take on anybody's behalf, "because `astimezone` on a naive value quietly reads the machine's
local timezone and so turns a hidden input into a stored one". A clock written that way would put
that hidden input back one layer down, where the refusal at the far end of the run cannot see it:
the record would be handed a value that is aware, so nothing would refuse it, and the zone it
carries would be a fact about the machine that AGL never asked for.

`datetime.now(UTC)` has no naive value to convert. It reads the system clock once and expresses
that instant in the zone it was handed, so there is no local zone in the call and nothing about
the machine in the answer.

## Not normalised, and not truncated - both of those are `run.py`'s

Passing `UTC` is not `RunSpec`'s normalising rule restated here. That rule is about a value that
*arrives* at some offset and is converted; this one never converts anything, and there is no
zone-free way to ask for an aware reading in the first place. The port says the offset is not its
business precisely so that this module needs no opinion about the one it hands back, and it is
free to hand back UTC for the reason above: it is the one zone that can be named without asking
the machine what zone it is in.

Nothing here truncates. `run.py` drops the microseconds because whole seconds is what `run.json`'s
wire form can hold - a fact about that file, not about the current time. A clock that truncated
would be a second copy of that rule, free to drift from it, and would forbid every later reader of
a moment from being more precise than the one record that happens to store one.

## `ManualClock` is a `Clock`, not a stand-in for one

Named for what it is - a clock whose hands move only when something moves them - and deliberately
not `FakeClock` or `StubClock`, for `MemoryStore`'s reason. §1.9's charge against the previous
implementation was that its fakes lived in `tests/fakes.py` and so "cannot power product modes";
this is the clock plan target #8 rests on ("every command runs end-to-end on fakes alone") and the
one `sdk/testing.py` hands a workflow author so that a run is identical twice. A name that says
"test double" invites the next reader to keep it out of the container, which is where it belongs.

**Frozen by default, and that is the port's own clause rather than a limitation.** "Nothing is
promised about two readings. They may be equal, and under a frozen clock they always are." So
`now()` returns the instant this was constructed with, as often as it is asked, and moves for
exactly one reason: something told it to. A clock that ticked when read would make "two readings
may be equal" untestable, which is the one thing this class exists to pin.

**`advance` goes forward and `set_to` goes anywhere**, and the split is about what a name
promises. The port says a reading is not promised to increase - "a system clock steps backwards
when something adjusts it" - so a fake that could not step backwards would be less honest than the
real thing, and a test showing that nothing in AGL compares two readings needs a second one that
is earlier. That capability lives on `set_to`, whose name promises no direction. `advance` refuses
it, because a member called `advance` going backwards is a lie at every call site that reads it.

**A moment that is not aware is refused, with `InputError`.** The port requires aware and
`RunSpec` refuses naive, so a fake that accepted one would let a test pass on a clock the real one
could never be - which is `MemoryStore`'s rule (wherever the port is silent, the fake agrees with
the real adapter) applied where the port is not silent at all. `InputError` rather than `run.py`'s
`InternalError`, because the two sit on opposite sides of the line `errors.py` draws: `run.json`
is a file nobody types, so a bad value in it means AGL wrote it wrong, while the moment handed to
this constructor is written by hand at a call site - the container's, or a workflow author's test
- and "what the caller supplied cannot be used, and nothing was attempted" is that class word for
word.

## Nothing here compares two moments

No monotonic reading, no elapsed-time member, no ordering, no sleep. The port considered the first
and the last and excluded both with reasons, and §3.6 keeps `at` out of control flow entirely.
`advance` adds a `timedelta` to the moment it holds and never compares one reading with another;
neither class offers a caller anything to compare with. A member that did would fail no test here
- it would quietly hand the framework a way to branch on the time, which is what the port's last
section exists to prevent.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from agl.ports.clock import Clock
from agl.ports.errors import InputError

__all__ = ["ManualClock", "SystemClock"]


# What `ManualClock` reads when nothing says otherwise: plan §3.6's own `run.json` example, so a
# record written on the all-fakes bundle carries the moment the plan prints and a reader who
# recognises it knows which clock produced it. A constant and never a reading - a default computed
# at construction would make the fake's zero-argument behaviour depend on the machine, which is the
# whole of what it exists not to do - and safe as a default argument because a datetime is
# immutable, so every `ManualClock()` starts from this value and none of them can edit it.
_DEFAULT_MOMENT: Final = datetime(2026, 8, 18, 9, 14, 2, tzinfo=UTC)


class SystemClock(Clock):
    """The machine's clock, read as an aware moment.

    Constructed with nothing and holding nothing: there is no state, no cached reading and no
    configured zone, so two of these are the same clock. `config/container.py` builds one of these
    for the real bundle exactly as it builds `ManualClock` for the all-fakes one, and the
    difference in the wiring is which class is named.
    """

    def now(self) -> datetime:
        """The current moment, aware, as `datetime.now(UTC)` gives it.

        **Aware at the source.** The zone is passed to the reading rather than attached to one
        afterwards, so no naive value ever exists here to be converted - see the module docstring
        for why `datetime.now().astimezone()` is the wrong spelling and what it would smuggle in.

        **Not normalised and not truncated.** Both are `RunSpec`'s: it converts whatever offset it
        is handed and drops the microseconds because whole seconds is what `run.json` can hold.
        Doing either here would be a second copy of a rule that lives one module away, free to
        drift from it, and truncating would additionally cap every other reader of a moment at the
        precision of the one record that happens to store one. UTC here is not that rule restated
        - nothing is being converted - it is the one zone nameable without asking the machine.
        """
        return datetime.now(UTC)


class ManualClock(Clock):
    """A `Clock` frozen at the moment it was given, until something moves it.

    Not a test double: this is the clock the all-fakes bundle runs on and the one `sdk/testing.py`
    hands a workflow author, which is why it is named for what it does rather than for the role it
    plays in a test. The module docstring argues the name, the default, and the split between
    `advance` and `set_to`.

    State is one moment, per instance, so two of these share nothing and a bundle built twice is
    two clocks.
    """

    def __init__(self, moment: datetime = _DEFAULT_MOMENT) -> None:
        self._moment = _aware(moment, "a clock is constructed with")

    def now(self) -> datetime:
        """The moment this clock holds - the same one every time, until told otherwise.

        Reading does not move it, and that is the whole point: the port promises nothing about two
        readings and says they may be equal, so a fake that ticked when read would make the clause
        untestable and would make a run that is identical twice impossible to produce.

        Returned as held, neither converted nor rounded, for `SystemClock.now`'s reason: what a
        record does with a moment is `run.py`'s business, and a fake that pre-empted it would stop
        agreeing with the real clock about what a reading is.
        """
        return self._moment

    def advance(self, by: timedelta) -> None:
        """Move the clock forward by `by`. The only thing that ever moves it apart from `set_to`.

        A negative `by` is refused: the member is called `advance`, and `set_to` is where going
        backwards lives - see the module docstring. Zero is not refused, because it moves nothing,
        and a reading that repeats is a reading the port already allows.

        The arithmetic is `datetime`'s own, on the moment as it is held. Under a fixed offset -
        which `_DEFAULT_MOMENT` has, and so does anything built from `UTC` or a `timezone` - that
        is the same as moving the instant by `by` exactly. The two differ only for a `ZoneInfo`
        moment stepping across a DST boundary, and this class does not convert to UTC to close
        that: converting is the thing `run.py` owns and this module deliberately does not do, and a
        fake that quietly reinterpreted the moment it was handed would no longer be holding it.
        """
        if by < timedelta(0):
            raise InputError(
                f"a clock cannot advance by {by}, which is backwards. Nothing was moved. A moment "
                f"earlier than the current one is what `set_to` is for - the port allows a clock "
                f"to step backwards, and `advance` is the member whose name promises it will not"
            )
        self._moment += by

    def set_to(self, moment: datetime) -> None:
        """Put the clock at `moment`, wherever that is relative to the one it holds.

        Earlier is allowed, and is the reason this member exists beside `advance`: the port says
        two readings are not promised to increase, "a system clock steps backwards when something
        adjusts it", and a fake that could not do that would be less honest than the clock it
        stands in for. Aware, on the same terms as the constructor.
        """
        self._moment = _aware(moment, "a clock is set to")


def _aware(moment: datetime, what: str) -> datetime:
    """`moment`, if it is a moment at all. Both halves of the check are `RunSpec._normalised`'s.

    `tzinfo is None` is the ordinary naive value. `utcoffset() is None` is a `tzinfo` that declines
    to say what the offset is, which is naive in every way that matters and which `RunSpec` refuses
    for that reason - so checking only the first half would leave this fake accepting a moment the
    record at the end of the run rejects, which is the drift the check exists to prevent.

    `InputError` rather than `InternalError`: this value was written by hand at whatever call site
    built the clock, and nothing has been changed when it is raised.
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise InputError(
            f"{what} {moment!r}, which has no timezone. A wall-clock reading with no place is not "
            f"a moment: a clock hands its reading to a run record, and that record refuses one"
        )
    return moment
