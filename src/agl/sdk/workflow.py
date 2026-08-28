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
returned the function would leave the framework holding a callable it had to interrogate: a
`version` is not on a function and cannot be read off one, and an attribute stapled to it by the
decorator is one `hasattr` away from the duck typing §1.2 charges. Since UF2.2 the params *are*
readable off the function - `Workflow.params` reads them - and that sharpens the point rather than
blunting it, because what is left on the object is exactly the one fact nothing else can see,
carried as a field of a class `isinstance` can narrow to.

## What this module builds: six members, of which four are delegates and one is a read

§3.3 gives `Run` six members - `params`, `step`, `worktree`, `integrate`, `activity`, `terminal` -
plus `Stop`, and 15.1 is where the sixth arrives. It was deliberately absent rather than stubbed
until then: a member that exists and refuses is a member every caller has to ask about, and
`hasattr` on it is exactly the duck typing this layer was built to replace.

**`terminal` is a property over `services.terminal`, and not a field.** The bundle has held a
port-typed `Terminal` since stage 9 and `api.py` is handed one already built, so a field would be
one object under two names on one frozen dataclass - `run.terminal` and `run.services.terminal`,
free to be handed different objects by any of the several places a `Run` is constructed - and
`_child` would have to copy it across in step with `services` for the two to go on agreeing. A
property has nothing to keep in step, and this class already reads through a field it holds one
member over. It is a property for a **different reason from `activity`**, which is a property
because the state behind it is mutable and a frozen slotted dataclass has nowhere to put it; here
the object is not mutable and is already held, so what is avoided is a second reference rather than
a second mechanism.

**That is what makes §3.7's single answerer structural rather than maintained.** `_child` copies
`services` across unchanged, so every `Run` in a tree reads one terminal out of one bundle: there is
no line anywhere that could build a second, and a question asked from a child worktree joins the
same queue as one asked from the root. A terminal per `Run` would give a run with four children five
slots and five sets of queues, four of them drawing over each other on one display, and every
`pending` reporting a fifth of what is waiting.

**The member is `terminal` and nothing else.** §3.3: "There is no `ask`, no `scope`, no `workspace`,
no `show`, no `view` attribute." A `run.show(...)` shortcut would be a seventh member and a second
spelling of `run.terminal.show(...)` - and §3.11's own table records `run.ask()` as "dissolved into
`run.terminal.show()` with an interactive view. One entry point", which a shortcut would undo one
line at a time.

**`step`, `worktree` and `integrate` are all delegates**, to `sdk/_engine/steps.py`,
`sdk/_engine/worktrees.py` and `sdk/_engine/integration.py`. ARCHITECTURE.md §6 carries a row for
each; the argument is that this module is the surface - a decorator, a frozen `Run`, `Stop` - and a
lock, a lazily opened checkout, a capture cell, a replay walk, a run-wide table of taken namespaces
and a lease held across a person's decision are plumbing, which `sdk/` keeps under `_engine/`
(`services.py` makes that case at length for the bundle). The fields those three need are here,
because a constructor's shape is what every call site is written against; what they *do* with them
is not.

**`integrate` is the one delegate whose return type is an `_engine` class**, and it has to be:
`ports.IntegrationOutcome` carries no `retry` and no `abort`, because those two release a lease
`ports/integration.py` argues at length is not the port's to model. `Integration` is that outcome
with the two verbs on it, and `Run.fingerprints` being a `Fingerprints` out of `_engine/journal.py`
is the precedent one field over.

**`activity` is a delegate for a second reason as well**, which is that a `Run` is frozen and
slotted and the current activity string is by definition mutable - §3.7's "the current agent
activity string for this Run ... or `None` when nothing is running". A frozen dataclass has nowhere
to put it, and the answer is not a second mechanism: `_steps` already holds this namespace's
mutable state, it is already the only thing that talks to an `AgentRunner`, and the string arrives
through a callback on the very call it makes. So the cell lives there and this is a property over
it. `sdk/_engine/steps.py` argues the rest, including why a replayed step has no activity at all.

## The class `registry.load` narrows to

`config/registry.py` names this module in as many words: `EntryPoint.load()` returns `Any`, nominal
narrowing needs a class to narrow *to*, and "the only such class is the object `@workflow` produces
in `sdk/workflow.py`, which did not exist when this module was written". `Workflow` is that class.
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

**Since UF2.2 the annotation is not one end of that but both.** `workflow()` is
`def workflow[P](*, version: str) -> Callable[[_Function[P]], Workflow[P]]`, so `P` flows purely
from `_Function[P] = Callable[[Run[P]], Awaitable[None]]` - that is, from `run: Run[TicketsParams]`
and from nothing else - and `Workflow.params` reads the same annotation back at runtime through
`get_type_hints`. The declaration and the inference source are one object, which is why "declaring
one params class and annotating another" is no longer an error to catch but a sentence with nothing
to refer to. While there were two, the pair could disagree in the quiet direction: `Run` is
covariant in `P`, so `@workflow(params=FixParams)` over `async def fix(run: Run)` type-checked
exactly, and handed the run a `FixParams` the function had annotated itself unable to read.

## The bundle, the address, the base, and the counter

`Run.services` is `sdk/_engine/services.py`'s eight ports, plus the build command 14.0 put beside
them because `Verifier.verify` takes one. It was carried unread from 10.3, on the
argument that a constructor's shape is what every call site is written against - each of
`cli/commands/`, `agl/testing.py` at 16.5, and every test that drives a workflow - and `run.step` is
the member that now reads it: the ledger through `services.store`, the checkout through
`services.workspaces`, the dispatch through `services.agents`, the entry's timestamp through
`services.clock`.

`scope` and `base` join it for the same reason and from the same caller. `api.run` already computes
both - `RunScope(project, label)` is the address it writes the record under, and `RunSpec.base_sha`
is the resolved commit it pins for exactly this purpose (§3.6: so that "a commit landing on `main`
between run and resume" cannot change "the first step's starting head"). Deriving either inside
`step` would mean this module reading `run.json` back through the store to learn something the
caller had in a local variable.

`fingerprints`, `worktrees` and `leases` are the run's three shared tables, and all three are
constructor arguments with a default **because `worktree()` hands its own to every child it cuts**.
`leases` joined the other two at 14.1 with nothing new to argue: §3.4 gives the framework one lease
per integration target, a table built per `Run` would be a table per namespace, and two siblings
landing into one parent would each take their own lock over their own dict and both be inside the
parent's checkout at once - the failure the lease exists to prevent, with the lease still nominally
taken. §3.6 scopes `n` per
`(namespace, step name)` and `Journal.__init__` argues that one counter per run is what makes that
key mean anything; §3.9 makes a namespace unique run-wide rather than sibling-wide, and
`_engine/worktrees.py` argues that a table built privately per `Run` is a table per *namespace*,
which cannot see a name taken anywhere else in the tree. Either built privately in here would look
identical at stage 12, where a run has exactly one namespace, and would be that stage's fix silently
removed the moment `run.worktree()` cut the second. So all three are fields with a default: the root
takes the default, and `_child` below passes on the objects this `Run` holds.

**`leases` is the one of the three the composition root does pass**, and that is not an
inconsistency in the defaulting. `api.run` releases it in a `finally` around the workflow's function
- §3.4 makes run exit "the sweeper, not the lifetime" for a lease no verb settled - so something
above the workflow has to be holding the handle, and the only way to hold what a defaulted field
built is to have built it. The default stays because `_child` and `agl/testing.py` and every test
that constructs a `Run` directly still want one, and a required argument would make each of them say
`Leases()` to get the thing they would have got anyway.

They are public for one reason and it is not that a workflow author needs them - none does. Every
field on this class is what the run was assembled with, and hiding some of the seven behind
underscores would make the ones the composition root does not pass look like a different kind of
thing from the ones it does.

## A child holds the `Run` that cut it, and the root holds `None`

`integrate()` at stage 14 lands a child's workspace into the **parent's** and writes
`IntegrationOutcome.head` into the **parent's** chain (§3.6), so it needs the parent `Run` - the
object, with its live journal in it. 13.1 built neither a parent field nor an index by scope, on
purpose; 14.0 settles it as `_parent`, private, defaulted `None`, and set by `_child` and by nothing
else. The field's own docstring argues that against the two alternatives, against §3.6's "the key,
not the object", and against the covariance the `worktrees` field one line above it had to give way
to. It is private because §3.3's surface is six members: a public `parent` would hand every workflow
author a tree to walk, and the first thing walked up a tree is somebody else's namespace.

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
version, a function that is not `async`, and since UF2.2 a first parameter this module cannot read a
params class off. `config/registry.py` settled the class for exactly this shape of fault and
`sdk/params.py` followed it: the declaration was written by a package the operator installed, AGL
only read it, and exit 70 reads as "file a bug" against the wrong codebase. Exit 2 says fix what you
supplied, which is as true of an annotation as of a flag. None of these is `InternalError`, which is
for an invariant AGL alone controls, and this module controls nothing that a workflow author does
not type.

**Two of the three are at import time and the third cannot be**, which UF2.2 changed and which is
worth saying rather than leaving to be discovered. `@workflow` runs at import, so a blank `version`
and a function that is not a coroutine function leave the workflow package's import as the exit 2 it
already is: `registry.load` catches `ImportError` and `AttributeError` and passes everything else
through untouched. The annotation is resolved *lazily*, at the first read of `Workflow.params`,
because a params class declared below the workflow function is not bound when the decorator runs -
so its refusals surface one moment later, on the `agl run` that asked. That moment is still before
anything happens: `api.run` reads `wf.params` to parse argv, ahead of the record, the lock, the
preflight and every port. `Workflow.params` argues the lateness and `_declared` holds the five
refusals.

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

**That the params class is a *params* dataclass**, and since UF2.2 not even that it is a dataclass.
`arg()` already refuses a malformed flag where it is written, and `params.parser_for` refuses a
class that is not a dataclass at all, a field declared without an `arg()`, a spelling claimed twice
and a field type nothing can parse - naming the class or the field, which is what the reader needs.
Re-deriving those rules here would be a second copy of them, free to drift from the first, for a
fault the run refuses before anything happens anyway.

`_check_params` used to make the first of them and went with the parameter it checked. Half of what
it caught is now unrepresentable - `@workflow(params=FixParams())` passed an *instance* where the
class belonged, and an annotation is a type - and the other half is `parser_for`'s own first line,
made at the same `agl run`, against the same class, naming it. What this module could add is not an
earlier refusal but a second one: resolution is lazy by necessity, so `@workflow` has no import-time
moment left in which to be the earlier of the two.

**That the workflow is registered under any particular key**, and since UF2.1 there is nothing here
that could be compared with one. A `name=` used to sit on the decorator beside `version=`, and the
comparison was never made - the registry indexes by the entry point, so the key was the name that
decided everything and the declaration was a copy of it that nothing read. What UF2.1 removed is
therefore not a check but the possibility of the disagreement; `Workflow` below says the rest.

**Anything about the function beyond its being a coroutine function** - at the decoration itself.
Its signature is mypy's business at the decoration site, where the annotations are. The one thing a
type checker cannot see is that the object is an `async def` rather than a plain callable returning
an awaitable, and `inspect.iscoroutinefunction` is the only honest form of that question - which is
worth asking, because such a function type-checks perfectly and then never yields to the event loop.

The first parameter's annotation is read later and is the one exception that proves the sentence:
`Workflow.params` reads it because it is now the *declaration*, not because this module wants an
opinion about signatures. It refuses exactly what stops it being one - a parameter that is not
there, one that is not annotated, one annotated something other than a `Run`, and one naming a class
nothing binds - and asks nothing else about the function at all.

## Three port names this module carries, for `sdk/roles.py`'s reason

`Namespace`, `Conflict` and `VerifierOutcome` are re-exported below and are `ports/ids.py`'s,
`ports/integration.py`'s and `ports/verifier.py`'s. They are here because **they are the vocabulary
a `Run`'s own members speak**, which is exactly why `sdk/roles.py` carries `Claude` and
`Restriction`: `worktree(name)` refuses a malformed name through `Namespace` and no copy of that
rule, and `integrate()` hands back an outcome whose `conflict` is a `Conflict` and whose `verdict`
is a `VerifierOutcome` - the two things §3.4's own snippet passes to a workflow's conflict view,
which therefore has to annotate its parameters with them. `ARCHITECTURE.md` §5 requires that the
front door take every name from a module in this package, so a name a `Run` speaks and this module
did not carry would be a name imported from `agl.ports` instead.

This is a module with logic that also carries port vocabulary, and not a fourth pure facade.
`sdk/terminal.py`, `sdk/questions.py` and `sdk/errors.py` are the pure ones, each over one port
module; three more of those would be three files holding one import each, and each of the three
names would then live a package away from the member that produces it. What decides it is which
question a reader is answering - "where does the thing `run.integrate()` gave me come from" is
answered here, beside `integrate`, and `Conflict` in a `sdk/integration.py` would be a second place
to look for a type this module already has to import to annotate `Integration`'s neighbours.

**19.2's tripwire, fired twice in one workflow.** `sdk/errors.py` exists because `fix`'s test file
had to write `from agl.ports.errors import ...` to say how a run refused; the same tripwire fired
again at 18.2 and 18.3, when `split/chunks.py` reached for `Namespace` and `split/views/conflict.py`
for both of the others, each reporting it rather than paying for it. `Restriction` and `Capability`
are not on this list and are `sdk/roles.py`'s, because a `Role` is declared out of them and a `Run`
only passes them through.

## Deliberately not built

No `Workflow.__call__`. It would keep `await tickets(run)` working now that the decorated name is a
`Workflow` rather than a function, and it is one line - and it is a second spelling of `wf.fn(run)`
on the object the registry hands to `api.py`, for a call nothing in this repository makes. The field
is public, so a workflow author's own test loses nothing.

No registry of decorated workflows, no `__init_subclass__`, no import-time side effect at all:
`@workflow` builds an object and returns it. The entry point *is* the registration, and a
module-level list here would be a second one, holding only the workflows that happened to be
imported.

No `Run` factory, and `_child` is private. Constructing the root `Run` is the composition root's
business - `api.py` builds it out of the record it just wrote - and cutting a child is `worktree()`,
which is the one caller `_child` has. A public factory would be a second way to make a `Run` in a
tree, free to hand one a table or a counter that is not the run's, which is the failure both fields
above exist to prevent.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from inspect import iscoroutinefunction, signature
from typing import cast, get_args, get_origin, get_type_hints

from agl.ports.errors import InputError, Stop
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace
from agl.ports.integration import Conflict
from agl.ports.terminal import Terminal
from agl.ports.verifier import VerifierOutcome
from agl.sdk._engine.integration import Integration, Leases
from agl.sdk._engine.integration import integrate as _integrate
from agl.sdk._engine.journal import Fingerprints
from agl.sdk._engine.preflight import Capabilities
from agl.sdk._engine.services import Services
from agl.sdk._engine.steps import Steps
from agl.sdk._engine.worktrees import Worktrees
from agl.sdk.roles import Role

__all__ = ["Conflict", "Namespace", "Run", "Stop", "VerifierOutcome", "Workflow", "workflow"]


@dataclass(frozen=True, slots=True)
class Run[P = object]:
    """What a workflow is handed, and the whole of what it is handed. §3.3's `run`.

    Frozen for `Services`' own reason: a run is what this invocation was assembled with, and
    reassigning a field halfway through would leave two halves of a workflow disagreeing about
    which parameters they were given. Slotted, so the surface is the fields below and an attribute
    nobody declared cannot be attached to it.

    §3.3's six members are all here, and two of them - `activity` and `terminal` - are properties
    rather than fields, for two different reasons the module docstring argues. The fields below are
    what this run was assembled with, and it argues each of those too.
    """

    params: P
    """The workflow's own parameters, at the type it declared them - §3.3's "mypy knows
    `run.params.concurrent` is an `int`". Already parsed and validated: `params.parse` refuses on
    the way in, before anything runs, so nothing here re-checks it."""

    services: Services
    """The ports this run is served by, and what `step` reaches every one of its dependencies
    through. Typed as port ABCs throughout, so a workflow cannot tell a fake bundle from a real
    one and cannot grow a branch on which it got."""

    scope: RunScope
    """Where this run's records go: `projects/<project>/runs/<label>/`, plus a namespace per
    worktree once 13.1 cuts one. The address a step's entry is written under and the scope its
    counter is keyed by (§3.6, rule 1)."""

    base: str
    """Where this namespace's chain starts - for the root, `RunSpec.base_sha`, already resolved.

    **A ref expression is legal here and is one case only**: a child cut by `worktree(name,
    base="main")`, whose base cannot be resolved at the call because `worktree()` is synchronous.
    Every other `Run` in a tree - the root, and every child cut from `None` or from another `Run` -
    holds a resolved commit id, because that is what a logical head is. `Steps._namespace` resolves
    this exactly once, through `services.history`, and hands the resolved value to both the
    checkout and the `Journal`, which is why `Journal`'s own docstring can go on insisting it never
    sees a ref name. Not re-checked here - `Journal` refuses an empty one and git judges the rest
    at `restore`, where the judging happens anyway."""

    fingerprints: Fingerprints = field(default_factory=Fingerprints)
    """§3.6's counter `n`, one per run and shared by every namespace's journal.

    Defaulted, because a root `Run` is the run and has nobody to inherit one from; a keyword all the
    same, because `worktree()` hands *this* object to the child it cuts. The module docstring says
    what a second counter over one run would cost."""

    worktrees: Worktrees[Run[object]] = field(default_factory=Worktrees)
    """§3.9's table of the namespaces this run has taken, run-wide and shared down the tree.

    `fingerprints`' shape and `fingerprints`' argument, one field over: defaulted for the root,
    passed on by `_child`, and never built inside a child - a table per `Run` is a table per
    namespace, which is sibling-wide uniqueness with the run-wide check written and unreachable.
    `sdk/_engine/worktrees.py` holds it and says what two names flattening onto one checkout costs.

    **`Run[object]` and not `Run[P]`, and the erasure is forced rather than chosen.** A table is a
    mutable container, so `Worktrees` is invariant in what it holds; a field of type
    `Worktrees[Run[P]]` therefore makes `Run` invariant in `P` too, and `Run` **must stay
    covariant** - that is what lets `worktree()` below hand this very `Run` to `_starts_at`, whose
    parameter is a `Run[object]`, and hand `self._child` to a table that builds `Run[object]`s.
    Every `Run` in one table really does share one `P` - the root's is the only table there is and
    `_child` is the only thing that adds to it - but nothing in the type system ties the two
    together, so `worktree()` narrows once, visibly, where it can say why."""

    leases: Leases = field(default_factory=Leases)
    """§3.4's lease per integration target, run-wide and shared down the tree.

    `fingerprints`' shape and `fingerprints`' argument, two fields over: defaulted for the root,
    passed on by `_child`, and never built inside a child. A `Leases` built per `Run` would be a
    lease table per *namespace*, and a lease table per namespace serialises nothing at all - two
    siblings landing into one parent would each take their own lock over their own dict and both be
    inside the parent's checkout at once, which is what the lease exists to prevent, with the lease
    still nominally taken. `sdk/_engine/integration.py` holds it and argues the rest, including why
    this is not §3.9's cross-process `flock` on the worktree registry and why the two must not be
    read as one mechanism at two sizes.

    **Not generic, so it costs no erasure where `worktrees` cost one.** A lease is keyed by the
    target's `RunScope` and holds a lock rather than a `Run`, so there is nothing in it for this
    class to be invariant in.

    Defaulted like the other two and passed by the two callers that drive a workflow: `api.run` and
    `api.resume` each construct one so that they can call `release_all` in a `finally` around the
    workflow's function, which is §3.4's sweeper: "run exit is the sweeper, not the lifetime", and
    what it catches is a lease no `retry()` or `abort()` reached. `resume` is
    "`run`'s last paragraph, line for line" in its own words, and this is one of the lines."""

    capabilities: Capabilities = field(default_factory=Capabilities)
    """§3.2's second preflight check, at step time: what each model's backend reported, asked once.

    `fingerprints`' shape and `fingerprints`' argument, three fields over: defaulted for the root,
    passed on by `_child`, and never built inside a child. `capabilities()` is contracted stable for
    the duration of a run (§3.2), so a table per namespace would ask a second time for an answer
    that cannot have changed.

    **The one of the four shared tables where sharing is an economy rather than the mechanism**, and
    it is worth saying which kind it is: a second `Fingerprints` or `Worktrees` or `Leases` breaks
    something, while a second `Capabilities` merely re-asks. That is also why this field is the one
    a directly-built `Run` can default without arranging anything - it holds no record of what
    preflight saw, and an empty one answers correctly on its first call.

    **Since UF1.3 this is the only containment there is**, and the field's importance changed with
    that rather than its shape. `api.run` used to make the same check at second zero over the roles
    `@workflow(roles=…)` declared; that parameter is gone, and containment needs a role's
    `requires`, which lives on the `Role` a factory returns and is unreachable without calling a
    factory preflight has no arguments for. So a capability mismatch is now caught here, at the
    first `run.step`, and nowhere earlier. `sdk/_engine/preflight.py` argues what that costs and why
    it was always this half that made the check real: the role a workflow hands to `run.step` is
    routinely `factory(on_question=handler)`, which is not the role any earlier check could see."""

    _parent: Run[P] | None = field(default=None, repr=False, compare=False)
    """The `Run` that cut this one, or `None` because nothing did. `integrate()`'s one seam.

    A landing has two ends and both of them are the parent's: §3.4 lands a child's `Workspace` into
    the target's, and §3.6 has the engine write `IntegrationOutcome.head` into the parent's chain.
    So `integrate()` needs the parent, and what it needs of the parent is the **object** - the live
    `Journal` behind `_steps`, whose `_last_good` the write lands on. `scope.namespaces[:-1]` is not
    that; it is the address the object would be at.

    **Why not the namespace table.** `worktrees` answers "who has taken this name", which is a
    question about names, and it is shared down the tree precisely so that one answer covers the
    whole run. Making it also answer "who cut me" gives one table two jobs and one of them
    ill-fitting: the root never appears in it - nothing takes the run's own namespace - so it would
    have to be inserted under a name §3.3 reserves in order to be findable at all, and the entry
    would exist to be looked up rather than to record a name being spent.

    **Why not an index by scope.** That is a *derived key*: it composes an address and hopes an
    object is there. The lookup can miss, and the one case where it misses is a `Run` with no
    parent, which is exactly the case `integrate()` has to refuse - so the mechanism's only failure
    is indistinguishable from its only interesting answer. `None` here says "this is the root"
    directly; a lookup that found nothing says "the root, or a bug, and I cannot tell which".
    Holding the reference makes the thing the engine wants structural rather than reconstructed.

    **Note the contrast with §3.6's "the key, not the object".** That paragraph is about the
    fingerprint counter, where the *key* does the work - counts are keyed `(scope, step name, base)`
    and a child's scope is unique run-wide, so sharing one `Fingerprints` is belt-and-braces rather
    than the mechanism. Here it is the other way round, and a reader who has just read that
    paragraph should not have to guess: a scope identifies an address, and an address is not a
    journal. Two `Run`s over one scope would be two chains, and advancing the wrong one moves a
    value nothing reads.

    **Covariant, and this one costs nothing where `worktrees` cost an erasure.** `Run` must stay
    covariant in `P` - that is what lets `worktree()` pass a `Run[P]` into `_starts_at`'s
    `Run[object]` and into a table of them. `Worktrees` is a mutable container and therefore
    invariant in what it holds, which is why that field is typed `Run[object]` and `worktree()`
    casts. A frozen dataclass field is read-only, so `Run[P] | None`
    is a covariant position and the type may be the honest one: a child's parent really is a `Run`
    at this run's own `P`, `_child` copying `params` across unchanged.

    Out of `repr` and out of `__eq__`. A recursive repr is the thing to weigh - a child printing its
    parent prints *its* parent, so one `repr` on a nested run walks the whole chain to the root -
    and equality gains nothing either, `scope` already naming the entire ancestry, so comparing
    parents would compare one fact twice and recursively.

    **Set by `_child` and by nothing else**, which is what makes the link true across a replay:
    `_child` is the only thing that builds a child, a reopen hands back the object it built rather
    than calling it again, and so a namespace's parent is decided once, when the name is first
    spent."""

    _steps: Steps = field(init=False, repr=False, compare=False)
    """The engine `step` delegates to - `sdk/_engine/steps.py`, holding this namespace's checkout
    and the walk over it.

    Derived rather than passed, because it is a function of the four fields above and a caller free
    to supply a different one could hand a `Run` an engine addressing another namespace. Built in
    `__post_init__` through `object.__setattr__`, which is how `Entry` sets its own derived field on
    a frozen dataclass. Out of `repr` and out of `__eq__`: two `Run`s are the same run when they
    were assembled from the same four values, and mutable plumbing is not a fifth."""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_steps",
            Steps(self.services, self.scope, self.base, self.fingerprints, self.capabilities),
        )

    @property
    def activity(self) -> str | None:
        """What the agent serving this Run is doing right now, or `None` when nothing is running.

            Text(run.activity or "")      # §3.7's board, inside a view re-invoked per frame

        **The string is the adapter's own** (§3.7): whichever backend is serving this step formats
        its own line - `Bash: ./gradlew build`, `Edit: domain/usecase.kt` - and the framework passes
        it through untouched. There is no `Activity` type, no shared vocabulary of verbs and no
        table here that maps one backend's words onto another's, so two providers in one run will
        word the same work differently and that is the accepted cost.

        **Live-only, and never persisted.** It is derived from a call that is in flight, so a step
        **replayed from cache reports nothing at all** - correctly, because nothing is running - and
        no part of it reaches an entry, a fingerprint or the store. An adapter with nothing to say
        never reports, so `None` is an ordinary answer during a step and not a sign of trouble;
        anything that renders this must read it as decoration rather than as progress.

        A plain attribute and not a call, because §3.7's views are re-invoked every frame:
        `Text(run.activity)` is already live, which is why the plan builds no `Activity` component
        and puts no activity parameter on any view signature. It is cleared when the step ends, on
        every ending there is - the value returned, the agent raised, the task was cancelled.
        """
        return self._steps.activity

    @property
    def terminal(self) -> Terminal:
        """The terminal this run shows on. §3.3's sixth member, and the whole of presentation.

            await run.terminal.show(views.board, tickets=backlog.tickets, runs=children)
            approval = await run.terminal.show(views.approve, question=q, priority=5)

        **A concrete terminal, not an abstract display** (§3.7). It speaks terminal concepts because
        it is one: `Screen`, `Rows`, `Text` are its own vocabulary and are free to be as
        terminal-specific as they like. There is no `Display` port, no `--display` flag and nothing
        to select between - a shared abstraction would have to be the intersection of a terminal and
        a browser, which is a worse terminal and a worse browser. A future web module is `run.web`,
        with websocket concepts on it and live alongside this one.

        **One `show`, and the view's return type decides what it does.** A passive `Screen` goes to
        the slot and answers `None` immediately; a `Screen[T]` joins a queue at its `priority` and
        blocks until a person answers, yielding the `T` their response produced. Both are awaited,
        because from here both are "put this in front of someone". `ports/terminal.py` holds the
        whole contract and every implementation satisfies it identically.

        **`show` registers the view and its arguments, not a value** - the redraw loop invokes the
        view again every frame - which is why `Text(run.activity)` is live with no component of its
        own and why passing the live dict of child `Run`s works. **Purity is the workflow's side of
        that bargain**: no I/O, no store reads, no sorting a thousand items, ten times a second.
        Nothing in this layer checks it, warns about it or could: a view is an ordinary function and
        the requirement is §3.7's, stated everywhere it is relied on and enforced nowhere.

        **The same object for every `Run` in the tree**, because `_child` copies `services` across
        and this reads out of it. That is §3.7's single answerer made structural: two agents in two
        worktrees asking at once stack in one set of queues on one display, and `pending` counts all
        of them. Screen identity is the registration and never the `Screen` value, so two children
        asking the same question are two questions and get two answers - that is the terminal's own
        rule and nothing here can weaken it.

        A property over `services.terminal` rather than a field, which the module docstring argues:
        the bundle already holds the object, and a field would be a second name for it on a frozen
        dataclass with a `_child` obliged to keep the two agreeing.
        """
        return self.services.terminal

    async def step[R](self, role: Role[R], *, commit: str | None = None, **inputs: object) -> R:
        """Run one step, or replay it. §3.3's "the only thing that persists anything".

            asking = implementer(on_question=answer)          # §3.3's factory, called once
            findings = await run.step(reviewer())
            await run.step(asking, findings=findings.high(),
                           commit="address review findings")   # the same role, a second time

        Resolves an entry from `(label, namespace, role.name)` plus a fingerprint over the role,
        the inputs and this namespace's starting head. **On a hit it returns the stored value
        without running anything** - no agent, no adapter, no cost. On a miss it restores the
        checkout to the last good head, builds an `AgentTask` from the `Role`, dispatches it to
        that model's provider, commits or wipes per `commit=`, and records what came back.

        **The step takes no name of its own** (§3.3, and §3.11's rejected member): the role already
        carries one, so a per-call-site string would be a second place to say the same thing, free
        to disagree with the declaration it is naming. Two calls on one role land in the same
        `steps/<role name>/` directory and are told apart inside it - by their inputs, which are
        fingerprint terms, or by §3.6's counter when the inputs match. That is what the second line
        above is: `fix` runs one `implementer` twice, once with a `request` and once with
        `findings`, and gets two entries under `steps/implement/`. Inferring a name from the
        caller's variable was rejected too - it breaks on anything but a bare identifier, and it
        would make a memo address depend on a local variable.

        **`commit=` is one of the three places in AGL where a mistake destroys work** rather than
        costing a re-run - §3.6's landing left out of the parent's chain and §3.4's red gate
        reverting a hand-resolved conflict are the others. Given, the framework
        commits whatever is dirty under that message and records the resulting head. Omitted, it
        restores the checkout to the last good head and removes everything that was not in it -
        `reset --hard` *and* `clean -fd` - so a read-only step is genuinely read-only and cannot
        leave a scratch file, a cache directory or a partial edit behind. Either way it happens
        whether this step returned or raised.

        **So a step without `commit=` should use a role declaring `Restriction.NO_VCS_WRITES`.**
        The framework does not check the combination, does not inspect what the role declared and
        does not compare HEAD before and after (§3.3) - it does one predictable thing per `commit=`.
        An agent that commits during a step that passed no `commit=` will have that work discarded,
        silently, because the wipe does not care what it is throwing away. Pairing the two is the
        author's job; §3.11's lint plugin is where a machine catches it.

        **The message is not in the fingerprint** (§3.6): it is cosmetic, so rewording it and
        replaying must not re-run an agent. The trade is that a replayed step keeps the commit it
        already made, message and all.

        **`**inputs` are fingerprinted, and appended to the prompt.** They must be JSON-serialisable
        or built from dataclasses - `InputError` otherwise, naming the path to the offending value -
        and any change to one re-runs the step and everything downstream of it, which is what gives
        replay its build-system cascade. They also reach the agent, as §3.3 says they must: the
        framework appends one block of canonical JSON under a fixed `## Inputs` heading at the end
        of the role's instructions, and interpolates nothing into the text the author wrote. **So
        write the prompt knowing the inputs arrive at the end** - `sdk/_engine/steps.py` carries
        that argument and the costs that come with it.

        **The result is the role's reporting-tool payload**, read back as the dataclass the role
        declared, on a fresh run and on a replay alike. A role declaring no reporting tool is an
        effect step: its result is `None` and its effect is commits. `Role[P = None]` is what makes
        `outcome = await run.step(implementer())` an error at the line that wrote it.

        `role.name` is opaque and was validated where it was declared - filesystem- and ref-safe,
        from `[A-Za-z0-9._-]` - because it is concatenated into a path, and it is validated again
        here on the way in, `StepName` being cheap and a `Role` reaching this method from anywhere.
        `R` rather than `P`: `Run[P]` already binds the workflow's params, and PEP 695 refuses a
        method parameter shadowing its class's.

        **`**inputs` may not be named `role` or `commit`** - those are this signature's own
        keywords, and a collision is a loud `TypeError` at the call. `name` was the third until the
        parameter went away, and it is now an ordinary input name like any other.
        """
        return await self._steps.step(role, commit=commit, inputs=inputs)

    def worktree(self, name: str, base: Run[object] | str | None = None) -> Run[P]:
        """A child `Run` with its own worktree and its own namespace. §3.3's `run.worktree`.

            w = parent.worktree(ticket.id, base=blocker)
            await w.step(agent, commit=f"implement {ticket.id}")

        **A plain synchronous call.** Not awaited, and deliberately not a context manager: "a
        context manager would tear the worktree down on exit, destroying exactly what you want to
        inspect after a failure. Worktrees persist until `clear`" (§3.3). Nothing is provisioned
        here either - no directory, no branch, no process - because a child's checkout is opened
        lazily by its first step, exactly as the run's own is. What this call costs is a dictionary
        lookup and an object.

        **The child shares this run's params, ports, counter and namespace table**, and has its own
        scope, its own base, its own checkout and its own `activity`. `worktree()` is the only real
        concurrency AGL has: §3.6 serializes steps within a namespace, so a `gather` over two steps
        on one `Run` is legal and simply does not overlap, and an author who wants two agents
        actually running at once opens two worktrees - which is what the trees root is flat for.

        **Its branch is `agl/_work/<label>/<name>`, and this method composes no part of it.**
        `tree_layout.worktree_branch` derives it and `WorkspaceProvider.open` creates it, from the
        namespace this call registers. The infix is not decoration: `agl/<label>/<name>` **cannot
        exist in git** beside `agl/<label>` in either creation order, because refs are files under
        `refs/heads/` and `agl/<label>` would have to be a file and a directory at once - and
        `git check-ref-format` passes each name individually, which is why "must be a legal ref"
        never caught it (§3.9). Routing children under `agl/_work/` keeps the deliverable branch
        cleanly named, which matters because that is the one the user pushes.

        **Idempotent: an existing name reopens rather than recreates** (§3.3), and reopening hands
        back *this same object* - so a replay walking the same calls lands in the same namespaces
        with the same chain, and two `Journal`s over one namespace, which would be two locks over
        one checkout, cannot arise. A `base` passed to a reopen is ignored, for the reason
        `WorkspaceProvider.open` ignores its own on reopen. **One name means one spelling**: this
        `Run` asking for `t-01` after `T-01` is refused rather than reopened, because the two are
        two of everything but the directory.

        **Names are unique within the run, not merely among siblings** (§3.9). The trees root is
        flat, so `T-01`'s child `sub-b` and a top-level `sub-b` are two scopes under `AGL_HOME` and
        one directory under `.trees/<label>/`; a name taken anywhere in this run is `ConflictError`
        naming both scopes, and the comparison casefolds because `T-01` and `t-01` are two refs to
        git and one directory on macOS. A malformed name is `InputError`, out of `Namespace` itself,
        before anything is registered. The name is otherwise opaque - rename `T-01` to `banana` and
        the framework behaves identically (§3.3).

        **`base` is another `Run`, a ref string, or omitted**, and a workflow with a dependency
        graph resolves its own blockers and passes the resulting `Run`: the framework never reads a
        `blocked_by` field and never learns that a graph exists (§3.3). Omitted means this Run's
        current logical head; a `Run` means that Run's; a string is taken as written and resolved
        once, later, when the child opens.

        **"Logical head" is the chain and never the physical worktree** (§3.6: "the starting head is
        chained logically, not read from disk"). It is this namespace's `base` before any entry and
        its last recorded entry's `head` after - not `Workspace.head()` and not the branch tip, both
        of which can be ahead of the chain with nothing journalled: a step that raised after
        `commit=` moved the branch and wrote no entry, and `integrate()` below moves it again on
        every landing. Cutting a child from either would hand it work this run has not recorded,
        which is the mirror of the failure §3.6 spends a paragraph on and is why this reads
        `_steps`.
        """
        # The first of this module's two `cast`s - `Workflow.params` is the other - and the field
        # docstring argues it: the table is invariant in what it holds, so holding `Run[P]` would
        # cost `Run` the covariance the two calls on this very line rest on. What makes the
        # narrowing true is that `_child` below is the only thing that ever puts a `Run` in this
        # table, and it copies `params` across unchanged.
        return cast(
            "Run[P]",
            self.worktrees.open(
                name, scope=self.scope, base=_starts_at(self, base), build=self._child
            ),
        )

    async def integrate(self) -> Integration:
        """Land this Run's work into its **parent's** worktree. §3.3's `run.integrate`.

            outcome = await run.integrate()
            while outcome.conflicted:                    # while, not if - §3.4
                if await run.terminal.show(views.conflict, conflict=outcome.conflict,
                                           build=outcome.verdict, priority=10):
                    await outcome.retry()
                else:
                    await outcome.abort()
                    break                                # load-bearing - §3.4

        **No argument, and there is nothing to point it elsewhere with** (§3.3). A landing has two
        ends and both of them are decided: the source is this Run's line of work and the target is
        the one that cut it. A `run.integrate(into=...)` would be a workflow choosing a target,
        which is a scheduling decision the framework has no vocabulary for and a way to land a
        child into a namespace whose chain nobody advances.

        **Serialized per target** (§3.4). Landings into one parent are taken one at a time, so a
        `gather` over two children's `integrate()` is legal and simply does not overlap - and the
        same lease also shuts the *parent's* own step walk while a landing is in flight, because a
        landing writes the parent's checkout and §3.6 makes a namespace's workspace single-threaded.
        Both are held until the outcome is settled, a conflict included: a target mid-landing is a
        tree no step may run in.

        **On conflict the framework does not ask** (§3.4). What comes back is an outcome whose
        `conflicted` is true, carrying a `Conflict` written for your own screen, with the target
        left held mid-landing and the lease still taken. Show whatever you like and then call one
        of the two verbs: `retry()` looks again at wherever the landing now stands - a collision
        somebody resolved by hand concludes and goes on down the same path a clean landing takes -
        and `abort()` gives up, releases the hold and puts the target back. **One of the two, on
        every path out**, including the paths where something raised: an unsettled outcome holds a
        lease that stops every later landing into that parent until the run exits.

        **The `while` and the `break` above are both §3.4's, and neither is stylistic.** `if` in
        place of `while` leaks the lease: a person who presses retry without having fixed anything
        gets a conflicted outcome back, the branch falls through, and the run holds the lease *and*
        the target's step lock until it exits. `break` closes the other end - `retry()` moves this
        outcome in place and an aborted one deliberately keeps its `Conflict`, so `conflicted` stays
        true after the verb that settled it and a loop trusting the condition alone spins forever.
        The loop ends by leaving it, never by the condition going false.

        **The view is handed `conflict=` and `build=`, never the outcome itself** (§3.4). Passing
        `outcome` would annotate a workflow author's view with `sdk/_engine`'s own private type and
        put both verbs in reach of a function whose whole job is to build a value. What a conflict
        screen renders is the port's `Conflict` plus the verifier's output when a red gate is what
        went wrong, and those two parameters are exactly that.

        **`retry()` on an outcome that has settled is `InternalError`** and `abort()` on one says
        nothing, which is `ports/integration.py`'s asymmetry inherited rather than reinvented: a
        retry with nothing pending means AGL lost track of a hold it took, while an abort meets that
        state on every ordinary path.

        **The root has no parent, so calling this there raises `InputError`.** §3.3 and §3.9: AGL
        never checks out or writes to any ref outside `agl/*`, so `main` and every branch of yours
        is **unaddressable rather than policy-protected** - there is no rule here to relax and no
        argument that would name one.

        **The parent's `last_good` advances to the landing's head** (§3.6), which is what keeps the
        parent's next fingerprint miss from restoring to a commit before every child that has
        landed and deleting all of it. Nothing journals an integration, so that advance lives as
        long as the process and a resume rebuilds the chain by walking the entries again.
        """
        if self._parent is None:
            raise InputError(_unaddressable(self.scope))
        # Two private names of two classes in one package, which is what `_starts_at` below already
        # does one member over: what a `Run` lands into is this module's business, and a public
        # `parent` would be a seventh member of §3.3's six handing every workflow author a tree to
        # walk. `Steps.landing` is the seam on the other side and argues its own half.
        return await _integrate(
            source=self._steps,
            target=self._parent._steps,
            address=self._parent.scope,
            services=self.services,
            leases=self.leases,
        )

    def _child(self, scope: RunScope, base: str) -> Run[P]:
        """One child `Run`, at an address and a starting head the table has already decided.

        Private, and called once per namespace by `Worktrees.open` - never by `worktree()` directly,
        which is what makes a reopen structurally unable to build a second `Run` over one namespace.
        The fields it does not vary are the ones a child must not vary: the params and the ports are
        the run's, and every shared table - the counter, the namespaces, the leases, the reported
        capabilities - is *this object's* rather than a new one, for the reasons each field gives.

        **And this is the one line that sets `_parent`**, which follows from that same sentence
        rather than being a second rule to keep: a child is built here exactly once per namespace,
        so the link is written exactly once, and a reopen - which does not reach this method at all
        - hands back the same object and therefore the same parent. There is no other way to make a
        child, and so no way for one to acquire a parent that did not cut it.
        """
        return Run(
            params=self.params,
            services=self.services,
            scope=scope,
            base=base,
            fingerprints=self.fingerprints,
            worktrees=self.worktrees,
            leases=self.leases,
            capabilities=self.capabilities,
            _parent=self,
        )


def _starts_at(run: Run[object], base: Run[object] | str | None) -> str:
    """§3.3's three spellings of a child's base, reduced to the one string a namespace starts at.

    A module-level function rather than a member, because it is a fact about the *argument* and not
    about the `Run` it was passed to: the `str` branch never looks at `run` at all, and the `Run`
    branch reads the other one's chain. Written as one function so the three cases sit together and
    a fourth cannot be added to only two of them.

    Reading `base._steps` is a private field of another instance of this same class, which is
    ordinary Python and is deliberate: what a `Run` starts a child at is this module's business, and
    a public `last_good` on `Run` would be a seventh member of §3.3's six offering a workflow author
    a head to branch on - which is exactly the "branch only on step results" rule read backwards.

    The two chain reads are `Steps.last_good` and never `Workspace.head()`: §3.6's "the starting
    head is chained logically, not read from disk", argued at the call site above and at
    `Steps.last_good` itself. A ref string is passed through untouched and unresolved, because this
    is a synchronous call and `History.resolve` is not one; `Steps._namespace` is where it is spent.
    """
    if base is None:
        return run._steps.last_good
    if isinstance(base, str):
        return base
    return base._steps.last_good


def _unaddressable(scope: RunScope) -> str:
    """Why the root cannot integrate, said as §3.3 and §3.9 say it rather than as a rule.

    **The distinction the message exists to make is that this is not a permission.** A refusal
    phrased as "AGL will not write to your branches" invites the next question, which is how to let
    it - a flag, a setting, a `--force`. There is nothing to let: §3.9 puts every ref AGL touches
    under `agl/*` and every checkout under the trees root, so a `Run` has exactly one thing it could
    land into and the root has none of them. `main` is not defended, it is unnameable.

    `InputError` for `Namespace`'s reason and `params.parse`'s: what the caller supplied cannot be
    used and nothing was attempted, so exit 2 sends a workflow author to the call they wrote rather
    than to a bug in the framework.
    """
    return (
        f"there is no parent to integrate into: {_where(scope)} called `run.integrate()`, and a "
        f"landing goes into the worktree of the `Run` that cut this one (§3.3). Only a child "
        f"opened with `run.worktree(name)` has one. There is no argument to point it elsewhere, "
        f"and that is not a policy: AGL never checks out or writes to any ref outside `agl/*` "
        f"(§3.9), so `main` and every branch of yours is unaddressable rather than protected - "
        f"there is no rule here that could be relaxed and no spelling that would name one"
    )


def _where(scope: RunScope) -> str:
    """Which `Run` in the tree asked, for a message and for nothing else.

    `_engine/worktrees.py` writes the same sentence for its own refusal, and this is deliberately a
    second copy rather than an import: that one is private to the module that owns the namespace
    table, and a message shared between two refusals is a message neither of them can reword.
    """
    if not scope.namespaces:
        return "the run itself"
    return "the worktree " + " -> ".join(str(name) for name in scope.namespaces)


# The one shape a workflow's function has. Private, because it is a spelling convenience rather
# than a name anything should import: `Callable[[Callable[[Run[P]], Awaitable[None]]], ...]` is
# what `workflow`'s return type says without it, and nobody reads that twice.
type _Function[P] = Callable[[Run[P]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _NoParams:
    """What `wf.params` is for a workflow annotated with a bare `Run` - §3.3's `async def fix(run:
    Run)`, a workflow that never reads `run.params`.

    **A dataclass, because "no params" has to be a params class like any other.** `Run[P]`'s PEP 696
    default is `object` and that is the right *static* answer - `run.params` is an `object` and
    reading a field off it is an error - but `object` is not a dataclass, and `params.parse`,
    `parser_for`, `to_json` and `from_json` each refuse anything that is not one. Those refusals are
    load-bearing and UF2.2 did not relax them, so resolving a bare `Run` to `object` would have made
    every `agl run` on a params-less workflow exit 2 on a workflow that declared itself correctly.

    An empty one, so nothing is invented: `parser_for` yields a parser with no flags, which is what
    makes `agl run w --anything` still an `InputError` rather than an ignored word; `to_json` yields
    `{}` and `from_json` reads `{}` back, so `run.json` records the parameters this run was given
    and they are none; and `run.params` is an instance with nothing on it, which is exactly what "no
    params" means. It is a `type[object]`, so `Workflow[object].params` type-checks unchanged.

    Private, and it is the one thing here a workflow author is not meant to be able to name: the
    class exists so that "no params" has a shape the rest of the framework already knows how to
    handle, not so that anyone declares it. Nothing is lost by not naming it - an author who wants
    to say "no parameters" writes a bare `Run`, which is §3.3's own spelling and one word shorter
    than an empty dataclass of their own.
    """


@dataclass(frozen=True, slots=True)
class Workflow[P = object]:
    """What `@workflow` produces, what an entry point resolves to, and what `registry.load`
    narrows to with `isinstance`. A workflow, as the framework knows one.

    Two fields and one derived read, and every one of the three is a fact about the function.
    Everything else about running it - fingerprints, replay, worktrees, branch naming,
    integration, preflight, exit codes, provider routing - is framework, and §3.3's table is
    emphatic that it stays framework.

    **There was a `roles` field, and UF1.3 is where it went.** 16.1 added it because preflight
    had to be *told*: roles are built inside the workflow's own body - a handler role is a closure
    over its `Run` (§3.7) - so nothing at decoration time could enumerate them, and §3.2's "collect
    the providers named by the workflow's roles" had no mechanism without a second declaration for
    an author to keep in step by hand. UF1.2 is what dissolved it. A role is now a `@role(model=…)`
    factory, and the factory carries `(name, model)` on the object bound at import - so the *model*
    is readable exactly where the role is not, and §3.2's provider check is about models.
    `sdk/_engine/preflight.py` reads the factories in the namespace `fn` was written in and asks
    this class for nothing, which is §3.11's entry for the parameter in as many words: "One
    declaration, not two."

    **And there was a `name`, which UF2.1 took off for the opposite reason.** That one was not a
    declaration of something readable elsewhere; it was a second *name* for what the entry-point
    key already names. A workflow has one name and it is that key: §3.3's
    `fix = "agl.workflows.fix:fix"` is what `agl workflows` lists, what `agl run` looks up, what
    `RunSpec.workflow` records and what the resume after it asks the registry for again. A copy here
    could only agree with the key or disagree with it, and nothing anywhere compared the two - so a
    package registered as `hotfix` while declaring `name="fix"` ran perfectly under `hotfix`,
    refused `fix`, and carried a declaration that read like the answer and decided nothing. Deleting
    the field does not make the two agree: it leaves one name, in the one place that decides
    anything, with no copy to keep in step with it.

    **And `params` was a third field, which UF2.2 turned into a read.** It is below, as a property
    over `fn`, and the class it answers with is the one the author annotated `fn`'s own first
    parameter with. That is UF2.1's removal again rather than UF1.3's: the decorator's `params=` was
    a second statement of something already written down and already enforced, and while there were
    two of them a workflow could declare one class and be handed another - `@workflow(params=X)` on
    `async def w(run: Run[Y])` type-checked as long as `Run[Y]` was assignable to `Run[X]`, which a
    bare `Run` always is. There is now one place to say it.
    """

    version: str
    """The version stamped into `RunSpec.workflow_version` at run start and compared with `==` on
    resume. Never parsed and never ordered - see the module docstring, and `ports/run.py`."""

    fn: _Function[P]
    """The `async def` itself, unwrapped and unchanged. `api.py` awaits `fn(run)`.

    **Also the whole of what preflight is given**, since UF1.3, and that is not a second job for
    this field: a function knows the module its `def` was executed in, the `@role(model=…)`
    factories a workflow can reach are the ones bound in that namespace, and a factory carries its
    model without being called. So `preflight.check(runner, wf.fn)` reads a registry rather than a
    declaration, and the field that used to tell it went away.

    **And since UF2.2 it is the whole of what the params are read from too**, which is the same
    move a second time: the annotation on this function's first parameter is a declaration mypy
    already enforces, so `params` below reads it rather than asking the author to repeat it."""

    @property
    def params(self) -> type[P]:
        """The dataclass of `arg()` fields this workflow is invoked with, read off `fn`'s own first
        parameter. The *class*: `params.parse` turns argv into an instance of it, and that instance
        is `Run.params`.

        `async def fix(run: Run[FixParams])` says `FixParams`, and a bare `Run` - §3.3's own
        spelling for a workflow that never reads its parameters - says `_NoParams`, which is what
        `Run[P]`'s PEP 696 default of `object` means once something has to parse argv into it.

        **A property, and never a field, because resolution has to be lazy.** A params class
        declared *below* the workflow function is not bound when the decorator runs, and Python
        3.14's deferred annotations make that worse rather than better: the hint is not evaluated
        until something asks. `get_type_hints(fn)` asks, through `fn.__globals__`, so a name bound
        after `@workflow` returned is a name this read can see and decoration time could not. That
        is the difference between a rule with an ordering constraint nobody wrote down and one with
        none, and `test_workflow.py` pins it with a params class declared under its own workflow.

        **Every failure here is an `InputError` and none of them is a default** - `_declared` below
        holds all five and says why each is refused rather than shrugged at. The cost of that
        choice is that the checks `@workflow` used to make at import time now happen at the first
        read, because a lazy resolver has no import-time moment left to make them in; what is
        gained is that they are made against the annotation the author wrote, and not against a
        second copy of it.

        The `cast` is this module's second, and it is the decorator's own signature read back:
        `declare` takes a `_Function[P]`, `_Function[P]` is `Callable[[Run[P]], Awaitable[None]]`,
        and so the annotation this read returns *is* the `P` mypy solved for at the decoration site.
        `_declared` claims nothing about what it found and hands back an `object`, which is honest
        about a value read out of an annotation at runtime; the narrowing is asserted here, once,
        where the argument for it can be written down.
        """
        return cast("type[P]", _declared(self.fn))


def workflow[P](*, version: str) -> Callable[[_Function[P]], Workflow[P]]:
    """Declare an async function to be a workflow. §3.3's one line of ceremony.

        @workflow(version="1.1")
        async def fix(run: Run[FixParams]) -> None:
            ...

    Keyword-only and required: a positional `@workflow("1.1")` is one string with nothing beside it
    to tell it apart from the next one. The decorated name becomes the `Workflow`, which is what the
    entry point points at - and since UF2.1 the entry point's key is the only name this workflow
    has.

    **One argument, because the decorator carries only what nothing else can see.** Three went, and
    each of them restated something the framework already had.

    There is no `roles=`, and that is UF1.3. 16.1 put one on this line because §3.2's preflight had
    no other way to see a role before the run started, and it was a second declaration of something
    the author had already written: a list to keep in step by hand with the factory calls in the
    body below it, and wrong in the quiet direction the moment the two parted. What replaced it is
    not a default and not an inference - it is that a role became a `@role(model=…)` factory
    (UF1.2), the decorator binds `(name, model)` to the object at import, and the module a workflow
    is written in is therefore already a registry of every model that workflow can name. The
    framework no longer has to be told what it can read. `sdk/_engine/preflight.py` holds what it
    costs, which is an over-approximation this decorator would have had no way to make smaller
    anyway: a workflow's body is what decides which of its module's roles a run reaches, and the
    body has not run yet.

    There is no `name=`, which is UF2.1. That one was not a declaration of something the framework
    could read elsewhere - it was a second *name* for the thing the entry-point key already names,
    free to disagree with it and compared with it by nothing. `Workflow` above argues what the
    disagreement looked like when it happened. What was deleted there is not a check: it is the pair
    of strings that made one possible.

    And there is no `params=`, which is UF2.2 and the clearest case of the three. `Run[FixParams]`
    on the function's own first parameter is a declaration **mypy already enforces** - misspell
    `run.params.reqest` and it is an error today - so `Workflow.params` reading it back is not
    inference from a coincidence but a read of the same object the author already wrote. While there
    were two of them the pair could disagree and quietly did: `Run` is covariant in `P`, so
    `@workflow(params=FixParams)` over `async def fix(run: Run)` type-checked perfectly and handed
    the run a `FixParams` the function had annotated itself unable to see.

    **`version=` is what is left, and it is the one nothing can infer.** No annotation, no registry
    and no namespace says *"I changed the shape of this workflow"*; only its author knows. It is
    also the load-bearing one - `RunSpec.workflow_version` is compared with `==` on resume, and a
    mismatch refuses the run rather than replaying a record into steps that have moved under it.

    Refuses with `InputError` - the module docstring argues the class - an empty `version` and a
    function that is not a coroutine function, both at import time, which is where a package that
    cannot be invoked correctly should fail. What the first parameter's annotation says is refused
    at the first read of `params` instead, and `Workflow.params` says why it cannot be sooner.
    """
    _check_text("version", version)

    def declare(fn: _Function[P]) -> Workflow[P]:
        if not iscoroutinefunction(fn):
            raise InputError(
                f"{fn!r} is decorated as a workflow and is not an `async def`. A workflow is one "
                f"async function (§3.3), the framework awaits it, and a plain function returning "
                f"an awaitable type-checks here and then never yields"
            )
        return Workflow(version=version, fn=fn)

    return declare


def _check_text(field: str, value: str) -> None:
    """Emptiness, and nothing else, for the same reason `RunSpec` asserts only that: what a good
    version looks like is the author's judgement and this module has no opinion past there being
    one. Whitespace counts as empty - a version of spaces stamps nothing a resume could compare."""
    if not value.strip():
        raise InputError(
            f"a workflow's {field} is required and cannot be blank: `@workflow` was given "
            f"{value!r}. It is written into every run record this workflow starts, and `RunSpec` "
            f"refuses an empty `workflow_version` - so a run declared this way could not be "
            f"recorded, let alone resumed"
        )


def _declared(fn: Callable[..., object]) -> object:
    """The params class `fn`'s own first parameter is annotated with. UF2.2's whole mechanism.

    Two spellings are accepted and they are the two §3.3 writes: `Run[FixParams]`, which names the
    class, and a bare `Run`, which is a workflow saying it has no parameters and resolves to
    `_NoParams`. Everything else is an `InputError` naming the function and the line its `def` is
    on, because **the alternative to refusing here is under-approximating silently**, which is UF1's
    own failure one level up: that registry scan quietly saw no models, so preflight asked about
    none and the run died at its first step instead of at second zero. A resolver that answered
    "no params" for an annotation it could not read would refuse every flag a correctly-declared
    workflow takes, and say so at the parse, about the flag, and never about the annotation.

    So: a function taking no parameters at all, a first parameter carrying **no annotation**, an
    annotation that is not a `Run`, a `Run` subclass, and an annotation naming something that cannot
    be resolved. Five, each with a message of its own below.

    Returns `object` rather than `type[object]` and claims nothing about what it found: this is a
    value read out of an annotation at runtime, and `Workflow.params` is where the one narrowing
    claim is made and argued.
    """
    parameters, hints = _hints(fn)
    if not parameters:
        raise InputError(
            f"the workflow {_written_at(fn)} takes no parameters, and a workflow is one async "
            f"function taking a `Run` (§3.3) - which is also where it declares its own parameters, "
            f"now that `@workflow` takes only `version=`. Write `async def {fn.__qualname__}(run: "
            f"Run[YourParams])`, or `run: Run` for a workflow that never reads `run.params`"
        )
    first = parameters[0]
    if first not in hints:
        raise InputError(
            f"the workflow {_written_at(fn)} annotates nothing on its first parameter {first!r}, "
            f"and that annotation is the one place a workflow declares its parameters (§3.3). An "
            f"unannotated parameter is **not** read as a bare `Run`: the two say different things "
            f"and only one of them was written down. Write `{first}: Run[YourParams]`, or "
            f"`{first}: Run` for a workflow that never reads `run.params`"
        )
    annotation = hints[first]
    origin = get_origin(annotation)
    subject = annotation if origin is None else origin
    if subject is Run:
        arguments = get_args(annotation)
        return arguments[0] if arguments else _NoParams
    raise InputError(_not_a_run(fn, first, annotation, subject))


def _not_a_run(fn: Callable[..., object], first: str, annotation: object, subject: object) -> str:
    """Why an annotation that is not one of §3.3's two spellings cannot be read as params.

    **A `Run` subclass is refused, and it is the interesting half of this refusal.** Nothing in the
    framework builds one, `_child` is the only thing that constructs a `Run` at all after `api.py`
    has built the root, and so a workflow annotated `MyRun[FixParams]` would be handed the `Run`
    this framework makes and never the class it asked for - a promise the annotation makes and the
    run breaks. Reading `FixParams` out of it anyway is worse than refusing: it would make the
    annotation stop being the single source, because the thing it named and the thing the workflow
    receives would be two, and every argument UF2.2 rests on is that they are one. A subclass is
    also free to add type parameters of its own, at which point "the first argument" stops being a
    rule and starts being a guess about which one meant the params.
    """
    if isinstance(subject, type) and issubclass(subject, Run):
        return (
            f"the workflow {_written_at(fn)} annotates {first!r} as {_describe(annotation)}, which "
            f"is a subclass of `Run`. A workflow is handed the `Run` the framework builds, never a "
            f"class of its own, so the annotation would be describing an object this run cannot "
            f"produce - and the params are read from it precisely because it and the object agree. "
            f"§3.3 gives two spellings and they are the whole list: `Run[YourParams]`, and a bare "
            f"`Run` for a workflow that never reads `run.params`"
        )
    return (
        f"the workflow {_written_at(fn)} annotates {first!r} as {_describe(annotation)}, and a "
        f"workflow is one async function taking a `Run` (§3.3). That annotation is also where it "
        f"declares its parameters, now that `@workflow` takes only `version=`, so this is not a "
        f"style note: there is nothing here to read the params class out of. Write `{first}: "
        f"Run[YourParams]`, or `{first}: Run` for a workflow that never reads `run.params`"
    )


def _hints(fn: Callable[..., object]) -> tuple[list[str], Mapping[str, object]]:
    """`fn`'s parameter names in order, and every annotation on it resolved through `fn.__globals__`
    - which is what makes a params class declared *below* the workflow function resolvable, and what
    makes an unimportable one an `InputError` here rather than a `NameError` out of the middle of a
    run.

    **Both reads are inside one guard, and `signature` is the surprising half.** Python 3.14
    evaluates no annotation until something asks, and `inspect.signature` asks: it builds a
    `Parameter` per argument with the annotation on it, so a first parameter naming a class nothing
    binds raises `NameError` out of `signature` before `get_type_hints` is ever reached. Reading the
    parameter names through some annotation-free path instead would only move the same failure to
    the next line, so the two are taken together and refused together.

    `sdk/params.py::_hints` is the same shape for the same situation one level down, where it is a
    params class's own fields being read; this is the workflow function's parameter. Deliberately a
    second copy and not an import: that one is about a dataclass and words its message about fields,
    and a message shared between two refusals is a message neither of them can reword.
    """
    try:
        return list(signature(fn).parameters), get_type_hints(fn)
    except (NameError, TypeError) as error:
        raise InputError(
            f"the workflow {_written_at(fn)} has an annotation that cannot be resolved: {error}. "
            f"Its first parameter is read for the params class it names (§3.3), so that annotation "
            f"has to name something importable where it is written - a class defined below the "
            f"function is fine, one that is never bound at all is not"
        ) from error


def _written_at(fn: Callable[..., object]) -> str:
    """The function and the line its `def` is on, for every refusal above.

    The file and line rather than the name alone, because the reader's next move is to edit that
    annotation and a workflow package's own module is not where they are standing: these refusals
    surface through `agl run`, at the first read of `wf.params`, and the name of a function in a
    package the operator installed is not by itself somewhere to go. `__qualname__` and not
    `__name__`, so that a workflow declared inside something else shows the `<locals>` that says so.
    """
    code = fn.__code__
    return f"`{fn.__qualname__}` at {code.co_filename}:{code.co_firstlineno}"


def _describe(thing: object) -> str:
    """A class as `grep` finds it; anything that is not one - `Run[FixParams]`, `list[str]` - at its
    own repr, which is how an annotation reads back closest to how it was typed."""
    if not isinstance(thing, type):
        return repr(thing)
    return f"{thing.__module__}.{thing.__qualname__}"
