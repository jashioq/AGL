"""`agl run <workflow> -n <label> [workflow flags] [--from <ref>]` - §3.10's first verb.

The command parses its own arguments, asks for the repository a run is addressed to, calls **one**
`api` function, renders what came back, and lets whatever was raised leave for `cli/main.py`'s
handler. That is the whole list, and the things absent from it are the point: §1.4 charges the old
CLI with `_cmd_clean` iterating worktrees, deleting branches and calling `shutil.rmtree` past the
`Store` port, and `_cmd_init` doing build-tool detection and TOML rendering in ~150 lines. So this
module does not read the store, does not touch git, does not decide what `--from` defaults to, names
no class and constructs nothing, and does not know what a workflow is. Each of those is `api.py`'s,
and the moment a second one appears here §1.4 has happened again.

Two consequences worth naming, because both are refusals a user meets:

**The §3.10 refusal for a label that already exists is `api.run`'s**, with its message. This module
does not pre-check the store to produce a nicer one - a second `read_record` here is exactly the
duplication being repaired, and a library caller has to get the same answer as `agl run` does.

**A flag the workflow will not take is refused by the workflow's own parser**, in `sdk/params.py`,
which is the only module that knows what flags this workflow has. The tail below is handed over
unread.

## This command asks for its own prerequisites, which is not this command deciding anything

§3.10: "Composition is per-command, not universal. `main.py` resolves settings and dispatches; each
operation then resolves its own prerequisites. `run`, `resume` and `clear` resolve a project and
build a container; `init` takes settings alone; `list_workflows` takes neither." What `cli/main.py`
hands over is therefore a `Registered` - a callable that resolves the project and builds the
container *when it is called* - rather than the project and the container themselves, and the one
line in `execute` that calls it is this command's clause of that sentence. 16.4's `init` writes the
project file a container needs in order to exist and will not have such a line; `agl workflows`
lists what is merely installed and will not have one either.

The distinction that keeps this a dumb command (§1.4) is between *whether* and *what*. This module
imports neither `config.container` nor `config.sources`, names no adapter, reads nothing off what
comes back and cannot tell a real bundle from `container.fakes()`. It supplies one bit - that a run
needs a repository - which is the one bit only a command knows, because it is the bit that says
which verb this is. Everything about how that answer is assembled stayed in `cli/main.py`, where
§1.4 put it, and a `container.real` appearing here would be the charge repeating with better
manners.

The call is placed *after* the two values argv already settled, and the order is the same argument
`main` makes one layer up: a label the filesystem would not take is refused before a settings file
is read, so someone who typed `-n my/label` outside a registered repository is told about the label
they typed rather than about a repository they did not mean to be asked about.

**`Registered` is declared here and named from `cli/main.py`, because the imports only go one way.**
`main` imports this module to declare the subcommand, so this module cannot import `main` back, and
one of the two has to spell `Callable[[], tuple[ProjectName, Services]]` while the other names it.
Written here it is written once - `main` annotates `Invocation.registered` as
`run_command.Registered`, the field's type stated where the parameter that receives it lives - and
written there it would have to be written twice, this file already importing both halves of it. A
`TYPE_CHECKING` block would be the third option and there is not one anywhere in this codebase. When
16.2 and 16.3 add commands taking the same callable, `cli/commands/__init__.py` is where it moves:
both import through it already, and the move changes a name and no type.

## The grammar, and the one thing the generic parser is allowed to know

    agl run <workflow> -n <label> [workflow flags] [--from <ref>]

Three arguments, and none of them belongs to any workflow. `<workflow>` indexes the `agl.workflows`
entry points - it is the *key*, not a module path (`config/registry.py` argues the difference at
length). `-n/--name` is the run's label, which becomes the branch `agl/<label>` and the run's
directory under `AGL_HOME`, so it is a `RunLabel` and `ports/ids.py` refuses anything the filesystem
and git would not both take. `--from` is the base ref.

**`--from` is framework-level and not a workflow param**, which §3.9 settles in one sentence: "every
code-producing workflow needs one and the framework needs it independently. It costs a non-code
workflow nothing." A workflow declaring its own `--base` would be one run parameter with two
spellings and two records, and the framework - which pins the ref to a commit before the first step
so that a commit landing mid-run cannot move it - would be reading the workflow's.

The parser holds **no default for `--from`**. `None` reaches `api.run` and means "the repository's",
answered by `History` at the one place that can see a repository. A default of `"main"` here would
be §1.2's `_TRUNK = ("main", "master")` back in the CLI, deciding for a repo it never looked at.

## Everything else on the line is the workflow's, and how it gets there

`main` parses with `parse_known_args`, so what the generic parser does not recognise arrives here as
`argv` and goes to `api.run` unexamined, which hands it to `sdk/params.py`. That is the only
composition of the two, and it is why the generic side stays generic: adding a workflow adds no
flag here, which is §1.2's charge answered and measurable target #1.

The composition has one known edge, recorded rather than engineered around: `parse_known_args`
consumes positionals greedily, so an *unrecognised* flag written **before** the workflow name -
`agl run -r hello fix -n auth` - lets its value be read as the workflow name. The grammar puts the
workflow name immediately after `run` and the refusal that follows names a workflow nobody has
(exit 3), which is a loud wrong answer rather than a quiet one. Teaching the generic parser to skip
a value it does not know the arity of is not possible; teaching it the workflow's flags is what this
whole layer exists not to do.

## Flag collisions: documented, and deliberately neither reserved nor refused

The generic spellings are `-n`, `--name`, `--from`, `-h` and `--help`, and this module holds the
first three. A workflow may declare any of them, and `sdk/params.py` says why it is not stopped
where it is written: encoding the CLI's flag list into the SDK is "a copy kept in agreement by
nobody". The decision here is that it is not stopped at the composition either, and the argument is
that the only way to catch it is to become the thing this module refuses to be.

Refusing a collision means comparing the workflow's declared flags against the generic list, and the
workflow's declared flags are on its params class, which is reached by loading it from the registry
- so a command that refused collisions would load the workflow, i.e. re-implement the first line of
`api.run` in order to look at the shape of a workflow. That is §1.4's charge with better manners,
and `api.run` cannot do the check for us either, because the generic list is not a fact it knows.

So the collision stands, and what makes it survivable is that it is loud in the case that matters.
The generic parser runs first and wins, and the workflow's flag is then simply never given a value:
if it is required - which is what `arg()` with no `default` means - `sdk/params.py` refuses the run
with "the following arguments are required", naming the flag the user thought they had passed, at
exit 2 and before anything runs. The silent case is a colliding flag that has a default, which
quietly keeps it; that is the cost, it is this small, and `tests/cli/test_run_command.py` pins both
halves so a later stage that decides to spend a registry load on the check has to come here first.

`-h` is the one collision with a different shape: the generic parser answers it, prints AGL's help
and exits 0, so a workflow's `-h` is unreachable rather than shadowed. `sdk/params.py` builds the
workflow's parser with `add_help=False` for exactly this - "two parsers claiming it would make one
word mean two helps depending on where it appeared".

## `allow_abbrev=False`, restated here because a subparser does not inherit it

`ArgumentParser` reads the flag off its own constructor, and `add_parser` builds a fresh one, so the
root parser's choice does not reach this one. With abbreviation on, argparse matches any unambiguous
prefix of a long flag: a workflow declaring `--fro`, `--nam` or `--hel` would have it eaten - value
and all - by `--from`, `--name` or `--help`, and be told its required parameter was missing. That is
the flag-collision failure above, extended to spellings nobody typed on either side.

## The event loop starts here, and success is the one status this module writes

`api.py` is async and starts no loop on purpose, so the loop belongs to the edge; `main`'s docstring
argues why the edge is the command rather than the dispatch. `asyncio.run` appears once, around the
one `api` call.

`0` is written below and it is not a second exit-code table. `ports/errors.py`'s table maps
*exceptions* to codes, and a run that returned raised none; there is no name in it for success and
deliberately none added. Every other status this command can produce is resolved by `main`'s handler
out of that one table, from the exception that reached it.
"""

import argparse
import asyncio
from collections.abc import Callable, Iterable, Sequence
from importlib.metadata import EntryPoint
from typing import Final

from agl import api
from agl.ports.errors import InternalError
from agl.ports.ids import ProjectName, RunLabel
from agl.sdk._engine.services import Services
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "Registered", "declare", "execute"]

# The subcommand, spelled once: `main._dispatch` compares against this name rather than a literal.
NAME: Final = "run"

# The three arguments, as `argparse` dests. `--from` would otherwise land on the attribute `from`,
# which is a keyword and unreachable except through `getattr` - so the dest is written out.
_WORKFLOW: Final = "workflow"
_LABEL: Final = "label"
_BASE_REF: Final = "base_ref"

# The generic spellings this module holds. The module docstring argues what happens when a workflow
# declares one of them, and this tuple is the list a later stage would have to consult to refuse it.
_LABEL_FLAGS: Final = ("-n", "--name")
_BASE_REF_FLAGS: Final = ("--from",)

# Not a row in `ports/errors.py`'s table and not the start of a second one - see the docstring.
_NOTHING_TO_REPORT: Final = 0

# What `add_subparsers` returns. Private in `argparse` and there is no public spelling of it; the
# alternative is `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]


type Registered = Callable[[], tuple[ProjectName, Services]]
"""A registered repository, asked for rather than received: the project this invocation addresses
and the ports built for it. `cli/main.py` produces it and `execute` calls it - see the docstring for
why the alias is written on this side of the import."""


def declare(commands: _Commands) -> RefusingParser:
    """Add `agl run` to the generic parser, and hand the subparser back for inspection.

    Returned rather than dropped for `params.parser_for`'s reason: what this parser holds - three
    arguments, one of them positional, none of them any workflow's - is §1.2's charge answered, and
    a test can read it off the object instead of trusting a sentence.
    """
    parser = commands.add_parser(
        NAME,
        help="start a run",
        description=(
            "Start a run of a workflow. Flags this parser does not recognise belong to the "
            "workflow and are passed to it; `agl workflows` lists what is installed."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _WORKFLOW,
        metavar="<workflow>",
        help="the workflow to run, named as the agl.workflows entry point registers it",
    )
    parser.add_argument(
        *_LABEL_FLAGS,
        dest=_LABEL,
        metavar="<label>",
        required=True,
        help="this run's name: its record under AGL_HOME and the branch agl/<label>",
    )
    parser.add_argument(
        *_BASE_REF_FLAGS,
        dest=_BASE_REF,
        metavar="<ref>",
        help="the ref this run's work starts from (default: the repository's own default branch)",
    )
    return parser


def execute(
    registered: Registered,
    parsed: argparse.Namespace,
    argv: Sequence[str],
    *,
    points: Iterable[EntryPoint] | None = None,
) -> int:
    """Read what the parser understood, ask for a repository, run it, and say it finished.

    `registered` is §3.10's per-command composition reaching the one command that needs it: a run is
    addressed to a project and served by ports, and this is where those are asked for. `argv` is
    everything the generic parser did not recognise - the workflow's own flags, unread here and
    unread by `api.run`, which passes them to `sdk/params.py`.

    Nothing is caught. A workflow's `Stop`, a label already taken, a name nothing registers, a flag
    the workflow refuses and a repository nobody registered all leave as themselves, and
    `cli/main.py`'s handler is the one place an exception becomes a number (§3.1). `api.run` catches
    nothing either, which is how a `ReviewNotConverging` arrives at that handler as the object the
    workflow raised - and how the `NotFoundError` naming `agl init` arrives with the message
    `config/toml_file.py` wrote where the facts were.
    """
    name = _said(parsed, _WORKFLOW)
    label = RunLabel(_said(parsed, _LABEL))
    # Only now, and only because this verb needs one: everything argv can refuse by itself has been
    # refused, so a mistyped label is not answered with a sentence about an unregistered repository.
    project, services = registered()
    asyncio.run(
        api.run(
            services,
            project,
            name,
            label,
            argv,
            base_ref=_perhaps(parsed, _BASE_REF),
            points=points,
        )
    )
    # §3.10's refusal reads `run 'auth' already exists`; a run that finished says so the same way.
    print(f"run {str(label)!r} finished")
    return _NOTHING_TO_REPORT


def _said(parsed: argparse.Namespace, dest: str) -> str:
    """One argument, as the string this module declared it to be.

    `argparse.Namespace` answers every attribute at `Any`, so a value read off it is unchecked until
    something checks it - which is `config/registry.py`'s problem in a smaller form, and gets its
    answer: the conversion happens at the one place holding the type to convert against. Here that
    place is the module that wrote `add_argument`.

    `InternalError` for anything else, because the dest is one this module declared and `argparse`
    was given no converter that could produce another type. A user cannot provoke it; we could.
    """
    value = getattr(parsed, dest)
    if isinstance(value, str):
        return value
    raise InternalError(
        f"the `{NAME}` parser produced {value!r} for {dest!r}, and every argument this module "
        f"declares is a string it took off the command line. That is AGL's own bug: the parser and "
        f"the reader are in one file and they disagree"
    )


def _perhaps(parsed: argparse.Namespace, dest: str) -> str | None:
    """The same, for an argument the user need not have given. `None` is the answer, not an absence.

    `--from` unset means "the repository's default ref", and `api.run` is where that is decided
    (§3.9). Passing `None` on is this module declining to decide it, which is the whole of its job
    here - a default written into `add_argument` would be a policy about a repository nobody looked
    at, chosen by the layer furthest from it.
    """
    value = getattr(parsed, dest)
    return None if value is None else _said(parsed, dest)
