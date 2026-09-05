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

import ast
import tomllib
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from textwrap import dedent
from typing import Final
import pytest
from packaging.requirements import Requirement
from agl.config import distribution
from agl.config.schema import AgentSettings
from agl.config.sources import DEFAULT_BUILD_TIMEOUT
from agl.config.toml_file import (
    FileAgent,
    FileProject,
    FileSettings,
    check_trees_root,
    check_unregistered,
    check_workspace_pin,
    git_root,
    make_workflow,
    make_workspace,
    read_document,
    read_project,
    read_settings,
    resolve_project,
    write_project,
)
from agl.ports.errors import ConflictError, InputError, NotFoundError, exit_code_for
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
    workspace_site_packages,
)
from agl.ports.ids import ProjectName, WorkflowName
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

def _beside(tmp_path: Path) -> tuple[Path, TreesRoot]:
    """A repository and a trees root laid out the way `agl init` lays them out: siblings.

    `<parent>/myapp` and `<parent>/.agl-trees/myapp`, which is the shape `agl init` picks. The pair
    is a helper because every write below needs one that survives `check_trees_root` - the reader
    refuses a nested trees root, so a writer test that used `tmp_path` for both would fail on the
    way back in and would be measuring the reader.
    """
    dev = tmp_path.resolve() / "dev"
    return dev / "myapp", TreesRoot(dev / ".agl-trees" / "myapp")

# --- The global settings file -----------------------------------------------------------------

def test_the_global_file_round_trips_a_nested_section_per_connector(tmp_path: Path) -> None:
    """Per-connector nesting: `[agent.<connector>]`, which a flat file could not express."""
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
    """`None` is silence. Deciding what it means is `sources.py`'s job, and it needs to see it."""
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

    The table is `agent` and the field is `agents` on purpose - the file's own spelling against the
    settings object's - and that is the only difference this module is allowed to introduce. A
    third provider adds a field to `AgentSettings` and must add a section here in the same commit;
    this is what notices.
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

    The distinction being asserted is the one `read_document` makes: absence answers `None` and
    every other `OSError` refuses, because "there is no such file" is ordinary and "it is a
    directory" is a broken installation.
    """
    home = _home(tmp_path)
    (home.path / "config.toml").mkdir(parents=True)
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert str(home.path / "config.toml") in str(raised.value)

def test_a_relative_path_is_refused_wherever_a_file_holds_one(tmp_path: Path) -> None:
    """The rule the `schema.py` types state in their own constructors, said here with the file
    and key."""
    home = _home(tmp_path)
    path = _settings_file(home, '[agent.claude]\ncli_path = "bin/claude"\n')
    with pytest.raises(InputError) as raised:
        read_settings(home)
    assert str(path) in str(raised.value)
    assert "agent.claude.cli_path" in str(raised.value)

# --- The project file -------------------------------------------------------------------------

def test_the_project_file_round_trips_the_five_keys_init_writes(tmp_path: Path) -> None:
    """All five keys. `trees_root` keeps its name here; `schema.Project` calls it `trees`."""
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

# --- The writer, which is only interesting as the reader's inverse ------------------------------
#
# `write_project` sits beside `read_project` because this is "the only module that knows TOML",
# and the whole of what that buys is one property: a file `agl init` writes is a file `agl run`
# reads. So the tests below assert the round trip rather than the bytes - a test comparing the
# rendered text against a literal would pass while agreeing with nothing, and would have to be
# edited by anybody who changed the spacing.

def test_a_file_the_writer_writes_is_one_the_reader_accepts(tmp_path: Path) -> None:
    """The round trip, which is the writer's entire contract: the file written and read back.

    All five keys, `build_timeout` included, and the expected value is spelled as the constant
    rather than as `600.0`: the number has one home in `sources.DEFAULT_BUILD_TIMEOUT`, `api.init`
    reads it rather than restating it, and a literal here would be the second copy that arrangement
    exists to prevent - one that goes on passing on the day the default moves and the writer follows
    it.
    """
    home = _home(tmp_path)
    repo = tmp_path.resolve() / "dev" / "myapp"
    trees = TreesRoot(tmp_path.resolve() / "dev" / ".agl-trees" / "myapp")

    written = write_project(
        home, ProjectName("myapp"), repo, trees, "./gradlew build", DEFAULT_BUILD_TIMEOUT
    )

    assert written == project_config(home, ProjectName("myapp"))
    assert read_project(home, ProjectName("myapp")) == FileProject(
        name=ProjectName("myapp"),
        repo=repo,
        trees_root=trees,
        build="./gradlew build",
        build_timeout=DEFAULT_BUILD_TIMEOUT,
    )

def test_a_build_command_holding_the_format_s_own_punctuation_round_trips(tmp_path: Path) -> None:
    """A build command is a shell line, so a quote and a backslash in it are ordinary.

    This is the assertion the escape table exists for, and it is why the value is written as a TOML
    *basic* string: a literal string admits no escapes at all, so `don't` would end the value early
    and produce a file `tomllib` refuses - a file `agl init` wrote and no later command could read.
    """
    home = _home(tmp_path)
    build = 'sh -c "make test" && echo don\'t \\ stop'

    write_project(home, ProjectName("myapp"), *_beside(tmp_path), build, DEFAULT_BUILD_TIMEOUT)

    assert read_project(home, ProjectName("myapp")).build == build

def test_the_writer_never_writes_over_a_project_file_that_is_already_there(tmp_path: Path) -> None:
    """`agl init` runs once per repo, and running it twice must not take a file away.

    `ConflictError` - exit 4, the class `api.run` answers a taken label with - and the file is
    asserted untouched afterwards, which is the assertion with teeth: a writer that refused *after*
    truncating would raise the same class and have destroyed the settings anyway.
    """
    home = _home(tmp_path)
    write_project(home, ProjectName("myapp"), *_beside(tmp_path), "make", DEFAULT_BUILD_TIMEOUT)

    with pytest.raises(ConflictError) as raised:
        write_project(
            home, ProjectName("myapp"), *_beside(tmp_path), "ninja", DEFAULT_BUILD_TIMEOUT
        )

    assert "myapp" in str(raised.value)
    assert read_project(home, ProjectName("myapp")).build == "make"

def test_the_free_refusal_and_the_write_refusal_are_one_message(tmp_path: Path) -> None:
    """`check_unregistered` answers with the path a new project's file goes to, or refuses.

    Two call sites and one sentence: `api.init` asks this before it puts a question to a person, so
    that a build command is not typed into a prompt and thrown away, and `write_project` asks the
    operating system the same thing again at the moment it matters. The messages are compared
    because two refusals about one fact that drifted apart would be two accounts of what happened.
    """
    home = _home(tmp_path)
    name = ProjectName("myapp")

    assert check_unregistered(home, name) == project_config(home, name)

    write_project(home, name, *_beside(tmp_path), "make", DEFAULT_BUILD_TIMEOUT)
    with pytest.raises(ConflictError) as free:
        check_unregistered(home, name)
    with pytest.raises(ConflictError) as written:
        write_project(home, name, *_beside(tmp_path), "make", DEFAULT_BUILD_TIMEOUT)

    assert str(free.value) == str(written.value)

def test_the_writer_makes_the_projects_directory_when_there_is_none(tmp_path: Path) -> None:
    """`agl init` is the first thing an installation runs, so `projects/` does not exist yet.

    `_project_files` already treats a missing `projects/` as an empty list rather than a refusal,
    which is the same fact read from the other side: an installation that has never registered
    anything is a working installation, and the first `init` is what gives it a directory.
    """
    home = _home(tmp_path)
    assert not home.path.exists()

    write_project(home, ProjectName("myapp"), *_beside(tmp_path), "make", DEFAULT_BUILD_TIMEOUT)

    assert read_project(home, ProjectName("myapp")).build == "make"

# --- The workspace, which is created and never written over --------------------------------------
#
# `make_workspace` sits beside `write_project` for that function's reason: this is "the only module
# that knows TOML", and the workspace's own project file is one AGL writes and later reads back.
# What differs is the contract, and it is the opposite one. `write_project` refuses a second call,
# because a repository registered twice is two answers to one question; this is called
# unconditionally by whatever is about to put something in the workspace, so a second call has to
# cost nothing rather than refuse - and "cost nothing" is asserted over the bytes below, because a
# function that rewrote the file it found would look identical from the paths alone.

def _tree(home: AglHome) -> list[str]:
    """Every path under `home`, relative and posix-spelled so one listing reads alike anywhere."""
    return sorted(path.relative_to(home.path).as_posix() for path in home.path.rglob("*"))

def _contents(home: AglHome) -> dict[str, bytes | None]:
    """Every path under `home` with the bytes it holds, `None` for a directory.

    The pair is what makes "changed nothing" one comparison: a key arriving is a creation, a key
    going is a deletion, and a value moving is the overwrite this function promises never to do.
    """
    return {
        path.relative_to(home.path).as_posix(): None if path.is_dir() else path.read_bytes()
        for path in home.path.rglob("*")
    }

def _members(home: AglHome) -> list[str]:
    """The globs the workspace's own project file declares as the members of its uv workspace."""
    document = tomllib.loads(workspace_pyproject(home).read_text(encoding="utf-8"))
    return list(document["tool"]["uv"]["workspace"]["members"])

def _pin(home: AglHome) -> str | None:
    """The requirement the workspace's project file pins AGL to, `None` where it names none.

    A key that is absent and a key holding something that is not a string answer alike, because
    what a reader of this wants to know is whether there is a requirement here to compare against,
    and neither of those two is one.
    """
    document = tomllib.loads(workspace_pyproject(home).read_text(encoding="utf-8"))
    requires = document.get("tool", {}).get("agl", {}).get("requires")
    return requires if isinstance(requires, str) else None

def test_making_a_workspace_creates_two_directories_and_a_project_file_and_nothing_else(
    tmp_path: Path,
) -> None:
    """The whole of what it makes, listed rather than sampled - from an AGL_HOME that was not there.

    A sampled assertion - "the workflows directory exists" - passes just as happily against a
    function that also wrote a `config.toml` nothing reads, or the `projects/` directory the writer
    above makes for itself on the first `agl init`. The listing is what says the three are all
    of it.
    """
    home = _home(tmp_path)
    assert not home.path.exists()

    make_workspace(home)

    assert _tree(home) == ["workspace", "workspace/pyproject.toml", "workspace/workflows"]
    assert workflows_dir(home).is_dir()
    assert workspace_pyproject(home).is_file()

def test_a_created_workspace_leaves_the_settings_file_and_the_projects_registry_absent(
    tmp_path: Path,
) -> None:
    """Neither is this function's to make, and the reader still answers with both of them missing.

    `config.toml` is the operator's own file and nothing in `src/` writes one; `projects/` belongs
    to the writer above, which makes it on the first `agl init`. Making either here would be
    reconciling a home rather than creating a workspace, and the read below is why neither needs
    making: a home with no settings file resolves to the same silence an empty one does.
    """
    home = _home(tmp_path)

    make_workspace(home)

    assert not settings_file(home).exists()
    assert not projects_dir(home).exists()
    assert read_settings(home) == FileSettings(claude=_SILENT, openai=_SILENT)

def test_the_workspace_project_file_the_writer_writes_is_one_the_reader_accepts(
    tmp_path: Path,
) -> None:
    """The round trip the project-file writer above is held to, asked of this file for its reason.

    `read_document` is the reader every TOML file in this tree goes through, so a workspace file
    this module wrote and could not parse would be one no later command could read either.
    """
    home = _home(tmp_path)

    make_workspace(home)

    assert read_document(workspace_pyproject(home)) is not None
    assert _members(home) == [f"{workflows_dir(home).name}/*"]

def test_the_members_glob_takes_in_every_workflow_directory_and_never_the_workspace_venv(
    tmp_path: Path,
) -> None:
    """`workflows/*` and not `*`, measured against a workspace holding one of each.

    uv is what resolves this glob and nothing in this repository runs uv, so what is measured is
    `Path.glob` over the two directories a workspace really holds side by side - the workflows, and
    the venv `workspace_site_packages` composes. The wrong glob is run as well as the right one,
    because "the declaration matches the workflow" is worth little without "the alternative matches
    the venv" beside it: that is the mistake being avoided, and an assertion nobody has watched fire
    proves the declaration is safe from nothing.
    """
    home = _home(tmp_path)
    make_workspace(home)
    (workflows_dir(home) / "triage").mkdir()
    workspace_site_packages(home, "python3.14").mkdir(parents=True)
    root = workspace_dir(home)

    assert sorted(path.name for glob in _members(home) for path in root.glob(glob)) == ["triage"]
    assert ".venv" in sorted(path.name for path in root.glob("*"))

def test_the_workspace_project_file_pins_the_running_agl_to_one_exact_version(
    tmp_path: Path,
) -> None:
    """The pin is a requirement a resolver could read, and it names this AGL and this version.

    **`packaging` parses it rather than a regex written here.** PEP 440's grammar is not something
    a test should carry a second opinion of, and the parser costs nothing to reach: `pytest`
    requires `packaging>=22` unconditionally, so it is installed wherever this suite runs and
    reaching for it declares no dependency the suite did not already have.

    Three claims, kept apart because they fail for different reasons. The name is the
    **distribution**'s and not the import package's, which is the collision
    `config/distribution.py` exists for and the one a pin assembled by hand would get wrong. The
    operator is `==` and not a range, because what this file records is which AGL made the
    workspace rather than which ones could run in it. And the version it admits is the one running
    now, which is what makes it a pin of anything at all.
    """
    home = _home(tmp_path)

    make_workspace(home)

    pinned = _pin(home)
    assert pinned is not None, (
        f"{workspace_pyproject(home)} names no requirement, and this tree is installed - "
        f"`installed_version()` answers {distribution.installed_version()!r}. A pin is left out "
        f"only where there is no metadata to read at all."
    )
    requirement = Requirement(pinned)
    assert requirement.name == distribution.DISTRIBUTION, (
        f"the workspace is pinned to {requirement.name!r} and AGL's distribution is "
        f"{distribution.DISTRIBUTION!r}. `importlib.metadata` and every resolver key on the "
        f"distribution name, which is not the `agl` an import statement says."
    )
    assert [clause.operator for clause in requirement.specifier] == ["=="], (
        f"the pin is {pinned!r}, whose specifier is not a single `==`. This file records the one "
        f"AGL that made the workspace, so a range would be a claim about which versions may run "
        f"here - which is not a question this file is answering."
    )
    assert requirement.specifier.contains(distribution.installed_version()), (
        f"the pin is {pinned!r} and the AGL that wrote it is "
        f"{distribution.installed_version()!r}. A pin that excludes the version that wrote it is "
        f"a mismatch AGL manufactured for itself."
    )

def test_the_workspace_root_declares_no_project_table_and_so_declares_no_workflow(
    tmp_path: Path,
) -> None:
    """Where the pin does *not* go, which is the half of the decision a later edit could undo.

    `[project] dependencies` is the obvious home for a requirement string and is the wrong one
    twice over. It would make the workspace root a package uv has to build rather than the virtual
    root it is - uv treats a `[tool.uv.workspace]` file with no `[project]` beside it as a root
    that is only a container - and it would give the file the one table
    `tests/test_measurable_targets.py`'s `_declarations` reads, so a root that grew a `[project]`
    would be one `entry-points` line away from being a workflow declaration AGL wrote itself.

    Asserted over the whole top level rather than on `project` alone: `[build-system]` would be
    the same mistake under another name, and so would anything else a later stage adds without
    asking what it makes the file into.
    """
    home = _home(tmp_path)

    make_workspace(home)

    document = tomllib.loads(workspace_pyproject(home).read_text(encoding="utf-8"))
    assert sorted(document) == ["tool"], (
        f"{workspace_pyproject(home)} holds the top-level tables {sorted(document)}. `tool` is "
        f"the whole of what AGL writes there - the uv members glob and AGL's own pin - and a "
        f"`project` table in particular turns this file from a virtual workspace root into a "
        f"package, one line short of declaring a workflow."
    )

def test_a_workspace_made_with_no_metadata_to_read_carries_no_pin_at_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bare checkout writes no pin, because the only thing it could write is not a version.

    `installed_version()` answers `UNINSTALLED` where there is no `.dist-info` to read, and that
    string opens with a letter and holds spaces, neither of which PEP 440 admits - so
    `agents-gl==unknown (agents-gl is not installed)` is a requirement no resolver can parse. The
    three available answers were a pin nothing can read, a placeholder pin that states a
    requirement nobody measured, and no key at all. This is the third, and it costs nothing new to
    answer for: a workspace whose root file names no pin is the shape every hand-made workspace
    already has.

    The arm is reached the way `tests/config/test_distribution.py` reaches it, by pointing
    `DISTRIBUTION` at the import package name for the duration of one test - so the lookup is the
    real one and the exception is the real `PackageNotFoundError` it raises, and nothing is
    stubbed. The sentinel is then asserted absent from the file's own text and not merely from a
    parsed key, because what must never be written is those characters.
    """
    monkeypatch.setattr(distribution, "DISTRIBUTION", distribution.__name__.partition(".")[0])
    home = _home(tmp_path)

    make_workspace(home)

    written = workspace_pyproject(home).read_text(encoding="utf-8")
    assert _pin(home) is None, (
        f"a workspace made with no metadata to read pinned {_pin(home)!r}. The only version "
        f"available on that path is {distribution.UNINSTALLED!r}, which is a sentence rather than "
        f"a version - so there is nothing here to pin and the key is left out."
    )
    assert distribution.UNINSTALLED not in written, (
        f"{workspace_pyproject(home)} holds {distribution.UNINSTALLED!r}. That string is what "
        f"`config/distribution.py` answers when nothing is installed, and putting it in this file "
        f"writes a requirement no resolver can parse - whichever key it lands under."
    )

def test_a_second_call_never_rewrites_the_pin_an_existing_workspace_already_carries(
    tmp_path: Path,
) -> None:
    """Creation is not reconciliation, narrowed onto the one key somebody will want to reconcile.

    The byte comparison below already covers the whole file, and this says the same thing about
    the key that is *supposed* to read as stale: an operator whose workspace was made by an older
    AGL holds a pin naming that older one, and a creation that refreshed it would erase the very
    disagreement a version-mismatch refusal exists to report. So the pin is edited to a version
    this tree is not, and it has to survive a second call untouched.
    """
    home = _home(tmp_path)
    make_workspace(home)
    written = workspace_pyproject(home)
    pinned = _pin(home)
    assert pinned is not None, "the arrangement needs a pin to make stale, and there is none"
    stale = f"{distribution.DISTRIBUTION}==0.0.0"
    written.write_text(written.read_text(encoding="utf-8").replace(pinned, stale), encoding="utf-8")

    make_workspace(home)

    assert _pin(home) == stale, (
        f"the workspace was pinned to {stale!r} and a second call left it pinned to {_pin(home)!r}."
        f" Creating a workspace never writes over one that is there - and this key least of all, "
        f"since a pin AGL keeps current is a pin that can never disagree with the AGL reading it."
    )

def test_a_second_call_over_a_finished_workspace_changes_no_file_and_makes_no_new_one(
    tmp_path: Path,
) -> None:
    """Idempotent, and asserted with teeth: the project file is edited first and must survive.

    A creation that refreshed the file would be indistinguishable from one that skipped it if the
    comparison were over the paths, which is why it is over the bytes. What that protects is
    anything the file comes to hold: this is called on every invocation that writes into the
    workspace, so a refresh would rewrite somebody else's file on every one of them.
    """
    home = _home(tmp_path)
    make_workspace(home)
    edited = workspace_pyproject(home)
    edited.write_text(
        edited.read_text(encoding="utf-8") + "# an operator's own line\n", encoding="utf-8"
    )
    before = _contents(home)

    make_workspace(home)

    assert _contents(home) == before
    assert "an operator's own line" in edited.read_text(encoding="utf-8")

def test_a_hand_made_workspace_missing_its_project_file_gains_one_and_keeps_its_workflows(
    tmp_path: Path,
) -> None:
    """Create-only is asked of each of the three, so a workspace made by hand is completed.

    That workspace is a real shape and not a hypothetical: `config/registry.py` reads a workflow out
    of a directory the operator wrote, and that reading wants nothing at the workspace root - so
    `workflows/<name>/` with no project file above it is a workspace AGL already runs. Creation that
    was all-or-nothing would leave one of those without a project file forever, and would leave a
    first call interrupted between the two creations unrepairable. What create-only forbids is
    overwriting, which the test above is about, and nothing here overwrites anything.
    """
    home = _home(tmp_path)
    written = workflows_dir(home) / "triage"
    written.mkdir(parents=True)
    declaration = '[project]\nname = "triage"\n'
    (written / "pyproject.toml").write_text(declaration, encoding="utf-8")

    make_workspace(home)

    assert workspace_pyproject(home).is_file()
    assert (written / "pyproject.toml").read_text(encoding="utf-8") == declaration

def test_a_workspace_path_that_is_a_file_is_refused_instead_of_passing_for_a_workspace(
    tmp_path: Path,
) -> None:
    """The failure that is not "already there": something is in the way and it is not a directory.

    `mkdir(exist_ok=True)` answers a directory that is already there and a *file* in its place with
    the same `FileExistsError` family, and the two mean opposite things - so the silence is scoped
    to the project file's own write, and a workspace that cannot be made says so rather than
    returning as though it had been made.
    """
    home = _home(tmp_path)
    home.path.mkdir(parents=True)
    workspace_dir(home).write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(InputError) as raised:
        make_workspace(home)

    assert str(workspace_dir(home)) in str(raised.value)

# --- The pin read back, which is the whole of what writing it bought ------------------------------
#
# `make_workspace` writes the pin once and never refreshes it, so this reader is the only thing
# that ever acts on a disagreement, and the states it has to tell apart are three rather than two.
# A workspace an installed AGL made records a requirement; a workspace made in a bare checkout
# records none, there being no version to write; and a workspace made by hand has no root file at
# all. Only the first can disagree with anything, so the rule is one sentence - refuse where both
# sides are there and differ - and the two silences are what keep a development tree runnable.
#
# The comparison is textual and the tests below say so on purpose. `_version_pin` is both the
# writer and the comparand, which is what makes a round trip provable without a requirement parser
# in `src/`; what it gives up is a hand-edited pin that means this version in another spelling.
#
# Only the round trip goes through `make_workspace`. Every other arrangement writes the root file
# itself, because the states worth testing are ones the writer cannot produce: a stale pin, an
# absent key, and a requirement that is not a string.

def _recording(home: AglHome, requirement: str | None) -> None:
    """A workspace whose root file records `requirement`, or records none where that is `None`."""
    workflows_dir(home).mkdir(parents=True)
    recorded = "" if requirement is None else f'\n[tool.agl]\nrequires = "{requirement}"\n'
    workspace_pyproject(home).write_text(
        f'[tool.uv.workspace]\nmembers = ["workflows/*"]\n{recorded}', encoding="utf-8"
    )

def test_a_workspace_this_agl_made_is_one_this_agl_runs_without_a_word(tmp_path: Path) -> None:
    """The round trip, and the reason a development tree is not refused on every run.

    This is the one case here that goes through the writer, and it is the load-bearing one: the pin
    is compared as text, so writer and reader agreeing is a fact about two spellings meeting rather
    than about a version number. It fails the moment either side changes how it composes the string
    - a `~=`, a normalised name, a space around the operator - and it fails on the tree the change
    was made in, which is the whole point of asserting it here rather than reasoning about it.
    """
    home = _home(tmp_path)
    make_workspace(home)

    check_workspace_pin(home)

    assert _pin(home) is not None, (
        f"this tree records no pin, so the silence above proves nothing - `installed_version()` "
        f"answers {distribution.installed_version()!r} and a pin is left out only where there is "
        f"no metadata at all."
    )

def test_a_workspace_another_agl_made_refuses_and_names_the_line_that_ends_it(
    tmp_path: Path,
) -> None:
    """Exit 4, both versions, the file, and the exact text that makes the two agree.

    The message is asserted on the line it tells the operator to write and not merely on the words
    "version" or "mismatch", because naming the fix is the whole of what this refusal is for: the
    pin is never refreshed by anything AGL runs, so an operator who cannot find the key is stuck
    with a command that refuses and no way through it. `_quoted` is what the fix line goes through
    in `src/`, and a double-quoted TOML basic string is what is asserted here.
    """
    home = _home(tmp_path)
    _recording(home, f"{distribution.DISTRIBUTION}==0.0.0")
    running = f"{distribution.DISTRIBUTION}=={distribution.installed_version()}"

    with pytest.raises(ConflictError) as raised:
        check_workspace_pin(home)

    said = str(raised.value)
    assert exit_code_for(raised.value) == 4
    assert f"{distribution.DISTRIBUTION}==0.0.0" in said
    assert running in said
    assert str(workspace_pyproject(home)) in said
    assert f'requires = "{running}"' in said, (
        f"the refusal does not spell the line that ends it. What it said was: {said}"
    )

def test_a_workspace_with_no_project_file_above_it_records_nothing_to_disagree_with(
    tmp_path: Path,
) -> None:
    """The hand-made workspace, and the home that is not there yet: nothing recorded, nothing said.

    Both are real shapes rather than hypotheticals. `config/registry.py` reads a workflow out of a
    directory with nothing above it, so `workflows/<name>/` alone is a workspace AGL already runs;
    and an operator who has never typed `agl new` has no `workspace/` at all. A reader that treated
    either as a disagreement would refuse every run on the machines least able to explain why.
    """
    home = _home(tmp_path)

    check_workspace_pin(home)

    (workflows_dir(home) / "triage").mkdir(parents=True)

    check_workspace_pin(home)

    assert not workspace_pyproject(home).exists()

def test_a_root_file_that_names_no_requirement_leaves_every_run_where_it_found_it(
    tmp_path: Path,
) -> None:
    """The third state's other spelling: a root file is there and AGL's own table is not.

    That is what a workspace made in a bare checkout carries - `_version_pin` answers `None` and
    the key is left out rather than written as a sentence no resolver could parse - so this is the
    file such a tree hands to an installed AGL later, and it must not read as a claim about it.
    """
    home = _home(tmp_path)
    _recording(home, None)

    check_workspace_pin(home)

    assert _pin(home) is None

def test_an_agl_with_no_metadata_of_its_own_refuses_no_workspace_at_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The running side absent, over a workspace that does name a version: still silence.

    A bare checkout has nothing to compare with, and a refusal there would be AGL claiming the
    workspace disagreed with a version it could not name. The arm is reached the way
    `tests/config/test_distribution.py` reaches it, by pointing `DISTRIBUTION` at the import
    package's name for one test, so the lookup and its `PackageNotFoundError` are the real ones.
    """
    monkeypatch.setattr(distribution, "DISTRIBUTION", distribution.__name__.partition(".")[0])
    home = _home(tmp_path)
    _recording(home, "agents-gl==0.0.0")

    check_workspace_pin(home)

def test_a_requirement_that_is_not_a_string_is_refused_rather_than_read_past(
    tmp_path: Path,
) -> None:
    """This module does not coerce a settings value, and the one key it reads here is no exception.

    The alternative was to treat a non-string as nothing recorded, which is the silence a missing
    key gets - and it would hand an operator who wrote `requires = ["..."]` a guard that had
    quietly switched itself off. The refusal names the key, which is what a silence cannot.
    """
    home = _home(tmp_path)
    workflows_dir(home).mkdir(parents=True)
    workspace_pyproject(home).write_text('[tool.agl]\nrequires = ["x"]\n', encoding="utf-8")

    with pytest.raises(InputError) as raised:
        check_workspace_pin(home)

    assert "tool.agl.requires" in str(raised.value)

# --- One workflow inside that workspace, written once ---------------------------------------------
#
# `make_workflow` is the sequel to the function above and the two are called back to back, so the
# contracts are stated against each other. The workspace is created where it is absent and passed
# over where it is not; a workflow directory is created and *refused* where it is already there,
# because a second call on this one is somebody about to lose the workflow they wrote.
#
# The scaffold's own text is rendered here rather than copied out of a template checked in beside
# it. `tests/test_measurable_targets.py`'s declaration scan walks this repository for any
# pyproject.toml declaring the workflow group, and a template file carrying a real entry-point
# table is exactly the thing it fires on - so the documents below are string constants in `src/`,
# and what a test can hold about them is what comes out the other end.
#
# What `agl run` does with the result is not asserted here, and deliberately: it needs a container,
# a project and the whole dispatch, and `tests/cli/test_new_command.py` is where the scaffold is
# scaffolded and then run. This file asks the narrower question - the writer wrote what it says it
# writes, and would not write it twice.

_GROUP: Final = "agl.workflows"

_TRIAGE: Final = WorkflowName("triage")

def _declarations(home: AglHome, name: WorkflowName) -> Mapping[str, object]:
    """The entry-point table of one written workflow's project file, `{}` where it declares none."""
    document = tomllib.loads(workflow_pyproject(home, name).read_text(encoding="utf-8"))
    project = document.get("project", {})
    entries = project.get("entry-points", {}) if isinstance(project, dict) else {}
    return entries.get(_GROUP, {}) if isinstance(entries, dict) else {}

def test_writing_a_workflow_makes_one_directory_holding_a_module_and_a_project_file(
    tmp_path: Path,
) -> None:
    """The whole of what it makes, listed rather than sampled, into a workspace already there.

    `make_workspace` is called first because that is the order `api.new_workflow` calls them in,
    and the listing then covers both: the workspace's own two entries, and this workflow's three.
    A sampled assertion would pass just as happily against a writer that also left a prompts
    directory, an example role or a `.venv` behind it.
    """
    home = _home(tmp_path)
    make_workspace(home)

    written = make_workflow(home, _TRIAGE, _GROUP)

    assert written == workflow_dir(home, _TRIAGE)
    assert _tree(home) == [
        "workspace",
        "workspace/pyproject.toml",
        "workspace/workflows",
        "workspace/workflows/triage",
        "workspace/workflows/triage/__init__.py",
        "workspace/workflows/triage/pyproject.toml",
    ]

def test_the_written_declaration_names_the_group_it_was_handed_and_the_module_beside_it(
    tmp_path: Path,
) -> None:
    """The group travels as an argument, and this is the half of that decision a test can hold.

    `config/registry.py` defines `GROUP` and imports this module, so the group cannot be imported
    back the other way and a second spelling of it here would be a constant free to drift from the
    one the reader uses. It is passed in instead - and what is asserted is that the argument is
    what lands in the file, which a hard-coded string would pass only by coincidence.
    """
    home = _home(tmp_path)
    make_workspace(home)

    make_workflow(home, _TRIAGE, "somebody.elses.group")

    document = tomllib.loads(workflow_pyproject(home, _TRIAGE).read_text(encoding="utf-8"))
    assert document["project"]["entry-points"] == {
        "somebody.elses.group": {"triage": "triage:triage"}
    }

def test_the_written_project_file_is_one_the_reader_of_every_other_toml_file_accepts(
    tmp_path: Path,
) -> None:
    """The round trip both other writers in this module are held to, asked of this file too.

    `read_document` is what `config/registry.py` reads a workflow declaration through, so a file
    this module wrote and that reader could not parse would be a workflow AGL could never list.
    """
    home = _home(tmp_path)
    make_workspace(home)

    make_workflow(home, _TRIAGE, _GROUP)

    assert read_document(workflow_pyproject(home, _TRIAGE)) is not None
    assert _declarations(home, _TRIAGE) == {"triage": "triage:triage"}

def test_the_written_module_parses_and_binds_the_name_its_own_declaration_points_at(
    tmp_path: Path,
) -> None:
    """The other half of the same round trip: the declaration's `module:attribute` is really there.

    A project file naming an attribute nothing binds is the way a scaffold looks complete in a
    listing and refuses at the first `agl run`. Both ends are read here - `ast` for what the module
    binds, the declaration for what is asked of it - so the two cannot drift apart silently.
    """
    home = _home(tmp_path)
    make_workspace(home)

    make_workflow(home, _TRIAGE, _GROUP)

    declared = _declarations(home, _TRIAGE)["triage"]
    assert isinstance(declared, str), f"an entry point is a string and this one is {declared!r}"
    module, attribute = declared.split(":")
    bound = {
        node.name
        for node in ast.parse(workflow_module(home, _TRIAGE).read_text(encoding="utf-8")).body
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    assert module == str(_TRIAGE), "the module named is the package the directory is imported as"
    assert attribute in bound, f"the declaration names {attribute!r} and the module binds {bound}"

def test_a_workflow_name_already_in_the_workspace_is_refused_and_nothing_of_it_is_touched(
    tmp_path: Path,
) -> None:
    """Create-only here means *refuse*, which is the opposite of what the workspace above does.

    A workspace is called for by everything that writes into it, so a second call has to cost
    nothing; a workflow directory is called for once, by somebody naming it, so a second call is
    that person about to lose what they wrote. The directory is filled with something of its own
    first, and the comparison is over the bytes: a writer that refused after overwriting one of the
    two files would be indistinguishable from this one if only the exception were asserted.
    """
    home = _home(tmp_path)
    make_workspace(home)
    make_workflow(home, _TRIAGE, _GROUP)
    workflow_module(home, _TRIAGE).write_text("# mine\n", encoding="utf-8")
    before = _contents(home)

    with pytest.raises(ConflictError) as raised:
        make_workflow(home, _TRIAGE, _GROUP)

    assert str(workflow_dir(home, _TRIAGE)) in str(raised.value)
    assert _contents(home) == before

def test_a_workflow_written_where_no_workspace_exists_brings_the_directories_with_it(
    tmp_path: Path,
) -> None:
    """The parents are made, so the writer does not depend on the order its caller happened to use.

    `api.new_workflow` calls `make_workspace` first and this is what says the dependency runs one
    way only: a workflow written into a home with nothing in it still lands where the layout says,
    and `config/registry.py`'s walk finds it there. What is *not* made is the workspace's own
    project file - that is `make_workspace`'s, and a writer that made one here would be a second
    answer to what a workspace root holds.
    """
    home = _home(tmp_path)

    make_workflow(home, _TRIAGE, _GROUP)

    assert workflow_module(home, _TRIAGE).is_file()
    assert not workspace_pyproject(home).exists()

def test_a_workflow_directory_that_cannot_be_made_says_so_rather_than_reporting_success(
    tmp_path: Path,
) -> None:
    """A file where the workflows directory belongs: refused, and the path named.

    The failure that is neither "already there" nor a bug - something is in the way and it is not a
    directory - and `InputError` rather than `ConflictError` because there is no workflow here to
    have collided with, only a workspace that is not one.
    """
    home = _home(tmp_path)
    workspace_dir(home).mkdir(parents=True)
    workflows_dir(home).write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(InputError) as raised:
        make_workflow(home, _TRIAGE, _GROUP)

    assert str(workflow_dir(home, _TRIAGE)) in str(raised.value)

# --- A trees root inside the repository, refused -------------------------------------------------
#
# `schema.Project` cannot make this check, because seeing it needs `Path.resolve()` and that type is
# pure - "the same values answer the same way on any machine, with any filesystem underneath".
# It lives here instead, where a `Project` comes out of a file and where the git-root walk already
# reads the filesystem, and is exported so that `init` refuses the same file when it writes one.

def _nested(tmp_path: Path, trees: str) -> Path:
    """A project file whose repo is a real directory and whose trees root is spelled `trees`."""
    home = _home(tmp_path)
    repo = tmp_path.resolve() / "myapp"
    repo.mkdir(parents=True, exist_ok=True)
    return _project_file(home, "myapp", f'repo = "{repo}"\ntrees_root = "{trees}"\n')

def test_a_trees_root_inside_the_repository_is_refused(tmp_path: Path) -> None:
    """AGL lives outside the target repo, and this is the one refusal a project file earns that is
    about two values rather than one.

    What it costs to allow is not subtle: `.trees/<label>/_base/` is a real checkout with a real
    working tree, so AGL's own worktrees would sit inside the repository they were cut from - in the
    operator's `git status`, swept up by `git add -A`, and walked by whatever their build walks.
    AGL keeps its own state under `AGL_HOME` for exactly that reason.

    The message is asserted to carry the file, both keys and both resolved paths, because a reader
    holding it has to decide which of the two to move.
    """
    path = _nested(tmp_path, str(tmp_path.resolve() / "myapp" / ".agl-trees"))
    with pytest.raises(InputError) as raised:
        read_project(_home(tmp_path), ProjectName("myapp"))
    said = str(raised.value)
    assert str(path) in said
    assert "trees_root" in said and "repo" in said
    assert str(tmp_path.resolve() / "myapp" / ".agl-trees") in said
    assert str(tmp_path.resolve() / "myapp") in said

def test_a_trees_root_that_is_the_repository_itself_is_refused(tmp_path: Path) -> None:
    """`is_relative_to` calls a path relative to itself, and that answer is the right one here: a
    trees root *at* the repository is the same failure at its worst, every checkout landing in the
    working tree's own root."""
    _nested(tmp_path, str(tmp_path.resolve() / "myapp"))
    with pytest.raises(InputError):
        read_project(_home(tmp_path), ProjectName("myapp"))

def test_a_trees_root_that_only_resolution_shows_to_be_inside_is_refused(tmp_path: Path) -> None:
    """**Why this could not live in `schema.Project.__post_init__`.** Spelled through a symlink and
    a `..`, the value looks like a sibling and is not one, and nothing short of following the link
    can tell. That read is what makes the check impure, and impure is what cannot go into a type
    whose whole promise is that it answers the same way on any filesystem."""
    repo = tmp_path.resolve() / "myapp"
    repo.mkdir()
    (repo / "inside").mkdir()
    link = tmp_path.resolve() / "elsewhere"
    link.symlink_to(repo / "inside", target_is_directory=True)
    home = _home(tmp_path)
    _project_file(home, "myapp", f'repo = "{repo}"\ntrees_root = "{link}/../inside/trees"\n')
    with pytest.raises(InputError) as raised:
        read_project(home, ProjectName("myapp"))
    assert "trees_root" in str(raised.value)

def test_a_trees_root_beside_the_repository_is_accepted(tmp_path: Path) -> None:
    """The control, and what `agl init` lays out is exactly this shape - `/Users/jan/dev/myapp` and
    `/Users/jan/dev/.agl-trees/myapp`. A refusal that fired on a sibling would refuse every project
    `agl init` writes."""
    _nested(tmp_path, str(tmp_path.resolve() / ".agl-trees" / "myapp"))
    project = read_project(_home(tmp_path), ProjectName("myapp"))
    assert project.trees_root == TreesRoot(tmp_path.resolve() / ".agl-trees" / "myapp")

def test_a_file_that_names_only_one_of_the_two_paths_is_not_refused(tmp_path: Path) -> None:
    """Silence is not a value here (the module's own rule), and a rule about how two paths sit
    relative to each other has nothing to say when the file supplied one of them. Which silence
    is itself a problem is `sources.py`'s to decide, when it applies the layer below the file."""
    home = _home(tmp_path)
    _project_file(home, "myapp", 'trees_root = "/tmp/agl-trees/myapp"\n')
    assert read_project(home, ProjectName("myapp")).repo is None

def test_the_check_is_exported_so_that_init_can_refuse_before_it_writes(tmp_path: Path) -> None:
    """`init` writes the very file the tests above read, and it must refuse the same pair.

    Exported rather than folded into `_project`, so that one helper serves the reader and the
    writer: a nested trees root is refused when the file is written as well as when it is read, and
    the two refusals cannot drift into disagreeing about what "inside" means. The path argument is
    the file the message will name - the writer has one before it writes.
    """
    repo = tmp_path.resolve() / "myapp"
    destination = project_config(_home(tmp_path), ProjectName("myapp"))
    check_trees_root(destination, repo, repo.parent / ".agl-trees")
    with pytest.raises(InputError) as raised:
        check_trees_root(destination, repo, repo / ".agl-trees")
    assert str(destination) in str(raised.value)

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

def test_a_repository_spelled_in_another_case_is_the_same_project(tmp_path: Path) -> None:
    """One directory reached by two spellings, and the filesystem is what says they are one.

    `agl init` records the repository as the operator spelled it that day; `Dev` on Monday and `dev`
    on Tuesday are one directory on a case-insensitive volume and two unequal strings, which is the
    day-one failure a comparison of resolved paths hands somebody who did nothing unusual.

    The probe is the truth and the platform name would be a guess - a case-sensitive volume can be
    mounted anywhere, macOS included. Where it says the volume *is* case-sensitive there is nothing
    to skip past: the two spellings are then two different directories, only one of them holds a
    `.git` entry, and the collision this pins cannot arise at all.
    """
    (tmp_path / "Probe").mkdir()
    if not (tmp_path / "probe").exists():
        pytest.skip("this volume is case-sensitive, so the two spellings are two directories")
    home = _home(tmp_path)
    _register(home, "myapp", _repo(tmp_path, "Myapp"))
    assert resolve_project(home, tmp_path.resolve() / "myapp").name == ProjectName("myapp")

def test_a_project_registered_for_a_repository_that_is_gone_is_skipped(tmp_path: Path) -> None:
    """A registration whose repository no longer exists is stale, not a refusal for everyone else.

    `aaa.toml` sorts first and names a directory that was deleted or is on a volume nobody mounted
    today, so the identity question cannot be answered about it. The scan carries on to the project
    that *is* here - the same judgement made for a file that disappears between the listing and the
    read, and the same answer the comparison gave when it was string equality over resolved paths.
    """
    home = _home(tmp_path)
    root = _repo(tmp_path, "myapp")
    _register(home, "aaa", tmp_path.resolve() / "deleted-last-week")
    _register(home, "myapp", root)
    assert resolve_project(home, root).name == ProjectName("myapp")

def test_a_listing_of_nothing_but_stale_registrations_is_still_not_found(tmp_path: Path) -> None:
    """And when the stale one is all there is, the operator gets the message, not an `OSError`."""
    home = _home(tmp_path)
    root = _repo(tmp_path, "myapp")
    _register(home, "aaa", tmp_path.resolve() / "deleted-last-week")
    with pytest.raises(NotFoundError) as raised:
        resolve_project(home, root)
    assert "no project is registered" in str(raised.value)
    assert str(root) in str(raised.value)

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
