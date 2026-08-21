"""`RichTerminal` - the redraw loop, the two halves of `show`, and a person at the keyboard.

The `Terminal` port over a real console. `queues.py` holds the slot and the queues and decides
*what* should be on screen; `_render.py` turns a `Screen` into something `rich` can draw;
`_display.py` owns the console it is drawn on. This module is the one that runs: it starts the
loop, invokes the registered view every frame, diffs, writes when something moved, reads what
somebody typed, and hands the display back on the way out.

## The loop, and why the diff is the whole design

§3.7: `show` registers the view function **and its arguments**, and the loop calls it again every
frame (~10 Hz), compares the `Screen` it returns against the last one, and writes only on a change.
Per-frame invocation is chosen over change detection because change detection would mean this
package knowing when a `Run`'s activity mutated, when a field was assigned, when a dict gained a
key - observable wrappers or dirty flags pushed into data a workflow owns. Calling the function
again needs none of that.

**The diff is what makes that affordable.** Invoking a view is a function call; writing to a
terminal is the expensive part, and the write is skipped when nothing moved. That is the entire
reason `Screen` and every component below it is a frozen dataclass with value equality, and the
reason `TextInput.maps` is excluded from that equality: a view rebuilds its `maps` lambda every
frame, two lambdas are never equal, and comparing it would report a change that is not one on
exactly the screens somebody is part-way through typing into.

**Purity is the view author's side of that bargain and this adapter does not police it.** The port
requires it, says it cannot enforce it, and says why. Nothing here deep-copies an argument, wraps
one, or checks whether one moved: a workflow passing the live dict of child runs is the mechanism
working as designed, and `runs[id].activity` being read again on every invocation is the whole
point.

**~10 Hz is a choice, not a promise.** It is a constructor argument with a default, the contract
suite encodes no frame rate anywhere, and a terminal redrawing once a second would be slower rather
than wrong.

## Single-threaded asyncio, one lock nowhere

The loop is another task on the workflow's own event loop. Neither it nor workflow code yields
part-way through building or reading a screen, so a half-updated backlog cannot be observed and
nothing here takes a lock over the queues. The one place a thread is genuinely required is the
blocking read of a keystroke, which is why `Keys` exists and why it is reached through
`run_in_executor` rather than called inline: a `read()` on the event loop would stop every frame,
every workflow step and every agent in the process until somebody pressed a key.

## What `show` dispatches on

**The return annotation says which kind of screen it is; what is dispatched on at run time is
whether `responses` is empty.** Nothing at run time can see an annotation, so `show` invokes the
view once to find out, and that invocation is the same one the loop makes ten times a second - the
purity the port requires is what makes an extra one free. A passive screen goes to the slot and
`show` returns `None` at once, *including while a question is displayed*, so a workflow updating
its board behind a question it is itself blocked on does not deadlock. An interactive screen joins
a queue at its priority and `show` blocks until somebody answers it.

A view that raises **at that first invocation** raises out of `show`, at the workflow's own call
site, because that is where the caller is and it is the one moment there is one. A view that starts
raising later - the ordinary case, since a view is invoked again forever - becomes an error frame
instead: the loop cannot hand an exception to anybody, and a repaint task that died on one is a
screen that silently stops updating.

## The input convention, in one paragraph, because it is a decision and not a standard

**Every response is numbered from 1, in the order the view offered them; a person types the number
and presses Enter.** If the response they picked is a `TextInput`, the terminal takes the screen -
the live region steps aside, because a person typing into one cannot see what they are typing - and
reads a second line, which is what they typed, verbatim. Anything else is ignored and the frame
stays up: a blank line, a word, a number no response occupies. A person mistyping at a terminal is
ordinary, and `queues.answer` reserves `InternalError` for an answer AGL itself misrouted.

`Choice.value` **is** the answer and a `TextInput`'s is `maps(typed)` - the workflow's own function,
called at the workflow's layer. Both are already `queues.answer`'s work. What this module does is
get a person's gesture to it, and it never learns what an `Approval` is.

**Where the keystrokes come from is injectable** (`Keys`), because a terminal whose input can only
come from a tty is a terminal no test can drive and no other front end can reuse. The default reads
`sys.stdin`.

## Handing the display back is guaranteed twice over

`__aexit__` stops the loop, unblocks every waiter through `queues.Screens.close`, and stops the
display - in a `finally`, so the last of those happens even if the first two fail. It returns
`None`, which is falsy, so an exception on its way out is never swallowed: a terminal that quietly
ate a `Stop` would turn a deliberate end into a silent one.

That the display is stopped on every path matters for a second, independent reason, argued in
`_display.py`: `rich.Live` replaces the process-global `sys.stdout` and `sys.stderr` while it is up,
and only `Live.stop()` puts them back. A run that skipped it would leave every later traceback in
the process going to a console whose live region no longer exists.

`show` outside the context raises `InternalError` on both sides of it - before `__aenter__` and
after `__aexit__`. The framework opens the terminal, so a call outside it is AGL's own ordering bug
rather than anything a workflow author did.
"""

import asyncio
import select
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import Final, Self, cast

from rich.console import Console
from rich.text import Text as RichText

from agl.adapters.rich_terminal._display import Display, display_for
from agl.adapters.rich_terminal._render import frame
from agl.adapters.rich_terminal.queues import Registration, Screens, View
from agl.ports.errors import InternalError
from agl.ports.terminal import Screen, Terminal, Text, TextInput

__all__ = ["Keys", "RichTerminal", "StdinKeys"]

FRAMES_PER_SECOND: Final = 10.0
"""§3.7's ~10 Hz, as this package's default and not as a promise. Named here so the number a
deployment gets and the number an argument overrides are the same one."""

_POLL: Final = 0.05
"""How long `StdinKeys` waits on the keyboard before looking at whether it has been stopped. It is
what makes a read abandonable: see `Keys.stop`."""


class Keys(ABC):
    """Where a person's keystrokes come from. One line at a time, and a way to give up waiting.

    A terminal that could only read a tty is a terminal no test can drive without one, so this is
    a constructor argument. It is deliberately the smallest thing that would do - lines, not
    keypresses, not modes, not an editing model - because the input convention is "type a number,
    press Enter" and a richer source would be a promise this package has nothing to make good on.

    **Implementations block, and are called on a thread**, never on the event loop. `stop` is what
    makes that safe: see its docstring for the shutdown this port exists to avoid.
    """

    @abstractmethod
    def read(self) -> str | None:
        """Block until a whole line has been typed, and return it without its line ending.

        `None` means there will never be another one: the input ended, or `stop` was called. A
        terminal that gets one stops reading - it does not spin, and it does not treat the end of
        input as an answer to whatever was on screen.
        """

    @abstractmethod
    def stop(self) -> None:
        """Abandon any read in progress and make every later one return `None` at once.

        **This is what keeps a shutdown from being held hostage by a read nobody will satisfy.**
        Cancelling the asyncio task waiting on a read returns control to `__aexit__` immediately,
        but the thread the read is on is still sitting in it, and a thread pool's workers are
        joined when the interpreter exits - so a `read()` that blocks forever is a process that
        never quite finishes, long after the terminal was handed back. An implementation that
        cannot interrupt its own read polls instead, which is what `StdinKeys` does.
        """


class StdinKeys(Keys):
    """The default: whole lines from this process's own standard input.

    `sys.stdin` is read through on every call rather than captured at construction, because a
    process that replaced its own - a harness, a wrapper - meant the replacement to be read.
    `rich.Live` redirects `stdout` and `stderr` and never `stdin`, so nothing this package does
    moves it underneath.

    **It polls rather than blocking outright**, and that is the whole of what is unusual here.
    `readline()` on a tty blocks until somebody presses Enter and there is no portable way to
    interrupt one, so a shutdown with a question on screen would wait on a person who has walked
    away. `select` with a short timeout, around a flag, turns "cancel this" into a wait of at most
    `_POLL` - and costs one syscall twenty times a second on a process that is already drawing ten
    frames in the same time.
    """

    __slots__ = ("_stopped",)

    def __init__(self) -> None:
        self._stopped = threading.Event()

    def read(self) -> str | None:
        """A line from standard input, or `None` at end of input, on error, or once stopped.

        An unreadable stdin - closed, or replaced by something with no file descriptor - is `None`
        rather than an exception: this runs on a worker thread where an exception would kill the
        reader, and a process with no usable input is a process nobody can answer a question on,
        which is a state the port already has a shape for (the question simply waits, and
        `Screens.close` fails it on the way out).

        That branch is also where a platform whose `select` cannot poll a console handle lands -
        Windows, which AGL does not currently claim to run on. There it reads as "no input", which
        is honest for this implementation and wrong for the machine; the fix is another `Keys`
        rather than anything here, which is what the seam is for.
        """
        while not self._stopped.is_set():
            stream = sys.stdin
            try:
                ready, _, _ = select.select([stream], [], [], _POLL)
            except (OSError, ValueError):
                return None
            if not ready:
                continue
            typed = stream.readline()
            if not typed:
                return None
            return typed.rstrip("\r\n")
        return None

    def stop(self) -> None:
        self._stopped.set()


class RichTerminal(Terminal):
    """The `Terminal` port over a `rich` console: one slot, two queues, a redraw loop and a reader.

    Built by the composition root and entered by the framework. Everything it decides is argued in
    the module docstring; what is below is how.
    """

    __slots__ = (
        "_console",
        "_display",
        "_keys",
        "_open",
        "_period",
        "_reads",
        "_screens",
        "_taken",
        "_tasks",
        "_written",
    )

    def __init__(
        self,
        console: Console | None = None,
        keys: Keys | None = None,
        *,
        frames_per_second: float = FRAMES_PER_SECOND,
    ) -> None:
        """Build one. Nothing is started and nothing is written until `__aenter__`.

        The console is a `rich.Console` because that is what this adapter draws on, and passing one
        is how a caller decides where frames go - a tty, a file, a buffer a test can read. The
        default is rich's own, which is standard output.
        """
        self._console = Console() if console is None else console
        self._keys = StdinKeys() if keys is None else keys
        self._period = 1.0 / frames_per_second
        self._screens = Screens()
        self._display: Display = display_for(self._console)
        self._written: Screen[object] | None = None
        self._open = False
        self._taken = False
        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._reads: ThreadPoolExecutor | None = None

    @property
    def written(self) -> Screen[object] | None:
        """The screen this terminal last **wrote**, or `None` if it has written none.

        Set at the write call site in `_draw`, after the diff has decided the frame changed; the
        only other lines that touch it clear it, because the screen was taken or handed back. It is
        the diff's own baseline, which is what makes it worth reading: there is one record, so a
        screen this reports is a screen that reached the display, and a write wrongly suppressed
        goes stale here rather than being papered over by a second record derived on demand.

        It is what `tests/adapters/test_rich_terminal.py`'s driver answers `displayed()` with, and
        the contract suite says out loud that a driver is written by the party it exists to catch -
        so the point of deriving nothing here is that a terminal which never wrote reports `None`
        and fails everything, rather than reporting what it would have shown if asked.
        """
        return self._written

    async def show[T](
        self,
        view: View[T],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        """Show what `view` returns; give back what the person answered, or `None` at once.

        The dispatch is the module docstring's: the view is invoked once, and a screen with no
        responses is a dashboard. `priority` reaches the queue and means nothing for the slot,
        which is why `Screens.hold` takes no such argument.

        The `cast` on the passive path is the one the port describes: `show` promises a `T` and a
        passive view's `T` is `None`, which no signature covering both can express without an
        overload pair the port rejected for reasons of its own.
        """
        if not self._open:
            raise InternalError(
                "`show` was called on a terminal that is not inside its context. The framework "
                "opens the terminal and hands the open one to a workflow, so a call from outside "
                "it - before it was entered, or after the display was handed back - is AGL's own "
                "ordering rather than anything a workflow author did"
            )
        if view(**params).responses:
            return await self._screens.queue(view, priority=priority, **params)
        self._screens.hold(view, **params)
        return cast("T", None)

    @property
    def pending(self) -> Mapping[int, int]:
        """Priority to queued count, excluding what is displayed. The queues' own snapshot."""
        return self._screens.pending

    async def __aenter__(self) -> Self:
        """Take the console over and start the two tasks: the redraw loop and the reader.

        Two rather than one, because they wait on different things. The loop sleeps a frame at a
        time and must keep drawing while somebody stares at a question; the reader spends most of
        its life blocked on a keystroke. Folding them together would mean either a loop that stops
        redrawing whenever a question is up - and a live argument that grew a response would never
        reach the screen - or a read that has to be re-armed every frame.
        """
        if self._open:
            raise InternalError(
                "this terminal is already inside its context. Entering twice would start a second "
                "redraw loop and a second reader over the same queues, and the first pair would "
                "keep drawing after the terminal was handed back - the framework opens a terminal "
                "once, so arriving here twice is AGL's own ordering bug"
            )
        self._display.start()
        self._reads = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agl-terminal-keys")
        self._open = True
        self._tasks = (
            asyncio.create_task(self._redrawing()),
            asyncio.create_task(self._answering()),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop drawing, unblock everyone waiting, and hand the console back. Returns `None`.

        The order is the one that leaves nothing running: `show` is refused first so nothing new
        arrives, the reader's source is told to give up so its thread is not left in a `read()`
        nobody will satisfy, both tasks are cancelled and awaited, the pool is dropped without
        waiting on it, and every outstanding question is failed rather than left blocked on a
        display that no longer exists.

        Stopping the display is in a `finally` because it is the step whose omission outlives the
        run: `sys.stdout` and `sys.stderr` are rich's while a live region is up, and nothing else
        in the process puts them back.

        The three parameters are ignored. They are here because the protocol has them, and no
        exception on its way out changes what any of the above has to do.
        """
        self._open = False
        try:
            self._keys.stop()
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks = ()
            if self._reads is not None:
                self._reads.shutdown(wait=False, cancel_futures=True)
                self._reads = None
            self._screens.close()
        finally:
            self._display.stop()
            self._written = None

    async def _redrawing(self) -> None:
        """The loop: draw, sleep a frame, repeat, until it is cancelled.

        Sleeping between frames rather than after a change, so that a live argument mutated by
        workflow code reaches the screen without anybody telling this task about it - which is the
        clause that makes `Text(run.activity)` live with no special component and no notification.
        """
        while True:
            self._draw()
            await asyncio.sleep(self._period)

    def _draw(self) -> None:
        """One frame: invoke the registered view, diff, and write only if something moved.

        **The write site.** `self._written` is assigned a screen here and in no other line of this
        package, immediately after the display has been handed that frame - which is what makes it
        a record of what was drawn rather than of what would be. The only other two places that
        touch it clear it to `None`, and both of them are un-drawings: `_typed`, which takes the
        screen away to read a line, and `__aexit__`, which hands the console back. `None == None`
        is what makes "nothing was displayed and nothing is displayed" a non-event; a `Screen`
        never compares equal to `None`.

        Nothing here catches a failed *write*. A view that raises is workflow code and expected to
        be wrong sometimes, so it becomes a frame (see `_screen_of`); a `rich` that cannot draw at
        all is our bug and will not draw the second time either, and a loop that retried it would
        produce ten failures a second for as long as the run lasted.
        """
        if self._taken:
            return
        registration = self._screens.displayed
        screen = None if registration is None else self._screen_of(registration)
        if screen == self._written:
            return
        self._display.write(None if screen is None else frame(screen))
        self._written = screen

    def _screen_of(self, registration: Registration) -> Screen[object]:
        """Invoke a registered view, and turn a view that raised into a screen saying so.

        The contract suite's gap 11 says the port settles nothing about a view that raises, so this
        is a decision rather than an implementation of a rule. The alternatives were letting it
        kill the redraw task - a screen that silently stops updating, and the failure surfacing
        nowhere at all - or swallowing it and drawing the last good frame forever, which is the
        same thing with the evidence removed. A frame that says which view failed and how is the
        only one of the three a person can act on.

        It is a `Screen` like any other, so it goes through the diff like any other: the same
        failure every frame is one write, because two `Text`s of the same message are equal.
        """
        try:
            return registration.screen()
        except Exception as failed:
            named = getattr(registration.view, "__name__", repr(registration.view))
            return Screen(Text(f"the view {named} could not be drawn: {failed!r}"))

    async def _answering(self) -> None:
        """The reader: while there is a question on screen, read a line and try to answer with it.

        Reading is gated on there being something answerable, so keystrokes at a dashboard are left
        in the terminal's own buffer rather than swallowed by a reader that has nothing to do with
        them. The gate is polled at the frame period, which is the same order as the time it takes
        a person to notice the question appeared.

        The loop ends when the source says there will be no more input. There is deliberately no
        fallback for that: a run whose input ended cannot be asked anything, its questions wait as
        the port says they do, and `Screens.close` fails them when the terminal shuts down.
        """
        while True:
            if self._screens.current is None:
                await asyncio.sleep(self._period)
                continue
            line = await self._read()
            if line is None:
                return
            await self._answer(line)

    async def _answer(self, line: str) -> None:
        """Turn one typed line into an answer to whatever is on screen now, or ignore it.

        **Whatever is on screen now**, and not whatever was on screen when the read started: a
        question can be preempted while somebody is looking at it, and the answer belongs to what
        they were looking at when they pressed Enter. That is also why the entry is re-read after a
        text field is typed into and the answer dropped if it changed - §3.7 accepts losing
        part-typed text to preemption, and delivering it to the question that took the screen would
        be worse than losing it.

        Everything a person could type that is not a response on that screen is ignored, which is
        argued in the module docstring: `Screens.answer` raises `InternalError` for a position no
        response occupies, and a mistype is not AGL's ordering bug.
        """
        entry = self._screens.current
        if entry is None:
            return
        offered = self._screen_of(entry).responses
        position = _position(line, len(offered))
        if position is None:
            return
        typed = ""
        picked = offered[position]
        if isinstance(picked, TextInput):
            read = await self._typed(picked)
            if read is None:
                return
            typed = read
        if self._screens.current is entry:
            self._screens.answer(position, typed)

    async def _typed(self, field: TextInput[object]) -> str | None:
        """Take the screen, prompt with the field's own label, and read what was typed.

        Reading free text takes the whole display because a person typing into a live region cannot
        see what they are typing - the next frame is drawn over it ten times a second. So the
        region steps aside, the prompt and the typing are ordinary console output above where it
        was, and the loop is held off for the duration.

        `self._written` is cleared on the way out, before the display is resumed: the screen was
        taken, so the next frame is new however much it looks like the one before, and a diff still
        holding the frame from before the read would decide not to redraw the thing it just
        scrolled off. It is the one place that record is written outside `_draw`, and it is written
        to `None` - "nothing is on the display" - rather than to a screen nobody wrote.
        """
        self._taken = True
        self._display.release()
        try:
            self._console.print(RichText(f"{field.label}:"))
            return await self._read()
        finally:
            self._written = None
            self._display.resume()
            self._taken = False

    async def _read(self) -> str | None:
        """One line from the keys, on a worker thread, so a blocking read never stops the loop.

        `run_in_executor` over a pool this terminal owns and drops without waiting on, rather than
        the default one: `asyncio.run` waits for the default executor's threads on the way out, so
        a read nobody answers would hold up the process long after the terminal was handed back.
        Between that and `Keys.stop`, a shutdown never waits on a keystroke.
        """
        reads = self._reads
        if reads is None:
            return None
        try:
            return await asyncio.get_running_loop().run_in_executor(reads, self._keys.read)
        except RuntimeError:
            # The pool was shut down between the check above and the submission - the terminal is
            # on its way out, and there is no line coming.
            return None


def _position(line: str, offered: int) -> int | None:
    """The 0-based response a typed line names, or `None` if it names none.

    The one translation between what a person reads and what the port counts: responses are drawn
    numbered from 1 by `_render`, and `Screen.responses` is indexed from 0. Both spellings exist in
    exactly one place each, which is here and there.
    """
    picked = line.strip()
    if not picked.isdigit():
        return None
    position = int(picked) - 1
    return position if 0 <= position < offered else None
