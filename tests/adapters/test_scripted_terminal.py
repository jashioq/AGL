"""`ScriptedTerminal` against the input-capable `Terminal` contract, plus what a script adds to it.

The first class is the port in full for a terminal that can take input: `TerminalContract` with its
two fixtures overridden and nothing else touched - the same eighteen tests `RichTerminal` runs, over
the same slot and the same two queues, because this terminal reuses `queues.Screens` rather than
reimplementing it. That is the price this deliverable set itself and it is the reason it is a
surface change rather than a fixture: `headless.py` argues that a terminal outside that suite agrees
with nothing, and a terminal AGL hands to strangers to test their workflows on is the last one that
may be a mock.

**The driver here is written by the party it exists to catch**, which `_terminal_driver` says of
itself in those words. What is done about it: `displayed()` is `ScriptedTerminal.displayed()`
unaltered, which derives the screen from the registration the queues hold rather than from anything
the terminal remembers separately, and `respond` is the same member a script is spent through - so
the suite drives the object exactly where a workflow author drives it, and there is no second path
that could be right while the first was wrong.

What follows are the claims that suite cannot make, all of them about the script, which is the one
thing this terminal has that the port does not know about:

  * **A script is spent in order, and a bare `int` is the press at that position.** The suite names
    a response through the driver and never through a constructor, so the coercion rule and the
    order of the list are visible only from here.
  * **A question with nothing left to answer it waits.** The documented trap, pinned so that it is a
    decision rather than an accident: it is what lets the contract suite build this terminal with an
    empty script and show a question before any response exists, and it is why a test whose script
    ran out hangs rather than failing.
  * **A gesture that arrives before the question waits in the script for it.** `respond` appends and
    drains rather than answering directly, so an early gesture and a scripted one are one mechanism
    with one set of rules.
  * **The board is readable behind a question.** The slot keeps being written while a question is
    displayed, and `slot()` is how a test asserts that without answering the question first - which
    would change the state it was asking about.
  * **What the script has left outlives the terminal**, and a question still waiting when it closes
    is failed rather than left blocked. Both are about the end of a test rather than the middle of
    one, which is where this class's own failure mode lives.
  * **The spelling a workflow author writes reaches this class**, through `agl.testing.answering`
    and `config/container.py`, and lands in both views of the bundle.

The views are this file's own rather than `tests/contracts/_terminal_views.py`'s, as
`test_rich_terminal.py`'s and `test_headless_terminal.py`'s are: reusing them would couple this file
to a suite this deliverable may not edit, and would make a failure here ambiguous between the two.

Named `test_scripted_terminal.py` for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import asyncio
from pathlib import Path
from typing import Final
import pytest
from agl import testing
from agl.adapters.rich_terminal.scripted import Press, ScriptedTerminal
from agl.ports.errors import UpstreamUnavailable
from agl.ports.terminal import Choice, Screen, Terminal, Text, TextInput
from contracts.terminal import TerminalContract, TerminalDriver

# Module-level tests do not inherit the marker the contract classes set on themselves, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is how
# a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

DEADLINE: Final = 10.0
"""How long anything here waits before calling it a hang. Every wait in this file bounds one, and
none of them asserts a speed - this terminal has no frame rate, and nothing here invents one."""

TICK: Final = 0.005
"""How often `displayed()` is read while waiting. Small enough to be invisible, large enough that a
test is not spinning the event loop flat out."""

SETTLE: Final = 0.5
"""How long a test lets the loop run before asserting that nothing happened - that a question with
no gesture behind it is still waiting. Being too short costs sensitivity and can never fail an
honest implementation, since every assertion made after it says "and nothing had changed"."""

# The two responses `question` offers, in the order it offers them. A press names one by position,
# and a `Press(0)` in a test body would name nothing a reader can see.
APPROVE: Final = 0
SAY_MORE: Final = 1

APPROVED: Final = "approved"
"""What the `Choice` carries, half of the answer it produces - the other half is which question it
came from, so an answer that reached the wrong `show` call says so."""

TYPED: Final = "not yet - land the other one first"
"""What a script types into the `TextInput`. It reaches the workflow through the screen's own
`maps`, which is the terminal's job on this port and not the script's."""

# The questions and the dashboards. Sentences, because each one ends up in a failure message saying
# what was on screen when something else should have been.
EARLY: Final = "the question that was asked first"
LATE: Final = "the question that was asked second"
RUNNING: Final = "two children running"
LANDED: Final = "one child landed, one still running"

AGENT: Final = 5
"""The agent-question priority. One integer, never a vocabulary: the port refuses named levels
and so does this file."""

def dashboard(line: str) -> Screen:
    """A passive screen with one line on it. `Screen` and not `Screen[None]`, which is the spelling
    a workflow author uses and the one PEP 696's default exists for."""
    return Screen(line)

def question(label: str) -> Screen[str]:
    """An approval screen: a body to read, a choice to pick and a field to type into.

    Both response kinds, because they are the two routes to one `T` and a script must reach either.
    The answer carries `label`, so a test can say *which* `show` call was answered rather than only
    that something was - which is the whole of what these tests are about once more than one
    question exists.
    """
    return Screen(
        body=Text(label),
        responses=[
            Choice("Approve", value=f"{label}: {APPROVED}"),
            TextInput("Say more", maps=lambda typed: f"{label}: {typed}"),
        ],
    )

class Gestures(TerminalDriver):
    """The person, played by the suite: two members over the terminal's own two.

    It derives nothing and holds nothing. `displayed()` forwards to the terminal's, which invokes
    the registered view at the moment of the call, and `respond` forwards to the member a
    constructor script is spent through - so the suite exercises the same path a workflow author's
    list does, and neither can be right while the other is wrong.
    """

    def __init__(self, terminal: ScriptedTerminal) -> None:
        self._terminal = terminal

    def displayed(self) -> Screen[object] | None:
        """What a person would be looking at now, straight from the terminal."""
        return self._terminal.displayed()

    async def respond(self, response: int, typed: str = "") -> None:
        """One gesture at the displayed screen. `async` because the port's driver is; nothing here
        awaits, because appending a press and spending it is the whole of what a gesture costs."""
        self._terminal.respond(response, typed)

@pytest.fixture
def terminal() -> ScriptedTerminal:
    """The terminal the module-level tests drive, with an **empty** script, built and not entered.

    Empty because the tests that take this fixture are the ones about a script running out and about
    a gesture arriving from `respond`; the tests about a written script build their own, since the
    script is what those are asserting and a fixture would put it a screen away from the assertion.

    Typed as the implementation rather than as the port, because every test below reads something
    the ABC deliberately does not have.
    """
    return ScriptedTerminal()

class TestScriptedTerminal(TerminalContract):
    """The input-capable half of the port in full, and nothing added.

    Two overrides, which is what the suite asks for, and the driver depends on the `terminal`
    fixture so that it is over the same object - the thing the suite names as something it cannot
    check from inside.
    """

    @pytest.fixture
    def terminal(self) -> Terminal:
        """The terminal, with no script at all, built and not yet entered.

        Empty on purpose and not as a shortcut: the suite queues questions before anything answers
        them and drives every one through `driver.respond`, so a terminal that arrived with
        responses in it would answer the first question before the suite had looked at it - and half
        of that suite is assertions that a question *stayed* queued.
        """
        return ScriptedTerminal()

    @pytest.fixture
    def driver(self, terminal: ScriptedTerminal) -> TerminalDriver:
        """The person, over that same terminal."""
        return Gestures(terminal)

async def test_a_script_is_spent_in_order_and_a_bare_int_is_the_press_at_that_position() -> None:
    """The two things about a list of gestures that no driver can show: the order, and the coercion.

    The suite names a response through `respond` one at a time, so a script written before the run
    is invisible to it. Both halves of that are asserted here against one terminal. **Order**: the
    first gesture answers the first question and the second answers the second, and `remaining`
    shrinks by one each time, which is what "spent in order" means when the answers themselves could
    be produced by any number of orderings. **Coercion**: `0` and `Press(0)` are the same gesture,
    which is `ports/terminal.py`'s own rule one vocabulary over - a bare `str` is a `Text` there, a
    bare `int` is a `Press` here - and it is applied on the way in, which is why `remaining` reports
    a `Press` for a list that was written with an integer in it.

    The typed gesture is here rather than in a test of its own because it is the same claim: what
    reaches the workflow is `maps(typed)`, the screen's own function, and a script that carried a
    finished value would be answering its own question.
    """
    async with ScriptedTerminal([APPROVE, Press(SAY_MORE, TYPED)]) as term:
        written = term.remaining
        assert written == (Press(APPROVE), Press(SAY_MORE, TYPED)), (
            f"the script reads {written!r} before anything was shown. A bare int is the press at "
            f"that position, coerced on the way in, so what is stored is a Press whatever was "
            f"written"
        )

        first = await term.show(question, priority=AGENT, label=EARLY)

        assert first == f"{EARLY}: {APPROVED}", (
            f"the first question was answered with {first!r}. The first gesture in the script "
            f"picks the response at position {APPROVE}, and `Choice.value` *is* the answer - a "
            f"terminal that carried anything else has dropped the only thing the workflow can use"
        )
        left = term.remaining
        assert left == (Press(SAY_MORE, TYPED),), (
            f"one question was answered and the script has {left!r} left. A gesture is spent once: "
            f"a script that kept it would answer every later question the same way, and one that "
            f"dropped two would run out early and hang"
        )

        second = await term.show(question, priority=AGENT, label=LATE)

        assert second == f"{LATE}: {TYPED}", (
            f"the second question was answered with {second!r}. The second gesture types into the "
            f"field, and what a field produces is `maps(typed)` - the workflow's own function at "
            f"the workflow's layer, which this terminal calls and never looks inside"
        )
        assert not term.remaining, (
            f"the script still holds {term.remaining!r} after both of its gestures were spent"
        )

async def test_a_question_with_nothing_left_in_the_script_waits_instead_of_failing(
    terminal: ScriptedTerminal,
) -> None:
    """The trap, pinned as a decision: an exhausted script idles, and idling is what a person does.

    There are no timeouts anywhere on this port, so a question nobody answers blocks its step
    indefinitely - and a terminal with nobody at it is exactly the state a script that ran out
    leaves. Raising instead was the alternative and it loses on where the failure would land: inside
    `show`, at the workflow's own call site, as an exception a retry loop's `except Exception` would
    swallow, after which the run carries on having been told a person refused something they were
    never asked.

    It is also what makes the contract suite runnable over this class at all. That suite builds the
    terminal with no script and shows a question before any response exists, then drives it through
    `respond`; a terminal that refused an unscripted question would fail every interactive test in
    it at the door.

    The cost is stated where an author will meet it: a test whose script runs out hangs rather than
    fails. This is the test that says the hang is on purpose.
    """
    async with terminal as term:
        asked = asyncio.create_task(term.show(question, priority=AGENT, label=EARLY))
        await _displaying(term, EARLY)

        await asyncio.sleep(SETTLE)

        assert not asked.done(), (
            "a question was shown to a terminal with an empty script and the show call came back "
            "anyway. There is nothing here that could have answered it: a terminal that returned "
            "early would hand a workflow an answer no gesture gave, which is worse than a test "
            "that hangs because the run would carry on and act on it"
        )

        term.respond(APPROVE)

        assert await asyncio.wait_for(asked, DEADLINE) == f"{EARLY}: {APPROVED}", (
            "the question that waited was answered by the first gesture to arrive after it, which "
            "is the whole of what waiting is for"
        )

async def test_a_gesture_that_arrives_before_the_question_waits_in_the_script_for_it(
    terminal: ScriptedTerminal,
) -> None:
    """`respond` appends and spends; it does not answer. One mechanism, so one set of rules.

    The alternative was a `respond` that reached the displayed screen directly and refused when
    there was none - and it would have made an early gesture and a scripted one two different
    things: a script written before the run waits for the question it belongs to, and a gesture
    typed one line too soon would have raised. Appending makes both the same, which is what lets a
    test build a terminal with an empty script and drive it, and what lets one built with a full
    script be driven further after its list runs out.

    That symmetry is what the contract suite rests on without knowing it: its driver is `respond`
    and nothing else, and every question it asks is answered by a gesture that arrived after the
    question. This is the same member, asked in the other order.
    """
    async with terminal as term:
        term.respond(SAY_MORE, TYPED)

        assert term.remaining == (Press(SAY_MORE, TYPED),), (
            f"a gesture arrived with nothing on screen and the script reads {term.remaining!r}. It "
            f"is appended and then spent if anything can be, so a gesture with nothing to answer "
            f"waits exactly as a written one does"
        )

        answered = await term.show(question, priority=AGENT, label=EARLY)

        assert answered == f"{EARLY}: {TYPED}", (
            f"the question was answered with {answered!r}. The gesture that was waiting names the "
            f"field and carries what was typed, and it is spent the moment there is a screen for "
            f"it - which is the same line that spends a scripted one"
        )
        assert not term.remaining, "the waiting gesture was spent, so nothing is left of it"

async def test_the_board_is_readable_behind_a_question_and_keeps_being_written_while_it_is_up(
    terminal: ScriptedTerminal,
) -> None:
    """The slot, read directly: what the workflow is saying while a person looks elsewhere.

    `displayed()` answers "what would a person see" and `slot()` answers "what is the workflow
    saying about itself", and the two differ exactly while a question is up. The port has no member
    that reports either - a passive `show` returns `None` and what it registered is thereafter
    invisible - so a test asserting that a board advanced *during* a negotiation has nowhere else to
    look, and answering the question first to get the board back on screen would change the state it
    was asking about.

    The contract suite makes the neighbouring claim through its driver: that showing a board under a
    question does not take the screen, and that the board that appears afterwards is the one at the
    last write. What is here is the half that needs two answers at once, and the fallback at the end
    is the same mechanism seen from the other side - once the queue empties, the two members agree.
    """
    async with terminal as term:
        await term.show(dashboard, line=RUNNING)
        asked = asyncio.create_task(term.show(question, priority=AGENT, label=EARLY))
        await _displaying(term, EARLY)

        await term.show(dashboard, line=LANDED)

        assert _body(term.slot()) == Text(LANDED), (
            f"the board was re-shown while a question was up and `slot()` reports "
            f"{term.slot()!r}. The slot is a register that is written whether or not anything is "
            f"drawing it, which needs no extra machinery, and it is why a workflow updating "
            f"its board behind a question it is itself blocked on does not deadlock"
        )
        assert _body(term.displayed()) == Text(EARLY), (
            f"showing a board while a question was up put {term.displayed()!r} in front of the "
            f"person. A dashboard is not in that ordering at all: the question is what the run is "
            f"blocked on, and a board that pushed it aside takes away the thing being waited for"
        )

        term.respond(APPROVE)
        await asyncio.wait_for(asked, DEADLINE)

        assert _body(term.displayed()) == Text(LANDED), (
            "the queue emptied and what appeared was not the board as it stood at the last write. "
            "No workflow is told that a question went away, so a slot that went stale under one "
            "would need a re-show nobody can know to make"
        )

async def test_a_script_the_run_never_spent_is_still_there_when_the_terminal_has_closed() -> None:
    """The assertion that catches the direction a hang does not: gestures the run never asked for.

    A script longer than the run that spent it is a workflow that took a branch the test did not
    think it was taking - a question not asked, a step that replayed, a handler that never ran. It
    is invisible from everywhere else: every `show` was answered, every assertion about the answers
    passes, and the only evidence is the gesture nobody used.

    So `close()` empties the queues and leaves the script alone, and `remaining` after the context
    reads what it read inside it. Clearing it there would be tidier and would take the evidence away
    at the exact moment a test is about to look for it.
    """
    term = ScriptedTerminal([APPROVE, APPROVE])
    async with term as opened:
        await opened.show(question, priority=AGENT, label=EARLY)

    assert term.remaining == (Press(APPROVE),), (
        f"one question was shown against a script of two gestures and the terminal closed holding "
        f"{term.remaining!r}. Closing is not somebody un-writing the test: the gesture the run "
        f"never asked for is the finding, and it is the only trace of a screen that was never shown"
    )

async def test_leaving_with_a_question_still_waiting_fails_it_rather_than_leaving_it_blocked(
    terminal: ScriptedTerminal,
) -> None:
    """The other end of the trap: a question the terminal outlives is answered by nobody, loudly.

    A script that runs out makes a question wait, which is honest while the terminal is up. Once it
    is not, waiting is a lie - the context is gone, no gesture can arrive, and with no timeouts
    anywhere on this port the workflow would hang on the way out of its own `async with`. So
    `Screens.close` fails every waiter with `UpstreamUnavailable`, which is the class the port
    already names for "this needs a person and there is not one" and is what the headless terminal
    raises for the same state at the other end of the run.

    `InternalError` would be wrong: shutting down with a question up is ordinary, since `__aexit__`
    runs on the failing paths too and the run that ends badly is the one most likely to have one
    open.
    """
    async with terminal as term:
        asked = asyncio.create_task(term.show(question, priority=AGENT, label=EARLY))
        await _displaying(term, EARLY)

    with pytest.raises(UpstreamUnavailable):
        await asyncio.wait_for(asked, DEADLINE)

async def test_the_spelling_a_workflow_author_writes_reaches_this_class_and_the_bundle(
    tmp_path: Path,
) -> None:
    """`testing.answering([...])` handed to `harness(terminal=...)`, which is the whole surface.

    Three layers and one object. The class is in `agl.adapters`, which contract 5 lets only the
    composition root name; `config/container.py` holds the `new`; and `agl.testing` is where the
    name an author writes lives, two layers above the adapter and unable to import it. A test that
    only exercised the class would leave the two hops in between unasserted, and they are the reason
    this deliverable is three files rather than one.

    The last line is `FakeServices.with_terminal`'s own claim, checked with the object that made it
    necessary: both views name the same terminal, so a test that shows a screen through the run and
    reads the terminal afterwards is reading the one the run used.
    """
    term = testing.answering([APPROVE, Press(SAY_MORE, TYPED)])

    assert isinstance(term, ScriptedTerminal), (
        f"`testing.answering` handed back a {type(term).__name__}. It is a delegate to "
        f"`container.answering`, which is the one place allowed to construct this class - a "
        f"different object here means the spelling an author writes and the class the contract "
        f"suite runs are two things"
    )
    assert term.remaining == (Press(APPROVE), Press(SAY_MORE, TYPED)), (
        f"the script reads {term.remaining!r} through the author's own spelling. The coercion is "
        f"the class's, applied on the way in, so it is the same list whichever door it came through"
    )

    harness = testing.harness(tmp_path, terminal=term)

    assert harness.fakes.terminal is term and harness.fakes.services.terminal is term, (
        "the harness took the scripted terminal into one of its two views and not the other. "
        "`with_terminal` swaps both at once for exactly this reason: a bundle where the two come "
        "apart is one where a test reads the terminal the run did not use"
    )

def _body(screen: Screen[object] | None) -> Text | None:
    """The body of a screen a read-back reported, or `None` if it reported nothing.

    A helper because every assertion below wants the body and none of them wants to say "is not
    None" first: the failure message carries the whole screen, so what is compared can be the one
    part a test knows - it built the view and passed the argument the body is made of.
    """
    return None if screen is None else _text(screen.body)

def _text(body: object) -> Text | None:
    """The body as a `Text`, or `None` for a component that is not one. Every view here has one."""
    return body if isinstance(body, Text) else None

async def _displaying(term: ScriptedTerminal, want: str) -> None:
    """Wait until `want` is the body of what a person would see, or fail saying what is.

    Polling rather than a single read, because a `show` started as a task has to reach the terminal
    before anything is displayed at all - and the deadline is a bound on hanging rather than a
    claim about speed, this terminal having no frame rate to make one out of.
    """
    loop = asyncio.get_running_loop()
    expires = loop.time() + DEADLINE
    while loop.time() < expires:
        if _body(term.displayed()) == Text(want):
            return
        await asyncio.sleep(TICK)
    raise AssertionError(
        f"{want!r} was never displayed within {DEADLINE:.0f}s. What is on screen is "
        f"{term.displayed()!r}, and the script has {term.remaining!r} left"
    )
