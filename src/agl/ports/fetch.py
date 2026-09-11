from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final
from agl.ports.errors import AglError, InternalError
from agl.ports.get_request import Fetch, RequestedWorkflow

__all__ = ["FetchAnswer", "FetchedFile", "FetchedWorkflow", "Fetcher", "RefusedWorkflow"]

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
        if len(self.commit) not in _SHA_LENGTHS or not _SHA_CHARACTERS.issuperset(self.commit):
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

class Fetcher(ABC):
    """Every download behind one port: a repository at a ref, and each workflow taken from it."""

    @abstractmethod
    async def fetch(self, fetch: Fetch) -> tuple[FetchAnswer, ...]:
        """Download one repository once, and take out of that copy every directory `fetch` asks for.

        :param fetch: one repository at one ref, with every workflow wanted from it already grouped
        :return: one answer per workflow in `fetch`, in order - a failure answered, never raised
        """
        ...
