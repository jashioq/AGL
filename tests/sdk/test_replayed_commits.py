"""What a replayed step leaves behind: its recorded commit on its checkout and its branch.

A step that replays hands back its recorded result and makes its recorded head the head its `Run`
goes on from. That head is a commit, and the checkout and the branch have to hold it, or the next
landing merges a branch without it, the next verify builds a tree without it, and a run that ends
there ends with the commit on no branch at all. Against the checkout's `HEAD` a recorded head is one
of three things:

- **ahead**: the checkout's `HEAD` is a strict ancestor of it. AGL moves the checkout and its branch
  forward to it, as the live step's commit did, before the workflow carries on.
- **at or past**: it is the checkout's `HEAD` or an ancestor of it. Nothing moves, and uncommitted
  work in the checkout stays where it is.
- **diverged**: neither. The step runs again instead of replaying, and so does a step whose
  recorded commit the repository no longer holds. Running again is a miss like any other: the
  checkout and its branch go back to the head the `Run` has recorded, and the agent works there.

A replay still never runs an agent. The three cases of the brief come first, each ending with the
next step's commit on its branch: a step that ran again with the same result and the step after it
replayed ("Read first" 2 of the resume-safety report), the same through a landing's verdict, and
the same through a record written before verifies were recorded. All of it is over real git,
because what is lost is a commit on a branch; `test_journal_walk.py` holds the fakes' side.
"""

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
import pytest
from agl import testing
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.shell.fake import FakeVerifier
from agl.config import container
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.tree_layout import TreesRoot
from agl.ports.verifier import Verifier, VerifierOutcome
from agl.sdk import (
    Claude,
    Restriction,
    Role,
    Run,
    Workflow,
    arg,
    describe,
    reporting_tool,
    role,
    workflow,
)
from agl.sdk._engine.services import Services
from agl.testing import AgentTask, Call, Reply

LABEL: Final = "test"
SCOPE: Final = RunScope(ProjectName("project"), RunLabel(LABEL))
BRANCH: Final = f"agl/{LABEL}"
FIXER: Final = "fix"
FIXER_BRANCH: Final = f"agl/_work/{LABEL}/{FIXER}"

BUILD: Final = "make test"
CHECK: Final = "make check"

# What the last line of `implement_and_check` asks the checkout, once the workflow has carried on.
OBSERVE: Final = "observe"

REQUEST: Final = "add a --verbose flag"
FINDING: Final = "the flag is parsed and never read"
# What a reviewer that judges by the build finds once the build passes.
LATER: Final = "the flag is read and never documented"
FEATURE: Final = "feature.txt"
FIX: Final = "fix.txt"

FIRST: Final = "do what was asked"
FIXED: Final = "fix what the review found"

# The step name a verify's entry is filed under, spelled out rather than imported from the journal.
VERIFY: Final = "run.verify"

# --- the workflows ------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Review:
    """What the review reports through its tool, as the docs example's own `Review` does."""

    findings: list[str] = describe("what is wrong, one item per finding, each naming its file")

record_review = reporting_tool(
    "record_review",
    "Record what the review found. Call it exactly once, at the end, even with no findings.",
    Review,
)

@role(model=Claude.OPUS, accepts=(str, Review))
def implementer() -> Role[None]:
    """The docs example's implementer, with its prompt written inline."""
    return Role(
        name="implement",
        instructions="Make this change: {{str}}\n\nThe last review found: {{Review}}",
    )

@role(model=Claude.OPUS, accepts=(str, VerifierOutcome))
def reviewer() -> Role[Review]:
    """The docs example's reviewer: read-only, and handed a build's outcome."""
    return Role(
        name="review",
        instructions="Review the last commit against: {{str}}\n\nThe build: {{VerifierOutcome}}",
        restrictions={Restriction.NO_FILE_WRITES, Restriction.NO_VCS_WRITES},
        tools=(record_review,),
    )

@dataclass(frozen=True, slots=True)
class Parameters:
    """The docs example's parameters."""

    request: str = arg("-r", "--request", help="what you want done")

implementing = implementer()
reviewing = reviewer()

@workflow
async def implement_and_check(run: Run[Parameters]) -> None:
    """The shape of `tests/docs/implement_and_check`, and a last look at the checkout."""
    request = run.params.request
    await run.step(implementing, request, commit=FIRST)
    checked = await run.verify(run.config["build"])
    review = await run.step(reviewing, request, checked)
    if review.findings:
        await run.step(implementing, request, review, commit=FIXED)
    await run.verify(OBSERVE)

@workflow
async def lands_then_fixes(run: Run[Parameters]) -> None:
    """One child's work lands, and a second child reviews the landing's verdict and fixes it."""
    request = run.params.request
    first = run.worktree("implement")
    await first.step(implementing, request, commit=FIRST)
    landing = await first.integrate()
    fixer = run.worktree(FIXER)
    review = await fixer.step(reviewing, request, landing.verdict)
    if review.findings:
        await fixer.step(implementing, request, review, commit=FIXED)
    await fixer.integrate()

# --- walking them over real git -----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Checkout:
    """Where a checkout stood when `OBSERVE` ran in it: its HEAD, what `git status` said, whether
    the index differs from HEAD, and whether the fix is in its working tree."""

    head: str

    status: str

    staged: bool

    fixed: bool

class _Build(Verifier):
    """The build, measuring the checkout it is run in: it passes once the fix is there, as a real
    one does. `OBSERVE` answers where the checkout stands instead."""

    def __init__(self) -> None:
        self.runs = 0
        self.observed: list[Checkout] = []

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        if command == OBSERVE:
            self.observed.append(_observed(workdir))
            return VerifierOutcome(passed=True, status=0, output="")
        self.runs += 1
        if (workdir / FIX).exists():
            return VerifierOutcome(passed=True, status=0, output="all passed\n")
        return VerifierOutcome(passed=False, status=1, output="1 failed\n")

class _Timed(_Build):
    """A build gate that passes and prints how long it took, so no two runs answer alike."""

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        self.runs += 1
        return VerifierOutcome(passed=True, status=0, output=f"built in {self.runs}s\n")

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

def _agent(seen: list[str], *, judging: bool) -> testing.Agent:
    """Implements, reviews with one finding, and fixes what it was told. The finding is the same
    every time, unless `judging` has it follow what the build it was handed says."""

    def agent(task: AgentTask) -> Reply:
        if any(offered.name == record_review.name for offered in task.tools):
            seen.append("review")
            found = LATER if judging and "all passed" in task.instructions else FINDING
            return Reply(calls=[Call(record_review.name, {"findings": [found]})])
        if FINDING in task.instructions:
            seen.append("fix")
            (task.workspace / FIX).write_bytes(b"the flag, read\n")
        elif LATER in task.instructions:
            seen.append("fix")
            (task.workspace / FIX).write_bytes(b"the flag, documented\n")
        else:
            seen.append("implement")
            (task.workspace / FEATURE).write_bytes(b"the flag\n")
        return Reply(says="done")

    return agent

def _services(
    root: Path, repository: Path, seen: list[str], *, build: str = BUILD, judging: bool = False
) -> Services:
    """The fakes' agent, writing down what it did in `seen`, over real git and a ledger on disk
    under `root`, with `build` as the project's build command."""
    trees = TreesRoot(root / "trees")
    fakes = container.fakes(trees, config={"build": build}, agent=_agent(seen, judging=judging))
    return replace(
        fakes.services,
        store=FilesystemStore(AglHome(root / "home")),
        workspaces=GitWorkspaceProvider(repository, trees),
        history=GitHistory(repository),
        integrator=GitIntegrator(repository),
    )

@dataclass(frozen=True, slots=True)
class Walked:
    """What one walk ran: the agents in order, and the entries it wrote, by step name."""

    agents: list[str]

    recorded: list[str]

async def _walked(
    repository: Path,
    root: Path,
    flow: Workflow[Parameters],
    verifier: Verifier,
    *,
    resume: bool,
    command: str = BUILD,
    interrupt_after: int | None = None,
    before_verifies: bool = False,
    judging: bool = False,
) -> Walked:
    """One walk of `flow` through `agl.testing`, run or resumed. `before_verifies` writes the
    ledger as AGL did before verifies were recorded."""
    seen: list[str] = []
    services = _services(root, repository, seen, build=command, judging=judging)
    store = _AsBefore(services.store) if before_verifies else services.store
    fakes = container.fakes(TreesRoot(root / "trees"))
    harness = testing.over(
        replace(fakes, services=replace(services, store=store, verifier=verifier), store=store)
    )
    if resume:
        await harness.resume(flow, interrupt_after=interrupt_after)
    else:
        await harness.run(flow, "-r", REQUEST, interrupt_after=interrupt_after)
    return Walked(seen, [entry.step for entry in harness.recorded])

async def _opened(services: Services, base: str) -> Run[None]:
    """One root `Run` with its checkout opened first, as `api._walk` opens it. A second one over
    the same services is a resume: the same ledger and checkout, and a fresh count of steps."""
    await services.workspaces.open(SCOPE.label, None, base)
    return Run(params=None, services=services, scope=SCOPE, base=base)

def _git(cwd: Path, *argv: str) -> str:
    """Run git for the fixture and the assertions, raw, so no adapter answers for itself."""
    return subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()

def _answers(cwd: Path, *argv: str) -> bool:
    """Whether a git question answered yes, by its exit status."""
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, check=False).returncode == 0

def _observed(checkout: Path) -> Checkout:
    """Where `checkout` stands, read with git and the file system."""
    return Checkout(
        head=_git(checkout, "rev-parse", "HEAD"),
        status=_git(checkout, "status", "--porcelain", "--untracked-files=all"),
        staged=not _answers(checkout, "diff", "--cached", "--quiet"),
        fixed=(checkout / FIX).is_file(),
    )

@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit, and no configuration from this machine."""
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL replay")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "README.md").write_bytes(b"seed\n")
    _git(work, "add", "README.md")
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work

# --- the brief's three cases --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_fix_replayed_after_its_review_ran_again_stays_on_the_branch(
    repository: Path, tmp_path: Path
) -> None:
    """"Read first" 2 of the resume-safety report. The build command changed between the walks,
    so the verify runs again, on the checkout at the fix, and the build passes where it failed.
    The review takes that outcome, misses, and is restored to the first commit, and runs again
    with the same findings; the fix then replays. The fix's commit has to come back onto the
    checkout and the branch before the workflow's last line looks at the checkout."""
    build = _Build()
    first = await _walked(
        repository, tmp_path, implement_and_check, build, resume=False, interrupt_after=4
    )
    fixed = _git(repository, "rev-parse", BRANCH)
    assert first == Walked(
        ["implement", "review", "fix"], ["implement", VERIFY, "review", "implement"]
    )
    assert _git(repository, "log", "-1", "--format=%s", fixed) == FIXED

    resumed = await _walked(
        repository, tmp_path, implement_and_check, build, resume=True, command=CHECK
    )

    assert resumed == Walked(["review"], [VERIFY, "review", VERIFY])
    assert build.observed == [Checkout(head=fixed, status="", staged=False, fixed=True)]
    assert _git(repository, "rev-parse", BRANCH) == fixed

@pytest.mark.asyncio
async def test_a_fix_replayed_after_a_review_of_a_landings_verdict_still_lands(
    repository: Path, tmp_path: Path
) -> None:
    """The same case through `Integration.verdict`, which is never recorded: on the resume the
    landing is tried again, its build gate prints another timing, and the review in the second
    child, handed that verdict, misses. Its restore takes the second child back to where it was
    cut, the review runs again with the same findings, and the fix replays. The second child's
    landing then has to carry the fix into the run's branch."""
    gate = _Timed()
    first = await _walked(
        repository, tmp_path, lands_then_fixes, gate, resume=False, interrupt_after=3
    )
    fixed = _git(repository, "rev-parse", FIXER_BRANCH)
    assert first.agents == ["implement", "review", "fix"]
    assert _git(repository, "log", "-1", "--format=%s", fixed) == FIXED
    assert not _answers(repository, "merge-base", "--is-ancestor", fixed, BRANCH)

    resumed = await _walked(repository, tmp_path, lands_then_fixes, gate, resume=True)

    assert resumed.agents == ["review"]
    assert _answers(repository, "merge-base", "--is-ancestor", fixed, BRANCH)
    assert _git(repository, "show", f"{BRANCH}:{FIX}") == "the flag, read"

@pytest.mark.asyncio
async def test_a_record_from_before_verifies_were_recorded_resumes_with_the_fix_on_the_branch(
    repository: Path, tmp_path: Path
) -> None:
    """The same case through a ledger AGL wrote before it recorded verifies: the resume finds no
    outcome for the build, runs it on the checkout at the fix, and the review misses."""
    build = _Build()
    first = await _walked(
        repository,
        tmp_path,
        implement_and_check,
        build,
        resume=False,
        interrupt_after=4,
        before_verifies=True,
    )
    fixed = _git(repository, "rev-parse", BRANCH)
    assert first.agents == ["implement", "review", "fix"]
    assert _git(repository, "log", "-1", "--format=%s", fixed) == FIXED

    resumed = await _walked(repository, tmp_path, implement_and_check, build, resume=True)

    assert build.runs == 2, "the resume found the build's outcome, so nothing here is old"
    assert resumed == Walked(["review"], [VERIFY, "review", VERIFY])
    assert build.observed == [Checkout(head=fixed, status="", staged=False, fixed=True)]
    assert _git(repository, "rev-parse", BRANCH) == fixed

# --- at or past, diverged, and gone -------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_replay_at_or_behind_the_checkouts_head_moves_nothing_and_keeps_uncommitted_work(
    repository: Path, tmp_path: Path
) -> None:
    """The first step's recorded head is behind the checkout, which stands at the second's. Both
    replay and neither moves anything: the branch, the reflog, an edit nobody committed and a file
    nobody added are all where the first walk and the person after it left them."""
    seen: list[str] = []
    services = _services(tmp_path, repository, seen)
    base = _git(repository, "rev-parse", "HEAD")
    checkout = tmp_path / "trees" / LABEL / "_base"
    first = await _opened(services, base)
    await first.step(implementing, REQUEST, commit=FIRST)
    await first.step(implementing, REQUEST, Review(findings=[FINDING]), commit=FIXED)
    fixed = _git(repository, "rev-parse", BRANCH)
    (checkout / FEATURE).write_bytes(b"edited, and nobody committed it\n")
    (checkout / "notes.txt").write_bytes(b"added, and nobody committed it\n")
    reflog = _git(checkout, "reflog", "--format=%H %gs")
    seen.clear()

    resumed = await _opened(services, base)
    await resumed.step(implementing, REQUEST, commit=FIRST)
    await resumed.step(implementing, REQUEST, Review(findings=[FINDING]), commit=FIXED)

    assert seen == []
    assert _git(repository, "rev-parse", BRANCH) == fixed
    assert _git(checkout, "reflog", "--format=%H %gs") == reflog
    assert _git(checkout, "status", "--porcelain", "--untracked-files=all").splitlines() == [
        f"M {FEATURE}",
        "?? notes.txt",
    ]

@pytest.mark.asyncio
async def test_a_fix_whose_recorded_commit_diverged_from_the_checkout_runs_again_instead(
    repository: Path, tmp_path: Path
) -> None:
    """A replay meets a diverged checkout with nobody touching the repository, once an input comes
    back to a value an earlier walk recorded. The build command goes from "make test" to "make
    check" and back, so the review judges a red build, a green one, then the red one again. The
    third walk's review replays the first walk's findings, and the fix they lead to is the first
    walk's too, but the checkout carries the second walk's fix, on a line the first walk's commit
    is not on. The fix runs again from the first commit, and the second walk's fix leaves the
    branch."""
    gate = FakeVerifier()
    gate.answers(BUILD, passed=False, output="1 failed\n")
    gate.answers(CHECK, passed=True, output="all passed\n")
    first = await _walked(
        repository,
        tmp_path,
        implement_and_check,
        gate,
        resume=False,
        interrupt_after=4,
        judging=True,
    )
    started = _git(repository, "rev-parse", f"{BRANCH}^")
    second = await _walked(
        repository,
        tmp_path,
        implement_and_check,
        gate,
        resume=True,
        command=CHECK,
        interrupt_after=3,
        judging=True,
    )
    elsewhere = _git(repository, "rev-parse", BRANCH)
    assert (first.agents, second.agents) == (["implement", "review", "fix"], ["review", "fix"])
    assert _git(repository, "show", f"{BRANCH}:{FIX}") == "the flag, documented"

    third = await _walked(
        repository, tmp_path, implement_and_check, gate, resume=True, judging=True
    )

    assert third == Walked(["fix"], [VERIFY, "implement", VERIFY])
    assert _git(repository, "show", f"{BRANCH}:{FIX}") == "the flag, read"
    assert _git(repository, "rev-parse", f"{BRANCH}^") == started
    assert not _answers(repository, "merge-base", "--is-ancestor", elsewhere, BRANCH)

@pytest.mark.asyncio
async def test_a_step_whose_checkout_was_moved_to_another_line_runs_again_and_drops_it(
    repository: Path, tmp_path: Path
) -> None:
    """The other way to a diverged checkout: somebody resets the run's branch and commits their own
    work on it between the walks. The step runs again from the head the `Run` has recorded, and,
    as every miss does, takes the checkout and its branch back there first, so that commit leaves
    the branch."""
    seen: list[str] = []
    services = _services(tmp_path, repository, seen)
    base = _git(repository, "rev-parse", "HEAD")
    checkout = tmp_path / "trees" / LABEL / "_base"
    await (await _opened(services, base)).step(implementing, REQUEST, commit=FIRST)
    _git(checkout, "reset", "-q", "--hard", base)
    (checkout / "other.txt").write_bytes(b"somebody else's work\n")
    _git(checkout, "add", "other.txt")
    _git(checkout, "commit", "-q", "-m", "somebody else's work")
    moved = _git(checkout, "rev-parse", "HEAD")
    seen.clear()

    await (await _opened(services, base)).step(implementing, REQUEST, commit=FIRST)

    assert seen == ["implement"]
    assert _git(repository, "rev-parse", f"{BRANCH}^") == base
    assert _git(repository, "log", "-1", "--format=%s", BRANCH) == FIRST
    assert not _answers(repository, "merge-base", "--is-ancestor", moved, BRANCH)
    assert not (checkout / "other.txt").exists()

@pytest.mark.asyncio
async def test_a_step_whose_recorded_commit_git_collected_runs_again_and_then_replays(
    repository: Path, tmp_path: Path
) -> None:
    """The fix's commit is taken off the branch and collected, so the repository no longer holds
    it. The resume replays the first step and runs the fix again, and the walk after that replays
    both, from the entry the second walk wrote."""
    seen: list[str] = []
    services = _services(tmp_path, repository, seen)
    base = _git(repository, "rev-parse", "HEAD")
    checkout = tmp_path / "trees" / LABEL / "_base"
    first = await _opened(services, base)
    await first.step(implementing, REQUEST, commit=FIRST)
    await first.step(implementing, REQUEST, Review(findings=[FINDING]), commit=FIXED)
    collected = _git(repository, "rev-parse", BRANCH)
    _git(checkout, "reset", "-q", "--hard", f"{BRANCH}^")
    _git(repository, "reflog", "expire", "--expire-unreachable=now", "--all")
    _git(repository, "gc", "-q", "--prune=now")
    assert not _answers(repository, "cat-file", "-e", f"{collected}^{{commit}}")
    seen.clear()

    resumed = await _opened(services, base)
    await resumed.step(implementing, REQUEST, commit=FIRST)
    await resumed.step(implementing, REQUEST, Review(findings=[FINDING]), commit=FIXED)
    again = list(seen)
    seen.clear()
    last = await _opened(services, base)
    await last.step(implementing, REQUEST, commit=FIRST)
    await last.step(implementing, REQUEST, Review(findings=[FINDING]), commit=FIXED)

    assert (again, seen) == (["fix"], [])
    assert _git(repository, "log", "-1", "--format=%s", BRANCH) == FIXED
    assert _git(repository, "show", f"{BRANCH}:{FIX}") == "the flag, read"
