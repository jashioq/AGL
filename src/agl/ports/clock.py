
from abc import ABC, abstractmethod
from datetime import datetime

__all__ = ["Clock"]


class Clock(ABC):

    @abstractmethod
    def now(self) -> datetime:
        ...
