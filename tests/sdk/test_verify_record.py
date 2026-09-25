"""What recording `run.verify` promises: a resume hands back the outcome, and runs nothing.

A verify's outcome is filed with the steps of the `Run` that ran it, under the step name
`run.verify`. Its point is its position among the verifies that `Run` records in one walk, and the
entry at a point holds the command, the head the `Run` had recorded and the outcome. A resume that
reaches the same point with the same command at the same recorded head gets the recorded outcome
back without the command running. Anywhere else the command runs, and its command, head and
outcome overwrite the entry at that point, so no entry holds the old outcome any more.

**The head is the one the `Run` has recorded, not the checkout's.** A replayed step moves the
checkout only forward to its recorded head, never back, so on a resume the checkout can stand past
the head the steps replayed so far. A verify keyed on the checkout would miss in exactly the case
this exists for, which is the one the real-git tests at the bottom walk: `implement_and_check`,
interrupted after its fix commit and resumed.

**A verify made while a step or a landing holds its worktree is not recorded.** A step's tool
handler that verifies is part of that step's worker, which a replay skips, so an entry for it would
only take a position that the next verify then finds.
"""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Final
import pytest
from agl import testing
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.shell.fake import FakeVerifier
from agl.config import container
from agl.ports.errors import InputError, InternalError, exit_code_for
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.tree_layout import TreesRoot
from agl.ports.verifier import Verifier
from agl.ports.workspace import Workspace
from agl.sdk import (
    Claude,
    Restriction,
    Role,
    Run,
    VerifierOutcome,
    arg,
    describe,
    reporting_tool,
    role,
    workflow,
)
from agl.sdk._engine.journal import Entry, Fingerprints, Journal, base_of, read_entry, write_entry
from agl.sdk._engine.prompts import composed
from agl.testing import AgentTask, Call, Reply

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)
CHILD: Final = "T-01"

BUILD: Final = "make test"
LINT: Final = "make lint"

# The step name a verify's entry is filed under, spelled out rather than imported from the journal,
# so that the suite is not checking the module against its own constant.
VERIFY: Final = "run.verify"

RED: Final = VerifierOutcome(passed=False, status=3, output="2 tests failed\n")
GREEN: Final = VerifierOutcome(passed=True, status=0, output="all passed\n")

# --- the journal, one walk at a time ------------------------------------------------------------

class _Build:
    """A verify's worker: counts its runs, and answers `answers` in turn, keeping the last."""

    def __init__(self, *answers: VerifierOutcome) -> None:
        self.runs = 0
        self._answers = answers

    async def __call__(self) -> VerifierOutcome:
        answer = self._answers[min(self.runs, len(self._answers) - 1)]
        self.runs += 1
        return answer

async def _opened(root: Path) -> tuple[container.FakeServices, Workspace, str]:
    """A bundle, the run's own checkout provisioned from `main`, and the commit it starts at."""
    fakes = container.fakes(TreesRoot(root / "trees"), files={"README.md": b"seed\n"})
    workspace = await fakes.services.workspaces.open(LABEL, None, "main")
    return fakes, workspace, await workspace.head()

def _walk(
    fakes: container.FakeServices,
    workspace: Workspace,
    head: str,
    fingerprints: Fingerprints | None = None,
) -> Journal:
    """One walk's journal at `head`: the same ledger and a fresh ordinal count, as a resume has."""
    return Journal(
        fakes.services.store,
        SCOPE,
        workspace,
        fakes.services.history,
        fakes.services.clock,
        Fingerprints() if fingerprints is None else fingerprints,
        head,
    )

def _address(point: int = 0) -> str:
    """Where the verify at `point` is filed, from the arithmetic spelled out: the sha256 of
    `run.verify:<point>`, whatever the command and the head."""
    return hashlib.sha256(f"{VERIFY}:{point}".encode()).hexdigest()

def _value(command: str, outcome: VerifierOutcome) -> JsonValue:
    """What the entry at a point holds beside its head: the command and the outcome's fields."""
    return {
        "command": command,
        "passed": outcome.passed,
        "status": outcome.status,
        "output": outcome.output,
    }

def _fed(outcome: VerifierOutcome, head: str) -> str:
    """The base of a step that takes `outcome` as its one input, as `sdk/_engine/steps.py` builds
    one: the input keyed by its type's name, and in the prompt as well as beside it."""
    inputs = {"VerifierOutcome": outcome}
    return base_of(
        instructions="review the work, given {{VerifierOutcome}}",
        model=Claude.SONNET,
        restrictions=frozenset(),
        tools=(),
        inputs=inputs,
        prompt=composed("review the work, given {{VerifierOutcome}}", inputs),
        head=head,
    )

async def _never() -> JsonValue:
    """A step's worker that a replay must not call."""
    raise AssertionError("a step the ledger holds ran its worker again")

async def _checking(journal: Journal, worker: Callable[[], Awaitable[JsonValue]]) -> None:
    """One read-only step, `check`, with `worker` as its worker."""
    await journal.step(
        StepName("check"),
        instructions="check the build",
        model=Claude.SONNET,
        restrictions=frozenset(),
        tools=(),
        inputs={},
        prompt="check the build",
        worker=worker,
    )

@pytest.mark.asyncio
async def test_a_verify_at_the_same_point_command_and_head_replays_without_running(
    tmp_path: Path,
) -> None:
    fakes, workspace, head = await _opened(tmp_path)
    first, resumed = _Build(RED), _Build(GREEN)

    assert await _walk(fakes, workspace, head).verify(BUILD, first) == RED
    assert await _walk(fakes, workspace, head).verify(BUILD, resumed) == RED

    assert (first.runs, resumed.runs) == (1, 0)

@pytest.mark.asyncio
async def test_a_verify_at_another_head_runs_and_the_next_walk_replays_that_outcome(
    tmp_path: Path,
) -> None:
    fakes, workspace, head = await _opened(tmp_path)
    await _walk(fakes, workspace, head).verify(BUILD, _Build(RED))
    (workspace.path / "fix.txt").write_bytes(b"the fix\n")
    fixed = await workspace.commit_all("fix what the review found")
    moved, again = _Build(GREEN), _Build(RED)

    assert await _walk(fakes, workspace, fixed).verify(BUILD, moved) == GREEN
    assert await _walk(fakes, workspace, fixed).verify(BUILD, again) == GREEN

    assert (moved.runs, again.runs) == (1, 0)

@pytest.mark.asyncio
async def test_a_verify_of_another_command_at_the_same_point_runs_and_replaces_the_outcome(
    tmp_path: Path,
) -> None:
    fakes, workspace, head = await _opened(tmp_path)
    await _walk(fakes, workspace, head).verify(BUILD, _Build(RED))
    lint = _Build(GREEN)

    assert await _walk(fakes, workspace, head).verify(LINT, lint) == GREEN

    entry = await read_entry(fakes.services.store, SCOPE, StepName(VERIFY), _address())
    assert entry is not None
    assert (entry.value, entry.head) == (_value(LINT, GREEN), head)
    assert lint.runs == 1

@pytest.mark.asyncio
async def test_a_command_changed_and_changed_back_runs_each_time_and_never_returns_the_first(
    tmp_path: Path,
) -> None:
    """Changed back, the command finds the other command's outcome at its point, so it runs: the
    first outcome was replaced, and nothing hands it back."""
    fakes, workspace, head = await _opened(tmp_path)
    build = _Build(RED, GREEN)
    await _walk(fakes, workspace, head).verify(BUILD, build)
    await _walk(fakes, workspace, head).verify(LINT, _Build(GREEN))

    assert await _walk(fakes, workspace, head).verify(BUILD, build) == GREEN

    assert build.runs == 2

@pytest.mark.asyncio
async def test_a_verify_at_a_changed_head_replaces_the_entry_at_the_same_point(
    tmp_path: Path,
) -> None:
    """The entry at the point now holds the new head, so a walk back at the old head runs too."""
    fakes, workspace, head = await _opened(tmp_path)
    await _walk(fakes, workspace, head).verify(BUILD, _Build(RED))
    (workspace.path / "fix.txt").write_bytes(b"the fix\n")
    fixed = await workspace.commit_all("fix what the review found")
    await _walk(fakes, workspace, fixed).verify(BUILD, _Build(GREEN))
    entry = await read_entry(fakes.services.store, SCOPE, StepName(VERIFY), _address())
    back = _Build(RED)

    assert await _walk(fakes, workspace, head).verify(BUILD, back) == RED

    assert entry is not None
    assert (entry.value, entry.head) == (_value(BUILD, GREEN), fixed)
    assert back.runs == 1

@pytest.mark.asyncio
async def test_two_verifies_of_one_command_at_one_head_replay_in_the_order_they_ran(
    tmp_path: Path,
) -> None:
    """The position is the point: the second verify is the second, on a resume too."""
    fakes, workspace, head = await _opened(tmp_path)
    flaky, resumed = _Build(RED, GREEN), _Build(RED)
    first = _walk(fakes, workspace, head)
    ran = [await first.verify(BUILD, flaky), await first.verify(BUILD, flaky)]

    again = _walk(fakes, workspace, head)
    replayed = [await again.verify(BUILD, resumed), await again.verify(BUILD, resumed)]

    assert ran == replayed == [RED, GREEN]
    assert resumed.runs == 0

@pytest.mark.asyncio
async def test_a_verify_inside_a_steps_worker_takes_no_position_the_next_verify_would_find(
    tmp_path: Path,
) -> None:
    """The step replays without its worker, so the verify inside it is never made again. Had it
    taken point 0, the verify after the step would find that outcome on the resume, with the same
    command at the same head, and hand it back in place of its own."""
    fakes, workspace, head = await _opened(tmp_path)
    first = _walk(fakes, workspace, head)
    inside, after, resumed = _Build(RED), _Build(GREEN), _Build(RED)

    async def verifies() -> JsonValue:
        await first.verify(BUILD, inside)
        return None

    await _checking(first, verifies)
    assert await first.verify(BUILD, after) == GREEN

    again = _walk(fakes, workspace, head)
    await _checking(again, _never)
    assert await again.verify(BUILD, resumed) == GREEN

    assert (inside.runs, after.runs, resumed.runs) == (1, 1, 0)

@pytest.mark.asyncio
async def test_a_replayed_verify_is_not_counted_among_the_steps_a_resume_replayed(
    tmp_path: Path,
) -> None:
    """`Replayed <n> steps from the record` counts steps, and a verify is not one."""
    fakes, workspace, head = await _opened(tmp_path)
    await _walk(fakes, workspace, head).verify(BUILD, _Build(RED))
    fingerprints = Fingerprints()

    assert await _walk(fakes, workspace, head, fingerprints).verify(BUILD, _Build(GREEN)) == RED

    assert fingerprints.replays == 0

@pytest.mark.asyncio
async def test_a_replayed_outcome_is_the_recorded_dataclass_and_fingerprints_alike_as_an_input(
    tmp_path: Path,
) -> None:
    """A step that takes the outcome is addressed by its type's qualified name and each field, so
    the one read back has to be a `VerifierOutcome` holding a `bool`, an `int` and a `str` again."""
    fakes, workspace, head = await _opened(tmp_path)
    await _walk(fakes, workspace, head).verify(BUILD, _Build(RED))

    replayed = await _walk(fakes, workspace, head).verify(BUILD, _Build(GREEN))

    assert type(replayed) is VerifierOutcome
    assert [type(replayed.passed), type(replayed.status), type(replayed.output)] == [bool, int, str]
    assert _fed(replayed, head) == _fed(RED, head)

@pytest.mark.asyncio
async def test_a_verify_is_filed_under_run_verify_at_its_position_with_command_and_head(
    tmp_path: Path,
) -> None:
    fakes, workspace, head = await _opened(tmp_path)
    first = _walk(fakes, workspace, head)

    await first.verify(BUILD, _Build(RED))
    await first.verify(LINT, _Build(GREEN))

    entries = [
        await read_entry(fakes.services.store, SCOPE, StepName(VERIFY), _address(point))
        for point in (0, 1)
    ]
    assert [(entry.value, entry.head) for entry in entries if entry is not None] == [
        (
            {"command": BUILD, "passed": False, "status": 3, "output": "2 tests failed\n"},
            head,
        ),
        ({"command": LINT, "passed": True, "status": 0, "output": "all passed\n"}, head),
    ]

@pytest.mark.parametrize(
    "value",
    [
        {"command": BUILD, "passed": False, "status": True, "output": ""},
        {"command": None, "passed": False, "status": 3, "output": ""},
        {"command": BUILD, "passed": False, "status": 3},
        {"command": BUILD, "passed": False, "status": 3, "output": "", "head": "4a91c07f"},
        ["2 tests failed\n"],
    ],
    ids=["a-bool-status", "no-command", "no-output", "an-unknown-key", "not-an-object"],
)
@pytest.mark.asyncio
async def test_a_recorded_outcome_of_any_other_shape_is_refused_and_the_command_not_run(
    tmp_path: Path, value: JsonValue
) -> None:
    fakes, workspace, head = await _opened(tmp_path)
    digest = _address()
    await write_entry(
        fakes.services.store,
        SCOPE,
        StepName(VERIFY),
        digest,
        Entry(fingerprint=digest, value=value, head=head, at=fakes.clock.now()),
    )
    build = _Build(GREEN)

    with pytest.raises(InternalError) as refused:
        await _walk(fakes, workspace, head).verify(BUILD, build)

    assert str(refused.value) == (
        'Run "auth" holds a recorded `run.verify` outcome that AGL did not write.'
    )
    assert build.runs == 0

@pytest.mark.asyncio
async def test_a_command_holding_a_lone_surrogate_is_refused_before_it_runs(
    tmp_path: Path,
) -> None:
    """Spelled `chr(0xD800)` in here, for `tests/test_no_literal_surrogates.py`'s reason."""
    fakes, workspace, head = await _opened(tmp_path)
    build = _Build(GREEN)

    with pytest.raises(InputError) as refused:
        await _walk(fakes, workspace, head).verify("make " + chr(0xD800), build)

    assert exit_code_for(refused.value) == exit_code_for(InputError)
    assert build.runs == 0

# --- a run, interrupted and resumed, on the fakes ------------------------------------------------

class _Counting(FakeVerifier):
    """The fakes' verifier, answering as it was scripted and writing down every command."""

    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        self.commands.append(command)
        return await super().verify(command, workdir)

class _AsBefore(Store):
    """The ledger as AGL wrote it before a verify was recorded: every entry but a verify's."""

    def __init__(self, store: Store) -> None:
        self._store = store

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        return await self._store.read_record(scope)

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        await self._store.write_record(scope, value)

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        return await self._store.read_entry(scope, step, digest)

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        if str(step) != VERIFY:
            await self._store.write_entry(scope, step, digest, value)

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        return await self._store.namespaces(scope)

    async def remove(self, scope: RunScope) -> None:
        await self._store.remove(scope)

# What each workflow was handed back, kept at module level because `EntryPoint.load` reads a module
# attribute and cannot see a local.
verdicts: Final[list[VerifierOutcome]] = []

@role(model=Claude.SONNET)
def implement() -> Role[None]:
    """A role whose agent writes one file and reports nothing."""
    return Role(name="implement", instructions="make the change asked for")

def _writes(task: AgentTask) -> Reply:
    """An agent that leaves a file in its checkout, so a step's `commit=` has something to keep."""
    (task.workspace / "feature.txt").write_bytes(b"the change\n")
    return Reply(says="done")

@workflow
async def verifies_the_build(run: Run) -> None:
    """Verifies the project's build command once, from the run itself."""
    verdicts.append(await run.verify(run.config["build"]))

@workflow
async def implements_then_verifies(run: Run) -> None:
    """Commits one step's work, then verifies it."""
    await run.step(implement(), commit="do what was asked")
    verdicts.append(await run.verify(BUILD))

@workflow
async def verifies_from_a_child_and_the_root(run: Run) -> None:
    """Verifies one command at one commit twice: from a child, then from the run itself."""
    verdicts.append(await run.worktree(CHILD).verify(BUILD))
    verdicts.append(await run.verify(BUILD))

@workflow
async def lands_a_child_then_verifies(run: Run) -> None:
    """Lands a child's work through the build gate, then verifies another command at the root."""
    child = run.worktree(CHILD)
    await child.step(implement(), commit="the child's work")
    await child.integrate()
    verdicts.append(await run.verify(LINT))

def _fakes(root: Path, gate: _Counting) -> container.FakeServices:
    """The fakes over `gate`, with an agent that writes a file and `build` declared."""
    verdicts.clear()
    fakes = container.fakes(TreesRoot(root / "trees"), config={"build": BUILD}, agent=_writes)
    return fakes.with_verifier(gate)

def _declaring(fakes: container.FakeServices, build: str) -> container.FakeServices:
    """The same fakes, one ledger and one repository, with the project's `build` changed."""
    declared = MappingProxyType({"build": build})
    return replace(fakes, services=replace(fakes.services, config=declared))

@pytest.mark.asyncio
async def test_a_resumed_run_hands_back_the_recorded_verdict_and_its_command_does_not_run(
    tmp_path: Path,
) -> None:
    gate = _Counting()
    gate.answers(BUILD, passed=False, status=3, output="2 tests failed\n")
    fakes = _fakes(tmp_path, gate)

    await testing.over(fakes).run(verifies_the_build, interrupt_after=1)
    await testing.over(fakes).resume(verifies_the_build)

    assert gate.commands == [BUILD]
    assert verdicts == [RED]

@pytest.mark.asyncio
async def test_a_resume_whose_build_command_changed_runs_it_and_the_next_resume_replays_it(
    tmp_path: Path,
) -> None:
    gate = _Counting()
    gate.answers(BUILD, passed=False, status=3, output="2 tests failed\n")
    gate.answers("make check", passed=True, status=0, output="all passed\n")
    fakes = _fakes(tmp_path, gate)
    changed = _declaring(fakes, "make check")

    await testing.over(fakes).run(verifies_the_build, interrupt_after=1)
    await testing.over(changed).resume(verifies_the_build, interrupt_after=1)
    await testing.over(changed).resume(verifies_the_build)

    assert gate.commands == [BUILD, "make check"]
    assert verdicts == [GREEN]

@pytest.mark.asyncio
async def test_a_record_holding_no_verify_outcome_resumes_and_the_verify_runs_its_command(
    tmp_path: Path,
) -> None:
    """A record from before verifies were recorded: the step replays and the verify runs, as it
    always did, and its outcome is recorded now."""
    gate = _Counting()
    gate.answers(BUILD, passed=False, status=3, output="2 tests failed\n")
    fakes = _fakes(tmp_path, gate)

    await testing.over(fakes.with_store(_AsBefore(fakes.store))).run(
        implements_then_verifies, interrupt_after=2
    )
    resumed = testing.over(fakes)
    await resumed.resume(implements_then_verifies)

    assert gate.commands == [BUILD, BUILD]
    assert [(entry.step, entry.value) for entry in resumed.recorded] == [
        (VERIFY, _value(BUILD, RED))
    ]
    assert verdicts == [RED]

@pytest.mark.asyncio
async def test_one_command_verified_in_a_child_and_the_root_is_recorded_under_each_run(
    tmp_path: Path,
) -> None:
    """One command at one commit, and two `Run`s: two points, two entries, two outcomes kept."""
    gate = _Counting()
    gate.answers(BUILD, passed=False, status=3, output="2 tests failed\n")
    fakes = _fakes(tmp_path, gate)
    first = testing.over(fakes)

    await first.run(verifies_from_a_child_and_the_root, interrupt_after=2)
    ran = list(gate.commands)
    verdicts.clear()
    await testing.over(fakes).resume(verifies_from_a_child_and_the_root)

    assert [(entry.step, entry.namespace) for entry in first.recorded] == [
        (VERIFY, CHILD),
        (VERIFY, None),
    ]
    assert ran == gate.commands == [BUILD, BUILD]
    assert verdicts == [RED, RED]

@pytest.mark.asyncio
async def test_a_landings_build_gate_is_never_recorded_and_runs_again_on_a_resume(
    tmp_path: Path,
) -> None:
    gate = _Counting()
    gate.answers(BUILD, passed=True, status=0, output="the gate passed\n")
    gate.answers(LINT, passed=True, status=0, output="lint passed\n")
    fakes = _fakes(tmp_path, gate)
    first, resumed = testing.over(fakes), testing.over(fakes)

    await first.run(lands_a_child_then_verifies, interrupt_after=2)
    await resumed.resume(lands_a_child_then_verifies)

    assert gate.commands.count(BUILD) == 2
    assert [(entry.step, entry.namespace) for entry in first.recorded] == [
        ("implement", CHILD),
        (VERIFY, None),
    ]
    assert [entry.value for entry in (*first.recorded, *resumed.recorded)] == [
        None,
        _value(LINT, VerifierOutcome(passed=True, status=0, output="lint passed\n")),
    ]

# --- implement_and_check, over real git ---------------------------------------------------------

REQUEST: Final = "add a --verbose flag"
FINDING: Final = "the flag is parsed and never read"
FIX: Final = "fix.txt"

@dataclass(frozen=True, slots=True)
class Review:
    """What the review reports through its tool."""

    findings: list[str] = describe("what is wrong, one item per finding, each naming its file")

record_review = reporting_tool(
    "record_review",
    "Record what the review found. Call it exactly once, at the end, even with no findings.",
    Review,
)

@role(model=Claude.OPUS, accepts=(str, Review))
def implementer() -> Role[None]:
    """The implementer: handed the request, and the review's findings for the fix."""
    return Role(
        name="implement",
        instructions="Make this change: {{str}}\n\nThe last review found: {{Review}}",
    )

@role(model=Claude.OPUS, accepts=(str, VerifierOutcome))
def reviewer() -> Role[Review]:
    """The reviewer: read-only, and handed the build's outcome."""
    return Role(
        name="review",
        instructions="Review the last commit against: {{str}}\n\nThe build: {{VerifierOutcome}}",
        restrictions={Restriction.NO_FILE_WRITES, Restriction.NO_VCS_WRITES},
        tools=(record_review,),
    )

@dataclass(frozen=True, slots=True)
class Parameters:
    """The workflow's parameters: the request, given with `-r`."""

    request: str = arg("-r", "--request", help="what you want done")

implementing = implementer()
reviewing = reviewer()

@workflow
async def implement_and_check(run: Run[Parameters]) -> None:
    """A review handed a verify's outcome, and the fix for what it finds: the case a recorded
    verify exists for."""
    request = run.params.request
    await run.step(implementing, request, commit="do what was asked")
    checked = await run.verify(run.config["build"])
    review = await run.step(reviewing, request, checked)
    if review.findings:
        await run.step(implementing, request, review, commit="fix what the review found")

def _answer_at(checkout: Path) -> VerifierOutcome:
    """What the build answers in `checkout`: it passes once the fix is there, as a real one does."""
    if (checkout / FIX).exists():
        return VerifierOutcome(passed=True, status=0, output="all passed\n")
    return VerifierOutcome(passed=False, status=1, output="1 failed\n")

class _Measuring(Verifier):
    """The build, measuring the checkout it is run in, and counting its runs."""

    def __init__(self) -> None:
        self.runs = 0

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        self.runs += 1
        return _answer_at(workdir)

def _checks(seen: list[str]) -> testing.Agent:
    """The agent: implements, reviews with one finding every time, and fixes what it was told."""

    def agent(task: AgentTask) -> Reply:
        if any(offered.name == record_review.name for offered in task.tools):
            seen.append("review")
            return Reply(calls=[Call(record_review.name, {"findings": [FINDING]})])
        if FINDING in task.instructions:
            seen.append("fix")
            (task.workspace / FIX).write_bytes(b"the flag, read\n")
        else:
            seen.append("implement")
            (task.workspace / "feature.txt").write_bytes(b"the flag\n")
        return Reply(says="done")

    return agent

async def _walked(repository: Path, root: Path, *, resume: bool) -> dict[str, JsonValue]:
    """One walk of `implement_and_check` over real git and a ledger on disk under `root`. The run
    is interrupted once its fourth entry, the fix's, is written; `resume` resumes it instead."""
    seen: list[str] = []
    gate = _Measuring()
    trees = TreesRoot(root / "trees")
    fakes = container.fakes(trees, config={"build": BUILD}, agent=_checks(seen))
    services = replace(
        fakes.services,
        store=FilesystemStore(AglHome(root / "home")),
        workspaces=GitWorkspaceProvider(repository, trees),
        history=GitHistory(repository),
        integrator=GitIntegrator(repository),
        verifier=gate,
    )
    harness = testing.over(replace(fakes, services=services, store=services.store))
    if resume:
        await harness.resume(implement_and_check)
    else:
        await harness.run(implement_and_check, "-r", REQUEST, interrupt_after=4)
    return {
        "agents": list[JsonValue](seen),
        "gate": gate.runs,
        "recorded": [entry.step for entry in harness.recorded],
        "restrictions": [str(restriction) for restriction in reviewing.restrictions],
    }

def _git(cwd: Path, *argv: str) -> str:
    """Run git for the fixture and the assertions, raw, so no adapter answers for itself."""
    return subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()

@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit, and no configuration from this machine."""
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL verify")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "README.md").write_bytes(b"seed\n")
    _git(work, "add", "README.md")
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work

@pytest.mark.asyncio
async def test_resuming_implement_and_check_after_an_interrupt_keeps_the_fix_commit_on_its_branch(
    repository: Path, tmp_path: Path
) -> None:
    """The review takes the build's outcome at the first commit; the fix goes in; the run is
    interrupted before it ends. On the resume the checkout is at the fix, where the build now
    passes, so a verify that ran again would hand the review another input: the review would run
    again from the first commit, and the fix would replay and move the checkout forward to its
    commit again. The recorded outcome is handed back instead, so neither the build nor an agent
    runs, and every step replays."""
    first = await _walked(repository, tmp_path, resume=False)
    fixed = _git(repository, "rev-parse", "agl/test")
    checkout = tmp_path / "trees" / "test" / "_base"

    assert first["agents"] == ["implement", "review", "fix"]
    assert first["recorded"] == ["implement", VERIFY, "review", "implement"]
    assert _git(repository, "log", "-1", "--format=%s", fixed) == "fix what the review found"
    assert _answer_at(checkout).passed, (
        "the build answers at the fix as it did at the first commit, so this test could not tell "
        "a verify that ran again from one handed back"
    )

    resumed = await _walked(repository, tmp_path, resume=True)

    assert (resumed["gate"], resumed["agents"], resumed["recorded"]) == (0, [], [])
    assert _git(repository, "rev-parse", "agl/test") == fixed

# The two seeds `tests/sdk/test_kill_and_resume.py` uses. The review's two restrictions come out of
# a frozenset in opposite orders under them, which the test below measures before it believes them.
INTERRUPTED_SEED: Final = "1"
RESUMED_SEED: Final = "31337"

_IN_A_PROCESS: Final = """
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import test_verify_record

walk = test_verify_record._walked(Path(sys.argv[2]), Path(sys.argv[3]), resume=sys.argv[4] == "1")
print(json.dumps(asyncio.run(walk)))
"""

def _in_a_process(repository: Path, root: Path, *, resume: bool, seed: str) -> JsonValue:
    """`_walked` in a fresh interpreter under `seed`, and what it printed."""
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            _IN_A_PROCESS,
            str(Path(__file__).parent),
            str(repository),
            str(root),
            "1" if resume else "0",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )
    assert finished.returncode == 0, f"PYTHONHASHSEED={seed} child failed:\n{finished.stderr}"
    answer: JsonValue = json.loads(finished.stdout.splitlines()[-1])
    return answer

def test_a_verify_fed_review_replays_when_resumed_in_a_process_with_another_hash_seed(
    repository: Path, tmp_path: Path
) -> None:
    """The recorded outcome, read back in another process, has to address the review exactly as
    the one the first process measured did, with the review's restrictions sorted either way."""
    first = _in_a_process(repository, tmp_path, resume=False, seed=INTERRUPTED_SEED)
    fixed = _git(repository, "rev-parse", "agl/test")

    resumed = _in_a_process(repository, tmp_path, resume=True, seed=RESUMED_SEED)

    assert isinstance(first, dict) and isinstance(resumed, dict)
    assert first["restrictions"] != resumed["restrictions"], (
        f"both seeds iterate the review's restrictions as {first['restrictions']}, so this test "
        f"cannot tell a sorted set from an iterated one and needs new seeds"
    )
    assert (first["gate"], first["agents"]) == (1, ["implement", "review", "fix"])
    assert (resumed["gate"], resumed["agents"]) == (0, [])
    assert _git(repository, "rev-parse", "agl/test") == fixed
