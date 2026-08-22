"""Stage 10's walking skeleton driven from the argv side: `main(argv)` on `container.fakes()`.

`tests/test_api.py` proved the operations from the library side. This module drives the real entry
point - the real parser, the real dispatch, the real top-level handler - and reads the real exit
code, which is §1.5's "nothing can script against AGL" turned into an assertion. The numbers below
are written out by hand for `tests/cli/test_exit_codes.py`'s reason: they are the API a script
branches on, so a change to one should have to be typed twice.

**The bundle is substituted through `main`'s one seam and nothing is monkeypatched.** `compose=` is
a keyword-only parameter whose default is the real composition, exactly as `api.run`'s `points=` is,
so the suite hands in `container.fakes()` and an `Invocation` carrying entry points this module
constructs itself. Nothing here reaches into a module's internals to do it, and nothing here needs a
git repository, an `AGL_HOME` or an installed distribution.

**The ordering criterion is pinned twice, and neither pin is the exit code.** §3.1 makes it a
stage-10 acceptance criterion that `Stop` is caught before `AglError`, and an outcome-only test
cannot fail on a swap: `exit_status` reads 7 out of the one table whichever clause caught it. What
differs is the rendering - a deliberate end goes to stdout with no prefix, a failure to stderr with
one - so the behavioural pin is built on that, and the structural pin walks `main`'s own `except`
clauses in source order.
"""

import ast
import asyncio
import inspect
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

import pytest

from agl.cli import main
from agl.config import container, registry
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.sdk.workflow import Run, Stop, workflow

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, so every flag on the line belongs to the generic parser."""


class ReviewNotConverging(Stop):
    """§3.1's own example of a workflow's reason to stop, subclassed as a workflow would."""


# What each workflow was handed, at module level because the workflows have to be: `EntryPoint.load`
# imports a module and reads an attribute in it, and sees no local of this module's functions.
handed: Final[list[Run[NoParams]]] = []


@workflow(name="probe", version="1.1", params=NoParams)
async def probe(run: Run[NoParams]) -> None:
    """Returns. Stage 10's wiring probe, standing in for 10.5's `workflows/noop/`."""
    handed.append(run)


@workflow(name="halting", version="0.1", params=NoParams)
async def halting(run: Run[NoParams]) -> None:
    """Ends deliberately, with a reason of its own - exit 7, and not printed as a failure."""
    raise ReviewNotConverging("two rounds and no convergence")


@workflow(name="exploding", version="0.1", params=NoParams)
async def exploding(run: Run[NoParams]) -> None:
    """Raises something that is not an `AglError` at all: a translation that did not happen."""
    raise ValueError("an adapter forgot to translate this")


def _point(name: str, attribute: str) -> EntryPoint:
    """§3.3's `probe = "agl.workflows.probe:probe"`, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)


POINTS: Final = (
    _point("probe", "probe"),
    _point("halting", "halting"),
    _point("exploding", "exploding"),
)


def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment: no network, no git, no process, one seeded repository."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})


def _compose(harness: container.FakeServices) -> main.Compose:
    """`main`'s seam, filled in: the fakes bundle, this project, and this module's workflows."""
    return lambda: main.Invocation(services=harness.services, project=PROJECT, points=POINTS)


def _main(harness: container.FakeServices, *argv: str) -> int:
    """One `agl` invocation, through the real parser and the real handler."""
    return main.main(argv, compose=_compose(harness))


def _clauses() -> list[str]:
    """The exception classes `main.main`'s `try` catches, in the order they are written.

    Read off the source rather than off the function object, because the ordering is a property of
    the text: `except` clauses are tried top to bottom, and the bug §3.1 names is a swap of two
    adjacent lines that leaves every type annotation and every signature identical.
    """
    entry = [
        node
        for node in ast.walk(ast.parse(inspect.getsource(main)))
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    assert len(entry) == 1, "agl/cli/main.py no longer defines exactly one `main`"
    caught: list[str] = []
    for block in (node for node in ast.walk(entry[0]) if isinstance(node, ast.Try)):
        for handler in block.handlers:
            assert isinstance(handler.type, ast.Name), f"unreadable clause at {handler.lineno}"
            caught.append(handler.type.id)
    return caught


# --- the four acceptance criteria stage 10 names -------------------------------------------------


def test_a_workflow_that_returns_exits_zero(tmp_path: Path) -> None:
    """`agl run <workflow> -n <label>` end to end through argv - the stage's first criterion.

    The record is asserted too, because "exits 0" would also be true of a `main` that parsed the
    line and did nothing: `run.json` is the one thing stage 10 persists, and it is the evidence
    that the dispatch reached `api.run` rather than merely returning.
    """
    handed.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "auth") == 0

    assert len(handed) == 1
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is not None


def test_the_workflow_is_handed_the_bundle_that_was_composed(tmp_path: Path) -> None:
    """§1.4's charge, from the far end: one composition, and the ports reach the workflow.

    `Git(Path.cwd())` was constructed four times and the whole `RunContext` twice. Identity is what
    makes this a test of that - an equal-looking second bundle would pass anything weaker.
    """
    handed.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "auth") == 0

    assert handed[0].services is harness.services


def test_the_same_label_twice_exits_four_in_section_3_10s_words(tmp_path: Path) -> None:
    """The second criterion: exit 4, with the plan's message reaching the user on stderr.

    The refusal is `api.run`'s and the command does not re-detect it, so what is asserted here is
    that it survives the trip: raised in the operation, resolved through the one table, rendered by
    the handler, and printed with nothing added but the program's name.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "probe", "-n", "auth") == 0

    assert _main(harness, "run", "probe", "-n", "auth") == 4


def test_the_existing_label_refusal_is_printed_as_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§3.10's sentence, on stderr, prefixed with the program's name and nothing else."""
    harness = _fakes(tmp_path)
    _main(harness, "run", "probe", "-n", "auth")
    capsys.readouterr()

    _main(harness, "run", "probe", "-n", "auth")

    captured = capsys.readouterr()
    assert captured.err == (
        "agl: run 'auth' already exists - `agl resume auth` or `agl clear auth`.\n"
    )
    assert captured.out == ""


def test_an_unknown_workflow_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The third criterion: `NotFoundError` from the registry, through the handler, as 3.

    The listing in the message is what makes 3 actionable, so it is asserted: the overwhelmingly
    likely cause is a typo and the names the operator meant are three words away.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "nosuch", "-n", "auth") == 3

    captured = capsys.readouterr()
    assert "there is no workflow named 'nosuch'" in captured.err
    assert "probe" in captured.err


def test_a_workflows_own_stop_subclass_exits_seven(tmp_path: Path) -> None:
    """The fourth: 7, not 6 and not 70, for a class that appears in no table.

    `exit_code_for` walks the MRO, so `ReviewNotConverging` resolves to `Stop`'s code without
    anybody editing `ports/errors.py` - and 7 is how a script tells "needs you" from "broken".
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "halting", "-n", "auth") == 7


# --- the ordering hazard, pinned twice and never by the exit code --------------------------------


def test_a_deliberate_stop_is_not_rendered_as_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§3.1's stage-10 criterion, made observable. **This is the test that fails on a clause swap.**

    Swapping `except Stop` with `except AglError` leaves the exit code at 7 - the table answers for
    the class, not for the clause - and changes exactly this: the stop would be printed to stderr
    with the `agl:` prefix a failure carries, and stdout would be empty. Both assertions below fail
    in that world, and neither of them mentions a number.
    """
    harness = _fakes(tmp_path)

    code = _main(harness, "run", "halting", "-n", "auth")

    captured = capsys.readouterr()
    assert code == 7
    assert captured.out == "stopped: two rounds and no convergence\n"
    assert captured.err == "", "a deliberate end was reported as a failure"


def test_the_handler_catches_stop_before_agl_error(tmp_path: Path) -> None:
    """The same criterion in the source: the clause order, read off `main`'s own text.

    The behavioural pin above is the one that matters and this is the one that says why it fails.
    `Stop` descends from `AglError`, so a handler written the other way round catches a deliberate
    end in the failure clause and nothing about the types or the signatures changes.

    `BaseException` is asserted absent for `cli/exit_codes.py`'s reason: `exit_status` takes
    `Exception`, so a `BaseException` arm would not typecheck - and it would answer a Ctrl-C with a
    number, where dying of the signal is what lets a shell loop be stopped by the key that stopped
    this process.
    """
    caught = _clauses()

    assert caught.index("Stop") < caught.index("AglError") < caught.index("Exception")
    assert "BaseException" not in caught


# --- refusals a user can provoke, and the one that is ours ---------------------------------------


def test_an_unknown_flag_exits_two_rather_than_leaving_through_system_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`argparse.ArgumentParser.error()` calls `sys.exit(2)`, which is a second exit-code table.

    The number it writes is even the right one, and it is still wrong: it bypasses
    `ports/errors.py`'s table and the handler with it, so nothing above could have rendered it,
    logged it or chosen otherwise. `RefusingParser` raises `InputError` instead, and this asserts
    the whole route - a `SystemExit` escaping `main` would fail this test by never returning.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "auth", "--nosuch") == 2

    assert "--nosuch" in capsys.readouterr().err


def test_a_missing_label_exits_two_rather_than_leaving_through_system_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`-n` is required, and a required argument argparse never saw is the other `error()` route.

    `exit_on_error=False` would not have covered it - that converts only what is raised while
    consuming a value, and a missing required argument still goes through `error()`.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe") == 2

    assert "-n/--name" in capsys.readouterr().err


def test_a_label_the_filesystem_would_not_take_exits_two(tmp_path: Path) -> None:
    """`RunLabel` validates on the way in (§3.3), and its `InputError` is the same 2.

    The label becomes a directory and the branch `agl/<label>`, so `my/label` is a path where a
    name belongs. Nothing downstream re-checks it, which is why it is checked before the run.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "my/label") == 2


def test_no_subcommand_at_all_exits_two(tmp_path: Path) -> None:
    """A bare `agl` is a usage error, not a default command: `agl run` is not what silence means."""
    harness = _fakes(tmp_path)

    assert _main(harness) == 2


def test_an_unexpected_exception_exits_seventy_with_its_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§1.5's charge answered: `_cmd_run` ended in a bare `except Exception` rendering any bug as
    `error: <str>`, so the traceback - the only part of a bug worth having - was thrown away.

    Anything that is not an `AglError` reaching the top is a translation an adapter did not perform,
    which is our bug, which is 70 (`cli/exit_codes.py` argues both halves). The traceback is printed
    because that is what "file a bug" needs, and the sentence after it is what tells the reader the
    bug is not theirs.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "exploding", "-n", "auth") == 70

    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert "an adapter forgot to translate this" in captured.err
    assert "AGL's own bug" in captured.err
    assert captured.out == ""


def test_help_still_exits_zero_through_system_exit(tmp_path: Path) -> None:
    """`-h` is `argparse`'s one sanctioned exit and `RefusingParser` leaves `exit()` untouched.

    `SystemExit` is a `BaseException`, so it passes the handler by construction rather than by an
    arm written to let it - the same structural reason `KeyboardInterrupt` is unanswered.
    """
    harness = _fakes(tmp_path)

    for argv in (("-h",), ("run", "-h")):
        with pytest.raises(SystemExit) as caught:
            main.main(argv, compose=_compose(harness))
        assert caught.value.code == 0


# --- the composition, and the number this module may not write -----------------------------------


def test_the_composition_happens_once_and_only_after_argv_is_understood(tmp_path: Path) -> None:
    """§1.4's charge, measured: one resolution per invocation, and none for a line that is wrong.

    Four `Git(Path.cwd())` and two `RunContext`s is what this counts against. The second half is the
    ordering `main` is written in: a person who typed the command wrong is told what they typed
    wrong, wherever they typed it, rather than being told they are not inside a registered
    repository - and `agl -h` reads no file and builds no adapter.
    """
    harness = _fakes(tmp_path)
    composed: list[main.Invocation] = []

    def counting() -> main.Invocation:
        composed.append(_compose(harness)())
        return composed[-1]

    assert main.main(("run", "probe", "-n", "auth"), compose=counting) == 0
    assert len(composed) == 1

    composed.clear()
    assert main.main(("run", "probe"), compose=counting) == 2
    assert composed == [], "argv was refused and the world was resolved anyway"


def test_main_writes_no_exit_code_of_its_own(tmp_path: Path) -> None:
    """"No integer literal appears in this file", made mechanical rather than promised.

    Every arm of the handler resolves through `exit_status`, and success is the command's to return
    because success is not a row in `ports/errors.py`'s table. A number typed here would be the
    second table starting, which is the same claim `tests/cli/test_exit_codes.py` scans for one
    module along - including the `1` of a `sys.argv[1:]` that is not written because `argparse`
    already defaults to it.
    """
    written = [
        node.value
        for node in ast.walk(ast.parse(inspect.getsource(main)))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ]

    assert not written, (
        f"agl/cli/main.py writes {written}. Exit codes are read out of `ports/errors.py`'s one "
        f"table through `cli/exit_codes.exit_status`, and nothing else here is a number"
    )


def test_the_seam_is_a_parameter_and_the_real_composition_is_its_default() -> None:
    """`compose=None` means the real one, spelled the way `api.run` spells `points=None`.

    A seam with a signature rather than a module attribute a test monkeypatches: `api.py` argues
    the choice, and this asserts that `main` can still be called the way `pyproject.toml`'s console
    script calls it - `main()` with nothing at all.
    """
    signature = inspect.signature(main.main)

    assert signature.parameters["argv"].default is None
    assert signature.parameters["compose"].default is None
    assert signature.parameters["compose"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.return_annotation is int


def test_argv_defaults_to_the_command_line_without_this_module_saying_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`argv=None` reaches `argparse`, whose own default is `sys.argv[1:]` - stated in one place.

    Driven through `sys.argv` because that is the only thing the console script sets: `agl` calls
    `main()` with no arguments, and everything this suite asserts about argv would be about a path
    the installed program never takes if that default were spelled differently here.
    """
    harness = _fakes(tmp_path)
    handed.clear()
    monkeypatch.setattr("sys.argv", ["agl", "run", "probe", "-n", "auth"])

    assert main.main(compose=_compose(harness)) == 0

    assert len(handed) == 1
    assert capsys.readouterr().out == "run 'auth' finished\n"
