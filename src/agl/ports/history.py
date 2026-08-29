
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from agl.ports.errors import InternalError

__all__ = ["ChangeKind", "FileChange", "History"]


class ChangeKind(StrEnum):

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class FileChange:

    path: str

    kind: ChangeKind

    previous_path: str | None = None

    def __post_init__(self) -> None:
        if not self.path:
            raise InternalError("a file change with an empty path names no file")
        if self.kind is ChangeKind.RENAMED:
            if not self.previous_path:
                raise InternalError(
                    f"the rename of {self.path!r} does not say what it was renamed from, and a "
                    f"rename with only one of its two names in it is a modification wearing the "
                    f"wrong label"
                )
            if self.previous_path == self.path:
                raise InternalError(
                    f"{self.path!r} is recorded as renamed to itself, which is not a change any "
                    f"reader can act on"
                )
        elif self.previous_path is not None:
            raise InternalError(
                f"{self.path!r} is {str(self.kind)!r} and also carries a previous path "
                f"{self.previous_path!r}; only a rename has one, and the two disagreeing means the "
                f"change was assembled wrong"
            )


class History(ABC):

    @abstractmethod
    async def default_ref(self) -> str:
        ...

    @abstractmethod
    async def resolve(self, ref: str) -> str:
        ...

    @abstractmethod
    async def exists(self, ref: str) -> bool:
        ...

    @abstractmethod
    async def contains(self, ancestor: str, descendant: str) -> bool:
        ...

    @abstractmethod
    async def changed_files(self, base: str, head: str) -> tuple[FileChange, ...]:
        ...

    @abstractmethod
    async def diff(self, base: str, head: str) -> str:
        ...

    @abstractmethod
    async def message(self, commit: str) -> str:
        ...
