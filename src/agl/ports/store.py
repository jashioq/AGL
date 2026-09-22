from abc import ABC, abstractmethod
from collections.abc import Mapping
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue

__all__ = ["Store"]

class Store(ABC):
    """Everything AGL records, behind one port: a record per run, and an entry per step run."""

    @abstractmethod
    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        """What this run was asked to do, as it was written down.

        Args:
            scope: which run; its namespaces are not consulted, so any depth answers the same

        Returns:
            a fresh mapping the caller owns, or `None`, which means nothing is recorded here
        """
        ...

    @abstractmethod
    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        """Record what this run was asked to do. Whole or not at all, to any reader.

        Args:
            scope: which run; namespaces are not consulted, and an existing record is replaced
            value: copied before control leaves the caller's line, so a builder stays reusable
        """
        ...

    @abstractmethod
    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        """One recorded run of one step. The whole of what replay decides on.

        Args:
            scope: which line of work ran it; one step name under two namespaces is two entries
            step: which step, by the name a workflow declared; never parsed or composed here
            digest: which run of that step; opaque here, and never composed or parsed either

        Returns:
            a fresh mapping the caller owns, or `None`, which means run the step
        """
        ...

    @abstractmethod
    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        """Record what this run of this step produced. Whole or not at all, to any reader.

        Args:
            scope: which line of work ran it; one step name under two namespaces is two entries
            step: which step, by the name a workflow declared; never parsed or composed here
            digest: which run of it; entries at other digests are left alone and are not pruned
            value: copied before control leaves the caller's line, so a builder stays reusable
        """
        ...

    @abstractmethod
    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        """The namespaces recorded immediately under a scope - the only enumeration AGL has.

        Args:
            scope: the parent; immediate children only, and a caller recurses with `inside`

        Returns:
            the same recorded set in the same order every time, so a walk is reproducible
        """
        ...

    @abstractmethod
    async def remove(self, scope: RunScope) -> None:
        """Remove this scope and everything recorded below it.

        Args:
            scope: the run at depth zero; absence succeeds, and stopping halfway is permitted
        """
        ...
