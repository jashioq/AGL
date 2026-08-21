"""`ShellVerifier` - the build gate as the user's own command line, run on this machine.

`Verifier` (§3.4, §3.5) is one method with one answer, and this is the implementation that runs
the configured build where AGL itself is running: one shell, one process group, everything it
printed, and one `VerifierOutcome` back. The port was written to admit two more - one that runs
the command in an isolated image, one that hands it to a service that runs it elsewhere - so
everything below is this runner's business and none of it is on the port.

## A shell, deliberately, because a build command is a command *line*

`verify` takes one `str` rather than a program and a list of arguments, and the port says why:
the command arrives "exactly as the user wrote it, operators and all ... it may join two commands,
redirect, or name a wrapper script". `./gradlew build` would survive being split on spaces.
`npm test && npm run lint` would not, and neither would `make -j8 2>&1 | tee build.log`. Half of
what a person writes down when asked for their build command needs an interpreter, so there is
one: `create_subprocess_shell`, which is `/bin/sh -c`.

Rejected: taking the command as argv and asking the user to spell `sh -c "..."` themselves when
they need an operator. That moves the shell from this module - where it is one call with one rule
attached - into the project's settings file, where the rule cannot be enforced and where the next
person to need a pipe writes the quoting by hand.

That decision is the entire reason the next section exists. An adapter with a shell in it has a
parser in it, and everything handed to that parser is program text.

## The working directory is passed as a working directory, and never as text

**`workdir` reaches the process as `cwd=` and is never interpolated into the command.** Not
concatenated, not formatted, not `shlex.quote`d, and above all never `cd {workdir} && {command}` -
there is no expression anywhere in this module holding both values, which
`tests/adapters/test_shell_verifier.py` asserts by parsing this file rather than by trusting this
paragraph, and demonstrates by running builds in directories whose names would execute.

The reason is where the path comes from. A worktree path is composed of the trees root *the user
chose* and a namespace *the workflow passed*, and one shipped workflow (`decompose`) passes
identifiers a model invented. §3.3's allowlist narrows what `ids.py` will accept for that middle
component to `[A-Za-z0-9._-]`, refusing `$`, backtick, `;` and `|` at construction - but that is
**defence in depth and not the guarantee**. It cannot reach the trees root a user chose, the home
directory that root sits under, or any other component of a path this process did not compose;
a directory named `$(curl …|sh)` is perfectly legal on every filesystem AGL runs on, and nothing
in `ids.py` is asked about it. The two defences agree rather than one leaning on the other: that
one stops such a name being *spelled* by AGL, this one stops any name being *executed* by AGL.

Stage 5 found the same class of bug one layer over, with no shell involved at all: a git ref
spelled `--output=/path` makes `diff-tree` write a file from a port whose whole promise is that it
changes nothing, and a branch spelled `--file=…` makes `merge` land somebody else's upstream and
report success. §3.5 states the generalisation this module is named in: **every value reaching a
command line is hostile regardless of where it came from.** So `command` is program text because
the user wrote it as program text, and `workdir` is a value, and the two never meet.

## The deadline is configuration, and it arrives through the constructor

The port has a section titled "There is no timeout parameter" and it is a decision rather than an
omission: `build_timeout` sits beside `build` in the project's settings (§3.11), so it is one
number for the whole project, the same on every call, and it reaches an implementation the way
every implementation is configured - the composition root builds this class with it. A parameter
on `verify` would put one unvarying value on the one call site there is, and would hand a hosted
verifier whose far side enforces its own deadline an argument it could only ignore.

**An expired deadline is a failed build, not an exception.** `verify` returns
`VerifierOutcome(passed=False, …)` carrying what the build had printed before the deadline and the
status the killed process reported. The port settles the reading: whatever an implementation
reports for an expiry "arrives here, the gate reads `passed`, and the work is rejected rather than
retried" - and §3.9 adds that a machine that ran out of memory, a build tool's helper dying, and a
genuine test failure are not cleanly distinguishable, so no attempt is made to be clever. Raising
would put "this build hung" in the same bucket as "there is no shell here", and §3.4's `integrate`
would have to catch an exception to learn the ordinary second answer to the only question it asks.

## A deadline that does not stop the work is not a deadline

A shell command spawns children, and children spawn daemons. Killing only the shell leaves the
build running - a compile still burning eight cores while the run has moved on - and it can leave
this adapter waiting on a pipe that a surviving grandchild still holds open, which is a hang
dressed as a deadline. So the build is started in a session of its own (`start_new_session=True`,
which makes the shell a session and process-group leader) and the *group* is what gets signalled:
`SIGTERM` first, because a build tool asked to stop unlinks its own lock files, then `SIGKILL` to
whatever ignored it.

Output is read incrementally into a list rather than through `communicate()`, for the same
deadline. `communicate()` buffers inside itself, so a build stopped at its deadline hands back
nothing at all - and the output of a build that hung is precisely what a person needs in order to
see where it hung. `read()` and never `readline()`: a `StreamReader` has a line limit, and a build
that prints a minified bundle or a base64 blob on one line is not a build that should fail on it.

## Two streams, one field, merged where they were made

The port has one `output` because "the two streams a local runner has are one thing here because
they are one thing on the screen". They are merged at the pipe - `stderr=asyncio.subprocess.STDOUT`
- rather than read separately and concatenated afterwards, so the order is the one the shell
produced: a compiler warning still sits above the line of test output that followed it. Reading
two pipes and joining them would put every error after every ordinary line and quietly rewrite the
transcript a person is trying to read.

Decoding is UTF-8 with `errors="replace"`, for `_runner.py`'s reasons and with its cost. Build
output is not promised to be UTF-8 - a filename on POSIX is bytes, and a test printing a random
buffer is a normal Tuesday - and the two lossless options are worse: bytes would push the decision
onto the failure screen, and `surrogateescape` mints exactly the lone surrogates `ports/run.py` and
the store refuse, so a stray byte would fail three layers later at a write instead of here. The
cost is real: an undecodable byte reaches the person as U+FFFD.

Nothing is truncated. A build that prints a megabyte prints a megabyte, and the tail is the half a
reader wants; a cap belongs to whatever draws the failure screen, which knows how much room it has.

## `passed` is the verdict; `status` is for a person

The exit status becomes `passed` here, once, at the moment the outcome is built - that is this
adapter's job, and 0 is the shell's own convention rather than a number invented here. The number
is then *carried* rather than consulted: nothing in this module, and nothing above it, reads
`VerifierOutcome.status` to decide anything. The port spends that field's docstring on the reading
it must not be given, and this is the implementation agreeing with it.

## No state between calls

`integrate()` calls this once per landing and a run lands children all afternoon, so the same
instance answers many times. It holds the deadline it was built with and nothing else: no cached
outcome, no process, no working directory, no lock. Every call starts a process, reads it, and
lets it go, which is what makes a red build unable to poison the next one.

## What this deliberately does not do

**No environment scrubbing.** The build inherits the environment, because a build command is the
one thing here that genuinely needs the user's `PATH`, toolchain, and language version manager -
a scrubbed environment would fail on most machines and would look like a red build while doing it.
Hermeticity is an *agent* port's contract (§3.5), where the thing being isolated is a model's
configuration rather than a compiler's.

**No shell of its own choosing.** Whatever `create_subprocess_shell` runs is what the platform
calls `/bin/sh`. Naming a shell here would mean this module deciding that the user's `&&` means
what bash says it means, on a machine where their own terminal might disagree.

**No general process helper.** §3.4's git runner is argv-only by design and this one is a shell by
design; the two share a paragraph of reasoning and not a line of code. Part 2's rule 6 gives the
extraction decision to a later stage, and there is nothing yet to extract that would not immediately
need a flag saying which of the two it was being.
"""

import asyncio
import os
import signal
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Final

from agl.ports.errors import UpstreamUnavailable, UpstreamUnexpected
from agl.ports.verifier import Verifier, VerifierOutcome

__all__ = ["ShellVerifier"]

# The deadline used when the composition root has nothing to hand over - a project with no
# `build_timeout` set. Half an hour: long enough that a cold-cache build of a large project
# finishes, short enough that a build which is never going to answer fails inside an afternoon
# rather than holding the merge queue open forever. A project whose build is genuinely longer
# says so in its settings, which is where the number belongs.
_DEFAULT_BUILD_TIMEOUT: Final = 1800.0

# How long the process group is given between being asked to stop and being made to. Build tools
# hold locks - a daemon's pid file, a package manager's cache lock - and unlink them on SIGTERM,
# so this margin is the difference between a tree the next build can use and one that refuses
# until somebody deletes a lock file by hand. It is not a second deadline: nothing useful is
# accomplished in it, and it is short enough to be invisible against a timed-out build.
_GRACE: Final = 5.0

# See the module docstring: build output is not promised to be UTF-8, and of the three ways to
# decode it this is the only one whose result AGL can also store.
_ENCODING: Final = "utf-8"
_UNDECODABLE: Final = "replace"

# How much is taken from the pipe at a time. A read size and nothing else - it bounds neither the
# output nor the memory, both of which are the build's to decide.
_CHUNK: Final = 65536

# The shell's own convention, and the one place in this module where a number becomes a verdict.
# It is applied to the exit status of a process, before any `VerifierOutcome` exists; the field
# called `status` is the copy carried afterwards for a person to read, and nothing consults it.
_PASSED: Final = 0


class ShellVerifier(Verifier):
    """`Verifier` over one shell on this machine: the configured command, in a given directory.

    Constructed by `config/container.py` with the project's `build_timeout` and nothing else -
    there is nothing else it could need, the command and the directory both arriving per call -
    and holding nothing between calls, which is what lets one instance gate every landing a run
    makes.
    """

    def __init__(self, build_timeout: float = _DEFAULT_BUILD_TIMEOUT) -> None:
        """`build_timeout` is the project's deadline, in seconds, for one build.

        A constructor argument because that is where implementations are configured and because
        the port refuses it as a method parameter - see the module docstring. Nothing is checked
        here and no process is started: a constructor cannot await, and a shell that is not there
        is found on the first call and reported as `UpstreamUnavailable`, which is the same answer
        one moment later.
        """
        self._build_timeout = build_timeout

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        """Run `command` in `workdir` under a shell, wait for it, and report what happened.

        The two values are kept apart, which is the clause this whole module exists to honour:
        `command` is handed to the shell as the program text the user wrote, `workdir` is handed
        to `create_subprocess_shell` as `cwd=`, and nothing joins them. See the module docstring
        for what that is defending against and why `ids.py`'s allowlist is not it.

        Three outcomes and one error. A build that finished answers with the shell's exit status
        and everything the command printed. A build that ran past the deadline is stopped, along
        with everything it started, and answers `passed=False` with what it had printed by then -
        an outcome and not an exception, which the port settles in as many words. A shell that
        could not be started at all raises `UpstreamUnavailable`, which is the one case where
        nothing ran.
        """
        process = await _started(command, workdir)
        captured: list[bytes] = []
        try:
            async with asyncio.timeout(self._build_timeout):
                await _drained(process, captured)
                finished = await process.wait()
        except TimeoutError:
            stopped = await _halted(process)
            return VerifierOutcome(
                passed=False,
                status=stopped,
                output=_text(captured) + _expired(self._build_timeout),
            )
        except BaseException:
            # Anything else raised while a build is running - a cancellation as a `TaskGroup`
            # unwinds around concurrent work, or the pipe below being unreadable - stops the build
            # on the way past and re-raises untouched, so that no exception leaving this module
            # leaves a compile behind it. It signals without awaiting, because awaiting inside a
            # cancellation is how a second exception replaces the first; the child watcher reaps
            # what the signal lands on. Known gap, and the price of not awaiting: a build that
            # ignores SIGTERM outlives this, where a build that runs past its deadline does not.
            _signalled(process, signal.SIGTERM)
            raise
        return VerifierOutcome(passed=finished == _PASSED, status=finished, output=_text(captured))


async def _started(command: str, workdir: Path) -> asyncio.subprocess.Process:
    """Start `command` under a shell, in `workdir`, in a session of its own and with no way in.

    **The one call in this package that hands text to an interpreter**, and the reason the module
    docstring is as long as it is. `command` is the whole of what the shell parses; `workdir` is
    `cwd=`, which is a `chdir` in the child between fork and exec and never a string anything
    reads. Neither value is combined with the other here or anywhere else.

    `start_new_session=True` makes the shell a session and process-group leader, so its children
    and their children share one group id - which is what `_halted` signals, and the difference
    between a deadline that stops a build and one that stops a shell and leaves the build running.

    `stdin=DEVNULL` is the door that would otherwise turn a build into a hang: a tool that stops to
    ask something reads EOF and gets on with failing, and a child holding the real stdin would be
    competing with the terminal adapter for the user's keystrokes.

    Every `OSError` is `UpstreamUnavailable`: `workdir` does not exist or is not a directory, there
    is no shell on this machine, the process table is full. That class names this case itself -
    "the build command cannot be run" - and its promise is the useful one, that nothing happened
    so the same call may well succeed later.

    The message names the directory and not the command, deliberately. The two are kept out of
    every shared expression in this module so that the structural test in
    `tests/adapters/test_shell_verifier.py` can be blunt about it, and the command is the one value
    here the reader can already see - they wrote it in their settings file.
    """
    try:
        return await asyncio.create_subprocess_shell(
            command,
            cwd=workdir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        raise UpstreamUnavailable(
            f"the project's build command could not be started in {workdir}: {error}. Nothing "
            f"ran, so this is not a failed build - the same call may well succeed once that "
            f"directory is there and a shell can be started in it"
        ) from error


async def _drained(process: asyncio.subprocess.Process, captured: list[bytes]) -> None:
    """Read the merged stream to end of file, into `captured` as it arrives.

    Written into rather than returned, because the caller keeps what was read when the deadline
    cancels this mid-read. That is the whole reason `communicate()` is not used: it buffers
    internally and hands back its buffer only on success, so a build stopped at its deadline would
    report nothing at all - and what a hung build printed before it hung is the only clue anybody
    gets about where it stopped.

    `read()` rather than `readline()`, because a `StreamReader` enforces a line limit and a build
    that prints a minified bundle, a base64 artifact or a very long diff on one line is not a build
    that should fail on the printing of it.

    `stdout` is optional on the type because a process may have been started without a pipe. This
    one was not, so `None` here is the runner answering something no outcome can be made out of -
    there would be no `output` to report - which is `UpstreamUnexpected`'s own sentence.
    """
    if process.stdout is None:
        raise UpstreamUnexpected(
            "the build was started with its output on a pipe and there is no pipe to read. "
            "Nothing can be reported about a build whose output cannot be reached, and the same "
            "call would answer the same way"
        )
    while chunk := await process.stdout.read(_CHUNK):
        captured.append(chunk)


async def _halted(process: asyncio.subprocess.Process) -> int:
    """Stop a build that ran past its deadline - all of it - and hand back the status it reported.

    Asked first and made second: `SIGTERM` to the whole group, a moment to unlink lock files, then
    `SIGKILL` to whatever is left. The second signal is sent whether or not the shell itself has
    already gone, which is the point of the group: a shell exits the instant it is asked to, and
    the compile it started does not, so a kill conditional on the leader still being alive would
    routinely leave the actual build running.

    What that costs is stated rather than hidden: after the leader has been reaped its group id is
    a number the system may eventually reuse, so this signals a group that is almost certainly the
    build's and, in a window measured in microseconds on a machine spawning processes as fast as it
    can, might not be. The alternative is a build that outlives its own deadline, which is the
    failure this function exists to prevent.
    """
    _signalled(process, signal.SIGTERM)
    with suppress(TimeoutError):
        async with asyncio.timeout(_GRACE):
            await process.wait()
    _signalled(process, signal.SIGKILL)
    return await process.wait()


def _signalled(process: asyncio.subprocess.Process, sign: signal.Signals) -> None:
    """Send `sign` to the build's whole process group. Never raises.

    The group id is the shell's own pid, because `start_new_session=True` made it a leader -
    `os.getpgid` is not consulted, being a second syscall that fails on exactly the race this one
    already has to survive.

    Both suppressions are deliberate. `ProcessLookupError` is the ordinary case of a build that
    finished between the deadline expiring and this signal, and `PermissionError` is a group this
    process may no longer signal - and neither may become an exception, because this runs on the
    path that turns an expired deadline into an ordinary rejected outcome, and a path that reports
    a failure must not become one.
    """
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, sign)


def _text(captured: Sequence[bytes]) -> str:
    """What the build printed, as a `str` the failure screen and the store can both take."""
    return b"".join(captured).decode(_ENCODING, errors=_UNDECODABLE)


def _expired(seconds: float) -> str:
    """The one line AGL adds to a build's own output, and only when it stopped that build.

    Everything else in `output` is the command's. This is here because the alternative is a
    transcript that stops mid-sentence with a negative number beside it, leaving the person at the
    failure screen to work out from a signal number that their build was killed rather than that it
    crashed. It is marked as AGL's so that nobody reads it as something their build said.
    """
    return (
        f"\n[agl] The build did not finish within {seconds:g}s and was stopped, along with "
        f"everything it had started. What is above is what it had printed by then.\n"
    )
