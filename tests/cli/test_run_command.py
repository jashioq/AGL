"""The grammar: `agl run <workflow> -n <label> [workflow flags] [--from <ref>]`, and its seams.

`tests/cli/test_main.py` drives the entry point for its exit codes; this module drives it for what
argv means. Three things are pinned and each of them is a charge from Part 1 or a decision §3.9
settles:

**The generic parser holds no workflow's flag** (§1.2). `--max-concurrent` sat on the generic `run`
parser with the help text "how many tickets to work on at once", so every workflow paid for one
workflow's input and it then persisted into a shared record. The pin is read off the parser object -
its options, its one positional and its namespace - rather than off a sentence, which is
`params.parser_for`'s own argument for being public.

**`--from` is framework-level and not a workflow param** (§3.9): "every code-producing workflow
needs one and the framework needs it independently." So it is on the generic parser, it reaches
`run.json`, and its absence is the repository's default rather than a branch written into the CLI.

**Abbreviation is off, and flag collisions are documented rather than refused.** Both are decisions
`cli/commands/run.py` argues at length, and both have a cost that only a test can hold still: a
prefix of a generic flag belongs to the workflow that declared it, a colliding *required* flag fails
loudly at exit 2, and a colliding *defaulted* one silently keeps its default. The last of those is
the price of not loading a workflow to inspect its shape, and it is pinned so that a later stage
deciding to pay differently has to come here first.
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
from agl.cli.commands import run as run_command
from agl.config import container, registry
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.run import JsonValue
from agl.ports.tree_layout import TreesRoot
from agl.sdk.params import RefusingParser, arg
from agl.sdk.workflow import Run, workflow

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)


@dataclass(frozen=True)
class FlaggedParams:
    """§3.3's example shape, which `agl run flagged -n auth -r "add oauth" -c 4` fills in."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)


@dataclass(frozen=True)
class PrefixParams:
    """A flag that is a proper prefix of `--from`: what abbreviation would have eaten."""

    fro: str = arg("--fro", help="a workflow's own flag, spelled like nobody else's")


@dataclass(frozen=True)
class RequiredCollisionParams:
    """A workflow declaring `-n`, which the generic parser also spells. Required, so it is loud."""

    note: str = arg("-n", "--note", help="a note the workflow cannot run without")


@dataclass(frozen=True)
class DefaultedCollisionParams:
    """The same collision with a default, which is the half that goes quiet. See the docstring."""

    note: str = arg("-n", "--note", default="unsaid", help="a note the workflow can do without")


# What each workflow was handed. Module level for `EntryPoint.load`'s reason: it imports a module
# and reads an attribute in it, so a workflow declared inside a test function is unreachable.
flagged_with: Final[list[FlaggedParams]] = []
prefixed_with: Final[list[PrefixParams]] = []
required_with: Final[list[RequiredCollisionParams]] = []
defaulted_with: Final[list[DefaultedCollisionParams]] = []


@workflow(name="flagged", version="1.1", params=FlaggedParams)
async def flagged(run: Run[FlaggedParams]) -> None:
    """Records what it was given, which is the whole of what these tests ask of a workflow."""
    flagged_with.append(run.params)


@workflow(name="prefixed", version="1.1", params=PrefixParams)
async def prefixed(run: Run[PrefixParams]) -> None:
    """Records `--fro`, the flag `allow_abbrev=True` would have handed to `--from` instead."""
    prefixed_with.append(run.params)


@workflow(name="required", version="1.1", params=RequiredCollisionParams)
async def required(run: Run[RequiredCollisionParams]) -> None:
    """Never reached: its `-n` is required and the generic parser took the line's only one."""
    required_with.append(run.params)


@workflow(name="defaulted", version="1.1", params=DefaultedCollisionParams)
async def defaulted(run: Run[DefaultedCollisionParams]) -> None:
    """Reached, and holding its default, because the generic parser answered its `-n` first."""
    defaulted_with.append(run.params)


def _point(name: str) -> EntryPoint:
    """§3.3's registration line, pointed at this module: a name, a `module:attr`, and a group."""
    return EntryPoint(name=name, value=f"{__name__}:{name}", group=registry.GROUP)


POINTS: Final = tuple(_point(name) for name in ("flagged", "prefixed", "required", "defaulted"))


def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment, seeded so `History` has a default ref and a commit to resolve."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})


def _main(harness: container.FakeServices, *argv: str) -> int:
    """One `agl` invocation, with this module's workflows in place of what is installed."""
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=lambda: (PROJECT, harness.services), points=POINTS
        ),
    )


def _record(harness: container.FakeServices) -> dict[str, JsonValue]:
    """The run's record, asserted present: `run.json` is what the generic flags end up in."""
    record = asyncio.run(harness.services.store.read_record(SCOPE))
    assert record is not None, "no run.json was written for this run"
    return record


def _run_parser() -> RefusingParser:
    """The `run` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return run_command.declare(commands)


# --- the generic parser, and what it deliberately does not hold ----------------------------------


def test_the_generic_parser_holds_three_arguments_and_no_workflows_flag() -> None:
    """§1.2's charge, read off the object: `--max-concurrent` could not be added here by accident.

    Three arguments, one of them the positional §3.3 reserves for the workflow name - "a workflow
    inventing a positional" is refused in `arg()` because this position is already spent - plus the
    `-h` every parser carries. A flag belonging to one workflow would show up in this set.
    """
    parser = _run_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help", "-n", "--name", "--from"}
    assert positionals == ["workflow"]


def test_abbreviation_is_off_on_the_root_parser_and_on_the_subparser() -> None:
    """The decision, asserted where it is made twice - a subparser does not inherit the flag.

    `add_parser` constructs a fresh `ArgumentParser`, which reads `allow_abbrev` off its own
    arguments, so the root's choice reaches nothing. With it on, a workflow's `--fro`, `--nam` or
    `--hel` is eaten - value and all - by a generic flag it merely starts with.
    """
    assert main.parser().allow_abbrev is False
    assert _run_parser().allow_abbrev is False


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
    """"Commands stay dumb" (§1.4), made mechanical: this module reaches `api` once, for `run`.

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
    it: `sdk/params.py`, naming the program as `agl run flagged`. §3.3's "before anything runs"."""
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x", "--nosuch") == 2

    assert asyncio.run(harness.services.store.read_record(SCOPE)) is None


# --- `--from`, which is the framework's and not any workflow's -----------------------------------


def test_from_is_a_framework_flag_and_lands_in_the_record(tmp_path: Path) -> None:
    """§3.9: "Base ref is a framework-level run parameter, not a workflow param."

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

    `_TRUNK = ("main", "master")` is §1.2's charge in the old preflight - a CLI deciding for a
    repository it had not looked at. `None` reaches `api.run`, which asks `History`, which is the
    one thing that can see the repository.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x") == 0

    assert _record(harness)["base_ref"] == asyncio.run(harness.services.history.default_ref())


# --- flag collisions: the decision, and both halves of what it costs ------------------------------


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


def test_a_workflow_declaring_a_generic_spelling_is_shadowed_loudly_when_it_is_required(
    tmp_path: Path,
) -> None:
    """The collision decision's loud half, and the reason it is survivable.

    Neither `sdk/params.py` nor this layer refuses a workflow that declares `-n`: refusing would
    mean loading the workflow to look at its params, which is the first line of `api.run`
    re-implemented in a command, which is §1.4's charge. So the generic parser wins - it runs first
    - and the workflow's required flag is simply never given a value, which `sdk/params.py` refuses
    by name at exit 2 before anything runs. The user is told which flag went missing.
    """
    required_with.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "required", "-n", "auth") == 2

    assert required_with == []


def test_a_workflow_declaring_a_generic_spelling_keeps_its_default_when_it_has_one(
    tmp_path: Path,
) -> None:
    """The quiet half, which is the whole of what the decision costs. Pinned so it stays known.

    A colliding flag with a default cannot report that it was shadowed: `-n auth` was consumed by
    the generic parser, the workflow's parser never saw it, and `default=SUPPRESS` leaves the
    dataclass's own value in place. The run proceeds with `note="unsaid"`. A later stage that
    decides to spend a registry load on refusing collisions changes this test first.
    """
    defaulted_with.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "defaulted", "-n", "auth") == 0

    assert defaulted_with == [DefaultedCollisionParams(note="unsaid")]
    assert _record(harness)["label"] == "auth"


# --- what the command says when it worked --------------------------------------------------------


def test_a_finished_run_is_named_the_way_the_refusal_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§3.10's refusal reads `run 'auth' already exists`; a run that finished says so alike.

    One line, on stdout, quoting the label the same way - so an operator reading a terminal full of
    `agl` output sees one vocabulary rather than two.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x") == 0

    assert capsys.readouterr().out == "run 'auth' finished\n"
