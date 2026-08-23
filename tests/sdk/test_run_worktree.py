"""What `run.worktree` promises: nesting in `AGL_HOME`, flat siblings in `.trees/`, one name each.

The suite over `sdk/_engine/worktrees.py` and over the half of `sdk/workflow.py` that reaches it.
`test_run_step.py` holds one namespace against real git; this file holds what happens when there is
more than one, which is the only real concurrency AGL has - §3.6 serializes steps within a namespace
on purpose, so an author who wants two agents running at once opens two worktrees.

**The repository is real git, and the ledger is a real `FilesystemStore`**, for
`test_run_step.py`'s reasons and for one more of this file's own: every claim below is about where
something landed. "The entry nests" is a path on disk, "the checkouts are siblings" is a directory
listing, and "`agl/auth` and `agl/_work/auth/T-01` coexist" is a question only git can be asked -
the fakes keep their branches in a dict, where the ref directory/file conflict §3.9 is about cannot
exist at all and so cannot be shown closed.

The fixtures are duplicated from `test_run_step.py` rather than imported. Nothing under `tests/`
imports another test module, `tests/` carries no `__init__.py` (see `tests/conftest.py`), and a
shared fixture module would make one file's arrangement another file's dependency - which is how a
suite acquires a base class nobody can change.

Five of these are worth naming, because each is written against a failure that is silent or remote:

  * **The asymmetry, both halves in one test.** §3.9: `AGL_HOME` nests because it records the
    parent-child structure of the run, and the trees root does not because a worktree inside another
    worktree's working tree is untracked files to the parent - its `git status` and its build gate
    would both see the child's entire checkout. Asserting either half alone is satisfiable by a
    design that got the other one wrong.
  * **Run-wide uniqueness, in both creation orders.** A registry that compared siblings would let
    `T-01`'s child `sub-b` and a top-level `sub-b` both through, and they are one directory under
    `.trees/<label>/`: the second would be handed the first one's working tree, with its work in it.
    Both orders, because a sibling-wide table admits whichever arrives second whatever that order
    is, and only one of the two orders is the obvious one to write.
  * **A child starts at its parent's *logical* head.** §3.6's "the starting head is chained
    logically, not read from disk". The branch can be ahead of the chain with nothing journalled -
    a step that raised after `commit=` does it today and `integrate()` will do it deliberately - so
    a child cut from where the branch actually is inherits work the run has no record of, and the
    parent's next fingerprint miss restores past it.
  * **A reopened namespace replays instead of re-cutting.** §3.3: "an existing name reopens rather
    than recreates, which is what makes replay work". An implementation that quietly re-provisioned
    would pass every test that only asks whether opening twice raises, and would destroy the
    committed work of every child on every resume.
  * **The name is opaque.** §3.3's own test is "rename `T-01` to `banana` and the framework behaves
    identically", and the sharpest form of it is that the two entries are **byte-identical files**:
    the namespace reaches the digest through nothing at all, so only the directory differs.
"""

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.history import GitHistory
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.config import container
from agl.ports.agent import AgentOutcome, Claude, Restriction, StopReason, ToolResult
from agl.ports.errors import ConflictError, InputError
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.run import JsonValue
from agl.ports.tree_layout import TreesRoot
from agl.sdk.roles import Role
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run

# Every test that awaits is marked one by one rather than through a module-level `pytestmark`,
# matching the rest of `tests/sdk/`. Several tests here are deliberately **not** async, because
# `worktree()` is a plain synchronous call (§3.3) and a test that had to await it would be asserting
# the opposite of what this file says.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

TICKET: Final = Namespace("T-01")
NESTED: Final = Namespace("sub-b")

# The file the repository is seeded with, and the one an agent writes when it is told to leave work
# behind. `FEATURE` is what "the child inherited the parent's commits" is asked about.
SEEDED: Final = "src/a.txt"
SEED: Final = b"the user's own work\n"
FEATURE: Final = "src/feature.py"
SIDEQUEST: Final = "src/sidequest.py"

_NOTHING: Final[Mapping[str, bytes]] = MappingProxyType({})


@dataclass(frozen=True)
class Summary:
    """A reporting payload: one string, which is the whole of what these agents have to say."""

    text: str


REPORT: Final = reporting_tool("report", "report what you did", Summary)


class _Crash(Exception):
    """What an agent dying mid-step looks like from here. Any exception would do."""


# --- the repository, the bundle, and the run -----------------------------------------------------


def _git(where: Path, *argv: str) -> str:
    """One git command, for arranging and observing. Never for the thing under test."""
    done = subprocess.run(["git", *argv], cwd=where, capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit, and no configuration from this machine.

    `test_run_step.py`'s fixture, duplicated for the reason the module docstring gives. The
    `GIT_CONFIG_*` variables are what make this suite the same suite everywhere, and they go through
    `monkeypatch` so the adapter, which inherits the environment, sees them too.
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
    """A `Run` over one real repository, one real ledger, one real history and one scripted agent.

    `test_run_step.py::_run` exactly, and `history` is real here for the reason it is real there:
    `Steps._namespace` resolves its base through `History.resolve` and hands the one resolved value
    to both the checkout and the `Journal`, and a fake history answers about a repository that has
    never heard of this one's commits. It does real work here rather than being an identity, because
    one test below cuts a child from a ref *name*.

    Called twice with the same arguments it is a resume: the same ledger on disk, the same worktrees
    reopened, and a fresh counter and a fresh namespace table, which is what §3.6 means by "`n` is
    never persisted" and what makes a second walk cut the same children again.
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


# --- roles, and the agents that serve them -------------------------------------------------------


def _role(instructions: str, *, read_only: bool = False) -> Role[Summary]:
    """A reporting role: its result is `REPORT`'s payload, read back as a `Summary`."""
    restrictions = {Restriction.NO_VCS_WRITES} if read_only else set[Restriction]()
    return Role(
        instructions=instructions,
        model=Claude.SONNET,
        restrictions=restrictions,
        tools=(REPORT,),
    )


class _Agent:
    """What the fake was asked, and what it was told back, written down."""

    def __init__(self) -> None:
        self.runs: list[str] = []
        """One entry per dispatch, holding that task's instructions. `len(runs)` is what "the agent
        was paid for again" means, and a replay's whole observable difference from a re-run."""

        self.results: list[ToolResult] = []
        """Every answer the reporting tool gave, refusals included."""


def _agent(
    record: _Agent, *, writes: Mapping[str, bytes] = _NOTHING, dies_once: bool = False
) -> Script:
    """One agent's conduct, in the only vocabulary the port has.

    Writing to `task.workspace` with the stdlib is the script's own code and not the adapter's,
    which is what lets a fake agent leave real files in a real worktree for `commit=` to record.

    `dies_once` raises on the **first** dispatch only, which is the arrangement one test below
    needs: a step that raised after `commit=` moves the branch and journals nothing, and the child
    cut afterwards has to be served by an agent that works.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        record.runs.append(conversation.task.instructions)
        for name, content in writes.items():
            target = conversation.task.workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if dies_once and len(record.runs) == 1:
            raise _Crash("the agent died mid-step")
        payload = {"text": f"{conversation.task.instructions} #0"}
        record.results.append(await conversation.call(REPORT.name, payload))
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script


# --- the ledger and the trees root, read off disk ------------------------------------------------
#
# Every path below is **spelled out** rather than composed through `home_layout` or `tree_layout`. A
# test that asked `step_dir` where an entry should be and then looked there would agree with the
# layout whatever either of them said, and the layout is half of what this file is about: that
# `AGL_HOME` nests and the trees root does not is a claim about two literal shapes on disk.


def _run_dir(tmp_path: Path) -> Path:
    """`<home>/projects/myapp/runs/auth/` - depth zero, the run itself."""
    return tmp_path / "home" / "projects" / "myapp" / "runs" / "auth"


def _steps_dir(tmp_path: Path, step: str, *namespaces: str) -> Path:
    """`<run>/worktrees/<n>/.../steps/<step>/` - §3.6's layout, written out as §3.6 draws it."""
    where = _run_dir(tmp_path)
    for namespace in namespaces:
        where = where / "worktrees" / namespace
    return where / "steps" / step


def _entries(tmp_path: Path, step: str, *namespaces: str) -> list[Path]:
    """Every entry file recorded for one step in one namespace, in filename order."""
    return sorted(_steps_dir(tmp_path, step, *namespaces).glob("*.json"))


def _one(tmp_path: Path, step: str, *namespaces: str) -> dict[str, JsonValue]:
    """The one entry that step recorded there. Two would mean it ran twice."""
    found = _entries(tmp_path, step, *namespaces)
    assert len(found) == 1, f"{_steps_dir(tmp_path, step, *namespaces)} holds {len(found)} entries"
    parsed: dict[str, JsonValue] = json.loads(found[0].read_text(encoding="utf-8"))
    return parsed


def _head(tmp_path: Path, step: str, *namespaces: str) -> str:
    """The commit one recorded step ended at - the value §3.6 chains `last_good` from."""
    recorded = _one(tmp_path, step, *namespaces)["head"]
    assert isinstance(recorded, str)
    return recorded


def _trees_dir(tmp_path: Path) -> Path:
    """`.trees/auth/` - every checkout belonging to this run, and nothing else."""
    return tmp_path / "trees" / "auth"


def _branches(repository: Path) -> list[str]:
    """Every branch in the repository, fully qualified, asked of git rather than of the layout."""
    listed = _git(repository, "for-each-ref", "--format=%(refname)", "refs/heads/")
    return listed.split()


# --- the asymmetry: memo namespaces nest, checkouts do not ---------------------------------------


@pytest.mark.asyncio
async def test_entries_nest_arbitrarily_while_every_checkout_is_a_flat_sibling(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.9's two layouts at once, in one nested run, both asserted on disk.

    Three namespaces, three steps: the run itself, its child `T-01`, and `T-01`'s child `sub-b`.

    **Half one - `AGL_HOME` nests**, because it is recording the parent-child structure of the run,
    so `sub-b`'s entry is two `worktrees/` deep. Asserted as the literal path §3.6 draws, because
    the alternative - `runs/auth/worktrees/sub-b/` for a grandchild - is a tree that has lost the
    only record there is of who cut whom, and every path in it is still perfectly well-formed.

    **Half two - the trees root is flat**, because a worktree inside another worktree's working tree
    appears to the parent as untracked files: the parent's `git status` and its build gate would
    both see the child's entire checkout, and an agent asked to commit its work would commit it. The
    assertion is therefore not only that `.trees/auth/sub-b/` exists but that
    `.trees/auth/T-01/sub-b` does **not** - a nested checkout would satisfy "the child has a
    worktree" perfectly well and would put a second repository inside the first one's build gate.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record, writes={FEATURE: b"the route\n"}))
    ticket = run.worktree("T-01")
    nested = ticket.worktree("sub-b")
    assert nested.scope == RunScope(PROJECT, LABEL, (TICKET, NESTED))

    await run.step("spec", _role("write the spec", read_only=True))
    await ticket.step("implement", _role("implement T-01"), commit="implement T-01")
    await nested.step("implement", _role("implement sub-b"), commit="implement sub-b")

    assert len(_entries(tmp_path, "spec")) == 1
    assert len(_entries(tmp_path, "implement", "T-01")) == 1
    assert len(_entries(tmp_path, "implement", "T-01", "sub-b")) == 1, (
        "the grandchild's entry is not under runs/auth/worktrees/T-01/worktrees/sub-b/steps/. "
        "`AGL_HOME` nests because it records the parent-child structure of the run (§3.9), and a "
        "flattened memo tree keeps every path well-formed while losing who cut whom"
    )

    trees = _trees_dir(tmp_path)
    assert sorted(place.name for place in trees.iterdir()) == ["T-01", "_base", "sub-b"], (
        "the checkouts are not flat siblings under .trees/auth/. §3.9: a worktree inside another "
        "worktree's working tree is untracked files to the parent, so its git status and its build "
        "gate would both see the child's entire checkout"
    )
    assert not (trees / "T-01" / "sub-b").exists()
    assert (trees / "T-01" / FEATURE).is_file()
    assert (trees / "sub-b" / FEATURE).is_file()
    assert len(record.runs) == 3


# --- one namespace per run, not one per parent ---------------------------------------------------


@pytest.mark.parametrize("nested_first", [True, False])
def test_a_grandchilds_name_and_a_top_level_name_collide_in_either_creation_order(
    repository: Path, tmp_path: Path, base: str, nested_first: bool
) -> None:
    """§3.9: "namespace names are unique within the run, not merely among siblings".

    `T-01`'s child `sub-b` and a top-level `sub-b` are two scopes under `AGL_HOME` and **one
    directory** under `.trees/auth/`, because the trees root is flat. Whichever opened second would
    be handed the first one's working tree, with the first one's work in it, and nothing anywhere
    would raise.

    **Both orders, because only one of them is the obvious one to write.** A table keyed per parent
    - which is what a `Worktrees` built inside each child would be - lets the second arrival through
    whichever way round it happens, and a test that asserted only the sibling case would be green
    against exactly that implementation.

    Synchronous, and nothing is provisioned by either call: `worktree()` is a plain call (§3.3), the
    refusal happens in the run's own namespace table, and no checkout is opened until a step runs.
    """
    run = _run(repository, tmp_path, base)
    ticket = run.worktree("T-01")

    if nested_first:
        ticket.worktree("sub-b")
        with pytest.raises(ConflictError) as raised:
            run.worktree("sub-b")
        held, asking = "the worktree T-01", "the run itself"
    else:
        run.worktree("sub-b")
        with pytest.raises(ConflictError) as raised:
            ticket.worktree("sub-b")
        held, asking = "the run itself", "the worktree T-01"

    assert held in str(raised.value) and asking in str(raised.value), (
        "the refusal does not name both scopes, so a reader is told a name is taken and left to "
        "find out by whom"
    )
    assert not (tmp_path / "trees").exists(), "a refused namespace provisioned a checkout anyway"


def test_two_spellings_of_one_name_are_one_directory_and_the_second_is_refused(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.9: "the comparison is case-insensitive (casefold): `T-01` and `t-01` are two refs to git
    and one directory on macOS".

    Both are perfectly good names - `ids.py` accepts each, and `Namespace("T-01") != Namespace(
    "t-01")`, which is right, because they really are two different branches. What is refused is the
    second one *in a run that already holds the first*, and it is refused on every platform rather
    than on whichever one the developer is using, because a case-sensitive volume would let both
    through and the failure would arrive on somebody else's laptop.

    **Asked of one `Run`, deliberately, because that is where the two comparisons differ.** A reopen
    is keyed on the name as written and a collision on the folded one, so this call is the case that
    distinguishes them: a table that folded both would hand `t-01` the `T-01` child, and a workflow
    would hold two names for one namespace and record one of them under the other's directory with
    nothing anywhere raising.

    The refusal prints both spellings, which is the whole of what makes it readable: "`t-01` is
    taken" would send a reader looking for a call that is not there.
    """
    run = _run(repository, tmp_path, base)
    run.worktree("T-01")

    with pytest.raises(ConflictError) as raised:
        run.worktree("t-01")

    assert "'t-01'" in str(raised.value) and "'T-01'" in str(raised.value)


def test_a_namespace_name_that_could_not_be_a_path_segment_or_a_ref_is_refused(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3: names are opaque strings, "validated on the way in", and `_base` is reserved.

    `InputError` and not `ConflictError`: nothing is taken and nothing collides - the name could
    never have been used. It comes out of `Namespace` itself, before the run's table is consulted,
    which is why a refused name leaves no entry in it and a later good name of the same shape works.
    """
    run = _run(repository, tmp_path, base)

    with pytest.raises(InputError, match="namespace"):
        run.worktree("../escape")
    with pytest.raises(InputError, match="_base"):
        run.worktree("_base")

    assert run.worktree("T-01") is not None
    assert not (tmp_path / "trees").exists()


# --- reopen, and what a resume rests on ----------------------------------------------------------


def test_asking_twice_for_one_name_hands_back_the_same_child_and_the_runs_own_tables(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3: "an existing name reopens rather than recreates, which is what makes replay work".

    **The same object, not an equal one.** A second `Run` over one namespace would be a second
    `Steps`, a second lazily opened checkout and a second `Journal` - "two locks over one namespace,
    which is not a lock at all" - and a second `last_good` chain starting where that namespace began
    rather than where it has got to.

    The two identities beneath it are asserted here rather than through behaviour, and the reason is
    worth stating because it is the reason a mutation of either is hard to catch. `Fingerprints`'
    key already carries the scope (§3.6 rule 1), and a child's scope is unique run-wide by the rule
    two tests up - so a counter built privately per child produces the same digests as the run's own
    for as long as no two `Run`s share a scope, and the only thing that makes two `Run`s share a
    scope is a reopen that built a second one. The identity is what the behaviour rests on, so the
    identity is what is asserted. The namespace table is not in that position - a private one is
    caught by the collision tests - and is asserted here beside it because they are one seam.
    """
    run = _run(repository, tmp_path, base)

    first = run.worktree("T-01")
    second = run.worktree("T-01")

    assert second is first
    assert first.fingerprints is run.fingerprints, (
        "the child was handed a counter of its own. §3.6 scopes `n` per (namespace, step name) and "
        "one counter per run is what makes that key mean anything"
    )
    assert first.worktrees is run.worktrees, (
        "the child was handed a namespace table of its own, which is a table per namespace - it "
        "cannot see a name taken anywhere else in the run, which is §3.9's check written and "
        "unreachable"
    )
    assert first.params is run.params and first.services is run.services
    assert first.scope == RunScope(PROJECT, LABEL, (TICKET,))


# --- who cut whom: the link `integrate()` walks --------------------------------------------------


def test_the_root_has_no_parent_and_every_child_holds_the_run_that_cut_it(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """14.0's seam. `integrate()` writes into the **parent's** chain and lands into the **parent's**
    checkout (§3.4, §3.6), so what it needs is the parent `Run`, and this is where it comes from.

    **Asserted by identity, and that is the claim rather than a shortcut.** What the engine wants
    off the parent is its live journal - the in-memory `last_good` a landing advances - so an
    equal-but-second `Run` over the parent's scope would satisfy `==` and carry a second `Steps`, a
    second checkout and a second chain, and advancing that one would move a value nothing reads.
    That is why the link is a reference and not an address to look one up by.

    **`None` is how a root says it is a root**, which is the case `integrate()` has to refuse: a run
    with nowhere to land is a workflow error, and this says so directly where a lookup that came
    back empty would say "the root, or a bug, and I cannot tell which".

    The grandchild is here because parentage and the namespace table agree at depth one and part
    company at depth two: `sub-b` was cut by `T-01`, while both of them are ordinary entries in the
    one run-wide table, which knows who *holds* a name and not who spent it.
    """
    run = _run(repository, tmp_path, base)

    child = run.worktree("T-01")
    grandchild = child.worktree("sub-b")

    assert run._parent is None
    assert child._parent is run
    assert grandchild._parent is child


def test_a_reopened_namespace_still_holds_the_parent_that_first_cut_it(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """`_child` is the only thing that builds a child, so it is the only thing that sets the link.

    A reopen never reaches it - `Worktrees.open` calls `build` exactly once per namespace - so the
    second call hands back the object the first one made, parent and all. That is what keeps the
    link true across a replay: a second walk makes the same `worktree()` calls and has to land on
    the same parent every time, because the chain a landing will advance is the one already in
    memory and there is only ever one of it per namespace.
    """
    run = _run(repository, tmp_path, base)
    child = run.worktree("T-01")

    first = child.worktree("sub-b")
    again = child.worktree("sub-b")

    assert again is first
    assert again._parent is child


@pytest.mark.asyncio
async def test_the_landing_seam_hands_out_the_namespaces_own_journal_and_checkout(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """14.0's third seam, and the two claims that make it a seam rather than an accessor.

    `integrate()` lands a child's workspace into its parent's and then advances the parent's chain,
    so it asks the parent's `Steps` for both at once. **The checkout has to be the one the parent's
    own steps work in** - landing into a second checkout over one branch is work done in a directory
    nothing else looks at - and **the journal has to be the live one**, because a chain advanced on
    a copy is a value nothing reads.

    The second claim is asserted the only way it can be shown from outside: advance through the seam
    and then cut a child, whose base is that chain (§3.6, "the starting head is chained logically,
    not read from disk"). A `landing()` that built its own `Journal` would pass every assertion
    above this one and leave every later child cut from the commit before the landing - which is the
    destructive failure `advance` exists to prevent, arriving through the door that was opened to
    prevent it.
    """
    record = _Agent()
    written = {FEATURE: b"the callback route\n"}
    run = _run(repository, tmp_path, base, _agent(record, writes=written))
    await run.step("spec", _role("write the spec"), commit="spec")

    journal, workspace = await run._steps.landing()
    again_journal, again_workspace = await run._steps.landing()

    assert (again_journal, again_workspace) == (journal, workspace)
    assert (workspace.path / FEATURE).is_file(), (
        "the seam opened a checkout of its own: what a landing goes into has to be the tree the "
        "parent's own steps have been committing to"
    )
    assert journal.last_good == _head(tmp_path, "spec")

    # What an integrator does to the target, and then what the engine does to the chain.
    sidequest = workspace.path / SIDEQUEST
    sidequest.parent.mkdir(parents=True, exist_ok=True)
    sidequest.write_bytes(b"landed from T-01\n")
    landed = await workspace.commit_all("land T-01")

    journal.advance(landed)

    assert run.worktree("T-02").base == landed, (
        "the chain the seam handed out is not the chain `worktree()` reads, so the landing moved "
        "one journal and every child after it was still cut from the commit before the landing"
    )


@pytest.mark.asyncio
async def test_a_reopened_namespace_replays_its_step_and_is_not_cut_again(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The reopen where it costs money: a second walk over the same ledger.

    An implementation that quietly re-cut a clean checkout passes "opening twice does not raise" and
    destroys every resume - `WorkspaceProvider.open` says so from its own side, and this is the same
    sentence one layer up. Three assertions, because they fail differently: the agent was not paid
    again, no second entry was written, and the child's branch still points where its own commit put
    it rather than back at the run's base.
    """
    record = _Agent()
    written = {FEATURE: b"the callback route\n"}
    role = _role("implement T-01")

    first = _run(repository, tmp_path, base, _agent(record, writes=written))
    made = await first.worktree("T-01").step("implement", role, commit="implement T-01")
    landed = _git(repository, "rev-parse", "refs/heads/agl/_work/auth/T-01").strip()

    second = _run(repository, tmp_path, base, _agent(record, writes=written))
    replayed = await second.worktree("T-01").step("implement", role, commit="implement T-01")

    assert replayed == made == Summary("implement T-01 #0")
    assert len(record.runs) == 1, "the resume paid for an agent whose result was on the ledger"
    assert len(_entries(tmp_path, "implement", "T-01")) == 1
    assert _git(repository, "rev-parse", "refs/heads/agl/_work/auth/T-01").strip() == landed, (
        "the reopened namespace was re-cut from the run's base, which throws away every commit the "
        "child had already made - the one thing a resume exists to keep"
    )
    assert (_trees_dir(tmp_path) / "T-01" / FEATURE).is_file()


@pytest.mark.asyncio
async def test_a_second_walk_over_a_nested_run_replays_every_namespace(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """Stage 13's own acceptance criterion: "replay of a nested run reproduces every namespace".

    Three namespaces at three depths, walked twice, with the recorder shared between the two runs so
    that "no agent was called" is counted across both rather than reset by the arrangement.

    What makes this more than a bigger version of `test_run_step.py`'s replay is where each
    namespace's chain starts. The root's is its pinned base; `T-01`'s is the root's logical head at
    the moment it was cut; `sub-b`'s is `T-01`'s logical head, which by then is the commit `T-01`'s
    own step made. A second walk reproduces all three only if every one of them is chained from
    recorded entries - a head read from the physical worktree is *already* past `T-01`'s
    `implement` on the second walk, so that step would miss, re-run, and cascade into `sub-b`.
    """
    record = _Agent()
    written = {FEATURE: b"the callback route\n"}

    first = await _nested(_run(repository, tmp_path, base, _agent(record, writes=written)))

    assert first == [
        Summary("write the spec #0"),
        Summary("implement T-01 #0"),
        Summary("repair #0"),
    ]
    assert len(record.runs) == 3

    replayed = await _nested(_run(repository, tmp_path, base, _agent(record, writes=written)))

    assert replayed == first
    assert len(record.runs) == 3, "a resume paid for agents whose results were on the ledger"
    assert len(_entries(tmp_path, "spec")) == 1
    assert len(_entries(tmp_path, "implement", "T-01")) == 1
    assert len(_entries(tmp_path, "repair", "T-01", "sub-b")) == 1


async def _nested(run: Run[None]) -> list[Summary]:
    """Three namespaces deep: one step in the run, one in a child, and one in a grandchild."""
    spec = await run.step("spec", _role("write the spec", read_only=True))
    ticket = run.worktree("T-01")
    built = await ticket.step("implement", _role("implement T-01"), commit="implement T-01")
    nested = ticket.worktree("sub-b")
    repaired = await nested.step("repair", _role("repair", read_only=True))
    return [spec, built, repaired]


# --- `steps/` and `worktrees/` are siblings ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_step_and_a_worktree_of_the_same_name_address_different_places(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.6: "`steps/` and `worktrees/` are sibling subtrees so `worktree("review")` and
    `step("review", ...)` in the same Run cannot collide".

    Both calls, in one `Run`, with the same string - and both work. `ids.py` keeps `StepName` and
    `Namespace` distinct types although their language is identical, on the argument that the two
    mean opposite things on disk; this is that argument measured, and the two directories are named
    literally so that a layout which merged them could not pass by renaming one.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    review = run.worktree("review")

    await run.step("review", _role("review the diff", read_only=True))
    await review.step("implement", _role("implement the review's findings", read_only=True))

    assert len(_entries(tmp_path, "review")) == 1
    assert len(_entries(tmp_path, "implement", "review")) == 1
    assert (_run_dir(tmp_path) / "steps" / "review").is_dir()
    assert (_run_dir(tmp_path) / "worktrees" / "review").is_dir()
    assert not (_run_dir(tmp_path) / "steps" / "review" / "worktrees").exists()
    assert len(record.runs) == 2


# --- the two branch names, in a repository that has to hold both ---------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("child_first", [False, True])
async def test_the_run_branch_and_a_child_branch_coexist_in_one_real_repository(
    repository: Path, tmp_path: Path, base: str, child_first: bool
) -> None:
    """§3.9's ref directory/file conflict, shown closed by the code that creates both.

    Refs are files under `refs/heads/`, so the obvious scheme - `agl/auth` for the run and
    `agl/auth/T-01` for its child - cannot exist in git in **either** creation order:

        fatal: cannot lock ref 'refs/heads/agl/auth/T-01': 'refs/heads/agl/auth' exists
        fatal: cannot lock ref 'refs/heads/agl/auth': 'refs/heads/agl/auth/T-01' exists

    `git check-ref-format` passes each name individually, which is why "must be a legal ref" never
    caught it and why nothing in `ids.py` could have. Both orders are driven here because each of
    those two messages is a different one of them.

    This is the test that would fail under `agl/<label>/<ns>`, and it has to be driven through a
    real `Run` on the real provider: `tests/ports/test_tree_layout.py` pins the *scheme* against
    git, and what is unproven until here is that the code which actually creates these two branches
    composes them through that scheme rather than assembling a name of its own.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    child = run.worktree("T-01")
    read_only = _role("look at it", read_only=True)

    if child_first:
        await child.step("implement", read_only)
        await run.step("spec", read_only)
    else:
        await run.step("spec", read_only)
        await child.step("implement", read_only)

    assert "refs/heads/agl/auth" in _branches(repository)
    assert "refs/heads/agl/_work/auth/T-01" in _branches(repository), (
        "the child's branch is not `agl/_work/<label>/<namespace>`. Under `agl/<label>/<ns>` this "
        "run could not have got this far: refs/heads/agl/auth would have to be a file and a "
        "directory at once, in either creation order (§3.9)"
    )
    assert _git(repository, "rev-parse", "refs/heads/agl/auth").strip() == base
    assert _git(repository, "rev-parse", "refs/heads/agl/_work/auth/T-01").strip() == base


# --- where a child starts ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_child_starts_at_the_parents_logical_head_and_not_at_the_runs_base(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """`base=None` means "this Run's current logical head", which is not `RunSpec.base_sha`.

    The parent commits a step first, so its chain has moved and its pinned base has not. A child cut
    from the pinned base would start behind its own parent: the work the run had already recorded
    would simply be absent from the child's checkout, the child would review or implement against a
    tree that is missing it, and nothing would raise.

    Two assertions, and the second is the one that cannot be satisfied by arithmetic: the child's
    first entry records the parent's recorded head, **and** the file the parent's step committed is
    really in the child's checkout.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record, writes={FEATURE: b"the route\n"}))

    await run.step("implement", _role("implement it"), commit="implement it")
    advanced = _head(tmp_path, "implement")
    assert advanced != base

    child = run.worktree("T-01")
    await child.step("review", _role("review", read_only=True))

    assert _head(tmp_path, "review", "T-01") == advanced, (
        "the child was cut from the run's pinned base rather than from where its parent's chain "
        "had got to, so it starts behind work the run has already recorded"
    )
    assert (_trees_dir(tmp_path) / "T-01" / FEATURE).is_file()


@pytest.mark.asyncio
async def test_a_child_cut_from_a_sibling_starts_at_that_siblings_recorded_head(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3's `w = parent.worktree(ticket.id, base=blocker)`, which is the whole of AGL's graph
    support: "a workflow with a dependency graph resolves its own blockers and passes the resulting
    `Run`; the framework never reads a `blocked_by` field and never learns that a graph exists".

    The parent runs no step at all here, so its own logical head is still the run's base - which is
    what makes this a real assertion rather than a coincidence: `b` starts at `a`'s head, and `a`'s
    head is the one value in this test that is neither the base nor anything the parent knows.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record, writes={FEATURE: b"the blocker\n"}))

    blocker = run.worktree("a")
    await blocker.step("implement", _role("implement a"), commit="implement a")
    blocked = run.worktree("b", base=blocker)
    await blocked.step("review", _role("review", read_only=True))

    landed = _head(tmp_path, "implement", "a")
    assert landed != base
    assert _head(tmp_path, "review", "b") == landed, (
        "the blocked child was not cut from its blocker: it starts at the parent's head, so the "
        "work it was waiting for is not in the tree it is working against"
    )
    assert (_trees_dir(tmp_path) / "b" / FEATURE).is_file()


@pytest.mark.asyncio
async def test_a_child_cut_from_a_ref_string_starts_where_that_ref_points(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """The third spelling of `base`: a ref expression, taken as written and resolved once.

    This is the one case where `History.resolve` does real work - a commit id resolves to itself -
    and it is resolved in `Steps._namespace` rather than at the call, because `worktree()` is
    synchronous and `resolve` is not. The one value goes to both the checkout and the `Journal`, so
    what the child was cut from and what its first fingerprint was taken over cannot disagree.

    A branch rather than a raw id, because a raw id would be indistinguishable from a `Run`-derived
    base and would prove nothing about resolution.
    """
    record = _Agent()
    _git(repository, "checkout", "-q", "-b", "sidequest")
    (repository / SIDEQUEST).write_bytes(b"somebody else's work\n")
    _git(repository, "add", SIDEQUEST)
    _git(repository, "commit", "-q", "-m", "a commit the run was not cut from")
    elsewhere = _git(repository, "rev-parse", "HEAD").strip()
    _git(repository, "checkout", "-q", "main")

    run = _run(repository, tmp_path, base, _agent(record))
    child = run.worktree("T-01", base="sidequest")
    await child.step("review", _role("review", read_only=True))

    assert elsewhere != base
    assert _head(tmp_path, "review", "T-01") == elsewhere, (
        "the child's chain did not start where the ref it was cut from points, so the tree it was "
        "given and the head its first fingerprint was taken over are two different commits"
    )
    assert (_trees_dir(tmp_path) / "T-01" / SIDEQUEST).is_file()
    assert _git(_trees_dir(tmp_path) / "T-01", "rev-parse", "HEAD").strip() == elsewhere


@pytest.mark.asyncio
async def test_a_child_is_cut_from_the_chain_and_not_from_where_the_branch_actually_is(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.6: "the starting head is chained logically, not read from disk", at the one moment stage
    13 can already produce the divergence.

    A step that raised after `commit=` is the case: the framework does one predictable thing per
    `commit=` "on success and on failure alike", so the commit lands and the branch moves - and no
    entry is written, because "a step is done when its file is there". The run's chain is therefore
    still at its base while `agl/auth` is a commit ahead of it, with nothing journalled in between.
    Stage 14's `integrate()` produces the same divergence deliberately and much more often.

    A child cut from `agl/auth` by name - which is how §3.9 describes it, and which
    `WorkspaceProvider.open` still accepts - would inherit a commit this run has no record of. The
    parent's next fingerprint miss then restores to the chain, *before* that commit, and the child
    is left working on top of something the run has just deleted.
    """
    record = _Agent()
    dying = _agent(record, writes={FEATURE: b"half a route\n"}, dies_once=True)
    run = _run(repository, tmp_path, base, dying)

    with pytest.raises(_Crash):
        await run.step("implement", _role("implement it"), commit="implement it")

    moved = _git(repository, "rev-parse", "refs/heads/agl/auth").strip()
    assert moved != base and _entries(tmp_path, "implement") == []

    child = run.worktree("T-01")
    await child.step("review", _role("review", read_only=True))

    assert _head(tmp_path, "review", "T-01") == base, (
        "the child was cut from where the branch physically is rather than from the run's chain, "
        "so it inherited a commit no entry records - and the parent's next fingerprint miss "
        "restores past that commit and deletes it out from under the child"
    )
    assert not (_trees_dir(tmp_path) / "T-01" / FEATURE).exists()


# --- the name is opaque --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renaming_a_namespace_changes_the_paths_and_nothing_else(
    repository: Path, tmp_path: Path, base: str
) -> None:
    """§3.3's own test: "rename `T-01` to `banana` and the framework behaves identically".

    Two children of one run, cut from the same head, running the same step with the same role and no
    inputs. The sharpest available form of "identically" is that the two entry files are **the same
    filename holding the same bytes**: a namespace reaches a fingerprint through nothing at all -
    §3.6's terms are the role, the inputs and the starting head - so the only place either name may
    appear is in a path and in a branch.

    A digest that differed between the two would mean the namespace had leaked into the fingerprint,
    which is not a wrong answer so much as a framework that had learned what a ticket is: every
    child would then re-fingerprint on being renamed, and `decompose` invents these names.
    """
    record = _Agent()
    run = _run(repository, tmp_path, base, _agent(record))
    role = _role("implement it", read_only=True)

    assert await run.worktree("T-01").step("implement", role) == Summary("implement it #0")
    assert await run.worktree("banana").step("implement", role) == Summary("implement it #0")

    (named,) = _entries(tmp_path, "implement", "T-01")
    (renamed,) = _entries(tmp_path, "implement", "banana")
    assert named.name == renamed.name, (
        "two namespaces running one step against one head recorded it under two digests, so the "
        "namespace is a fingerprint term - and renaming a ticket would re-run every step under it"
    )
    assert named.read_bytes() == renamed.read_bytes()
    assert (_trees_dir(tmp_path) / "banana").is_dir()
    assert "refs/heads/agl/_work/auth/banana" in _branches(repository)
