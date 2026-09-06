from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from types import MappingProxyType
from typing import Final
from agl.config import distribution, workspace_path
from agl.config.toml_file import read_document
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.home_layout import AglHome, workflows_dir

__all__ = [
    "GROUP",
    "BrokenWorkflow",
    "Discovery",
    "check_satisfied",
    "check_unbroken",
    "discovered",
    "load",
    "names",
]

GROUP: Final = "agl.workflows"

_PYPROJECT_FILE: Final = "pyproject.toml"
_PROJECT: Final = "project"
_ENTRY_POINTS: Final = "entry-points"
_TOOL: Final = "tool"
_AGL: Final = "agl"
_REQUIRES: Final = "requires"

@dataclass(frozen=True, slots=True)
class BrokenWorkflow:
    """A workspace directory that claims a workflow and yields none: its name, and why not."""

    directory: str

    reason: str

@dataclass(frozen=True, slots=True)
class Discovery:
    """One walk: what it read, where each was declared, what would not read, what will not run."""

    points: tuple[EntryPoint, ...]

    broken: tuple[BrokenWorkflow, ...]

    # Keyed by declared name and not by directory name, the two being free to differ. A caller
    # that handed its own points over walked nothing, so no declaration came out of a directory
    # and this stays empty - `api.py` digests what is in here, and an empty map is what such a
    # run records.
    directories: Mapping[str, Path] = MappingProxyType({})

    # Keyed the same way, and holding the refusal a name earns before anything imports it. A
    # declaration stays in `points` when its directory's AGL bound is unmet, because `agl
    # workflows` lists what a workspace declares rather than what would load - so what would
    # otherwise be an `ImportError` out of the workflow's own first line is a sentence here.
    unsatisfied: Mapping[str, str] = MappingProxyType({})

def discovered(home: AglHome) -> Discovery:
    # Every point this walk synthesises names a module inside the workspace, and `EntryPoint.load`
    # resolves that name through `sys.path` like any other import - so the workspace is put there
    # here, where the points are made, rather than at whichever caller eventually loads one.
    workspace_path.extend(home)
    directory = workflows_dir(home)
    try:
        entries = sorted(directory.iterdir())
    except FileNotFoundError:
        return Discovery((), ())
    except OSError as error:
        raise InputError(
            f"{directory} cannot be listed: {error}. That directory is where AGL reads the "
            f"workflows you have written, so nothing at all can be listed until it can be read"
        ) from error
    points: list[EntryPoint] = []
    broken: list[BrokenWorkflow] = []
    directories: dict[str, Path] = {}
    unsatisfied: dict[str, str] = {}
    for entry in entries:
        if not entry.is_dir():
            continue
        found = _declared(entry)
        points.extend(found.points)
        broken.extend(found.broken)
        directories.update(found.directories)
        unsatisfied.update(found.unsatisfied)
    return Discovery(tuple(points), tuple(broken), directories, unsatisfied)

# A directory's name is not a workflow's name - `_declared` reads the key on the left of a
# declaration, wherever the file holding it sits - so a broken directory that happens to share a
# declared name has no claim on it, and the declaration wins. What is left is a name nothing
# declares, where the directory that could not be read is the likeliest thing the operator meant.
def check_unbroken(found: Discovery, name: str) -> None:
    if any(point.name == name for point in found.points):
        return
    for entry in found.broken:
        if entry.directory == name:
            raise InputError(entry.reason)

# Asked between `check_unbroken` and `load`, and the order is the whole of what this buys: `load`
# is where a workflow's module is imported, and a workflow written against an AGL this one is not
# fails that import on whichever name moved. Answering first is what turns that into a sentence.
def check_satisfied(found: Discovery, name: str) -> None:
    refusal = found.unsatisfied.get(name)
    if refusal is not None:
        raise InputError(refusal)

def names(points: Iterable[EntryPoint]) -> tuple[str, ...]:
    return tuple(sorted(_index(points)))

def load[T](points: Iterable[EntryPoint], name: str, kind: type[T]) -> T:
    index = _index(points)
    point = index.get(name)
    if point is None:
        raise NotFoundError(_unknown(name, index))
    try:
        loaded = point.load()
    except (ImportError, AttributeError) as error:
        raise InputError(_unloadable(name, point, error)) from error
    if not isinstance(loaded, kind):
        raise InputError(
            f"the workflow {name!r} is declared as {point.value!r}, which loaded and turned out "
            f"to be a {_describe(type(loaded))} rather than a {_describe(kind)}. The {GROUP} line "
            f"declaring {name!r} is pointing at the wrong object: what belongs to the right of "
            f"the colon is the name `@workflow` is bound to, which is the decorated function's "
            f"own, the decorator being what turns that function into the thing AGL runs. AGL only "
            f"read what was declared"
        )
    return loaded

def _index(points: Iterable[EntryPoint]) -> Mapping[str, EntryPoint]:
    index: dict[str, EntryPoint] = {}
    for point in points:
        held = index.get(point.name)
        if held is not None:
            raise ConflictError(
                f'two workflows are declared under the name {point.name!r}, one as {held.value!r} '
                f'and the other as {point.value!r}. AGL will not choose between them: running the '
                f'wrong one of two workflows that answer to the same name is a mistake nothing '
                f'downstream could report, so the name stays ambiguous until one of the two '
                f'declarations gives it up. Each is one `<name> = "<module>:<attribute>"` line '
                f'under [project.entry-points."{GROUP}"] in the pyproject.toml of a workflow '
                f'directory, and the name is the key on the left of that line - so changing one of '
                f'those two keys, or taking one of the two directories out of the workspace, is '
                f'the whole fix. Which two directories they are is the one thing AGL cannot say: a '
                f'declaration records the module to import and not the file it was read from, and '
                f'that module is usually, but is not required to be, the name of the directory '
                f'holding it. Searching the workspace for {point.name!r} finds both lines'
            )
        index[point.name] = point
    return index

def _unknown(name: str, index: Mapping[str, EntryPoint]) -> str:
    registered = tuple(sorted(index))
    if not registered:
        return (
            f"there is no workflow named {name!r}, and in fact no workflow is declared at all: "
            f"nothing in the workflows/ directory of your AGL workspace declares an entry point "
            f"in the {GROUP} group. A workflow is a directory you write there and declare in its "
            f"own pyproject.toml; nothing is installed and there is no list in AGL to add it to, "
            f"so that directory is the whole of it. `agl new <name>` writes one, and makes the "
            f"workspace too if that is not there yet; `agl workflows` spells out the line that "
            f"declares one, for a directory you would rather write yourself"
        )
    return (
        f"there is no workflow named {name!r}. Declared under {GROUP}: {', '.join(registered)}. "
        f"`agl workflows` prints the same list. Those are the keys the workspace's project files "
        f"write to the left of a declaration rather than the names of the directories holding "
        f"them, so if {name!r} is a directory you wrote, the name to type is the one its own "
        f"pyproject.toml declares"
    )

# The import machinery raises `ModuleNotFoundError` only where no finder answered at all, and sets
# `name` to whatever it gave up on - so a package that is simply absent is told apart here from the
# workflow's own code failing, which arrives as a plain `ImportError` (`from agl.sdk import gone`)
# or as an `AttributeError` (a declaration naming an object its module does not hold).
def _unloadable(name: str, point: EntryPoint, error: ImportError | AttributeError) -> str:
    missing = error.name if isinstance(error, ModuleNotFoundError) else None
    if missing is not None and _package(missing) != _package(point.module):
        return _uninstalled(name, point, missing)
    return (
        f"the workflow {name!r} is declared as {point.value!r}, and loading it failed: {error}. "
        f"That declaration is one line of the {GROUP} table in a workflow directory's "
        f"pyproject.toml, and what stands to the left of the colon is imported like any other "
        f"module - the workspace sits on this process's import path, so a workflow directory is "
        f"imported as a top-level module named after itself. The fix is inside that directory, in "
        f"the module and attribute the line names or in the code they resolve to; AGL only read "
        f"what was declared. The original error is chained below this one"
    )

# One wording for three callers: `api.run` and `api.resume` have installed by the time they reach
# this and `api.workflow_help` never does, and an install that was refused and warned, one that was
# never asked for and a package no file declares are three states nothing here can tell apart. So
# this names what installs and what does not, rather than a command to type.
def _uninstalled(name: str, point: EntryPoint, missing: str) -> str:
    return (
        f"the workflow {name!r} is declared as {point.value!r}, and importing it went looking for "
        f"{missing!r} and found nothing. That name is not part of {_package(point.module)!r}, "
        f"which is where this workflow's own code lives, so it is something the workflow imports "
        f"rather than something it is: a dependency, and it is not installed. An install puts in "
        f"reach what a workflow declares in the `[project] dependencies` of its own pyproject.toml "
        f"and nothing else, so if {missing!r} is not written there then writing it there is the "
        f"whole fix - a package a workflow imports and never declares is one nothing installs, "
        f"ever. If it is written there, nothing installed it before this import: what installs is "
        f"`agl run` and `agl resume`, each of which does it before importing anything at all. So "
        f"either this was one of those two and the install was refused, which said why on this "
        f"terminal above this refusal, or it was a command that imports a workflow without "
        f"installing first - which `agl workflows <workflow>` does, to read the flags one takes"
    )

def _package(module: str) -> str:
    return module.partition(".")[0]

def _describe(kind: type[object]) -> str:
    return f"{kind.__module__}.{kind.__qualname__}"

def _declared(directory: Path) -> Discovery:
    path = directory / _PYPROJECT_FILE
    try:
        document = read_document(path)
    except InputError as error:
        return _broken(directory, str(error))
    # A directory with no project file has claimed nothing. The workspace is the operator's own, so
    # a scratch copy, a notes directory or a `.venv` is stray rather than a workflow that broke.
    if document is None:
        return Discovery((), ())
    project = _nested(document, _PROJECT)
    table = _nested(_nested(project, _ENTRY_POINTS), GROUP)
    if not table:
        return _broken(directory, _undeclared(path))
    values = {name: value for name, value in table.items() if isinstance(value, str)}
    if len(values) < len(table):
        return _broken(directory, _unusable(path, sorted(set(table) - set(values))))
    # The same read of the same file the declaration came out of, and the bound sits in a `[tool]`
    # table uv walks past - so nothing here opens a second document and no sync resolves the line.
    owned = _nested(_nested(document, _TOOL), _AGL)
    bound = distribution.unsatisfied_bound(owned.get(_REQUIRES))
    return Discovery(
        tuple(
            EntryPoint(name=name, value=value, group=GROUP)
            for name, value in sorted(values.items())
        ),
        (),
        dict.fromkeys(values, directory),
        {} if bound is None else dict.fromkeys(values, _unsatisfied(path, bound)),
    )

def _nested(table: Mapping[str, object], key: str) -> Mapping[str, object]:
    raw = table.get(key)
    return raw if isinstance(raw, dict) else {}

def _broken(directory: Path, reason: str) -> Discovery:
    return Discovery((), (BrokenWorkflow(directory=directory.name, reason=reason),))

def _undeclared(path: Path) -> str:
    return (
        f'{path} declares no workflow: it parses, and it holds no {GROUP} entry point table. A '
        f'workflow directory names the object AGL is to run by writing '
        f'[project.entry-points."{GROUP}"] and one `<name> = "<module>:<attribute>"` line under '
        f'it, and the name on the left of that line is the one `agl run` takes'
    )

def _unusable(path: Path, declarations: list[str]) -> str:
    return (
        f'{path} declares {", ".join(declarations)} under {GROUP}, and what stands beside each of '
        f'those is not a string. An entry point is `<name> = "<module>:<attribute>"`, so there is '
        f'nothing written here that AGL could import'
    )

def _unsatisfied(path: Path, bound: str) -> str:
    return (
        f'{path} says this workflow needs {distribution.DISTRIBUTION}{bound}, and the AGL running '
        f'here is {distribution.installed_version()}. Nothing has been imported: a workflow whose '
        f'first line is `from agl.sdk import ...` written against an AGL this is not fails on '
        f'whichever name moved, and the failure names a line in your file rather than the version '
        f'that is wrong. That bound is the `{_REQUIRES}` line of this file\'s [{_TOOL}.{_AGL}] '
        f'table, which `agl new` writes naming the AGL that scaffolded the workflow - a floor and '
        f'not a pin, so any later AGL meets it. So either install an AGL the bound admits, or - '
        f'once the workflow is known to run against the one you have - widen the bound to say so'
    )
