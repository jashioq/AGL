"""`agl workflows [<workflow>]`: the listing that imports nothing, and the help that imports one.

This verb was designed with no argument and has an optional one, which is a deliberate deviation
from the grammar it started with and is asserted here as deliberately as it is argued in
`cli/commands/workflows.py`. The two halves are different claims and the tests are separated
accordingly, because the interesting property of each is what it does *not* do.

**The listing must survive a workflow that will not import.** `registry.names` never calls `load`,
so a workflow whose own code is broken still appears in the listing and every other workflow still
runs. A registry that imported the world to print a list would let one half-written directory in
the workspace take down the command an operator runs to find out what they have. So one of this
module's entry points is deliberately unloadable, and the listing is asserted to contain its name.

**Naming it must fail loudly.** The other half of the same guarantee: the load happens behind an
explicit request, so `agl workflows broken` is the operator asking for the one thing that is broken,
and a silent answer would be worse than a refusal. Exit 2 - `config/registry.py` argues that class
against `InternalError` and `UpstreamUnavailable` both.

**Neither invocation composes a repository.** `list_workflows` takes neither a project nor a
services bundle. The `registered` on the `Invocation` raises if it is called, which is `main`'s own
seam used as the instrument - nothing here reaches into a module to count anything. What it does
take is the home the workspace sits under, and that is not a new dependency for this command:
`main._compose` resolves settings for every invocation there is and always did, while `registered`
- the callable that builds a container - is the half that stayed lazy.

**`_perhaps` here is this module's own.** `run.py`, `resume.py` and `clear.py` share one argv
reader out of `cli/commands/__init__.py`; this one is not a fourth caller of it. It returns
`str | None` rather than `str`, and its refusal says "a string it took off the command line or
nothing at all", which is the whole of what an optional positional means here - so it is a different
function rather than a copy, which is what the other three were and no longer are.

The bundle is not needed at all, which is itself the point: these tests build no `container.fakes()`
and no trees root, because a command that listed what the workspace declares and needed a repository
to do it would be a defect.
"""

import ast
import inspect
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl.cli import main
from agl.cli.commands import new as new_command
from agl.cli.commands import workflows as workflows_command
from agl.config import registry, sources
from agl.ports.home_layout import AglHome, workflows_dir
from agl.ports.ids import ProjectName
from agl.sdk.params import RefusingParser, arg
from agl.sdk.workflow import Run, workflow

# `agl init` is the one command that reads these two and neither invocation below is one; the fields
# are not optional (`cli/main.py` argues why), so both carry a real value nothing here looks at.
ELSEWHERE: Final = Path("/nowhere")
SETTINGS: Final = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(ELSEWHERE)})

@dataclass(frozen=True)
class Flagged:
    """The example params class, so the help printed below has something in it."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3, help="how many at once")

@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing: its help is a usage line and no options."""

@workflow(version="1.0")
async def tickets(run: Run[Flagged]) -> None:
    """Declared for its flags alone; nothing below runs it."""

@workflow(version="1.0")
async def probe(run: Run[NoParams]) -> None:
    """Declared so the listing has a second name in it, and one with no flags to print."""

def _point(name: str, attribute: str) -> EntryPoint:
    """A registration line, pointed at this module: a name, a `module:attr`, and a group."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)

# A module nothing can import, declared under a name the listing still shows. `EntryPoint.load`
# raises `ImportError`, which `registry.load` turns into `InputError` - and `names` never loads.
BROKEN: Final = EntryPoint(
    name="broken", value="agl.workflows.no_such_package:broken", group=registry.GROUP
)

POINTS: Final = (_point("tickets", "tickets"), _point("probe", "probe"), BROKEN)

def _never() -> tuple[ProjectName, object]:
    """A `Registered` that fails the test if a command calls it: this command takes neither."""
    raise AssertionError("`agl workflows` composed a repository")

def _main(*argv: str, points: tuple[EntryPoint, ...] = POINTS) -> int:
    """One `agl` invocation, with this module's entry points in place of what is installed."""
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=_never,  # type: ignore[arg-type]
            settings=SETTINGS,
            cwd=ELSEWHERE,
            points=points,
        ),
    )

def _workspace(tmp_path: Path) -> AglHome:
    """An AGL_HOME under `tmp_path`, so nothing here can reach the operator's own."""
    return AglHome(tmp_path / "home")

def _directory(home: AglHome, named: str, pyproject: str) -> None:
    """One directory under `workspace/workflows/`, holding the project file it is handed."""
    path = workflows_dir(home) / named
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(pyproject, encoding="utf-8")

def _declaring(named: str, attribute: str) -> str:
    """A project file declaring one workflow, pointed at this module so it resolves already."""
    return (
        f'[project]\nname = "{named}"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{registry.GROUP}"]\n{named} = "{__name__}:{attribute}"\n'
    )

def _reading(home: AglHome, *argv: str) -> int:
    """One `agl` invocation with no entry points supplied, so the workspace is what answers."""
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=_never,  # type: ignore[arg-type]
            settings=sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home.path)}),
            cwd=ELSEWHERE,
            points=None,
        ),
    )

def _workflows_parser() -> RefusingParser:
    """The `workflows` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return workflows_command.declare(commands)

# --- the listing, which imports nothing ----------------------------------------------------------

def test_the_listing_is_the_registrys_sorted_names_one_per_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """List what is registered. Sorted, on stdout, one name per line.

    One per line because a listing is data somebody pipes - `agl workflows | while read` is the
    reason it is not a sentence with commas in it - and sorted because `registry.names` sorts, so a
    listing is stable across environments rather than ordered by a metadata scan.
    """
    assert _main("workflows") == 0

    captured = capsys.readouterr()
    assert captured.out == "broken\nprobe\ntickets\n"
    assert captured.err == ""

def test_a_workflow_that_cannot_be_imported_does_not_take_the_listing_down(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`registry.names` never calls `load`, and this is the guarantee that buys.

    An operator with one half-written workflow in their workspace still gets the answer to "what do
    I have", and every other workflow still runs. This is the test the deliberate mutation goes red
    on: an `execute` that loaded each workflow to list them would refuse the whole command here.
    """
    assert _main("workflows") == 0

    assert "broken" in capsys.readouterr().out

def test_a_workspace_that_declares_nothing_says_so_on_stderr_and_still_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty listing needs a sentence and not blank output - and not on the stream being piped.

    Logs go to stderr and data to stdout, so `agl workflows | wc -l` has to answer 0 here; and
    silence from a command that was asked a question reads as a command that failed quietly, so the
    explanation goes to stderr rather than nowhere. Exit 0, because nothing failed: no workflow
    declared is the true answer.

    The sentence is where an operator with an empty workspace learns what to do next, so both
    halves of that are asserted: the command that writes a workflow, and the shape of the
    declaration for a directory somebody would rather write by hand. `registry.py`'s own "no
    workflow is declared at all" names the command too and still defers here for the line, which is
    why a message that merely named the group would not do. The command is asserted as
    `new_command.NAME` and not as text, so a module deleted out from under the sentence breaks this
    test rather than leaving an operator pointed at a command that is not there.
    """
    assert _main("workflows", points=()) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "agl.workflows" in captured.err
    assert '<name> = "<module>:<attribute>"' in captured.err
    assert f"agl {new_command.NAME}" in captured.err

# --- the workspace, read whenever no entry points are handed in ----------------------------------

def test_a_directory_that_declares_no_workflow_is_named_beside_the_names_that_do(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The listing's guarantee, reaching the directories an operator wrote themselves.

    One bad directory cannot answer for the others - `config/registry.py` says so and
    `tests/config/test_registry.py` pins the walk; this is the half a person sees. The bad one goes
    to stderr for `_NOTHING_DECLARED`'s reason: stdout is the list a script reads names off, and a
    directory that declares nothing is not a name `agl run` takes.
    """
    home = _workspace(tmp_path)
    _directory(home, "triage", _declaring("triage", "tickets"))
    _directory(home, "half-written", "[project\n")

    assert _reading(home, "workflows") == 0

    captured = capsys.readouterr()
    assert captured.out == "triage\n"
    assert "half-written" in captured.err

def test_naming_a_directory_that_declares_no_workflow_refuses_with_its_own_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2 and the file that will not parse, which is the same class and the same code a
    declaration pointing at a module nothing can import gets: a declaration that does not hold up,
    read by AGL and written by whoever wrote the workflow. Exit 3's "there is no workflow by that
    name" would be the wrong sentence entirely - the operator typed the name of a directory they
    are writing."""
    home = _workspace(tmp_path)
    _directory(home, "half-written", "[project\n")

    assert _reading(home, "workflows", "half-written") == 2

    assert "pyproject.toml" in capsys.readouterr().err

# --- the name, which imports exactly one ---------------------------------------------------------

def test_naming_a_workflow_prints_the_flags_it_declares(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The UX gap once declined, closed: `agl run tickets -h` cannot show these, and this can.

    The usage line names `agl run tickets` rather than `agl workflows tickets`, because these are
    flags typed on *that* command - the parser is the very one `api.run` parses with, so what is
    printed is what will be accepted rather than a second description of it.

    `-h` is absent, and that is the decision rather than an omission: `sdk/params.py` builds this
    parser with `add_help=False` so that one word does not mean two helps depending on where it
    appears, and `agl run tickets -h` still prints AGL's `run` help.
    """
    assert _main("workflows", "tickets") == 0

    captured = capsys.readouterr()
    assert "agl run tickets" in captured.out
    assert "--request" in captured.out
    assert "what to build" in captured.out
    assert "--concurrent" in captured.out
    assert "-h" not in captured.out
    assert captured.err == ""

def test_naming_the_broken_workflow_fails_loudly_for_that_name_and_no_other(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The other half of the listing's guarantee: a load behind an explicit request fails loudly.

    Exit 2 and not 70 - `config/registry.py` argues it in as many words: "AGL only read what was
    declared", so exit 70's "file a bug against AGL" would send the reader to the wrong codebase.
    The message names the declaration's value, which is the string to search the workspace for, and
    the listing above is asserted still to work afterwards.
    """
    assert _main("workflows", "broken") == 2

    assert "agl.workflows.no_such_package:broken" in capsys.readouterr().err
    assert _main("workflows") == 0

def test_a_name_nothing_registers_exits_three_and_lists_what_does(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The registry's `NotFoundError`, unwrapped: 3, and the names the operator meant are right
    there, because the overwhelmingly likely cause is a typo."""
    assert _main("workflows", "nosuch") == 3

    captured = capsys.readouterr().err
    assert "nosuch" in captured
    assert "tickets" in captured

def test_a_workflow_with_no_flags_prints_a_usage_line_rather_than_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A workflow may declare no parameters, and the honest answer is a usage line with none in it.

    Not a sentence of AGL's own about emptiness: `format_help()` is argparse's rendering of the
    parser that will actually parse, and inventing prose here would be a second help format kept in
    agreement with it by nobody.
    """
    assert _main("workflows", "probe") == 0

    assert capsys.readouterr().out.strip() == "usage: agl run probe"

# --- what the command is, read off the module ----------------------------------------------------

def test_the_workflows_parser_holds_one_optional_positional_and_no_flags() -> None:
    """The grammar, read off the object: `agl workflows [<workflow>]`.

    Optional, so that the original spelling - the bare `agl workflows` - stays the listing it
    always was, and the argument added later cannot make anybody type one.
    """
    parser = _workflows_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help"}
    assert [action.dest for action in positionals] == ["workflow"]
    assert parser.parse_args([]).workflow is None

def test_the_command_calls_api_and_nothing_else() -> None:
    """`ARCHITECTURE.md`'s "Commands stay dumb", made mechanical, on the command whose subject is
    workflows.

    Two `api` names and no third, which is the shape of the deviation: the listing and the help are
    two functions because one of them imports a package and the other must never. A `registry.` or
    a `params.` appearing here would be this command learning what a workflow is - which is exactly
    what that rule forbids, in the file most tempted by it.
    """
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(workflows_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"list_workflows", "workflow_help"}

def test_the_command_starts_no_event_loop() -> None:
    """Both operations are sync, so this module has no `asyncio.run` and does not import `asyncio`.

    `cli/main.py` names this command as the reason the loop belongs to the command rather than the
    dispatch: an operation that awaits nothing must not be made to pretend otherwise. Read off the
    source, because a command that wrapped a sync call in a loop would work and still be wrong.
    """
    source = ast.parse(inspect.getsource(workflows_command))

    imported = {
        name.name
        for node in ast.walk(source)
        if isinstance(node, ast.Import)
        for name in node.names
    }

    assert "asyncio" not in imported

def test_neither_invocation_asks_for_a_registered_repository() -> None:
    """`list_workflows` takes neither - measured on both spellings of the command.

    `_never` raises, so a clause that called `invocation.registered` would fail every test in this
    file; this one says it in its own name, and covers the argument form too, because the half that
    loads a workflow is the half most likely to want a repository it has no business wanting.
    """
    assert _main("workflows") == 0
    assert _main("workflows", "tickets") == 0

# --- the tail, which this command may not carry --------------------------------------------------

def test_a_second_positional_is_refused_and_points_at_the_command_that_takes_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`_dispatch`'s tail refusal, reached by the fourth command to share it.

    One optional name is the grammar and two words are not one name. The message is asserted not to
    have kept its original wording: "read back from the record `agl run` wrote" was true of
    `resume` and `clear` and says nothing about a command addressed to no run at all, and the
    sentence had to become what is true of every caller - that only `agl run` names a workflow.
    """
    assert _main("workflows", "tickets", "probe") == 2

    captured = capsys.readouterr().err
    assert "probe" in captured
    assert "agl workflows <workflow>" in captured
