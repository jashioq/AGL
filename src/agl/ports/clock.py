"""`Clock` - the only source of the current time.

Reading the current time is an input from outside the process, exactly as reading a repository or
running an agent is, and it gets a port for the same reason those do: so the framework can be
handed a different one. Two things want that. §3.6 stamps every step entry with `at`, and a test
that asserts what was recorded has to know what the answer will be; and the harness workflow
authors test against (`sdk/testing.py`) has to be able to produce a run that is identical twice.

**`at` is never read for control flow.** §3.6 says so where it defines the entry - `at` is for
debugging and for the view - and that is what makes an injected clock safe rather than a hole. A
fake clock changes what is written down and cannot change what happens: replay compares
fingerprints, restores recorded heads and branches on step results, and no decision anywhere reads
a timestamp back. If one ever did, this port would become the way to make a run behave differently
on a Tuesday.

## Aware, never naive

`now()` returns an aware datetime. `RunSpec.created_at` refuses a naive one outright - see
`_normalised` in `ports/run.py`, which refuses it *before* calling `astimezone`, because
`astimezone` on a naive value quietly reads the machine's local timezone and so turns a hidden
input into a stored one. A clock whose reading ends up in that record has to meet the same bar, or
the refusal lands at the far end of a run from the implementation that caused it.

The offset itself is not this port's business: every aware spelling denotes one instant, and
`RunSpec` normalises to UTC and truncates to whole seconds because whole seconds is what its wire
form can hold. Restating "UTC" here would be a second rule free to drift from the one in `run.py`,
and restating "whole seconds" would forbid an implementation from being more precise than the one
record that happens to store its output.

## Sync, not async

Reading a clock waits for nothing. An awaitable `now()` would put an `await` at every call site and
buy exactly nothing: there is no implementation of this that does I/O, and leaving room for one
costs a keyword everywhere a moment is stamped.

## Considered and excluded

**A monotonic reading.** Nothing in v1.1 measures elapsed time. The view formats an interval from a
moment it captured itself, and §3.7 has no timeouts anywhere. A second member would exist to be
faked and for nothing else, and the two readings would then need a documented relationship that
nobody has a use for.

**Any sleep or schedule member.** Waiting belongs to the event loop, which already has it, and a
port that owned waiting would be an invitation for a workflow to await on framework time - which
is the one thing the rule below forbids.

## Not on the `Run` surface, deliberately

§3.6 places exactly one rule on workflow authors: **branch only on step results**.
`if datetime.now().hour < 18` breaks replay, because the resumed run reads a different hour and
takes a different branch while the recorded entries say otherwise. The property test at stage 11 -
run to completion, kill at every step boundary, resume, assert identical final state - exists to
catch precisely that. So this is the framework's clock, injected into the framework's own stamping
of `at`, and there is deliberately no accessor for it on the object a workflow is handed.
"""

from abc import ABC, abstractmethod
from datetime import datetime

__all__ = ["Clock"]


class Clock(ABC):
    """The current time, and nothing else.

    An ABC with one method rather than an alias for `Callable[[], datetime]`, because this is a
    service the container builds and puts in the bundle beside the others: a named type is what a
    call site reads, what `mypy --strict` names when it disagrees, and what a fake has somewhere
    to hang its contract on. The saving from an alias would be one class statement.
    """

    @abstractmethod
    def now(self) -> datetime:
        """The current moment, as an aware datetime.

        **Aware, always.** A naive value is a wall-clock reading with no place, and the record
        this feeds refuses one (`RunSpec.created_at`). Any offset will do; UTC is not required
        here, because normalising is `run.py`'s job and every aware spelling denotes one instant.

        **Nothing is promised about two readings.** They may be equal, and under a frozen clock
        they always are - which is what makes a frozen clock an honest implementation of this
        rather than one that merely compiles. Nor are they promised to increase: a system clock
        steps backwards when something adjusts it, and nothing in AGL compares two of these to
        each other. Anything that needed an ordering would need a monotonic source, which this
        port deliberately does not have.
        """
