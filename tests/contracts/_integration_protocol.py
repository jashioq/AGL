"""The hold a conflict leaves, and the two verbs that end it: `retry`, `abort`, and their asymmetry.

Split out of `integration.py` along a line the port draws itself. `land` is the question - "is this
work in the target now, or not" - and this is the protocol that follows the second answer: **the
target is left held mid-landing, and the run must call `retry` or `abort` on every path out of that
hold, including the paths where something raised.** The port calls that a contract rather than a
convention, and the three tests that hold it apart from a convention are here.

## What "held" is made of is not this suite's business, and that is the whole design

§1.3's charge was one tool's merge state machine written out as method names - `merge_in_progress`,
`unmerged_paths`, `abort_merge`, `commit_merge` - so this port has no in-progress predicate, no way
to ask which files are half-resolved, no staging step and no ref format. A suite that reached for
any of that would be reintroducing exactly what the split removed.

So nothing below looks at a held target. **The hold is observed only through the two verbs**, and
the one observation that says it exists is `retry` not raising: a landing is pending, so there is
something to try again. The one that says it is gone is `retry` raising `InternalError` afterwards.
That pair is the whole vocabulary this suite has for a state it is forbidden to inspect, and it is
enough, because it is the same vocabulary the framework has.

## The asymmetry is deliberate and is pinned as an asymmetry

Called with nothing pending, `retry` raises `InternalError` and `abort` succeeds and says nothing.
That is not an inconsistency to be smoothed over: the framework calls `retry` only in answer to a
conflicted outcome, so nothing pending means AGL lost track of a hold it took, and the two-case
outcome has no honest spelling for "there was nothing to do". `abort` meets the same state on every
ordinary path - a release after a crash, a person who finished the held landing by hand - and a
teardown that raises on a half-finished setup is a teardown people learn to wrap in a bare
`except`. One test asserts both verbs against one target in one state, so the contrast is written
down rather than inferred from two tests that happen to sit near each other.

`IntegratorContract` in `integration.py` inherits this class. Implementers subclass that one, never
this one, and the `integrator`, `provider` and `base` fixtures these tests take are declared there.
"""

import pytest

from agl.ports.errors import InternalError
from agl.ports.integration import Integrator
from agl.ports.workspace import WorkspaceProvider

from ._integration_targets import (
    CHILD_WORK,
    hold_a_target,
    open_a_target_and_two_children,
)
from ._workspace_files import ALPHA, TRACKED, read, record, write


class IntegrationProtocolContract:
    """`retry` and `abort`: the loop, the release, and what each of them does with nothing pending.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_abort_releases_the_hold_and_leaves_the_target_exactly_as_it_was_before_land(
        self, integrator: Integrator, provider: WorkspaceProvider, base: str
    ) -> None:
        """The release, and the two halves of it that can be told apart from outside.

        The first half is the state: `abort` leaves the target exactly as it was before `land`,
        which here is the state the *first* child's landing left - not the state the run started
        in. An implementation that put the target back too far would be undoing a landing that
        succeeded, which is `Workspace.restore`'s job at a different moment and never this one's.

        The second half is the hold itself, and it is the sharper assertion. A target whose files
        look right and whose landing is still pending is a target the next `retry` acts on and the
        next `abort` has to unwind again - and, through this port, an implementation that tidied
        the tree and forgot the record is indistinguishable from one that did the job, right up
        until something asks. So something asks: with the hold released there is nothing pending,
        and `retry` says so by raising. That is the only question this port answers about a hold,
        and it is asked here because this is the test that claims the hold is gone.
        """
        held = await hold_a_target(integrator, provider, base)

        await integrator.abort(held.target)

        assert await held.target.head() == held.head, (
            f"after an abort the target is at a state other than {held.head!r}, where it stood "
            f"before the landing that conflicted. `abort` gives up on the pending landing and "
            f"puts the target back - a target left somewhere else is a run that has silently "
            f"moved a deliverable branch nobody asked it to move"
        )
        assert read(held.target, TRACKED) == held.contents, (
            "the file the two children collided over does not hold what it held before the "
            "conflicted landing. Putting the head back is not the whole of it: whatever the "
            "attempt left in the working tree is what the next step, and the next person to look, "
            "would read as the target's own state"
        )
        with pytest.raises(InternalError):
            await integrator.retry(held.target)

    async def test_abort_with_nothing_pending_succeeds_and_leaves_a_finished_landing_alone(
        self, integrator: Integrator, provider: WorkspaceProvider, base: str
    ) -> None:
        """Tolerance, and the case that makes tolerance more than politeness.

        A release after a crash is the ordinary case rather than the exceptional one - the run must
        call this on every path out of a hold, including the paths where something raised, and a
        run that died holding a target is exactly the run that cannot report what state it was in.
        So the first call below is against a target nothing has ever landed into.

        The rest is the case the port names by hand: **a person who finished the held landing
        themselves lands in this same state, and the right thing is to leave their work alone.**
        This suite cannot make a person resolve a conflict, but it can produce the state they leave
        behind - a target with work landed in it and nothing pending - and that is what a completed
        landing is. An implementation reading "abort" as "undo the last landing" passes every test
        that only ever aborts a real hold, and quietly destroys landed work here. It is `abort`'s
        one genuine hazard, which is why the assertions are about what is still there rather than
        about what came back: this method returns nothing, and *returning at all* is the whole of
        the tolerance clause.
        """
        target, child, _ = await open_a_target_and_two_children(provider, base)
        fresh = await target.head()

        await integrator.abort(target)

        assert await target.head() == fresh, "aborting a target holding nothing moved it anyway"

        write(child, ALPHA, CHILD_WORK)
        await record(child, "the child's own work")
        outcome = await integrator.land(child, target)
        assert outcome.conflicted is False, (
            f"landing one child's work into an untouched target reported a conflict: "
            f"{outcome.conflict}. This test needs a landing that completed"
        )
        settled = await target.head()

        await integrator.abort(target)
        await integrator.abort(target)

        assert await target.head() == settled, (
            f"a target that had landed work and holds nothing pending is at {await target.head()!r}"
            f" rather than {settled!r} after an abort. This is the state a person who finished the "
            f"landing by hand leaves, and `abort` undid their work: it gives up on a landing that "
            f"never completed, and undoing one that did is `Workspace.restore` at a different "
            f"moment entirely"
        )
        assert read(target, ALPHA) == CHILD_WORK, (
            "the landed work is gone from the target's tree after an abort that had nothing to "
            "abort. Called twice over, which is what a `clear` after a crash does"
        )

    async def test_retry_with_nothing_pending_is_an_internal_error_where_abort_is_not(
        self, integrator: Integrator, provider: WorkspaceProvider, base: str
    ) -> None:
        """One target, one state, two verbs, two answers - and the difference is the point.

        `retry` is called by the framework only in answer to a conflicted outcome, so reaching it
        with nothing pending means AGL lost track of a hold it took. `InternalError` is what that
        is: our invariant, our bug, exit 70. The alternative would be answering with the two-case
        outcome, which has no honest spelling for "there was nothing to do" - a head would claim a
        landing that never happened, and a `Conflict` would send a workflow to a screen about a
        collision nobody had.

        `abort` meets the same state constantly and says nothing, and the two facts are asserted
        against one target here so that the asymmetry is a documented pairing rather than something
        a reader has to notice across two files. An implementation tempted to make them consistent
        with each other is being asked to pick which of the two clauses to break.
        """
        target, _, _ = await open_a_target_and_two_children(provider, base)
        fresh = await target.head()

        with pytest.raises(InternalError):
            await integrator.retry(target)

        await integrator.abort(target)

        assert await target.head() == fresh, (
            "a target that has never been landed into moved under a retry that should have "
            "refused and an abort that should have done nothing"
        )

    async def test_retry_after_a_conflict_answers_the_same_two_cases_and_the_target_stays_held(
        self, integrator: Integrator, provider: WorkspaceProvider, base: str
    ) -> None:
        """The protocol loops, and `abort` is what ends it.

        `retry` is called after something *outside this port* changed the situation - the person at
        the workflow's conflict screen edited the held target, or resolved the collision on the far
        side. Nothing outside this port has changed anything here, so the answer is the one the
        port calls ordinary: a `Conflict` again, the target still held, and the workflow deciding
        again. That is the honest thing to assert, and the reason the *other* branch is a gap
        `integration.py` lists rather than a test: a `retry` that lands needs the collision
        resolved in the held target, and resolving one means knowing what a hold is made of.

        Twice, because a loop that runs once is a sequence. Then `abort`, because a run owes the
        target one of the two verbs on every path out - and afterwards there is nothing pending,
        which is what ending it means.

        Nothing here re-supplies the source, and nothing can: `retry` takes only the target,
        because the pending landing already knows what it was landing and a re-supplied source
        would be a second chance to supply a different one. That is pinned by the signature and by
        `mypy --strict`, not by an assertion.
        """
        held = await hold_a_target(integrator, provider, base)

        again = await integrator.retry(held.target)

        assert again.conflicted is True, (
            f"retrying a landing whose collision nobody resolved answered with head "
            f"{again.head!r}. Nothing outside this port touched the held target between the "
            f"conflict and this call, so an implementation that lands here has either found a "
            f"resolution nobody made or forgotten what it was holding"
        )
        assert again.head is None, "the two-case outcome, and this is the case with no head in it"
        assert again.conflict is not None and again.conflict.summary, (
            "a conflicted retry came back with nothing for the workflow's screen. `summary` is "
            "the only part of a `Conflict` guaranteed to say anything, and the decision being "
            "asked of the person reading it is which of `retry` and `abort` to call next"
        )

        once_more = await integrator.retry(held.target)
        assert once_more.conflicted is True, (
            "a second retry of an unresolved landing did not answer as the first one did, so the "
            "target stopped being held somewhere in the loop the port says this protocol is"
        )

        await integrator.abort(held.target)

        assert await held.target.head() == held.head, "the release puts it back, loop or no loop"
        assert read(held.target, TRACKED) == held.contents, (
            "the work that had already landed is not what the target holds after the loop ended"
        )
        with pytest.raises(InternalError):
            await integrator.retry(held.target)
