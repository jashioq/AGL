"""`RichTerminal` against the `Terminal` contract, plus the things a real console makes visible.

The first class is the port in full: `TerminalContract` with its two fixtures overridden and
nothing else touched. Everything `Terminal` promises is asserted there, by a suite written at stage
3 against the port's docstrings and before this adapter existed - which is the inversion the build
rests on (§1.9), and the reason nothing below re-asserts any of it.

What is below is what that suite says outright it cannot see. Its own docstring lists seventeen
gaps; these are the ones a rich console over a buffer can close, in the order they matter:

  * **That anything was ever drawn** (gap 1). "Nothing here looks at a display. `displayed()` is
    what an implementation says it is showing, and one that reported a screen it never wrote passes
    everything below." So the first two tests take the screen the driver reports and find its text
    in the bytes the console received. That is the witness tying `displayed()` to something real,
    and without it every other assertion in this file and in that suite rests on an unbacked claim.
  * **The diff, and write-on-change** (gap 3). "Comparing this frame against the last and writing
    only on a change is what makes per-frame invocation affordable, and it is invisible from out
    here: a terminal that rewrote everything every frame passes." It is not invisible from in here:
    frames go by over an unchanging view and the console receives not one further byte.
  * **That a redraw loop exists at all** (gap 2). "An implementation that derives the screen from
    the view and its arguments only when somebody asks what is displayed passes." So one test
    mutates a live argument and then touches the terminal with nothing whatsoever - no `show`, no
    read of what is displayed - before finding the new value in the console's own bytes.
  * **The streams `rich` takes over.** Not in that suite's list at all, because from inside the port
    there is no such thing. `Live.start()` replaces the process-global `sys.stdout` and `sys.stderr`
    with a `FileProxy` routing writes through the console, and only `Live.stop()` puts them back; a
    run that skipped it leaves every later traceback in the process going to a console whose live
    region is gone. Asserted on the ordinary path and on the exception path, which is the one the
    lifecycle suite raises a `Stop` down.
  * **The console that cannot animate.** A plain log stream is a real deployment of this adapter
    (§3.7 phrases the headless rule on input rather than on a TTY for exactly that reason), and it
    takes the other of `_display.py`'s two paths - no `Live`, no redirection, a frame printed for
    every change and none for a screen that did not change.

Three more sit beside those and are decisions this adapter made that nothing else would notice: a
view that starts raising becomes a frame rather than a dead repaint task, a person mistyping is
ignored rather than being an `InternalError`, and a shutdown never waits on a keystroke nobody is
going to press.

**The driver here is written by the party it exists to catch**, which `_terminal_driver` says of
itself in those words. Two things are done about it. `displayed()` returns `RichTerminal.written`,
which the terminal assigns at its write call site and nowhere else - so it reports what reached the
display, and a suppressed write goes stale rather than being covered by a second value derived on
demand. And `respond` types the digits a person would type into the same `Keys` a tty would feed,
so the whole read-and-parse half of the adapter is under the contract suite rather than beside it.

The views are this file's own rather than `tests/contracts/_terminal_views.py`'s, as
`test_rich_terminal_queues.py`'s are: reusing them would couple this file to a suite this
deliverable may not edit, and would make a failure here ambiguous between the two.

Named `test_rich_terminal.py` for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import asyncio
import io
import queue
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
from rich.console import Console

from agl.adapters.rich_terminal.terminal import Keys, RichTerminal, StdinKeys
from agl.ports.errors import Stop, UpstreamUnavailable
from agl.ports.terminal import (
    Choice,
    Component,
    Row,
    Rows,
    Screen,
    Terminal,
    Text,
    TextInput,
)
from contracts.terminal import TerminalContract, TerminalDriver

# Module-level tests do not inherit the marker the contract classes set on themselves, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is how
# a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

DEADLINE: Final = 10.0
"""How long anything here waits before calling it a hang. Every wait in this file bounds one, and
none of them asserts a speed: the terminal's frame rate is its own choice and nothing here encodes
it."""

TICK: Final = 0.005
"""How often `written` is read while waiting. Small against a redraw loop, large enough that a test
is not spinning the event loop flat out."""

SETTLE: Final = 0.5
"""How long a test lets frames go by before asserting that nothing was written. Five frames at this
adapter's default rate. Being too short costs sensitivity and can never fail an honest
implementation, since every assertion made after it says "and nothing had changed"."""

PROMPTLY: Final = 2.0
"""How long leaving the context may take while a read nobody will ever answer is in flight. It is
not a performance assertion - two seconds is enormous for four cancelled tasks - it is the
difference between a shutdown and a process waiting on a person who walked away."""

_WIDTH: Final = 100
"""The console width these tests render at, fixed so that what a frame contains is a fact about the
terminal rather than about the machine running it. Every string below fits on one line at this
width, so a test looking for one in the output is not looking for something rich wrapped."""

# What the fake keyboard does between looking at whether it has been stopped. Short, because one
# test measures how long a shutdown takes with a read in flight.
_KEYBOARD_POLL: Final = 0.01

# The two responses `question` offers, in the order it offers them. A driver names a response by
# position, and `respond(0)` in a test body would name nothing a reader can see.
APPROVE: Final = 0
SAY_MORE: Final = 1

APPROVED: Final = "approved"
TYPED: Final = "not yet - land the other one first"

# The questions and the dashboards. Sentences, because each one ends up in a failure message saying
# what was on screen when something else should have been.
EARLY: Final = "the question that was asked first"
RUNNING: Final = "two children running"
LANDED: Final = "one child landed, one still running"

# §3.7's board, and the activity lines its own example shows.
TICKET: Final = "T-01"
READING: Final = "Read: connectors/api/backend.ts"
EDITING: Final = "Edit: domain/usecase.kt"

# What a person types that names no response at all: nothing, a word, the number below the first
# one and a number past the last. None of them may answer anything, and none of them may stop the
# reader reading.
_MISTYPED: Final = ("", "banana", "0", "9")


@dataclass(frozen=True, slots=True)
class Answer:
    """What responding to one of these screens produces: the workflow's own type, in shape.

    Frozen, so two built from the same parts compare equal and a test can say *which* answer came
    back rather than only that something did.
    """

    asked: str
    said: str


class Wobble(Exception):
    """What a view raises in the two tests where one does. Its own class, so a test asserting that
    a frame named the failure is not matching on something another failure could have produced."""


def dashboard(line: str) -> Screen:
    """A passive screen with one line on it. `Screen` and not `Screen[None]`, which is the spelling
    a workflow author uses and the one PEP 696's default exists for."""
    return Screen(line)


def board(rows: Mapping[str, str]) -> Screen:
    """§3.7's board over a mapping the caller keeps a reference to.

    This exists for the tests that mutate an argument long after `show` was called: the lookup
    happens again on every invocation, which is why a live dict reaches the display with no second
    `show` and no notification of any kind.
    """
    return Screen(Rows([Row(name, activity) for name, activity in rows.items()]))


def question(label: str) -> Screen[Answer]:
    """§3.7's approval screen: a body to read, a choice to pick and a field to type into.

    Both response kinds, because they are the two routes to one `T` and because the input
    convention has to be shown answering each of them. The `maps` lambda is rebuilt on every
    invocation and is excluded from comparison, which is what lets the diff hold this screen still
    while somebody reads it.
    """
    return Screen(
        body=Text(label),
        responses=[
            Choice("Approve", value=Answer(asked=label, said=APPROVED)),
            TextInput("Say more", maps=lambda typed: Answer(asked=label, said=typed)),
        ],
    )


def unreliable(label: str, wobbles: list[bool]) -> Screen:
    """A view that draws until its argument says otherwise, and raises from then on.

    Both halves matter. It has to *work* first, so that the failure is a view that started raising
    rather than one that could never be shown - which is the ordinary case, since a view is invoked
    again for as long as it is on screen and workflow data moves underneath it. And the switch is a
    live argument rather than a closure, because that is how everything else in this file moves.
    """
    if wobbles[0]:
        raise Wobble("this view cannot draw itself any more")
    return Screen(label)


class Typing(Keys):
    """A keyboard a test types on: lines in from the loop's thread, lines out on a worker thread.

    The injectable half of `Keys` doing the job it exists for - a terminal whose input could only
    come from a tty is a terminal no test can drive without one. It is a real implementation of
    that port rather than a stub: the terminal reads it through `run_in_executor` exactly as it
    reads a keyboard, so every test here goes through the same parse, the same numbering and the
    same "take the screen to read a line" that a person's keystrokes go through.

    **It polls rather than blocking outright**, for the reason `StdinKeys` does: `stop` has to end
    a read nobody is ever going to satisfy, and a `Queue.get()` with no timeout could not be
    interrupted. Ten milliseconds, because one test measures a shutdown against a read in flight.

    `given` is appended to from the worker thread and read from the event loop with no lock, which
    is sound for the one thing it is used for: `list.append` and `len` are each a single bytecode
    under the GIL, and no test does anything but wait for the count to reach a number.
    """

    __slots__ = ("_lines", "_stopped", "_waiting", "given")

    def __init__(self) -> None:
        self._lines: queue.Queue[str] = queue.Queue()
        self._stopped = threading.Event()
        self._waiting = threading.Event()
        self.given: list[str] = []

    def read(self) -> str | None:
        self._waiting.set()
        try:
            while not self._stopped.is_set():
                try:
                    line = self._lines.get(timeout=_KEYBOARD_POLL)
                except queue.Empty:
                    continue
                self.given.append(line)
                return line
            return None
        finally:
            self._waiting.clear()

    def stop(self) -> None:
        self._stopped.set()

    def enter(self, *lines: str) -> None:
        """Type some lines and carry on. They are read in the order they were typed, whenever the
        terminal gets to them - which is what a keyboard buffer does."""
        for line in lines:
            self._lines.put(line)

    async def entered(self, *lines: str) -> None:
        """Type them and wait until the terminal has taken every one.

        The count is taken **before** the lines go in, because the reader is on another thread and
        may have one of them before this coroutine gets its next line of execution - a target
        computed afterwards would be a target one line too far away, and this would wait out its
        deadline against a terminal doing everything right.
        """
        wanted = len(self.given) + len(lines)
        self.enter(*lines)
        await self._until(lambda: len(self.given) >= wanted, f"the terminal to read {lines}")

    async def waiting_for_a_key(self) -> None:
        """Wait until a read is genuinely in flight - the state a shutdown has to survive."""
        await self._until(self._waiting.is_set, "the terminal to start reading the keyboard")

    async def _until(self, ready: Callable[[], bool], what: str) -> None:
        loop = asyncio.get_running_loop()
        expires = loop.time() + DEADLINE
        while loop.time() < expires:
            if ready():
                return
            await asyncio.sleep(TICK)
        raise AssertionError(
            f"{what} was still waiting after {DEADLINE:.0f}s. This terminal reads while a question "
            f"is on screen, so nothing happening here means either that no question is up or that "
            f"the reader is not running at all. It has taken {self.given!r}"
        )


class Presses(TerminalDriver):
    """The person, played by the suite: what is on screen, and typing what answers it.

    Both members are argued in the module docstring, and both are written the way they are because
    the suite says plainly that this class is written by the party it exists to catch.

    `displayed` reads the terminal's own record of the frame it last wrote. It derives nothing: a
    terminal that never wrote reports `None` and fails everything, and one whose diff wrongly
    decided not to write reports the stale screen and fails the suite's own waits.

    `respond` types. It looks at the displayed screen exactly as a person would - to see whether
    the response it is about to pick opens a text field - and then puts the same digits through the
    same keyboard. Nothing here reaches `Screens.answer` behind the terminal's back, which would
    leave the numbering, the parse, the mistype rule and the screen-taking read untested while the
    suite reported twelve passes.
    """

    def __init__(self, terminal: RichTerminal, keys: Typing) -> None:
        self._terminal = terminal
        self._keys = keys

    def displayed(self) -> Screen[object] | None:
        return self._terminal.written

    async def respond(self, response: int, typed: str = "") -> None:
        screen = self._terminal.written
        assert screen is not None, (
            "the driver was asked to answer a screen and this terminal has written none. Every "
            "caller in the contract suite has just read `displayed()`, so nothing there answers "
            "an empty display"
        )
        assert 0 <= response < len(screen.responses), (
            f"the driver was asked for response {response} on a screen offering "
            f"{len(screen.responses)}. A position no response occupies is not a gesture a person "
            f"can make, and this suite never names one"
        )
        lines = [str(response + 1)]
        if isinstance(screen.responses[response], TextInput):
            lines.append(typed)
        await self._keys.entered(*lines)


@pytest.fixture(autouse=True)
def _not_a_dumb_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make rich's animation test answer the same way on every machine.

    `Console.is_dumb_terminal` reads `TERM` from the environment, and a `TERM` of `dumb` or
    `unknown` - which is what a bare CI runner exports - would send a console this file forced to
    be a terminal down the *other* of `_display.py`'s two paths. Then the tests about the animating
    display would silently be testing the appending one, and the two tests about `sys.stdout` and
    `sys.stderr` would pass by never redirecting anything.
    """
    monkeypatch.setenv("TERM", "xterm-256color")


@pytest.fixture
def output() -> io.StringIO:
    """Where the terminal's bytes actually go. A buffer rather than a tty, and read as one."""
    return io.StringIO()


@pytest.fixture
def console(output: io.StringIO) -> Console:
    """A console rich will animate, whose output a test can read.

    `force_terminal=True` is what puts it on the `Live` path - in-place redraw, and the
    process-global stream redirection that comes with it - while the bytes go somewhere a test can
    look. That combination is the whole reason this file can see anything the contract suite
    cannot.
    """
    return Console(file=output, force_terminal=True, width=_WIDTH)


@pytest.fixture
def keys() -> Typing:
    """The keyboard both the module-level tests and the contract suite's driver type on."""
    return Typing()


@pytest.fixture
def terminal(console: Console, keys: Typing) -> RichTerminal:
    """The adapter the module-level tests drive, built and not yet entered.

    Typed as the implementation rather than as the port, because these tests read `written` - which
    is this adapter's own and is deliberately not on the ABC.
    """
    return RichTerminal(console, keys)


@pytest.fixture
def driver(terminal: RichTerminal, keys: Typing) -> Presses:
    """A person at that terminal, typing on that keyboard."""
    return Presses(terminal, keys)


class TestRichTerminal(TerminalContract):
    """The port in full, against a real rich console over a buffer.

    Two overrides and nothing else, which is what the suite asks for. Both depend on the fixtures
    above, which is how the driver is guaranteed to be over the same terminal - the thing the suite
    names as something it cannot check from inside.
    """

    @pytest.fixture
    def terminal(self, console: Console, keys: Typing) -> Terminal:
        """The adapter, over a console `Live` will animate and a keyboard the driver types on."""
        return RichTerminal(console, keys)

    @pytest.fixture
    def driver(self, terminal: RichTerminal, keys: Typing) -> TerminalDriver:
        """The person, over that same terminal and that same keyboard."""
        return Presses(terminal, keys)


async def test_the_screen_reported_as_displayed_is_the_text_the_console_actually_received(
    terminal: RichTerminal, driver: Presses, output: io.StringIO
) -> None:
    """Gap 1, closed: what the driver reports and what the console received are the same screen.

    The contract suite's first stated limit is that nothing in it looks at a display, so a terminal
    whose `displayed()` reported a screen it never wrote passes all twelve of its tests. This is
    the assertion that makes those twelve mean something: the body of the screen the driver hands
    back is found, as text, in the bytes the console was given.

    It is written through the driver rather than through `RichTerminal.written` on purpose. The
    driver is the object the suite trusts, and tying *it* to real bytes is what the suite needs;
    reading the terminal's own record here would leave the one indirection the warning is about
    untested.
    """
    async with terminal as term:
        await term.show(dashboard, line=RUNNING)
        shown = await _drawn(term, Text(RUNNING))

        assert driver.displayed() == shown, (
            "the driver reports a different screen from the one the terminal recorded writing. "
            "They are the same value read through one field, so a difference here means the "
            "driver derives something of its own - which is the failure this file exists to "
            "prevent, not to demonstrate"
        )
        assert RUNNING in output.getvalue(), (
            f"the driver says {shown!r} is displayed and the console never received the text of "
            f"it. `displayed()` is what every ordering claim in the contract suite is "
            f"synchronised against, so a terminal that reports a screen nobody could have seen "
            f"passes that suite while showing a person nothing at all"
        )


async def test_a_question_is_drawn_with_its_responses_numbered_the_way_a_person_answers_them(
    terminal: RichTerminal, keys: Typing, output: io.StringIO
) -> None:
    """The other half of gap 1, and the only place the input convention is visible as a whole.

    A person is told what to type by the frame in front of them, and what they type is parsed
    against the same order. Both ends are asserted here against one screen: the labels and their
    numbers are in the bytes, and then typing the number that was drawn beside a label answers with
    that label's own value.

    Nothing about this is observable from the contract suite - it names a response by position and
    never learns that a position is drawn as a digit - and getting it wrong in one place only is a
    terminal that offers a person numbers it will not accept.
    """
    async with terminal as term:
        asked = asyncio.create_task(term.show(question, label=EARLY))
        await _drawn(term, Text(EARLY))

        frame = output.getvalue()
        assert "1." in frame and "Approve" in frame, (
            f"the question is displayed and the console received no numbered choice: {frame!r}. "
            f"The numbering a person reads is the numbering the terminal parses, so a frame "
            f"without it is a screen nobody can answer"
        )
        assert "2." in frame and "Say more" in frame, (
            "both responses are offered, so both are drawn and both are numbered"
        )

        await keys.entered(str(APPROVE + 1))

        assert await _within(asked) == Answer(asked=EARLY, said=APPROVED), (
            "typing the number drawn beside a choice did not answer with that choice's own value. "
            "`Choice.value` *is* the answer, and the digit is the whole of how a person names it"
        )


async def test_picking_a_text_field_takes_the_screen_to_read_it_and_gives_the_screen_back(
    terminal: RichTerminal, keys: Typing, output: io.StringIO
) -> None:
    """The second half of the input convention: a field is picked, and then it is typed into.

    A `TextInput` cannot be answered by a number alone, so picking one opens a read of its own -
    and that read takes the whole display, because a person typing into a live region cannot see
    what they are typing. There is no field drawn on the frame and no cursor in it: picking is what
    opens the editor, and until somebody picks, there is nothing to type into.

    Three things, and the last is the one an implementation can get wrong while looking right. The
    field's own label is what a person is prompted with, so they know which question the empty line
    under their cursor belongs to. What they typed reaches the workflow through the screen's own
    `maps`. And **the display comes back**: a terminal that took the screen and never gave it back
    would answer this question correctly and then draw nothing for the rest of the run.
    """
    async with terminal as term:
        asked = asyncio.create_task(term.show(question, label=EARLY))
        await _drawn(term, Text(EARLY))

        await keys.entered(str(SAY_MORE + 1), TYPED)

        assert await _within(asked) == Answer(asked=EARLY, said=TYPED), (
            f"picking the field and typing {TYPED!r} did not reach the workflow through the "
            f"screen's own `maps`. The terminal collects a string and hands it straight over - it "
            f"never learns what the result is"
        )
        assert "Say more:" in output.getvalue(), (
            f"nothing prompted for the text: the console holds {output.getvalue()!r}. The field's "
            f"label is the workflow author's own words for what to type, and a bare cursor under a "
            f"screen that has just been taken away says nothing at all"
        )

        await term.show(dashboard, line=LANDED)
        await _drawn(term, Text(LANDED))
        assert LANDED in output.getvalue(), (
            "the display never came back after the read that took it. The record of what was "
            "written says this frame went up, and the console never received it - which is a "
            "terminal drawing into a live region it stopped and never restarted"
        )


async def test_a_screen_that_has_not_changed_is_never_written_again_and_a_changed_one_is(
    terminal: RichTerminal, output: io.StringIO
) -> None:
    """Gap 3, closed: the diff, which is the clause that makes per-frame invocation affordable.

    §3.7's design is a view re-invoked ten times a second, and it only works because the expensive
    part - the write - is skipped when nothing moved. The contract suite says outright that a
    terminal rewriting everything every frame passes it, and from out here that is true: nothing on
    the port could tell the two apart.

    So: frames go by over a view whose answer cannot change, and the console receives not one
    further byte. Then the argument moves and the console receives a frame at once. The second half
    is what stops the first from being satisfied by a terminal that draws nothing at all.
    """
    rows = {TICKET: READING}
    async with terminal as term:
        await term.show(board, rows=rows)
        await _drawn(term, Rows([Row(TICKET, READING)]))
        settled = output.getvalue()

        await asyncio.sleep(SETTLE)

        assert output.getvalue() == settled, (
            f"the console received {len(output.getvalue()) - len(settled)} further bytes over "
            f"{SETTLE}s with nothing on screen changing. The view is invoked every frame and "
            f"returns an equal `Screen` every time: the diff is what turns that into one write, "
            f"and a terminal writing them all is rewriting a person's screen ten times a second "
            f"to no effect"
        )

        rows[TICKET] = EDITING

        await _drawn(term, Rows([Row(TICKET, EDITING)]))
        assert EDITING in output.getvalue(), (
            "the diff skipped a frame that had genuinely changed. Skipping a write when nothing "
            "moved and skipping one when something did are the same comparison read two ways, and "
            "a terminal that never writes passes the first half of this test perfectly"
        )


async def test_a_live_argument_reaches_the_display_with_nothing_else_touching_the_terminal(
    terminal: RichTerminal, output: io.StringIO
) -> None:
    """Gap 2, closed: there is a loop, and it is what puts the change on screen.

    The contract suite pins re-invocation as *registration* and never as a schedule, and says so:
    "an implementation that derives the screen from the view and its arguments only when somebody
    asks what is displayed passes". Everything in that suite either shows something or reads
    `displayed()` in the same breath, so a terminal that only worked when asked would look
    identical.

    Here nothing asks. The mapping is mutated and then the test sleeps: no `show`, no read of what
    is displayed, no member of the port called at all. What the console holds afterwards was
    written by a task that ran on its own, which is the only thing that could have written it.
    """
    rows = {TICKET: READING}
    async with terminal as term:
        await term.show(board, rows=rows)
        await _drawn(term, Rows([Row(TICKET, READING)]))

        rows[TICKET] = EDITING
        await asyncio.sleep(SETTLE)

        assert EDITING in output.getvalue(), (
            f"a live argument was mutated, several frames' worth of time passed with nothing "
            f"touching the terminal, and the console holds {output.getvalue()!r}. `show` "
            f"registers the view and its arguments and a loop invokes it again - a terminal that "
            f"waits to be asked leaves a workflow's board frozen at whatever it said when the "
            f"last question was answered"
        )


async def test_the_streams_rich_takes_over_are_the_same_objects_after_an_ordinary_run(
    terminal: RichTerminal,
) -> None:
    """`Live` replaces `sys.stdout` and `sys.stderr` while it is up, and `stop` is what restores.

    Not a gap in the contract suite so much as something outside its world: gap 7 says the display
    being handed back is observed as `show` raising afterwards and never as a device restored,
    because nothing on the port could report one. This is what a device restored looks like from
    inside the process.

    Rich's mechanism, in its own words: `_enable_redirect_io` swaps both streams for a `FileProxy`
    routing writes through the console, which is how a stray `print` or a warning stops landing in
    the middle of a live region and scrambling it. `_disable_redirect_io`, called only from
    `Live.stop`, swaps them back. A run that never stopped would leave `sys.stderr` pointing at a
    console whose live region no longer exists, for the rest of the process.

    The redirect is asserted to have *happened* first. Without that half this test would pass
    against a terminal that took nothing over, which is exactly what it would do if the console
    were not animating - and then it would be guarding nothing.
    """
    before = (sys.stdout, sys.stderr)
    async with terminal as term:
        await term.show(dashboard, line=RUNNING)
        await _drawn(term, Text(RUNNING))
        assert (sys.stdout, sys.stderr) != before, (
            "`Live` is up over a console this test forced to be a terminal and neither stream was "
            "redirected, so the rest of this test would be asserting that nothing was restored "
            "after nothing was taken"
        )

    assert (sys.stdout, sys.stderr) == before, (
        f"the run ended with `sys.stdout` as {sys.stdout!r} and `sys.stderr` as {sys.stderr!r}. "
        f"Only `Live.stop` puts them back, so a leaked `FileProxy` outlives the terminal that "
        f"made it and every traceback after this point goes through a console that is gone"
    )


async def test_the_streams_are_put_back_when_the_run_ends_in_the_exception_it_was_stopped_by(
    terminal: RichTerminal,
) -> None:
    """The same clause on the failing path, which is the one the lifecycle suite raises a `Stop` on.

    `__aexit__` running on every path out is already the port's requirement - "the run that ends
    badly is the run whose display most needs handing back" - and this is a second, independent
    reason for it that lives entirely inside this adapter. The failing run is also the likeliest
    one to be followed by somebody reading a traceback, which is precisely what a leaked `FileProxy`
    would eat.
    """
    before = (sys.stdout, sys.stderr)
    with pytest.raises(Stop):
        async with terminal as term:
            await term.show(dashboard, line=RUNNING)
            await _drawn(term, Text(RUNNING))
            raise Stop("the workflow ended itself with a screen still up")

    assert (sys.stdout, sys.stderr) == before, (
        f"the run ended in a `Stop` and left `sys.stdout` as {sys.stdout!r} and `sys.stderr` as "
        f"{sys.stderr!r}. Stopping the display is in a `finally` for this reason: the path that "
        f"reports a failure must not be the path that breaks the reporting"
    )


async def test_a_console_that_cannot_animate_still_gets_every_frame_that_changed_and_no_others(
    keys: Typing,
) -> None:
    """The other of `_display.py`'s two paths: a plain log stream, which is a real deployment.

    §3.7 phrases the headless rule on input rather than on "no TTY attached" precisely so that a
    stream with output and no input has a rule too, and a run whose output is redirected to a file
    is that stream. `Live` is no use to it - `Live.refresh` on a non-terminal console renders
    nothing at all while it is started - so the frames are printed instead, and the diff is what
    keeps that from being ten copies of one screen every second.

    Both halves are asserted, because a log that repeated itself and a log that stopped writing
    are the two ways to get this wrong, and each one looks fine if only the other is checked.
    Nothing is redirected on this path either, since nothing was taken over.
    """
    log = io.StringIO()
    streams = (sys.stdout, sys.stderr)
    async with RichTerminal(Console(file=log, width=_WIDTH), keys) as term:
        await term.show(dashboard, line=RUNNING)
        await _drawn(term, Text(RUNNING))

        assert RUNNING in log.getvalue(), (
            f"a console that cannot redraw in place received {log.getvalue()!r} rather than the "
            f"frame. A file is not a terminal and it is not nothing either: it gets what changed"
        )
        printed = log.getvalue()
        await asyncio.sleep(SETTLE)
        assert log.getvalue() == printed, (
            f"{SETTLE}s of frames over an unchanging screen appended "
            f"{len(log.getvalue()) - len(printed)} bytes to a log. The diff is what makes an "
            f"appending display usable at all - without it a run's log is its frame rate"
        )

        await term.show(dashboard, line=LANDED)
        await _drawn(term, Text(LANDED))
        assert LANDED in log.getvalue(), "a changed screen is appended, which is what a log is"

        assert (sys.stdout, sys.stderr) == streams, (
            "a console that is not a terminal had its process's streams redirected. Rich only "
            "redirects for a terminal, and this path uses no `Live` at all, so anything moving "
            "here is this adapter taking over something it was never handed"
        )


async def test_a_view_that_starts_raising_becomes_a_frame_and_the_loop_carries_on_drawing(
    terminal: RichTerminal, output: io.StringIO
) -> None:
    """Gap 11 says the port settles nothing here, so this is what this adapter decided.

    A view is invoked again for as long as it is on screen, so a view that raises is not a call
    that failed once - it is a call that will fail ten times a second until the workflow shows
    something else. The three ways to take that are: let it kill the redraw task, which is a screen
    that silently stops updating and a failure that surfaces nowhere; swallow it and keep drawing
    the last good frame, which is the same thing with the evidence removed; or draw the failure.

    The third is the only one a person can act on, and the second half of this test is why it is
    not enough on its own: the loop has to still be running afterwards. A terminal that reported
    the failure and then stopped drawing would pass the first assertion and leave the run blind.
    """
    wobbles = [False]
    async with terminal as term:
        await term.show(unreliable, label=RUNNING, wobbles=wobbles)
        await _drawn(term, Text(RUNNING))

        wobbles[0] = True

        failed = await _until(
            term,
            lambda screen: isinstance(screen.body, Text) and Wobble.__name__ in screen.body.value,
            "a frame naming the view that could not be drawn",
        )
        assert isinstance(failed.body, Text) and "unreliable" in failed.body.value, (
            f"the frame drawn for a failed view is {failed.body!r} and does not name the view. A "
            f"workflow shows several, and 'something raised' sends its author looking through all "
            f"of them"
        )
        assert Wobble.__name__ in output.getvalue(), "and it reached the console, like any frame"

        await term.show(dashboard, line=LANDED)
        await _drawn(term, Text(LANDED))


async def test_a_view_that_raises_the_first_time_raises_at_the_workflow_s_own_call_site(
    terminal: RichTerminal,
) -> None:
    """The one moment a view's exception has somewhere better to go than a frame.

    `show` has to invoke the view once, because the return annotation says which kind of screen it
    is and nothing at run time can see an annotation - what is dispatched on is whether `responses`
    is empty. If *that* invocation raises, there is a caller standing right there, and handing it
    the exception puts the traceback at the line that named the view and its arguments. The port
    says a mistyped argument surfaces inside the redraw loop rather than at the call site; where it
    can be raised at the call site instead, it is.

    The registration is refused with it, which is the part worth pinning: a `show` that raised and
    still left something on the slot would put an error frame on screen for a call the workflow
    already saw fail.
    """
    async with terminal as term:
        await term.show(dashboard, line=RUNNING)
        await _drawn(term, Text(RUNNING))

        with pytest.raises(Wobble):
            await term.show(unreliable, label=LANDED, wobbles=[True])

        await asyncio.sleep(SETTLE)
        assert term.written == dashboard(RUNNING), (
            f"a `show` that raised at its own call site left {term.written!r} on screen. The view "
            f"never produced a screen, so there was nothing to register and nothing to draw"
        )


async def test_a_line_that_names_no_response_is_ignored_and_the_question_stays_up(
    terminal: RichTerminal, keys: Typing
) -> None:
    """A person mistyping is ordinary, and none of the four ways to do it is an error.

    `queues.answer` raises `InternalError` for a position no response occupies, and its docstring
    says why: the terminal renders the responses it got from that same screen, so an answer naming
    a position that is not there is AGL's own ordering bug. That reasoning holds exactly because
    this module refuses to pass one on. A blank line, a word, the number below the first response
    and one past the last are all just keys somebody pressed.

    What must survive is the reader. An implementation that let any of these through would answer a
    question with something nobody chose; one that raised on them would kill the task that reads
    the keyboard, and the terminal would look alive - frames still going up - while every question
    from then on waited forever.
    """
    async with terminal as term:
        asked = asyncio.create_task(term.show(question, label=EARLY))
        await _drawn(term, Text(EARLY))

        await keys.entered(*_MISTYPED)
        await asyncio.sleep(SETTLE)

        assert not asked.done(), (
            f"one of {_MISTYPED} answered the question. None of them names a response: two are "
            f"not numbers at all, and the other two are the positions on either side of the ones "
            f"this screen offers"
        )
        assert term.written == question(EARLY), (
            f"the question left the screen after somebody mistyped, and what is up is "
            f"{term.written!r}. Nothing was answered, so nothing moved"
        )

        await keys.entered("1")

        assert await _within(asked) == Answer(asked=EARLY, said=APPROVED), (
            "the keyboard stopped being read after a mistype. The reader is one task for the "
            "life of the terminal, so an exception in it is every question from then on waiting "
            "on nobody"
        )


async def test_shutting_down_does_not_wait_on_a_read_nobody_is_ever_going_to_answer(
    terminal: RichTerminal, keys: Typing
) -> None:
    """The read is abandonable, which is what makes `__aexit__` a shutdown rather than a hope.

    A question on screen means a thread sitting in a blocking read, and the person it is waiting
    for may have walked away - there are no timeouts anywhere on this port, so that is not an
    anomaly, it is Tuesday. Cancelling the task that awaits the read returns control at once, but
    the thread is still in it, and a thread pool's workers are joined when the interpreter exits.
    So `Keys.stop` ends the read itself, and the pool is dropped without waiting on it.

    The other half is the workflow: a question outstanding when the terminal shuts down can never
    be answered, so `Screens.close` fails it rather than leaving a run blocked on a display that
    has been handed back.
    """
    loop = asyncio.get_running_loop()
    async with terminal as term:
        asked = asyncio.create_task(term.show(question, label=EARLY))
        await _drawn(term, Text(EARLY))
        await keys.waiting_for_a_key()
        leaving = loop.time()

    took = loop.time() - leaving
    assert took < PROMPTLY, (
        f"leaving the context took {took:.1f}s with a read in flight. A shutdown that waits on a "
        f"keystroke waits on a person, and the whole reason this port has a context manager is "
        f"that the run which ends badly is the one whose display most needs handing back"
    )
    with pytest.raises(UpstreamUnavailable):
        await _within(asked)


async def test_the_default_keyboard_reads_whole_lines_from_this_process_s_own_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`StdinKeys` is what a deployment actually gets, and nothing else in this file goes near it.

    Every other test here types on `Typing`, which is the point of `Keys` being injectable - but it
    also means the default implementation would otherwise be the one part of this adapter no test
    ever ran. Three claims, and they are the whole of what it promises: a line comes back without
    its ending, `sys.stdin` is read through on every call rather than captured when the object was
    built - which is why a process that replaced its own is read correctly - and the end of input
    is `None` rather than an empty line that would look like somebody pressing Enter.

    A file rather than a tty, because a tty is not a thing a test suite has. What that costs is the
    waiting: `select` reports a regular file ready immediately, so nothing here exercises the poll.
    The test below covers the half that matters about it.
    """
    typed = tmp_path / "typed"
    typed.write_text(f"{SAY_MORE + 1}\n{TYPED}\n", encoding="utf-8")
    with typed.open(encoding="utf-8") as stdin:
        monkeypatch.setattr(sys, "stdin", stdin)
        keys = StdinKeys()

        assert keys.read() == str(SAY_MORE + 1), "a line, without the newline that ended it"
        assert keys.read() == TYPED, "and the next one, from the same stream, in order"
        assert keys.read() is None, (
            "the end of input came back as something other than `None`. A terminal that read an "
            "empty string there would take it for somebody pressing Enter, ten thousand times a "
            "second, against whatever question was on screen"
        )


async def test_a_keyboard_that_has_been_stopped_gives_up_instead_of_waiting_for_a_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The clause that keeps a shutdown from waiting on somebody who walked away.

    `Keys.stop` exists because there is no portable way to interrupt a blocking `readline`, and a
    thread still sitting in one is a process that does not finish: a thread pool joins its workers
    when the interpreter exits, long after the terminal was handed back. So a stopped keyboard
    reads nothing, even with a line sitting there for it - which is what makes the read a wait this
    adapter can end rather than one it can only hope ends.
    """
    typed = tmp_path / "typed"
    typed.write_text(f"{APPROVE + 1}\n", encoding="utf-8")
    with typed.open(encoding="utf-8") as stdin:
        monkeypatch.setattr(sys, "stdin", stdin)
        keys = StdinKeys()
        keys.stop()

        assert keys.read() is None, (
            "a stopped keyboard read a line that was waiting for it. Stopping is what `__aexit__` "
            "does to end a read nobody is going to answer, and one that kept reading afterwards "
            "would hand a keystroke to a terminal that has already handed the display back"
        )


async def _drawn(terminal: RichTerminal, body: Component) -> Screen[object]:
    """Wait until the terminal has written a screen with this body, and hand that screen back.

    The body and not the whole `Screen`, because the body is what a test knows: it built the view
    and passed the argument the body is made of.
    """
    return await _until(
        terminal, lambda screen: screen.body == body, f"a screen whose body is {body!r}"
    )


async def _until(
    terminal: RichTerminal, ready: Callable[[Screen[object]], bool], what: str
) -> Screen[object]:
    """Read what the terminal last wrote until it satisfies `ready`, or fail naming what it is.

    Polling, and every bound in this file is a bound on hanging: nothing here assumes how long a
    frame takes, and a terminal redrawing once a second would pass everything below.
    """
    loop = asyncio.get_running_loop()
    expires = loop.time() + DEADLINE
    while loop.time() < expires:
        screen = terminal.written
        if screen is not None and ready(screen):
            return screen
        await asyncio.sleep(TICK)
    raise AssertionError(
        f"{what} was never written within {DEADLINE:.0f}s. The last frame this terminal wrote is "
        f"{terminal.written!r}"
    )


async def _within[T](work: asyncio.Task[T]) -> T:
    """Await something that ought to finish, under a deadline, so a failure is reported once."""
    async with asyncio.timeout(DEADLINE):
        return await work
