
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
]


_SETTINGS_FILE: Final = "config.toml"
_PROJECTS: Final = "projects"
_RUNS: Final = "runs"
_STEPS: Final = "steps"
_WORKTREES: Final = "worktrees"
_RUN_RECORD: Final = "run.json"
_PROJECT_SUFFIX: Final = ".toml"
_ENTRY_SUFFIX: Final = ".json"

_MAX_SEGMENT_BYTES: Final = 255

_DIGEST_CHARACTERS: Final = frozenset("0123456789abcdef")
_DIGEST_LENGTH: Final = 64


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
        return RunScope(self.project, self.label, (*self.namespaces, namespace))

    @property
    def run(self) -> RunScope:
        return RunScope(self.project, self.label)


def settings_file(home: AglHome) -> Path:
    return _root(home) / _SETTINGS_FILE


def projects_dir(home: AglHome) -> Path:
    return _root(home) / _PROJECTS


def project_config(home: AglHome, project: ProjectName) -> Path:
    return projects_dir(home) / f"{_checked_project(project)}{_PROJECT_SUFFIX}"


def project_dir(home: AglHome, project: ProjectName) -> Path:
    return projects_dir(home) / _checked_project(project)


def scope_dir(home: AglHome, scope: RunScope) -> Path:
    path = project_dir(home, scope.project) / _RUNS / str(scope.label)
    for namespace in scope.namespaces:
        path = path / _WORKTREES / str(namespace)
    return path


def run_record(home: AglHome, scope: RunScope) -> Path:
    return scope_dir(home, scope.run) / _RUN_RECORD


def step_dir(home: AglHome, scope: RunScope, step: StepName) -> Path:
    return scope_dir(home, scope) / _STEPS / str(step)


def step_entry(home: AglHome, scope: RunScope, step: StepName, digest: str) -> Path:
    return step_dir(home, scope, step) / f"{_checked_digest(digest)}{_ENTRY_SUFFIX}"


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
