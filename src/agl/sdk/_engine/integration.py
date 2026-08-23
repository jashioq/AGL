"""What `run.integrate()` is: the framework's lease, one landing into the parent, and the outcome
a workflow decides about.

§3.3 gives this one sentence - "merge this Run's branch into its **parent's** worktree, serialized
per target, then run the build gate and revert on failure" - and every clause of it is a decision
made here rather than behind a port. The order is fixed and the whole of it happens inside one
lease:

    open both namespaces -> read the target's head -> land -> is the source in? -> gate
    -> advance the parent's chain -> release

The last arrow but one is the one that destroys work rather than costing a re-run. §3.6:
"**`integrate()` advances the parent's `last_good`** ... the parent's next step to miss its
fingerprint would `restore()` to a commit *before* every landed child and delete all of it." That
and a mispaired `commit=` are the only two paths in AGL with that property, and `_concluded` below
carries the comment that says so at the line it happens on.

## The lease is the framework's, and this is the other end of the port's argument

§3.4: "the framework a lease per integration target - landings into one target are serialised, and
the lease is released when the run exits". `ports/integration.py` spends a section on why that is
not a member of `Integrator`, and the argument reads the same from this side: a lease is a rule
about **AGL's own concurrency** - how many of AGL's runs may be asking at once, and what becomes of
the answer when one of them dies - and not a fact about landing work. An integrator whose far side
already serialises would have to maintain a lease nothing consults; every other implementation would
be carrying enforcement of a framework rule inside whichever adapter happened to be configured,
where the framework could no longer see it. So it is here, in the module `run.integrate()` is, and
an `Integrator` gets to be three methods about work.

What is on the port and only looks like the same word is the **hold**: a conflicted `land` leaves
the target mid-landing, which is a state of the target that only the implementation can create and
only the implementation can undo. `abort` is that, and this module calls it. The two are not
alternatives - a live conflict is one lease and one hold at once - and confusing them is how a run
ends up releasing the wrong one.

## This is not §3.9's repository lock, and a reader is owed the difference in one place

§3.9 asks for a **cross-process `flock(2)`** on a file in the trees root, taken around `git worktree
add`, `prune` and `remove`, because those three mutate `.git/worktrees/` and two `agl` invocations
are two processes sharing one `.git/`. It is held for milliseconds and, in that section's own words,
"never across a merge or a human decision". It lives in `adapters/git/_trees.py` and this module
never takes it.

The lease below is the opposite of that on every axis. It is held **across a human's deliberation**
- from the moment an integration starts until its outcome is settled, conflict screen and all - and
it is scoped to **one run's integration target**, so that, §3.4's words again, "a human
deliberating in one run never blocks another". One guards a registry file for the length of a
subprocess; the other guards a merge queue for the length of an afternoon.

## In-process, and the reason is structural rather than an economy

An `asyncio.Lock` per target, and nothing on disk. That is not "good enough for v1.1": two
concurrent runs **cannot share an integration target**. A target is a run's own `_base` worktree
(§3.9), one per `agl/<label>`, and §3.10 refuses a second run under a label that already has a
record - so the set of targets one process can land into is exactly the set of targets it owns. Two
processes contend over the worktree registry, which is what §3.9's `flock` is for, and over nothing
else here.

What a cross-process lease would have to be is worth naming, because the day AGL grows something
that lands into another run's target is the day it becomes necessary: a file whose holder is
identifiable after a crash, with a release that survives the holder dying. That is a different
mechanism from a lock, and building it now would be building it against no requirement.

## Run-wide, shared down the tree, and never built inside a child

`Leases` is a field on `Run` with a default, exactly like `Run.fingerprints` and `Run.worktrees`,
and for their argument: the root takes the default and `_child` hands *this* object on. A `Leases`
built per `Run` would be a lease table per **namespace**, and a lease table per namespace
serialises nothing - two siblings landing into one parent would each hold their own lock over their
own dict and both be inside the parent's checkout at once, which is the failure the lease exists to
prevent, with the lease still nominally taken.

## Run exit releases the lease and does **not** abort the adapter's hold

`api.run` calls `Leases.release_all` in a `finally` around the workflow's function, and that is the
whole of what run exit does. It deliberately does not walk the live integrations calling
`Integrator.abort`, and the reason is the one §3.4 states about the shortcut it forbids: **the hold
is durable by design.** It is `MERGE_HEAD` in the target's own git directory, readable by a later
invocation, precisely so that "a resumed run must be able to find a hold it did not take" - and the
previous deliverable made a pre-existing hold answer as a `Conflict` rather than as exit 70, so
finding one is now an ordinary path with a screen at the end of it.

Aborting on the way out is `abort()`-before-land wearing a different hat. It "silently discards
partial human resolutions, which `retry()` exists to preserve" - and the moment it would fire is
the worst one available, because a process that is exiting while a conflict is unresolved is very
often a person who pressed Ctrl-C to go and look at the collision by hand.

The port's rule is "the run must call `retry` or `abort` on every path out of that hold", and the
subject of that sentence is the **run**. A run outlives a process; that is what `resume` is. What
this module owes the hold is that the next invocation can find it, and the durable hold is what
discharges that.

## A landing is a second writer of the target's checkout, which the plan does not write down

§3.6 says "**A namespace's workspace is single-threaded** ... two concurrent steps in one namespace
share one `Workspace`", and `Journal` holds a lock because of it: overlapped, "A's pre-run restore
wipes the files B's worker has just written, B's `commit_all` records A's changes under B's message,
and A's `head()` after its own commit reads B's". Every one of those sentences is true of a landing
into that same namespace, which restores nothing but writes the whole tree, moves the branch and
reads the head - and the plan never says so, because §3.6 is about steps and §3.4 is about
integrations and nothing in either is about both.

So an integration takes the target namespace's step lock as well, through `Journal.exclude_steps`,
and holds it for exactly as long as it holds the lease. A `gather` over a parent's own step and a
child's `integrate()` is legal and simply does not overlap, which is the same answer §3.6 gives for
two steps in one namespace and costs the same thing: latency.

**The order is lease first, then the step lock, always**, and `Leases.claim` is the one function
that takes them so the order cannot be got wrong at a call site. No cycle exists: `Journal.step`
takes no lease and has no way to reach one, so nothing anywhere acquires the two the other way
round. The one shape that could close a cycle is exotic and worth naming rather than waving at - a
role's `on_question` callback, which is workflow code and does run inside a step, calling
`integrate()` on a child of the very namespace whose step is running. That would be a workflow
asking one namespace to be inside a step and inside a landing at once, and it would hang rather
than corrupt anything.

**And this is what makes `Journal.advance` safe to be a plain assignment.** That method takes no
lock and could not: it is synchronous, and taking `_running` would deadlock against this module,
which is already holding it. The exclusion is here, and `advance`'s docstring points at this
paragraph.

## `Integration` is `_engine`'s type on the public surface, and it has to be

`ports.IntegrationOutcome` carries `head`, `conflict` and `conflicted` and **no verbs**. It cannot
carry them: `retry()` and `abort()` release a lease the port does not model, and a value type that
released one would be the lease living in `ports/` after all. So the thing `integrate()` returns is
defined here, with the port type's three meanings kept exactly and two methods added.

There is precedent and it is one field over: `Run.fingerprints` is `_engine.journal.Fingerprints`.
What a workflow author does with this type is read three properties and call one of two methods -
§3.3's own example is the whole of the surface - and none of that requires importing the name.

**Mutable, where the port's outcome is frozen, and the plan's snippet is why.** §3.3 writes
`await outcome.retry()` and looks at nothing it returns, so a `retry` that handed back a second
outcome would leave the workflow holding a stale first one; the loop a person clicking "try again"
twice produces has to be `while outcome.conflicted`. So `retry()` moves *this* outcome and returns
nothing, which also keeps one answer to `conflicted` where two could disagree.

## The framework emits; it never asks - and nothing here can run §3.3's example yet

§3.4: "On conflict the framework does not ask. It returns a `Conflict` outcome and holds the lease;
the workflow shows its own screen and decides." Nothing in this module shows a screen, reads an
answer, or knows that a terminal exists. `run.terminal` is stage 15, so §3.3's snippet cannot be
executed end to end by anything in this repository today: what is built is both halves it touches -
the outcome it branches on, and the two verbs it calls - and the middle line is 15's.

**The dependency that creates, stated here because stage 15 will otherwise meet it as a surprise.**
The lease is held while the workflow's conflict screen is up. A conflict screen queued behind two
agent questions would therefore stall the merge queue on something unrelated - which is §3.7 word
for word, and "that is the entire justification for one level of preemption". Preemption is not
cosmetic because of this module.

## The one build AGL runs, and the fact a reader should be able to check in one grep

§3.4: "**The framework runs exactly one build: the merge gate**, inside `integrate()`." That is not
a summary of a policy, it is the whole of AGL's relationship with building anything - and `_gated`
below holds the only call to `Verifier.verify` in this repository. The port's own docstring says
"there is exactly one call site in the framework, inside `integrate()`", and the two halves of that
sentence are meant to be checkable against each other rather than believed.

**Agent self-verification is not the other half of this, and is not related to it.** An
implementation agent doing test-driven work runs the suite in its own workspace through its own
tools, as often as its loop requires; the framework never sees, counts or schedules those runs,
exactly as it does not track the agent's file writes (§3.4). They are unbounded by design - "an
agent must never wait for permission to check its own work" - and the only thing that limits them is
the workflow's `concurrent` knob. The reason to name them here at all is that a reader who knows
agents run tests constantly will otherwise go looking for where those runs are counted, and the
answer is nowhere: they are shell calls inside a step, invisible to the framework on purpose, and
§3.11 refuses `Verify()` as a step worker in those words.

## Deliberately not here

No `Integrator.revert()`, and nothing below wants one. Undoing a landing that *succeeded* is
`Workspace.restore(before)`, which `_gated` calls and §3.11 records as one primitive at its fourth
moment; `ports/integration.py` spends a section sending a reader who looks for `revert` to exactly
that answer.

No deadline on the gate. `verify` takes a command and a working directory and no timeout, because
`build_timeout` is project configuration and reaches an implementation where implementations are
configured (§3.11) - so there is nothing here to pass one to, nothing here that waits on a clock,
and no `wait_for` simulating one. What an expired deadline *means* is settled on the port: whatever
the implementation reports arrives as an outcome, the gate reads `passed`, and the work is rejected
rather than retried.

No `held(target)` predicate and no way to ask one. §3.4 offers it as an alternative exit and the
previous deliverable declined it; `retry()` below asks by trying, which is
`adapters/git/_runner.py`'s own lesson about probing after a failure rather than before every call.

No journalling of an integration. Nothing under `steps/` records that a child went in - "no
fingerprint over a landing, no file for one" (`Journal.advance`) - which is exactly why §3.4 has a
resumed run finding a hold it did not take, and why the advance below lives only as long as the
process.
"""

import asyncio
from collections.abc import Callable

from agl.ports.errors import InternalError
from agl.ports.history import History
from agl.ports.home_layout import RunScope
from agl.ports.integration import Conflict, IntegrationOutcome, Integrator
from agl.ports.verifier import Verifier, VerifierOutcome
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import Journal
from agl.sdk._engine.services import Services
from agl.sdk._engine.steps import Steps

__all__ = ["Integration", "Leases", "integrate"]


class Leases:
    """§3.4's lease per integration target, and the target's step lock taken behind it.

    One instance per run, shared by every `Run` in the tree - a field on `Run` with a default,
    `Fingerprints`' and `Worktrees`' shape and their argument, which the module docstring makes for
    this one: a table built per `Run` is a table per namespace, and two siblings landing into one
    parent would each take their own lock in their own dict and both be in the parent's checkout at
    once.

    **A target is a parent `Run`, addressed by its `RunScope`.** The scope and not the object,
    because a lock is keyed rather than held: two `Run`s over one scope cannot arise - `Worktrees`
    hands back the object it built - and a `RunScope` is a frozen value that already names the whole
    ancestry, so equal scopes are the same target and nothing else is.

    A plain class and deliberately mutable, for `Fingerprints`' reason: it is state a run
    accumulates and exists to be taken from.

    **No `held()`, no enumeration, no count.** Nothing in AGL asks how many landings are in flight,
    and a predicate here would be answerable only in the instant between two `await`s. `claim` and
    `release_all` are the whole surface: one for an integration, one for run exit.
    """

    def __init__(self) -> None:
        # Locks are kept forever and leases are not. A run has one target per namespace that ever
        # takes a child's work, which is bounded by the workflow, so nothing prunes this; `_live` is
        # the one that would grow without bound, and a lease removes itself from it on release.
        self._locks: dict[RunScope, asyncio.Lock] = {}
        self._live: dict[RunScope, Lease] = {}

    async def claim(self, target: RunScope, journal: Journal) -> Lease:
        """Take the lease on `target`, then shut that namespace's step walk. Always that order.

        **One function takes both, which is what makes the ordering a fact rather than a
        convention.** The module docstring argues why a landing needs the step lock at all - it is a
        second writer of a checkout §3.6 promises is single-threaded - and why no cycle exists.
        Spelling the pair out at a call site would be an order to get right once per call site, and
        the second one would be written by somebody reading the first.

        The lease is taken first because it is the coarser of the two and the one a person waits
        inside: a run holding the target's step lock while queuing for the lease would stop the
        target's own steps on behalf of a landing that has not started.

        **The lease is released if the step lock cannot be taken**, which is not defensive tidiness:
        the acquisition suspends, so a cancellation arriving between the two would otherwise leave a
        lease held by nobody for the life of the process, and every later integration into that
        target would wait on it forever.
        """
        lock = self._locks.get(target)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[target] = lock
        await lock.acquire()
        try:
            admit = await journal.exclude_steps()
        except BaseException:
            lock.release()
            raise
        lease = Lease(target, lock, admit, self._returned)
        # No `await` between the acquisition and this line, so at most one live lease per target is
        # a fact about the loop rather than a claim: nothing can run in between to see the gap.
        self._live[target] = lease
        return lease

    def release_all(self) -> None:
        """Give back everything this run is still holding. `api.run`'s `finally`, and nothing else.

        §3.4: "the lease is released when the run exits". A workflow that ended with a conflict
        unresolved - returned without deciding, raised, or was stopped - leaves a live `Integration`
        with a lease in it, and the object it is reachable from is going away with the workflow.

        **This does not abort the adapter's hold**, and the module docstring argues it at length:
        the hold is durable so that a later invocation can find it, `land` now answers a
        pre-existing hold with a `Conflict` rather than exit 70, and releasing it here would
        discard a partial resolution somebody may be in the middle of making. The port's "call
        `retry` or `abort` on every path out" binds the run, and a run outlives a process.

        Synchronous, because releasing a lock is an assignment and a `finally` on the way out of a
        run is the last place to put a suspension - and idempotent through `Lease.release`, so a
        second call after a settled integration says nothing.
        """
        for lease in tuple(self._live.values()):
            lease.release()

    def _returned(self, lease: Lease) -> None:
        """One lease is done with. Called by `Lease.release` and by nothing else.

        Identity-checked rather than keyed alone, so that a stale release cannot evict a lease
        somebody else has since taken on the same target. That ordering is impossible today - the
        lock is still held when this runs - and the check costs one comparison to keep it impossible
        if the release order ever changes.
        """
        if self._live.get(lease.target) is lease:
            del self._live[lease.target]


class Lease:
    """One target's lease while an integration into it is live, and the step lock behind it.

    Handed out by `Leases.claim` and released by exactly two things: the `Integration` that settled,
    and `Leases.release_all` on the way out of a run. Not constructed anywhere else, which is why it
    is not exported - a lease built by hand would be a release for a lock nobody took.

    **Idempotent, and that is what lets run exit be unconditional.** `release_all` cannot ask an
    integration whether it settled, and an `asyncio.Lock` released twice raises `RuntimeError` - on
    the way out of a run, from a `finally`, over the exception the run is already ending with.
    """

    def __init__(
        self,
        target: RunScope,
        lease: asyncio.Lock,
        admit: Callable[[], None],
        returned: Callable[[Lease], None],
    ) -> None:
        # Which target this is the lease on. Public because `Leases` reads it back on release, and
        # because a lease that could not say what it is on would be a handle with no name in it.
        self.target = target
        self._lease = lease
        self._admit = admit
        self._returned = returned
        self._released = False

    def release(self) -> None:
        """Let the target's steps run again, then let the next landing in. Reverse of `claim`.

        The order is the acquisition's, backwards, which is the only order that never leaves a
        coroutine holding the inner lock while waiting for the outer one. Nothing suspends here, so
        the pair is one event and a cancellation cannot land between the halves.

        **The `_released` guard is unreachable through the public surface today, and the eviction
        below is why.** This method calls `_returned`, which takes the lease out of `Leases._live`,
        and `release_all` iterates exactly that table - so a lease sits in it for precisely as long
        as it is unreleased, and the only two callers there are (`Integration._settle` and
        `release_all`) cannot between them reach a released one. A reader who deletes the eviction
        deletes that property along with it, and the guard is what they would be relying on
        afterwards without knowing it. It is kept as belt-and-braces for the caller that would meet
        the failure: `release_all` runs from `api.run`'s `finally`, over whatever exception is
        already ending the run, and `asyncio.Lock.release` on a lock nobody holds raises
        `RuntimeError: Lock is not acquired` - which would surface there in place of the workflow's
        own failure, on the way out, where nothing is left to report the real one.
        """
        if self._released:
            return
        self._released = True
        self._admit()
        self._lease.release()
        self._returned(self)


class Integration:
    """What `run.integrate()` hands back: §3.3's outcome, and the two verbs the port cannot carry.

        outcome = await run.integrate()
        if outcome.conflicted:
            if await run.terminal.show(views.conflict, outcome=outcome, priority=10):
                await outcome.retry()
            else:
                await outcome.abort()

    §3.3's own example is the specification, and every member below exists because that example
    reads it. `head`, `conflict` and `conflicted` are `ports.IntegrationOutcome`'s three, with its
    meanings unchanged; `retry` and `abort` are the two the port cannot have, because they release a
    lease `ports/integration.py` argues at length is not the port's to model. `verdict` is the
    fourth thing the port has nowhere to put - what the merge gate's build answered - and the reason
    it is here rather than there is one this class already exists to make: a `Conflict` is a tuple
    of paths and one line, and a build's output is neither.

    **The state is one of three, and `conflicted` does not tell them apart.** Live and conflicted -
    the lease is held, the target is held, and the workflow owes a decision. Landed - the head is
    the target's new state, the parent's chain has been advanced, and everything is released.
    Aborted - the conflict stands as the record of why nothing landed, and everything is released.
    The last two are **settled**, which is what `retry` refuses and `abort` says nothing about.

    **A live conflict has two causes and one shape**, deliberately: the work would not combine, or
    it combined and then failed the build gate (§3.4). Both hold the lease, both are ended by the
    same two verbs, and §3.3's snippet is written once because of it. `verdict` is what tells them
    apart for a workflow that wants to show a different screen for each.

    An aborted outcome deliberately keeps its `Conflict` rather than clearing it: the port's
    invariant is that exactly one of `head` and `conflict` is set, "work either landed, and the
    target has a resulting state, or it did not, and there is something to put on a screen", and
    giving up on a landing does not make the collision not have happened.

    **Not thread- or task-safe within one outcome.** Two coroutines calling `retry()` on one of
    these is a workflow handing one decision to two deciders, and no lease can help - the lease
    serialises *integrations*, and these two are the same one.
    """

    def __init__(
        self,
        *,
        source: Workspace,
        target: Workspace,
        journal: Journal,
        integrator: Integrator,
        history: History,
        verifier: Verifier,
        build: str,
        before: str,
        lease: Lease,
    ) -> None:
        """Everything one integration needs to be carried to an end, and nothing about a `Run`.

        Workspaces and a `Journal` rather than the two `Steps` they came out of, because this object
        outlives the call that built it: a live conflict is decided by workflow code running much
        later, and re-opening a namespace at that point would be asking a lazy one-time open to
        happen twice. `Steps.landing` is where they are opened, once, together.

        Three ports and a string rather than the `Services` bundle they were taken out of, which is
        the same choice `integrate()` makes about `Run`: what an integration wants is a landing, an
        ancestry question, a build and the command to build with, and a bundle handed in whole would
        put a `Store`, an `AgentRunner` and a `Terminal` inside the object that decides a merge.
        `build` is a `str` because `Verifier.verify` takes the command on the call - §3.11 routes
        `build_timeout` the other way, into the implementation - and `services.py` argues at length
        that this call site is the only reason that string travels above the edge at all.
        """
        self._source = source
        self._target = target
        self._journal = journal
        self._integrator = integrator
        self._history = history
        self._verifier = verifier
        self._build = build
        # The target's head from before anything landed - **`_gated`'s revert target**. §3.11
        # refuses `Integrator.revert()` because undoing a landing that succeeded is
        # `Workspace.restore(head)`, one primitive at several moments, and this is the gate's: the
        # framework reads the target's head before it calls `land` and hands that same value back
        # when the build says no. Read here rather than in `_gated` because by then the landing has
        # moved it, and a value read afterwards names the state that has to be undone.
        self._before = before
        self._lease = lease
        self._head: str | None = None
        self._conflict: Conflict | None = None
        self._verdict: VerifierOutcome | None = None
        self._settled = False

    @property
    def head(self) -> str | None:
        """The target's state after the work landed, and `None` when it did not.

        `ports.IntegrationOutcome.head`'s meaning exactly, including its clause that "a landing that
        changed nothing is still a landing" and reports the target's unchanged head. Opaque: the
        framework records it, hands it back to the same implementation that produced it, and never
        parses, abbreviates or orders one.
        """
        return self._head

    @property
    def conflict(self) -> Conflict | None:
        """What stopped it, and `None` when nothing did. The workflow's screen reads this.

        Set means the work is not in the target. It stays set after `abort()`, which is the record
        of why the landing was given up rather than a claim that the hold is still there.
        """
        return self._conflict

    @property
    def conflicted(self) -> bool:
        """Did it fail to land? §3.3's worked example reads exactly this, and this is what it reads.

        A property for `ports.IntegrationOutcome.conflicted`'s reason: the two spellings ask the
        same question today and only one of them keeps working if the answer is ever encoded
        differently.
        """
        return self._conflict is not None

    @property
    def verdict(self) -> VerifierOutcome | None:
        """What the merge gate answered about this landing, and `None` when it never ran.

        **The member `ports.IntegrationOutcome` has no room for, which is why `Integration` is this
        module's own type.** A `Conflict` is two fields - a tuple of paths and one line - and a
        failed build is neither of those things: the reason the gate said no is a build's output,
        which is minutes of text, and a conflict screen showing a person one sentence about a red
        build is a screen they cannot act on. `summary` says what happened and this says what the
        command printed, and the workflow decides how much of it to put on the screen.

        **It is also how a workflow tells the two kinds of conflict apart.** Both come back
        `conflicted`, both hold the lease, and both are ended by `retry()` or `abort()` - which is
        deliberate, because it is what lets §3.3's snippet be written once. A workflow that wants to
        route them differently - a diff view for a textual collision, a build log for a red gate -
        reads this: `None` means the work would not combine, and set means it combined and then did
        not build. Nothing in the framework branches on it.

        Set on every gate that ran, including the passing one a landing goes through, because the
        output of a build that passed is still the build this landing was decided by. Cleared to
        `None` whenever a textual conflict is recorded, so a gate failure that is later retried into
        a collision cannot leave the previous attempt's verdict standing beside somebody else's
        `Conflict`.
        """
        return self._verdict

    async def retry(self) -> None:
        """Try this integration again, from wherever it now stands. §3.3's "retry" button.

        **What "again" means is the whole of this method's design.** A person at the conflict
        screen went and did something to the target - resolved the collision by hand, resolved it
        on the far side, or concluded the landing themselves - and this port has no opinion about
        what and no way to find out. So the first question is whether a landing is still pending,
        and the port deliberately gives nothing to ask it with: §1.3's charge was one tool's merge
        state machine written out as method names, `merge_in_progress` first among them, and §3.4's
        offer of a `held(target)` predicate was declined at 14.0.

        So it asks by trying. `Integrator.retry` raises `InternalError` when nothing is pending -
        "a person who finished the landing themselves is why `abort` is tolerant" - and that
        refusal is the only honest predicate there is. `adapters/git/_runner.py` made the same
        choice for the same reason: probe after a failure rather than before every call.

        **Both answers then continue down the path a first landing takes**, which is what makes
        §3.3's snippet correct on every conflict a workflow can be handed rather than on most of
        them. A collision resolved by hand concludes, is checked for containing the source, goes
        through the gate and advances the parent's chain, exactly as if it had never conflicted; a
        collision still unresolved is a `Conflict` again and the workflow decides again. The
        alternative reading - "retry means `Integrator.retry`, and if nothing is pending that is an
        error" - would put a button on the workflow's own screen that raises exit 70 at the person
        who fixed the problem.

        **"The same path" now includes the build gate, and that is the hole this closes.** A landing
        concluded by `Integrator.retry` is a human's own merge, made by hand in the target's
        checkout, and it is the landing least like the one the framework composed - so a `retry`
        that advanced the chain without building would let exactly the resolution a person invented
        under time pressure past the one check §3.4 has. It does not, because there is one path and
        `_concluded` is it: containment first, then the gate, then the advance, whichever call
        produced the outcome.

        **A red gate is retried through here too**, and lands in the second branch below rather than
        the first: the gate's revert leaves nothing pending, so `Integrator.retry` raises, the
        landing is offered again into a target that is back where it started, and the gate runs
        again on the tree that produces. That is what makes "fix the build and press retry" a thing
        a workflow can offer without knowing which kind of conflict it is looking at.

        **Nothing here gives the lease back when something raises, and that is deliberate rather
        than `integrate()`'s missing `except`.** That function can wrap its landing in
        `except BaseException: lease.release(); raise` because a `land` that raised left **no hold**
        behind - `GitIntegrator` re-raises exactly when the target is *not* held - so the lease is
        the only thing outstanding and giving it back is the whole of the cleanup. By the time this
        method runs the target may be held, and `ports/integration.py` binds the run to call `retry`
        or `abort` on every path out of that hold, "including the paths where something raised". So
        a gate that raises in here leaves the lease held and this outcome unsettled on purpose: the
        hold is still there, nothing else may land into that target while it is, and `abort()` is
        the verb the workflow still owes. A wrapper here would hand the lease to the next landing
        while somebody's half-finished merge sits in the target, which is the ordering `abort()`
        below refuses in as many words and the reason a failed `abort` keeps the lease too. The cost
        is real and is not hidden: a workflow that catches the exception and neither retries nor
        aborts has stopped every later landing into that parent for the life of the run.

        **Nothing pending is `InternalError`, and "pending" is this outcome being unsettled.** After
        it landed, and after `abort()`, there is no integration left to try again: the lease is
        gone, the parent's chain has already been advanced or deliberately not, and answering
        anything at all would mean taking a lease this object no longer holds. That is the same
        asymmetry `ports/integration.py` pins for its own two verbs and for its reason - the
        two-case outcome has no honest spelling for "there was nothing to do", where `abort` meets
        this state on every ordinary path and says nothing.

        Returns nothing. The class docstring argues it: §3.3 looks at no return value, so a second
        outcome handed back here would be a second answer to `conflicted`, free to disagree with the
        one the workflow is already holding.
        """
        if self._settled:
            raise InternalError(_nothing_to_retry(self._head))
        outcome: IntegrationOutcome | None = None
        try:
            outcome = await self._integrator.retry(self._target)
        except InternalError:
            # The port's own answer to "nothing is pending", used as the predicate it declines to
            # offer - see this method's docstring. Narrow by contract rather than by luck:
            # `Integrator.retry` raises this class for exactly one condition and reports everything
            # else as `UpstreamUnavailable` or `UpstreamUnexpected`.
            outcome = None
        if outcome is None:
            outcome = await self._integrator.land(self._source, self._target)
        await self._concluded(outcome, again=False)

    async def abort(self) -> None:
        """Give up on this landing: release the hold, release the lease, and settle.

        The tolerant one, and the tolerance is inherited rather than invented - `Integrator.abort`
        is "tolerant of there being nothing pending" for `WorkspaceProvider.remove`'s reason, "a
        release after a crash is the ordinary case rather than the exceptional one". So a second
        `abort()` says nothing, and an `abort()` on an outcome that landed does nothing at all: it
        is settled, and undoing a landing that succeeded is `Workspace.restore` at a different
        moment entirely (§3.11) - which `_gated` below is, and which this deliberately is not.

        **The lease is released after the hold and not before.** A lease given back first would let
        the next landing into a target that is still held, which the adapter answers with the
        pre-existing-hold `Conflict` - a second workflow sent to a screen about somebody else's
        collision, for no reason but an ordering here.

        **A failed `abort` keeps the lease**, which is the safe direction and is deliberate: the
        target is still held, so nothing else may land into it, and the run's own exit is what
        gives the lease back. The outcome stays unsettled, so a workflow that catches and retries
        the abort finds it still there to abort.
        """
        if self._settled:
            return
        await self._integrator.abort(self._target)
        self._settle()

    async def _concluded(self, outcome: IntegrationOutcome, *, again: bool) -> None:
        """One integrator answer, carried down the one path every landing takes.

        Shared by the first `land` and by every `retry`, which is what makes "both then continue
        down the same path a first landing takes" a fact about where this method is called from
        rather than a rule two call sites have to keep in step.

        `again` is the bound on one re-landing and nothing else; the containment check below says
        what it is for.
        """
        if outcome.conflicted:
            # §3.4: the framework does not ask. The lease stays held, the target stays held, and
            # this object goes back to the workflow with something to put on a screen.
            #
            # The verdict is cleared rather than left alone, because it is what a workflow reads to
            # tell a red gate from a collision: an outcome that failed the gate and was then
            # retried into a textual conflict would otherwise hand the screen the *previous*
            # attempt's build output beside a `Conflict` that has nothing to do with it.
            self._conflict = outcome.conflict
            self._head = None
            self._verdict = None
            return
        head = outcome.head
        if head is None:
            # Unreachable, and checked because mypy cannot see why: `IntegrationOutcome` refuses an
            # instance carrying neither a head nor a conflict in its own `__post_init__`, so this is
            # AGL's bug about AGL's type rather than anything an adapter did.
            raise InternalError(
                "an integration outcome reports neither a landing nor a conflict, which the type "
                "refuses to be constructed as - so this is not an adapter's answer, it is ours"
            )
        if not await self._history.contains(await self._source.head(), head):
            if again:
                raise InternalError(_still_not_in(self._source.branch, self._target.branch, head))
            # **The head belongs to somebody else's landing.** `land` answers a pre-existing hold
            # with a `Conflict` (§3.4, so that a resumed run can find a hold it did not take), so a
            # `retry` may conclude a landing this call never offered: the process died holding child
            # A's conflict, the resumed run's next `integrate()` is child B, the person picks retry,
            # and `Integrator.retry` concludes **A's** landing and hands back a head to a call site
            # that asked about B. Unchecked, that head becomes B's `last_good`, the gate runs on a
            # tree with none of B's work in it, and the workflow believes B landed.
            #
            # The target is free now, so land again and re-enter this path with the second answer -
            # which may itself be a conflict, and is then an ordinary live outcome. Bounded at one:
            # a second landing that still does not contain the source is not a third attempt.
            await self._concluded(
                await self._integrator.land(self._source, self._target), again=True
            )
            return

        # **The gate, and the early return is the whole of how a red one is kept off the advance.**
        # Not an `if verdict.passed:` wrapped around the four lines below, because that shape leaves
        # the advance reachable and relies on a condition staying correct; this leaves the method
        # before the advance exists. `_gated` reverts and records the conflict on its way out, so
        # everything after this line is a landing that both merged and built.
        if not await self._gated():
            return

        # **The destroy-work line.** §3.6: "`integrate()` advances the parent's `last_good`. A child
        # landing moves the parent's physical head, but `last_good` is chained from step entries and
        # `integrate()` is not a step - so the parent's next step to miss its fingerprint would
        # `restore()` to a commit *before* every landed child and delete all of it." Leaving this
        # call out does not raise, does not re-run anything and does not show up until the parent's
        # next miss, at which point `reset --hard` and `clean -fd` take away every child that has
        # landed in this run. It and a mispaired `commit=` are the only two paths in AGL that
        # destroy work rather than costing a re-run.
        #
        # It is safe as a plain synchronous call because of the lock this integration is holding:
        # `advance` takes no lock of its own (it could not - it is not async, and taking the
        # target's `_running` would deadlock against `Leases.claim`, which took it), and what keeps
        # a step in this namespace from being mid-walk right now is `exclude_steps`, held since the
        # lease was claimed and released only below.
        self._journal.advance(head)
        self._head = head
        self._conflict = None
        self._settle()

    async def _gated(self) -> bool:
        """Build the combined tree and say whether the landing may stand. §3.4's merge gate.

        **This line is the only call to `Verifier.verify` in AGL.** §3.4: "The framework runs
        exactly one build: the merge gate, inside `integrate()`", and `ports/verifier.py` says the
        same thing from the other end - "there is exactly one call site in the framework, inside
        `integrate()`". Neither sentence is worth anything unless it can be checked, so it is worth
        saying where a reader will check it: `grep -rn "[.]verify(" src/`, and the one line it finds
        that is neither prose nor an adapter implementing the port is the first statement below.
        Agent self-verification is not a second one and is not related to this one - an agent's own
        test runs are shell calls inside a step, unbounded by design and invisible to the framework
        (§3.4, §3.11), and the module docstring says why they are named here at all.

        **Inside the lease, and serial because the merge queue serialises it - and it must be.** The
        gate tests a combined state that exists only momentarily: this source, on top of exactly
        what the target held when the lease was taken, and nothing else. If another item landed
        mid-build the tree that was verified would not be the tree being decided about, and a
        failure could not be attributed to either item - so a red build would revert a landing that
        may well have been innocent, and a green one would clear a combination nobody built. The
        lease is what makes that impossible, and the target namespace's step lock behind it is
        load-bearing for the same reason one layer down: a build is a reader of a checkout a step in
        that namespace would otherwise be writing.

        **And this is the only thing in AGL that catches a semantic conflict.** §3.4: two items that
        each work alone, merge without textual collision, and are broken together. Nothing before
        this point can see one - `Integrator.land` compares texts, `History.contains` compares
        ancestry, and both of them said yes - which is exactly the case a merge train exists for.

        ## Failed, and why that is a `Conflict` rather than a raise or a third case

        A red gate is the framework's other answer to "does this work combine", so it is said in the
        framework's word for that. §3.4 calls the gate "the only thing that catches semantic
        conflicts" in as many words, and a conflict is what a semantic conflict is; raising instead
        would put "your tests are red on the combination" on the workflow's exception path, where a
        person's decision would have to be made inside an `except`, and `ports/verifier.py` already
        refuses that reading for the port ("a failing build is neither of those - it is the
        answer"). A third case on this object would cost §3.3's snippet a second branch to write and
        every workflow a second screen to route, for two states that want the identical two verbs.

        **§3.11's refusal of a third `IntegrationOutcome` case is about something else and does not
        bind here.** That row refuses a case for *asynchronous landing* - "opened, and waiting for a
        reviewer" - on the grounds that it would put a scheduling concept the framework has no
        vocabulary for into the port, and that a change request is a non-idempotent external write.
        A failed build is neither: it is decided, it is synchronous, and it has already happened.

        So `Conflict.paths` is `()`, which the port protects the spelling of: "`()` means 'I cannot
        tell you which'" and never "nothing collided". The framework genuinely cannot say which
        files are semantically incompatible - there is no such file, that is the nature of the thing
        - and inventing one would be worse than saying nothing. `summary` is the field the port
        guarantees says something, so it is written for the person at the workflow's screen rather
        than for a log, and the build's own output travels beside it on `verdict`, which is why this
        module has a type of its own to put it on.

        ## The revert, which is one primitive at its fourth moment

        `Workspace.restore(self._before)` on the **target**, where `before` is the head read inside
        the lease before anything landed. There is no `Integrator.revert()` and there must not be:
        this undoes a landing that *succeeded*, so there is no pending state to consult and nothing
        to learn about it, and every integrator would owe an implementation of it - including the
        ones for which the target's recorded past is not theirs to rewrite. §3.11 puts it as one
        primitive at four moments, and naming them is the point: **reset-before-rerun** (§3.6, a
        step whose entry is missing), **wipe-on-omitted-`commit=`** (§3.3, so a read-only step is
        genuinely read-only), **revert-on-gate-failure**, which is this line, and
        **abort-on-conflict**, which is `abort()` above and the one of the four that is a port call
        rather than this one.

        `restore` is `reset --hard` **and** `clean -fd` - one verb doing both halves, named so that
        nobody goes looking for the missing clean - so it also takes away whatever the build left in
        the target's tree: a coverage file, a compiled artifact, a cache directory the build tool
        made. That is wanted rather than tolerated, and it is this stage's acceptance criterion in
        one sentence: **a failing gate leaves the branch unmerged and the tree clean.** A target
        left holding a rejected build's leavings would hand them to the next landing, which
        `Integrator.land` is entitled to refuse for unrecorded work, and to the next person who
        looks.

        The lease is deliberately still held when this returns `False`. A red gate is a conflict the
        workflow decides about exactly as it decides about a textual one - `retry()` re-lands and
        re-gates, `abort()` gives up - and releasing here would put the next landing into a target
        somebody is still deliberating over.

        ## A machine that ran out of memory reads as a failed build, and that is the decision

        This is the branch where a reader will want to be clever, so: do not be. §3.9 is explicit
        that "if a build dies from machine exhaustion, the gate reads it as a failed build and
        reverts the merge - an OOM presents as a rejected item", and that "Gradle daemon death, exit
        137, and a genuine test failure are not cleanly distinguishable, so no attempt is made to be
        clever". There is no exit-status table here, no retry on a suspicious number, no
        second-chance build. `passed` is the one field the framework branches on and `status` is a
        clue for the person reading the failure screen afterwards, which is exactly the case §3.9
        says will happen and be misattributed. The cost is a re-run; the alternative is a framework
        guessing at the difference between a broken machine and broken code, on a signal that does
        not carry it.
        """
        verdict = await self._verifier.verify(self._build, self._target.path)
        self._verdict = verdict
        # **One `bool`, and `status` is never looked at.** This is the line to be unclever on: §3.9
        # says a build killed for machine exhaustion, a build tool's long-lived helper dying
        # underneath it and a genuine test failure "are not cleanly distinguishable, so no attempt
        # is made to be clever", and an exhausted machine therefore presents as a rejected item. The
        # last section of this method's docstring is about this branch and nothing else.
        if verdict.passed:
            return True
        await self._target.restore(self._before)
        self._conflict = Conflict(
            paths=(),
            summary=_gate_refused(self._build, verdict.status, self._target.branch, self._before),
        )
        # Not reachable with a head already set - `_concluded` records one only after this returns
        # `True`, and a retry that got here left `None` behind. Written anyway, beside the conflict,
        # because the port's invariant is that exactly one of the two is set and the two lines that
        # keep it should be readable together.
        self._head = None
        return False

    def _settle(self) -> None:
        """This integration is over, whichever way it ended. The one place the lease goes back.

        Both endings come through here - the landing that advanced the chain, and the abort that
        gave up - so "the lease is held until the outcome is settled" is one line rather than two
        that could drift. Marked before the release rather than after, so that a `release` which
        somehow raised still leaves a settled outcome rather than one `retry` would act on again.
        """
        self._settled = True
        self._lease.release()


async def integrate(
    *,
    source: Steps,
    target: Steps,
    address: RunScope,
    services: Services,
    leases: Leases,
) -> Integration:
    """Land `source`'s work into `target`, and hand back the outcome. `Run.integrate`'s whole body.

    Two `Steps` and not two `Run`s, because `sdk/workflow.py` imports `_engine` and `_engine` never
    imports it back - a module here that named `Run` would be an import cycle before it was anything
    else, which is the argument `worktrees.py` makes for taking a `build` callback. What an
    integration wants of a `Run` is its namespace's checkout and, for the target, the live `Journal`
    the advance lands on; `Steps.landing` hands over exactly that pair and nothing else.

    `address` is the **target's** `RunScope` and is the lease's key. It is passed rather than
    derived because a `Steps` does not publish its scope, and deriving one would be composing an
    address for an object already in hand.

    The order below is §3.3's, and every line of it is inside the lease:

      1. Open both namespaces. The child's for the source `Workspace`, the parent's for the target
         `Workspace` **and** the `Journal`. Before the lease, because opening a namespace is a lazy
         one-time provisioning under `Steps`' own lock and has nothing to do with landing - and
         because the target's `Journal` is what `Leases.claim` needs in order to shut its steps.
      2. Read the target's head, **after** the lease and **before** the landing. `_gated` needs it
         as the revert target when the build says no, and it is read after the lease so that
         nothing can have moved it between the reading and the landing it describes.
      3. Land, and carry the answer down `Integration._concluded`, which gates it and advances the
         parent's chain or gives the workflow something to decide about.

    **The lease is released if anything raises**, and only the lease: a `land` that raised did not
    leave a hold behind - `GitIntegrator` re-raises exactly when the target is *not* held - and the
    holds this path does produce come back as conflicted outcomes rather than as exceptions.

    **`Integration.retry` deliberately has no wrapper like this one, and the difference is the
    sentence above read the other way round.** A retry runs against a target that may already be
    **held**, and `ports/integration.py` binds the run to call `retry` or `abort` on every path out
    of that hold, "including the paths where something raised" - so an exception in there leaves a
    verb the workflow still owes, and giving the lease back under it would let the next landing into
    a target somebody's half-finished merge is sitting in. Here there is no hold to owe a verb to,
    which is what makes releasing the lease the whole of the cleanup rather than half of it. The two
    are not one shape written twice and one of them forgotten; a reader about to make them symmetric
    should read `Integration.retry`'s docstring first, where the cost of this one is also written
    down.
    """
    # The source's journal is deliberately dropped. A landing writes nothing to the child's chain:
    # the child's `last_good` is built from its own step entries and integrating is not one of them,
    # which is why §3.6 puts the advance on the parent's side and only there.
    _, child = await source.landing()
    journal, parent = await target.landing()
    lease = await leases.claim(address, journal)
    try:
        integration = Integration(
            source=child,
            target=parent,
            journal=journal,
            integrator=services.integrator,
            history=services.history,
            verifier=services.verifier,
            # §3.4's one build command, taken off the bundle at the one call site that has it.
            # `Services.build` exists for this line and for no other: `Verifier.verify` puts the
            # command on the call, and until 14.0 nothing above the edge held a `Project`'s.
            build=services.build,
            before=await parent.head(),
            lease=lease,
        )
        await integration._concluded(
            await services.integrator.land(child, parent), again=False
        )
    except BaseException:
        lease.release()
        raise
    return integration


def _nothing_to_retry(head: str | None) -> str:
    """Why a settled outcome has nothing to try again, in the two shapes a workflow reaches it."""
    ended = (
        f"it landed, and the target is at {head!r}"
        if head is not None
        else "it was aborted, and the hold was released"
    )
    return (
        f"this integration is over - {ended} - so there is nothing left to try again. `retry` is "
        f"for an outcome that is still conflicted and still holding its lease; once one has "
        f"settled, the lease is back, the parent's chain has been decided, and a retry would be "
        f"acting on a landing nothing is holding. A second `abort` is the tolerant one and says "
        f"nothing; this is the asymmetry `ports/integration.py` pins for its own two verbs"
    )


def _gate_refused(command: str, status: int, target: str, before: str) -> str:
    """The line on the conflict screen when a landing merged cleanly and then would not build.

    `Conflict.summary` is "the only part of a `Conflict` guaranteed to say anything", and for a red
    gate it is carrying more than usual: `paths` is empty by necessity, so this sentence is the
    whole of the structured answer. Written for the person deciding between `retry` and `abort`, so
    it says the three things that decision turns on - what happened, which command said so and how
    it ended, and what state the target is in now - and points at the build's own output rather than
    trying to quote it.
    """
    return (
        f"the build gate refused this landing. {target!r} took the work with no textual collision, "
        f"and then {command!r} ran in that tree and ended with status {status}, so the landing was "
        f"undone: {target!r} is back at {before!r} and its working tree holds nothing the build "
        f"left behind. There is no list of colliding files because there is nothing to list - what "
        f"failed is the combination rather than any one file, which is the semantic conflict this "
        f"gate exists to catch and the reason two pieces of work that each build alone can still "
        f"be refused together. The build's own output is on the outcome, beside this conflict"
    )


def _still_not_in(source: str, target: str, head: str) -> str:
    """A second landing whose head still does not contain the source. Not a third attempt."""
    return (
        f"{target!r} is at {head!r} after landing {source!r} into it a second time, and that state "
        f"still does not contain {source!r}. The first answer was somebody else's landing being "
        f"concluded (§3.4: a resumed run finds a hold it did not take), which this re-landing is "
        f"the answer to - so a second one that still leaves the work out is not a case to try "
        f"again through, it is AGL and the integrator disagreeing about what landed. Nothing has "
        f"been advanced: the parent's chain still names the state it did before this integration"
    )
