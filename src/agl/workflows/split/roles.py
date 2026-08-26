"""The two agents `split` runs: one planner, and the implementer that every chunk gets a copy of.

Two declarations and nothing else, for `fix/roles.py`'s reasons: everything done *to* a role -
building an `AgentTask` out of it, fingerprinting it, routing it to a provider, checking it against
what a backend can do - is framework, so each function below is a `return` of one literal and no
logic. §3.3 says a role *is* "a `@role(model=…)` factory returning a frozen `Role`", and neither of
these takes an argument: nothing about a plan or a chunk implementation is decided at the call
site, so the override surface these two expose is empty and everything about them lives in this
module. `fix`'s `implementer` is the workflow with the one knob, and `fix/roles.py` argues what the
parameter list is for.

They are declared here at module level so that `__init__.py` imports two names rather than declaring
two roles; `@role(model=…)` carries `(name, model)` on the factory object at import, which is what
§3.2's preflight reads without ever calling one. **Since UF1.3 the import is the declaration**: the
namespace `__init__.py` binds these two names into is the registry preflight scans, so nothing
beside the workflow function says a second time what these two lines already say.

## One declaration, N agents

`implementer` is declared once below and produces N agents in a run: `split` opens a worktree per
chunk and every one of them runs `w.step(implementer(), chunk=c, ...)` concurrently. That is the
same "one role, two steps" idea `fix` makes about its implementer, taken one step further - the
chunks differ in what they are *given*, never in who they are, and `**inputs` is the mechanism for
exactly that difference. N *declarations* here - one factory per chunk - would be N copies of one
prompt, free to drift, for a distinction the framework already carries in the step inputs.

**One declaration is a claim about this file and not about how many times the factory is called.**
Each chunk calls it for itself, so the N values are N objects; what makes them one role is that
they are *equal* - one prompt file, one model, one restriction set, and `Role` a frozen dataclass
of frozen values with no identity to compare. §3.6 fingerprints the terms and not the object, so N
equal roles produce N equal role-halves and every chunk's step is told apart by its inputs and its
head, which is exactly what "N independent chunks" wants. Sharing one instance across concurrent
steps would have been safe too - nothing mutates it and `sdk/_engine/steps.py` builds a fresh
`AgentTask` per call - and UF1.2 did share one, hoisted above the `TaskGroup` and threaded into the
chunk coroutine as a parameter. It bought N-1 prompt reads at the price of a name, an argument and
an import, and UF1.4 unwound it; `__init__.py`'s workflow function argues that trade.

## Why both models are Claude, where `fix` names two vendors

`fix` is the workflow that proves two providers fit in one run (Part 5's target #4); `split` is the
workflow that proves N agents fit in one run without stepping on each other. Naming a second vendor
here would demonstrate nothing that is not already measured and would make this file's model choices
about coverage rather than about the work - and §3.2 is explicit that a model is named beside the
prompt because the reason is semantic.

The semantic reason is that both halves of this workflow are judgement over unfamiliar code.
Dividing a job into pieces that will not collide when they are merged is the harder of the two and
the one every later failure descends from, and implementing a chunk is `fix`'s implement step with a
narrower assignment - the chunk is smaller, but the codebase is exactly as new to the agent as it
was there. A cheaper model on the implementer is the first thing anybody will want to tune, and it
is available by editing one line; what it is not is a cost knob, which is why there is no
configuration-level override of either (`sdk/roles.py` argues that where the field is).

## The prompts are files, read here, every time a factory is called

`prompt_file()` reads at declaration time and hands back text, which is the sanctioned spelling
(§3.7) and not a convenience: §3.6 fingerprints `role.instructions`, so a role holding
`"prompts/plan.md"` would fingerprint the *filename*, editing the prompt would move no digest, and a
resume would replay what the old wording produced as a cache hit with nothing anywhere to notice.
Declaration time is each call rather than this module's import since UF1.2, and since UF1.3 no read
happens that a run did not ask for - nothing calls a factory at import any more. So a run reads
`plan.md` once and `implement.md` once per chunk, N+1 in total, each one a few microseconds against
a step that runs an agent for minutes. That is the arithmetic UF1.2 hoisted the implementer above
the `TaskGroup` to improve and UF1.4 decided was not worth what the hoist cost; `__init__.py` makes
the argument.
The relative paths resolve against this module's own directory, so they find
`agl/workflows/split/prompts/` wherever this package was installed - and that stays true from inside
a function body, a frame's globals being its own module's rather than its caller's.

Both are written knowing their inputs arrive at the end as one block of canonical JSON under a fixed
`## Inputs` heading, with nothing templated or substituted (§3.3), so neither file holds a
placeholder, a brace or a format specifier and both end by saying what shape to expect underneath
them.
"""

from agl.sdk import Capability, Claude, Restriction, Role, prompt_file, role
from agl.workflows.split.chunks import Chunks, report_chunks

__all__ = ["implementer", "planner"]


@role(model=Claude.OPUS)
def planner() -> Role[Chunks]:
    """Reads the repository and divides the job into chunks that will not collide when merged.

    **The step this role serves passes no `commit=`**, so when it ends - returned or raised - the
    framework restores its worktree to the last good head and removes everything that was not in it.
    `NO_VCS_WRITES` and `NO_FILE_WRITES` are the other half of that call, in `fix/roles.py`'s sense:
    a planner reads, it does not edit, and an agent that committed during a step that passed no
    `commit=` would have that work discarded silently. Note what `NO_FILE_WRITES` does not promise -
    it denies this agent's editing tools and cannot stop a command it runs from leaving a cache
    directory behind, which is one of the cases the wipe exists for.

    `tools=[report_chunks]` is what makes `plan` a reporting step, and therefore what makes
    `run.step(planner())` return a `Chunks` rather than `None` - through the factory's declared
    return type, which is what carries the payload parameter out of this module. An agent that ends
    its turn without calling it has produced no payload, so there is no result, nothing is written
    down and the step runs again - `RoleIncompleteError`, which the framework raises and this
    package never has to.

    `requires`: `SHELL` because the prompt's whole first half is reading the repository with `git
    ls-files`, `git grep` and `git log`, and a backend that cannot run one cannot plan anything;
    `TOOL_CALLING` because it reports through a tool and a backend that cannot call one cannot
    finish this step at all. Not `FILE_EDIT` - it edits nothing, and asking for it would refuse a
    read-only backend that would have served perfectly.

    **Not `MID_RUN_QUESTIONS`, and this is where the absence is the interesting decision.** §3.7's
    negotiation shape - propose, ask, revise, inside one step and one session - was written about
    exactly this kind of agent, and `tickets`' `decompose` has a handler for exactly this reason. It
    is declined here because `split` has one interactive screen and it is the conflict screen: §3.7
    gives that screen priority 10 *because* "a conflict screen queued behind two agent questions
    would stall the merge queue on something unrelated", and a run with N implementers and a
    negotiating planner is a run whose queue can hold several questions at once. Approving a plan
    before N agents spend an hour on it is worth real money, and it is `tickets`' business rather
    than this workflow's; adding it here would mean a third screen, a capability on both roles and a
    queue this workflow was not written to reason about. Stated as a decision because it is one, not
    because there was nothing to add."""
    return Role(
        name="plan",
        instructions=prompt_file("prompts/plan.md"),
        restrictions={Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES},
        tools=[report_chunks],
        requires={Capability.SHELL, Capability.TOOL_CALLING},
    )


@role(model=Claude.OPUS)
def implementer() -> Role:
    """One chunk, in its own worktree, cut from the same commit as every other chunk.

    **`NO_VCS_WRITES` on a role whose step does pass `commit=`.** Not the pairing rule above - this
    is the other half of the same idea, and it matters more here than it does in `fix`. The
    framework commits whatever this agent leaves dirty at step end under `implement <chunk id>`,
    records the resulting head, and that head is what `integrate()` lands into the parent. An agent
    committing on its own account moves the branch under a framework that is about to commit and
    record on top of it, and what it puts at risk is not only its own step: the head this workflow
    lands is the one the ledger recorded, so work committed outside that record is work no landing
    carries.

    **`requires` is what a backend must be able to do at all**, and this list is short because it is
    honest. `FILE_EDIT` because writing the change is the whole task. `SHELL` because the prompt's
    inner loop is a test command and a role that cannot run one cannot do test-driven development.
    Not `TOOL_CALLING`: this role declares no tools, its step is an effect step whose result is
    `None`, and requiring a capability nothing here uses would refuse a backend that could have run
    this perfectly well.

    **Not `MID_RUN_QUESTIONS`, and here the reason is arithmetic.** There are N of these running at
    once, each in a session no other one can see, and §3.7's queues are per-terminal rather than
    per-run - so N implementers with a handler is a queue that can hold N questions, each blocking
    its own step indefinitely because there are no question timeouts anywhere by design. A person
    who walks away from that returns to a run where nothing has moved and `pending` is the only
    thing that would have told them. `split` therefore runs its implementers unattended on purpose:
    everything an implementer needs to decide is in `chunk.work`, the planner is what decides it,
    and the one moment this workflow genuinely needs a person is the conflict screen at the end of a
    landing."""
    return Role(
        name="implement",
        instructions=prompt_file("prompts/implement.md"),
        restrictions={Restriction.NO_VCS_WRITES},
        requires={Capability.FILE_EDIT, Capability.SHELL},
    )
