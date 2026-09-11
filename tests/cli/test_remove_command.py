"""`agl remove <workflow>`: the command, the question it puts first, its streams and its status.

`api.remove` decides: `config/inspection.py` finds the entry and refuses what may not go, the
question comes from `config/questions.py`, and `config/placement.py` takes the entry out. This file
drives all of it through `main`, the way an operator reaches it, with the real `confirm` reading a
replaced `sys.stdin` wherever the answer is the thing under test - nothing patches `builtins.input`,
for `tests/cli/test_confirm.py`'s reason.

**The name is an entry's own.** `agl remove` takes the name of what stands in `workflows/` - the
directory `agl get` placed or `agl new` wrote - and not a name `agl run` takes, which a hand-written
directory is free to make different. Removing by a declared name would take every other name that
directory declares with it, so the question lists every one, and a declared name that is no entry
is refused with the entry that declares it.

**Every refusal comes before the question**, which is what the `confirm` below that raises is for:
a name nothing holds exits 3 naming what is there, a dot-led name or a path exits 2, and an entry
another workflow depends on exits 4 naming each dependent.

**The streams.** The question is on stderr, and the one line on stdout is `removed <workflow>`, so
a script reads what went off stdout and a decline - `n`, stdin at its end, or stdin closed outright
- leaves it empty and exits 0, the operator's answer and not a failure.

**No install and no download.** The syncer and the fetcher behind every invocation here raise if
anything so much as builds one: the workspace's environment is brought up to date by the next sync,
which `agl run` and `agl resume` each begin with, and discovery never needed one.
"""

import ast
import dataclasses
import inspect
import io
import shutil
import sys
from pathlib import Path
from typing import Final
import pytest
from agl.cli import main
from agl.cli.commands import remove as remove_command
from agl.config import registry, sources
from agl.config.questions import Confirm
from agl.ports.fetch import Fetcher
from agl.ports.home_layout import STAGED_REPLACED, STAGING_PREFIX, AglHome, workflows_dir
from agl.ports.ids import ProjectName
from agl.ports.sync import Syncer
from agl.sdk._engine.services import Services
from agl.sdk.params import RefusingParser

# Never opened: `agl remove` reads the home it is handed and no working directory.
ELSEWHERE: Final = Path("/nowhere")

_MODULE: Final = b"from agl.sdk import Run, workflow\n"

_CLOSED: Final = "n - stdin was closed, and that is taken as no\n"

_LOST: Final = "n - a standard stream is closed, so nothing can be read, and that is taken as no\n"

def _never() -> tuple[ProjectName, Services]:
    raise AssertionError("`agl remove` composed a repository")

def _no_syncer() -> Syncer:
    raise AssertionError("`agl remove` built a syncer, so something meant to install")

def _no_fetcher() -> Fetcher:
    raise AssertionError("`agl remove` built a fetcher, so something meant to download")

def _asking_nothing(question: str) -> bool:
    raise AssertionError(f"`agl remove` asked {question!r} where it should have refused first")

def _home(tmp_path: Path) -> AglHome:
    return AglHome(tmp_path / "home")

def _workflow(home: AglHome, directory: str, *declared: str, project: str = "") -> Path:
    """A directory in `workflows/` named `directory` in [project] name too, declaring `declared`."""
    path = workflows_dir(home) / directory
    path.mkdir(parents=True)
    declarations = "\n".join(f'{name} = "{directory}:{name}"' for name in declared)
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "{directory}"\nversion = "0.1.0"\n{project}\n'
        f'[project.entry-points."{registry.GROUP}"]\n{declarations}\n',
        encoding="utf-8",
    )
    (path / "__init__.py").write_bytes(_MODULE)
    return path

def _tree(directory: Path) -> dict[str, bytes]:
    """Every file under `directory` and its bytes, keyed by POSIX path relative to it."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }

def _typed(monkeypatch: pytest.MonkeyPatch, lines: str | None) -> None:
    """`lines` standing in for stdin, or `None` for the stdin a `<&-` leaves the process."""
    monkeypatch.setattr(sys, "stdin", None if lines is None else io.StringIO(lines))

def _main(home: AglHome, *argv: str, confirm: Confirm | None = None) -> int:
    """One `agl` invocation reading `home`, with no repository, installer or fetcher behind it.

    `confirm` left out is the real one, reading whatever the test put on `sys.stdin`.
    """

    def compose() -> main.Invocation:
        invocation = main.Invocation(
            registered=_never,
            settings=sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home.path)}),
            cwd=ELSEWHERE,
            syncer=_no_syncer,
            fetcher=_no_fetcher,
        )
        return invocation if confirm is None else dataclasses.replace(invocation, confirm=confirm)

    return main.main(argv, compose=compose)

def _remove_parser() -> RefusingParser:
    """The `remove` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return remove_command.declare(commands)

# --- the question and its answers ---------------------------------------------------------------

def test_a_workflow_answered_yes_is_gone_and_the_one_line_on_stdout_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gone from `agl workflows` at once, with no install between: discovery walks the directory."""
    home = _home(tmp_path)
    _workflow(home, "triage", "triage")
    _workflow(home, "lint", "lint")
    _typed(monkeypatch, "y\n")

    assert _main(home, "remove", "triage") == 0

    captured = capsys.readouterr()
    assert captured.out == "removed triage\n"
    assert captured.err == f"{workflows_dir(home) / 'triage'} declares 'triage'. Remove it? [y/n] "
    assert sorted(entry.name for entry in workflows_dir(home).iterdir()) == ["lint"]
    assert _main(home, "workflows") == 0
    assert capsys.readouterr().out == "lint\n"

@pytest.mark.parametrize(
    ("typed", "said"), [("n\n", ""), ("N\n", ""), ("", _CLOSED), (None, _LOST)]
)
def test_a_no_stdin_at_its_end_or_stdin_closed_keeps_the_workflow_and_exits_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    typed: str | None,
    said: str,
) -> None:
    """`n`, `< /dev/null` and `<&-`: the workflow as it was, stdout empty, and no traceback.

    `<&-` is the case this command could least afford to get wrong. `input` raises `RuntimeError`
    rather than `EOFError` there, which untranslated reaches `main`'s last clause - a traceback and
    70, from a command whose next step would have deleted a directory.
    """
    home = _home(tmp_path)
    standing = _workflow(home, "triage", "triage")
    before = _tree(standing)
    _typed(monkeypatch, typed)

    assert _main(home, "remove", "triage") == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"{standing} declares 'triage'. Remove it? [y/n] {said}"
    )
    assert _tree(standing) == before

def test_an_answer_that_is_neither_yes_nor_no_puts_the_whole_question_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt `agl get` asks through, reused: `yes` is not `y`, so it is asked again."""
    home = _home(tmp_path)
    standing = _workflow(home, "triage", "triage")
    _typed(monkeypatch, "yes\ny\n")

    assert _main(home, "remove", "triage") == 0

    captured = capsys.readouterr()
    assert captured.err == f"{standing} declares 'triage'. Remove it? [y/n] " * 2
    assert captured.out == "removed triage\n"

def test_the_entry_stands_untouched_for_as_long_as_the_question_is_being_asked(
    tmp_path: Path,
) -> None:
    """Asked, then removed: the answer is looked at before anything moves, never after."""
    home = _home(tmp_path)
    standing = _workflow(home, "triage", "triage")
    before = _tree(standing)
    seen: list[dict[str, bytes]] = []

    def looking(question: str) -> bool:
        seen.append(_tree(standing))
        return True

    assert _main(home, "remove", "triage", confirm=looking) == 0

    assert seen == [before]
    assert not standing.exists()

def test_every_workflow_the_entry_declares_is_named_in_the_question_put(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory declaring two names, removed by its own: both go, and both were named first."""
    home = _home(tmp_path)
    standing = _workflow(home, "triage_dir", "sort-issues", "label_prs")
    _typed(monkeypatch, "n\n")

    assert _main(home, "remove", "triage_dir") == 0

    assert capsys.readouterr().err == (
        f"{standing} declares 'label_prs', 'sort-issues'. Remove it? [y/n] "
    )

# --- what the name reaches ----------------------------------------------------------------------

def test_a_name_differing_only_in_case_removes_the_entry_as_it_is_spelled_on_disk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Triage` stands and `triage` is typed: the question and the line on stdout say `Triage`."""
    home = _home(tmp_path)
    _workflow(home, "Triage", "triage")
    _typed(monkeypatch, "y\n")

    assert _main(home, "remove", "triage") == 0

    captured = capsys.readouterr()
    assert captured.err.startswith(f"{workflows_dir(home) / 'Triage'} declares 'triage'.")
    assert captured.out == "removed Triage\n"
    assert list(workflows_dir(home).iterdir()) == []

def test_a_link_goes_as_the_link_and_the_directory_it_names_is_left_as_it_was(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator's own checkout at the far end of a link is not this command's to delete."""
    home = _home(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "triage"
    elsewhere.mkdir(parents=True)
    (elsewhere / "pyproject.toml").write_text(
        f'[project]\nname = "triage"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{registry.GROUP}"]\ntriage = "triage:triage"\n',
        encoding="utf-8",
    )
    (elsewhere / "notes.md").write_bytes(b"# kept elsewhere\n")
    before = _tree(elsewhere)
    workflows_dir(home).mkdir(parents=True)
    link = workflows_dir(home) / "triage"
    link.symlink_to(elsewhere, target_is_directory=True)
    _typed(monkeypatch, "y\n")

    assert _main(home, "remove", "triage") == 0

    captured = capsys.readouterr()
    assert captured.err.startswith(f"{link} is a link, and declares 'triage'. Remove the link,")
    assert captured.out == "removed triage\n"
    assert not link.exists(follow_symlinks=False)
    assert _tree(elsewhere) == before

def test_a_delete_that_cannot_finish_says_where_what_is_left_now_stands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Out of the workspace at the rename, and what would not delete named on stderr.

    `shutil.rmtree` doing nothing is the instrument: the delete `tempfile` runs on the way out
    ignores what it cannot take, so without a look afterwards a root-owned file left inside would
    sit in `workflows/` unannounced, under a line on stdout saying the workflow was removed.
    """
    home = _home(tmp_path)
    _workflow(home, "triage", "triage")
    _typed(monkeypatch, "y\n")
    monkeypatch.setattr(shutil, "rmtree", lambda path, *args, **kwargs: None)

    assert _main(home, "remove", "triage") == 0

    captured = capsys.readouterr()
    (left,) = list(workflows_dir(home).iterdir())
    assert left.name.startswith(".")
    assert not (left / "pyproject.toml").exists()
    assert captured.out == "removed triage\n"
    assert f"what is left is in {left}" in captured.err

# --- the refusals, each before the question -----------------------------------------------------

def test_a_name_nothing_in_workflows_holds_exits_three_naming_what_it_does_hold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The dot-led staging directory is not offered: this command can never take one."""
    home = _home(tmp_path)
    _workflow(home, "lint", "lint")
    (workflows_dir(home) / f"{STAGING_PREFIX}1t3p5p_r").mkdir()

    assert _main(home, "remove", "triage", confirm=_asking_nothing) == 3

    said = capsys.readouterr().err
    assert "'triage'" in said
    assert "What it holds: 'lint'." in said
    assert STAGING_PREFIX not in said

def test_a_name_only_a_declaration_uses_exits_three_naming_the_entry_that_declares_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`sort-issues` is declared in `triage_dir`, which is the name this command takes."""
    home = _home(tmp_path)
    standing = _workflow(home, "triage_dir", "sort-issues", "label_prs")

    assert _main(home, "remove", "sort-issues", confirm=_asking_nothing) == 3

    assert "a workflow declared in 'triage_dir'" in capsys.readouterr().err
    assert standing.is_dir()

@pytest.mark.parametrize(
    "named", [f"{STAGING_PREFIX}1t3p5p_r", ".", "..", "", "triage/", "../home", "a\\b"]
)
def test_a_dot_led_name_a_traversal_or_a_path_exits_two_and_nothing_is_touched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], named: str
) -> None:
    """A staging directory an override left can hold the only copy of the workflow it replaced.

    So neither it nor anything outside `workflows/` is reachable by a name typed here: the name is
    refused as a name, before the workspace is so much as listed.
    """
    home = _home(tmp_path)
    staging = workflows_dir(home) / f"{STAGING_PREFIX}1t3p5p_r" / STAGED_REPLACED
    staging.mkdir(parents=True)
    (staging / "__init__.py").write_bytes(b"# the only copy\n")

    assert _main(home, "remove", named, confirm=_asking_nothing) == 2

    assert repr(named) in capsys.readouterr().err
    assert (staging / "__init__.py").read_bytes() == b"# the only copy\n"

def test_an_entry_another_workflow_depends_on_exits_four_naming_the_workflow_that_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With it gone every sync would be refused, or the dependency would go to an index instead."""
    home = _home(tmp_path)
    helper = _workflow(home, "helper", "helper")
    triage = _workflow(home, "triage", "triage", project='dependencies = ["helper"]')

    assert _main(home, "remove", "helper", confirm=_asking_nothing) == 4

    said = capsys.readouterr().err
    assert str(triage) in said
    assert "'helper'" in said
    assert helper.is_dir()

def test_an_argument_too_many_on_a_remove_line_is_refused_by_the_dispatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One entry per command, so a second is the dispatch's refusal and nothing is asked."""
    home = _home(tmp_path)
    triage = _workflow(home, "triage", "triage")
    _workflow(home, "lint", "lint")

    assert _main(home, "remove", "triage", "lint", confirm=_asking_nothing) == 2

    assert "'lint'" in capsys.readouterr().err
    assert triage.is_dir()

# --- what the command is, read off the module ---------------------------------------------------

def test_the_remove_parser_takes_one_positional_and_no_option_of_its_own() -> None:
    """No `--yes` and no `--force`: the question is always put, and `yes y |` answers it."""
    parser = _remove_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help"}
    assert positionals == ["workflow"]

def test_the_command_calls_exactly_one_api_function() -> None:
    """"Commands stay dumb" made mechanical - the same scan the other command suites make."""
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(remove_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"remove"}

def test_the_command_never_asks_for_a_registered_repository_installer_or_fetcher(
    tmp_path: Path,
) -> None:
    """A workflow is taken out of the workspace, which lives under no repository, as `agl new`.

    `_never`, `_no_syncer` and `_no_fetcher` on the `Invocation` are the instruments: calling any
    of them fails the command, and the command succeeds.
    """
    home = _home(tmp_path)
    _workflow(home, "triage", "triage")

    assert _main(home, "remove", "triage", confirm=lambda question: True) == 0
    assert list(workflows_dir(home).iterdir()) == []
