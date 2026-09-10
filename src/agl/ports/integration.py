from abc import ABC, abstractmethod
from dataclasses import dataclass
from agl.ports.errors import InternalError
from agl.ports.workspace import Workspace

__all__ = ["Conflict", "IntegrationOutcome", "Integrator"]

@dataclass(frozen=True, slots=True)
class Conflict:
    """Why nothing landed: the colliding paths and a summary, outliving the hold it explains."""

    paths: tuple[str, ...]

    summary: str

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

        :return: whether a conflict came back instead of a head, and so whether the target is held
        """
        return self.conflict is not None

class Integrator(ABC):
    """Every landing behind one port: put the work in, look again, or give up the hold it left."""

    @abstractmethod
    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        """Put what `source` holds into `target`, and say whether it went in.

        :param source: the work to land; an implementation may need no more of it than its branch
        :param target: landed into, and left held mid-landing when the answer is a conflict
        :return: the target's head, unchanged where nothing moved, or the conflict that stopped it
        """
        ...

    @abstractmethod
    async def retry(self, target: Workspace) -> IntegrationOutcome:
        """Look again at the landing `target` holds, after somebody changed it from outside.

        :param target: a landing must be pending on it; the source is not supplied a second time
        :return: a head where it went in this time, or a conflict again with the target still held
        :raises InternalError: called with nothing pending, which means AGL lost track of a hold
        """
        ...

    @abstractmethod
    async def abort(self, target: Workspace) -> None:
        """Give up on the pending landing, leaving `target` exactly as it was before `land`.

        :param target: tolerant of nothing being pending, so a failure path may call it blind
        """
        ...
