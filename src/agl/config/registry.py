from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
from agl.config import workspace_path
from agl.config.toml_file import read_document
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.home_layout import AglHome, workflows_dir

__all__ = ["GROUP", "BrokenWorkflow", "Discovery", "check_unbroken", "discovered", "load", "names"]

GROUP: Final = "agl.workflows"

_PYPROJECT_FILE: Final = "pyproject.toml"
_PROJECT: Final = "project"
_ENTRY_POINTS: Final = "entry-points"

@dataclass(frozen=True, slots=True)
class BrokenWorkflow:
    """A workspace directory that claims a workflow and yields none: its name, and why not."""

    directory: str

    reason: str

@dataclass(frozen=True, slots=True)
class Discovery:
    """One walk of the workspace: the entry points it read, and the directories it could not."""

    points: tuple[EntryPoint, ...]

    broken: tuple[BrokenWorkflow, ...]

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
    for entry in entries:
        if not entry.is_dir():
            continue
        found = _declared(entry)
        points.extend(found.points)
        broken.extend(found.broken)
    return Discovery(tuple(points), tuple(broken))

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
        raise InputError(
            f"the workflow {name!r} is declared as {point.value!r}, and loading it failed: "
            f"{error}. That declaration is one line of the {GROUP} table in a workflow "
            f"directory's pyproject.toml, and what stands to the left of the colon is imported "
            f"like any other module - the workspace sits on this process's import path, so a "
            f"workflow directory is imported as a top-level module named after itself. The fix is "
            f"inside that directory, in the module and attribute the line names or in the code "
            f"they resolve to; AGL only read what was declared. The original error is chained "
            f"below this one"
        ) from error
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
            f"so that directory is the whole of it. `agl workflows` spells out the line that "
            f"declares one"
        )
    return (
        f"there is no workflow named {name!r}. Declared under {GROUP}: {', '.join(registered)}. "
        f"`agl workflows` prints the same list. Those are the keys the workspace's project files "
        f"write to the left of a declaration rather than the names of the directories holding "
        f"them, so if {name!r} is a directory you wrote, the name to type is the one its own "
        f"pyproject.toml declares"
    )

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
    table = _nested(_nested(_nested(document, _PROJECT), _ENTRY_POINTS), GROUP)
    if not table:
        return _broken(directory, _undeclared(path))
    values = {name: value for name, value in table.items() if isinstance(value, str)}
    if len(values) < len(table):
        return _broken(directory, _unusable(path, sorted(set(table) - set(values))))
    return Discovery(
        tuple(
            EntryPoint(name=name, value=value, group=GROUP)
            for name, value in sorted(values.items())
        ),
        (),
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
