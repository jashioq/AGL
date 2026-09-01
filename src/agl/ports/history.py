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
        """Where a run starts from when the user names none. Only the repository knows this.

        :return: a ref expression, which may carry a `/` and so is none of `ids.py`'s names
        """
        ...

    @abstractmethod
    async def resolve(self, ref: str) -> str:
        """What a ref expression names right now. This is what pins a run's base.

        :param ref: a ref expression, resolved however this implementation resolves one
        :return: the full unabbreviated commit id, which is what `RunSpec.base_sha` is pinned to
        :raises NotFoundError: the ref is well-formed and this repository holds nothing under it
        """
        ...

    @abstractmethod
    async def exists(self, ref: str) -> bool:
        """Does this repository hold anything under this name? `resolve` with the answer dropped.

        :param ref: a ref expression the caller already composed; nothing new can be learnt of it
        :return: `True` for exactly the refs `resolve` answers for, `False` for the ones it refuses
        """
        ...

    @abstractmethod
    async def contains(self, ancestor: str, descendant: str) -> bool:
        """The one ancestry question AGL asks, before it deletes or keeps: is X already in Y.

        :param ancestor: the state that must already be accounted for
        :param descendant: the state that must already account for it
        :return: whether `ancestor` is reachable from `descendant`, and nothing about how far
        """
        ...

    @abstractmethod
    async def changed_files(self, base: str, head: str) -> tuple[FileChange, ...]:
        """Which files differ between two states, and how - the half a workflow decides on.

        :param base: the state changes are measured from; swapping the pair inverts the answer
        :param head: the state they are measured to
        :return: one change per differing file, in an order this port declines to promise
        """
        ...

    @abstractmethod
    async def diff(self, base: str, head: str) -> str:
        """The same change as text - the half a person or a model reads.

        :param base: the state the patch is against
        :param head: the state the patch arrives at
        :return: a unified patch, handed over untouched rather than structured into a taxonomy
        """
        ...

    @abstractmethod
    async def message(self, commit: str) -> str:
        """What one commit is called. The other half of `Workspace.commit_all(message)`.

        :param commit: a ref expression or a commit id, exactly as `resolve` takes one
        :return: the message with no trailing whitespace, so two implementations answer alike
        :raises NotFoundError: it names no state here, and "no message" would be a lie about one
        """
        ...
