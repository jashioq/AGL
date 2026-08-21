"""`FakeVerifier` - the build gate with no build behind it: scripted answers, and no process.

**A product feature and not a test double** (§1.9). It is what `--dry-run` runs on and what plan
target #8 rests on - *every command runs end-to-end on fakes alone, no network, no git* - so the
rule `memory_store.py` and `adapters/git/fake.py` state for their ports is the rule here: wherever
the port is silent, this agrees with `ShellVerifier`. A fake more permissive than the real thing
lets a workflow pass on fakes and fail in anger, and the difference stays invisible until the day
somebody drops the `--dry-run`.

**Nothing here starts anything.** No `subprocess`, no `asyncio.subprocess`, no shell, no `os`
call that could reach the process table - the imports at the top are the whole of what this module
can do, and they are two. That is the point of it: a run whose gate is this one runs a merge train
end to end on a laptop with no toolchain installed, in the time it takes to walk a dict.

`tests/contracts/verifier.py` is what stops it drifting into fiction, and it runs against this
class exactly as it runs against the real one: a failing build is an outcome and never an
exception, `passed` is a real `bool`, `status` is an `int` that is not a `bool`, `output` is a
`str`, and a red build does not poison the next answer.

## Scripted by command, because the command is what the caller varies

    verifier = FakeVerifier()
    verifier.answers("npm test", passed=False, status=1, output="2 failing")

`verify` takes a command and a directory, the directory is the workspace of whichever child is
being landed, and the command is the project's one configured build - so scripting *by command* is
scripting by the thing a test can name in advance and hold still. Two rejected alternatives, both
of which look tidier and are worse:

  * **A queue of outcomes, answered in order.** It reads well until a workflow lands children
    concurrently or a resumed run skips a landing that was already recorded, at which point the
    test is asserting against an order the framework never promised, and it fails on a change to
    scheduling rather than on a change to behaviour.
  * **A callable the test supplies.** It can express everything, including things no verifier can
    do, so the fake stops being a verifier and starts being a place to put arbitrary code - and
    the contract suite that keeps this honest can only hold *this* class to the port.

An unscripted command passes. That is `--dry-run`'s requirement rather than a convenience: nothing
scripts a command on the way to target #8, and a gate that answered "failed" by default would
report every landing of a dry run as rejected. A test that wants the opposite says so once, at
construction, and the flag is deliberately a fact about the instance rather than a value that
drifts as answers are scripted.

## What it holds, and what it does not

It holds the script and the default and nothing else. No record of what it was asked, no count of
calls, no last outcome: the port's one consumer branches on `passed` and reads the other two
fields for a person, so a recorder here would be a surface tests could assert against that no real
implementation has. If a later stage needs one, it is one list and this docstring is where the
argument for adding it goes.

`UpstreamUnavailable` is not reachable here and is not simulated. It is a fact about a runner -
"the build command cannot be run" - and this runner cannot fail to start, having nothing to start;
a fake that raised it on a directory that happens not to exist would be inventing the one thing it
has no evidence about, and `tests/contracts/verifier.py` names that clause as one no suite can
reach from outside either.
"""

from pathlib import Path
from typing import Final

from agl.ports.verifier import Verifier, VerifierOutcome

__all__ = ["FakeVerifier"]

# The port's own words for an implementation with no number of its own to report: it "says `0` or
# `1`, agreeing with `passed`. That is reporting rather than lying." This fake has no number, so
# these are what a scripted answer carries unless the script names one.
_AGREES_PASSED: Final = 0
_AGREES_FAILED: Final = 1

# What a command nobody scripted answers, built once because `VerifierOutcome` is frozen and one
# instance handed back twice is two identical answers rather than any kind of shared state.
_UNSCRIPTED_PASS: Final = VerifierOutcome(passed=True, status=_AGREES_PASSED, output="")
_UNSCRIPTED_FAIL: Final = VerifierOutcome(passed=False, status=_AGREES_FAILED, output="")


class FakeVerifier(Verifier):
    """`Verifier` over a dict: the answer a command was scripted to give, or the default.

    Constructed the way the real one is - by `config/container.py`, once, and handed to the thing
    that gates landings - so a bundle swaps `ShellVerifier(build_timeout=…)` for `FakeVerifier()`
    and nothing above notices. There is no deadline here because nothing takes time: a build that
    is a dict lookup cannot run past one, and accepting the number so the signatures matched would
    be accepting a value this class could only ignore.
    """

    def __init__(self, *, unscripted_passes: bool = True) -> None:
        """`unscripted_passes` is what a command nobody scripted answers. Passing, by default.

        The default is `--dry-run`'s: nothing scripts a build command on the way to running a
        whole workflow on fakes, and a gate that failed by default would reject every landing of
        a run whose point was to show the shape of the work. A test that wants a gate which is red
        until told otherwise says `FakeVerifier(unscripted_passes=False)`, and says it here rather
        than by scripting every command it can think of.
        """
        self._scripted: dict[str, VerifierOutcome] = {}
        self._unscripted = _UNSCRIPTED_PASS if unscripted_passes else _UNSCRIPTED_FAIL

    def answers(
        self, command: str, *, passed: bool, status: int | None = None, output: str = ""
    ) -> None:
        """Script what `command` answers from now on. Scripting it twice keeps the second answer.

        `passed` is required and the other two are not, because the verdict is the only thing the
        framework reads and the rest is for a person: a test about a merge train wants "this build
        fails" and nothing else, and a test about the failure screen wants the output as well.

        `status` defaults to the port's own agreement clause - `0` when it passed, `1` when it did
        not - which is what an implementation with no number of its own reports. A test that means
        to see a particular number on a failure screen names it.

        Not async, and not a form of `verify`. Scripting is something a test does before the run
        starts, so it is an ordinary method a fixture calls; making it awaitable would put the
        arrangement of a test into the same shape as the thing under test.
        """
        reported = status if status is not None else (_AGREES_PASSED if passed else _AGREES_FAILED)
        self._scripted[command] = VerifierOutcome(passed=passed, status=reported, output=output)

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        """The scripted answer for `command`, or the default. `workdir` is accepted and unread.

        Nothing is started, nothing is read from disk, and the directory is not checked for
        existence: what a runner can be pointed at is a fact about that runner, and this one has
        no filesystem in it to be pointed at. `ShellVerifier` raising `UpstreamUnavailable` on a
        directory that is not there is a fact about a shell rather than a clause of the port, and
        inventing an agreement with it here would mean this class asserting something about the
        world it cannot see.

        Answering repeatedly is answering repeatedly: the outcomes are frozen and the dict is only
        written by `answers`, so the tenth call answers what the first did and a scripted failure
        cannot leave anything behind for the call after it.
        """
        return self._scripted.get(command, self._unscripted)
