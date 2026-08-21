"""Where a frame actually goes: the console, and the two ways one can be put on it.

`terminal.py` decides *when* to write - it invokes the view, diffs the result and skips the write
when nothing moved - and this module is what it writes *to*. Split off because owning a `rich.Live`
is a separate idea from owning a redraw loop, and because there are two of these and only one loop:
a console that can animate redraws in place, and one that cannot has frames appended to it as they
change.

## Two implementations, chosen by rich's own test

`console.is_terminal and not console.is_dumb_terminal` is the condition `Live.refresh` itself
branches on, and it is used here so that this package's answer to "will anything animate" is the
same as the library's. Nothing else is consulted - not `isatty` on the file, not `TERM` directly,
not a flag on the terminal - because a second test that disagreed with rich's would mean writing
frames through a `Live` that renders none of them.

**The appending display is a real deployment and not a test artefact.** §3.7 phrases the headless
rule on input rather than on "no TTY attached" precisely because a plain log stream has output and
no input; a run whose output is redirected to a file is that log stream, and it gets every frame
that changed, one after another, which is exactly what a log wants.

## `auto_refresh=False`, and it is load-bearing

`Live`'s default is `True`, and `Live.start()` then spawns a `_RefreshThread` that calls
`refresh()` on its own schedule. That thread would be a second writer to the display, racing the
asyncio redraw loop that this package's whole design rests on being the only one - and it would
redraw frames the diff had already decided not to write. So it is turned off and the cadence is
owned by `terminal.py`, which is where the frame rate is a decision somebody made.

`transient=False`, the default, is kept deliberately: the last frame of a run is worth keeping on
screen. A transient `Live` erases its region on the way out, so a run that ended with a board
showing what it did would end by wiping it.

## The redirects stay on, and `stop()` is what makes that safe

`Live` takes `redirect_stdout=True` and `redirect_stderr=True` by default, and `start()` -
whenever the console is a terminal - replaces the process-global `sys.stdout` and `sys.stderr`
with a `FileProxy` routing writes through the console. That is rich's own mechanism for the
interleaving problem: without it, anything that writes to stderr while a live region is up lands in
the middle of the frame and scrambles it. Both are left on, because turning them off would leave a
stray `print` or a warning corrupting the display and there is nothing else in the process that
would stop it.

The obligation that buys is `stop()`, which calls rich's `_disable_redirect_io` and puts the two
streams back. **It has to run on every path out**, including the failing ones: a `Live` that is
never stopped leaves `sys.stderr` as a `FileProxy` pointing at a console whose live region is gone,
for the rest of the process, and every traceback after that goes somewhere nobody is looking.
`Terminal.__aexit__` already runs on every path for the port's own reason - the display is handed
back - and this is a second, independent reason for it. `tests/adapters/test_rich_terminal.py`
asserts the two streams are the same objects after a run as before it, on both paths.
"""

from abc import ABC, abstractmethod

from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text as RichText

__all__ = ["Display", "display_for"]

_NOTHING: RenderableType = RichText("")
"""What an empty display holds. A `Live` cannot be shown nothing - it renders whatever it was last
given - so "nothing is displayed" is written as an empty renderable rather than left as the last
frame of a screen that has since been answered."""


class Display(ABC):
    """A console that frames are put on, started and stopped, and briefly handed back.

    Five members and no state a caller can read. In particular there is no "what is on screen"
    here: the record of what was last written lives on the terminal beside the diff that decided to
    write it, because those two are the same fact and keeping them in one place is what makes a
    suppressed write show up as a stale screen instead of as two records disagreeing.
    """

    @abstractmethod
    def start(self) -> None:
        """Take the console over. Called once, from `Terminal.__aenter__`."""

    @abstractmethod
    def write(self, frame: RenderableType | None) -> None:
        """Put a frame on the console, or `None` to show nothing at all.

        Called only when the redraw loop's diff has decided something changed, so this never has to
        ask whether the write is worth making.
        """

    @abstractmethod
    def release(self) -> None:
        """Give the console back for as long as somebody is being read from.

        Reading free text takes the whole screen: a person typing into a live region cannot see
        what they are typing, because the next frame is drawn over it. So the display steps aside,
        the prompt and the typing are ordinary console output, and `resume` puts it back.
        """

    @abstractmethod
    def resume(self) -> None:
        """Take the console back after a read. The caller resets its own last-frame record first -
        the screen was taken, so the next frame is new however much it looks like the one before."""

    @abstractmethod
    def stop(self) -> None:
        """Hand the console back for good, restoring anything `start` took over."""


class Animating(Display):
    """A console that redraws in place, through one `rich.Live` this class owns for its lifetime."""

    __slots__ = ("_live",)

    def __init__(self, console: Console) -> None:
        self._live = Live(console=console, auto_refresh=False, transient=False)

    def start(self) -> None:
        """`refresh=False`, because there is nothing to show yet: the first frame arrives when a
        workflow shows a view, and refreshing here would draw an empty region above it."""
        self._live.start(refresh=False)

    def write(self, frame: RenderableType | None) -> None:
        """One update, one refresh, and the refresh is the only one this display ever performs."""
        self._live.update(_NOTHING if frame is None else frame, refresh=True)

    def release(self) -> None:
        """Stop the live region, which prints its last frame and leaves it above the prompt.

        `Live.stop` is idempotent, so a display released twice is released once, and stopping one
        that was already released is not an error - which is what makes `stop` on the way out safe
        whatever the input was doing when the run ended.
        """
        self._live.stop()

    def resume(self) -> None:
        self._live.start(refresh=False)

    def stop(self) -> None:
        self._live.stop()


class Appending(Display):
    """A console that cannot animate: every frame that changed is printed under the last one.

    No `Live` at all, and that is deliberate rather than an omission. `Live.refresh` on a
    non-terminal console does nothing while it is started - it renders only on the way out - so a
    `Live` here would swallow every frame and print one at the end. A file gets what a file can
    use: the frames that differed, in order.

    Nothing is redirected either, because nothing was taken over: `sys.stdout` and `sys.stderr` are
    left exactly as they were, which is correct for a stream that is already a file somebody else
    is appending to.
    """

    __slots__ = ("_console",)

    def __init__(self, console: Console) -> None:
        self._console = console

    def start(self) -> None:
        """Nothing to take over."""

    def write(self, frame: RenderableType | None) -> None:
        """Print the frame. `None` prints nothing: an empty line would be a frame in the log
        saying a screen was answered, which is a thing nothing asked to be written down."""
        if frame is not None:
            self._console.print(frame)

    def release(self) -> None:
        """Nothing is animating, so nothing has to step aside for a prompt."""

    def resume(self) -> None:
        """See `release`."""

    def stop(self) -> None:
        """Nothing was taken over, so there is nothing to hand back."""


def display_for(console: Console) -> Display:
    """Which of the two a console gets, by rich's own animation test. The one place that decides."""
    if console.is_terminal and not console.is_dumb_terminal:
        return Animating(console)
    return Appending(console)
