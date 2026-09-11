import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import InvalidName, canonicalize_name
from packaging.version import InvalidVersion, Version
from agl.ports.errors import InputError

__all__ = ["check_member", "dependencies", "dependency_names", "distribution_name"]

_PROJECT: Final = "project"
_NAME: Final = "name"
_VERSION: Final = "version"
_DYNAMIC: Final = "dynamic"
_REQUIRES_PYTHON: Final = "requires-python"
_DEPENDENCIES: Final = "dependencies"
_OPTIONAL_DEPENDENCIES: Final = "optional-dependencies"
_DEPENDENCY_GROUPS: Final = "dependency-groups"
_TOOL: Final = "tool"
_UV: Final = "uv"

# `adapters/uv/syncer.py` hands `uv sync` this interpreter, and uv refuses the whole workspace when
# one member's `requires-python` leaves it out.
_RUNNING_PYTHON: Final = ".".join(str(part) for part in sys.version_info[:3])

_REFUSED: Final = "uv refuses to sync any of the workspace over it"

# Each shape refused is one uv 0.11 was seen to refuse the whole sync over, build the member for or
# sync past `[project] dependencies` for - `uv sync --offline` over a scratch workspace holding one
# member of it - or one that can: a dynamic field nothing builds, a `[tool.uv]` key that is inert.
def check_member(path: Path, document: Mapping[str, object]) -> None:
    """Refuse a project file uv would not sync as a workspace member, or would sync past."""
    project = _table(document, _PROJECT)
    if distribution_name(document) is None:
        raise InputError(_unnamed(path, project.get(_NAME)))
    _check_static(path, project)
    _check_python(path, project)
    _check_dependencies(path, project)
    _check_nothing_else_resolved(path, document, project)

def distribution_name(document: Mapping[str, object]) -> str | None:
    """Its `[project] name` spelled as uv compares members' names, `None` where uv reads none."""
    name = _table(document, _PROJECT).get(_NAME)
    if not isinstance(name, str):
        return None
    try:
        return canonicalize_name(name, validate=True)
    except InvalidName:
        return None

def dependencies(document: Mapping[str, object]) -> tuple[str, ...]:
    """Its `[project] dependencies` as written and in order, the strings among them alone."""
    declared = _table(document, _PROJECT).get(_DEPENDENCIES)
    if not isinstance(declared, list):
        return ()
    return tuple(entry for entry in declared if isinstance(entry, str))

def dependency_names(document: Mapping[str, object]) -> frozenset[str]:
    """Every distribution its `[project] dependencies` names, spelled as uv compares names."""
    named = [_named(entry) for entry in dependencies(document)]
    return frozenset(name for name in named if name is not None)

def _check_static(path: Path, project: Mapping[str, object]) -> None:
    dynamic = project.get(_DYNAMIC)
    if dynamic is not None and dynamic != []:
        raise InputError(_dynamic(path, dynamic))
    version = project.get(_VERSION)
    if isinstance(version, str):
        try:
            Version(version)
        except InvalidVersion:
            pass
        else:
            return
    raise InputError(_unversioned(path, version))

def _check_python(path: Path, project: Mapping[str, object]) -> None:
    bound = project.get(_REQUIRES_PYTHON)
    if bound is None:
        return
    if not isinstance(bound, str):
        raise InputError(_unreadable_python(path, bound))
    try:
        allowed = SpecifierSet(bound)
    except InvalidSpecifier as error:
        raise InputError(_unreadable_python(path, bound)) from error
    if not allowed.contains(_RUNNING_PYTHON, prereleases=True):
        raise InputError(_other_python(path, bound))

def _check_dependencies(path: Path, project: Mapping[str, object]) -> None:
    declared = project.get(_DEPENDENCIES, [])
    if not isinstance(declared, list) or not all(isinstance(entry, str) for entry in declared):
        raise InputError(_unlisted(path, declared))
    for entry in declared:
        try:
            Requirement(entry)
        except InvalidRequirement as error:
            raise InputError(_unreadable_requirement(path, entry, error)) from error

# What `agl get` asks the operator about is `[project] dependencies`, and each of these can make the
# sync reach past that list - seen of uv 0.11: every extra and every group resolved and a git URL in
# either cloned, the `dev` group installed, and `[tool.uv]` repointing a dependency to another
# source, installing a list of its own, or holding a workspace of its own that refuses the sync.
def _check_nothing_else_resolved(
    path: Path, document: Mapping[str, object], project: Mapping[str, object]
) -> None:
    for spelled, held in (
        (f"[{_PROJECT}.{_OPTIONAL_DEPENDENCIES}]", project.get(_OPTIONAL_DEPENDENCIES)),
        (f"[{_DEPENDENCY_GROUPS}]", document.get(_DEPENDENCY_GROUPS)),
        (f"[{_TOOL}.{_UV}]", _table(document, _TOOL).get(_UV)),
    ):
        if held is not None and held != {}:
            raise InputError(_resolved_beyond(path, spelled))

def _named(entry: str) -> str | None:
    try:
        return canonicalize_name(Requirement(entry).name)
    except InvalidRequirement:
        return None

def _table(table: Mapping[str, object], key: str) -> Mapping[str, object]:
    raw = table.get(key)
    return raw if isinstance(raw, dict) else {}

def _unnamed(path: Path, name: object) -> str:
    return (
        f"{path} gives [{_PROJECT}] {_NAME} as {name!r}, and a workspace member's name is one uv "
        f"reads - letters, digits, '.', '_' and '-', starting and ending with a letter or a "
        f"digit - so {_REFUSED} while it is missing or anything else"
    )

def _dynamic(path: Path, dynamic: object) -> str:
    return (
        f"{path} lists {dynamic!r} under [{_PROJECT}] {_DYNAMIC}, and a workflow is never built "
        f"- it is imported from where it sits - so a field left for a build to fill in is one "
        f"nothing fills in. Except uv: a workspace member whose version or dependencies are "
        f"dynamic is one it builds while the workspace syncs, installing a build backend and "
        f"running it, which is code no [{_PROJECT}] {_DEPENDENCIES} line names"
    )

def _unversioned(path: Path, version: object) -> str:
    return (
        f"{path} gives [{_PROJECT}] {_VERSION} as {version!r}, and a workspace member's version is "
        f"one uv reads as PEP 440 - so {_REFUSED} while it is missing or anything else"
    )

def _unreadable_python(path: Path, bound: object) -> str:
    return (
        f"{path} gives [{_PROJECT}] {_REQUIRES_PYTHON} as {bound!r}, which is not a version "
        f"specifier uv can read - and {_REFUSED}"
    )

def _other_python(path: Path, bound: str) -> str:
    return (
        f"{path} says this workflow needs Python {bound}, and the interpreter AGL runs on - the "
        f"one the workspace is synced for - is {_RUNNING_PYTHON}. A workspace holding one member "
        f"that cannot run there is one uv will not sync at all, every other workflow in it included"
    )

def _unlisted(path: Path, declared: object) -> str:
    return (
        f"{path} gives [{_PROJECT}] {_DEPENDENCIES} as {declared!r}, where uv reads a list of "
        f"requirement strings - and {_REFUSED}"
    )

def _unreadable_requirement(path: Path, entry: str, error: InvalidRequirement) -> str:
    return (
        f"{path} lists {entry!r} under [{_PROJECT}] {_DEPENDENCIES}, which is not a requirement "
        f"PEP 508 can read: {error}. uv cannot read it either, and falls back to building the "
        f"workflow to learn what it depends on - installing a build backend and running it while "
        f"the workspace syncs"
    )

def _resolved_beyond(path: Path, table: str) -> str:
    return (
        f"{path} has a {table} table, which uv reads off a workspace member while it syncs the "
        f"workspace, and what one can say reaches past [{_PROJECT}] {_DEPENDENCIES}: something "
        f"resolved, fetched or installed that the list does not name, or the sync refused "
        f"outright. That list is the one AGL asks about before a workflow is placed, so a download "
        f"may declare what it needs there and nowhere else"
    )
