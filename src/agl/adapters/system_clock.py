from datetime import UTC, datetime, timedelta
from typing import Final
from agl.ports.clock import Clock
from agl.ports.errors import InputError

__all__ = ["ManualClock", "SystemClock"]

_DEFAULT_MOMENT: Final = datetime(2026, 8, 18, 9, 14, 2, tzinfo=UTC)

class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)

class ManualClock(Clock):
    def __init__(self, moment: datetime = _DEFAULT_MOMENT) -> None:
        self._moment = _aware(moment, "a clock is constructed with")

    def now(self) -> datetime:
        return self._moment

    def advance(self, by: timedelta) -> None:
        if by < timedelta(0):
            raise InputError(
                f"a clock cannot advance by {by}, which is backwards. Nothing was moved. A moment "
                f"earlier than the current one is what `set_to` is for - the port allows a clock "
                f"to step backwards, and `advance` is the member whose name promises it will not"
            )
        self._moment += by

    def set_to(self, moment: datetime) -> None:
        self._moment = _aware(moment, "a clock is set to")

def _aware(moment: datetime, what: str) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise InputError(
            f"{what} {moment!r}, which has no timezone. A wall-clock reading with no place is not "
            f"a moment: a clock hands its reading to a run record, and that record refuses one"
        )
    return moment
