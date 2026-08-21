"""`Screens` on its own: the slot, the queues, `pending`, and who is owed an answer.

Unit tests for `adapters/rich_terminal/queues.py`, and for now they are the only ones there are.
`tests/contracts/terminal.py` is what finally grades this behaviour and it cannot run until 6.2
exists to put a `Terminal` in front of it - so until then every claim §3.7 makes about one slot and
two queues is checked here or checked nowhere. The suite is written on that assumption: it goes at
the arithmetic, at the ordering after preemption, and at the two directions identity could be got
wrong, rather than at the happy path a module's own author already believes in.

**Nothing here is a `Terminal`.** No context manager, no redraw loop, no `rich`, no input. Which
half of `show` a view lands in - the dispatch on an empty `responses` tuple - is 6.2's decision and
so is refusing a call from outside the context, so neither is asserted. What is driven here is the
bookkeeping alone, and driven the way `terminal.py` will drive it: `hold` and `queue` for the two
halves of `show`, `current` and `displayed` for what should be up, `answer` for a person, `pending`
for the port's own property, `close` on the way out.

**The views are this module's own** rather than `tests/contracts/_terminal_views.py`'s. Reusing that
one would couple these tests to a suite this deliverable may not edit, and would make a failure here
ambiguous between the two. They are a dozen lines, and every one takes its data as a parameter
because `show` registers the arguments - two tests below mutate one long after the call.

Named `test_rich_terminal_queues.py` for the module it covers: `tests/` carries no `__init__.py`, so
pytest's module names are the bare filenames and two files of one name would collide at import.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import pytest

from agl.adapters.rich_terminal.queues import Screens
from agl.ports.errors import InternalError, UpstreamUnavailable
from agl.ports.terminal import Choice, Row, Rows, Screen, Text, TextInput

# On the module, and every test here is `async` so that it reaches all of them: `queue` needs a
# running loop to make a future on, and `asyncio_mode = "strict"` turns a missing marker into a test
# pytest quietly skips - which is how a file like this passes against a module it never called.
pytestmark = pytest.mark.asyncio

# §3.7's own two priorities - an agent question and a merge conflict - as two integers that differ.
# Nothing here is a vocabulary: the module compares numbers, and this suite would pass on 1 and 2.
AGENT: Final = 5
CONFLICT: Final = 10

# The two responses `question` offers, in the order it offers them. A driver names a response by
# position, and `answer(0)` in a test body would name nothing a reader can see.
APPROVE: Final = 0
SAY_MORE: Final = 1

APPROVED: Final = "approved"
TYPED: Final = "not yet - land the other one first"

# The questions. Sentences, because each one ends up in a failure message saying which screen was
# current when another should have been.
EARLY: Final = "the question that was asked first"
LATE: Final = "the question that was asked second"
LAST: Final = "the question that was asked third"
URGENT: Final = "the conflict holding the merge queue"

# The dashboards, and §3.7's board.
RUNNING: Final = "two children running"
LANDED: Final = "one child landed, one still running"
TICKET: Final = "T-01"
OTHER: Final = "T-02"
READING: Final = "Read: connectors/api/backend.ts"
EDITING: Final = "Edit: domain/usecase.kt"

# The options `offer` is given, in the tests that grow a view's responses after it was registered.
STANDING: Final = "the option the view was shown with"
GROWN: Final = "the option that arrived after it"


@dataclass(frozen=True, slots=True)
class Answer:
    """What responding to one of these screens produces: the workflow's own type, in shape.

    Frozen, so two built from the same parts compare equal and a test can say *which* answer came
    back rather than only that something did. `asked` is the question it came from, so an answer
    that reached the wrong registration says so instead of being indistinguishable from the right
    one.
    """

    asked: str
    said: str


class Exploded(Exception):
    """What a workflow's own `maps` raises in the one test where it does.

    Not an `AglError`: the point of that test is that a mapping function is workflow code and that
    whatever it raises reaches the `show` call that registered it, unchanged and unclassified.
    """


def dashboard(line: str) -> Screen:
    """A passive screen with one line on it. Empty `responses` is what makes it passive."""
    return Screen(line)


def board(rows: Mapping[str, str]) -> Screen:
    """§3.7's board, over a mapping the caller keeps a reference to and mutates."""
    return Screen(Rows([Row(name, activity) for name, activity in rows.items()]))


def question(label: str) -> Screen[Answer]:
    """§3.7's approval screen: a body to read, a choice to pick, and a field to type into.

    A fresh `maps` lambda on every invocation, and `TextInput.maps` is excluded from comparison, so
    two invocations with the same `label` compare **equal**. That is what makes "two identical
    registrations are still two entries" a claim worth pinning rather than a tautology.
    """
    return Screen(
        Text(label),
        [
            Choice("Approve", value=Answer(label, APPROVED)),
            TextInput("Say more", maps=lambda typed: Answer(label, typed)),
        ],
    )


def offer(label: str, options: Sequence[str]) -> Screen[Answer]:
    """An interactive screen whose *responses* come from a live argument rather than its body."""
    return Screen(Text(label), [Choice(option, value=Answer(label, option)) for option in options])


def _explode(typed: str) -> Answer:
    raise Exploded(typed)


def exploding(label: str) -> Screen[Answer]:
    """A screen whose `maps` raises - a workflow author's bug, reached through a person's answer."""
    return Screen(Text(label), [TextInput("Say more", maps=_explode)])


def ask(screens: Screens, label: str, priority: int = AGENT) -> asyncio.Future[Answer]:
    """Queue `question` and hand back what its `show` call would be waiting on.

    `ensure_future` rather than a task wrapping it: `queue` already returns the future itself, so
    what comes back here is that same object and `done()` on it is exact rather than one loop pass
    behind. Every ordering claim below is made against which of these resolves.
    """
    return asyncio.ensure_future(screens.queue(question, priority=priority, label=label))


async def resolved(waiting: asyncio.Future[Answer], what: str) -> Answer:
    """Take what a registration was answered with, having first said that it was answered at all.

    **Nothing in this file ever waits, and that is deliberate.** `answer` resolves the registration
    that was current before it returns, so a correct module leaves the future done the instant the
    call comes back. A bare `await` on one nothing resolved would hang until pytest was killed, and
    a hanging test reads as a slow one - which is the failure mode the contract suite spends a
    `DEADLINE` constant on. Here the same protection is exact and free: `done()` is false only when
    the answer went somewhere else, which is the thing being asserted anyway.
    """
    assert waiting.done(), (
        f"{what} was never answered. `answer` resolves the registration that was current before it "
        f"returns, so a `show` still waiting here is one whose answer went somewhere else"
    )
    return await waiting


def body_of(screens: Screens) -> object:
    """The body of whatever is displayed, or `None` - what a driver would report, in one call."""
    displayed = screens.displayed
    return None if displayed is None else displayed.screen().body


# --- The slot ---------------------------------------------------------------------------------


async def test_the_slot_is_empty_until_something_is_held() -> None:
    """A terminal that has been shown nothing is showing nothing, and owes nobody an answer."""
    screens = Screens()

    assert screens.slot is None
    assert screens.current is None
    assert screens.displayed is None
    assert dict(screens.pending) == {}


async def test_holding_a_second_view_replaces_the_first_and_the_first_never_comes_back() -> None:
    """Size one, replaced on write. Ordering a dashboard is meaningless, so there is no ordering.

    The second assertion is the one that bites. An implementation that kept dashboards in a queue
    would put the second one up and work its way back to the first, and a test that looked once
    would not see it - so the slot is read again after several frames' worth of invocations, which
    is all a queue behind it would need to surface.
    """
    screens = Screens()

    screens.hold(dashboard, line=RUNNING)
    assert body_of(screens) == Text(RUNNING)

    screens.hold(dashboard, line=LANDED)

    for _ in range(10):
        assert body_of(screens) == Text(LANDED), (
            "the slot came back to a board that had been replaced. It has size one and is replaced "
            "on write: a workflow that re-shows a board to change which view is on screen would "
            "find the old one returning"
        )


async def test_the_slot_is_written_under_a_question_and_is_where_the_queues_end() -> None:
    """§3.7's "no extra machinery", from all three sides at once.

    A passive registration under a question does not take the screen, because a dashboard is not in
    that ordering at all. It is still written. And when the queues empty, what appears is the board
    as it stood at the **last write** - not the one that was up when the question arrived, which is
    the whole difference between a register and a snapshot. If the slot went stale under a question
    a workflow would have to re-`show` its board after every answer, which means knowing when a
    question was dismissed, which is a notification this port does not have.
    """
    screens = Screens()
    screens.hold(dashboard, line=RUNNING)
    owed = ask(screens, EARLY)
    assert body_of(screens) == Text(EARLY)

    screens.hold(dashboard, line=LANDED)

    assert body_of(screens) == Text(EARLY), (
        "a dashboard registered while a question was current took the screen. The question is what "
        "a person is being asked to answer, and a board that pushed it aside takes away the thing "
        "the run is blocked on"
    )
    screens.answer(APPROVE)
    assert await resolved(owed, "the question that was current") == Answer(EARLY, APPROVED)
    assert body_of(screens) == Text(LANDED), (
        "the queues emptied and the board that came back is the one that was up when the question "
        "arrived rather than the one written under it. The slot is a register, not a snapshot"
    )


async def test_a_passive_registration_registers_no_priority_at_all() -> None:
    """The side taken on the suite's gap #5, asserted so that it is a decision and not a drift.

    The port says `pending` reports every priority the terminal has been asked for, and also that
    priority means nothing for a passive screen; both readings are live and `queues.py` argues this
    one. `hold` has no priority parameter, so what this pins is that holding a dashboard - any
    number of them - leaves the map exactly as it was.
    """
    screens = Screens()
    screens.hold(dashboard, line=RUNNING)
    screens.hold(dashboard, line=LANDED)

    assert dict(screens.pending) == {}

    owed = ask(screens, EARLY, priority=AGENT)
    screens.hold(dashboard, line=RUNNING)

    assert dict(screens.pending) == {AGENT: 0}, (
        "a dashboard put a priority into `pending`. The map's whole subject is people being kept "
        "waiting, and a key a dashboard created can never become non-zero"
    )
    screens.answer(APPROVE)
    await resolved(owed, "the question that was current")


async def test_the_slot_registers_the_view_and_its_arguments_rather_than_a_screen() -> None:
    """A live argument reaches the display with no second registration, which is why it is a view.

    Both kinds of change at once - a cell whose value moved, and a row that did not exist when the
    view was registered - because an implementation that re-read the mapping but cached its shape
    would survive the first alone. A `Screen` kept at registration time fails both.
    """
    rows = {TICKET: READING}
    screens = Screens()
    screens.hold(board, rows=rows)
    assert body_of(screens) == Rows([Row(TICKET, READING)])

    rows[TICKET] = EDITING
    rows[OTHER] = ""

    assert body_of(screens) == Rows([Row(TICKET, EDITING), Row(OTHER, "")]), (
        "the board did not follow the mapping it was registered with. `show` registers the "
        "function and its arguments, so the lookup happens again every frame - a terminal holding "
        "the value the view returned once needs a notification this port does not have"
    )


# --- One priority, in the order they arrived ----------------------------------------------------


async def test_a_question_is_current_the_moment_it_is_queued_and_resolves_for_nobody_else() -> None:
    """Displacement is immediate in both directions: it takes the screen at once, and it waits."""
    screens = Screens()
    screens.hold(dashboard, line=RUNNING)

    owed = ask(screens, EARLY)

    assert screens.current is not None
    assert body_of(screens) == Text(EARLY), "a question does not wait for a frame to become current"
    assert not owed.done(), (
        "an interactive registration resolved before anybody answered it. There are no timeouts "
        "anywhere on this port: a question waits for a person, and a terminal that answers on "
        "their behalf makes a workflow's decision on the strength of nothing"
    )

    screens.answer(APPROVE)
    assert await resolved(owed, "the question that was current") == Answer(EARLY, APPROVED)


async def test_questions_at_one_priority_are_current_in_the_order_they_were_asked() -> None:
    """FIFO within a priority, so simultaneous questions from several agents stack and wait.

    Not last-in-first-out, which would leave the agent that asked first waiting longest while its
    siblings are served ahead of it. The loop asserts the whole clause: each reaches the screen in
    turn, and answering it resolves *that* registration and not another.
    """
    screens = Screens()
    owed = [(label, ask(screens, label)) for label in (EARLY, LATE, LAST)]

    for position, (label, waiting) in enumerate(owed):
        assert body_of(screens) == Text(label), (
            f"the question asked {position + 1} of 3 is not the one on screen. FIFO within a "
            f"priority is the whole of what decides whose question is put to a person next"
        )
        screens.answer(APPROVE)
        assert await resolved(waiting, repr(label)) == Answer(label, APPROVED)


async def test_answering_resolves_the_registration_that_was_current_and_no_other() -> None:
    """One answerer, and only the displayed screen can be answered.

    What this rules out is an answer that satisfies every screen that would accept it. Either way
    round, an agent is handed the answer to a question it never asked - and unlike a question still
    waiting, it will act on it.
    """
    screens = Screens()
    early = ask(screens, EARLY)
    late = ask(screens, LATE)

    assert not early.done() and not late.done()

    screens.answer(APPROVE)

    assert await resolved(early, repr(EARLY)) == Answer(EARLY, APPROVED)
    assert not late.done(), (
        "one answer resolved two registrations. The second question has not been in front of "
        "anybody, and nobody has said anything about it"
    )

    assert body_of(screens) == Text(LATE)
    screens.answer(APPROVE)
    assert await resolved(late, repr(LATE)) == Answer(LATE, APPROVED)


# --- Preemption, and what comes back afterwards -------------------------------------------------


async def test_the_highest_priority_takes_the_screen_at_once_and_a_lower_one_does_not_take_it_back(
) -> None:
    """Preemption is not cosmetic and it is not "next in line".

    `integrate()` holds the target lease while a conflict is unresolved, so a conflict queued behind
    two agent questions stalls the merge queue on something unrelated. That is the entire
    justification for one level of it, and it is why the displacement has to happen the moment the
    conflict arrives.

    The other half is the one an implementation can fail while looking right: a lower-priority
    question arriving afterwards does not take the screen back. The highest priority is always the
    current one and there is no fairness rule that would let a lower one interrupt.
    """
    screens = Screens()
    early = ask(screens, EARLY, priority=AGENT)
    late = ask(screens, LATE, priority=AGENT)
    assert body_of(screens) == Text(EARLY)

    urgent = ask(screens, URGENT, priority=CONFLICT)

    assert body_of(screens) == Text(URGENT), (
        "a conflict arrived at a higher priority and the agent question kept the screen. "
        "Displacement is immediate: a conflict that waited its turn would leave the merge queue "
        "behind exactly the thing preemption exists to get it in front of"
    )
    ask(screens, LAST, priority=AGENT)
    assert body_of(screens) == Text(URGENT), (
        "an agent question arrived while a conflict was current and took the screen. The highest "
        "priority is always the current one"
    )
    assert not early.done() and not late.done(), (
        "a question resolved while the conflict was the screen in front of the person"
    )

    screens.answer(APPROVE)
    assert await resolved(urgent, "the conflict") == Answer(URGENT, APPROVED)


async def test_a_displaced_question_keeps_its_place_and_the_fallback_is_the_queue_as_it_was() -> (
    None
):
    """The claim the whole "current is derived" design exists for.

    EARLY is current, LATE queues behind it, URGENT displaces both, LAST arrives at the low priority
    while the conflict is up. Once the conflict is answered the order is EARLY, LATE, LAST: the
    displaced question is not lost, not answered by the gesture that dismissed the conflict, and not
    sent to the back of its own queue behind the one that arrived while it was off screen. It
    arrived first and was never answered, so the fallback is the queue as it always was, minus what
    has been answered since.
    """
    screens = Screens()
    early = ask(screens, EARLY, priority=AGENT)
    late = ask(screens, LATE, priority=AGENT)
    urgent = ask(screens, URGENT, priority=CONFLICT)
    last = ask(screens, LAST, priority=AGENT)

    assert body_of(screens) == Text(URGENT)
    screens.answer(APPROVE)
    assert await resolved(urgent, "the conflict") == Answer(URGENT, APPROVED)

    for label, waiting in ((EARLY, early), (LATE, late), (LAST, last)):
        assert body_of(screens) == Text(label), (
            f"after the conflict was dismissed the terminal did not fall back to {label!r} in its "
            f"turn. A question displaced by a more urgent one keeps its place in its own queue"
        )
        screens.answer(APPROVE)
        assert await resolved(waiting, repr(label)) == Answer(label, APPROVED)

    assert screens.current is None
    assert screens.displayed is None


# --- Identity is the registration, never the screen ---------------------------------------------


async def test_two_identical_registrations_are_two_entries_answered_separately() -> None:
    """Two agents, one question between them, and two answers owed.

    The premise is asserted first, because without it this proves nothing: two independently built
    screens with the same text really are equal, since `Screen` compares by value and
    `TextInput.maps` is excluded from that comparison. So a module keyed on the value cannot tell
    these two calls apart, and this is where that costs something - one `show` returning an answer
    nobody gave it, to an agent's `on_question` handler, which carries it back into a live session.
    """
    assert question(EARLY) == question(EARLY), (
        "two independently built frames of this view do not compare equal, so `Screens` could tell "
        "these two registrations apart by value and this test is not asking what it was written to"
    )
    screens = Screens()
    one = ask(screens, EARLY)
    two = ask(screens, EARLY)

    assert dict(screens.pending) == {AGENT: 1}, (
        f"two registrations were made with the same view and the same arguments, one is "
        f"current, and the queue reports {dict(screens.pending)} rather than one waiting behind "
        f"it. Keyed on the screen's value, two agents' questions have just been merged into one"
    )

    screens.answer(APPROVE)
    assert await resolved(one, "the first of the two identical questions") == Answer(
        EARLY, APPROVED
    )
    assert not two.done(), (
        "one answer resolved both identical registrations. Whoever made the second was handed an "
        "answer to a question that was never put in front of anybody - and it is "
        "indistinguishable, at the call site, from one somebody gave"
    )

    assert body_of(screens) == Text(EARLY)
    screens.answer(APPROVE)
    assert await resolved(two, "the second of the two identical questions") == Answer(
        EARLY, APPROVED
    )


async def test_the_frames_of_one_registration_are_one_entry_however_often_the_view_is_invoked(
) -> None:
    """One question, many frames, one entry, and one answer that ends it.

    A view is re-invoked every frame and each invocation builds a fresh `Screen`. Those are frames
    of one screen. A module that read a fresh value as a fresh registration would grow its queue
    while nobody did anything at all: `pending` would climb on its own, the workflow watching it
    would report a backlog that is really a frame counter, and the person who answered would find
    another question exactly like it underneath.
    """
    screens = Screens()
    owed = ask(screens, EARLY)
    entry = screens.current
    settled = dict(screens.pending)

    for _ in range(20):
        assert screens.displayed is not None
        screens.displayed.screen()

    assert screens.current is entry, (
        "twenty frames of one registration and what is current is a different entry. A `show` call "
        "is one entry however many times its view was invoked"
    )
    assert dict(screens.pending) == settled == {AGENT: 0}, (
        f"the queue went from {settled} to {dict(screens.pending)} with nothing queued and nothing "
        f"answered in between - a module counting its own redraws and calling the total a backlog"
    )

    screens.answer(APPROVE)
    assert await resolved(owed, "the question that was current") == Answer(EARLY, APPROVED)
    assert dict(screens.pending) == {AGENT: 0}, "one answer is the end of one registration"


async def test_an_entry_is_the_registration_and_never_the_screen_its_view_returned() -> None:
    """The sharp half: a response that did not exist when the question was queued can be picked.

    A module holding the `Screen` from registration time has one response here and cannot be told to
    use a second. One that derives the screen from the view and its arguments has two, and answers
    with what the second one carries - which is visible in what the registration resolves to, so
    this needs nothing to report what is displayed.
    """
    options = [STANDING]
    screens = Screens()
    owed = asyncio.ensure_future(
        screens.queue(offer, priority=AGENT, label=EARLY, options=options)
    )
    assert screens.current is not None
    assert len(screens.current.screen().responses) == 1, (
        "the view was registered with one option and the screen already offers more, so this test "
        "cannot tell a grown response from one that was there all along"
    )

    options.append(GROWN)

    assert len(screens.current.screen().responses) == 2, (
        "the responses did not follow the list the view was registered with"
    )
    screens.answer(1)
    assert await resolved(owed, "the question whose responses grew") == Answer(EARLY, GROWN), (
        "the response picked was the one added after the question was queued. A registration is "
        "the function and its arguments - not the value the function returned once"
    )


# --- `pending` ----------------------------------------------------------------------------------


async def test_pending_counts_what_is_waiting_and_excludes_what_is_displayed() -> None:
    """§3.7's `{5: 2, 10: 0}`, built exactly, because the zero is the specification.

    Two clauses at once. What is on screen is excluded - it is displayed, not pending - so the
    conflict at 10 contributes nothing to its own count while a person is looking at it. And every
    priority the terminal has been asked for is reported, including the ones with nothing waiting.

    The state is §3.7's own: two agent questions waiting, one of which was displaced rather than
    never shown, and a conflict displayed with nothing behind it.
    """
    screens = Screens()
    early = ask(screens, EARLY, priority=AGENT)
    late = ask(screens, LATE, priority=AGENT)
    urgent = ask(screens, URGENT, priority=CONFLICT)

    assert dict(screens.pending) == {AGENT: 2, CONFLICT: 0}, (
        f"two agent questions are waiting behind a displayed conflict and `pending` reports "
        f"{dict(screens.pending)}. The displaced question is waiting again, the one queued behind "
        f"it never stopped, and the conflict is on screen - which is displayed and so counts as "
        f"nothing"
    )

    screens.answer(APPROVE)
    await resolved(urgent, "the conflict")
    for waiting in (early, late):
        screens.answer(APPROVE)
        await resolved(waiting, "one of the two agent questions")

    assert dict(screens.pending) == {AGENT: 0, CONFLICT: 0}, (
        f"every question has been answered and `pending` reports {dict(screens.pending)}. A "
        f"priority this terminal has been asked for stays in the map at zero: a workflow that read "
        f"a number there while the queue was busy has to keep reading the same key to watch it "
        f"empty, and a key that vanishes makes that a different answer on a different terminal"
    )


async def test_pending_counts_one_waiting_behind_one_displayed_at_the_same_priority() -> None:
    """The single-priority arithmetic, both states, and the second is the one worth having.

    One question displayed with nothing behind it is `{5: 0}` and not `{5: 1}` - the subtraction is
    the port's own "excluding whatever is on screen" - and a module that forgot it would report a
    backlog of one to a workflow whose only question is in front of a person right now.
    """
    screens = Screens()
    early = ask(screens, EARLY)
    assert dict(screens.pending) == {AGENT: 0}

    late = ask(screens, LATE)
    assert dict(screens.pending) == {AGENT: 1}

    screens.answer(APPROVE)
    await resolved(early, repr(EARLY))
    assert dict(screens.pending) == {AGENT: 0}

    screens.answer(APPROVE)
    await resolved(late, repr(LATE))
    assert dict(screens.pending) == {AGENT: 0}, (
        "the queue emptied and the priority it emptied at stopped being reported"
    )


async def test_pending_is_a_fresh_mapping_and_the_one_already_taken_does_not_move() -> None:
    """A read of current state, and the mapping it hands back does not change afterwards.

    The consumer is what makes this matter: a view is invoked again every frame, so a workflow that
    put `term.pending` into a dashboard is reading it ten times a second, and a live view of the
    queue is something that mutates underneath a comprehension half-way through building a row.

    A module returning its own dictionary fails the first half; one that cached the map and kept
    handing back the same object fails the second. A `MappingProxyType` over the live dictionary
    fails the first while looking like it addressed it, which is why the write is checked too: a
    read-only view of something that moves is still something that moves.
    """
    screens = Screens()
    early = ask(screens, EARLY)
    late = ask(screens, LATE)

    before = screens.pending
    taken = dict(before)
    assert taken == {AGENT: 1}

    assert screens.pending is not before, (
        "two reads handed back the same object, so one of them is stale by construction"
    )
    with pytest.raises(TypeError):
        before[AGENT] = 99  # type: ignore[index]

    screens.answer(APPROVE)
    await resolved(early, repr(EARLY))

    assert dict(before) == taken, (
        f"the mapping `pending` handed back said {taken} and now says {dict(before)}. It is a "
        f"snapshot: a workflow that read it into a view is holding it while it builds a row"
    )
    assert dict(screens.pending) == {AGENT: 0}, (
        "reading `pending` again after an answer did not show the queue move. Reading it again is "
        "the only way anything sees it move, so a snapshot that is also stale is a number nobody "
        "can act on"
    )

    screens.answer(APPROVE)
    await resolved(late, repr(LATE))


# --- Answers reach the workflow's own type ------------------------------------------------------


async def test_a_choice_answers_with_the_value_it_carries() -> None:
    """`Choice.value` *is* the answer - no key, no id, no index beside it.

    So a terminal that carried anything else would be carrying something the workflow has no name
    for.
    """
    screens = Screens()
    owed = ask(screens, EARLY)

    screens.answer(APPROVE)

    assert await resolved(owed, "the question that was current") == Answer(EARLY, APPROVED)


async def test_a_typed_answer_reaches_the_workflow_through_the_screens_own_maps() -> None:
    """The terminal collects a string, hands it over, and never learns what an `Answer` is.

    A terminal that returned the typed string itself would typecheck at its own boundary - the
    `cast` `queue` already needs would swallow it - and would hand a workflow a `str` where it was
    promised its own type, failing wherever that value was next used rather than here. Same screen
    as the test above, answered the other way, because the two routes to one `T` are two answers to
    one screen and not two screens that happen to differ.
    """
    screens = Screens()
    owed = ask(screens, EARLY)

    screens.answer(SAY_MORE, TYPED)

    assert await resolved(owed, "the question typed into") == Answer(EARLY, TYPED), (
        "what was typed is turned into the workflow's type by the screen's own `maps`. A terminal "
        "answering with the raw string, with the label beside the field, or with anything it built "
        "itself has taken over a mapping that belongs to the workflow"
    )


async def test_a_maps_that_raises_fails_the_registration_it_belongs_to_and_not_the_terminal(
) -> None:
    """A workflow author's bug, delivered where it was written rather than where it was noticed.

    `maps` is workflow code called by the terminal on a person's keystroke. Letting it escape would
    kill whichever task delivered that keystroke, leaving a person looking at a terminal that no
    longer answers and a workflow blocked forever on a future nobody will resolve. So it arrives at
    the `show` call that registered it, as the exception it was, and the question is retired: the
    terminal carries on with whatever is behind it.
    """
    screens = Screens()
    doomed = asyncio.ensure_future(screens.queue(exploding, priority=AGENT, label=EARLY))
    behind = ask(screens, LATE)

    screens.answer(0, TYPED)

    with pytest.raises(Exploded):
        await resolved(doomed, "the question whose mapping raised")
    assert body_of(screens) == Text(LATE), (
        "a question whose mapping raised stayed on screen. It has been answered as far as the "
        "person is concerned, and leaving it current would put them in front of a screen that "
        "cannot be got rid of"
    )
    assert dict(screens.pending) == {AGENT: 0}

    screens.answer(APPROVE)
    assert await resolved(behind, repr(LATE)) == Answer(LATE, APPROVED)


async def test_answering_when_nothing_is_being_asked_is_agls_own_ordering_bug() -> None:
    """`InternalError`, and both shapes of "nothing": an empty terminal, and a dashboard.

    The second is the one that happens. A dashboard is displayed and cannot be answered, so an
    answer arriving against one is the terminal having decided a keystroke meant something it
    could not have meant - which is our ordering, not a workflow author's, and 70 sends the reader
    to the right codebase.
    """
    screens = Screens()

    with pytest.raises(InternalError):
        screens.answer(APPROVE)

    screens.hold(dashboard, line=RUNNING)
    assert screens.displayed is not None and screens.current is None

    with pytest.raises(InternalError):
        screens.answer(APPROVE)


async def test_answering_a_position_no_response_occupies_leaves_the_question_where_it_was() -> None:
    """The other `InternalError`, and the question is untouched by it.

    A response is named by its position in the order the view offered them, and the only thing that
    names one is the terminal drawing that same screen - so an impossible position is our bug. What
    matters as much is that it costs nothing: the question is still current, still owed an answer,
    and still answerable by a position that exists.
    """
    screens = Screens()
    owed = ask(screens, EARLY)

    for impossible in (-1, 2, 99):
        with pytest.raises(InternalError):
            screens.answer(impossible)

    assert body_of(screens) == Text(EARLY)
    assert not owed.done(), "a refused answer resolved the question it could not answer"
    assert dict(screens.pending) == {AGENT: 0}

    screens.answer(APPROVE)
    assert await resolved(owed, "the question that was current") == Answer(EARLY, APPROVED)


# --- Shutting down, and questions nobody is waiting for any more ---------------------------------


async def test_closing_unblocks_every_waiter_and_leaves_nothing_displayed() -> None:
    """A question outstanding at shutdown can never be answered, so it fails rather than blocks.

    With no timeouts anywhere on this port, a waiter left behind is a workflow hanging on a terminal
    that no longer exists. `UpstreamUnavailable` is the class the port already names for "this needs
    a person and there is not one", which is exactly what a shut-down terminal leaves a question in.
    """
    screens = Screens()
    early = ask(screens, EARLY, priority=AGENT)
    late = ask(screens, LATE, priority=AGENT)
    urgent = ask(screens, URGENT, priority=CONFLICT)
    screens.hold(dashboard, line=RUNNING)

    screens.close()

    for waiting in (early, late, urgent):
        with pytest.raises(UpstreamUnavailable):
            await resolved(waiting, "a question outstanding at shutdown")
    assert screens.current is None
    assert screens.displayed is None, "the slot outlived the terminal that was drawing it"
    assert dict(screens.pending) == {AGENT: 0, CONFLICT: 0}, (
        f"closing reported {dict(screens.pending)}. Nothing is waiting on a person any more, and a "
        f"priority that was asked for is not un-asked by shutting down"
    )


async def test_an_abandoned_question_leaves_its_queue_and_the_next_one_takes_the_screen() -> None:
    """A `show` whose caller was cancelled is owed nothing, and must not hold the screen.

    The port settles nothing about a cancelled `show`, and this decides only the part that would
    otherwise be a hang: an entry nobody is waiting for, left at the head of the highest queue,
    would be current forever, would be counted by `pending` forever, and the questions behind it
    would never reach a person.
    """
    screens = Screens()
    early = ask(screens, EARLY)
    late = ask(screens, LATE)
    assert body_of(screens) == Text(EARLY)

    early.cancel()
    await asyncio.sleep(0)

    with pytest.raises(asyncio.CancelledError):
        await resolved(early, "the question whose caller was cancelled")
    assert body_of(screens) == Text(LATE), (
        "the question whose caller went away is still holding the screen, and the one behind it "
        "will never reach a person"
    )
    assert dict(screens.pending) == {AGENT: 0}

    screens.answer(APPROVE)
    assert await resolved(late, repr(LATE)) == Answer(LATE, APPROVED)
