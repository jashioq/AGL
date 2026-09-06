import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.home_layout import (
    AglHome,
    project_config,
    projects_dir,
    settings_file,
    workflow_dir,
    workflow_module,
    workflow_pyproject,
    workflows_dir,
    workspace_dir,
    workspace_pyproject,
)
from agl.ports.ids import ProjectName, WorkflowName
from agl.ports.tree_layout import TreesRoot

__all__ = [
    "FileAgent",
    "FileProject",
    "FileSettings",
    "check_trees_root",
    "check_unregistered",
    "git_root",
    "make_workflow",
    "make_workspace",
    "read_document",
    "read_project",
    "read_settings",
    "resolve_project",
    "write_project",
]

_PROJECT_SUFFIX: Final = ".toml"
_AGENT: Final = "agent"
_CLAUDE: Final = "claude"
_OPENAI: Final = "openai"
_ENABLED: Final = "enabled"
_CLI_PATH: Final = "cli_path"
_NAME: Final = "name"
_REPO: Final = "repo"
_TREES_ROOT: Final = "trees_root"
_BUILD: Final = "build"
_BUILD_TIMEOUT: Final = "build_timeout"
_SECTIONS: Final = (_CLAUDE, _OPENAI)
_AGENT_KEYS: Final = (_ENABLED, _CLI_PATH)
_PROJECT_KEYS: Final = (_NAME, _REPO, _TREES_ROOT, _BUILD, _BUILD_TIMEOUT)

_HOME_KEYS: Final = frozenset({"home", "agl_home", "AGL_HOME"})

# uv reads a member as a glob against the directory holding this file, so `*` there would take in
# the `.venv` a sync builds beside `workflows/` - the one `home_layout.workspace_site_packages`
# composes - and the workspace would hold its own environment as a member of itself. It is the
# whole of the document, and the `[project]` table it leaves out is what makes the file a virtual
# uv workspace root rather than a package of its own - and what keeps it from ever reading as the
# workflow declaration `config/registry.py` looks for.
_MEMBERS_TABLE: Final = '[tool.uv.workspace]\nmembers = ["workflows/*"]\n'

# The scaffold is rendered from these rather than copied out of a template checked in beside them,
# because a pyproject.toml in this repository carrying a real entry-point table is exactly what
# `tests/test_measurable_targets.py`'s declaration scan exists to catch.
#
# A `WorkflowName` is a Python identifier, so nothing interpolated below can carry a character a
# TOML basic string or a Python source file would need escaped.
_MODULE_DOCUMENT: Final = """from agl.sdk import Run, workflow

@workflow
async def {name}(run: Run) -> None:
    ...
"""

# No `[build-system]`: the workspace is on this process's import path rather than installed into
# it, so a workflow is imported from where it was written and nothing has to build it. It declares
# no requirement either, and the bound on AGL sits under `[tool.agl]` rather than in
# `dependencies` for the same reason: uv walks past a `[tool]` table it does not own, so the bound
# is read by `config/registry.py` and resolved by nobody.
_PROJECT_DOCUMENT: Final = """[project]
name = "{name}"
version = "0.1.0"

[project.entry-points."{group}"]
{name} = "{name}:{name}"
{requires}"""

# Tested for existence and never for being a directory: a linked worktree or a submodule writes a
# file holding a `gitdir:` line there instead.
_GIT: Final = ".git"

# The escapes a TOML basic string requires, as the format defines them; every other control
# character takes the format's own `\u00xx` fallback, `\x7f` included.
_ESCAPED: Final = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}

_FIRST_PRINTABLE: Final = 0x20
_DELETE: Final = 0x7F

@dataclass(frozen=True, slots=True)
class FileAgent:
    enabled: bool | None

    cli_path: Path | None

@dataclass(frozen=True, slots=True)
class FileSettings:
    claude: FileAgent
    openai: FileAgent

@dataclass(frozen=True, slots=True)
class FileProject:
    name: ProjectName

    repo: Path | None

    trees_root: TreesRoot | None

    build: str | None

    build_timeout: float | None

_NOTHING_SAID: Final = FileSettings(
    claude=FileAgent(enabled=None, cli_path=None),
    openai=FileAgent(enabled=None, cli_path=None),
)

def read_settings(home: AglHome) -> FileSettings:
    path = settings_file(home)
    document = read_document(path)
    if document is None:
        return _NOTHING_SAID
    intruders = sorted(_HOME_KEYS & document.keys())
    if intruders:
        raise InputError(
            f"{path}: {intruders[0]} cannot be set here. This file lives inside AGL_HOME, so a "
            f"home written in it could only be read once home had already been resolved. Set the "
            f"AGL_HOME environment variable instead, or pass it on the command line"
        )
    _only(document, (_AGENT,), path, "")
    agents = _sub_table(document, _AGENT, path, "")
    _only(agents, _SECTIONS, path, f"{_AGENT}.")
    return FileSettings(
        claude=_agent(_sub_table(agents, _CLAUDE, path, f"{_AGENT}."), path, _CLAUDE),
        openai=_agent(_sub_table(agents, _OPENAI, path, f"{_AGENT}."), path, _OPENAI),
    )

def read_project(home: AglHome, project: ProjectName) -> FileProject:
    path = project_config(home, project)
    document = read_document(path)
    if document is None:
        raise NotFoundError(
            f"no project named {str(project)!r} is registered: AGL looked for {path} and there is "
            f"no such file. `agl init` inside the repository writes it"
        )
    return _project(path, document)

def check_unregistered(home: AglHome, project: ProjectName) -> Path:
    path = project_config(home, project)
    if path.exists():
        raise ConflictError(_already(path, project))
    return path

def write_project(
    home: AglHome,
    project: ProjectName,
    repo: Path,
    trees_root: TreesRoot,
    build: str,
    build_timeout: float,
) -> Path:
    path = project_config(home, project)
    document = "".join(
        f"{key} = {_quoted(value)}\n"
        for key, value in (
            (_NAME, str(project)),
            (_REPO, str(repo)),
            (_TREES_ROOT, str(trees_root.path)),
            (_BUILD, build),
        )
    ) + f"{_BUILD_TIMEOUT} = {build_timeout!r}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
    except FileExistsError as error:
        raise ConflictError(_already(path, project)) from error
    except OSError as error:
        raise InputError(
            f"{path} cannot be written: {error}. That is where AGL keeps this project's settings, "
            f"so `agl init` has nowhere to record the repository it was run in"
        ) from error
    return path

def make_workspace(home: AglHome) -> None:
    try:
        workflows_dir(home).mkdir(parents=True, exist_ok=True)
        try:
            with workspace_pyproject(home).open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(_MEMBERS_TABLE)
        except FileExistsError:
            return
    except OSError as error:
        raise InputError(
            f"the workspace at {workspace_dir(home)} cannot be created: {error}. That subtree is "
            f"where the workflows you write live, and AGL makes it rather than asking you to - so "
            f"until it can be made there is nowhere for a workflow to go"
        ) from error

def make_workflow(home: AglHome, name: WorkflowName, group: str, bound: str | None) -> Path:
    directory = workflow_dir(home, name)
    try:
        directory.mkdir(parents=True)
    except FileExistsError as error:
        raise ConflictError(_already_written(directory, name)) from error
    except OSError as error:
        raise InputError(_unwritable(directory, error)) from error
    project = _PROJECT_DOCUMENT.format(name=name, group=group, requires=_bound_table(bound))
    for path, document in (
        (workflow_module(home, name), _MODULE_DOCUMENT.format(name=name)),
        (workflow_pyproject(home, name), project),
    ):
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(document)
        except OSError as error:
            raise InputError(_unwritable(path, error)) from error
    return directory

def git_root(start: Path) -> Path:
    directory = start.resolve()
    for candidate in (directory, *directory.parents):
        if (candidate / _GIT).exists():
            return candidate
    raise NotFoundError(
        f"{directory} is not inside a git repository: AGL walked up from it to "
        f"{directory.anchor} looking for a {_GIT} entry and found none. AGL works on a "
        f"repository, so run it from inside one - and `agl init` there to register it"
    )

def check_trees_root(path: Path, repo: Path, trees_root: Path) -> None:
    inside = trees_root.resolve()
    around = repo.resolve()
    if not inside.is_relative_to(around):
        return
    raise InputError(
        f"{path}: {_TREES_ROOT} is inside {_REPO}. {_TREES_ROOT} resolves to {inside} and {_REPO} "
        f"to {around}, so AGL's working checkouts would be cut inside the repository they are cut "
        f"*from* - present in your `git status`, swept up by `git add -A`, and walked by whatever "
        f"your build walks. AGL lives outside the target repository and keeps its own state under "
        f"AGL_HOME so that it never appears there. Point {_TREES_ROOT} at a directory beside the "
        f"repository rather than under it"
    )

def resolve_project(home: AglHome, start: Path) -> FileProject:
    root = git_root(start)
    for candidate in _project_files(home):
        document = read_document(candidate)
        if document is None:
            continue
        project = _project(candidate, document)
        if project.repo is None:
            continue
        try:
            # `samefile` asks the filesystem - device and inode - so a repository reached through a
            # symlink and the same one reached directly are one project, as are two spellings
            # differing only in case.
            if project.repo.samefile(root):
                return project
        except OSError:
            continue
    raise NotFoundError(
        f"no project is registered for the repository at {root}: AGL read every project settings "
        f"file under {home.path} and none of them names it as its repo. Run `agl init` inside "
        f"{root} to write one"
    )

def read_document(path: Path) -> Mapping[str, object] | None:
    """The TOML at `path`, `None` where there is no file, `InputError` for every other failure."""
    try:
        with path.open("rb") as handle:
            document: dict[str, object] = tomllib.load(handle)
    except FileNotFoundError:
        return None
    except tomllib.TOMLDecodeError as error:
        raise InputError(
            f"{path} is not valid TOML: {error}. AGL will not guess at what a half-parsed file "
            f"meant to say"
        ) from error
    except (OSError, UnicodeDecodeError) as error:
        raise InputError(f"{path} cannot be read: {error}") from error
    return document

def _project(path: Path, document: Mapping[str, object]) -> FileProject:
    _only(document, _PROJECT_KEYS, path, "")
    trees = _absolute(document, _TREES_ROOT, path, "")
    repo = _absolute(document, _REPO, path, "")
    if repo is not None and trees is not None:
        check_trees_root(path, repo, trees)
    return FileProject(
        name=_project_name(path, _text(document, _NAME, path, "")),
        repo=repo,
        trees_root=None if trees is None else TreesRoot(trees),
        build=_text(document, _BUILD, path, ""),
        build_timeout=_seconds(document, _BUILD_TIMEOUT, path, ""),
    )

def _project_name(path: Path, spelled: str | None) -> ProjectName:
    try:
        name = ProjectName(path.stem)
    except InputError as error:
        raise InputError(
            f"{path}: its filename is not a usable project name. {error}"
        ) from error
    if spelled is not None and spelled != str(name):
        raise InputError(
            f"{path}: {_NAME} is {spelled!r} but the file is called {path.name!r}, and a "
            f"project's name is its filename - that is where AGL looks it up and where its runs "
            f"are recorded. Rename the file, or correct the key"
        )
    return name

def _project_files(home: AglHome) -> list[Path]:
    directory = projects_dir(home)
    try:
        entries = sorted(directory.iterdir())
    except FileNotFoundError:
        return []
    except OSError as error:
        raise InputError(f"{directory} cannot be listed: {error}") from error
    return [entry for entry in entries if entry.suffix == _PROJECT_SUFFIX and entry.is_file()]

def _agent(table: Mapping[str, object], path: Path, section: str) -> FileAgent:
    prefix = f"{_AGENT}.{section}."
    _only(table, _AGENT_KEYS, path, prefix)
    return FileAgent(
        enabled=_flag(table, _ENABLED, path, prefix),
        cli_path=_absolute(table, _CLI_PATH, path, prefix),
    )

def _only(table: Mapping[str, object], expected: tuple[str, ...], path: Path, prefix: str) -> None:
    for key in table:
        if key not in expected:
            raise InputError(
                f"{path}: {prefix}{key} is not something AGL configures. This file's keys are "
                f"{', '.join(prefix + name for name in expected)}. An unknown key is refused "
                f"rather than ignored, because a misspelt one would keep the default silently"
            )

def _sub_table(
    table: Mapping[str, object], key: str, path: Path, prefix: str
) -> Mapping[str, object]:
    raw = table.get(key)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    raise _wrong(path, prefix + key, "a table", raw)

def _flag(table: Mapping[str, object], key: str, path: Path, prefix: str) -> bool | None:
    raw = table.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    raise _wrong(path, prefix + key, "true or false", raw)

def _text(table: Mapping[str, object], key: str, path: Path, prefix: str) -> str | None:
    raw = table.get(key)
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    raise _wrong(path, prefix + key, "a string", raw)

def _seconds(table: Mapping[str, object], key: str, path: Path, prefix: str) -> float | None:
    raw = table.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise _wrong(path, prefix + key, "a number of seconds", raw)
    return float(raw)

def _absolute(table: Mapping[str, object], key: str, path: Path, prefix: str) -> Path | None:
    text = _text(table, key, path, prefix)
    if text is None:
        return None
    value = Path(text)
    if not value.is_absolute():
        raise InputError(
            f"{path}: {prefix}{key} is {text!r}, which is a relative path. Every path in a "
            f"settings file is absolute, because this file is read from wherever AGL happened to "
            f"be invoked and a relative one would name a different directory each time"
        )
    return value

def _already(path: Path, project: ProjectName) -> str:
    return (
        f"a project named {str(project)!r} is already registered: {path} exists, and `agl init` "
        f"writes that file once per repository and never writes over it. If that is this "
        f"repository, its settings are already there - edit the file to change them, or delete it "
        f"and run `agl init` again. If it is a different repository whose directory happens to "
        f"carry the same name, one of the two has to be renamed: a project's name is its "
        f"directory's name, and that name is the file AGL records its runs beside"
    )

def _already_written(directory: Path, name: WorkflowName) -> str:
    return (
        f"a workflow named {str(name)!r} is already in your workspace: {directory} exists, and "
        f"`agl new` writes a workflow directory once and never writes over one - whatever is in "
        f"there is yours. Edit it, or run `agl new` under a name nothing has taken. `agl "
        f"workflows` lists the names the workspace declares, which are the keys each directory's "
        f"own pyproject.toml writes rather than the directories' own names"
    )

def _unwritable(path: Path, error: OSError) -> str:
    return (
        f"{path} cannot be written: {error}. `agl new` writes a workflow directory and the two "
        f"files in it, so this one is unfinished - what did get written is left where it is "
        f"rather than half-removed, and deleting the directory is what starts the command over"
    )

# Empty where there is no bound to write: `config/distribution.py` answers `None` on a tree with no
# version of its own, and a workflow claiming nothing beats one claiming a version no reader parses.
def _bound_table(bound: str | None) -> str:
    return "" if bound is None else f"\n[tool.agl]\nrequires = {_quoted(bound)}\n"

def _quoted(value: str) -> str:
    escaped = "".join(
        _ESCAPED[character]
        if character in _ESCAPED
        else f"\\u{ord(character):04x}"
        if ord(character) < _FIRST_PRINTABLE or ord(character) == _DELETE
        else character
        for character in value
    )
    return f'"{escaped}"'

def _wrong(path: Path, key: str, expected: str, got: object) -> InputError:
    return InputError(
        f"{path}: {key} is {got!r}, which is not {expected}. AGL does not coerce a settings value "
        f"into the type it was expecting - a file that says something other than what it meant is "
        f"worth stopping for"
    )
