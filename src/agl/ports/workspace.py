
from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from pathlib import Path

from agl.ports.ids import Namespace, RunLabel

__all__ = ["Workspace", "WorkspaceProvider"]


class WorkspaceProvider(ABC):

    @abstractmethod
    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        ...

    @abstractmethod
    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        ...

    @abstractmethod
    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        ...

    @abstractmethod
    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        ...


class Workspace(ABC):

    @property
    @abstractmethod
    def path(self) -> Path:
        ...

    @property
    @abstractmethod
    def branch(self) -> str:
        ...

    @abstractmethod
    async def head(self) -> str:
        ...

    @abstractmethod
    async def commit_all(self, message: str) -> str:
        ...

    @abstractmethod
    async def restore(self, head: str) -> None:
        ...
