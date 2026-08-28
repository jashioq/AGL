"""§3.2's preflight: is every backend this workflow names ready, and can it do what is asked.

Two questions in the plan and two moments here, and which question is asked at which moment is the
whole of this module's design.

## The registry is the workflow's own module and what it binds, and preflight never calls a factory

§3.2 asks preflight to "collect the providers named by the workflow's roles", and until UF1.3 the
framework had to be *told* what those were. Roles are built inside the workflow's own body - a
handler role is a closure over its `Run` (§3.7) - so nothing at decoration time could enumerate
them, and 16.1 answered that with a keyword: `@workflow(roles=[implementer(), reviewer()])`, a
second declaration for the author to keep in step by hand with the factory calls below it.

**UF1.2 dissolved the problem rather than the symptom.** A role is a `@role(model=…)` factory
returning a frozen `Role`, and the decorator binds `(name, model)` onto the factory object at
import - so the model is readable exactly where the role is not. §3.2's first check is about
**providers**, providers come from **models**, and a model is the one thing about a role that is
knowable before the workflow's body has run. §3.11: "One declaration, not two."

**So the registry is `vars(sys.modules[fn.__module__])`, plus one level into any module bound
there, and nothing is registered anywhere else.** `sdk/roles.py` chose that scope and argues it: a
process-global table keyed by qualname would collect every role in every workflow the interpreter
has imported, and preflight would then demand a provider for a workflow that is not being run.

**The one level is UF1.5's, and what it answers is a defect rather than a preference.** A role
arrives in a workflow through one of two imports an author picks between on grounds that have
nothing to do with preflight: `from .roles import implementer` binds a factory in the workflow's
namespace, and `from . import roles` binds a *module* and reaches `roles.implementer()` through it.
Reading only the first found nothing at all in the second case - preflight asked about **zero**
models, cleared second zero naming no provider, and the run died at its first step with whatever
the adapter said. That is not a narrower registry, it is a check that silently did not run, and it
is the exact failure §3.2 exists to prevent. Neither scope is complete even now, and the section
below is where that is said rather than left to be discovered.

**The scan happens here, at preflight, and not at decoration.** A workflow's module is executed top
to bottom, so a factory written *below* the `@workflow` function is not bound to anything when the
decorator runs - a decoration-time snapshot would silently miss it and the run would reach a
backend nobody had asked about. Reading the namespace at second zero reads it after the module is
whole. `tests/sdk/test_preflight.py` pins that against a module written in that order rather than
against this paragraph.

**And a factory is never called.** §3.2: preflight "never invokes the function, which it could not
do without arguments it does not have" - `implementer(on_question=…)` takes a handler that does not
exist until a `Run` does. `RoleFactory.model` is a plain attribute for exactly this reader.

## Half one, at second zero: `check()`

**Availability, over each distinct model rather than each factory.** `check_ready` costs a real
turn on one of the two harnesses in view, and two roles naming one model are one question; the
answer is a state of the world and not a fact about a declaration. Distinct *models* and not
distinct providers, because that is the argument the port takes - `ports/agent.py` spends a
paragraph on why both query members carry a `ModelId`, and a routing runner asked without one
"could only answer for some provider, which is a lie in either direction".

**And that is all of half one.** A Claude+OpenAI run dies at second zero on a missing binary or a
logged-out session - §3.2's motivating case, and the stage's acceptance criterion in as many words:
"Preflight still refuses a logged-out provider at second zero."

## Capability containment left second zero with `roles=`, and this is what that cost

The shape before UF1.3 was two halves at second zero - `check_ready` per distinct model **and**
capability containment per role - plus containment again, memoised, at every `run.step`.

**Containment cannot be made to survive here, and the reason is structural rather than a matter of
effort.** It compares `role.requires` against `runner.capabilities(role.model)`, and `requires`
lives on the `Role` a factory *returns*. Reaching it means calling the factory. Preflight may not
call one - it has no arguments for a parameter list the author chose - so the term the comparison
needs is unreachable from the registry. A registry entry knows the model and nothing else about the
role, which is precisely why the model was put on the decorator.

**What makes the loss affordable is an argument the stage supplies about the shape that already
existed**: *the second half is the backstop that makes the first an optimisation rather than a
correctness requirement.* Containment at second zero never decided whether a bad role ran - the
step-time check did, and had to, because the role a negotiating workflow hands to `run.step` is
`factory(on_question=handler)` and not the value any earlier check could have seen. So what
disappeared was an early copy of a check that still happens, and not the check.

**What it costs, said plainly rather than waved at.** A capability mismatch is now caught at the
**first `run.step`** - after `api.run` has written a record, taken the run lock and opened a
worktree, and after the workflow function has begun. Before UF1.3 that same mismatch was refused
with nothing on disk. That is a real regression in *when* the refusal lands, and it is the price of
removing a declaration an author had to keep in step by hand. It is bounded: the refusal is the
same class with the same message and the same exit code, one step later, and `agl clear <label>` is
what takes the record away. `tests/sdk/test_preflight.py` moved the suites that measured it rather
than dropping them, and says so.

## The registry over-approximates, and that is the accepted cost

A role **imported into a workflow's module and never stepped with** is in the namespace, so
preflight demands its provider. The stage records this as known and accepted: it is a false
refusal, which is loud and fixable rather than silent, and erring toward refusing early is the
right direction. The framework cannot do better from here - which of a module's roles a run
actually reaches is decided by the workflow's body, and the body has not run.

**UF1.5 made that wider, and the widening is the same trade taken once more rather than a new
one.** A module bound in the workflow's namespace is read too, so `from . import roles` demands the
provider of every factory in `roles.py` and not only of the ones this workflow steps with - and a
workflow module that binds *another workflow's* module demands that workflow's backends as well.
The cost is real and it is larger than the paragraph above's. What it buys is that the
module-qualified spelling is checked at all, and the failure it replaces was the silent one: a
false refusal is loud, names its factory and its two modules, and is one import from being fixed.

**What this scan cannot see, said plainly rather than implied by an omission.** It reads the
`RoleFactory` values bound in the workflow's module and those bound in the modules bound there, and
that is the whole of it. It does not see a factory held in a dict, a list, or any other container;
one built at run time by a call or a comprehension rather than bound by an `import` or a `def`; one
bound two modules deep, behind a module that itself only binds another; or one reached through
anything that is not a module - a class attribute, an instance, somebody's own namespace object.
**When it misses one, the run clears second zero naming no provider and dies at the first step**,
with whatever the adapter says and nothing from here. Nothing in this module enumerates a
workflow's roles, and no line of it may be written as though it did.

**And that is acceptable for one reason rather than for a comfortable one: the per-step containment
check is the guarantee and this pass is the optimisation**, not the reverse. §3.2 says it in those
words - "preflight is a best-effort provider check plus a per-step guarantee" - and that ordering is
what makes the boundary a cost instead of a lie. A factory the scan missed is not an unchecked
role: `Capabilities.require` runs over the role the workflow actually hands to `run.step`, missed
or not, which is the check §3.2 calls the guarantee and the one no namespace could have made. What
is lost is earliness on the *other* question - a harness that is not there surfaces at the first
dispatch, in the adapter's own words, rather than at second zero in preflight's - and the cure is
the spelling, not a deeper scan: a factory bound where this function looks is checked, and §3.2's
second-zero promise is exact for the ordinary spelling and best-effort for the rest.

**So the refusal says where the demand came from.** A person meeting this reads that
`{model}` is required by the factory `{name}`, in the module it was declared in, reached from the
module the workflow is written in - and that an unused import is a known cause, of the name itself
or of a module that binds it, since after UF1.5 either can be the line to delete. Without that,
"that harness is not on `PATH`" is a dead end for a workflow whose author never meant to name that
provider at all: they have a vendor's name and nothing to pull on. `_not_ready` below is the
sentence, and `tests/sdk/test_preflight.py` asserts the over-approximation as behaviour, because it
is documented and not accidental.

**This is the one place `UpstreamUnavailable` does not pass through untouched**, and the change is
UF1.3's rather than a weakening of 16.1's rule. That rule's own argument was that a wrapper "would
either drop the reason a person acts on or add a sentence naming a model the adapter's message
already names" - and its second horn stopped being true when the model stopped coming from a
declaration. Preflight now knows something the adapter cannot: which factory, in which module, put
that model in front of it, and that the namespace it read over-approximates. The first horn is
answered by construction rather than by care - the adapter's own message is quoted verbatim at the
front of the new one, and its exception is the `__cause__`, so nothing it said is dropped and the
object it raised is still there to be inspected.

## Half two, at every `run.step`, over the role actually handed in: `Capabilities.require()`

Containment, memoised per run, and since UF1.3 **it is the whole of containment**.

The spelling for a handler-carrying role is `module_role_factory(on_question=handler)` inside the
workflow function, because §3.7's handler is a closure over that `Run` and a factory's parameter
list is the only way one reaches a role (§3.3). So the role half one could see - if it could see a
role at all - has model M and no `MID_RUN_QUESTIONS`, while the role that actually runs needs it.
Without a check at the step, a role reaching a backend that cannot ask produces exactly the silent
failure `sdk/roles.py` spends four paragraphs refusing: the adapter must not block, so it tells the
agent no answer is available, the workflow's approval gate is simply absent, and the step reports a
result. Nothing raises and nothing is logged as wrong.

**Question handling falls out of containment with no special case.** §3.2's third check is that a
role declaring `on_question` resolves to a provider with `MID_RUN_QUESTIONS` - and `sdk/roles.py`
folds that member into `requires` at declaration time, so there is nothing left to check
separately. What this module owes is one clause in the message: when the missing member is
`MID_RUN_QUESTIONS` and the role declares a handler, say that the handler is what put it there,
because otherwise the reader goes looking for a line that is not in their file. `roles.py` asks for
that sentence by name. **And so does tool calling, on the same terms, since 19.2**: a role declaring
`tools=` folds `TOOL_CALLING` in the same way, and the whole of the difference is a second clause
below. Both clauses are conditioned on the thing that *implies* the member rather than on the
member itself, since whether the author typed it is not observable from here and the sentence is
only worth saying to somebody who did not.

**`check_ready` is deliberately not repeated here.** It costs a turn, and it is a state of the
world preflight has already asked about; asking again once per step would spend a turn per step to
re-learn something that was true at second zero. `capabilities()` costs no turn on any backend in
view and is contracted stable for the run, so one call per model per run is the whole bill.

**There is no "was this role declared?" check, deliberately.** There is no declaration left to
compare against, and there was no honest one before: it would have needed `Run` to carry half one's
record, `Run` is built directly by a great many tests that never went through `api.run`, and a
record arriving empty by default would make the check either meaningless or wrong. Containment
needs no injection at all: an empty `Capabilities` answers correctly on its first call, which is
why this is the half that can sit on `Run` at no cost.

## What it takes, and what it refuses with

**An `AgentRunner` and the workflow's function, never a `Services`.** One port answers both
questions and the bundle would hand this module eight; a second reader would then be one field
access away, in the module whose whole job is to refuse before anything has happened. The function
is the smallest thing that names the registry - it knows the module its `def` was executed in - so
the composition root passes what it already holds and learns nothing about how a role is found.

**A capability miss is `DeniedError`, and that class is the port's choice rather than this
module's.** `ports/errors.py` holds the one exception-to-exit-code table in the codebase, and it
names this case in the class it belongs to: `DeniedError` is "the operation is well-formed and
possible, and something refused to allow it", listing among its examples "an agent lacks a
capability the role requires". That is preflight's second check written out, so there is nothing
here to decide.

**The two refusals a run can meet here are the same fact about the world, split where the reader's
next move splits**, and the port's contrast clause is what puts each on its own side:

* `UpstreamUnavailable`, exit 6 - **the harness is not there.** Nothing answered at all: a binary
  off `PATH`, a version too old to speak to, a session nobody is logged into. A state of the world,
  and `AgentRunner.check_ready` measures it in ten seconds of somebody's time - they log in and run
  the command again.
* `DeniedError`, exit 5 - **the harness is there and cannot do this.** A runner answered
  `capabilities()` and the answer did not contain what the role requires, which is exactly
  `DeniedError`'s "refusal, not absence: something reachable said no. If nothing answered at all,
  that is `UpstreamUnavailable`." Permanent, so the workflow is what changes: the role names a
  model whose backend has the capability, or it stops requiring it.

Not `InputError`, though "nothing was attempted" is literally true at the line that raises. That
class is for input AGL could not make sense of, and every term of the role was well-formed -
`Role.__post_init__` checked them at the line the author wrote. What failed is not the declaration
but a backend's answer about it, and the table above is where that distinction is already recorded.

There is a third class below and it is not a third refusal: `InternalError` if the module a
workflow function names is not in `sys.modules`. That is an invariant AGL controls end to end - a
function's `__module__` is the module its `def` ran in, an entry point is what imported it, and
`sys.modules` keeps a module for the life of the process - so exit 70 is the honest answer and a
`KeyError` out of a subscript is not.
"""

import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any, Final

from agl.ports.agent import AgentRunner, Capability, ModelId
from agl.ports.errors import DeniedError, InternalError, UpstreamUnavailable
from agl.sdk.roles import Role, RoleFactory

__all__ = ["Capabilities", "check"]

# The one shape preflight needs a workflow function to have, which is none: it is read for the
# module it was written in and never called. Spelled here rather than imported from
# `sdk/workflow.py` because that module imports this one for `Capabilities`, and a shared alias
# would be a cycle bought for a line of annotation.
type _Declaration = Callable[..., object]

# The two clauses `sdk/roles.py` asks stage 16 to build into a message by name: "when the missing
# member is `MID_RUN_QUESTIONS` and the author never typed it, say that `on_question` put it there,
# and when it is `TOOL_CALLING`, say that `tools=` did - otherwise the reader goes looking for a
# line that is not in their file." Whether they typed it is not observable from here,
# `Role.__post_init__` having folded each pair together; the *trigger* being declared is what makes
# each sentence true either way, since a role carrying one needs its member whether or not it also
# names it.
_FROM_ON_QUESTION: Final = (
    f". {str(Capability.MID_RUN_QUESTIONS)!r} is in this role's `requires` because it declares "
    f"`on_question`: `sdk/roles.py` folds it in at declaration time, so there is no line in the "
    f"workflow to go looking for. A backend that cannot ask would not block on the question - it "
    f"would tell the agent no answer is available, leaving the approval gate silently absent and "
    f"the step reporting a result anyway (§3.7)"
)

# The same courtesy for the second implication, and the failure it names is the louder of the two -
# a role whose tools never reach the model cannot fire the reporting one, so the step ends with no
# payload and 12.1 raises `RoleIncompleteError`. That is a real failure rather than a silent one,
# which is why this clause explains where the member came from rather than what would go wrong: the
# reader's problem is finding the declaration, and it is `tools=` and not a line of `requires=`.
_FROM_TOOLS: Final = (
    f". {str(Capability.TOOL_CALLING)!r} is in this role's `requires` because it declares `tools`: "
    f"`sdk/roles.py` folds it in at declaration time, so there is no line in the workflow to go "
    f"looking for. Either this role names a model whose backend can call a tool, or it offers none "
    f"- and a role with no tools is an effect step, whose result is `null` (§3.3)"
)


class Capabilities:
    """One run's record of what each model's backend reported, asked once per model.

    Built by `Run` with a default factory and handed to every child `worktree()` cuts, exactly as
    `Fingerprints`, `Worktrees` and `Leases` are and for a related reason: `capabilities()` is
    contracted stable for the duration of a run (§3.2), so a second table over one run would ask a
    second time for an answer that cannot have changed. Unlike those three, nothing breaks if it is
    *not* shared - a per-namespace table would be correct and merely wasteful - which is why this is
    the one of the four a directly-built `Run` can default with nothing arranged.

    No lock. Two gathered namespaces may both miss on one model and both call, and the second write
    stores the value the first did: the port makes the answer stable for the run, so a race here
    costs one redundant call and can never record two answers.
    """

    def __init__(self) -> None:
        self._known: dict[ModelId, frozenset[Capability]] = {}

    async def require(self, runner: AgentRunner, role: Role[object], *, step: str) -> None:
        """Refuse `role` unless the backend serving its model offers everything it requires.

        §3.2's second and third checks in one containment, which is `sdk/roles.py`'s own reading of
        what stage 16 is written against: "one containment and no special case - `role.requires <=
        await runner.capabilities(role.model)`, per role".

        `DeniedError` - exit 5 - because a runner answered and the answer did not contain what the
        role requires, which is `ports/errors.py`'s own example of that class ("an agent lacks a
        capability the role requires") and its own contrast: refusal, not absence. The module
        docstring holds the argument and the sentence it rests on.

        **`step` is required, and UF1.3 is why.** It is the name the workflow handed this role to,
        and it decides how the refusal names the role. It used to be optional, because half one
        called this with no step to name and a role it knew only as one the workflow had declared;
        half one no longer sees a role at all, so `sdk/_engine/steps.py` is the only caller there
        is and it passes the validated `StepName` - which is what makes a refusal and the ledger
        agree about which step this was.

        The runner arrives per call rather than at construction because this object is built by a
        default factory on a frozen `Run`, where no port is in scope yet. That costs nothing in
        honesty: `Run._child` copies `services` across unchanged, so every caller in one run hands
        over the same runner, and the cache is keyed by the only thing that varies.
        """
        held = self._known.get(role.model)
        if held is None:
            held = await runner.capabilities(role.model)
            self._known[role.model] = held
        missing = frozenset(role.requires) - held
        if missing:
            raise DeniedError(_unmet(step, role, missing, held))


async def check(runner: AgentRunner, declared_by: _Declaration) -> None:
    """§3.2's provider check over the module a workflow is written in. Returns nothing, or refuses.

    Called once by `api.run`, before the record is written and before anything is provisioned, so
    that a run refused here leaves nothing for an operator to `agl clear` before they can retry.
    `api.resume` makes the same call and nothing has to move for it: that operation loads the same
    `Workflow` out of the same registry, so it reads the same namespace and this loop answers for it
    identically.

    `declared_by` is the workflow's own `async def` - `wf.fn`, and never a `Workflow`, which this
    module could not import without a cycle. What is read off it is `__module__`, and what that
    names is the registry: the `@role(model=…)` factories bound in that namespace and in any module
    bound there, each carrying the model it will build roles on. No factory is called and no `Role`
    is built. That scan is best-effort by §3.2's own ordering and the module docstring lists what it
    cannot reach; the guarantee is `Capabilities.require` at every step.

    One refusal, and it is `UpstreamUnavailable` (exit 6) when a backend cannot serve a model right
    now - the harness is not there. The adapter's own sentence is quoted whole and its exception is
    the cause; what preflight adds is which factory, in which module, put that model in front of it,
    because the namespace over-approximates and a person meeting a provider they never meant to use
    needs to be told where the demand came from. A workflow module holding no role factory at all
    passes without asking anybody anything, which is what keeps a workflow that runs no agent
    working.

    **Capability containment is not here**, and the module docstring argues the whole of why: it
    needs `role.requires`, which is on a `Role`, which is unreachable without calling a factory this
    module has no arguments for. `Capabilities.require` at every `run.step` is where it lives, over
    the role a workflow actually handed in.
    """
    for factory in _demanded(_declared_beside(declared_by)):
        try:
            await runner.check_ready(factory.model)
        except UpstreamUnavailable as unavailable:
            raise UpstreamUnavailable(
                _not_ready(unavailable, factory, declared_by.__module__)
            ) from unavailable


def _declared_beside(declared_by: _Declaration) -> tuple[RoleFactory[..., Any], ...]:
    """Every `@role(model=…)` factory bound in the module this function was written in, and every
    one bound in a module bound there.

    Read now rather than at decoration, which is the ordering that makes this correct: a module runs
    top to bottom, so a factory written below the `@workflow` function is not bound when the
    decorator runs, and a snapshot taken there would miss it silently. By the time a run starts, the
    module is whole.

    **Two tiers, because two imports reach a role and until UF1.5 only one of them was seen.**
    `from .roles import implementer` binds a factory in the workflow's namespace; `from . import
    roles` binds a module and reaches `roles.implementer()` through it, binding no factory this
    function could find. So the second spelling asked about zero models and cleared second zero
    naming no provider - the silent miss the module docstring opens on. Imported names count in
    both tiers, which is the documented over-approximation rather than an oversight: the module
    docstring says what it costs, and `_not_ready` says it to whoever hits it.

    **Exactly one level, and nothing recurses.** A module bound inside a bound module is not read.
    The depth is a choice about how wide the over-approximation runs and not a limit of the
    mechanism, and one level is what the two spellings above need; anything deeper is one of the
    things the module docstring says this scan does not see.

    **Direct bindings first, then the ones reached through a module, `vars()` order within each.**
    `_demanded` keeps the *first* factory naming each model so that a refusal names a declaration
    its reader can go and find, and the nearest one - the line in the file they already have open -
    is the one worth naming. Within a tier the order is the namespace's own, because `dict` is
    insertion ordered and a module's namespace is one: a run naming three backends reports the
    first the author wrote, not whichever hashed lowest today.

    **One factory can arrive twice and nothing here prevents it.** `from . import roles` beside
    `from .roles import implementer` reaches one object through both tiers. `_demanded` dedups by
    *model*, which absorbs that for free along with the unrelated case of two factories naming one
    model, so a second sighting costs a `setdefault` that finds its key already taken.

    `RoleFactory[..., Any]` because neither parameter is read here. `**P` is the author's own
    signature, which preflight exists not to call, and `R` is the payload type of a role that will
    not be built - and the class is invariant in `R`, so there is no widening that would let a
    tuple of differently-typed factories be spelled honestly. What is read is `model` and `name`,
    which every factory has at the same types.
    """
    written_in = sys.modules.get(declared_by.__module__)
    if written_in is None:
        raise InternalError(
            f"the workflow function {declared_by.__qualname__!r} says it was written in "
            f"{declared_by.__module__!r}, and that module is not in `sys.modules`. "
            f"Preflight reads a workflow's role factories out of the namespace its `def` ran in "
            f"(§3.11), and an entry point is what imported that module, so there is no supported "
            f"way to reach this line"
        )
    # Taken as a tuple once, because it is walked twice and the second walk is over the same
    # bindings the first one read: two `vars()` calls would be two answers to one question.
    beside = tuple(vars(written_in).values())
    return tuple(bound for bound in beside if isinstance(bound, RoleFactory)) + tuple(
        inside
        for bound in beside
        if isinstance(bound, ModuleType)
        for inside in vars(bound).values()
        if isinstance(inside, RoleFactory)
    )


def _demanded(factories: tuple[RoleFactory[..., Any], ...]) -> tuple[RoleFactory[..., Any], ...]:
    """One factory per distinct model, in binding order: the first that named it.

    Distinct models and not distinct factories, because `check_ready` costs a real turn and two
    roles on one model are one question about the state of the world. The *factory* is carried
    along rather than the bare `ModelId` so that a refusal can name a declaration a reader can go
    and find - which is the whole of what `RoleFactory.name` is for, and the half of §3.2's
    registered `(name, model)` that is not acted on.

    `setdefault` rather than `dict.fromkeys`, for the same reason and one value along: the first
    factory naming a model is the one that put the demand there, and a later one overwriting it
    would name a line the reader has no particular cause to look at.
    """
    first: dict[ModelId, RoleFactory[..., Any]] = {}
    for factory in factories:
        first.setdefault(factory.model, factory)
    return tuple(first.values())


def _not_ready(
    refusal: UpstreamUnavailable, factory: RoleFactory[..., Any], workflow_module: str
) -> str:
    """The adapter's refusal, plus where the demand for that model came from.

    Two things a reader needs and only one of them is the adapter's. Which of installed, current
    and authenticated failed is the adapter's alone, so its sentence comes first and comes whole -
    16.1's "passes through untouched" survives as a promise about *content* rather than about
    object identity, and the exception itself is the `__cause__` for anything that wants it.

    What the adapter cannot know is why AGL asked at all. Since UF1.3 the model comes from a
    namespace scan rather than from a line the author wrote, and that scan over-approximates: a
    factory imported into the workflow's module and never stepped with demands its provider here
    just the same. So the sentence names the factory, the module it was declared in, and the module
    it was reached from - and then says that an unused import is a known cause, because otherwise
    the one person this over-approximation ever inconveniences has a provider name and no thread to
    pull.

    **Which import, since UF1.5, is the part this had to stop assuming.** The scan reads one level
    into any module bound in the workflow's namespace, so a factory can reach preflight without its
    *name* being bound in that module at all - `from . import roles` is the ordinary spelling and
    binds only `roles`. "If `<factory>` is imported into `<workflow module>` and never used" was
    then a sentence sending its reader to look for a line that is not in their file - exactly what
    `_unmet`'s two clauses exist to prevent, one check over. So both bindings are named, and so is
    what the wider scan does: importing a module for one of its roles demands the providers of all
    of them, which is the shape of false refusal a reader will not otherwise guess at. Neither
    naming needs to know which tier this factory came through - the reader has `factory.__module__`
    and their own file, and one grep answers it.
    """
    return (
        f"{refusal} - and AGL asked because {str(factory.model)!r} is the model of the role "
        f"factory `{factory.name}`, declared in {factory.__module__!r} and reached from "
        f"{workflow_module!r}, which is the module this run's workflow is written in. Preflight "
        f"reads the `@role(model=…)` factories in that namespace - and in any module bound in it - "
        f"and asks each distinct model's backend whether it is ready, without calling any of them "
        f"(§3.2). That scan over-approximates, deliberately: a role imported into a workflow's "
        f"module and never stepped with still demands its provider here, and so does every other "
        f"role of a module imported for one of them, which is the known cost of one declaration "
        f"instead of two. If nothing in {workflow_module!r} steps with `{factory.name}`, this is a "
        f"false refusal and the line that put the demand there is an import - of `{factory.name}` "
        f"itself, or of a module that binds it - so dropping that import drops this demand; "
        f"otherwise the harness above is the thing to fix"
    )


def _unmet(
    step: str, role: Role[object], missing: frozenset[Capability], held: frozenset[Capability]
) -> str:
    """Why this role cannot run on this model, and which of the two things to change.

    Both sets are named, because "it requires more than this backend offers" leaves the reader to
    work out which member, and the two fixes differ per member: drop the requirement, or name a
    model whose backend has it.

    Then a clause for each member `Role.__post_init__` could have put there rather than the author,
    because "stop requiring it" is unactionable advice about a line that is not in their file. Both
    are conditioned on the *trigger* rather than on the member, which is what keeps them honest: a
    role that typed `requires={SHELL}` gets no explanation, and one that typed `TOOL_CALLING`
    itself and declares no tools gets none either.
    """
    wanted = sorted(str(member) for member in missing)
    offered = sorted(str(member) for member in held)
    message = (
        f"the role handed to step {step!r} cannot run on {str(role.model)!r}: it requires "
        f"{wanted}, which the backend serving that model does not offer - it reports {offered}. "
        f"A capability "
        f"is what a backend can be asked for at all (§3.2), so this does not clear up on its own: "
        f"either the role names a model whose backend has it, or it stops requiring it"
    )
    if Capability.MID_RUN_QUESTIONS in missing and role.on_question is not None:
        message += _FROM_ON_QUESTION
    if Capability.TOOL_CALLING in missing and role.tools:
        message += _FROM_TOOLS
    return message
