"""What `run.step` promises: one agent run per step, and a checkout that ends where it was told to.

The suite over `sdk/_engine/steps.py` and over the half of `sdk/workflow.py` that reaches it.
`test_journal_walk.py` holds the replay loop against a hand-written worker; this file holds the
thing that *builds* that worker - a `Role` becoming an `AgentTask`, a reporting declaration becoming
a `Tool` with a capture cell behind it, and `commit=` deciding what happens to the worktree.

**The repository is real git, and that is the point rather than an expense.** The git fakes keep
their commits in memory, so "the recorded head is a commit whose tree holds the agent's file" would
be an assertion about a dict, and "the untracked file is gone" would be an assertion about a
directory nothing had ever asked git about. Everything below that names a commit, a tree, a status
or an untracked file is asked of `git` itself, in a repository with no configuration from the
machine it runs on. The ledger is a real `FilesystemStore` for the same reason in miniature:
"nothing under `steps/<name>/`" is a directory listing here, not a digest recomputed by the test
from the arithmetic it is checking.

Eight of these are worth naming, because each is written against a failure that is silent:

  * **The entry's `head` is recorded after the commit.** "A `run.commit()` after the step
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
  * **What the agent is asked is the role's own text with this step's inputs substituted into
    it, and not one character the framework added around them.** A placeholder is the only route
    an input has to the agent, so what is left to fail in silence is a template engine quietly
    rewriting a prompt that carries a JSON Schema. The section near the bottom asserts the whole
    dispatched string and not a substring of it.
  * **A `{{TypeName}}` placeholder says where in that text an input goes, and a value that spells
    one is never expanded.** The substitution is a single pass that resumes in the *original*
    string, so an input whose own field reads `{{Decisions}}` is written out and read back by
    nothing - which is what a `str.replace` per name would not promise, and which fails as a
    prompt carrying an instruction the workflow never wrote. A declared type this step did not
    pass renders `Not provided` and nothing besides: what a missing input means is a sentence the
    prompt's author writes, and a framework wording it here would be arguing with theirs.
  * **The address that step records at is taken over that same string.** Composition reaches a
    digest through the `prompt` term of `base_of` and through nothing else, so a rewrite of it
    re-runs what it changed. Without that term the rewrite is the quietest failure in this file:
    every recorded entry keeps its address, every step replays, and the document each address
    stands for is one nobody was ever asked.

`run.activity` is here too, at the end, because this file already holds the only thing that
dispatches to an adapter. There is little to it by design - the framework holds the last string
it was handed and hands it back - so what the tests are written against is the two ways it
could be wrong that nobody would see - a line surviving the step that produced it, and a step
replayed from cache producing one at all.
"""

import asyncio
import hashlib
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
    Restriction,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome, RunScope, step_dir
from agl.ports.ids import ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import base_of
from agl.sdk.roles import Role, RoleIncompleteError, prompt_file, role
from agl.sdk.tools import reporting_tool, tool
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
    `test_journal.py`'s qualified type name adds. A reporting tool declared over it carries
    `REPORT`'s own name and description too, which leaves the payload *type* as the only
    difference between two otherwise identical roles - and so as the only thing that can move the
    fingerprint.
    """

    text: str

RESTATE: Final = reporting_tool(REPORT.name, "report what you did", Restatement)

@dataclass(frozen=True)
class _Asking:
    """The payload of a role's own asking tool. One field, which is the whole of a question here."""

    question: str

_ASK: Final = "ask_the_operator"
"""What a workflow calls its asking tool. Nothing in AGL knows the name, which is the point: the
framework supplies no asking tool of its own, so this is a string this file chose."""

@dataclass(frozen=True)
class Ticket:
    """One of `_role`'s declared input types, and the name a value of it is recorded under."""

    name: str

@dataclass(frozen=True)
class Highs:
    """A second declared type, so a step can carry two inputs and the order they are written in
    can differ between two calls that mean the same thing."""

    count: int

@dataclass(frozen=True)
class Urgent(Ticket):
    """A `Ticket` a role that declared only `Ticket` still takes, since the match is `isinstance`.

    No field of its own, deliberately: what separates it from its base in a fingerprint is then
    the qualified type name `journal.py` tags the value with and nothing else, which is the half
    that has to hold for a subclass and its base to be two steps under one key.
    """

@dataclass(frozen=True)
class Both(Ticket, Highs):
    """A value two unrelated declarations of `_role` both take, which is the ambiguity refusal.

    Multiple inheritance is not an exotic way to reach that state - it is the only one a plain
    class hierarchy offers, and a workflow whose `Request` is also a `Note` has written it without
    meaning to. Neither `Ticket` nor `Highs` is below the other, so there is no narrowest match.
    """

@dataclass(frozen=True)
class Finding:
    """A workflow's own dataclass, nested inside a declared type rather than passed as one."""

    ticket: str
    severity: int

@dataclass(frozen=True)
class Findings:
    """The tickets example's `highs` as a type a role can declare: the list is a field of one.

    A step passes instances of the types its role accepts, so a bare `list` is not an input any
    more - it is what one of them holds, which is also what puts a second dataclass a level down.
    """

    items: list[Finding]

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

    **`history` is real because a step reaches it.** `Steps._namespace` resolves its base
    through `History.resolve` and hands the one resolved value to both the checkout and the
    `Journal`, so that the cut and the chain cannot disagree about where a namespace began; a
    `FakeHistory` here answers about a `FakeRepository` that has never heard of this repository's
    commits, and would refuse the run's own pinned base. Real git is asked about real git.

    Called twice with the same arguments it is a resume: the same ledger on disk, the same worktree
    reopened, and a fresh counter, which is what "`n` is never persisted" means.
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

    `name` is what its entries are recorded under, since `run.step` carries none of its own -
    so a test that wants two addresses declares two roles, and one that wants two calls at
    one address hands this same object over twice.

    `read_only` declares `NO_VCS_WRITES`, which is what an author pairs with a step
    that passes no `commit=`. Nothing checks the pairing - the framework does one predictable thing
    either way - so it is here because these tests should read the way a workflow does.

    It accepts nothing, and that is what lets one factory carry a prompt written afresh at every
    call site: `RoleFactory.__call__` requires a declaration's `accepts=` and its prompt's
    placeholders to be the same set, so a factory declaring a type would demand that every prompt
    written through it name that type. The four below are the input-carrying shapes, one per set of
    accepted types, and each is spelled the way a workflow spells one - a role, its prompt, and the
    types that prompt names.
    """
    restrictions = {Restriction.NO_VCS_WRITES} if read_only else set[Restriction]()
    return Role(
        name=name,
        instructions=instructions,
        restrictions=restrictions,
        tools=(REPORT,),
    )

def _triage(instructions: str) -> Role[Summary]:
    """The `Role` the four factories below return, so the one thing that differs between them is
    the `accepts=` on their decorator - which is the half a prompt has to agree with."""
    return Role(
        name="triage",
        instructions=instructions,
        restrictions={Restriction.NO_VCS_WRITES},
        tools=(REPORT,),
    )

@role(model=Claude.SONNET, accepts=(Ticket,))
def _one_ticket(instructions: str) -> Role[Summary]:
    """A role taking the base type alone, which is where a subclass of it is recorded too."""
    return _triage(instructions)

@role(model=Claude.SONNET, accepts=(Ticket, Highs))
def _ticket_and_highs(instructions: str) -> Role[Summary]:
    """Two unrelated declarations, so a step can carry two inputs and a `Both` can tie between
    them - neither being below the other is what leaves an ambiguous value with no name."""
    return _triage(instructions)

@role(model=Claude.SONNET, accepts=(Findings,))
def _findings_only(instructions: str) -> Role[Summary]:
    """One declared type whose own field is a list of the workflow's own dataclasses."""
    return _triage(instructions)

@role(model=Claude.SONNET, accepts=(Ticket, Urgent))
def _either_ticket(instructions: str) -> Role[Summary]:
    """A role declaring a type and a subclass of it, so one `Urgent` matches two declarations.

    `_one_ticket` declares the base alone, which is the other half of the same rule: there the
    subclass is recorded under `Ticket`, and here under `Urgent`, because the name is the declared
    type's and the narrowest declaration that matched is the one that supplies it.
    """
    return _triage(instructions)

@role(model=Claude.SONNET)
def _effect(name: str, instructions: str) -> Role[None]:
    """A role with no reporting tool: its result is `null` and its effect is commits."""
    return Role(name=name, instructions=instructions)

@role(model=Claude.SONNET)
def _promising() -> Role[Summary]:
    """A role annotated `Role[Summary]` that declares no reporting tool - and therefore lies.

    `Role[P]` solves `P` from `tools=`, and an omitted `tools=` solves it from the return
    annotation instead, so this declaration is clean under `mypy --strict` and there is nothing at
    the declaration to object to. What it promises is a `Summary`; what `run.step` can hand back is
    `null`. The section near the bottom of this file is where that is measured and argued.
    """
    return Role(name="audit", instructions="audit the worktree")

@role(model=Claude.SONNET)
def _deciding(*, ask: Tool | None = None) -> Role[Summary]:
    """A reporting role that negotiates: the asking tool's handler is a closure over a `Run`, so it
    can only reach a role as the one argument this factory takes.

    `Role[Summary]` is written out because the display is mixed - a list holding a `ReportingTool`
    and a plain `Tool` does not solve for `P`, which `tests/sdk/test_roles.py` pins in both
    directions and calls the explicit parameter the sanctioned fallback for."""
    return Role[Summary](
        name="decide", instructions="decide", tools=[REPORT] if ask is None else [REPORT, ask]
    )

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
        """Every answer the reporting tool gave, refusals included - the rejection path is a
        `ToolResult` going back to the model, so this is where it is visible from."""

        self.asked: list[str] = []
        """Every question the script put to the role's own asking tool, in the order it asked."""

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
            record.results.append(await conversation.call(_ASK, {"question": asks}))
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
    """The whole promise, at the surface a workflow actually writes.

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
    """A workflow of three sequential steps - the `fix` shape, with a report on every one."""
    spec = await run.step(_role("spec", "write the spec", read_only=True))
    # The typing promise, checked by `mypy --strict` over `tests/` rather than hoped for: the
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
    """"If the agent returns without firing it, there is no result and the step re-runs".

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
    """The ordering a paragraph is spent on: the entry's `head` is read **after** the commit.

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
    """The wipe: "not a scratch file, not a cache directory, not a partial edit".

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
    """The message is kept out of the fingerprint: it is cosmetic, so rewording it must not
    re-run an agent. The trade comes with it - the replayed step keeps the commit it already
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
    """"The wipe runs whether the step succeeded or raised".

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

    "No check of what the role declared, and no comparison of HEAD before and after" - one
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

    It reports an activity line on its way in, so that the cell that is `None` when nothing is
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
    """The wipe survives a cancellation, which is the one path a bare `finally` does not cover.

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
    """The other ending, through the same door: "one predictable thing either way".

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
    """Undecided in advance and settled by the engine: first-wins, refusal going back in-session.

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
    """"Rejected by the tool back to the agent within the same conversation, so the model
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
    """The other step kind: no reporting tool, so the result is `null` and the effect is commits.

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

# --- a known hole: a role may promise a payload and declare nothing that can produce one ----------
#
# **This is open, and the test below exists so that the next person meets the argument rather than
# the surprise.** It is not a bug in the step: `steps.py` does the only thing it can, and the
# declaration it is serving is the thing that was wrong.
#
# `Role[P]` carries its reporting tool as one member of `tools: Sequence[Tool | ReportingTool[P]]`,
# so `P` is solved from whatever `tools=` holds - and when it holds nothing, from the annotation on
# the factory instead. `Role[Summary]` with no tools is therefore a legal, `mypy --strict`-clean
# declaration of a role that cannot report. `Steps.step` finds no `ReportingTool` in it, builds no
# capture cell, and ends at `return cast(R, None)`: the workflow is handed `None` with mypy still
# holding that it is a `Summary`, and the ledger records `null`, which is the truth.
#
# Closing it means `Role` carrying its reporting tool as its own member rather than as a union
# element - `reports: ReportingTool[P]`, required, so that `Missing named argument "reports"` is
# what an author gets - which was measured to work and to close the second-reporting-tool hole with
# it. It is a different deliverable: it moves a public field on `Role`, rewrites every role
# declaration in `src/`, `tests/` and any workflow anyone has written, and touches nothing this
# file's subject does. Until then the hole is here, in one test, with its name on it.

@pytest.mark.asyncio
async def test_a_role_promising_a_payload_with_no_reporting_tool_is_handed_none(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The hole, driven end to end rather than argued: real role, real step, real ledger.

    Both halves are here because either alone would read as something else. `assert_type` is the
    static half and it *passes* - that is the defect, not a check that this test is doing its job -
    and `mypy --strict` runs over `tests/`, so this line is a gate saying the hole is still open. A
    day when `Role` learns to refuse this declaration is a day this file fails to type-check, which
    is the notification being arranged.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record, reports=False))

    summary = await run.step(_promising(), commit="audit the worktree")

    assert_type(summary, Summary)
    assert _one(tmp_path, "audit")["value"] is None, "the ledger recorded something other than null"
    assert len(record.runs) == 1
    assert summary is None, (
        "the step handed back something other than `None`, so `steps.py` no longer ends a "
        "capture-less step at `return cast(R, None)` and this hole has moved rather than closed"
    )

# --- the role's own asking tool -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_roles_asking_tool_reaches_the_runner_and_its_answer_returns(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The answer returns into the same live session, so a negotiation is N rounds inside one
    step rather than N steps.

    A question is an ordinary tool the workflow supplies: `Role.tools` folds
    `Capability.TOOL_CALLING` into `requires` at declaration time, the engine hands `AgentTask` the
    whole tuple, and what comes back out of the handler is what the agent reads. A `step` that
    dropped a role's non-reporting tools would leave preflight insisting on a capability nothing
    used, and the workflow's approval gate simply absent - the agent approving itself, with nothing
    raised and nothing logged as wrong.

    This is the one round; `tests/sdk/test_agent_questions.py` is the whole negotiation, with a
    person at the end of it.
    """
    record = _Agent()

    async def _answers(asked: _Asking) -> ToolResult:
        record.asked.append(asked.question)
        return ToolResult(text="land it")

    run = _run(repository, tmp_path, base, _agent(record, asks="Land it, or keep going?"))
    asking = tool(_ASK, "ask the person running this task", _Asking, _answers)

    assert await run.step(_deciding(ask=asking)) == Summary("decide #0")
    assert record.asked == ["Land it, or keep going?"]
    assert record.results[0].text == "land it", "the answer did not reach the agent that asked"

# --- what the agent is actually asked -------------------------------------------------------------
#
# The mechanism is one pass of a regex and it is not a template engine. A `{{TypeName}}`
# placeholder is filled from this step's inputs - the section after the next one takes that apart on
# its own - and the framework puts nothing of its own anywhere around the result. The four tests
# below are written against the four ways that goes wrong at the scale of a whole prompt:
#
#   * *Something interpolates.* `_TEMPLATED` is a prompt carrying `{`, `}`, `{name}`, a JSON Schema
#     and a `%s`, which is what these prompts really look like, and it is asserted to survive
#     **byte-identical** with a real placeholder filled beside it. `str.format` raises `KeyError` on
#     it and `%` raises `TypeError` on it, so either of those two implementations is a red test
#     rather than a subtly different prompt. The quiet third one - a `str.replace` or a regex over
#     `{name}` - is what the byte-identity is really for, because nothing about it would raise: a
#     single `{` opens nothing here, and `{{` cannot occur in the schema either.
#   * *A prompt comes back with something in it nobody wrote*: a heading, a blank line, one
#     trailing newline. Asserted as equality against the role's own instructions, and asserted for
#     a step with no inputs because that is the shape most dispatches in AGL have - every reviewer
#     reviews the worktree and takes none at all - so a stray character there is in almost every
#     prompt and re-runs every entry ever recorded.
#   * *The text is a function of the call rather than of this step's inputs.* Two calls writing the
#     same inputs in a different argument order must fill one prompt identically - the mapping is
#     read by name and never iterated, so the order they were written in has nowhere to go - and
#     must replay, which is what the same inputs have to mean to a resume.
#   * *A dataclass arrives as something other than its fields.* Every input is one, so the tag and
#     the fields are asserted where a list of them is nested a level down, which is the shape the
#     tickets example needs and not an exotic one.
#
# **The expected text is spelled out here rather than imported.** A suite that called
# `canonical_json` to check what `canonical_json` produced would agree with it whatever either of
# them said.

def _tagged(name: str) -> str:
    """The `__agl_type__` tag `journal.py` writes in front of a dataclass's own fields.

    The module half is read off `__name__` rather than spelled out, for the reason
    `test_a_dataclass_input_reaches_the_agent_as_its_fields_and_its_type` gives: that string is
    pytest's import mode talking and not this file's claim. The type name is spelled at every call.
    """
    return '{"__agl_type__":"' + __name__ + "." + name + '",'

# A prompt written the way these prompts really are: a payload schema, a placeholder that is not
# one, and two percent signs. `_TEMPLATED.format(**inputs)` raises `KeyError: '"type"'` and
# `_TEMPLATED % inputs` raises `TypeError` at `100% of` - measured, not assumed - so neither
# templating implementation passes this quietly, and neither survives the byte-identical prefix.
_TEMPLATED: Final = (
    'Report through the tool below. Its payload schema is {"type": "object", "properties": '
    '{"text": {"type": "string"}}}, and `{name}` is what a finding calls the ticket it belongs '
    "to. Keep 100% of the diff and write %s wherever you skipped something."
)

@pytest.mark.asyncio
async def test_a_schema_carrying_prompt_reaches_the_agent_untouched_beside_a_filled_placeholder(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The reason for rejecting templating, written as the assertion that catches it.

    Two assertions where one would do, because they fail differently and both are worth reading. The
    prefix says the author's text was not touched - which is the claim - and the equality says what
    changed is the placeholder and only the placeholder. A role that carries a JSON Schema is not a
    contrived case: `roles.py` puts the prompt text in `instructions`, and a reporting role's prompt
    is usually explaining a schema.

    An input is passed and a placeholder is written for it, so the substitution has work to do over
    this prompt. Were nothing passed instead, an implementation that interpolated only when it had a
    mapping to interpolate from would walk straight through the schema and the `%s` untested.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    written = _TEMPLATED + " Fix {{Ticket}} first."

    await run.step(_one_ticket(written), Ticket("T-01"))

    (asked,) = record.runs
    assert asked.startswith(_TEMPLATED), (
        "the role's own instructions were rewritten on the way to the agent. Nothing may "
        "interpolate here: these prompts carry JSON Schemas, and a `{name}` in one is literal text"
    )
    value = _tagged("Ticket") + '"name":"T-01"}'
    assert asked == _TEMPLATED + " Fix " + value + " first."

@pytest.mark.asyncio
async def test_a_step_with_no_inputs_is_dispatched_the_roles_instructions_and_nothing_else(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The substitution pass is the identity on a prompt with no placeholder in it.

    Equality and not `startswith`, because every wrong version of this passes `startswith`: a
    heading over an empty object, a blank line, one trailing newline. This is the shape most
    dispatches in AGL have - every reviewer reviews the worktree and takes no inputs at all - so a
    stray character here is in almost every prompt, and since the composed text is a fingerprint
    term it is also every recorded entry in existence missing its address and being paid for again.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_role("review", "review the diff", read_only=True))

    assert record.runs == ["review the diff"]

@pytest.mark.asyncio
async def test_the_same_inputs_written_in_a_different_order_compose_and_replay_the_same(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """Each input is keyed by its own type, so the text is a function of the inputs, not the call.

    Argument order is the one thing about these two calls that differs, and there is nowhere for it
    to go: the key is the type's name rather than the position, and the mapping those keys are in is
    read by name and never iterated, so where each value lands is decided by where the *author* put
    the placeholder. A matching that read positions instead would key these two calls differently
    and still pass a containment check.

    Asserted as the whole dispatched string, because everything fixed about it is in the parts a
    containment check cannot see: that the author's own words on either side survive, that both
    values arrive where they were asked for rather than one of them replacing the other, and that
    the separators are the compact ones the fingerprint was taken with.

    The replay is the half that costs money when it is wrong, and it is also this file's answer to
    "did the fingerprint move": the entry is written by the first walk and found by the second,
    which is only true if `journal.step` is still being handed `role.instructions` and `inputs` as
    the two separate terms the fingerprint records. A composed prompt hashed in their place would
    re-run every step ever recorded, and this is the cheapest place that shows.
    """
    record = _Agent()
    role = _ticket_and_highs("triage {{Ticket}}, {{Highs}} of them high")

    first = _run(repository, tmp_path, base, _agent(record))
    await first.step(role, Ticket("T-01"), Highs(3))

    second = _run(repository, tmp_path, base, _agent(record))
    await second.step(role, Highs(3), Ticket("T-01"))

    ticket = _tagged("Ticket") + '"name":"T-01"}'
    highs = _tagged("Highs") + '"count":3}'
    assert len(record.runs) == 1, "reordering two arguments re-ran the agent"
    assert record.runs == ["triage " + ticket + ", " + highs + " of them high"], (
        "the values landed somewhere other than the placeholders the author wrote for them, so a "
        "call that passes its inputs in one order and a call that passes them in another are two "
        "documents, two addresses and two agents paid for one step's work"
    )
    assert len(_entries(tmp_path, "triage")) == 1

@pytest.mark.asyncio
async def test_a_dataclass_input_reaches_the_agent_as_its_fields_and_its_type(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The standing `Findings(highs)`, whose one field is a list of the workflow's own dataclasses.

    The `__agl_type__` tag is asserted rather than tolerated, at both depths. `test_journal.py`'s
    qualified type name puts a dataclass's own in the fingerprint at every level, and what stands
    at the placeholder is the canonical text the digest was taken over - so the tag is in front of
    the agent by construction, and the only way it would not be is a second serialiser, free to
    disagree with the first about what these inputs were. It reads as information rather than
    noise: it is the type the workflow named.

    The nesting is the point rather than an elaboration: an input is an instance of a type the role
    declared, so the list a `triage` really wants is a field of one and never an input itself. The
    placeholder is `{{Findings}}` - the type's name, which is what a step's inputs are recorded
    under - and the module-qualified spelling stays inside the value, where the fingerprint needs
    it to tell two same-named types apart.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    typed = _tagged("Finding")

    await run.step(
        _findings_only("triage these:\n{{Findings}}"),
        Findings([Finding("T-01", 3), Finding("T-07", 5)]),
    )

    value = (
        _tagged("Findings")
        + '"items":['
        + typed
        + '"severity":3,"ticket":"T-01"},'
        + typed
        + '"severity":5,"ticket":"T-07"}]}'
    )
    assert record.runs == ["triage these:\n" + value], (
        "the findings handed to `triage` did not reach the agent asked to triage them, or they "
        "reached it as something other than the canonical text their fingerprint was taken over"
    )

# --- and the address it is recorded under ---------------------------------------------------------
#
# The four above are about the text. This one is about the digest, and it is the only thing that
# makes composing a prompt a *changeable* decision rather than a one-way door.
#
# `base_of` hashes `role.instructions` and the inputs the step was handed, so *how* the two
# become one document reaches no digest through either of them. Compose them some other way and
# every entry ever recorded keeps the address it already has while standing for a prompt nobody was
# ever asked: every step replays, none is run under the new composition, and there is no gate, no
# assertion and no diagnostic anywhere that says so. Which is why `prompt` is a term of its own -
# derived from two terms already there, so it separates no pair they do not and re-runs nothing by
# itself, and read for exactly one thing: a change to the composition moves every digest.
#
# Recomputed here rather than pinned as a number, because a pinned digest has to be retyped on the
# very edit it exists to fail. And fed `record.runs[0]` - the string the agent actually received -
# rather than a second call to `composed`, so a step that hashed one text and dispatched another
# fails here too, which no equality between two callers of one function could see.

async def _unhandled(payload: Mapping[str, JsonValue]) -> ToolResult:
    """`base_of` reads a tool's name, its description and its schema and never its handler, which
    `tests/sdk/test_journal.py` pins - so the address below needs a callable and not this one."""
    return ToolResult(text="")

_DISPATCHED: Final = Tool(
    name=REPORT.name,
    description=REPORT.description,
    payload_schema=REPORT.payload_schema,
    handler=_unhandled,
)
"""`REPORT` as `steps.py` converts it on the way to an `AgentTask`: the three declared terms, and a
handler bound at dispatch that the fingerprint does not read."""

@pytest.mark.asyncio
async def test_the_entry_a_step_records_is_addressed_by_the_prompt_the_agent_was_handed(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The composition is in the digest, which is what lets it be changed at all.

    One step, run for real against the real ledger, and then its address rebuilt from the outside:
    the role's own four terms, the inputs the call passed, the head the run was cut from, and the
    prompt read back off the agent that received it. `sha256(base + ":" + n)` is spelled out for
    `test_journal.py`'s reason - a suite that imported the arithmetic would agree with it whatever
    it said - and `n` is nought because this is the first call at this address.

    The role's text carries a placeholder because the composition is otherwise the identity: a
    prompt naming none of this step's inputs is dispatched exactly as it was declared, the address
    would match whether or not the composed text reached the digest, and the guard below says so
    rather than letting this pass for free.
    """
    record = _Agent()
    role = _ticket_and_highs("triage {{Ticket}}, {{Highs}} high")
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(role, Ticket("T-01"), Highs(3))

    (asked,) = record.runs
    assert asked != role.instructions, (
        "this step composed nothing onto its instructions, so the address below would match "
        "whether or not the composition reaches the digest and this test would measure nothing"
    )
    computed = base_of(
        instructions=role.instructions,
        model=role.model,
        restrictions=role.restrictions,
        tools=(_DISPATCHED,),
        inputs={"Ticket": Ticket("T-01"), "Highs": Highs(3)},
        prompt=asked,
        head=base,
    )
    assert _text(_one(tmp_path, "triage"), "fingerprint") == hashlib.sha256(
        f"{computed}:0".encode()
    ).hexdigest(), (
        "the entry this step wrote is not addressed by the text its agent was handed, so the "
        "composition has left the fingerprint - and the next change to it will replay every "
        "recorded step in existence against a prompt none of them was ever asked"
    )

# --- and where in the prompt an input goes --------------------------------------------------------
#
# `{{TypeName}}` is where the author says a value belongs, filled from the mapping this step's
# inputs were keyed into. Four things about it are decisions rather than details, and each one is a
# test below:
#
#   * **The grammar is exactly `{{`, a dotted Python name, `}}`, with no whitespace inside the
#     braces.** `{Ticket}` opens nothing, `{{Ticket}` closes nothing, and `{{ two words }}` is
#     prose - the name is compared against a `__qualname__`, which never has a space in it, so a
#     spelling that had to be trimmed first would be a second spelling of one placeholder with
#     nothing holding the two together. One spelling can be widened later without breaking a prompt
#     anybody wrote; two cannot be narrowed. `{{ Ticket }}` is the one near-miss that is not pinned
#     here: padded braces are what every templating engine spells a substitution as, so a prompt
#     carrying one is refused where it is declared rather than delivered as prose, and
#     `tests/sdk/test_roles.py` is where that refusal is measured.
#   * **A value that spells a placeholder is written out and never expanded.** One `re.sub`, which
#     resumes at the end of each match in the *original* string, so nothing the substitution wrote
#     is ever scanned. The test hands `Ticket` a field whose text is `{{Highs}}` and passes a real
#     `Highs` in the same call, so a second pass would have something to find and would find it.
#   * **A declared type this step did not pass renders `Not provided`.** Those two words, asserted
#     as the whole dispatched string, because every editorialising version of it - a parenthesis, a
#     full stop, "no value was supplied" - passes a containment check and argues with the sentence
#     the prompt's author wrote underneath.
#   * **The name is the declared type's and not the instance's.** An `Urgent` handed to a role that
#     accepts `Ticket` fills `{{Ticket}}`, and the same value handed to a role that accepts both
#     fills `{{Urgent}}` instead, because the narrowest declaration that matched is the one that
#     names it. Keyed off the instance, the author's own input would vanish from the prompt while
#     the ledger went on recording that inputs were supplied. The two refusals that rule needs -
#     no narrowest match, and two values landing under one name - are with the other input
#     refusals at the bottom of this file.

@pytest.mark.asyncio
async def test_a_placeholder_is_replaced_by_the_canonical_text_of_the_input_it_names(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """One value, in the middle of a sentence, spelled the way the fingerprint spells it.

    The substituted text is `canonical_json` of that one input and not a second rendering of it:
    the same serialiser, the same separators and the same `__agl_type__` tag the `inputs` term is
    hashed over, which is what keeps there from being two answers in this repository to "what was
    this value". A readable second spelling would be free to disagree with the first, and both of
    them are hashed now - the mapping through `inputs` and the substitution through `prompt`.

    Asserted as the whole string, for the reason the four tests above are: what is fixed about
    this is the parts a containment check cannot see - that the author's own words on either side
    survive untouched, and that the value arrives where they put it rather than at the end.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_one_ticket("Fix {{Ticket}} today."), Ticket("T-01"))

    value = _tagged("Ticket") + '"name":"T-01"}'
    assert record.runs == ["Fix " + value + " today."], (
        "the placeholder was not filled with this step's input, so the author put the value "
        "where they wanted it and the agent was handed the sentence with a gap in it"
    )

@pytest.mark.asyncio
async def test_a_declared_type_this_step_did_not_pass_renders_exactly_the_two_words(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """`accepts=` is a permission, so a placeholder with nothing behind it is a reachable state.

    What it renders is `Not provided` and nothing else, because the prompt's author is the one who
    knows what missing means - "if it is missing, work it out" and "if it is missing, stop" are
    both real endings, and a framework that explained the absence would be arguing with whichever
    one is written under it.

    Equality against the role's own text with the two words in it, which also says the second
    thing: the words stand exactly where the placeholder did, with no punctuation, no line and no
    apology of the framework's own around them.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_findings_only("The findings are:\n{{Findings}}"))

    assert record.runs == ["The findings are:\nNot provided"]

@pytest.mark.asyncio
async def test_an_input_whose_own_text_spells_a_placeholder_is_written_out_and_not_expanded(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The one pass, measured where a second pass would have something to find.

    `Ticket`'s field is the literal text `{{Highs}}` and a real `Highs` is passed in the same call,
    so an implementation that replaced one name at a time - `str.replace` in a loop is the obvious
    one - would fill the ticket first and then expand what it had just written. What reaches the
    agent would carry a value the workflow put nowhere, at a spot in the prompt the author marked
    for something else, and nothing about it raises: the step runs, records and replays.

    `re.sub` resumes at the end of each match in the string it was handed, so what a replacement
    writes is never part of what is scanned. That is the whole of the guarantee, and it holds by
    construction rather than by an escape or a check.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(
        _ticket_and_highs("ticket {{Ticket}}, count {{Highs}}"),
        Ticket("{{Highs}}"),
        Highs(3),
    )

    ticket = _tagged("Ticket") + '"name":"{{Highs}}"}'
    highs = _tagged("Highs") + '"count":3}'
    assert record.runs == ["ticket " + ticket + ", count " + highs], (
        "a substituted value was scanned again, so an input's own text became a second "
        "placeholder and put some other input where the workflow never asked for it"
    )

@pytest.mark.asyncio
async def test_braces_that_are_not_a_placeholder_are_left_in_the_prompt_untouched(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The grammar's negative half, which is what lets a prompt carry a payload schema.

    `{Ticket}` opens nothing here, `{{Ticket}` closes nothing, and `{{ two words }}` is prose that
    happens to sit between braces - the byte-identity test above makes that claim against a whole
    realistic prompt, and this one makes it about the grammar in isolation. The engines an author
    might be quoting are still quotable: a filter, a block tag or a sentence between `{{` and `}}`
    reaches the agent as it was written.

    The one near-miss that is *not* here is `{{ Ticket }}`, and its absence is the decision:
    padding the braces is what every templating engine spells a substitution as, so it is refused
    at the declaration rather than delivered as prose - `tests/sdk/test_roles.py` is where that is
    measured, and this test could not declare the role it would need.

    All three survive verbatim, and the real one beside them is filled, so this fails as "the
    grammar moved" rather than as "nothing was substituted at all".
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    written = "{Ticket} {{ two words }} {{Ticket} {{Ticket}}"

    await run.step(_one_ticket(written), Ticket("T-01"))

    value = _tagged("Ticket") + '"name":"T-01"}'
    assert record.runs == ["{Ticket} {{ two words }} {{Ticket} " + value], (
        "the placeholder grammar takes something other than `{{Name}}` with no space in it, so "
        "an author's literal braces are being rewritten and the declaration-time scan that has to "
        "agree with this one is reading a different language"
    )

@pytest.mark.asyncio
async def test_a_subclass_of_a_declared_type_fills_that_declarations_own_placeholder(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """`_one_ticket` accepts `Ticket`; an `Urgent` is one, and `{{Ticket}}` is where it goes.

    Keyed off the instance instead, this value would land under `Urgent`, `{{Ticket}}` would
    render `Not provided`, and the ledger would go on recording that an input was supplied - the
    author's own value gone from the prompt with the entry saying otherwise, which is a step paid
    for and answered without the thing it was about.

    Nothing is collapsed by the shared key: `Urgent` adds no field, so the qualified type name
    `journal.py` writes inside the value is the *only* difference between it and its base, and it
    is asserted here in front of the agent. `Ticket("T-01")` and `Urgent("T-01")` are therefore
    two canonical texts, two `inputs` terms and two digests under one name.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_one_ticket("Fix {{Ticket}}."), Urgent("T-01"))

    value = _tagged("Urgent") + '"name":"T-01"}'
    assert record.runs == ["Fix " + value + "."], (
        "a subclass of a declared type did not fill that type's placeholder, so a role declaring "
        "a base cannot be handed anything below it without the prompt losing the value"
    )

@pytest.mark.asyncio
async def test_a_value_matching_a_type_and_its_subclass_is_recorded_under_the_narrower(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """Two declarations match, and the one further down wins - the only answer that is not a coin.

    `_either_ticket` accepts `Ticket` and `Urgent` both. An `Urgent` is an instance of each, so
    something has to choose, and choosing the base would make the narrower declaration
    unreachable: no value could ever land under `Urgent`, and a prompt writing `{{Urgent}}` would
    read `Not provided` forever with nothing anywhere saying why. The narrower is also the more
    informative of the two, and it is the one the author went to the trouble of declaring.

    Both placeholders are in the prompt, so this says where the value went *and* where it did not.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    await run.step(_either_ticket("base {{Ticket}} / derived {{Urgent}}"), Urgent("T-01"))

    value = _tagged("Urgent") + '"name":"T-01"}'
    assert record.runs == ["base Not provided / derived " + value], (
        "a value matching a declared type and a subclass of it was recorded under the base, which "
        "leaves the subclass declared, matchable and impossible to ever record anything under"
    )

# --- a prompt that came out of a file ------------------------------------------------------------
#
# "**`instructions` is prompt text, never a path.** A role holding a filename would
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
    """The whole of the promise, measured at the far end: what the agent was asked **is** the
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
    """The named failure, shown closed - and the control beside it, because "it re-ran" is only
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
        "produced - the whole reason the role is in the digest, arriving as a cache hit"
    )
    assert len(_entries(tmp_path, "review")) == 2

# --- a reporting tool's payload type is a term too ------------------------------------------------

@pytest.mark.asyncio
async def test_a_step_reporting_through_another_payload_type_does_not_replay_the_first(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The second half of the qualified type name, at the surface where it costs something.

    Two roles identical in every term a fingerprint takes but one: the reporting tool's payload
    *type*. Same instructions, same model, same restrictions, same tool name and description, and a
    payload dataclass of exactly the same shape under a different name. Before the type name went
    in they derived a byte-identical schema, so the second walk found the first's entry and
    replayed it **into the new type** - nothing raised, nothing failed to parse, and the workflow
    read a `Restatement` that was recorded as a `Summary`.

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
    """The folded counter key, and the sharpest failure in this file: a **false cache hit**.

    `StepName` allows `[A-Za-z0-9._-]`, so `Role(name="Review")` is a legal declaration, and a
    step's address is its role's name. Two roles differing only in case, in one namespace,
    alike in every term `base_of` takes - same instructions, same model, same restrictions, same
    tools, no inputs, and run back to back over a tree neither commits to, so the same head - are
    one `base` by construction, because `base_of` has no name parameter to tell them apart.

    What separated them was the counter's key and the directory. Keyed on the raw `StepName`, both
    sat at `n = 0` and hashed to one digest; and `steps/Review/` and `steps/review/` are **one
    directory** on a case-insensitive volume, which is macOS by default. So the second step read the
    first step's file, matched the fingerprint it found there, and handed back a value no agent
    produced for it - no re-run, no exception, and the wrong answer. Every other silent failure
    around replay costs money; this one costs correctness.

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
    """The framework holds the last string it was handed and hands it back, and that is all.

    The two lines are read from *inside* the run, because that is the only place there is anything
    to read - `None` when nothing is running means an assertion after the step can only ever see
    `None`. They are deliberately spelled the documented way, tool name and target, to make
    the point that nothing here parsed either one: no `Activity` type, no verb taxonomy, no lookup
    table, so what comes back is what the adapter said, character for character.

    **And it is cleared when the step ends**, which is the half that fails silently. A line left
    standing describes work that finished minutes ago, on a screen redrawn every frame, and
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
        "the last line of a finished step is still there. `None` means nothing is running, "
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

    **A step replayed from cache has no activity at all, correctly, since nothing is running.**
    The second walk below is handed a script that reports on its very first line and is
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
    """The one thing a `Run` adds that a bare `Journal` could not have measured: the lazy open.

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
    """Names are opaque strings, "validated on the way in" - filesystem- and ref-safe.

    The name is the role's, so this is where "on the way in" is: at the line that
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

    The field is `_model` because nothing but `@role(model=…)` writes a role's model -
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
    }.items():
        object.__setattr__(undeclared, field, value)

    with pytest.raises(InputError, match="step name"):
        await run.step(undeclared)

    assert record.runs == []
    assert not (tmp_path / "trees").exists(), "a refused step name provisioned a checkout anyway"

@pytest.mark.asyncio
async def test_an_input_of_an_undeclared_type_names_both_sides_and_spends_nothing(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """`accepts=` is the whole list, so a value of no type on it has no name to be recorded under.

    Both halves are asserted because a message carrying one of them leaves the author guessing at
    the other: what was handed over is on the call site's line, and what the role declared is on a
    decorator in some other module. A refusal naming only the first is the one that reads as a
    framework being fussy rather than as two lines that disagree.

    The check runs above `Capabilities.require` and above the journal, so a mistake in a workflow's
    own call costs neither a probe of a backend nor a checkout - which is what the last two
    assertions are for. It is the step-name test above making its argument about the other refusal
    that can be settled from the call alone: a run that cannot record a step should not pay for one.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    with pytest.raises(InputError) as refusal:
        await run.step(_ticket_and_highs("triage {{Ticket}} and {{Highs}}"), Summary("nope"))

    assert "Summary" in str(refusal.value), "the refusal did not name the type that was passed"
    assert "['Highs', 'Ticket']" in str(refusal.value), (
        "the refusal did not name what the role accepts, which is the half that is not on screen "
        "at the line the author has to change"
    )
    assert record.runs == []
    assert not (tmp_path / "trees").exists(), "a refused input provisioned a checkout anyway"

@pytest.mark.asyncio
async def test_two_inputs_of_one_type_are_refused_rather_than_one_replacing_the_other(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """One key per type, so a second value of a type has nowhere to go but over the first.

    What this refuses is not a lost argument, which would be loud enough on its own. The dropped
    value reaches no fingerprint, so two calls differing only in it share one digest and the second
    replays the first's recorded result - a value handed back for work never done, which is the one
    failure `sdk/_engine/journal.py`'s canonicaliser is built to make unreachable.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    role = _one_ticket("triage {{Ticket}}")

    with pytest.raises(InputError, match="two Ticket values"):
        await run.step(role, Ticket("T-01"), Ticket("T-07"))

    assert record.runs == []
    assert not (tmp_path / "trees").exists()

@pytest.mark.asyncio
async def test_a_role_no_factory_built_accepts_nothing_and_the_refusal_says_where_to_declare(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """A hand-built `Role` carries no `accepts`, for the reason it carries no model.

    `RoleFactory.__call__` binds both, and it binds them there so that preflight can read them off
    the factory without calling it - so the refusal has to say which line is missing rather than
    only that something is. A reader told "this role accepts nothing" goes looking for a field of
    `Role`, which is exactly the place the declaration deliberately is not.

    The role below names no model either, and this refusal is still the one that arrives: the
    inputs are checked from the call alone, above the first thing that reads `role.model`.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    bare = Role[Summary](name="triage", instructions="triage the findings", tools=(REPORT,))

    with pytest.raises(InputError) as refusal:
        await run.step(bare, Ticket("T-01"))

    assert "accepts nothing at all" in str(refusal.value)
    assert "@role(model=..., accepts=(Ticket,))" in str(refusal.value)
    assert record.runs == []

@pytest.mark.asyncio
async def test_an_input_matching_two_unrelated_declared_types_is_refused_and_not_keyed_by_either(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """Two declarations match and neither is below the other, so there is no name to record it as.

    Every other tie in this scheme has an answer that is not a coin toss - a subclass and its base
    resolve to the subclass, which the section on placeholders measures. This one has none: `Both`
    is a `Ticket` and a `Highs`, and picking either would be a rule living in the framework about
    which of the workflow's own types the step meant. Picked silently, the wrong placeholder is
    the one that fills and the right one reads `Not provided`, with the step paid for either way.

    The refusal names both candidates, because the value's own type is on the call site's line and
    the two it collided with are on a decorator in some other module.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    with pytest.raises(InputError) as refusal:
        await run.step(
            _ticket_and_highs("triage {{Ticket}} and {{Highs}}"), Both(count=3, name="T-01")
        )

    assert "['Highs', 'Ticket']" in str(refusal.value), (
        "the refusal did not name the declarations that tied, which is the half not on screen at "
        "the line the author has to change"
    )
    assert "Both" in str(refusal.value)
    assert record.runs == []
    assert not (tmp_path / "trees").exists(), "an ambiguous input provisioned a checkout anyway"

@pytest.mark.asyncio
async def test_a_subclass_and_its_declared_base_land_under_one_name_and_are_refused(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The collision the declared-type key creates, and it is the same refusal as two of one type.

    `_one_ticket` accepts `Ticket` alone, so a `Ticket` and an `Urgent` are both recorded under
    `Ticket` - one key, two values, and the second would take the first's place in the fingerprint
    and in the prompt. That is the two-of-one-type refusal above reached by a second road, and
    the guard has to fire on this one too or keying by the declared type bought a silent drop
    where there was none.

    The message is asserted for the clause that is new: a reader handed "two Ticket values" while
    holding a `Ticket` and an `Urgent` needs to be told that the second is recorded as the first.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    role = _one_ticket("triage {{Ticket}}")

    with pytest.raises(InputError, match="two Ticket values") as refusal:
        await run.step(role, Ticket("T-01"), Urgent("T-07"))

    assert "subclass of Ticket is recorded under Ticket" in str(refusal.value)
    assert record.runs == []
    assert not (tmp_path / "trees").exists()

@pytest.mark.asyncio
async def test_a_declaration_whose_prompt_and_accepts_disagree_is_refused_before_a_step_spends(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """A role knows both halves, so the two are compared where they are written and nowhere later.

    `run.step` is never entered: the refusal is raised while its first argument is being built, so
    there is no step name to resolve, no fingerprint to look up, no checkout to cut and no agent to
    dispatch to - which is what the last two assertions say, in the shape the input refusals above
    say it. That is a stronger claim than "it happens early": a declaration this run never reaches
    is refused all the same, because the factory is what checks it.

    The half asserted here that `tests/sdk/test_roles.py` cannot make is the spend. The half made
    there and not here is the message, which names the placeholders, the accepted types and the
    line each of them is written on.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))

    @role(model=Claude.SONNET, accepts=(Ticket,))
    def _disagreeing() -> Role[Summary]:
        return _triage("triage the findings")

    with pytest.raises(InputError, match="Ticket"):
        await run.step(_disagreeing(), Ticket("T-01"))

    assert record.runs == []
    assert not (tmp_path / "trees").exists(), "a refused declaration provisioned a checkout anyway"
