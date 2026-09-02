"""The grammar: `agl clear <label>`, and the one stream an invocation that worked writes to.

`tests/test_clear.py` drives `api.clear` from the library side, where the traversal, the order and
the unconditional deletion are asserted. This module drives the real entry point for what argv
means, and there are four claims to make about it:

**It holds a label and nothing else.** The line for this verb, read off the parser object rather
than off a sentence - which is `params.parser_for`'s own argument for being public and
`cli/commands/run.py`'s for returning its subparser. There is no flag to declare: `clear` takes the
whole run away and has nothing left to be asked twice about.

**What `api.clear` answers with reaches stdout.** The command's whole job past the call is to turn a
`Cleared` into lines, so the pin is the lines: the branch this run left is named on stdout, in the
listing, by an invocation that also deleted it. A test asserting only that the run went would pass
against a command that printed nothing at all.

**A clear that worked writes nothing to stderr.** Exit 0 and one block on stdout - logs to stderr,
data to stdout - so a script reading `agl clear`'s output gets what it asked for and no diagnostic
mixed into it. There is no decision for `clear` to report and so nothing here is a warning: what
reaches stderr is a refusal, and a refusal does not carry an exit status of 0.

**A tail is refused, and refused where the tail is produced.** `main` parses with
`parse_known_args`, once, for `run`'s sake, so an unrecognised argument on a `clear` line arrives at
the dispatch. The refusal is one sentence shared by both verbs that reach it, and it is worded for
neither of their grammars in particular - which is what the assertion in that test is about.

**`clear.py` is the third caller of the shared `_said`.** `run.py`, `resume.py` and `clear.py` all
read one string off a namespace and refuse the same way when the parser hands back something else,
so one helper in `cli/commands/__init__.py` says it once and takes the verb's `NAME`. A command
declaring a flag would need a second reader beside it and a refusal naming both kinds, which is a
sentence that helper cannot say without a parameter whose only value is that clause - and none of
the three does. `workflows.py`'s `_perhaps` stays out on its own reason: it returns `str | None`, so
it is a different function rather than a fourth copy.

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
    """A registration line, pointed at this module: a name, a `module:attr`, and a group."""
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

def test_the_clear_parser_holds_one_positional_and_no_flags_at_all() -> None:
    """The line for this verb, read off the object: `agl clear <label>`.

    `-f` was the one flag this parser ever declared, and it named the only question `clear` used to
    ask - whether the run's own branch could go. Nothing asks it now, so the assertion is that the
    option set is `argparse`'s own and nothing of AGL's has been added back beside it.
    """
    parser = _clear_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help"}
    assert positionals == ["label"]

def test_abbreviation_is_off_on_the_clear_subparser(tmp_path: Path) -> None:
    """A subparser does not inherit `allow_abbrev` - `add_parser` builds a fresh `ArgumentParser`
    which reads the flag off its own arguments.

    `--help` is the only long option left to abbreviate, and that is what makes this worth keeping
    rather than deleting with the flag that motivated it: with abbreviation on, `--hel` on the one
    destructive verb prints a help screen and exits 0, so a mistyped line reads as a successful one.
    Asserted twice - off the parser, and through the real entry point, where the mistyped flag has
    to come out as the tail refusal.
    """
    assert _clear_parser().allow_abbrev is False

    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0

    assert _main(harness, "clear", "auth", "--hel") == 2
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is not None, (
        "a mistyped flag was absorbed and the run was taken away anyway"
    )

def test_the_command_calls_exactly_one_api_function() -> None:
    """`ARCHITECTURE.md`'s "Commands stay dumb", made mechanical - and this is the command the rule
    is about.

    The command this replaces iterated worktrees, deleted branches and called `shutil.rmtree` past
    the `Store` port. The same scan `tests/cli/test_run_command.py` and
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
    """The finished line, on stdout, quoting the label the way every other `agl` line quotes it.

    The refusal for a taken label reads `run 'auth' already exists`, `agl run` says `run 'auth'
    finished` and `agl resume` says `resume 'auth' finished`; this is that shape with the verb the
    operator typed. The run is arranged as merged, so that what the listing under it holds is the
    same two lines a merged run and an unmerged one both produce - which is the point of the test
    below.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0
    _merged(harness)
    capsys.readouterr()

    assert _main(harness, "clear", "auth") == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "clear 'auth' finished\n"
        "branches gone: agl/auth\n"
        "worktrees gone: _base\n"
    )
    assert captured.err == ""
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is None
    assert harness.repository.tip(BRANCH) is None

def test_a_clear_lists_the_worktrees_and_branches_it_took_away_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The acceptance criterion through argv: an unmerged branch goes, and the line saying so is the
    only record an operator gets of what went.

    The same run as the test above with the base ref left where it was, so the branch is not
    contained and the output is asserted byte for byte against that same block: the listing is what
    `clear` did rather than what it decided, and it does not vary with the world. Three things at
    once, and each is a separate way to get this wrong - the status is 0, because taking a run away
    is what was asked for; the listing names `agl/auth`, because a deletion nobody is told about is
    the failure this command used to have; and stderr is empty, which is the split, logs to stderr
    and data to stdout.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0
    capsys.readouterr()

    assert _main(harness, "clear", "auth") == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "clear 'auth' finished\n"
        "branches gone: agl/auth\n"
        "worktrees gone: _base\n"
    )
    assert BRANCH in captured.out
    assert captured.err == ""
    assert harness.repository.tip(BRANCH) is None, (
        "the branch the listing named as taken away is still there"
    )
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is None, (
        "the run's records survived a clear that reported taking everything"
    )

def test_the_force_flag_a_script_still_carries_is_refused_rather_than_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`-f` was the spelling every wrapper script and every operator's memory holds, and it is gone.

    Refused and not absorbed, which is the half worth pinning: `main` parses with
    `parse_known_args`, so a flag no subparser declares reaches `_dispatch` as a tail rather than
    raising there and then, and a `_no_tail` that let it through would have made `agl clear auth -f`
    quietly do what it now does anyway. That is the one shape of this change nobody would notice
    going wrong, because the clear it silently performed would be the right one.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "working", "-n", "auth") == 0
    capsys.readouterr()

    assert _main(harness, "clear", "auth", "-f") == 2

    assert "-f" in capsys.readouterr().err
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is not None, (
        "the run was taken away by a line that named a flag `clear` no longer has"
    )

def test_clearing_a_label_with_no_record_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`NotFoundError` out of `api.clear`, resolved to 3 out of the one table, printed with nothing
    added but the program's name.

    A typo'd label is what this refusal is for - `run` and `resume` are separate verbs so that a
    mistyped one is loud, and a `clear` that shrugged at a name nobody used would be the one
    command where a typo says "done".
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

    The message is asserted not to say "takes a label and nothing else", which is true of both
    callers today and is exactly why it may not be the wording: a helper two verbs share cannot be
    phrased for the grammar they currently happen to agree on, or the next flag either of them
    declares makes it a lie in the one place nobody looks.
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
