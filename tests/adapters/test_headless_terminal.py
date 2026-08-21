"""`HeadlessTerminal` against the headless half of the `Terminal` contract, and what that half
cannot see.

The first class is the port in full for a terminal that cannot take input:
`HeadlessTerminalContract` with its single fixture overridden and nothing else touched. Four
headless rules and three lifecycle ones, all seven written at stage 3 against the port's docstrings
and before any implementation of it existed - which is the inversion the build rests on (§1.9), and
the reason nothing below re-asserts any of them. There is no `driver` fixture because there is
nothing to drive: this terminal displays nothing and answers nothing, which the suite argues is the
design rather than a convenience.

What follows are the claims that suite cannot make, in two kinds.

**Two are places the port is genuinely open**, and the tests exist so that the side taken is written
down somewhere a reader can find rather than inferred from behaviour:

  * **Gap 6**, what a headless `pending` lists. "It never queues anything, so only 'no count is
    positive' is asserted." Both readings answer 0 to `pending.get(5, 0)`, so a test here decides
    nothing for anybody else's implementation; it records this one's.
  * **Gap 17**, an interactive `show` outside the context. "Two of this port's rules reach that one
    call - it is outside the context, and it is a `Screen[T]` on a terminal that cannot answer it -
    and nothing says which wins." The suite deliberately does not test it, this implementation does
    *something*, and that something is pinned below as a choice.

**Three are about cost, which is invisible from the port** and is the whole of why this class exists
rather than being a mode of the one that draws. A headless terminal is what runs unattended for
hours, so a per-`show` leak that nobody would notice on a laptop is the deployment's memory profile:

  * **Nothing is retained.** The suite can see only that no count is positive - an implementation
    that raised `UpstreamUnavailable` while quietly keeping the screen would pass it. Here the
    terminal's entire state is compared before and after a workflow loop's worth of boards and a
    hundred refused questions, and weak references say whether a view or its arguments outlived the
    call that passed them.
  * **A view is invoked once and never again.** The discriminator is whether `responses` is empty,
    which cannot be known without invoking the view, so one invocation is owed; a second would be
    pure waste on a terminal that draws nothing, and a loop of them would be waste ten times a
    second.
  * **A passive `show` never suspends.** The suite's gap 9 says it asserts only that one comes back
    inside a deadline, and a terminal that took four seconds passes. A workflow calls this on every
    pass through its loop, so what is pinned here is the mechanical form of "never blocks": the
    coroutine finishes on its first step, without the scheduler being involved at all.

One more is neither: **entering twice is refused**, which the port does not discuss and which
`RichTerminal` decides. It is here because a fake more permissive than the adapter is the drift
§1.9 forbids - the difference would first be visible on the day somebody dropped the `--dry-run`.

The views are this file's own rather than `tests/contracts/_terminal_views.py`'s, as
`test_rich_terminal.py`'s are: reusing them would couple this file to a suite this deliverable may
not edit, and would make a failure here ambiguous between the two.

Named `test_headless_terminal.py` for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import asyncio
import gc
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import pytest

from agl.adapters.rich_terminal.headless import HeadlessTerminal
from agl.ports.errors import InternalError, UpstreamUnavailable
from agl.ports.terminal import Choice, Screen, Terminal, Text, TextInput
from contracts.terminal import HeadlessTerminalContract

# Module-level tests do not inherit the marker the contract classes set on themselves, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is how
# a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

DEADLINE: Final = 10.0
"""How long the one bulk loop below may take before it is called a hang. It is a bound on hanging
and not a speed: a thousand of anything under it is nothing, and a thousand that never finish is the
failure it exists to name."""

SETTLE: Final = 0.5
"""How long a test lets pass before asserting that a view was not invoked again. This terminal has
no frame rate to be compared against - it has no loop at all - so this is simply longer than any
loop would have waited before making its second call."""

BOARDS: Final = 1_000
"""How many dashboards a test shows in a row. A workflow shows its board on every pass through its
loop, so this is an ordinary hour rather than an unfair one."""

QUESTIONS: Final = 100
"""How many questions the same test asks and has refused. Fewer than the boards, because a run asks
a person less often than it redraws - and more than a handful, because what is being asserted is
that a hundred of them accumulate exactly as much as one did."""

APPROVED: Final = "approved"
"""What the `Choice` carries. Nothing here can ever pick it, which is the point: the value exists so
that the screen is a question, and the terminal never gets far enough to compute an answer."""

# The questions and the dashboards. Sentences, because each one ends up in a failure message saying
# what was shown when something else should have been.
EARLY: Final = "the question that was asked first"
LATE: Final = "the question that was asked second"
RUNNING: Final = "two children running"
LANDED: Final = "one child landed, one still running"

# §3.7's two priorities: an agent question and a merge conflict. Two integers that differ, never a
# vocabulary - the port refuses named levels and so does this file.
AGENT: Final = 5
CONFLICT: Final = 10


def dashboard(line: str) -> Screen:
    """A passive screen with one line on it. `Screen` and not `Screen[None]`, which is the spelling
    a workflow author uses and the one PEP 696's default exists for."""
    return Screen(line)


def question(label: str) -> Screen[str]:
    """§3.7's approval screen: a body to read, a choice to pick and a field to type into.

    Both response kinds, because they are the two routes to one `T` - and because the refusal must
    not depend on which of them is offered. What the terminal dispatches on is whether `responses`
    is empty, and a screen offering either kind is not empty.
    """
    return Screen(
        body=Text(label),
        responses=[
            Choice("Approve", value=APPROVED),
            TextInput("Say more", maps=lambda typed: typed),
        ],
    )


class Activity:
    """A workflow object a view reads, and something a weak reference can be taken to.

    A plain class rather than a `dict` or a `str`, for the second reason: the builtins a workflow
    would naturally pass do not support weak references, and the test that asks whether an argument
    outlived the `show` that carried it needs one that does. What it stands for is §3.7's own live
    argument - the thing a view reads again on every invocation.
    """

    def __init__(self, line: str) -> None:
        self.line = line


@dataclass(slots=True)
class Counting[T]:
    """A view wrapped in a count of how many times it was invoked.

    It forwards `**params` rather than naming any, so one wrapper covers a dashboard taking a `line`
    and a question taking a `label` - and so that what the terminal passes is what the view under it
    receives, which is the part a count would otherwise be silent about.
    """

    view: Callable[..., Screen[T]]
    calls: int = 0

    def __call__(self, **params: object) -> Screen[T]:
        self.calls += 1
        return self.view(**params)


@pytest.fixture
def terminal() -> HeadlessTerminal:
    """The adapter the module-level tests drive, built and not yet entered.

    Typed as the implementation rather than as the port, because two tests below read state that is
    this class's own - its slots - which is deliberately nothing the ABC has.
    """
    return HeadlessTerminal()


class TestHeadlessTerminal(HeadlessTerminalContract):
    """The headless half of the port in full: four rules and the lifecycle, and nothing added.

    One override, which is what the suite asks for. There is no `driver` fixture to supply - a
    terminal that cannot take input displays nothing, so `terminal` is the whole of what an
    implementer hands over, and this class is what that claim looks like when it is true.
    """

    @pytest.fixture
    def terminal(self) -> Terminal:
        """The headless terminal, built and not yet entered. It takes no arguments at all."""
        return HeadlessTerminal()


async def test_pending_lists_no_priority_at_all_on_a_terminal_that_refused_every_question(
    terminal: HeadlessTerminal,
) -> None:
    """Gap 6, recorded: this implementation's `pending` is empty, and the port leaves that open.

    The suite asserts only that no count is positive, and says why: "the port says the map reports
    every priority this terminal has been asked for, and a priority it was asked for and then
    refused is exactly the case that sentence does not settle. Both readings leave a workflow's
    `pending.get(5, 0)` answering 0, which is the number that clause exists to make agree, so
    nothing here decides it." **This test is one side of that and not a rule** - another headless
    terminal may list every priority it turned away and be just as right.

    The side taken, and the argument for it: a key here could never become non-zero, so listing one
    would tell a reader that somebody is queued at priority 5 in a map whose whole subject is people
    being kept waiting - `queues.py` refuses the analogous key for a passive `show` in exactly those
    words. And the other reading has this terminal remember something per distinct priority for
    questions it declined at the door, which is the one thing the class below it must not do.

    The last assertion is the reading-independent half, and it is here so that a reader who takes
    the other side can see what does not change: `pending.get(...)` answers 0 either way, which is
    what the port's clause is actually for.
    """
    async with terminal as term:
        assert dict(term.pending) == {}, (
            f"a terminal that has been asked for nothing reports {dict(term.pending)}. Nothing is "
            f"ever queued here, so the map starts empty however it ends up"
        )

        await term.show(dashboard, line=RUNNING)
        await _refused(term, question, priority=AGENT, label=EARLY)
        await _refused(term, question, priority=CONFLICT, label=LATE)

        assert dict(term.pending) == {}, (
            f"two questions were refused and a board dropped, and `pending` reports "
            f"{dict(term.pending)}. This implementation lists a priority it queued something at, "
            f"and it queues nothing - a refused question was never accepted, and a key that can "
            f"never become non-zero is a number a workflow can watch forever"
        )
        assert term.pending.get(AGENT, 0) == 0 and term.pending.get(CONFLICT, 0) == 0, (
            "the count a workflow actually reads changed with the reading. Whether a refused "
            "priority appears is open; that `pending.get(p, 0)` is 0 for every p is not, and it is "
            "the whole of what the port's clause exists to make agree between implementations"
        )


async def test_a_workflow_loops_worth_of_boards_and_refused_questions_leaves_the_terminal_as_it_was(
    terminal: HeadlessTerminal,
) -> None:
    """Nothing accumulates: the terminal's entire state after all that is the state it was entered
    in.

    The suite can see that no count in `pending` is positive, and that is all it can see - "an
    implementation that raised `UpstreamUnavailable` while quietly keeping the screen would say
    otherwise, which is the one thing this can catch". A screen kept somewhere `pending` does not
    report is invisible to it, and so is a list of every priority ever refused, a count of frames
    that never were, and a log of views shown.

    This is the implementation that runs unattended for hours. A dashboard shown ten times a second
    for an afternoon is a hundred thousand calls, so anything retained per `show` is retained a
    hundred thousand times, and the failure would be a run that gets slower and fatter with nothing
    on screen to show for it.

    So the comparison is over everything the object holds - its declared slots and any instance
    dictionary - rather than over a member somebody thought to check. Both halves matter: a
    `Terminal` declares no `__slots__` of its own, so a subclass that declares some still gets a
    `__dict__` beside them, and a terminal accumulating into one would be invisible to a check that
    only read the other.
    """
    async with terminal as term:
        entered = _state(term)

        for round_ in range(QUESTIONS):
            for _ in range(BOARDS // QUESTIONS):
                await term.show(dashboard, line=RUNNING if round_ % 2 else LANDED)
            await _refused(
                term,
                question,
                priority=AGENT if round_ % 2 else CONFLICT,
                label=EARLY if round_ % 2 else LATE,
            )

        assert _state(term) == entered, (
            f"{BOARDS} boards and {QUESTIONS} refused questions left this terminal holding "
            f"{_state(term)}, and it was entered holding {entered}. Nothing here is queued, "
            f"registered, drawn or counted, so a run of any length leaves exactly what a run of "
            f"none does"
        )
        assert dict(term.pending) == {}, (
            f"`pending` reports {dict(term.pending)} after {QUESTIONS} questions were refused. "
            f"Refusing one is not accepting it, and nothing is ever waiting on a person here"
        )


async def test_neither_a_dropped_board_nor_a_refused_question_keeps_hold_of_a_view_or_its_arguments(
    terminal: HeadlessTerminal,
) -> None:
    """The other half of retention, and the half a state comparison cannot reach.

    §3.7's mechanism is that `show` registers the view function **and its arguments** rather than a
    value, which is what lets a live dict of child runs reach a display with no second `show`. The
    terminal that draws holds both for as long as the screen is up, and must. This one draws
    nothing, so holding either is holding it forever: a workflow passing the live `Run` of every
    child would find that the terminal it thought was a no-op is the reason none of them can be
    collected.

    Weak references are how that is asked. Everything is built inside a helper and dropped when it
    returns, so the only references that could survive are the terminal's own - and `gc.collect()`
    is there because the refusal's traceback is part of a cycle, which is a fact about exceptions
    rather than about this terminal (`_refused` says so where it lets the exception die).

    A passive screen and a refused one, because the two paths keep different things: the dropped
    board's view is invoked and its `Screen` discarded, while the question's view is invoked and
    then the arguments are named in an exception message. Either one could have kept a reference,
    and each would look fine while the other was checked.
    """
    async with terminal as term:
        watched = await _shown_and_forgotten(term)
        gc.collect()

        held = sorted(what for what, ref in watched.items() if ref() is not None)
        assert not held, (
            f"this terminal is still holding {held} after the `show` calls that passed them "
            f"returned. It has nothing to draw and nothing queued, so a view or an argument alive "
            f"in here is alive for the rest of the run - and the arguments §3.7 has a workflow "
            f"pass are the live objects of every child it is running"
        )


async def test_a_view_is_invoked_exactly_once_for_each_kind_of_screen_and_never_again_afterwards(
    terminal: HeadlessTerminal,
) -> None:
    """One invocation, because the dispatch needs one; not two, because nothing here draws.

    **The one is owed.** The port says the return annotation says which kind of screen it is and
    that what is dispatched on at run time is whether `responses` is empty - nothing at run time can
    see an annotation, so the view has to be invoked to find out, and that is as true of the
    terminal that drops the screen as of the one that draws it.

    **The second would be waste.** `RichTerminal` invokes a registered view again every frame
    because the diff and the redraw are what make a live argument reach a display; there is no
    display here and no loop, so a second invocation would buy a workflow nothing and cost it a
    function call ten times a second, forever, on the deployment this class exists for. The half of
    this test that sleeps is what would catch a loop somebody added out of symmetry with the
    sibling implementation.

    Both kinds, and the counts are equal on purpose: the refusal happens *after* the invocation
    that classified the screen, so an implementation that guessed from the annotation, or that
    invoked the view a second time to build its error message, would show up as a different number
    on one path than on the other.
    """
    board = Counting(dashboard)
    asked = Counting(question)

    async with terminal as term:
        await term.show(board, line=RUNNING)
        assert board.calls == 1, (
            f"a passive `show` invoked its view {board.calls} times. One is what the dispatch "
            f"costs - a screen with no responses is a dashboard, and nothing but invoking the view "
            f"can say whether it has any"
        )

        await _refused(term, asked, priority=AGENT, label=EARLY)
        assert asked.calls == 1, (
            f"a refused `show` invoked its view {asked.calls} times. The refusal is decided by the "
            f"same single invocation that classified the screen: a second one would mean the "
            f"question was examined twice on the way to being turned away"
        )

        await asyncio.sleep(SETTLE)

        assert (board.calls, asked.calls) == (1, 1), (
            f"a view was invoked again {SETTLE}s after the `show` that passed it returned - the "
            f"counts are now {(board.calls, asked.calls)}. Something in here is looping over a "
            f"registration, and this terminal registers nothing because it draws nothing"
        )


async def test_a_passive_show_finishes_on_its_first_step_and_a_thousand_of_them_cost_nothing(
    terminal: HeadlessTerminal,
) -> None:
    """"Never blocks", in the only form that is mechanical rather than a stopwatch.

    The suite's gap 9 says it cannot do better than a deadline: "It is asserted to come back inside
    the deadline, which is what a suite can see. A terminal that took four seconds passes, and a
    threshold tight enough to catch it would fail an honest implementation on a loaded machine." So
    nothing below is a threshold either. Stepping the coroutine by hand asks the exact question: a
    passive `show` that never suspends finishes on its first `send`, and one that awaits anything at
    all - a lock, a sleep, a queue, a yield to the loop - hands back a value instead.

    That is worth pinning rather than assuming. A workflow shows its board on every pass through its
    own loop, and §3.7's slot "keeps updating while a question is displayed" precisely so that a
    workflow updating its board behind a question it is itself blocked on does not deadlock. A
    headless terminal has no question to be behind, and a `show` that suspended here would still
    make a workflow's progress depend on the scheduler for a call that does nothing.

    The thousand in a row are the same claim at the scale a run makes it, under a deadline that
    bounds a hang and asserts no speed.
    """
    async with terminal as term:
        step = term.show(dashboard, line=RUNNING)
        try:
            step.send(None)
        except StopIteration as finished:
            answered = finished.value
        else:
            step.close()
            raise AssertionError(
                "a passive `show` suspended instead of finishing. There is nothing here to wait "
                "for - no display to take, no queue to join and no lock over any of it - so a "
                "workflow's board update should not be something the event loop has to schedule"
            )

        assert answered is None, (
            f"a passive `show` finished at once and answered {answered!r}. It is dropped, and the "
            f"workflow carries on with exactly what it would have got from a terminal that drew it"
        )

        async with asyncio.timeout(DEADLINE):
            for _ in range(BOARDS):
                await term.show(dashboard, line=RUNNING)


async def test_an_interactive_show_outside_the_context_is_an_internal_error_and_reaches_no_view(
    terminal: HeadlessTerminal,
) -> None:
    """Gap 17, recorded: **the lifecycle rule wins, and this is a choice rather than a rule.**

    The suite says so in as many words: "Two of this port's rules reach that one call - it is
    outside the context, and it is a `Screen[T]` on a terminal that cannot answer it - and nothing
    says which wins. It is asserted for a terminal that can take input, where only one rule applies,
    and for a passive screen on both, where the headless rule and the lifecycle rule do not
    disagree." So the port permits `UpstreamUnavailable` here, and an implementation that raised it
    would not be wrong.

    Three reasons for the side taken. The framework opens the terminal, so a `show` from outside it
    cannot be anything a workflow author wrote, and `InternalError` exits 70, which reads as "file a
    bug" and sends the reader to the right codebase - `UpstreamUnavailable` exits 6 and would send
    them looking for a display that was never the problem on a terminal that was never going to have
    one. It keeps this terminal and `RichTerminal` answering identically for every `show` outside a
    context, which is what the fake owes the adapter. And the check precedes the invocation, so the
    view is not reached at all: the last assertion is that half, and it is the one that would notice
    an implementation which classified the screen first and then decided which rule applied.

    Both sides of "outside", as the lifecycle suite reads it: before entering is the one a test can
    stage, and after leaving is the one that actually happens.
    """
    asked = Counting(question)

    with pytest.raises(InternalError):
        await terminal.show(asked, priority=AGENT, label=EARLY)

    async with terminal as term:
        await _refused(term, asked, priority=AGENT, label=EARLY)

    with pytest.raises(InternalError):
        await terminal.show(asked, priority=CONFLICT, label=LATE)

    assert asked.calls == 1, (
        f"the view was invoked {asked.calls} times across three `show` calls, one of which was "
        f"inside the context. A call from outside is refused before anything is asked of the view: "
        f"the ordering that put it there is already wrong, and a view is workflow code that the "
        f"port only promises to invoke while the terminal is open"
    )


async def test_entering_a_second_time_is_refused_the_way_the_terminal_that_draws_refuses_it(
    terminal: HeadlessTerminal,
) -> None:
    """Parity where the port is silent, which is the rule every fake in this package states.

    The port says nothing about entering twice, and the suite's gap 8 declines even the neighbouring
    question of re-entering after leaving: "The framework opens one, once, and a suite that demanded
    either answer would be inventing a clause." So this is not a rule - it is `RichTerminal`'s
    decision, made here for the reason §1.9 gives.

    `RichTerminal` refuses a second `__aenter__` because it would start a second redraw loop and a
    second reader over the same queues, and the first pair would keep drawing after the terminal was
    handed back. There is nothing here for a second entry to duplicate, and it is refused anyway:
    the framework's ordering bug has to fail on fakes exactly where it fails in anger, or the dry
    run every AGL command is meant to be runnable as would be the one place it passes.

    `InternalError` for the same reason as every other lifecycle refusal on this port: the framework
    opens the terminal, so arriving here twice is ours.
    """
    async with terminal as term:
        with pytest.raises(InternalError):
            await term.__aenter__()

        await term.show(dashboard, line=RUNNING)


async def _refused(
    term: Terminal,
    view: Callable[..., Screen[object]],
    /,
    *,
    priority: int = 0,
    **params: object,
) -> None:
    """Show an interactive screen, require it to be refused, and keep nothing of the refusal.

    The exception is deliberately not bound and never carried out of this frame. Its traceback
    references `show`'s own frame, which holds the view and the arguments it was called with, so a
    test asking whether anything survived a refusal would otherwise be looking at what its own
    `pytest.raises` is holding. That is a fact about tracebacks rather than about this terminal, and
    it is written here once instead of at each of the four callers.

    The signature is `show`'s own, forwarded rather than repackaged: `view` positional-only,
    `priority` a keyword of this function's, and everything else collected. `priority` is named here
    rather than left to `**params` because it is named there - a helper that swallowed it into the
    parameters would pass it to the *view* instead of to the terminal, which is the same collision
    the port already accepts and spells out.
    """
    try:
        await term.show(view, priority=priority, **params)
    except UpstreamUnavailable:
        return
    raise AssertionError(
        f"an interactive screen was shown to a terminal that cannot take input and nothing was "
        f"raised. `UpstreamUnavailable` at the first question is the port's own clause, and the "
        f"alternative is a step blocked forever on nobody: there are no timeouts anywhere here, so "
        f"a question queued on this terminal is a run that looks like work for as long as anybody "
        f"is prepared to wait. The screen was shown with {params!r}"
    )


async def _shown_and_forgotten(term: Terminal) -> dict[str, weakref.ref[Any]]:
    """Show one screen of each kind, then hand back weak references to everything they were made of.

    Everything is built and dropped inside this frame, so that once it returns the only references
    left to any of it are the terminal's own. The views are defined here rather than at module level
    for the same reason: a module-level function is referenced by the module and would be alive
    whatever the terminal did with it.
    """
    board = Activity(RUNNING)
    asked = Activity(EARLY)

    def dropped(activity: Activity) -> Screen:
        return Screen(activity.line)

    def turned_away(activity: Activity) -> Screen[str]:
        return Screen(activity.line, [Choice("Approve", value=APPROVED)])

    await term.show(dropped, activity=board)
    await _refused(term, turned_away, activity=asked)

    return {
        "the argument of the board it dropped": weakref.ref(board),
        "the argument of the question it refused": weakref.ref(asked),
        "the view of the board it dropped": weakref.ref(dropped),
        "the view of the question it refused": weakref.ref(turned_away),
    }


def _state(terminal: HeadlessTerminal) -> dict[str, str]:
    """Everything this terminal is holding, described: its declared slots and any instance
    dictionary beside them.

    Both halves, because `Terminal` declares no `__slots__` of its own - so a subclass that declares
    some gets a `__dict__` anyway, and an implementation accumulating into one would be invisible to
    a check that only read the other. Read off the class rather than typed out here, so that a slot
    added later is compared without anybody remembering to add it.

    **Descriptions and not the values**, which is the difference between this catching an
    accumulation and only appearing to. A terminal that grew a list per `show` would hand back *the
    same list object* on both reads, and a snapshot holding it would then be compared against
    itself and agree - the one failure this exists to name, passing. A `repr` is taken when it is
    taken, so a list that gained a thousand entries between the two reads says so.
    """
    held: dict[str, str] = {
        name: repr(getattr(terminal, name)) for name in HeadlessTerminal.__slots__
    }
    held.update({name: repr(value) for name, value in getattr(terminal, "__dict__", {}).items()})
    return held
