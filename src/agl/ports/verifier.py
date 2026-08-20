"""`Verifier` - the build gate, and why one call site still earns a port.

Run the project's build command somewhere and say whether it passed. That is the whole of it: one
method, one answer the framework branches on, and two more fields carried so that a person looking
at a failure can see what actually happened.

## One consumer, and a port anyway

There is exactly one call site in the framework, inside `integrate()` (§3.4). **The framework runs
exactly one build: the gate.** It is serial because the queue in front of it serialises it, and it
has to be - it tests a combined state that exists only momentarily, so if something else lands
mid-build the tree that was verified is not the tree being decided about and a failure cannot be
attributed to anything. It is also the only thing that catches the semantic conflict, where two
pieces of work each pass alone, combine with no textual collision, and the combination is broken.

A single consumer is normally an argument *against* a port, so §3.5 makes the argument for one and
it is worth restating where the port lives. AGL has exactly four sensors on the target repository,
all of them out-of-process: the repository's own state, file reads, this outcome, and whatever an
agent reports through a tool. **This is the only channel for "is this code actually good."** It is
necessarily out-of-band - the thing being asked cannot be trusted to answer about itself - and the
useful implementations vary: one that runs the command on this machine, one that runs it in an
isolated image, one that hands it to a service that runs it elsewhere and waits. Several are
expected, plus a fake.

§1.7 is the defect being fixed, and it is a short one. The previous build gate was a closure over a
raw command runner, reached from the runtime layer - no port, no boundary, nothing to substitute. A
build could therefore only ever be one thing, on this machine, in this process tree. Nothing above
was written wrong; there was simply nowhere for a second implementation to go.

## Agent self-verification is not modelled here, and must not be

A reader will notice that agents run tests constantly and wonder where those runs are. They are not
here and they are not anywhere (§3.4). An implementation agent doing test-driven work runs the suite
in its own workspace through its own tools, as often as its loop requires, and the framework never
sees, counts or schedules those runs - exactly as it does not track the agent's file writes. They
are **unbounded by design**: an agent must never wait for permission to check its own work. The only
thing that limits them is the workflow's `concurrent` knob, which is what that knob is for.

Giving them a port would mean the framework counting something it cannot observe, and would put a
second meaning on this type - "the gate said no" and "an agent's own run said no" are not the same
event and only one of them decides anything.

## There is no timeout parameter

Decided, not forgotten. The deadline is project configuration - `build_timeout`, sitting beside
`build` in the project's settings - so it is a property of the project, the same for every call, and
it reaches an implementation where implementations are configured: the composition root builds this
port with whatever it needs, exactly as it builds every other one. A parameter would put one
unvarying number on every call site (there is one), and would hand an implementation whose far side
enforces its own deadline a value it could only ignore. What a deadline expiring *means* is settled
below, under `status`.

## The test both types below were written against

Could a second, structurally different implementation satisfy this honestly? Two are held against
every member: one that runs the command in an isolated image on this machine, and one that hands it
to a service that runs it elsewhere and reports back. Neither may be forced to invent a value it
does not have, which is why nothing here asks for a duration, a machine, an artifact, a stream, a
step breakdown, or a way to cancel - and why `status`, the one field with an obvious wrong reading,
spends its docstring on that reading.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Verifier", "VerifierOutcome"]


@dataclass(frozen=True, slots=True)
class VerifierOutcome:
    """What the build gate answered: the verdict, a number for a person, and the text it made."""

    passed: bool
    """Did the build pass. **The only thing the framework branches on.**

    One `bool`, decided by the implementation, because the framework's use of it is one `if`: a
    landing that fails the gate is undone (§3.4) and one that passes is kept. A finer grading would
    be a vocabulary the framework would then have to hold opinions about, and the two ports either
    side of this decision - the one that landed the work and the one that puts it back - both take
    the same action whatever the shade of failure was.
    """

    status: int
    """The number the runner reported, carried so that a person can see it. **Nothing branches on
    it.**

    An implementation with no number of its own to report says `0` or `1`, agreeing with `passed`.
    That is reporting rather than lying, and it is worth being explicit that this field is not
    promised to be any particular kind of runner's numeric convention - a reader who takes it for
    one will start writing comparisons against remembered magic numbers, and this port cannot
    promise that any given implementation produces them.

    §3.9 settles the posture, and the field exists inside it rather than against it: a build killed
    because the machine ran out of memory, a long-lived helper of the build tool dying underneath
    it, and a genuine test failure **are not cleanly distinguishable, so no attempt is made to be
    clever**. An exhausted machine presents as a rejected piece of work, and the gate undoes the
    landing just as it would for a real failure. A number here is a clue for the person reading the
    failure screen afterwards - which is exactly the case §3.9 says will happen and be
    misattributed - and never a signal for code.

    An expired deadline is the same story. Whatever the implementation reports for it arrives here,
    the gate reads `passed`, and the work is rejected rather than retried.
    """

    output: str
    """What the command produced, as text: for the person, and for the failure screen.

    A plain `str`, for `History.diff`'s reason. Build output is the interchange format every reader
    of it - a person, a model - already reads, and structuring it would mean this port inventing a
    taxonomy of build events that every implementation would have to render its own output into. The
    two streams a local runner has are one thing here because they are one thing on the screen, and
    a service that returns one blob of log text has nothing to split.

    Empty is legal and means the command printed nothing, which passing builds routinely do.
    """


class Verifier(ABC):
    """Run the build command and say whether it passed. One method.

    Its errors are `errors.py`'s and nothing else. `UpstreamUnavailable` when the command cannot be
    started at all - `errors.py` names this case in those words - and `UpstreamUnexpected` when the
    runner answered something the adapter cannot make an outcome out of.

    **A failing build is neither of those.** It is the answer, so it comes back as an outcome with
    `passed` false: the gate failing is the ordinary working of the gate, and raising would put
    "your tests are red" in the same bucket as "the runner is not installed".
    """

    @abstractmethod
    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        """Run `command` in `workdir`, wait for it, and report what happened.

        `command` is the build command **exactly as the user wrote it** in the project's settings,
        operators and all: it may join two commands, redirect, or name a wrapper script living in
        the project. One string and not a program plus a list of arguments, because a command line
        is what a person writes down when asked for their build command, and the shape that takes a
        program and arguments cannot express what half of them will write.

        `workdir` is where it runs, and one rule goes with it, stated here because this is the port
        that has to be implemented and not the place it is called from:

        **The working directory is given as the working directory, and is never interpolated into
        the command text.** Path components under it can originate as agent output - a workflow's
        namespaces are named by whatever the workflow passed, and one shipped workflow passes
        identifiers a model invented. `ids.py` narrowed the character set those names may use as
        defence in depth, and says plainly what it is defending: it accepts `$`, backtick, `;` and
        `|` because they are perfectly legal in a name, and that is safe exactly as long as nothing
        composes such a name into a string that something else then parses. Joining the two here
        would be that composition, and it would be reached by a path AGL does not control.

        Async because the answer takes minutes and the framework has other work in flight. There is
        no way to cancel it; the deadline is configuration - see the module docstring.
        """
