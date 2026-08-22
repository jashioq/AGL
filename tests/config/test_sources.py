"""Precedence, layer by layer, driven entirely by literal mappings and a `tmp_path` home.

**Not one test below reads the process environment**, and that is half of what is being asserted.
`resolve_settings` and `resolve_project` take the environment as an argument, so every case here
hands them a dict written in the test, and a case that passed by accident because the machine
happened to export something is not a shape this file can have. The two tests at the bottom are the
other half: they are the only ones that touch `os.environ`, they exercise the single impure line,
and one of them mutates the real environment *after* `resolve` returns to show that the answer no
longer moves.

No git repository is created either - `toml_file.git_root` walks the filesystem for a `.git` entry
and asks git nothing, so a bare directory named `.git` is the whole of the input it can see. Paths
are compared resolved, because `tmp_path` on macOS sits under a symlinked temporary directory.

Refusals are asserted on their class *and* on the variable, the value or the file appearing in the
message: "it raised" is satisfied by a refusal that leaves the operator hunting for which of their
seven variables was the wrong one.
"""

from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from textwrap import dedent
from typing import Final

import pytest

from agl.config.schema import ClaudeSettings, OpenAiSettings
from agl.config.sources import Overrides, resolve, resolve_project, resolve_settings
from agl.ports.errors import InputError, NotFoundError
from agl.ports.home_layout import AglHome, project_config
from agl.ports.ids import ProjectName
from agl.ports.tree_layout import TreesRoot

# The seven variables the naming rule produces. Written out once, here, so that a rule quietly
# changing shape breaks a test that names the old spelling rather than passing on the new one.
_HOME: Final = "AGL_HOME"
_BUILD: Final = "AGL_BUILD"
_BUILD_TIMEOUT: Final = "AGL_BUILD_TIMEOUT"
_CLAUDE_ENABLED: Final = "AGL_AGENT_CLAUDE_ENABLED"
_CLAUDE_CLI_PATH: Final = "AGL_AGENT_CLAUDE_CLI_PATH"
_OPENAI_ENABLED: Final = "AGL_AGENT_OPENAI_ENABLED"
_OPENAI_CLI_PATH: Final = "AGL_AGENT_OPENAI_CLI_PATH"

_NAME: Final = "myapp"


def _home(tmp_path: Path) -> AglHome:
    return AglHome(tmp_path.resolve() / "agl-home")


def _env(home: AglHome, **rest: str) -> Mapping[str, str]:
    """An environment that names a home, plus whatever the case is about. A literal, every time."""
    return {_HOME: str(home.path), **rest}


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip(), encoding="utf-8")
    return path


def _settings_file(home: AglHome, text: str) -> Path:
    return _write(home.path / "config.toml", text)


def _repo(tmp_path: Path) -> Path:
    """A directory that looks like a working tree to a filesystem walk, and to nothing else."""
    root = (tmp_path.resolve() / "repo").resolve()
    (root / ".git").mkdir(parents=True, exist_ok=True)
    return root


def _resolve_both(environ: Mapping[str, str], repo: Path) -> None:
    """Both halves of the core, in the order a command runs them. A refusal from either surfaces."""
    resolve_project(resolve_settings(Overrides(), environ), Overrides(), environ, repo)


def _project_file(home: AglHome, repo: Path, *, keys: str = "") -> Path:
    """§3.10's file, with `name`, `repo` and `trees_root` always present and the rest per case."""
    return _write(
        project_config(home, ProjectName(_NAME)),
        f'name = "{_NAME}"\n'
        f'repo = "{repo}"\n'
        f'trees_root = "{repo.parent}/.agl-trees/{_NAME}"\n{dedent(keys)}',
    )


# --- home: three layers, and the file is not one of them ---------------------------------------


def test_home_prefers_the_flag_over_the_environment_variable(tmp_path: Path) -> None:
    flagged = tmp_path.resolve() / "flagged"
    settings = resolve_settings(Overrides(home=flagged), _env(_home(tmp_path)))
    assert settings.home == AglHome(flagged)


def test_home_falls_from_the_flag_to_the_environment_variable(tmp_path: Path) -> None:
    home = _home(tmp_path)
    assert resolve_settings(Overrides(), _env(home)).home == home


def test_home_falls_from_the_environment_to_the_default_under_the_user_home(
    tmp_path: Path,
) -> None:
    """`$HOME/.agl`, expanded from the passed mapping - never through `Path.home()`."""
    user = tmp_path.resolve() / "somebody"
    settings = resolve_settings(Overrides(), {"HOME": str(user)})
    assert settings.home == AglHome(user / ".agl")


def test_home_has_no_file_layer_because_the_file_lives_inside_it(tmp_path: Path) -> None:
    """The missing fourth layer and 9.3's dedicated refusal are one fact. This is the other half."""
    home = _home(tmp_path)
    path = _settings_file(home, 'home = "/elsewhere"\n')
    with pytest.raises(InputError) as raised:
        resolve_settings(Overrides(), _env(home))
    assert str(path) in str(raised.value)
    assert "inside AGL_HOME" in str(raised.value)


def test_a_relative_home_variable_is_refused_naming_the_variable(tmp_path: Path) -> None:
    with pytest.raises(InputError) as raised:
        resolve_settings(Overrides(), {_HOME: "relative/agl"})
    assert _HOME in str(raised.value)
    assert "relative/agl" in str(raised.value)


def test_no_home_variable_and_no_user_home_is_refused_naming_both(tmp_path: Path) -> None:
    with pytest.raises(InputError) as raised:
        resolve_settings(Overrides(), {})
    assert _HOME in str(raised.value)
    assert "HOME" in str(raised.value)


# --- the connector sections: four layers each ---------------------------------------------------


def test_enabled_falls_flag_then_environment_then_file_then_true(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _settings_file(
        home,
        """
        [agent.claude]
        enabled = true
        """,
    )
    flags = Overrides(claude_enabled=False)
    with_variable = _env(home, **{_CLAUDE_ENABLED: "true"})

    assert resolve_settings(flags, with_variable).agents.claude.enabled is False
    assert resolve_settings(Overrides(), with_variable).agents.claude.enabled is True
    off = _env(home, **{_CLAUDE_ENABLED: "false"})
    assert resolve_settings(Overrides(), off).agents.claude.enabled is False
    assert resolve_settings(Overrides(), _env(home)).agents.claude.enabled is True
    _settings_file(home, "")
    assert resolve_settings(Overrides(), _env(home)).agents.claude.enabled is True


def test_enabled_defaults_to_true_because_configured_is_not_available(tmp_path: Path) -> None:
    """§3.2.1: whether a harness is installed is `check_ready`'s answer, not a settings default."""
    agents = resolve_settings(Overrides(), _env(_home(tmp_path))).agents
    assert agents.claude.enabled
    assert agents.openai.enabled


def test_cli_path_falls_flag_then_environment_then_file_then_none(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _settings_file(
        home,
        """
        [agent.openai]
        cli_path = "/from/file"
        """,
    )
    flags = Overrides(openai_cli_path=Path("/from/flag"))
    environ = _env(home, **{_OPENAI_CLI_PATH: "/from/env"})
    assert resolve_settings(flags, environ).agents.openai.cli_path == Path("/from/flag")
    assert resolve_settings(Overrides(), environ).agents.openai.cli_path == Path("/from/env")
    assert resolve_settings(Overrides(), _env(home)).agents.openai.cli_path == Path("/from/file")
    _settings_file(home, "")
    assert resolve_settings(Overrides(), _env(home)).agents.openai.cli_path is None


def test_every_one_of_the_seven_variables_is_spelled_as_the_rule_says(tmp_path: Path) -> None:
    """`AGL_` + the setting's path in upper snake case, pinned by driving all seven at once."""
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    _project_file(home, repo)
    environ = _env(
        home,
        **{
            _BUILD: "make check",
            _BUILD_TIMEOUT: "12.5",
            _CLAUDE_ENABLED: "false",
            _CLAUDE_CLI_PATH: "/harness/claude",
            _OPENAI_ENABLED: "false",
            _OPENAI_CLI_PATH: "/harness/openai",
        },
    )
    settings = resolve_settings(Overrides(), environ)
    assert settings.home == home
    assert settings.agents.claude == ClaudeSettings(False, Path("/harness/claude"))
    assert settings.agents.openai == OpenAiSettings(False, Path("/harness/openai"))
    project = resolve_project(settings, Overrides(), environ, repo)
    assert (project.build, project.build_timeout) == ("make check", 12.5)


# --- the acceptance criterion -------------------------------------------------------------------


def test_the_stage_criterion_build_timeout_from_flag_then_env_then_file_then_default(
    tmp_path: Path,
) -> None:
    """One setting, four layers, in order of preference. This is stage 9.2's acceptance criterion.

    The same `build_timeout` is resolved from a flag; then with the flag gone, from the
    environment; then with the variable gone as well, from the project file; then with all three
    gone, from the default §3.10's example file writes as `build_timeout = 600`.
    """
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    _project_file(home, repo, keys='build = "make"\nbuild_timeout = 300\n')
    settings = resolve_settings(Overrides(), _env(home))
    with_variable = _env(home, **{_BUILD_TIMEOUT: "200"})

    flagged = resolve_project(settings, Overrides(build_timeout=100.0), with_variable, repo)
    assert flagged.build_timeout == 100.0

    from_environment = resolve_project(settings, Overrides(), with_variable, repo)
    assert from_environment.build_timeout == 200.0

    from_file = resolve_project(settings, Overrides(), _env(home), repo)
    assert from_file.build_timeout == 300.0

    _project_file(home, repo, keys='build = "make"\n')
    defaulted = resolve_project(settings, Overrides(), _env(home), repo)
    assert defaulted.build_timeout == 600.0


# --- the rest of the project ---------------------------------------------------------------------


def test_build_falls_flag_then_environment_then_file_and_has_no_default(tmp_path: Path) -> None:
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    path = _project_file(home, repo, keys='build = "from file"\n')
    settings = resolve_settings(Overrides(), _env(home))
    with_variable = _env(home, **{_BUILD: "from env"})

    flagged = Overrides(build="from flag")
    assert resolve_project(settings, flagged, with_variable, repo).build == "from flag"
    assert resolve_project(settings, Overrides(), with_variable, repo).build == "from env"
    assert resolve_project(settings, Overrides(), _env(home), repo).build == "from file"

    _project_file(home, repo)
    with pytest.raises(InputError) as raised:
        resolve_project(settings, Overrides(), _env(home), repo)
    assert str(path) in str(raised.value)
    assert "build" in str(raised.value)


def test_name_and_repo_and_trees_root_take_no_flag_and_no_environment_layer(
    tmp_path: Path,
) -> None:
    """They say which repository a project *is*. An override would file one repo's runs under
    another's project, silently, for as long as the flag or the variable was set."""
    assert {field.name for field in fields(Overrides)}.isdisjoint({"name", "repo", "trees_root"})
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    _project_file(home, repo, keys='build = "make"\n')
    environ = _env(
        home,
        AGL_NAME="other",
        AGL_REPO=str(tmp_path.resolve() / "elsewhere"),
        AGL_TREES_ROOT=str(tmp_path.resolve() / "other-trees"),
    )
    project = resolve_project(resolve_settings(Overrides(), environ), Overrides(), environ, repo)
    assert project.name == ProjectName(_NAME)
    assert project.repo == repo
    assert project.trees == TreesRoot(Path(f"{repo.parent}/.agl-trees/{_NAME}"))


def test_a_command_run_outside_a_registered_repository_gets_not_found_unchanged(
    tmp_path: Path,
) -> None:
    """`toml_file`'s refusal, propagated rather than reclassified: the message says `agl init`."""
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    settings = resolve_settings(Overrides(), _env(home))
    with pytest.raises(NotFoundError) as raised:
        resolve_project(settings, Overrides(), _env(home), repo)
    assert "agl init" in str(raised.value)


def test_a_directory_in_no_git_repository_gets_not_found_unchanged(tmp_path: Path) -> None:
    home = _home(tmp_path)
    outside = tmp_path.resolve() / "outside"
    outside.mkdir()
    settings = resolve_settings(Overrides(), _env(home))
    with pytest.raises(NotFoundError):
        resolve_project(settings, Overrides(), _env(home), outside)


# --- what the environment layer refuses ----------------------------------------------------------


@pytest.mark.parametrize(
    ("variable", "value", "expected"),
    [
        (_BUILD_TIMEOUT, "soon", "a number of seconds"),
        (_CLAUDE_ENABLED, "maybe", "true or false"),
        (_CLAUDE_ENABLED, "1", "true or false"),
        (_OPENAI_ENABLED, "yes", "true or false"),
    ],
)
def test_a_malformed_variable_is_refused_naming_it_its_value_and_what_was_expected(
    tmp_path: Path, variable: str, value: str, expected: str
) -> None:
    """Never a silent fall through: a typo that looks like a setting nobody set is the failure."""
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    _project_file(home, repo, keys='build = "make"\n')
    environ = _env(home, **{variable: value})
    with pytest.raises(InputError) as raised:
        _resolve_both(environ, repo)
    assert variable in str(raised.value)
    assert repr(value) in str(raised.value)
    assert expected in str(raised.value)


@pytest.mark.parametrize("spelling", ["true", "TRUE", "True", " false ", "FALSE"])
def test_the_two_accepted_boolean_spellings_are_case_insensitive_and_stripped(
    tmp_path: Path, spelling: str
) -> None:
    home = _home(tmp_path)
    settings = resolve_settings(Overrides(), _env(home, **{_CLAUDE_ENABLED: spelling}))
    assert settings.agents.claude.enabled == (spelling.strip().lower() == "true")


@pytest.mark.parametrize("variable", [_HOME, _CLAUDE_CLI_PATH, _BUILD, _BUILD_TIMEOUT])
def test_a_variable_set_to_the_empty_string_is_refused_rather_than_treated_as_unset(
    tmp_path: Path, variable: str
) -> None:
    """An empty variable reads as an operator clearing a setting, so it is never a skipped layer."""
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    _project_file(home, repo, keys='build = "make"\n')
    environ = {**_env(home), variable: "   "}
    with pytest.raises(InputError) as raised:
        _resolve_both(environ, repo)
    assert variable in str(raised.value)


def test_a_relative_cli_path_variable_is_refused_naming_the_variable(tmp_path: Path) -> None:
    """`schema` refuses a relative harness path too; only this refusal can name the variable."""
    home = _home(tmp_path)
    with pytest.raises(InputError) as raised:
        resolve_settings(Overrides(), _env(home, **{_OPENAI_CLI_PATH: "~/bin/harness"}))
    assert _OPENAI_CLI_PATH in str(raised.value)
    assert "~/bin/harness" in str(raised.value)


def test_a_build_timeout_out_of_range_is_still_the_schema_refusal(tmp_path: Path) -> None:
    """This layer's job is that a number arrives; one copy of the range rule lives in 9.1."""
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    _project_file(home, repo, keys='build = "make"\n')
    settings = resolve_settings(Overrides(), _env(home))
    with pytest.raises(InputError) as raised:
        resolve_project(settings, Overrides(), _env(home, **{_BUILD_TIMEOUT: "0"}), repo)
    assert "build_timeout" in str(raised.value)


# --- the pure core is pure, and the impure line is one line ---------------------------------------


def test_the_pure_core_ignores_the_process_environment_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real environment says one thing and the literal mapping another. The literal wins."""
    monkeypatch.setenv(_HOME, str(tmp_path.resolve() / "ambient"))
    monkeypatch.setenv(_CLAUDE_ENABLED, "false")
    home = _home(tmp_path)
    settings = resolve_settings(Overrides(), _env(home))
    assert settings.home == home
    assert settings.agents.claude.enabled


def test_resolve_reads_the_environment_once_and_downstream_sees_that_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The contract §1.10 asks for: after this returns, the answer is fixed for the invocation."""
    home = _home(tmp_path)
    repo = _repo(tmp_path)
    _project_file(home, repo, keys='build = "make"\n')
    monkeypatch.setenv(_HOME, str(home.path))
    monkeypatch.setenv(_BUILD, "as it was")

    resolved = resolve(Overrides())
    assert resolved.settings.home == home

    monkeypatch.setenv(_BUILD, "changed underneath")
    monkeypatch.setenv(_CLAUDE_ENABLED, "false")
    assert resolved.project(repo).build == "as it was"
    assert resolved.settings.agents.claude.enabled
