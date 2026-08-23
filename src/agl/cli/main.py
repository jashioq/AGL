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
project and builds the container *when called*, and the command's own clause is what calls it. `run`
calls it; 16.4's `init` and `workflows` will not. That is the whole of "each operation resolves its
own prerequisites" - the command supplies one bit, whether it needs a repository, and learns nothing
about what the answer is made of, which is what keeps it as dumb as §1.4 requires.
`cli/commands/run.py` holds the `Registered` alias and argues why it is written on that side.

`Path.cwd()` travels inside the thunk with the rest of it, which is the half that matters for 16.4:
`agl init` detects its own git root, and it can only do that in a process where this module has not
already refused to start over the absence of the file init is about to write.

## The seam: `Invocation`, and why the composition is a parameter with a real default

Everything below the parser needs three things - the workflows this invocation can reach, and, for
the commands addressed to a repository, its ports and the project they serve - and every one of them
is an answer about the machine AGL is running on. `_compose` is the impure step that asks the one
question every command shares: the environment, through `sources.resolve`. The other two are asked
by `_registered`, when a command asks for them, and by `api.run`'s own `points=None`, which is
`registry.installed()`.

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
so that `agl workflows` (16.4) - whose operation is sync, because it awaits nothing - is not made to
pretend otherwise by a dispatch that awaits everything.

## Only `run` exists

`resume`, `clear`, `init` and `workflows` are deliverables 16.2, 16.3 and 16.4, and there is no stub
for any of them here: a subcommand that parses and then refuses is a command whose grammar was
guessed a stage early, and `api.py` already declares the four signatures the dispatch will be
written against. `_dispatch` grows one clause per command, and its own refusal is `InternalError`
for the reason `api._unbuilt` gives - argparse admits only the names declared here, so arriving with
another one is AGL's bug and not the caller's mistake.
"""

import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from traceback import print_exception
from typing import Final

from agl.cli.commands import run as run_command
from agl.cli.exit_codes import exit_status
from agl.config import container, sources
from agl.ports.errors import AglError, InternalError, Stop
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

    There is no `settings` field, and the absence is a decision rather than an oversight. No command
    declared today reads settings - `run` reads them only through the ports the container built out
    of them - so a field here would be a general facility with no consumer, added on the strength of
    a guess about a second one. 16.4 brings `init`, which takes `Settings` and nothing else, and it
    is the deliverable that adds the field, beside its one reader and in the same edit.
    """

    registered: run_command.Registered
    """How to reach a registered repository: called by the clause of a command that needs one, and
    by nothing in this module. Deferred rather than resolved, because `agl init` writes the project
    file this would look for and `agl workflows` never looks for it - see the module docstring.

    It answers with a `ProjectName` and not a `config.schema.Project`, because that is the whole of
    what `api` takes and it says why: the rest of a `Project` has already been spent by the
    container in constructing the ports handed back beside it."""

    points: Iterable[EntryPoint] | None = None
    """The `agl.workflows` entry points to resolve a workflow name against, or `None` for what is
    installed. `api.run` declares this seam and this field is it, threaded one layer up so argv can
    reach it: `None` is what every real invocation means, and every real invocation passes it."""


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
    commands = root.add_subparsers(
        dest=_COMMAND, metavar="<command>", required=True, parser_class=RefusingParser
    )
    run_command.declare(commands)
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
    """
    resolved = sources.resolve(sources.Overrides())
    return Invocation(registered=lambda: _registered(resolved))


def _registered(resolved: sources.Resolved) -> tuple[ProjectName, Services]:
    """The project this directory is in and the ports built for it - asked for, never volunteered.

    §1.4's whole charge lives in these two lines and both happen at most once per invocation:
    `Path.cwd()` is written once, where it was written four times, and `container.real` is the only
    `new` in the process. They sit behind a callable rather than beside `sources.resolve` because
    `Resolved.project` reads a file `agl init` has not written yet, and `agl workflows` reads no
    project file at all.

    `NotFoundError` when this directory is not inside a git repository, or is inside one that no
    project file names. Deliberately not caught: `config/toml_file.py` raises it where the facts
    are, its message already sends the reader to `agl init` - run once per project and never again -
    and `main`'s handler resolves it to 3 out of the one table.
    """
    project = resolved.project(Path.cwd())
    return project.name, container.real(resolved.settings, project)


def _dispatch(invocation: Invocation, parsed: argparse.Namespace, tail: Sequence[str]) -> int:
    """The chosen command, handed what was composed and what argv said. One clause per command.

    `tail` is what the generic parser did not recognise, and it belongs to `run` alone: a workflow's
    flags are the only arguments AGL deliberately does not understand. 16.2's `resume` and 16.3's
    `clear` take a label and nothing else, so the clause each of them adds will refuse a tail rather
    than carry one.

    Each clause hands on the parts of the invocation its command takes, which is what §3.10's
    per-command composition looks like from here: `run` takes `registered` because a run is
    addressed to a repository, and the clauses 16.4 adds will not, because `init` writes what
    `registered` would look for and `workflows` looks for nothing.
    """
    command = getattr(parsed, _COMMAND)
    if command == run_command.NAME:
        return run_command.execute(invocation.registered, parsed, tail, points=invocation.points)
    raise InternalError(
        f"`{_PROGRAM} {command}` reached the dispatch and there is no command by that name. The "
        f"parser admits only the subcommands declared in this module, so this is AGL's own bug "
        f"rather than anything you typed - a command was declared and never given a clause here"
    )
