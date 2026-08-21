"""`GitRunner` against real git, in real repositories, because that is the only thing it claims.

There is no contract suite here and there is not meant to be: the suites in `tests/contracts/` test
ports, and `_runner.py` is not one - it is private plumbing behind three of them (§3.4), reached
only from inside `agl/adapters/git/`. What it promises is instead a set of claims about one
program, and every test below provokes the real program into making them true or false.

**Nothing here mocks a subprocess.** A fabricated exit status would assert that this file and
`_runner.py` remember the same numbers, which is a fact about two files rather than about git: the
whole deliverable is the mapping from what git actually does to what `ports/errors.py` means, and a
fake git is written by the same hand that wrote the mapping. So a missing binary is a `PATH` with
nothing in it, a refusal is git refusing, a timeout is git genuinely taking too long, and a signal
death is git genuinely being signalled. The one thing arranged rather than provoked is the
environment: the repositories below carry no global or system git configuration, so a developer's
own `~/.gitconfig` cannot decide whether this suite passes.

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
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.git._runner import GitRunner, unreadable
from agl.ports.errors import (
    ConflictError,
    NotFoundError,
    UpstreamUnavailable,
    UpstreamUnexpected,
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
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "AGL contract")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "agl@example.invalid")
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
    and `FilesystemStore._encoded` refuse, so an odd byte in a path would surface three layers
    later as an `InternalError` at a write. U+FFFD is lossy, visible, and storable, which is the
    trade `_runner.py` states rather than hides.
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
    and `History.contains` is the member that decides whether `clear` tidies a run up or destroys
    it, so a constant there is not a small mistake.
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

    The shape 5.2 meets: a line of work under a name already taken. `errors.py` calls this "the
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


# --- git does not finish, or does not answer at all ----------------------------------------------


async def test_a_command_that_runs_too_long_is_stopped_and_the_repository_still_works(
    repository: Path,
) -> None:
    """A real timeout: git is genuinely slow, the runner stops it, and the repository survives.

    Three claims in one test, because they are one claim. The call raises `UpstreamUnavailable`.
    It returns in far less time than the command would have taken, which is what says the process
    was actually stopped rather than waited out. And the next git command in that repository
    works - the reason `_stopped` sends SIGTERM before SIGKILL is that git unlinks its own lock
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

    The runner's own default is a backstop sized for a `worktree add` on a large repository
    (§3.9), which makes it useless as a guard on anything small. So a call site that knows its
    operation's shape passes its own, and this is the parameter 5.2 will reach for first.
    """
    with pytest.raises(UpstreamUnavailable):
        await runner.run(*SLOW, refusal=ConflictError, timeout=0.2)


async def test_a_cancelled_call_raises_cancellation_and_not_an_agl_error(
    runner: GitRunner, repository: Path
) -> None:
    """§3.9 runs several children at once, so a `TaskGroup` unwinding is an ordinary afternoon.

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


async def test_a_command_runs_where_the_caller_said_and_not_where_the_runner_lives(
    runner: GitRunner, repository: Path
) -> None:
    """`cwd=` is how 5.2 commits inside one worktree rather than in the repository it was built
    with, so a runner that quietly ignored it would record every step's work in the wrong tree.

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

    §3.3's `[A-Za-z0-9._-]` allowlist would refuse this name as a namespace, and that is the point
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
