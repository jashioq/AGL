"""Running git, and saying what a refusal meant - the one place in this package that starts a
process.

`adapters/git/` implements three ports over one program (§3.4), and every question all three of
them ask is a git invocation. This is what they ask through: an argv list goes in, git's standard
output comes back, and a failure comes back as an `AglError` from `ports/errors.py` and as nothing
else. Private by its leading underscore, because it is one program's plumbing rather than a
capability anything could implement: no port imports it and nothing outside `agl/adapters/git/`
names it.

## An argv list, and no string a shell could ever see

Every invocation is `asyncio.create_subprocess_exec("git", *argv)`. There is no `shell=True` here,
no `create_subprocess_shell`, and nothing anywhere below builds a command out of a formatted
string. That matters because namespace names reach these arguments and a namespace is *agent
output*: §3.3 narrowed the charset to `[A-Za-z0-9._-]` at stage 3, but the charset is defence in
depth and this is the guarantee. Both members take their arguments variadically for that reason -
`run("rev-parse", "--verify", ref)` - so there is no parameter into which a caller could pass one
long command line and have it split.

**What that does not cover, and where the cover is.** Argv discipline stops a value being read as
*shell* syntax; it does nothing about a value being read as a git *option*, since `git rev-parse
--verify -x` is one program deciding that its own argument begins with a dash. The fix is
`--end-of-options`, and it belongs at the call site rather than here: where it goes depends on the
subcommand, so placing it would mean this module knowing the subcommands, which is the one thing
it must not know (below). 5.2, 5.3 and 5.4 pass it themselves.

## "git said no" and "git is not there" are different answers

This is the distinction the module exists for, because it decides which exit code a person sees.

  * **Could not start, or did not finish** - git is not on `PATH`, the working directory is gone,
    the process had to be stopped on a timeout - is `UpstreamUnavailable` (6). That class's own
    sentence names this case ("its CLI is not on `PATH`"), and its promise is the useful one: the
    same call may well succeed later.
  * **Started, and refused** is a thing git decided, and what the decision *means* depends on what
    was asked - which the caller knows and this module does not. So the caller states it; see the
    next section.
  * **Started, and was killed by a signal nobody here sent** is `UpstreamUnexpected` (6), word for
    word that class's "a subprocess exited with a status the adapter has no meaning for". A
    segfaulting or OOM-killed git did not refuse anything, and reporting it as the caller's
    refusal would answer a question git never got to.

Telling the first from the second needs one fact this module can get without knowing any
subcommand: whether git can read a repository where it was just asked to work. So on the failure
path - and only there - it asks, with `rev-parse --git-dir`, plumbing whose whole answer is its
exit status. If that fails too, nothing here can be read and the answer is `UpstreamUnavailable`
regardless of what the caller declared.

That the probe runs *after* a failure rather than before every call is the old implementation's
one durable lesson about this boundary: pre-checking every ref "would triple the process count on
the path where nothing is wrong, and git checks again anyway". The cost is one extra process per
failure, on a path that was already going to raise.

## `refusal=` is how `NotFoundError` gets here, and it has no default

`tests/contracts/history.py` requires `NotFoundError` - not `UpstreamUnexpected` - from all five
`History` members for a well-formed ref or commit id this repository does not hold. But git spells
that refusal exactly as it spells every other one: a non-zero exit and a sentence. Whether "no"
means *absent* depends on the question, so the question's author names the class:

    await self._git.run("rev-parse", "--verify", ref, refusal=NotFoundError)
    await self._git.run("worktree", "add", ..., refusal=ConflictError)

The two rejected alternatives are why it looks like this. A table of subcommands here would put
every consumer's vocabulary into their shared plumbing, which is §1.3's charge against the
27-member `Vcs` restated one layer down. Handing callers git's stderr to interpret would be
`FileStatus.code` all over again - one program's human-facing output crossing a boundary for
somebody else to read - so **no caller can reach stderr at all**: it appears only inside the
message of the error raised here, where it is prose for a person and not a value to branch on.

No default, for `WorkspaceProvider.open`'s reason and `Conflict.paths`': the meaning of a refusal
is something a call site states, not something it falls into by leaving an argument off. A default
of `ConflictError` would make a forgotten parameter report a missing ref as "the world already
holds something", which is the exact confusion this parameter exists to prevent.

## Only machine-readable output leaves here

`run` returns git's standard output as it arrived - not stripped, not split - because the callers
parse `-z` and `--porcelain` forms whose trailing NUL is data. Stripping is theirs to do on the
one-line answers. Nothing here parses anything, and `unreadable` below is what a caller raises
when its own parse fails, so that "we could not read what git said" is spelled once rather than
three times.

Decoding is UTF-8 with `errors="replace"`. Git does not promise its output is UTF-8 - a path on
POSIX is bytes - and the two lossless options are both worse: bytes would push the decision onto
three call sites, and `surrogateescape` mints exactly the lone surrogates `ports/run.py` and the
store refuse, so an odd filename would fail three layers later at a write instead of here. The
cost is real and stated: a path holding undecodable bytes comes back with U+FFFD in it and so is
not byte-identical to the name on disk.

## What this deliberately does not do

**No lock.** §3.9's one contention point is `worktree add`/`prune` and its guard is a cross-process
`flock` on a file in the trees root; that is 5.2's, next to the registry it protects. A mutex here
would serialise every git call in the process, which is the opposite of what three ports running
under one event loop are for.

**No repository-root resolution.** git resolves its own common directory for every command, so
nothing needs the main root to make an invocation correct, and §3.9's lock file is addressed from
the trees root rather than derived from the repository. A member with no consumer is a member the
next reader has to account for.

**No environment scrubbing beyond one variable.** `GIT_TERMINAL_PROMPT=0` is set because a git
that stops to ask for something has no terminal to ask on and would hang until the timeout, and
stdin is `DEVNULL` so that a subprocess cannot take a keystroke meant for the terminal adapter's
redraw loop. Everything else is inherited. Known gap, unfixed on purpose: an inherited `GIT_DIR`
or `GIT_WORK_TREE` - which exists only when AGL is itself run from inside a git hook - would
redirect every command below past `cwd=` to another repository. Hermeticity is an agent-port
contract (§3.5) rather than a git one, and the day this bites, the fix is two more keys here.

**No general process helper.** This paragraph was written at stage 5 saying stage 8 would be the
*second* consumer of process execution and would take the decision about extracting one. It was
already wrong by stage 6, which added `adapters/shell/verifier.py`, and stage 8 makes three - so the
count is corrected here and the decision is recorded rather than left to be re-litigated from a
false premise.

**The decision, taken at stage 8: there is no shared helper, and a fourth consumer arriving is not
by itself a reason to build one.** The three disagree on seven axes and no two agree on all of them:
shell or exec, buffered or streamed, `DEVNULL` or `PIPE` on standard input, merged or separate
standard error, process or group signalling, deadline or none, and exit code or output stream as the
failure signal. This module sits at one end of most of them - argv-only, buffered, `DEVNULL`,
separate, process, deadline, exit code - and a helper covering all three would take a flag per axis,
each flag existing to say which of three callers it was being. The same paragraph, under the same
heading, is in `adapters/shell/verifier.py` and `adapters/openai/runner.py`, where stage 8's version
of it is argued at length.

So everything here is git's: git's exit-code conventions, git's plumbing probe, git on `PATH`.
"""

import asyncio
import os
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.ports.errors import AglError, UpstreamError, UpstreamUnavailable, UpstreamUnexpected

__all__ = ["GitRunner", "unreadable"]

# A backstop against a wedged process, not a performance budget. Generous enough that a checkout
# of a large repository on a cold cache finishes - `worktree add` copies a whole source tree
# (§3.9) - and short enough that a run which is never going to answer fails inside a coffee break
# rather than never. A call site that knows its operation is bigger than that passes its own.
_DEFAULT_TIMEOUT: Final = 120.0

# How long a stopped git is given to tidy up before it is killed outright. git installs handlers
# that unlink its own `*.lock` files on a fatal signal, so SIGTERM plus a moment is the difference
# between a repository the next command can use and one holding a stale `index.lock`. Unlinking a
# few files needs none of this; the margin is for a machine under load.
_GRACE: Final = 5.0

# See the module docstring: git's output is not promised to be UTF-8, and of the three ways to
# decode it this is the only one whose result AGL can also store.
_ENCODING: Final = "utf-8"
_UNDECODABLE: Final = "replace"

# git's own convention for a question answered by the exit status: 0 is yes, 1 is no, and anything
# else is a failure. `merge-base --is-ancestor`, `diff --quiet`, `rev-parse --verify --quiet` and
# a conflicted `merge` all spell it this way - it is the program's, not a guess made here.
_ANSWERED_NO: Final = 1

# How much of what git said goes into an error message. A failing `merge` prints its conflicts to
# standard output and a failing `diff` can have a patch behind it; a message a person reads on a
# terminal is not the place for either in full.
_REASON_LIMIT: Final = 500

# The plumbing question this module asks to tell "git refused" from "there is nothing here to
# refuse with". Its answer is its exit status; the path it prints is not read.
_REPOSITORY_PROBE: Final = ("rev-parse", "--git-dir")


def unreadable(what: str, output: str) -> UpstreamUnexpected:
    """The error for git output a caller cannot parse. Returned, so call sites `raise` it.

    `UpstreamUnexpected` and not `UpstreamUnavailable`, because that class draws exactly this
    line: git answered, and the answer is not something we can act on - "our understanding of it
    is what failed" - so retrying unchanged produces the same answer. It is here rather than in
    each of the three adapters so that the one sentence AGL says about unparsable git output is
    said in one place, and so that a caller reaching for it is reminded which class it is.

    `what` names the thing being read in AGL's own words ("a worktree registration", "a change
    entry"), and `output` is the fragment that would not read. The fragment is quoted rather than
    summarised: this is the one message whose reader needs the bytes.
    """
    return UpstreamUnexpected(
        f"git answered with something AGL cannot read as {what}: {_capped(output)!r}. The "
        f"repository is fine and this adapter's reading of it is not, so the same call will "
        f"answer the same way"
    )


class GitRunner:
    """One repository, and the two shapes of question the three git adapters ask it.

    Constructed by `config/container.py` with the repository and nothing else, like every other
    adapter, and holding no state past that: no cache, no open handle, no lock. Three of these
    over one repository - a `WorkspaceProvider`, a `History` and an `Integrator`, which is what
    §3.4 splits `Vcs` into - are the same runner, and that they can be is the reason there is
    nothing here to share.
    """

    def __init__(self, repository: Path, timeout: float = _DEFAULT_TIMEOUT) -> None:
        """`repository` is where a command runs unless one says otherwise; `timeout` its backstop.

        Nothing is checked here and no process is started: a constructor cannot await, and a
        synchronous probe would be the one blocking call in a package that is async precisely so
        that several agents can run at once. A path that is not a repository is found on the first
        call and reported as `UpstreamUnavailable`, which is the same answer one moment later.
        """
        self._repository = repository
        self._timeout = timeout

    async def run(
        self,
        *argv: str,
        cwd: Path | None = None,
        refusal: type[AglError],
        timeout: float | None = None,
    ) -> str:
        """Run `git <argv>` and hand back its standard output. A refusal raises `refusal`.

        The ordinary member. `cwd` defaults to the repository and is passed for a command that
        must run inside one worktree; `timeout` defaults to the runner's.

        `refusal` says what a deliberate "no" from *this* question means - `NotFoundError` for a
        ref that names nothing, `ConflictError` for a line of work already there - and has no
        default; the module docstring argues both halves. It is consulted only for a refusal: a
        git that could not start, did not finish, or died on a signal raises what that was,
        whatever the caller declared.

        Output arrives whole: not stripped, because a `-z` form ends in a NUL that is data, and
        the one-line answers are the caller's to strip. Standard error is not returned at all, and
        appears only in the message of an error raised from here.
        """
        result = await self._completed(argv, cwd, timeout)
        if result.code != 0:
            raise await self._refused(result, argv, cwd, timeout, refusal)
        return result.out

    async def answers(
        self,
        *argv: str,
        cwd: Path | None = None,
        refusal: type[AglError],
        timeout: float | None = None,
    ) -> bool:
        """Ask a question git answers with its exit status: 0 is yes, 1 is no, anything else fails.

        For the handful of commands built that way - `merge-base --is-ancestor`, `diff --quiet`, a
        `merge` that reports a conflict as exit 1 - where a non-zero status is one of the answers
        rather than a failure. Everything else, including 128, is a failure and goes through the
        same classification `run` uses, so a made-up commit id handed to `--is-ancestor` still
        raises `refusal` rather than quietly reading as "not an ancestor".

        **Not a way to tolerate a refusal.** `git branch -D` exits 1 both for a branch that is not
        there and for one another worktree has checked out, so a caller reading that as "no" could
        not tell "already gone" from "still in use" - and the port members that must be tolerant
        of absence are destructive ones, where that is the difference between tidying up and
        losing work. Tolerance is `run` with a `refusal` class and an `except` around it, at the
        call site, where what is being tolerated can be named.

        Standard output is discarded. A caller that wants the value as well as the answer wants
        `run`, which raises on the "no" and hands back both.
        """
        result = await self._completed(argv, cwd, timeout)
        if result.code == 0:
            return True
        if result.code == _ANSWERED_NO:
            return False
        raise await self._refused(result, argv, cwd, timeout, refusal)

    async def _completed(
        self, argv: Sequence[str], cwd: Path | None, timeout: float | None
    ) -> _Completed:
        """Start git, wait for it, and hand back what it did. Classifies nothing.

        The whole of the process handling, and the reason it is one function: the probe in
        `_refused` runs through here too, and a probe that went through classification would
        classify itself. What this raises is only what is true before any exit status exists - it
        could not start, or it did not finish.

        A cancellation - a `TaskGroup` unwinding around several concurrent children (§3.9) - stops
        the process on the way past and re-raises untouched. It signals without awaiting, because
        awaiting inside a cancellation is how a second exception replaces the first; the child
        watcher reaps what the signal lands on.
        """
        where = self._repository if cwd is None else cwd
        seconds = self._timeout if timeout is None else timeout
        process = await _spawned(argv, where)
        try:
            async with asyncio.timeout(seconds):
                out, err = await process.communicate()
        except TimeoutError:
            await _stopped(process)
            raise UpstreamUnavailable(
                f"{_asked(argv, where)} did not finish within {seconds:g}s and was stopped. "
                f"Whatever it had already done is done, and git unlinks its own lock files when "
                f"it is asked to stop, so the same call may well succeed later"
            ) from None
        except BaseException:
            with suppress(ProcessLookupError):
                process.terminate()
            raise
        # `returncode` is typed optional because a `Process` may still be running; this one has
        # just been waited on, so `None` is unreachable and 0 is the only honest stand-in for it.
        code = process.returncode if process.returncode is not None else 0
        return _Completed(code, _text(out), _text(err))

    async def _refused(
        self,
        result: _Completed,
        argv: Sequence[str],
        cwd: Path | None,
        timeout: float | None,
        refusal: type[AglError],
    ) -> AglError:
        """What a non-zero exit meant. Returned rather than raised, so call sites read as `raise`.

        Three answers in the order the module docstring argues them: a signal is not a refusal, a
        repository nothing can read is not a refusal either, and what is left is git deciding -
        which is the caller's `refusal` to name.
        """
        where = self._repository if cwd is None else cwd
        asked = _asked(argv, where)
        if result.code < 0:
            return UpstreamUnexpected(
                f"{asked} was killed by signal {-result.code} rather than answering. git refused "
                f"nothing here - it did not get that far - so what stopped it is outside this "
                f"repository and outside AGL"
            )
        if not await self._readable(where, timeout):
            return UpstreamUnavailable(
                f"{asked} failed, and git cannot read a repository there at all. Nothing was "
                f"attempted, so the same call may well succeed once the repository is reachable: "
                f"{_reason(result)}"
            )
        return refusal(f"git refused {asked}: {_reason(result)}")

    async def _readable(self, where: Path, timeout: float | None) -> bool:
        """Can git read a repository in `where`? The one question that needs no subcommand.

        `rev-parse --git-dir` is plumbing whose answer is its exit status, so nothing here reads
        the path it prints. It walks upwards exactly as every other git command does, which is the
        limit worth stating: a directory that is not a repository but sits inside one answers
        `True`, because git would have run the failed command against that outer repository too.
        The question is "was there a repository for git to refuse from", not "is this directory a
        repository root".

        Run only after a failure, never before a call - the module docstring has the argument -
        and it cannot recurse, because `_completed` classifies nothing. A probe that cannot start
        or does not finish answers `False`, which is the same conclusion by a shorter road.
        """
        try:
            probe = await self._completed(_REPOSITORY_PROBE, where, timeout)
        except UpstreamError:
            return False
        return probe.code == 0


@dataclass(frozen=True, slots=True)
class _Completed:
    """One finished git process: what it exited with, and what it wrote. Never leaves this module.

    `err` is here so that the failure messages above can quote git, and for nothing else. It is
    not on either public member's return, which is the whole of the guarantee that no caller
    parses git's human-facing output - the boundary §1.3 caught `FileStatus.code` crossing.
    """

    code: int
    out: str
    err: str


async def _spawned(argv: Sequence[str], where: Path) -> asyncio.subprocess.Process:
    """Start `git <argv>` in `where`, with pipes and no way in.

    `create_subprocess_exec` and never `_shell`: the arguments reach `execve` as they were written
    and no interpreter sees them, which is the guarantee the module docstring rests on. `git` is
    named rather than resolved, leaving `PATH` to the exec, so the binary a run uses is the one
    the user's own shell would find.

    `stdin=DEVNULL` and `GIT_TERMINAL_PROMPT=0` are the two doors that would otherwise turn a
    subprocess into a hang: an editor or a prompt with a terminal to reach for waits forever, and
    a child holding the real stdin competes with the terminal adapter for the user's keystrokes.

    Every `OSError` is `UpstreamUnavailable`: git missing from `PATH`, git present and not
    executable, `where` gone. That class names the first of those itself, and for the reader of an
    exit code the three are one thing - nothing started, so the same call may succeed later.
    """
    try:
        return await asyncio.create_subprocess_exec(
            "git",
            *argv,
            cwd=where,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ | {"GIT_TERMINAL_PROMPT": "0"},
        )
    except OSError as error:
        raise UpstreamUnavailable(
            f"{_asked(argv, where)} could not be started: {error}. Nothing ran, so the same call "
            f"may well succeed once git is installed and the directory is there"
        ) from error


async def _stopped(process: asyncio.subprocess.Process) -> None:
    """Stop a git that ran out of time, and wait for it to actually be gone.

    SIGTERM first and SIGKILL only if that is ignored, which is not politeness: git installs
    handlers that unlink the `*.lock` files it is holding when it is asked to stop, and skipping
    straight to SIGKILL is the difference between a repository whose next command works and one
    where every command refuses until somebody deletes `index.lock` by hand.

    Reaped either way. What the killed command had already written stays written - this cleans up
    a process, never a repository, having no idea what was being attempted and no business
    guessing.
    """
    with suppress(ProcessLookupError):
        process.terminate()
    try:
        async with asyncio.timeout(_GRACE):
            await process.wait()
    except TimeoutError:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()


def _text(raw: bytes) -> str:
    """Git's bytes as a `str` AGL can also store. See the module docstring for what it costs."""
    return raw.decode(_ENCODING, errors=_UNDECODABLE)


def _asked(argv: Sequence[str], where: Path) -> str:
    """The invocation, for a message a person reads. Quotes what a bare join would run together."""
    spelled = " ".join(
        part if part and not any(character.isspace() for character in part) else repr(part)
        for part in argv
    )
    return f"`git {spelled}` in {where}"


def _reason(result: _Completed) -> str:
    """The most useful thing git said about why it refused.

    Standard error first, then standard output - `merge` reports what would not combine on the
    latter - and the exit status when it said nothing at all, which happens and leaves a message
    reading "git refused: " with nothing after it.
    """
    return _capped(result.err.strip()) or _capped(result.out.strip()) or f"exit {result.code}"


def _capped(text: str) -> str:
    """`text`, short enough to read. A patch or a list of conflicts belongs in neither message."""
    return text if len(text) <= _REASON_LIMIT else f"{text[:_REASON_LIMIT]}..."
