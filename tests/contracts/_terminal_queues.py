"""A question waits for a person, one at a time, in the order they were asked.

Split out of `terminal.py` along the port's own line - "one slot, two queues" - and holding the
half of the queues that is about *answering*: that a `Screen[T]` blocks, that the two kinds of
response both produce a `T`, that questions at one priority are answered in the order they arrived,
that a question asked outside the context raises rather than waiting for nobody, and that exactly
one screen can be answered at a time. What `pending` reports and what preemption
does to the ordering are the other half, and they stay in `terminal.py` because §3.7 calls one "the
specification" and the other "not cosmetic".

**A single answerer is assumed here, and it is a reading of the port rather than a quotation.**
§3.7 says a human answers one thing at a time and that is why it must queue, and says the
highest-priority screen is always the one rendered; the ABC adds that `pending` excludes what is on
screen, which only means anything if exactly one thing is. The last test below turns that into a
clause: a queued question does not resolve while another is displayed. An implementation that
answered several at once would make `pending` a number nobody could act on and would put a person in
front of two questions with one keyboard.

`TerminalContract` in `terminal.py` inherits this class. Implementers subclass that one, never this
one, and the `terminal` and `driver` fixtures these tests take are declared there and in
`_terminal_lifecycle`.
"""

import pytest

from agl.ports.errors import InternalError
from agl.ports.terminal import Terminal

from ._terminal_driver import (
    Asking,
    TerminalDriver,
    answer,
    let_frames_pass,
    shown,
    within,
)
from ._terminal_views import (
    AGENT,
    APPROVE,
    APPROVED,
    EARLY,
    LAST,
    LATE,
    SAY_MORE,
    TYPED,
    Approval,
    question,
)


class TerminalQueueContract:
    """Blocking, both kinds of response, FIFO within a priority, and one answerer.

    `pytestmark` is repeated on every contract class in this package rather than inherited from one
    of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test, which is
    the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_an_interactive_screen_blocks_until_someone_answers_and_yields_what_they_picked(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """The other half of "always awaited", and the half that waits.

        A `Screen[T]` blocks until a person responds and yields the `T` their response produced.
        Both halves are asserted and the first is the one an implementation can pass weakly without:
        frames go by with the question on screen and the call has not come back, because there are
        no timeouts anywhere in this port and a question nobody answered blocks its step
        indefinitely. A terminal that returned early - a default, a `None`, whatever was on the
        screen before - would hand a workflow an answer no person gave, and §3.7's approval loop
        would revise a proposal against nobody's opinion.

        The second half is `Choice`: the value picking it produces is what `show` answers with.
        There is no key, no id and no index beside it, so a terminal that carried anything other
        than `value` would be carrying something the workflow has no name for.
        """
        async with terminal as term, Asking(term) as ask:
            asked = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)

            await let_frames_pass()
            assert not asked.done(), (
                "an interactive show came back before anybody had answered the screen it put up. "
                "There are no timeouts anywhere on this port: a question waits for a person, and a "
                "terminal that answers on their behalf makes a workflow's decision on the strength "
                "of nothing"
            )

            await answer(driver, APPROVE)

            assert await within(asked, "the question, once it was answered") == Approval(
                label=EARLY, said=APPROVED
            ), (
                "the choice that was picked carries the value the workflow gets back, and what "
                "came back is not it. `Choice.value` *is* the answer - there is deliberately no "
                "second way of naming which one was chosen - so a terminal that reported a label, "
                "a position or a screen has dropped the only thing the caller can use"
            )

    async def test_a_typed_answer_reaches_the_workflow_through_the_screens_own_maps(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """The terminal collects a string and hands it over, and never learns what a `T` is.

        `TextInput.maps` is the workflow's function, at the workflow's layer, and calling it is how
        typed text becomes the type a workflow declared. That is why the two response kinds are one
        `Response[T]` and why `show` promises a single return type across a screen offering both:
        §3.7's approval screen has a `Choice` and a `TextInput` side by side and answers with an
        `Approval` either way.

        A terminal that returned the typed string itself would typecheck at its own boundary - the
        `cast` its `show` already needs would swallow it - and would hand a workflow a `str` where
        it was promised its own type, failing wherever that value was next used rather than here.

        The same screen as the previous test, answered the other way. Both responses are offered on
        every question this suite shows, so the two routes to a `T` are two answers to one screen
        and not two screens that happen to differ.
        """
        async with terminal as term, Asking(term) as ask:
            asked = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)

            await answer(driver, SAY_MORE, TYPED)

            assert await within(asked, "the question, once it was typed into") == Approval(
                label=EARLY, said=TYPED
            ), (
                f"what was typed was {TYPED!r} and the screen's own `maps` turns that into the "
                f"workflow's type. A terminal that answered with the raw string, with the label "
                f"beside the field, or with anything it built itself has taken over a mapping that "
                f"belongs to the workflow - and this port never learns what the result is"
            )

    async def test_questions_at_one_priority_are_answered_in_the_order_they_were_asked(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """FIFO within a priority, so simultaneous questions from several agents stack and wait.

        Three children asking at once is the ordinary case (§3.7), and the order they are put to a
        person in is the order they arrived. Not last-in-first-out, which would leave the agent that
        asked first waiting longest while its siblings are served ahead of it, and not an order
        nobody can predict, which would make "two of them are waiting" a statement with no second
        half.

        The first question is waited for before the other two are asked, so their arrival order is a
        fact of this test rather than a race between three tasks. After that the loop asserts the
        whole of the clause: each one reaches the screen in turn, and answering it resolves *that*
        `show` call and not another.
        """
        async with terminal as term, Asking(term) as ask:
            early = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)
            late = ask(question, priority=AGENT, label=LATE)
            last = ask(question, priority=AGENT, label=LAST)

            for position, (label, asked) in enumerate(
                ((EARLY, early), (LATE, late), (LAST, last))
            ):
                await shown(driver, label)
                await answer(driver, APPROVE)
                assert await within(asked, f"the question asked {position + 1} of 3") == Approval(
                    label=label, said=APPROVED
                ), (
                    f"answering the screen showing {label!r} did not answer the show call that "
                    f"asked it. Three questions arrived at one priority in a known order, and "
                    f"FIFO within a priority is the whole of what decides which person's question "
                    f"is put in front of them next"
                )

    async def test_a_question_asked_outside_the_context_raises_instead_of_waiting_for_nobody(
        self, terminal: Terminal
    ) -> None:
        """The same clause as `_terminal_lifecycle`'s, where getting it wrong hangs the framework.

        A passive `show` outside the context that quietly did nothing is a lost dashboard. An
        interactive one that quietly *queued* is a workflow blocked forever on a terminal nobody is
        drawing, with no timeout anywhere on this port to end it - and from outside it looks exactly
        like a person who has not answered yet.

        This is asserted here rather than beside the passive case because it is only unambiguous for
        a terminal that can take input. On a headless one, two of the port's rules reach the same
        call - it is outside the context, and it is a `Screen[T]` on a terminal that cannot answer
        it - and the port does not say which wins. `terminal.py`'s gaps say so instead of a test
        deciding it by accident.

        No driver, because nothing here ever reaches a screen. The deadline is what separates the
        two failures this test tells apart: the wrong exception fails immediately, and a `show` that
        joined a queue fails at the deadline saying so.
        """
        with pytest.raises(InternalError):
            await within(
                terminal.show(question, priority=AGENT, label=EARLY),
                "an interactive show outside the terminal's context",
            )

    async def test_a_queued_question_does_not_resolve_while_another_one_is_on_screen(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """One answerer, settled: only the displayed screen can be answered, and one at a time.

        The port does not say this in a sentence of its own, and three of its sentences require it.
        A human answers one thing at a time, which is why a `Screen[T]` queues at all. The
        highest-priority screen is *always the one rendered*, singular. And `pending` excludes
        whatever is on screen - a subtraction that means nothing unless the thing on screen is one
        thing. So: exactly one interactive screen is displayed at a time, and only that one can be
        answered.

        What this rules out is an implementation that treats an answer as satisfying every screen
        that would accept it, or that resolves a queued `show` from anything other than a person
        answering the screen it put up. Either one hands an agent an answer to a question it never
        asked, and neither is visible in a suite that queues one question at a time.

        Two distinguishable questions, so that "the first one resolved" is a different observation
        from "one of them resolved". `_terminal_registration` runs the same shape with two
        *identical* ones, where the failure is that they collapse into one entry.
        """
        async with terminal as term, Asking(term) as ask:
            early = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)
            late = ask(question, priority=AGENT, label=LATE)

            await let_frames_pass()
            assert not early.done() and not late.done(), (
                "a show resolved with nothing answered at all. Both of these are waiting on a "
                "person, and the queue exists because there is one of them"
            )

            await answer(driver, APPROVE)
            assert await within(early, "the question that was on screen") == Approval(
                label=EARLY, said=APPROVED
            )

            await let_frames_pass()
            assert not late.done(), (
                "one answer resolved two show calls. The second question was never on screen and "
                "nobody has looked at it: an agent that gets back an answer to a question it never "
                "put in front of anybody is worse off than one still waiting, because it will act "
                "on it"
            )

            await shown(driver, LATE)
            await answer(driver, APPROVE)
            assert await within(late, "the question that was queued behind it") == Approval(
                label=LATE, said=APPROVED
            ), (
                "the queued question did not come back with its own answer once it reached the "
                "screen and was answered in turn"
            )
