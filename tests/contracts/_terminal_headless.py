"""A terminal that cannot take input: a passive screen no-ops, an interactive one says so at once.

Split out of `terminal.py` because it is the half of this port a terminal with a person in front of
it must **not** satisfy. The two halves are mutually exclusive - one queues a question and waits,
one refuses it - so they are two classes rather than one class with a flag, and `terminal.py`'s
docstring argues that choice and what it protects against.

**The rule is phrased on the terminal's ability to take input, not on a TTY being attached**, and
§3.7 says why in as many words: a plain log stream has output and no input, and the TTY wording
gives it no rule at all. So a terminal writing frames into a file, a terminal writing nothing, and a
terminal on a pipe are all one case here, and it is the case where a workflow needing a person
genuinely cannot run.

**This half needs no driver, and that is the design rather than a convenience.** A terminal that
cannot take input never displays a screen anybody can answer, so there is nothing for a driver to
report and nothing for it to answer - `HeadlessTerminalContract` therefore declares only the
`terminal` fixture, and the fake that every command in AGL runs against end to end can be pointed at
this suite with no test-support machinery at all.

**That the headless behaviour doubles as the fake is why these three clauses are asserted at all.**
A fake that answered differently from the adapter would be a fake that quietly drifts into fiction,
and §3.7 puts the headless rule on the port precisely so both implementations owe it.

`HeadlessTerminalContract` in `terminal.py` inherits this class. Implementers subclass that one,
never this one, and the `terminal` fixture these tests take is declared in `_terminal_lifecycle`.
"""

from typing import Final

import pytest

from agl.ports.errors import UpstreamUnavailable
from agl.ports.terminal import Terminal

from ._terminal_driver import came_back, within
from ._terminal_views import AGENT, EARLY, LANDED, LATE, RUNNING, dashboard, question

# How many times each rule is asked for, in the test that pins the answer not changing. Three,
# interleaved, because the failure being ruled out is an answer that depends on when it was asked.
_ROUNDS: Final = 3


class HeadlessRulesContract:
    """No-op, refuse, and answer the same way every time for as long as the terminal is open.

    `pytestmark` is repeated on every contract class in this package rather than inherited from one
    of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test, which is
    the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_a_passive_screen_is_a_no_op_that_still_answers_none(
        self, terminal: Terminal
    ) -> None:
        """Nothing to show it on, nothing shown, and the workflow carries on regardless.

        A dashboard is information a person may look at, so a terminal with nobody in front of it
        drops it and says nothing about having done so. That is what lets every command in AGL run
        end to end without a display of any kind: a workflow shows its board on every pass through
        its loop, and none of those calls is a branch anybody has to write.

        The value is asserted as well as the absence of an exception, because it is the same value
        the input-capable half returns and a workflow cannot tell which terminal it holds. If one of
        them answered `None` and the other something else, "the same code runs either way" would be
        false in the one place nothing checks.
        """
        async with terminal as term:
            nothing = await came_back(
                term.show(dashboard, line=RUNNING), "a passive show on a headless terminal"
            )

            assert nothing is None, (
                f"a passive screen on a terminal that cannot take input answered with {nothing!r}. "
                f"It is dropped, and the workflow that showed it carries on with exactly what it "
                f"would have got from a terminal that drew it"
            )

    async def test_an_interactive_screen_says_upstream_unavailable_rather_than_blocking_on_nobody(
        self, terminal: Terminal
    ) -> None:
        """A workflow needing human input cannot run here, and saying so at the first question is
        the whole point.

        The alternative is blocking forever on nobody, and §3.7 rejects it in one sentence: there
        are no timeouts anywhere on this port, so a question nobody can answer blocks its step
        indefinitely and "stuck" and "waiting for you" look alike from outside. A run that stops
        immediately with a reason beats one that looks like work for as long as anybody is prepared
        to wait.

        `UpstreamUnavailable` and not `DeniedError` or `InternalError`: nothing refused anything and
        nobody's code is wrong - the display simply could not be reached, which is what that class
        says and what its exit code 6 tells a script.

        The deadline is what makes this testable at all. An implementation that queued the question
        instead of refusing it would hang here, and a suite without a bound would report that as a
        slow test rather than as the clause it broke.
        """
        async with terminal as term:
            with pytest.raises(UpstreamUnavailable):
                await within(
                    term.show(question, priority=AGENT, label=EARLY),
                    "an interactive show on a headless terminal",
                )

    async def test_headlessness_is_decided_once_for_the_terminals_lifetime_and_never_per_show(
        self, terminal: Terminal
    ) -> None:
        """Settled: this is a property of the terminal, not of the call.

        The rule is phrased on whether the terminal **can take input**, which is something a
        terminal either can or cannot do. A terminal that changed its mind mid-run would make a
        workflow's behaviour depend on *when* it asked and would make `UpstreamUnavailable`
        intermittent - the worst kind of failure, because the run that fails and the run that
        succeeds are the same run with different timing, and no amount of reading the workflow
        explains either.

        So one that no-ops a passive screen no-ops all of them, and one that raises on a `Screen[T]`
        raises on every one. Whether an implementation decides that at construction or on the way
        into the context is its own business and nothing here asks; what the contract requires is
        that the answer does not change inside one context.

        Interleaved and repeated, because the two rules are two halves of one decision: an
        implementation that consulted something per call could answer either one differently on any
        pass, and asking each of them three times with the other in between is the cheapest shape
        that would catch it.
        """
        async with terminal as term:
            for attempt in range(_ROUNDS):
                nothing = await came_back(
                    term.show(dashboard, line=RUNNING if attempt else LANDED),
                    f"a passive show on a headless terminal, attempt {attempt + 1}",
                )
                assert nothing is None, (
                    f"a passive screen was dropped quietly and then, on attempt {attempt + 1}, "
                    f"answered with {nothing!r}. What this terminal does with a screen is decided "
                    f"by whether it can take input, and that does not change while it is open"
                )

                with pytest.raises(UpstreamUnavailable) as refused:
                    await within(
                        term.show(question, priority=AGENT, label=EARLY if attempt else LATE),
                        f"an interactive show on a headless terminal, attempt {attempt + 1}",
                    )
                assert isinstance(refused.value, UpstreamUnavailable), (
                    f"attempt {attempt + 1} was refused with something other than the class the "
                    f"port names. A workflow catching UpstreamUnavailable to report that it needs "
                    f"a person catches this and nothing else"
                )

    async def test_nothing_is_ever_queued_on_a_terminal_that_refuses_every_question(
        self, terminal: Terminal
    ) -> None:
        """`pending` is real here too, and everything in it is zero.

        A terminal that refuses every `Screen[T]` has nothing waiting on a person, ever. So whatever
        priorities its map reports, no count in it is positive - and an implementation that raised
        `UpstreamUnavailable` while quietly keeping the screen would say otherwise, which is the one
        thing this can catch and the reason it is worth a test.

        **Which priorities appear is deliberately not asserted.** The port says the map reports
        every priority this terminal has been asked for, and a priority it was asked for and then
        refused is exactly the case that sentence does not settle. Both readings leave a workflow's
        `pending.get(5, 0)` answering 0, which is the number that clause exists to make agree, so
        nothing here decides it - and `terminal.py`'s gaps say so rather than leaving a reader to
        infer it from a test that is not there.
        """
        async with terminal as term:
            with pytest.raises(UpstreamUnavailable):
                await within(
                    term.show(question, priority=AGENT, label=EARLY),
                    "an interactive show on a headless terminal",
                )

            counts = dict(term.pending)
            assert all(count == 0 for count in counts.values()), (
                f"a terminal that cannot take input reports {counts} queued. Nothing here waits on "
                f"a person: the question was refused rather than accepted, and a positive count is "
                f"a workflow being told somebody is about to be asked something nobody will see"
            )
