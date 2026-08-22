"""What the two file shapes hold, what they refuse, and how a repository finds its project.

**No real git repository is created anywhere below, and that is part of the claim.** `git_root`
walks the filesystem looking for a `.git` entry and asks nothing of git itself - no subprocess, no
adapter - so a marker file or an empty directory is the entire input it can see. A test that ran
`git init` would be testing git, cost a subprocess per case, and quietly hide the day somebody
replaces the walk with a `git rev-parse`.

Two more things the tests below are shaped by. Paths are compared *resolved*: `tmp_path` on macOS
sits under a symlinked temporary directory, so a test that compared it raw would pass on Linux and
fail here for a reason that has nothing to do with the code. And every refusal is asserted on its
class and on the file and key appearing in the message, because "it raised" is satisfied by a
refusal that leaves the operator hunting for which of their files was wrong.
"""

from dataclasses import fields
from pathlib import Path
from textwrap import dedent
from typing import Final

import pytest

from agl.config.schema import AgentSettings
from agl.config.toml_file import (
    FileAgent,
    FileProject,
    FileSettings,
    git_root,
    read_project,
    read_settings,
    resolve_project,
)
from agl.ports.errors import InputError, NotFoundError
from agl.ports.home_layout import AglHome, project_config
from agl.ports.ids import ProjectName
from agl.ports.tree_layout import TreesRoot

_SILENT: Final = FileAgent(enabled=None, cli_path=None)


def _write(path: Path, text: str) -> Path:
    """A file with its parents, dedented so the cases below can be written as they look on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip(), encoding="utf-8")
    return path


def _home(tmp_path: Path) -> AglHome:
    return AglHome(tmp_path.resolve() / "agl-home")


def _settings_file(home: AglHome, text: str) -> Path:
    return _write(home.path / "config.toml", text)


def _project_file(home: AglHome, name: str, text: str) -> Path:
    return _write(project_config(home, ProjectName(name)), text)


def _repo(tmp_path: Path, name: str, *, marker: str = "dir") -> Path:
    """A directory that looks like a working tree. `.git` is a directory or a file, as git does."""
    root = (tmp_path.resolve() / name).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if marker == "dir":
        (root / ".git").mkdir()
    else:
        (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w\n", encoding="utf-8")
    return root


# --- The global settings file -----------------------------------------------------------------


def test_the_global_file_round_trips_a_nested_section_per_connector(tmp_path: Path) -> None:
    """§1.10's repair: `[agent.<connector>]`, which the flat file could not express."""
    home = _home(tmp_path)
    _settings_file(
        home,
        """
        [agent.claude]
        enabled = true
        cli_path = "/opt/homebrew/bin/claude"

        [agent.openai]
        enabled = false
        cli_path = "/opt/homebrew/bin/harness"
        """,
    )
    assert read_settings(home) == FileSettings(
        claude=FileAgent(enabled=True, cli_path=Path("/opt/homebrew/bin/claude")),
        openai=FileAgent(enabled=False, cli_path=Path("/opt/homebrew/bin/harness")),
    )


def test_a_missing_global_file_is_silence_and_not_a_refusal(tmp_path: Path) -> None:
    """The ordinary case: an operator who configured nothing has a working installation."""
    assert read_settings(_home(tmp_path)) == FileSettings(claude=_SILENT, openai=_SILENT)


def test_a_section_the_file_omits_says_nothing_rather_than_saying_off(tmp_path: Path) -> None:
    """`None` is silence. Deciding what silence means is 9.2's, and it needs to see the silence."""
    home = _home(tmp_path)
    _settings_file(home, "[agent.claude]\nenabled = true\n")
    settings = read_settings(home)
    assert settings.claude == FileAgent(enabled=True, cli_path=None)
    assert settings.openai == _SILENT


def test_an_empty_section_and_an_absent_one_are_the_same_answer(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _settings_file(home, "[agent.claude]\n")
    assert read_settings(home) == read_settings(_home(tmp_path / "elsewhere"))


def test_the_file_names_its_sections_exactly_as_the_settings_object_names_its_fields() -> None:
    """The one mapping that must not drift: `[agent.<x>]` fills `AgentSettings.<x>`.

    The table is `agent` and the field is `agents` on purpose (§1.10's spelling against 9.1's), and
    that is the only difference this module is allowed to introduce. A third provider adds a field
    to `AgentSettings` and must add a section here in the same commit; this is what notices.
    """
    assert tuple(field.name for field in fields(FileSettings)) == ("claude", "openai")
    assert tuple(field.name for field in fields(FileSettings)) == tuple(
        field.name for field in fields(AgentSettings)
    )


def test_agl_home_is_refused_as_a_key_in_the_file_that_lives_inside_it(tmp_path: Path) -> None:
    """It could only be read once home was resolved - hence three precedence layers, not four."""
    home = _home(tmp_path)
    path = _settings_file(home, 'home = "/somewhere/else"\n')
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert str(path) in str(raised.value)
    assert "AGL_HOME" in str(raised.value)


# --- Strictness -------------------------------------------------------------------------------


def test_an_unknown_top_level_key_is_refused_and_the_expected_keys_are_named(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    path = _settings_file(home, "concurrency = 4\n")
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert str(path) in str(raised.value)
    assert "concurrency" in str(raised.value)
    assert "agent" in str(raised.value)


def test_an_unknown_connector_section_is_refused_rather_than_carried_along(tmp_path: Path) -> None:
    """`Provider` is a closed set, so `[agent.anthropic]` is not data to pass on - it is a typo."""
    home = _home(tmp_path)
    _settings_file(home, "[agent.anthropic]\nenabled = true\n")
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert "agent.anthropic" in str(raised.value)
    assert "agent.claude" in str(raised.value)


def test_an_unknown_key_inside_a_section_is_refused(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _settings_file(home, "[agent.claude]\nenabld = true\n")
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert "agent.claude.enabld" in str(raised.value)
    assert "agent.claude.enabled" in str(raised.value)


def test_a_value_of_the_wrong_type_is_refused_and_never_coerced(tmp_path: Path) -> None:
    home = _home(tmp_path)
    path = _settings_file(home, '[agent.claude]\nenabled = "yes"\n')
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert str(path) in str(raised.value)
    assert "agent.claude.enabled" in str(raised.value)


def test_a_section_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _settings_file(home, "agent = 3\n")
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert "agent" in str(raised.value)


def test_malformed_toml_is_an_input_error_naming_the_file(tmp_path: Path) -> None:
    home = _home(tmp_path)
    path = _settings_file(home, "[agent.claude\nenabled = true\n")
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert str(path) in str(raised.value)


def test_a_file_that_cannot_be_read_is_an_input_error_and_not_a_missing_file(
    tmp_path: Path,
) -> None:
    """A directory where the file should be. Chosen over `chmod 000`, which does nothing as root.

    The distinction being asserted is the one `_document` makes: absence answers `None` and every
    other `OSError` refuses, because "there is no such file" is ordinary and "it is a directory" is
    a broken installation.
    """
    home = _home(tmp_path)
    (home.path / "config.toml").mkdir(parents=True)
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert str(home.path / "config.toml") in str(raised.value)


def test_a_relative_path_is_refused_wherever_a_file_holds_one(tmp_path: Path) -> None:
    """The rule the 9.1 types state in their own constructors, said here with the file and key."""
    home = _home(tmp_path)
    path = _settings_file(home, '[agent.claude]\ncli_path = "bin/claude"\n')
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert str(path) in str(raised.value)
    assert "agent.claude.cli_path" in str(raised.value)


# --- The project file -------------------------------------------------------------------------


def test_the_project_file_round_trips_the_five_keys_the_plan_writes(tmp_path: Path) -> None:
    """§3.10 prints this file in full. `trees_root` becomes `trees_root`; 9.1's field is `trees`."""
    home = _home(tmp_path)
    _project_file(
        home,
        "myapp",
        """
        name = "myapp"
        repo = "/Users/jan/dev/myapp"
        trees_root = "/Users/jan/dev/.agl-trees/myapp"
        build = "./gradlew build"
        build_timeout = 600
        """,
    )
    assert read_project(home, ProjectName("myapp")) == FileProject(
        name=ProjectName("myapp"),
        repo=Path("/Users/jan/dev/myapp"),
        trees_root=TreesRoot(Path("/Users/jan/dev/.agl-trees/myapp")),
        build="./gradlew build",
        build_timeout=600.0,
    )


def test_an_integer_timeout_arrives_as_the_float_the_settings_object_declares(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _project_file(home, "myapp", "build_timeout = 600\n")
    timeout = read_project(home, ProjectName("myapp")).build_timeout
    assert timeout == 600.0
    assert isinstance(timeout, float)


def test_a_boolean_timeout_is_refused_although_python_calls_it_an_integer(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _project_file(home, "myapp", "build_timeout = true\n")
    with pytest.raises(InputError) as raised:
        read_project(home, ProjectName("myapp"))
    assert "build_timeout" in str(raised.value)


def test_the_typo_that_would_silently_keep_a_default_is_refused(tmp_path: Path) -> None:
    """`build_timout` is the failure a configuration file exists to prevent."""
    home = _home(tmp_path)
    path = _project_file(home, "myapp", "build_timout = 600\n")
    with pytest.raises(InputError) as raised:
        read_project(home, ProjectName("myapp"))
    assert str(path) in str(raised.value)
    assert "build_timout" in str(raised.value)
    assert "build_timeout" in str(raised.value)


def test_the_name_comes_from_the_filename_when_the_key_is_absent(tmp_path: Path) -> None:
    """A project's identity on disk is its filename, and this module alone ever sees that."""
    home = _home(tmp_path)
    _project_file(home, "myapp", 'repo = "/dev/myapp"\n')
    assert read_project(home, ProjectName("myapp")).name == ProjectName("myapp")


def test_a_name_key_that_disagrees_with_the_filename_is_refused(tmp_path: Path) -> None:
    """Two spellings of one fact, reconciled where both are visible rather than downstream."""
    home = _home(tmp_path)
    path = _project_file(home, "myapp", 'name = "other"\n')
    with pytest.raises(InputError) as raised:
        read_project(home, ProjectName("myapp"))
    assert str(path) in str(raised.value)
    assert "other" in str(raised.value)


def test_a_relative_repo_is_refused_with_the_file_and_the_key_named(tmp_path: Path) -> None:
    home = _home(tmp_path)
    path = _project_file(home, "myapp", 'repo = "../myapp"\n')
    with pytest.raises(InputError) as raised:
        read_project(home, ProjectName("myapp"))
    assert str(path) in str(raised.value)
    assert "repo" in str(raised.value)


def test_a_relative_trees_root_is_refused_before_it_reaches_the_wrapper(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _project_file(home, "myapp", 'trees_root = ".agl-trees/myapp"\n')
    with pytest.raises(InputError) as raised:
        read_project(home, ProjectName("myapp"))
    assert "trees_root" in str(raised.value)


def test_a_project_that_was_never_registered_is_not_found(tmp_path: Path) -> None:
    """A name is not a guess: absence here is a refusal, unlike the global settings file."""
    with pytest.raises(NotFoundError) as raised:
        read_project(_home(tmp_path), ProjectName("nobody"))
    assert "agl init" in str(raised.value)


# --- Walking up to the git root -----------------------------------------------------------------


def test_the_walk_finds_a_git_directory_from_a_nested_working_directory(tmp_path: Path) -> None:
    root = _repo(tmp_path, "myapp")
    deep = root / "src" / "main" / "kotlin"
    deep.mkdir(parents=True)
    assert git_root(deep) == root


def test_the_walk_finds_a_git_file_as_well_as_a_git_directory(tmp_path: Path) -> None:
    """A linked worktree and a submodule write a `gitdir:` file, so existence is the test."""
    root = _repo(tmp_path, "worktree", marker="file")
    assert (root / ".git").is_file()
    assert git_root(root) == root


def test_the_walk_answers_with_a_resolved_path(tmp_path: Path) -> None:
    root = _repo(tmp_path, "myapp")
    link = tmp_path.resolve() / "link"
    link.symlink_to(root, target_is_directory=True)
    assert git_root(link / "src") == root


def test_a_directory_in_no_repository_at_all_is_not_found(tmp_path: Path) -> None:
    """One of the two absences, and it gets its own message: there is nothing here to register."""
    outside = tmp_path.resolve() / "not-a-repo"
    outside.mkdir()
    with pytest.raises(NotFoundError) as raised:
        git_root(outside)
    assert "not inside a git repository" in str(raised.value)


# --- Resolving which project a directory is in --------------------------------------------------


def _register(home: AglHome, name: str, repo: Path) -> None:
    _project_file(home, name, f'repo = "{repo}"\nbuild = "make"\nbuild_timeout = 60\n')


def test_only_the_project_whose_repo_is_this_git_root_matches(tmp_path: Path) -> None:
    """What makes labels per-project: repo A's run is not repo B's, because this returns B."""
    home = _home(tmp_path)
    first, second = _repo(tmp_path, "alpha"), _repo(tmp_path, "beta")
    _register(home, "alpha", first)
    _register(home, "beta", second)
    assert resolve_project(home, second / "src").name == ProjectName("beta")
    assert resolve_project(home, first).name == ProjectName("alpha")


def test_a_repository_reached_through_a_symlink_is_the_same_project(tmp_path: Path) -> None:
    """Both sides are compared resolved, so one repository is one project by whatever route."""
    home = _home(tmp_path)
    root = _repo(tmp_path, "myapp")
    (root / "src").mkdir()
    link = tmp_path.resolve() / "by-another-name"
    link.symlink_to(root, target_is_directory=True)
    _register(home, "myapp", root)
    assert resolve_project(home, link / "src").name == ProjectName("myapp")


def test_a_registered_repo_spelled_through_a_symlink_still_matches(tmp_path: Path) -> None:
    """The other direction: the *file* names the link, the caller stands in the real directory."""
    home = _home(tmp_path)
    root = _repo(tmp_path, "myapp")
    link = tmp_path.resolve() / "by-another-name"
    link.symlink_to(root, target_is_directory=True)
    _register(home, "myapp", link)
    assert resolve_project(home, root).name == ProjectName("myapp")


def test_a_git_repository_no_project_file_names_is_not_found(tmp_path: Path) -> None:
    """The second absence, with its own message: a repository, simply not a registered one."""
    home = _home(tmp_path)
    _register(home, "alpha", _repo(tmp_path, "alpha"))
    unregistered = _repo(tmp_path, "beta")
    with pytest.raises(NotFoundError) as raised:
        resolve_project(home, unregistered)
    assert "no project is registered" in str(raised.value)
    assert str(unregistered) in str(raised.value)
    assert "agl init" in str(raised.value)


def test_an_installation_with_no_projects_directory_resolves_to_not_found(tmp_path: Path) -> None:
    """Nobody has run `agl init` yet. An empty listing, not a refusal about a missing directory."""
    with pytest.raises(NotFoundError):
        resolve_project(_home(tmp_path), _repo(tmp_path, "myapp"))


def test_resolution_outside_any_repository_fails_on_the_walk_and_says_so(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _register(home, "alpha", _repo(tmp_path, "alpha"))
    outside = tmp_path.resolve() / "elsewhere"
    outside.mkdir()
    with pytest.raises(NotFoundError) as raised:
        resolve_project(home, outside)
    assert "not inside a git repository" in str(raised.value)


def test_a_malformed_project_file_refuses_the_scan_rather_than_being_skipped(
    tmp_path: Path,
) -> None:
    """A skipped file is a project that silently stops existing, and `agl init` would be a lie.

    `aaa.toml` sorts before `myapp.toml`, so the scan meets it first. The refusal is what the
    operator needs: the file they have to fix, rather than a `NotFoundError` about a project they
    registered last week.
    """
    home = _home(tmp_path)
    root = _repo(tmp_path, "myapp")
    _register(home, "myapp", root)
    broken = _project_file(home, "aaa", "repo = \n")
    with pytest.raises(InputError) as raised:
        resolve_project(home, root)
    assert str(broken) in str(raised.value)


def test_a_non_toml_entry_beside_the_project_files_is_not_parsed(tmp_path: Path) -> None:
    """The listing filters on the suffix `home_layout` composes, so a stray file changes nothing."""
    home = _home(tmp_path)
    root = _repo(tmp_path, "myapp")
    _register(home, "myapp", root)
    _write(project_config(home, ProjectName("myapp")).parent / "notes.txt", "not toml at all [\n")
    assert resolve_project(home, root).name == ProjectName("myapp")


def test_the_run_directory_of_a_project_is_not_mistaken_for_a_project_file(tmp_path: Path) -> None:
    """`projects/myapp/` sits beside `projects/myapp.toml`; only one of them is a settings file."""
    home = _home(tmp_path)
    root = _repo(tmp_path, "myapp")
    _register(home, "myapp", root)
    (project_config(home, ProjectName("myapp")).parent / "myapp" / "runs").mkdir(parents=True)
    assert resolve_project(home, root).repo == root
