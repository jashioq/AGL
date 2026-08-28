"""The grammar: `agl clear <label> [-f]`, and the two streams one invocation writes to.

`tests/test_clear.py` drives `api.clear` from the library side, where the traversal, the order and
`git branch -d`'s two answers are asserted. This module drives the real entry point for what argv
means, and there are four claims to make about it:

**It holds a label and one flag, and nothing else.** §3.10's line for this verb, read off the parser
object rather than off a sentence - which is `params.parser_for`'s own argument for being public and
`cli/commands/run.py`'s for returning its subparser.

**`-f` reaches `api.clear`.** The stage's acceptance criterion is about a flag changing an outcome,
so the pin is the outcome: the same run, cleared twice over, keeps its branch without the flag and
loses it with one. A test asserting that the parser has a `--force` would pass against a command
that never passed it on.

**A kept branch is a message and not a failure.** Exit 0, the finished line on stdout, the warning
on stderr - §3.8's "logs to stderr, data to stdout". A status of its own would make every wrapper
script treat a tidy-up decision as an error, and `ports/errors.py`'s table maps exceptions to codes
and holds no row for success.

**A tail is refused, and refused where the tail is produced.** `main` parses with
`parse_known_args`, once, for `run`'s sake, so an unrecognised argument on a `clear` line arrives at
the dispatch. 16.2 wrote that refusal for a grammar that is a label and nothing else; this command
has a flag on it legitimately, so what the helper says had to become true of both.

The bundle is substituted through `main`'s one seam and nothing is monkeypatched, exactly as
`tests/cli/test_main.py` and `tests/cli/test_resume_command.py` do it.
"""

import ast
import asyncio
import inspect
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.claude_code.fake import Conversation, Script
from agl.cli import main
from agl.cli.commands import clear as clear_command
from agl.config import container, registry, sources
from agl.ports.agent import AgentOutcome, Claude, StopReason
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot, run_branch
from agl.sdk.params import RefusingParser
from agl.sdk.roles import Role, role
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
BRANCH: Final = run_branch(LABEL)

SEEDED: Final = "src/a.txt"
WRITTEN: Final = "src/feature.py"


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, so every line below is AGL's own vocabulary."""


@role(model=Claude.SONNET)
def writing() -> Role:
    """An effect role: no reporting tool, so the step's whole purpose is that an agent wrote a file
    the `commit=` then records - which is what puts `agl/auth` ahead of the base ref."""
    return Role(name="write", instructions="leave some work behind")


@workflow(version="1.0")
async def working(run: Run[NoParams]) -> None:
    """One step that commits, so this run's branch is not contained in the ref it started from."""
    await run.step(writing(), commit="the work this run produced")


def _point(name: str) -> EntryPoint:
    """§3.3's registration line, pointed at this module: a name, a `module:attr`, and a group."""
    return EntryPoint(name=name, value=f"{__name__}:{name}", group=registry.GROUP)


POINTS: Final = (_point("working"),)


def _writing(conversation: Conversation) -> None:
    """Write one file into the checkout the task names. The script's own code, not the adapter's."""
    target = conversation.task.workspace / WRITTEN
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"work an agent left behind\n")


def _agent() -> Script:
    """An agent that leaves a file behind and reports nothing."""

    async def _script(conversation: Conversation) -> AgentOutcome:
        _writing(conversation)
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script


def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment, seeded so `History` has a default ref and a commit to resolve."""
    return container.fakes(
        TreesRoot(tmp_path / "trees"), files={SEEDED: b"one\n"}, claude=_agent()
    )


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


def _clear_parser() -> RefusingParser:
    """The `clear` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return clear_command.declare(commands)


def _merged(harness: container.FakeServices) -> None:
    """Move the base ref up to the run's branch: the world in which the work has landed."""
    tip = harness.repository.tip(BRANCH)
    assert tip is not None, "the run left no branch, so there is nothing to move the base ref to"
    harness.repository.move("main", tip)


# --- the grammar, read off the parser -------------------------------------------------------------


def test_the_clear_parser_holds_one_positional_and_the_force_flag() -> None:
    """§3.10's line for this verb, read off the object: `agl clear <label> [-f]`.

    Both spellings of the flag, because `-f` is what an operator types and `--force` is what a
    script does, and §3.10 writes the semantics as `git branch -d` versus `-D` - which is git's own
    short spelling and the reason this one is not `-F` or `--yes`.
    """
    parser = _clear_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help", "-f", "--force"}
    assert positionals == ["label"]


def test_the_force_flag_defaults_to_off() -> None:
    """The asymmetry §3.10 states runs one way: a retained branch costs a stale ref, a deleted one
    costs the entire run. A destructive default is that asymmetry ignored, and `store_true` is what
    makes the safe answer the one an operator gets by not saying anything."""
    parsed = _clear_parser().parse_args(["auth"])

    assert parsed.force is False


def test_abbreviation_is_off_on_the_clear_subparser(tmp_path: Path) -> None:
    """A subparser does not inherit `allow_abbrev` - `add_parser` builds a fresh `ArgumentParser`
    which reads the flag off its own arguments.

    It is load-bearing here in a way it is not on `agl resume`: this parser declares a long flag, so
    with abbreviation on `--for` and `--forc` would both be accepted spellings of the one flag in
    AGL that deletes something. So the property is asserted twice - off the parser, and through the
    real entry point, where `--for` has to come out as a refusal rather than as a forced clear.
    """
    assert _clear_parser().allow_abbrev is False

    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0

    assert _main(harness, "clear", "auth", "--for") == 2
    assert harness.repository.tip(BRANCH) is not None, (
        "`--for` was read as `--force` and deleted an unmerged branch"
    )


def test_the_command_calls_exactly_one_api_function() -> None:
    """"Commands stay dumb" (§1.4), made mechanical - and this is the command that charge is about.

    §1.4 names `_cmd_clean` for iterating worktrees, deleting branches and calling `shutil.rmtree`
    past the `Store` port. The same scan `tests/cli/test_run_command.py` and
    `tests/cli/test_resume_command.py` make, and a second `api.` name appearing here is that use
    case moving back into the CLI in the one place it was charged with living.
    """
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(clear_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"clear"}


# --- end to end through argv ----------------------------------------------------------------------


def test_a_clear_takes_the_run_away_and_names_it_the_way_the_others_do(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One line, on stdout, quoting the label the way every other `agl` line quotes it.

    §3.10's refusal reads `run 'auth' already exists`, `agl run` says `run 'auth' finished` and
    `agl resume` says `resume 'auth' finished`; this is that shape with the verb the operator typed.
    Nothing on stderr, because this run's work is in the base ref and there is nothing to warn
    about - which is what makes the test below about a warning rather than about a banner.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0
    _merged(harness)
    capsys.readouterr()

    assert _main(harness, "clear", "auth") == 0

    captured = capsys.readouterr()
    assert captured.out == "clear 'auth' finished\n"
    assert captured.err == ""
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is None
    assert harness.repository.tip(BRANCH) is None


def test_an_unmerged_branch_is_kept_and_said_on_stderr_at_a_zero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stage's acceptance criterion through argv: "`clear` on an unmerged branch warns and
    keeps it".

    Three things at once, and each is a separate way to get this wrong: the status is 0, because a
    kept branch is a decision rather than a failure and `ports/errors.py` has no row for success;
    the finished line is still on stdout, because the command did what it was asked; and the warning
    is on stderr, which is §3.8's "logs to stderr, data to stdout" - a script reading `agl clear`'s
    output should not have to filter a diagnostic out of what it asked for.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0
    capsys.readouterr()

    assert _main(harness, "clear", "auth") == 0

    captured = capsys.readouterr()
    assert captured.out == "clear 'auth' finished\n"
    assert BRANCH in captured.err and "-f" in captured.err
    assert harness.repository.tip(BRANCH) is not None, (
        "the branch was deleted although the base ref does not contain it yet"
    )
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is None, (
        "the run's records survived a clear that was only supposed to keep its branch"
    )


@pytest.mark.parametrize("flag", ["-f", "--force"])
def test_the_force_flag_reaches_api_clear(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    """"`-f` deletes" - the other half of the criterion, and the assertion is the outcome.

    The same run and the same command as the test above with one word added, so what is being
    asserted is that the word travelled: a parser that declared the flag and a command that never
    passed it on would satisfy every test about the grammar and none about this.

    Both spellings, because `-f` is what a person types and `--force` is what a script writes, and
    an `add_argument` that lost one of them would be found by nothing else.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0
    capsys.readouterr()

    assert _main(harness, "clear", "auth", flag) == 0

    captured = capsys.readouterr()
    assert captured.out == "clear 'auth' finished\n"
    assert captured.err == "", "a forced clear kept nothing and warned about it anyway"
    assert harness.repository.tip(BRANCH) is None, (
        f"`{flag}` is `git branch -D` and the branch is still there, so the flag did not reach "
        f"`api.clear`"
    )


def test_clearing_a_label_with_no_record_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`NotFoundError` out of `api.clear`, resolved to 3 out of the one table, printed with nothing
    added but the program's name.

    A typo'd label is what this refusal is for - §3.10 keeps `run` and `resume` as separate verbs
    so that a mistyped one is loud, and a `clear` that shrugged at a name nobody used would be the
    one command where a typo says "done".
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "clear", "auth") == 3

    captured = capsys.readouterr()
    assert captured.err == "agl: run 'auth' does not exist - there is nothing to clear.\n"
    assert captured.out == ""


def test_a_label_the_filesystem_would_not_take_exits_two(tmp_path: Path) -> None:
    """`RunLabel` validates on the way in and its `InputError` is the same 2 `agl run` answers with.

    Refused by the command before `registered()` is called, which is the ordering
    `cli/commands/run.py` argues: somebody who typed `agl clear my/label` outside a registered
    repository is told about the label they typed.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "clear", "my/label") == 2


def test_no_label_at_all_exits_two(tmp_path: Path) -> None:
    """The positional is required: a bare `agl clear` is a usage error and not a default label.

    Sharper here than on `agl resume`, this being the destructive verb: a `clear` that defaulted to
    anything would delete something nobody named.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "clear") == 2


# --- the tail, which this command may not carry ---------------------------------------------------


def test_a_workflow_flag_on_a_clear_line_is_refused_and_says_where_flags_went(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_dispatch`'s tail refusal, reached by the second command to share it.

    `agl clear auth -r "..."` is somebody expecting the flags `agl run` took, and `main` parses with
    `parse_known_args` - once, for `run`'s sake - so argparse hands the flag on rather than refusing
    it. The clause refuses it at exit 2, and the record is asserted untouched afterwards because the
    refusal happens before `registered()` is called: a clear refused this way has not resolved a
    repository, let alone deleted anything.

    The message is asserted not to have kept 16.2's wording. "takes a label and nothing else" was
    exact while `resume` was the only caller and is false of a grammar with `-f` in it, so the one
    helper says what is true of both instead of forking into two sentences kept in agreement by
    nobody.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0
    capsys.readouterr()

    assert _main(harness, "clear", "auth", "-r", "something else") == 2

    captured = capsys.readouterr()
    assert "-r" in captured.err
    assert "record" in captured.err
    assert "agl run <workflow> -n <label>" in captured.err
    assert "a label and nothing else" not in captured.err
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is not None, (
        "a refused clear took the run away anyway"
    )
    assert harness.repository.tip(BRANCH) is not None


def test_a_second_positional_is_refused_the_same_way(tmp_path: Path) -> None:
    """The other shape of a tail: one label is the grammar, and two words are not one label.

    Worth its own line because argparse's own answer to a surplus positional differs from its answer
    to an unknown flag, and `parse_known_args` collects both into the same tail.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0

    assert _main(harness, "clear", "auth", "other") == 2
