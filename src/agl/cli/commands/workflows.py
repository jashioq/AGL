"""`agl workflows [<workflow>]` - §3.10's fifth verb, and the UX gap stage 10 declined, closed.

The command reads its one optional argument, calls **one** `api` function, prints what came back,
and lets whatever was raised leave for `cli/main.py`'s handler. It names no class, constructs
nothing, imports no workflow itself and does not know what a workflow is - which is what keeps
§1.4's charge from repeating in the one command whose whole subject is workflows.

**It takes neither a project nor a container**, which §3.10 states outright - "`run`, `resume` and
`clear` resolve a project and build a container; `init` takes settings alone; `list_workflows` takes
neither" - and which `execute` below makes structural by having no `Registered` parameter for one to
arrive through. The reason is the one §3.10 gives: a listing that demanded a registered repository
would "make `agl workflows` demand a registered repository to list what is merely installed", which
is the one place an operator asking "what do I have?" is least likely to be standing.

## The grammar, and the half of it that extends §3.10

    agl workflows [<workflow>]

§3.10 writes `agl workflows` with **no argument**. The optional name is 16.4's addition and is
recorded here as a deviation from the plan rather than folded in as if it had always been there.

**With no argument it lists, and nothing is imported to answer.** `registry.names` never calls
`load`, which `config/registry.py` argues is not an optimisation: "one workflow package that fails
to import still appears in the listing, and every other workflow still runs. A registry that
imported the world to print a list would let any broken third-party package take down the command an
operator runs to find out what they have." That guarantee is untouched by everything below it.

**With a name it loads that one workflow and prints the flags it declares.** The load happens behind
an explicit request for that workflow, so a broken package fails loudly for the name that was asked
for and for no other - the listing above still answers about all of them.

## What this closes, and the half of it that stays closed

`cli/commands/run.py` records the gap in full and this is the other end of it. `agl run fix -h`
cannot show that workflow's own flags, and a colliding workflow flag cannot be refused, without
loading the workflow to inspect it - which stage 10 called "§1.4's charge with better manners" and
declined. 16.4 splits the two halves, because they are not the same cost:

**The help half is built, as a verb of its own rather than as a second meaning for `-h`.** Making
`-h` mean the workflow's help whenever a workflow name happens to be on the line is exactly the
objection `sdk/params.py` builds the workflow's parser with `add_help=False` to avoid - "two parsers
claiming it would make one word mean two helps depending on where it appeared" - with a positional
standing in for the parser. So `agl run fix -h` still prints AGL's `run` help, always, and `agl run
-h`'s own description points here. One word, one meaning; the second help has a name.

**The collision half stays declined, and the argument is stronger than it was.** Refusing a
colliding flag means comparing the workflow's flags against the generic ones on *every* `agl run`,
which means importing third-party code before every run to answer a question the user already gets a
loud answer to: `sdk/params.py` refuses a required colliding flag at exit 2, naming the flag, before
anything runs. And an operator can now *see* a collision, because `agl workflows <name>` prints the
workflow's flags beside the generic ones `agl run -h` prints. A refusal on every run buys, over
that, only the silent case - a colliding flag that has a default - at the price of the guarantee the
listing above exists for.

**`allow_abbrev=False`, restated here because a subparser does not inherit it.** `ArgumentParser`
reads the flag off its own constructor and `add_parser` builds a fresh one; `cli/commands/run.py`
makes the whole argument. This parser declares no long flag to be a prefix of, and it is written for
`cli/commands/resume.py`'s reason: a parser that had quietly been abbreviating since before its
first flag was added is worse than one that never did.

## The tail is refused, and it is refused in `cli/main.py`

`main.parse_known_args` carries everything the generic parser did not recognise, and only `agl run`
has a use for one. `execute` below takes no `argv`, so there is no parameter here an unrecognised
flag could arrive through. This command is the reason `main._no_tail`'s sentence had to stop being
about a run's record: `agl workflows` is addressed to no run at all, and what is true of all four of
that helper's callers is that only `agl run` names a workflow to hand unknown arguments to.

## No event loop, two streams, and the one status this module writes

`api.list_workflows` and `api.workflow_help` are both sync, because both await nothing - one reads
packaging metadata and one imports a package. `cli/main.py`'s docstring gives that as the reason the
loop belongs to the command rather than to the dispatch, and names this command as the case that
would otherwise be made to pretend: there is no `asyncio.run` in this file and there must not be.

**The names go to stdout, one per line, and the empty case goes to stderr.** §3.8 is "logs to
stderr, data to stdout", and a listing is data somebody pipes: `agl workflows | wc -l` has to answer
0 on an installation with none, so the sentence explaining an empty listing cannot be on the stream
being counted. It is still a sentence and not blank output, because silence from a command that was
asked a question reads as a command that failed quietly.

`0` is written below and it is not a second exit-code table. `ports/errors.py`'s table maps
*exceptions* to codes, and nothing installed is not an exception - it is the true answer.
"""

import argparse
import sys
from collections.abc import Iterable
from importlib.metadata import EntryPoint
from typing import Final

from agl import api
from agl.ports.errors import InternalError
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

# The subcommand, spelled once: `main._dispatch` compares against this name rather than a literal.
NAME: Final = "workflows"

# The one argument, as an `argparse` dest.
_WORKFLOW: Final = "workflow"

# Not a row in `ports/errors.py`'s table and not the start of a second one - see the docstring.
_NOTHING_TO_REPORT: Final = 0

# What an empty listing says. It names the mechanism rather than apologising, because the reader is
# either a new installation or somebody whose package did not declare the entry point it meant to.
_NOTHING_INSTALLED: Final = (
    "no workflow is installed: the agl.workflows entry point group is empty in this environment. A "
    "workflow arrives as a package that declares one line in that group - nothing is registered "
    "here, and there is no central list in AGL to add one to."
)

# What `add_subparsers` returns. Private in `argparse` and there is no public spelling of it; the
# alternative is `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]


def declare(commands: _Commands) -> RefusingParser:
    """Add `agl workflows` to the generic parser, and hand the subparser back for inspection.

    Returned rather than dropped for `params.parser_for`'s reason and every other command's: what
    this parser holds - one optional positional, no flags, nothing any workflow declared - is the
    grammar this module's docstring argues, and a test can read it off the object.
    """
    parser = commands.add_parser(
        NAME,
        help="list installed workflows, or print one workflow's flags",
        description=(
            "List every workflow installed in this environment. Nothing is imported to answer "
            "that, so a package that will not load still appears in the list. Naming one loads it "
            "and prints the flags `agl run <workflow>` takes for it."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _WORKFLOW,
        metavar="<workflow>",
        nargs="?",
        help="a workflow to describe: prints the flags it declares, and loads it to read them",
    )
    return parser


def execute(parsed: argparse.Namespace, *, points: Iterable[EntryPoint] | None = None) -> int:
    """Print the installed workflows, or the flags of the one that was named.

    `points` is the entry-point seam `api` declares and `cli/main.py` threads: `None` is what every
    real invocation means and is what asks the interpreter what is installed. There is no
    `registered` parameter and no `argv` - see the module docstring for both.

    Nothing is caught. A name nothing registers, a package that will not import, an entry point
    pointing at the wrong object and a name two packages both claim all leave as themselves, and
    `cli/main.py`'s handler is the one place an exception becomes a number (§3.1).
    """
    named = _perhaps(parsed, _WORKFLOW)
    if named is not None:
        # `format_help()` ends in a newline of its own and `print` adds another; the strip is so
        # that one command produces one trailing blank line rather than two.
        print(api.workflow_help(named, points=points).rstrip("\n"))
        return _NOTHING_TO_REPORT
    installed = api.list_workflows(points=points)
    if not installed:
        print(_NOTHING_INSTALLED, file=sys.stderr)
        return _NOTHING_TO_REPORT
    for name in installed:
        print(name)
    return _NOTHING_TO_REPORT


def _perhaps(parsed: argparse.Namespace, dest: str) -> str | None:
    """One argument the user need not have given, as the string this module declared it to be.

    `argparse.Namespace` answers every attribute at `Any`, so a value read off it is unchecked until
    something checks it, and the conversion happens at the one place holding the type to convert
    against - which is the module that wrote `add_argument`. Another copy of the readers in
    `cli/commands/run.py` and its siblings rather than an import of one: each is private to the
    module that declared *its* own arguments, and a command importing another command's reader would
    be the first line of the two sharing a parser.

    `None` is the answer for an argument nobody typed and not an absence: `nargs="?"` with no
    default leaves it there as `None`, and "list everything" is what this command means by it.

    `InternalError` for anything else, because the dest is one this module declared and `argparse`
    was given no converter that could produce another type. A user cannot provoke it; we could.
    """
    value = getattr(parsed, dest)
    if value is None or isinstance(value, str):
        return value
    raise InternalError(
        f"the `{NAME}` parser produced {value!r} for {dest!r}, and the one argument this module "
        f"declares is a string it took off the command line or nothing at all. That is AGL's own "
        f"bug: the parser and the reader are in one file and they disagree"
    )
