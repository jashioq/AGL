from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Verifier", "VerifierOutcome"]

@dataclass(frozen=True, slots=True)
class VerifierOutcome:
    """Everything a build hands back: whether it passed, its exit status, and its output."""

    passed: bool

    status: int

    output: str

class Verifier(ABC):
    """Every build behind one port: one command run in one directory, and the verdict it gave."""

    @abstractmethod
    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        """Run the project's build command in a workspace, wait for it, and report what happened.

        :param command: one command line exactly as the user wrote it, operators and all
        :param workdir: passed as the working directory, never interpolated into `command`
        :return: the verdict a landing is kept or undone on; a failing build is this, not a raise
        """
        ...
