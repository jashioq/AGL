"""What `run.step` promises: one agent run per step, and a checkout that ends where it was told to.

The suite over `sdk/_engine/steps.py` and over the half of `sdk/workflow.py` that reaches it.
`test_journal_walk.py` holds §3.6's loop against a hand-written worker; this file holds the thing
that *builds* that worker - a `Role` becoming an `AgentTask`, a reporting declaration becoming a
`Tool` with a capture cell behind it, and `commit=` deciding what happens to the worktree.

**The repository is real git, and that is the point rather than an expense.** The git fakes keep
their commits in memory, so "the recorded head is a commit whose tree holds the agent's file" would
be an assertion about a dict, and "the untracked file is gone" would be an assertion about a
directory nothing had ever asked git about. Everything below that names a commit, a tree, a status
or an untracked file is asked of `git` itself, in a repository with no configuration from the
machine it runs on. The ledger is a real `FilesystemStore` for the same reason in miniature:
"nothing under `steps/<name>/`" is a directory listing here, not a digest recomputed by the test
from the arithmetic it is checking.

Five of these are worth naming, because each is written against a failure that is silent:

  * **The entry's `head` is recorded after the commit.** §3.3: "a `run.commit()` after the step
    would run *after* the entry was written, so the recorded `head` would predate the commit - and
    `head` is the reset target, so the next step to miss its fingerprint would delete the work."
    The assertion is therefore not that the head moved - it moves on a run that committed nothing -
    but that the tree the recorded head names **holds the file the agent wrote**.
  * **A step without `commit=` leaves no untracked file behind.** A reset-only implementation
    passes every weaker version of this, which is why the agent writes both a tracked edit and a
    new file and why `git status --porcelain` is asked rather than inferred.
  * **The commit-or-wipe runs when a step raises.** Otherwise a failed reviewer's scratch files sit
    in the checkout its own retry works in, and the next agent reviews them.
  * **The commit-or-wipe also runs, to the end, when a step is cancelled** - the same ending
    through the one door a `finally` does not close by itself. It is the hardest of these to write
    honestly, because the bug it is written against is timing-shaped and a test that waited would
    watch the wipe finish and call that a pass. `_cancelled` and the section it heads say how that
    is avoided; nothing between the cancellation and the assertions is allowed to `await`.
  * **An agent that never reports leaves no entry.** The step re-runs, which is only true if
    nothing was written; a `RoleIncompleteError` that had recorded something would be a step that
    read as done and had no result.

`run.activity` is here too, at the end, because this file already holds the only thing that
dispatches to an adapter. There is little to it by design (§3.7: the framework holds the last
string it was handed and hands it back), so what the tests are written against is the two ways it
could be wrong that nobody would see - a line surviving the step that produced it, and a step
replayed from cache producing one at all.
"""

import asyncio
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Final, assert_type

import pytest

from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.config import container
from agl.ports.agent import AgentOutcome, Claude, Restriction, StopReason, ToolResult
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome, RunScope, step_dir
from agl.ports.ids import ProjectName, RunLabel, StepName
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace
from agl.sdk.roles import Role, RoleIncompleteError
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run

# Every test below is async and marked one by one rather than through a module-level `pytestmark`,
# matching the rest of `tests/sdk/`: `asyncio_mode = "strict"` turns a missing marker into a test
# pytest silently *skips*, which is how a file like this passes without having awaited anything.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# The file the repository is seeded with, and what a step that edits it puts there instead.
SEEDED: Final = "src/a.txt"
SEED: Final = b"the user's own work\n"
EDITED: Final = b"edited by the agent\n"

# What an agent writes when it is told to leave something behind: one file git is tracking and one
# it has never heard of. The second is the assertion that matters - a `reset --hard` alone reverts
# the first and leaves the second sitting there.
SCRATCH: Final = "scratch/notes.md"
FEATURE: Final = "src/feature.py"

_NOTHING: Final[Mapping[str, bytes]] = MappingProxyType({})


@dataclass(frozen=True)
class Summary:
    """A reporting payload: one string, which is the whole of what these agents have to say."""

    text: str


REPORT: Final = reporting_tool("report", "report what you did", Summary)


class _Crash(Exception):
    """What an agent dying mid-step looks like from here. Any exception would do - the walk has no
    opinion about which, and lets it out untouched."""


# --- the repository, the bundle, and the run -----------------------------------------------------


def _git(where: Path, *argv: str) -> str:
    """One git command, for arranging and observing. Never for the thing under test.

    `test_git_workspace.py`'s helper and its argument: a test that built its repository through the
    adapter would be resting its arrangement on the behaviour it is about to check.
    """
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit, and no configuration from this machine.

    The `GIT_CONFIG_*` variables are what make this suite the same suite everywhere - a developer
    with `commit.gpgsign` on, a `core.hooksPath` of their own or a template directory would
    otherwise be running different tests - and they go through `monkeypatch` so the adapter, which
    inherits the environment, sees them too. The identity variables are set because `commit_all`
    deliberately does not invent one.
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
    seeded = work / SEEDED
    seeded.parent.mkdir(parents=True)
    seeded.write_bytes(SEED)
    _git(work, "add", SEEDED)
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work


@pytest.fixture
def base(repository: Path) -> str:
    """The commit the run is cut from, resolved - the pinned `RunSpec.base_sha` shape of a base."""
    return _git(repository, "rev-parse", "HEAD").strip()


def _run(repository: Path, tmp_path: Path, base: str, script: Script | None = None) -> Run[None]:
    """A `Run` over one real repository, one real ledger and one scripted agent.

    The bundle comes from the composition root's fakes and has two of its eight fields replaced,
    which is the smallest arrangement that puts real git and a real store under a `Run` without a
    test constructing eight ports by hand. The five that stay fake - history, integrator, verifier,
    terminal, clock - are not reached by a step, and the sixth, the routing runner, is where the
    script goes.

    Called twice with the same arguments it is a resume: the same ledger on disk, the same worktree
    reopened, and a fresh counter, which is what §3.6 means by "`n` is never persisted".
    """
    trees = TreesRoot(tmp_path / "trees")
    harness = container.fakes(trees, claude=script)
    services = replace(
        harness.services,
        store=FilesystemStore(AglHome(tmp_path / "home")),
        workspaces=GitWorkspaceProvider(repository, trees),
    )
    return Run(params=None, services=services, scope=SCOPE, base=base)


async def _checkout(repository: Path, tmp_path: Path, base: str) -> Workspace:
    """The run's own checkout, reopened - `WorkspaceProvider.open` is idempotent by contract, so
    asking for it after a step hands back exactly what that step left."""
    provider = GitWorkspaceProvider(repository, TreesRoot(tmp_path / "trees"))
    return await provider.open(LABEL, None, base)


# --- roles, and the agents that serve them -------------------------------------------------------


def _role(instructions: str, *, read_only: bool = False) -> Role[Summary]:
    """A reporting role: its result is `REPORT`'s payload, read back as a `Summary`.

    `read_only` declares `NO_VCS_WRITES`, which is what §3.3 asks an author to pair with a step
    that passes no `commit=`. Nothing checks the pairing - the framework does one predictable thing
    either way - so it is here because these tests should read the way a workflow does.
    """
    restrictions = {Restriction.NO_VCS_WRITES} if read_only else set[Restriction]()
    return Role(
        instructions=instructions,
        model=Claude.SONNET,
        restrictions=restrictions,
        tools=(REPORT,),
    )


def _effect(instructions: str) -> Role[None]:
    """A role with no reporting tool: its result is `null` and its effect is commits (§3.3)."""
    return Role(instructions=instructions, model=Claude.SONNET)


class _Agent:
    """What the fake was asked and what it was told back, written down.

    A recorder here rather than on `FakeAgentRunner`, which deliberately holds no record of what it
    ran: what a test wants to know is already reachable from the script it supplied.
    """

    def __init__(self) -> None:
        self.runs: list[str] = []
        """One entry per dispatch, holding that task's instructions. `len(runs)` is what "the agent
        was paid for again" means, and a replay's whole observable difference from a re-run."""

        self.results: list[ToolResult] = []
        """Every answer the reporting tool gave, refusals included - §3.3's rejection path is a
        `ToolResult` going back to the model, so this is where it is visible from."""

        self.asked: list[Question] = []
        """Every question the script put to `on_question`, or nothing if it never asked."""


def _agent(
    record: _Agent,
    *,
    writes: Mapping[str, bytes] = _NOTHING,
    reports: bool = True,
    calls: int = 1,
    raises: bool = False,
    asks: str | None = None,
    stop: StopReason | None = StopReason.COMPLETED,
    says: str = "",
) -> Script:
    """One agent's conduct, in the only vocabulary the port has.

    Writing to `task.workspace` with the stdlib is the script's own code and not the adapter's -
    `adapters/claude_code/fake.py` says so in as many words - which is what lets a fake agent leave
    a tracked edit and an untracked file behind for the endings below to deal with.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        record.runs.append(conversation.task.instructions)
        if asks is not None:
            answer = await conversation.ask(Question(prompt=asks))
            record.results.append(ToolResult(text="" if answer is None else answer.text))
        for name, content in writes.items():
            target = conversation.task.workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if raises:
            raise _Crash("the agent died mid-step")
        for attempt in range(calls if reports else 0):
            payload = {"text": f"{conversation.task.instructions} #{attempt}"}
            record.results.append(await conversation.call(REPORT.name, payload))
        return AgentOutcome(stop_reason=stop, text=says)

    return _script


# --- the ledger, read off disk -------------------------------------------------------------------


def _entries(tmp_path: Path, step: str) -> list[dict[str, JsonValue]]:
    """Everything recorded under `steps/<step>/`, in filename order. Empty when nothing is.

    Read as files rather than through the `Store`, because "no entry was written" is a claim about
    a directory: a `read_entry` at an address the test computed could only say that *that* address
    is empty, and the address is what a mistake here would have moved.
    """
    directory = step_dir(AglHome(tmp_path / "home"), SCOPE, StepName(step))
    found: list[dict[str, JsonValue]] = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))
    ]
    return found


def _one(tmp_path: Path, step: str) -> dict[str, JsonValue]:
    """The one entry `steps/<step>/` holds. Two would mean the step ran twice."""
    entries = _entries(tmp_path, step)
    assert len(entries) == 1, f"steps/{step}/ holds {len(entries)} entries, not one"
    return entries[0]


def _text(entry: Mapping[str, JsonValue], key: str) -> str:
    """One string off an entry, narrowed. A parsed file is anything, and mypy is right to say so."""
    value = entry[key]
    assert isinstance(value, str)
    return value


def _tree(repository: Path, commit: str) -> list[str]:
    """Every path in the tree a commit names - what "the recorded head holds the file" is asked of.

    Asked of the repository rather than of the worktree, because a commit id is an object in the
    shared object store and the question is about the object, not about what is checked out.
    """
    return _git(repository, "ls-tree", "-r", "--name-only", commit).split()


# --- three steps, and the second walk that pays for none of them ---------------------------------


@pytest.mark.asyncio
async def test_three_sequential_steps_replay_against_a_second_walk(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.6's whole promise, at the surface a workflow actually writes.

    Three steps, one of them committing, then the same three walked again: the second walk calls no
    agent and returns the same three values. The recorder is shared between the two runs so that
    "no agent was called" is counted across both rather than reset by the arrangement.
    """
    record = _Agent()
    written = {SEEDED: EDITED}

    first = await _three(_run(repository, tmp_path, base, _agent(record, writes=written)))

    assert first == [Summary("write the spec #0"), Summary("implement it #0"), Summary("review #0")]
    assert len(record.runs) == 3
    assert [len(_entries(tmp_path, step)) for step in ("spec", "implement", "review")] == [1, 1, 1]

    replayed = await _three(_run(repository, tmp_path, base, _agent(record, writes=written)))

    assert replayed == first
    assert len(record.runs) == 3, "a resume paid for agents whose results were on the ledger"


async def _three(run: Run[None]) -> list[Summary]:
    """A workflow of three sequential steps - §3.3's `fix` shape, with a report on every one."""
    spec = await run.step("spec", _role("write the spec", read_only=True))
    # §3.3's typing promise, checked by `mypy --strict` over `tests/` rather than hoped for: the
    # `Role[Summary]` carries the payload type through `step` and out to the workflow.
    assert_type(spec, Summary)
    built = await run.step("implement", _role("implement it"), commit="implement the spec")
    review = await run.step("review", _role("review", read_only=True))
    return [spec, built, review]


# --- an agent that never reports -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_agent_that_never_reports_leaves_no_entry_and_the_step_runs_again(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3: "if the agent returns without firing it, there is no result and the step re-runs".

    Both halves, because either alone is satisfiable by the wrong thing: an entry that was written
    would make the step read as done with no result in it, and a step that did not re-run would
    leave the run stuck on an address nothing will ever fill.
    """
    record = _Agent()
    silent = _run(repository, tmp_path, base, _agent(record, reports=False, says="I have finished"))
    role = _role("review", read_only=True)

    with pytest.raises(RoleIncompleteError, match="report"):
        await silent.step("review", role)

    assert _entries(tmp_path, "review") == [], "a step with no result recorded one anyway"

    with pytest.raises(RoleIncompleteError):
        await silent.step("review", role)

    assert len(record.runs) == 2, "the second attempt replayed a step that had recorded nothing"

    # And the address the two failures would have used is still free: a walk whose agent does
    # report lands its entry there, which is what "claimed no slot" means from outside.
    reporting = _run(repository, tmp_path, base, _agent(record))
    assert await reporting.step("review", role) == Summary("review #0")
    assert len(record.runs) == 3
    assert len(_entries(tmp_path, "review")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop", "fix"),
    [
        (StopReason.LIMIT, "raise the limit"),
        (StopReason.COMPLETED, "the prompt is what did not read"),
        (None, "did not say why it stopped"),
    ],
)
async def test_the_incomplete_message_sends_the_reader_to_the_fix_the_stop_reason_implies(
    repository: Path, tmp_path: Path, base: str, stop: StopReason | None, fix: str
) -> None:
    """`AgentOutcome.stop_reason`'s own distinction, spent where that field says it should be.

    "It ran out of turns" and "it decided it was finished" send a reader to different fixes - raise
    the limit, or fix the prompt - and `None` says the message can offer neither. The agent's
    closing text is quoted with all three, because it is what it said instead of reporting and it
    is the only evidence there is.
    """
    record = _Agent()
    said = "I read the diff and it looked fine to me"
    run = _run(repository, tmp_path, base, _agent(record, reports=False, stop=stop, says=said))

    with pytest.raises(RoleIncompleteError) as raised:
        await run.step("review", _role("review", read_only=True))

    assert fix in str(raised.value)
    assert said in str(raised.value), "the one thing the agent did say was dropped from the report"


# --- what `commit=` does, and when it does it ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_step_with_commit_records_a_head_whose_tree_holds_the_agents_file(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The ordering §3.3 spends a paragraph on: the entry's `head` is read **after** the commit.

    A weaker test - "the recorded head is not `last_good`" - passes on a run where the worker
    committed nothing at all, and passes against the bug: `commit_all` on a clean tree is a no-op
    returning the unchanged head, so the two heads agree and nothing notices. What cannot be
    satisfied by a head read too early is that the commit the entry names **contains the file the
    agent wrote**.
    """
    record = _Agent()
    written = {FEATURE: b"the callback route\n"}
    run = _run(repository, tmp_path, base, _agent(record, writes=written))

    await run.step("implement", _role("implement T-01"), commit="implement T-01")

    recorded = _text(_one(tmp_path, "implement"), "head")
    assert FEATURE in _tree(repository, recorded), (
        "the entry's `head` names a commit from before this step's own commit. `head` is the reset "
        "target, so the next step to miss its fingerprint restores to it and deletes the work"
    )
    assert recorded != base
    workspace = await _checkout(repository, tmp_path, base)
    assert (workspace.path / FEATURE).read_bytes() == b"the callback route\n"
    assert _git(workspace.path, "status", "--porcelain") == ""


@pytest.mark.asyncio
async def test_a_step_without_commit_leaves_the_worktree_byte_identical_to_last_good(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3's wipe: "not a scratch file, not a cache directory, not a partial edit".

    The agent leaves a tracked edit **and** a file git has never heard of, because a reset-only
    implementation passes the version of this test that only checks the edit - untracked files
    survive `reset --hard`, and that is the exact case `Workspace.restore` exists to make one
    operation rather than two.
    """
    record = _Agent()
    left = {SEEDED: EDITED, SCRATCH: b"half a thought\n"}
    run = _run(repository, tmp_path, base, _agent(record, writes=left))

    assert await run.step("review", _role("review", read_only=True)) == Summary("review #0")

    workspace = await _checkout(repository, tmp_path, base)
    assert (workspace.path / SEEDED).read_bytes() == SEED, "the tracked edit was not reverted"
    assert not (workspace.path / SCRATCH).exists(), (
        "the untracked file survived, which is `reset --hard` without the `clean -fd`: the next "
        "step's agent works in a checkout holding a file no step put there"
    )
    assert _git(workspace.path, "status", "--porcelain") == ""
    assert _git(workspace.path, "rev-parse", "HEAD").strip() == base
    assert _text(_one(tmp_path, "review"), "head") == base


@pytest.mark.asyncio
async def test_changing_only_the_commit_message_does_not_invalidate_the_entry(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.6 keeps the message out of the fingerprint: it is cosmetic, so rewording it must not
    re-run an agent. The trade is stated there too - the replayed step keeps the commit it already
    made, message and all - and that half is asserted, because it is the one that surprises."""
    record = _Agent()
    written = {FEATURE: b"the callback route\n"}
    role = _role("implement T-01")

    first = _run(repository, tmp_path, base, _agent(record, writes=written))
    await first.step("implement", role, commit="implement T-01")

    second = _run(repository, tmp_path, base, _agent(record, writes=written))
    await second.step("implement", role, commit="implement T-01: add the oauth callback route")

    assert len(record.runs) == 1, "rewording a commit message re-ran the agent"
    recorded = _text(_one(tmp_path, "implement"), "head")
    subject = _git(repository, "log", "-1", "--format=%s", recorded).strip()
    assert subject == "implement T-01"


# --- the endings run when a step raises ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_wipe_runs_when_a_step_raises_and_no_entry_is_written(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3: "the wipe runs whether the step succeeded or raised".

    The failure it prevents is not this step's - this step is already over - it is the next one's:
    a reviewer that scribbled on its way to dying would otherwise leave the scribbles in the
    checkout its own retry works in, and the retry's agent reviews them.
    """
    record = _Agent()
    left = {SEEDED: EDITED, SCRATCH: b"half a thought\n"}
    run = _run(repository, tmp_path, base, _agent(record, writes=left, raises=True))

    with pytest.raises(_Crash, match="died mid-step"):
        await run.step("review", _role("review", read_only=True))

    workspace = await _checkout(repository, tmp_path, base)
    assert (workspace.path / SEEDED).read_bytes() == SEED
    assert not (workspace.path / SCRATCH).exists()
    assert _git(workspace.path, "status", "--porcelain") == ""
    assert _entries(tmp_path, "review") == [], "a step that raised was recorded as done"


@pytest.mark.asyncio
async def test_a_step_that_raises_with_commit_commits_anyway_and_still_records_nothing(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The other ending, on the same path: `commit=` given, the framework commits either way.

    "No check of what the role declared, and no comparison of HEAD before and after" (§3.3) - one
    predictable thing per `commit=`, and the exception does not make it two. What keeps this from
    stranding a half-finished commit is the rule beside it: no entry means `last_good` never
    advanced, so the next attempt's unconditional pre-run restore puts the branch back before it.
    """
    record = _Agent()
    run = _run(
        repository,
        tmp_path,
        base,
        _agent(record, writes={FEATURE: b"half a route\n"}, raises=True),
    )

    with pytest.raises(_Crash):
        await run.step("implement", _role("implement T-01"), commit="implement T-01")

    workspace = await _checkout(repository, tmp_path, base)
    committed = _git(workspace.path, "rev-parse", "HEAD").strip()
    assert committed != base
    assert FEATURE in _tree(repository, committed)
    assert _entries(tmp_path, "implement") == []

    # And the retry restores past it, which is what makes the commit above harmless rather than a
    # half-done step nobody can see: `last_good` is chained from entries, and there are none.
    reporting = _run(repository, tmp_path, base, _agent(record))
    await reporting.step("implement", _role("implement T-01"), commit="implement T-01")
    assert _git(workspace.path, "rev-parse", "HEAD").strip() == base
    assert not (workspace.path / FEATURE).exists()


# --- the endings run when a step is cancelled ----------------------------------------------------
#
# The raise path above and this one are the same ending through two different doors, and only this
# door needs `journal.py`'s shield: `await workspace.restore(...)` written plainly in a `finally`
# is aborted at its own first suspension the moment a second cancellation arrives, so the wipe gets
# as far as `reset --hard` and no further and every untracked file the step created survives into
# whatever runs next.
#
# **Both tests are arranged so that they cannot pass for the wrong reason**, and the arrangement is
# the interesting part, because two different wrong implementations pass a careless version:
#
#   * *A single `cancel()` is not enough to fail even the unshielded code.* asyncio delivers one
#     cancellation once - `CancelledError` is raised at the worker's own `await`, and the `finally`
#     that follows is then an ordinary piece of code with nothing pending against it. So
#     `_cancelled` cancels until the task is actually dead, which is what a supervisor tearing a
#     run down does and what a second Ctrl-C is.
#   * *`asyncio.shield` on its own does not wait.* `await shield(inner)` re-raises in the outer task
#     immediately and leaves `inner` running, detached, so the `finally` returns with the wipe
#     merely in progress. A test that awaited anything at all before looking - reopening the
#     checkout, say - would hand the event loop back and watch that detached wipe finish. So the
#     checkout is opened **before** the step, and every assertion after the cancellation is
#     synchronous: `Path.exists`, `read_bytes`, and `_git`, which is a blocking `subprocess.run`
#     and yields to no event loop. Nothing detached can make progress inside them.


def _blocks(record: _Agent, running: asyncio.Event, writes: Mapping[str, bytes]) -> Script:
    """An agent that leaves its files behind and then never finishes - a step to cancel.

    `running` is set once the leavings are on disk, so the test cancels at a point it chose rather
    than at one it hoped for: before it is set there is nothing to wipe, and after it the agent is
    suspended and will stay that way until the task around it is torn down.

    It reports an activity line on its way in, so that the cell §3.7 says is `None` when nothing is
    running has something in it at the moment the cancellation lands. Without that the assertion
    about it afterwards would be true of an implementation that never set it either.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        record.runs.append(conversation.task.instructions)
        conversation.report("Bash: ./gradlew build")
        for name, content in writes.items():
            target = conversation.task.workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        running.set()
        await asyncio.Event().wait()
        raise AssertionError("the blocked agent was resumed, which nothing in this test does")

    return _script


async def _cancelled[T](task: asyncio.Task[T]) -> None:
    """Cancel until the task is dead, then assert that it died of it.

    Not one `cancel()`, for the reason the section header gives: one is delivered at the worker's
    suspension and leaves the ending an ordinary `finally` with nothing pending against it, so a
    single-shot version of this passes against the very bug it is written for. Cancelling until
    `done()` is also the honest model of what tears a run down - a supervisor that asks again, a
    person pressing Ctrl-C twice - and it is what puts a cancellation *inside* the ending's own
    `await`, which is the moment the whole of this hinges on.

    Nothing here cancels the ending itself. It is a task of its own, `journal.py` shields it, and
    the cancellations below land on the step and on nothing else.
    """
    while not task.done():
        task.cancel()
        await asyncio.sleep(0)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled(), (
        "the step swallowed its cancellation and ended some other way. A step that runs its ending "
        "and then declines to die is a task nothing can stop, which is worse than the leavings the "
        "ending exists to sweep up"
    )


@pytest.mark.asyncio
async def test_a_cancelled_step_still_wipes_the_worktree_and_records_nothing(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3's wipe survives a cancellation, which is the one path a bare `finally` does not cover.

    A cancelled reviewer's scratch files are the same contamination a crashed reviewer's are - the
    next step's agent works in the checkout this one left - and a cancellation is the more likely
    of the two to happen at the worst moment, because it happens while the agent is mid-flight by
    definition.

    The untracked file is the assertion that carries this. `reset --hard` is the first half of
    `restore` and `clean -fd` the second, so a wipe interrupted between them reverts the tracked
    edit and leaves the scratch file exactly where it was: an implementation that gets half way
    through passes on `SEEDED` and fails only here.
    """
    record = _Agent()
    running = asyncio.Event()
    left = {SEEDED: EDITED, SCRATCH: b"half a thought\n"}
    # Opened before the step and never reopened after it - see the section header. Idempotent by
    # contract, so the step below is handed this same checkout.
    workspace = await _checkout(repository, tmp_path, base)
    run = _run(repository, tmp_path, base, _blocks(record, running, left))

    step = asyncio.create_task(run.step("review", _role("review", read_only=True)))
    await running.wait()
    await _cancelled(step)

    assert not (workspace.path / SCRATCH).exists(), (
        "a cancelled step left its untracked file in the checkout. The ending did not run to the "
        "end: `restore` is `reset --hard` and then `clean -fd`, and a cancellation delivered "
        "between the two leaves exactly this behind for the next step's agent to work on top of"
    )
    assert (workspace.path / SEEDED).read_bytes() == SEED
    assert _git(workspace.path, "status", "--porcelain") == ""
    assert _git(workspace.path, "rev-parse", "HEAD").strip() == base
    assert _entries(tmp_path, "review") == [], "a cancelled step was recorded as done"
    assert run.activity is None, "a cancelled step left its last activity line standing"


@pytest.mark.asyncio
async def test_a_cancelled_step_with_commit_still_commits_and_still_records_nothing(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The other ending, through the same door: §3.3's "one predictable thing either way".

    `commit=` given, the framework commits whatever is dirty - and a cancellation does not make
    that two things any more than an exception did. What keeps the commit from stranding a
    half-finished step is the rule beside it, which is also asserted: no entry means `last_good`
    never advanced, so the next attempt's unconditional pre-run restore puts the branch back past
    it.
    """
    record = _Agent()
    running = asyncio.Event()
    workspace = await _checkout(repository, tmp_path, base)
    blocked = _blocks(record, running, {FEATURE: b"half a route\n"})
    run = _run(repository, tmp_path, base, blocked)

    step = asyncio.create_task(
        run.step("implement", _role("implement T-01"), commit="implement T-01")
    )
    await running.wait()
    await _cancelled(step)

    committed = _git(workspace.path, "rev-parse", "HEAD").strip()
    assert committed != base, (
        "a cancelled step with `commit=` committed nothing. The ending did not run: the framework "
        "does one predictable thing per `commit=`, and being torn down is not a third one"
    )
    assert FEATURE in _tree(repository, committed)
    assert _git(workspace.path, "status", "--porcelain") == ""
    assert _entries(tmp_path, "implement") == []


# --- the reporting tool, and the second call -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_call_to_the_reporting_tool_is_refused_and_the_first_payload_stands(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3 does not settle this and 12.1 does: first-wins, with the refusal going back in-session.

    Last-wins is the other candidate and it fails silently - an agent reporting once per finding
    records only the last one, and the workflow reads one finding where the review found six.
    First-wins fails in the channel this design already built for a payload it will not take: the
    model is told, in words, inside the same conversation, and stops.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record, calls=2))

    assert await run.step("review", _role("review", read_only=True)) == Summary("review #0")

    assert [result.rejected for result in record.results] == [False, True]
    assert "already recorded" in record.results[1].text
    assert _one(tmp_path, "review")["value"] == {"text": "review #0"}


@pytest.mark.asyncio
async def test_a_malformed_payload_is_rejected_back_to_the_agent_and_not_raised(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3: "rejected by the tool back to the agent within the same conversation, so the model
    corrects itself. Not an adapter retry, not a workflow retry" - and not an exception either.

    The script sends a payload the declaration will not take, reads the refusal, and sends a good
    one. One step, one agent run, one entry, and the workflow never learns any of it happened.
    """
    record = _Agent()

    async def _corrects(conversation: Conversation) -> AgentOutcome:
        record.runs.append(conversation.task.instructions)
        record.results.append(await conversation.call(REPORT.name, {"text": 7}))
        record.results.append(await conversation.call(REPORT.name, {"text": "on reflection"}))
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    run = _run(repository, tmp_path, base, _corrects)

    assert await run.step("review", _role("review", read_only=True)) == Summary("on reflection")
    assert [result.rejected for result in record.results] == [True, False]
    assert "a string" in record.results[0].text
    assert len(record.runs) == 1


# --- an effect step ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_effect_step_records_a_null_value_and_the_commits_are_the_result(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3's other step kind: no reporting tool, so the result is `null` and the effect is commits.

    The role declares no tools at all, which means the task carries none - and the script therefore
    could not call one if it wanted to, `Conversation.call` refusing a tool the task did not
    declare. Nothing about the outcome is read: an effect step's agent is judged by what is in the
    commit.
    """
    record = _Agent()
    run = _run(
        repository,
        tmp_path,
        base,
        _agent(record, reports=False, writes={FEATURE: b"the callback route\n"}),
    )

    await run.step("implement", _effect("implement T-01"), commit="implement T-01")

    entry = _one(tmp_path, "implement")
    assert entry["value"] is None, "an effect step recorded something other than null"
    assert FEATURE in _tree(repository, _text(entry, "head"))
    assert len(record.runs) == 1


# --- the role's own question handler -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_roles_question_handler_reaches_the_runner_and_its_answer_returns(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.7: the answer returns into the same live session, so a negotiation is N rounds inside one
    step rather than N steps.

    `Role.on_question` folds `Capability.MID_RUN_QUESTIONS` into `requires` at declaration time, on
    the argument that there is no role which declares a handler and does not need a backend able to
    ask. A `step` that did not pass the handler on would leave preflight insisting on a capability
    nothing used, and the workflow's approval gate simply absent - the agent approving itself, with
    nothing raised and nothing logged as wrong.
    """
    record = _Agent()

    async def _answers(question: Question) -> Answer:
        record.asked.append(question)
        return Answer(text="land it")

    run = _run(repository, tmp_path, base, _agent(record, asks="Land it, or keep going?"))
    role = Role(
        instructions="decide",
        model=Claude.SONNET,
        tools=(REPORT,),
        on_question=_answers,
    )

    assert await run.step("decide", role) == Summary("decide #0")
    assert [question.prompt for question in record.asked] == ["Land it, or keep going?"]
    assert record.results[0].text == "land it", "the answer did not reach the agent that asked"


# --- `run.activity` ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_is_the_adapters_own_last_line_and_is_gone_when_the_step_ends(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.7: the framework holds the last string it was handed and hands it back, and that is all.

    The two lines are read from *inside* the run, because that is the only place there is anything
    to read - `None` when nothing is running means an assertion after the step can only ever see
    `None`. They are deliberately spelled the way §3.7 spells them, tool name and target, to make
    the point that nothing here parsed either one: no `Activity` type, no verb taxonomy, no lookup
    table, so what comes back is what the adapter said, character for character.

    **And it is cleared when the step ends**, which is the half that fails silently. A line left
    standing describes work that finished minutes ago, on a screen §3.7 redraws every frame, and
    nothing anywhere raises about it.
    """
    record = _Agent()
    seen: list[str | None] = []
    run: Run[None] | None = None

    async def _reports(conversation: Conversation) -> AgentOutcome:
        assert run is not None, "the script ran before the `Run` it reads existed"
        record.runs.append(conversation.task.instructions)
        seen.append(run.activity)
        conversation.report("Bash: ./gradlew build")
        seen.append(run.activity)
        conversation.report("Edit: domain/usecase.kt")
        seen.append(run.activity)
        record.results.append(await conversation.call(REPORT.name, {"text": "done"}))
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    run = _run(repository, tmp_path, base, _reports)

    assert await run.step("review", _role("review", read_only=True)) == Summary("done")

    assert seen == [None, "Bash: ./gradlew build", "Edit: domain/usecase.kt"], (
        "the activity a step reported is not what came back out of `run.activity`: either an "
        "adapter's line was rewritten on its way through, or the cell is not the most recent one"
    )
    assert run.activity is None, (
        "the last line of a finished step is still there. §3.7's `None` means nothing is running, "
        "and a view re-invoked every frame will go on reporting a build that ended long ago"
    )


@pytest.mark.asyncio
async def test_a_step_that_raises_leaves_no_activity_behind_and_a_replayed_one_reports_none(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The two endings that are not "it returned", and the one that cannot report at all.

    An agent that died mid-`Bash` is not still running `Bash`, so the cell is cleared on the way
    out of a dispatch that raised exactly as on the way out of one that returned. (The cancelled
    ending is asserted where the cancellation is, beside the wipe it shares a `finally` with.)

    **A step replayed from cache has no activity at all, correctly, since nothing is running**
    (§3.7). The second walk below is handed a script that reports on its very first line and is
    never called at all, which is the whole mechanism: activity comes from a callback passed on the
    dispatch, a replay hit returns the stored value without dispatching, and so there is no call
    that could produce a line. Nothing about it is written down, which is the other half of the
    same sentence and is why it cannot come back off the ledger either.
    """
    record = _Agent()

    async def _dies(conversation: Conversation) -> AgentOutcome:
        record.runs.append(conversation.task.instructions)
        conversation.report("Bash: ./gradlew build")
        raise _Crash("the agent died mid-step")

    dying = _run(repository, tmp_path, base, _dies)

    with pytest.raises(_Crash):
        await dying.step("review", _role("review", read_only=True))

    assert dying.activity is None, (
        "an agent that died mid-`Bash` left `Bash` on the board. The cell is cleared on every exit "
        "from the dispatch and not only on the one that returned"
    )

    # And now a walk that records something, followed by one that replays it.
    fresh = _run(repository, tmp_path, base, _agent(record))
    assert await fresh.step("review", _role("review", read_only=True)) == Summary("review #0")

    async def _shouts(conversation: Conversation) -> AgentOutcome:
        record.runs.append(conversation.task.instructions)
        conversation.report("Read: connectors/api/backend.ts")
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    replaying = _run(repository, tmp_path, base, _shouts)
    assert await replaying.step("review", _role("review", read_only=True)) == Summary("review #0")

    assert len(record.runs) == 2, "the replay dispatched an agent, so it proves nothing about this"
    assert replaying.activity is None, (
        "a step replayed from cache produced an activity line. Nothing was running, so there was "
        "nothing to report - and activity is never persisted, so nothing could have come back"
    )


# --- two steps arriving at an unopened namespace at once -----------------------------------------


@pytest.mark.asyncio
async def test_two_gathered_steps_open_one_checkout_and_take_two_addresses(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The one thing 12.1 adds that stage 11 could not have measured: the lazy open, contended.

    A `Journal` is built over a `Workspace`, so the checkout has to be opened before the walk that
    serializes steps exists. Two gathered steps in a fresh namespace both arrive at that open. If
    the second builds a second `Journal`, the two walks hold different locks over one checkout and
    overlap - and with real git they really do overlap, every `restore` being a subprocess and so a
    genuine suspension - so both take the counter's address before either claims it, both write to
    the same digest, and the ledger ends up holding **one** entry for two steps that ran.

    The two steps are deliberately identical: same name, same role, no inputs, so they share a
    `base` and only the counter separates them. That is what makes the entry count the assertion.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    role = _role("review", read_only=True)

    both = await asyncio.gather(run.step("review", role), run.step("review", role))

    assert list(both) == [Summary("review #0"), Summary("review #0")]
    assert len(record.runs) == 2
    assert len(_entries(tmp_path, "review")) == 2, (
        "two steps in one namespace wrote one entry between them: they overlapped, so both took "
        "the same address and the second clobbered the first"
    )


# --- what a step refuses before it provisions anything -------------------------------------------


@pytest.mark.asyncio
async def test_a_step_name_that_could_not_be_a_path_segment_is_refused(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3: names are opaque strings, "validated on the way in" - filesystem- and ref-safe.

    Refused before anything is opened and before any agent is dispatched, which is the whole reason
    the `StepName` is constructed first: a run that cannot record a step should not pay for one.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    with pytest.raises(InputError, match="step name"):
        await run.step("../escape", _role("review", read_only=True))

    assert record.runs == []
    assert not (tmp_path / "trees").exists(), "a refused step name provisioned a checkout anyway"
