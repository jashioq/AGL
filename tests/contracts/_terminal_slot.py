"""The slot: size one, replaced on write, no ordering, and still being written while unseen.

Split out of `terminal.py` along the line the port draws itself - "one slot, two queues" - because
a dashboard and a question are handled by one method and share almost nothing else. A passive
screen has no ordering, cannot be answered, never blocks and never joins anything; the only thing it
has in common with an interactive one is that a workflow puts both in front of a person by calling
`show`.

**Every assertion here needs the driver**, and that is not incidental to the slot: a passive `show`
returns `None`, so what it registered is invisible to every member on the ABC. The queues can be
watched through `pending` and through which `show` an answer reaches; the slot cannot be watched
through anything the port exposes. `_terminal_driver` argues that fixture at length, and this module
is the clearest case for why it had to exist.

`TerminalContract` in `terminal.py` inherits this class. Implementers subclass that one, never this
one, and the `terminal` and `driver` fixtures these tests take are declared there and in
`_terminal_lifecycle`.
"""

import pytest

from agl.ports.terminal import Terminal, Text

from ._terminal_driver import (
    Asking,
    TerminalDriver,
    answer,
    came_back,
    let_frames_pass,
    shown,
    within,
)
from ._terminal_views import AGENT, APPROVE, EARLY, LANDED, RUNNING, dashboard, question


class TerminalSlotContract:
    """A dashboard goes up, stays up, is replaced rather than queued, and outlives being hidden.

    `pytestmark` is repeated on every contract class in this package rather than inherited from one
    of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test, which is
    the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_a_passive_screen_answers_none_and_the_workflow_carries_on_with_it_up(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """One verb for both kinds of screen, and this is the half that does not wait.

        `show` is always awaited, and what makes a passive screen passive at run time is that
        `responses` is empty - not the annotation, which nothing can see from inside. So the two
        things pinned here are that the call comes back, and that it comes back with `None`: an
        implementation is free to hand back anything at all from behind the `cast` its own `show`
        needs, and a workflow that was promised nothing and given a `Screen` would carry it until
        somebody used it.

        And the screen is up *afterwards*. A dashboard that only existed for the duration of the
        call would satisfy "returns None" and be no dashboard at all - the whole point is that the
        workflow goes back to work with its board in front of somebody.
        """
        async with terminal as term:
            nothing = await came_back(term.show(dashboard, line=RUNNING), "a passive show")

            assert nothing is None, (
                f"a passive screen answered with {nothing!r}. A view returning `Screen` promises "
                f"nothing back, and this is the value a workflow carries on from - anything else "
                f"is a lie the annotation cannot catch and the caller has no use for"
            )
            await shown(driver, RUNNING)

    async def test_the_slot_holds_one_screen_and_showing_a_second_replaces_the_first(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """Size one, replace on write. Ordering a dashboard is meaningless, so there is no ordering.

        This is also the slot's half of what identity means on this port. Two `show` calls are two
        registrations - `_terminal_registration` argues that where it bites hardest - and for the
        slot the consequence is the simplest one available: the second is what is on screen, and the
        first is gone rather than queued behind it, waiting, or coming back.

        The assertion that bites is the one after the frames go by. An implementation that kept
        dashboards in a queue would put the second one up and then work its way back to the first,
        and a suite that looked once would not see it; one that treated the second as a new entry
        beside the first would alternate. Neither is a thing `priority` could fix, which is why the
        port says priority has no meaning here rather than forbidding it in a signature that could
        not enforce it.
        """
        async with terminal as term:
            await came_back(term.show(dashboard, line=RUNNING), "the first dashboard")
            await shown(driver, RUNNING)

            await came_back(term.show(dashboard, line=LANDED), "the second dashboard")

            await shown(driver, LANDED)
            await let_frames_pass()
            current = driver.displayed()
            assert current is not None and current.body == Text(LANDED), (
                f"the slot is showing {current!r} some frames after a second dashboard replaced "
                f"the first. The slot has size one and is replaced on write - a terminal that "
                f"queued dashboards would come back to the stale one, and a workflow that re-shows "
                f"a board to change which view is on screen would find the old one returning"
            )

    async def test_the_slot_keeps_updating_while_a_question_is_up_and_is_what_the_queue_ends_at(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """The clause that means no extra machinery: `show` re-registers, the terminal is just not
        drawing it.

        Three things, and they are one mechanism seen from three sides. A passive `show` while a
        question is displayed **still returns at once** - it joins nothing and waits for nobody, so
        a workflow updating its board mid-question is not blocked behind the person who has not
        answered yet. It **does not take the screen**, because the highest-priority screen is always
        the one shown and a dashboard is not in that ordering at all. And when the queue empties,
        what appears is the board as it stood at the last write and not the one that was up when the
        question arrived.

        That last one is the whole of §3.7's "no extra machinery". If the slot went stale under a
        question, a workflow would have to re-`show` its dashboard after every answer to get a
        current one back - which means knowing when a question was dismissed, which is a
        notification this port does not have and should not grow.
        """
        async with terminal as term, Asking(term) as ask:
            await came_back(term.show(dashboard, line=RUNNING), "the board before the question")
            await shown(driver, RUNNING)
            asked = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)

            await came_back(term.show(dashboard, line=LANDED), "the board under the question")

            await let_frames_pass()
            current = driver.displayed()
            assert current is not None and current.body == Text(EARLY), (
                f"showing a dashboard while a question was up put {current!r} on screen. A passive "
                f"screen goes to the slot, which has no place in that ordering: the question is "
                f"what a person is being asked to answer, and a board that pushed it aside takes "
                f"away the thing the run is blocked on"
            )

            await answer(driver, APPROVE)
            await within(asked, "the question, once it was answered")

            await shown(driver, LANDED)
