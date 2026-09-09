"""The grammar: `agl run <workflow> -n <label> [workflow flags] [--from <ref>]`, and its seams.

`tests/cli/test_main.py` drives the entry point for its exit codes; this module drives it for what
argv means. Three things are pinned, and each of them is a defect in what came before or a decision
this grammar settles:

**The generic parser holds no workflow's flag.** `--max-concurrent` sat on the generic `run`
parser with the help text "how many tickets to work on at once", so every workflow paid for one
workflow's input and it then persisted into a shared record. The pin is read off the parser object -
its options, its one positional and its namespace - rather than off a sentence, which is
`params.parser_for`'s own argument for being public.

**`--from` is framework-level and not a workflow param**: every code-producing workflow needs one
and the framework needs it independently. So it is on the generic parser, it reaches `run.json`,
and its absence is the repository's default rather than a branch written into the CLI.

**Abbreviation is off, and a spelling this parser owns is refused where the workflow declares it.**
The first makes `--fro` a flag of its own rather than a way to write `--from`; the second is what
ended a defect this file used to pin as a decision - a workflow declaring `-n` was shadowed, loudly
where its field was required and in silence where it had a default, because the generic parser runs
first and the workflow's own never saw the flag. Both spellings now come from `agl.sdk.params`,
which is also where `arg()` refuses a field that claims one, and `RESERVED_FLAGS` is compared here
against the parser this command actually builds - so a flag added here and not to that set fails
the build instead of quietly becoming un-refused.
"""

import argparse
import ast
import asyncio
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl.adapters.uv.fake import FakeSyncer
from agl.cli import main
from agl.cli.commands import run as run_command
from agl.config import container, registry, sources
from agl.ports.home_layout import RunScope, workspace_dir
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.run import JsonValue
from agl.ports.sync import Syncer
from agl.ports.tree_layout import TreesRoot
from agl.sdk.params import RESERVED_FLAGS, RefusingParser, arg
from agl.sdk.workflow import Run, workflow

# `agl init` is the one command that reads `settings` and `cwd`, and no invocation below is one -
# but neither field is optional (`cli/main.py` argues why), so both carry a real value nothing here
# looks at. `/nowhere` is absolute, which is the whole of what `AglHome` insists on, and no file
# under it is ever opened: `read_settings` treats a missing `config.toml` as a file that said
# nothing.
ELSEWHERE: Final = Path("/nowhere")
SETTINGS: Final = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(ELSEWHERE)})

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

@dataclass(frozen=True)
class FlaggedParams:
    """The example params shape, which `agl run flagged -n auth -r "add oauth" -c 4` fills in."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)

@dataclass(frozen=True)
class PrefixParams:
    """A flag that is a proper prefix of `--from`: what abbreviation would have eaten."""

    fro: str = arg("--fro", help="a workflow's own flag, spelled like nobody else's")

# A workflow declaring a flag `agl run` owns, written out rather than declared here: `arg()` raises
# where it is read, so a class in this module would refuse at import and take the file's collection
# with it. That is the refusal under test, met the way an author meets it - in a file of their own.
RESERVING: Final = "reserving"

RESERVING_SOURCE: Final = '''from dataclasses import dataclass
from agl.sdk import Run, arg, workflow

@dataclass(frozen=True)
class Colliding:
    """A note the author wanted `-n` for, which is the run's own label flag."""

    note: str = arg("-n", "--name", default="unsaid")

@workflow
async def reserving(run: Run[Colliding]) -> None:
    """Never entered: the module raises while `EntryPoint.load` is importing it."""
'''

# What each workflow was handed. Module level for `EntryPoint.load`'s reason: it imports a module
# and reads an attribute in it, so a workflow declared inside a test function is unreachable.
flagged_with: Final[list[FlaggedParams]] = []
prefixed_with: Final[list[PrefixParams]] = []

@workflow
async def flagged(run: Run[FlaggedParams]) -> None:
    """Records what it was given, which is the whole of what these tests ask of a workflow."""
    flagged_with.append(run.params)

@workflow
async def prefixed(run: Run[PrefixParams]) -> None:
    """Records `--fro`, the flag `allow_abbrev=True` would have handed to `--from` instead."""
    prefixed_with.append(run.params)

def _point(name: str) -> EntryPoint:
    """A registration line, pointed at this module: a name, a `module:attr`, and a group."""
    return EntryPoint(name=name, value=f"{__name__}:{name}", group=registry.GROUP)

POINTS: Final = tuple(_point(name) for name in ("flagged", "prefixed"))

def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment, seeded so `History` has a default ref and a commit to resolve."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})

def _main(
    harness: container.FakeServices,
    *argv: str,
    syncer: Syncer | None = None,
    points: tuple[EntryPoint, ...] = POINTS,
) -> int:
    """One `agl` invocation, with this module's workflows in place of what is installed.

    The installer is a fake because `agl run` installs what the workspace declares on the way past:
    the field's own default would start uv on every invocation below, and `ELSEWHERE` is not a home
    anything may write to. `points` is a parameter for the one workflow that cannot live here - the
    module it is declared in raises while it is being imported, which is the whole of that test.
    """
    installer = FakeSyncer() if syncer is None else syncer
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=lambda: (PROJECT, harness.services),
            settings=SETTINGS,
            cwd=ELSEWHERE,
            points=points,
            syncer=lambda: installer,
        ),
    )

def _record(harness: container.FakeServices) -> dict[str, JsonValue]:
    """The run's record, asserted present: `run.json` is what the generic flags end up in."""
    record = asyncio.run(harness.services.store.read_record(SCOPE))
    assert record is not None, "no run.json was written for this run"
    return record

type _Commands = argparse._SubParsersAction[RefusingParser]

def _declared(declare: Callable[[_Commands], RefusingParser]) -> RefusingParser:
    """One subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return declare(commands)

def _options(parser: RefusingParser) -> set[str]:
    """Every option string a parser answers to, `argparse`'s own `-h`/`--help` among them."""
    return {flag for action in parser._actions for flag in action.option_strings}

# --- the generic parser, and what it deliberately does not hold ----------------------------------

def test_the_generic_parser_holds_three_arguments_and_no_workflows_flag() -> None:
    """Read off the object: `--max-concurrent` could not be added here by accident.

    Three arguments, one of them the positional reserved for the workflow name - "a workflow
    inventing a positional" is refused in `arg()` because this position is already spent - plus the
    `-h` every parser carries. A flag belonging to one workflow would show up in this set.
    """
    parser = _declared(run_command.declare)

    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert _options(parser) == {"-h", "--help", "-n", "--name", "--from"}
    assert positionals == ["workflow"]

def test_abbreviation_is_off_on_the_root_parser_and_on_the_subparser() -> None:
    """The decision, asserted where it is made twice - a subparser does not inherit the flag.

    `add_parser` constructs a fresh `ArgumentParser`, which reads `allow_abbrev` off its own
    arguments, so the root's choice reaches nothing. With it on, a workflow's `--fro`, `--nam` or
    `--hel` is eaten - value and all - by a generic flag it merely starts with.
    """
    assert main.parser().allow_abbrev is False
    assert _declared(run_command.declare).allow_abbrev is False

def test_a_workflows_flags_are_left_in_the_tail_and_never_in_the_namespace() -> None:
    """The composition of the two parsers, in one line of argv: what the generic side keeps, and
    what it hands over verbatim.

    The namespace is asserted whole rather than key by key - a fourth key would be the generic
    parser having learned something about a workflow - and the tail is asserted in order, because
    `-c 4` is a flag and its value and the workflow's parser reads them as a pair.
    """
    parsed, tail = main.parser().parse_known_args(
        ["run", "flagged", "-n", "auth", "-r", "add oauth", "-c", "4"]
    )

    assert vars(parsed) == {
        "command": "run", "workflow": "flagged", "label": "auth", "base_ref": None
    }
    assert tail == ["-r", "add oauth", "-c", "4"]

def test_the_command_calls_exactly_one_api_function() -> None:
    """`ARCHITECTURE.md`'s "Commands stay dumb", made mechanical: this module reaches `api` once,
    for `run`.

    `_cmd_clean` iterated worktrees, deleted branches and called `shutil.rmtree` past the `Store`
    port; `_cmd_init` did build-tool detection and TOML rendering in ~150 lines. The repair is not
    that this command is short - it is that everything which decides anything is one call away, so
    a second `api.` name appearing here is a use case moving back into the CLI.
    """
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(run_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"run"}

# --- a workflow's own flags --------------------------------------------------------------------

def test_a_workflows_flags_reach_the_workflow_and_its_record(tmp_path: Path) -> None:
    """One chain, end to end through argv: what was typed, what the workflow was handed, and what
    `run.json` holds - which is what makes `agl resume auth` take no flags."""
    flagged_with.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "add oauth", "-c", "4") == 0

    assert flagged_with == [FlaggedParams(request="add oauth", concurrent=4)]
    assert _record(harness)["params"] == {"request": "add oauth", "concurrent": 4}

def test_the_generic_flags_may_be_written_anywhere_on_the_line(tmp_path: Path) -> None:
    """`-n` before or after a workflow's flags, and the tail keeps its order either way.

    Worth pinning because `parse_known_args` collects unrecognised arguments in two places - as it
    walks the optionals and again from whatever is left - and a flag and its value separated by a
    generic flag is the arrangement where those two places could disagree.
    """
    flagged_with.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-r", "add oauth", "-n", "auth", "-c", "4") == 0

    assert flagged_with == [FlaggedParams(request="add oauth", concurrent=4)]

def test_a_flag_the_workflow_refuses_exits_two_from_the_workflows_own_parser(
    tmp_path: Path,
) -> None:
    """The tail is handed over unread, so the refusal comes from the only module that could give
    it: `sdk/params.py`, naming the program as `agl run flagged`, before anything runs."""
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x", "--nosuch") == 2

    assert asyncio.run(harness.services.store.read_record(SCOPE)) is None

# --- `--from`, which is the framework's and not any workflow's -----------------------------------

def test_from_is_a_framework_flag_and_lands_in_the_record(tmp_path: Path) -> None:
    """Base ref is a framework-level run parameter, not a workflow param.

    It is on the generic parser, so every workflow gets it and none declares it, and it reaches
    `run.json` beside the sha it resolved to rather than reaching the workflow's params at all.
    """
    flagged_with.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x", "--from", "main") == 0

    record = _record(harness)
    assert record["base_ref"] == "main"
    assert record["params"] == {"request": "x", "concurrent": 3}

def test_without_from_the_base_ref_is_the_repositorys_and_not_the_clis(tmp_path: Path) -> None:
    """No default is written into `add_argument`, and that is the decision.

    `_TRUNK = ("main", "master")` is the old preflight's version of it - a CLI deciding for a
    repository it had not looked at. `None` reaches `api.run`, which asks `History`, which is the
    one thing that can see the repository.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x") == 0

    assert _record(harness)["base_ref"] == asyncio.run(harness.services.history.default_ref())

# --- the flags this parser owns, which no workflow may declare -----------------------------------

def test_a_prefix_of_a_generic_flag_belongs_to_the_workflow_that_declared_it(
    tmp_path: Path,
) -> None:
    """`allow_abbrev=False`, from the far end: `--fro` is a spelling, not an abbreviation.

    This is the test the decision exists for. With abbreviation on, the generic parser matches
    `--fro` as an unambiguous prefix of `--from` and takes the value with it, and the workflow -
    which documents `--fro` and nothing else - is told its required parameter is missing.
    """
    prefixed_with.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "prefixed", "-n", "auth", "--fro", "mine") == 0

    assert prefixed_with == [PrefixParams(fro="mine")]
    assert _record(harness)["base_ref"] != "mine"

def test_an_abbreviation_of_a_generic_flag_is_not_a_way_to_spell_it(tmp_path: Path) -> None:
    """The same decision from the user's side: `--fro` is not `--from` for a workflow without it.

    Refused at exit 2 by the workflow's parser - which is where an unknown flag is refused - rather
    than silently meaning something the person did not type.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x", "--fro", "main") == 2

def test_the_reserved_set_is_every_option_string_this_parser_answers_to() -> None:
    """The seam the refusal rests on, read off the parser object rather than off a sentence.

    `sdk/params.py` cannot import a command - the layering runs the other way - so `RESERVED_FLAGS`
    lives there and `cli/commands/run.py` declares `-n/--name` and `--from` from it, which leaves
    `argparse`'s own `-h`/`--help` as the one part of the set nothing there constructs. This is what
    holds that part, and what makes an argument added to this command and not to the set a failure
    rather than a spelling that silently stopped being refused.

    `run` alone, and the other tail-less five are not an omission: `run` is the only command that
    hands a workflow argv at all. `agl resume` reads the parameters back out of the record and
    `main._no_tail` refuses anything else on that line, so its own `-h`/`--help` - the whole of what
    it owns, pinned in `tests/cli/test_resume_command.py` - is nobody's to collide with. Reserving
    the union would take a spelling away from every workflow the day `resume` grew a flag.
    """
    assert RESERVED_FLAGS == _options(_declared(run_command.declare))

def test_a_workflow_declaring_a_flag_agl_run_owns_refuses_the_run_that_named_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What the two shadowing tests here became, driven from where an author actually meets it.

    A required `-n` used to fail at exit 2 saying the flag the operator *had* typed was missing, and
    a defaulted one used to keep its default with nothing said on either stream. Both are gone in
    one place: `arg()` refuses the spelling, so the workflow's own module raises while
    `EntryPoint.load` is importing it - above the record, above the checkout, and naming the flag
    and the set it belongs to. `registry.load` catches `ImportError` and `AttributeError` and this
    is neither, so the `InputError` reaches `main` as itself and leaves on `InputError`'s own code.
    """
    harness = _fakes(tmp_path)
    written = tmp_path / "workspace"
    written.mkdir()
    (written / f"{RESERVING}.py").write_text(RESERVING_SOURCE, encoding="utf-8")
    sys.path.insert(0, str(written))
    # Not `_point`, whose value names *this* module: what has to be imported is the file above.
    declared = EntryPoint(name=RESERVING, value=f"{RESERVING}:{RESERVING}", group=registry.GROUP)

    status = _main(harness, "run", RESERVING, "-n", "auth", points=(declared,))

    assert status == 2
    assert "owns -n/--name" in capsys.readouterr().err
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is None

# --- what the command says when it worked --------------------------------------------------------

def test_a_finished_run_is_named_the_way_the_refusal_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal reads `run 'auth' already exists`; a run that finished says so alike.

    One line, on stdout, quoting the label the same way - so an operator reading a terminal full of
    `agl` output sees one vocabulary rather than two.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x") == 0

    assert capsys.readouterr().out == "run 'auth' finished\n"

# --- the install this command folded in ----------------------------------------------------------

def test_an_install_this_command_could_not_finish_stops_the_run_before_it_records_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`agl run` installs what the workspace declares, and a refusal is exit 6 and no run at all.

    There is no `agl sync` any more, so this is where an operator meets uv: the install is folded
    into the three commands that need one and is asked for by nobody. It is scripted at the
    workspace directory rather than unconditionally, which is what says the installer was pointed
    at that directory and not at the project file inside it or at `workflows/` below it - a sync
    asked for anywhere else would meet `FakeSyncer`'s unscripted answer and this run would finish.

    Nothing is recorded and the workflow is not entered, which places the install above both: a run
    that had written `run.json` first would leave a label somebody has to `agl clear` before they
    could retry the command that failed.
    """
    harness = _fakes(tmp_path)
    flagged_with.clear()
    installer = FakeSyncer()
    installer.answers(
        workspace_dir(SETTINGS.home), synced=False, status=2, output="error: no solution found\n"
    )

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x", syncer=installer) == 6

    assert "error: no solution found" in capsys.readouterr().err
    assert flagged_with == []
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is None
