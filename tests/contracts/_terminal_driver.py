"""The one thing this suite needs that the port does not have: something that plays the person.

Every other suite in this package drives its port with the port's own methods. This one cannot.
`Terminal` has no member that answers a screen, and that is not an oversight - answering is what a
person does, and a real implementation reads a keypress. `show` on an interactive screen does not
come back until somebody has answered it, so from outside the port there is no way to see that a
question is up, no way to answer it, and no way to observe the slot at all: a passive `show` returns
`None` and the dashboard it registered is thereafter invisible to every member on the ABC.

So there is an extra fixture, an implementer writes it, and it is the largest cost in this
deliverable. It is stated here rather than buried.

## Two members, and why each one is the smallest thing that would do

`displayed()` reports **the port's own `Screen`** - the value the registered view produced for the
frame currently on screen - and `None` when nothing is up. Not a string of what was drawn, not a
widget, not a cursor position, not a region of a buffer: a `Screen` is a value the implementation
already has, because diffing this frame against the last one is what the redraw loop does with it.
That is what keeps this member free of any rendering model. A driver that reported drawn text would
be a driver only one kind of terminal could write.

`respond(response, typed)` **names a response by position and never carries a value.** Handing over
a finished `T` would let the suite compute the answer itself, and then `Choice.value` and
`TextInput.maps` would never be exercised at all: turning a person's gesture into the workflow's own
type is the terminal's job on this port, and a driver that did it for them would be testing nothing.
Position, because "in the order offered" is the only ordering `Screen.responses` has, and picking
the second thing offered is what a person does.

It answers **whatever is displayed at the moment it is called**, which is why every caller here has
just read `displayed()`. Nothing in this package calls it with nothing on screen.

`displayed()` is synchronous for `pending`'s reason - it is a read of current state rather than
work - and `respond` is not, so that an implementation may await whatever it does with an answer
before saying it is delivered.

## Waiting belongs to the suite, not to the driver

A `wait_until_displayed` on the driver would put the polling, the deadline and the failure message
inside code the implementation's own author writes, which is the one place a contract suite must not
put them. Polling `displayed()` from here keeps all three visible, and asks an implementer for one
member fewer.

## What the driver costs, and why it was accepted anyway

**It is written by the party it exists to catch.** A terminal whose `displayed()` reports a screen
it never wrote passes everything below. Nothing observable from outside the process can close that,
and the choice was between a driver that reports and one that also acts - a driver that could
"dismiss", "preempt" or "redraw" would let a suite drive the queue directly and would dictate the
implementation's internals in the bargain.

Two things keep the damage small. The driver only ever *reports*; the queue is moved exclusively by
`show` and by answering. And **every ordering claim in this suite rests on which `show` call an
answer reaches**, which is the port's own surface: `displayed()` is used to synchronise, to see the
slot - which no member of the port can report - and never as the only witness for who was answered.
An implementation that lied about what is displayed and told the truth about which answer went where
would still have to run a correct queue to pass.

The headless half of this suite never touches any of it, which is the other half of the design: a
terminal that cannot take input displays nothing, so an implementation of it has no driver to write
and `HeadlessTerminalContract` never asks for one.

## Every deadline here bounds a hang and asserts nothing about speed

An interactive `show` blocks until someone answers, and several tests below turn on something that
might never resolve at all. Without a deadline those are hanging tests, which look like slow ones -
`_agent_questions` makes the same argument about a run that never returns. `DEADLINE` is generous
enough that nothing under it is slowness; anything over it is a screen nobody is ever going to
answer.

`SETTLE` is the other direction and is the one number here that touches frames. It is how long a
test waits before asserting that something did *not* happen - that a queued question stayed queued,
that frames did not pile up as entries. It is deliberately not a frame rate and does not need to be
one: too short a settle weakens those assertions and can never fail an honest implementation, since
every one of them says "and nothing had changed".
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Final, Self

from agl.ports.terminal import Component, Screen, Terminal, Text

from ._terminal_views import Approval

DEADLINE: Final = 10.0
"""How long anything here waits before calling it a hang. A hundred frames at §3.7's ~10 Hz."""

TICK: Final = 0.005
"""How often `displayed()` is read while waiting. Small enough to be invisible against a redraw
loop, large enough that a test is not spinning the event loop flat out."""

SETTLE: Final = 0.5
"""How long a test lets frames go by before asserting that nothing moved. See the module
docstring: this is not a frame rate, and being too short costs sensitivity rather than honesty."""


class TerminalDriver(ABC):
    """The person, played by the suite: what is on screen, and answering it.

    Implement it beside the terminal it drives, over that same terminal, and hand it back from
    `TerminalContract`'s `driver` fixture. Two members and nothing else - the module docstring
    argues each one, and argues what a third would have cost.
    """

    @abstractmethod
    def displayed(self) -> Screen[object] | None:
        """The screen on display right now, or `None` if this terminal is showing nothing.

        The `Screen` the currently displayed view produced - the same value the redraw loop diffs
        against the last frame - and not a description of anything drawn. Synchronous, for the
        reason `pending` is a property: a read of current state rather than work.

        Called in a poll from this suite, so it must be cheap and must not block the loop the
        redraw task is running on.
        """

    @abstractmethod
    async def respond(self, response: int, typed: str = "") -> None:
        """Answer whatever is displayed now, through its `response`-th response.

        `response` indexes `Screen.responses` on the displayed screen, in the order the view
        offered them. `typed` is what was typed and matters only for a `TextInput`; a `Choice`
        ignores it, exactly as a person picking one does.

        **What the answer produces is the terminal's to compute**: `Choice.value` for a choice,
        `maps(typed)` for a field. This member carries a gesture, never a `T`.

        Every caller in this package has just read `displayed()` and is naming one of that screen's
        own responses, so nothing here calls this with nothing on screen or with a position no
        response occupies.
        """


async def within[T](work: Awaitable[T], what: str) -> T:
    """Await something that ought to finish, and fail with a sentence if it does not.

    A `TimeoutError` says which primitive noticed; a reader needs to be told which clause broke.
    So every wait in this suite comes through here and names what it was waiting for.
    """
    try:
        async with asyncio.timeout(DEADLINE):
            return await work
    except TimeoutError as expired:
        raise AssertionError(
            f"{what} did not finish within {DEADLINE:.0f}s. There are no timeouts anywhere in this "
            f"port, so a screen nobody answers blocks its step forever - which means a suite that "
            f"waited indefinitely here would be the bug rather than the test for it"
        ) from expired


async def came_back(work: Awaitable[object], what: str) -> object:
    """`within`, widened, for the tests that look at what a *passive* `show` answered with.

    `show` over a passive view is typed as returning `None`, and mypy refuses to let a caller use
    the value of a call that returns `None` - the right rule everywhere except here, where what
    that value actually is at run time is the clause being pinned. An implementation is free to
    hand back anything at all behind a `cast`, and this is the one thing that would notice.
    """
    return await within(work, what)


async def until(
    driver: TerminalDriver, ready: Callable[[Screen[object]], bool], what: str
) -> Screen[object]:
    """Read `displayed()` until something satisfying `ready` is up, or fail naming what is.

    Polling rather than an event, because an event would be a third member on the driver and the
    module docstring argues where waiting belongs. Nothing here assumes how long a frame takes: the
    deadline is a bound on hanging, and an implementation that redraws once a second passes.
    """
    loop = asyncio.get_running_loop()
    expires = loop.time() + DEADLINE
    while loop.time() < expires:
        screen = driver.displayed()
        if screen is not None and ready(screen):
            return screen
        await asyncio.sleep(TICK)
    raise AssertionError(
        f"{what} was never displayed within {DEADLINE:.0f}s. What is on screen is "
        f"{driver.displayed()!r}. The highest-priority screen is always the one shown, and when it "
        f"is dismissed the terminal falls back to the next queued question and finally to the slot"
    )


async def shown(driver: TerminalDriver, want: str | Component) -> Screen[object]:
    """Wait until the displayed screen's body is `want`, and hand that screen back.

    The body, and not the whole `Screen`, because the body is what a test knows: it built the view
    and passed the argument the body is made of. What responses that screen carries is the view's
    business and is asserted where it matters.
    """
    body = Text(want) if isinstance(want, str) else want
    return await until(driver, lambda screen: screen.body == body, f"a screen whose body is {body}")


async def answer(driver: TerminalDriver, response: int, typed: str = "") -> None:
    """`respond`, under a deadline, because an implementation may await anything it likes here."""
    await within(driver.respond(response, typed), f"answering the displayed screen with {response}")


async def let_frames_pass() -> None:
    """Give the redraw loop time to run, for the assertions that say nothing happened."""
    await asyncio.sleep(SETTLE)


class Asking:
    """Interactive `show` calls, started as tasks, and cleaned up if a test leaves one unanswered.

    An interactive `show` does not return until somebody answers it, so a test that wants two
    questions queued has to start both and carry on. `async with Asking(term) as ask` and then
    `ask(question, label=EARLY, priority=AGENT)` hands back the task that call is waiting in, which
    is what every assertion about *which* `show` an answer reached is made against.

    On the way out it cancels whatever is still running. A test that failed part-way otherwise
    leaves a `show` waiting forever, and a task outliving its terminal reports itself in the next
    test's output rather than in this one's failure.

    Typed to `Approval` throughout rather than generically, because every interactive view in this
    suite produces one. The port's promise is that `Screen[T]` carries a *workflow's* own type
    across a mixed list of responses, and one such type exercises it.
    """

    def __init__(self, term: Terminal) -> None:
        self._term = term
        self._started: list[asyncio.Task[Approval]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for task in self._started:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._started, return_exceptions=True)

    def __call__(
        self,
        view: Callable[..., Screen[Approval]],
        *,
        priority: int = 0,
        **params: object,
    ) -> asyncio.Task[Approval]:
        """Start `show` and hand back the task it is waiting in, without awaiting it."""
        task = asyncio.create_task(self._term.show(view, priority=priority, **params))
        self._started.append(task)
        return task
