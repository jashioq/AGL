from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Verifier", "VerifierOutcome"]

@dataclass(frozen=True, slots=True)
class VerifierOutcome:
    """Whether a verify command passed, with its exit status and output."""

    passed: bool
    """`True` where the command exited 0, `False` for any other status and for a timeout."""

    status: int
    """The command's exit status."""

    output: str
    """Everything the command wrote, its standard output and standard error together."""

class Verifier(ABC):
    """Every build behind one port: one command run in one directory, and the verdict it gave."""

    @abstractmethod
    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        """Run one command line in a workspace, wait for it, and report what happened.

        Args:
            command: as the project file or the workflow wrote it, shell operators and `""` alike
            workdir: passed as the working directory, never interpolated into `command`

        Returns:
            what a landing is kept or undone on and `run.verify` returns; a failure is no raise
        """
        ...
