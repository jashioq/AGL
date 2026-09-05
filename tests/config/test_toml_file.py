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
from agl.config.sources import DEFAULT_BUILD_TIMEOUT
from agl.config.toml_file import (
    FileAgent,
    FileProject,
    FileSettings,
    check_trees_root,
    check_unregistered,
    git_root,
    read_project,
    read_settings,
    resolve_project,
    write_project,
)
from agl.ports.errors import ConflictError, InputError, NotFoundError
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
