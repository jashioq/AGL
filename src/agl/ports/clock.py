from abc import ABC, abstractmethod
from datetime import datetime

__all__ = ["Clock"]

class Clock(ABC):
    """AGL's only reading of the time, as a port: a run can be handed a clock that never moves."""

    @abstractmethod
    def now(self) -> datetime:
        """The current moment, as an aware datetime - never naive, whatever the offset.

        :return: one instant; two readings may be equal and are not promised to increase
        """
        ...
