import string
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final
from agl.ports.errors import InputError, InternalError
from agl.ports.ids import WorkflowName

__all__ = ["Fetch", "GetRequest", "RepositoryAtRef", "RequestedWorkflow"]

_SHAPE: Final = "owner/repo[@ref]/path/to/workflow[,sibling...]"

_SEPARATOR: Final = "/"
_REF_MARK: Final = "@"
_SIBLING_MARK: Final = ","

# Every character GitHub allows in a repository's name, which is wider than what it allows in an
# owner's - so no name it hands out is refused here, and nothing that would move a download address,
# a `?`, a `#`, a `%`, a space or a slash, is let into one.
_ADDRESS_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "._-")

_TRAVERSAL: Final = frozenset({".", ".."})

_BACKSLASH: Final = "\\"

# Unicode's top-level category for control, format, surrogate, private-use and unassigned code
# points - none of which is a character anyone reads in a directory's name.
_INVISIBLE_CATEGORY: Final = "C"

@dataclass(frozen=True, slots=True)
class RepositoryAtRef:
    """One public repository at one ref: downloaded once, however many workflows it holds."""

    owner: str

    repo: str

    ref: str | None
    """As written after the `@`, or None for whichever branch is the default when it is fetched."""

    def __post_init__(self) -> None:
        named = [("owner", self.owner), ("repository", self.repo)]
        if self.ref is not None:
            named.append(("ref", self.ref))
        for noun, value in named:
            reason = _unaddressable(value)
            if reason is not None:
                raise InputError(f"{noun} {value!r} cannot be used: {reason}")

    def __str__(self) -> str:
        spelled = f"{self.owner}{_SEPARATOR}{self.repo}"
        return spelled if self.ref is None else f"{spelled}{_REF_MARK}{self.ref}"

@dataclass(frozen=True, slots=True)
class RequestedWorkflow:
    """One workflow asked for: the repository it is in, its directory there, and the argument."""

    repository: RepositoryAtRef

    directory: str
    """From the repository's root, `/`-separated, and ending in the directory's own name."""

    spec: str
    """The whole argument this was read from, a comma list's other entries included."""

    name: WorkflowName = field(init=False)
    """The directory's own name, which is the one it is placed under in the workspace."""

    def __post_init__(self) -> None:
        *parents, own = self.directory.split(_SEPARATOR)
        for segment in parents:
            reason = _unwalkable(segment)
            if reason is not None:
                raise InputError(f"directory {self.directory!r} cannot be used: {reason}")
        try:
            name = WorkflowName(own)
        except InputError as refused:
            raise InputError(
                f"directory {self.directory!r} is placed in the workspace under its own name, "
                f"and {refused}"
            ) from refused
        object.__setattr__(self, "name", name)

    def __str__(self) -> str:
        return f"{self.repository}{_SEPARATOR}{self.directory}"

@dataclass(frozen=True, slots=True)
class Fetch:
    """One repository at one ref and every workflow wanted from it: one download, not one each."""

    repository: RepositoryAtRef
    """As its first workflow spelled it: a later one may spell owner and name in another case."""

    workflows: tuple[RequestedWorkflow, ...]

    def __post_init__(self) -> None:
        if not self.workflows:
            raise InternalError(
                f"a fetch of {self.repository} was handed no workflow at all, and a download that "
                f"nothing is extracted from buys nothing"
            )
        strays = [
            str(workflow)
            for workflow in self.workflows
            if _fetch_key(workflow.repository) != _fetch_key(self.repository)
        ]
        if strays:
            raise InternalError(
                f"a fetch of {self.repository} was handed {strays}, which it does not hold: one "
                f"download is one repository at one ref, and another's directory is not in it"
            )

@dataclass(frozen=True, slots=True)
class GetRequest:
    """Every workflow one command asks for, in the order asked: no two placed in one directory."""

    workflows: tuple[RequestedWorkflow, ...]

    def __post_init__(self) -> None:
        if not self.workflows:
            raise InputError(f"no workflow was asked for - expected at least one {_SHAPE}")
        placed: dict[str, RequestedWorkflow] = {}
        for workflow in self.workflows:
            earlier = placed.get(workflow.name.collision_key)
            if earlier is not None:
                raise InputError(_placed_twice(earlier, workflow))
            placed[workflow.name.collision_key] = workflow

    @classmethod
    def parsed(cls, specs: Sequence[str]) -> GetRequest:
        """Every workflow the arguments of one command ask for, read in the order they were written.

        :param specs: one `owner/repo[@ref]/path/to/workflow[,sibling...]` per argument
        :return: the whole request, or none of it: one bad argument refuses every other one too
        :raises InputError: naming the argument, what was expected of it and what is wrong with it
        :raises InternalError: handed one `str`, which would read as one argument per character
        """
        if isinstance(specs, str):
            raise InternalError(
                f"GetRequest.parsed was handed the one string {specs!r} rather than a sequence of "
                f"them, and a `str` is a sequence of its own characters - each would be read as an "
                f"argument of its own"
            )
        return cls(tuple(workflow for spec in specs for workflow in _requested(spec)))

    @property
    def fetches(self) -> tuple[Fetch, ...]:
        """The downloads this request needs: one per repository at a ref, first asked first.

        :return: each with every workflow wanted from it, owner and name matched in any case
        """
        grouped: dict[tuple[str, str, str | None], list[RequestedWorkflow]] = {}
        for workflow in self.workflows:
            grouped.setdefault(_fetch_key(workflow.repository), []).append(workflow)
        return tuple(Fetch(members[0].repository, tuple(members)) for members in grouped.values())

def _requested(spec: str) -> tuple[RequestedWorkflow, ...]:
    problem = _malformed(spec)
    if problem is not None:
        raise InputError(f"{spec!r} {problem} - expected {_SHAPE}")
    owner, named, *path = spec.split(_SEPARATOR)
    # GitHub allows no `@` in an owner's or a repository's name, so the first one starts the ref. A
    # git ref may hold `/` itself - `release/1.2` - but here the next `/` ends it, so a ref of that
    # shape cannot be written in this grammar at all.
    repo, marked, ref = named.partition(_REF_MARK)
    *parents, siblings = path
    try:
        repository = RepositoryAtRef(owner, repo, ref if marked else None)
        return tuple(
            RequestedWorkflow(repository, _SEPARATOR.join((*parents, sibling)), spec)
            for sibling in siblings.split(_SIBLING_MARK)
        )
    except InputError as refused:
        raise InputError(f"in {spec!r}, {refused}") from refused

def _malformed(spec: str) -> str | None:
    if not spec:
        return "is empty"
    if spec.startswith(_SEPARATOR):
        return "starts with '/', where the repository's owner belongs"
    if spec.endswith(_SEPARATOR):
        return "ends with '/', where the name of the workflow's own directory belongs"
    segments = spec.split(_SEPARATOR)
    if "" in segments:
        return "holds '//', with nothing between the two"
    _, *after_owner = segments
    if not after_owner:
        return "names an owner and no repository"
    named, *path = after_owner
    if not path:
        return "names a repository and no directory inside it"
    _, marked, ref = named.partition(_REF_MARK)
    if marked and not ref:
        return "has an '@' with no ref after it, where no '@' at all asks for the default branch"
    if "" in path[-1].split(_SIBLING_MARK):
        return f"has an empty entry in its comma list {path[-1]!r}, and each entry names a sibling"
    return None

def _unaddressable(value: str) -> str | None:
    if not value:
        return "it is empty"
    if value in _TRAVERSAL:
        return "it is a path traversal segment, which would move the address it is written into"
    for index, character in enumerate(value):
        if character not in _ADDRESS_CHARACTERS:
            return (
                f"it contains {character!r} at position {index}, and it may hold only letters "
                f"A-Z a-z, digits, and '.', '_' or '-'"
            )
    return None

def _unwalkable(segment: str) -> str | None:
    if not segment:
        return "it has an empty segment, which a '/' at either end or two in a row would write"
    if segment in _TRAVERSAL:
        return (
            f"its segment {segment!r} is a path traversal segment, and the path runs down from "
            f"the repository's root and nowhere else"
        )
    for index, character in enumerate(segment):
        if character == _BACKSLASH:
            return (
                f"its segment {segment!r} contains {character!r} at position {index}, which is a "
                f"separator on Windows, and this path is separated by '/' alone"
            )
        if unicodedata.category(character).startswith(_INVISIBLE_CATEGORY):
            return (
                f"its segment {segment!r} contains {character!r} at position {index}, which is a "
                f"control or other invisible character"
            )
    return None

# GitHub answers to an owner and a repository in any case, while git keeps two refs that differ only
# in case apart - so one fetch covers every spelling of the first two, and one spelling of the ref.
def _fetch_key(repository: RepositoryAtRef) -> tuple[str, str, str | None]:
    return repository.owner.casefold(), repository.repo.casefold(), repository.ref

def _placed_twice(earlier: RequestedWorkflow, later: RequestedWorkflow) -> str:
    if str(earlier) == str(later):
        return f"{str(later)!r} is asked for twice, and a workspace holds one workflow of each name"
    if earlier.name == later.name:
        return (
            f"{str(earlier)!r} and {str(later)!r} are both workflow {str(later.name)!r}, and a "
            f"workspace holds one workflow of each name"
        )
    return (
        f"{str(earlier)!r} and {str(later)!r} are workflows {str(earlier.name)!r} and "
        f"{str(later.name)!r}, which differ only in case and so are one directory on a "
        f"case-insensitive volume"
    )
