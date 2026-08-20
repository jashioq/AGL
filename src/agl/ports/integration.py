"""`Integrator`, `IntegrationOutcome` and `Conflict` - land this workspace into the target, or tell
me why not.

Two isolated places and one question: put what the first holds into the second, or say what stopped
it. `workspace.py` makes those places and `history.py` reads what they record; this is the one port
in AGL that moves work from one line of work into another, and `run.integrate()` (§3.3) is the only
thing that asks.

## The verb is `land`, not `merge`

A merge is one way to land. Naming the method after it would fix the mechanism in the vocabulary and
leave every other mechanism describing itself in a word that does not fit: an implementation that
lands by opening a change request against the target, and never combining anything locally at all,
would spend its docstring explaining that its `merge` does not merge. The consumer's question is "is
this work in the target now, or not", so that is what the method is named after.

## The state machine of a landing stays behind the adapter

§1.3's charge against the previous implementation was a single 27-member port speaking one tool's
vocabulary, and the merge half of it was that tool's state machine written out as method names:
`merge_in_progress`, `unmerged_paths`, `abort_merge`, `commit_merge`. Nothing there was AGL asking a
question - it was AGL driving one program's operation one call at a time - and the consequence the
plan names is exactly the second implementation below: an integrator that opens a change request has
no in-progress merge to report, no half-resolved paths to list, and no separate "now commit it" step
to be told to take, so it could not implement that port without lying four times.

So there is no `in_progress` predicate here, no way to ask which files are half-resolved, no
staging step, no ref format, and no pair of verbs for finishing versus abandoning one program's
operation. There are three methods, and each of them is a whole thing a consumer wants done.

## There is no `revert`, and a reader looking for one should find this

§3.4 has the framework undo a landing whose build gate then failed. That is not a fourth method
here, for two reasons. It undoes a landing that *succeeded*, so there is no pending state to consult
and nothing left to learn about it - the target simply has to be put back where it was. And "put the
target back where it was" is `Workspace.restore(head)`, which already exists: §3.3 and §3.6 use that
same primitive before re-running a step whose entry is missing, and on the way out of a step that
passed no `commit=`. This is the third moment, not a third operation. The framework reads the
target's head before it calls `land` and hands that same value back on failure.

A `revert` here would be a second spelling of one operation, and every integrator would owe an
implementation of it - including the ones for which the target's recorded past is not theirs to
rewrite. `abort` below is the different thing and is not this: it releases a landing that never
completed, and it is the only one of the two that needs the implementation's own knowledge.

The check itself is run by the framework after landing and before keeping. This port does not run
it, is not handed it, and does not know it exists.

## The lease is the framework's, deliberately

§3.4 gives the framework a lease per integration target - landings into one target are serialised,
and the lease is released when the run exits. It is not modelled here, and the boundary is worth
arguing rather than asserting, because "hold" appears on both sides of it.

The lease is a rule about AGL's own concurrency: how many of its own runs may be asking at once, and
what happens to the answer when one of them dies. That is not a fact about landing work, and putting
`claim`/`release` on this port would make every implementation responsible for AGL's scheduling
policy - including implementations whose far side already serialises, which would then maintain a
lease nothing consults. It would also put enforcement of a framework rule inside whichever adapter
happened to be configured, where the framework could no longer see it. `sdk/_engine/integration.py`
owns it.

What *is* here is a different hold and only looks like the same word: after a conflicted `land` the
target is left mid-landing, and that is a state of the target which only the implementation can
create and only the implementation can undo. Hence `abort`, and hence its being a method rather than
something the framework does by itself.

## The test every member below was written against

Could a second, structurally different implementation satisfy this honestly? Not "could it be made
to compile" - could it implement this without ignoring a parameter and without raising on something
the shape here implies it supports. The one held against every member is the integrator §1.3 says
the previous port made impossible: one that lands by opening a change request against the target and
never touches a local checkout.

It reads `Workspace.branch` on both sides and never `Workspace.path`. That is a use of the
parameter and not an evasion of it - a workspace is passed because it names a line of work and can
report where that line currently is, and what an implementation needs from those two facts is its
own business. What no implementation may be forced to do is invent a value it does not have, which
is why `Conflict.paths` may be empty and why nothing here asks for a diff, a message, an author or
an ordering.

The one cost that implementation has to accept is stated plainly rather than hidden: **there is no
third outcome for "opened, and waiting for someone to approve it".** §3.11 splits the work so that
the workflow decides and the framework carries out, so an integrator whose far side wants a reviewer
waits for that reviewer inside `land` rather than reporting an open request as a conflict. `land` is
async and the framework runs other work while it waits, so the cost is latency and not a stall - but
the shape here says landed or not, and an implementation that can say neither yet has to keep
waiting until it can.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agl.ports.errors import InternalError
from agl.ports.workspace import Workspace

__all__ = ["Conflict", "IntegrationOutcome", "Integrator"]


@dataclass(frozen=True, slots=True)
class Conflict:
    """Why the work would not combine: which files collided, and one line a person can read."""

    paths: tuple[str, ...]
    """The colliding files, repository-relative and separated by forward slashes.

    The same convention as `history.FileChange.path`, and `str` for the reasons that type gives:
    these are names inside a repository rather than locations on this machine, and one of the two
    states being combined may never have been checked out here at all. That docstring makes the
    argument; this one does not repeat it.

    **Empty is a claim, not an absence.** An integrator that cannot enumerate what collided reports
    `()` and says why in `summary`. A far side that answers only "these cannot be combined cleanly"
    is a real implementation, and this shape has to let it be honest instead of inventing a list. So
    `()` means "I cannot tell you which" and never "nothing collided" - nothing collided is not a
    `Conflict` at all, it is an `IntegrationOutcome` carrying a head. Anything reading this tuple to
    find out *whether* there was a conflict is reading the wrong field; `conflicted` is that
    question.

    No default, for `WorkspaceProvider.open`'s reason: `()` is something an implementation states,
    not something it falls into by leaving an argument off.
    """

    summary: str
    """One line for a person, and the only part of a `Conflict` guaranteed to say anything.

    The workflow puts it on its own screen - §3.4 has the framework hand back an outcome rather than
    ask - so it is written for that screen and not for a log: what would not combine, in whatever
    detail this implementation has. Refused empty, because a `Conflict` with no paths and no summary
    tells the person at the screen nothing whatever, and the decision being asked of them is which
    of `retry` and `abort` to call.
    """

    def __post_init__(self) -> None:
        # `InternalError` and not `InputError`, for `FileChange`'s reason: nobody types one of
        # these. An adapter assembled it out of what it was told, so a malformed one is our bug.
        if not self.summary:
            raise InternalError(
                "a conflict with no summary explains nothing, and an implementation that cannot "
                "list the colliding paths has this line and nothing else to say them in"
            )
        for index, path in enumerate(self.paths):
            if not path:
                raise InternalError(
                    f"the conflicting path at position {index} is empty, and names no file; an "
                    f"implementation with no paths to report passes an empty tuple instead"
                )


@dataclass(frozen=True, slots=True)
class IntegrationOutcome:
    """Did it land: either the target's resulting state, or what stopped it.

    Exactly one of the two, and checked. The alternative is a type with four states of which two are
    nonsense - neither field set says nothing happened at all, both set says it landed and also did
    not - and every consumer would then carry branches for cases no implementation can produce.
    """

    head: str | None = None
    """The target's state after the work landed, and `None` when it did not.

    Opaque, exactly as it is in `workspace.py`: the framework records it, hands it back to the same
    implementation that produced it, and never parses, abbreviates or orders one.

    **A landing that changed nothing is still a landing** and reports the target's unchanged head.
    A child whose work is already contained in the target is the ordinary way to reach that - a
    replayed run, a step that produced nothing - and it is not a failure, not a conflict, and not a
    case for a third field. `head` names where the target is now, which is the only thing the caller
    was going to do with it.
    """

    conflict: Conflict | None = None
    """What stopped it, and `None` when nothing did.

    Set means the target is held mid-landing and the run owes it a `retry` or an `abort`; see
    `Integrator`, where that protocol is the contract rather than a convention.
    """

    def __post_init__(self) -> None:
        # `InternalError` for all three: the framework built this out of what an adapter reported.
        if (self.head is None) == (self.conflict is None):
            both = "both a head and a conflict" if self.head is not None else "neither"
            raise InternalError(
                f"an integration outcome carries {both}, and it has to carry exactly one: work "
                f"either landed, and the target has a resulting state, or it did not, and there is "
                f"something to put on a screen"
            )
        if self.head is not None and not self.head:
            raise InternalError(
                "an integration outcome's head is empty, and an empty string names no state; a "
                "landing that changed nothing reports the target's unchanged head"
            )

    @property
    def conflicted(self) -> bool:
        """Did it fail to land? §3.3's worked example reads exactly this, off what `integrate()`
        returned, and this is what it reads.

        A property rather than leaving workflow authors to write `outcome.head is None`, so that the
        encoding above stays this module's business. The two spellings ask the same question today,
        and only one of them keeps working if the answer ever comes to be encoded differently.
        """
        return self.conflict is not None


class Integrator(ABC):
    """Land work from one workspace into another. Three methods, and a protocol they share.

    ## The conflict protocol, which is a contract and not a convention

    **On conflict the framework does not ask** (§3.4). `land` returns an outcome whose `conflicted`
    is true, and **the target is left held mid-landing** - not put back, not finished, not resolved
    by guessing. The workflow shows its own screen and decides, which is the split §3.11 draws:
    detecting the conflict and holding the target is the framework's, deciding what to do about it
    is the workflow's.

    **The run must call `retry` or `abort` on every path out of that hold**, including the paths
    where something raised. `abort` is the release, and having it be a call is what makes the hold
    explicit and releasable rather than a state only the adapter knows it is in. A port whose
    conflict left no way to say "stop, put it back" would be a port where a failed run's target
    stays half-combined until a person finds it.

    ## What these raise

    Everything is from `errors.py` and nothing else, so a caller never learns what the thing
    underneath happened to throw: `UpstreamUnavailable` when the repository or the far side cannot
    be reached at all, `UpstreamUnexpected` when it answered something the adapter cannot act on.

    **A conflict is not among them.** It is the ordinary second answer to this port's question, so
    it is a return value: raising would make the workflow's own decision path an exception handler,
    and would put "could not be combined" in the same bucket as "the far side is down".

    All three are async, for `History`'s reason: an implementation may have to leave the process or
    cross a network to do this, and a synchronous signature would block the loop that is running
    several agents at once. Here it is load-bearing rather than merely prudent - `land` may be
    waiting on a person.
    """

    @abstractmethod
    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        """Put what `source` holds into `target`, and say whether it went in.

        Both sides are `Workspace` and not names, because a workspace is what the framework has: it
        carries the line of work's name, it can report where that line currently is, and for a
        local implementation it is also the checkout the work happens in. An implementation uses the
        parts of that it needs - a change-request integrator reads `branch` on both sides and never
        `path` - and none of them is asked to invent the parts it does not.

        Returns a head when the work is in, including when it was already in and nothing moved. On
        conflict it returns a `Conflict` and leaves `target` held; see this class's docstring for
        what the run then owes it.
        """

    @abstractmethod
    async def retry(self, target: Workspace) -> IntegrationOutcome:
        """Try again to finish the landing `target` holds, and say whether it went in this time.

        Called after something *outside this port* changed the situation - the person at the
        workflow's conflict screen edited the held target, or resolved the collision on the far
        side. This port has no opinion about what they did and no way to find out; it looks again.

        Takes only the target, because the pending landing already knows what it was landing. The
        implementation created that state and is the only thing that can describe it, and a
        re-supplied source would be a second chance to supply a different one.

        The answer is the same two-case outcome, and a `Conflict` again is the ordinary result of a
        partial resolution: the target stays held, and the workflow decides again. The protocol
        loops, and `abort` is what ends it.

        **A landing has to be pending.** Called with nothing held, this raises `InternalError`: the
        framework calls it only in answer to a conflicted outcome, so nothing pending means AGL lost
        track of a hold it took, and the two-case outcome has no honest spelling for "there was
        nothing to do". A person who finished the landing themselves is why `abort` is tolerant.
        """

    @abstractmethod
    async def abort(self, target: Workspace) -> None:
        """Give up on the pending landing, leaving `target` exactly as it was before `land`.

        The release. It is what the run calls on the way out when the workflow decides this work is
        not going in, and on the way out of a run that failed for reasons of its own while a target
        was held.

        **Tolerant of there being nothing pending.** Doing this to a target that holds nothing
        succeeds and says nothing, for `WorkspaceProvider.remove`'s reason and in the same words: a
        release after a crash is the ordinary case rather than the exceptional one, and a teardown
        that raises on a half-finished setup is a teardown people learn to wrap in a bare `except`.
        A person who finished the held landing by hand lands in this case, and the right thing is to
        leave their work alone.

        Returns nothing, because there is nothing to report: the target is where it was, which the
        caller already knew, and any newer question about it is `Workspace.head`'s to answer.

        **Not a revert.** This undoes a landing that never completed. Undoing one that did is
        `Workspace.restore` - see the module docstring, which is where a reader looking for `revert`
        is sent.
        """
