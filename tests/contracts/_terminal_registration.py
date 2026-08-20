"""What a `show` call registers, what a frame of it is, and why two identical calls are still two.

Split out of `terminal.py` because these four tests are one idea seen from four sides, and because
the idea is the one thing this port leaves genuinely open. **Identity is the `show` registration and
never the `Screen` value.**

The port's own types are the argument. `Screen` is a frozen dataclass with value equality and
`TextInput.maps` is explicitly excluded from that equality, so two independently built questions
with the same text compare equal - and they must, or a redraw loop's diff would report a change
every frame and rewrite the screen ten times a second for as long as somebody was typing into it.
That equality is load-bearing, and it forces the reading in both directions:

* **The frames of one registration are one screen.** A view is invoked again every frame and returns
  a fresh `Screen` each time; if a fresh value were a fresh screen, a single question would enqueue
  a new entry ten times a second and `pending` would count the frame rate.
* **Two `show` calls are two entries even when nothing tells their screens apart.** If identity were
  the value, two agents asking the same question at the same moment would collapse into one entry,
  and one of them would receive an answer to a question it never asked - silently, and with the
  agent then acting on it. `show` returns the answer to *its* caller, so every call must get its
  own. Showing the same text to a person twice is the lesser evil by a wide margin.

## What these tests can and cannot say about per-frame re-invocation

They pin the registration and never a schedule. That `show` keeps the function and its arguments is
observable - a live argument mutated after the call reaches the screen with no second `show`, and a
response that did not exist when the view was registered can be picked - and that is what a workflow
depends on when it passes the live dict of child runs.

**No frame rate is encoded anywhere**, and none should be: §3.7's ~10 Hz is an implementation's
choice and a terminal that redraws once a second is not breaking a promise. Every wait below is a
deadline on hanging. The cost is stated in `terminal.py`'s gaps: an implementation that derives the
screen from the registration only when somebody asks what is displayed passes these tests, because
from outside it is indistinguishable from one that derives it on a timer.

`TerminalContract` in `terminal.py` inherits this class. Implementers subclass that one, never this
one, and the `terminal` and `driver` fixtures these tests take are declared there and in
`_terminal_lifecycle`.
"""

from typing import Final

import pytest

from agl.ports.terminal import Row, Rows, Terminal, Text

from ._terminal_driver import (
    Asking,
    TerminalDriver,
    answer,
    came_back,
    let_frames_pass,
    shown,
    until,
    within,
)
from ._terminal_views import (
    AGENT,
    APPROVE,
    APPROVED,
    EARLY,
    EDITING,
    GROWN,
    OTHER,
    READING,
    STANDING,
    TICKET,
    Approval,
    board,
    offer,
    question,
)

# The response `offer` grows: the view is registered offering one, and this is the second.
_GROWN_RESPONSE: Final = 1

# What a ticket with no run behind it yet shows in its activity cell. `Text`'s own docstring calls
# an empty label ordinary, and §3.7's board writes exactly this.
_NOTHING_YET: Final = ""


class TerminalRegistrationContract:
    """A registration, its frames, two of them at once, and two arguments that move underneath.

    `pytestmark` is repeated on every contract class in this package rather than inherited from one
    of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test, which is
    the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_the_frames_of_one_registration_are_one_screen_and_never_an_entry_each(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """One question, many frames, one entry, and one answer that ends it.

        A view is re-invoked every frame and each invocation builds a fresh `Screen`. Those are
        frames of one screen. An implementation that read a fresh value as a fresh registration
        would grow its queue while nobody did anything at all - `pending` would climb on its own,
        the workflow watching it would report a backlog that is really a frame counter, and the
        person who answered the question would find another one exactly like it underneath.

        Asserted through `pending` rather than through the driver, because `pending` is the port's
        own count and is the number a workflow reads. The queue is empty at that priority with the
        question displayed - what is on screen is displayed, not pending - and it is still empty
        after frames have gone by, and still empty after one answer ended the whole thing.
        """
        async with terminal as term, Asking(term) as ask:
            asked = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)
            settled = dict(term.pending)

            await let_frames_pass()

            assert dict(term.pending) == settled, (
                f"the queue went from {settled} to {dict(term.pending)} with nothing shown and "
                f"nothing answered in between. Every frame invokes the view again and builds a "
                f"fresh Screen, and those are frames of one screen: an implementation that "
                f"enqueued each of them counts its own redraws and calls the total a backlog"
            )
            assert dict(term.pending) == {AGENT: 0}, (
                f"one question is displayed at priority {AGENT} and nothing is behind it, so the "
                f"count there is zero - what is on screen is displayed, not pending"
            )

            await answer(driver, APPROVE)
            assert await within(asked, "the one question that was asked") == Approval(
                label=EARLY, said=APPROVED
            )

            await let_frames_pass()
            assert dict(term.pending) == {AGENT: 0}, (
                f"one answer left {dict(term.pending)} behind. A single show call is a single "
                f"entry however many times its view was invoked, so answering it once is the end "
                f"of it"
            )

    async def test_two_identical_show_calls_are_two_entries_and_each_is_answered_separately(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """Two agents, one question between them, and two answers owed.

        The premise is asserted first, because without it this test proves nothing: two
        independently built screens with the same text really are equal, since `Screen` compares by
        value and `TextInput.maps` is excluded from that comparison. So an implementation keyed on
        the value cannot tell these two calls apart, and this is the test where that costs
        something.

        What it costs: one `show` call would return an answer nobody gave it. The workflow that made
        the second call is an agent's `on_question` handler, and it would carry that answer back
        into a live session and act on it. The port hands the answer to the caller, so every caller
        needs one of its own - and the alternative reading buys nothing except not showing a person
        the same sentence twice.

        `pending` is the first witness and the second `show` call is the decisive one. One entry
        waiting behind the displayed screen means two registrations exist; a `two` that resolves off
        the first answer, or never resolves at all, means they were folded into one.
        """
        async with terminal as term, Asking(term) as ask:
            assert question(EARLY) == question(EARLY), (
                "two independently built frames of this view do not compare equal, so an "
                "implementation could tell these two show calls apart by value and this test is "
                "not asking it the question it was written to ask"
            )
            one = ask(question, priority=AGENT, label=EARLY)
            await shown(driver, EARLY)
            two = ask(question, priority=AGENT, label=EARLY)

            await let_frames_pass()
            assert dict(term.pending) == {AGENT: 1}, (
                f"two show calls were made with the same view and the same arguments, one of them "
                f"is displayed, and the queue reports {dict(term.pending)} rather than one waiting "
                f"behind it. Two calls are two entries: an implementation keyed on the screen's "
                f"value has just merged two agents' questions into one"
            )

            await answer(driver, APPROVE)
            assert await within(one, "the first of the two identical questions") == Approval(
                label=EARLY, said=APPROVED
            )

            await let_frames_pass()
            assert not two.done(), (
                "one answer resolved both identical show calls. Whoever made the second one was "
                "handed an answer to a question that was never put in front of anybody - and it "
                "is indistinguishable, at the call site, from an answer somebody gave"
            )

            await shown(driver, EARLY)
            await answer(driver, APPROVE)
            assert await within(two, "the second of the two identical questions") == Approval(
                label=EARLY, said=APPROVED
            ), "the second registration reached the screen in its turn and was answered in its turn"

    async def test_a_live_argument_reaches_the_slot_without_the_workflow_showing_anything_again(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """§3.7's board, mutated in place: this is why arguments need not be values.

        `show` registers the view **and its arguments**, so passing the live dict of child runs
        works - the lookup is evaluated again each time the view is invoked, and mutating something
        in place shows up for the same reason. A workflow re-`show`s only to change *which* view is
        on screen, and this is the clause that lets it: no notification, no observable wrapper, no
        dirty flag pushed into data the workflow owns.

        A terminal that kept the `Screen` the view returned at registration time passes every other
        test in this suite and fails this one, which is the whole reason it is written. Both kinds
        of change are made at once - a cell whose value moved, and a row that did not exist when the
        view was shown - because an implementation that re-read the mapping but cached its shape
        would survive the first alone.
        """
        rows = {TICKET: READING}
        async with terminal as term:
            await came_back(term.show(board, rows=rows), "the board")
            await shown(driver, Rows([Row(TICKET, READING)]))

            rows[TICKET] = EDITING
            rows[OTHER] = _NOTHING_YET

            await shown(driver, Rows([Row(TICKET, EDITING), Row(OTHER, _NOTHING_YET)]))

    async def test_a_view_offers_the_response_its_live_argument_grew_after_it_was_shown(
        self, terminal: Terminal, driver: TerminalDriver
    ) -> None:
        """The same clause where the driver reports nothing: the answer itself is the witness.

        The board test above asks the driver what is on screen. This one does not need to: the
        response being picked did not exist when the view was registered, so a terminal holding the
        `Screen` from that moment has one response and cannot be told to use a second - and a
        terminal that derives the screen from the view and its arguments has two, and answers with
        what the second one carries. What `show` returns is the assertion, and that is the port's
        own surface.

        The waiting in the middle is synchronisation and not a claim: it says only that the screen
        offering two responses is up before one of them is picked, which is what a person would
        have to see too.
        """
        options = [STANDING]
        async with terminal as term, Asking(term) as ask:
            asked = ask(offer, label=EARLY, options=options)
            registered = await shown(driver, EARLY)
            assert len(registered.responses) == 1, (
                f"the view was shown with one option and the screen offers "
                f"{len(registered.responses)}, so this test cannot tell a grown response from one "
                f"that was there all along"
            )

            options.append(GROWN)

            grown = await until(
                driver,
                lambda screen: len(screen.responses) == 2,
                "a screen offering the response its argument grew",
            )
            assert grown.body == Text(EARLY), "the same screen, with one more way to answer it"

            await answer(driver, _GROWN_RESPONSE)

            picked = await within(asked, "the question, once its new response was picked")

            assert picked == Approval(label=EARLY, said=GROWN), (
                f"the response picked was the one added after `show` was called, and the answer "
                f"came back as {picked!r}. `show` registers the function and its arguments - not "
                f"the value the function returned once - so what a person is offered is what the "
                f"view says now"
            )
