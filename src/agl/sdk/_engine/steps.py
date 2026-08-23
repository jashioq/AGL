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

**And provisioning the run's own worktree properly is 13.4's**, from the pinned `RunSpec.base_sha`
and per §3.9. `WorkspaceProvider.open` is idempotent by contract - "an existing workspace is
returned exactly as it stands" - so what this does today is provision it on first use and what 13.4
does is provision it before a workflow is entered. The call below does not change; what changes is
that it stops being the first one.

## `Fingerprints` is the run's, and this is the seam 13.1 fills

One counter per run, shared by every namespace's `Journal` - `Journal.__init__` argues why, and the
short version is that its key already carries the scope, so a counter built per journal would be
rule 1's fix removed. At stage 12 a run has exactly one namespace, so a counter built per `Run`
happens to be indistinguishable from the right thing, which is precisely why it is a constructor
argument on `Run` and a constructor argument here rather than something either of them builds.
13.1's `run.worktree()` cuts a child `Run` and must hand it *this* object; a counter buried in a
constructor with no way in would leave it building a second one, and two counters over one run is
the failure §3.6 spells out - siblings each looking in their own ledger of counts for a digest that
is not there, both re-running, forever, silently.

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

## `**inputs` are fingerprint terms, and this module does not touch the prompt

§3.3 calls them "ordinary Python values interpolated into the prompt", and *that they are part of
the fingerprint* is the half of that sentence AGL implements: they go to `base_of` and nowhere else,
and `AgentTask.instructions` is `role.instructions` verbatim. Interpolation is deliberately not
performed here, because the plan specifies no syntax for it and every syntax that could be invented
is worse than none. `str.format` breaks any prompt containing a brace, and prompts contain JSON
Schemas, code and examples; `%` breaks any prompt containing a percent sign; and a rendered block
appended to the prompt would be a format nothing in the plan describes, imposed on every role that
never asked for one. A workflow that wants a value in front of its agent builds the role where the
value is in scope and puts the text in `instructions`, which §3.6 already fingerprints - `roles.py`
notes that a role carrying `on_question` is built that way for a related reason.

**This is reported as an ambiguity in §3.3 rather than resolved silently**: under this reading the
plan's own `w.step("triage", triage, findings=highs)` fingerprints the findings correctly and does
not put them in front of the agent, which is a gap in the plan and not a decision this deliverable
is entitled to close by inventing a template language.

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
from typing import cast

from agl.ports.agent import AgentOutcome, AgentTask, StopReason, Tool, ToolResult
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import Fingerprints, Journal
from agl.sdk._engine.services import Services
from agl.sdk.roles import Role, RoleIncompleteError
from agl.sdk.tools import ReportingTool

__all__ = ["Steps"]


class Steps:
    """One namespace's step engine: its checkout, its journal, and the run's shared counter.

    Built by `Run.__post_init__` and reached only through `Run.step`, whose body is one line over
    this. One of these per `Run`, which is one per namespace - the run's own at stage 12, and one
    more per child at 13.1 - and the state it holds is the state a namespace has: the checkout, the
    walk over it, and the lock that makes opening those two a single event.
    """

    def __init__(
        self, services: Services, scope: RunScope, base: str, fingerprints: Fingerprints
    ) -> None:
        """The ports, the address, the commit this namespace starts at, and the run's counter.

        `base` is a resolved commit id and never a ref expression, for the reason `Journal`'s class
        docstring gives at length: it is hashed into every first fingerprint in this namespace and
        handed to `restore`, and `RunSpec.base_sha` is pinned precisely so that a commit landing on
        the ref between run and resume cannot move either. Nothing here checks it - `Journal`
        refuses an empty one, and git judges the rest at `restore`, where the judging happens
        anyway.
        """
        self._services = services
        self._scope = scope
        self._base = base
        self._fingerprints = fingerprints
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
                        instructions=role.instructions,
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
        """
        if self._opened is not None:
            return self._opened
        async with self._opening:
            if self._opened is None:
                workspace = await self._services.workspaces.open(
                    self._scope.label, _namespace_of(self._scope), self._base
                )
                self._opened = (
                    Journal(
                        self._services.store,
                        self._scope,
                        workspace,
                        self._services.clock,
                        self._fingerprints,
                        self._base,
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
