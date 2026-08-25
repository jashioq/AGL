"""`ScriptedTerminal` - the `Terminal` a test answers, from a list written before the run starts.

The third implementation of the port, and the one a workflow author drives: `Press` is one gesture,
a list of them is what a person would have done, and the terminal spends that list on whatever
screen is in front of it. `agl/testing.py` spells it `answering([...])` and `harness(terminal=...)`
takes the result; this module is what that builds.

## Why a third class and not a `Keys` somebody writes

`HeadlessTerminal` refuses a `Screen[T]` and is right to - there is nobody there - so a workflow
that routes an agent question to §3.7's approval screen exits 6 under the default harness. Until
this module existed, answering one meant the `agl[terminal]` extra, a hand-written `Keys`, and a
workflow-side import of `adapters/rich_terminal/terminal.py`, which contract 6 forbids a workflow to
touch and contract 5 forbids anything above the composition root to name at all. The seam was real
and it was the wrong size: `Keys` is the shape a *tty* has, so reusing it made every author
re-derive "type the number, press Enter" - a rendering convention - in order to say "approve".

A `Press` says the thing a test means: *the response at this position, and this is what was typed
into it*. Nothing about digits, lines, or the order a renderer draws them in.

## It is not a mock, and the price of that is the whole of this module's design

A terminal outside `tests/contracts/terminal.py` is under no contract and so free to agree with
nothing - `tests/instruments/keyboard.py` refuses a hand-rolled one in those words - and that
argument applies twice as hard to a terminal handed to strangers: an answering fake that
resolved `show` calls in its own order would let a workflow pass here and deadlock in front of a
person. So this class runs `TerminalContract` - the input-capable half, the one `RichTerminal` runs
- as a third subclass, in `tests/adapters/test_scripted_terminal.py`. That is why the queueing below
is `queues.Screens` and not a list of futures: the slot, the two queues, `current` derived from the
head of the highest non-empty queue, `pending`'s zero per priority ever asked for, and the answer a
`Choice` or a `TextInput` produces are all decided there, once, for every terminal AGL ships.

**What this module adds to that is a source of gestures, and nothing else.** It draws nothing, reads
no key, imports no `rich` (so contract 3 is untouched, as it is for `headless.py`) and holds no
state of its own but the script and the open flag.

## No loop, no task, no frame rate - the screen is derived when somebody asks

There is deliberately no redraw loop. The contract suite's gap #2 sanctions exactly this - "an
implementation that derives the screen from the view and its arguments only when somebody asks what
is displayed passes, and §3.7's ~10 Hz is deliberately encoded nowhere" - and for a terminal with no
display the alternative is a task that computes frames nobody looks at. `displayed()` invokes the
registered view at the moment it is called, so a live argument mutated by workflow code is visible
on the next read for the same reason it would be visible on the next frame.

State therefore changes at exactly two moments, and both drain the script: a `show` that queues a
question, and a `respond` that appends one. Nothing else can make a screen become the displayed one
- the slot is not in that ordering, and `queues.py` never dequeues in order to display - so there is
no third moment for a scheduler to have to cover.

**The cost of having no loop, stated rather than discovered.** A gesture is spent the instant a
question reaches the terminal, so in a workflow whose children ask concurrently, the order of a
written script is *arrival* order and not the order a person would have answered in. A person is
slower than the event loop: a conflict screen arriving a millisecond after an agent question would
take the screen and be answered first, where here the agent question was already answered. Each
gesture still goes to whatever is displayed at the moment it is spent - the rule is kept, and it is
the timing that differs - and `respond` reproduces the human order exactly whenever a test wants it,
because it is spent when the test says so. A drain deferred onto the event loop would close the gap
and would put a scheduler between a workflow's `show` and its answer, which is the thing this module
does not have and is better for not having.

## The one real trap: a question with nothing left to answer it waits forever

**A script that runs out does not raise, it idles**, and a test that then shows a question hangs
rather than fails. That is honest - §3.7 has no timeouts anywhere, and a real terminal with nobody
sitting at it does precisely this - and it is also what makes the contract suite buildable over this
object: the suite constructs the terminal with an *empty* script and shows a question before any
response exists, and that question must wait for `driver.respond` rather than fail at the door.

An exhausting script could have raised instead, and the cost of that is what settles it: the failure
would arrive inside `show`, at the workflow's own call site, as an exception the workflow may well
catch - a retry loop around a step swallows it, and the run carries on having been told a person
refused. A hang is reported by whatever `pytest-timeout` or CI deadline the author already has, and
`remaining` below is the assertion that catches the *other* direction, a script whose responses were
never spent. If a test of yours hangs on a `show`, this is the first thing to look at.

## Where the parts live, and why they are three files apart

The class is here because it is an implementation of a port and contract 5 lets only
`config/container.py` say `new`; the factory that constructs it is there, one line, beside the other
two terminals; and `agl/testing.py` re-exports the pair as `answering` and `Press`, because that is
where a workflow author's spellings live and `agl.testing` may not import `agl.adapters`. `Press` is
defined *here*, at the bottom of the stack, so that one class travels up through both of those
rather than a second one being declared at the top and converted on the way down.
"""

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Self, cast

from agl.adapters.rich_terminal.queues import Screens, View
from agl.ports.errors import InternalError
from agl.ports.terminal import Screen, Terminal

__all__ = ["Press", "ScriptedTerminal"]


@dataclass(frozen=True, slots=True)
class Press:
    """One gesture: which of the screen's own responses, and what was typed into it.

    `Press(1, "not yet - land the other one first")` is a person picking the second response and
    typing a sentence; `Press()` is picking the first and typing nothing. It carries no value and no
    label, for `TerminalDriver.respond`'s reason: turning a gesture into the workflow's own type is
    the terminal's job on this port - `Choice.value` *is* the answer and a `TextInput`'s is
    `maps(typed)` - so a script that handed over a finished `T` would be testing itself.

    Frozen and comparable, so `remaining` can be asserted against a list a test wrote out.
    """

    response: int = 0
    """Which response, by position, in the order the view offered them.

    A position because that is what a person picks and because "in the order offered" is the only
    ordering `Screen.responses` has. It defaults to `0` because the overwhelmingly common script is
    a list of approvals, and `Press()` should be the cheapest thing to write.

    A position no response occupies is refused by `queues.Screens.answer` with an `InternalError`,
    which is the one place this terminal's failures are not about AGL - see `respond`."""

    typed: str = ""
    """What was typed. **It matters only for a `TextInput`**, exactly as it does for a person: a
    `Choice` ignores it, so a script may leave it off wherever the response it names is one."""


class ScriptedTerminal(Terminal):
    """The `Terminal` port over a list of gestures: one slot, two queues, and a script for a person.

    Built by `config/container.answering` and by nothing else, entered by the framework, and
    indistinguishable from `RichTerminal` at every point a workflow can see. The module docstring
    argues everything it decides; what is below is how.

    Three members are not on the port and exist for the test holding this: `displayed`, `slot` and
    `remaining` to read, `respond` to drive. They are what a `TerminalDriver` is written out of.
    """

    __slots__ = ("_open", "_screens", "_script")

    def __init__(self, responses: Sequence[Press | int] = ()) -> None:
        """Build one over `responses`, spent in order. An empty one is driven by `respond` alone.

        **A bare `int` means `Press(int)`**, which is `ports/terminal.py`'s own coercion rule one
        module over - "anywhere a component is expected, a bare `str` means `Text`" - and it is
        applied the same way: on the way in, so what this *stores* is always a `Press` and no reader
        below has a second shape to account for. `answering([0, 0, Press(1, "later")])` is what that
        buys, and a script of approvals is the common case it was bought for.

        A `deque` rather than a list and an index, because the script is consumed from the front and
        `remaining` is the whole of what a test reads back: an index would leave "how many are left"
        derived in one place and "which is next" in another.
        """
        self._screens = Screens()
        self._script: deque[Press] = deque(_pressed(response) for response in responses)
        self._open = False

    async def show[T](
        self,
        view: View[T],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        """Register what `view` returns; answer it from the script if there is anything left to.

        The dispatch is the port's own and is `RichTerminal`'s line for line: nothing at run time
        can see an annotation, so the view is invoked once and a screen with no responses is a
        dashboard. A dashboard goes to the slot and this returns `None` at once **including while a
        question is displayed**, so a workflow updating its board behind a question it is itself
        blocked on does not deadlock.

        A question joins its queue and *then* the script is drained, which is the whole of the
        ordering here. The response that comes off the script answers **whatever is displayed**,
        which is the highest-priority queued screen and not necessarily the one this call just
        queued - the same thing a person would have answered, and the reason a scripted conflict at
        priority 10 is answered before the agent question that was already up.

        Draining before the `await` rather than after it is not an optimisation: the future is
        resolved by then, so awaiting it returns without suspending, and a `show` that had suspended
        first would need something else to be running to wake it. There is nothing else running.

        The `cast` on the passive path is the one the port describes: `show` promises a `T`, a
        passive view's `T` is `None`, and no signature covering both can say so without the overload
        pair the port rejected for reasons of its own.
        """
        if not self._open:
            raise InternalError(
                "`show` was called on a terminal that is not inside its context. The framework "
                "opens the terminal and hands the open one to a workflow, so a call from outside "
                "it - before it was entered, or after it was left - is AGL's own ordering rather "
                "than anything a workflow author did, and that is true of a question as much as of "
                "a dashboard: a script cannot be spent on a terminal nobody opened"
            )
        if view(**params).responses:
            answered = self._screens.queue(view, priority=priority, **params)
            self._spend()
            return await answered
        self._screens.hold(view, **params)
        return cast("T", None)

    @property
    def pending(self) -> Mapping[int, int]:
        """Priority to queued count, excluding what is displayed. The queues' own snapshot."""
        return self._screens.pending

    def displayed(self) -> Screen[object] | None:
        """What a person would be looking at now: the current question, else the board, else none.

        The port's fallback order, which is `queues.Screens.displayed`'s and is not re-derived here.
        The view is invoked at the moment this is called - see the module docstring - so a live
        argument mutated since the last read is already in what comes back, and two reads of an
        unchanged view produce equal screens because every component compares by value.

        Synchronous, for `pending`'s reason: a read of current state rather than work. It is what
        `tests/adapters/test_scripted_terminal.py`'s driver answers `displayed()` with, and the
        contract suite says out loud that a driver is written by the party it exists to catch - so
        what this reports is derived from the registration the queues hold and from nothing this
        class remembers separately.

        A view that raises comes straight out, as it does from `show`'s first invocation.
        `queues.py` says the port settles nothing about a view that raises (the suite's gap 11) and
        this terminal has no frame to put an error message on: there is a caller standing right
        here, which is the one condition under which handing it over beats drawing it.
        """
        registration = self._screens.displayed
        return None if registration is None else registration.screen()

    def slot(self) -> Screen[object] | None:
        """The board, whether or not it is what is on screen, or `None` if none was ever shown.

        `displayed()` above answers "what would a person see"; this answers "what is the workflow
        saying about itself", and the two differ exactly while a question is up. §3.7's slot keeps
        being written under a question - `show` re-registers, the terminal simply is not drawing it
        - so a test that wants to assert a board advanced during a negotiation has to be able to
        read the board rather than the negotiation. Without this that assertion needs the question
        answered first, which changes the state it was asking about.
        """
        slot = self._screens.slot
        return None if slot is None else slot.screen()

    @property
    def remaining(self) -> tuple[Press, ...]:
        """What the script has left, in order, oldest first.

            assert not terminal.remaining

        The assertion that catches the direction a hang does not: a script longer than the run that
        spent it means a screen the workflow never showed, which is a workflow that took a branch
        the test did not think it was taking. Reading empty is the ordinary end state and is worth
        asserting for exactly that reason.
        """
        return tuple(self._script)

    def respond(self, response: int = 0, typed: str = "") -> None:
        """Add one gesture to the end of the script and spend whatever the script can now spend.

        This is what makes a terminal built with an empty script drivable a gesture at a time, and
        it is the whole of what `tests/contracts/terminal.py`'s `TerminalDriver` needs beyond
        `displayed()`. Appending rather than answering directly is deliberate: there is then one
        path that answers a screen, so a gesture that arrives before the question it was meant for
        waits for it instead of raising - which is what a scripted response does too, and the two
        must not be different mechanisms with different rules.

        Synchronous, because nothing here awaits: the future a `show` is waiting on is resolved
        before this returns, and the driver's own `respond` is `async` only so that an
        implementation that *did* need to await something could.

        `queues.Screens.answer` refuses a position no response occupies, with an `InternalError`.
        That class is wrong about whose mistake it is here - a script naming response 5 on a screen
        offering two is the test author's - and it is left alone anyway, because reclassifying it
        would mean this module re-deriving the check that module already makes against the screen it
        is holding, and two checks over one condition is how the two come to disagree. The message
        names the position and the number offered, which is what a reader needs either way.
        """
        self._script.append(Press(response, typed))
        self._spend()

    async def __aenter__(self) -> Self:
        """Open it, which starts nothing, and hand back this same terminal.

        "An implementation with nothing to start implements both halves as no-ops, which is honest
        rather than empty" - the port's own sentence, and it covers this class as much as the
        headless one: there is no loop, no display and no reader here either, and what the flag buys
        is the port's other clause, that a `show` outside the context is refused.

        **Entering twice is refused**, which the port is silent about and both other implementations
        decide the same way. `RichTerminal` refuses it because a second entry would start a second
        redraw loop over the same queues; there is nothing here for a second entry to duplicate, and
        it is refused anyway, because a terminal a test drives that accepted an ordering bug the
        adapter rejects would let a workflow pass here and fail in front of a person.
        """
        if self._open:
            raise InternalError(
                "this terminal is already inside its context. The framework opens a terminal once, "
                "so arriving here twice is AGL's own ordering bug - and it is refused here, where "
                "there is nothing to start twice, so that a workflow tested on a script fails it "
                "exactly where a run on a real terminal would"
            )
        self._open = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Refuse every later `show`, unblock everyone still waiting, and return `None`.

        `Screens.close` is what the port's shutdown clause has here: a question outstanding when the
        terminal goes away can never be answered - there is nobody in front of it and no script left
        that will be spent - so every waiter is failed with `UpstreamUnavailable` rather than left
        blocked. With no timeouts anywhere on this port the alternative is a test that hangs on the
        way out of its own `async with`, which is the failure this class is otherwise most likely to
        produce.

        **The script is left as it is**, and `remaining` after the context is what it was inside it.
        Closing is not somebody un-writing the test: a script with three responses left when the run
        ended is the finding, and clearing it here would take away the evidence at the one moment a
        test is about to look.

        Returning `None` is falsy, so an exception on its way out carries on - a terminal that
        quietly ate a `Stop` would turn a deliberate end into a silent one. The three parameters are
        ignored; they are here because the protocol has them.
        """
        self._open = False
        self._screens.close()

    def _spend(self) -> None:
        """Answer the displayed question from the front of the script, for as long as both exist.

        The loop rather than a single step, because one gesture can uncover another screen: a script
        of three approvals against three questions already queued spends all three here, and a
        workflow that queued them from one `TaskGroup` would otherwise need a `show` per response to
        make progress. It ends when the script runs dry or when nothing is displayed that can be
        answered - the second being the idling the module docstring argues, and neither being an
        error.

        `Screens.answer` is what applies one: it retires the entry, computes the workflow's own
        value from the response the position names, and resolves that `show` call and no other. A
        `maps` that raises comes back to its own `show` rather than out of here, which is that
        module's decision and is what keeps one bad script from stopping the rest of the run.
        """
        while self._script and self._screens.current is not None:
            press = self._script.popleft()
            self._screens.answer(press.response, press.typed)


def _pressed(response: Press | int) -> Press:
    """The coercion rule, in the one place that performs it: a bare `int` is a `Press`.

    `ports/terminal.py` does the same for `str` into `Text` and states the reason there - the rule
    is made uniform so that no site is the exception a reader has to remember, and coercion happens
    on the way in so that what is stored is always the coerced form.
    """
    return Press(response) if isinstance(response, int) else response
