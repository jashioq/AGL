# DELETED AT 19.4
"""The `noop` workflow: it does nothing, and **it is deleted at stage 19.4.**

This package is scaffolding and nothing else. `docs/agl-build-stages.md` says so in its own words -
"`workflows/noop/` is scaffolding and is deleted at 19.4" - and 19.4's row ends with `delete
workflows/noop/`. So nothing in AGL may come to depend on it. It registers a name, it is invoked, it
returns, and on the day it goes away the only other thing that has to change is the one line in
`pyproject.toml` that registers it.

**Why it exists.** Stage 10 is the walking skeleton and its first acceptance criterion is that `agl
run noop -n x` exits 0 *through the real wiring*: argv, `cli/main.py`, the composition root, the
`agl.workflows` entry-point group, `api.run`, and a workflow's own function. Every workflow AGL
actually ships is written on `run.step`, which arrives at stage 12 over stage 11's journal - so at
10.5 there is no real workflow that could be run at all, and the walking skeleton would otherwise
have nothing to walk. `fix/` and `split/` are stage-0 skeletons that raise; a workflow declared
inside a test proves the SDK but not the *installation*, because an `EntryPoint` a test constructs
never touches the group an operator's `pip install` writes into. The one thing left that can
demonstrate the whole path is an installed workflow that does nothing, and this is it.

That is also the whole of what it is for. Wiring problems surface here rather than at stage 19,
which is the stage's stated purpose, and a probe that did any work would be a probe with a second
reason to fail.

## `--stop`, the one flag, doing the stage's two remaining jobs

A params dataclass with no fields would still have exercised `sdk/params.py`, and it would have
exercised none of it that matters: §3.3's promise is that a workflow's `arg()` fields *become named
CLI flags*, and the composition where that can go wrong is the generic parser and the workflow's
parser sharing one command line (`cli/commands/run.py`). One declared flag is what proves it end to
end rather than in a unit test.

Stage 10's other outstanding criterion is that **a raised `Stop` exits 7** - "not 6 or 70" - and
observing that from a shell needs a workflow that can raise one. `--stop <reason>` is both:

    agl run noop -n x                     # returns, exit 0
    agl run noop -n x --stop "nothing to do here"   # raises, exit 7, reason on stdout

The reason travels the whole way, which is what makes the flag worth reading: a person types it, the
generic parser declines to recognise it, `api.run` hands it to `sdk/params.py`, the parsed dataclass
reaches `run.params`, and the string comes back out of the process as the message of the exception
this module raised. `run.json` records it under `params` on the way past.

**A `str` with `default=""`, not a `bool` switch**, because a switch cannot carry a reason and
§3.1's point about `Stop` is that the reason is the workflow's to name. The cost is a corner worth
stating rather than hiding: `--stop ""` is indistinguishable from not passing the flag, since
`sdk/params.py`'s field types are `str`, `int`, `float` and `bool` and an optional string has no
spelling but a falsy default. Stopping with an empty reason would print `stopped: ` and tell nobody
anything, so the corner costs nothing here and is not worth a sentinel value to close.

## `AskedToStop` is this workflow's own class, per §3.1

"`Stop` is the framework's terminal-end mechanism and carries no domain vocabulary. Workflows
subclass it under their own names." `ReviewNotConverging` and `BacklogStalled` are the plan's
examples; `AskedToStop` is this workflow's, and its domain is exactly one fact - somebody asked.
`exit_code_for` walks the MRO, so it resolves to `Stop`'s 7 without appearing in any table and
without the framework learning what it means.

## What it builds: nothing at all

No steps, no worktrees, no journal, no store access, no `run.json` writing. `api.run` has already
written the record - including the `base_sha` pinned to a full object name (§3.6) - before this
function is awaited, and duplicating any of that here would make the probe assert its own work
instead of the framework's. The body below is a conditional and a `raise`, and the absence of
everything else is the measurement.

A workflow imports `sdk` and `ports` alone (contract 6) - never `adapters`, never `config`. This one
imports `agl.sdk` and, transitively through it, nothing a workflow author could not have written.
"""

from dataclasses import dataclass

from agl.sdk.params import arg
from agl.sdk.workflow import Run, Stop, workflow

__all__ = ["AskedToStop", "NoopParams", "noop"]


@dataclass(frozen=True)
class NoopParams:
    """One flag, so that stage 10 proves `arg()` through the real command line and not a unit test.

    Frozen, following §3.3's own example. The field is a `str` rather than a switch because the
    reason a run stopped is the workflow's to carry - the module docstring argues both halves.
    """

    stop: str = arg(
        "-s",
        "--stop",
        default="",
        help="end the run deliberately with this reason (exit 7) instead of returning",
    )
    """Why to stop, or `""` to do nothing and return. Recorded into `run.json` under `params`
    either way, which is what makes `agl resume` take no flags (§3.3)."""


class AskedToStop(Stop):
    """`noop`'s own reason to end a run: somebody passed `--stop`.

    A `Stop` subclass under this workflow's own name, which is §3.1's rule - the framework defines
    no vocabulary of reasons, and `exit_code_for` walks the MRO, so this exits 7 while appearing in
    no table. It is deliberately the thinnest possible instance of that rule: one fact, no fields,
    and a message that is whatever the operator typed.
    """


@workflow(name="noop", version="1", params=NoopParams)
async def noop(run: Run[NoopParams]) -> None:
    """Do nothing - or, given `--stop <reason>`, end the run deliberately carrying that reason.

    The whole of the workflow. `api.run` wrote `run.json` before awaiting this, and stage 10
    persists nothing else, so returning is the entire success path: what is being proved is that
    the invocation arrived here at all.

    Nothing is caught on the way out. `AskedToStop` leaves as itself, `api.run` wraps nothing, and
    `cli/main.py` catches `Stop` before `AglError` and prints it to stdout without the `agl:` prefix
    a failure carries. That ordering is the stage's acceptance criterion (§3.1) and this is the one
    installed workflow that can make a shell demonstrate it.
    """
    if run.params.stop:
        raise AskedToStop(run.params.stop)
