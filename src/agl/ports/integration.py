from abc import ABC, abstractmethod
from dataclasses import dataclass
from agl.ports.errors import InternalError
from agl.ports.verifier import VerifierOutcome
from agl.ports.workspace import Workspace

__all__ = ["Conflict", "Integration", "IntegrationOutcome", "Integrator"]

@dataclass(frozen=True, slots=True)
class Conflict:
    """The files that collided in a merge, with a summary."""

    paths: tuple[str, ...]
    """The files that collided, and empty where the collision names no file of its own."""

    summary: str
    """What collided and what state the parent is in, in words a screen can carry."""

    def __post_init__(self) -> None:
        if not self.summary:
            raise InternalError(
                "a conflict with no summary explains nothing, and an implementation that cannot "
                "list the colliding paths has this line and nothing else to say them in"
            )
        for index, path in enumerate(self.paths):
            if not path:
                raise InternalError(
                    f"the conflicting path at position {index} is empty, and names no file; an "
                    f"implementation with no paths to report passes an empty tuple instead"
                )

class Integration(ABC):
    """One landing of a child's work into its parent, and where it stands."""

    @property
    @abstractmethod
    def head(self) -> str | None:
        """The commit the parent is at once the work landed.

        Returns:
            The parent's new head, or `None` if the work hasn't landed.
        """
        ...

    @property
    @abstractmethod
    def conflict(self) -> Conflict | None:
        """What stopped the landing.

        Returns:
            The [`Conflict`][agl.sdk.Conflict], or `None` if the work landed.
        """
        ...

    @property
    @abstractmethod
    def conflicted(self) -> bool:
        """Whether a conflict is holding the parent.

        Returns:
            `True` while a conflict holds the parent, `False` once `retry` has landed the work
                or `abort` has given it up.
        """
        ...

    @property
    @abstractmethod
    def verdict(self) -> VerifierOutcome | None:
        """The build gate's outcome on the latest attempt.

        Returns:
            The build's [`VerifierOutcome`][agl.sdk.VerifierOutcome], or `None` where no build
                ran. It tells the two kinds of conflict apart: `None` means the work would not
                combine, and set means it combined and then did not build.
        """
        ...

    @property
    @abstractmethod
    def refused_by_the_gate(self) -> bool:
        """Whether the build failed after a clean merge, which was then undone.

        Returns:
            `True` while the gate's refusal holds the parent, `False` otherwise.
        """
        ...

    @abstractmethod
    async def retry(self) -> None:
        """Tries the landing again, against the parent's checkout as it now stands.

        Raises:
            InternalError: This landing already ended, in `retry` or in `abort`.
            agl.sdk.UpstreamUnavailable: Git or the build command couldn't be run.
            agl.sdk.UpstreamUnexpected: Git refused the landing, or answered unreadably.
        """
        ...

    @abstractmethod
    async def abort(self) -> None:
        """Gives up a conflicted landing, leaving the parent as it was before it.

        Raises:
            agl.sdk.UpstreamUnavailable: Git couldn't be run, so the parent is still held.
            agl.sdk.UpstreamUnexpected: Git refused, so the parent is still held.
        """
        ...

@dataclass(frozen=True, slots=True)
class IntegrationOutcome:
    """Everything a landing hands back: a head, or the conflict that stopped it, and never both."""

    head: str | None = None

    conflict: Conflict | None = None

    def __post_init__(self) -> None:
        if (self.head is None) == (self.conflict is None):
            both = "both a head and a conflict" if self.head is not None else "neither"
            raise InternalError(
                f"an integration outcome carries {both}, and it has to carry exactly one: work "
                f"either landed, and the target has a resulting state, or it did not, and there is "
                f"something to put on a screen"
            )
        if self.head is not None and not self.head:
            raise InternalError(
                "an integration outcome's head is empty, and an empty string names no state; a "
                "landing that changed nothing reports the target's unchanged head"
            )

    @property
    def conflicted(self) -> bool:
        """Did the work fail to land? What a workflow's own conflict screen branches on.

        Returns:
            whether a conflict came back instead of a head, and so whether the target is held
        """
        return self.conflict is not None

class Integrator(ABC):
    """Every landing behind one port: put the work in, look again, or give up the hold it left."""

    @abstractmethod
    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        """Put what `source` holds into `target`, and say whether it went in.

        Args:
            source: the work to land; an implementation may need no more of it than its branch
            target: landed into, and left held mid-landing when the answer is a conflict

        Returns:
            the target's head, unchanged where nothing moved, or the conflict that stopped it
        """
        ...

    @abstractmethod
    async def retry(self, target: Workspace) -> IntegrationOutcome:
        """Look again at the landing `target` holds, after somebody changed it from outside.

        Args:
            target: a landing must be pending on it; the source is not supplied a second time

        Returns:
            a head where it went in this time, or a conflict again with the target still held

        Raises:
            InternalError: called with nothing pending, which means AGL lost track of a hold
        """
        ...

    @abstractmethod
    async def abort(self, target: Workspace) -> None:
        """Give up on the pending landing, leaving `target` exactly as it was before `land`.

        Args:
            target: tolerant of nothing being pending, so a failure path may call it blind
        """
        ...
