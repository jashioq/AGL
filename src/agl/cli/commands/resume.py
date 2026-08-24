"""`agl resume <label>` - §3.10's second verb, and the shortest grammar in the CLI.

The command parses its one argument, asks for the repository the run is addressed to, calls **one**
`api` function, says it finished, and lets whatever was raised leave for `cli/main.py`'s handler.
That is the whole list, and `cli/commands/run.py` argues at length why the things absent from it are
the point: this module does not read the store, does not touch git, names no class, constructs
nothing, and does not know what a workflow is. §1.4's charge is `_cmd_clean` iterating worktrees and
`_cmd_init` doing build-tool detection in the CLI, and one `api` call is what a command is instead.

Two refusals a user meets here belong entirely to `api.resume` and are not re-detected on the way:
**a label with no record** is its `NotFoundError` (exit 3), written as the mirror of the message
`agl run` gives a label that is taken, and **a workflow version that is not the one the record was
stamped with** is its `ConflictError` (exit 4). A pre-check in this module would be a second
`read_record` and a second opinion, which is the duplication being repaired - and a library caller
has to get the same answers `agl resume` does.

## The grammar, and why there is nothing else in it

    agl resume <label>

One positional and no flags at all. §3.10: "`resume` takes the label only; params come from
`run.json`." That is the sentence this file is, and every argument the `run` parser holds is absent
for a reason the record already settled - the workflow name is `RunSpec.workflow`, the base ref is
`RunSpec.base_ref` and the commit under it `RunSpec.base_sha`, and the workflow's own flags are
`RunSpec.params`. A `--from` here would let a resume start somewhere the recorded run did not, which
is precisely what §3.6 pins `base_sha` against.

**The label is positional where `agl run` spells it `-n <label>`**, and the asymmetry is the
grammar's rather than an inconsistency. `run` has a positional already - the workflow name - and
§3.3 forbids a workflow's own parameters from claiming another, so the run's name has to be a flag
there. Here there is nothing else on the line to be confused with, and §3.10 writes it exactly this
way in both places: `agl run <workflow> -n <label>` and `agl resume <label>`.

**`allow_abbrev=False`, restated here because a subparser does not inherit it.** `ArgumentParser`
reads the flag off its own constructor and `add_parser` builds a fresh one, so the root parser's
choice does not reach this one; `cli/commands/run.py` makes the whole argument. It matters less here
than there, this parser declaring no long flag to be a prefix of, and it is written all the same:
the reason a later stage would add one is that a flag appeared, and a parser that had quietly been
abbreviating since before it was added is worse than one that never did.

## The tail is refused, and it is refused in `cli/main.py`

`main.parse_known_args` carries everything the generic parser did not recognise, and `_dispatch` has
said since 10.4 that the clause each label-taking command adds refuses a tail rather than carrying
one. `execute` below therefore takes no `argv` at all, which is what makes that structural: there is
no parameter here an unrecognised flag could arrive through, so a dispatch that tried to hand one
over would not compile. The refusal's wording is `main._no_tail`'s to write, beside the parse that
produced the tail - and 16.3's `clear`, whose grammar has a flag in it, is what made that sentence
say what is true of both rather than what was true of this one.

## The event loop starts here, and success is the one status this module writes

`api.py` is async and starts no loop on purpose, so the loop belongs to the edge; `cli/main.py`'s
docstring argues why the edge is the command rather than the dispatch. `asyncio.run` appears once,
around the one `api` call.

`0` is written below and it is not a second exit-code table. `ports/errors.py`'s table maps
*exceptions* to codes, and a resume that returned raised none; there is no name in it for success
and deliberately none added.
"""

import argparse
import asyncio
from collections.abc import Iterable
from importlib.metadata import EntryPoint
from typing import Final

from agl import api
from agl.cli.commands import Registered
from agl.ports.errors import InternalError
from agl.ports.ids import RunLabel
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

# The subcommand, spelled once: `main._dispatch` compares against this name rather than a literal.
NAME: Final = "resume"

# The one argument, as an `argparse` dest.
_LABEL: Final = "label"

# Not a row in `ports/errors.py`'s table and not the start of a second one - see the docstring.
_NOTHING_TO_REPORT: Final = 0

# What `add_subparsers` returns. Private in `argparse` and there is no public spelling of it; the
# alternative is `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]


def declare(commands: _Commands) -> RefusingParser:
    """Add `agl resume` to the generic parser, and hand the subparser back for inspection.

    Returned rather than dropped for `params.parser_for`'s reason and `cli/commands/run.py`'s: what
    this parser holds - one positional, no flags, nothing any workflow declared - is §3.10's
    sentence about resume taking the label only, and a test can read it off the object instead of
    trusting this docstring.
    """
    parser = commands.add_parser(
        NAME,
        help="continue a run from its record",
        description=(
            "Continue a run that already exists. It takes the label and nothing else: the "
            "workflow, the base ref and the parameters are read back from the run's own record, "
            "which is what `agl run` wrote them there for."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _LABEL,
        metavar="<label>",
        help="the run to continue: the name `agl run -n <label>` gave it",
    )
    return parser


def execute(
    registered: Registered,
    parsed: argparse.Namespace,
    *,
    points: Iterable[EntryPoint] | None = None,
) -> int:
    """Read the label, ask for a repository, continue the run, and say it finished.

    `registered` is §3.10's per-command composition reaching the second command that needs one: a
    run is addressed to a project and served by ports, and this is where those are asked for. It is
    called *after* the label has been turned into a `RunLabel`, which is the ordering
    `cli/commands/run.py` argues one file over - somebody who typed `agl resume my/label` outside a
    registered repository is told about the label they typed rather than about a repository they
    did not mean to be asked about.

    There is no `argv` parameter, and its absence is this command's half of `_dispatch`'s tail
    refusal - see the module docstring.

    Nothing is caught. A workflow's `Stop`, a label with no record, a version the record was not
    stamped with, params the workflow will not take and a repository nobody registered all leave as
    themselves, and `cli/main.py`'s handler is the one place an exception becomes a number (§3.1).
    """
    label = RunLabel(_said(parsed, _LABEL))
    project, services = registered()
    asyncio.run(api.resume(services, project, label, points=points))
    # §3.10's refusal reads `run 'auth' already exists`; `agl run` says `run 'auth' finished` when
    # it worked, and this is that line with the verb the operator typed in front of it - one
    # vocabulary, and still possible to tell which command produced it.
    print(f"resume {str(label)!r} finished")
    return _NOTHING_TO_REPORT


def _said(parsed: argparse.Namespace, dest: str) -> str:
    """One argument, as the string this module declared it to be.

    `argparse.Namespace` answers every attribute at `Any`, so a value read off it is unchecked
    until something checks it, and the conversion happens at the one place holding the type to
    convert against - which is the module that wrote `add_argument`. A second copy of
    `cli/commands/run.py`'s helper rather than an import of it: that one is private to the module
    that declared *its* three arguments, and a command importing another command's reader would be
    the first line of the two sharing a parser.

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
