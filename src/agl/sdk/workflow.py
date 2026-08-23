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
plus `Stop`. **Four of the six are here.** `integrate` is 14 and `terminal` is 15. They are not
stubbed, not declared raising `NotImplementedError`, and not present as attributes that refuse. A
member that exists and refuses is a member every caller has to ask about, and `hasattr` on it is
exactly the duck typing this layer was built to replace.

**`step` and `worktree` are both delegates**, to `sdk/_engine/steps.py` and
`sdk/_engine/worktrees.py`. ARCHITECTURE.md §6 carries a row for each; the argument is that this
module is the surface - a decorator, a frozen `Run`, `Stop` - and a lock, a lazily opened checkout,
a capture cell, a replay walk and a run-wide table of taken namespaces are plumbing, which `sdk/`
keeps under `_engine/` (`services.py` makes that case at length for the bundle). The fields those
two need are here, because a constructor's shape is what every call site is written against; what
they *do* with them is not.

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

## The bundle, the address, the base, and the counter

`Run.services` is `sdk/_engine/services.py`'s eight ports. It was carried unread from 10.3, on the
argument that a constructor's shape is what every call site is written against - each of
`cli/commands/`, `sdk/testing.py` at 16.5, and every test that drives a workflow - and `run.step` is
the member that now reads it: the ledger through `services.store`, the checkout through
`services.workspaces`, the dispatch through `services.agents`, the entry's timestamp through
`services.clock`.

`scope` and `base` join it for the same reason and from the same caller. `api.run` already computes
both - `RunScope(project, label)` is the address it writes the record under, and `RunSpec.base_sha`
is the resolved commit it pins for exactly this purpose (§3.6: so that "a commit landing on `main`
between run and resume" cannot change "the first step's starting head"). Deriving either inside
`step` would mean this module reading `run.json` back through the store to learn something the
caller had in a local variable.

`fingerprints` and `worktrees` are the run's two shared tables, and both are constructor arguments
with a default **because `worktree()` hands its own to every child it cuts**. §3.6 scopes `n` per
`(namespace, step name)` and `Journal.__init__` argues that one counter per run is what makes that
key mean anything; §3.9 makes a namespace unique run-wide rather than sibling-wide, and
`_engine/worktrees.py` argues that a table built privately per `Run` is a table per *namespace*,
which cannot see a name taken anywhere else in the tree. Either built privately in here would look
identical at stage 12, where a run has exactly one namespace, and would be that stage's fix silently
removed the moment `run.worktree()` cut the second. So both are fields with a default: the root
takes the default, and `_child` below passes on the objects this `Run` holds.

They are public for one reason and it is not that a workflow author needs them - none does. Every
field on this class is what the run was assembled with, and hiding two of the six behind underscores
would make the two the composition root does not pass look like a different kind of thing from the
four it does.

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

No `Run` factory, and `_child` is private. Constructing the root `Run` is the composition root's
business - `api.py` builds it out of the record it just wrote - and cutting a child is `worktree()`,
which is the one caller `_child` has. A public factory would be a second way to make a `Run` in a
tree, free to hand one a table or a counter that is not the run's, which is the failure both fields
above exist to prevent.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, is_dataclass
from inspect import iscoroutinefunction
from typing import cast

from agl.ports.errors import InputError, Stop
from agl.ports.home_layout import RunScope
from agl.sdk._engine.journal import Fingerprints
from agl.sdk._engine.services import Services
from agl.sdk._engine.steps import Steps
from agl.sdk._engine.worktrees import Worktrees
from agl.sdk.roles import Role

__all__ = ["Run", "Stop", "Workflow", "workflow"]


@dataclass(frozen=True, slots=True)
class Run[P = object]:
    """What a workflow is handed, and the whole of what it is handed. §3.3's `run`.

    Frozen for `Services`' own reason: a run is what this invocation was assembled with, and
    reassigning a field halfway through would leave two halves of a workflow disagreeing about
    which parameters they were given. Slotted, so the surface is the fields below and an attribute
    nobody declared cannot be attached to it.

    Three of §3.3's six members belong to stages 13 to 15 and are absent rather than stubbed - see
    the module docstring, which also argues each field below.
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
    covariant** - that is what lets §3.3's own `async def fix(run: Run) -> None` be decorated with
    `@workflow(params=FixParams)`, which the module docstring names as a promise of the surface and
    `test_workflow.py` pins. Every `Run` in one table really does share one `P` - the root's is the
    only table there is and `_child` is the only thing that adds to it - but nothing in the type
    system ties the two together, so `worktree()` narrows once, visibly, where it can say why."""

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
            self, "_steps", Steps(self.services, self.scope, self.base, self.fingerprints)
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

    async def step[R](
        self, name: str, role: Role[R], *, commit: str | None = None, **inputs: object
    ) -> R:
        """Run one step, or replay it. §3.3's "the only thing that persists anything".

            findings = await run.step("review", reviewer)
            await run.step("repair", implementer, findings=findings.high(),
                           commit="address review findings")

        Resolves an entry from `(label, namespace, name)` plus a fingerprint over the role, the
        inputs and this namespace's starting head. **On a hit it returns the stored value without
        running anything** - no agent, no adapter, no cost. On a miss it restores the checkout to
        the last good head, builds an `AgentTask` from the `Role`, dispatches it to that model's
        provider, commits or wipes per `commit=`, and records what came back.

        **`commit=` is the one place in AGL where a mistake destroys work.** Given, the framework
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
        `outcome = await run.step("implement", implementer)` an error at the line that wrote it.

        `name` is opaque and validated on the way in - filesystem- and ref-safe, from
        `[A-Za-z0-9._-]` - because it is concatenated into a path. `R` rather than `P`: `Run[P]`
        already binds the workflow's params, and PEP 695 refuses a method parameter shadowing its
        class's.
        """
        return await self._steps.step(name, role, commit=commit, inputs=inputs)

    def worktree(self, name: str, base: Run[object] | str | None = None) -> Run[P]:
        """A child `Run` with its own worktree and its own namespace. §3.3's `run.worktree`.

            w = parent.worktree(ticket.id, base=blocker)
            await w.step("implement", implementer, commit=f"implement {ticket.id}")

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
        `commit=` moved the branch and wrote no entry, and stage 14's `integrate()` will move it
        again. Cutting a child from either would hand it work this run has not recorded, which is
        the mirror of the failure §3.6 spends a paragraph on and is why this reads `_steps`.
        """
        # The one `cast` in this module, and the field docstring argues it: the table is invariant
        # in what it holds, so holding `Run[P]` would cost `Run` the covariance §3.3's bare-`Run`
        # workflow signature rests on. What makes the narrowing true is that `_child` below is the
        # only thing that ever puts a `Run` in this table, and it copies `params` across unchanged.
        return cast(
            "Run[P]",
            self.worktrees.open(
                name, scope=self.scope, base=_starts_at(self, base), build=self._child
            ),
        )

    def _child(self, scope: RunScope, base: str) -> Run[P]:
        """One child `Run`, at an address and a starting head the table has already decided.

        Private, and called once per namespace by `Worktrees.open` - never by `worktree()` directly,
        which is what makes a reopen structurally unable to build a second `Run` over one namespace.
        The four fields it does not vary are the four a child must not vary: the params and the
        ports are the run's, and the counter and the table are *this object's* rather than new ones,
        for the reasons the module docstring gives about each.
        """
        return Run(
            params=self.params,
            services=self.services,
            scope=scope,
            base=base,
            fingerprints=self.fingerprints,
            worktrees=self.worktrees,
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
