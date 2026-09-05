from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.ports.errors import InputError, InternalError
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName

__all__ = [
    "AglHome",
    "RunScope",
    "project_config",
    "project_dir",
    "projects_dir",
    "run_record",
    "scope_dir",
    "settings_file",
    "step_dir",
    "step_entry",
    "workflows_dir",
    "workspace_dir",
    "workspace_pyproject",
    "workspace_site_packages",
]

_SETTINGS_FILE: Final = "config.toml"
_PROJECTS: Final = "projects"
_RUNS: Final = "runs"
_STEPS: Final = "steps"
_WORKTREES: Final = "worktrees"
_RUN_RECORD: Final = "run.json"
_PROJECT_SUFFIX: Final = ".toml"
_ENTRY_SUFFIX: Final = ".json"

_WORKSPACE: Final = "workspace"
_WORKFLOWS: Final = "workflows"
_PYPROJECT_FILE: Final = "pyproject.toml"
_VENV: Final = ".venv"
_VENV_LIBRARY: Final = "lib"
_SITE_PACKAGES: Final = "site-packages"

_MAX_SEGMENT_BYTES: Final = 255

_DIGEST_CHARACTERS: Final = frozenset("0123456789abcdef")
_DIGEST_LENGTH: Final = 64

_INTERPRETER_FIRST: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_INTERPRETER_CHARACTERS: Final = _INTERPRETER_FIRST | frozenset("0123456789._-")

@dataclass(frozen=True, slots=True)
class AglHome:
    path: Path

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise InputError(
                f"AGL_HOME {str(self.path)!r} cannot be used: it is a relative path, and a "
                f"relative root resolves against the current working directory"
            )

@dataclass(frozen=True, slots=True)
class RunScope:
    project: ProjectName
    label: RunLabel
    namespaces: tuple[Namespace, ...] = ()

    def inside(self, namespace: Namespace) -> RunScope:
        """The same run one worktree deeper. The only way to gain depth.

        :param namespace: appended to the sequence; nesting is arbitrary, so this composes freely
        :return: a scope one namespace longer, addressing that worktree's own subtree
        """
        return RunScope(self.project, self.label, (*self.namespaces, namespace))

    @property
    def run(self) -> RunScope:
        """The same run at depth zero. The only way to lose depth.

        :return: the scope a per-run file belongs to, whichever worktree happened to ask
        """
        return RunScope(self.project, self.label)

def settings_file(home: AglHome) -> Path:
    """The operator's own settings, and the only file at the top of AGL's own root.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :return: `<home>/config.toml`, read by `config/` before anything has been constructed
    """
    return _root(home) / _SETTINGS_FILE

def projects_dir(home: AglHome) -> Path:
    """The registered projects, one settings file and one recorded subtree each.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :return: `<home>/projects/`, the one container here whose contents are themselves an answer
    """
    return _root(home) / _PROJECTS

def project_config(home: AglHome, project: ProjectName) -> Path:
    """One project's settings file - a repository, a trees root, a build command.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :param project: refused when `.toml` would push the filename past a path segment's 255 bytes
    :return: `<home>/projects/<project>.toml`
    """
    return projects_dir(home) / f"{_checked_project(project)}{_PROJECT_SUFFIX}"

def project_dir(home: AglHome, project: ProjectName) -> Path:
    """Everything AGL has recorded about one project, its runs included.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :param project: held to the same length rule as its settings file, so one answer covers both
    :return: `<home>/projects/<project>/`
    """
    return projects_dir(home) / _checked_project(project)

def scope_dir(home: AglHome, scope: RunScope) -> Path:
    """The directory a scope addresses. The one place the worktree nesting is written down.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :param scope: each namespace adds a `worktrees/<namespace>` pair, so depth two is two pairs
    :return: the run's directory at depth zero, a nested worktree's below it
    """
    path = project_dir(home, scope.project) / _RUNS / str(scope.label)
    for namespace in scope.namespaces:
        path = path / _WORKTREES / str(namespace)
    return path

def run_record(home: AglHome, scope: RunScope) -> Path:
    """The run's own record, of which there is one per run and it sits at the top.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :param scope: its namespaces are not consulted, so any depth inside a run answers the same
    :return: `<run>/run.json`
    """
    return scope_dir(home, scope.run) / _RUN_RECORD

def step_dir(home: AglHome, scope: RunScope, step: StepName) -> Path:
    """One step's entries, in the scope that ran it - every recorded run of it, superseded ones too.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :param scope: which line of work ran it; the same step under two namespaces is two directories
    :param step: which step; the name becomes the segment as it stands, validated by `ids.py`
    :return: `<scope>/steps/<step>/`, a sibling of `worktrees/` and so never colliding with one
    """
    return scope_dir(home, scope) / _STEPS / str(step)

def step_entry(home: AglHome, scope: RunScope, step: StepName, digest: str) -> Path:
    """One recorded run of one step - the file whose existence is the whole of a step's status.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :param scope: which line of work ran it; the same step under two namespaces is two directories
    :param step: which step; the name becomes the segment as it stands, validated by `ids.py`
    :param digest: the journal's own sha256 hexdigest, refused unless 64 lowercase hex characters
    :return: `<scope>/steps/<step>/<digest>.json`
    """
    return step_dir(home, scope, step) / f"{_checked_digest(digest)}{_ENTRY_SUFFIX}"

def workspace_dir(home: AglHome) -> Path:
    """The operator's own workflows and the project file that declares them, in one subtree.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :return: `<home>/workspace/`, a sibling of `projects/` that AGL reads and never creates
    """
    return _root(home) / _WORKSPACE

def workspace_pyproject(home: AglHome) -> Path:
    """The workspace's own project file, which is where its entry points are written down.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :return: `<home>/workspace/pyproject.toml`
    """
    return workspace_dir(home) / _PYPROJECT_FILE

def workflows_dir(home: AglHome) -> Path:
    """The workflows an operator has written, one directory each and no table listing them.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :return: `<home>/workspace/workflows/`, the other container whose contents are an answer
    """
    return workspace_dir(home) / _WORKFLOWS

# A venv keeps its pure-Python packages under `lib/python<major>.<minor>/` on POSIX and directly
# under `Lib/` on Windows, and only the POSIX shape is composed: `adapters/git/_trees.py` imports
# `fcntl`, so no run of AGL reaches a Windows machine at all. The segment arrives as an argument
# because reading it means `sysconfig` or `sys`, which `tests/ports/test_home_layout.py` refuses.
def workspace_site_packages(home: AglHome, interpreter: str) -> Path:
    """What a workflow may import from the workspace venv, for one interpreter and no other.

    :param home: where AGL keeps its own state, which is never where code is checked out
    :param interpreter: the `lib/` subdirectory that interpreter installs into, `python3.14`
    :return: `<home>/workspace/.venv/lib/<interpreter>/site-packages`
    """
    library = workspace_dir(home) / _VENV / _VENV_LIBRARY
    return library / _checked_interpreter(interpreter) / _SITE_PACKAGES

def _root(home: AglHome) -> Path:
    if not isinstance(home, AglHome):
        raise InternalError(
            f"home_layout was given a {type(home).__name__}, not an AglHome: AGL_HOME and the "
            f"trees root are different directories, and their layouts are never conflated"
        )
    return home.path

def _checked_project(project: ProjectName) -> str:
    name = str(project)
    length = len(name.encode("utf-8")) + len(_PROJECT_SUFFIX)
    if length > _MAX_SEGMENT_BYTES:
        raise InputError(
            f"project name {name!r} cannot be used: its settings file "
            f"{name + _PROJECT_SUFFIX!r} would be {length} bytes long, and a path segment may "
            f"not exceed {_MAX_SEGMENT_BYTES}"
        )
    return name

def _checked_digest(digest: str) -> str:
    if len(digest) != _DIGEST_LENGTH or not _DIGEST_CHARACTERS.issuperset(digest):
        raise InternalError(
            f"step digest {digest!r} is not a digest: expected {_DIGEST_LENGTH} characters of "
            f"lowercase hexadecimal, which is what sha256 hexdigests are, and what keeps a "
            f"framework-generated path segment inside the root it is joined onto"
        )
    return digest

def _checked_interpreter(interpreter: str) -> str:
    if interpreter[:1] not in _INTERPRETER_FIRST or not _INTERPRETER_CHARACTERS.issuperset(
        interpreter
    ):
        raise InternalError(
            f"interpreter {interpreter!r} is not a directory name a venv holds: expected a "
            f"letter and then letters, digits, dots, hyphens or underscores, which is what "
            f"`python3.14` is, and what keeps a framework-generated path segment inside the "
            f"root it is joined onto"
        )
    return interpreter
