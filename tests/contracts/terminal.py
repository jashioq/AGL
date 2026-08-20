"""What every `Terminal` owes, asserted before an implementation of one exists - in two halves.

A terminal that can take input and a terminal that cannot satisfy **different halves of one
contract**, so there are two classes here. Subclass whichever one describes the implementation,
override its fixtures, and add nothing:

    class TestTheTerminalIWrote(TerminalContract):
        @pytest.fixture
        def terminal(self) -> Terminal:
            return TheTerminalIWrote(...)        # built, and not yet entered

        @pytest.fixture
        def driver(self, terminal: Terminal) -> TerminalDriver:
            return TheDriverIWrote(terminal)     # over that same terminal

    class TestTheHeadlessOne(HeadlessTerminalContract):
        @pytest.fixture
        def terminal(self) -> Terminal:
            return TheHeadlessOneIWrote(...)     # no driver: it displays nothing

The real adapter and the fake both run these classes, which is the whole mechanism keeping a fake
from drifting into fiction (§1.9) - and here it matters more than anywhere else in the package,
because §3.7 has the headless behaviour *double* as the fake. The two are not an implementation and
a stand-in for it; they are two implementations of one port, and this is what keeps them honest. It
is written at stage 3, before either exists, because a subagent that writes its own tests writes
tests that pass - and stage 6 ends with "contract suite 3.5 passes", a sentence worth something only
when the suite had no stake in the outcome.

`TerminalContract` is one class assembled from four modules and `HeadlessTerminalContract` from two;
only those two names and `TerminalDriver` are public. `_terminal_lifecycle` holds what both owe -
the context manager, and the two things true outside it - and declares the `terminal` fixture for
both. `_terminal_slot` and `_terminal_queues` follow the port's own line, "one slot, two queues".
`_terminal_registration` holds what a `show` call registers and is where this port's one genuinely
open question is settled. `_terminal_headless` holds the rule a terminal with no input
follows. What this module keeps for itself is the pair §3.7 singles out: preemption, which it calls
"not cosmetic", and `pending`, whose example it states as a specification.

## Two classes, and not one class with a capability fixture

The two halves contradict each other. A terminal that can take input queues a `Screen[T]` and waits;
one that cannot raises `UpstreamUnavailable` on the same call. There is no implementation that does
both and no test that can be written to accept either without asserting nothing.

A single class with a `takes_input` fixture was the alternative, and it fails on the thing that
matters: the flag would be set by the same person who wrote the implementation, and a wrong flag
would **skip** the half that applies rather than fail it. A headless implementation that declared
itself interactive would drag a `driver` fixture into existence that it has nothing to build from;
an interactive one that declared itself headless would quietly run none of the queue tests, which is
precisely the failure mode this deliverable exists to prevent.

Two classes turn that into a test failure in both directions. Point an input-capable terminal at
`HeadlessTerminalContract` and it queues the question the suite requires it to refuse, and fails on
the deadline. Point a headless one at `TerminalContract` and every interactive test raises where it
should have waited, and every slot test finds nothing displayed. Choosing wrongly is loud.

It also settles the driver: only `TerminalContract` declares one, and the headless half is runnable
with the single fixture every implementation can supply.

## The driver, in one paragraph

`Terminal` has no member that answers a screen - answering is what a person does - so this suite
needs something that plays one, and that is an extra fixture an implementer writes. Two members:
what is displayed, and responding to it by naming one of that screen's own responses.
`_terminal_driver` argues its shape, argues what a third member would have cost, and states plainly
that a driver is written by the party it exists to catch. Every ordering claim below rests on which
`show` call an answer reaches, which is the port's own surface; the driver is used to synchronise
and to see the slot, which no member of this port can report.

## Written against the port, never against a renderer

Nothing here assumes a TTY, a curses screen, a control code, a colour, a size, a position, a
library, or a frame rate. `Screen`, `Rows`, `Row`, `Text`, `Choice` and `TextInput` are the whole
vocabulary, because they are the whole of what a view is; everything else is mechanism and mechanism
lives in `adapters/`. §3.7's future `run.web` is a different object with websocket concepts on it,
and a suite that had crept into terminal *implementation* concepts would be a suite that had decided
what a terminal is made of on behalf of the next one.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe. Every one is a limit of what this port's surface can be made to
reveal, not a test somebody forgot.

1. **That anything was ever drawn.** Nothing here looks at a display. `displayed()` is what an
   implementation says it is showing, and one that reported a screen it never wrote passes
   everything below. What is pinned is which screen is current and which `show` call an answer
   reaches; that a person could have seen any of it is not observable from inside the process.

2. **Any frame rate, or that a redraw loop exists.** Re-invocation is asserted as *registration* - a
   live argument reaching the screen, a response that grew after `show` was called - and never as a
   schedule. An implementation that derives the screen from the view and its arguments only when
   somebody asks what is displayed passes, and §3.7's ~10 Hz is deliberately encoded nowhere.

3. **The diff, and write-on-change.** Comparing this frame against the last and writing only on a
   change is what makes per-frame invocation affordable, and it is invisible from out here: a
   terminal that rewrote everything every frame passes.

4. **That preemption keeps text somebody was part-way through typing.** §3.7 lists losing it as
   known and accepted unless an implementation keeps input state per screen, and the driver has no
   way to type without submitting - a member that could would be a member dictating how input is
   held.

5. **Whether `pending` lists a priority a *passive* `show` was given.** The clause says the map
   reports every priority the terminal has been asked for, and priority has no meaning for a passive
   screen, so both readings are live. Every exact-equality assertion here is made in a test that has
   shown no passive screen, and an implementation may take either reading.

6. **What a headless terminal's `pending` lists**, for the same clause at the other end. It never
   queues anything, so only "no count is positive" is asserted.

7. **That the display was handed back.** `__aexit__` is observed as the terminal being outside its
   context afterwards - `show` raising `InternalError` - and never as a device restored, a mode
   reset or a screen cleared. Nothing on this port could report that, which is why the port asks for
   a context manager rather than a `restored` flag somebody would then have to trust.

8. **Re-entering a terminal after leaving it.** Not asserted either way. The framework opens one,
   once, and a suite that demanded either answer would be inventing a clause.

9. **That a passive `show` returned *immediately*.** It is asserted to come back inside the
   deadline, which is what a suite can see. A terminal that took four seconds passes, and a
   threshold tight enough to catch it would fail an honest implementation on a loaded machine.

10. **Anything about more than two priorities.** Two are exercised, which is §3.7's own example and
    what one level of preemption needs. Nothing here says what three levels of displacement do.

11. **A view that raises, or one whose arguments do not match its parameters.** The port says a
    misspelled argument surfaces inside the redraw loop rather than at the call site, and settles
    nothing about what a terminal does then - so nothing here provokes one, because there is no
    answer to hold an implementation to.

12. **Purity.** The port requires it, cannot enforce it, and says so; neither can this. Every view
    here is pure, and nothing checks that an impure one is refused, because none is offered.

13. **Any error but two.** `UpstreamUnavailable` on a headless terminal and `InternalError` outside
    the context are the only ones provoked. There is no member on this port that could make a
    display fail mid-run, so no translation is exercised.

14. **Anything about two terminals, two workflows or two event loops.** One terminal in one loop,
    which is also the port's own model: single-threaded asyncio with the redraw loop as another
    task.

15. **What a cancelled `show` does.** The port says nothing about cancellation and neither does
    this suite. `Asking` cancels whatever a failing test left waiting, so that a failure is reported
    once instead of trailing a warning, and no assertion depends on what happens to a cancelled
    screen.

16. **That the driver tells the truth.** It is the one fixture in this package whose job is to
    report rather than to act, and it is written by the party it exists to catch.

17. **What an interactive `show` outside the context does on a *headless* terminal.** Two of this
    port's rules reach that one call - it is outside the context, and it is a `Screen[T]` on a
    terminal that cannot answer it - and nothing says which wins. It is asserted for a terminal that
    can take input, where only one rule applies, and for a passive screen on both, where the
    headless rule and the lifecycle rule do not disagree.

## Where the port is silent, and what this suite assumed

**That a driver can exist at all** - that an implementation can say what it is displaying and be
told what somebody pressed. Everything interactive below rests on it, and `_terminal_driver` argues
it as the cost it is.

**That "outside the context" has two sides.** The port's sentence names no side, and this suite
reads a `show` after `__aexit__` as outside it just as much as one before `__aenter__`. The second
is the one that actually happens: a workflow holding `run.terminal` past the end of a run, with the
display already handed back.

**That `__aenter__` may hand back a different object of the same type.** `Self` says which type, not
which object, so type is what is asserted.

**That a preempted question keeps its place in its own queue.** FIFO within a priority is by
arrival, so a question displaced by a more urgent one is still ahead of anything queued behind it
and is what the terminal falls back to when the urgent one is dismissed. The alternative - putting
it at the back - would take a person out of the question they were half-way through and then hand
them somebody else's.

**That only answering the displayed screen resolves a `show`**, and that exactly one is displayed.
`_terminal_queues` argues that from the three sentences that require it.

**That identity is the `show` registration and never the `Screen` value.**
`_terminal_registration` argues it from the port's own types, and it is the one reading here whose
alternative silently hands an agent an answer to a question it never asked.

**That headlessness is decided once for a terminal's lifetime.** `_terminal_headless` argues it: the
rule is phrased on what the terminal can do, and one that changed its mind would make
`UpstreamUnavailable` intermittent.

**That a passive `show` under a question still comes back at once.** The slot keeps updating while a
question is displayed, and nothing says the write waits for the screen to be free - a workflow
updating its board behind a question it is itself blocked on would otherwise deadlock.
"""

from collections.abc import Iterator

import pytest

from agl.ports.terminal import Terminal, Text

from ._terminal_driver import (
    Asking,
    TerminalDriver,
    answer,
    let_frames_pass,
    shown,
    within,
)
from ._terminal_headless import HeadlessRulesContract
from ._terminal_lifecycle import TerminalLifecycleContract
from ._terminal_queues import TerminalQueueContract
from ._terminal_registration import TerminalRegistrationContract
from ._terminal_slot import TerminalSlotContract
from ._terminal_views import (
    AGENT,
    APPROVE,
    APPROVED,
    CONFLICT,
    EARLY,
    LAST,
    LATE,
    URGENT,
    Approval,
    question,
)

__all__ = ["HeadlessTerminalContract", "TerminalContract", "TerminalDriver"]


class TerminalContract(
    TerminalSlotContract,
    TerminalQueueContract,
    TerminalRegistrationContract,
    TerminalLifecycleContract,
):
    """The suite for a terminal that can take input: one slot, two queues, and a person at them.

    Its own three tests are the pair §3.7 singles out. **Preemption**, which it calls not cosmetic:
    `integrate()` holds the target lease while a conflict is unresolved, so a conflict screen queued
    behind two agent questions would stall the merge queue on something unrelated. And
    **`pending`**, twice: the state §3.7 writes out as a specification, zeros and all, and the
    snapshot the port promises whoever reads it. The four halves this class is assembled from are
    named in the module docstring.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and a
    test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def driver(self) -> TerminalDriver | Iterator[TerminalDriver]:
        """Something that plays the person, **over the same terminal the `terminal` fixture built**.

        The second and last knob, and the only one in this package that reports rather than acts.
        `Terminal` has no member that answers a screen, so a suite for it cannot drive the queues
        with the port alone; `_terminal_driver` argues the two members at length, argues what a
        third would have cost, and says plainly what handing this to the implementation's own author
        does and does not buy.

        The same terminal as `terminal`, which nothing here can check: make this fixture depend on
        that one, as the example in the module docstring does. A driver over some other terminal
        fails these tests as though the implementation were broken.

        The return type is a union so that `mypy --strict` accepts either shape of override: return
        a driver, or `yield` one and tear it down after. pytest takes both, and an override
        narrowing a plain `-> TerminalDriver` to `-> Iterator[TerminalDriver]` would not typecheck.
        An `async def` fixture (`@pytest_asyncio.fixture`) is a third shape no annotation here can
        cover; if an implementation needs one, a `# type: ignore[override]` on it is the honest
        escape and costs this suite nothing.
        """
        raise NotImplementedError(
            "the Terminal contract suite has no way to answer a screen: subclass TerminalContract "
            "and override the `driver` fixture with a TerminalDriver over the same terminal the "
            "`terminal` fixture hands back - or subclass HeadlessTerminalContract instead, which "
            "needs no driver because a terminal that cannot take input displays nothing"
        )

    async def test_a_more_urgent_question_takes_the_screen_and_the_one_it_displaced_comes_back(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """One level of preemption, and the reason it exists is a lease rather than a look.

        `integrate()` leaves its target held mid-landing while a conflict is unresolved. A conflict
        screen queued behind two agent questions would therefore stall the merge queue on something
        unrelated to it - not a cosmetic delay, a run whose landing cannot proceed until somebody
        finishes answering a question about something else. That is the entire justification for
        preemption, and it is why the displacement has to be immediate rather than "next in line".

        Three claims here, and the middle one is the one an implementation can fail while looking
        right. A more urgent question **takes the screen** from a less urgent one. A less urgent one
        arriving afterwards **does not take it back**, because the highest-priority screen is always
        the one shown and there is no fairness rule that would let a lower priority interrupt. And
        the displaced question **comes back** when the urgent one is dismissed - it is not lost, not
        answered by the gesture that dismissed the other, and not sent to the back of its own queue
        behind the one that arrived while it was off screen.

        That last part is why the fallback is checked all the way down: after the conflict, the
        order is the order the three agent questions arrived in, which is what FIFO within a
        priority means once preemption has moved something off screen and back.
        """
        async with terminal as term, Asking(term) as ask:
            early = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)
            late = ask(question, priority=AGENT, label=LATE)

            urgent = ask(question, priority=CONFLICT, label=URGENT)

            await shown(driver, URGENT)
            last = ask(question, priority=AGENT, label=LAST)
            await let_frames_pass()
            current = driver.displayed()
            assert current is not None and current.body == Text(URGENT), (
                f"an agent question arrived while a conflict was on screen and what is displayed "
                f"is {current!r}. The highest-priority screen is always the one shown: a terminal "
                f"that let a lower priority take the screen would put the merge queue back behind "
                f"the thing preemption exists to get it in front of"
            )
            assert not early.done() and not late.done() and not last.done(), (
                "a question resolved while the conflict was the screen in front of the person. "
                "Only what is displayed can be answered, and what was displayed is the conflict"
            )

            await answer(driver, APPROVE)
            assert await within(urgent, "the conflict, once it was answered") == Approval(
                label=URGENT, said=APPROVED
            )

            for label, asked in ((EARLY, early), (LATE, late), (LAST, last)):
                await shown(driver, label)
                await answer(driver, APPROVE)
                assert await within(asked, f"the question showing {label!r}") == Approval(
                    label=label, said=APPROVED
                ), (
                    f"after the conflict was dismissed the terminal did not fall back to {label!r} "
                    f"in its turn. The question that was displaced keeps its place - it arrived "
                    f"before the ones behind it and was never answered - so the fallback is the "
                    f"queue as it always was, minus what has been answered since"
                )

    async def test_pending_counts_what_is_waiting_and_keeps_reporting_a_priority_that_emptied(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """§3.7's `{5: 2, 10: 0}`, built exactly, because the zero is the specification.

        Two clauses, and the map states both at once. **What is on screen is excluded** - it is
        displayed, not pending - so the conflict at 10 contributes nothing to its own count while a
        person is looking at it. And **every priority the terminal has been asked for is reported,
        including the ones with nothing waiting**, which is what the zero at 10 is.

        The port says the second one in as many words and gives the reason: two implementations
        would otherwise disagree about the empty entries, and a workflow reading `pending.get(10,
        0)` would see the same run differently on each. That is a workflow rendering "2 waiting" in
        a corner and getting a different corner from a different terminal - `pending` exists because
        there are no timeouts anywhere here, so an unanswered question is invisible without it and a
        person can walk away from a fully blocked run believing it is working.

        The state is the one §3.7 describes: two agent questions waiting, one of which was displaced
        rather than never shown, and a conflict displayed with nothing behind it. Then everything is
        answered, and the assertion at the end is the zeros clause in its purest form - both
        priorities still listed, both empty, because that is what "has been asked for" means.

        No passive screen is shown anywhere in this test. Whether a dashboard's `priority` argument
        - which the port says means nothing for one - reaches this map is genuinely unsettled, and
        the gaps say so; exact equality here would have decided it by accident.
        """
        async with terminal as term, Asking(term) as ask:
            early = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)
            late = ask(question, priority=AGENT, label=LATE)
            urgent = ask(question, priority=CONFLICT, label=URGENT)
            await shown(driver, URGENT)

            assert dict(term.pending) == {AGENT: 2, CONFLICT: 0}, (
                f"the queues hold two agent questions waiting behind a displayed conflict, and "
                f"`pending` reports {dict(term.pending)}. §3.7 writes this exact state as "
                f"{{{AGENT}: 2, {CONFLICT}: 0}}: the displaced question is waiting again, the one "
                f"queued behind it never stopped, and the conflict is on screen - which is "
                f"displayed and so counts as nothing"
            )

            await answer(driver, APPROVE)
            await within(urgent, "the conflict, once it was answered")
            for label, asked in ((EARLY, early), (LATE, late)):
                await shown(driver, label)
                await answer(driver, APPROVE)
                await within(asked, f"the question showing {label!r}")

            assert dict(term.pending) == {AGENT: 0, CONFLICT: 0}, (
                f"every question has been answered and `pending` reports {dict(term.pending)}. A "
                f"priority this terminal has been asked for stays in the map with a count of zero: "
                f"a workflow that read a number there while the queue was busy has to keep reading "
                f"the same key to watch it empty, and a key that vanishes makes that a different "
                f"answer on a different implementation"
            )

    async def test_pending_is_a_snapshot_and_reading_it_again_is_how_the_queue_moves(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """A read of current state, and the mapping it hands back does not change afterwards.

        The port makes `pending` a property rather than a method because it is a read rather than
        work, and says the mapping returned is a snapshot. That matters to the one consumer there
        is: a view is invoked again every frame, so a workflow that put `term.pending` into a
        dashboard is reading it ten times a second, and an implementation that handed back a live
        view of its own queue would be handing workflow code something that mutates underneath a
        comprehension halfway through building a row.

        So the mapping taken before an answer still reads the same after it, and a fresh read shows
        the queue has moved. An implementation returning its own dictionary fails the first
        half; one that cached the map and kept handing back the same object fails the second.
        """
        async with terminal as term, Asking(term) as ask:
            early = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)
            late = ask(question, priority=AGENT, label=LATE)
            await let_frames_pass()

            before = term.pending
            taken = dict(before)
            assert taken == {AGENT: 1}, (
                f"one question is displayed and one is waiting behind it, and `pending` reports "
                f"{taken}. The rest of this test is about that mapping not changing, so it has to "
                f"be right before it can stay right"
            )

            await answer(driver, APPROVE)
            await within(early, "the question that was on screen")
            await shown(driver, LATE)

            assert dict(before) == taken, (
                f"the mapping `pending` handed back said {taken} and now says {dict(before)}. It "
                f"is a snapshot: a workflow that read it into a view is holding it while it builds "
                f"a row, and a live view of the terminal's own queue changes under whoever is "
                f"iterating it"
            )
            assert dict(term.pending) == {AGENT: 0}, (
                f"reading `pending` again after an answer reports {dict(term.pending)} rather than "
                f"an emptier queue. Reading it again is the only way anything sees the queue move, "
                f"so a snapshot that is also stale is a number nobody can act on"
            )

            await answer(driver, APPROVE)
            await within(late, "the question that was queued behind it")


class HeadlessTerminalContract(HeadlessRulesContract, TerminalLifecycleContract):
    """The suite for a terminal that **cannot take input**: it drops a dashboard and refuses a
    question.

    It has no tests of its own. `_terminal_headless` holds the rule and the argument for asserting
    it - that §3.7 phrases it on input rather than on a TTY so that a plain log stream has a rule
    too, and that this behaviour doubles as the fake every AGL command runs against.
    `_terminal_lifecycle` holds the context manager, which a terminal owes whether or not anybody
    can answer it.

    **No `driver` fixture**, because there is nothing to drive: this terminal displays nothing and
    answers nothing, so `terminal` is the whole of what an implementer supplies. The module
    docstring argues why that is a class of its own rather than a flag on the other one.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and a
    test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio
