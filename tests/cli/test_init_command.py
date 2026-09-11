"""The grammar `agl init`, and its acceptance criterion: reachable and working end to end.

`tests/test_init.py` drives `api.init` from the library side, where the ordering between the
refusals and the question is asserted. This module drives the real entry point - the real parser,
the real `_compose`, the real dispatch and the real handler - in **a real temporary git repository
with a temporary `AGL_HOME`**, which is the criterion word for word, and then asks the two modules
that read a project's settings whether they take what it wrote. The round trip is the criterion; the
file's bytes are not.

**These tests let `main` compose for real**, which `tests/cli/test_main.py` calls its deliberate
exception and which is unavoidable here: `agl init` is the one command whose whole subject is the
composition - it runs where no project file exists, so a `compose=` that handed in a ready-made
`Invocation` would be substituting the thing under test. What is substituted instead is one field of
the real invocation, `ask`, because the alternative is a suite that blocks on a prompt.

**Nothing patches `builtins.input`.** That is what `Invocation.ask` exists for, and a suite reaching
past every seam a module has in order to answer one question is exactly what a seam with a signature
prevents (`api.py` argues the pattern; `cli/main.py` holds the real default). The tests below that
close stdin, or another standard stream, are not an exception to that: they replace the stream, let
the real default stand, and a closed stream is the thing they report on rather than a way past a
seam.

**A real `git init` here, and marker directories in the library suite.** `toml_file.git_root` asks
git nothing, so a `.git` directory is the whole of what it can see and the library tests use one.
This file spends the subprocess anyway, once per test: "reachable and working end to end" is a claim
about a repository somebody actually has, and a criterion measured against a directory named `.git`
would be measuring the walk rather than the command.
"""

import ast
import inspect
import io
import sys
from pathlib import Path
from typing import Final
import pytest
from agl.cli import main
from agl.cli.commands import init as init_command
from agl.config import sources
from agl.config.toml_file import read_project
from agl.ports.errors import InputError, NotFoundError
from agl.ports.ids import ProjectName
from agl.sdk.params import RefusingParser

BUILD: Final = "./gradlew build"

def _repository(tmp_path: Path, name: str = "myapp") -> Path:
    """A real git repository, one level below a parent AGL can put a trees root in."""
    root = tmp_path.resolve() / "dev" / name
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    return root

def _git(cwd: Path, *argv: str) -> None:
    """One git command, for the repository this file's tests are run against."""
    import subprocess

    subprocess.run(("git", *argv), cwd=cwd, check=True, capture_output=True)

def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An `AGL_HOME` that does not exist yet - which is what a first `agl init` meets.

    Set in the process environment because that is where `sources.resolve` reads it, and it reads
    it inside `_compose` rather than at import, so setting it before `main` is called is what
    reaches it.
    """
    home = tmp_path / "home"
    monkeypatch.setenv("AGL_HOME", str(home))
    return home

def _main(cwd: Path, *argv: str, answer: str = BUILD) -> int:
    """One `agl` invocation composed for real, with the one question answered by a lambda.

    `_compose()` is called and then one field of what it produced is replaced, which is the smallest
    substitution that leaves the composition itself under test: the settings are the ones the
    environment resolved, and `cwd` is handed in because a test may not move the process.
    """
    resolved = main._compose()
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=resolved.registered, settings=resolved.settings, cwd=cwd,
            ask=lambda _: answer,
        ),
    )

def _init_parser() -> RefusingParser:
    """The `init` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return init_command.declare(commands)

# --- the acceptance criterion --------------------------------------------------------------------

def test_agl_init_registers_a_repository_that_had_no_project_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The criterion: `agl init` reachable and working end to end, in a fresh repository.

    Reachable is the half per-command composition bought and this is where it is spent - the
    project and the container were once built before the dispatch chose a command, so in this
    directory `main` would have refused with `NotFoundError` before `init` was reached, however
    well `init` was written.

    Working is the round trip: `read_project` takes the file by name and `resolve_project` finds it
    by walking up from inside the repository, which are the two ways every later command reaches a
    project. The file's key set is asserted beside the resolved values, because `build_timeout` is
    the key that would otherwise be invisible: a `Project` carrying the right timeout proves nothing
    about whether the file mentions it, the default layer being able to answer either way - and the
    reason it is written is that it is the one knob on this file people revisit, in the one place
    they would look for it.
    """
    home = _home(tmp_path, monkeypatch)
    repo = _repository(tmp_path)

    assert _main(repo, "init") == 0

    written = home / "projects" / "myapp.toml"
    assert f"init wrote {written}" in capsys.readouterr().out
    settings = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home)})
    assert read_project(settings.home, ProjectName("myapp")).build == BUILD
    project = sources.resolve_project(settings, sources.Overrides(), {}, repo)
    assert project.name == ProjectName("myapp")
    assert project.repo == repo
    assert project.trees.path == repo.parent / ".agl-trees" / "myapp"
    assert project.build == BUILD
    assert project.build_timeout == sources.DEFAULT_BUILD_TIMEOUT
    assert [
        line.split(" = ")[0] for line in written.read_text(encoding="utf-8").splitlines()
    ] == ["name", "repo", "trees_root", "build", "build_timeout"]

def test_a_run_in_that_repository_now_composes_where_it_could_not_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Afterwards every workflow works with no further setup - the half `init` is for.

    Before it, `Invocation.registered()` raises `NotFoundError` naming `agl init`; after it, the
    same callable resolves a project and builds a container. That is the whole claim of the command,
    and it is asserted through the real composition because a substituted one proves nothing about
    it. Nothing is run: `container.real` constructing is the evidence, and running a workflow here
    would be `tests/cli/test_run_command.py`'s job with real adapters attached.
    """
    _home(tmp_path, monkeypatch)
    repo = _repository(tmp_path)
    with pytest.raises(NotFoundError, match="agl init"):
        main._registered(sources.resolve(sources.Overrides()), repo)

    assert _main(repo, "init") == 0

    project, services = main._registered(sources.resolve(sources.Overrides()), repo)
    assert str(project) == "myapp"
    assert services.build == BUILD

# --- the refusals, through argv ------------------------------------------------------------------

def test_a_second_init_in_the_same_repository_exits_four(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`init` runs once per repo. Exit 4 is `run`'s class for a world that already holds it.

    The settings are asserted intact afterwards, because that is what the refusal is *for*: somebody
    who edited `build` by hand and ran `agl init` again must not lose the edit.
    """
    home = _home(tmp_path, monkeypatch)
    repo = _repository(tmp_path)
    assert _main(repo, "init") == 0
    capsys.readouterr()

    assert _main(repo, "init", answer="ninja") == 4

    assert "already registered" in capsys.readouterr().err
    settings = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home)})
    assert read_project(settings.home, ProjectName("myapp")).build == BUILD

def test_init_outside_a_git_repository_exits_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`git_root`'s refusal, through the handler, as 3 - and nothing written.

    The same class and the same number an unregistered repository answers with, which is right: both
    are "AGL looked and there is no such thing", and `ports/errors.py` puts that on the class.
    """
    home = _home(tmp_path, monkeypatch)
    elsewhere = tmp_path.resolve() / "elsewhere"
    elsewhere.mkdir()

    assert _main(elsewhere, "init") == 3

    assert ".git" in capsys.readouterr().err
    assert not home.exists()

def test_a_trees_root_a_symlink_puts_inside_the_repository_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`check_trees_root`, reached from the writer's side, through argv.

    `<repo's parent>/.agl-trees` is beside the repository as written and a symlink is what makes
    that a lie. Refused at exit 2 with nothing written, so the operator fixes the link rather than
    discovering, at their first `agl run`, that they have a registered project AGL will not use.
    """
    home = _home(tmp_path, monkeypatch)
    repo = _repository(tmp_path)
    (repo / "inside").mkdir()
    (repo.parent / ".agl-trees").symlink_to(repo / "inside", target_is_directory=True)

    assert _main(repo, "init") == 2

    assert "trees_root" in capsys.readouterr().err
    assert not (home / "projects").exists()

def test_init_with_its_stdin_closed_exits_two_rather_than_reporting_a_bug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`agl init < /dev/null`, and the one test in this file that lets the real `ask` stand.

    `_main` above replaces `ask`, which is right for every case where the question has an answer
    and wrong for this one: what is being asserted is a fact about the field's *default*. So the
    invocation below is `_main`'s minus that one substitution, and `sys.stdin` is what the test
    replaces instead - which is the situation being reported rather than a way past a seam.

    Exit 2 is the user-visible half and the traceback's absence is the other. `input` raises
    `EOFError`, which is not an `AglError`, so untranslated it reaches `cli/main.py`'s last clause -
    a traceback and `_OUR_BUG`, telling somebody who pressed Ctrl-D on the first command they ever
    ran that they had found a bug in AGL. Both are asserted, because a refusal that exited 2 and
    printed a traceback anyway would still be that.
    """
    home = _home(tmp_path, monkeypatch)
    repo = _repository(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    resolved = main._compose()

    code = main.main(
        ("init",),
        compose=lambda: main.Invocation(
            registered=resolved.registered, settings=resolved.settings, cwd=repo
        ),
    )

    assert code == 2
    captured = capsys.readouterr().err
    assert "stdin" in captured
    assert "Traceback" not in captured
    assert not home.exists(), "a refused init wrote something anyway"

def test_the_default_ask_turns_a_closed_stdin_into_a_refusal_that_keeps_the_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Invocation.ask`'s default on its own, for the two halves an exit code cannot show.

    `cli/main.py` is where `input` is named, so it is where the `EOFError` is translated - the rule
    `ARCHITECTURE.md` states for an adapter, applied one layer up the way `config/toml_file.py`
    applies it to its own `OSError`. It is not translated in `api.init`, which catches nothing and
    may not: `tests/test_api_no_except.py` holds that, and a handler there would be the first
    `except` in a module whose whole property is having none.

    So the refusal quotes the question instead of restating what a build command is for. `_asked`
    is handed a prompt and does not know which question it asked; `api.init` owns the sentence
    about an answer that arrived empty. One refusal per thing refused, and no second copy of the
    question anywhere to fall out of step with `api.py`'s.

    `__cause__` is the other half, and the one nothing else would notice going missing: the exit
    code, the class and the message are all identical without `raise ... from`, and what goes is
    the `EOFError` under the refusal on the traceback.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    with pytest.raises(InputError) as raised:
        main._asked("build command: ")

    assert "build command:" in str(raised.value)
    assert isinstance(raised.value.__cause__, EOFError)

@pytest.mark.parametrize("stream", ["stdin", "stdout", "stderr"])
def test_the_default_ask_refuses_a_stream_closed_outright_as_it_refuses_the_end_of_stdin(
    monkeypatch: pytest.MonkeyPatch, stream: str
) -> None:
    """`<&-`, `>&-`, `2>&-`: `input` raises `RuntimeError` for each, and it is chained the same way.

    An answer is waiting on stdin every time, so what is refused is the stream and never an empty
    line - `api.init`'s own refusal of one would otherwise pass for this.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{BUILD}\n"))
    monkeypatch.setattr(sys, stream, None)

    with pytest.raises(InputError) as raised:
        main._asked("build command: ")

    assert "build command:" in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)

def test_init_with_its_stdin_closed_outright_exits_two_and_prints_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`agl init <&-`: the refusal end of file gets, where it would otherwise be a bug report."""
    home = _home(tmp_path, monkeypatch)
    repo = _repository(tmp_path)
    monkeypatch.setattr(sys, "stdin", None)
    resolved = main._compose()

    code = main.main(
        ("init",),
        compose=lambda: main.Invocation(
            registered=resolved.registered, settings=resolved.settings, cwd=repo
        ),
    )

    assert code == 2
    captured = capsys.readouterr().err
    assert "stdin" in captured
    assert "Traceback" not in captured
    assert not home.exists(), "a refused init wrote something anyway"

# --- what the command is, read off the module ----------------------------------------------------

def test_the_init_parser_holds_no_arguments_at_all(tmp_path: Path) -> None:
    """The line for this verb is one word. Everything `init` needs it works out for itself.

    `-h` is argparse's own and is the only option on it; a positional here would be a repository or
    a name typed twice, and both are facts about where the command was run.
    """
    parser = _init_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help"}
    assert positionals == []

def test_the_command_calls_exactly_one_api_function() -> None:
    """`ARCHITECTURE.md`'s "Commands stay dumb", made mechanical - and this is a command the rule
    was written for.

    The command this replaces did build-tool detection, TOML rendering and template writing in ~150
    lines. The same scan the other command suites make: a second `api.` name here is that use case
    starting to come back, and a `toml_file.` or a `Path(` would be the real thing.
    """
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(init_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"init"}

def test_the_command_never_asks_for_a_registered_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`init` takes settings alone, and this is the half of that a test can measure.

    `registered()` resolves the very file this command writes, so a clause that called it would make
    `agl init` refuse in every repository it exists for. The counter is on the `Invocation`, which
    is `main`'s own seam, so nothing here reaches into a module to find out.
    """
    _home(tmp_path, monkeypatch)
    repo = _repository(tmp_path)
    asked: list[str] = []

    def _never() -> tuple[ProjectName, object]:
        asked.append("registered")
        raise AssertionError("`agl init` composed a repository")

    code = main.main(
        ("init",),
        compose=lambda: main.Invocation(
            registered=_never,  # type: ignore[arg-type]
            settings=sources.resolve_settings(
                sources.Overrides(), {"AGL_HOME": str(tmp_path / "home")}
            ),
            cwd=repo,
            ask=lambda _: BUILD,
        ),
    )

    assert code == 0
    assert asked == []

def test_the_command_starts_no_event_loop() -> None:
    """`api.init` is sync, so this module has no `asyncio.run` and does not import `asyncio`.

    `cli/main.py` gives that as the reason the loop belongs to the command rather than the dispatch:
    a dispatch that awaited everything would make a synchronous command pretend otherwise. Read off
    the source, because "it worked anyway" is true of a command that wrapped a sync call in a loop.

    It is also the cheapest mechanical guard that `agl init` installs nothing. `agl new`, `agl run`
    and `agl resume` each end in a `Syncer`, and every one of them awaits it, so a clause added
    here would have to import `asyncio` to reach one - which is the assertion below.
    """
    source = ast.parse(inspect.getsource(init_command))

    imported = {
        name.name
        for node in ast.walk(source)
        if isinstance(node, ast.Import)
        for name in node.names
    }
    called = {
        node.func.value.id
        for node in ast.walk(source)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }

    assert "asyncio" not in imported
    assert "asyncio" not in called

# --- the tail, which this command may not carry --------------------------------------------------

def test_an_argument_on_an_init_line_is_refused_and_points_at_the_two_commands_that_take_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_dispatch`'s tail refusal, reached by the third command to share it, and re-worded for it.

    An earlier version explained that a run's arguments are read back from the record `agl run`
    wrote, which is true of `resume` and `clear` and says nothing about a command addressed to no
    run. What survives is a fact about `agl run` - it is the only command that names a workflow -
    and the signpost to `agl workflows <workflow>`, which is where a person who typed a workflow's
    flag on the wrong line finds out what that workflow actually takes.
    """
    home = _home(tmp_path, monkeypatch)
    repo = _repository(tmp_path)

    assert _main(repo, "init", "myapp") == 2

    captured = capsys.readouterr().err
    assert "myapp" in captured
    assert "agl workflows <workflow>" in captured
    assert not home.exists(), "a refused init wrote something anyway"
