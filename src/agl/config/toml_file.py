import os
import stat
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.config.distribution import DISTRIBUTION, UNINSTALLED, installed_version
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
    "check_workspace_pin",
    "git_root",
    "make_workflow",
    "make_workspace",
    "read_document",
    "read_project",
    "read_settings",
    "resolve_project",
    "write_project",
    "write_workspace_pin",
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
# composes - and the workspace would hold its own environment as a member of itself.
_MEMBERS_TABLE: Final = '[tool.uv.workspace]\nmembers = ["workflows/*"]\n'

# `[tool.<name>]` is the table a tool owns in a pyproject.toml and every other tool reads past, so
# this one is AGL's alone. The file holds no `[project]` table at all, which is what makes it a
# virtual uv workspace root rather than a package of its own, and what keeps it from ever reading
# as the workflow declaration `config/registry.py` looks for.
_TOOL: Final = "tool"
_AGL: Final = "agl"
_REQUIRES: Final = "requires"

# The scaffold is rendered from these rather than copied out of a template checked in beside them,
# because a pyproject.toml in this repository carrying a real entry-point table is exactly what
# `tests/test_measurable_targets.py`'s declaration scan exists to catch.
#
# A `WorkflowName` is a Python identifier, so nothing interpolated below can carry a character a
# TOML basic string or a Python source file would need escaped.
_MODULE_DOCUMENT: Final = """from agl.sdk import Run, workflow

@workflow(version="1")
async def {name}(run: Run) -> None:
    ...
"""

# No `[build-system]` and no dependency on AGL itself: the workspace is on this process's import
# path rather than installed into it, so a workflow is imported from where it was written and
# nothing has to build it.
_PROJECT_DOCUMENT: Final = """[project]
name = "{name}"
version = "0.1.0"

[project.entry-points."{group}"]
{name} = "{name}:{name}"
"""

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

# What a re-pin writes beside the file it is replacing, so an interrupted one leaves a name nothing
# in AGL reads: `config/registry.py` walks `workflows/` and never the workspace root's siblings.
_PARTIAL_PREFIX: Final = "partial-"

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
                handle.write(_workspace_document())
        except FileExistsError:
            return
    except OSError as error:
        raise InputError(
            f"the workspace at {workspace_dir(home)} cannot be created: {error}. That subtree is "
            f"where the workflows you write live, and AGL makes it rather than asking you to - so "
            f"until it can be made there is nowhere for a workflow to go"
        ) from error

def make_workflow(home: AglHome, name: WorkflowName, group: str) -> Path:
    directory = workflow_dir(home, name)
    try:
        directory.mkdir(parents=True)
    except FileExistsError as error:
        raise ConflictError(_already_written(directory, name)) from error
    except OSError as error:
        raise InputError(_unwritable(directory, error)) from error
    for path, document in (
        (workflow_module(home, name), _MODULE_DOCUMENT.format(name=name)),
        (workflow_pyproject(home, name), _PROJECT_DOCUMENT.format(name=name, group=group)),
    ):
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(document)
        except OSError as error:
            raise InputError(_unwritable(path, error)) from error
    return directory

# The one place in AGL that rewrites something an operator holds, and it is deliberately not part
# of `make_workspace`: creating a workspace writes over nothing, so a workspace made by an older
# AGL keeps the pin that says so until somebody asks for it to move. `agl sync` is that asking and
# is the only caller - a re-pin folded into the creation would refresh the pin on every `agl new`,
# and a pin kept current is one `check_workspace_pin` could never disagree with.
def write_workspace_pin(home: AglHome) -> None:
    """Record the running AGL as the one this workspace's workflows are written against."""
    pin = _version_pin()
    # Nothing written rather than a refusal, which is `check_workspace_pin`'s answer to the same
    # state read from the other side: an AGL with no metadata cannot name itself, so it neither
    # judges a recorded pin nor replaces one - and a checkout is where `agl sync` is run most.
    if pin is None or _recorded_pin(home) == pin:
        return
    path = workspace_pyproject(home)
    _rewrite(path, _repinned(_file_text(path), pin, path))

# What this refusal stands between is a workspace and an AGL that did not make it, and what leaves
# it room to fire is that `write_workspace_pin` above moves the pin for one command and for nothing
# a run does: an operator who upgraded AGL has not synced yet, and their workspace still names what
# wrote it. Compared as text against the string `_version_pin` writes, which is what keeps the
# comparison free of a requirement parser: PEP 503 normalises `agents_gl` onto `agents-gl` and PEP
# 440 admits `== 0.0.1` beside `==0.0.1`, so a pin somebody rewrote by hand can mean this version
# and still read as a disagreement here. What settles that is `agl sync` writing the one spelling
# this compares against, which is why the refusal below points at the command and shows the line it
# writes rather than leaving an operator to spell it.
def check_workspace_pin(home: AglHome) -> None:
    """Refuse where the workspace records one AGL and another is about to run its workflows."""
    recorded = _recorded_pin(home)
    running = _version_pin()
    if recorded is None or running is None or recorded == running:
        return
    path = workspace_pyproject(home)
    raise ConflictError(
        f"your AGL workspace was made by {recorded!r} and the AGL running now is {running!r}: "
        f"{path} sets {_REQUIRES} under [{_TOOL}.{_AGL}], which names the AGL the workflows in "
        f"that workspace were written against, and it does not name this one. AGL refuses to run "
        f"one rather than hoping the two agree - a workflow is written against the `agl.sdk` of a "
        f"particular AGL, and what a run spends before finding out otherwise is agent turns. Two "
        f"things end this and both are yours to choose between. Install {recorded!r} again, and "
        f"this workspace runs as it always did. Or keep the AGL you have: read your workflows "
        f"against this version's `agl.sdk`, then run `agl sync`, which writes "
        f"`{_REQUIRES} = {_quoted(running)}` into {path} and installs what those workflows declare "
        f"against it. That command is the only thing in AGL that moves the line, which is what "
        f"lets a workspace go on naming an AGL you no longer run. `agl sync` itself, `agl init`, "
        f"`agl new`, `agl workflows` and `agl clear` are unaffected, none of them running a "
        f"workflow"
    )

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

def _workspace_document() -> str:
    pin = _version_pin()
    if pin is None:
        return _MEMBERS_TABLE
    return f"{_MEMBERS_TABLE}\n[{_TOOL}.{_AGL}]\n{_REQUIRES} = {_quoted(pin)}\n"

# PEP 440 admits neither a leading letter nor a space, so `UNINSTALLED` can never be half of a
# requirement any resolver reads. A workspace made where there is no metadata to read therefore
# carries no pin at all, which is what a workspace made by hand carries too.
def _version_pin() -> str | None:
    version = installed_version()
    return None if version == UNINSTALLED else f"{DISTRIBUTION}=={version}"

def _recorded_pin(home: AglHome) -> str | None:
    path = workspace_pyproject(home)
    document = read_document(path)
    return None if document is None else _pin_of(document, path)

def _pin_of(document: Mapping[str, object], path: Path) -> str | None:
    tools = _sub_table(document, _TOOL, path, "")
    return _text(_sub_table(tools, _AGL, path, f"{_TOOL}."), _REQUIRES, path, f"{_TOOL}.{_AGL}.")

# One line edited in place rather than the file re-rendered from `_workspace_document`: the
# workspace root is written once and is the operator's thereafter - their own tables, their own
# comments - and a re-render would take all of it away to move one string. What makes a textual
# edit safe to make at all is `_checked_document`, which parses the result before it is written.
def _repinned(text: str, pin: str, path: Path) -> str:
    written = f"{_REQUIRES} = {_quoted(pin)}\n"
    lines = text.splitlines(keepends=True)
    header = _header_line(lines)
    if header is None:
        kept = text.rstrip("\n")
        opening = f"{kept}\n\n" if kept else ""
        return _checked_document(f"{opening}[{_TOOL}.{_AGL}]\n{written}", pin, path)
    key = _key_line(lines, header)
    before = lines[: header + 1] if key is None else lines[:key]
    after = lines[header + 1 :] if key is None else lines[key + 1 :]
    return _checked_document("".join([*before, written, *after]), pin, path)

def _header_line(lines: Sequence[str]) -> int | None:
    header = f"[{_TOOL}.{_AGL}]"
    return next((index for index, line in enumerate(lines) if line.strip() == header), None)

# The search stops at the next table header, because `requires` is not AGL's word alone: PEP 518
# gives `[build-system]` a `requires` of its own, and every workspace root this module writes is a
# file a build system's table could join later.
def _key_line(lines: Sequence[str], header: int) -> int | None:
    for index in range(header + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("["):
            return None
        if stripped.partition("=")[0].strip() == _REQUIRES:
            return index
    return None

# The composed text is parsed and read back before anything is written, so a spelling the line edit
# above cannot reach - TOML admits `agl.requires` under `[tool]` and a quoted `"requires"` under
# the header, and neither is the line this looks for - refuses with the file untouched instead of
# producing one that declares the same key twice and no longer parses.
def _checked_document(text: str, pin: str, path: Path) -> str:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise InputError(_unpinnable(path, pin)) from error
    if _pin_of(document, path) != pin:
        raise InputError(_unpinnable(path, pin))
    return text

def _rewrite(path: Path, text: str) -> None:
    try:
        # Beside the file and not in the system temp directory: `os.replace` is atomic within one
        # filesystem and raises `EXDEV` across two, which is the same reason `dir=` is written in
        # `adapters/filesystem/store.py`. What it buys here is that an interrupted re-pin leaves
        # the operator's workspace declaration whole rather than truncated.
        handle, partial = tempfile.mkstemp(dir=path.parent, prefix=_PARTIAL_PREFIX)
    except OSError as error:
        raise InputError(_unrewritable(path, error)) from error
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as opened:
            # `mkstemp` opens at 0600 by definition, and this is the operator's own file rather
            # than one of AGL's records - so the mode it already had is carried onto the rename.
            os.chmod(partial, stat.S_IMODE(path.stat().st_mode))
            opened.write(text)
        os.replace(partial, path)
    except OSError as error:
        with suppress(OSError):
            os.unlink(partial)
        raise InputError(_unrewritable(path, error)) from error

def _file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InputError(f"{path} cannot be read: {error}") from error

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

def _unpinnable(path: Path, pin: str) -> str:
    return (
        f"{path} cannot be re-pinned to {pin!r}, and nothing has been written: AGL composed the "
        f"file with that line in it, read the result back, and {_TOOL}.{_AGL}.{_REQUIRES} still "
        f"does not say it. What AGL edits is the one `{_REQUIRES}` line under a "
        f"`[{_TOOL}.{_AGL}]` header, and TOML spells that key more ways than one - "
        f"`{_AGL}.{_REQUIRES}` written under `[{_TOOL}]`, or a quoted `\"{_REQUIRES}\"` under the "
        f"header - so this file uses a spelling AGL's own writer does not reach. That is yours to "
        f"settle rather than AGL's to guess at: leave a `[{_TOOL}.{_AGL}]` table whose line reads "
        f"`{_REQUIRES} = {_quoted(pin)}`, and run `agl sync` again"
    )

def _unrewritable(path: Path, error: OSError) -> str:
    return (
        f"{path} cannot be rewritten: {error}. That file records which AGL your workspace was made "
        f"by, and `agl sync` re-pins it to the AGL running now before it installs anything. The "
        f"replacement is written beside it and renamed over it, so what is there is the file that "
        f"was always there, and nothing has been installed"
    )

def _unwritable(path: Path, error: OSError) -> str:
    return (
        f"{path} cannot be written: {error}. `agl new` writes a workflow directory and the two "
        f"files in it, so this one is unfinished - what did get written is left where it is "
        f"rather than half-removed, and deleting the directory is what starts the command over"
    )

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
