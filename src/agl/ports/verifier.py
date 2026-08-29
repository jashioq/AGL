
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Verifier", "VerifierOutcome"]


@dataclass(frozen=True, slots=True)
class VerifierOutcome:

    passed: bool

    status: int

    output: str


class Verifier(ABC):

    @abstractmethod
    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        ...
