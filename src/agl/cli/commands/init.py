"""`agl init` - §3.10's fourth verb, and the one §1.4 charges by name at ~150 lines.

The command declares no arguments, calls **one** `api` function, says where the file went, and lets
whatever was raised leave for `cli/main.py`'s handler. That is the whole list, and here the absences
are not a general principle but the specific answer to a specific charge. §1.4: "**`_cmd_init` is a
use case in the CLI** - build-tool detection (`_BUILD_GUESSES` is domain policy), TOML rendering,
template writing. ~150 lines."

Each of those three is gone, and none of them is gone by being moved here:

  * **Build-tool detection is not written anywhere in AGL.** §3.10 names `_BUILD_GUESSES` only to
    say why it exists - "inferring it is unreliable" - and then has `init` *ask*. So the guesses are
    not domain policy relocated to `api`; they are a mechanism this version does not have, and the
    question is put to the operator through a callable `cli/main.py` fills in with `input`.
  * **TOML rendering is `config/toml_file.py`'s**, which is "the only module that knows TOML"
    (ARCHITECTURE.md §6) and now holds the writer beside the reader, so what `init` writes is what
    `read_project` accepts and a test says so rather than a docstring.
  * **The standards template is dropped**, on §3.10's own instruction: "that content is
    tickets-specific and belongs to the workflow". Nothing here writes into the target repository,
    which is §3.5 and is also why there is nothing to template.

So this module reads no file, writes no file, walks up to no git root, names no class, constructs
nothing, and does not know what a project is. It takes no `Registered`, and that absence is the
sharpest one: `registered()` resolves the very file this command exists to write, so a `clear`-style
line here would make `agl init` refuse in every repository it is for.

## The grammar

    agl init

No arguments at all - §3.10's line for this verb exactly, and the reason `execute` below takes no
`argparse.Namespace`: there is nothing declared for it to read, and a parameter for a thing a module
has no use for is what `cli/commands/resume.py` argues against one file over. Everything `init`
needs is a fact about where it was typed, and `cli/main.py` reads that once.

**`allow_abbrev=False`, restated here because a subparser does not inherit it.** `ArgumentParser`
reads the flag off its own constructor and `add_parser` builds a fresh one. It has nothing to bite
on today, this parser declaring no flag; it is written for the reason `cli/commands/resume.py` gives
for writing it on an equally bare parser - the day a flag is added, a parser that had quietly been
abbreviating since before it existed is worse than one that never did.

## The tail is refused, and it is refused in `cli/main.py`

`main.parse_known_args` carries everything the generic parser did not recognise, and only `agl run`
has a use for one: a workflow's own flags are the arguments AGL deliberately does not understand.
`execute` takes no `argv`, which is what makes that structural rather than remembered. 16.4 is the
deliverable that made `main._no_tail` say what is true of all four of its callers, `init` and
`workflows` being addressed to no run at all.

## No event loop, and the one status this module writes

`api.init` is sync, because it awaits nothing: it walks the filesystem and writes one file, and no
port is involved. `cli/main.py`'s docstring gives that as the reason the loop belongs to the command
rather than to the dispatch - a dispatch that awaited everything would make the two sync operations
pretend otherwise - so there is no `asyncio.run` in this file and there must not be one.

`0` is written below and it is not a second exit-code table. `ports/errors.py`'s table maps
*exceptions* to codes, and an init that returned raised none.

**The finished line names the file rather than the project**, which is where this one departs from
`run`, `resume` and `clear`. Those three are addressed to a run and their line names the run, which
is the thing the operator will type next. `init` produces a file, and the file is what the operator
does something with next: §3.10 keeps it under `AGL_HOME` "so AGL never appears in `git status`", so
it is nowhere they can find by looking around, and `build` is the one value in it somebody edits by
hand. A line saying `init 'myapp' finished` would name the one thing they already know.
"""

import argparse
from pathlib import Path
from typing import Final

from agl import api
from agl.api import Ask
from agl.config.schema import Settings
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

# The subcommand, spelled once: `main._dispatch` compares against this name rather than a literal.
NAME: Final = "init"

# Not a row in `ports/errors.py`'s table and not the start of a second one - see the docstring.
_NOTHING_TO_REPORT: Final = 0

# What `add_subparsers` returns. Private in `argparse` and there is no public spelling of it; the
# alternative is `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]


def declare(commands: _Commands) -> RefusingParser:
    """Add `agl init` to the generic parser, and hand the subparser back for inspection.

    Returned rather than dropped for `params.parser_for`'s reason and every other command's: what
    this parser holds - nothing - is §3.10's line for this verb, and a test can read it off the
    object instead of trusting this docstring.
    """
    return commands.add_parser(
        NAME,
        help="register this repository as a project",
        description=(
            "Register the repository you are in. AGL finds its git root, asks for the command "
            "that builds and tests it, picks a place beside it for the working checkouts, and "
            "writes the project's settings under AGL_HOME - never into the repository, so AGL "
            "never appears in `git status`. Run it once per repository."
        ),
        allow_abbrev=False,
    )


def execute(settings: Settings, cwd: Path, ask: Ask) -> int:
    """Register this repository, and say where the settings went.

    The three arguments are what `cli/main.py` composed and nothing else: the settings every command
    shares, the directory this invocation was typed in, and how to put a question to whoever typed
    it. None of them is a project or a container, which is §3.10's per-command composition reaching
    the first command that needs neither - `api.py` argues why `init` could not have one.

    Nothing is caught. A directory outside any git repository, a directory whose name is not a
    usable project name, a repository that is registered already, a trees root that would land
    inside the repository and a blank build command all leave as themselves, and `cli/main.py`'s
    handler is the one place an exception becomes a number (§3.1).
    """
    written = api.init(settings, cwd, ask)
    print(f"init wrote {written}")
    return _NOTHING_TO_REPORT
