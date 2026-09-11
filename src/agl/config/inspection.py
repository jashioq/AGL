import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from types import MappingProxyType
from typing import Final
from agl.config import registry, workspace_member
from agl.config.provenance import Provenance, fetched_hash, rendered
from agl.config.toml_file import parsed_document, read_document
from agl.config.workflow_files import in_bytecode_cache
from agl.ports.errors import ConflictError, InputError
from agl.ports.fetch import FetchAnswer, FetchedFile, FetchedWorkflow, RefusedWorkflow
from agl.ports.get_request import RequestedWorkflow
from agl.ports.home_layout import PROVENANCE_FILE, AglHome, workflow_dir, workflows_dir

__all__ = [
    "Inspection",
    "Member",
    "PlaceableWorkflow",
    "StandingEntry",
    "folded",
    "inspected",
    "listed",
]

_PYPROJECT_FILE: Final = "pyproject.toml"
_PACKAGE_MODULE: Final = "__init__.py"
_SEPARATOR: Final = "/"
_MODULE_SEPARATOR: Final = "."

_REFUSED: Final = "uv refuses to sync any of the workspace over it"

@dataclass(frozen=True, slots=True)
class PlaceableWorkflow:
    """A downloaded workflow nothing refused: what to place, and what to ask the operator first."""

    workflow: RequestedWorkflow

    commit: str

    files: Mapping[str, FetchedFile]
    """Every file to write below its directory, bytes as they are: AGL's provenance file too."""

    dependencies: tuple[str, ...]
    """Its `[project] dependencies` as written and in order, empty where there is nothing to ask."""

    existing: Path | None
    """What stands where it would be placed, its name matched as a case-insensitive volume would."""

type Inspection = PlaceableWorkflow | RefusedWorkflow

@dataclass(frozen=True, slots=True)
class Member:
    """One member of the workspace as the others meet it: its declarations and names under uv."""

    where: str
    """How a refusal names it: the directory it stands in, or the argument that asked for it."""

    declared: frozenset[str]
    """Every name `agl run` takes that it declares."""

    distribution: str | None
    """Its `[project] name` as uv compares members' names, `None` where uv reads none."""

    required: frozenset[str]
    """Every distribution its `[project] dependencies` names, spelled as uv compares names."""

    dependencies: tuple[str, ...]
    """Its `[project] dependencies` themselves, as written and in order."""

@dataclass(frozen=True, slots=True)
class StandingEntry:
    """One name the workflows directory holds, folded, and the member standing there, if any."""

    path: Path

    folded: str

    member: Member | None

@dataclass(frozen=True, slots=True)
class _Candidate:
    """A download every check of its own passed, before it is measured against everything else."""

    workflow: RequestedWorkflow

    commit: str

    files: Mapping[str, FetchedFile]

    dependencies: tuple[str, ...]

    member: Member

def inspected(answers: Sequence[FetchAnswer], home: AglHome) -> tuple[Inspection, ...]:
    """One inspection per answer, in the answers' own order: placeable as it stands, or refused."""
    entries = listed(home)
    checked = [
        _checked(answer) if isinstance(answer, FetchedWorkflow) else answer for answer in answers
    ]
    candidates = [one for one in checked if isinstance(one, _Candidate)]
    return tuple(
        _settled(one, entries, candidates, home) if isinstance(one, _Candidate) else one
        for one in checked
    )

def _checked(fetched: FetchedWorkflow) -> _Candidate | RefusedWorkflow:
    try:
        return _candidate(fetched)
    except InputError as refused:
        return RefusedWorkflow(fetched.workflow, refused)

# Ordered for whoever reads the refusal: whether this is a workflow at all, then whether this AGL is
# one it was written for - which would explain any later check it failed - then what would stop it
# loading, and last what would stop uv syncing the workspace it joins.
def _candidate(fetched: FetchedWorkflow) -> _Candidate:
    workflow = fetched.workflow
    # Refused in the words discovery uses about a file, and nothing of this one is on disk yet, so
    # they name where it was downloaded from - by repository and directory, since the argument's
    # `@ref` is written last and would stand between the directory and its files.
    where = Path(workflow.repository.owner, workflow.repository.repo, workflow.directory)
    path = where / _PYPROJECT_FILE
    held = fetched.files.get(_PYPROJECT_FILE)
    if held is None:
        raise InputError(_unprojected(workflow))
    document = parsed_document(path, held.content)
    found = registry.declarations(where, document)
    if found.broken:
        raise InputError(found.broken[0].reason)
    if found.unsatisfied:
        raise InputError(next(iter(found.unsatisfied.values())))
    if _PACKAGE_MODULE not in fetched.files:
        raise InputError(_unpackaged(workflow))
    for point in found.points:
        _check_own(path, workflow, point)
    workspace_member.check_member(path, document)
    dependencies = workspace_member.dependencies(document)
    member = Member(
        f"{str(workflow)!r}, which this same command asks for",
        frozenset(point.name for point in found.points),
        workspace_member.distribution_name(document),
        workspace_member.dependency_names(document),
        dependencies,
    )
    files = {name: file for name, file in fetched.files.items() if _placed(name)}
    return _Candidate(workflow, fetched.commit, files, dependencies, member)

# Neither is ever placed. Bytecode is written again from the source beside it at the first import,
# and a repository can ship bytecode whose embedded hash CPython does not check against that source
# - code that would run and that no review of the directory, and no hash of it, would ever see. The
# provenance file is AGL's to write, and one that arrives describes wherever it was copied from.
def _placed(name: str) -> bool:
    return not in_bytecode_cache(name) and name.split(_SEPARATOR)[0] != PROVENANCE_FILE

# The module an entry point names is resolved on the import path like any other, so a declaration
# pointing past its own package runs whatever answers to that name - another workflow, AGL's own
# environment or the standard library - rather than anything that arrived in this download.
def _check_own(path: Path, workflow: RequestedWorkflow, point: EntryPoint) -> None:
    parsed = EntryPoint.pattern.match(point.value)
    if parsed is None:
        raise InputError(_unshaped(path, point))
    module = parsed.group("module")
    if module.partition(_MODULE_SEPARATOR)[0] != str(workflow.name):
        raise InputError(_foreign(path, workflow, point, module))

# Whatever else stands under workflows/, or arrives beside this in the same command, is measured
# against - a directory another download would replace included, since until the operator answers
# either may be the one left standing. What stands where this one goes is the one exception.
def _settled(
    candidate: _Candidate,
    entries: Sequence[StandingEntry],
    candidates: Sequence[_Candidate],
    home: AglHome,
) -> Inspection:
    workflow = candidate.workflow
    standing = [entry for entry in entries if entry.folded == workflow.name.collision_key]
    if len(standing) > 1:
        destination = workflow_dir(home, workflow.name)
        return RefusedWorkflow(workflow, ConflictError(_ambiguous(workflow, destination, standing)))
    existing = standing[0] if standing else None
    others = [
        entry.member for entry in entries if entry is not existing and entry.member is not None
    ]
    others.extend(other.member for other in candidates if other is not candidate)
    for other in others:
        clash = _clash(workflow, candidate.member, other)
        if clash is not None:
            return RefusedWorkflow(workflow, ConflictError(clash))
    provenance = Provenance(workflow, candidate.commit, fetched_hash(candidate.files))
    files = {**candidate.files, PROVENANCE_FILE: FetchedFile(rendered(provenance))}
    return PlaceableWorkflow(
        workflow,
        candidate.commit,
        MappingProxyType(files),
        candidate.dependencies,
        None if existing is None else existing.path,
    )

def _clash(workflow: RequestedWorkflow, mine: Member, theirs: Member) -> str | None:
    shared = sorted(mine.declared & theirs.declared)
    if shared:
        return _declared_twice(workflow, shared, theirs)
    if theirs.distribution is not None and theirs.distribution == mine.distribution:
        return _named_twice(workflow, theirs.distribution, theirs)
    if theirs.distribution is not None and theirs.distribution in mine.required:
        return _requires_member(workflow, theirs.distribution, theirs)
    if mine.distribution is not None and mine.distribution in theirs.required:
        return _required_by(workflow, mine.distribution, theirs)
    return None

def listed(home: AglHome) -> tuple[StandingEntry, ...]:
    """Every entry of workflows/ in name order, and none where there is no workflows/ yet."""
    directory = workflows_dir(home)
    try:
        entries = sorted(directory.iterdir())
    except FileNotFoundError:
        return ()
    except OSError as error:
        raise InputError(_unlistable(directory, error)) from error
    return tuple(StandingEntry(entry, folded(entry.name), _member_at(entry)) for entry in entries)

# A project file that will not parse declares nothing to discovery and names nothing uv could read,
# so it holds no name a download could collide with - the sync is refused over it already.
def _member_at(directory: Path) -> Member | None:
    if not directory.is_dir():
        return None
    try:
        document = read_document(directory / _PYPROJECT_FILE)
    except InputError:
        return None
    if document is None:
        return None
    return Member(
        str(directory),
        frozenset(point.name for point in registry.declarations(directory, document).points),
        workspace_member.distribution_name(document),
        workspace_member.dependency_names(document),
        workspace_member.dependencies(document),
    )

# `WorkflowName.collision_key`'s fold, asked of a directory's own name - which need not be a
# workflow's, since the operator names a directory they make by hand whatever they like.
def folded(name: str) -> str:
    return unicodedata.normalize("NFC", name.casefold())

def _unprojected(workflow: RequestedWorkflow) -> str:
    return (
        f'{workflow} holds no pyproject.toml, and a workflow directory declares itself in one: its '
        f'[project.entry-points."{registry.GROUP}"] table is where the name `agl run` takes is '
        f"written. Placed as it stands it would declare nothing, and uv takes every directory "
        f"under workflows/ as a member of the workspace - {_REFUSED}"
    )

def _unpackaged(workflow: RequestedWorkflow) -> str:
    return (
        f"{workflow} holds no __init__.py, so the directory it would be placed as is a namespace "
        f"package rather than a package: a declaration naming an attribute of it loads nothing, "
        f"and a module under it can be answered from any other directory on the import path "
        f"that shares its name"
    )

def _unshaped(path: Path, point: EntryPoint) -> str:
    return (
        f"{path} declares {point.name!r} as {point.value!r}, which is not an entry point "
        f"importlib can read: one is `<module>:<attribute>`, dotted names either side of the colon"
    )

def _foreign(path: Path, workflow: RequestedWorkflow, point: EntryPoint, module: str) -> str:
    return (
        f"{path} declares {point.name!r} as {point.value!r}, which imports {module!r} - and a "
        f"workflow `agl get` places may declare only what its own package holds, which is "
        f"{str(workflow.name)!r}, the name it is placed under. Anything else would run code from "
        f"outside the directory that was downloaded: the one the operator is asked about, and the "
        f"one its provenance file's hash measures"
    )

def _ambiguous(
    workflow: RequestedWorkflow, destination: Path, standing: Sequence[StandingEntry]
) -> str:
    return (
        f"{workflow} would be placed at {destination}, where {len(standing)} entries stand whose "
        f"names differ only in case: {', '.join(str(entry.path) for entry in standing)}. A "
        f"case-insensitive volume holds those as one, and AGL will not choose which of them a "
        f"download replaces"
    )

def _declared_twice(workflow: RequestedWorkflow, shared: Sequence[str], other: Member) -> str:
    return (
        f"{workflow} declares {', '.join(repr(name) for name in shared)}, and so does "
        f"{other.where}. Two declarations of one name are refused by `agl workflows` and `agl run` "
        f"alike - AGL will not choose between them - so this one is not placed beside the other"
    )

def _named_twice(workflow: RequestedWorkflow, distribution: str, other: Member) -> str:
    return (
        f"{workflow} is named {distribution!r} in [project] name, as uv compares names, and so is "
        f"{other.where}. uv takes every directory under workflows/ as a member of one workspace, "
        f"and it will not sync a workspace holding two members of one name at all"
    )

def _requires_member(workflow: RequestedWorkflow, distribution: str, other: Member) -> str:
    return (
        f"{workflow} depends on {distribution!r}, which is the [project] name of {other.where}. uv "
        f"reads a dependency on a workspace member's name as a dependency on that member, and "
        f"{_REFUSED} unless a [tool.uv.sources] entry says so - which no workflow `agl get` places "
        f"may carry"
    )

def _required_by(workflow: RequestedWorkflow, distribution: str, other: Member) -> str:
    return (
        f"{workflow} is named {distribution!r} in [project] name, and {other.where} depends on a "
        f"distribution of that name. uv reads a dependency on a workspace member's name as a "
        f"dependency on that member, so beside it {_REFUSED} unless a [tool.uv.sources] entry in "
        f"the other says so"
    )

def _unlistable(directory: Path, error: OSError) -> str:
    return (
        f"{directory} cannot be listed: {error}. That is where every workflow in the workspace "
        f"stands, and what stands there is what a download is checked against and what a removal "
        f"looks for - so nothing can be placed or removed until it can be read"
    )
