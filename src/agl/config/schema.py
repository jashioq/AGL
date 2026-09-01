from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome
from agl.ports.ids import ProjectName
from agl.ports.tree_layout import TreesRoot

__all__ = ["AgentSettings", "ClaudeSettings", "OpenAiSettings", "Project", "Settings"]

@dataclass(frozen=True, slots=True)
class ClaudeSettings:
    enabled: bool

    cli_path: Path | None

    def __post_init__(self) -> None:
        _check_cli_path(self.cli_path, "claude")

@dataclass(frozen=True, slots=True)
class OpenAiSettings:
    enabled: bool

    cli_path: Path | None

    def __post_init__(self) -> None:
        _check_cli_path(self.cli_path, "openai")

@dataclass(frozen=True, slots=True)
class AgentSettings:
    claude: ClaudeSettings
    openai: OpenAiSettings

@dataclass(frozen=True, slots=True)
class Settings:
    home: AglHome

    agents: AgentSettings

@dataclass(frozen=True, slots=True)
class Project:
    name: ProjectName

    repo: Path

    trees: TreesRoot

    build: str

    build_timeout: float

    def __post_init__(self) -> None:
        if not self.repo.is_absolute():
            raise InputError(
                f"repo {str(self.repo)!r} cannot be used: it is a relative path, and a relative "
                f"repository resolves against whatever directory the process started in - which "
                f"for an agent step is a worktree AGL chose, not the one the operator typed it in"
            )
        if not self.build.strip():
            raise InputError(
                f"build {self.build!r} cannot be used: it is the command the merge gate runs, and "
                f"a blank one would make every run's gate pass without building anything. If this "
                f"project has no build, that is a decision to make where the gate is configured, "
                f"not a value that arrives here empty"
            )
        if not isfinite(self.build_timeout) or self.build_timeout <= 0:
            raise InputError(
                f"build_timeout {self.build_timeout!r} cannot be used: it is a number of seconds "
                f"the build is allowed to take, so it must be finite and greater than zero. Zero "
                f"or less kills every build before it starts; an infinite deadline is a run that "
                f"hangs on a build nobody is watching"
            )

def _check_cli_path(cli_path: Path | None, section: str) -> None:
    if cli_path is not None and not cli_path.is_absolute():
        raise InputError(
            f"{section} cli_path {str(cli_path)!r} cannot be used: it is a relative path, and a "
            f"relative program path resolves against the process's working directory - which for "
            f"an agent run is a worktree AGL chose. Give an absolute path, or leave it unset and "
            f"let the adapter resolve the harness from PATH"
        )
