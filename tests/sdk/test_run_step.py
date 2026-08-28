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

Six of these are worth naming, because each is written against a failure that is silent:

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
  * **What the agent is asked is the role's own text plus this step's inputs.** §3.3 appends one
    block of canonical JSON under a fixed heading rather than interpolating, and both halves of that
    fail in silence: inputs that never arrive leave a `triage` agent triaging findings it was never
    shown, while a template engine quietly rewrites a prompt that carries a JSON Schema. The section
    near the bottom asserts the whole dispatched string and not a substring of it.

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
from agl.adapters.git.history import GitHistory
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.config import container
from agl.ports.agent import (
    AgentOutcome,
    Claude,
    QuestionHandler,
    Restriction,
    StopReason,
    ToolResult,
)
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome, RunScope, step_dir
from agl.ports.ids import ProjectName, RunLabel, StepName
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace
from agl.sdk.roles import Role, RoleIncompleteError, prompt_file, role
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


@dataclass(frozen=True)
class Restatement:
    """`Summary`'s shape under another name, for the payload-identity section near the bottom.

    Field for field the same, so the schema derived from it is the same schema but for the one term
    13.0 added: the qualified type name. A reporting tool declared over it carries `REPORT`'s own
    name and description too, which leaves the payload *type* as the only difference between two
    otherwise identical roles - and so as the only thing that can move the fingerprint.
    """

    text: str


RESTATE: Final = reporting_tool(REPORT.name, "report what you did", Restatement)


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
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL contract")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
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

    The bundle comes from the composition root's fakes and has three of its eight fields replaced,
    which is the smallest arrangement that puts real git and a real store under a `Run` without a
    test constructing eight ports by hand. The four that stay fake - integrator, verifier, terminal,
    clock - are not reached by a step, and the fifth, the routing runner, is where the script goes.

    **`history` is real because a step now reaches it.** 13.2 made `Steps._namespace` resolve its
    base through `History.resolve` and hand the one resolved value to both the checkout and the
    `Journal`, so that the cut and the chain cannot disagree about where a namespace began; a
    `FakeHistory` here answers about a `FakeRepository` that has never heard of this repository's
    commits, and would refuse the run's own pinned base. Real git is asked about real git.

    Called twice with the same arguments it is a resume: the same ledger on disk, the same worktree
    reopened, and a fresh counter, which is what §3.6 means by "`n` is never persisted".
    """
    trees = TreesRoot(tmp_path / "trees")
    harness = container.fakes(trees, claude=script)
    services = replace(
        harness.services,
        store=FilesystemStore(AglHome(tmp_path / "home")),
        workspaces=GitWorkspaceProvider(repository, trees),
        history=GitHistory(repository),
    )
    return Run(params=None, services=services, scope=SCOPE, base=base)


async def _checkout(repository: Path, tmp_path: Path, base: str) -> Workspace:
    """The run's own checkout, reopened - `WorkspaceProvider.open` is idempotent by contract, so
    asking for it after a step hands back exactly what that step left."""
    provider = GitWorkspaceProvider(repository, TreesRoot(tmp_path / "trees"))
    return await provider.open(LABEL, None, base)


# --- roles, and the agents that serve them -------------------------------------------------------


@role(model=Claude.SONNET)
def _role(name: str, instructions: str, *, read_only: bool = False) -> Role[Summary]:
    """A reporting role: its result is `REPORT`'s payload, read back as a `Summary`.

    `name` is what its entries are recorded under, since `run.step` carries none of its own
    (§3.3) - so a test that wants two addresses declares two roles, and one that wants two calls at
    one address hands this same object over twice.

    `read_only` declares `NO_VCS_WRITES`, which is what §3.3 asks an author to pair with a step
    that passes no `commit=`. Nothing checks the pairing - the framework does one predictable thing
    either way - so it is here because these tests should read the way a workflow does.
    """
    restrictions = {Restriction.NO_VCS_WRITES} if read_only else set[Restriction]()
    return Role(
        name=name,
        instructions=instructions,
        restrictions=restrictions,
        tools=(REPORT,),
    )


@role(model=Claude.SONNET)
def _effect(name: str, instructions: str) -> Role[None]:
    """A role with no reporting tool: its result is `null` and its effect is commits (§3.3)."""
    return Role(name=name, instructions=instructions)


@role(model=Claude.SONNET)
def _deciding(*, on_question: QuestionHandler | None = None) -> Role[Summary]:
    """A reporting role that negotiates: §3.7's handler is a closure over a `Run`, so it can only
    reach a role as the one argument this factory takes."""
    return Role(name="decide", instructions="decide", tools=(REPORT,), on_question=on_question)


@role(model=Claude.SONNET)
def _restating() -> Role[Restatement]:
    """`_role("review", "review", read_only=True)` in every fingerprint term but one: it reports
    through a tool of the same name and description whose payload type is a different class."""
    return Role(
        name="review",
        instructions="review",
        restrictions={Restriction.NO_VCS_WRITES},
        tools=(RESTATE,),
    )


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
    spec = await run.step(_role("spec", "write the spec", read_only=True))
    # §3.3's typing promise, checked by `mypy --strict` over `tests/` rather than hoped for: the
    # `Role[Summary]` carries the payload type through `step` and out to the workflow.
    assert_type(spec, Summary)
    built = await run.step(_role("implement", "implement it"), commit="implement the spec")
    review = await run.step(_role("review", "review", read_only=True))
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
    role = _role("review", "review", read_only=True)

    with pytest.raises(RoleIncompleteError, match="report"):
        await silent.step(role)

    assert _entries(tmp_path, "review") == [], "a step with no result recorded one anyway"

    with pytest.raises(RoleIncompleteError):
        await silent.step(role)

    assert len(record.runs) == 2, "the second attempt replayed a step that had recorded nothing"

    # And the address the two failures would have used is still free: a walk whose agent does
    # report lands its entry there, which is what "claimed no slot" means from outside.
    reporting = _run(repository, tmp_path, base, _agent(record))
    assert await reporting.step(role) == Summary("review #0")
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
        await run.step(_role("review", "review", read_only=True))

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

    await run.step(_role("implement", "implement T-01"), commit="implement T-01")

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

    assert await run.step(_role("review", "review", read_only=True)) == Summary("review #0")

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
    role = _role("implement", "implement T-01")

    first = _run(repository, tmp_path, base, _agent(record, writes=written))
    await first.step(role, commit="implement T-01")

    second = _run(repository, tmp_path, base, _agent(record, writes=written))
    await second.step(role, commit="implement T-01: add the oauth callback route")

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
        await run.step(_role("review", "review", read_only=True))

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
        await run.step(_role("implement", "implement T-01"), commit="implement T-01")

    workspace = await _checkout(repository, tmp_path, base)
    committed = _git(workspace.path, "rev-parse", "HEAD").strip()
    assert committed != base
    assert FEATURE in _tree(repository, committed)
    assert _entries(tmp_path, "implement") == []

    # And the retry restores past it, which is what makes the commit above harmless rather than a
    # half-done step nobody can see: `last_good` is chained from entries, and there are none.
    reporting = _run(repository, tmp_path, base, _agent(record))
    await reporting.step(_role("implement", "implement T-01"), commit="implement T-01")
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

    step = asyncio.create_task(run.step(_role("review", "review", read_only=True)))
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
        run.step(_role("implement", "implement T-01"), commit="implement T-01")
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

    assert await run.step(_role("review", "review", read_only=True)) == Summary("review #0")

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

    assert await run.step(_role("review", "review", read_only=True)) == Summary("on reflection")
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

    await run.step(_effect("implement", "implement T-01"), commit="implement T-01")

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

    assert await run.step(_deciding(on_question=_answers)) == Summary("decide #0")
    assert [question.prompt for question in record.asked] == ["Land it, or keep going?"]
    assert record.results[0].text == "land it", "the answer did not reach the agent that asked"


# --- what the agent is actually asked -------------------------------------------------------------
#
# §3.3 settles the mechanism and it is not templating: "the framework appends one structured block
# of canonical JSON under a fixed heading, and the author writes the prompt knowing inputs arrive at
# the end". The five tests below are written against the five ways that goes wrong, and only the
# first of them is the obvious one:
#
#   * *The block never arrives.* Stage 12's actual behaviour and the whole of 13.0(i): §3.3's own
#     `w.step(triage, findings=highs)` fingerprints the findings correctly, pays for an
#     agent, and hands it a prompt with no findings in it. Nothing raises, the step records a
#     result, and what the run produced is a triage of nothing.
#   * *Something interpolates.* `_TEMPLATED` is a prompt carrying `{`, `}`, `{name}`, a JSON Schema
#     and a `%s`, which is what these prompts really look like, and it is asserted to survive
#     **byte-identical** in front of the block. `str.format` raises `KeyError` on it and `%` raises
#     `TypeError` on it, so either of those two implementations is a red test rather than a subtly
#     different prompt. The quiet third one - a `str.replace` or a regex over `{name}` - is what the
#     byte-identity is really for, because nothing about it would raise.
#   * *A step with no inputs is given a block anyway*: a heading over an empty object, or merely a
#     trailing newline nobody would ever see. Asserted as equality against the role's instructions.
#   * *The block is not canonical.* Two calls writing the same inputs in a different keyword order
#     must compose the same text, which is `sort_keys` seen from outside the journal - and must
#     replay, which is what the same inputs have to mean to a resume.
#   * *A dataclass arrives as something other than its fields.* §3.3 passes `findings=highs`, so
#     this is the shape the plan's own example needs and not an exotic one.
#
# **The expected text is spelled out here rather than imported.** A suite that called
# `canonical_json` to check what `canonical_json` produced would agree with it whatever either of
# them said, and the same goes twice over for the heading: it is fixed by §3.3, an author writes
# the closing paragraph of a prompt against it, and no fingerprint contains it - so respelling it is
# a change to every prompt in AGL that nothing else in this repository can see.


# The heading §3.3 fixes, with the blank lines that separate it from the prompt above and the block
# below - the whole of what the framework inserts between an author's text and their step's inputs.
_HEADING: Final = "\n\n## Inputs\n\n"

# A prompt written the way these prompts really are: a payload schema, a placeholder that is not
# one, and two percent signs. `_TEMPLATED.format(**inputs)` raises `KeyError: '"type"'` and
# `_TEMPLATED % inputs` raises `TypeError` at `100% of` - measured, not assumed - so neither
# templating implementation passes this quietly, and neither survives the byte-identical prefix.
_TEMPLATED: Final = (
    'Report through the tool below. Its payload schema is {"type": "object", "properties": '
    '{"text": {"type": "string"}}}, and `{name}` is what a finding calls the ticket it belongs '
    "to. Keep 100% of the diff and write %s wherever you skipped something."
)


@dataclass(frozen=True)
class Finding:
    """§3.3's `findings=highs`: a list of the workflow's own dataclasses, passed as one input."""

    ticket: str
    severity: int


@pytest.mark.asyncio
async def test_the_inputs_a_step_passes_are_appended_to_what_the_agent_is_asked(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """13.0(i): `**inputs` are fingerprint terms **and** they reach the agent (§3.3).

    Asserted as the whole dispatched string rather than as `"T-01" in asked`, because everything
    §3.3 fixes about the block is in the parts a containment check cannot see: that the role's own
    text comes first, that one fixed heading separates the two, that the keys are sorted, and that
    the separators are the compact ones the fingerprint was taken with.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_role("triage", "triage the findings", read_only=True), ticket="T-01", high=3)

    assert record.runs == ["triage the findings" + _HEADING + '{"high":3,"ticket":"T-01"}'], (
        "the step's inputs were fingerprinted and never shown to the agent, which is §3.3's own "
        "tickets example paying for a triage of findings it was never handed"
    )


@pytest.mark.asyncio
async def test_a_prompt_carrying_braces_and_percent_signs_reaches_the_agent_byte_identical(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3's reason for rejecting templating, written as the assertion that catches it.

    Two assertions where one would do, because they fail differently and both are worth reading. The
    prefix says the author's text was not touched - which is the claim - and the equality says what
    was added is the block and only the block. A role that carries a JSON Schema is not a contrived
    case: `roles.py` puts the prompt text in `instructions`, and a reporting role's prompt is
    usually explaining a schema.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_role("triage", _TEMPLATED, read_only=True), ticket="T-01")

    (asked,) = record.runs
    assert asked.startswith(_TEMPLATED), (
        "the role's own instructions were rewritten on the way to the agent. Nothing may "
        "interpolate here: these prompts carry JSON Schemas, and a `{name}` in one is literal text"
    )
    assert asked == _TEMPLATED + _HEADING + '{"ticket":"T-01"}'


@pytest.mark.asyncio
async def test_a_step_with_no_inputs_is_dispatched_the_roles_instructions_and_nothing_else(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3's block is appended when there is one, and "nothing at all" when there is not.

    Equality and not `startswith`, because every wrong version of this passes `startswith`: a
    heading over an empty object, a blank line, one trailing newline. This is the shape most
    dispatches in AGL have - every reviewer reviews the worktree and takes no inputs at all - so a
    stray character here is in almost every prompt, changes no fingerprint, and re-runs nothing.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_role("review", "review the diff", read_only=True))

    assert record.runs == ["review the diff"]


@pytest.mark.asyncio
async def test_the_same_inputs_in_a_different_keyword_order_compose_and_replay_the_same(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """Canonical JSON sorts keys, so the block is a function of the inputs and not of the call.

    The replay is the half that costs money when it is wrong, and it is also this file's answer to
    "did the fingerprint move": the entry is written by the first walk and found by the second,
    which is only true if `journal.step` is still being handed `role.instructions` and `inputs` as
    the two separate terms §3.6 records. A composed prompt hashed in place of them would re-run
    every step ever recorded, and this is the cheapest place that shows.
    """
    record = _Agent()
    role = _role("triage", "triage the findings", read_only=True)

    first = _run(repository, tmp_path, base, _agent(record))
    await first.step(role, ticket="T-01", high=3)

    second = _run(repository, tmp_path, base, _agent(record))
    await second.step(role, high=3, ticket="T-01")

    assert len(record.runs) == 1, "reordering two keyword arguments re-ran the agent"
    assert record.runs[0].endswith('{"high":3,"ticket":"T-01"}'), (
        "the block is written in the order the call wrote its keywords, so two calls carrying the "
        "same inputs hand two different prompts to two agents - and the digest they share, which "
        "is taken over sorted keys, says the two are one step and replays the first one's result"
    )
    assert len(_entries(tmp_path, "triage")) == 1


@pytest.mark.asyncio
async def test_a_dataclass_input_reaches_the_agent_as_its_fields_and_its_type(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3's own `findings=highs`, which is a list of the workflow's own dataclasses.

    The `__agl_type__` tag is asserted rather than tolerated. §3.6 rule 6 puts a dataclass's
    qualified name in the fingerprint at every depth, and this block is the same canonical text the
    digest was taken over - so the tag is in front of the agent by construction, and the only way it
    would not be is a second serialiser, free to disagree with the first about what these inputs
    were. It reads as information rather than noise: it is the type the workflow named.

    `Finding.__module__` rather than the literal `"test_run_step"`, because that string is pytest's
    import mode talking and not this file's claim.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    typed = '{"__agl_type__":"' + Finding.__module__ + '.Finding",'

    await run.step(
        _role("triage", "triage the findings", read_only=True),
        findings=[Finding("T-01", 3), Finding("T-07", 5)],
    )

    block = (
        '{"findings":['
        + typed
        + '"severity":3,"ticket":"T-01"},'
        + typed
        + '"severity":5,"ticket":"T-07"}]}'
    )
    assert record.runs == ["triage the findings" + _HEADING + block], (
        "the findings §3.3 hands to `triage` did not reach the agent asked to triage them, or they "
        "reached it as something other than the canonical text their fingerprint was taken over"
    )


# --- a prompt that came out of a file ------------------------------------------------------------
#
# §3.7: "**`instructions` is prompt text, never a path.** A role holding a filename would
# fingerprint the filename, so editing the prompt would move nothing and a resume would replay what
# the old wording produced - as a cache hit, with nothing to notice. `prompt_file()` reads at
# declaration time and is the sanctioned spelling."
#
# `tests/sdk/test_roles.py` pins what `prompt_file` returns and what it refuses. These two are the
# claim that sentence is really about, and neither can be made there: a `prompt_file` that answered
# with the path it was handed would satisfy every type in the codebase, and the only place it shows
# is in front of an agent - or, worse, in a digest that did not move.


@pytest.mark.asyncio
async def test_a_role_declared_with_prompt_file_asks_the_agent_what_the_file_says(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The whole of §3.7's promise, measured at the far end: what the agent was asked **is** the
    file's text.

    Equality against the file's own contents rather than a containment check, because the two
    implementations worth catching both pass a containment check on something: a role holding the
    path would hand the agent a path, and a role holding a stripped or reflowed copy would hand it
    a prompt the author did not write and a digest nobody could reproduce by reading the file.
    """
    record = _Agent()
    prompt = tmp_path / "prompts" / "review.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Review the worktree against the spec.\n\nReport what you found.\n")
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_role("review", prompt_file(prompt), read_only=True))

    assert record.runs == [prompt.read_text(encoding="utf-8")], (
        "the agent was not asked what the prompt file says. A role that carried the filename would "
        "look exactly like this from every other angle - it would type-check, it would "
        "fingerprint, and the run would finish"
    )


@pytest.mark.asyncio
async def test_editing_the_prompt_file_re_runs_the_step_and_the_agent_reads_the_new_wording(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.7's named failure, shown closed - and the control beside it, because "it re-ran" is only
    a claim if the unedited case replays.

    Three walks over one ledger. The first records an entry; the second re-declares the role from
    the *unchanged* file and replays it, paying for no agent; the third re-declares it after an edit
    and pays for one, which is what a role holding the filename could not do - the filename would be
    identical across all three, the digest would still match, and the resume would hand back what
    the old wording produced with nothing anywhere to notice.

    The last assertion is the half that says the re-run was for the right reason: the agent was
    asked the *new* text, not merely asked again.
    """
    record = _Agent()
    prompt = tmp_path / "prompts" / "review.md"
    prompt.parent.mkdir(parents=True)
    first_wording = "Review the worktree against the spec.\n"
    prompt.write_text(first_wording, encoding="utf-8")

    first = _run(repository, tmp_path, base, _agent(record))
    await first.step(_role("review", prompt_file(prompt), read_only=True))

    unedited = _run(repository, tmp_path, base, _agent(record))
    await unedited.step(_role("review", prompt_file(prompt), read_only=True))
    assert len(record.runs) == 1, "the control: re-reading an unchanged prompt file must replay"

    edited_wording = "Review the worktree against the spec, and check the tests too.\n"
    prompt.write_text(edited_wording, encoding="utf-8")
    edited = _run(repository, tmp_path, base, _agent(record))
    await edited.step(_role("review", prompt_file(prompt), read_only=True))

    assert record.runs == [first_wording, edited_wording], (
        "editing the prompt file moved nothing, so the resume replayed what the old wording "
        "produced - §3.6's own reason for putting the role in the digest, arriving as a cache hit"
    )
    assert len(_entries(tmp_path, "review")) == 2


# --- a reporting tool's payload type is a term too ------------------------------------------------


@pytest.mark.asyncio
async def test_a_step_reporting_through_another_payload_type_does_not_replay_the_first(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.6 rule 6's second half, at the surface where it costs something.

    Two roles identical in every term a fingerprint takes but one: the reporting tool's payload
    *type*. Same instructions, same model, same restrictions, same tool name and description, and a
    payload dataclass of exactly the same shape under a different name. Before 13.0 the two derived
    a byte-identical schema, so the second walk found the first's entry and replayed it **into the
    new type** - nothing raised, nothing failed to parse, and the workflow read a `Restatement` that
    was recorded as a `Summary`.

    The control comes first for the reason it always does: a run where everything re-runs would pass
    the second half of this and mean nothing by it.
    """
    record = _Agent()
    review = _role("review", "review", read_only=True)
    restated = _restating()

    first = _run(repository, tmp_path, base, _agent(record))
    assert await first.step(review) == Summary("review #0")

    unchanged = _run(repository, tmp_path, base, _agent(record))
    assert await unchanged.step(review) == Summary("review #0")
    assert len(record.runs) == 1, "the control: the same role twice is one agent run"

    swapped = _run(repository, tmp_path, base, _agent(record))
    assert await swapped.step(restated) == Restatement("review #0")

    assert len(record.runs) == 2, (
        "the step replayed an entry recorded for another payload type. The workflow asked for a "
        "`Restatement` and was handed what an agent reported as a `Summary`, off the ledger, "
        "without an agent being asked and without anything failing to parse"
    )
    assert len(_entries(tmp_path, "review")) == 2


# --- two roles whose names differ only in case ----------------------------------------------------


def _numbered(record: _Agent) -> Script:
    """An agent whose answer says which dispatch it was, so two results cannot look alike.

    `_agent` builds its payload out of the instructions, which is exactly what two roles alike in
    every fingerprint term have in common - so a replay and a re-run would report the same string
    and the test below could only count dispatches. This one counts them into the payload, which
    puts the false cache hit in the *value* a workflow reads rather than only in a recorder.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        record.runs.append(conversation.task.instructions)
        payload = {"text": f"dispatch {len(record.runs)}"}
        record.results.append(await conversation.call(REPORT.name, payload))
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script


def _recorded(tmp_path: Path, *steps: str) -> set[str]:
    """Every entry filename under these step directories, deduplicated - the honest entry count.

    A set of names rather than a sum of lengths, because the two directories this is asked about
    are **one** directory on a case-insensitive volume and two on a case-sensitive one: adding the
    globs up double-counts every file on macOS, and globbing only one of them misses the other's on
    Linux. An entry is named for its digest, so the names are unique across the pair either way and
    the size of the set is the number of entries however the volume spells the directories.
    """
    home = AglHome(tmp_path / "home")
    return {
        path.name for step in steps for path in step_dir(home, SCOPE, StepName(step)).glob("*.json")
    }


@pytest.mark.asyncio
async def test_two_roles_differing_only_in_case_do_not_replay_each_others_entries(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """UF1.6, and the sharpest failure in this file: a **false cache hit**.

    `StepName` allows `[A-Za-z0-9._-]`, so `Role(name="Review")` is a legal declaration, and since
    UF1.1 a step's address is its role's name. Two roles differing only in case, in one namespace,
    alike in every term `base_of` takes - same instructions, same model, same restrictions, same
    tools, no inputs, and run back to back over a tree neither commits to, so the same head - are
    one `base` by construction, because `base_of` has no name parameter to tell them apart.

    What separated them was the counter's key and the directory. Keyed on the raw `StepName`, both
    sat at `n = 0` and hashed to one digest; and `steps/Review/` and `steps/review/` are **one
    directory** on a case-insensitive volume, which is macOS by default. So the second step read the
    first step's file, matched the fingerprint it found there, and handed back a value no agent
    produced for it - no re-run, no exception, and the wrong answer. Every other silent failure in
    §3.6 costs money; this one costs correctness.

    The repair is `Fingerprints`' folded counter key, not a folded path segment: the author's
    spelling reaches disk verbatim (`tests/ports/test_home_layout.py`) and the second spelling
    lands at `n = 1`, which is right on a case-sensitive volume too, where the entries are two
    files in two directories and the counter is the only thing that made them two digests.

    The assertions are in the order they lose their meaning: the value, which is what a workflow
    actually reads; the dispatch count, which is what a replay is; and the ledger, which is what a
    resume will walk.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _numbered(record))

    capitalised = await run.step(_role("Review", "review", read_only=True))
    lowercase = await run.step(_role("review", "review", read_only=True))

    assert capitalised == Summary("dispatch 1")
    assert lowercase == Summary("dispatch 2"), (
        "the second role was handed the first one's recorded value. Two roles that differ only in "
        "case shared one address, so `review` replayed what `Review` reported - a result no agent "
        "produced for it, off the ledger, with nothing raised and nothing re-run"
    )
    assert len(record.runs) == 2, "one of the two steps was never dispatched to an agent"
    assert len(_recorded(tmp_path, "Review", "review")) == 2


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

    assert await run.step(_role("review", "review", read_only=True)) == Summary("done")

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
        await dying.step(_role("review", "review", read_only=True))

    assert dying.activity is None, (
        "an agent that died mid-`Bash` left `Bash` on the board. The cell is cleared on every exit "
        "from the dispatch and not only on the one that returned"
    )

    # And now a walk that records something, followed by one that replays it.
    fresh = _run(repository, tmp_path, base, _agent(record))
    assert await fresh.step(_role("review", "review", read_only=True)) == Summary("review #0")

    async def _shouts(conversation: Conversation) -> AgentOutcome:
        record.runs.append(conversation.task.instructions)
        conversation.report("Read: connectors/api/backend.ts")
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    replaying = _run(repository, tmp_path, base, _shouts)
    assert await replaying.step(_role("review", "review", read_only=True)) == Summary("review #0")

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
    role = _role("review", "review", read_only=True)

    both = await asyncio.gather(run.step(role), run.step(role))

    assert list(both) == [Summary("review #0"), Summary("review #0")]
    assert len(record.runs) == 2
    assert len(_entries(tmp_path, "review")) == 2, (
        "two steps in one namespace wrote one entry between them: they overlapped, so both took "
        "the same address and the second clobbered the first"
    )


# --- what a step refuses before it provisions anything -------------------------------------------


def test_a_step_name_that_could_not_be_a_path_segment_is_refused_at_the_declaration() -> None:
    """§3.3: names are opaque strings, "validated on the way in" - filesystem- and ref-safe.

    Since UF1.1 the name is the role's, so this is where "on the way in" now is: at the line that
    declared it, before a run exists at all. `tests/sdk/test_roles.py` holds the rest of the
    refusal's shape; what is here is the half that belongs beside the step - that no `run.step`
    could ever be reached with one.
    """
    with pytest.raises(InputError, match="step name"):
        _role("../escape", "review", read_only=True)


@pytest.mark.asyncio
async def test_the_step_refuses_the_same_name_again_before_it_provisions_anything(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The engine's own `StepName(role.name)`, which is above the journal lookup deliberately: a
    run that cannot record a step should not pay for one, and should not cut a checkout for it
    either.

    **The role below did not come from `Role(...)`**, and it cannot: the declaration refuses this
    name, which is the test above. So the only way to reach the engine's check is to build the
    value the way nothing in AGL builds one - past `__post_init__`, field by field - and that is
    what this does. It is not a shape a workflow can write, and the point of measuring it is that
    the two checks are the duplication `sdk/roles.py` argues for by name (`AgentTask`'s refusals,
    re-made one layer earlier): each has to hold on its own, or the outer one is the only one and
    the inner one is decoration.

    The field is `_model` because since UF1.2 nothing but `@role(model=…)` writes a role's model -
    `Role.model` is the property that reads it and refuses when nothing has. This loop is writing
    what a factory would have written, which is the same statement one field down.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    undeclared: Role[Summary] = Role.__new__(Role)
    for field, value in {
        "name": "../escape",
        "instructions": "review",
        "_model": Claude.SONNET,
        "restrictions": frozenset({Restriction.NO_VCS_WRITES}),
        "tools": (REPORT,),
        "requires": frozenset(),
        "on_question": None,
    }.items():
        object.__setattr__(undeclared, field, value)

    with pytest.raises(InputError, match="step name"):
        await run.step(undeclared)

    assert record.runs == []
    assert not (tmp_path / "trees").exists(), "a refused step name provisioned a checkout anyway"
