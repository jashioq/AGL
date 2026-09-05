"""The walking skeleton driven from the argv side: `main(argv)` on `container.fakes()`.

`tests/test_api.py` proved the operations from the library side. This module drives the real entry
point - the real parser, the real dispatch, the real top-level handler - and reads the real exit
code, which is the old defect - nothing could script against AGL - turned into an assertion. The
numbers below are written out by hand for `tests/cli/test_exit_codes.py`'s reason: they are the API
a script branches on, so a change to one should have to be typed twice.

**The bundle is substituted through `main`'s one seam and nothing is monkeypatched.** `compose=` is
a keyword-only parameter whose default is the real composition, exactly as `api.run`'s `points=` is,
so the suite hands in `container.fakes()` and an `Invocation` carrying entry points this module
constructs itself. Nothing here reaches into a module's internals to do it, and nothing here needs a
git repository, an `AGL_HOME` or an installed distribution.

**Two tests are the deliberate exception, and both are about the composition itself.** The project
and the container sit behind a callable on the `Invocation`, so what has to be shown is that
composing no longer resolves either - and a seam that substitutes the composition cannot be used to
assert what the real composition does. Those two set `AGL_HOME` and a working directory with no
repository above it and let `main` compose for real, which is also the only route to the answer for
an unregistered repository: `NotFoundError`, exit 3, naming `agl init`.

**The ordering criterion is pinned twice, and neither pin is the exit code.** It is an acceptance
criterion that `Stop` is caught before `AglError`, and an outcome-only test cannot fail on a swap:
`exit_status` reads 7 out of the one table whichever clause caught it. What differs is the
rendering - a deliberate end goes to stdout with no prefix, a failure to stderr with one - so the
behavioural pin is built on that, and the structural pin walks `main`'s own `except` clauses in
source order.

**The group clause is tested here because here is the only place it is visible.** A `TaskGroup`
whose child raises hands `api` back an `ExceptionGroup`, which is not an `AglError` - and
`agl.testing`'s harness splits that group before a workflow-level test can see it, so the rule is
CLI-only and the divergence it repairs went unnoticed until late. The workflows below that open a
`TaskGroup` are the smallest thing that reaches `main`'s handler holding a real one, and every
assertion about them is made through `main.main`: the real parser, the real dispatch, the real
arms. `tests/cli/test_exit_codes.py` asserts the same rule on constructed groups, where the leaves
are the same objects and nothing has to be run to make one.

**The group tests assert parity rather than numbers wherever there is a parity to assert.** The
whole of the group rule's first clause is that a failure inside a chunk costs what that failure
costs in a sequential workflow, so the test that says so runs both and compares them - a pair of
tests each pinning 6 would go on passing in a world where one of the two had quietly become 70.
"""

import ast
import asyncio
import inspect
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl.cli import main
from agl.config import container, distribution, registry, sources
from agl.ports.errors import (
    ConflictError,
    NotFoundError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.sdk.workflow import Run, Stop, workflow

# `agl init` is the one command that reads `settings` and `cwd`, and no invocation below is one -
# but neither field is optional (`cli/main.py` argues why), so both carry a real value nothing here
# looks at. `/nowhere` is absolute, which is the whole of what `AglHome` insists on, and no file
# under it is ever opened: `read_settings` treats a missing `config.toml` as a file that said
# nothing.
ELSEWHERE: Final = Path("/nowhere")
SETTINGS: Final = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(ELSEWHERE)})

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, so every flag on the line belongs to the generic parser."""

class ReviewNotConverging(Stop):
    """A workflow's own reason to stop, subclassed as a workflow would."""

# What the workflows below raise, so that the same failure can be raised sequentially and inside a
# `TaskGroup` and the two outcomes compared word for word. Each is a sentence an adapter would have
# written where the facts were, because half of what these tests read is the message beside a code.
NO_CONVERGENCE: Final = "two rounds and no convergence"
UNREACHABLE: Final = "the agent backend could not be reached"
UNPARSEABLE: Final = "the agent finished with no reporting-tool payload"
TAKEN: Final = "another run holds the integration lease on agl/auth"
UNTRANSLATED: Final = "a chunk's adapter forgot to translate this"

# What each workflow was handed, at module level because the workflows have to be: `EntryPoint.load`
# imports a module and reads an attribute in it, and sees no local of this module's functions.
handed: Final[list[Run[NoParams]]] = []

@workflow(version="1.1")
async def probe(run: Run[NoParams]) -> None:
    """Returns. The wiring probe, standing in for a workflow package that does nothing."""
    handed.append(run)

@workflow(version="0.1")
async def halting(run: Run[NoParams]) -> None:
    """Ends deliberately, with a reason of its own - exit 7, and not printed as a failure."""
    raise ReviewNotConverging("two rounds and no convergence")

@workflow(version="0.1")
async def exploding(run: Run[NoParams]) -> None:
    """Raises something that is not an `AglError` at all: a translation that did not happen."""
    raise ValueError("an adapter forgot to translate this")

async def _chunk(error: Exception) -> None:
    """One `TaskGroup` child, which raises before it awaits anything. **The absence is the point.**

    A child that awaits first is a child the group can cancel once a sibling has failed, and a
    cancelled task contributes no leaf - so a workflow written that way would hand back a group of
    one however many of its chunks were doomed, and every test below about several leaves would be
    testing a single-leaf group instead. Raising on the first step puts both failures in the ready
    queue before either task's done-callback runs, which is what makes the group hold both.
    """
    raise error

@workflow(version="0.1")
async def failing(run: Run[NoParams]) -> None:
    """`fix`'s shape: one failure, raised sequentially. The half of the parity with no group."""
    raise UpstreamUnavailable(UNREACHABLE)

@workflow(version="0.1")
async def chunked(run: Run[NoParams]) -> None:
    """`split`'s shape: the same failure as `failing`, raised inside one child of a `TaskGroup`."""
    async with asyncio.TaskGroup() as chunks:
        chunks.create_task(_chunk(UpstreamUnavailable(UNREACHABLE)))

@workflow(version="0.1")
async def nested(run: Run[NoParams]) -> None:
    """A chunk that opens a `TaskGroup` of its own, so the same leaf arrives one group deeper."""

    async def deeper() -> None:
        async with asyncio.TaskGroup() as inner:
            inner.create_task(_chunk(UpstreamUnavailable(UNREACHABLE)))

    async with asyncio.TaskGroup() as chunks:
        chunks.create_task(deeper())

@workflow(version="0.1")
async def agreeing(run: Run[NoParams]) -> None:
    """Two chunks, two classes, one code: "agree" about the code rather than about the class."""
    async with asyncio.TaskGroup() as chunks:
        chunks.create_task(_chunk(UpstreamUnavailable(UNREACHABLE)))
        chunks.create_task(_chunk(UpstreamUnexpected(UNPARSEABLE)))

@workflow(version="0.1")
async def disagreeing(run: Run[NoParams]) -> None:
    """Two chunks that say to do two different things - 6 and 4, and no honest way to choose."""
    async with asyncio.TaskGroup() as chunks:
        chunks.create_task(_chunk(UpstreamUnavailable(UNREACHABLE)))
        chunks.create_task(_chunk(ConflictError(TAKEN)))

@workflow(version="0.1")
async def halting_together(run: Run[NoParams]) -> None:
    """`halting`'s deliberate end, raised inside a chunk instead. The same words, on purpose."""
    async with asyncio.TaskGroup() as chunks:
        chunks.create_task(_chunk(ReviewNotConverging(NO_CONVERGENCE)))

@workflow(version="0.1")
async def halting_and_failing(run: Run[NoParams]) -> None:
    """One chunk that ended deliberately and one that broke - 7 and 6, which do not agree."""
    async with asyncio.TaskGroup() as chunks:
        chunks.create_task(_chunk(ReviewNotConverging(NO_CONVERGENCE)))
        chunks.create_task(_chunk(UpstreamUnavailable(UNREACHABLE)))

@workflow(version="0.1")
async def chunked_bug(run: Run[NoParams]) -> None:
    """`exploding` inside a chunk: the leaf nobody translated, and the one a traceback is for."""
    async with asyncio.TaskGroup() as chunks:
        chunks.create_task(_chunk(ValueError(UNTRANSLATED)))

def _point(name: str, attribute: str) -> EntryPoint:
    """A `probe = "agl.workflows.probe:probe"` line, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)

POINTS: Final = (
    _point("probe", "probe"),
    _point("halting", "halting"),
    _point("exploding", "exploding"),
    _point("failing", "failing"),
    _point("chunked", "chunked"),
    _point("nested", "nested"),
    _point("agreeing", "agreeing"),
    _point("disagreeing", "disagreeing"),
    _point("halting_together", "halting_together"),
    _point("halting_and_failing", "halting_and_failing"),
    _point("chunked_bug", "chunked_bug"),
)

def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment: no network, no git, no process, one seeded repository."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})

def _compose(harness: container.FakeServices) -> main.Compose:
    """`main`'s seam, filled in: the fakes bundle, this project, and this module's workflows.

    `registered` is a callable because composition is per-command, and here it is one that answers
    without reading anything - which is the whole of what a `run` invocation needs from a
    registered repository, and exactly what a real one would have had to resolve a project to get.
    """
    return lambda: main.Invocation(
        registered=lambda: (PROJECT, harness.services),
        settings=SETTINGS,
        cwd=ELSEWHERE,
        points=POINTS,
    )

def _main(harness: container.FakeServices, *argv: str) -> int:
    """One `agl` invocation, through the real parser and the real handler."""
    return main.main(argv, compose=_compose(harness))

def _unregistered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine with an AGL home and a working directory that is nobody's project.

    `AGL_HOME` is set in the process environment because that is where `sources.resolve` reads it,
    and it reads it inside `_compose` rather than at import - so setting it before `main` is called
    is what reaches it. An empty directory is a legitimate home: `toml_file.read_settings` treats a
    missing `config.toml` as a file that said nothing, which is what makes settings resolvable on a
    machine where AGL has never run.

    The working directory has no `.git` above it anywhere, which is the first of the two absences
    `config/toml_file.py` raises `NotFoundError` for - the other being a repository no project file
    names. Both carry `agl init`, and this is the cheaper one to arrange.
    """
    home = tmp_path / "home"
    home.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("AGL_HOME", str(home))
    monkeypatch.chdir(elsewhere)

def _clauses() -> list[str]:
    """The exception classes `main.main`'s `try` catches, in the order they are written.

    Read off the source rather than off the function object, because the ordering is a property of
    the text: `except` clauses are tried top to bottom, and the bug in question is a swap of two
    adjacent lines that leaves every type annotation and every signature identical.
    """
    entry = [
        node
        for node in ast.walk(ast.parse(inspect.getsource(main)))
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    assert len(entry) == 1, "agl/cli/main.py no longer defines exactly one `main`"
    caught: list[str] = []
    for block in (node for node in ast.walk(entry[0]) if isinstance(node, ast.Try)):
        for handler in block.handlers:
            assert isinstance(handler.type, ast.Name), f"unreadable clause at {handler.lineno}"
            caught.append(handler.type.id)
    return caught

# --- the four acceptance criteria ----------------------------------------------------------------

def test_a_workflow_that_returns_exits_zero(tmp_path: Path) -> None:
    """`agl run <workflow> -n <label>` end to end through argv - the first criterion.

    The record is asserted too, because "exits 0" would also be true of a `main` that parsed the
    line and did nothing: `run.json` is the one thing a bare run persists, and it is the evidence
    that the dispatch reached `api.run` rather than merely returning.
    """
    handed.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "auth") == 0

    assert len(handed) == 1
    assert asyncio.run(harness.services.store.read_record(SCOPE)) is not None

def test_the_workflow_is_handed_the_bundle_that_was_composed(tmp_path: Path) -> None:
    """`ARCHITECTURE.md`'s "Commands stay dumb", from the far end: one composition, and the ports
    reach the workflow.

    `Git(Path.cwd())` was constructed four times and the whole `RunContext` twice. Identity is what
    makes this a test of that - an equal-looking second bundle would pass anything weaker.
    """
    handed.clear()
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "auth") == 0

    assert handed[0].services is harness.services

def test_the_same_label_twice_exits_four(tmp_path: Path) -> None:
    """The second criterion: exit 4, with the refusal's own message reaching the user on stderr.

    The refusal is `api.run`'s and the command does not re-detect it, so what is asserted here is
    that it survives the trip: raised in the operation, resolved through the one table, rendered by
    the handler, and printed with nothing added but the program's name.
    """
    harness = _fakes(tmp_path)
    assert _main(harness, "run", "probe", "-n", "auth") == 0

    assert _main(harness, "run", "probe", "-n", "auth") == 4

def test_the_existing_label_refusal_is_printed_as_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal's sentence, on stderr, prefixed with the program's name and nothing else."""
    harness = _fakes(tmp_path)
    _main(harness, "run", "probe", "-n", "auth")
    capsys.readouterr()

    _main(harness, "run", "probe", "-n", "auth")

    captured = capsys.readouterr()
    assert captured.err == (
        "agl: run 'auth' already exists - `agl resume auth` or `agl clear auth`.\n"
    )
    assert captured.out == ""

def test_an_unknown_workflow_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The third criterion: `NotFoundError` from the registry, through the handler, as 3.

    The listing in the message is what makes 3 actionable, so it is asserted: the overwhelmingly
    likely cause is a typo and the names the operator meant are three words away.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "nosuch", "-n", "auth") == 3

    captured = capsys.readouterr()
    assert "there is no workflow named 'nosuch'" in captured.err
    assert "probe" in captured.err

def test_a_workflows_own_stop_subclass_exits_seven(tmp_path: Path) -> None:
    """The fourth: 7, not 6 and not 70, for a class that appears in no table.

    `exit_code_for` walks the MRO, so `ReviewNotConverging` resolves to `Stop`'s code without
    anybody editing `ports/errors.py` - and 7 is how a script tells "needs you" from "broken".
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "halting", "-n", "auth") == 7

# --- the ordering hazard, pinned twice and never by the exit code --------------------------------

def test_a_deliberate_stop_is_not_rendered_as_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ordering criterion, made observable. **This is the test that fails on a clause swap.**

    Swapping `except Stop` with `except AglError` leaves the exit code at 7 - the table answers for
    the class, not for the clause - and changes exactly this: the stop would be printed to stderr
    with the `agl:` prefix a failure carries, and stdout would be empty. Both assertions below fail
    in that world, and neither of them mentions a number.
    """
    harness = _fakes(tmp_path)

    code = _main(harness, "run", "halting", "-n", "auth")

    captured = capsys.readouterr()
    assert code == 7
    assert captured.out == "stopped: two rounds and no convergence\n"
    assert captured.err == "", "a deliberate end was reported as a failure"

def test_the_handler_catches_stop_before_agl_error(tmp_path: Path) -> None:
    """The same criterion in the source: the clause order, read off `main`'s own text.

    The behavioural pin above is the one that matters and this is the one that says why it fails.
    `Stop` descends from `AglError`, so a handler written the other way round catches a deliberate
    end in the failure clause and nothing about the types or the signatures changes.

    `BaseException` is asserted absent for `cli/exit_codes.py`'s reason: `exit_status` takes
    `Exception`, so a `BaseException` arm would not typecheck - and it would answer a Ctrl-C with a
    number, where dying of the signal is what lets a shell loop be stopped by the key that stopped
    this process.
    """
    caught = _clauses()

    assert caught.index("Stop") < caught.index("AglError") < caught.index("Exception")
    assert "BaseException" not in caught

# --- the group clause, which nothing below the CLI can observe -----------------------------------

def test_a_failure_in_one_chunk_costs_what_the_same_failure_costs_sequentially(
    tmp_path: Path,
) -> None:
    """The first clause, asserted as the parity it exists to restore rather than as a number.

    "Unwrap a single-exception group and map its leaf." `split` runs its chunks under a
    `TaskGroup`, so the same `UpstreamUnavailable` an adapter raises in `fix` arrives here wrapped
    - and the wrapper once cost 64 points of exit status, which is the difference between a script
    retrying an unreachable backend and a script filing a bug against AGL.

    Both invocations are run and compared, and the number is pinned after them. Two tests each
    asserting 6 would both go on passing on the day one of the two quietly became something else.

    A bundle and a trees root each, here and in the two comparisons below: the label is the same on
    both sides on purpose, and two runs under one label in one tree meet the second one's `_base`
    checkout already on disk - which is a fact about `clear` and has nothing to say about a group.
    """
    concurrently = _main(_fakes(tmp_path / "concurrently"), "run", "chunked", "-n", "auth")
    sequentially = _main(_fakes(tmp_path / "sequentially"), "run", "failing", "-n", "auth")

    assert concurrently == sequentially
    assert sequentially == 6

def test_a_leaf_costs_the_same_however_deeply_its_group_is_nested(tmp_path: Path) -> None:
    """Groups nest because `TaskGroup`s do, and a leaf is the same leaf at any depth.

    `split` opens one and each chunk may open its own, so "a single-exception group" has to be a
    fact about what the run did rather than about how the workflow spelled its concurrency. The two
    workflows below differ in exactly one thing - one wrapper - and a rule that read a group's
    immediate children would answer 70 for the deeper of them.
    """
    deeper = _main(_fakes(tmp_path / "deeper"), "run", "nested", "-n", "auth")
    shallower = _main(_fakes(tmp_path / "shallower"), "run", "chunked", "-n", "auth")

    assert deeper == shallower
    assert shallower == 6

def test_chunks_that_fail_the_same_way_exit_that_way_whatever_their_classes(
    tmp_path: Path,
) -> None:
    """"For several leaves that agree, use that code" - and agreement is about the code.

    `UpstreamUnavailable` and `UpstreamUnexpected` are two classes and one published answer:
    `ports/errors.py` leaves both out of the table so that both inherit `UpstreamError`'s 6, "so a
    caller that does not care which it was catches this and a script still sees one code". A run
    that hit one of each therefore failed one way twice, and 70 would be this handler inventing a
    distinction the hierarchy exists to remove.
    """
    assert _main(_fakes(tmp_path), "run", "agreeing", "-n", "auth") == 6

def test_chunks_that_fail_differently_exit_seventy_naming_every_one_of_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """"For leaves that disagree, 70, naming all of them" - the naming being the half asserted here.

    The number is argued: a run that failed several different ways is genuinely not attributable to
    one code, and `InternalError` is the honest answer rather than a guess. What that argument
    costs the operator is a 70 whose usual meaning is "file a bug" for a run in which nothing was
    AGL's fault, so the naming is not decoration - it is the only thing that tells them which
    failures produced the number and that neither of them was ours.

    Each leaf is asserted beside the status it resolves to on its own, because that is what makes
    the sentence actionable: 6 says retry the backend and 4 says the label or the lease is taken,
    and an operator shown two class names and no codes has to go and read the table to act.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "disagreeing", "-n", "auth") == 70

    captured = capsys.readouterr()
    assert f"6  UpstreamUnavailable: {UNREACHABLE}" in captured.err
    assert f"4  ConflictError: {TAKEN}" in captured.err
    assert "do not resolve to one exit status" in captured.err
    assert captured.out == ""

def test_a_deliberate_stop_in_a_chunk_reads_exactly_like_one_raised_on_its_own(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The group rule's other half, and the second half of it is the rendering.

    A `Stop` inside a `TaskGroup` used to exit 70, and it was also printed as a traceback under a
    sentence saying AGL had a bug - so a workflow that ended deliberately in a chunk told the
    operator both of the two things `Stop` exists to say it is not. The exit code is
    `cli/exit_codes.py`'s to answer and the message is `main`'s, and both are asserted here against
    the identical stop raised sequentially, which is the only comparison that fails in a world
    where one of the two arms drifts.
    """
    together = _main(_fakes(tmp_path / "together"), "run", "halting_together", "-n", "auth")
    concurrent = capsys.readouterr()
    alone = _main(_fakes(tmp_path / "alone"), "run", "halting", "-n", "auth")
    sequential = capsys.readouterr()

    assert together == alone
    assert alone == 7
    assert concurrent.out == sequential.out == f"stopped: {NO_CONVERGENCE}\n"
    assert concurrent.err == sequential.err == ""

def test_a_chunk_that_stopped_beside_a_chunk_that_broke_is_named_with_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """"All of them" includes the deliberate end, because it is half of why the run exits 70.

    A run in which one chunk finished the work it had and another could not reach its backend is
    exactly the run that cannot be attributed to one code: 7 says "needs you" and 6 says "broken",
    and there is no answer that is both. What the operator has to be able to see is that pair, so
    the stop is named on stderr beside the failure - and it is still reported as a stop on stdout,
    because nothing about the disagreement makes it one.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "halting_and_failing", "-n", "auth") == 70

    captured = capsys.readouterr()
    assert captured.out == f"stopped: {NO_CONVERGENCE}\n"
    assert f"7  ReviewNotConverging: {NO_CONVERGENCE}" in captured.err
    assert f"6  UpstreamUnavailable: {UNREACHABLE}" in captured.err
    assert "Traceback" not in captured.err, "a translated refusal was rendered as a bug"

def test_an_untranslated_exception_in_a_chunk_keeps_the_traceback_it_would_have_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same defect inside a group: the fix is not to stop catching but to stop hiding.

    A leaf nobody translated is our bug wherever it was raised, so it resolves to 70 and it keeps
    the one part of a bug worth having. The traceback is printed for that leaf and for no other -
    a well-worded refusal beside it is the message, and a stack under a sentence a person can act on
    is how `_cmd_run` used to make every failure look the same.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "chunked_bug", "-n", "auth") == 70

    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert UNTRANSLATED in captured.err
    assert "AGL's own bug" in captured.err
    assert captured.out == ""

# --- refusals a user can provoke, and the one that is ours ---------------------------------------

def test_an_unknown_flag_exits_two_rather_than_leaving_through_system_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`argparse.ArgumentParser.error()` calls `sys.exit(2)`, which is a second exit-code table.

    The number it writes is even the right one, and it is still wrong: it bypasses
    `ports/errors.py`'s table and the handler with it, so nothing above could have rendered it,
    logged it or chosen otherwise. `RefusingParser` raises `InputError` instead, and this asserts
    the whole route - a `SystemExit` escaping `main` would fail this test by never returning.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "auth", "--nosuch") == 2

    assert "--nosuch" in capsys.readouterr().err

def test_a_missing_label_exits_two_rather_than_leaving_through_system_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`-n` is required, and a required argument argparse never saw is the other `error()` route.

    `exit_on_error=False` would not have covered it - that converts only what is raised while
    consuming a value, and a missing required argument still goes through `error()`.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe") == 2

    assert "-n/--name" in capsys.readouterr().err

def test_a_label_the_filesystem_would_not_take_exits_two(tmp_path: Path) -> None:
    """`RunLabel` validates on the way in, and its `InputError` is the same 2.

    The label becomes a directory and the branch `agl/<label>`, so `my/label` is a path where a
    name belongs. Nothing downstream re-checks it, which is why it is checked before the run.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "my/label") == 2

def test_no_subcommand_at_all_exits_two(tmp_path: Path) -> None:
    """A bare `agl` is a usage error, not a default command: `agl run` is not what silence means."""
    harness = _fakes(tmp_path)

    assert _main(harness) == 2

def test_an_unexpected_exception_exits_seventy_with_its_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The old defect answered: `_cmd_run` ended in a bare `except Exception` rendering any bug
    as `error: <str>`, so the traceback - the only part of a bug worth having - was thrown away.

    Anything that is not an `AglError` reaching the top is a translation an adapter did not perform,
    which is our bug, which is 70 (`cli/exit_codes.py` argues both halves). The traceback is printed
    because that is what "file a bug" needs, and the sentence after it is what tells the reader the
    bug is not theirs.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "exploding", "-n", "auth") == 70

    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert "an adapter forgot to translate this" in captured.err
    assert "AGL's own bug" in captured.err
    assert captured.out == ""

def test_help_still_exits_zero_through_system_exit(tmp_path: Path) -> None:
    """`-h` is `argparse`'s one sanctioned exit and `RefusingParser` leaves `exit()` untouched.

    `SystemExit` is a `BaseException`, so it passes the handler by construction rather than by an
    arm written to let it - the same structural reason `KeyboardInterrupt` is unanswered.
    """
    harness = _fakes(tmp_path)

    for argv in (("-h",), ("run", "-h")):
        with pytest.raises(SystemExit) as caught:
            main.main(argv, compose=_compose(harness))
        assert caught.value.code == 0

def test_the_version_flag_prints_the_installed_version_and_exits_zero_like_help(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--version` is `-h`'s sibling and leaves the same way: `argparse` prints it during the scan
    and exits, before the required subcommand is looked for.

    So `agl --version` takes no command after it, which is the whole reason this is a parser action
    rather than a clause in the dispatch - and it is asserted here because a `store_true` flag
    reading the same way on the command line would exit 2 asking for a subcommand instead.

    The line is compared against `config/distribution.py`'s reader rather than against a version
    typed here: `pyproject.toml`'s number is spent permanently at a release, and a copy of it in
    this file would be a second place to change on the day it moves.
    """
    harness = _fakes(tmp_path)

    with pytest.raises(SystemExit) as caught:
        main.main(("--version",), compose=_compose(harness))

    assert caught.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == f"agl {distribution.installed_version()}\n"
    assert captured.err == ""

def test_a_version_flag_after_a_command_is_the_workflows_and_not_agls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A root flag is only a root flag before the subcommand, and this is what that buys.

    `agl run <workflow>` hands everything it does not understand to the workflow's own parser, and
    a flag declared on the root parser does not change which arguments those are: `--version` typed
    after a command is the workflow's to accept or refuse, exactly as it was before this flag
    existed. `probe` declares none, so it refuses - and the refusal, rather than a version, is what
    says the flag was never taken off the line.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "run", "probe", "-n", "auth", "--version") == 2

    assert "--version" in capsys.readouterr().err

# --- the composition, and the number this module may not write -----------------------------------

def test_the_composition_happens_once_and_only_after_argv_is_understood(tmp_path: Path) -> None:
    """`ARCHITECTURE.md`'s "Commands stay dumb", measured: one resolution per invocation, and none
    for a wrong line.

    Four `Git(Path.cwd())` and two `RunContext`s is what this counts against. The second half is the
    ordering `main` is written in: a person who typed the command wrong is told what they typed
    wrong, wherever they typed it, rather than being told they are not inside a registered
    repository - and `agl -h` reads no file and builds no adapter.
    """
    harness = _fakes(tmp_path)
    composed: list[main.Invocation] = []

    def counting() -> main.Invocation:
        composed.append(_compose(harness)())
        return composed[-1]

    assert main.main(("run", "probe", "-n", "auth"), compose=counting) == 0
    assert len(composed) == 1

    composed.clear()
    assert main.main(("run", "probe"), compose=counting) == 2
    assert composed == [], "argv was refused and the world was resolved anyway"

def test_composing_resolves_settings_and_not_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole of that change, measured on the composition that would have failed it.

    `_compose` used to resolve the project and build the container before the dispatch chose a
    command, so in the directory below it raised - and `agl init`, the command whose job is to make
    that directory a project, could not have been reached from here however it was written. Now
    composing asks the environment and stops, and the refusal arrives only when something calls the
    thunk that would resolve a repository.

    The private `_compose` is called on purpose: `compose=` substitutes the thing under test, and
    the two halves being asserted - that composing returns, and that calling *then* raises - are
    only distinguishable on the real one.
    """
    _unregistered(tmp_path, monkeypatch)

    invocation = main._compose()

    assert isinstance(invocation, main.Invocation)
    with pytest.raises(NotFoundError) as caught:
        invocation.registered()
    assert "agl init" in str(caught.value)

def test_an_unregistered_repository_exits_three_naming_agl_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A command invoked in an unregistered repository gets `NotFoundError` -> exit 3, naming
    `agl init`, which is run once per project and never again.

    The same fact as the test above, through the real entry point with no seam filled in at all -
    the real parser, the real `_compose`, the real dispatch, the real handler. What it adds is the
    route out: the refusal is raised inside a command, which is inside `main`'s `try`, so it leaves
    as a number and a sentence rather than as a traceback, and the sentence is the one
    `config/toml_file.py` wrote where the facts were rather than one re-worded on the way past.
    """
    _unregistered(tmp_path, monkeypatch)

    assert main.main(("run", "probe", "-n", "auth")) == 3

    captured = capsys.readouterr()
    assert "agl init" in captured.err
    assert captured.out == ""

def test_main_writes_no_exit_code_of_its_own(tmp_path: Path) -> None:
    """"No integer literal appears in this file", made mechanical rather than promised.

    Every arm of the handler resolves through `exit_status`, and success is the command's to return
    because success is not a row in `ports/errors.py`'s table. A number typed here would be the
    second table starting, which is the same claim `tests/cli/test_exit_codes.py` scans for one
    module along - including the `1` of a `sys.argv[1:]` that is not written because `argparse`
    already defaults to it.
    """
    written = [
        node.value
        for node in ast.walk(ast.parse(inspect.getsource(main)))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ]

    assert not written, (
        f"agl/cli/main.py writes {written}. Exit codes are read out of `ports/errors.py`'s one "
        f"table through `cli/exit_codes.exit_status`, and nothing else here is a number"
    )

def test_the_working_directory_is_read_exactly_once_in_the_whole_of_agl() -> None:
    """`ARCHITECTURE.md`'s "Commands stay dumb", counted: `Git(Path.cwd())` was constructed **four
    times**, once per command.

    This stopped being free when `init` arrived. `Path.cwd()` used to sit inside the thunk that
    resolves a project, which was the whole of what needed it; `agl init` is the second reader - it
    finds its own git root - so the honest choices were a second read in the `init` path or one read
    hoisted here and carried on the `Invocation`. Four started as two, so the count is the test.

    **A source scan, for `test_main_writes_no_exit_code_of_its_own`'s reason**: "it works" is true
    of a codebase with the expression in five places, and the claim is about where the expression
    is. `ast` rather than `grep` so that the sentences *about* `Path.cwd()` - and there are several,
    including in `api.py` and `sdk/roles.py` - are not counted as reads of it. `os.getcwd` is
    counted with it, because a second spelling of one process-global is the way a count like this
    quietly stops meaning anything.
    """
    root = Path(inspect.getfile(main)).parents[1]
    reads = [
        (module.relative_to(root), node.lineno)
        for module in sorted(root.rglob("*.py"))
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and (node.value.id, node.attr) in {("Path", "cwd"), ("os", "getcwd")}
    ]

    assert [str(where) for where, _ in reads] == ["cli/main.py"], (
        f"AGL asks the process where it is standing in {reads}. It is read once, by `_compose`, "
        f"and carried on the `Invocation`: `_registered` receives it and so does `api.init`, which "
        f"takes a `cwd` parameter precisely so that nothing below `cli/` has to ask"
    )

def test_the_seam_is_a_parameter_and_the_real_composition_is_its_default() -> None:
    """`compose=None` means the real one, spelled the way `api.run` spells `points=None`.

    A seam with a signature rather than a module attribute a test monkeypatches: `api.py` argues
    the choice, and this asserts that `main` can still be called the way `pyproject.toml`'s console
    script calls it - `main()` with nothing at all.
    """
    signature = inspect.signature(main.main)

    assert signature.parameters["argv"].default is None
    assert signature.parameters["compose"].default is None
    assert signature.parameters["compose"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.return_annotation is int

def test_argv_defaults_to_the_command_line_without_this_module_saying_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`argv=None` reaches `argparse`, whose own default is `sys.argv[1:]` - stated in one place.

    Driven through `sys.argv` because that is the only thing the console script sets: `agl` calls
    `main()` with no arguments, and everything this suite asserts about argv would be about a path
    the installed program never takes if that default were spelled differently here.
    """
    harness = _fakes(tmp_path)
    handed.clear()
    monkeypatch.setattr("sys.argv", ["agl", "run", "probe", "-n", "auth"])

    assert main.main(compose=_compose(harness)) == 0

    assert len(handed) == 1
    assert capsys.readouterr().out == "run 'auth' finished\n"
