
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from agl.config import toml_file
from agl.config.schema import AgentSettings, ClaudeSettings, OpenAiSettings, Project, Settings
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome, project_config

__all__ = [
    "DEFAULT_BUILD_TIMEOUT",
    "Overrides",
    "Resolved",
    "resolve",
    "resolve_project",
    "resolve_settings",
]


_HOME: Final = "home"
_REPO: Final = "repo"
_TREES_ROOT: Final = "trees_root"
_BUILD: Final = "build"
_BUILD_TIMEOUT: Final = "build_timeout"
_AGENT: Final = "agent"
_CLAUDE: Final = "claude"
_OPENAI: Final = "openai"
_ENABLED: Final = "enabled"
_CLI_PATH: Final = "cli_path"

_PREFIX: Final = "AGL_"
_TRUE: Final = "true"
_FALSE: Final = "false"

_USER_HOME: Final = "HOME"

_DEFAULT_HOME_DIRNAME: Final = ".agl"
_DEFAULT_ENABLED: Final = True

DEFAULT_BUILD_TIMEOUT: Final = 600.0


@dataclass(frozen=True, slots=True)
class Overrides:

    home: Path | None = None
    build: str | None = None
    build_timeout: float | None = None
    claude_enabled: bool | None = None
    claude_cli_path: Path | None = None
    openai_enabled: bool | None = None
    openai_cli_path: Path | None = None


@dataclass(frozen=True, slots=True)
class Resolved:

    settings: Settings
    overrides: Overrides
    environ: Mapping[str, str]

    def project(self, cwd: Path) -> Project:
        return resolve_project(self.settings, self.overrides, self.environ, cwd)


def resolve(overrides: Overrides) -> Resolved:
    environ: Mapping[str, str] = MappingProxyType(dict(os.environ))
    return Resolved(resolve_settings(overrides, environ), overrides, environ)


def resolve_settings(overrides: Overrides, environ: Mapping[str, str]) -> Settings:
    flagged = _first(overrides.home, _path(environ, _variable(_HOME)))
    home = AglHome(_default_home(environ) if flagged is None else flagged)
    said = toml_file.read_settings(home)
    claude = _agent(
        _CLAUDE, overrides.claude_enabled, overrides.claude_cli_path, said.claude, environ
    )
    openai = _agent(
        _OPENAI, overrides.openai_enabled, overrides.openai_cli_path, said.openai, environ
    )
    return Settings(
        home=home,
        agents=AgentSettings(
            claude=ClaudeSettings(enabled=claude[0], cli_path=claude[1]),
            openai=OpenAiSettings(enabled=openai[0], cli_path=openai[1]),
        ),
    )


def resolve_project(
    settings: Settings, overrides: Overrides, environ: Mapping[str, str], cwd: Path
) -> Project:
    said = toml_file.resolve_project(settings.home, cwd)
    path = project_config(settings.home, said.name)
    return Project(
        name=said.name,
        repo=_required(said.repo, path, _REPO),
        trees=_required(said.trees_root, path, _TREES_ROOT),
        build=_required(
            _first(overrides.build, _text(environ, _variable(_BUILD)), said.build), path, _BUILD
        ),
        build_timeout=_settled(
            overrides.build_timeout,
            _seconds(environ, _variable(_BUILD_TIMEOUT)),
            said.build_timeout,
            default=DEFAULT_BUILD_TIMEOUT,
        ),
    )


def _first[T](*layers: T | None) -> T | None:
    for value in layers:
        if value is not None:
            return value
    return None


def _settled[T](*layers: T | None, default: T) -> T:
    answer = _first(*layers)
    return default if answer is None else answer


def _required[T](answer: T | None, path: Path, key: str) -> T:
    if answer is None:
        raise InputError(
            f"{path}: {key} is not set, and there is no default AGL could apply - it is a fact "
            f"about this project that only this file holds. `agl init` inside the repository "
            f"writes the file with all five of its keys; add {key} to it, or run init again"
        )
    return answer


def _agent(
    section: str,
    enabled: bool | None,
    cli_path: Path | None,
    said: toml_file.FileAgent,
    environ: Mapping[str, str],
) -> tuple[bool, Path | None]:
    return (
        _settled(
            enabled,
            _flag(environ, _variable(_AGENT, section, _ENABLED)),
            said.enabled,
            default=_DEFAULT_ENABLED,
        ),
        _first(cli_path, _path(environ, _variable(_AGENT, section, _CLI_PATH)), said.cli_path),
    )


def _variable(*path: str) -> str:
    return _PREFIX + "_".join(path).upper()


def _default_home(environ: Mapping[str, str]) -> Path:
    said = environ.get(_USER_HOME, "").strip()
    if said and Path(said).is_absolute():
        return Path(said) / _DEFAULT_HOME_DIRNAME
    raise InputError(
        f"AGL cannot tell where to keep its own state: {_variable(_HOME)} is unset, and the "
        f"default {_DEFAULT_HOME_DIRNAME} directory under your home cannot be located because "
        f"{_USER_HOME} is {said!r} rather than an absolute path. Set {_variable(_HOME)} to an "
        f"absolute directory"
    )


def _text(environ: Mapping[str, str], variable: str) -> str | None:
    if variable not in environ:
        return None
    value = environ[variable].strip()
    if not value:
        raise InputError(
            f"{variable} is set to the empty string, which is not a value AGL can use. An empty "
            f"variable reads as an operator clearing a setting, so it is refused rather than "
            f"treated as unset - to let the settings file or the default decide, unset it"
        )
    return value


def _flag(environ: Mapping[str, str], variable: str) -> bool | None:
    value = _text(environ, variable)
    if value is None:
        return None
    if value.lower() in (_TRUE, _FALSE):
        return value.lower() == _TRUE
    raise _wrong(variable, value, f"{_TRUE} or {_FALSE}")


def _seconds(environ: Mapping[str, str], variable: str) -> float | None:
    value = _text(environ, variable)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as error:
        raise _wrong(variable, value, "a number of seconds") from error


def _path(environ: Mapping[str, str], variable: str) -> Path | None:
    value = _text(environ, variable)
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise InputError(
            f"{variable} is {value!r}, which is a relative path. Every path AGL is given is "
            f"absolute, because a relative one resolves against whatever directory AGL was invoked "
            f"from - for an agent step, a worktree AGL chose. A leading ~ counts: the shell "
            f"expands it, and a variable set without one arrives here unexpanded"
        )
    return path


def _wrong(variable: str, value: str, expected: str) -> InputError:
    return InputError(
        f"{variable} is {value!r}, which is not {expected}. AGL refuses it rather than falling "
        f"through to the settings file or the default, because a typo that looks like a setting "
        f"nobody set is the failure configuration exists to prevent"
    )
