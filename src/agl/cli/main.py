import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from traceback import print_exception
from types import TracebackType
from typing import Final
from agl.api import Ask
from agl.cli import commands
from agl.cli.commands import clear as clear_command
from agl.cli.commands import init as init_command
from agl.cli.commands import new as new_command
from agl.cli.commands import resume as resume_command
from agl.cli.commands import run as run_command
from agl.cli.commands import workflows as workflows_command
from agl.cli.exit_codes import exit_code_for, exit_status, leaves
from agl.config import container, distribution, sources
from agl.config.schema import Settings
from agl.ports.errors import AglError, InputError, InternalError, Stop
from agl.ports.ids import ProjectName
from agl.ports.sync import Syncer
from agl.sdk._engine.services import Services
from agl.sdk.params import RefusingParser

__all__ = ["Compose", "Invocation", "main", "parser"]

_PROGRAM: Final = "agl"

_COMMAND: Final = "command"

_VERSION: Final = "--version"

_DESCRIPTION: Final = "Run AI agent workflows against a code repository."

# The import package, which is what a frame's `__name__` says it belongs to. Spelled again rather
# than shared with `_PROGRAM`: an import statement says `agl`, a person types `agl` and PyPI holds
# `agents-gl` - three names for three things, and `config/distribution.py` argues the third.
_PACKAGE: Final = "agl"

_OUR_BUG: Final = (
    "that traceback is AGL's own bug and not something you did wrong: it was raised inside AGL's "
    "own code rather than inside anything AGL called out to. An adapter is meant to translate what "
    "it catches into an `agl.ports.errors` class at its boundary, and one did not - so nothing "
    "above it could report the failure in words. Please report it with the lines above"
)

def _asked(prompt: str) -> str:
    try:
        return input(prompt)
    # `input` raises `EOFError` on a closed stdin - a Ctrl-D at the prompt, or a command run as
    # `agl init < /dev/null`.
    except EOFError as closed:
        raise InputError(
            f"stdin was closed before this question could be answered - a Ctrl-D, or a command run "
            f"with nothing on its input. Nothing has been written, so run it again somewhere the "
            f"question can be answered: {prompt.strip()}"
        ) from closed

@dataclass(frozen=True, slots=True)
class Invocation:
    registered: commands.Registered

    settings: Settings

    cwd: Path

    points: Iterable[EntryPoint] | None = None

    ask: Ask = _asked

    # A thunk and not a built `Syncer`, for the reason `registered` is one: every invocation
    # carries this field and three commands in the grammar call it, so `clear`, `init` and
    # `workflows` construct nothing. It is not on `Services` and takes no project -
    # `config/container.py` says why beside `real_syncer`.
    syncer: Callable[[], Syncer] = container.real_syncer

type Compose = Callable[[], Invocation]

def main(argv: Sequence[str] | None = None, *, compose: Compose | None = None) -> int:
    try:
        parsed, tail = parser().parse_known_args(argv)
        invocation = _compose() if compose is None else compose()
        return _dispatch(invocation, parsed, tail)
    except Stop as stop:
        print(f"stopped: {stop}")
        return exit_status(stop)
    except AglError as refusal:
        print(f"{_PROGRAM}: {refusal}", file=sys.stderr)
        return exit_status(refusal)
    except ExceptionGroup as concurrent:
        return _concurrent(concurrent)
    except Exception as bug:
        print_exception(bug, file=sys.stderr)
        print(f"{_PROGRAM}: {_attributed(bug)}", file=sys.stderr)
        return exit_status(bug)

def parser() -> RefusingParser:
    # With abbreviation on, `argparse` matches any unambiguous prefix of a long flag - so a workflow
    # declaring `--fro`, `--nam` or `--hel` would have it eaten, value and all, by `--from`,
    # `--name` or `--help`, and would then be told its required parameter was missing.
    root = RefusingParser(prog=_PROGRAM, description=_DESCRIPTION, allow_abbrev=False)
    # `argparse`'s own action, for `-h`'s reason: it prints and exits during the scan, before the
    # required subcommand is looked for, so `agl --version` needs no command after it. A `--version`
    # typed after one is nobody's flag here and reaches the workflow as tail, like any other.
    root.add_argument(
        _VERSION,
        action="version",
        version=f"{_PROGRAM} {distribution.installed_version()}",
        help=f"print the installed {distribution.DISTRIBUTION} version and exit",
    )
    declared = root.add_subparsers(
        dest=_COMMAND, metavar="<command>", required=True, parser_class=RefusingParser
    )
    run_command.declare(declared)
    resume_command.declare(declared)
    clear_command.declare(declared)
    init_command.declare(declared)
    new_command.declare(declared)
    workflows_command.declare(declared)
    return root

def _compose() -> Invocation:
    resolved = sources.resolve(sources.Overrides())
    cwd = Path.cwd()
    return Invocation(
        registered=lambda: _registered(resolved, cwd), settings=resolved.settings, cwd=cwd
    )

def _registered(resolved: sources.Resolved, cwd: Path) -> tuple[ProjectName, Services]:
    project = resolved.project(cwd)
    return project.name, container.real(resolved.settings, project)

def _dispatch(invocation: Invocation, parsed: argparse.Namespace, tail: Sequence[str]) -> int:
    command = getattr(parsed, _COMMAND)
    if command == run_command.NAME:
        return run_command.execute(
            invocation.registered,
            parsed,
            tail,
            syncer=invocation.syncer(),
            home=invocation.settings.home,
            points=invocation.points,
        )
    if command == resume_command.NAME:
        _no_tail(command, tail)
        return resume_command.execute(
            invocation.registered,
            parsed,
            syncer=invocation.syncer(),
            home=invocation.settings.home,
            points=invocation.points,
        )
    if command == clear_command.NAME:
        _no_tail(command, tail)
        return clear_command.execute(invocation.registered, parsed)
    if command == init_command.NAME:
        _no_tail(command, tail)
        return init_command.execute(invocation.settings, invocation.cwd, invocation.ask)
    if command == new_command.NAME:
        _no_tail(command, tail)
        return new_command.execute(invocation.settings.home, parsed, syncer=invocation.syncer())
    if command == workflows_command.NAME:
        _no_tail(command, tail)
        return workflows_command.execute(
            invocation.settings.home, parsed, points=invocation.points
        )
    raise InternalError(
        f"`{_PROGRAM} {command}` reached the dispatch and there is no command by that name. The "
        f"parser admits only the subcommands declared in this module, so this is AGL's own bug "
        f"rather than anything you typed - a command was declared and never given a clause here"
    )

def _no_tail(command: str, tail: Sequence[str]) -> None:
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

def _concurrent(group: ExceptionGroup[Exception]) -> int:
    deliberate, failed = group.split(Stop)
    if deliberate is not None:
        for stop in leaves(deliberate):
            print(f"stopped: {stop}")
    if failed is not None:
        _, untranslated = failed.split(AglError)
        if untranslated is not None:
            print_exception(untranslated, file=sys.stderr)
            # One line per leaf and not one for the group: a run that fanned out can hold a
            # workflow's own failure beside an adapter's, and those are two different faults.
            for leaf in leaves(untranslated):
                print(f"{_PROGRAM}: {_attributed(leaf)}", file=sys.stderr)
        print(f"{_PROGRAM}: {_severally(group)}", file=sys.stderr)
    return exit_status(group)

def _severally(group: ExceptionGroup[Exception]) -> str:
    held = tuple(leaves(group))
    status = exit_status(group)
    named = "\n".join(f"    {exit_status(one)}  {type(one).__name__}: {one}" for one in held)
    if {exit_status(one) for one in held} == {status}:
        return (
            f"this run's concurrent children raised, and every one of them below is exit {status} "
            f"- so that is what the run exits with, exactly as any one of them raised on its own "
            f"would have:\n{named}"
        )
    return (
        f"this run's concurrent children raised, and they do not resolve to one exit status - so "
        f"the run exits {status}. A run that failed several different ways is not attributable to "
        f"one code, and `InternalError`'s is the honest answer rather than a guess at which "
        f"of them was the real one, so read this {status} as 'these disagreed' and not as its "
        f"usual 'file a bug'. All of them, with the status each resolves to on its own:\n{named}"
    )

def _attributed(error: Exception) -> str:
    called = _called_frame(error)
    if called is None:
        return _OUR_BUG
    code = called.tb_frame.f_code
    return (
        f"that traceback was not raised by AGL's own code: `{code.co_qualname}` at "
        f"{code.co_filename}:{called.tb_lineno} is the last frame AGL called out to, and every "
        f"frame after it in the traceback above ran outside AGL. A workflow's own function is not "
        f"the only place AGL runs code somebody else wrote - a role's activity reporter, a tool's "
        f"handler and a terminal view are each invoked from inside AGL as well, and what any of "
        f"them raises comes out of the run as the object it raised. So read the frames after that "
        f"one: where they are yours, so is the fault, and there is nothing here to report. Where "
        f"none of them is, an adapter called out and let what came back through untranslated, and "
        f"that half is AGL's - please report that with the lines above. Either way the exception "
        f"resolves to exit {exit_code_for(InternalError)}, which says AGL had no name for it "
        f"rather than whose the fault was"
    )

# The reset on every frame of AGL's own is what makes this the frame after the *last* of them: a
# workflow calls back into AGL and AGL calls back out again, so the *first* non-AGL frame is the
# workflow's own line whatever raised, and answering with that one would blame a workflow for
# every failure under it.
def _called_frame(error: Exception) -> TracebackType | None:
    beyond: TracebackType | None = None
    frame = error.__traceback__
    while frame is not None:
        beyond = None if _ours(frame) else beyond or frame
        frame = frame.tb_next
    return beyond

def _ours(frame: TracebackType) -> bool:
    named = frame.tb_frame.f_globals.get("__name__")
    if not isinstance(named, str):
        return False
    return named == _PACKAGE or named.startswith(f"{_PACKAGE}.")
