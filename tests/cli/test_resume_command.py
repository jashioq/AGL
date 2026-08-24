"""The grammar: `agl resume <label>`, and the two things it deliberately refuses to carry.

`tests/test_resume.py` drives `api.resume` from the library side, where every refusal §3.10 and
§3.11 ask for is asserted. This module drives the real entry point for what argv means, and there
are only three claims to make about a command whose whole grammar is one positional:

**It holds nothing else.** §3.10: "`resume` takes the label only; params come from `run.json`." The
pin is read off the parser object rather than off a sentence - one positional and no flag but `-h` -
which is `params.parser_for`'s own argument for being public and `cli/commands/run.py`'s for
returning its subparser.

**A tail is refused, and refused where the tail is produced.** `main` parses with
`parse_known_args`, once, for `run`'s sake, so an unrecognised argument on a `resume` line arrives
at the dispatch rather than at argparse's own error. `cli/main.py`'s `_dispatch` has said since 10.4
that the clause each label-taking command adds "will refuse a tail rather than carry one", and
`agl resume auth -r "..."` is the invocation that says why it matters: somebody expecting the flags
`agl run` took, whose answer is not "unrecognised argument" but where those flags went.

**It stays a dumb command** (§1.4). One `api` name, read off the module's own source, because the
repair is not that the file is short - it is that everything which decides anything is one call
away.

The bundle is substituted through `main`'s one seam and nothing is monkeypatched, exactly as
`tests/cli/test_main.py` does it: `compose=` is a keyword-only parameter whose default is the real
composition, so the suite hands in `container.fakes()` and an `Invocation` carrying entry points
this module constructs itself.
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
from agl.cli.commands import resume as resume_command
from agl.config import container, registry, sources
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.sdk.params import RefusingParser, arg
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
    """§3.3's example shape, so that `agl run flagged -n auth -r "add oauth"` has flags to store -
    which is the whole of what `agl resume auth` then does not have to be given."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)


# What the workflow was handed, once per invocation. Module level for `EntryPoint.load`'s reason: it
# imports a module and reads an attribute in it, so a workflow declared in a test is unreachable.
flagged_with: Final[list[FlaggedParams]] = []


@workflow(name="flagged", version="1.1", params=FlaggedParams)
async def flagged(run: Run[FlaggedParams]) -> None:
    """Records what it was given, which is what makes "the resume was handed the record's params"
    visible from the argv side without this module reading a store."""
    flagged_with.append(run.params)


def _point(name: str) -> EntryPoint:
    """§3.3's registration line, pointed at this module: a name, a `module:attr`, and a group."""
    return EntryPoint(name=name, value=f"{__name__}:{name}", group=registry.GROUP)


POINTS: Final = (_point("flagged"),)


def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment, seeded so `History` has a default ref and a commit to resolve."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})


def _main(harness: container.FakeServices, *argv: str) -> int:
    """One `agl` invocation, with this module's workflows in place of what is installed."""
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=lambda: (PROJECT, harness.services),
        settings=SETTINGS,
        cwd=ELSEWHERE,
        points=POINTS,
        ),
    )


def _resume_parser() -> RefusingParser:
    """The `resume` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return resume_command.declare(commands)


# --- the grammar, read off the parser -------------------------------------------------------------


def test_the_resume_parser_holds_one_positional_and_no_flags() -> None:
    """§3.10's sentence, read off the object: "`resume` takes the label only".

    Every argument the `run` parser holds is absent because the record already settled it - the
    workflow name, the base ref, and the workflow's own flags - so a flag appearing in this set is
    a decision the record was supposed to have made.
    """
    parser = _resume_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help"}
    assert positionals == ["label"]


def test_abbreviation_is_off_on_the_resume_subparser() -> None:
    """A subparser does not inherit `allow_abbrev` - `add_parser` builds a fresh `ArgumentParser`
    which reads the flag off its own arguments. It matters less here than on `run`, this parser
    declaring no long flag to be a prefix of, and it is written anyway: the reason a later stage
    would add one is that a flag appeared, and by then the abbreviating would already be on."""
    assert _resume_parser().allow_abbrev is False


def test_the_command_calls_exactly_one_api_function() -> None:
    """"Commands stay dumb" (§1.4), made mechanical: this module reaches `api` once, for `resume`.

    The same scan `tests/cli/test_run_command.py` makes of the run command, and the same argument:
    a second `api.` name appearing here is a use case moving back into the CLI.
    """
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(resume_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"resume"}


# --- end to end through argv ----------------------------------------------------------------------


def test_a_resume_runs_the_workflow_the_record_names_with_the_params_it_stored(
    tmp_path: Path,
) -> None:
    """The command end to end: `agl run flagged -n auth -r "add oauth" -c 4`, then `agl resume
    auth`.

    The second line names no workflow and carries no flag, and the workflow is nevertheless handed
    the same instance - which is §3.3's "persisted into `run.json`, which is why `agl resume auth`
    takes no flags" arriving through the real parser, the real dispatch and the real command.
    """
    flagged_with.clear()
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "add oauth", "-c", "4") == 0

    assert _main(harness, "resume", "auth") == 0

    assert flagged_with == [
        FlaggedParams(request="add oauth", concurrent=4),
        FlaggedParams(request="add oauth", concurrent=4),
    ]


def test_a_finished_resume_is_named_the_way_the_run_command_names_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One line, on stdout, quoting the label the way every other `agl` line quotes it.

    §3.10's refusal reads `run 'auth' already exists` and `agl run` says `run 'auth' finished`; this
    is that shape with the verb the operator typed, so a terminal full of `agl` output reads as one
    vocabulary and still says which command produced which line.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x") == 0
    capsys.readouterr()

    assert _main(harness, "resume", "auth") == 0

    assert capsys.readouterr().out == "resume 'auth' finished\n"


def test_resuming_a_label_with_no_record_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§3.10's symmetric refusal, through the handler: `NotFoundError` out of `api.resume`, resolved
    to 3 out of the one table, printed with nothing added but the program's name.

    A typo'd label is the case the verb exists to make loud, so the message is asserted to name the
    label and the command that would start one.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "resume", "auth") == 3

    captured = capsys.readouterr()
    assert captured.err == (
        "agl: run 'auth' does not exist - `agl run <workflow> -n auth` starts one.\n"
    )
    assert captured.out == ""


def test_a_label_the_filesystem_would_not_take_exits_two(tmp_path: Path) -> None:
    """`RunLabel` validates on the way in and its `InputError` is the same 2 `agl run` answers with.

    Refused by the command before `registered()` is called, which is the ordering
    `cli/commands/run.py` argues: somebody who typed `agl resume my/label` outside a registered
    repository is told about the label they typed.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "resume", "my/label") == 2


def test_no_label_at_all_exits_two(tmp_path: Path) -> None:
    """The positional is required: a bare `agl resume` is a usage error and not a default label."""
    harness = _fakes(tmp_path)

    assert _main(harness, "resume") == 2


# --- the tail, which this command may not carry ---------------------------------------------------


def test_a_workflow_flag_on_a_resume_line_is_refused_and_says_where_flags_went(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_dispatch`'s tail refusal, and the invocation it is written for.

    `agl resume auth -r "..."` is somebody expecting the flags `agl run` took, and `main` parses
    with `parse_known_args` - once, for `run`'s sake - so argparse hands the flag on rather than
    refusing it. The clause is what refuses it, at exit 2, and the message is asserted for the fact
    the reader needs next: the parameters came from the record, and a different run is how you get
    different ones.

    The record is asserted untouched afterwards because the refusal is `_dispatch`'s: it happens
    before `registered()` is called, so a resume refused this way has not resolved a repository,
    let alone read a store.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x") == 0
    flagged_with.clear()
    capsys.readouterr()

    assert _main(harness, "resume", "auth", "-r", "something else") == 2

    captured = capsys.readouterr()
    assert "-r" in captured.err
    assert "run.json" in captured.err or "record" in captured.err
    assert "agl run <workflow> -n <label>" in captured.err
    assert flagged_with == [], "a refused resume ran the workflow anyway"


def test_a_second_positional_is_refused_the_same_way(tmp_path: Path) -> None:
    """The other shape of a tail: one label is the grammar, and two words are not one label.

    Worth its own line because argparse's own answer to a surplus positional differs from its answer
    to an unknown flag, and `parse_known_args` collects both into the same tail - so this asserts
    that the clause covers what the parser did not consume rather than what looked like a flag.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "x") == 0

    assert _main(harness, "resume", "auth", "other") == 2


def test_the_run_command_still_carries_its_tail(tmp_path: Path) -> None:
    """The other half of the refusal, so that it is about `resume` and not about tails.

    `run` is the one verb whose line carries arguments AGL deliberately does not understand, and a
    `_dispatch` that refused every tail would break §1.2's whole repair. Asserted through the flag a
    workflow declares and the generic parser has never heard of.
    """
    flagged_with.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "flagged", "-n", "auth", "-r", "add oauth") == 0

    assert flagged_with == [FlaggedParams(request="add oauth", concurrent=3)]
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is not None
