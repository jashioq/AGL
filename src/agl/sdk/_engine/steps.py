"""What `run.step` is: a journal lookup, a task, a dispatch, a commit-or-wipe and an entry write.

§3.3 calls `run.step` "the only thing that persists anything", and everything else in AGL hangs off
it - worktrees at 13, integration at 14, the terminal at 15. It does those five things in one order:

    journal lookup -> `AgentTask` from the `Role` -> dispatch -> commit-or-wipe -> entry write

and the last arrow is the one place in this design where a mistake destroys work rather than merely
costing a re-run. §3.3 states that failure in full: "a `run.commit()` after the step would run
*after* the entry was written, so the recorded `head` would predate the commit - and `head` is the
reset target, so the next step to miss its fingerprint would delete the work." Committing is
therefore inside the step's atomic unit, which is why `commit=` is a parameter here and not a call
of its own - and why the ordering is not this module's to keep. `journal.py`'s walk owns it: this
module hands that walk a worker and a `commit=`, and the walk restores, runs, commits or wipes,
reads the head and writes the entry, in that order, in one function. Nothing in this file reads a
head or writes an entry, so there is no second place the order could be wrong.

Two things here are ordered all the same, and both are ordered by what §3.6 fingerprints:

* **The tools tuple is built before the lookup**, because a tool's name, description and payload
  schema are three of the fingerprint's terms (§3.6 rule 4). It cannot be built later without the
  address being computed from something other than what the agent is actually offered.
* **The `AgentTask` is built inside the worker**, so a replay hit builds none and touches no
  adapter at all. A task composed before the lookup would be a `Path`, a frozen value and an
  `AgentTask.__post_init__` spent on every replayed step of every resume - and, worse, would read
  as though dispatch were the thing being decided rather than the thing being skipped.

## One thing happens before all five: §3.2's capability check over the role handed in

`api.run` runs preflight over the roles the workflow **declared**, at second zero, which is the
only place a missing harness can be caught before forty minutes of work. This module runs the
containment half again, per step, over the role it was actually handed - and the two are not the
same role. §3.7's question handler is a closure over a `Run`, so a role that asks is built inside
the workflow function as `replace(declared_role, on_question=handler)`, and what preflight saw
therefore had no `MID_RUN_QUESTIONS` in `requires` while what runs does. Without this line, such a
role reaching a backend that cannot ask is the silent failure `sdk/roles.py` spends four paragraphs
refusing: the adapter must not block, so the agent is told no answer is available, the approval
gate is absent, and the step reports a result.

It is one `capabilities()` call per model per run - the run's own table is passed in - and never a
`check_ready`, which costs a turn. `sdk/_engine/preflight.py` holds the whole argument.

## Why this is a module of its own, with `Run.step` a delegate over it

`sdk/workflow.py` is the surface: a decorator, a frozen `Run`, and `Stop`. This is plumbing - a
lock, a lazily opened checkout, a capture cell, a walk - and `sdk/_engine/` is where `sdk/` keeps
plumbing, which `services.py` argues at length for the bundle. Two smaller reasons point the same
way. `workflow.py` is already at the project's 300-line convention, so the member that costs the
most to read wrongly would be the one arriving at the bottom of the longest file in the package.
And a workflow author reading `workflow.py` to find out what a `Run` *is* should not have to read
past the engine to get there.

## The checkout is opened once, lazily, and the lock here is not the journal's

A `Journal` is built over a `Workspace`, so the checkout has to exist before the walk does. This
module opens it on the first step in the namespace and never again, under `_opening`, and then
builds the one `Journal` that namespace will ever have.

**Why a lock at all, when §3.6 already serializes steps within a namespace.** That serialization is
`Journal._running`, and there is no `Journal` yet at the moment this runs. Two gathered steps in a
fresh namespace would otherwise both find nothing opened, both call `WorkspaceProvider.open`, and
both build a `Journal` - and two `Journal`s over one scope are "two locks over one namespace, which
is not a lock at all" (`Journal.__init__`). So the lock here holds exactly the one-time open shut,
and is released before the walk it enables: holding it across the step would be a second answer to a
question §3.6 has already answered inside `Journal.step`, and the first thing to go wrong with two
answers is that only one of them gets maintained.

**Why lazily, when 11.4 measured that provisioning inside a sibling coroutine hands ordering to
git.** That finding was about *siblings* - worktrees provisioned inside a `gather`, where the
suspension decides which child gets which counter slot, and the mutation went red at only 3 of 4
kill points until they were provisioned before the `gather`. A lazy open inside this lock cannot
decide anything, because nothing else in this namespace can be running: the open happens once, the
step behind it waits on the same lock in the order it arrived, and both then contend for the
journal's lock in that same order. The counter is still taken with nothing suspending between it
and the dispatch, because it is taken inside `Journal.step`, which this module reaches only after
the checkout is open.

**And the run's own worktree is no longer provisioned here first.** 13.4 gave that to `api.run`,
which opens `_base` from the pinned `RunSpec.base_sha` before the workflow function is awaited, so
that §3.9's "`agl/<label>` is a real ref from run start" holds for a run whose workflow has not yet
taken a step - and so that AGL's own integration branch lives in a `Workspace` rather than in the
user's checkout. Not one line below moved, which is the point of it having been written this way:
`WorkspaceProvider.open` is idempotent by contract - "an existing workspace is returned exactly as
it stands" - so the call in `_namespace` hands back that same checkout with whatever is in it,
rather than cutting a second one. What changed is which caller is first, and only for the run's own
namespace: every child a `worktree()` cuts is still provisioned here, on its first step, and the
paragraphs above are why that is safe.

## `Fingerprints` is the run's, and this is the seam `worktree()` fills

One counter per run, shared by every namespace's `Journal` - `Journal.__init__` argues why, and the
short version is that its key already carries the scope, so a counter built per journal would be
rule 1's fix removed. At stage 12 a run had exactly one namespace, so a counter built per `Run`
happened to be indistinguishable from the right thing, which is precisely why it is a constructor
argument on `Run` and a constructor argument here rather than something either of them builds.
`run.worktree()` cuts a child `Run` and hands it *this* object; a counter buried in a constructor
with no way in would leave it building a second one, and two counters over one run is the failure
§3.6 spells out - siblings each looking in their own ledger of counts for a digest that is not
there, both re-running, forever, silently.

## The starting head: read from here, resolved here, and never read from disk

Two members added at 13.2 and they are the same sentence from two ends. `last_good` hands out where
this namespace's chain has got to, synchronously, because `Run.worktree` is a plain call and a
child's base is that value; `_namespace` turns whatever this `Steps` was built with into a resolved
commit id, once, and gives the one value to the checkout and to the `Journal` alike. Each member's
own docstring carries the argument, and the shared half is §3.6's: the chain is logical, so neither
of them may reach for `Workspace.head()` or a branch tip - both of which run ahead of the chain the
moment something moves the branch without journalling it, which a step that raised after `commit=`
already does today and `integrate()` will do deliberately at stage 14.

## The reporting tool: converted here, captured here, and never named across the port

`sdk/tools.py`'s `ReportingTool` deliberately carries no handler, because a `Role` is a module-level
value shared across steps and across concurrent runs: a handler built beside the declaration would
close over a cell shared by every invocation that role ever serves, and two siblings reporting at
once would each read the other's payload. So the conversion happens here, per invocation, and the
handler closes over this one call's `_Capture`.

What crosses the port is an ordinary `ports.agent.Tool`, indistinguishable from any other. That is
§3.3's rule that **the adapter must not learn which tool is the reporting one**, and it is not a
courtesy: `ports/agent.py` spends a paragraph on it, and both adapters are built around one uniform
move - the agent calls a tool, the adapter awaits the handler, the handler's `text` goes back into
the conversation. Nothing in this module requires either of them to change, and nothing in it may.

**A malformed payload is a rejection and not an exception** (§3.3): the declaration is asked for a
`rejection`, and if there is one it goes back as `ToolResult(rejected=True)` inside the same
conversation, so the model corrects itself. Not an adapter retry, not a workflow retry. By the time
a call is malformed there is a session in flight holding all the reasoning that produced it.

**A second call is refused and the first payload stands.** §3.3 does not say, and the two candidate
rules are last-wins and first-wins; this is first-wins, for the reason `Role.__post_init__` gives
for refusing two reporting *declarations* - "with two, `run.step` would have to pick one, and
whichever it picked would be a rule living in the framework about a decision the workflow made". Two
calls to one tool put the framework in the identical position, and the two rules differ in how they
fail. Last-wins fails silently: an agent that reports once per finding records only the last one,
the workflow reads one finding where the review found six, and nothing anywhere raises. First-wins
fails loudly and in the one channel this design already built for exactly this - the refusal goes
back to the model, in-session, in words, and the model stops. The cost is that a model which
reported and then thought better of it cannot correct itself through this tool; the payload it
committed to is what the ledger holds. That is the cheaper of the two mistakes, and it is the only
one of the two that anybody finds out about.

The rejection is answered **before** the payload is validated. A second call's contents cannot
matter, so validating first would tell the model to fix a payload that was never going to be
recorded, and buy a turn spent producing a corrected one that is refused for the other reason.

## No payload at all is `RoleIncompleteError`, raised from inside the worker

§3.3: "if the agent returns without firing it, there is no result and the step re-runs". Raised
inside the worker, deliberately, so that the walk treats it as any other failure: no entry is
written - "a step is done when its file is there" - and the commit-or-wipe still runs, so a
reviewer that scribbled on its way to not reporting cannot contaminate the retry.

Its message distinguishes what `AgentOutcome.stop_reason` distinguishes, in that field's own words:
"it ran out of turns" and "it decided it was finished" send a reader to different fixes - raise the
limit, or fix the prompt - and `None` says the message can offer neither. `AgentOutcome.text` is
quoted whole, because it is what the agent said instead of reporting and it is the only evidence
there is; capping it would trim the one thing that makes the failure legible.

## Activity: one string, held and handed back, and never written down

§3.7 gives the framework one job here and it is smaller than it looks: **hold the last string an
adapter handed over, and hand it back**. Each adapter formats its own line - `Bash: ./gradlew
build`, `Edit: domain/usecase.kt` - and the router passes it through untouched, so there is no
`Activity` type, no shared verb taxonomy, no framework lookup table and no shape imposed on what an
adapter may say. The cost is cosmetic inconsistency between backends; the gain is that no future
backend has to map its vocabulary onto another's. `_reported` is therefore an assignment, and the
absence of anything else in it is the design rather than a gap waiting to be filled.

The cell is here and not on `Run` because `Run` is a frozen slots dataclass and this is the object
it already keeps its mutable state in - the checkout, the lock, the journal. `run.activity` reads
it through a property, which is the whole of that member. One `Steps` per namespace means one cell
per namespace, which is what §3.7's "the current agent activity string for this Run" means once
13.1 cuts a child: a child Run reports its own steps and not its parent's.

**`None` when nothing is running, and it is cleared on every exit from the dispatch** - success,
failure and cancellation alike, which is what a `finally` around exactly the `agents.run` call
buys. That `finally` needs none of `journal.py`'s shielding, and the difference is worth naming:
an assignment does not suspend, so a `CancelledError` arriving cannot land between deciding to
clear the cell and clearing it. Only an ending that awaits can be interrupted halfway.

**A step replayed from cache has no activity at all, correctly, since nothing is running.** That is
structural rather than checked: `on_activity` is passed inside the worker, and a replay hit returns
the stored value without ever building the worker's task or reaching an adapter, so there is no
call that could report a line. Nothing about activity reaches an `Entry`, a fingerprint or the
store - §3.7 and §3.3 both say never persisted, and the way to keep that true is for the only
writer to be a callback the port hands out during a live call.

§3.7 notes that a Run with two steps in flight "returns the most recent" and that
`activity_for(step)` "can be added if per-step granularity turns out to matter". It is not built,
and at stage 12 the distinction has no instance to arise in: §3.6 serializes steps within a
namespace, so at most one step in this namespace is ever in flight and "the most recent" is "the
only one". A gathered pair waits its turn rather than overlapping, and the cell is written by
whichever of them holds the journal's lock.

## `**inputs` are fingerprinted by the journal and appended to the prompt here

§3.3 settles how a value reaches the agent, and it is not templating: "the framework appends one
structured block of canonical JSON under a fixed heading, and the author writes the prompt knowing
inputs arrive at the end". Templating was considered and rejected in the plan itself - `str.format`
breaks on any prompt containing a brace and these prompts carry JSON Schemas; `%` breaks on a
percent sign - so nothing in this module formats, substitutes or rewrites one character of what an
author wrote. `_composed` is a concatenation and is meant to read as one: `role.instructions` comes
out of it byte-identical, at the front, which the suite pins with a role whose text carries `{`,
`}`, `{name}`, a JSON Schema and a `%s`. Without the append, §3.3's own `w.step("triage", triage,
findings=highs)` fingerprints the findings correctly and the triage agent never sees them, which is
the whole of what 13.0(i) is.

**The block is `journal.canonical_json` and not a second serialiser**, and the reuse is the property
worth having rather than a saving: what the agent is shown is byte-for-byte what was fingerprinted,
so the prompt and the cache key cannot disagree about what the inputs were. A pretty-printer here
would be a second answer to "what do these inputs say", free to drift from the one the digest was
taken over, and what drift means in this direction is an input change the agent can see that replay
cannot - or the reverse, a re-run whose prompt is identical to the one before it. The costs come
with the reuse and are real: the separators are compact rather than spaced, `ensure_ascii=True`
renders every non-ASCII character as an escape, and §3.6 rule 6 tags every dataclass at every depth
with its qualified type name. The tag is information rather than noise - `models.Finding` tells a
model what it is looking at - and it is a fingerprint term, so a prompt that hid it would be hiding
the one thing that decides whether this step re-runs.

**Empty `inputs` appends nothing at all**: no heading, no separator, not a newline. A step that
passes none dispatches text that is not merely equal to `role.instructions` but *is* it, so every
role that takes its work from the worktree - every reviewer, most implementers - is untouched by any
of this.

**Nothing about the fingerprint moves, and the composed text is not one of its terms.**
`journal.step` still receives `instructions=role.instructions` and `inputs=inputs` as two separate
arguments, which is §3.6's shape and a **stored format**: every digest ever written was taken over
those two terms separately, so hashing the composition instead would re-run every step recorded by
every run in existence - and buy nothing, the composition being a pure function of two terms already
in there. The composed string exists for the dispatch and for nothing else. Its corollary is the
cost and belongs in the same breath: respelling `_INPUTS_HEADING` changes every prompt in AGL
without changing a single digest, so a resume would replay results the old heading produced. That is
the trade §3.6 makes for the commit message, made here knowingly, and it is why the heading is a
constant nobody is expected to touch rather than a knob.

**A replayed step composes nothing**, which falls out of where the composition is rather than being
a rule anything has to remember: it happens inside `_worker`, and a hit returns the stored value
without ever building the task.

## `context` and `plan_only` take their defaults, and one of them is unreachable

`AgentTask` carries both; `Role` declares neither, and §3.3's list of what a workflow author writes
- instructions, model, restrictions, tools, required capabilities - has no room for either. So
`context` is `None` and `plan_only` is `False`, which is `AgentTask`'s own reading of "the workflow
has none". For `context` that is honest: it is standing context for a whole task, and nothing in
AGL has any. For `plan_only` it means the field is **unreachable from a workflow** - there is no
declaration anywhere that could set it - which is a finding about §3.3's Role list rather than
something to fix by deriving it from `restrictions`, a derivation `ports/agent.py` refuses by name.
"""

import asyncio
from collections.abc import Mapping
from typing import Final, cast

from agl.ports.agent import AgentOutcome, AgentTask, StopReason, Tool, ToolResult
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import Fingerprints, Journal, canonical_json
from agl.sdk._engine.preflight import Capabilities
from agl.sdk._engine.services import Services
from agl.sdk.roles import Role, RoleIncompleteError
from agl.sdk.tools import ReportingTool

__all__ = ["Steps"]

# §3.3's fixed heading: the one line between a role's own instructions and the canonical JSON of
# that step's `**inputs`. **Fixed** is the whole of the specification - one spelling, never derived
# from a step name, a role, an input key or anything else - because "the author writes the prompt
# knowing inputs arrive at the end", and a heading assembled per call is one no prompt could be
# written against. Markdown because these prompts are markdown, and `##` rather than `#` because a
# prompt's own title is usually `#`: what this heads is a section of the instructions and not a
# second document stapled to them. Deliberately no adjective - not "Canonical JSON inputs", not "AGL
# inputs" - because the two words are what an author writes their closing paragraph against, and
# every extra one is a word that has to stay true. See the module docstring for the cost of ever
# respelling it: no digest changes, so nothing re-runs, and every prompt in AGL is different.
_INPUTS_HEADING: Final = "## Inputs"


class Steps:
    """One namespace's step engine: its checkout, its journal, and the run's shared counter.

    Built by `Run.__post_init__`. One of these per `Run`, which is one per namespace - the run's own
    at stage 12, and one more per child at 13.1 - and the state it holds is the state a namespace
    has: the checkout, the walk over it, and the lock that makes opening those two a single event.

    Three things read it and each is one line over one member. `Run.step` is `step`; `Run.worktree`
    is `last_good`, read synchronously because a child's base is its parent's logical head; and
    stage 14's integration engine is `landing`, which is the namespace a child's work goes into.
    """

    def __init__(
        self,
        services: Services,
        scope: RunScope,
        base: str,
        fingerprints: Fingerprints,
        capabilities: Capabilities,
    ) -> None:
        """The ports, the address, where this namespace starts, the run's counter and its answers.

        `base` is **usually** a resolved commit id and is allowed to be a ref expression, which is
        the one thing about this signature that changed at 13.2 and the reason `_namespace` resolves
        below. `Journal` still takes only the resolved form, for the reason its class docstring
        gives at length: the base is hashed into every first fingerprint in the namespace and handed
        to `restore`, and `RunSpec.base_sha` is pinned precisely so that a commit landing on a ref
        between run and resume cannot move either. What arrives here unresolved is exactly one case
        - a child cut by `worktree(name, base="main")`, where the call is synchronous and
        `History.resolve` is not - and it is resolved once, in `_namespace`, before either the
        checkout or the walk sees it. Nothing here checks it: `Journal` refuses an empty one, and
        git judges the rest at `restore`, where the judging happens anyway.

        `capabilities` is the run's table of what each model's backend reported (§3.2), shared down
        the tree like the counter beside it and passed in for that reason rather than built here:
        one `Steps` is one namespace, and a table per namespace would re-ask a question the port
        contracts to answer the same way for the whole run.
        """
        self._services = services
        self._scope = scope
        self._base = base
        self._fingerprints = fingerprints
        self._capabilities = capabilities
        # The checkout and the walk over it arrive together and exactly once - see `_namespace`,
        # and the module docstring for why the pair is one field rather than two.
        self._opened: tuple[Journal, Workspace] | None = None
        self._opening = asyncio.Lock()
        # §3.7's activity, and the whole of the framework's part in it: the last line an adapter
        # handed over, or `None` because nothing is running. Never read by anything below this
        # object and never written down - see the module docstring.
        self._activity: str | None = None

    @property
    def activity(self) -> str | None:
        """The line the adapter serving this namespace last reported, or `None` when idle.

        `Run.activity`'s whole implementation. A plain attribute read rather than a call, because
        §3.7's views are re-invoked per frame and `Text(run.activity)` is therefore already live -
        which is also why no component and no view parameter exists for it.
        """
        return self._activity

    @property
    def last_good(self) -> str:
        """Where this namespace's chain has got to - what a child cut from here starts at.

        §3.6's `last_good`, read from the one place it is kept: this namespace's `base` until the
        journal exists, and the journal's own after. There is no third answer and no moment with
        none, because `Journal._last_good` is initialised to exactly this `base`.

        **Synchronous, which is the reason it is a property here at all.** `Run.worktree` is a plain
        call (§3.3), so a child's base has to be readable without awaiting - and the two values that
        *are* async are precisely the two §3.6 forbids: `Workspace.head()` and the branch tip are
        the physical worktree, which can be ahead of this chain with nothing journalled (a step that
        raised after `commit=`; stage 14's `integrate()`), and reading either would hand a child
        work this run has no record of.

        Before the journal exists this answers the raw `base`, ref expression and all - the
        grandchild case in one line: a child cut from `base="main"` whose own child is cut before
        the first has opened passes `"main"` on, and each of them resolves it at its own open. Two
        resolutions of one ref can differ if something lands on it in between, which is the same
        cost `_namespace` documents for the single case and not a new one.
        """
        return self._base if self._opened is None else self._opened[0].last_good

    async def landing(self) -> tuple[Journal, Workspace]:
        """This namespace as an integration target: what work lands into, and what records that it
        did.

        **Deliverable 14's seam, and its caller is `sdk/_engine/integration.py`.** `integrate()`
        lands a child's workspace into its *parent's* and then puts `IntegrationOutcome.head` into
        the parent's chain (§3.6), so it needs both halves of one namespace and it needs them as
        objects rather than as names: `Integrator.land(source, target)` takes a `Workspace`, and
        `Journal.advance` writes a field only the live journal has. Both are here, together, because
        a landing that moved one without the other is the destructive failure §3.6 spends a
        paragraph on - the checkout ahead of the chain, and the parent's next fingerprint miss
        resetting past every child that has landed.

        **Named for what the caller wants, which is why it is not `_namespace` under a second
        name.** `_namespace` is this class's one-time open and its double-checked lock, and what
        makes it private is that its invariants are this module's to keep; another module reaching
        through that underscore would make them everybody's. One named member says who asks and what
        for, in the class that already owns both halves and opens them exactly once.

        **On `Steps` and deliberately not on `Run`.** §3.3's `Run` is six members and this is not
        among them: it hands out a checkout and a mutable chain, which is the plumbing every
        argument for `_engine/` is about, and a workflow author holding it could move their own
        parent's `last_good` without the framework hearing of it. The engine reaches it as
        `run._parent._steps.landing()` - two private names of two classes in one package, which is
        exactly what `workflow._starts_at` already does one field over.

        The open is the same one-time open every step in this namespace goes through, so landing
        into a namespace that has taken no step provisions it exactly as its first step would have.
        `WorkspaceProvider.open` is idempotent by contract - "an existing workspace is returned
        exactly as it stands" - so the run's own `_base`, already opened by `api.run` before the
        workflow was awaited, comes back with whatever is in it.
        """
        return await self._namespace()

    def _reported(self, line: str) -> None:
        """What the serving adapter calls to say what is happening. It is held, and nothing else.

        No parsing, no normalising, no truncation, no vocabulary of verbs: §3.7 makes the string
        the adapter's own and the framework's job holding it. The port asks that this not block,
        and an assignment does not.
        """
        self._activity = line

    async def step[R](
        self, name: str, role: Role[R], *, commit: str | None, inputs: Mapping[str, object]
    ) -> R:
        """Replay this step if it is recorded, and otherwise run its agent and record it.

        `Run.step`'s whole body, one layer down. The order is the module docstring's, and the two
        halves that are this module's rather than the journal's are the tools tuple - built here,
        because three of its fields are fingerprint terms - and the worker, which is where the
        `AgentTask` is composed and the dispatch happens, so that a replay hit does neither.

        The value comes back from the walk as `JsonValue` and leaves here as `R`: §3.6's "the Role
        declares the payload type and the framework deserializes on read", on a fresh run and on a
        replay alike, through the one `ReportingTool.read` that both paths share.
        """
        # First, and before anything is opened: a step name is a path segment, and a name that
        # cannot be one should be refused with nothing provisioned and no agent paid for.
        step = StepName(name)
        # §3.2's capability check, over the role that will actually run rather than over the one
        # the workflow declared - and the two differ routinely, because §3.7's handler is a closure
        # over this `Run`, so a role that asks is spelled `replace(declared, on_question=handler)`
        # here and reaches `api.run`'s preflight without `MID_RUN_QUESTIONS` in `requires`.
        # `sdk/_engine/preflight.py` argues why this half is what makes §3.2's third check real,
        # and why `check_ready` is deliberately not repeated at this line: it costs a turn, and it
        # asks about a state of the world preflight has already asked about.
        #
        # Above the journal lookup, so a role that cannot run is refused with nothing provisioned -
        # and refused on a replay as well as on a miss, which is the honest reading of "the role
        # this workflow handed over cannot run here": a workflow whose refusals depended on which
        # steps happened to be cached would be one that behaved differently on resume.
        await self._capabilities.require(self._services.agents, role, step=str(step))
        journal, workspace = await self._namespace()

        # At most one `ReportingTool` in `role.tools` - `Role.__post_init__` refuses two - so the
        # loop cannot overwrite a capture, and the tuple keeps the author's declaration order,
        # which §3.6 rule 4 makes a fingerprint term rather than a presentation choice.
        capture: _Capture[R] | None = None
        tools: list[Tool] = []
        for declared in role.tools:
            if isinstance(declared, ReportingTool):
                capture = _Capture(declared)
                tools.append(capture.tool)
            else:
                tools.append(declared)
        offered = tuple(tools)

        async def _worker() -> JsonValue:
            """Everything a miss costs: one task, one dispatch, and what the agent reported."""
            try:
                outcome = await self._services.agents.run(
                    AgentTask(
                        # §3.3's append, and the only line in AGL that decides what an agent is
                        # asked: the role's own text, then this step's inputs under a fixed
                        # heading. Composed here rather than above the lookup, so a replay hit
                        # composes nothing - the same reason the whole task is built in here - and
                        # `journal.step` below still fingerprints the two terms separately, which
                        # the module docstring argues at length is not an oversight.
                        instructions=_composed(role.instructions, inputs),
                        workspace=workspace.path,
                        model=role.model,
                        restrictions=frozenset(role.restrictions),
                        tools=offered,
                    ),
                    # The role's own handler, passed through untouched (§3.7). A role that declares
                    # one has `Capability.MID_RUN_QUESTIONS` folded into `requires` at declaration
                    # time, so not passing it would leave a workflow's approval gate silently
                    # absent while preflight went on insisting the backend could ask - which
                    # `roles.py` names as the one outcome this design keeps buying checks to avoid.
                    on_question=role.on_question,
                    # And its sibling, `on_activity`. Passed here and nowhere else, which is what
                    # makes "a step replayed from cache has no activity at all" (§3.7) a fact about
                    # where this line is rather than a rule anything has to remember.
                    on_activity=self._reported,
                )
            finally:
                # `None` when nothing is running, on every exit from the dispatch and not only the
                # one that returned: an agent that died or was cancelled mid-`Bash` is not still
                # running `Bash`, and a stale line left in the cell would say it was, on a screen
                # that redraws it every frame. The module docstring says why this `finally` needs
                # no shielding where `journal.py`'s does.
                self._activity = None
            # An effect step declares no reporting tool: its result is `null` and its effect is
            # commits (§3.3). Nothing about the outcome is inspected, because there is nothing the
            # framework could do with it that the workflow did not already ask for.
            return None if capture is None else capture.reported(outcome)

        value = await journal.step(
            step,
            instructions=role.instructions,
            model=role.model,
            restrictions=role.restrictions,
            # The converted tools, not the declarations: `base_of` reads exactly the three fields
            # the two spellings share, so the digest is the same either way - and hashing what the
            # agent is actually offered is the honest one of two identical answers.
            tools=offered,
            inputs=inputs,
            worker=_worker,
            commit=commit,
        )
        if capture is None:
            # The one `cast` here, and what makes it true is `Role[P = None]`: an effect role's
            # payload type defaults to `None`, so a role with no reporting tool is a `Role[None]`
            # and this returns exactly what the annotation promises. mypy cannot derive that at
            # this line - `R` is bound by the caller's declaration and nothing in this branch
            # narrows it - which leaves one corner open and unclosable from here: a role spelled
            # `Role[Summary]` with no reporting tool in `tools` type-checks at its declaration, and
            # this hands back a `None` wearing that type. A type parameter is erased by the time
            # this runs, so `roles.py` is the only place that declaration could be refused.
            return cast(R, None)
        return capture.read(value)

    async def _namespace(self) -> tuple[Journal, Workspace]:
        """This namespace's checkout and the one journal over it, opened once, on first use.

        Double-checked around `_opening` rather than guarded by it alone, so that every step after
        the first pays nothing at all - not a lock acquisition, and not the suspension an
        acquisition can be. The re-check inside is the half that matters: two gathered steps in a
        fresh namespace both see `None`, and without it the second would open a second checkout and
        build a second `Journal`, which is two locks over one namespace and so no lock at all.

        **The base is resolved here, once, and the resolved value goes to both.**
        `WorkspaceProvider.open` accepts a ref expression or a commit id, deliberately, and
        `Journal` accepts only the second - so this is the one place the two forms meet, and it
        spends a single value on both so the cut and the chain cannot disagree about where this
        namespace began. `History.resolve` on a full object name is the identity (a commit id is a
        valid ref expression), so this is a no-op for the root and for every `Run`-derived child,
        and does real work only for `worktree(name, base="main")`.

        **What that leaves standing, stated rather than discovered.** A ref-string base is *not*
        pinned across a resume the way `RunSpec.base_sha` is: §3.6 pins the run's own base precisely
        so that "a commit landing on `main` between run and resume" cannot move the first step's
        head, and a child cut from a ref re-resolves at every open. If that ref has moved, the
        child's first fingerprint moves with it and its steps re-run. That is loud in the bill and
        never a false cache hit - the digest differs, so nothing wrong is ever replayed - and the
        workflow that wants a pin passes a `Run` or a commit id, both of which are already one.

        The grandchild case follows from `last_good` and is worth naming here too: a child cut from
        a ref string whose own child is cut *before* the first has opened passes the unresolved
        string on, and the grandchild resolves it at its own open. Two resolutions, possibly two
        commits, both of them honest readings of what that ref said when each namespace began.
        """
        if self._opened is not None:
            return self._opened
        async with self._opening:
            if self._opened is None:
                base = await self._services.history.resolve(self._base)
                workspace = await self._services.workspaces.open(
                    self._scope.label, _namespace_of(self._scope), base
                )
                self._opened = (
                    Journal(
                        self._services.store,
                        self._scope,
                        workspace,
                        self._services.clock,
                        self._fingerprints,
                        base,
                    ),
                    workspace,
                )
            return self._opened


class _Capture[P]:
    """One invocation's reporting tool: the `Tool` an adapter is handed, and what it captured.

    Per invocation and never per role, which is the whole reason `ReportingTool` carries no handler
    - see the module docstring. The declaration is kept beside the cell because both public answers
    need it: the handler asks it for a `rejection`, and `read` asks it for the payload dataclass.
    """

    def __init__(self, declaration: ReportingTool[P]) -> None:
        self._declaration = declaration
        self._payload: dict[str, JsonValue] | None = None
        # What crosses the port: an ordinary `Tool`, carrying nothing that says which one it is,
        # and a handler closing over this object rather than over the shared declaration.
        self.tool = Tool(
            name=declaration.name,
            description=declaration.description,
            payload_schema=declaration.payload_schema,
            handler=self._called,
        )

    async def _called(self, payload: Mapping[str, JsonValue]) -> ToolResult:
        """The agent called it. Refuse a second call, refuse a malformed one, or capture it.

        Every answer is a `ToolResult` and none is an exception, which is §3.3's rejection path:
        the model is told, inside the same conversation, and corrects itself. The order of the two
        refusals is argued in the module docstring - a second call's contents cannot matter, so
        asking about them first would cost a turn and change nothing.
        """
        if self._payload is not None:
            return ToolResult(
                text=(
                    f"{self._declaration.name} has already recorded this step's result: it records "
                    f"one payload per run, and the first one stands. This call changed nothing."
                ),
                rejected=True,
            )
        rejection = self._declaration.rejection(payload)
        if rejection is not None:
            return ToolResult(text=rejection, rejected=True)
        # Copied on the way in, for `ports/store.py`'s reason one layer earlier: this mapping
        # becomes the entry's `value`, and an adapter that kept the dict it passed would be holding
        # a live handle on a step's recorded result.
        self._payload = dict(payload)
        return ToolResult(
            text=(
                f"{self._declaration.name} recorded this step's result. Nothing further is needed "
                f"from this tool."
            )
        )

    def reported(self, outcome: AgentOutcome) -> JsonValue:
        """What the agent reported, or `RoleIncompleteError` because it never did.

        The outcome is an argument rather than a field because it is the *reason* half of the
        failure and not part of the capture: this object knows only whether a payload arrived, and
        `AgentOutcome` is what says which fix the reader should reach for.
        """
        if self._payload is None:
            raise RoleIncompleteError(_unreported(self._declaration.name, outcome))
        return self._payload

    def read(self, value: object) -> P:
        """The recorded value as the dataclass the role declared - §3.6's deserialize-on-read.

        Takes `object` because on a replay the value came off the ledger, and `ReportingTool.read`
        raises `InternalError` for one that will not fit: AGL wrote it and AGL is reading it.
        """
        return self._declaration.read(value)


def _composed(instructions: str, inputs: Mapping[str, object]) -> str:
    """§3.3's dispatch text: the role's instructions, the fixed heading, and the inputs as JSON.

    **Concatenation, and nothing else.** No `str.format`, no `%`, no f-string over the author's own
    text, no substitution of any kind - which is what lets a prompt carrying a JSON Schema, a
    literal `{name}` or a stray `%s` through unchanged, and those are the exact characters §3.3
    rejects templating over. `instructions` is either returned as it stands or emitted as the first
    element of the join, so it survives byte-identical either way.

    **Empty inputs return the argument itself**, so a step that passes none is dispatched with the
    role's instructions and not with a copy of them that happens to compare equal. That is what
    "appends nothing at all" has to mean to be worth asserting: no heading over an empty object, no
    trailing blank line, nothing for a diff of two prompts to show.

    The three parts are joined by a blank line because that is what separates sections of a markdown
    prompt, and there is no trailing newline: this value is the whole of one message and nothing
    appends to it.

    `canonical_json` can raise `InputError` and here it cannot, which is worth one clause rather
    than a guard: `journal.step` has already put these same inputs through `base_of`, and `base_of`
    canonicalises them by the same rules. A step whose inputs cannot be hashed never reaches a
    dispatch, so the refusal a workflow author sees still names `inputs.findings[0].deadline` and
    not some path this function invented.

    A module-level function and not a member: it reads nothing off a `Steps`, and the only thing it
    needs to be near is `_INPUTS_HEADING`.
    """
    if not inputs:
        return instructions
    return "\n\n".join((instructions, _INPUTS_HEADING, canonical_json(inputs)))


def _namespace_of(scope: RunScope) -> Namespace | None:
    """Which checkout this scope addresses: a child's, or `None` for the run's own `_base`.

    The deepest namespace and not the whole tuple, because the trees root is flat (§3.9) and
    `WorkspaceProvider.open` accordingly takes one name - which is also why §3.3 makes namespace
    names unique run-wide rather than merely among siblings. `None` is the only way to name the
    run's own place: §3.3 reserves `_base` and `ids.py` refuses it in every spelling, so there is no
    `Namespace` value a caller could pass instead.
    """
    return scope.namespaces[-1] if scope.namespaces else None


def _unreported(tool: str, outcome: AgentOutcome) -> str:
    """Why a reporting step has no result, and which of the two fixes to reach for."""
    return (
        f"the agent finished without ever calling {tool!r}, so this step produced no result: "
        f"nothing was recorded and it will run again on the next attempt. {_because(outcome)} It "
        f"said this instead of reporting: {outcome.text!r}"
    )


def _because(outcome: AgentOutcome) -> str:
    """`AgentOutcome.stop_reason`'s own distinction, which is the whole of what this can offer.

    Three answers because the field has three, and the middle one is the reason it is not a boolean:
    "the backend did not say" is a fact about the backend rather than a way of stopping, and a
    message that guessed for it would send a reader to a limit that was never reached.
    """
    if outcome.stop_reason is StopReason.LIMIT:
        return (
            "The backend stopped it against its will - turns, tokens, time or budget - so it may "
            "simply have run out of room before it reported: raise the limit."
        )
    if outcome.stop_reason is StopReason.COMPLETED:
        return (
            "It ended its own turn, having decided it was finished, so the limit is not what it "
            "reached: the prompt is what did not read as asking for a report through that tool."
        )
    return (
        "The backend did not say why it stopped, so neither a limit it reached nor a prompt that "
        "never asked for the report can be ruled out from here."
    )
