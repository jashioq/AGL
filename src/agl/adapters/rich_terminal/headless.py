"""`HeadlessTerminal` - the `Terminal` nobody can answer: a board is dropped, a question refused.

The `Terminal` port with no display and no way to take input. A passive `Screen` is a no-op that
still answers `None`; a `Screen[T]` raises `UpstreamUnavailable` at the first question rather than
blocking forever on nobody. Both clauses are §3.7's and both are stated on the ABC rather than in
one implementation, "because a behaviour written down in only one implementation is a behaviour the
other one is free to get wrong" - so what this module implements is the port, and never
`RichTerminal`.

## The rule is about input, not about a TTY

§3.7 phrases it on whether the terminal **can take input**, and says why in as many words: a plain
log stream has output and no input, and the TTY wording gives it no rule at all. A run whose frames
go into a file, a run drawing nothing whatsoever, and a run on the far end of a pipe are one case
here - what they have in common is not how much they draw but that there is nobody to answer, so
the thing that varies cannot be a rendering mode. **That is why this is a class and not a flag on
the terminal that draws.**

`tests/contracts/terminal.py` argues the other half of that choice at length, and it is worth
repeating exactly where somebody would be tempted to add the flag: a `takes_input` argument would be
set by the same person who wrote the implementation, and a wrong one would *skip* the half of the
contract that applies rather than fail it. Two classes make choosing wrongly loud in both
directions - point this one at `TerminalContract` and every slot test finds nothing displayed; point
the drawing one at `HeadlessTerminalContract` and it queues the question the suite requires it to
refuse. So there is no constructor argument here that could be turned off, and headlessness is not a
value this object holds at all: it is which class the composition root built.

## Headlessness cannot change inside one context, because there is nothing to change

The port's rule is phrased on what the terminal *can do*, and one that changed its mind mid-run
would make `UpstreamUnavailable` intermittent - the worst kind of failure, since the run that fails
and the run that succeeds are the same run with different timing. Here that is structural rather
than maintained. Nothing is consulted per `show`: no field, no environment variable, no
`isatty()`, no clock, no count of how many screens have gone by. The only branch in `show` is over
`Screen.responses`, which is a property of the workflow's own screen and not of this terminal, and
the only state on the object is whether it is inside its context. A terminal that no-ops one passive
screen no-ops every one of them for the same reason a function returns the same answer twice.

## Nothing is shared with the terminal that draws

No import of `terminal.py`, `queues.py`, `_display.py`, `_render.py` or `rich`: stdlib and
`agl.ports`, and that is the whole list. This is a second implementation of one port, not a subclass
of the first and not a configuration of it - it has no queues, because nothing is ever queued; no
slot, because nothing is ever drawn; no loop, no console and no reader. Sharing machinery is how a
fake stops being an independent witness: the two are kept honest by both running
`tests/contracts/terminal.py`, and a suite run twice over one mechanism proves that mechanism
consistent rather than either implementation correct.

## This is the fake, and §1.9 is why it is held to the adapter's standard

§3.7 has the headless behaviour double as the fake, which is what makes plan target #8 - every
command runs end to end on fakes alone, no network, no git, no display - reachable at all. So the
rule the other fakes state for their own ports (`memory_store.py`, `adapters/git/fake.py`,
`shell/fake.py`) is the rule here: **wherever the port is silent, this agrees with `RichTerminal`.**
A fake more permissive than the adapter lets a workflow pass on fakes and fail in anger, and the
difference stays invisible until the day somebody drops the `--dry-run`. Two silences are settled
that way below - a `show` outside the context, and a second `__aenter__` - and each says so where it
is decided.

## What it holds: one bool, for as long as it runs

A run showing its board ten times a second for six hours and asking a hundred questions nobody can
answer leaves this object exactly as it was entered. Nothing is registered, nothing is queued,
nothing is counted and no reference to a view or its arguments outlives the call that passed them:
the `Screen` a view returns is read for its `responses` and dropped on the same line. That is not
frugality for its own sake - this is the implementation that runs unattended, and a terminal
accumulating one small thing per `show` accumulates it a few hundred thousand times a day.
"""

from collections.abc import Callable, Mapping
from types import MappingProxyType, TracebackType
from typing import Final, Self, cast

from agl.ports.errors import InternalError, UpstreamUnavailable
from agl.ports.terminal import Screen, Terminal

__all__ = ["HeadlessTerminal"]

_NOTHING_PENDING: Final[Mapping[int, int]] = MappingProxyType({})
"""What `pending` answers, always: no priority, and so no count that could ever be positive.

One shared object rather than a fresh mapping per read, which is the opposite of what `queues.py`
does and for the reason that module gives. There, `pending` builds a new `dict` every read because a
workflow puts it into a view, reads it ten times a second and iterates it while a row is built, and
a live view of a queue that moves changes under the comprehension. Here there is no queue to move:
the proxy is over a dict nothing else references and no member of this class can reach, so a
snapshot that cannot go stale is the same object every time.
"""


class HeadlessTerminal(Terminal):
    """The `Terminal` port with no display and no input: drop a board, refuse a question.

    Built by the composition root, entered by the framework, and indistinguishable from the terminal
    that draws at every point a workflow can see - which is the whole of what makes it AGL's fake.
    The module docstring argues everything it decides; what is below is how.

    `__slots__` is this class's state in full, and it is one flag, owned by the lifecycle. There is
    no field saying that this terminal is headless, because that is what the class is.
    """

    __slots__ = ("_open",)

    def __init__(self) -> None:
        """Build one. It takes no arguments, and the absence is the design rather than a shortage.

        The argument this constructor conspicuously does not have is `takes_input`, and the module
        docstring says why: a flag would be set by the party it exists to catch, and a wrong one
        would skip the half of the contract that applies instead of failing it. There is nothing
        else to pass either - no console, because nothing is drawn, and no source of keystrokes,
        because a terminal that could be given one would not be this class.
        """
        self._open = False

    async def show[T](
        self,
        view: Callable[..., Screen[T]],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        """Drop what `view` returns and answer `None`, or refuse it because nobody can answer it.

        **The dispatch is the port's own**: nothing at run time can see an annotation, so what
        decides which of the two rules applies is whether `responses` is empty. That takes one
        invocation of the view, and it is the only one there will ever be - there is no loop here to
        make a second, which is what a terminal drawing nothing owes the deployment it exists for.
        The `Screen` it returns is read for its responses and dropped on the same expression: for a
        dashboard, dropping it *is* the no-op, and there is nothing to draw it with in any case.

        **A passive screen answers `None`, and the value matters as much as the absence of an
        exception.** It is the same value `RichTerminal` returns, so a workflow showing its board on
        every pass through its loop cannot tell which terminal it holds and none of those calls is a
        branch anybody has to write. The `cast` is the one the port describes: `show` promises a
        `T`, a passive view's `T` is `None`, and no signature covering both can say so without the
        overload pair the port rejected for reasons of its own.

        **A question raises `UpstreamUnavailable`, and not `DeniedError` or `InternalError`**:
        nothing refused anything and nobody's code is wrong, the display simply could not be
        reached, which is what that class says and what its exit code 6 tells a script. Saying so at
        the first question is the whole point - there are no timeouts anywhere on this port, so the
        alternative is a step blocked indefinitely on nobody, where "stuck" and "waiting for you"
        look alike from outside.

        The message names the view and the priority because a workflow shows several questions and
        "a question could not be asked" sends its author looking through all of them. `priority`
        reaches nothing else: no queue is joined, and the port already says it means nothing for a
        screen that is not queued.

        **Outside the context this is an `InternalError` whichever kind of screen it was**, and that
        is the contract suite's gap 17 - two of this port's rules reach an interactive `show` from
        outside and nothing says which wins. The lifecycle rule is taken to win, for three reasons.
        The framework opens the terminal, so a call from outside it cannot be anything an author
        wrote, and `InternalError` exits 70, which reads as "file a bug" and sends the reader to the
        right codebase; `UpstreamUnavailable` would send them hunting for a display that was never
        the problem, on a terminal that was never going to have one. It keeps this terminal and
        `RichTerminal` answering identically for every `show` outside a context, which is the fake's
        own requirement. And the check costs nothing and precedes the invocation, so a `show` from
        the wrong place cannot reach a view at all - which matters for a view that is not as pure as
        the port asks. It is a decision and not a rule, and
        `tests/adapters/test_headless_terminal.py` records it as one.

        A view that raises comes straight out, at the workflow's own call site, exactly as it does
        from `RichTerminal`'s first invocation: there is a caller standing right there, and handing
        it the exception puts the traceback at the line that named the view and its arguments. The
        port settles nothing about a view that raises (the suite's gap 11), so this is parity with
        the sibling implementation rather than a rule either of them found.
        """
        if not self._open:
            raise InternalError(
                "`show` was called on a terminal that is not inside its context. The framework "
                "opens the terminal and hands the open one to a workflow, so a call from outside "
                "it - before it was entered, or after it was left - is AGL's own ordering rather "
                "than anything a workflow author did, and that is true of a question as much as of "
                "a dashboard: this terminal could not have answered one either way"
            )
        if view(**params).responses:
            named = getattr(view, "__name__", repr(view))
            raise UpstreamUnavailable(
                f"the view {named} asks a question at priority {priority} and this terminal cannot "
                f"take input, so there is nobody to answer it and no display it could be put on. A "
                f"workflow that needs a person genuinely cannot run this way; there are no "
                f"timeouts anywhere on this port, so the alternative to saying so now is a step "
                f"that blocks forever and a run that looks like work for as long as anybody waits"
            )
        return cast("T", None)

    @property
    def pending(self) -> Mapping[int, int]:
        """Priority to queued count: empty, on every read and for the life of the terminal.

        Nothing is ever queued here, so nothing is ever waiting on a person, so no count could be
        positive. That much the contract suite asserts. **Which priorities appear is the suite's
        gap 6 and is genuinely open**: the port says the map reports every priority the terminal has
        been asked for, and a priority it was asked for and then *refused* is exactly the case that
        sentence does not cover. This is one side of it, recorded here and pinned by a test in
        `tests/adapters/test_headless_terminal.py` rather than left for a reader to infer.

        Both readings answer 0 to `pending.get(5, 0)`, which is the number the clause exists to make
        agree across implementations, so the clause itself does not choose. Two things do. **A key
        here could never become non-zero**, and `queues.py` refuses the analogous key for a passive
        `show` with that same argument - it would tell a reader that somebody asked something, in a
        map whose entire subject is people being kept waiting, and on this terminal every key would
        be one of those forever. And **remembering a refused question is the one thing this class
        must not do**: it is what runs unattended for hours, the other reading has it accumulate a
        key per distinct priority for questions it declined at the door, and "nothing is retained"
        is easier to keep true when there is no structure to retain anything in.

        A snapshot, trivially: `_NOTHING_PENDING` wraps a dict nothing else can reach, so the
        mapping handed back cannot change afterwards and reading it again is not a different answer.
        """
        return _NOTHING_PENDING

    async def __aenter__(self) -> Self:
        """Open it, which is a no-op, and hand back this same terminal.

        "An implementation with nothing to start implements both halves as no-ops, which is honest
        rather than empty" - the port's own sentence, and this is the implementation it describes.
        There is no redraw loop to start, no display to take over and no reader to arm; what the
        flag buys is the port's other clause, that a `show` outside the context is refused.

        `Self` says which type comes back, not which object, and this one returns itself: a workflow
        and the framework hold one terminal, and the type is what `async with build_terminal() as
        term` keeps.

        **Entering twice is refused, and the port is silent about it.** `RichTerminal` refuses it
        because a second entry would start a second redraw loop and a second reader over the same
        queues; there is nothing here for a second entry to duplicate, and it is refused anyway,
        because a fake that quietly accepted an ordering bug the adapter rejects is the drift §1.9
        forbids - the dry run would pass and the real terminal would fail. Leaving and entering
        again is a different question, left alone: the suite's gap 8 says the port settles it in
        neither direction and the framework opens one terminal once.
        """
        if self._open:
            raise InternalError(
                "this terminal is already inside its context. The framework opens a terminal once, "
                "so arriving here twice is AGL's own ordering bug - and it is refused here, where "
                "there is nothing to start twice, so that a run on fakes fails it exactly where a "
                "run on a real terminal would"
            )
        self._open = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close it, which is a no-op, and return `None` so nothing on its way out is swallowed.

        There is no display to hand back and no task to stop, so what this does is the other half of
        the flag: `show` is refused from here on, which is how the port's "no further frames are
        drawn" reads for a terminal that drew none. It runs on every path out, including the failing
        ones, because that is what a context manager is for.

        **Returning `None` is falsy, so an exception in flight carries on out.** A terminal that
        quietly ate a `Stop` would turn a deliberate end into a silent one: the CLI would exit 0 and
        the run that stopped on purpose would look like the run that finished. Nothing here is
        tempted to - there is no cleanup that could fail and nothing worth reporting instead - and
        the annotation says so where a reader looks.

        The three parameters are ignored. They are here because the protocol has them, and this port
        asks nothing of them.
        """
        self._open = False
