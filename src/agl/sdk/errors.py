"""Re-export facade over `agl.ports.errors`: what AGL raises at a workflow, at the name a workflow
author imports. **No logic**, exactly as `sdk/terminal.py` and `sdk/questions.py` beside it hold
none.

    from agl.sdk import UpstreamUnavailable

    with pytest.raises(UpstreamUnavailable):
        await harness.run(fix, "-r", "add oauth")

The classes live in `ports/` because every layer raises out of them and `ports` may not import
`sdk` - `ARCHITECTURE.md` §5 states the rule, `sdk/terminal.py` carries the argument at length, and
it is one argument covering three modules rather than three. This module exists so that an author
asserting *how* their run refused never reaches into a package the layering put below them.

## Why this module was not written until 18.0, and what wrote it

`sdk/__init__.py` argued the hierarchy off the front door at 16.5 and marked the decision as one to
watch rather than one that was settled: the nine classes "are not the authoring surface ... what AGL
raises *at* everyone rather than part of what a workflow is built *from*", with the tripwire spelled
out - "if `fix` or `split` catches an AGL class, that is the evidence this decision was wrong, and
the repair is to re-export the hierarchy from a module in this package rather than to point authors
at `ports`."

Stage 17 fired it, and not from the direction the tripwire was aimed. `fix` itself catches nothing;
its *test file* asserts three refusals - a flag no parser would take, a question no screen could
answer, and the `UpstreamUnavailable` a headless terminal makes when the workflow's own handler puts
a screen up - and had to write `from agl.ports.errors import ...` to name them. That is the same
failure the tripwire describes: what an author asserts a run refused with is part of the surface
whether they catch it or raise `pytest.raises` at it, and there was nowhere on the front door to
import it from. So the repair is the one that paragraph named in advance, and this is it.

## The nine, and the two that are not here

**Every class in the hierarchy, and no subset of it.** `AglError` and the eight below it, including
the two that "exist to be caught": `UpstreamError` is what a caller that does not care which of the
two happened catches, and a facade offering the leaves without the base would send that caller into
`agl.ports` for it. `sdk/terminal.py`'s rule about curation applies with full force here - deciding
which errors an author "really" needs would be the one kind of logic a facade must not hold.

**`EXIT_CODES` and `exit_code_for` are the other two names on `ports/errors.py`, and they are not
here.** This is not the curation that rule forbids, because the cut is not one this module invented:
`ports/errors.py` says in its own first lines that it holds two things - "the `AglError` hierarchy,
organised by meaning, **and** the one exception -> exit-code table in the codebase" - and
`cli/exit_codes.py` already takes exactly the other half of it, re-exporting those two names and
holding no table of its own. An exit code is what a *process* answers with and what a shell script
branches on; a workflow function has no process to exit and `api.py` never returns one. Putting the
table here would advertise a mapping no workflow has any business reading, and would make `agl.sdk`
the second front door onto the CLI's own vocabulary. An author who does want the number - a test
asserting the exit code `agl run` would have produced - is writing about the CLI and imports it
from `cli`.

**`Stop` is in the hierarchy and is deliberately not re-exported here**, and it is the one name on
the front door this module could have claimed and must not. It is already there, through
`sdk/workflow.py`, which has re-exported it since stage 10 and argues it at length beside the `Run`
it is raised out of - §3.3's surface is "six members, plus `Stop`", §3.1 makes it a workflow's own
mechanism, and workflows subclass it under their own names. **One name does not get two import
paths into one front door**: `from agl.sdk.errors import Stop` and `from agl.sdk.workflow import
Stop` would be two spellings a reader has to choose between and two modules that have to keep
agreeing about which one owns it, for a name that is on `agl.sdk` either way.

Which module owns it there is decided by direction, and the distinction is worth having rather than
being a tie broken by seniority: **this module holds what a workflow catches or asserts on, and
`Stop` is the one class a workflow raises.** It is a declaration a workflow makes, like `Role` and
`@workflow`, and it belongs beside them. The cost is that `except Stop: raise` before a narrower
`except UpstreamError:` - the trap `sdk/workflow.py` warns about - names two modules if it is
written with submodule imports; off the front door it is one line, `from agl.sdk import Stop,
UpstreamError`, which is the spelling the door exists to make true.

## No logic, and the absence is what is being specified

No alias, no wrapper, no subclass of our own, no `AglError` declared here. Every name below **is**
the class `agl.ports.errors` defines - `is`-identical, not merely compatible - which matters more
for exceptions than for anything else the facades cover: `except` and `pytest.raises` are identity
comparisons up the MRO, so a facade that wrapped or re-declared anything would hand an author a
class that never catches what AGL actually raised. `tests/sdk/test_front_door.py` asserts the
identity rather than the presence, for exactly that reason.
"""

from agl.ports.errors import (
    AglError,
    ConflictError,
    DeniedError,
    InputError,
    InternalError,
    NotFoundError,
    UpstreamError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)

# Listed rather than computed from `ports.errors.__all__`, for `sdk/terminal.py`'s reason: a
# re-export assembled at runtime is invisible to `ruff`, to `mypy` and to a reader. It is also what
# makes the two absences above readable as decisions - a computed list would take `EXIT_CODES` and
# `Stop` along with the rest and nobody would ever have had to argue either.
__all__ = [
    "AglError",
    "ConflictError",
    "DeniedError",
    "InputError",
    "InternalError",
    "NotFoundError",
    "UpstreamError",
    "UpstreamUnavailable",
    "UpstreamUnexpected",
]
