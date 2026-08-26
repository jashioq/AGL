"""The two agents `fix` runs: Claude implements, OpenAI reviews.

Two declarations and nothing else. §3.3 lists roles as one of the four things a workflow author
writes, and everything done *to* one - building an `AgentTask` out of it, fingerprinting it, routing
it to a provider, checking it against what a backend can do - is framework. Each function below is a
`return` of one literal and no logic, which is still data written as code and is still the whole of
§1.2's complaint about the five near-duplicate functions this replaces: what the functions buy is
not behaviour but a closed override surface, argued below.

## Two factories, and what a call site of one may change

§3.3 says a role *is* "a `@role(model=…)` factory returning a frozen `Role`", and the two below are
that. The parameter list is the whole of what a call site may vary: `implementer` takes
`on_question` because §3.7's handler is a closure over the workflow's `Run` and cannot be written
at module level, and `reviewer` takes nothing at all because there is nothing about a review this
workflow decides at the call. Everything else - the prompt, the model, the restrictions, the tool,
the capabilities - is inside these functions and unreachable from `__init__.py`. What that replaced
was `replace(implementer, on_question=answer)`, which reached every field of a frozen dataclass
because `replace` cannot be given a whitelist, and which could as easily have changed the model or
dropped `NO_FILE_WRITES` (§3.11: "a mutation with pleasant syntax").

They are declared here at module level so that `__init__.py` imports two names rather than
declaring two roles, and so that a factory is one thing a reader can find: `@role(model=…)` carries
`(name, model)` on the factory object at import, which is what §3.2's preflight reads without ever
calling one - it has no arguments to call one with. **Since UF1.3 that is the mechanism and not a
description of one.** `__init__.py`'s two imports are what put these factories in the namespace
preflight scans, so the import line above the workflow function *is* the declaration, and there is
nothing beside the workflow saying the same thing a second time and free to disagree with it.

## Why the models are named on the decorators at all

§3.2: model choice is a workflow-level declaration sitting next to the prompt, because the reason
for the choice is semantic. `Claude.OPUS` implements because implementing is the half that needs
deep judgement about code it is reading for the first time; `OpenAI.SOL` reviews because a reviewer
that shares the implementer's blind spots is not a review - a second vendor is worth more here than
a second prompt. Naming a model is a domain choice, like naming a database, and it is the sanctioned
way for a workflow to say which provider it wants. **No vendor syntax appears anywhere in this
package**: not a harness name, not an SDK, not a binary. `task.model.provider` is what decides which
adapter serves these, and nothing here knows or can find out.

There is no configuration-level override of either. `sdk/roles.py` argues that where the field is:
an override buys *why is my Opus role running something else?* and costs a schema, a resolution
order and a validation rule.

## The prompts are files, read here, every time a factory is called

`prompt_file()` reads at declaration time and hands back text, which is the sanctioned spelling
(§3.7) and not a convenience. §3.6 fingerprints `role.instructions`, so a role holding
`"prompts/implement.md"` would fingerprint the *filename*: editing the prompt would move no digest,
and a resume would replay what the old wording produced, as a cache hit, with nothing anywhere to
notice. Reading here means editing `prompts/implement.md` re-runs the implement step and everything
downstream of it, which is the build-system cascade replay exists for.

Declaration time is now each call rather than this module's import, and UF1.3 took the last reads
that were not a run's: two per run and none at all at import, since nothing outside a workflow's
body calls a factory any more. `sdk/roles.py` argues why the per-call read is a non-event;
what it does change is that a missing prompt is refused at the first call rather than at the import
- still before any agent, since a workflow calls its factories at the top of its body or at the
step that uses them.

The relative paths resolve against this module's own directory, so they find
`agl/workflows/fix/prompts/` wherever this package was installed - and that stays true from inside
a function body, a frame's globals being its own module's rather than its caller's.

## Both prompts are written knowing their inputs arrive at the end

The framework appends `**inputs` as one block of canonical JSON under a fixed `## Inputs` heading,
at the end of the role's instructions, and interpolates nothing (§3.3). So neither file below
contains a placeholder, a brace or a format specifier, and both end by telling their agent what
shape to expect underneath them. `implement.md` is written for two readings on purpose - the first
of its two steps passes it a `request` and the second passes it `findings`, and one prompt covers
both because the inputs, not the prompt, are what differ. That is also why they are one role and so
one name: both are `implement` on disk, told apart by the inputs. `review.md` takes no inputs at
all, so nothing is appended to it and it never mentions a block that will not be there.
"""

from agl.sdk import (
    Capability,
    Claude,
    OpenAI,
    QuestionHandler,
    Restriction,
    Role,
    prompt_file,
    role,
)
from agl.workflows.fix.findings import Findings, report_findings

__all__ = ["implementer", "reviewer"]


@role(model=Claude.OPUS)
def implementer(*, on_question: QuestionHandler | None = None) -> Role:
    """Claude, writing the change - and one declaration serves both of the steps that write code.

    **One role, two steps.** They differ in what they are given, not in who they are or what they
    are allowed to do, and `**inputs` is the mechanism for exactly that difference: the first call
    passes a `request`, the second passes `findings`, and `prompts/implement.md` is written to read
    correctly under either. Two roles here would be two copies of one prompt, free to drift, for a
    distinction the framework already carries.

    **`name="implement"` is therefore what *both* of those steps are recorded under**, since the
    call carries no name of its own (§3.3). They land in one `steps/implement/` directory and are
    separated inside it by their digests, their inputs and their starting heads both being
    fingerprint terms - so the repair step says `implement` wherever a name is printed, and
    `__init__.py` argues that consequence where the second call is made. It is not something to work
    around here: a second role named `repair` would be the second copy of the prompt this paragraph
    exists to refuse.

    **`NO_VCS_WRITES` on a role whose steps do pass `commit=`.** Not the pairing rule below - this
    is the other half of the same idea. The framework commits whatever this agent leaves dirty, at
    step end, under the message the call named, and records the resulting head as the reset target.
    An agent committing on its own account gets no help from it: at best it produces a history
    nobody asked for on the branch a human is going to read, and at worst it moves the branch under
    a framework that is about to commit and record on top of it. Committing here is the framework's
    job and the restriction says so.

    **`requires` is what a backend must be able to do at all**, and this role's list is short
    because it is honest. `FILE_EDIT` because writing the change is the whole task. `SHELL` because
    the prompt's inner loop is a test command and a role that cannot run one cannot do test-driven
    development. Not `TOOL_CALLING`: this role declares no tools, its steps are effect steps whose
    result is `null`, and requiring a capability nothing here uses would refuse a backend that could
    have run this perfectly well.

    **`MID_RUN_QUESTIONS` is declared here even though nothing on this declaration asks a question,
    and that is the interesting line.** The role that actually runs is
    `implementer(on_question=answer)`, called inside the workflow function because §3.7's handler is
    a closure over the `Run`; `sdk/roles.py` folds the capability into `requires` at that moment, so
    the running role needs it whether or not this line says so.

    **What it buys is no longer an earlier refusal, and UF1.3 is where that changed.** Preflight's
    second-zero half reads models off factories and never a `requires`, which is on a `Role` and
    unreachable without calling one - so a backend that cannot ask mid-run is refused at the first
    `run.step` either way, and this member cannot move that. What it buys instead is that the
    declared role and the negotiating one require **the same set**. The factory's parameter list is
    the whole override surface (§3.11), and it is what a reader checks to see what a call site may
    change; with this line, no call of it can require *less* than the declaration says, so reading
    the declaration is reading what will be enforced. Without it, `implementer()` and
    `implementer(on_question=…)` would be two roles with two requirement sets, and the shorter one
    would be the one written down.

    It is a true statement rather than an over-declaration, which is the test `sdk/roles.py` sets
    for declaring a capability by hand: **every step in this workflow that uses this role uses the
    handler version of it**, so there is no path on which this role runs without needing a backend
    that can ask. `sdk/roles.py` sanctions the spelling in as many words -
    "`requires={MID_RUN_QUESTIONS}` with no handler is left exactly as written ... which is
    over-declaring and is the author's business" - and the implication it refuses to run backwards
    is exactly what makes this line safe: it cannot conjure a handler, and it cannot disagree with
    the folded-in member, because they are the same member. It costs nothing downstream either,
    `requires` being no part of a step's fingerprint."""
    return Role(
        name="implement",
        instructions=prompt_file("prompts/implement.md"),
        restrictions={Restriction.NO_VCS_WRITES},
        requires={Capability.FILE_EDIT, Capability.SHELL, Capability.MID_RUN_QUESTIONS},
        on_question=on_question,
    )


@role(model=OpenAI.SOL)
def reviewer() -> Role[Findings]:
    """OpenAI, reading what Claude wrote - and **the role whose step must never pass `commit=`.**

    **This is the pairing §3.3 calls "the author's job, by convention and not enforcement", and it
    is one of the three places in AGL where a mistake destroys work rather than merely costing a
    re-run.** §3.3 writes "the single place" and then "(one of three - see §3.4 and §3.6)" in the
    same sentence; the other two are a landing left out of the parent's chain and a red merge gate
    reverting a conflict somebody resolved by hand, and neither is reachable from `fix`. The
    `review` step in `__init__.py` passes no `commit=`, so when it ends - whether it returned or
    raised - the framework restores this worktree to the last good head and removes everything that
    was not in it: `reset --hard` *and* `clean -fd`. That is what makes a read-only step genuinely
    read-only, and it is also a wipe that does not care what it is throwing away. Nothing checks the
    combination. Nothing inspects whether HEAD moved. If this role were ever given a step that
    committed, or if the `review` call ever grew a `commit=`, the two halves would still both do
    exactly what they say and the result would be silently wrong.

    So `NO_VCS_WRITES` is here as the other half of that call, and the two are to be read together:
    **an agent that commits during a step that passed no `commit=` has its work discarded,
    silently.**

    `NO_FILE_WRITES` beside it says the rest of the same intent: this role reads, it does not edit.
    Note what it does *not* promise. It denies the agent's own editing tools; it cannot stop a test
    command from writing a cache directory, and running the project's gates does exactly that. §3.3
    names that case - "an agent that leaves a `.pytest_cache`" - as one of the reasons the wipe
    exists, so the leavings are harmless and the restriction is about intent rather than about
    enforcement.

    **`tools=[report_findings]` is what makes the review a reporting step**, and therefore what
    makes `run.step(reviewer())` return a `Findings` rather than `None` - through the factory's
    declared return type, which is what carries the payload parameter out of this module. If the
    agent ends its turn without ever calling it, there is no payload, so there is no result, nothing
    is written down and the step runs again - `RoleIncompleteError`, which the framework raises and
    this package never has to.

    `requires`: `SHELL` because the prompt asks this agent to run the project's gates, and
    `TOOL_CALLING` because it reports through a tool and a backend that cannot call one cannot
    finish this step at all. Not `FILE_EDIT` - it edits nothing, and asking for it would refuse a
    read-only backend that would have served perfectly.

    **Not `MID_RUN_QUESTIONS`, and this role is where the absence is a decision rather than a
    shortage.** `implementer` carries a handler and declares the capability; this one carries
    neither, and it is not for want of a screen - `views.agent_question` would serve a reviewer's
    question as well as an implementer's. It is that there is nothing here to negotiate about. This
    agent is handed a finished commit and asked to say what is wrong with it, under
    `NO_FILE_WRITES`, into a tool whose payload is the entire result; a question mid-review would be
    asking a person to help write the review they asked for. And it is this provider that §3.7 names
    as "the backend with no second asking mechanism", where a harness's own `tool_timeout_sec` can
    end a question the design gives no timeout to and leave the agent with nothing to fall back on -
    "preflight is where this would be caught if it can be caught at all". Declaring a handler here
    would be declaring exactly the precondition §3.2's third check exists to refuse, on the one
    provider where it is closest to true. The reviewer asks nothing, so nothing is declared."""
    return Role(
        name="review",
        instructions=prompt_file("prompts/review.md"),
        restrictions={Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES},
        tools=[report_findings],
        requires={Capability.SHELL, Capability.TOOL_CALLING},
    )
