"""The slot and the two queues: what should be on screen, and who is owed an answer.

`Terminal.show` is one method with two jobs, and this is the bookkeeping under both. A passive
`Screen` goes to **the slot**; a `Screen[T]` joins **a queue** at its priority and blocks its caller
until a person answers it. Which screen is current, what `pending` reports, and which `show` call an
answer resolves are all decided here.

**Nothing here draws, reads a key, or schedules anything.** `terminal.py` owns the redraw loop, the
input, and the task the two run in; it asks this module what to put up and tells it what somebody
pressed. That split is why `rich` is not imported here even though contract 3 would allow it
anywhere under `agl.adapters.rich_terminal`: this half is a register and two lists, and a queue with
a renderer in reach is a queue somebody eventually renders from.

## Current is derived, and an entry leaves its queue only when it is answered

The obvious implementation dequeues in order to display - pop the head, hold it as "the current
screen", put it back when something more urgent arrives - and every hard case in the port then
becomes a special case of putting it back. Preemption has to re-insert the displaced entry at the
*front* of its own queue rather than the back, or a person is taken out of the question they were
half-way through and then handed one that arrived while it was off screen. `pending` has to remember
to count the held one separately from the queued ones. And between the pop and the push there is an
entry that is in no queue and on no screen, which is a state every reader has to account for.

So **nothing is ever dequeued in order to be displayed**. An entry joins its queue in `queue()`
and leaves it in `answer()`, and that is the whole of its movement. Current is *derived*: the head
of the highest non-empty queue, recomputed on every read. Preemption is then not an operation at
all - a higher-priority arrival changes what the derivation returns, immediately and with nothing
moved - and "the displaced question keeps its place" stops being a rule this module implements and
becomes a thing it could not express otherwise. FIFO after preemption is not a special case
either: the queue was never disturbed, so it is still in arrival order.

## Identity is the `show` registration, never the `Screen` value

Both halves of that follow from keeping the **function and its arguments** rather than the value
they produce, which is also what makes a live argument reach the display with no second `show`.

*The frames of one registration are one entry.* A view is re-invoked every frame and returns a
fresh `Screen` each time. Were a fresh value a fresh entry, one question would enqueue ten entries
a second and `pending` would report the frame rate as a backlog.

*Two `show` calls are two entries even when nothing tells their screens apart.* `Screen` is a
frozen dataclass with value equality and `TextInput.maps` is excluded from that equality, so two
agents asking an identical question produce *equal* screens. Keyed on the value they would
collapse into one, and one agent would receive - silently, and then act on - the answer to a
question it never asked. Showing a person the same sentence twice is the lesser evil by a wide
margin. Hence `eq=False` on both classes below: an entry is itself, and the only way to have two
is to have called `show` twice.

## `pending` is a fresh mapping every read

The port calls it a snapshot, and the consumer is what makes that load-bearing: a workflow puts
`term.pending` into a view, so it is read ten times a second and iterated while a row is built. A
live view of the queues would mutate under a comprehension half-way through. A `MappingProxyType`
over this module's own dictionary is the trap that looks like the fix - it is read-only and it still
changes - so what `pending` builds is a new `dict` each time, and the proxy around it is there only
to say that writing to it would be writing to a copy.

Every priority that has ever been queued at keeps its key, at zero, because the port says the map
reports every priority the terminal has been asked for and gives the reason: a workflow reading
`pending.get(10, 0)` must see the same run the same way on every implementation. So a priority's
list is emptied and never deleted.

**A passive `show` registers no priority.** The port says the map reports every priority the
terminal has been asked for, and also that priority means nothing for a passive screen; the
contract suite's gap #5 says both readings are live and every exact-equality assertion in it is
made in a test that showed no dashboard. This is the side taken, and `hold()` takes no priority
argument at all so that the decision is structural rather than remembered. The argument for it:
`show`'s `priority` defaults to `0`, so the other reading puts `{0: 0}` into the map of every
workflow that ever displayed a board, and that key can never become non-zero - it would tell a
reader that a dashboard exists, in a map whose whole subject is people being kept waiting.

## What is deliberately absent

**No timeouts** - §3.7 accepts that an unanswered question blocks its step indefinitely, and
`pending` exists because of it. **No notification when a question is dismissed**: the slot is a
register that is written whether or not anything is drawing it, so when the queues empty the board
that appears is the board as it stood at the last write, and no workflow has to learn that a
question went away. **No per-screen input state** - preemption losing half-typed text is §3.7's
own known and accepted cost, and holding it would be `terminal.py`'s to hold in any case, since it
owns input. **No ordering for the slot**, because ordering a dashboard is meaningless.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from agl.ports.errors import InternalError, UpstreamUnavailable
from agl.ports.terminal import Choice, Response, Screen, TextInput

__all__ = ["Entry", "Registration", "Screens", "View"]


type View[T] = Callable[..., Screen[T]]
"""What `show` is handed: a function returning a screen, with its arguments passed separately.

The port's own `Callable[..., Screen[T]]`, named once so the three places that spell it agree. Its
parameters are unchecked for the reason `Terminal.show` states - a `ParamSpec` cannot coexist with a
keyword-only parameter of `show`'s own, and §3.7's surface chose `priority`.
"""


@dataclass(frozen=True, slots=True, eq=False)
class Registration:
    """One `show` call, kept as the view and the arguments it was given - never as a `Screen`.

    `eq=False` is the load-bearing part and the module docstring argues it: two registrations built
    from the same view and the same arguments produce screens that compare **equal**, so anything
    keyed on the value would fold two agents' questions into one. Identity is what tells them apart,
    which is the default `object` gives and which this decorator would otherwise take away.

    Frozen because a registration never changes: a workflow re-`show`s to change *which* view is on
    screen, and mutating what a live argument holds is a change to the argument, not to this.
    """

    view: View[object]
    """The function, invoked again for every frame it is on screen.

    `View[object]` rather than `View[T]`: this module never learns what a `T` is, and does not need
    to - `Screen` is covariant, so a `Callable[..., Screen[Approval]]` is one of these already, and
    the one place where the type is genuinely lost is `queue()`, which says so there."""

    params: Mapping[str, object]
    """The arguments, exactly as `show` was given them, and evaluated only when the view is invoked.

    This is why arguments need not be values: passing the live dict of child runs works because the
    lookup happens again on every frame, and mutating an object in place shows up for the same
    reason."""

    def screen(self) -> Screen[object]:
        """Invoke the view and hand back what it returned. A fresh `Screen` every call.

        The freshness is the mechanism rather than a cost: `terminal.py` compares this against the
        last frame and writes only on a change, which is what makes per-frame invocation affordable.
        Purity is the view author's side of that bargain, unenforceable here and stated by the port.

        Anything the view raises comes straight out. The contract suite's gap #11 says the port
        settles nothing about a view that raises, so nothing here decides it either - swallowing it
        would be deciding, quietly, in the direction of a screen that silently stops updating.
        """
        return self.view(**self.params)


@dataclass(frozen=True, slots=True, eq=False)
class Entry(Registration):
    """A registration in a queue: a question, and the caller waiting on the answer to it.

    It holds no `Screen` and no answer, and it is never removed in order to be displayed - see the
    module docstring. What makes it current is only ever where it sits: head of the highest
    non-empty queue.
    """

    priority: int
    """The queue it joined. A plain `int`, so this module compares numbers and never learns that one
    of them meant "merge conflict"."""

    answered: asyncio.Future[object]
    """What the `show` call is waiting on, resolved exactly once and by exactly one gesture.

    `object` because the workflow's type is not this module's to know: what goes in is whatever the
    picked `Choice` carried or whatever the picked `TextInput` mapped, both of which are already a
    `T` at run time. `queue()` is where that is handed back at the type the caller was promised."""


class Screens:
    """One terminal's slot and queues, and the whole of what it remembers.

    Built by `terminal.py`, one per terminal, and driven by it: `hold` and `queue` for the two
    halves of `show`, `displayed` for what to draw, `current` for whether a keypress is an answer,
    `answer` to deliver one, `pending` for the port's own property, and `close` on the way out.

    Single-threaded asyncio throughout (§3.7): the redraw loop is another task and neither it nor
    workflow code yields part-way through a method here, so nothing below takes a lock and no state
    is ever observed half-updated.
    """

    __slots__ = ("_queues", "_slot")

    def __init__(self) -> None:
        self._slot: Registration | None = None
        self._queues: dict[int, list[Entry]] = {}

    def hold(self, view: View[object], /, **params: object) -> None:
        """Put a passive registration in the slot, replacing whatever was there.

        Size one, replaced on write, no ordering, and no priority - the port says priority means
        nothing for a passive screen and the module docstring says why that is spelled as an absent
        parameter here rather than an ignored one.

        The replaced registration is *gone*, not queued behind this one and not coming back. And
        this succeeds while a question is displayed, because the slot is a register and the
        terminal is simply not drawing it: that is §3.7's "no extra machinery", and it is why a
        workflow updating its board behind a question it is itself blocked on does not deadlock.

        `view` is positional-only, and `params` is collected the way `show` collects it, so that
        `terminal.py` forwards rather than repackages. A view with a parameter named `view` cannot
        be shown, which is the cost the port already accepted for `priority`.
        """
        self._slot = Registration(view, params)

    def queue[T](self, view: View[T], /, *, priority: int = 0, **params: object) -> Awaitable[T]:
        """Join the queue at `priority`, and hand back what the `show` call waits on.

        Appended, so the queue stays in arrival order - FIFO within a priority is by arrival, and
        nothing below ever reorders a queue or takes an entry out of one except to answer it.

        **The one place a type is lost.** A `Future[T]` cannot be stored beside futures of every
        other workflow type, because `Future` is invariant; a `Future[object]` can, and what is
        put into it is the `T` the view's own `Choice` or `TextInput` produced. So the cast states
        a fact rather than hoping for one, and it is the same cast `Terminal.show` says it needs -
        made once here instead of at every call site that would otherwise carry an `object` away.

        The done callback is how an *abandoned* question leaves: if the awaiting task is cancelled,
        nobody will ever answer this entry, and an entry nobody is waiting for that stayed at the
        head of the highest queue would wedge the terminal - it would be current forever, `pending`
        would count it forever, and the questions behind it would never reach a person. The port
        settles nothing about a cancelled `show` (the suite's gap #15 says so) and this decides only
        the part that would otherwise be a hang.
        """
        answered: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        entry = Entry(view, params, priority, answered)
        self._queues.setdefault(priority, []).append(entry)
        answered.add_done_callback(lambda _: self._retire(entry))
        return cast("Awaitable[T]", answered)

    @property
    def slot(self) -> Registration | None:
        """What a passive `show` last registered, or `None` if none ever has.

        Read directly only by tests and by `displayed`; `terminal.py` draws through `displayed`,
        which is where the fallback order lives.
        """
        return self._slot

    @property
    def current(self) -> Entry | None:
        """The question that owns the screen: head of the highest non-empty queue, or `None`.

        Derived on every read and stored nowhere, which is the module's central decision. The
        highest priority is always the current one, so a lower-priority question arriving while a
        higher one is up does not take the screen and does not need to be stopped from taking it.
        """
        busy = (priority for priority, entries in self._queues.items() if entries)
        busiest = max(busy, default=None)
        return None if busiest is None else self._queues[busiest][0]

    @property
    def displayed(self) -> Registration | None:
        """What should be on screen: the current question, else the slot, else nothing.

        The port's fallback order in the one place that owns ordering - "when it is dismissed the
        terminal falls back to the next queued question, and finally to the slot" - so `terminal.py`
        draws what this returns and never re-derives the rule. An `Entry` comes back as itself, so a
        caller that needs to know whether what is up can be answered asks `current`.
        """
        current = self.current
        return self._slot if current is None else current

    @property
    def pending(self) -> Mapping[int, int]:
        """Priority to queued count, excluding whatever is displayed, as a fresh mapping.

        The subtraction is the port's "that is displayed, not pending", and it is one entry at one
        priority because exactly one question is displayed at a time. Every priority ever queued at
        is reported, including the ones with nothing waiting, because the port makes the zeros the
        specification.

        Fresh every read, and the module docstring argues the shape: the proxy is over a new `dict`,
        so a workflow holding one while it builds a row is holding something that cannot move.
        """
        counts = {priority: len(entries) for priority, entries in self._queues.items()}
        current = self.current
        if current is not None:
            counts[current.priority] -= 1
        return MappingProxyType(counts)

    def answer(self, response: int, typed: str = "") -> None:
        """Answer the displayed question through its `response`-th response, and retire it.

        `response` indexes the displayed screen's own `responses`, in the order the view offered
        them - a position, because that is what a person picks, and because the value belongs to
        the workflow. **The answer is computed here and it is the workflow's own type**:
        `Choice.value` *is* the answer, and for a `TextInput` it is `maps(typed)`, the workflow's
        function called at the workflow's layer. A terminal that handed back the raw string would
        typecheck behind `show`'s cast and fail wherever the value was next used.

        It resolves **that** registration and no other. The entry leaves its queue first, so what
        `current` returns afterwards is already the next one - the displaced question that kept its
        place, or the one queued behind it, or the slot.

        Two things raise `InternalError`, and both are ours rather than a workflow author's: an
        answer arriving with no question displayed, and a position no response occupies.
        `terminal.py` renders the responses it got from this same screen and knows from `current`
        whether anything can be answered, so either one means our own ordering is wrong.

        A `maps` that raises is not one of them. It is workflow code, and the failure belongs to the
        `show` call that registered it: it arrives there as the exception it was, rather than
        escaping into whichever task delivered the keystroke, where it would kill the input handler
        and leave a person looking at a terminal that no longer answers and a workflow waiting on a
        future nobody will ever resolve.
        """
        entry = self.current
        if entry is None:
            raise InternalError(
                f"answered with response {response} while no question was displayed. Only the "
                f"displayed screen can be answered and the terminal knows which one that is, "
                f"so an answer arriving with nothing to answer is AGL's own ordering rather "
                f"than anything a workflow author did"
            )
        offered = entry.screen().responses
        if not 0 <= response < len(offered):
            raise InternalError(
                f"answered with response {response} on a screen offering {len(offered)}. A "
                f"response is named by its position in the order the view offered them, and the "
                f"only thing that names one is the terminal drawing that same screen"
            )
        self._retire(entry)
        if entry.answered.done():
            # Abandoned between being asked and being answered - the awaiting task was cancelled and
            # its done callback has not run yet. It is owed nothing, so the keystroke lands on
            # whatever is current when the next one arrives.
            return
        try:
            given = _given(offered[response], typed)
        # Broad on purpose: this is the workflow's own `maps`, and the docstring argues that its
        # failure belongs to the `show` call that registered it rather than to the input handler.
        except Exception as failed:
            entry.answered.set_exception(failed)
        else:
            entry.answered.set_result(given)

    def close(self) -> None:
        """Unblock every waiter, empty the queues and clear the slot. Called on the way out.

        A question outstanding when the terminal shuts down can never be answered - the display has
        been handed back and there is nobody in front of it - so every waiter is failed rather than
        left blocked, which with no timeouts anywhere on this port would be a workflow hanging on a
        terminal that no longer exists.

        `UpstreamUnavailable` is the class the port already names for "this needs a person and
        there is not one", which is exactly the state a shut-down terminal leaves a pending
        question in. It is not `InternalError`: shutting down with a question up is ordinary,
        since `__aexit__` runs on the failing paths too and the run that ends badly is the one
        most likely to have one open.

        The priorities themselves are kept. A key that has been asked for stays in `pending` at
        zero, and closing is not somebody un-asking.
        """
        for entries in self._queues.values():
            for entry in tuple(entries):
                if not entry.answered.done():
                    entry.answered.set_exception(
                        UpstreamUnavailable(
                            "the terminal shut down with this question still waiting for an "
                            "answer, so nobody can ever give one"
                        )
                    )
            entries.clear()
        self._slot = None

    def _retire(self, entry: Entry) -> None:
        """Take an entry out of its queue. Idempotent, and the only thing that removes one.

        Called from `answer` on the ordinary path and from every future's done callback on the
        others - cancellation, and `close`. Idempotence is what lets both happen for one entry, and
        membership is by identity because these classes carry `eq=False`.
        """
        entries = self._queues.get(entry.priority)
        if entries is not None and entry in entries:
            entries.remove(entry)


def _given(chosen: Response[object], typed: str) -> object:
    """What a response produces when it is picked: the workflow's own type, either way.

    The two routes to one `T`, and the whole of what this module knows about answers. A `Choice`
    carries its value - there is deliberately no key, id or index beside it, so the value is the
    only thing a caller could use. A `TextInput` carries the function, and calling it here is what
    makes `show` promise one return type across a screen offering both.

    `match` over the closed `Response` union rather than `isinstance`, so that a response kind added
    to the port is a type error here rather than a branch that silently falls through.
    """
    match chosen:
        case Choice():
            return chosen.value
        case TextInput():
            return chosen.maps(typed)
