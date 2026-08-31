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

**Nothing patches `builtins.input` either.** The question `init` asks travels as a
parameter, so a test hands in a lambda and reads what the prompt said - and `cli/main.py` is the one
place `input` is named at all.

## The ordering is the part that fails silently

Everything that can refuse without asking anybody anything happens before the question, which is
`api.run`'s rule about preflight applied to the one thing here that costs more than a syscall. An
`init` that asked first and refused afterwards passes every test about the refusal itself and wastes
a build command an operator typed. So the tests that arrange a refusal all hand in an `ask` that
records, and assert it was never called.
"""

from pathlib import Path
from typing import Final

import pytest

from agl import api
from agl.config import sources
from agl.config.schema import Settings
from agl.config.toml_file import read_project
from agl.ports.errors import ConflictError, InputError, NotFoundError, exit_code_for
from agl.ports.ids import ProjectName

BUILD: Final = "./gradlew build"


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


class _Asked:
    """An `Ask` that records. The seam, filled in with something a test can interrogate."""

    def __init__(self, answer: str = BUILD) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


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

    written = api.init(settings, repo, _Asked())

    assert _keys(written) == ["name", "repo", "trees_root", "build", "build_timeout"]
    assert read_project(settings.home, ProjectName("myapp")).build == BUILD
    resolved = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert resolved.name == ProjectName("myapp")
    assert resolved.repo == repo
    assert resolved.trees.path == repo.parent / ".agl-trees" / "myapp"
    assert resolved.build == BUILD
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
    written = api.init(settings, repo, _Asked())

    written.write_text(
        written.read_text(encoding="utf-8").replace(
            f"build_timeout = {sources.DEFAULT_BUILD_TIMEOUT!r}", "build_timeout = 1800"
        ),
        encoding="utf-8",
    )

    resolved = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert resolved.build_timeout == 1800.0
    assert resolved.build_timeout != sources.DEFAULT_BUILD_TIMEOUT


def test_the_project_is_named_after_the_repositorys_own_directory(tmp_path: Path) -> None:
    """The example file is `repo = ".../myapp"` and `name = "myapp"`, and this is why.

    It is also what lets `agl init` take no arguments at all: the two facts a project file needs
    that nobody types are both derivable from where the command was run.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path, "other-thing")

    written = api.init(settings, repo, _Asked())

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

    api.init(settings, repo, _Asked())

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

    written = api.init(settings, inside, _Asked())

    assert written.name == "myapp.toml"
    assert read_project(settings.home, ProjectName("myapp")).repo == repo


# --- the question, and the seam it travels on ----------------------------------------------------


def test_the_build_command_is_asked_for_once_and_the_prompt_says_what_it_is_for(
    tmp_path: Path,
) -> None:
    """`init` asks for the build command, and nothing anywhere in AGL guesses at one.

    There is no build-tool detection anywhere in AGL, so this one question is the whole mechanism,
    and the prompt has to name the thing being asked about: there are two build commands in AGL's
    world - the merge gate's, which is this, and the one a workflow writes into a prompt, which is
    deliberately no business of the framework's - and "build command:" alone would not distinguish
    them.
    """
    asked = _Asked()

    settings = _settings(tmp_path)

    api.init(settings, _repo(tmp_path), asked)

    assert len(asked.prompts) == 1
    assert "merge gate" in asked.prompts[0]
    assert read_project(settings.home, ProjectName("myapp")).build == BUILD


def test_what_the_answer_says_is_stripped_and_stored_as_typed(tmp_path: Path) -> None:
    """A line somebody typed arrives with the whitespace they typed around it, and nothing else.

    Stripped, because `input` hands back what was entered; not otherwise touched, because
    `schema.Project` hands the string to a shell and this is not the module that gets an opinion
    about what a shell line means.
    """
    settings = _settings(tmp_path)

    api.init(settings, _repo(tmp_path), _Asked("  make test && ./verify.sh  "))

    assert read_project(settings.home, ProjectName("myapp")).build == "make test && ./verify.sh"


def test_a_blank_build_command_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    """`schema.Project` refuses a blank build where the file is read; this is that rule earlier.

    A file written blank is one every later command refuses, so the operator would learn about it
    from a command that was not asking - and would have a registered project they then have to
    clear by hand. Refused here, nothing is written and `agl init` can simply be run again.
    """
    settings = _settings(tmp_path)

    with pytest.raises(InputError) as raised:
        api.init(settings, _repo(tmp_path), _Asked("   "))

    assert exit_code_for(raised.value) == 2
    assert "merge gate" in str(raised.value)
    assert not (settings.home.path / "projects").exists()


# --- the refusals, and the order they are in -----------------------------------------------------


def test_a_second_init_in_the_same_repository_is_a_conflict(tmp_path: Path) -> None:
    """`init` runs once per repo, and the second run must not take the first one's file away.

    `ConflictError` - exit 4 - which is the class `api.run` answers a label that already exists
    with, and for the same reason `ports/errors.py` gives: everything named was found, and the world
    already holds something this operation would have to overwrite. The settings are asserted intact
    afterwards, because a refusal that fired after truncating would raise the same class.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    api.init(settings, repo, _Asked("make"))

    with pytest.raises(ConflictError) as raised:
        api.init(settings, repo, _Asked("ninja"))

    assert exit_code_for(raised.value) == 4
    assert read_project(settings.home, ProjectName("myapp")).build == "make"


def test_the_conflict_is_refused_before_anybody_is_asked_anything(tmp_path: Path) -> None:
    """The ordering, and it is the half that fails silently.

    `api.run` puts every free refusal in front of the one that costs real turns; here the expensive
    step is a person, and an `init` that asked first would take a build command from somebody whose
    repository was registered last week and throw it away. The recording `ask` is what notices.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    api.init(settings, repo, _Asked("make"))
    asked = _Asked("ninja")

    with pytest.raises(ConflictError):
        api.init(settings, repo, asked)

    assert asked.prompts == [], "a repository that was already registered was asked for a build"


def test_a_directory_that_is_in_no_git_repository_is_not_found(tmp_path: Path) -> None:
    """`git_root`'s own refusal, uncaught: exit 3, and the message already says to run this here.

    AGL works on a repository, so registering something that is not one has no meaning - and the
    answer is not to write a project file for a directory whose `repo` key names nothing git would
    recognise.
    """
    settings = _settings(tmp_path)
    elsewhere = tmp_path.resolve() / "elsewhere"
    elsewhere.mkdir()
    asked = _Asked()

    with pytest.raises(NotFoundError) as raised:
        api.init(settings, elsewhere, asked)

    assert exit_code_for(raised.value) == 3
    assert ".git" in str(raised.value)
    assert asked.prompts == []


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
    asked = _Asked()

    with pytest.raises(InputError) as raised:
        api.init(settings, repo, asked)

    assert exit_code_for(raised.value) == 2
    assert "my app" in str(raised.value)
    assert asked.prompts == []


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
    asked = _Asked()

    with pytest.raises(InputError) as raised:
        api.init(settings, repo, asked)

    assert exit_code_for(raised.value) == 2
    assert "trees_root" in str(raised.value)
    assert asked.prompts == []
    assert not (settings.home.path / "projects").exists()


# --- what the signature says ---------------------------------------------------------------------


def test_init_is_sync_and_starts_no_event_loop(tmp_path: Path) -> None:
    """`list_workflows`' rule: an operation that awaits nothing is not declared async.

    It touches no port - `Store` holds runs and a project file is not one, and the write goes to
    `config/toml_file.py`, "the only module that knows TOML". So `cli/commands/init.py` has no
    `asyncio.run`, which is what `cli/main.py` means by leaving the loop to the command: a dispatch
    that awaited everything would make the two sync commands pretend to be something they are not.
    """
    written = api.init(_settings(tmp_path), _repo(tmp_path), _Asked())

    assert isinstance(written, Path)
