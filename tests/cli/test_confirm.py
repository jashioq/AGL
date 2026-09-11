"""The default behind `Invocation.confirm`: `cli/main.py` reading a yes or a no off stdin.

`config/questions.py` decides what `agl get` asks, and hands each question to a `Confirm`; this is
the one `agl` runs with. It takes `y` or `n` in either case and nothing else - an empty line,
`yes` and ` y` are each asked again, whole - so a slip at the keyboard is put again, not guessed at.

**The question goes to stderr, and `input` is handed no prompt.** `input` writes a prompt to stdout
whenever stdin or stdout is not a terminal, and stdout is what a machine reads off `agl`. Stdin is
replaced here by something that is not a terminal - the path a prompt handed to `input` would take
to stdout - and every test that reads the streams asserts stdout empty.

**A closed stdin is a no.** `input` raises `EOFError` at end of file - `< /dev/null`, a script whose
input ran dry, a Ctrl-D - and that declines the question it interrupted, with the rest of the line
saying so, so nothing written after it runs on from the prompt. Nothing remembers it: a terminal is
read again after a Ctrl-D, so each question meets its own end of file - and under `< /dev/null`
every question does, which is the whole of "no terminal means no", with no `isatty` and no flag.

**Nothing patches `builtins.input`**, for `tests/cli/test_init_command.py`'s reason: stdin is what
is replaced, and it is the situation reported on rather than a way past a seam. A stdin that fails
rather than ending is not taken as an answer either. pytest's own captured stdin raises `OSError`,
so a suite that leaves this default standing where it meant to answer for itself fails where it
reads, rather than declining every question and passing on a command that placed nothing.
"""

import io
import sys
from pathlib import Path
from typing import Final
import pytest
from agl.cli import main
from agl.config import sources
from agl.config.inspection import PlaceableWorkflow
from agl.config.questions import DeclinedWorkflow, answered, needed
from agl.ports.get_request import RepositoryAtRef, RequestedWorkflow
from agl.ports.ids import ProjectName
from agl.sdk._engine.services import Services

_QUESTION: Final = "Override it?"

_PROMPT: Final = "Override it? [y/n] "

_CLOSED: Final = "n - stdin was closed, and that is taken as no\n"

_SHA: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

# Never opened, like the home below: a question names what stands there and reads nothing.
_WORKFLOWS: Final = Path("/nowhere/workspace/workflows")

class _Unreadable:
    """A stdin that fails rather than ending, the way pytest's own captured one does."""

    def readline(self) -> str:
        raise OSError("pytest: reading from stdin while output is captured!")

def _typed(monkeypatch: pytest.MonkeyPatch, lines: str) -> None:
    """`lines` standing in for stdin, which is then no terminal - `input` reads it a line a call."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(lines))

def _placeable(name: str, *, existing: bool, dependencies: tuple[str, ...]) -> PlaceableWorkflow:
    repository = RepositoryAtRef("jashioq", "myrepo", None)
    directory = f"workflows/mine/{name}"
    workflow = RequestedWorkflow(repository, directory, f"{repository}/{directory}")
    standing = _WORKFLOWS / name if existing else None
    return PlaceableWorkflow(workflow, _SHA, {}, dependencies, standing)

def _never() -> tuple[ProjectName, Services]:
    raise AssertionError("asking a question composed a repository")

# --- one question --------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("typed", "confirmed"), [("y", True), ("Y", True), ("n", False), ("N", False)]
)
def test_each_answer_it_takes_is_taken_the_first_time_it_is_typed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    typed: str,
    confirmed: bool,
) -> None:
    _typed(monkeypatch, f"{typed}\n")

    assert main._confirmed(_QUESTION) is confirmed

    captured = capsys.readouterr()
    assert captured.err == _PROMPT
    assert captured.out == ""

@pytest.mark.parametrize("typed", ["", "yes", "no", " y", "n ", "Y\t", "yy", "y\r"])
def test_anything_else_typed_is_answered_by_the_whole_question_put_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], typed: str
) -> None:
    """Surrounding whitespace included, and so a line a Windows editor ended with CRLF."""
    _typed(monkeypatch, f"{typed}\ny\n")

    assert main._confirmed(_QUESTION) is True

    captured = capsys.readouterr()
    assert captured.err == _PROMPT * 2
    assert captured.out == ""

def test_a_closed_stdin_declines_the_question_and_lets_nothing_escape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _typed(monkeypatch, "")

    assert main._confirmed(_QUESTION) is False

    captured = capsys.readouterr()
    assert captured.err == _PROMPT + _CLOSED
    assert captured.out == ""

def test_the_question_is_written_to_stderr_and_nothing_at_all_to_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two lines that are no answer, then end of file: a prompt handed to `input` makes three."""
    _typed(monkeypatch, "maybe\nyes\n")

    main._confirmed(_QUESTION)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == _PROMPT * 3 + _CLOSED

def test_a_stdin_that_fails_rather_than_ends_is_an_error_and_never_a_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stdin", _Unreadable())

    with pytest.raises(OSError, match="captured"):
        main._confirmed(_QUESTION)

# --- a batch of them -----------------------------------------------------------------------------

def test_no_terminal_at_all_declines_every_download_in_the_batch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`agl get < /dev/null`: each download meets its first question and is declined at it."""
    first = _placeable("alpha", existing=True, dependencies=("rich",))
    second = _placeable("beta", existing=False, dependencies=("httpx",))
    (collision, _) = needed(first)
    (dependencies,) = needed(second)
    _typed(monkeypatch, "")

    assert answered([first, second], main._confirmed) == (
        DeclinedWorkflow(first, collision),
        DeclinedWorkflow(second, dependencies),
    )
    captured = capsys.readouterr()
    assert captured.err == f"{collision} [y/n] {_CLOSED}{dependencies} [y/n] {_CLOSED}"
    assert captured.out == ""

def test_a_stdin_closing_mid_batch_declines_every_question_still_to_come(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One `y` typed and then end of file: the first question is answered, and each after it no."""
    first = _placeable("alpha", existing=True, dependencies=("rich",))
    second = _placeable("beta", existing=False, dependencies=("httpx",))
    (collision, first_dependencies) = needed(first)
    (second_dependencies,) = needed(second)
    _typed(monkeypatch, "y\n")

    assert answered([first, second], main._confirmed) == (
        DeclinedWorkflow(first, first_dependencies),
        DeclinedWorkflow(second, second_dependencies),
    )
    captured = capsys.readouterr()
    assert captured.err == (
        f"{collision} [y/n] {first_dependencies} [y/n] {_CLOSED}{second_dependencies} [y/n] "
        f"{_CLOSED}"
    )
    assert captured.out == ""

# --- the seam ------------------------------------------------------------------------------------

def test_the_default_behind_the_seam_reads_the_operators_own_answer_off_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Suites hand their own answers in, so they would all pass on a default that said yes itself.

    `agl get` at a terminal would then place over what stands, and install what it names, having
    asked nobody - so the default is driven here with a yes and a no, and must return each.
    """
    settings = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": "/nowhere"})
    invocation = main.Invocation(registered=_never, settings=settings, cwd=Path("/nowhere"))
    _typed(monkeypatch, "y\nn\n")

    assert invocation.confirm(_QUESTION) is True
    assert invocation.confirm(_QUESTION) is False
    captured = capsys.readouterr()
    assert captured.err == _PROMPT * 2
    assert captured.out == ""
