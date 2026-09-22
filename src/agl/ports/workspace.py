from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from agl.ports.ids import Namespace, RunLabel

__all__ = ["Workspace", "WorkspaceProvider"]

class WorkspaceProvider(ABC):
    """Every checkout behind one port: open one, find them, ask whether one goes, unmake, hold."""

    @abstractmethod
    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        """Provision an isolated place for these identifiers, or hand back the one already there.

        Args:
            label: which run the place belongs to; the provider derives its own layout from it
            namespace: which checkout inside it, `None` naming the run's own and nothing else
            base: a ref or a commit id, consulted only when provisioning and ignored on reopen

        Returns:
            the place, an existing one exactly as the previous attempt left it

        Raises:
            ConflictError: a line of work of this name exists and is not this workspace's
        """
        ...

    @abstractmethod
    async def residue(self, label: RunLabel) -> tuple[Namespace, ...]:
        """Every child place of this run this provider can still find, recorded anywhere or not.

        Args:
            label: which run; the run's own place is never among them and needs no finding

        Returns:
            each namespace once and in one order, so a teardown walking this is reproducible
        """
        ...

    @abstractmethod
    async def check_removable(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Refuse now if `remove` and `discard` would not both finish here, before either is spent.

        Args:
            label: which run; the address the two teardown verbs take, asked ahead of them
            namespace: which checkout, `None` for the run's own; a place that is not there goes

        Raises:
            ConflictError: something outside this provider is holding the place or its branch
        """
        ...

    @abstractmethod
    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Take the isolated place back. The line of work it carried survives.

        Args:
            label: which run; a provider is addressed by name, never by a path a caller computed
            namespace: which checkout, `None` for the run's own; absence succeeds and is silent
        """
        ...

    @abstractmethod
    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Delete the line of work itself, which `remove` does not. Call `remove` first.

        Args:
            label: which run; the same name `open` took, and what goes here does not come back
            namespace: which line of work, `None` for the run's own; absence succeeds silently
        """
        ...

    @abstractmethod
    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        """Claim this run for this process for as long as the context is open, or refuse at once.

        Args:
            label: the whole of the address - a run is claimed, never a single checkout

        Returns:
            a context manager that enters or raises, never one that waits

        Raises:
            ConflictError: naming the label, while another holder has it open
        """
        ...

class Workspace(ABC):
    """One checkout to work in: its path, its branch, and the head it commits or restores to."""

    @property
    @abstractmethod
    def path(self) -> Path:
        """Where the work happens - what an `AgentTask` and a `Verifier` are pointed at.

        Returns:
            an absolute directory, settled at provisioning and unchanging while it is open
        """
        ...

    @property
    @abstractmethod
    def branch(self) -> str:
        """The name this line of work is published under.

        Returns:
            the name it actually carries, opaque here and never parsed back into its parts
        """
        ...

    @abstractmethod
    async def head(self) -> str:
        """Where this checkout currently is - a question about the world, not about this object.

        Returns:
            the commit id, in the spelling `History` and `restore` both accept
        """
        ...

    @abstractmethod
    async def commit_all(self, message: str) -> str:
        """Record everything dirty here under one message. Nothing dirty is not an error.

        Args:
            message: the workflow's own vocabulary, and outside the step's fingerprint

        Returns:
            the resulting head, or the unchanged one where there was nothing to record
        """
        ...

    @abstractmethod
    async def restore(self, head: str) -> None:
        """Put the working tree back at `head` and remove everything that was not in it.

        Args:
            head: a state this workspace produced; untracked leavings go with the reset
        """
        ...
