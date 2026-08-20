"""`IntegratorContract` - what every `Integrator` owes, asserted before an implementation exists.

Subclass it once per implementation, override the three fixtures, and add nothing:

    class TestTheIntegratorIWrote(IntegratorContract):
        @pytest.fixture
        def integrator(self, repository: Path) -> Integrator:
            return TheIntegratorIWrote(repository, ...)

        @pytest.fixture
        def provider(self, repository: Path) -> WorkspaceProvider:
            return TheProviderIWrote(repository, ...)   # over that same repository

        @pytest.fixture
        def base(self, repository: Path) -> str:
            return "..."

The real adapter and the fake both run this class, which is the whole mechanism keeping a fake from
drifting into fiction (§1.9). It is written here, at stage 3, before either exists, because a
subagent that writes its own tests writes tests that pass - and stage 5 ends with "the contract
suite passes", a sentence worth something only when the suite had no stake in the implementation.

`IntegratorContract` is one class assembled from two modules, and only this name is public. Its own
tests are `land` - the two shapes of a landing that worked, the conflict that is an answer rather
than an exception, and the cross-port property §3.4 needs when a gate says no.
`_integration_protocol` is the hold a conflict leaves and the two verbs that end it, which the port
itself sets apart as "a protocol they share". `_integration_targets` under both builds the merge
train every test is made of, out of `_workspace_files`' names.

## Why this suite takes a `WorkspaceProvider`

`land` takes two `Workspace`es and nothing else, and there is no member on this port that makes
one. So a suite for it has to get its isolated places from somewhere, and this is the same
dependency `HistoryContract` declares out loud for the same reason: across these ports there is
exactly one way to record a state, `Workspace.commit_all`, and work that was never recorded is work
no integrator can be asked to land. The alternative is an implementation-supplied fixture handing
over a prepared pair, which is a knob whose whole job would be to be shaped by whoever also writes
the implementation.

The cost is real and is listed in the gaps: an `Integrator` whose repository is provisioned by a
broken `WorkspaceProvider` fails this suite for the other port's reason. Every test asserts what it
built before asking about it, so a failure says which side of that line it came from.

## Written against the port, never against one tool

§1.3's charge was a single port speaking git's merge state machine, and §3.4's answer is that the
state machine stays inside `adapters/git/integrator.py`. **So there is no porcelain anywhere in
this suite.** Nothing here runs a command, reads a status line, parses a marker out of a file,
knows what a half-resolved path looks like, or asks whether something is in progress. A commit id
is an opaque string that came out of `head()`; a conflict is a value with a sentence in it; a hold
is a thing that can be retried or released and has no other observable properties at all.

The implementation held against every test is the one the port names: an integrator that lands by
opening a change request against the target and never touches a local checkout. It reads `branch`
on both sides and never `path`, and nothing below asks it for anything else.

## Where the revert-on-gate-failure test lives, and why there is no `Verifier` fixture

§3.4 has the framework undo a landing whose build gate then failed, and that is the property this
suite would be most missed for. It is **not** a fourth method on this port: §3.11 records that
`Integrator.revert()` was deliberately not built, because undoing a landing that *succeeded* is
`Workspace.restore(head)` - the same primitive §3.3 and §3.6 already use before re-running a step
and on the way out of a read-only one. This is the third moment, not a third operation.

So the test asserts the outcome and not which primitive got there: land, put the target back at the
head it was read at, and assert the target is indistinguishable from before. It sits in this class
because both ports it touches are ones this suite already holds - the integrator under test and the
workspaces it lands between - and because the reader who goes looking for `revert` on this port
should find it here, in the same place the port's own docstring sends them.

**A `Verifier` is not among the fixtures, and that is a decision rather than an omission.** The gate
contributes exactly one `bool` to this sequence and no observable state: whether the framework takes
the undo branch is `sdk/_engine/integration.py`'s to decide and stage 9's to test, and the property
here is true of every path that reaches it. Requiring one would also make the integrator half of
this suite unrunnable at the stage it is written for - stage 5 ships the git adapters and stage 6
ships the first `Verifier`, and the build stages split this deliverable's acceptance across exactly
that line.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe.

1. **That a `retry` ever lands.** The port's two-case outcome applies to `retry` as much as to
   `land`, and only the conflicted case is exercised here. A retry that succeeds needs the
   collision resolved in the held target between the two calls, and resolving one means putting
   that target into a state this suite would have to know the shape of - which is the one piece of
   knowledge §3.4 removed from this port on purpose. So the landed branch of `retry` is exercised
   by nothing here, and an implementation whose `retry` can only ever conflict passes.

2. **What a held target looks like.** Nothing inspects one: no marker, no half-resolved path, no
   in-progress predicate, no ref. The hold is observed only as `retry` not raising and, once
   released, as `retry` raising - which is the whole vocabulary the framework has for it too.

3. **`UpstreamUnavailable` and `UpstreamUnexpected`.** Nothing here can make a repository or a far
   side unreachable, and no member takes anything that would provoke either. The one error this
   suite raises against is `InternalError`, from `retry` with nothing pending, which is ours.

4. **That `Conflict.paths` names anything.** Empty is a claim the port protects - an integrator
   that cannot enumerate what collided reports `()` and says why in `summary` - so the test accepts
   either, and asserts only that a non-empty tuple names the file that actually collided. Against
   an implementation that reports `()`, that assertion never runs.

5. **That the framework runs a gate at all, or that a failing gate is what triggers the undo.**
   This suite pins the property and not the wiring, for the reasons above.

6. **That `land` leaves the source alone.** The port promises nothing about the source's state
   afterwards, so nothing here asserts one - including the case where an implementation records
   something on the source's line of work as part of landing.

7. **Anything about the lease, or about two runs.** §3.4 gives the framework a lease per
   integration target and `sdk/_engine/integration.py` owns it; the port deliberately does not
   model it. This suite drives one integrator in one process and cannot start a second.

8. **That a landing is atomic, or what a crash mid-landing leaves behind.** Nothing here can kill a
   process. What is asserted is that an `abort` after a conflict puts the target back, which is the
   half of that story with a witness in this process.

9. **That an integrator whose far side wants a reviewer waits inside `land`.** The port accepts
   that cost in as many words and there is no third outcome for "opened, and waiting". A suite
   cannot produce a reviewer, and from out here waiting is indistinguishable from a slow landing.

10. **That the `Integrator` and the `WorkspaceProvider` are over one repository.** Nothing can
    check it from out here. A pair over two repositories fails these tests as though the
    implementation were broken, which is why the fixtures say it in as many words.

## Where the port is silent, and what this suite assumed

**That a successful landing leaves the target's own checkout holding the combined work, at the head
the outcome names.** The port says `land` puts what the source holds into the target and reports
"the target's state after the work landed", and does not spell out that the target `Workspace` is
then at that state. Two things in §3.4 force the reading: the build gate runs in the target's
workspace, so a target whose tree does not hold the combination would have the gate deciding about
a tree the outcome does not name; and the undo is `Workspace.restore(head)` on that same workspace,
which can only put back something that moved. An implementation whose far side lands elsewhere owes
the target the result, and that is the cost the port already accepts for it.

**That retrying a landing nobody resolved conflicts again.** The port describes `retry` as looking
again after something outside it changed the situation, and calls a repeated `Conflict` the
ordinary result of a partial resolution. Nothing changed at all is the limiting case of that, and
the only other answer available would be a head nobody produced.

**That an ordinary completed landing is the "nothing pending" state for `abort`.** The port names
the person who finished the held landing by hand and says the right thing is to leave their work
alone; this suite cannot make a person resolve a conflict, so it produces the state they leave -
work landed, nothing pending - and holds `abort` to the same promise there.

**That two children creating one file with contents sharing no line must collide.**
`_integration_targets` argues that where it builds them: there is no combination of those two
states that is anybody's answer, so an implementation that produces one has guessed.
"""

from collections.abc import Iterator

import pytest

from agl.ports.integration import Integrator
from agl.ports.workspace import WorkspaceProvider

from ._integration_protocol import IntegrationProtocolContract
from ._integration_targets import (
    CHILD_WORK,
    hold_a_target,
    open_a_target_and_two_children,
)
from ._workspace_files import ALPHA, TRACKED, body, read, record, write


class IntegratorContract(IntegrationProtocolContract):
    """The suite. One question - is this work in the target now - and the protocol its second
    answer starts.

    Its own tests are `land`: work that goes in, work that was already in, work that will not
    combine, and the target being put back after a gate said no. The half it inherits is
    `_integration_protocol`, named in this module's docstring.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and
    a test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def integrator(self) -> Integrator | Iterator[Integrator]:
        """The implementation under test, bound to one repository by construction.

        Bound by construction is the port's own design - no method takes a repository, only the two
        workspaces it is landing between - so this fixture is the only place the repository is
        named, exactly as the container names it once and hands the same instance to `integrate()`.

        The return type is a union so that `mypy --strict` accepts either shape of override: return
        an integrator, or `yield` one and tear it down after. pytest takes both, and an override
        narrowing a plain `-> Integrator` to `-> Iterator[Integrator]` would not typecheck. An
        `async def` fixture (`@pytest_asyncio.fixture`) is a third shape no annotation here can
        cover; if an implementation needs one, a `# type: ignore[override]` on it is the honest
        escape and costs this suite nothing.
        """
        raise NotImplementedError(
            "the Integrator contract suite has no implementation to run against: subclass "
            "IntegratorContract and override the `integrator` fixture to hand back the Integrator "
            "under test"
        )

    @pytest.fixture
    def provider(self) -> WorkspaceProvider | Iterator[WorkspaceProvider]:
        """A provider **over the same repository**, because that is how this suite makes a landing.

        `land` takes two workspaces and this port has no member that makes one, so every situation
        below is provisioned and recorded through `WorkspaceProvider` and `Workspace`. This
        module's docstring argues why that is better than a fixture handing over a prepared pair,
        and states its cost.

        The same repository as `integrator`, which nothing here can check: make both fixtures
        depend on whichever one builds it. A pair over two repositories fails these tests as though
        the implementation were broken.

        Function-scoped, like every fixture in this package. Each test lands under the same label,
        so a provider carried between tests would hand the second one the first one's lines of
        work - and in this suite that means the first test's landings.
        """
        raise NotImplementedError(
            "the Integrator contract suite has no way to make the workspaces it lands between: "
            "subclass IntegratorContract and override the `provider` fixture with a "
            "WorkspaceProvider over the same repository the Integrator under test lands in"
        )

    @pytest.fixture
    def base(self) -> str:
        """A state of that repository for the workspaces this suite lands between to be cut from.

        The same value `WorkspaceContract` and `HistoryContract` ask for and for the same reason:
        `open` takes one, and a provider is addressed by name rather than by anything a caller
        computed, so nothing here can ask it what is in the repository it is over.

        One base for all three workspaces, because a run's own place and its children are cut from
        one state and two children that never shared a state would have nothing to collide over.
        """
        raise NotImplementedError(
            "the Integrator contract suite has nothing to cut a workspace from: subclass "
            "IntegratorContract and override the `base` fixture with a ref or commit id that "
            "exists in the repository under test"
        )

    async def test_landing_puts_the_source_s_work_into_the_target_and_says_where_it_is_now(
        self, integrator: Integrator, provider: WorkspaceProvider, base: str
    ) -> None:
        """The whole question this port exists to answer, and the one shape a run carries on from.

        Both sides are `Workspace` because a workspace is what the framework has: it carries the
        line of work's name, it can report where that line currently is, and for a local
        implementation it is also the checkout the work happens in. What an implementation reads
        off them is its own business, and nothing here asks.

        Three assertions, and the second is the one an implementation can pass weakly without.
        The outcome says it landed; **the target's own tree holds the work**, because §3.4 runs the
        build gate in that tree and a gate testing a tree the outcome does not name is a gate
        deciding about nothing; and the head the outcome reports is the head the target is now at,
        which is the same claim from the other side. This module's docstring argues that reading
        where the port is silent about it.
        """
        target, child, _ = await open_a_target_and_two_children(provider, base)
        before = await target.head()
        write(child, ALPHA, CHILD_WORK)
        landed = await record(child, "the child's own work")
        assert landed != before, (
            "recording the child's work left it at the state the target is still at, so nothing "
            "below would be evidence about landing anything"
        )

        outcome = await integrator.land(child, target)

        assert outcome.conflicted is False, (
            f"landing a child's work into a target that has touched nothing reported a conflict: "
            f"{outcome.conflict}. There is nothing here for it to collide with"
        )
        assert outcome.head is not None, "not conflicted, so the outcome carries a head"
        assert read(target, ALPHA) == CHILD_WORK, (
            "the child's work is not in the target after a landing that reported success. This is "
            "the assertion an implementation that moved a ref and stopped fails: the framework "
            "runs the build gate in this tree, and it is testing the combination or it is testing "
            "nothing"
        )
        assert await target.head() == outcome.head, (
            f"the outcome says the target is at {outcome.head!r} and the target says it is at "
            f"{await target.head()!r}. The head is what the run records for a landing, and the "
            f"gate that runs next runs in this workspace - so the state named and the state "
            f"standing there have to be one thing"
        )
        assert await target.head() != before, (
            "work arrived in the target and its head did not move, so nothing recorded the "
            "landing and nothing can be put back to before it"
        )

    async def test_work_the_target_already_holds_still_lands_and_the_head_does_not_move(
        self, integrator: Integrator, provider: WorkspaceProvider, base: str
    ) -> None:
        """A landing that changed nothing is still a landing, and the port says so by hand.

        This is the ordinary shape of a replayed run (§3.6): a resume walks the same workflow
        again, reaches the same integration, and the child's work is already in. It is also what a
        step that produced nothing looks like from here. Neither is a failure, neither is a
        conflict, and neither is a third case - `head` names where the target is now, which is the
        only thing the caller was going to do with it.

        The assertion that bites is that the head did not move. An implementation recording an
        empty landing anyway would answer with a new head every time a resume ran, which is a
        deliverable branch growing a commit per replay and a `contains` question drifting away from
        the state anybody recorded.
        """
        target, child, _ = await open_a_target_and_two_children(provider, base)
        write(child, ALPHA, CHILD_WORK)
        await record(child, "the child's own work")
        first = await integrator.land(child, target)
        assert first.conflicted is False, (
            f"landing a child's work into an untouched target reported a conflict: "
            f"{first.conflict}. This test is about landing it a second time"
        )
        settled = await target.head()

        again = await integrator.land(child, target)

        assert again.conflicted is False, (
            f"landing work the target already holds reported a conflict: {again.conflict}. A "
            f"child whose work is already contained in the target is the ordinary way a replayed "
            f"run reaches this port, and it is not a failure, not a collision, and not a case for "
            f"a workflow's conflict screen"
        )
        assert again.head == settled, (
            f"a landing that had nothing to do answered with {again.head!r} rather than with the "
            f"target's unchanged head {settled!r}. A landing that changed nothing still reports "
            f"where the target is now"
        )
        assert await target.head() == settled, (
            "the target moved under a landing of work it already held, so a resume adds a state "
            "to the deliverable branch every time it runs"
        )
        assert read(target, ALPHA) == CHILD_WORK, "and the work that was already there still is"

    async def test_a_conflict_is_the_second_answer_and_never_an_exception(
        self, integrator: Integrator, provider: WorkspaceProvider, base: str
    ) -> None:
        """Two children, one file, and the answer a workflow puts on its own screen.

        **A conflict is a return value.** Raising would make the workflow's own decision path an
        exception handler, and would put "could not be combined" in the same bucket as "the far
        side is down" - two things whose only common feature is that neither landed. So this test
        contains no `pytest.raises`, and that absence is the assertion: an implementation that
        raises fails before reaching a line of its own.

        It is also where "not resolved by guessing" is asserted, and it is asserted by the outcome
        rather than by looking at the target. An implementation that picked a side would have
        returned a head, and `_integration_targets` builds a collision no honest implementation can
        combine precisely so that a head here means a guess.

        `paths` is accepted empty, because the port protects that case: an integrator that cannot
        enumerate what collided reports `()` and says why in `summary`, and a far side answering
        only "these cannot be combined cleanly" is a real implementation this shape has to let be
        honest. What is not accepted is a list that names files while leaving out the one that
        actually collided.

        The hold this leaves is real and is released here, because a run owes the target one of the
        two verbs on every path out. What that hold *is*, and what the two verbs do to it, is
        `_integration_protocol`'s.
        """
        held = await hold_a_target(integrator, provider, base)
        outcome = held.outcome

        assert outcome.head is None, (
            f"a conflicted outcome carries the head {outcome.head!r}. The two cases are exactly "
            f"one each: work landed and the target has a resulting state, or it did not and there "
            f"is something to put on a screen"
        )
        conflict = outcome.conflict
        assert conflict is not None, "conflicted, so there is a conflict to read"
        assert conflict.summary, (
            "a conflict came back with nothing for a person to read. `summary` is the only part "
            "guaranteed to say anything - the workflow shows its own screen, and the decision "
            "being asked there is which of `retry` and `abort` to call"
        )
        if conflict.paths:
            assert TRACKED in conflict.paths, (
                f"the conflict names {conflict.paths} and the file the two children each created "
                f"is {TRACKED}. An implementation that cannot enumerate what collided reports an "
                f"empty tuple and says why in the summary; one that names some paths and not the "
                f"one that collided is telling a workflow to go and look in the wrong place"
            )

        await integrator.abort(held.target)

    async def test_a_landing_undone_after_a_gate_failed_leaves_the_target_as_if_it_never_happened(
        self, integrator: Integrator, provider: WorkspaceProvider, base: str
    ) -> None:
        """§3.4's undo, asserted as the outcome it has to reach rather than as the call that
        reaches it.

        The framework reads the target's head before it calls `land`, runs the build gate on what
        landed, and on failure hands that same value back to `Workspace.restore`. There is no
        `Integrator.revert()` and §3.11 says why: undoing a landing that succeeded leaves no
        pending state to consult, so it is not this port's knowledge that is needed - the target
        simply has to be put back where it was, which `Workspace.restore` already does at two other
        moments. This module's docstring argues why the test for that lives here and why no
        `Verifier` appears in it.

        So what is asserted is indistinguishability, from three sides. The landed file is gone -
        `restore` removes what was not in the head it was given, which is the half that would
        survive a bare move of the head and the half a failed gate cannot afford to leave behind.
        The target's own work is untouched, because "as if the landing never happened" is not "as
        if nothing ever happened". And the same landing can be made again and lands the same way,
        which is the strongest form of the claim available from out here: an implementation that
        remembered the first landing - a recorded merge, a memo of what it had already combined -
        answers the second one with a head and no work, and the run has a gate-passing state
        nobody's code is in.
        """
        target, child, _ = await open_a_target_and_two_children(provider, base)
        write(target, TRACKED, body("the target's own work"))
        before = await record(target, "the target's own work")
        write(child, ALPHA, CHILD_WORK)
        await record(child, "the child's own work")

        outcome = await integrator.land(child, target)
        assert outcome.conflicted is False, (
            f"landing a child's work into the target reported a conflict: {outcome.conflict}. The "
            f"two touch different files, and this test is about undoing a landing that worked"
        )
        assert read(target, ALPHA) == CHILD_WORK, "the landing put the work in, as a precondition"
        assert await target.head() != before, "and moved the target off the head read before it"

        await target.restore(before)

        assert await target.head() == before, (
            f"restoring the target to the head read before the landing left it at "
            f"{await target.head()!r}. This is the value the framework carries across the gate, "
            f"and putting the target back is the whole of what a failed gate does"
        )
        assert read(target, ALPHA) is None, (
            "the landed work is still in the target's tree after the landing was undone. A gate "
            "that failed rejects the combination, and a target still carrying it is one the next "
            "landing combines with, the next gate tests, and the next reader believes"
        )
        assert read(target, TRACKED) == body("the target's own work"), (
            "the target's own work went with the undone landing. What is being put back is the "
            "state before this landing, not the state before everything"
        )

        again = await integrator.land(child, target)

        assert again.conflicted is False, (
            f"landing the same work again after the first landing was undone reported a conflict: "
            f"{again.conflict}. The target is at the state that landing was made from, so an "
            f"implementation refusing here is remembering something the target no longer holds"
        )
        assert read(target, ALPHA) == CHILD_WORK, (
            "landing the same work again after the undo answered with a head and left the work "
            "out of the target. The target is indistinguishable from before that landing or it is "
            "not, and an implementation that recorded the first attempt somewhere of its own has "
            "just told a run that a combination is in when nobody's code is"
        )
