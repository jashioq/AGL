"""`agl clear <label> [-f]` - §3.10's third verb, and the one §1.4 charges by name.

The command parses its two arguments, asks for the repository the run is addressed to, calls **one**
`api` function, renders what came back, and lets whatever was raised leave for `cli/main.py`'s
handler. That is the whole list, and here the absences are not a general principle but a specific
answer: §1.4's charge is that `_cmd_clean` **iterated worktrees, deleted branches and called
`shutil.rmtree` past the `Store` port** - a use case living in the CLI, doing by hand what a port
exists to be asked. So this module reads no store, touches no git, computes no path under the trees
root, names no class and constructs nothing, and it does not know what a namespace is. Every one of
those is `api.clear`'s, and the moment one of them appears here the charge has been re-earned in the
one command it was written about.

The two things a user meets here belong entirely to `api.clear` and are not re-detected on the way:
**a label with no record** is its `NotFoundError` (exit 3), the third member of the pair `agl run`
and `agl resume` are written as, and **a branch that is not yet in the base ref** is the warning it
answers with. A pre-check in this module would be a second `read_record` and a second opinion about
what "merged" means, which is the duplication being repaired - and a library caller has to get the
same answers `agl clear` does.

## The grammar

    agl clear <label> [-f]

One positional and one flag, which is §3.10's line for this verb exactly. `-f/--force` is
`git branch -d` versus `-D`: without it the run's own branch is deleted only if the base ref already
contains it, and otherwise kept with the warning below. The flag carries no argument and defaults to
off, because the asymmetry §3.10 states runs one way - a retained branch costs a stale ref, a
deleted one costs the entire run - and a destructive default is that asymmetry ignored.

The label is positional for `agl resume`'s reason: there is nothing else on the line to be confused
with, and §3.10 writes it this way in both places.

**`allow_abbrev=False`, restated here because a subparser does not inherit it.** `ArgumentParser`
reads the flag off its own constructor and `add_parser` builds a fresh one, so the root parser's
choice does not reach this one. It is load-bearing here in a way it is not on `agl resume`: this
parser declares a long flag, so with abbreviation on `--for`, `--forc` and even `--f` would all be
accepted spellings of `--force` - abbreviations nobody wrote down, of the one flag in AGL that
deletes something.

## The tail is refused, and it is refused in `cli/main.py`

`main.parse_known_args` carries everything the generic parser did not recognise, and only `agl run`
has a use for one: a workflow's own flags are the arguments AGL deliberately does not understand.
`execute` below therefore takes no `argv` at all, which is what makes that structural - there is no
parameter here an unrecognised flag could arrive through. The refusal's wording is `main`'s, beside
the parse that produced the tail, and 16.2 built the helper that says it; what 16.3 changed is that
the helper had to stop saying "a label and nothing else", `-f` being on this line legitimately.

## The event loop, the warning, and the two streams

`api.py` is async and starts no loop on purpose, so the loop belongs to the edge and `cli/main.py`'s
docstring argues why the edge is the command. `asyncio.run` appears once, around the one `api` call.

**The warning is written here and is not this module's opinion.** `api.clear` answers with the
sentence or with `None`, having been the thing that knew whether the branch was contained; this
prints it. It goes to **stderr** while the finished line goes to stdout, which is §3.8's "logs to
stderr, data to stdout": a kept branch is a diagnostic about a command that succeeded, and a script
reading `agl clear`'s output should not have to filter it out of what it asked for.

`0` is written below and it is not a second exit-code table. `ports/errors.py`'s table maps
*exceptions* to codes, and a clear that returned raised none - the whole point of §3.10's warning is
that it is a non-zero-value message on a zero exit, so a status of its own would make a kept branch
a failure and every wrapper script treat it as one.
"""

import argparse
import asyncio
import sys
from typing import Final

from agl import api
from agl.cli.commands import Registered
from agl.ports.errors import InternalError
from agl.ports.ids import RunLabel
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

# The subcommand, spelled once: `main._dispatch` compares against this name rather than a literal.
NAME: Final = "clear"

# The two arguments, as `argparse` dests.
_LABEL: Final = "label"
_FORCE: Final = "force"

# The generic spellings this module holds. `-f` is git's own for the same meaning, which is what
# §3.10 asks for by writing the semantics as `git branch -d` versus `-D`.
_FORCE_FLAGS: Final = ("-f", "--force")

# Not a row in `ports/errors.py`'s table and not the start of a second one - see the docstring.
_NOTHING_TO_REPORT: Final = 0

# What `add_subparsers` returns. Private in `argparse` and there is no public spelling of it; the
# alternative is `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]


def declare(commands: _Commands) -> RefusingParser:
    """Add `agl clear` to the generic parser, and hand the subparser back for inspection.

    Returned rather than dropped for `params.parser_for`'s reason and `cli/commands/run.py`'s: what
    this parser holds - one positional, one flag, nothing any workflow declared - is §3.10's line
    for this verb, and a test can read it off the object instead of trusting this docstring.
    """
    parser = commands.add_parser(
        NAME,
        help="take a run away",
        description=(
            "Take a run away: its checkouts, its child branches and its records. The run's own "
            "branch is deleted only if the base ref already contains it, and otherwise kept with "
            "a warning - `-f` deletes it regardless."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _LABEL,
        metavar="<label>",
        help="the run to take away: the name `agl run -n <label>` gave it",
    )
    parser.add_argument(
        *_FORCE_FLAGS,
        dest=_FORCE,
        action="store_true",
        help="delete the run's own branch even if the base ref does not contain it yet",
    )
    return parser


def execute(registered: Registered, parsed: argparse.Namespace) -> int:
    """Read the two arguments, ask for a repository, take the run away, and render the answer.

    `registered` is §3.10's per-command composition reaching the third command that needs one: a run
    is addressed to a project and served by ports, and this is where those are asked for. It is
    called *after* the label has been turned into a `RunLabel`, which is the ordering
    `cli/commands/run.py` argues one file over - somebody who typed `agl clear my/label` outside a
    registered repository is told about the label they typed rather than about a repository they did
    not mean to be asked about.

    There is no `argv` parameter and no `points`: the tail belongs to `agl run` alone (see the
    module docstring), and `clear` loads no workflow, so the entry-point seam every other command
    threads has nothing to reach here.

    Nothing is caught. A label with no record, a line of work something still holds open, a wedged
    worktree registry and a repository nobody registered all leave as themselves, and the handler
    in `cli/main.py` is the one place an exception becomes a number (§3.1).
    """
    label = RunLabel(_said(parsed, _LABEL))
    force = _flagged(parsed, _FORCE)
    project, services = registered()
    kept = asyncio.run(api.clear(services, project, label, force=force))
    # §3.10's refusal reads `run 'auth' already exists`; `agl run` and `agl resume` say `run 'auth'
    # finished` and `resume 'auth' finished`. This is that line with the verb the operator typed.
    print(f"clear {str(label)!r} finished")
    if kept is not None:
        print(kept, file=sys.stderr)
    return _NOTHING_TO_REPORT


def _said(parsed: argparse.Namespace, dest: str) -> str:
    """One argument, as the string this module declared it to be.

    `argparse.Namespace` answers every attribute at `Any`, so a value read off it is unchecked until
    something checks it, and the conversion happens at the one place holding the type to convert
    against - which is the module that wrote `add_argument`. A third copy of `cli/commands/run.py`'s
    helper rather than an import of one: each is private to the module that declared *its* own
    arguments, and a command importing another command's reader would be the first line of the two
    sharing a parser.

    `InternalError` for anything else, because the dest is one this module declared and `argparse`
    was given no converter that could produce another type. A user cannot provoke it; we could.
    """
    value = getattr(parsed, dest)
    if isinstance(value, str):
        return value
    raise InternalError(_disagreeing(value, dest))


def _flagged(parsed: argparse.Namespace, dest: str) -> bool:
    """The same, for a flag that is present or absent. `store_true` answers `False`, never `None`.

    Its own reader rather than a `bool(...)` at the call site, and the difference is the one that
    matters: every value `argparse` hands over is `Any`, so `bool(value)` would happily turn the
    string `"false"` into `True` and report a forced clear the operator never asked for. This is the
    one flag in AGL that deletes a branch, so it is the last place to widen a type by coercion.
    """
    value = getattr(parsed, dest)
    if isinstance(value, bool):
        return value
    raise InternalError(_disagreeing(value, dest))


def _disagreeing(value: object, dest: str) -> str:
    """What the two readers above say when the parser produced something neither declared.

    One sentence for both, because it is one fault: this module wrote `add_argument` and this module
    reads the result, so a mismatch is the parser and the reader disagreeing inside one file.
    """
    return (
        f"the `{NAME}` parser produced {value!r} for {dest!r}, and every argument this module "
        f"declares is either a string it took off the command line or a flag that is on or off. "
        f"That is AGL's own bug: the parser and the reader are in one file and they disagree"
    )
