"""Precedence: flags > env > file > defaults, resolved once, into the immutable objects 9.1 holds.

§1.10 charges the old configuration with three defects, and this module is the repair for all
three. Two of them look like one and are not.

**There was no precedence at all.** `AGL_HOME` was environment-only, `--max-concurrent` was
flag-only, `build` was file-only. Each setting had exactly one source, so there was no rule to write
down and nowhere to write it: an operator who exported a variable for a file-only setting got
silence, and the only way to learn which source a setting listened to was to read the code that read
it. Below, every setting has an ordered list of layers, it is the *same* order for all of them, and
one function applies it.

**It was not resolved once.** `agl_home()` and `load_project()` were called inside *every* `_cmd_*`,
so the answer was recomputed per command - and `load_project` re-scanned and re-parsed every
project's file each time (9.3 settles the scan half). Here `resolve` reads the process environment
exactly once, and each file is read exactly once per invocation.

**So the contract this module leaves behind is that nothing downstream may re-read the environment
or re-parse a settings file.** After `resolve` returns, the answer is fixed for the invocation.
Anything below the composition root that consults `os.environ` for a setting has re-opened a
question closed here, and the second answer is free to differ from the first.

## A pure core, and one line that is not

`resolve_settings` and `resolve_project` are pure in the sense that matters: nothing ambient reaches
them. The environment arrives as a `Mapping[str, str]` argument and the working directory as a
`Path`, and the files they read are the ones under the home their arguments name. They do touch a
disk - the file layer is a real layer - but they cannot see the process's environment or its cwd, so
a test drives them with a literal mapping and a `tmp_path` home and gets exactly what it said.

`resolve` is the one impure entry point: it snapshots `os.environ`, calls the pure core with it, and
returns a `Resolved` holding both the settings and that snapshot. That split is what makes "resolved
once" testable rather than asserted - there is exactly one line here that touches the real
environment, and `Resolved` carries a *copy*, so the project layer resolves from the answer the
settings layer saw rather than asking the process again.

## `Overrides` is the flag layer, and it is deliberately not an argparse parser

The flag layer is a precedence layer and this module owns precedence, so the type saying *what the
flags said* is defined here. What it is not is a parser: which flags exist, how they are spelled and
which of them `argparse` accepts is `cli/main.py`'s decision at stage 10.4, and this module receives
the parsed answer as data. Every field is optional and `Overrides()` - the ordinary case - means the
flags said nothing, the exact inversion of 9.1's rule that no field on `Settings` or `Project` has a
default: there, silence would be an invisible fifth layer; here, silence *is* the layer's answer.

## Two objects, because two commands run outside a registered repository

`agl init` and `agl workflows` (§3.10) run where no project file exists - `init` writes the first
one. `Settings` resolves fine for them; `Project` cannot exist at all. So `resolve` returns the
settings and leaves `Resolved.project(cwd)` to the commands that need one, where
`toml_file.resolve_project`'s `NotFoundError` is the right refusal. One object with a nullable
project would make every consumer unwrap something absent for exactly two commands.

## The layers, setting by setting

| Setting | Layers | Default |
|---|---|---|
| `home` | flags > env > default | `$HOME/.agl` |
| `agent.<connector>.enabled` | flags > env > file > default | `True` |
| `agent.<connector>.cli_path` | flags > env > file > default | `None` |
| `build_timeout` | flags > env > file > default | `600.0` |
| `build` | flags > env > file | *none - refused if unset* |
| `name`, `repo`, `trees_root` | file | *none - refused if unset* |

**`home` has three layers, not four.** The global settings file lives *inside* `AGL_HOME`, so it
cannot say where `AGL_HOME` is: the value would decide where to look for the file holding it.
`toml_file.read_settings` refuses a `home` key with a message saying exactly that - the refusal and
this missing layer are one fact, stated in the two places a reader might look for it.

**`enabled` defaults to true** because §3.2.1 makes *configured* and *available* different
questions. The schema records what the operator asked for; whether a harness is installed,
authenticated and on `PATH` is `AgentRunner.check_ready` at preflight. Defaulting to false would
disable-by-omission a connector nobody opted out of, and silently, an unset setting being no event
that anything can report.

**`cli_path` defaults to `None`** because `None` is exactly what `ClaudeCodeRunner` and
`OpenAiRunner` already mean by it: resolve the binary the ordinary way. The default is the adapters'
own, restated rather than invented, so there is no second policy about how a harness is found.

**`build_timeout` is where the four-layer rule is demonstrated.** The stage's acceptance criterion
is this one setting resolved from a flag, then the environment, then the file, then the default, in
that order of preference, and `tests/config/test_sources.py` walks exactly that. The default is
`600.0`, which is what §3.10's example project file writes as `build_timeout = 600`.

**`build` has no default.** There is no build command right for an unknown repository, and `agl
init` asks the operator for one (§3.10). Absent from flags, environment and file alike, that is an
`InputError` naming the project file it belongs in.

**`name`, `repo` and `trees_root` take no flag and no environment layer**, and that is a decision
rather than an omission. They are facts about which repository a project *is*, established once by
`agl init` and thereafter what a project is looked up by (§3.6). A flag repointing `repo` at a
different repository would silently record one repo's runs under another's project, and an exported
variable would do it for every invocation in that shell. Only a file can hold a fact of that kind,
so only the file layer is offered.

## The environment variable names are derived, never listed

One rule, spelled once in `_variable` and applied everywhere: `AGL_` followed by the setting's path
in upper snake case. That yields `AGL_HOME`, `AGL_BUILD`, `AGL_BUILD_TIMEOUT`,
`AGL_AGENT_CLAUDE_ENABLED`, `AGL_AGENT_CLAUDE_CLI_PATH`, `AGL_AGENT_OPENAI_ENABLED` and
`AGL_AGENT_OPENAI_CLI_PATH`, and it lets a reader predict the variable for any setting they can see.
Seven hand-written constants would be seven things free to drift out of that shape one at a time.
The section is `agent`, singular - §1.10's name for it and the file's table name both, so the
operator meets one vocabulary whichever layer they are writing in.

`HOME` is the one variable read here that is not an `AGL_` setting. It expands the default `~/.agl`,
and it is read from the passed mapping rather than through `Path.home()`, which would reach the real
process environment from inside the pure core and quietly make the default untestable.

## The environment layer parses, and a malformed value is refused

Environment values are strings and everything else is typed, so this layer converts; where it
cannot, `InputError` names the variable, its value and what was expected. Never a silent fall
through to the next layer, which would make `AGL_BUILD_TIMEOUT=soon` indistinguishable from a
setting nobody set - the failure configuration exists to prevent, and 9.3's reason for refusing
an unknown key.

Two spellings of a boolean are accepted and no others: `true` and `false`, matched without regard to
case once surrounding whitespace is stripped. Not `1`, not `yes`, not `on`. TOML writes `true` and
`false`, so one word means one thing in both layers, and a set admitting `1` invites the argument
about `2`. A variable **set to the empty string is refused rather than treated as unset**,
uniformly: `AGL_AGENT_CLAUDE_CLI_PATH=` reads as an operator clearing something, and letting it mean
"the file decides" would be a layer skipped. To mean "resolve the harness from `PATH`", unset it.

Range is deliberately not checked here. `schema.Project` refuses a non-finite or non-positive
`build_timeout`, one copy of that rule is enough, and this layer's job is that what arrives there is
a number at all - the division 9.3's `_seconds` makes.

## Errors, and what passes through untouched

`agl.ports.errors` classes only. `InputError` for anything the operator supplied that cannot be
used. `NotFoundError` propagates out of `toml_file.resolve_project` unchanged - not inside a git
repository, or inside one no project file names, both already carrying the message that sends the
reader to `agl init`. Reclassifying it would replace a message written where the facts were with one
written where they are not.

## Deliberately not built

No `--max-concurrent`: §1.10 names it as the flag-only setting, and §3.3 has since moved workflow
inputs onto the workflow, as named flags declared with `arg()`. It is not a setting this module
resolves because it is not a setting. No XDG lookup, no `.env` file, no per-project environment
overlay, no cached module-level singleton: each is a fifth source, and the charge being answered is
that the old code had too few rules about sources, not too few sources.
"""

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

__all__ = ["Overrides", "Resolved", "resolve", "resolve_project", "resolve_settings"]


# The settings tree's own path segments. Every environment variable name below is composed from
# these by `_variable`, and the project keys double as what a refusal names. They coincide with
# `toml_file`'s private vocabulary because the operator gets one vocabulary, not because either
# module may reach into the other: that module spells a *file format*, this one spells the
# *setting path* the environment rule is a pure function of.
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

# The one variable read here that is not an AGL setting: it expands the default home.
_USER_HOME: Final = "HOME"

# The fourth layer, and the only place in AGL that states any of it.
_DEFAULT_HOME_DIRNAME: Final = ".agl"
_DEFAULT_ENABLED: Final = True
_DEFAULT_BUILD_TIMEOUT: Final = 600.0


@dataclass(frozen=True, slots=True)
class Overrides:
    """What the flags said: the top precedence layer as data. Not a parser - see the docstring.

    Every field is `None` when the flag was not given, which is the whole of what this type
    expresses, and `Overrides()` is what `agl run` with no configuration flags hands in. `home`,
    `claude_cli_path` and `openai_cli_path` must be absolute; unlike the environment layer this one
    leaves that refusal to `AglHome` and to `schema`'s connector sections, because a flag was typed
    seconds ago and the operator needs no help finding where it came from.

    There is no field for `name`, `repo` or `trees_root`. Those three are file-only by decision,
    and leaving them off this class is how the decision is enforced rather than remembered.
    """

    home: Path | None = None
    build: str | None = None
    build_timeout: float | None = None
    claude_enabled: bool | None = None
    claude_cli_path: Path | None = None
    openai_enabled: bool | None = None
    openai_cli_path: Path | None = None


@dataclass(frozen=True, slots=True)
class Resolved:
    """One invocation's answer: the settings, plus the two outside layers frozen as they were.

    `overrides` and `environ` are kept because the project layer needs them and must not ask the
    process a second time - `environ` is the snapshot taken at the one impure line, not a view of
    anything live. They are not a second way to read a setting: everything they can decide has been
    decided by the time this object exists, and `settings` and `project` are where the answers are.
    """

    settings: Settings
    overrides: Overrides
    environ: Mapping[str, str]

    def project(self, cwd: Path) -> Project:
        """The project `cwd` is in, resolved from the same snapshot the settings came from.

        Called only by the commands that need a registered repository. `NotFoundError` if `cwd` is
        not inside a git repository, or is inside one that no project file names.
        """
        return resolve_project(self.settings, self.overrides, self.environ, cwd)


def resolve(overrides: Overrides) -> Resolved:
    """The one impure entry point. Reads the process environment once, then defers to the core."""
    environ: Mapping[str, str] = MappingProxyType(dict(os.environ))
    return Resolved(resolve_settings(overrides, environ), overrides, environ)


def resolve_settings(overrides: Overrides, environ: Mapping[str, str]) -> Settings:
    """Flags, environment, the global file and the defaults, composed into `schema.Settings`.

    Home is settled first, and with three layers, because the file layer is read from under it.
    """
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
    """Which project `cwd` is in, with the other layers composed onto what its file said.

    `toml_file.resolve_project` is the file layer and the lookup both - it walks up to the git root
    and finds the file naming it. Its `NotFoundError` is not caught: outside a registered
    repository "run `agl init`" is the answer, and that module already gives it.
    """
    said = toml_file.resolve_project(settings.home, cwd)
    path = project_config(settings.home, said.name)
    return Project(
        name=said.name,
        # File-only, both - and `resolve_project` matched on `repo` to return at all, so that one
        # cannot in fact be absent here. The refusal is what a `read_project` route would need, and
        # what narrows the type for the reader and the checker alike.
        repo=_required(said.repo, path, _REPO),
        trees=_required(said.trees_root, path, _TREES_ROOT),
        build=_required(
            _first(overrides.build, _text(environ, _variable(_BUILD)), said.build), path, _BUILD
        ),
        build_timeout=_settled(
            overrides.build_timeout,
            _seconds(environ, _variable(_BUILD_TIMEOUT)),
            said.build_timeout,
            default=_DEFAULT_BUILD_TIMEOUT,
        ),
    )


def _first[T](*layers: T | None) -> T | None:
    """The rule, written once: the first layer with an answer wins, and `None` is no answer.

    Every setting is expressed through this, or through `_settled`, which is this plus a default.
    Seven hand-written `if` chains would be seven places for a layer to be silently skipped, and a
    skipped layer is precisely what §1.10 charges.
    """
    for value in layers:
        if value is not None:
            return value
    return None


def _settled[T](*layers: T | None, default: T) -> T:
    """`_first` for a setting with a fourth layer. The default is simply the last one."""
    answer = _first(*layers)
    return default if answer is None else answer


def _required[T](answer: T | None, path: Path, key: str) -> T:
    """A setting no layer supplied and no default can invent. `InputError` naming where it belongs.

    One message for all three, because all three belong in the same file: `agl init` writes it with
    every key §3.10 prints, so a project missing one has a file that was edited or half-written.
    """
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
    """One connector's two settings. Written once and called twice, because the rule is one rule.

    The sections are separate types for 9.1's reasons, but the precedence applied to them is the
    same; the day it differs, this grows a parameter instead of one of two copies quietly not
    growing it.
    """
    return (
        _settled(
            enabled,
            _flag(environ, _variable(_AGENT, section, _ENABLED)),
            said.enabled,
            default=_DEFAULT_ENABLED,
        ),
        # The default is `None`, which is also what "no layer answered" is, so there is nothing for
        # `_settled` to add: the adapters' own meaning for `None` is already the last word.
        _first(cli_path, _path(environ, _variable(_AGENT, section, _CLI_PATH)), said.cli_path),
    )


def _variable(*path: str) -> str:
    """`AGL_` + the setting's path in upper snake case. The whole naming rule, in one expression."""
    return _PREFIX + "_".join(path).upper()


def _default_home(environ: Mapping[str, str]) -> Path:
    """`$HOME/.agl` - the third layer, computed from the mapping and never from the process.

    Refused rather than guessed where `HOME` is unset or relative, which happens in a cron job or a
    bare container: inventing a home would put AGL's state somewhere nobody would look for it, and
    naming `AGL_HOME` as the fix costs one export and is unambiguous.
    """
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
    """What a variable says, stripped, or `None` where it is unset. Empty is never an answer.

    Every other reader below goes through this one, so the unset rule and the empty rule are each
    written once and every variable gets both.
    """
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
    """`true` or `false`, case-insensitively, and nothing else. See the module docstring."""
    value = _text(environ, variable)
    if value is None:
        return None
    if value.lower() in (_TRUE, _FALSE):
        return value.lower() == _TRUE
    raise _wrong(variable, value, f"{_TRUE} or {_FALSE}")


def _seconds(environ: Mapping[str, str], variable: str) -> float | None:
    """A number of seconds. Range is `schema.Project`'s to refuse, not this layer's."""
    value = _text(environ, variable)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as error:
        raise _wrong(variable, value, "a number of seconds") from error


def _path(environ: Mapping[str, str], variable: str) -> Path | None:
    """An absolute path. Relative is refused here, where the variable's name can be named.

    `AglHome` and `schema._check_cli_path` refuse a relative path in their own constructors and say
    why; this is not that refusal repeated. It is the only one that can tell the operator which
    variable to go and fix, and the only place a `~` no shell expanded is caught - an unexpanded
    tilde being exactly a relative path.
    """
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
    """The one wording for "that variable does not say that". Returned, so callers raise it."""
    return InputError(
        f"{variable} is {value!r}, which is not {expected}. AGL refuses it rather than falling "
        f"through to the settings file or the default, because a typo that looks like a setting "
        f"nobody set is the failure configuration exists to prevent"
    )
