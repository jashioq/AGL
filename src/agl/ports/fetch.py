from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final
from agl.ports.errors import AglError, InternalError
from agl.ports.get_request import Fetch, RepositoryAtRef, RequestedWorkflow

__all__ = [
    "FetchAnswer",
    "FetchedFile",
    "FetchedWorkflow",
    "Fetcher",
    "RefusedWorkflow",
    "Resolution",
    "ResolvedRef",
    "UnresolvedRef",
]

_SEPARATOR: Final = "/"

_UNWALKABLE: Final = frozenset({"", ".", ".."})

_SHA_CHARACTERS: Final = frozenset("0123456789abcdef")
# A git object id: sha1 is 40 characters of lowercase hexadecimal, sha256 is 64.
_SHA_LENGTHS: Final = frozenset({40, 64})

@dataclass(frozen=True, slots=True)
class FetchedFile:
    """One regular file out of a download: its bytes, and whether its owner may execute it."""

    content: bytes

    executable: bool = False

@dataclass(frozen=True, slots=True)
class FetchedWorkflow:
    """One workflow a download held: every file under its directory, at the commit downloaded."""

    workflow: RequestedWorkflow

    commit: str
    """The full object id of the commit downloaded, whatever ref the repository was asked at."""

    files: Mapping[str, FetchedFile]
    """Keyed by `/`-separated path below the workflow's own directory, whose name no key holds."""

    def __post_init__(self) -> None:
        if not _a_full_object_id(self.commit):
            raise InternalError(
                f"{self.workflow} was answered with commit {self.commit!r}, which is not a full "
                f"object id: expected 40 characters of lowercase hexadecimal (sha1) or 64 "
                f"(sha256), because that is what records which commit a download was, and a ref "
                f"does not"
            )
        for path in self.files:
            segments = path.split(_SEPARATOR)
            if _UNWALKABLE.intersection(segments):
                raise InternalError(
                    f"{self.workflow} was answered with a file at {path!r}, and every path here "
                    f"runs down from the workflow's own directory: no empty, '.' or '..' segment, "
                    f"and no leading '/', or placing it would write somewhere else"
                )
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))

@dataclass(frozen=True, slots=True)
class RefusedWorkflow:
    """One workflow a download did not yield, and the error saying why - answered, never raised."""

    workflow: RequestedWorkflow

    refusal: AglError
    """Never raised: `NotFoundError` where the repository, the ref or the directory is not there."""

    def __post_init__(self) -> None:
        if not str(self.refusal):
            raise InternalError(
                f"{self.workflow} was refused with a {type(self.refusal).__name__} that says "
                f"nothing, and the reason is the whole of what a person is shown for it"
            )

type FetchAnswer = FetchedWorkflow | RefusedWorkflow

@dataclass(frozen=True, slots=True)
class ResolvedRef:
    """One repository's ref as it stands: the commit it names at the moment it was asked."""

    repository: RepositoryAtRef

    commit: str
    """A full object id - a download of `repository` a moment later may already be past it."""

    def __post_init__(self) -> None:
        if not _a_full_object_id(self.commit):
            raise InternalError(
                f"{self.repository} was resolved to {self.commit!r}, which is not a full object "
                f"id: expected 40 characters of lowercase hexadecimal (sha1) or 64 (sha256), "
                f"because that is what a placed workflow's recorded commit is compared with"
            )

@dataclass(frozen=True, slots=True)
class UnresolvedRef:
    """A ref that could not be resolved, and the error saying why - answered, never raised."""

    repository: RepositoryAtRef

    refusal: AglError
    """Never raised: `NotFoundError` where the repository or the ref is not there to be asked of."""

    def __post_init__(self) -> None:
        if not str(self.refusal):
            raise InternalError(
                f"{self.repository} went unresolved with a {type(self.refusal).__name__} that "
                f"says nothing, and the reason is the whole of what a person is shown for it"
            )

type Resolution = ResolvedRef | UnresolvedRef

class Fetcher(ABC):
    """Every download behind one port, and every question of which commit a ref names now."""

    @abstractmethod
    async def fetch(self, fetch: Fetch) -> tuple[FetchAnswer, ...]:
        """Download one repository once, and take out of that copy every directory `fetch` asks for.

        :param fetch: one repository at one ref, with every workflow wanted from it already grouped
        :return: one answer per workflow in `fetch`, in order - a failure answered, never raised
        """
        ...

    @abstractmethod
    async def resolve(self, repository: RepositoryAtRef) -> Resolution:
        """Ask which commit one repository's ref names now, downloading nothing to learn it.

        :param repository: its ref asked exactly as written, and `None` as the default branch
        :return: the commit, or why none could be told - a failure answered, never raised
        """
        ...

def _a_full_object_id(commit: str) -> bool:
    return len(commit) in _SHA_LENGTHS and _SHA_CHARACTERS.issuperset(commit)
