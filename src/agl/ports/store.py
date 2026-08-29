
from abc import ABC, abstractmethod
from collections.abc import Mapping

from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue

__all__ = ["Store"]


class Store(ABC):

    @abstractmethod
    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        ...

    @abstractmethod
    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        ...

    @abstractmethod
    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        ...

    @abstractmethod
    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        ...

    @abstractmethod
    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        ...

    @abstractmethod
    async def remove(self, scope: RunScope) -> None:
        ...
