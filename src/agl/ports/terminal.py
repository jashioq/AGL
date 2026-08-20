"""The `Terminal` port - a workflow's one way of putting something in front of a person - and the
component types its own methods speak.

`show` a view and either carry on (a dashboard) or wait for an answer (a question). `Screen`,
`Rows`, `Row`, `Text`, `Choice` and `TextInput` are what a view is built out of.

## Why the components are here and not in `sdk/`

`Terminal.show` takes a view function returning a `Screen[T]`, so `Screen` is part of this port's
own signature. Were it in `sdk/terminal.py`, beside the workflow authors who write views, this
module would have to import `sdk` and contract 1's one-way flow - `workflows` -> {`sdk`,
`adapters`} -> `ports` - would invert on its lowest edge. So they live here, and `sdk/terminal.py`
and `sdk/questions.py` are pure re-export facades holding no logic: that is how an author writes
`from agl.sdk import Screen` and never reaches into `ports`.

## Terminal-shaped, and still a port

§3.7: presentation reaches a workflow as a concrete object with terminal concepts on it, and a
future web module is `run.web`, with websocket concepts on it - a different shape, because it is a
different thing, and both can be live at once. There is deliberately no `Display` port, no
`--display` flag and no selection between kinds of display: a shared abstraction would have to be
the intersection of a terminal and a browser, which is a worse terminal and a worse browser.

Terminal-*shaped* is not terminal-*implementation*-shaped, though, and none of the second is here:
no styling, no colour, no sizes, no positions, no control codes, no notion of a screen having a
size at all. That is mechanism, and mechanism lives in `adapters/`. Here is what a view is made
of, and a view is a value.

## One coercion rule, everywhere

Anywhere a component is expected, a bare `str` means `Text`. §3.7's own example writes
`Row(t.id, t.title, Text(...))` - mixing both in one call - so the rule is the plan's; it is made
uniform here so no site is the exception a reader has to remember. Coercion happens on the way in,
so what a component *stores* is always the coerced form.

That is also why `Row`, `Rows` and `Screen` write their own `__init__` rather than take the one a
dataclass generates. A generated `__init__` accepts each field at the field's own type, and these
three accept something wider than they keep. The alternative - declare the field wide and normalise
in `__post_init__` - leaves `Screen.body` typed `str | Component` permanently, so every `match` over
it needs a `case str` arm no `Screen` can reach, and the exhaustiveness `Component` exists to give
is gone. `object.__setattr__` is how a frozen dataclass writes its own fields; `run.py` does the
same in `__post_init__`, for the same reason.

## Every component compares by value, because views are re-invoked per frame

The adapter's redraw loop calls a registered view again every frame (~10 Hz), compares the `Screen`
it returns against the last one, and writes only on a change. **That comparison is the entire
reason per-frame re-invocation is cheap** - the expensive part is the write, and the write is
skipped when nothing moved. So every type below is a frozen dataclass with value equality, and
`TextInput.maps` is excluded from that equality; its docstring is the argument, and is the
paragraph in this module most likely to be "cleaned up" by someone who has not read it.

## There is no `Timer`, and this is where it went

§1.8's charge against the previous implementation was that its terminal port shipped an entire
component tree - a UI framework masquerading as a connector - and `Timer` was part of it. §3.7
retires it: because views are re-invoked per frame, `Text(elapsed(...))` is live with no special
component at all, and `Timer(since=...)` survives only as optional sugar for smooth sub-second
ticking, "no longer the mechanism for anything". At 10 Hz a formatted string suffices. Nothing here
needs one, so nothing here has one.

## Deliberately absent

**No default view** - a workflow that shows nothing shows nothing, and duplicated screens between
workflows are accepted for the same reason as duplicated prompts. **No banner or notification
layer**: the workflow knows it is halted, so its own view says so (`board(halted=True)`), and a
second passive layer would exist to carry what one already carries. **No machine-readable form of
a run.** Part 2 rule 3 makes a second surface a second *object* - `run.web`, `run.events` - beside
`run.terminal`, not a second output mode bolted onto this one; what survives of "machine-readable
output" is that nothing above an adapter computes and shows in the same function.

**No refusals.** Every other pure type in this package checks itself in `__post_init__`; these do
not, and the difference is when they are built. A component is rebuilt by a view ten times a second
for as long as it is on screen, so a refusal here would raise inside the redraw loop, repeatedly,
against a screen already displayed, where there is no caller left to hand it to. An empty label
shows as an empty label, which its author sees the first time they look.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

__all__ = [
    "Choice",
    "Component",
    "Response",
    "Row",
    "Rows",
    "Screen",
    "Terminal",
    "Text",
    "TextInput",
]


@dataclass(frozen=True, slots=True)
class Text:
    """A piece of text on a screen. The leaf of the component tree, and the whole of it.

    It exists so that a body and a cell have one type: `Screen(body=...)` and `Row(...)` both take
    a component, and without a leaf each would instead take "a component, or else a string".

    **It carries no styling and no colour, and that is a decision rather than an omission.** A
    colour model here would do one of two wrong things: name what one kind of display can do -
    assuming an attached one, a palette, and that emphasis is a colour at all - or invent a neutral
    vocabulary of importance that nobody asked for and every implementation would then map onto its
    own. Emphasis is a property of how a thing is shown, and that is `adapters/`.
    """

    value: str
    """The text. Empty is ordinary: §3.7's own board writes `Text(... if ... else "")` for a
    ticket with no run behind it yet, and a blank cell is the honest thing to show for one."""


@dataclass(frozen=True, slots=True, init=False)
class Row:
    """One line of cells, written out one by one: `Row(t.id, t.title, Text(elapsed(t.started_at)))`.

    Varargs here and a `Sequence` on `Rows` is §3.7's asymmetry, kept deliberately rather than
    tidied into one shape, because the two are written differently at every call site that exists:
    a table's rows arrive as a comprehension over the workflow's own data, and a row's cells are
    typed out in order by someone who knows how many there are. Making `Row` take a list would put
    brackets around every row in every view to buy consistency with something nobody writes twice.

    Nothing here says how a cell is sized, how it aligns, or where the line ends. A row is what the
    workflow means; laying one out belongs to whatever is doing the drawing.
    """

    cells: tuple[Text, ...]
    """The cells, left to right, after coercion - so a `str` cell is already a `Text` by the time
    anything reads this. Empty is legal and is a blank line."""

    def __init__(self, *cells: str | Text) -> None:
        # The hand-written `__init__` a `*cells` signature requires: a dataclass field is one name
        # bound to one value and cannot be varargs, so the generated constructor cannot express
        # this. The generated `__eq__` over `cells` - the part that matters - is what is kept.
        object.__setattr__(self, "cells", tuple(_coerced(cell) for cell in cells))


@dataclass(frozen=True, slots=True, init=False)
class Rows:
    """A table: rows, in the order given, and no header, no column spec and no sort.

    A header is a `Row`, which is why there is no field for one: a caller that wants one puts it
    first, and a header field would make every implementation decide what a header means. Order is
    the caller's - a view sorts its own data before building this, within §3.7's purity rule, which
    is why "no sorting a thousand items" is a rule about views and not a field here.
    """

    rows: tuple[Row, ...]
    """The rows, in order, always a tuple - so a view that builds one by comprehension and a view
    that builds one by hand produce values that compare equal."""

    def __init__(self, rows: Sequence[Row]) -> None:
        object.__setattr__(self, "rows", tuple(rows))


type Component = Text | Row | Rows
"""Everything a screen's body can be. **A closed union, on purpose.**

An adapter can `match` this exhaustively and have `mypy` prove it covered every case, so a
component added here is a build failure in every implementation that has not learned to draw it -
which is the correct outcome, and is unavailable from a base class with an open set of subclasses.

A workflow does not add components. These are the terminal's own vocabulary, and a workflow that
wants a different shape writes a different arrangement of these three - which is also the answer
to "why so few": three is what §3.7's views are built from, and rule 6 says build the general case
on the second consumer, not the first.
"""


@dataclass(frozen=True, slots=True)
class Choice[T]:
    """One answer a person can pick, and the value picking it produces.

    `Choice("Approve", value=Approval(ok=True))`: the label is what they read, the value is what
    `show` returns. No key, no id and no index beside them, for `questions.Question.options`'
    reason - the value *is* the answer, so a second way of naming it would be a second thing to
    keep true.
    """

    label: str
    """What the person reads. Prose, in the workflow author's own words."""

    value: T
    """What `show` returns when this is picked.

    **Compared**, unlike `TextInput.maps`: it is data rather than a callable, a view re-invoked per
    frame rebuilds an equal one, and what equality means for it is the workflow's own type's to
    decide. A `T` with no `__eq__` falls back to identity and so differs every frame - that type's
    choice, made visible, and the fix is a frozen dataclass."""


@dataclass(frozen=True, slots=True)
class TextInput[T]:
    """A free-text answer, and the function that turns what was typed into the workflow's own type.

    `TextInput("Suggest changes", maps=lambda s: Approval(ok=False, feedback=s))`. The mapping is
    the workflow's, at the workflow's layer: the terminal collects a string and hands it straight
    over, and never learns what an `Approval` is.
    """

    label: str
    """What the person reads - the prompt beside the field, not the text they type."""

    maps: Callable[[str], T] = field(compare=False, repr=False)
    """What was typed, as a `T`. **Excluded from comparison, and this is the load-bearing part.**

    A view is re-invoked every frame and §3.7's own example passes `maps=lambda s: ...`, so each
    invocation builds a **fresh function object**. Two lambdas are never equal. Were this compared,
    every frame of an interactive screen would differ from the last, the diff would find a change
    that is not one, and the terminal would rewrite the screen ten times a second forever - on
    exactly the screens a human is part-way through typing into, which are the screens where
    rewriting costs the most. Excluding it is what makes the diff work at all.

    It is sound because purity is required of views (§3.7): when two frames compare equal, the two
    `maps` were built by the same function from the same arguments and are interchangeable, so the
    adapter may keep either object. A view that violates purity by returning a *different* mapping
    from the same inputs breaks here, silently, and that is the cost of the requirement rather than
    an argument against it - the same requirement already forbids I/O and store reads.

    `repr` is off for the same reading: a lambda's `repr` is its address, which changes every frame
    and would make two equal screens print differently in a log or an error message.
    """


type Response[T] = Choice[T] | TextInput[T]
"""The ways a screen can be answered: pick one of several, or type something.

Closed, for `Component`'s reason. Both produce a `T`, which is what lets `Screen[T]` promise one
return type across a mixed list of them - §3.7's approval screen offers a `Choice` and a
`TextInput` side by side and `show` returns an `Approval` either way.
"""


@dataclass(frozen=True, slots=True, init=False)
class Screen[T = None]:
    """One whole thing to show: a body, and the ways it can be answered.

    `Screen` is a dashboard and `Screen[T]` is a question - the same type, and the parameter is
    what says which. `T = None` (PEP 696) is what makes the bare spelling mean `Screen[None]`, so a
    view annotated `-> Screen` says "returns nothing" without anybody writing it out.
    """

    body: Component
    """What is on the screen, always coerced - a `str` body is a `Text` before anything reads this,
    which is what lets an adapter `match` this against `Component` and cover every case."""

    responses: tuple[Response[T], ...]
    """The ways it can be answered, in the order offered. Empty means passive, and empty is the
    runtime discriminator `show` actually dispatches on - see `Terminal.show`."""

    def __init__(self, body: str | Component, responses: Sequence[Response[T]] = ()) -> None:
        object.__setattr__(self, "body", _coerced(body))
        object.__setattr__(self, "responses", tuple(responses))


def _coerced[C: Component](value: str | C) -> Text | C:
    """The coercion rule, in the one place that performs it: a bare `str` is a `Text`. Generic so
    each site gets it back at the type it keeps - `Row` a `Text`, `Screen` a `Component` - instead
    of widening every cell to `Component` in order to share one helper."""
    return Text(value) if isinstance(value, str) else value


class Terminal(ABC):
    """Show a view; wait for an answer if the view asks for one. One method, one property, and a
    lifecycle.

    ## One slot, two queues

    This is the whole contract, and both implementations satisfy it identically:

    * A passive `Screen` goes to **the slot**: size one, replaced on write, no ordering. Ordering
      dashboards is meaningless, which is why `priority` means nothing for one.
    * A `Screen[T]` joins **a queue** at its priority, because a person answers one thing at a
      time. FIFO within a priority, so simultaneous questions from several agents stack and wait.
    * The highest-priority screen is always the one shown. When it is dismissed the terminal falls
      back to the next queued question, and finally to the slot. **The slot keeps updating while a
      question is up** - `show` re-registers the view, the terminal simply is not drawing it - so
      when the queue empties the current dashboard appears, with no extra machinery.

    **Preemption is not cosmetic.** `integrate()` leaves its target held mid-landing while a
    conflict is unresolved, so a conflict screen queued behind two agent questions would stall the
    merge queue on something unrelated. That is the entire justification for one level of it.

    **Priority is a plain `int`, default 0.** Not named levels: `MEDIUM` and `HIGH` would encode
    "agent question" and "merge conflict", which are one workflow's concepts and not the
    framework's. An int keeps the terminal comparing numbers and leaves room between levels.

    **Known and accepted** (§3.7, both of them): preemption loses text a person was part-way
    through typing, unless the implementation keeps input state per screen. And there are no
    timeouts anywhere - an unanswered question blocks its step indefinitely, so "stuck" and
    "waiting for you" look alike from outside. `pending` exists because of the second.

    ## Headless is this port's contract, not one adapter's quirk

    A terminal with no display attached **no-ops a passive screen and raises `UpstreamUnavailable`
    on an interactive one**. A workflow needing human input genuinely cannot run without a person,
    and saying so at the first question beats blocking forever on nobody. That contract is what
    lets the headless implementation double as the fake, so every command runs end to end with no
    display of any kind - and it is stated here, on the ABC, because a behaviour written down in
    only one implementation is a behaviour the other one is free to get wrong.

    ## The lifecycle, which goes beyond §3.7's stated surface

    A `Terminal` is an async context manager, and that is this module's own addition. A redraw loop
    is a task that has to be started and stopped, and an implementation that takes a display over
    has to hand it back; an ABC with no way to say "stop" would leave the framework unable to shut
    one down and would push handing the display back into an exit handler somewhere outside this
    port entirely, where nothing enforces that it runs. An implementation with nothing to start
    implements both halves as no-ops, which is honest rather than empty.

    `show` outside the context raises `InternalError`: the framework opens the terminal, so a call
    outside it is AGL's own ordering bug rather than anything a workflow author did. On exit the
    display is handed back and no further frames are drawn.
    """

    @abstractmethod
    async def show[T](
        self,
        view: Callable[..., Screen[T]],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        """Show what `view` returns, and give back what the person answered.

        **Always awaited.** A passive screen returns `None` immediately and the workflow carries on
        with the screen still up; an interactive one blocks until a person responds, and yields the
        `T` their response produced. One verb for both, because from the workflow's side both are
        "put this in front of someone".

        **The return type decides the behaviour; `responses` decides it at runtime.** `Screen` is
        passive and `Screen[T]` is interactive, but nothing at run time can see an annotation, so
        what the terminal actually dispatches on is whether `responses` is empty. The two must
        agree, and when they do not this port cannot help: a view annotated `-> Screen[Approval]`
        that returns a screen with no responses yields `None` where its caller was promised an
        `Approval`, and the failure surfaces wherever that `None` is next used. That is the view
        author's bug, it is not catchable here, and saying so is better than implying otherwise.

        **One signature, not an overload pair.** A stricter-looking pair - `priority` on the
        interactive one, absent from the passive one - could not actually reject anything, because
        `**params` swallows any keyword either way. So `priority` has no meaning for a passive
        screen rather than being forbidden by a signature unable to enforce it. The one real
        consequence: a view with a parameter literally named `priority` cannot be shown with it,
        because `**params` cannot carry a name the signature has already claimed. `view` is
        positional-only so that it, and `self`, are not two more such names.

        **The view's own parameters are unchecked, deliberately and at a cost.**
        `Callable[..., Screen[T]]` checks the return type and nothing else. A `ParamSpec` would
        check the arguments too, but a `ParamSpec` cannot coexist with a keyword-only parameter of
        `show`'s own, so checking a view's arguments and having a `priority` keyword are mutually
        exclusive in today's type system - and §3.7's surface chose `priority`. The cost is real: a
        misspelled or mistyped view argument surfaces as a failure inside the redraw loop rather
        than at this call site. It was noticed, and this is the trade.

        **`show` registers the function and its arguments, not a value.** The loop invokes the view
        again every frame, which is why arguments need not be values: passing the live dict of
        child runs works because `runs[id].activity` is evaluated again each time, and mutating an
        object in place shows up for the same reason. A workflow re-`show`s only to change *which*
        view is on screen.

        **Purity is a requirement, not a convention**: no I/O, no store reads, no sorting a
        thousand items. Ten times a second is forgiving, not free. This port cannot enforce it and
        states it anyway, because it is the only thing making the design work - and because
        `TextInput.maps`' exclusion from comparison is sound only while it holds.
        """

    @property
    @abstractmethod
    def pending(self) -> Mapping[int, int]:
        """Priority -> queued count, **excluding whatever is on screen** - that is displayed, not
        pending.

        §3.7's example is `{5: 2, 10: 0}`, and the zero is the specification: the map reports every
        priority this terminal has been asked for, not only the ones with something waiting. Said
        here because two implementations would otherwise disagree about the empty entries, and a
        workflow reading `pending.get(10, 0)` would see the same run differently on each.

        Why it exists at all: without it, three simultaneous questions mean two of them wait
        invisibly, and with no timeouts anywhere a person can walk away from a fully blocked run
        believing it is working. The workflow decides how to show it - a count in a corner, a line
        of the dashboard, nothing.

        A snapshot, and a property because it is a read of current state rather than work: the
        mapping returned does not change afterwards, and reading it again is how you see the queue
        move.
        """

    @abstractmethod
    async def __aenter__(self) -> Self:
        """Start whatever this implementation needs running, and take over the display.

        Returns `Self`, so `async with build_terminal() as term` hands back the implementation's
        own type rather than a `Terminal`. A no-op for an implementation with nothing to start.
        """

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop drawing, hand the display back, and leave the terminal usable by whatever comes
        next.

        Runs on every path out, including the failing ones - which is the point of a context
        manager here, since the run that ends badly is the run whose display most needs handing
        back. Returning `None` is a falsy result, so an exception on its way out is never
        swallowed: a terminal that quietly ate a `Stop` would turn a deliberate end into a silent
        one.

        The three parameters describe the exception in flight, if there is one. An implementation
        may ignore all three: they are here because the protocol has them, not because this port
        asks anything of them.
        """
