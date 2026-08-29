
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agl.ports.errors import InternalError
from agl.ports.workspace import Workspace

__all__ = ["Conflict", "IntegrationOutcome", "Integrator"]


@dataclass(frozen=True, slots=True)
class Conflict:

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
        return self.conflict is not None


class Integrator(ABC):

    @abstractmethod
    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        ...

    @abstractmethod
    async def retry(self, target: Workspace) -> IntegrationOutcome:
        ...

    @abstractmethod
    async def abort(self, target: Workspace) -> None:
        ...
