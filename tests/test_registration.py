"""Registration from the library side: what it derives, what it refuses, and what it leaves behind.

`tests/cli/test_main.py` drives the real entry point and proves which commands register and which
refuse instead. This module is `toml_file.register_repository` on its own, where the derivations
are cheap to arrange and the ordering between the refusals is what is being asserted.

**No real git repository is created here, and that is part of the claim.** `toml_file.git_root`
walks the filesystem looking for a `.git` entry and asks git nothing - no subprocess, no adapter -
so a marker directory is the entire input registration can see, and `tests/config/test_toml_file.py`
makes the same argument for the same walk. What a real repository would add is a subprocess per
case and the chance of quietly testing git.

**Nothing here moves the process.** `register_repository` takes a starting directory rather than
reading one, which is what keeps `Path.cwd()` in `cli/main.py` and nowhere else, and every test
below is what that decision buys: two repositories can be registered in one test, in one process,
and a failure leaves no working directory behind it. A suite driving an ambient `Path.cwd()` would
have had to `monkeypatch.chdir` for every one of them.

**Nothing is asked, so nothing is answered.** Registration takes a home and a directory and no
callable to put a question through: it is something `agl run` does on the way past rather than
something an operator is stopped for.

## The ordering is the part that fails silently

Everything that can refuse happens before the file is written. A registration that wrote first and
refused afterwards passes every test about the refusal itself and leaves a project behind it, which
the next command then resolves to. So the tests that arrange a refusal assert that `projects/` was
never made.
"""

from pathlib import Path
import pytest
from agl.config import sources
from agl.config.schema import Settings
from agl.config.toml_file import read_project, register_repository
from agl.ports.errors import ConflictError, InputError, NotFoundError, exit_code_for
from agl.ports.home_layout import project_config, project_dir
from agl.ports.ids import ProjectName

def _settings(tmp_path: Path) -> Settings:
    """An installation whose home is under `tmp_path`, resolved through the pure core.

    A literal mapping rather than the process environment, which is `sources.resolve_settings`'
    whole point: nothing ambient reaches it, so this is the settings object a machine with that
    `AGL_HOME` and no `config.toml` resolves - and a missing global file is silence, not a refusal.
    """
    return sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(tmp_path / "home")})

def _repo(tmp_path: Path, name: str = "myapp", *, parent: str = "dev") -> Path:
    """A directory that looks like a working tree, one level below a parent AGL can write in.

    The parent is a parameter for one case: two repositories whose directories carry the same name
    have to sit in two of them, or they are one directory.
    """
    root = tmp_path.resolve() / parent / name
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

def test_the_file_registration_writes_is_one_the_reader_and_the_resolver_both_accept(
    tmp_path: Path,
) -> None:
    """The round trip, which is the criterion rather than the bytes.

    What matters about this file is not its text but that the two modules reading a project's
    settings take it: `toml_file.read_project` by name, and `sources.resolve_project` by the layers
    over it. A test comparing the rendered TOML against a literal would agree with nothing and
    would have to be edited by anyone who changed a space.

    This is also the claim the registering path depends on rather than merely benefits from:
    `cli/main.py`'s `_registering` writes and then resolves again, so a file the resolver would
    refuse is refused in the same command that wrote it.

    **The key set is asserted as well as the resolved values**, and `build_timeout` is why. The
    file holds the facts only this repository can supply, and the timeout is not one of them - it
    is AGL's own default, left to the layer that owns it. The two assertions together are what say
    that an absent key and a pre-written `600.0` answer identically, which is the whole reason the
    writer does not put one there.

    The expected timeout is spelled as `sources.DEFAULT_BUILD_TIMEOUT` rather than as `600.0`: the
    number has one home, and a literal here would be the second copy - one that keeps passing on
    the day the default moves.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)

    assert register_repository(settings.home, repo) is None

    written = project_config(settings.home, ProjectName("myapp"))
    assert _keys(written) == ["name", "repo", "trees_root"]
    assert read_project(settings.home, ProjectName("myapp")).config == {}
    resolved = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert resolved.name == ProjectName("myapp")
    assert resolved.repo == repo
    assert resolved.trees.path == repo.parent / ".agl-trees" / "myapp"
    assert resolved.config == {}
    assert resolved.build_timeout == sources.DEFAULT_BUILD_TIMEOUT

def test_a_build_timeout_added_to_the_file_by_hand_outranks_the_default_layer(
    tmp_path: Path,
) -> None:
    """The key is readable though nothing writes one, which is what leaving it out has to cost.

    An operator wanting a different timeout adds the line themselves, exactly as they add a key
    their workflow declared: `toml_file.RESERVED_KEYS` still names `build_timeout`, so the reader
    takes it and `config/sources.py` puts the file above the default. Resolved before the edit as
    well as after it, because "the file answers" is a claim only where the default answered before.

    The property this pins is also the one `sources.py` warns about in the other direction: a
    project whose file names a timeout keeps that one when AGL's own default moves. That is right
    for a line somebody wrote on purpose, and it is why nothing writes one on their behalf.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    register_repository(settings.home, repo)
    written = project_config(settings.home, ProjectName("myapp"))
    before = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert before.build_timeout == sources.DEFAULT_BUILD_TIMEOUT

    with written.open("a", encoding="utf-8") as handle:
        handle.write("build_timeout = 1800\n")

    resolved = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert resolved.build_timeout == 1800.0
    assert resolved.build_timeout != sources.DEFAULT_BUILD_TIMEOUT

def test_keys_added_by_hand_resolve_on_the_next_read_without_a_second_registration(
    tmp_path: Path,
) -> None:
    """The file is read fresh at every resolution, so an operator's edit is the whole of the step.

    Resolved once before the edit as well as after it, so a resolver that cached the first answer
    for the process would hand back the empty config and fail here. Nothing registers a second
    time and nothing could: a repository a file already names resolves, and registration is what
    only an unresolved one reaches.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    register_repository(settings.home, repo)
    written = project_config(settings.home, ProjectName("myapp"))
    assert sources.resolve_project(settings, sources.Overrides(), {}, repo).config == {}

    with written.open("a", encoding="utf-8") as handle:
        handle.write('build = "./scripts/check"\nlinter = ""\n')

    resolved = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert resolved.config == {"build": "./scripts/check", "linter": ""}

def test_the_project_is_named_after_the_repositorys_own_directory(tmp_path: Path) -> None:
    """The example file is `repo = ".../myapp"` and `name = "myapp"`, and this is why.

    It is also what lets registration ask nothing at all: the two facts a project file needs that
    nobody types are both derivable from where the command was run.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path, "other-thing")

    register_repository(settings.home, repo)

    assert project_config(settings.home, ProjectName("other-thing")).name == "other-thing.toml"
    assert read_project(settings.home, ProjectName("other-thing")).repo == repo

def test_the_trees_root_is_beside_the_repository_and_never_under_it(tmp_path: Path) -> None:
    """The layout in one path: `<repo's parent>/.agl-trees/<name>`, which is the example.

    Under the repository, AGL's checkouts would be in the operator's `git status`, swept up by `git
    add -A` and walked by whatever their build walks - which is what `check_trees_root` refuses and
    what this layout means never to produce in the first place.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)

    register_repository(settings.home, repo)

    trees = read_project(settings.home, ProjectName("myapp")).trees_root
    assert trees is not None
    assert trees.path == repo.parent / ".agl-trees" / "myapp"
    assert not trees.path.is_relative_to(repo)

def test_the_git_root_is_found_from_a_directory_deep_inside_the_repository(tmp_path: Path) -> None:
    """It detects the git root. Nobody runs their first `agl run` from the top of their tree.

    The name and the repo both come from the root rather than from where the command was typed,
    which is the whole of what detecting it is for.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    inside = repo / "src" / "deep"
    inside.mkdir(parents=True)

    register_repository(settings.home, inside)

    assert project_config(settings.home, ProjectName("myapp")).name == "myapp.toml"
    assert read_project(settings.home, ProjectName("myapp")).repo == repo

def test_two_repositories_of_one_directory_name_get_distinct_ledger_roots_and_trees_roots(
    tmp_path: Path,
) -> None:
    """The collision the suffix exists for, and every place the name it picks reaches.

    Four, and this asserts all of them: `projects/<name>.toml`; the `name` key inside it, which
    `toml_file._project_name` holds to the file's own stem; `projects/<name>/`, where the runs are
    recorded; and the trees root, which `register_repository` composes here and which is then
    written into the file and read back from it rather than recomposed - so the suffix reaches it
    once and for good.

    **The ledger roots are distinct because of the suffix and the trees roots are not.** Both
    ledgers sit under one `projects/`, so the name is the whole of what separates them. The trees
    roots differ by parent before the suffix is considered at all: two repositories of one
    directory name are in two parents by definition, and each root is `<parent>/.agl-trees/<name>`.
    The suffix is consistency there rather than the thing doing the work, and it is worth keeping
    anyway, because the last segment of the trees root is how an operator reads which project a
    checkout belongs to.
    """
    settings = _settings(tmp_path)
    first = _repo(tmp_path)
    second = _repo(tmp_path, parent="elsewhere")

    one = register_repository(settings.home, first)
    two = register_repository(settings.home, second)

    assert one is None
    assert two is not None
    assert "myapp-1" in two and "myapp" in two
    assert project_config(settings.home, ProjectName("myapp")).is_file()
    assert read_project(settings.home, ProjectName("myapp-1")).name == ProjectName("myapp-1")
    assert read_project(settings.home, ProjectName("myapp-1")).repo == second
    assert project_dir(settings.home, ProjectName("myapp")) != project_dir(
        settings.home, ProjectName("myapp-1")
    )
    trees = [
        sources.resolve_project(settings, sources.Overrides(), {}, repo).trees.path
        for repo in (first, second)
    ]
    assert trees == [
        first.parent / ".agl-trees" / "myapp",
        second.parent / ".agl-trees" / "myapp-1",
    ]

def test_the_project_file_registration_writes_has_no_build_key_and_nothing_supplies_one(
    tmp_path: Path,
) -> None:
    """No key is written for `build` and no default stands in: the resolved config has no entry."""
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)

    register_repository(settings.home, repo)

    assert "build" not in _keys(project_config(settings.home, ProjectName("myapp")))
    environ = {"AGL_BUILD": "make"}
    resolved = sources.resolve_project(settings, sources.Overrides(), environ, repo)
    assert "build" not in resolved.config

# --- the refusals, and the order they are in -----------------------------------------------------

def test_registering_a_repository_a_file_already_names_refuses_rather_than_suffixing_it(
    tmp_path: Path,
) -> None:
    """The one path left to `free_project_name`'s repo-aware refusal, and why it is still there.

    **Lazy registration all but closes it.** `cli/main.py`'s `_registering` calls this only after
    `toml_file.resolve_project` raised `NotFoundError`, and that refusal says every file under
    `projects/` was read and none of them names this repository - so the taken candidate
    `free_project_name` meets can only be one naming somebody else's, and a suffix is the right
    answer. The `InputError` path does not reach registration at all: a file too broken to read its
    `repo` out of makes `resolve_project` raise `_unreadable` instead, which is not a
    `NotFoundError`, so nothing registers over the top of it.

    **What is left is the race**, and it is what this arranges by calling the registrar twice
    directly: a second AGL in this same repository that registered it between the two steps.
    Without the guard that one writes `myapp-1.toml` naming the same `repo`, `-` being 0x2D and `.`
    0x2E, so `resolve_project`'s sorted walk would answer every later command with a ledger root
    holding no runs. `write_project`'s own `_appeared` is the same guard one step further in.

    `ConflictError` - exit 4 - which is the class `api.run` answers a label that already exists
    with, and for the same reason `ports/errors.py` gives: everything named was found, and the
    world already holds something this operation would have to overwrite. The file is asserted byte
    for byte afterwards, hand edit included, because a refusal that fired after truncating would
    raise the same class.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path)
    register_repository(settings.home, repo)
    written = project_config(settings.home, ProjectName("myapp"))
    edited = written.read_text(encoding="utf-8") + 'build = "make"\n'
    written.write_text(edited, encoding="utf-8")

    with pytest.raises(ConflictError) as raised:
        register_repository(settings.home, repo)

    assert exit_code_for(raised.value) == 4
    assert written.read_text(encoding="utf-8") == edited
    assert not project_config(settings.home, ProjectName("myapp-1")).exists()

def test_a_directory_that_is_in_no_git_repository_is_not_found(tmp_path: Path) -> None:
    """`git_root`'s own refusal, uncaught: exit 3, and the message says where to run AGL instead.

    AGL works on a repository, so registering something that is not one has no meaning - and the
    answer is not to write a project file for a directory whose `repo` key names nothing git would
    recognise.
    """
    settings = _settings(tmp_path)
    elsewhere = tmp_path.resolve() / "elsewhere"
    elsewhere.mkdir()

    with pytest.raises(NotFoundError) as raised:
        register_repository(settings.home, elsewhere)

    assert exit_code_for(raised.value) == 3
    assert ".git" in str(raised.value)
    assert not (settings.home.path / "projects").exists()

def test_a_repository_whose_directory_name_is_not_a_usable_project_name_is_refused(
    tmp_path: Path,
) -> None:
    """The name is the directory's, so `ids.py`'s allowlist reaches registration through it.

    The allowlist refuses non-ASCII and shell metacharacters wholesale, and a project name becomes
    `projects/<name>.toml` and the directory beside it. The refusal is `ProjectName`'s own and is
    not re-worded on the way past - a fourth copy of that rule would be a fourth thing to keep in
    agreement with the allowlist.
    """
    settings = _settings(tmp_path)
    repo = _repo(tmp_path, "my app")

    with pytest.raises(InputError) as raised:
        register_repository(settings.home, repo)

    assert exit_code_for(raised.value) == 2
    assert "my app" in str(raised.value)
    assert not (settings.home.path / "projects").exists()
