from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from agl.ports.ids import Namespace, RunLabel

__all__ = ["Workspace", "WorkspaceProvider"]

class WorkspaceProvider(ABC):
    """Every checkout behind one port: open one, take it back, discard the work, hold the run."""

    @abstractmethod
    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        """Provision an isolated place for these identifiers, or hand back the one already there.

        :param label: which run the place belongs to; the provider derives its own layout from it
        :param namespace: which checkout inside it, `None` naming the run's own and nothing else
        :param base: a ref or a commit id, consulted only when provisioning and ignored on reopen
        :return: the place, an existing one exactly as the previous attempt left it
        :raises ConflictError: a line of work of this name exists and is not this workspace's
        """
        ...

    @abstractmethod
    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Take the isolated place back. The line of work it carried survives.

        :param label: which run; a provider is addressed by name, never by a path a caller computed
        :param namespace: which checkout, `None` for the run's own; absence succeeds and is silent
        """
        ...

    @abstractmethod
    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Delete the line of work itself, which `remove` does not. Call `remove` first.

        :param label: which run; the same name `open` took, and what goes here does not come back
        :param namespace: which line of work, `None` for the run's own; absence succeeds silently
        """
        ...

    @abstractmethod
    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        """Claim this run for this process for as long as the context is open, or refuse at once.

        :param label: the whole of the address - a run is claimed, never a single checkout
        :return: a context manager that enters or raises, never one that waits
        :raises ConflictError: naming the label, while another holder has it open
        """
        ...

class Workspace(ABC):
    """One checkout to work in: its path, its branch, and the head it commits or restores to."""

    @property
    @abstractmethod
    def path(self) -> Path:
        """Where the work happens - what an `AgentTask` and a `Verifier` are pointed at.

        :return: an absolute directory, settled at provisioning and unchanging while it is open
        """
        ...

    @property
    @abstractmethod
    def branch(self) -> str:
        """The name this line of work is published under.

        :return: the name it actually carries, opaque here and never parsed back into its parts
        """
        ...

    @abstractmethod
    async def head(self) -> str:
        """Where this checkout currently is - a question about the world, not about this object.

        :return: the commit id, in the spelling `History` and `restore` both accept
        """
        ...

    @abstractmethod
    async def commit_all(self, message: str) -> str:
        """Record everything dirty here under one message. Nothing dirty is not an error.

        :param message: the workflow's own vocabulary, and outside the step's fingerprint
        :return: the resulting head, or the unchanged one where there was nothing to record
        """
        ...

    @abstractmethod
    async def restore(self, head: str) -> None:
        """Put the working tree back at `head` and remove everything that was not in it.

        :param head: a state this workspace produced; untracked leavings go with the reset
        """
        ...
