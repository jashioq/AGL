"""The two agents `fix` runs: Claude implements, OpenAI reviews.

Two module-level declarations and nothing else. §3.3 lists roles as one of the four things a
workflow author writes, and everything done *to* one - building an `AgentTask` out of it,
fingerprinting it, routing it to a provider, checking it against what a backend can do - is
framework. There is no code in this module, only data written as code, which is the whole of §1.2's
complaint about the five near-duplicate functions this replaces.

## They are declared here, at module level, because preflight cannot see them otherwise

`@workflow(roles=[implementer, reviewer])` in `__init__.py` is what §3.2's preflight walks before
the run starts: it collects the providers these two name, asks each whether its harness is
installed and authenticated, and compares each role's `requires` against what that provider can do.
A role built inside the workflow function would be invisible to it, and a Claude-plus-OpenAI run
would then die forty minutes in at the review step rather than at second zero. Nothing else about
the declaration below is a fact about the framework; that one is.

## Why the models are named here at all

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

## The prompts are files, read here, at import

`prompt_file()` reads at declaration time and hands back text, which is the sanctioned spelling
(§3.7) and not a convenience. §3.6 fingerprints `role.instructions`, so a role holding
`"prompts/implement.md"` would fingerprint the *filename*: editing the prompt would move no digest,
and a resume would replay what the old wording produced, as a cache hit, with nothing anywhere to
notice. Reading here means editing `prompts/implement.md` re-runs the implement step and everything
downstream of it, which is the build-system cascade replay exists for.

The relative paths resolve against this module's own directory, so they find
`agl/workflows/fix/prompts/` wherever this package was installed.

## Both prompts are written knowing their inputs arrive at the end

The framework appends `**inputs` as one block of canonical JSON under a fixed `## Inputs` heading,
at the end of the role's instructions, and interpolates nothing (§3.3). So neither file below
contains a placeholder, a brace or a format specifier, and both end by telling their agent what
shape to expect underneath them. `implement.md` is written for two readings on purpose - the
`implement` step passes it a `request` and the `repair` step passes it `findings`, and one prompt
covers both because the inputs, not the prompt, are what differ. `review.md` takes no inputs at all,
so nothing is appended to it and it never mentions a block that will not be there.
"""

from typing import Final

from agl.sdk import Capability, Claude, OpenAI, Restriction, Role, prompt_file
from agl.workflows.fix.findings import report_findings

__all__ = ["implementer", "reviewer"]

implementer: Final = Role(
    instructions=prompt_file("prompts/implement.md"),
    model=Claude.OPUS,
    restrictions={Restriction.NO_VCS_WRITES},
    requires={Capability.FILE_EDIT, Capability.SHELL, Capability.MID_RUN_QUESTIONS},
)
"""Claude, writing the change - and the same declaration serves `implement` and `repair`.

**One role, two steps.** They differ in what they are given, not in who they are or what they are
allowed to do, and `**inputs` is the mechanism for exactly that difference: `implement` passes a
`request`, `repair` passes `findings`, and `prompts/implement.md` is written to read correctly under
either. Two roles here would be two copies of one prompt, free to drift, for a distinction the
framework already carries.

**`NO_VCS_WRITES` on a role whose steps do pass `commit=`.** Not the pairing rule below - this is
the other half of the same idea. The framework commits whatever this agent leaves dirty, at step
end, under the message the call named, and records the resulting head as the reset target. An agent
committing on its own account gets no help from it: at best it produces a history nobody asked for
on the branch a human is going to read, and at worst it moves the branch under a framework that is
about to commit and record on top of it. Committing here is the framework's job and the restriction
says so.

**`requires` is what a backend must be able to do at all**, and this role's list is short because it
is honest. `FILE_EDIT` because writing the change is the whole task. `SHELL` because the prompt's
inner loop is a test command and a role that cannot run one cannot do test-driven development.
Not `TOOL_CALLING`: this role declares no tools, its steps are effect steps whose result is `null`,
and requiring a capability nothing here uses would refuse a backend that could have run this
perfectly well.

**`MID_RUN_QUESTIONS` is declared here even though nothing on this declaration asks a question, and
that is the interesting line.** The role that actually runs is
`replace(implementer, on_question=answer)`, built inside the workflow function because §3.7's
handler is a closure over the `Run`; `sdk/roles.py` folds the capability into `requires` at that
moment, so the running role needs it whether or not this line says so. What this line buys is
*when* the refusal happens. Preflight is two halves (§3.2): `check_ready` plus containment over the
**declared** roles at second zero, and containment again over the role actually handed to
`run.step`. Without this member, half one walks a role that does not need the capability, and a
backend that cannot ask mid-run is caught by half two - after `api.run` has written a record,
provisioned a worktree and cut a branch, leaving an operator a `DeniedError` and an `agl clear`
where they could have had a refusal before anything existed.

It is a true statement rather than an over-declaration, which is the test `sdk/roles.py` sets for
declaring a capability by hand: **every step in this workflow that uses this role uses the handler
version of it**, so there is no path on which this role runs without needing a backend that can ask.
`sdk/roles.py` sanctions the spelling in as many words - "`requires={MID_RUN_QUESTIONS}` with no
handler is left exactly as written ... which is over-declaring and is the author's business" - and
the implication it refuses to run backwards is exactly what makes this line safe: it cannot conjure
a handler, and it cannot disagree with the folded-in member, because they are the same member. It
costs nothing downstream either, `requires` being no part of a step's fingerprint."""

reviewer: Final = Role(
    instructions=prompt_file("prompts/review.md"),
    model=OpenAI.SOL,
    restrictions={Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES},
    tools=[report_findings],
    requires={Capability.SHELL, Capability.TOOL_CALLING},
)
"""OpenAI, reading what Claude wrote - and **the role whose step must never pass `commit=`.**

**This is the pairing §3.3 calls "the author's job, by convention and not enforcement", and it is
one of the three places in AGL where a mistake destroys work rather than merely costing a re-run.**
§3.3 writes "the single place" and then "(one of three - see §3.4 and §3.6)" in the same sentence;
the other two are a landing left out of the parent's chain and a red merge gate reverting a
conflict somebody resolved by hand, and neither is reachable from `fix`. The `review`
step in `__init__.py` passes no `commit=`, so when it ends - whether it returned or raised - the
framework restores this worktree to the last good head and removes everything that was not in it:
`reset --hard` *and* `clean -fd`. That is what makes a read-only step genuinely read-only, and it is
also a wipe that does not care what it is throwing away. Nothing checks the combination. Nothing
inspects whether HEAD moved. If this role were ever given a step that committed, or if the `review`
call ever grew a `commit=`, the two halves would still both do exactly what they say and the result
would be silently wrong.

So `NO_VCS_WRITES` is here as the other half of that call, and the two are to be read together:
**an agent that commits during a step that passed no `commit=` has its work discarded, silently.**

`NO_FILE_WRITES` beside it says the rest of the same intent: this role reads, it does not edit.
Note what it does *not* promise. It denies the agent's own editing tools; it cannot stop a test
command from writing a cache directory, and running the project's gates does exactly that. §3.3
names that case - "an agent that leaves a `.pytest_cache`" - as one of the reasons the wipe exists,
so the leavings are harmless and the restriction is about intent rather than about enforcement.

**`tools=[report_findings]` is what makes `review` a reporting step**, and therefore what makes
`run.step("review", reviewer)` return a `Findings` rather than `None`. If the agent ends its turn
without ever calling it, there is no payload, so there is no result, nothing is written down and the
step runs again - `RoleIncompleteError`, which the framework raises and this package never has to.

`requires`: `SHELL` because the prompt asks this agent to run the project's gates, and
`TOOL_CALLING` because it reports through a tool and a backend that cannot call one cannot finish
this step at all. Not `FILE_EDIT` - it edits nothing, and asking for it would refuse a read-only
backend that would have served perfectly.

**Not `MID_RUN_QUESTIONS`, and this role is where the absence is a decision rather than a
shortage.** `implementer` carries a handler and declares the capability; this one carries neither,
and it is not for want of a screen - `views.agent_question` would serve a reviewer's question as
well as an implementer's. It is that there is nothing here to negotiate about. This agent is handed
a finished commit and asked to say what is wrong with it, under `NO_FILE_WRITES`, into a tool whose
payload is the entire result; a question mid-review would be asking a person to help write the
review they asked for. And it is this provider that §3.7 names as "the backend with no second
asking mechanism", where a harness's own `tool_timeout_sec` can end a question the design gives no
timeout to and leave the agent with nothing to fall back on - "preflight is where this would be
caught if it can be caught at all". Declaring a handler here would be declaring exactly the
precondition §3.2's third check exists to refuse, on the one provider where it is closest to true.
The reviewer asks nothing, so nothing is declared."""
