"""The half of the contract a terminal owes whether or not it can take input, and the one fixture.

Split out of `terminal.py` because both public suites need it and neither one may inherit it from
the other. A terminal that takes input and a terminal that cannot satisfy *different* halves of this
port - one queues a question and one refuses it - but the lifecycle is not one of the halves: a
redraw loop is started and stopped, a display is taken over and handed back, and a `show` outside
the context is AGL's own ordering bug in both. So this class holds those three, and both
`TerminalContract` and `HeadlessTerminalContract` inherit it. Neither is subclassed by an
implementer; those two are.

The `terminal` fixture lives here for the same reason: one declaration, inherited by both, rather
than the same paragraph written twice and drifting.

**The lifecycle is `ports/terminal.py`'s own addition and goes beyond §3.7's stated surface**, which
is exactly why it is asserted here. §3.7 says a terminal is an async context manager and says why;
the ABC then spells out what `__aexit__` owes, and a clause written down in one implementation and
not the other is a clause the other one is free to get wrong.
"""

from collections.abc import Iterator

import pytest

from agl.ports.errors import InternalError, Stop
from agl.ports.terminal import Terminal

from ._terminal_driver import came_back
from ._terminal_views import LANDED, RUNNING, dashboard


class TerminalLifecycleContract:
    """Entering, leaving, and the two things that are true outside.

    `pytestmark` is repeated on every contract class in this package rather than inherited from one
    of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test, which is
    the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def terminal(self) -> Terminal | Iterator[Terminal]:
        """The implementation under test, **built and not yet entered**.

        Not entered, because entering it is half of what this class asserts and because two tests
        below have to call `show` from outside the context. A fixture that handed back an already
        running terminal would make both of them untestable and would hide the one call the
        framework makes before any workflow sees this object.

        Function-scoped, like every fixture in this package. These tests leave screens on the slot
        and questions in the queues, and a terminal carried between them would hand the next test
        the last one's backlog - which in this suite means the next test's `pending` is somebody
        else's.

        The return type is a union so that `mypy --strict` accepts either shape of override: return
        a terminal, or `yield` one and tear it down after. pytest takes both, and an override
        narrowing a plain `-> Terminal` to `-> Iterator[Terminal]` would not typecheck. An
        `async def` fixture (`@pytest_asyncio.fixture`) is a third shape no annotation here can
        cover; if an implementation needs one, a `# type: ignore[override]` on it is the honest
        escape and costs this suite nothing.
        """
        raise NotImplementedError(
            "the Terminal contract suite has no implementation to run against: subclass "
            "TerminalContract (a terminal that can take input) or HeadlessTerminalContract (one "
            "that cannot) and override the `terminal` fixture with a Terminal that has not been "
            "entered"
        )

    async def test_entering_starts_the_terminal_and_hands_back_one_of_its_own_kind(
        self, terminal: Terminal
    ) -> None:
        """`__aenter__` returns `Self`, so `async with build_terminal() as term` keeps the type.

        That is the whole of the promise and it is asserted as the whole of it: the object handed
        back is of the implementation's own type, not a `Terminal`-shaped wrapper that would make
        `pending` read on one object and `show` called on another. Identity is deliberately *not*
        asserted - `Self` says which type, not which object - and the gaps list says so.

        A `show` inside the context is here as the other half of the sentence. What it does differs
        between the two suites that inherit this class - one displays a dashboard, one no-ops it -
        and neither is this test's business. That it does *not* raise is, because the next test
        asserts the same call raising from outside, and two tests that both expect an exception
        would agree with an implementation that raises everywhere.
        """
        async with terminal as term:
            assert isinstance(term, type(terminal)), (
                f"entering handed back a {type(term).__name__} and the terminal is a "
                f"{type(terminal).__name__}. `__aenter__` returns Self so that the framework holds "
                f"the implementation's own type rather than a Terminal - a different object here "
                f"is a second terminal, and whichever of the two a workflow ends up with, the "
                f"other one is the one with the queues in it"
            )
            await came_back(term.show(dashboard, line=RUNNING), "a passive show inside the context")

    async def test_show_outside_the_context_is_agls_own_ordering_bug_and_not_a_workflow_authors(
        self, terminal: Terminal
    ) -> None:
        """`InternalError`, and the error class is the message: this one is ours.

        The framework opens the terminal and hands the open one to a workflow, so a `show` that
        happens outside cannot be anything an author wrote - it is our ordering that is wrong, and
        `InternalError` exits 70, which reads as "file a bug" and sends the reader to the right
        codebase. `UpstreamUnavailable` here would send them looking for a display that was never
        the problem, and returning quietly would leave a run drawing to a terminal it does not hold.

        Outside has two sides and both are asserted. Before entering is the one a test can stage;
        **after leaving is the one that actually happens**, because a workflow holding a reference
        to `run.terminal` past the end of a run is an ordinary bug and the display has been handed
        back by then. The port's sentence has no "before" or "after" in it, and this suite reads it
        as covering both - `terminal.py`'s assumptions list says so.

        A passive screen in both places, deliberately. It is the one call whose meaning inside the
        context is the same for every implementation of this port, so what it does outside is
        answered by this clause alone and not by whether the terminal can take input.
        """
        with pytest.raises(InternalError):
            await terminal.show(dashboard, line=RUNNING)

        async with terminal as term:
            await came_back(term.show(dashboard, line=RUNNING), "a passive show inside the context")

        with pytest.raises(InternalError):
            await terminal.show(dashboard, line=LANDED)

    async def test_an_exception_on_its_way_out_is_never_swallowed_and_the_terminal_still_shut_down(
        self, terminal: Terminal
    ) -> None:
        """The run that ends badly is the run whose display most needs handing back.

        Two claims in one, because they are the two halves of the same sentence. `__aexit__` runs on
        the failing path - which is the entire point of a context manager here rather than a `stop`
        somebody remembers to call - and it returns `None`, which is falsy, so the exception carries
        on out. A terminal that quietly ate a `Stop` would turn a deliberate end into a silent one:
        the CLI would exit 0, the person would be told nothing, and the run that stopped on purpose
        would look like the run that finished.

        `Stop` rather than a bare `Exception` because it is the one an implementation would most
        plausibly want to be helpful about, and because a workflow's own `Stop` subclass reaching
        the CLI is how "needs you" is told from "broken".

        That the terminal really did shut down is asserted through the port and not through anything
        an implementation reports about itself: `show` afterwards raises `InternalError`, which is
        the previous test's clause and here is the evidence that `__aexit__` ran at all.
        """
        with pytest.raises(Stop):
            async with terminal as term:
                await came_back(term.show(dashboard, line=RUNNING), "a passive show before a Stop")
                raise Stop("the workflow ended itself with a screen still up")

        with pytest.raises(InternalError):
            await terminal.show(dashboard, line=LANDED)
