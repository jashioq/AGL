"""`ShellVerifier` and `FakeVerifier` against the `Verifier` contract, plus the one clause that
suite says it cannot assert - here, where it has a witness.

The first two classes are the port in full: `VerifierContract` with its four fixtures overridden
and nothing else touched, run once against the real adapter and once against the fake. That suite
was written at stage 3, against the port's docstrings and before either implementation existed,
which is the inversion the build rests on (§1.9) and the reason nothing below re-asserts any of it.

**Two of those fixtures are where that suite is armed or disarmed, and it says so about itself.**
Its first gap is the port's one security clause - that `workdir` is never interpolated into the
command text - and it cannot assert it because it does not choose `workdir`: "the test would be
armed by the party it is meant to catch, and an author who supplies a tame path disarms it
silently". So the `workdir` fixture below is not `tmp_path`. It is a directory whose *name* is a
command substitution, a semicolon, a pipe, a background operator, two kinds of quote and some
spaces - a name that would change the answer, or run something, the moment anything pasted it into
a command line. The `failing_command` fixture is the other one: the suite leaves the choice of
stream to the implementer and states the reason to pick the untidy one - "a runner that keeps only
the tidy stream is one this fixture can be pointed at to catch" - so it announces on stderr.

What follows the two classes is what the suite lists as beyond it, in the order it lists them:

  * **That the workspace path is never interpolated** (gap 1). Asserted three ways, because a
    green result has to be readable: a directory whose name would create a file if any shell ever
    evaluated it, with a control that proves the name really is loaded; a build that reports the
    directory it ran in, which is what tells `cwd=` from a path quietly ignored; and this module's
    own source, parsed, so that "no expression holds both values" is a fact about the code rather
    than a claim in a docstring.
  * **That an expired deadline is a failed build and not an exception, and that it stops the work**
    (gap 6). The port settles the first; the second is this adapter's own promise, and a deadline
    that leaves a compile running is not one.
  * **`UpstreamUnavailable` when the command cannot be started** (gap 3). "Provoking it means
    breaking the runner itself", which from out here is one directory that is not there.
  * **That an empty `output` from a passing build is accepted** (gap 5). Every command in that
    suite came from a fixture, so a runner that crashed on a silent build would not be caught.
  * **That both streams arrive** (gap 7). Partially: the suite asserts an announcement comes back
    and cannot see which stream it was on.

Named `test_shell_verifier.py`, for the module it covers: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import ast
import asyncio
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.shell import verifier as verifier_module
from agl.adapters.shell.fake import FakeVerifier
from agl.adapters.shell.verifier import ShellVerifier
from agl.ports.errors import UpstreamUnavailable
from agl.ports.verifier import Verifier
from contracts.verifier import ANNOUNCEMENT, VerifierContract

# A directory name that is a loaded gun, handed to every test in the contract suite below.
#
# `$(exit 7)` is a command substitution, `;` ends a command, `|` starts a pipeline, `&` puts one in
# the background, and the quotes and spaces are what a naive `cd {workdir} && {command}` would
# split on. If this name ever reached a command line, `exit 7` would run, `echo leaked` would print
# a word no build here ever prints, and the `cd` would be looking for a directory whose name is the
# first space-separated fragment of this one - so the build's verdict would be decided by the path
# rather than by the command, which is the failure this fixture exists to make visible. A `/` and a
# NUL are the only bytes a filename cannot hold; everything else here is legal on every filesystem
# AGL runs on, which is exactly why §3.3's allowlist is defence in depth and not the guarantee.
HOSTILE_NAME: Final = "agl $(exit 7); echo leaked | cat & 'q' \"d\" tree"

# What the real adapter is asked to run. Both are `/bin/sh`, since that is what a shell verifier
# is; the announcement goes to **stderr** for the reason the suite's own fixture docstring gives.
SHELL_PASSING: Final = "exit 0"
SHELL_FAILING: Final = f"echo {ANNOUNCEMENT} >&2; exit 1"

# What the fake is scripted with. Two strings that look like build commands and are only ever keys:
# nothing runs them, which is the whole of what the fake is for.
FAKE_PASSING: Final = "npm run build"
FAKE_FAILING: Final = "npm test"
FAKE_FAILING_OUTPUT: Final = f"2 failing\n{ANNOUNCEMENT}\n"


def hostile_directory(tmp_path: Path, name: str = HOSTILE_NAME) -> Path:
    """A real directory under `tmp_path` whose name would misbehave if it were ever executed."""
    hostile = tmp_path / name
    hostile.mkdir()
    return hostile


class TestShellVerifier(VerifierContract):
    """The port in full, against a real shell and real processes.

    Four overrides and nothing else, which is what the suite asks for. The deadline is the
    adapter's default: nothing here waits long enough to meet it, and the tests that do build
    their own verifier with one they can afford.
    """

    @pytest.fixture
    def verifier(self) -> Verifier:
        """The adapter, built with its deadline and nothing else, as the port requires."""
        return ShellVerifier()

    @pytest.fixture
    def workdir(self, tmp_path: Path) -> Path:
        """**Not `tmp_path`.** A directory whose name is a command substitution and a pipeline.

        The suite's first gap says it cannot assert the never-interpolate clause partly because
        this fixture is written by the party the clause is meant to catch, and "an author who
        supplies a tame path disarms it silently". This one does not disarm it: every test in the
        suite runs its build in a directory whose name, pasted into any command line, would run
        `exit 7`, print `leaked`, and leave the `cd` pointing at somewhere that does not exist.
        A green suite is therefore also a statement that none of that happened.
        """
        return hostile_directory(tmp_path)

    @pytest.fixture
    def passing_command(self) -> str:
        """A build that passes and prints nothing, which is what passing builds routinely do."""
        return SHELL_PASSING

    @pytest.fixture
    def failing_command(self) -> str:
        """A build that fails and announces on **stderr**, which is the untidy stream.

        The suite leaves the choice open and names the reason to make it this way: this port has
        one `output` field where a local runner has two streams, so an adapter that kept only
        stdout would pass every other assertion and hand a person an empty failure screen. Pointing
        the fixture at stderr is what turns that into a failing test.
        """
        return SHELL_FAILING


class TestFakeVerifier(VerifierContract):
    """The same suite, against the fake - which is the mechanism that stops it drifting (§1.9).

    The fixtures differ in exactly one thing that matters, the implementation under test. The
    hostile directory is handed over here too, although nothing in the fake can be endangered by
    it: the two subclasses are meant to be readable side by side, and a tame path here would
    suggest the fixture is about the fake rather than about the suite.
    """

    @pytest.fixture
    def verifier(self) -> Verifier:
        """The fake, scripted with the two answers the suite is about to ask for."""
        fake = FakeVerifier()
        fake.answers(FAKE_PASSING, passed=True)
        fake.answers(FAKE_FAILING, passed=False, output=FAKE_FAILING_OUTPUT)
        return fake

    @pytest.fixture
    def workdir(self, tmp_path: Path) -> Path:
        """The same armed directory. The fake accepts it and never reads it."""
        return hostile_directory(tmp_path)

    @pytest.fixture
    def passing_command(self) -> str:
        """The command scripted to pass, printing nothing."""
        return FAKE_PASSING

    @pytest.fixture
    def failing_command(self) -> str:
        """The command scripted to fail, carrying the announcement it was scripted with."""
        return FAKE_FAILING


# --- Gap 1: the workspace path is a directory and never program text ----------------------------

# A filename with no shell metacharacters in it, so that its appearance can only mean one thing:
# something evaluated the directory name it is hidden inside.
MARKER: Final = "AGL-A-SHELL-EVALUATED-THE-PATH"

# The name of the directory the build below runs in. `touch` needs no `/` to be dangerous, which
# is what makes this expressible as one path component: wherever the shell that evaluated it was
# standing, a file appears.
LOADED_NAME: Final = f"agl $(touch {MARKER}) tree"


@pytest.mark.asyncio
async def test_a_workdir_whose_name_would_run_a_command_never_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The port's one security clause, with the witness the contract suite says it lacks.

    That suite's gap 1 rejects the obvious test on two counts. The second is that a green result
    could not be read - *"nothing interpolated this path" and "this path had nothing in it to
    interpolate" produce the same `VerifierOutcome`* - so this test fires the gun before checking
    that the adapter did not. The control below is deliberately the thing the adapter must never
    do: one `shell=True` command with the directory pasted into it, which creates `MARKER` and
    proves the name is loaded. Only then is the marker removed and the adapter asked to run a
    build in the same directory.

    `monkeypatch.chdir` puts this process inside `tmp_path` first, so that a substitution evaluated
    by *any* shell - one given the hostile directory as `cwd`, or one inheriting this process's -
    leaves its file somewhere this test can see and nowhere it could do harm.

    The verdict is asserted as well as the marker, because they fail differently: a `cd` to a
    directory whose name has been split on spaces fails, and a build that answered `False` here
    would be one whose verdict the path decided.
    """
    monkeypatch.chdir(tmp_path)
    hostile = hostile_directory(tmp_path, LOADED_NAME)

    subprocess.run(f"cd {hostile}", shell=True, cwd=tmp_path, capture_output=True, check=False)
    fired = sorted(tmp_path.rglob(MARKER))
    assert fired, (
        f"the control did not fire: pasting {LOADED_NAME!r} into a command line was supposed to "
        f"run `touch {MARKER}` and create a file, and no such file appeared. This test's whole "
        f"value is that the directory name is dangerous, so a fixture that is not disarms it"
    )
    for stray in fired:
        stray.unlink()

    outcome = await ShellVerifier().verify(SHELL_PASSING, hostile)

    assert not sorted(tmp_path.rglob(MARKER)), (
        f"a build ran in a directory whose name holds `$(touch {MARKER})` and the file appeared, "
        f"so the path reached a shell as text. It is passed as `cwd=` precisely so that it cannot"
    )
    assert outcome.passed is True, (
        f"a build that is `{SHELL_PASSING}` came back failed with output {outcome.output!r} when "
        f"its working directory was named {LOADED_NAME!r}, so the path decided the verdict"
    )


@pytest.mark.asyncio
async def test_the_build_really_ran_inside_the_directory_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cwd=` was used, rather than the path being quietly ignored.

    The other half of the same clause, and the half that keeps the test above honest: an adapter
    that dropped `workdir` on the floor would pass every assertion about markers that did not
    appear, while running every build in whatever directory the framework happened to be standing
    in. Two witnesses, because they fail differently - what the build says its directory is, and
    where a file it created actually landed.

    `pwd -P` rather than `pwd`, and `resolve()` on both sides: `/var` is a symlink to `/private/var`
    on this platform, so the logical and physical spellings of a temporary directory differ and a
    string comparison would be asserting something about symlinks.

    `monkeypatch.chdir` is not part of the assertion. It is here so that an adapter which ignored
    `workdir` entirely writes its file into a temporary directory rather than into the repository
    this test is running out of - a failing test may leave a mess, and not in somebody's checkout.
    """
    monkeypatch.chdir(tmp_path)
    hostile = hostile_directory(tmp_path)

    outcome = await ShellVerifier().verify("pwd -P; : > landed.txt", hostile)

    assert outcome.passed is True, f"the build failed: {outcome.output!r}"
    assert Path(outcome.output.strip()).resolve() == hostile.resolve(), (
        f"a build asked where it was standing answered {outcome.output.strip()!r}, and it was "
        f"given {str(hostile)!r}. The working directory is passed as `cwd=`, so this is where it "
        f"has to have run"
    )
    assert (hostile / "landed.txt").is_file(), (
        "a build created a file with a relative path and it did not land in the directory the "
        "build was given, so the workspace was not this process's working directory for it"
    )


# A directory name whose fragments are a command that leaves a file behind and a command that
# prints a word, so that either one running is visible from outside.
EXTRA: Final = "AGL-AN-EXTRA-COMMAND-RAN"
LEAK: Final = "AGL-LEAKED-FROM-THE-PATH"
CHAINED_NAME: Final = f"agl; touch {EXTRA}; echo {LEAK} | cat"
TOKEN: Final = "AGL-THE-BUILD-ITSELF-PRINTED-THIS"


@pytest.mark.asyncio
async def test_a_workdir_holding_a_semicolon_and_a_pipe_decides_nothing_about_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The metacharacters `ids.py` refuses, in the half of a path `ids.py` never sees.

    §3.3's allowlist refuses `;` and `|` in a namespace, and this directory holds both - which is
    the point of the port's paragraph about what a charset cannot reach. A name like this is one
    `mkdir` away for any user who chose a trees root with a semicolon in it, and nothing in AGL
    is asked about that name.

    Three witnesses for one clause. The verdict is the command's, which a naive `cd` would have
    taken over; nothing named `EXTRA` exists anywhere under the temporary directory, which is what
    a second command running would leave; and `LEAK` is absent from the output, which is what a
    pipeline hidden in the path would have printed into it. A passing command is used deliberately:
    a failing one would come back failed either way, and would prove nothing about who decided.
    """
    monkeypatch.chdir(tmp_path)
    hostile = hostile_directory(tmp_path, CHAINED_NAME)

    outcome = await ShellVerifier().verify(f"echo {TOKEN}", hostile)

    assert outcome.passed is True, (
        f"a build that only echoes came back failed with output {outcome.output!r}, in a "
        f"directory named {CHAINED_NAME!r}. The path is not part of the command"
    )
    assert TOKEN in outcome.output, f"the build's own output did not come back: {outcome.output!r}"
    assert LEAK not in outcome.output, (
        f"{LEAK!r} appears in a build's output and no build here prints it - it is a fragment of "
        f"the directory name, so a pipeline hidden in the path ran and printed into the transcript"
    )
    assert not sorted(tmp_path.rglob(EXTRA)), (
        f"a file named {EXTRA!r} exists, and the only place that name appears is inside the "
        f"working directory's own name after a `;`. A second command ran"
    )


def test_the_adapter_never_builds_a_command_out_of_the_workspace_path() -> None:
    """The structural half: `verifier.py`'s own source, parsed, with both names looked for.

    Every runtime test above shows that a particular hostile path did not reach a shell. This one
    shows there is nothing to reach it *with*: the module is parsed, every expression that can
    build a string out of values - an f-string, a t-string, `+`, `%`, `.format()`, `.join()` - is
    collected, and none of them may have both `command` and `workdir` reachable inside it. The
    spawn itself is then checked directly: one call, its command argument a bare name, its `cwd=`
    a bare name, and the two different.

    **What this does not cover**, said plainly rather than left to be discovered. It reads one
    file, so a helper in another module that joined the two would be invisible to it. It reads
    syntax, so a value laundered through an intermediate - `line = f"cd {workdir}"` and then
    `line + command` - passes, since neither expression holds both names. And it cannot see a call
    assembled at runtime. What covers those is the three tests above: laundering that reached a
    shell would fire the marker, and this pair - the syntax and the effect - is the strongest
    thing available from outside the module. `shlex` is asserted absent from the *code* for the
    reason the port names it - quoting the path into the command is the plausible wrong fix rather
    than the obvious one - and absent from the code only, since the module docstring says as much
    in prose and a check that could not tell a mention from a call would punish the explanation.
    """
    source_path = verifier_module.__file__
    assert source_path is not None, "the verifier module has no source file to read"
    source = Path(source_path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in _interpolations(tree):
        assert not {"command", "workdir"} <= _names(node), (
            f"line {node.lineno} of {source_path} builds a value out of both `command` and "
            f"`workdir`: {ast.unparse(node)!r}. The working directory is passed as `cwd=` and is "
            f"never interpolated into the command text - not joined, not formatted, not quoted"
        )

    spawns = [call for call in ast.walk(tree) if _spawn_of(call) is not None]
    assert len(spawns) == 1, (
        f"{source_path} starts {len(spawns)} processes. This module is one call to "
        f"`create_subprocess_shell`, and a second one is a second place the rule has to hold"
    )
    spawn = spawns[0]
    assert isinstance(spawn, ast.Call)
    assert _spawn_of(spawn) == "create_subprocess_shell", (
        "the build command is a command line the user wrote, operators and all, so it is run "
        "through a shell - see the port on why a program plus arguments cannot express it"
    )
    assert spawn.args, "the shell is started with no command at all"
    program = spawn.args[0]
    assert isinstance(program, ast.Name), (
        f"the shell is handed {ast.unparse(program)!r} rather than one unmodified name, so "
        f"something is being composed on the way in"
    )
    passed_as_cwd = [keyword for keyword in spawn.keywords if keyword.arg == "cwd"]
    assert len(passed_as_cwd) == 1, "the working directory must be passed, and passed as `cwd=`"
    directory = passed_as_cwd[0].value
    assert isinstance(directory, ast.Name) and directory.id != program.id, (
        f"`cwd=` is {ast.unparse(directory)!r}. It is the workspace path, handed over as a "
        f"directory and not as part of anything"
    )
    assert "shlex" not in _names(tree) | _imported(tree), (
        "this module reaches for `shlex`. Quoting the workspace path into the command is not the "
        "fix - the path is not part of the command at all"
    )


def _interpolations(tree: ast.AST) -> Iterator[ast.expr]:
    """Every expression in `tree` that builds one value out of others."""
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr | ast.TemplateStr):
            yield node
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Mod):
            yield node
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"format", "join"}
        ):
            yield node


def _names(node: ast.AST) -> set[str]:
    """Every bare name reachable inside `node`."""
    return {found.id for found in ast.walk(node) if isinstance(found, ast.Name)}


def _imported(tree: ast.AST) -> set[str]:
    """Every module the source imports, by top-level name. Prose in a docstring is not an import."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module.split(".")[0])
    return found


def _spawn_of(node: ast.AST) -> str | None:
    """The name of the process-starting function `node` calls, if it is a call to one."""
    if not isinstance(node, ast.Call):
        return None
    called = node.func.attr if isinstance(node.func, ast.Attribute) else None
    if called is None and isinstance(node.func, ast.Name):
        called = node.func.id
    return called if called in {"create_subprocess_shell", "create_subprocess_exec"} else None


# --- Gap 6: an expired deadline, and what it leaves behind ---------------------------------------

# Short enough to cost nothing, long enough that a shell has started and printed. The sleep is two
# orders of magnitude longer, so no assertion below can be satisfied by the build simply finishing.
DEADLINE: Final = 0.5
SLEEP: Final = 60.0


@pytest.mark.asyncio
async def test_a_deadline_that_expires_is_a_failed_build_and_never_an_exception(
    tmp_path: Path,
) -> None:
    """The port's answer to an expiry, which the contract suite says it never waits to see.

    *Whatever the implementation reports for it arrives here, the gate reads `passed`, and the work
    is rejected rather than retried.* So there is no `pytest.raises` in this test and that absence
    is half the assertion: a `TimeoutError` escaping would reach §3.4's `integrate` as something
    other than the ordinary second answer to the only question it asks.

    The elapsed time is the other half. A verifier that answered `passed=False` after waiting out
    the whole sleep would satisfy every other assertion here and would hold the merge queue open
    for as long as a hung build cared to run.
    """
    started = time.monotonic()
    outcome = await ShellVerifier(build_timeout=DEADLINE).verify(f"sleep {SLEEP:g}", tmp_path)
    elapsed = time.monotonic() - started

    assert outcome.passed is False, "a build that never finished was reported as having passed"
    assert isinstance(outcome.status, int) and not isinstance(outcome.status, bool)
    assert elapsed < SLEEP / 3, (
        f"a build with a {DEADLINE:g}s deadline took {elapsed:.1f}s to answer, against a command "
        f"that sleeps {SLEEP:g}s. The deadline is what makes a hung build a rejected landing "
        f"rather than a stopped run"
    )


@pytest.mark.asyncio
async def test_an_expired_deadline_stops_the_children_the_shell_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deadline that does not stop the work is not a deadline.

    A build command spawns children - a compiler, a test runner, a daemon - and killing only the
    shell leaves them running: a machine still burning cores on a landing that was rejected
    minutes ago, and a pipe held open by a grandchild that this adapter would still be reading
    from. The adapter starts the shell in a session of its own and signals the whole process group,
    and this is what says so.

    The pid is written to a file rather than printed, so that nothing here depends on when a
    shell's own buffer is flushed - and the file landing in the workspace is one more witness that
    `cwd=` was used. The wait afterwards is a poll rather than a sleep: a signal is delivered
    promptly and reaped when the system gets to it, and asserting on the first microsecond would
    be asserting about a scheduler.

    `monkeypatch.chdir` is here for the reason it is above: an adapter that ignored `workdir` would
    otherwise write its pid file into the repository this test runs out of.
    """
    monkeypatch.chdir(tmp_path)
    pidfile = tmp_path / "agl-child.pid"

    outcome = await ShellVerifier(build_timeout=DEADLINE).verify(
        f"sleep {SLEEP:g} & echo $! > {pidfile.name}; wait", tmp_path
    )

    assert outcome.passed is False, "a build that never finished was reported as having passed"
    assert pidfile.is_file(), "the build never recorded the child it started; nothing to check"
    child = int(pidfile.read_text(encoding="utf-8").strip())
    assert not await _alive_after(child, seconds=5.0), (
        f"the shell was stopped at its deadline and the child it started (pid {child}) is still "
        f"running. The whole process group is signalled precisely so that a stopped build is a "
        f"stopped build rather than an orphaned one"
    )


async def _alive_after(pid: int, seconds: float) -> bool:
    """Is `pid` still running after up to `seconds`? Polls, and answers as soon as it knows."""
    deadline = time.monotonic() + seconds
    while _alive(pid) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return _alive(pid)


def _alive(pid: int) -> bool:
    """Signal 0: the ordinary way to ask whether a process exists without disturbing it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# --- Gaps 3, 5 and 7: the errors, the silence, and the two streams -------------------------------


@pytest.mark.asyncio
async def test_a_build_that_cannot_be_started_at_all_is_upstream_unavailable(
    tmp_path: Path,
) -> None:
    """The one failure that is an error rather than an answer, which the suite cannot provoke.

    Its gap 3 says why: "with a shell in the picture every string starts", so a command naming no
    program comes back as a failed build with a number on it, which is the correct answer and not
    this error. Breaking the runner itself is the only way in, and a working directory that is not
    there is the version of that a test can arrange. `errors.py` names the case in its own words -
    *the build command cannot be run* - and the promise that goes with it is that nothing happened.
    """
    with pytest.raises(UpstreamUnavailable):
        await ShellVerifier().verify(SHELL_PASSING, tmp_path / "no-such-workspace")


@pytest.mark.asyncio
async def test_a_passing_build_that_printed_nothing_is_an_ordinary_pass(tmp_path: Path) -> None:
    """Empty output is legal, and the contract suite can only honour that by never demanding text.

    Its gap 5 is exactly this shape: the reverse - an implementation that refused, or crashed on, a
    command that printed nothing - would not be caught there, because every command in that suite
    is one an implementer supplied. Here the silence is the assertion.
    """
    outcome = await ShellVerifier().verify(SHELL_PASSING, tmp_path)

    assert outcome.passed is True, f"a build that is `{SHELL_PASSING}` failed: {outcome.output!r}"
    assert outcome.output == "", (
        f"a build that printed nothing came back with output {outcome.output!r}. Empty is legal "
        f"and passing builds routinely produce it, so nothing may be invented to fill it"
    )


@pytest.mark.asyncio
async def test_both_streams_arrive_in_the_one_field_the_port_has(tmp_path: Path) -> None:
    """One `output`, because the two streams "are one thing on the screen".

    The suite's gap 7 stops at "a marker the failing command announced comes back", and cannot see
    which stream carried it or whether the other was dropped. This asks for both at once. The
    ordering is not asserted: the streams are merged at the pipe rather than read separately and
    concatenated, so the order is the one the shell wrote and nothing here needs to promise what a
    shell does with its own buffers.
    """
    outcome = await ShellVerifier().verify("echo agl-tidy; echo agl-untidy >&2", tmp_path)

    assert "agl-tidy" in outcome.output, "what the build printed to stdout was dropped"
    assert "agl-untidy" in outcome.output, (
        "what the build printed to stderr was dropped. A local runner has two streams and this "
        "port has one, deliberately - and stderr is where a failing build says why"
    )


# --- The fake's own default, which is the thing no contract suite can be told about --------------


@pytest.mark.asyncio
async def test_the_fake_answers_a_command_nobody_scripted(tmp_path: Path) -> None:
    """An unscripted command passes, because that is what `--dry-run` needs it to do.

    Target #8 is every command running end to end on fakes alone, and nothing on that path scripts
    a build command - so a gate that failed by default would report every landing of a dry run as
    rejected. The opposite is one constructor argument away, for a test that wants a red gate
    without enumerating every command it might be asked about.
    """
    unscripted = "./gradlew build"

    permissive = await FakeVerifier().verify(unscripted, tmp_path)
    strict = await FakeVerifier(unscripted_passes=False).verify(unscripted, tmp_path)

    assert permissive.passed is True, (
        "a command nobody scripted was reported as a failed build, so a dry run of a workflow "
        "that lands anything reports every landing of it as rejected"
    )
    assert strict.passed is False, (
        "`unscripted_passes=False` is how a test asks for a gate that is red until told "
        "otherwise, and it was answered with a pass"
    )
