
from abc import ABC, abstractmethod
from collections.abc import Mapping

from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue

__all__ = ["Store"]


class Store(ABC):

    @abstractmethod
    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        """What this run was asked to do, as it was written down.

        :param scope: which run; its namespaces are not consulted, so any depth answers the same
        :return: a fresh mapping the caller owns, or `None`, which means nothing is recorded here
        """
        ...

    @abstractmethod
    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        """Record what this run was asked to do. Whole or not at all, to any reader.

        :param scope: which run; namespaces are not consulted, and an existing record is replaced
        :param value: copied before control leaves the caller's line, so a builder stays reusable
        """
        ...

    @abstractmethod
    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        """One recorded run of one step. The whole of what replay decides on.

        :param scope: which line of work ran it; one step name under two namespaces is two entries
        :param step: which step, by the name a workflow declared; never parsed or composed here
        :param digest: which run of that step; opaque here, and never composed or parsed either
        :return: a fresh mapping the caller owns, or `None`, which means run the step
        """
        ...

    @abstractmethod
    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        """Record what this run of this step produced. Whole or not at all, to any reader.

        :param scope: which line of work ran it; one step name under two namespaces is two entries
        :param step: which step, by the name a workflow declared; never parsed or composed here
        :param digest: which run of it; entries at other digests are left alone and are not pruned
        :param value: copied before control leaves the caller's line, so a builder stays reusable
        """
        ...

    @abstractmethod
    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        """The namespaces recorded immediately under a scope - the only enumeration AGL has.

        :param scope: the parent; immediate children only, and a caller recurses with `inside`
        :return: the same recorded set in the same order every time, so a walk is reproducible
        """
        ...

    @abstractmethod
    async def remove(self, scope: RunScope) -> None:
        """Remove this scope and everything recorded below it.

        :param scope: the run at depth zero; absence succeeds, and stopping halfway is permitted
        """
        ...
