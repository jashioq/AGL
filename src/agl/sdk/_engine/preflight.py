"""§3.2's preflight: is every backend this workflow names ready, and can it do what is asked.

Three checks in the plan and two moments here, and the reason there are two is the whole of this
module's design.

## The framework cannot see a workflow's roles, so the workflow has to hand them over

§3.2 asks preflight to "collect the providers named by the workflow's roles", and until 16.1 there
was no mechanism at all: a `Workflow` held a name, a version, a params class and a function, and
roles are module-level declarations *inside the workflow's own package* (§3.3 keeps them "reusable
module-level declarations"). Nothing above could enumerate them. So `@workflow` grew a keyword-only
`roles=`, `Workflow` grew a `roles` field, and this module takes that tuple.

**The lazy alternative fails the stage's own acceptance criterion**, which is why it was not taken.
Checking each role at the step that uses it needs no declaration and no new keyword - and §3.2's
motivating case is a Claude+OpenAI run dying "at second zero on a missing binary or a logged-out
session, not forty minutes in at the review step". The review step is the *second* role. A per-step
check alone is precisely the failure that paragraph is written against.

## Half one, at second zero, over the roles the workflow declares: `check()`

**Availability first, over each distinct model rather than each role.** `check_ready` costs a real
turn on one of the two harnesses in view, and two roles naming one model are one question; the
answer is a state of the world and not a fact about a declaration. Distinct *models* and not
distinct providers, because that is the argument the port takes - `ports/agent.py` spends a
paragraph on why both query members carry a `ModelId`, and a routing runner asked without one
"could only answer for some provider, which is a lie in either direction".

**Then capability containment, per role, asking each model once.** §3.2 requires `capabilities()`
to be "stable for the duration of a run", so one answer per model serves every role naming it, and
`Capabilities` below is what holds them.

**Availability before capability, though capability is the cheaper refusal.** `api.py` orders its
own refusals cheapest-first and this is the one place that rule is deliberately not followed. On a
machine where the harness is missing or logged out, `capabilities()` still answers - both adapters
report a frozen constant - so its answer there is hypothetical, and refusing on it first would send
a reader to their workflow when what is wrong is their machine. The operator's first move is to
install or log in, and everything else about that backend is provisional until they have.

**Question handling falls out of containment with no special case.** §3.2's third check is that a
role declaring `on_question` resolves to a provider with `MID_RUN_QUESTIONS` - and `sdk/roles.py`
folds that member into `requires` at declaration time, so there is nothing left here to check
separately. What this module owes is one clause in the message: when the missing member is
`MID_RUN_QUESTIONS` and the role declares a handler, say that the handler is what put it there,
because otherwise the reader goes looking for a line that is not in their file. `roles.py` asks for
that sentence by name.

## Half two, at every `run.step`, over the role actually handed in: `Capabilities.require()`

Containment only, memoised per run, and **it is what makes the third check real**.

The natural spelling for a handler-carrying role is `dataclasses.replace(module_level_role,
on_question=handler)` inside the workflow function, because §3.7's handler is a closure over that
`Run`. So the role half one saw has model M and no `MID_RUN_QUESTIONS`, while the role that
actually runs needs it, and the declared tuple cannot be made to say otherwise without asking
authors to keep two declarations agreeing. Without a check at the step, a role reaching a backend
that cannot ask produces exactly the silent failure `sdk/roles.py` spends four paragraphs refusing:
the adapter must not block, so it tells the agent no answer is available, the workflow's approval
gate is simply absent, and the step reports a result. Nothing raises and nothing is logged as
wrong.

**`check_ready` is deliberately not repeated here.** It costs a turn, and it is a state of the
world preflight has already asked about; asking again once per step would spend a turn per step to
re-learn something that was true at second zero. `capabilities()` costs no turn on any backend in
view and is contracted stable for the run, so one call per model per run is the whole bill.

**There is no "was this role declared?" check, deliberately.** It would need `Run` to carry half
one's record of what the workflow handed over, `Run` is built directly by a great many tests that
never went through `api.run`, and a record arriving empty by default would make the check either
meaningless or wrong. Containment needs no injection at all: an empty `Capabilities` answers
correctly on its first call, which is why this is the half that can sit on `Run` at no cost.

## What it takes, and what it refuses with

**An `AgentRunner` and roles, never a `Services`.** One port answers both questions and the bundle
would hand this module eight; a second reader would then be one field access away, in the module
whose whole job is to refuse before anything has happened.

**`UpstreamUnavailable` passes through untouched.** The stage's acceptance criterion is that a role
naming a harness that is missing, out of date or logged out fails with that class, and the adapter
that raised it is the only thing that knows which of the three it was. `adapters/routing.py` makes
the same promise one layer down for the same reason: a wrapper here would either drop the reason a
person acts on or add a sentence naming a model the adapter's message already names.

**A capability miss is `DeniedError`, and that class is the port's choice rather than this
module's.** `ports/errors.py` holds the one exception-to-exit-code table in the codebase, and it
names this case in the class it belongs to: `DeniedError` is "the operation is well-formed and
possible, and something refused to allow it", listing among its examples "an agent lacks a
capability the role requires". That is preflight's second check written out, so there is nothing
here to decide.

**The two refusals this module can raise are the same fact about the world, split where the reader's
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
"""

from collections.abc import Sequence
from typing import Final

from agl.ports.agent import AgentRunner, Capability, ModelId
from agl.ports.errors import DeniedError
from agl.sdk.roles import Role

__all__ = ["Capabilities", "check"]

# How a refusal names the role it is about, since a `Role` has no name to quote - §1.2's whole
# point is that a role is data, and §3.3 lists no name among the terms an author writes. Half one
# knows only that the workflow declared it; half two knows the step it was handed to, which is the
# more useful of the two and is why the wording is composed here rather than fixed.
_DECLARED: Final = "a role this workflow declares"

# The one clause `sdk/roles.py` asks stage 16 to build into a message by name: "when the missing
# member is `MID_RUN_QUESTIONS` and the author never typed it, say that `on_question` put it there
# - otherwise the reader goes looking for a line that is not in their file." Whether they typed it
# is not observable from here, `Role.__post_init__` having folded the two together; a declared
# handler is what makes the sentence true either way, since a role carrying one needs that member
# whether or not it also names it.
_FROM_ON_QUESTION: Final = (
    f". {str(Capability.MID_RUN_QUESTIONS)!r} is in this role's `requires` because it declares "
    f"`on_question`: `sdk/roles.py` folds it in at declaration time, so there is no line in the "
    f"workflow to go looking for. A backend that cannot ask would not block on the question - it "
    f"would tell the agent no answer is available, leaving the approval gate silently absent and "
    f"the step reporting a result anyway (§3.7)"
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

    async def require(
        self, runner: AgentRunner, role: Role[object], *, step: str | None = None
    ) -> None:
        """Refuse `role` unless the backend serving its model offers everything it requires.

        §3.2's second and third checks in one containment, which is `sdk/roles.py`'s own reading of
        what stage 16 is written against: "one containment and no special case - `role.requires <=
        await runner.capabilities(role.model)`, per role".

        `DeniedError` - exit 5 - because a runner answered and the answer did not contain what the
        role requires, which is `ports/errors.py`'s own example of that class ("an agent lacks a
        capability the role requires") and its own contrast: refusal, not absence. The module
        docstring holds the argument and the sentence it rests on.

        `step` is the name the workflow handed this role to, and `None` says the caller is half one
        and has no step yet. It decides only how the refusal names the role; `sdk/_engine/steps.py`
        passes the validated `StepName`, so a refusal and the ledger agree about which step this
        was.

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
            raise DeniedError(_unmet(_where(step), role, missing, held))


async def check(runner: AgentRunner, roles: Sequence[Role[object]]) -> None:
    """§3.2's preflight over the roles a workflow declares. Returns nothing, or refuses.

    Called once by `api.run`, before the record is written and before anything is provisioned, so
    that a run refused here leaves nothing for an operator to `agl clear` before they can retry.
    `api.resume` (16.2) reuses this call unchanged and nothing has to move for it: that operation
    loads the same `Workflow` out of the same registry, so `wf.roles` is the same tuple and these
    two loops answer for it identically.

    Two refusals and no third. `UpstreamUnavailable` (exit 6) when a backend cannot serve a model
    right now, untouched from the adapter that said so - the harness is not there. `DeniedError`
    (exit 5) when it is there and cannot do what a role requires - something reachable said no, and
    the workflow is what changes. A workflow declaring no roles - `roles=()`, the default - passes
    without asking anything, which is what keeps `workflows/noop/` working unchanged.
    """
    # Availability first, over distinct models: the module docstring argues both halves of that
    # sentence - the ordering, and why this is not once per role.
    for model in _models(roles):
        await runner.check_ready(model)
    # One table for the pass, so two roles on one model ask once. Deliberately not the run's own
    # `Capabilities`: this runs before a `Run` exists, and handing the run a warm cache would make
    # the step-time check depend on preflight having run - which `api.resume` and every test that
    # builds a `Run` directly would then have to arrange.
    known = Capabilities()
    for role in roles:
        await known.require(runner, role)


def _models(roles: Sequence[Role[object]]) -> tuple[ModelId, ...]:
    """Every model these roles name, once each, in declaration order.

    `dict.fromkeys` rather than a `set`, because the order a refusal arrives in should be the order
    the author wrote their roles: a run naming three backends should report the first one that is
    not ready, not whichever one happened to hash lowest today.
    """
    return tuple(dict.fromkeys(role.model for role in roles))


def _where(step: str | None) -> str:
    """How the refusal names the role: by the step it was handed to, or as one the workflow made."""
    return _DECLARED if step is None else f"the role handed to step {step!r}"


def _unmet(
    where: str, role: Role[object], missing: frozenset[Capability], held: frozenset[Capability]
) -> str:
    """Why this role cannot run on this model, and which of the two things to change.

    Both sets are named, because "it requires more than this backend offers" leaves the reader to
    work out which member, and the two fixes differ per member: drop the requirement, or name a
    model whose backend has it.
    """
    wanted = sorted(str(member) for member in missing)
    offered = sorted(str(member) for member in held)
    message = (
        f"{where} cannot run on {str(role.model)!r}: it requires {wanted}, which the backend "
        f"serving that model does not offer - it reports {offered}. A capability is what a backend "
        f"can be asked for at all (§3.2), so this does not clear up on its own: either the role "
        f"names a model whose backend has it, or it stops requiring it"
    )
    if Capability.MID_RUN_QUESTIONS in missing and role.on_question is not None:
        message += _FROM_ON_QUESTION
    return message
