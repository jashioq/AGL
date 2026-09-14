"""`agl init` from the library side: what it detects, what it refuses, and what it leaves behind.

`tests/cli/test_init_command.py` drives the real entry point in a real git repository and proves
the whole operation end to end. This module is the operation on its own, where the refusals are
cheap to arrange and the ordering between them is what is being asserted.

**No real git repository is created here, and that is part of the claim.** `toml_file.git_root`
walks the filesystem looking for a `.git` entry and asks git nothing - no subprocess, no adapter -
so a marker directory is the entire input `api.init` can see, and `tests/config/test_toml_file.py`
makes the same argument for the same walk. What a real repository would add is a subprocess per
case and the chance of quietly testing git.

**Nothing here moves the process.** `api.init` takes a `cwd` rather than reading one, which was
the first decision, and every test below is what that decision buys: two repositories can be
registered in one test, in one process, and a failure leaves no working directory behind it. A
suite driving an ambient `Path.cwd()` would have had to `monkeypatch.chdir` for every one of them.

**Nothing is asked, so nothing is answered.** `api.init` takes the settings and a directory and no
callable to put a question through, and `tests/cli/test_init_command.py` runs the command with its
stdin closed to show the same thing from the other end.

## The ordering is the part that fails silently

Everything that can refuse happens before the file is written. An `init` that wrote first and
refused afterwards passes every test about the refusal itself and leaves a registered project behind
it, which the next `agl init` then refuses as a conflict. So the tests that arrange a refusal assert
that `projects/` was never made.
"""

import inspect
from pathlib import Path
import pytest
from agl import api
from agl.config import sources
from agl.config.schema import Settings
from agl.config.toml_file import read_project
from agl.ports.errors import ConflictError, InputError, NotFoundError, exit_code_for
from agl.ports.ids import ProjectName

def _settings(tmp_path: Path) -> Settings:
    """An installation whose home is under `tmp_path`, resolved through the pure core.

    A literal mapping rather than the process environment, which is `sources.resolve_settings`'
    whole point: nothing ambient reaches it, so this is the settings object a machine with that
    `AGL_HOME` and no `config.toml` resolves - and a missing global file is silence, not a refusal.
    """
    return sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(tmp_path / "home")})

def _repo(tmp_path: Path, name: str = "myapp") -> Path:
    """A directory that looks like a working tree, one level below a parent `init` can write in."""
    root = tmp_path.resolve() / "dev" / name
    (root / ".git").mkdir(parents=True)
    return root

def _keys(written: Path) -> list[str]:
    """The keys the written file holds, in the order they are printed.

    Read off the text as `key = value` lines rather than through a TOML parser, so that this says
    something the reader's own round-trip tests do not: `read_project` answers `None` for a key that
    is absent and for a file that never had one, which is exactly the difference being asserted.
    """
    return [line.split(" = ")[0] for line in written.read_text(encoding="utf-8").splitlines()]

# --- what it writes ------------------------------------------------------------------------------

def test_the_file_it_writes_is_one_the_reader_and_the_resolver_both_accept(tmp_path: Path) -> None:
    """The round trip, which is the criterion rather than the bytes.

    What matters about this file is not its text but that the two modules reading a project's
    settings take it: `toml_file.read_project` by name, and `sources.resolve_project` by the layers
    over it. A test comparing the rendered TOML against a literal would agree with nothing and
    would have to be edited by anyone who changed a space.

    **The key set is asserted as well as the resolved values**, and `build_timeout` is why. It is
    the one key on the file whose value people revisit - a build that outgrows ten minutes is the
    ordinary case - so it has to be *in* the file, where somebody opening it will find it, rather
    than left to the default layer where nothing would show it exists. A test that only checked the
    resolved `600.0` would pass against a file that never mentioned it, the layer below answering.

    The expected timeout is spelled as `sources.DEFAULT_BUILD_TIMEOUT` rather than as `600.0`: the
    number has one home, `api.init` reads it rather than restating it, and a literal here would be
    the second copy - one that keeps passing on the day the default moves and the writer follows.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)

    written = api.init(settings, repo)

    assert _keys(written) == ["name", "repo", "trees_root", "build_timeout"]
    assert read_project(settings.home, ProjectName("myapp")).config == {}
    resolved = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert resolved.name == ProjectName("myapp")
    assert resolved.repo == repo
    assert resolved.trees.path == repo.parent / ".agl-trees" / "myapp"
    assert resolved.config == {}
    assert resolved.build_timeout == sources.DEFAULT_BUILD_TIMEOUT

def test_the_timeout_in_the_file_is_what_answers_and_not_the_default_layer(
    tmp_path: Path,
) -> None:
    """The file is the layer that answers, which is the whole of what writing the key buys.

    Edit the value and it takes effect with no flag and no environment variable - which is the
    thing an operator does with this key, and the thing they could not do with a key that was not
    there. The default layer still exists behind it, for a file somebody removed the key from and
    for every project file written by hand before `agl init` existed.

    The property this pins is also the one `sources.py` warns about in the other direction: a
    project registered today keeps the timeout it was registered with when AGL's own default moves,
    because the file outranks the default. That is right for a file somebody may have edited.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    written = api.init(settings, repo)

    written.write_text(
        written.read_text(encoding="utf-8").replace(
            f"build_timeout = {sources.DEFAULT_BUILD_TIMEOUT!r}", "build_timeout = 1800"
        ),
        encoding="utf-8",
    )

    resolved = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert resolved.build_timeout == 1800.0
    assert resolved.build_timeout != sources.DEFAULT_BUILD_TIMEOUT

def test_keys_added_by_hand_after_init_resolve_on_the_next_read_without_a_second_init(
    tmp_path: Path,
) -> None:
    """The file is read fresh at every resolution, so an operator's edit is the whole of the step.

    Resolved once before the edit as well as after it, so a resolver that cached the first answer
    for the process would hand back the empty config and fail here. `init` is not run again, and
    could not be: it refuses a file that is already there.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    written = api.init(settings, repo)
    assert sources.resolve_project(settings, sources.Overrides(), {}, repo).config == {}

    with written.open("a", encoding="utf-8") as handle:
        handle.write('build = "./scripts/check"\nlinter = ""\n')

    resolved = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert resolved.config == {"build": "./scripts/check", "linter": ""}

def test_the_project_is_named_after_the_repositorys_own_directory(tmp_path: Path) -> None:
    """The example file is `repo = ".../myapp"` and `name = "myapp"`, and this is why.

    It is also what lets `agl init` take no arguments at all: the two facts a project file needs
    that nobody types are both derivable from where the command was run.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path, "other-thing")

    written = api.init(settings, repo)

    assert written.name == "other-thing.toml"
    assert read_project(settings.home, ProjectName("other-thing")).repo == repo

def test_the_trees_root_is_beside_the_repository_and_never_under_it(tmp_path: Path) -> None:
    """The layout in one path: `<repo's parent>/.agl-trees/<name>`, which is the example.

    Under the repository, AGL's checkouts would be in the operator's `git status`, swept up by `git
    add -A` and walked by whatever their build walks - which is what `check_trees_root` refuses and
    what this layout means never to produce in the first place.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)

    api.init(settings, repo)

    trees = read_project(settings.home, ProjectName("myapp")).trees_root
    assert trees is not None
    assert trees.path == repo.parent / ".agl-trees" / "myapp"
    assert not trees.path.is_relative_to(repo)

def test_the_git_root_is_found_from_a_directory_deep_inside_the_repository(tmp_path: Path) -> None:
    """It detects the git root. Nobody runs `agl init` from the top of their tree.

    The name and the repo both come from the root rather than from where the command was typed,
    which is the whole of what detecting it is for.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    inside = repo / "src" / "deep"
    inside.mkdir(parents=True)

    written = api.init(settings, inside)

    assert written.name == "myapp.toml"
    assert read_project(settings.home, ProjectName("myapp")).repo == repo

# --- nothing is asked --------------------------------------------------------------------------

def test_init_takes_the_settings_and_a_directory_and_nothing_to_ask_a_question_through() -> None:
    """The signature is the claim: with no callable on it, there is nowhere a question could go."""
    assert list(inspect.signature(api.init).parameters) == ["settings", "cwd"]

def test_the_project_file_init_writes_has_no_build_key_and_nothing_else_supplies_one(
    tmp_path: Path,
) -> None:
    """No key is written for `build` and no default stands in: the resolved config has no entry."""
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)

    written = api.init(settings, repo)

    assert "build" not in _keys(written)
    environ = {"AGL_BUILD": "make"}
    resolved = sources.resolve_project(settings, sources.Overrides(), environ, repo)
    assert "build" not in resolved.config

# --- the refusals, and the order they are in -----------------------------------------------------

def test_a_second_init_in_the_same_repository_is_a_conflict(tmp_path: Path) -> None:
    """`init` runs once per repo, and the second run must not take the first one's file away.

    `ConflictError` - exit 4 - which is the class `api.run` answers a label that already exists
    with, and for the same reason `ports/errors.py` gives: everything named was found, and the world
    already holds something this operation would have to overwrite. The file is asserted byte for
    byte afterwards, hand edit included, because a refusal that fired after truncating would raise
    the same class.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    written = api.init(settings, repo)
    edited = written.read_text(encoding="utf-8") + 'build = "make"\n'
    written.write_text(edited, encoding="utf-8")

    with pytest.raises(ConflictError) as raised:
        api.init(settings, repo)

    assert exit_code_for(raised.value) == 4
    assert written.read_text(encoding="utf-8") == edited

def test_a_directory_that_is_in_no_git_repository_is_not_found(tmp_path: Path) -> None:
    """`git_root`'s own refusal, uncaught: exit 3, and the message already says to run this here.

    AGL works on a repository, so registering something that is not one has no meaning - and the
    answer is not to write a project file for a directory whose `repo` key names nothing git would
    recognise.
    """
    settings = _settings(tmp_path)
    elsewhere = tmp_path.resolve() / "elsewhere"
    elsewhere.mkdir()

    with pytest.raises(NotFoundError) as raised:
        api.init(settings, elsewhere)

    assert exit_code_for(raised.value) == 3
    assert ".git" in str(raised.value)
    assert not (settings.home.path / "projects").exists()

def test_a_repository_whose_directory_name_is_not_a_usable_project_name_is_refused(
    tmp_path: Path,
) -> None:
    """The name is the directory's, so `ids.py`'s allowlist reaches `agl init` through it.

    The allowlist refuses non-ASCII and shell metacharacters wholesale, and a project name becomes
    `projects/<name>.toml` and the directory beside it. The refusal is `ProjectName`'s own and is
    not re-worded on the way past - `api.py` catches nothing, and a fourth copy of that rule would
    be a fourth thing to keep in agreement with the allowlist.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path, "my app")

    with pytest.raises(InputError) as raised:
        api.init(settings, repo)

    assert exit_code_for(raised.value) == 2
    assert "my app" in str(raised.value)
    assert not (settings.home.path / "projects").exists()

def test_a_trees_root_that_only_resolution_shows_to_be_inside_is_refused_before_writing(
    tmp_path: Path,
) -> None:
    """`check_trees_root` is exported so that `init` refuses a trees root inside the repository
    when the file is written, and this is the arrangement in which the layout `init` picks can
    actually be inside it.

    `<repo's parent>/.agl-trees` is beside the repository as written, and a symlink is what makes
    the written path a lie: point that name at a directory inside the repository and AGL's checkouts
    land in the operator's own working tree - present in `git status`, swept up by `git add -A`.
    Only `Path.resolve()` can see it, which is exactly why the check could not go on
    `schema.Project` and why it is impure by construction.

    Refused where the trees root is *chosen*, so nothing is written. Left to the reader alone, `agl
    init` would report success and the next command in that repository would refuse.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    (repo / "inside").mkdir()
    (repo.parent / ".agl-trees").symlink_to(repo / "inside", target_is_directory=True)

    with pytest.raises(InputError) as raised:
        api.init(settings, repo)

    assert exit_code_for(raised.value) == 2
    assert "trees_root" in str(raised.value)
    assert not (settings.home.path / "projects").exists()

# --- what the signature says ---------------------------------------------------------------------

def test_init_is_sync_and_starts_no_event_loop(tmp_path: Path) -> None:
    """`list_workflows`' rule: an operation that awaits nothing is not declared async.

    It touches no port - `Store` holds runs and a project file is not one, and the write goes to
    `config/toml_file.py`, "the only module that knows TOML". So `cli/commands/init.py` has no
    `asyncio.run`, which is what `cli/main.py` means by leaving the loop to the command: a dispatch
    that awaited everything would make a synchronous command pretend to be something it is not.
    """
    written = api.init(_settings(tmp_path), _repo(tmp_path))

    assert isinstance(written, Path)
