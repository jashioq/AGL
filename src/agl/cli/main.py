"""The `agl` console entry point: argv in, one composition, one exit code out.

§1.4 is what this file answers, and the charge is worth quoting rather than paraphrasing:
`Git(Path.cwd())` was constructed **four times**, once per command, and `ClaudeRunner`, `FileStore`,
`RichTerminal` and the whole `RunContext` were assembled **twice**, duplicated between `_cmd_run`
and `_cmd_resume`. Below, `sources.resolve` is called once; `Path.cwd()` is written once and
`container.real` is called once, both inside a callable that a command invokes if - and only if - it
is a command addressed to a repository. `cli.py` reached 546 lines because every command re-derived
the world before doing its work; what replaces it is a parser, a handler, and a call.

## What this module does, in order, and why that is the order

Build the generic parser, parse argv, compose the invocation, dispatch, and turn whatever leaves the
dispatch into a status. **argv is understood before anything is resolved**: `agl run` with no
workflow name answers with a usage line rather than with "you are not inside a registered
repository", so a person who typed the command wrong is told what they typed wrong, wherever they
typed it. It also means `agl -h` reads no file and builds no adapter.

`main` **returns** its code on every path and never calls `sys.exit`; the console-script wrapper
`pyproject.toml` generates is what exits. Taking argv as an argument rather than reading `sys.argv`
is the other half of the same decision: the pair is what lets the suite drive the real entry point
with the real parser and read the real code, which is the whole of §1.5's "nothing can script
against AGL" read as a test rather than as a complaint. `argv=None` is handed straight to
`argparse`, whose own default is `sys.argv[1:]`, so the fallback is stated in exactly one place and
it is not this one.

## Composition is per-command (§3.10), so this module resolves settings and nothing else

"`main.py` resolves settings and dispatches; each operation then resolves its own prerequisites.
`run`, `resume` and `clear` resolve a project and build a container; `init` takes settings alone;
`list_workflows` takes neither." Stage 10 wrote it the other way round - the project resolved and
the container built *before* the dispatch chose a command - which was correct while `run` was the
only verb and wrong the moment `init` exists. `init` writes the very project file a container needs
in order to be constructible, so composing before dispatching makes it unreachable in principle
rather than merely awkward, and it makes `agl workflows` demand a registered repository in order to
list what is merely installed.

The repair is deliberately not a branch. A `_compose` that read `parsed.command` and resolved this
much for one verb and that much for another would put per-command knowledge in the one function that
must not hold any, and every command added after it would edit that function. Instead `_compose`
resolves settings and returns a **thunk**: `Invocation.registered` is a callable that resolves the
project and builds the container *when called*, and the command's own clause is what calls it.
`run`, `resume` and `clear` call it; `init` and `workflows` do not. That is the whole of "each
operation resolves its own prerequisites" - the command supplies one bit, whether it needs a
repository, and learns nothing about what the answer is made of, which is what keeps it as dumb as
§1.4 requires.
`cli/commands/__init__.py` holds the `Registered` alias and argues why it lives in the package both
commands already import through rather than on either of them.

## `Path.cwd()` is written once, and 16.4 is where that stopped being free

It used to sit inside the thunk, which was the right place while `_registered` was its only reader:
a command with no project to resolve never invoked it. `agl init` is the second reader - it detects
its own git root, and §3.10 has it run in exactly the repository no project file names yet - and
`api.init` takes a `cwd: Path` rather than reading one, for the three reasons `api.py` gives. So it
is read **here**, once, before either destination: `_compose` reads it, `Invocation` carries it,
`_registered` receives it, and the `init` clause hands it on. The alternative was a second
`Path.cwd()` in the `init` path, and the first line of this docstring is a charge about a value
being constructed four times. Two is where four starts. `tests/cli/test_main.py` scans every module
under `src/` for the expression and counts one.

## The seam: `Invocation`, and why the composition is a parameter with a real default

Everything below the parser needs five things - the settings, the directory this was typed in, how
to put a question to whoever typed it, the workflows this invocation can reach, and, for the
commands addressed to a repository, its ports and the project they serve. Every one of them is an
answer about the machine AGL is running on, and `_compose` is the impure step that asks them: the
environment through `sources.resolve`, and the working directory. The last two are deferred - the
project and the container to `_registered`, when a command asks for them, and what is installed to
`api`'s own `points=None`, which is `registry.installed()`.

`compose=` is a keyword-only parameter defaulting to `None`, meaning that one. It is the seam
`api.run` already established for `points=` and it is spelled the same way deliberately - "the
alternative was for callers above to monkeypatch a module attribute to test anything, which is a
seam too, without a signature". A suite substituting `container.fakes()` here reaches the real
parser, the real dispatch and the real handler, and target #8's all-fakes bundle stops being a thing
only a library caller can have.

Being a *callable* rather than a value is load-bearing twice: it is what keeps the composition
inside the `try`, so a malformed setting leaves as an exit code rather than as a traceback, and it
is what lets a test assert that composing never happened at all for an invocation argv refused. The
same argument covers `registered`, one layer further in and for the refusal that moved there: an
unregistered repository raises `NotFoundError` inside a command inside that same `try`, and the
handler answers 3 for it with `config/toml_file.py`'s own sentence naming `agl init`.

## The generic parser learns nothing about any workflow

§1.2's charge is `--max-concurrent` sitting on the *generic* `run` parser with the help text "how
many tickets to work on at once": one workflow's input, paid for by every workflow, and then
persisted into a shared record. So the parser built here holds `agl`'s own vocabulary and no
workflow's - the command name, and (in `cli/commands/run.py`) the workflow name, `-n/--name` and
`--from`. Everything it does not recognise is carried through untouched to `api.run`, which hands it
to `sdk/params.py`, the only module that knows a workflow's flags. `parser()` is public for the
reason `params.parser_for` is: a parser can be inspected, and "the generic parser holds no
workflow's flag" is a property a test can read off it rather than a sentence.

**`allow_abbrev=False`, on the root parser and on every subparser.** With abbreviation on, argparse
matches any unambiguous *prefix* of a long flag, and the flags it would match against are the
generic ones - so a workflow declaring `--fro`, `--nam` or `--hel` would have its flag silently
eaten by `--from`, `--name` or `--help`, value and all, and the workflow would be told its required
parameter was missing. The failure is invisible in the direction that matters: the user typed the
flag their workflow documents and another parser answered. `sdk/params.py` disabled it on the
workflow's side already, in one sentence that applies whole here - "an abbreviation is a spelling
nobody wrote down, which stops working the day a second flag makes it ambiguous".

## The handler, and the ordering §3.1 makes a stage-10 acceptance criterion

`Stop` descends from `AglError`, so a bare `except AglError` above it swallows a deliberate end and
reports 6 or 70 where the contract promises 7. The three clauses below are therefore in one order
and only one, and each renders differently on purpose:

  * `Stop` - **stdout, no prefix, no traceback.** A run that ended deliberately did not fail, and
    printing it as a failure is the mistake the ordering exists to prevent. This is also what makes
    the ordering *observable*: `exit_status` answers 7 from the table whichever clause caught it, so
    an outcome-only test cannot fail on a swap, while a test reading stdout can.
  * `AglError` - **stderr, prefixed `agl:`, no traceback.** A refusal is the message, and every one
    a user can provoke carries a sentence written where the facts were.
  * `Exception` - **stderr, with the traceback, and a sentence saying it is ours.** §1.5's charge is
    that `_cmd_run` ended in a bare `except Exception` rendering any bug as `error: <str>`; the fix
    is not to stop catching but to stop hiding. `cli/exit_codes.py` argues why this is 70.

`KeyboardInterrupt` is deliberately unanswered and there is no `BaseException` arm. `exit_status`
takes `Exception`, so writing one would not typecheck, and `cli/exit_codes.py`'s docstring gives the
reason at length: a Ctrl-C is the operator taking the process back, and the faithful end is to die
of the signal rather than to exit with a number that resembles it. `SystemExit` is left alone for
the same structural reason and one practical one - `-h` exits 0 through it, and must keep doing so.

**No number is written in this file.** Every arm resolves through `exit_status`, and success is the
command's to return, because success is not an entry in `ports/errors.py`'s table and must not
become one. `tests/cli/test_main.py` scans this module's source for an integer literal, the way
`tests/cli/test_exit_codes.py` scans that one.

## The event loop is started once, and below here

`api.py` is async and starts no loop, deliberately: a library that started one could not be called
from inside one, which is what 16.5's harness and every `pytest.mark.asyncio` test do. The loop
therefore belongs to the edge, and the edge is either this module or the command. It is the command,
so that `agl workflows` and `agl init` - whose operations are sync, because they await nothing - are
not made to pretend otherwise by a dispatch that awaits everything. Three commands start a loop and
two do not, which is a fact each command states in its own file and this module never asks about.

## All five verbs exist, and 16.4 is what made that true

§3.10's grammar is five lines and there are five clauses below. The dispatch has been written
against that whole surface since 10.4 - `api.py` declared the signatures and this module grew one
clause per command as each was built, rather than a stub that parsed and then refused, which would
have been a grammar guessed a stage early. `_dispatch`'s own refusal is `InternalError`: argparse
admits only the names declared here, so arriving with another one is AGL's bug and not the caller's
mistake.

The clauses differ in exactly what §3.10's per-command composition says they should. `run`, `resume`
and `clear` take `registered`; `init` takes the settings, the directory and the ask; `workflows`
takes neither a project nor settings. `points` stops at the three that resolve a workflow name -
`clear` loads none, and `init` has none to load.

**The tail belongs to `run` alone, and 16.2 is where that stopped being a sentence.** `run` is the
only verb whose line carries arguments AGL deliberately does not understand, so every other clause
refuses what the generic parser did not recognise instead of carrying it. The refusal is written
here, beside the `parse_known_args` that produced the tail, rather than in each command: a command
that had to be handed a tail in order to refuse it would need a parameter for the thing it has no
use for, and none of the four takes an `argv` at all for exactly that reason.

16.3 generalised the helper rather than forking it, and 16.4 had to generalise what it *says* for
the same reason. 16.2 wrote it as "this command takes a label and nothing else", which `agl clear
<label> [-f]` made false; 16.3 rewrote it around the record a run's arguments are read back from,
which `agl init` and `agl workflows` make false in turn, neither being addressed to a run at all.
What is true of all four is about `agl run` rather than about them: it is the only command that
names a workflow, and a workflow's flags are the only arguments AGL does not understand. One
sentence, four callers, and the signpost to `agl workflows <workflow>` in it - which is where a
person who typed a workflow's flag on the wrong line finds out what that workflow takes.
"""

import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from traceback import print_exception
from typing import Final

from agl.api import Ask
from agl.cli import commands
from agl.cli.commands import clear as clear_command
from agl.cli.commands import init as init_command
from agl.cli.commands import resume as resume_command
from agl.cli.commands import run as run_command
from agl.cli.commands import workflows as workflows_command
from agl.cli.exit_codes import exit_status
from agl.config import container, sources
from agl.config.schema import Settings
from agl.ports.errors import AglError, InputError, InternalError, Stop
from agl.ports.ids import ProjectName
from agl.sdk._engine.services import Services
from agl.sdk.params import RefusingParser

__all__ = ["Compose", "Invocation", "main", "parser"]

# The name the parser prints and the handler prefixes with. One string, because a usage line and an
# error line disagreeing about what the program is called is a small thing that reads as a bug.
_PROGRAM: Final = "agl"

# Where `add_subparsers` puts the chosen command's name. Read once, in `_dispatch`.
_COMMAND: Final = "command"

_DESCRIPTION: Final = "Run AI agent workflows against a code repository."

# The one sentence a traceback needs above it, so that the reader knows whose bug they are holding.
_OUR_BUG: Final = (
    "that traceback is AGL's own bug and not something you did wrong. An adapter is meant to "
    "translate what it catches into an `agl.ports.errors` class at its boundary, and one did not - "
    "so nothing above it could report the failure in words. Please report it with the lines above"
)


@dataclass(frozen=True, slots=True)
class Invocation:
    """What one `agl` invocation runs on: how to reach a repository, and the workflows it can see.

    The result of the composition step, and the whole of what a command is handed besides its own
    arguments. Frozen for `Services`' reason: it is what this invocation was assembled with, and two
    halves of a dispatch disagreeing about which store they were given is not a state worth having.

    **`settings` and `cwd` arrived at 16.4, with `init`.** Until then no command read either: `run`
    reads its settings only through the ports the container built out of them, and the working
    directory travelled inside `registered`'s thunk because `_registered` was its only reader. `agl
    init` is the second reader of both - it takes `Settings` because it writes a file under
    `AGL_HOME`, and a `cwd` because §3.10 has it find its own git root and `api.py` argues why that
    is a parameter rather than an ambient read. So the two fields are here beside their readers and
    in the deliverable that produced them, which is what the sentence they replaced promised.

    Neither is optional, and that is deliberate. A `Settings | None` would be a field two of five
    clauses narrow every time, and a `cwd` defaulted to anything would be a second place the process
    could be asked where it is standing.
    """

    registered: commands.Registered
    """How to reach a registered repository: called by the clause of a command that needs one, and
    by nothing in this module. Deferred rather than resolved, because `agl init` writes the project
    file this would look for and `agl workflows` never looks for it - see the module docstring.

    It answers with a `ProjectName` and not a `config.schema.Project`, because that is the whole of
    what `api` takes and it says why: the rest of a `Project` has already been spent by the
    container in constructing the ports handed back beside it."""

    settings: Settings
    """What this installation is configured with, resolved once by `sources.resolve`. Read by the
    `init` clause alone: the other four reach configuration through the ports built out of it, and
    `agl init` is the command that runs where no container can be built."""

    cwd: Path
    """The directory this invocation was typed in - the one place in the process `Path.cwd()` is
    read, carried rather than re-asked. `_registered` resolves the project from it and `agl init`
    finds its git root in it; see the module docstring for why that is one read and not two."""

    points: Iterable[EntryPoint] | None = None
    """The `agl.workflows` entry points to resolve a workflow name against, or `None` for what is
    installed. `api.run` declares this seam and this field is it, threaded one layer up so argv can
    reach it: `None` is what every real invocation means, and every real invocation passes it."""

    ask: Ask = input
    """How `agl init` puts its one question to whoever is running it. `api.init` requires one and
    holds no default, so that `api` - a library - cannot read a person's stdin by omission; this is
    where the real answer is written, at the edge, where `print` already lives.

    `input` and not a terminal. `Terminal` is a port, `init` is composed without one on purpose, and
    `container.real` would build a `RichTerminal` that takes the console over and starts a redraw
    loop - which is a great deal of machinery for one line of text, on the one command that runs
    before AGL knows anything about this repository.

    A field with a real default rather than a module attribute a test monkeypatches, which is
    `points`' argument and `compose=`'s: a suite that had to patch `builtins.input` to drive `agl
    init` would be reaching past every seam this module has."""


type Compose = Callable[[], Invocation]
"""How an invocation is assembled. `main`'s seam - see the module docstring."""


def main(argv: Sequence[str] | None = None, *, compose: Compose | None = None) -> int:
    """Parse `argv`, compose once, dispatch, and answer with a process exit status.

    `argv` is `sys.argv[1:]` when it is `None`, which is `argparse`'s own default rather than a
    second statement of it. `compose` is the composition seam and `None` is the real one.

    Returns rather than exits, on every path. The three clauses below are in the one order §3.1
    permits and each renders differently; `-h` still leaves through `SystemExit`, which is a
    `BaseException` and therefore none of this function's business.
    """
    try:
        parsed, tail = parser().parse_known_args(argv)
        # After argv made sense, and exactly once: §1.4's whole complaint in one line.
        invocation = _compose() if compose is None else compose()
        return _dispatch(invocation, parsed, tail)
    except Stop as stop:
        # First, and on stdout with no prefix: a deliberate end is not a failure, and rendering it
        # as one is precisely the bug that swapping this clause with the next would reintroduce.
        print(f"stopped: {stop}")
        return exit_status(stop)
    except AglError as refusal:
        print(f"{_PROGRAM}: {refusal}", file=sys.stderr)
        return exit_status(refusal)
    except Exception as bug:
        # The traceback first and the sentence last, because the last line is the one that is read.
        print_exception(bug, file=sys.stderr)
        print(f"{_PROGRAM}: {_OUR_BUG}", file=sys.stderr)
        return exit_status(bug)


def parser() -> RefusingParser:
    """The generic parser: `agl <command> ...`, holding AGL's vocabulary and no workflow's.

    Public for the reason `params.parser_for` is - a parser can be inspected, and what this one does
    *not* hold is §1.2's charge answered. `RefusingParser` throughout, so that `argparse`'s own
    `error()` raises `InputError` instead of reaching `sys.exit(2)` behind the one exit-code table;
    `parser_class=` restates at the type level what `add_subparsers` already does at runtime.
    """
    root = RefusingParser(prog=_PROGRAM, description=_DESCRIPTION, allow_abbrev=False)
    declared = root.add_subparsers(
        dest=_COMMAND, metavar="<command>", required=True, parser_class=RefusingParser
    )
    run_command.declare(declared)
    resume_command.declare(declared)
    clear_command.declare(declared)
    init_command.declare(declared)
    workflows_command.declare(declared)
    return root


def _compose() -> Invocation:
    """Read the environment once, and hand on the means to ask for everything else.

    `sources.resolve` snapshots the process environment and "the contract this module leaves behind
    is that nothing downstream may re-read the environment or re-parse a settings file". That is the
    one question every command shares, so it is the one asked here; the project and the container
    are what only three of the five need, and `_registered` is where those are asked for instead.
    `points` is left `None` so that what is installed is asked of the registry at the one place
    `api` already asks it.

    `Overrides()` - the flag layer says nothing. §3.10's grammar has no configuration flag, and
    `sources.Overrides` is where one would arrive if a later stage adds `--home` or `--build`: the
    field exists, typed, on the object this passes, so the parser is all that would have to change.

    **`Path.cwd()` is written here and nowhere else in AGL.** Two commands need the directory this
    was typed in - `agl init` to find a git root, everything addressed to a repository to resolve a
    project - and one read serves both because the answer is carried rather than re-asked. The
    module docstring argues it; `ask` takes its real default off `Invocation`, which is the same
    decision about the other process-global this file reaches for.
    """
    resolved = sources.resolve(sources.Overrides())
    cwd = Path.cwd()
    return Invocation(
        registered=lambda: _registered(resolved, cwd), settings=resolved.settings, cwd=cwd
    )


def _registered(resolved: sources.Resolved, cwd: Path) -> tuple[ProjectName, Services]:
    """The project `cwd` is in and the ports built for it - asked for, never volunteered.

    §1.4's whole charge lives in these two lines and both happen at most once per invocation:
    `container.real` is the only `new` in the process, and the working directory this resolves
    against was read once, by `_compose`, where it was read four times. They sit behind a callable
    rather than beside `sources.resolve` because `Resolved.project` reads a file `agl init` has not
    written yet, and `agl workflows` reads no project file at all.

    `cwd` is a parameter for `api.init`'s reason one layer down: `sources.py`'s contract is that
    "nothing downstream may re-read the environment", the working directory is environment, and a
    second read here would be free to disagree with the one `agl init` was handed.

    `NotFoundError` when `cwd` is not inside a git repository, or is inside one that no project file
    names. Deliberately not caught: `config/toml_file.py` raises it where the facts are, its message
    already sends the reader to `agl init` - run once per project and never again - and `main`'s
    handler resolves it to 3 out of the one table.
    """
    project = resolved.project(cwd)
    return project.name, container.real(resolved.settings, project)


def _dispatch(invocation: Invocation, parsed: argparse.Namespace, tail: Sequence[str]) -> int:
    """The chosen command, handed what was composed and what argv said. One clause per command.

    `tail` is what the generic parser did not recognise, and it belongs to `run` alone: a workflow's
    flags are the only arguments AGL deliberately does not understand. The other four declare every
    argument they take, so all four clauses refuse a tail through one helper rather than carrying
    one.

    Each clause hands on the parts of the invocation its command takes, which is what §3.10's
    per-command composition looks like from here. `run`, `resume` and `clear` take `registered`
    because all three are addressed to a repository; `init` and `workflows` do not, because `init`
    writes the very file `registered` would look for and `workflows` looks for nothing - and neither
    clause may grow a call to it. `points` stops at the three that resolve a workflow name: `clear`
    loads none and `init` has none to load. `settings`, `cwd` and `ask` stop at `init`, which is the
    one command composed without a container and therefore the one that needs them by name.
    """
    command = getattr(parsed, _COMMAND)
    if command == run_command.NAME:
        return run_command.execute(invocation.registered, parsed, tail, points=invocation.points)
    if command == resume_command.NAME:
        _no_tail(command, tail)
        return resume_command.execute(invocation.registered, parsed, points=invocation.points)
    if command == clear_command.NAME:
        _no_tail(command, tail)
        return clear_command.execute(invocation.registered, parsed)
    if command == init_command.NAME:
        _no_tail(command, tail)
        return init_command.execute(invocation.settings, invocation.cwd, invocation.ask)
    if command == workflows_command.NAME:
        _no_tail(command, tail)
        return workflows_command.execute(parsed, points=invocation.points)
    raise InternalError(
        f"`{_PROGRAM} {command}` reached the dispatch and there is no command by that name. The "
        f"parser admits only the subcommands declared in this module, so this is AGL's own bug "
        f"rather than anything you typed - a command was declared and never given a clause here"
    )


def _no_tail(command: str, tail: Sequence[str]) -> None:
    """Refuse what the generic parser did not recognise, for the four commands that declare it all.

    `parse_known_args` carries every argument no parser claimed, and only `run` has a use for one: a
    workflow's own flags are the arguments AGL deliberately does not understand, and a run is where
    a workflow is named. The other four declare their whole grammar on their own subparser - a
    label, `clear`'s `-f`, nothing at all, an optional workflow name - so an argument arriving here
    is somebody expecting the flags `agl run` took, and the answer is not "unrecognised argument"
    but where those flags went and how to find out what they are.

    **Written once for all four**, which is why it says what is true of all four, and the sentence
    has been rewritten twice for that reason. 16.2 wrote "takes a label and nothing else", exact
    while `resume` was the only caller and false the moment `agl clear <label> [-f]` shared the
    helper; 16.3 rewrote it around the record a run's arguments are read back from, which `agl init`
    and `agl workflows` make false in turn, neither being addressed to a run. What holds for all of
    them is a fact about `agl run` rather than about them - it is the only command that names a
    workflow, so it is the only one with anything to hand an argument AGL does not understand.

    `InputError`, exit 2 out of the one table: what the caller supplied cannot be used and nothing
    was attempted. It is refused here, in the dispatch, rather than inside the command, because a
    command that had to be handed a tail in order to refuse it would carry a parameter for the one
    thing it has no use for - and not one of the four takes an `argv` at all, which is what makes
    this structural rather than remembered.

    Deliberately not a refusal argparse could have made. Each subparser declares its own arguments,
    so `parse_args` would already reject anything else - but `main` parses with `parse_known_args`,
    once, for `run`'s sake, and a second parse per command in order to get a stricter error is two
    parsers over one line. One helper, one sentence, and each clause says which commands it is for.
    """
    if tail:
        raise InputError(
            f"`{_PROGRAM} {command}` does not take {list(tail)}: the arguments on this line are "
            f"the ones `{_PROGRAM} {command} -h` lists and no others. `{_PROGRAM} run` is the one "
            f"command that carries arguments AGL does not understand, because it is the one that "
            f"names a workflow to hand them to - a run's own workflow, its base ref and its "
            f"parameters are read back afterwards from the record `{_PROGRAM} run` wrote, and the "
            f"rest of AGL's commands either address a run that already has one or address no run "
            f"at all. To run a workflow with parameters, start a run: `{_PROGRAM} run <workflow> "
            f"-n <label> [workflow flags]`; `{_PROGRAM} workflows <workflow>` lists the flags one "
            f"takes"
        )
