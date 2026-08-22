"""The `@workflow` decorator, the `Run` a workflow is handed, and `Stop`. Never a base class.

§3.3's target is "one package, one entry-point line, one readable function", and this module is the
third of those: a workflow is an `async def` taking a `Run` and returning `None`, decorated with
what the framework needs to know about it. There is no class to subclass, no `setup`, no `resume`.
§1.2's charge against the old dispatch was that a workflow "existed" exactly when two guesses about
a package's insides both came true, and a decorated function is the smallest thing that cannot be
guessed at.

**The decorator returns the `Workflow`, not the function.** §3.3's registration line is
`tickets = "agl.workflows.tickets:tickets"`, so the decorated name *is* the entry point's target,
and what an entry point resolves to is what the registry hands to `api.py`. A decorator that
returned the function would leave the framework holding a callable with no name, no version and no
params class, and it would be back to asking a module what it contains.

## What this stage builds, and what it deliberately leaves empty

§3.3 gives `Run` six members - `params`, `step`, `worktree`, `integrate`, `activity`, `terminal` -
plus `Stop`. **One of the six is here.** `step` and `activity` are stage 12, over the journal stage
11 builds; `worktree` is 13, `integrate` is 14 and `terminal` is 15. They are not stubbed, not
declared raising `NotImplementedError`, and not present as attributes that refuse. A member that
exists and refuses is a member every caller has to ask about, and `hasattr` on it is exactly the
duck typing this layer was built to replace. Stage 10 is the walking skeleton - `agl run noop -n x`
exits 0 through the real wiring - and a `Run` carrying only `params` is what proves that.

## The class `registry.load` narrows to

`config/registry.py` names this module in as many words: `EntryPoint.load()` returns `Any`, nominal
narrowing needs a class to narrow *to*, and "the only such class is the object `@workflow` produces
in `sdk/workflow.py`, which does not exist until stage 10.2". `Workflow` is that class.
`registry.load(points, name, Workflow)` runs `isinstance(loaded, Workflow)` and refuses anything
else with its own `InputError`, which is the hole a `runtime_checkable` `Protocol` could not have
closed - an object carrying the right attribute *names* would have passed.

One consequence lands on the caller, and 10.3 should write it deliberately. A bare generic class in
`type[T]` position infers `T` as `Workflow[Any]`, PEP 696 default notwithstanding, so `api.py`
annotates the result:

    wf: Workflow[object] = registry.load(points, name, Workflow)

after which `wf.params` is a `type[object]`, `params.parse` returns an `object`, and `wf.fn` takes
the `Run[object]` built from it - one chain, no `Any` anywhere in it. `Workflow[object]` cannot be
passed as `kind` instead: a subscripted generic is not usable with `isinstance`.

## `Run` is generic in its params, and the default is `object`

§3.3 promises that "mypy knows `run.params.concurrent` is an `int`". That is only true if the params
type is on `Run`, so `Run[P]` it is, and a workflow that reads its parameters annotates
`run: Run[TicketsParams]`.

`disallow_any_generics` is on under `--strict`, so a bare `Run` in an annotation would be an error
without a type-parameter default - and §3.3's own examples write `async def fix(run: Run) -> None`
for a workflow that never reads its params. Both classes here take `P = object`, following
`ports/terminal.py`'s `Screen[T = None]`, which met the same question and answered it the same way.

`object` rather than `Any`, because the parameter is genuinely **unknown** and not **unchecked**:
`run.params` on a bare `Run` is an `object`, and reading a field off it is an error, which is the
true statement. `Any` would wave `run.params.concurrent` through on a workflow that declared no such
field - §3.3's one typing promise turned into a lie in the place it is easiest to believe.

The decorator ties the two ends together: `@workflow(params=TicketsParams)` infers `P` from that
argument and then requires a function taking a `Run[TicketsParams]`, so declaring one params class
and annotating another is an error at the decoration site. A function annotated with a bare `Run` is
accepted at any `P`, `Run` being covariant in it.

## The bundle is carried now and first read at stage 12

`Run.services` is `sdk/_engine/services.py`'s eight ports, and nothing this stage does looks at it.
It is here because `Run` is constructed by `api.py` at 10.3, and a constructor's shape is what every
call site is written against - each of `cli/commands/`, `sdk/testing.py` at 16.5, and every test
that drives a workflow. The first member to read it is `run.step` at stage 12: the journal's entries
through `services.store`, the pre-step reset through `services.workspaces`, the dispatch through
`services.agents`. Adding the field then would mean revisiting every one of those sites for a value
that had been available all along, and it would make this stage's wiring mimed rather than real -
`container.real()`'s output would have nowhere to go, which is the one thing the walking skeleton
exists to disprove.

## `Stop` is re-exported, never redefined

`ports/errors.py` has held `Stop` since stage 1 and says why it is there rather than here: `ports`
may not import `sdk`. What this module adds is the import a workflow author writes -
`from agl.sdk.workflow import Stop` - and one warning they need as much as the CLI does.

A workflow raises its own subclass carrying a domain reason: `ReviewNotConverging`,
`BacklogStalled`. The framework catches the base and the run ends at exit 7; `exit_code_for` walks
the MRO, so a subclass resolves without appearing in any table and without the framework ever
learning a vocabulary of reasons.

**`Stop` descends from `AglError`, so any handler must catch it first.** Plan §3.1 makes that a
stage-10 acceptance criterion for the CLI, and it is the same trap one layer up: a workflow driving
a retry loop writes `except AglError:` around a step to decide whether to try again, and a `Stop`
raised inside that step - by its own halt policy, or by something it called - is then swallowed as a
failure and retried. That is the one shape of this bug where the run *keeps working* after it was
told to end. Put `except Stop: raise` first, or catch the narrower classes.

## Every refusal is `InputError`

The faults this module can see are one kind: a workflow package declaring itself wrongly - an empty
name, an empty version, a `params=` that is not a dataclass, a function that is not `async`.
`config/registry.py` settled the class for exactly this shape of fault and `sdk/params.py` followed
it: the declaration was written by a package the operator installed, AGL only read it, and exit 70
reads as "file a bug" against the wrong codebase. Exit 2 says fix what you supplied, which is as
true of a decorator argument as of a flag. None of these is `InternalError`, which is for an
invariant AGL alone controls, and this module controls nothing that a workflow author does not type.

`@workflow` runs at import time, so its refusal leaves the workflow package's import as the exit 2
it already is: `registry.load` catches `ImportError` and `AttributeError` and passes everything else
through untouched.

## `version` is on the decorator, and required

`RunSpec.workflow_version` is a required, non-empty field, stamped at run start and compared with
`==` on resume, where a mismatch refuses the run and tells the user to start a new one. Something
has to supply it, and the alternatives are both worse. Deriving it from the providing distribution
through `EntryPoint.dist` would plumb packaging metadata into `registry.load`, whose generic
signature is written to know nothing whatever about workflows. Defaulting it to a constant makes
every comparison equal, which is a resume that never refuses, which is the migration nobody is going
to write happening silently instead of loudly. So it is a required keyword, and a workflow with
nothing to say about it writes `version="1"` once. §3.3's examples predate the field.

## What `@workflow` does not check

**That the params dataclass is a *params* dataclass.** `arg()` already refuses a malformed flag
where it is written, and `params.parser_for` refuses a field declared without one, a spelling
claimed twice and a field type nothing can parse - naming the field, which is what the reader needs.
Re-deriving those rules here would be a second copy of them, free to drift from the first, for a
fault the run refuses before anything happens anyway. What is checked here is what is visible from
here: that the argument is a dataclass class, and not an instance of one.

**That `name` matches the entry-point key.** The registry indexes by the entry point, so the name
here is what a workflow calls itself and the name there is what an operator types. Comparing them
needs both, and only `api.py` holds both.

**Anything about the function beyond its being a coroutine function.** Its signature is mypy's
business at the decoration site, where the annotations are. The one thing a type checker cannot see
is that the object is an `async def` rather than a plain callable returning an awaitable, and
`inspect.iscoroutinefunction` is the only honest form of that question - which is worth asking,
because such a function type-checks perfectly and then never yields to the event loop.

## Deliberately not built

No `Workflow.__call__`. It would keep `await tickets(run)` working now that the decorated name is a
`Workflow` rather than a function, and it is one line - and it is a second spelling of `wf.fn(run)`
on the object the registry hands to `api.py`, for a call nothing in this repository makes. The field
is public, so a workflow author's own test loses nothing.

No registry of decorated workflows, no `__init_subclass__`, no import-time side effect at all:
`@workflow` builds an object and returns it. The entry point *is* the registration, and a
module-level list here would be a second one, holding only the workflows that happened to be
imported.

No `Run` factory and no `Run.child`. Constructing the root `Run` is the composition root's business
at 10.3, and cutting a child is `run.worktree` at stage 12; a helper here would prejudge both.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, is_dataclass
from inspect import iscoroutinefunction

from agl.ports.errors import InputError, Stop
from agl.sdk._engine.services import Services

__all__ = ["Run", "Stop", "Workflow", "workflow"]


@dataclass(frozen=True, slots=True)
class Run[P = object]:
    """What a workflow is handed, and the whole of what it is handed. §3.3's `run`.

    Frozen for `Services`' own reason: a run is what this invocation was assembled with, and
    reassigning a field halfway through would leave two halves of a workflow disagreeing about
    which parameters they were given. Slotted, so the surface is the two fields below and an
    attribute nobody declared cannot be attached to it.

    Five of §3.3's six members belong to stages 12 to 15 and are absent rather than stubbed - see
    the module docstring, which also says why the bundle is carried before anything reads it.
    """

    params: P
    """The workflow's own parameters, at the type it declared them - §3.3's "mypy knows
    `run.params.concurrent` is an `int`". Already parsed and validated: `params.parse` refuses on
    the way in, before anything runs, so nothing here re-checks it."""

    services: Services
    """The ports this run is served by. Carried, and first read by `run.step` at stage 12."""


# The one shape a workflow's function has. Private, because it is a spelling convenience rather
# than a name anything should import: `Callable[[Callable[[Run[P]], Awaitable[None]]], ...]` is
# what `workflow`'s return type says without it, and nobody reads that twice.
type _Function[P] = Callable[[Run[P]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Workflow[P = object]:
    """What `@workflow` produces, what an entry point resolves to, and what `registry.load`
    narrows to with `isinstance`. A workflow, as the framework knows one.

    Four facts and no behaviour. Everything else about running it - fingerprints, replay,
    worktrees, branch naming, integration, preflight, exit codes, provider routing - is framework,
    and §3.3's table is emphatic that it stays framework.
    """

    name: str
    """What the workflow calls itself: `tickets`, `fix`, `split`. `RunSpec.workflow` records the
    entry-point key the run was started with, and by convention they are the same string; nothing
    here compares them, because only `api.py` holds both. A plain `str` for `RunSpec.workflow`'s
    reason - a key in the `agl.workflows` table is not a filename and not a git ref, so `ids.py`'s
    types neither fit nor apply."""

    version: str
    """The version stamped into `RunSpec.workflow_version` at run start and compared with `==` on
    resume. Never parsed and never ordered - see the module docstring, and `ports/run.py`."""

    params: type[P]
    """The dataclass of `arg()` fields this workflow is invoked with. The *class*: `params.parse`
    turns argv into an instance of it, and that instance is `Run.params`. Named for the decorator
    keyword that supplies it, which is why one word covers a type here and a value there."""

    fn: _Function[P]
    """The `async def` itself, unwrapped and unchanged. `api.py` awaits `fn(run)`."""


def workflow[P](
    *, name: str, version: str, params: type[P]
) -> Callable[[_Function[P]], Workflow[P]]:
    """Declare an async function to be a workflow. §3.3's one line of ceremony.

        @workflow(name="fix", version="1.1", params=FixParams)
        async def fix(run: Run[FixParams]) -> None:
            ...

    Keyword-only, all three required: a positional would make `@workflow("fix", "1.1", FixParams)`
    a thing to get in the wrong order once and be wrong about for the life of a run's records. The
    decorated name becomes the `Workflow`, which is what the entry point points at.

    Refuses with `InputError` - the module docstring argues the class - an empty `name` or
    `version`, a `params` that is not a dataclass class, and a function that is not a coroutine
    function. All four at import time, which is where a package that cannot be invoked correctly
    should fail.
    """
    _check_text("name", name)
    _check_text("version", version)
    _check_params(params)

    def declare(fn: _Function[P]) -> Workflow[P]:
        if not iscoroutinefunction(fn):
            raise InputError(
                f"the workflow {name!r} is declared on something that is not an `async def`: "
                f"{fn!r}. A workflow is one async function (§3.3), the framework awaits it, and a "
                f"plain function returning an awaitable type-checks here and then never yields"
            )
        return Workflow(name=name, version=version, params=params, fn=fn)

    return declare


def _check_text(field: str, value: str) -> None:
    """Emptiness, and nothing else, for the same reason `RunSpec` asserts only that: what a good
    workflow name looks like is the registry's judgement and what a good version looks like is the
    author's. Whitespace counts as empty - a name of spaces names nothing anyone could type."""
    if not value.strip():
        raise InputError(
            f"a workflow's {field} is required and cannot be blank: `@workflow` was given "
            f"{value!r}. Both are written into every run record this workflow starts, and "
            f"`RunSpec` refuses an empty `workflow` or `workflow_version` - so a run declared this "
            f"way could not be recorded, let alone resumed"
        )


def _check_params(params: object) -> None:
    """That the argument is a dataclass *class*. Takes `object` so that `is_dataclass`'s type guard
    narrows nothing in the caller, where `params` has to stay the `type[P]` it was declared."""
    if isinstance(params, type) and is_dataclass(params):
        return
    raise InputError(
        f"`@workflow(params=...)` was given {_describe(params)}, and a workflow's parameters are a "
        f"dataclass of `arg()` fields (§3.3) - the class itself, never an instance of it. It is "
        f"what the CLI derives this workflow's flags from and what `run.params` is an instance of"
    )


def _describe(thing: object) -> str:
    """A class as `grep` finds it; anything that is not one at its own repr, which is what shows a
    reader they passed an instance where the class belonged. `sdk/params.py` describes the same."""
    if not isinstance(thing, type):
        return repr(thing)
    return f"{thing.__module__}.{thing.__qualname__}"
