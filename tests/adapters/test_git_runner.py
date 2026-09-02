"""`GitRunner` against real git, in real repositories, because that is the only thing it claims.

There is no contract suite here and there is not meant to be: the suites in `tests/contracts/` test
ports, and `_runner.py` is not one - it is private plumbing behind three of them, `Workspace`,
`Integrator` and `History`, reached only from inside `agl/adapters/git/`. What it promises is
instead a set of claims about one program, and every test below provokes the real program into
making them true or false.

**Nothing here mocks a subprocess.** A fabricated exit status would assert that this file and
`_runner.py` remember the same numbers, which is a fact about two files rather than about git: the
whole deliverable is the mapping from what git actually does to what `ports/errors.py` means, and a
fake git is written by the same hand that wrote the mapping. So a missing binary is a `PATH` with
nothing in it, a refusal is git refusing, a timeout is git genuinely taking too long, and a signal
death is git genuinely being signalled. The one thing arranged rather than provoked is the
environment: the repositories below carry no global or system git configuration, so a developer's
own `~/.gitconfig` cannot decide whether this suite passes.

**One failure below is not git's at all**, and it is the only one: a value that cannot be encoded
for a child process. `os.fsencode` runs inside `asyncio.create_subprocess_exec`, before any binary
is looked for, so no git is involved and none is blamed - and it is provoked rather than fabricated
here too, because Python genuinely refuses these values. It is why `InputError` is in this module's
mapping.

**What is not covered here, and why.** The classification of an unreadable *parse* is
`unreadable`'s, and that is a function returning an error rather than a thing git does, so it is
asserted directly. `DeniedError` is nowhere in this module's mapping - an unreadable repository is
`UpstreamUnavailable`, and a refusal on grounds of permission is a refusal like any other, whose
meaning the call site names - so there is nothing here to provoke.

Named `test_git_runner.py`, for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import asyncio
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Final
import pytest
from agl.adapters.git import _runner as git_runner
from agl.adapters.git._runner import GitRunner, unreadable
from agl.ports.errors import (
    ConflictError,
    InputError,
    NotFoundError,
    UpstreamError,
    UpstreamUnavailable,
    UpstreamUnexpected,
    exit_code_for,
)

# On the module rather than on each test, and every test here is `async` so that it applies to all
# of them: `asyncio_mode = "strict"` turns a missing marker into a test pytest quietly skips, which
# is how a file like this passes against an implementation it never called. Two tests below need
# no event loop and are `async` anyway, which costs nothing and leaves no test in this file able to
# be added without the marker.
pytestmark = pytest.mark.asyncio

# Something well-formed that no repository built here holds, and forty characters of lowercase hex
# naming no state anywhere - the same two shapes `tests/contracts/history.py` refuses with, so that
# what is provoked below is absence rather than a malformed argument.
ABSENT_REF: Final = "agl-runner-test-names-no-such-thing"
ABSENT_ID: Final = "dead" * 10

# Asking git whether a ref resolves, with `--end-of-options` where `_runner.py` says it belongs:
# argv discipline stops an argument being read as shell syntax and does nothing about one being
# read as a git option, so the call site is where that door gets closed.
VERIFY: Final = ("rev-parse", "--verify", "--end-of-options")

# A filename holding every metacharacter that would matter if any of this reached a shell. It is a
# real file, committed, and asked about by this exact name: the command substitutions would leave
# their marks behind, and git would not find the file, if an interpreter ever saw the argument.
DANGEROUS: Final = "a;b$(touch subshell)`touch backtick`&&touch chained.txt"
MARKS: Final = ("subshell", "backtick", "chained")

# git's own convention for making a subcommand out of a shell command. Ironic in a test for a
# module whose thesis is that no shell sees anything, and unavoidable: nothing git does on a small
# repository is slow enough to time out, and nothing else can make it take a measurable moment or
# be signalled from inside. The shell here is git's, spelled in git's configuration, and it changes
# nothing about how the runner invokes git.
SLOW: Final = ("-c", "alias.slow=!sleep 3", "slow")
SELF_SIGNALLING: Final = ("-c", "alias.boom=!kill -TERM $PPID", "boom")

# The two values no child process can be handed. `chr` rather than the escape, and a scalar rather
# than a tuple of them: a module-level `Final` holding a surrogate *literal* crashes `mypy --strict`
# inside its own cache with no file named, which `tests/test_no_literal_surrogates.py` is the fence
# around and this is one of the spellings that fence permits.
LONE_SURROGATE: Final = chr(0xD800)
EMBEDDED_NUL: Final = "a\x00b"

def _git(repository: Path, *argv: str) -> str:
    """Run git for the fixtures. Synchronous on purpose: this is arrangement, not the thing under
    test, and a test that built its repository through the runner would be resting the arrangement
    on the mapping it is about to check."""
    done = subprocess.run(
        ["git", *argv], cwd=repository, capture_output=True, text=True, check=True
    )
    return done.stdout

@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A real repository with one commit in it, and no configuration from this machine.

    The three `GIT_CONFIG_*` variables are what make this suite the same suite everywhere: a
    developer with `commit.gpgsign` on, or a template directory, or an `init.defaultBranch` of
    their own, would otherwise be running different tests. They are set through `monkeypatch` so
    that the runner - which inherits the environment, and says so - sees them too.
    """
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL contract")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "first.txt").write_text("first\n", encoding="utf-8")
    _git(work, "add", "first.txt")
    _git(work, "commit", "-q", "-m", "first")
    yield work

@pytest.fixture
def runner(repository: Path) -> GitRunner:
    """The runner under test, over that repository, with the module's own default timeout."""
    return GitRunner(repository)

# --- What comes back when git answers -----------------------------------------------------------

async def test_a_command_that_succeeds_hands_back_what_git_wrote(
    runner: GitRunner, repository: Path
) -> None:
    """The ordinary path: an argv list in, git's standard output out, nothing raised."""
    head = await runner.run("rev-parse", "HEAD", refusal=ConflictError)

    assert head.strip() == _git(repository, "rev-parse", "HEAD").strip()
    assert head.endswith("\n"), (
        "the output was stripped on the way through. A `-z` form ends in a NUL that is data, and "
        "a runner that tidied one line would silently eat the last field of the next parse"
    )

async def test_output_that_is_not_utf8_comes_back_with_replacements_rather_than_surrogates(
    runner: GitRunner, repository: Path
) -> None:
    """Git's output is bytes, and AGL's records are text a store has to be able to write.

    `surrogateescape` would round-trip and would mint exactly the lone surrogates `ports/run.py`
    and `adapters/filesystem/_documents.py`'s `_encoded` refuse, so an odd byte in a path would
    surface three layers later as an `InternalError` at a write. U+FFFD is lossy, visible, and
    storable, which is the trade `_runner.py` states rather than hides.
    """
    (repository / "bytes.bin").write_bytes(b"a\xffb")
    _git(repository, "add", "bytes.bin")
    _git(repository, "commit", "-q", "-m", "bytes")

    content = await runner.run("cat-file", "blob", "HEAD:bytes.bin", refusal=ConflictError)

    assert content == "a�b"
    assert not any("\ud800" <= character <= "\udfff" for character in content), (
        "a lone surrogate reached a caller, and the store refuses to write one"
    )

async def test_answers_reads_gits_yes_and_no_off_the_exit_status(
    runner: GitRunner, repository: Path
) -> None:
    """`merge-base --is-ancestor` is the shape `answers` exists for: 0 is yes and 1 is no.

    Both directions, because an implementation that answered a constant would pass one of them -
    and `History.contains` is the member that decides whether a landing happened, so a constant
    there is not a small mistake.
    """
    (repository / "second.txt").write_text("second\n", encoding="utf-8")
    _git(repository, "add", "second.txt")
    _git(repository, "commit", "-q", "-m", "second")

    ancestry = ("merge-base", "--is-ancestor")
    assert await runner.answers(*ancestry, "HEAD~1", "HEAD", refusal=NotFoundError)
    assert not await runner.answers(*ancestry, "HEAD", "HEAD~1", refusal=NotFoundError)

# --- A refusal git states deliberately ----------------------------------------------------------

async def test_the_same_refusal_raises_whichever_class_the_call_site_named(
    runner: GitRunner,
) -> None:
    """The whole of how `NotFoundError` reaches here, in one test.

    One git failure - a ref this repository does not hold - asked about twice, and the class
    raised is the one the caller declared each time. That is the argument made assertable: git
    spells "absent" and "already taken" identically, so the meaning cannot come from git, and it
    comes from the question's author rather than from a table of subcommands in the runner.
    """
    with pytest.raises(NotFoundError) as absent:
        await runner.run(*VERIFY, ABSENT_REF, refusal=NotFoundError)
    with pytest.raises(ConflictError):
        await runner.run(*VERIFY, ABSENT_REF, refusal=ConflictError)

    assert ABSENT_REF in str(absent.value), (
        "the message does not say what was asked. git's own sentence is the only thing a person "
        "has to go on here, which is why it is carried into the error rather than handed back"
    )

async def test_a_conflict_git_states_is_the_refusal_a_worktree_provider_will_declare(
    runner: GitRunner,
) -> None:
    """`ConflictError` provoked by git actually refusing to overwrite something that exists.

    The shape a workspace provider meets: a line of work under a name already taken.
    `errors.py` calls this "the
    world already holds something this operation would have to take or overwrite", and nothing has
    been changed when it is raised, which is what the assertion after it checks.
    """
    await runner.run("branch", "spoken-for", refusal=ConflictError)

    with pytest.raises(ConflictError) as refused:
        await runner.run("branch", "spoken-for", refusal=ConflictError)

    assert "spoken-for" in str(refused.value)
    assert await runner.run(*VERIFY, "spoken-for", refusal=NotFoundError)

async def test_answers_refuses_a_status_that_is_not_one_of_the_two_answers(
    runner: GitRunner,
) -> None:
    """A made-up commit id is not "not an ancestor", and reading 128 as "no" would say it was.

    `tests/contracts/history.py` requires `NotFoundError` from `contains` for a well-formed id
    this repository does not hold; git answers that with 128 rather than with 1. So `answers`
    takes the same `refusal` its sibling does and consults it for everything outside 0 and 1.
    """
    with pytest.raises(NotFoundError):
        await runner.answers(
            "merge-base", "--is-ancestor", ABSENT_ID, "HEAD", refusal=NotFoundError
        )

# --- git is not there ---------------------------------------------------------------------------

async def test_a_directory_with_no_repository_is_unavailable_whatever_the_caller_declared(
    tmp_path: Path,
) -> None:
    """The distinction the module exists for, at its sharpest.

    The same command, the same declared refusal, and a directory git cannot read a repository in:
    the answer is `UpstreamUnavailable` and not the caller's `NotFoundError`, because the ref was
    never looked for. Exit 6 says "the same call may well succeed later"; exit 3 would send a
    person hunting for a ref in a repository that is not there.
    """
    empty = tmp_path / "not-a-repository"
    empty.mkdir()

    with pytest.raises(UpstreamUnavailable) as unreachable:
        await GitRunner(empty).run("rev-parse", "HEAD", refusal=NotFoundError)

    assert str(empty) in str(unreachable.value)

async def test_a_git_that_is_not_on_path_is_unavailable(
    runner: GitRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Not mocked: `PATH` is emptied, so the binary is genuinely unfindable at exec.

    `UpstreamUnavailable` names this case in its own docstring - "its CLI is not on `PATH`" - and
    it is the one failure where nothing whatever happened, so the same call succeeds the moment
    git is installed.
    """
    nowhere = tmp_path / "empty-path"
    nowhere.mkdir()
    monkeypatch.setenv("PATH", str(nowhere))

    with pytest.raises(UpstreamUnavailable) as missing:
        await runner.run("rev-parse", "HEAD", refusal=ConflictError)

    assert "could not be started" in str(missing.value)

async def test_a_working_directory_that_is_not_there_is_unavailable(tmp_path: Path) -> None:
    """The other way a process fails to start, and the same answer: nothing ran."""
    with pytest.raises(UpstreamUnavailable):
        await GitRunner(tmp_path / "never-created").run("status", refusal=ConflictError)

async def test_a_value_that_cannot_be_encoded_at_all_is_input_and_not_an_upstream_failure(
    runner: GitRunner,
) -> None:
    """The third way a start fails, and the only one where trying again is pointless.

    **It is not git's failure and it is not the repository's.** A child process is handed its
    arguments, its working directory and its environment as *bytes*: `os.fsencode` runs inside
    `asyncio.create_subprocess_exec`, before any binary is looked for. A lone surrogate outside
    `\\udc80`-`\\udcff` has no encoding even under `surrogateescape`, and a `str` holding a NUL
    cannot be a C string at all - so Python raises before the fork. Provoked and not fabricated,
    like everything else here: Python really does refuse these, and nothing below patches anything.

    **The class it used to be was no class.** `_spawned` caught `OSError`, and both of these are
    `ValueError` - `UnicodeEncodeError` is a subclass of it - so they left this adapter as
    themselves. `cli/main.py`'s last handler prints a traceback and *this is our bug* over anything
    that is not an `AglError`, and `exit_code_for` answers 70 for it. Exit 70 for a string somebody
    passed is the mistake `ports/run.py` and `sdk/_engine/journal.py` were both corrected for: a
    surrogate arrives from outside, so the answer is `InputError` and the number is 2. This is the
    fourth seam that value reaches and it now answers the same as the other three.

    **`InputError` and not `UpstreamUnavailable`, which is the interesting half.** Nothing ran here
    either, so the two look alike from the call site - and `UpstreamUnavailable` means *the same
    call may well succeed later*, which is a claim about a missing binary or an unmounted directory.
    This call encodes the same way every time. Sending a person to check whether git is installed,
    forever, is worse than telling them the value is unusable.

    **Two values and one clause.** `_spawned` passes `create_subprocess_exec` four literals besides
    argv, `cwd` and the environment, so the only `ValueError` reachable from that call is one of
    these three being unencodable - which is why the handler is written about `ValueError` rather
    than about `UnicodeEncodeError` alone, and why the NUL is asserted beside the surrogate rather
    than left to be discovered as a second traceback.
    """
    for value in (LONE_SURROGATE, EMBEDDED_NUL):
        with pytest.raises(InputError) as refused:
            await runner.run(*VERIFY, value, refusal=NotFoundError)

        said = str(refused.value)
        assert exit_code_for(refused.value) == 2, (
            f"a value no process can be handed came back as exit "
            f"{exit_code_for(refused.value)}. It is malformed input and 2 is what says so; the "
            f"three other places AGL meets a surrogate all answer 2, and this one used to answer "
            f"70 by not answering at all"
        )
        assert not isinstance(refused.value, UpstreamError), (
            f"the refusal is an `UpstreamError`, whose whole promise is that the same call may "
            f"succeed later: {said!r}. This one cannot. Nothing about the repository, the binary "
            f"or the machine will change how this text encodes"
        )
        assert "could not be started" in said, (
            f"the message does not say that nothing ran: {said!r}. git received no such argument "
            f"and refused nothing, so a message reading as a refusal sends a person into the "
            f"repository looking for something that was never asked about"
        )

# --- git does not finish, or does not answer at all ----------------------------------------------

async def test_a_command_that_runs_too_long_is_stopped_and_the_repository_still_works(
    repository: Path,
) -> None:
    """A real timeout: git is genuinely slow, the runner stops it, and the repository survives.

    Three claims in one test, because they are one claim. The call raises `UpstreamUnavailable`.
    It returns in far less time than the command would have taken, which is what says the process
    was actually stopped rather than waited out. And the next git command in that repository
    works - the reason `_stop` sends SIGTERM before SIGKILL is that git unlinks its own lock
    files when asked to stop, and a stale `index.lock` would fail every later command until
    somebody deleted it by hand.
    """
    started = time.monotonic()

    with pytest.raises(UpstreamUnavailable) as stopped:
        await GitRunner(repository, timeout=0.2).run(*SLOW, refusal=ConflictError)

    assert time.monotonic() - started < 2.0, (
        "the runner waited the command out instead of stopping it"
    )
    assert "did not finish" in str(stopped.value)
    assert not list((repository / ".git").glob("*.lock"))
    assert _git(repository, "status", "--porcelain") == ""

async def test_the_timeout_can_be_named_per_call_as_well_as_per_runner(
    runner: GitRunner,
) -> None:
    """A checkout is not a `rev-parse`, and the call that knows that says so.

    The runner's own default is a backstop sized for a `worktree add` on a large repository, which
    makes it useless as a guard on anything small. So a call site that knows its operation's shape
    passes its own.
    """
    with pytest.raises(UpstreamUnavailable):
        await runner.run(*SLOW, refusal=ConflictError, timeout=0.2)

async def test_a_cancelled_call_raises_cancellation_and_not_an_agl_error(
    runner: GitRunner, repository: Path
) -> None:
    """A workflow runs several children at once, so a `TaskGroup` unwinding is an ordinary
    afternoon.

    One claim, and it is the one that matters: `CancelledError` passes through untouched. A runner
    that caught it into an `UpstreamUnavailable` would make a cancelled task look like a failed
    one and would stop a group unwinding at all.

    **It does not prove the process was stopped**, and nothing from out here can: the signal goes
    to a git this test has no handle on, and the `status` below would be clean whether or not it
    landed. That half rests on `_completed` signalling before it re-raises, which is read rather
    than asserted. What `status` does show is that a cancellation leaves the repository usable.
    """
    task = asyncio.create_task(runner.run(*SLOW, refusal=ConflictError))
    await asyncio.sleep(0.2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert _git(repository, "status", "--porcelain") == ""

# --- The two clauses inside `_signal` that no answer can witness ---------------------------------

# `_signal` is what `_stop` spends twice for its terminate-then-kill escalation, and what
# `_completed`'s `except BaseException` spends once on the way out. It is the third copy of a
# sequence `src/agl/adapters/shell/verifier.py` and `src/agl/adapters/openai/_session.py` already
# share, and it differs from them in exactly one line: those two escalate against the child's
# process *group* and this one against the process, because `_spawned` gives its child no session
# of its own. `ARCHITECTURE.md`'s "No general subprocess helper" says why that one line may differ
# and why nothing else may - and the two properties below are what "nothing else" meant. This
# module had neither of them. `tests/adapters/test_shell_verifier.py` argues both at length for the
# pair; what is repeated here is only what is different about git.
#
# They are deliberately not folded into a shared helper: `ARCHITECTURE.md`'s "Deliberately not
# built" refuses one, and `.importlinter`'s adapter-independence contract forbids one adapter
# importing another. Three implementations that have to agree is what these tests are for.

# A git alias that exits at once and leaves something of its own behind holding the pipe. That is
# what puts the child in the state the guard is about - reaped, with the transport still open -
# and it is not contrived: `_completed` reads `communicate()` under a deadline, so any git whose
# grandchild outlives it arrives here.
ORPHAN_SLEEP: Final = 30.0
ORPHANED: Final = "orphan.pid"
ORPHANING: Final = (
    "-c",
    f"alias.orphan=!sleep {ORPHAN_SLEEP:g} & echo $! > {ORPHANED}",
    "orphan",
)

# A git that takes a moment, for the two tests below that deny the signal and then wait the child
# out. Short, because with signalling denied that wait is real: `SLOW`'s three seconds are spent
# proving a timeout is prompt, and these two are spent only on the child dying by itself.
BRIEF: Final = ("-c", "alias.brief=!sleep 1", "brief")

# How long the reaped-child arrangement is given to become the state it is about.
REAPED_WITHIN: Final = 10.0

async def _reaped_with_the_pipe_still_open(repository: Path) -> asyncio.subprocess.Process:
    """A git that has exited and been reaped, whose transport is still open. Fails if it cannot.

    The two halves are what make the guard reachable. `returncode` is set the moment the child
    exits, and asyncio only tears the transport down once every pipe has disconnected as well - so
    a grandchild holding stdout keeps `_proc` alive on a pid the kernel has already handed back.
    Signalling then reaches whatever now holds that number.
    """
    process = await git_runner._spawned(ORPHANING, repository)
    deadline = time.monotonic() + REAPED_WITHIN
    while process.returncode is None and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert process.returncode is not None, (
        f"git did not exit within {REAPED_WITHIN:g}s, so this test is not exercising the guard it "
        f"is about"
    )
    return process

def _orphan(repository: Path) -> int | None:
    """The pid of the grandchild this file started, so the test can take it away again."""
    pidfile = repository / ORPHANED
    if not pidfile.is_file():
        return None
    said = pidfile.read_text(encoding="utf-8").strip()
    return int(said) if said else None

async def test_a_git_that_has_already_been_reaped_is_never_signalled(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reaped pid is the kernel's to hand out again, so signalling one signals whoever holds it.

    **The window is real here and it is not the pair's.** `verifier.py` reaches `os.killpg` with the
    pid itself and gets no help from anything; this module calls `process.send_signal`, and asyncio
    does raise `ProcessLookupError` once it has torn the transport down - which is why the ordinary
    reap looks safe from outside. It is only safe until a pipe outlives the child. asyncio finishes
    a transport when the process has exited *and* every pipe has disconnected, so a git whose
    grandchild inherited stdout leaves `returncode` set with `_proc` still open, and
    `BaseSubprocessTransport.send_signal` on POSIX is `os.kill(self._proc.pid, signal)` with no
    check of its own. That is exactly the shape `_completed` produces: it reads `communicate()`
    under a deadline, and the deadline expires because something is still holding the pipe.

    So the arrangement is a git that exits immediately and backgrounds a `sleep` that does not, and
    the guard being the module's own rather than borrowed from asyncio is the point of writing it.

    **The instrument is a spy, and it has to be.** `test_shell_verifier.py` argues this for its own
    copy: "a process group that was *not* signalled" has no witness, arranging a real pid reuse
    would mean starting processes until the kernel handed back a number this test had released, and
    a green result would still not tell "nothing was signalled" from "something was, and it was not
    looking". `os.kill` is the call the transport makes, so that is what is replaced, and the
    assertion is that it was never reached. Nothing is awaited between the substitution and the two
    calls, which is also why `returncode is not None` is exact rather than best-effort: the loop's
    reaping callback is what sets it, and it cannot run inside a function with no `await` in it.
    """
    process = await _reaped_with_the_pipe_still_open(repository)
    signalled: list[tuple[int, int]] = []

    def recorded(pid: int, number: int) -> None:
        signalled.append((pid, number))

    monkeypatch.setattr(os, "kill", recorded)
    try:
        git_runner._signal(process, signal.SIGTERM)
        git_runner._signal(process, signal.SIGKILL)
    finally:
        monkeypatch.undo()
        orphan = _orphan(repository)
        if orphan is not None:
            with suppress(ProcessLookupError):
                os.kill(orphan, signal.SIGKILL)

    assert signalled == [], (
        f"a git that had already exited and been reaped was signalled anyway: {signalled}. Its pid "
        f"went back to the kernel when it was reaped, so this is a signal aimed at whatever now "
        f"holds the number - which on a machine running a build is whatever started next. Nothing "
        f"in this adapter's answer would ever show it"
    )

async def test_a_signal_the_os_refuses_leaves_the_timeout_saying_what_it_always_says(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`PermissionError` may not leave this adapter, and the deadline is where it would.

    `_stop` is called from inside `except TimeoutError:`, one line before the
    `UpstreamUnavailable` that says the command was stopped. A signal the kernel refuses used to
    raise straight out of there - `suppress(ProcessLookupError)` does not cover it - so the whole
    call came back as a bare `PermissionError`. That is an `OSError`, not an `AglError`, so
    `cli/main.py`'s last handler prints a traceback and *this is our bug*, and `exit_code_for`
    answers 70: a timeout reported as a crash in AGL.

    The two siblings answer a denied signal by falling back from the group to the child itself.
    This module has no group to be denied - it signals the process, which is the one line
    `ARCHITECTURE.md` allows to differ - so there is nothing left to fall back *to*, and what it
    owes is the other half of what they promise: the escalation carries on and the caller gets this
    adapter's own answer. `_stop` still waits the child out, which is why the alias here sleeps
    for a second rather than three.

    Asserted by effect through `run`, not by a spy: what is being claimed is what a caller sees.
    """

    def denied(pid: int, number: int) -> None:
        raise PermissionError(f"signalling {pid} is not permitted")

    monkeypatch.setattr(os, "kill", denied)

    with pytest.raises(UpstreamUnavailable) as stopped:
        await GitRunner(repository, timeout=0.2).run(*BRIEF, refusal=ConflictError)

    assert "did not finish" in str(stopped.value), (
        f"the deadline came back saying something else: {str(stopped.value)!r}. A signal the "
        f"kernel would not deliver does not change what happened - git was asked to stop and did "
        f"not answer in time"
    )

async def test_a_cancelled_call_still_raises_cancellation_when_the_signal_is_refused(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same clause in the other place that spends it, where getting it wrong is worse.

    `_completed`'s `except BaseException:` signals and re-raises. A `PermissionError` out of that
    line does not merely mislabel a failure - it **replaces the exception being unwound with a
    different one**, so a `CancelledError` never arrives, the `TaskGroup` above it does not treat
    the group as cancelled, and what a workflow author reads is a permission problem they do not
    have. The test above this section pins that cancellation passes through untouched; this pins
    that it still does when the stop cannot be delivered.

    It is the same defect as the deadline's and it is treated the same way, which is the whole
    reason both places now go through one guarded helper rather than each calling `terminate()`
    under a `suppress` of its own.
    """

    def denied(pid: int, number: int) -> None:
        raise PermissionError(f"signalling {pid} is not permitted")

    task = asyncio.create_task(GitRunner(repository).run(*BRIEF, refusal=ConflictError))
    await asyncio.sleep(0.2)
    monkeypatch.setattr(os, "kill", denied)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

async def test_a_command_runs_where_the_caller_said_and_not_where_the_runner_lives(
    runner: GitRunner, repository: Path
) -> None:
    """`cwd=` is how `Workspace.commit_all` commits inside one worktree rather than in the
    repository the runner was built with, so a runner that quietly ignored it would record every
    step's work in the wrong tree.

    Asserted with `rev-parse --show-prefix`, whose whole output is where git thinks it is.
    """
    inner = repository / "nested"
    inner.mkdir()

    prefix = await runner.run("rev-parse", "--show-prefix", cwd=inner, refusal=ConflictError)

    assert prefix.strip() == "nested/"
    assert (await runner.run("rev-parse", "--show-prefix", refusal=ConflictError)).strip() == ""

async def test_a_git_killed_by_a_signal_is_unexpected_rather_than_the_callers_refusal(
    runner: GitRunner,
) -> None:
    """git dying is not git refusing, and `errors.py` has the sentence for it.

    Provoked rather than fabricated: the alias signals git itself from inside, so the process
    really is terminated by a signal nobody in `_runner.py` sent. `UpstreamUnexpected` is that
    class's own "a subprocess exited with a status the adapter has no meaning for" - reporting it
    as `ConflictError` would claim git had decided something, when it never got that far.
    """
    with pytest.raises(UpstreamUnexpected) as died:
        await runner.run(*SELF_SIGNALLING, refusal=ConflictError)

    assert "killed by signal" in str(died.value)

# --- No shell, ever -------------------------------------------------------------------------------

async def test_an_argument_that_would_be_dangerous_in_a_shell_arrives_literally_and_does_nothing(
    runner: GitRunner, repository: Path
) -> None:
    """The guarantee namespace values rest on, asserted from both sides.

    A file whose name holds a command substitution, a backtick pair and a `&&` is committed, then
    asked about by that exact name. git finds it, which is the *literal* half - an interpreter
    would have mangled the argument into something naming no file - and none of the three marks
    those commands would leave exists afterwards, which is the *harmless* half.

    The `[A-Za-z0-9._-]` allowlist in `src/agl/ports/ids.py` would refuse this name as a namespace,
    and that is the point
    of asserting it here: the charset is defence in depth and this is the guarantee underneath it,
    so it has to hold for a value the charset would never have let through.
    """
    (repository / DANGEROUS).write_text("literal\n", encoding="utf-8")
    _git(repository, "add", "--", DANGEROUS)
    _git(repository, "commit", "-q", "-m", "dangerous")

    content = await runner.run("cat-file", "blob", f"HEAD:{DANGEROUS}", refusal=NotFoundError)

    assert content == "literal\n", (
        "git did not resolve the path it was handed, which is what happens to a name an "
        "interpreter has been at"
    )
    for mark in MARKS:
        assert not (repository / mark).exists(), f"a shell ran the {mark!r} half of the argument"

async def test_a_dangerous_argument_that_names_nothing_still_only_refuses(
    runner: GitRunner, repository: Path
) -> None:
    """The same string down the failure path, where a naive implementation would interpolate it.

    An error message is the one place a rejected argument is guaranteed to be handled, and the
    failure path is where a `f"git {command}"` would have been written. Nothing runs, and the
    answer is the class the caller named.
    """
    with pytest.raises(NotFoundError):
        await runner.run(*VERIFY, DANGEROUS, refusal=NotFoundError)

    for mark in MARKS:
        assert not (repository / mark).exists()

# --- The error a caller raises when its own parse fails -------------------------------------------

async def test_unreadable_says_the_repository_is_fine_and_our_reading_of_it_is_not() -> None:
    """`UpstreamUnexpected`, spelled once for the three adapters that parse porcelain.

    A function returning an error rather than anything git does, which is the whole reason it can
    live in the runner instead of being repeated in `workspace.py`, `history.py` and
    `integrator.py` in three different sentences. `async` only so that it carries the module's
    marker like everything else here - see this file's docstring for why that is not optional.
    """
    error = unreadable("a worktree registration", "worktree /somewhere\x00nonsense")

    assert isinstance(error, UpstreamUnexpected)
    assert "a worktree registration" in str(error)
    assert "nonsense" in str(error)

async def test_unreadable_does_not_put_a_whole_patch_in_a_message() -> None:
    """A message a person reads on a terminal is not the place for a megabyte of output."""
    error = unreadable("a change entry", "x" * 10_000)

    assert len(str(error)) < 1_000
    assert "..." in str(error)
