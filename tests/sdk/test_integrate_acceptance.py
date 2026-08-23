"""Stage 14's acceptance criteria, established from outside the implementation that claims them.

A second suite over `run.integrate()`, written against the plan rather than against
`sdk/_engine/integration.py`, and deliberately not a re-reading of
`tests/sdk/test_run_integrate.py`. Where that file and this one make the same claim, this one makes
it in a shape that file structurally cannot: **through real git**, **across a process boundary**, or
**by observing the serialization itself** rather than the state it leaves behind. Nothing here is a
duplicate for the sake of a second green tick; every test below either covers a criterion in a
stronger medium or covers something the implementer's own suite has no arrangement for.

The five criteria, and what discharges each:

  1. **Concurrent children serialize into one `_base`.**
     `test_concurrent_landings_into_one_target_never_overlap` watches the two sections of a landing
     that can be seen from a port - `Integrator.land` and the merge gate - and asserts that one
     child's are never interleaved with another's. A suite that checked only the final tree would
     pass against an implementation with no lease at all, because the fakes are fast enough that
     three landings can complete in sequence by luck.
     `test_three_children_land_into_one_real_base_and_all_three_survive` then does it against real
     git, where a landing is a dozen subprocesses and the interleaving is not a matter of luck.
  2. **A failing gate leaves the branch unmerged and the tree clean.**
     `test_a_red_gate_leaves_a_real_target_unmerged_and_its_tree_clean` asks git itself: the branch
     tip, `merge-base --is-ancestor`, `status --porcelain`, and the absence of `MERGE_HEAD`. A fake
     verifier that starts no process cannot leave a build artifact behind, and a fake workspace's
     "clean" is a dict comparison; both are the thing being claimed.
  3. **The parent's `last_good` advances - on the MISS path.**
     `test_a_landed_child_survives_the_parents_next_fingerprint_miss` lands a child, then makes the
     parent miss, and asserts the landed *contents* and the landed *ancestry* are both still there
     after the pre-run `reset --hard` + `clean -fd`. Real git, because that is the primitive whose
     effect is being survived. §3.6 calls forgetting the advance one of the two paths in AGL that
     destroy work rather than costing a re-run.
  4. **A resumed run finds a hold it did not take, and does not exit 70.**
     `test_a_second_process_meets_the_hold_the_first_one_died_holding` and its `abort` twin, through
     `instruments/landing.py`. Two real processes, the first killed with `os._exit` while holding a
     conflicted merge, the second re-driving the same workflow over the same `AGL_HOME` and the same
     repository - because `api.resume` is 16.2 and raises. The exit status is mapped through
     `cli/exit_codes.exit_status`, so "not exit 70" is the number the CLI would have printed.
  5. **Root `integrate()` raises.**
     `test_the_root_refuses_to_integrate_with_the_error_the_plan_asks_for` pins the class, the exit
     status it resolves to, and the distinction §3.9 makes: `main` is unaddressable, not protected.

Beyond the five, and each of these is a question the implementer's suite has no arrangement to ask:

  * whether a second landing into a target is stopped while a conflict is unresolved, and whether a
    *step* in that namespace is stopped too - the direction that matters, because a conflict is held
    across a human's afternoon;
  * whether the lease and the step lock come back when a workflow **raises** mid-conflict, and
    whether a `Stop` subclass still resolves to 7 now that there is a `try` in `api.run`;
  * whether a landing concluded by a person's own hand goes through the build gate - and what the
    gate's revert then does to that person's resolution, which is the one thing here that turned up
    a cost the plan does not write down;
  * whether a conflict held in one target stops a landing into another, and whether `integrate()`
    works at all three deep, into a namespace that is not the run's own `_base`;
  * whether an integration replays - kill a run that has landed, resume it, and compare the whole
    world against a run that was never interrupted (§3.6's own contract-test shape) - and whether
    integrating one child twice lands it twice;
  * whether a `land` that raises, a `retry` whose gate raises, or a landing cancelled while it
    queues leaves the target leased by a call that is over.

**Where the fakes are used and where they are not.** A claim about AGL's own concurrency - the
lease, the step lock, what run exit gives back - is a claim about `asyncio` objects in one process,
and the fakes are the right medium: they are fast, they collide honestly (`FakeIntegrator` runs a
real three-way merge) and nothing about git is in the claim. A claim about what is *left behind* -
an unmerged branch, a clean tree, a surviving commit, a hold that outlives its process - is a claim
about a repository, and there the fake is the thing under test wearing the answer: `adapters/git/
fake.py` says outright that a hold surviving a process is unreachable for it. So criteria 2, 3 and 4
are asked of real git, in this file's own `_World`, built the way
`tests/sdk/test_kill_and_resume.py` builds one.

Fixtures are duplicated from the neighbouring files rather than imported, for their reason: nothing
under `tests/` imports another test module, and a shared fixture module would make one file's
arrangement another file's dependency.

Named `test_integrate_acceptance.py`: `tests/` carries no `__init__.py` - see `tests/conftest.py` -
so pytest's module names are the bare filenames and every one has to be unique.
"""

import asyncio
import itertools
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

import pytest

from agl import api
from agl.adapters.claude_code.fake import Conversation, FakeAgentRunner, Script
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.rich_terminal.headless import HeadlessTerminal
from agl.adapters.routing import RoutingAgentRunner
from agl.adapters.system_clock import SystemClock
from agl.cli.exit_codes import exit_status
from agl.config import container, registry
from agl.ports.agent import AgentOutcome, Claude, Provider, Restriction, StopReason
from agl.ports.errors import (
    InputError,
    InternalError,
    Stop,
    UpstreamUnavailable,
    UpstreamUnexpected,
)
from agl.ports.history import History
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.integration import IntegrationOutcome, Integrator
from agl.ports.tree_layout import TreesRoot, base_worktree, run_branch, worktree_branch
from agl.ports.verifier import Verifier, VerifierOutcome
from agl.ports.workspace import Workspace
from agl.sdk._engine.services import Services
from agl.sdk.roles import Role
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run, workflow
from instruments.landing import (
    CHILD,
    CHILD_TEXT,
    CONTESTED,
    PARENT_TEXT,
    RESOLVED,
    Config,
    driver_path,
)

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# The three children, and the one file each of them adds. Distinct files on purpose: criterion 1 is
# about landings not overlapping, and two children colliding would confuse "did not overlap" with
# "would not combine".
CHILDREN: Final = ("T-01", "T-02", "T-03")
SEEDED: Final = "src/a.txt"
SEED: Final = b"the user's own work\n"
PARENT_FILE: Final = "src/parent.py"
PARENT_BODY: Final = b"what the parent's own step wrote\n"

# The two bodies of `CONTESTED`, taken from `instruments/landing.py` so that the fakes-side tests
# here and the two-process tests at the bottom collide over one pair of values rather than two that
# could drift. Twelve lines apiece and not one shared, because a merge that combined them would be a
# merge that guessed - `tests/contracts/_integration_targets.py` argues why a suite has to *cause* a
# conflict rather than declare one.
PARENT_SIDE: Final = PARENT_TEXT.encode()
CHILD_SIDE: Final = CHILD_TEXT.encode()

# The gate's vocabulary. `ARTIFACT` and `LEAVINGS` are what a build tool drops into the directory it
# was pointed at - one file and one directory, because `clean -fd` has to take both - and `RED` is
# what a person would be reading on the conflict screen.
ARTIFACT: Final = "build.log"
LEAVINGS: Final = ".build-cache"
RED: Final = "1 test failed: the two changes disagree about what `parse` returns\n"

# How long something that should not be waiting is given before the test calls it a lease nobody
# gave back. Never spent on a green run.
_LIVENESS: Final = 30.0

# How long the tests that prove a negative wait before concluding that a landing, or a step, really
# is queued behind something. Spent on every green run, because the wait is the proof. Short,
# because what it has to outlast is one dispatch against fakes.
_SERIALIZED: Final = 1.0

# How many event-loop turns an observed section of a landing yields for before it does its work. The
# whole of what makes criterion 1's log able to show an interleaving: an implementation with no
# lease would have every gathered child inside `land` at once within this many turns, and one with a
# lease has them queued on a lock that these turns cannot advance.
_TURNS: Final = 8


# --- the agent, the roles, and what each of them writes -------------------------------------------


@dataclass(frozen=True)
class Summary:
    """A reporting payload: one string, which is the whole of what these agents have to say."""

    text: str


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes no flags - `api.run` still parses an empty argv against it."""


REPORT: Final = reporting_tool("report", "report what you did", Summary)


def _role(instructions: str) -> Role[Summary]:
    """A reporting role that may commit: its result is `REPORT`'s payload, read back as a
    `Summary`."""
    return Role(
        instructions=instructions,
        model=Claude.SONNET,
        restrictions=set[Restriction](),
        tools=(REPORT,),
    )


# Module-level, which is what a `Role` is (§3.3), and distinct per writer: the script below decides
# what to write from the instructions it was handed, so two roles sharing a string would be two
# namespaces writing one file.
PREPARE: Final = _role("prepare the parent")
COLLIDE: Final = _role("implement over the same file the parent touched")
REVIEW: Final = _role("review the target's worktree")
LOOK_AGAIN: Final = _role("review the target's worktree a second time")
RECORD: Final = _role("record what the run has landed so far")
BUILDS: Final = {name: _role(f"implement {name}") for name in CHILDREN}


def _agent(recorded: list[str] | None = None) -> Script:
    """One agent for every role here: write what this prompt is meant to write, then report.

    `recorded` is where a test learns that a step **missed** - the whole of what a replay hit is, in
    §3.6's own words, is that the worker was not called - and it is a plain list because the port
    hands a fake no recorder and `adapters/shell/fake.py` argues at length why it should not.

    Writing to `task.workspace` with the stdlib is the script's own code and not the adapter's,
    which is what lets a fake agent leave real files in a real directory for `commit=` to record.
    """

    async def _script(conversation: Conversation) -> AgentOutcome:
        said = conversation.task.instructions
        if recorded is not None:
            recorded.append(said)
        for name, content in _WRITES.get(said, {}).items():
            where = conversation.task.workspace / name
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_bytes(content)
        await conversation.call(REPORT.name, {"text": said})
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script


def _work(name: str) -> bytes:
    """What child `name`'s agent puts in its own file. Distinct per child, so a target holding two
    of them is holding two different things rather than one written twice."""
    return f"the work {name} did\n".encode()


def _file(name: str) -> str:
    """Where child `name`'s work goes - one file per child, none of them shared."""
    return f"src/{name}.py"


# Keyed on the prompt, because that is the only thing the port hands a script that says which step
# this is: `AgentTask` carries no namespace and no step name, deliberately (§3.3).
_WRITES: Final[Mapping[str, Mapping[str, bytes]]] = {
    PREPARE.instructions: {PARENT_FILE: PARENT_BODY, CONTESTED: PARENT_SIDE},
    COLLIDE.instructions: {CONTESTED: CHILD_SIDE},
    REVIEW.instructions: {"scratch/notes.md": b"half a thought\n"},
    LOOK_AGAIN.instructions: {"scratch/more.md": b"and another\n"},
    RECORD.instructions: {"notes/after.md": b"what the run has landed so far\n"},
    **{role.instructions: {_file(name): _work(name)} for name, role in BUILDS.items()},
}


# --- the all-fakes bundle, for the claims that are about AGL's own concurrency --------------------


def _harness(tmp_path: Path, recorded: list[str] | None = None) -> container.FakeServices:
    """The all-fakes bundle: no network, no git, no process, one repository behind all three."""
    return container.fakes(
        TreesRoot(tmp_path / "trees"),
        # `CONTESTED` is deliberately **not** seeded: the parent and one child each create it, from
        # a base in which it does not exist and where neither has seen the other's version.
        files={SEEDED: SEED},
        claude=_agent(recorded),
    )


async def _base_of(history: History) -> str:
    """The pinned commit a run is cut from - `RunSpec.base_sha`'s shape, asked through the port."""
    return await history.resolve(await history.default_ref())


async def _tree(
    harness: container.FakeServices,
    *,
    verifier: Verifier | None = None,
    integrator: Integrator | None = None,
) -> Run[None]:
    """One root `Run` over this bundle, optionally with two of its ports wrapped or swapped.

    `Services` is a frozen dataclass of ports and a string, so a substitution is `replace` and
    nothing else - every other field is the *same object* the bundle holds, which is what keeps
    `harness.repository` and `harness.store` readable afterwards. `container.fakes()` deliberately
    has no parameter for either, and adding one so that a test could watch a landing would be the
    composition root growing a member for this file's benefit.
    """
    services = harness.services
    if verifier is not None:
        services = replace(services, verifier=verifier)
    if integrator is not None:
        services = replace(services, integrator=integrator)
    return Run(params=None, services=services, scope=SCOPE, base=await _base_of(services.history))


async def _head(harness: container.FakeServices, namespace: Namespace | None) -> str:
    """Where one checkout's line of work is now, asked through the port rather than of a dict.

    `WorkspaceProvider.open` is idempotent by contract, so this reopens what the run already
    provisioned and cuts nothing. `None` is the run's own `_base` - the target every landing goes
    into.
    """
    workspaces = harness.services.workspaces
    opened = await workspaces.open(LABEL, namespace, await _base_of(harness.services.history))
    return await opened.head()


def _fake_target(tmp_path: Path) -> Path:
    """`.trees/auth/_base/` - spelled out rather than composed through `tree_layout`, because a test
    that asked the layout where a checkout should be and then looked there would agree with the
    layout whatever either of them said."""
    return tmp_path / "trees" / "auth" / "_base"


# --- watching the serialization itself ------------------------------------------------------------


class _Watcher:
    """Who was inside a landing, where, and in what order - criterion 1's whole instrument.

    A landing is not one call, so there is nothing to time. What there is, is two moments inside it
    that a *port* can see: `Integrator.land`, which is where the work is combined, and
    `Verifier.verify`, which is the merge gate §3.4 puts inside the lease and calls "serial because
    the merge queue serializes it, and it must be". Both are recorded here against the target they
    were about and the task that asked, and each yields the event loop for `_TURNS` turns before
    doing anything - which is what turns "did not overlap" into a question with a wrong answer
    available. Without the yields, three landings against in-memory fakes can complete one after
    another with no lease anywhere, and a log of them would look identical either way.
    """

    def __init__(self) -> None:
        self.log: list[tuple[str, str, str]] = []

    async def inside(self, target: Path, section: str) -> None:
        """Record that this task is inside `section` of a landing into `target`, and yield."""
        task = asyncio.current_task()
        self.log.append((str(target), "?" if task is None else task.get_name(), section))
        for _ in range(_TURNS):
            await asyncio.sleep(0)

    def visitors(self, target: Path) -> list[str]:
        """The tasks that entered an observed section of a landing into `target`, in order."""
        return [task for where, task, _ in self.log if where == str(target)]


class _Watched(Integrator):
    """An `Integrator` that says when a landing starts, and otherwise is the one it was given.

    A wrapper rather than a second implementation, because what is being observed is the framework's
    ordering and not the adapter's answers: every outcome below is the real one, so a test that
    watches the order still asserts the landing that actually happened.
    """

    def __init__(self, real: Integrator, watcher: _Watcher) -> None:
        self._real = real
        self._watcher = watcher

    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        await self._watcher.inside(target.path, "land")
        return await self._real.land(source, target)

    async def retry(self, target: Workspace) -> IntegrationOutcome:
        await self._watcher.inside(target.path, "retry")
        return await self._real.retry(target)

    async def abort(self, target: Workspace) -> None:
        await self._real.abort(target)


class _Gate(Verifier):
    """A `Verifier` that answers a fixed verdict, says where and when it ran, and can leave a mess.

    Three things `FakeVerifier` cannot do, and none of them is a defect in it. It "accepts `workdir`
    and never reads it", so where the gate ran is exactly the fact that fake was designed not to
    have. It starts nothing, so it leaves nothing behind, where a real build tool writes a log and a
    cache directory into the tree it was pointed at. And it cannot be watched, because a dict lookup
    has no duration to be inside of.
    """

    def __init__(
        self, *, passed: bool, watcher: _Watcher | None = None, leaves: bool = False
    ) -> None:
        self.calls: list[tuple[str, Path]] = []
        # Public and mutable, which is the one thing `FakeVerifier.answers` can do that this cannot
        # say in a constructor: "fix the build and press retry" is a *sequence*, and a gate whose
        # verdict was fixed for the life of the object could only ever test one half of it.
        self.passed = passed
        # Raise once instead of answering, and clear itself. `ports/verifier.py` promises a failing
        # build is an outcome and not an exception, and the one thing that genuinely raises is a
        # shell that could not be started at all - `UpstreamUnavailable`, the case where nothing
        # ran. One landing meets it, the next does not, which is what an unavailable shell looks
        # like when somebody fixes their `PATH`.
        self.explodes = False
        self._watcher = watcher
        self._leaves = leaves

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        if self._watcher is not None:
            await self._watcher.inside(workdir, "gate")
        if self.explodes:
            self.explodes = False
            raise UpstreamUnavailable("no shell on this machine could start the build")
        self.calls.append((command, workdir))
        if self._leaves:
            (workdir / ARTIFACT).write_bytes(b"what the build printed\n")
            (workdir / LEAVINGS).mkdir(exist_ok=True)
            (workdir / LEAVINGS / "objects").write_bytes(b"and what it compiled\n")
        return VerifierOutcome(
            passed=self.passed, status=0 if self.passed else 1, output="" if self.passed else RED
        )


async def _landed_children(run: Run[None], names: Sequence[str]) -> None:
    """Give each named child a namespace and one commit of its own, before anything lands."""
    for name in names:
        child = run.worktree(name)
        await child.step("implement", BUILDS[name], commit=f"implement {name}")


# --- criterion 5: the root has no parent, and the refusal says which kind of refusal it is --------


@pytest.mark.asyncio
async def test_the_root_refuses_to_integrate_with_the_error_the_plan_asks_for(
    tmp_path: Path,
) -> None:
    """§3.3 and §3.9: `main` is **unaddressable rather than policy-protected**, and the class is the
    one that sends a workflow author to the line they wrote.

    Three claims, and the middle one is the reason this test exists beside the implementer's own.

    **The class is `InputError`.** What the caller supplied cannot be used and nothing was
    attempted.

    **The exit status is that class's, and 70 is the wrong answer.** §1.5's charge was that exit
    codes were meaningless, and §3.1 answers it with one table; a refusal whose *number* is 70 tells
    an operator to file a bug about a call a workflow author made on purpose. So this asks
    `cli/exit_codes.exit_status` - the function `cli/main.py` uses - rather than asserting a class
    and hoping the mapping agrees. Nothing in the framework's own suite reads the two together.

    **The message carries the distinction.** A refusal phrased as a permission - "AGL will not write
    to your branches" - invites the reader to go looking for the flag that lets it, and there is
    none to find: §3.9 puts every ref AGL touches under `agl/*`, so a `Run` has exactly one thing it
    could land into and the root has none of them. The words that carry that are what is asserted.

    Asked **after** the root has cut a child, deliberately: a run that has a parent-child tree in it
    is where a workflow author most plausibly reaches for `run.integrate()` on the wrong object, and
    an implementation that answered from a table of namespaces rather than from `_parent` could pass
    this on an empty run and fail here.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    child = run.worktree(CHILDREN[0])
    await child.step("implement", BUILDS[CHILDREN[0]], commit="implement T-01")

    with pytest.raises(InputError) as raised:
        await run.integrate()

    said = str(raised.value)
    assert exit_status(raised.value) == exit_status(InputError("")), (
        f"the root's refusal resolves to exit {exit_status(raised.value)}, which is not the status "
        f"`InputError` carries. §3.1 has one table and §1.5's whole charge is that a number nobody "
        f"can act on is worse than none - and 70 in particular tells an operator to file a bug "
        f"about a call a workflow author wrote on purpose"
    )
    assert exit_status(raised.value) != exit_status(InternalError("")), (
        "the root's refusal exits with `InternalError`'s status, which is `file a bug`"
    )
    assert "unaddressable" in said, (
        f"the refusal does not say the word: {said!r}. §3.3 and §3.9 make `main` unaddressable "
        f"rather than protected, and a refusal that reads as a policy sends the reader looking for "
        f"the setting that relaxes it"
    )
    assert "agl/*" in said, (
        "the refusal does not name the invariant it follows from - AGL never checks out or writes "
        "to any ref outside `agl/*` (§3.9) - so it reads as a rule rather than as a consequence"
    )
    assert await child.integrate() is not None, (
        "the child of that same root could not integrate either, so what was refused above is not "
        "`the root has no parent` but something about this run"
    )


# --- criterion 1: concurrent children serialize into one `_base` ---------------------------------


@pytest.mark.asyncio
async def test_concurrent_landings_into_one_target_never_overlap(tmp_path: Path) -> None:
    """§3.4: "landings into one target are serialised" - asserted about the *serialization* and not
    about the tree it leaves behind.

    **A suite that checked only the final state would pass against an implementation with no lease
    at all.** Three landings against in-memory fakes take microseconds each and nothing in them
    suspends for long; run them under `gather` with the lease deleted and they can still complete
    one after another, all three files present, every ancestry assertion green. The failure the
    lease prevents is a *race*, and a race that did not happen this time is not evidence.

    So this watches instead. A landing is not one call, but two moments inside it are visible from a
    port: `Integrator.land`, where the work is combined, and `Verifier.verify`, the merge gate §3.4
    places inside the lease and calls serial "because the merge queue serializes it, and it must be
    - it tests a combined state that exists only momentarily". Both are wrapped, both yield the
    event loop before doing their work, and the log they leave is the assertion: **every task's
    entries into that target are contiguous**. Interleaved is the failure, in the exact shape §3.4
    names - "if another item lands mid-build, the tree verified is not the tree being decided about,
    and a failure cannot be attributed".

    The yields are what make the wrong answer reachable: with no lease, all three tasks are inside
    `land` within one of them. With the lease, the other two are asleep on a lock that no number of
    turns can advance, so a correct implementation is unaffected by how many there are.

    The end state is asserted too, because a serialization that dropped a landing would satisfy the
    log: the parent's line of work must contain all three children, asked of `History` rather than
    of a directory, and all three files must be in the tree the gate ran in.
    """
    harness = _harness(tmp_path)
    watcher = _Watcher()
    run = await _tree(
        harness,
        verifier=_Gate(passed=True, watcher=watcher),
        integrator=_Watched(harness.services.integrator, watcher),
    )
    await _landed_children(run, CHILDREN)
    landed = {name: await _head(harness, Namespace(name)) for name in CHILDREN}

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            *(
                asyncio.create_task(run.worktree(name).integrate(), name=name)
                for name in CHILDREN
            )
        ),
        timeout=_LIVENESS,
    )

    visitors = watcher.visitors(_fake_target(tmp_path))
    blocks = [name for name, _ in itertools.groupby(visitors)]
    assert len(blocks) == len(set(visitors)), (
        f"two landings into one target overlapped: the order they were inside `land` and the merge "
        f"gate was {visitors}, which visits {blocks} - a task appearing in two blocks was inside a "
        f"landing that another task had already started and not finished. §3.4 serialises landings "
        f"into one target precisely so the gate decides about the tree it was handed; overlapped, "
        f"the combined state one build verified is not the one that was kept"
    )
    assert len(visitors) == 2 * len(CHILDREN), (
        f"the watcher saw {visitors}, and three landings owe six visits - one `land` and one gate "
        f"each. Fewer means a landing skipped the gate, which is the check §3.4 gives the framework"
    )
    assert [one.conflicted for one in outcomes] == [False] * len(CHILDREN), (
        f"children touching three different files did not all land: "
        f"{[one.conflict for one in outcomes]}"
    )
    settled = await _head(harness, None)
    for name, head in landed.items():
        assert await harness.services.history.contains(head, settled), (
            f"the target is at {settled!r}, which does not contain {name}'s work at {head!r}. All "
            f"three were told they had landed, so one landing was computed against a head another "
            f"had already moved past and the loser's work is simply not there"
        )
        assert (_fake_target(tmp_path) / _file(name)).read_bytes() == _work(name), (
            f"{name}'s file is missing or holds somebody else's work in the target's checkout, "
            f"which is the tree the gate ran in and the one the next step is handed"
        )


# --- the lease, past the point the implementer's own suite stops ----------------------------------


async def _held(
    tmp_path: Path, *, verifier: Verifier | None = None
) -> tuple[container.FakeServices, Run[None], Run[None], Run[None]]:
    """A run whose first child cannot land: the parent and that child both create `CONTESTED`.

    The child is opened **before** the parent's own step, so the two lines of work share a base in
    which the file does not exist and neither has seen the other's version - the shape
    `tests/contracts/_integration_targets.py` requires of a conflict a suite causes on purpose. A
    second child is prepared alongside, with work of its own that collides with nothing.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness, verifier=verifier)
    blocked = run.worktree(CHILDREN[0])
    spare = run.worktree(CHILDREN[1])
    await run.step("prepare", PREPARE, commit="prepare the parent")
    await blocked.step("implement", COLLIDE, commit="implement T-01")
    await spare.step("implement", BUILDS[CHILDREN[1]], commit="implement T-02")
    return harness, run, blocked, spare


@pytest.mark.asyncio
async def test_a_second_landing_waits_while_the_first_conflict_is_undecided(
    tmp_path: Path,
) -> None:
    """§3.4: the lease is held "from the moment an integration starts until its outcome is settled,
    conflict screen and all". The half that is a *negative*, and the one no state assertion reaches.

    A conflicted outcome goes back to the workflow with the target held mid-landing and the lease
    still taken, and stage 15's screen is put up while it is. So the interesting question is not
    what an abort puts back - the implementer's suite asks that - but whether anything at all stops
    a **second** child from landing into a target somebody is still deliberating over. Nothing else
    could: `Integrator.land` would answer the second child with the *first* child's collision, and a
    workflow would show a person a screen about files their two lines of work have never disagreed
    about.

    The wait is the assertion. Then the first conflict is aborted and the second landing goes on,
    which is what shows it was queued rather than broken.
    """
    harness, run, blocked, spare = await _held(tmp_path)
    first = await blocked.integrate()
    assert first.conflicted is True, "this test needs a target left holding a landing"

    second = asyncio.create_task(spare.integrate())
    finished, _ = await asyncio.wait({second}, timeout=_SERIALIZED)

    assert not finished, (
        "a second child landed into a target whose first landing is still unresolved. The lease is "
        "held across the workflow's own decision (§3.4), and without it this landing is offered "
        "into a held target - which `land` answers with somebody else's `Conflict`, sending a "
        "person to a screen about a collision that is not theirs"
    )

    await first.abort()
    outcome = await asyncio.wait_for(second, timeout=_LIVENESS)

    assert outcome.conflicted is False, (
        f"the queued landing failed once the lease came back: {outcome.conflict}. It was waiting, "
        f"not broken - the abort settles the first outcome and the next landing goes on"
    )
    assert (_fake_target(tmp_path) / _file(CHILDREN[1])).read_bytes() == _work(CHILDREN[1])
    assert await harness.services.history.contains(
        await _head(harness, Namespace(CHILDREN[1])), await _head(harness, None)
    )


@pytest.mark.asyncio
async def test_a_step_in_the_target_namespace_waits_while_a_conflict_is_undecided(
    tmp_path: Path,
) -> None:
    """"A target mid-landing is a tree no step may run in" - the direction the implementer's suite
    does not take.

    That suite parks a step and offers a landing, which proves the landing queues behind the step.
    The converse is the one that matters in life, because §3.4 holds the lease "across a human's
    deliberation" and a conflict screen can be up for an afternoon: while it is, the target's
    checkout is **full of a half-applied merge**. A step allowed to run in it would restore over the
    collision, hand its agent a tree nobody composed, and commit whatever came back under the
    parent's own message - none of which raises, and all of which §3.6's serialization lock exists
    to prevent one writer at a time.

    So a step in the parent is offered while its own child's conflict is undecided, and it must not
    complete. Aborting the conflict is what lets it through, which is also the assertion that the
    lease's release gives back **both** things it took: `Leases.claim` takes the lease and then the
    namespace's step lock, and a release that returned only the first would leave this step hanging
    for the life of the process with no error anywhere.
    """
    _, run, blocked, _ = await _held(tmp_path)
    conflict = await blocked.integrate()
    assert conflict.conflicted is True, "this test needs a target left holding a landing"

    step = asyncio.create_task(run.step("review", REVIEW))
    finished, _ = await asyncio.wait({step}, timeout=_SERIALIZED)

    assert not finished, (
        "a step ran in the parent's namespace while a landing into it was unresolved. The target's "
        "checkout is holding a half-applied merge at that moment, so this step restored over "
        "somebody's collision and its agent was handed a tree nothing composed"
    )

    await conflict.abort()
    said = await asyncio.wait_for(step, timeout=_LIVENESS)

    assert said.text == REVIEW.instructions, (
        "the queued step did not run to completion once the conflict was settled, so what the "
        "abort gave back was not the step lock the lease took"
    )


@pytest.mark.asyncio
async def test_a_conflict_held_in_one_target_does_not_stop_a_landing_into_another(
    tmp_path: Path,
) -> None:
    """§3.4: the lease "is scoped to this run's integration target, so a human deliberating in one
    run never blocks another" - and within one run, one target's deliberation must not stop another
    target's queue either.

    The arrangement is a tree three deep, which is also the only place `integrate()` is exercised
    against a target that is **not** the run's own `_base`: a middle namespace has no checkout until
    something asks for one, and `Steps.landing` is what provisions it. A grandchild's landing into
    that middle namespace conflicts and is left undecided; a top-level child then lands into the
    root, and must not wait for it.

    A lease keyed by anything coarser than the target - the run, or a single lock - passes every
    other test in this file and hangs here, with nothing raising and nothing to read.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    middle = run.worktree("middle")
    grandchild = middle.worktree("grandchild")
    spare = run.worktree(CHILDREN[2])
    await middle.step("prepare", PREPARE, commit="prepare the middle namespace")
    await grandchild.step("implement", COLLIDE, commit="implement over it")
    await spare.step("implement", BUILDS[CHILDREN[2]], commit="implement T-03")

    stuck = await grandchild.integrate()
    assert stuck.conflicted is True, "this test needs one target left holding a landing"

    outcome = await asyncio.wait_for(spare.integrate(), timeout=_LIVENESS)

    assert outcome.conflicted is False, (
        f"a landing into the root failed while another target was holding a conflict: "
        f"{outcome.conflict}"
    )
    assert (_fake_target(tmp_path) / _file(CHILDREN[2])).read_bytes() == _work(CHILDREN[2])
    assert stuck.conflicted is True, "the unrelated landing settled somebody else's conflict"
    await stuck.abort()


@pytest.mark.asyncio
async def test_a_nested_landing_advances_the_middle_namespace_so_its_own_landing_carries_it(
    tmp_path: Path,
) -> None:
    """Integration at depth, and the reason the advance is what makes it work at all.

    A grandchild lands into a middle namespace; the middle namespace then lands into the root. The
    second landing carries the first only if the middle namespace's *chain* moved when the
    grandchild went in - `Integrator.land` reads `source.branch`, and the branch moved, but
    everything the framework does around it is keyed on `last_good`. This is §3.6's advance seen
    from the one angle where it is load-bearing for correctness rather than for survival: not "the
    work is still there", but "the work is in what landed next".

    Nothing in the implementer's suite opens a namespace three deep, so nothing there asks whether a
    target that is not `_base` is provisioned, addressed and advanced like one.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    middle = run.worktree("middle")
    grandchild = middle.worktree("grandchild")
    await grandchild.step("implement", BUILDS[CHILDREN[0]], commit="implement T-01")
    built = await _head(harness, Namespace("grandchild"))

    inner = await grandchild.integrate()
    assert inner.conflicted is False, f"the nested landing did not go in: {inner.conflict}"
    outer = await middle.integrate()

    assert outer.conflicted is False, f"the middle namespace did not land: {outer.conflict}"
    assert outer.head is not None
    assert await harness.services.history.contains(built, outer.head), (
        f"the root is at {outer.head!r} and that state does not contain the grandchild's work at "
        f"{built!r}. The middle namespace landed what its *chain* said it had, and the "
        f"grandchild's landing is exactly the thing that moves that chain - §3.6's advance, "
        f"failing here as a wrong answer rather than as a deletion"
    )
    assert (_fake_target(tmp_path) / _file(CHILDREN[0])).read_bytes() == _work(CHILDREN[0])


# --- a real repository: the medium criteria 2 and 3 are actually claims about ---------------------


@dataclass(frozen=True, slots=True)
class _World:
    """The four directories one real-git scenario happens in, all under one root.

    The trees root is a *sibling* of the repository rather than a directory inside it, which is the
    layout §3.9 draws and which `tests/adapters/test_git_workspace.py` gives the reason for: a
    worktree inside the user's working tree shows up in their `git status`.
    """

    root: Path

    @property
    def home(self) -> Path:
        return self.root / "home"

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def trees(self) -> Path:
        return self.root / "trees"

    @property
    def log(self) -> Path:
        return self.root / "landings.jsonl"

    @property
    def target(self) -> Path:
        """`.trees/auth/_base/` - the checkout every landing here goes into (§3.9)."""
        return base_worktree(TreesRoot(self.trees), LABEL)


# Fixed to the second, so that a commit's object id is a function of its tree, its parents and its
# message and of nothing else. The replay test at the bottom compares commit *ids* between a run
# that was killed and one that never was, and a merge commit made a second later is a different one.
MOMENT: Final = "2026-08-18T09:14:02+00:00"


def _git(cwd: Path, *argv: str) -> str:
    """Run git for the fixtures and the assertions.

    Synchronous and raw, on purpose: this is arrangement and observation, not the thing under test,
    and a test that asked its own adapter where a branch was would be resting the assertion on the
    behaviour it is about to check. `tests/adapters/test_git_integrator.py` makes the same choice.
    """
    return subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def _git_answers(cwd: Path, *argv: str) -> bool:
    """One of git's exit-status questions, asked from out here. 0 is yes and 1 is no."""
    done = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert done.returncode in (0, 1), f"`git {' '.join(argv)}` answered neither yes nor no: {done}"
    return done.returncode == 0


def _contains(world: _World, ancestor: str, descendant: str) -> bool:
    """Is `ancestor` in `descendant`'s line of work? git's own answer, not the adapter's."""
    return _git_answers(world.repo, "merge-base", "--is-ancestor", ancestor, descendant)


def _tip(world: _World, branch: str) -> str:
    """Where a branch is, read out of the repository the worktrees share."""
    return _git(world.repo, "rev-parse", branch).strip()


def _holding(where: Path) -> bool:
    """Is a landing pending in this checkout? `MERGE_HEAD` is the hold and there is nothing else."""
    return _git_answers(where, "rev-parse", "--verify", "--quiet", "MERGE_HEAD")


def _read(where: Path) -> bytes | None:
    """What is at `where`, or `None` if nothing is - which is what a wipe having taken it looks
    like.

    A helper rather than `read_bytes` at the call site, because the interesting failures below are
    exactly the ones where the file is *gone*, and a `FileNotFoundError` out of the assertion line
    replaces the sentence explaining what its absence means with a traceback.
    """
    return where.read_bytes() if where.is_file() else None


def _new_world(root: Path) -> _World:
    """A world with one commit in it. Separate from the fixture, because the replay test needs a
    second one - its reference run happens in a world of its own and is compared across the two."""
    made = _World(root)
    made.home.mkdir(parents=True, exist_ok=True)
    made.repo.mkdir(parents=True, exist_ok=True)
    _git(made.repo, "init", "-q", "-b", "main")
    seed = made.repo / SEEDED
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_bytes(SEED)
    _git(made.repo, "add", "--all")
    _git(made.repo, "commit", "-q", "--no-gpg-sign", "-m", "the state a run is cut from")
    return made


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _World:
    """A real repository with one commit, on `main`, and no configuration from this machine.

    The `GIT_CONFIG_*` variables are what make these the same tests everywhere: a developer with
    `commit.gpgsign` on, a `merge.ff` of their own or - most to the point - a
    `merge.verifySignatures` or a `pull.twohead` would otherwise be running different ones. They go
    through `monkeypatch` so that the adapters, which inherit the environment and say so, see them
    too, and so that the child processes started at the bottom of this file inherit them in turn.
    The identity is set because `commit_all` deliberately invents none; the two dates are set
    because the replay test compares commit ids across processes and a commit id is a function of
    its author and committer lines.
    """
    absent = str(tmp_path / "no-git-config")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", absent)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", absent)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "AGL acceptance")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "agl@example.invalid")
        monkeypatch.setenv(f"GIT_{role}_DATE", MOMENT)
    return _new_world(tmp_path / "world")


def _real(
    world: _World,
    *,
    gate: Verifier,
    recorded: list[str] | None = None,
    watcher: _Watcher | None = None,
) -> Services:
    """The bundle these run on: real git, a real store, a scripted agent, and a watchable gate.

    Named adapter by adapter rather than taken from `container.real()`, for
    `instruments/replay.py`'s reason one adapter over: that function also builds a Claude runner and
    a rich terminal, one of which wants a pip extra and neither of which a run with no vendor in it
    has any use for. Tests are outside `agl.*`, so contract 5 has nothing to say about naming three
    git adapters here.

    `watcher` wraps the real integrator rather than replacing it, so a test that watches the order
    of two landings is still asserting about the landings that actually happened.
    """
    integrator: Integrator = GitIntegrator(world.repo)
    if watcher is not None:
        integrator = _Watched(integrator, watcher)
    return Services(
        store=FilesystemStore(AglHome(world.home)),
        workspaces=GitWorkspaceProvider(world.repo, TreesRoot(world.trees)),
        history=GitHistory(world.repo),
        integrator=integrator,
        verifier=gate,
        terminal=HeadlessTerminal(),
        clock=SystemClock(),
        agents=RoutingAgentRunner({Provider.CLAUDE: FakeAgentRunner(_agent(recorded))}),
        build=container.FAKE_BUILD,
    )


async def _real_run(world: _World, services: Services) -> Run[None]:
    """One root `Run` over a real repository, assembled the way `api.run` assembles one.

    The record is not written, because nothing below reads one - `api.resume` is 16.2 - but the
    `_base` checkout is opened first, exactly as 13.4 put it there, so that `agl/<label>` is a real
    ref from run start and a landing is offered into a checkout that already exists.
    """
    base = await _base_of(services.history)
    await services.workspaces.open(LABEL, None, base)
    return Run(params=None, services=services, scope=SCOPE, base=base)


# --- criterion 2: a failing gate leaves the branch unmerged and the tree clean --------------------


@pytest.mark.asyncio
async def test_a_red_gate_leaves_a_real_target_unmerged_and_its_tree_clean(world: _World) -> None:
    """The criterion, asked of git rather than of a dictionary.

    §3.4 has the framework "run the build gate and revert on failure", and the revert is
    `Workspace.restore(before)` - `reset --hard` **and** `clean -fd`, one verb doing both halves. A
    fake makes both halves invisible: `FakeVerifier` starts no process, so a build that leaves a log
    and a cache directory in the tree it was pointed at is not a thing that can happen to it, and a
    fake workspace's "clean" is a dict comparison rather than git's own answer about a working tree.
    So every assertion below is a git command.

    Seven claims, and none of them is implied by another:

      * the run's branch is where it was, so **the branch is unmerged** in the sense a person means
        when they type `git log agl/auth`;
      * `merge-base --is-ancestor` says the child's work is not in it - a revert that put the tree
        back but left the ref where the landing moved it satisfies the tree assertions and not this;
      * `git status --porcelain` in the target is silent, which is the whole of "the tree is clean"
        and covers the build's own leavings, the merge's, and anything else;
      * the build's log and its cache **directory** are both gone, because `clean -fd` has to take a
        directory as well as a file and one of the two is the half a reader forgets;
      * the parent's own work and the user's seed are still there, so the revert went back *to* the
        state the landing was offered against and not past it;
      * nothing is holding - no `MERGE_HEAD` - so the gate's revert is not `abort`'s job left
      undone; * and the parent's chain did not move, asserted **behaviourally**: the parent's next
      step is a fingerprint miss, so it restores to `last_good`, and if that had been advanced over
      a landing that was undone the restore would move the tree to a state the branch is not on.

    Then the gate is fixed and the *next* child lands. That is the criterion's real cost read
    forwards: `Integrator.land` is entitled to refuse a landing that would write over unrecorded
    work in the target's checkout, so a target left holding a rejected build's output is a target
    the next child cannot land into, for a reason that has nothing to do with either of them.
    """
    gate = _Gate(passed=False, leaves=True)
    services = _real(world, gate=gate)
    run = await _real_run(world, services)
    first, second = run.worktree(CHILDREN[0]), run.worktree(CHILDREN[1])
    await run.step("prepare", PREPARE, commit="prepare the parent")
    await first.step("implement", BUILDS[CHILDREN[0]], commit="implement T-01")
    await second.step("implement", BUILDS[CHILDREN[1]], commit="implement T-02")
    branch = run_branch(LABEL)
    before = _tip(world, branch)
    built = _tip(world, worktree_branch(LABEL, Namespace(CHILDREN[0])))

    outcome = await first.integrate()

    assert outcome.conflicted is True, (
        "the gate was scripted to fail and the landing stood anyway. §3.4 runs the build gate and "
        "reverts on failure, and a landing kept over a red build is the semantic conflict this "
        "gate is the only thing in AGL that can catch"
    )
    assert _tip(world, branch) == before, (
        f"{branch} is at {_tip(world, branch)!r} rather than {before!r}, where it stood when the "
        f"lease was taken - so the revert did not put the branch back and `git log {branch}` shows "
        f"a person work the build rejected"
    )
    assert not _contains(world, built, branch), (
        f"{branch} still contains the child's {built!r} after the gate rejected it. That is the "
        f"criterion word for word - a failing gate leaves the branch unmerged - and a branch still "
        f"holding rejected work is one the next landing builds on top of"
    )
    assert _git(world.target, "status", "--porcelain") == "", (
        f"the target's working tree is not clean after the revert:\n"
        f"{_git(world.target, 'status', '--porcelain')}"
    )
    assert not (world.target / ARTIFACT).exists(), "the rejected build's log is still in the target"
    assert not (world.target / LEAVINGS).exists(), (
        "the rejected build's cache directory is still in the target. `restore` is `reset --hard` "
        "*and* `clean -fd`, and a directory is the half of `-fd` a reader forgets"
    )
    assert not (world.target / _file(CHILDREN[0])).exists(), "the landing itself was not undone"
    assert _read(world.target / PARENT_FILE) == PARENT_BODY, (
        "the parent's own work is gone from its checkout, so the revert went back past the state "
        "the landing was offered against rather than to it"
    )
    assert _read(world.target / SEEDED) == SEED, "the user's own work is gone too"
    assert not _holding(world.target), (
        "the target is still holding a merge after a gate failure, so the revert moved a head and "
        "left git mid-landing - and the next `land` would be answered with this one's collision"
    )
    assert _tip(world, worktree_branch(LABEL, Namespace(CHILDREN[0]))) == built, (
        "the child's own branch moved under a landing that was rejected. A landing lands what the "
        "source *recorded* and never touches the place it was recorded from - and a retry has "
        "nothing to offer if the source has been rewritten"
    )
    assert _git(world.repo, "status", "--porcelain") == "", (
        "the user's own checkout is dirty. §3.9: AGL never touches the target repository except "
        "through a workspace, and a merge is the one command in this package with an obvious wrong "
        "place to run it"
    )

    await outcome.abort()
    await run.step("review", REVIEW)

    assert _tip(world, branch) == before, (
        f"{branch} moved to {_tip(world, branch)!r} when the parent's next step restored to its "
        f"chain, so the chain had been advanced over a landing that was undone. §3.6 makes that "
        f"the one value whose being wrong deletes work rather than costing a re-run"
    )
    assert _read(world.target / PARENT_FILE) == PARENT_BODY

    gate.passed = True
    landed = await second.integrate()

    assert landed.conflicted is False, (
        f"the next child could not land into a target the gate had reverted: {landed.conflict}. "
        f"`Integrator.land` refuses a landing that would write over unrecorded work, so anything a "
        f"rejected build left behind is a refusal aimed at whoever comes next"
    )
    assert _read(world.target / _file(CHILDREN[1])) == _work(CHILDREN[1])


# --- criterion 3: the advance, proven where it destroys work --------------------------------------


@pytest.mark.asyncio
async def test_a_landed_child_survives_the_parents_next_fingerprint_miss(world: _World) -> None:
    """§3.6's destroy-work line, produced in the medium that does the destroying.

    "**`integrate()` advances the parent's `last_good`.** A child landing moves the parent's
    physical head, but `last_good` is chained from step entries and `integrate()` is not a step - so
    the parent's next step to miss its fingerprint would `restore()` to a commit *before* every
    landed child and delete all of it."

    **A hit proves nothing**, which is why this arranges a miss and asserts that it was one. §3.6's
    replay returns on a hit before `restore` is ever reached, so a suite that landed a child and
    then replayed a recorded step would pass with the advance deleted. `review` has never run in
    this run, so it misses; it takes no `commit=`, so **both** of §3.3's restores fire - the
    unconditional one before the worker and the wipe after it - and each of them is `reset --hard`
    *and* `clean -fd` against whatever `last_good` says. That the worker ran is asserted directly,
    because "the worker was not called" is the whole of what a replay hit is (§3.6) and this test is
    worthless without a miss.

    **What is asserted is contents and ancestry, not a head string.** A head that changed is
    consistent with the advance being written and with the landing having been redone; a *file* that
    still holds what the child wrote, and a *branch* that git says still contains the child's
    commit, are the two facts a person would go and check. Then a second miss, and then an effect
    step whose own commit must still contain the child - so the parent's future work is built on top
    of the landing rather than beside it.
    """
    recorded: list[str] = []
    services = _real(world, gate=_Gate(passed=True), recorded=recorded)
    run = await _real_run(world, services)
    child = run.worktree(CHILDREN[0])
    await run.step("prepare", PREPARE, commit="prepare the parent")
    await child.step("implement", BUILDS[CHILDREN[0]], commit="implement T-01")
    built = _tip(world, worktree_branch(LABEL, Namespace(CHILDREN[0])))
    branch = run_branch(LABEL)

    outcome = await child.integrate()
    assert outcome.conflicted is False, f"the landing did not go in: {outcome.conflict}"
    assert _contains(world, built, branch), "the landing did not reach the run's own branch"

    recorded.clear()
    await run.step("review", REVIEW)

    assert recorded == [REVIEW.instructions], (
        f"the parent's next step ran {recorded} rather than missing its fingerprint and calling "
        f"its worker once. A hit returns before `restore` is reached, so this test would be "
        f"asserting that nothing happened - §3.6's replay makes the miss the only interesting path"
    )
    assert _read(world.target / _file(CHILDREN[0])) == _work(CHILDREN[0]), (
        "the landed child's file is gone from the target's checkout, or holds something else, "
        "after a read-only step in the parent. That step restored to `last_good`, which means the "
        "landing never reached the parent's chain - and `reset --hard` plus `clean -fd` took the "
        "child away with nothing raising, nothing re-running and the workflow still believing it "
        "landed"
    )
    assert _read(world.target / PARENT_FILE) == PARENT_BODY, (
        "the parent's own work is gone too, so the restore went back further than the landing"
    )
    assert _contains(world, built, branch), (
        f"git says {branch} no longer contains {built!r}. The file surviving and the ancestry "
        f"surviving are two claims: a restore that moved the branch back would leave the tree "
        f"looking right for as long as nobody committed on top of it"
    )
    assert _contains(world, built, _git(world.target, "rev-parse", "HEAD").strip()), (
        "the target's checkout is on a state that does not contain the child, so the branch and "
        "the worktree disagree about what has landed"
    )
    assert _git(world.target, "status", "--porcelain") == "", (
        "the read-only step left something in the target's checkout, which is the other half of "
        "what its ending `restore` is for"
    )

    await run.step("look-again", LOOK_AGAIN)
    await run.step("record", RECORD, commit="record what has landed")

    assert _read(world.target / _file(CHILDREN[0])) == _work(CHILDREN[0]), (
        "a second miss in the parent deleted the landed child, so the advance survived one restore "
        "and not the next"
    )
    assert _contains(world, built, _tip(world, branch)), (
        f"the parent committed on top of a state that does not contain {built!r}, so the run's own "
        f"line of work now forks away from the child that landed into it - and the child's work is "
        f"reachable only from a branch nobody will push"
    )


# --- criterion 1 again, in the medium where an interleaving is not a matter of luck ---------------


@pytest.mark.asyncio
async def test_three_children_land_into_one_real_base_and_all_three_survive(
    world: _World,
) -> None:
    """The same criterion against real git, where a landing is a dozen subprocesses.

    Against the fakes an unleased implementation *might* interleave; against real git it certainly
    does, because every `git` call is a real suspension and three coroutines started together are
    three merges started together in one checkout - which is not a race with a subtle outcome, it is
    two `git merge` invocations in one worktree and a repository in a state git has no name for.

    So this is the criterion in its plainest form and its most expensive medium: three children,
    three worktrees, three real merges into `agl/auth`, and afterwards the branch has to contain all
    three - asked of `merge-base --is-ancestor` rather than of an outcome that says so - with all
    three files in the `_base` checkout and the user's own repository untouched throughout.

    The watcher runs here too, so the ordering claim is made in both media by one instrument. And
    the merge count is asserted, which nothing else here does: `--no-ff` means each landing is an
    event in the target's history (§3.9 wants `git log agl/auth` to say which child arrived when),
    so three landings owe exactly three merge commits - a fourth would be a landing done twice and a
    second would be two children arriving as one.
    """
    watcher = _Watcher()
    services = _real(world, gate=_Gate(passed=True, watcher=watcher), watcher=watcher)
    run = await _real_run(world, services)
    for name in CHILDREN:
        await run.worktree(name).step("implement", BUILDS[name], commit=f"implement {name}")
    built = {name: _tip(world, worktree_branch(LABEL, Namespace(name))) for name in CHILDREN}
    branch = run_branch(LABEL)

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            *(asyncio.create_task(run.worktree(name).integrate(), name=name) for name in CHILDREN)
        ),
        timeout=_LIVENESS,
    )

    visitors = watcher.visitors(world.target)
    blocks = [name for name, _ in itertools.groupby(visitors)]
    assert len(blocks) == len(set(visitors)), (
        f"two landings into one real checkout overlapped: {visitors}. Two `git merge` invocations "
        f"in one worktree is not a race with a subtle outcome - the second one meets the first "
        f"one's index"
    )
    assert [one.conflicted for one in outcomes] == [False] * len(CHILDREN), (
        f"three children touching three files did not all land: "
        f"{[one.conflict for one in outcomes]}"
    )
    for name, head in built.items():
        assert _contains(world, head, branch), (
            f"git says {branch} does not contain {name}'s {head!r}. All three were told they had "
            f"landed, so one landing was computed against a head another had already moved past"
        )
        assert _read(world.target / _file(name)) == _work(name), (
            f"{name}'s file is missing from the target's checkout, or holds somebody else's work"
        )
    assert _git(world.repo, "rev-list", "--count", "--merges", branch).strip() == str(len(CHILDREN))
    assert _git(world.target, "status", "--porcelain") == "", (
        f"the target's tree is dirty after three landings:\n"
        f"{_git(world.target, 'status', '--porcelain')}"
    )
    assert _git(world.repo, "status", "--porcelain") == "", (
        "the user's own checkout is dirty. §3.9's whole premise is that `git status` in `repo/` "
        "stays clean while a run lands work"
    )


# --- what run exit gives back when the workflow raises rather than returns ------------------------


class _Abandoned(Stop):
    """What a workflow raises while a conflict is still on its screen.

    A `Stop` subclass on purpose, and that is not decoration: §3.1 makes the ordering hazard a
    stage-10 acceptance criterion - `Stop` descends from `AglError`, so a handler catching the base
    first reports 6 or 70 where the contract promises 7 - and 14.1 put a `try` into `api.run` for
    the lease. `api.py`'s own docstring answers that the rule "was about catching" and a `finally`
    names no class. This is that answer measured: the object leaves `api.run` untouched and resolves
    to `Stop`'s exit status, with a lease release having run on the way out.
    """


_STRANDED: list[Run[object]] = []
"""Where the workflow below hands its `Run` tree back to the test that started it.

A module-level cell because a workflow function takes a `Run` and returns `None` - there is no
return value and no argument to smuggle one through, which is the shape §3.3 chose. The one test
that reads it clears it first.
"""


@workflow(name="raises-mid-conflict", version="1", params=NoParams)
async def raises_mid_conflict(run: Run[NoParams]) -> None:
    """A workflow that hits a conflict and then gives up by raising, mid-decision.

    Not contrived: a workflow whose conflict screen raised, a role's `on_question` handler that
    raised `Stop`, and a person pressing Ctrl-C all arrive at `api.run`'s `finally` in exactly this
    state - a live `Integration` holding a lease *and* the parent namespace's step lock, reachable
    only from an object that is going away with the workflow.
    """
    child = run.worktree(CHILDREN[0])
    await run.step("prepare", PREPARE, commit="prepare the parent")
    await child.step("implement", COLLIDE, commit="implement T-01")
    outcome = await child.integrate()
    if not outcome.conflicted:  # pragma: no cover - the arrangement guarantees a collision
        raise AssertionError("this workflow exists to raise while a conflict is unresolved")
    _STRANDED.extend((run, child))
    raise _Abandoned("the workflow gave up while the conflict was still on the screen")


@pytest.mark.asyncio
async def test_a_workflow_that_raises_mid_conflict_gives_back_the_lease_and_the_step_lock(
    tmp_path: Path,
) -> None:
    """§3.4's "the lease is released when the run exits", on the exit nobody arranges for.

    The implementer's suite covers a workflow that *returns* with a conflict undecided. The raise is
    a different line of code reaching the same `finally`, and it is the ordinary one: a conflict
    screen is where a run is most likely to end in anger, and §3.1's `Stop` hazard lives on exactly
    this path. Three claims, none of which the return-path test can make.

    **The exception is not touched.** It leaves `api.run` as the object the workflow raised, so
    `cli/exit_codes.exit_status` resolves it to `Stop`'s 7 without either module having heard of
    `_Abandoned`. Had 14.1's `try` been an `except` of any width, the answer would be 6 or 70 -
    which is §3.1's stage-10 criterion, re-asked now that there is a `try` in that function.

    **Both things the lease took come back.** `Leases.claim` takes the target's lease and then that
    namespace's step lock, and `Lease.release` gives back the second and then the first. A release
    that returned only the lease leaves every later step in the parent hanging for the life of the
    process, with nothing raising and nothing to read - so a step and a landing are both offered
    afterwards, and neither may be waiting.

    **And the adapter's hold is deliberately left alone**, which is §3.4's durable hold and the
    reason `abort()` on the way out is the forbidden shortcut: the target's checkout still holds a
    collision nobody decided, so a later invocation can find it. That is asserted first, before the
    step below restores over it.
    """
    _STRANDED.clear()
    harness = _harness(tmp_path)
    points: Sequence[EntryPoint] = (
        EntryPoint(
            name="raises-mid-conflict",
            value=f"{__name__}:raises_mid_conflict",
            group=registry.GROUP,
        ),
    )

    with pytest.raises(_Abandoned) as raised:
        await api.run(harness.services, PROJECT, "raises-mid-conflict", LABEL, (), points=points)

    assert exit_status(raised.value) == exit_status(Stop("")), (
        f"a workflow's own `Stop` subclass left `api.run` resolving to exit "
        f"{exit_status(raised.value)} rather than to {exit_status(Stop(''))}. §3.1 makes that a "
        f"stage-10 criterion and 14.1 put a `try` into that function - a `finally` names no class, "
        f"and an `except` of any width would turn a deliberate end into a bug report"
    )
    assert len(_STRANDED) == 2, "the workflow did not reach the end it was written for"
    run, child = _STRANDED
    assert _read(_fake_target(tmp_path) / CONTESTED) not in (PARENT_SIDE, CHILD_SIDE), (
        "the target's checkout holds one side of the collision whole, so run exit released the "
        "adapter's hold as well as the lease. §3.4 makes the hold durable precisely so a later "
        "invocation can find one it did not take, and undoing it here discards whatever resolution "
        "a person had started"
    )

    stepped = asyncio.create_task(run.step("review", REVIEW))
    landing = asyncio.create_task(child.integrate())
    said, again = await asyncio.wait_for(
        asyncio.gather(stepped, landing), timeout=_LIVENESS
    )

    assert said.text == REVIEW.instructions, (
        "a step in the parent namespace did not complete after the run that was holding its step "
        "lock raised - so `release_all` gave back the lease and not the lock behind it"
    )
    assert again is not None, "a second landing into that target did not complete after run exit"
    await again.abort()


# --- a landing that raises, and a landing that is cancelled while queued --------------------------


class _Refuses(Integrator):
    """An `Integrator` whose first `land` raises, and which is otherwise the one it was given.

    `UpstreamUnexpected` because that is what `GitIntegrator.land` lets out when git refused for a
    reason that is not a collision - a source branch that has gone, histories with no common state,
    a target checkout holding changes the merge would overwrite. Every one of those is an ordinary
    thing, and none of them is a conflicted outcome: they leave `integrate()` by raising, past the
    point where the lease has been taken.
    """

    def __init__(self, real: Integrator) -> None:
        self._real = real
        self._refused = False

    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        if not self._refused:
            self._refused = True
            raise UpstreamUnexpected(
                "git refused this landing for a reason that is not a collision"
            )
        return await self._real.land(source, target)

    async def retry(self, target: Workspace) -> IntegrationOutcome:
        return await self._real.retry(target)

    async def abort(self, target: Workspace) -> None:
        await self._real.abort(target)


@pytest.mark.asyncio
async def test_a_land_that_raises_does_not_strand_the_targets_lease(tmp_path: Path) -> None:
    """`integrate()`'s `except BaseException: lease.release(); raise`, asked rather than read.

    A `land` that raises is not a conflict and is not rare: `Integrator.land` promises to report
    "git refused for a reason that is none of those" as an error, and the workflow above it is
    entitled to catch one and carry on. What must not happen is that the target is left leased by a
    call that is over - because a lease has no predicate, no timeout and no owner, so every later
    landing into that parent, and every later step in it, would wait for the life of the process
    with nothing raising and nothing to read.

    So the failure is provoked once and then the two things that would hang are both offered. This
    is the one path in `integrate()` that gives the lease back without settling an outcome, and the
    implementer's own suite has no arrangement that makes `land` raise at all.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness, integrator=_Refuses(harness.services.integrator))
    first, second = run.worktree(CHILDREN[0]), run.worktree(CHILDREN[1])
    await first.step("implement", BUILDS[CHILDREN[0]], commit="implement T-01")
    await second.step("implement", BUILDS[CHILDREN[1]], commit="implement T-02")

    with pytest.raises(UpstreamUnexpected):
        await first.integrate()

    landing = asyncio.create_task(second.integrate())
    stepped = asyncio.create_task(run.step("review", REVIEW))
    outcome, said = await asyncio.wait_for(asyncio.gather(landing, stepped), timeout=_LIVENESS)

    assert outcome.conflicted is False, (
        f"the landing after a raised one did not go in: {outcome.conflict}"
    )
    assert said.text == REVIEW.instructions
    assert _read(_fake_target(tmp_path) / _file(CHILDREN[1])) == _work(CHILDREN[1])


@pytest.mark.asyncio
async def test_cancelling_a_queued_landing_does_not_strand_the_target(tmp_path: Path) -> None:
    """A landing cancelled while it waits for the lease leaves nothing behind it.

    `Leases.claim` suspends twice - once on the lease and once on the target namespace's step lock -
    and its own docstring says the release between them is "not defensive tidiness". A cancellation
    arriving while a landing is queued is the ordinary shape of that: a person presses Ctrl-C while
    three children are waiting on one conflict screen, and a `TaskGroup` cancels the siblings.

    What must survive is the *queue*: the cancelled landing never held anything, so the child behind
    it must still be able to land once the conflict in front is settled. Nothing here asserts what
    the cancellation did to the cancelled task beyond its being cancelled - that is asyncio's - and
    everything asserts what the next caller finds.
    """
    harness, run, blocked, spare = await _held(tmp_path)
    held = await blocked.integrate()
    assert held.conflicted is True, "this test needs a target left holding a landing"

    queued = asyncio.create_task(spare.integrate())
    for _ in range(_TURNS):
        await asyncio.sleep(0)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued

    await held.abort()
    outcome = await asyncio.wait_for(spare.integrate(), timeout=_LIVENESS)

    assert outcome.conflicted is False, (
        f"the landing after a cancelled one did not go in: {outcome.conflict}. A landing that was "
        f"cancelled while queued held nothing, so nothing it did may reach the next one"
    )
    assert _read(_fake_target(tmp_path) / _file(CHILDREN[1])) == _work(CHILDREN[1])
    assert await asyncio.wait_for(run.step("review", REVIEW), timeout=_LIVENESS) is not None


# --- what the gate does to a landing a person concluded with their own hands ----------------------


@pytest.mark.asyncio
async def test_a_landing_a_person_concluded_by_hand_still_goes_through_the_build_gate(
    tmp_path: Path,
) -> None:
    """The hole 14.3 is written to close, and the cost of closing it that way.

    §3.4 gives the framework exactly one build and puts it inside `integrate()`. A landing reached
    through `retry()` after somebody resolved a collision **by hand** is the landing least like the
    one the framework composed - a person invented it, under time pressure, in a checkout - so a
    `retry` that advanced the parent's chain without building would send exactly that past the one
    check there is. It does not: `Integrator.retry` concludes the merge, and `_concluded` then
    carries it down the same path a first landing takes, gate included.

    That is the first half and it is what this test is for. **The second half is what the revert
    then costs, and it is worth writing down because nothing else does.** The gate says no, the
    framework reverts with `Workspace.restore(before)` - `reset --hard` and `clean -fd` - and the
    state it takes away is the person's own resolution. Press retry again with the build fixed and
    the landing is offered from scratch: the same two lines of work, the same collision, the
    conflict markers back in the file, and the afternoon they spent resolving it gone with nothing
    said.

    §3.4 forbids `abort()`-before-land by name because "it silently discards partial human
    resolutions, which `retry()` exists to preserve". This is that discard arriving through a door
    the plan does not look at. Both halves are asserted here so that neither can change silently.
    """
    harness, run, blocked, _ = await _held(tmp_path)
    target = _fake_target(tmp_path)
    outcome = await blocked.integrate()
    assert outcome.conflicted is True, "this test needs a collision to resolve by hand"
    before = await _head(harness, None)

    target.joinpath(*CONTESTED.split("/")).write_bytes(RESOLVED.encode())
    harness.verifier.answers(container.FAKE_BUILD, passed=False, status=2, output=RED)
    await outcome.retry()

    assert outcome.conflicted is True, (
        "a landing concluded by a person's own hand went in over a red build, so `retry` advanced "
        "the parent's chain without building. §3.4 gives the framework one check and this is the "
        "landing that most needs it - a merge nothing in AGL composed"
    )
    assert outcome.verdict is not None and outcome.verdict.passed is False, (
        "the outcome carries no build verdict, so a workflow cannot tell this conflict - a red "
        "gate on a resolution somebody made - from the textual one it started as"
    )
    assert await _head(harness, None) == before, "the gate's revert did not put the target back"
    assert _read(target.joinpath(*CONTESTED.split("/"))) != RESOLVED.encode(), (
        "the person's resolution is still in the target's checkout after the gate reverted the "
        "landing that carried it, so `restore` did not do what §3.11 says it does"
    )

    harness.verifier.answers(container.FAKE_BUILD, passed=True, status=0, output="")
    await outcome.retry()

    assert outcome.conflicted is True, (
        "the retry after the build was fixed landed - which would mean the resolution survived the "
        "gate's revert. It does not: this assertion is the *cost* being pinned rather than a "
        "behaviour being asked for, and the day it changes is a day worth knowing about"
    )
    body = _read(target.joinpath(*CONTESTED.split("/")))
    assert body is not None and b"<<<<<<<" in body, (
        f"the target's copy of the contested file is {body!r}. What is being recorded here is that "
        f"'fix the build and press retry' offers the landing again from scratch, so a collision "
        f"somebody had already resolved is back in front of them with the markers in it - §3.4's "
        f"own reason for forbidding `abort()` before a land, arriving through the gate's revert"
    )
    await outcome.abort()


# --- criterion 4: a resumed run finds a hold it did not take --------------------------------------


def _spawn(
    world: _World,
    *,
    programme: str,
    tag: str,
    decision: str = "none",
    gate: str = "green",
    kill_at: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """One child process, run to whichever of its two endings it was configured for.

    The environment is inherited, which is what carries the `GIT_CONFIG_*` variables the `world`
    fixture set: a child of this process is subject to the same hermeticity, or these are different
    tests on every machine. Nothing is asserted about the status here - the tests below do that, and
    the status is the thing several of them are about - but stderr travels back with it so that a
    child that died two frames inside an adapter does not present as a landing that mysteriously
    never happened.
    """
    config = Config(
        home=str(world.home),
        repo=str(world.repo),
        trees=str(world.trees),
        project=str(PROJECT),
        label=str(LABEL),
        base=_tip(world, "HEAD"),
        programme=programme,
        decision=decision,
        gate=gate,
        kill_at=kill_at,
        log=str(world.log),
        tag=tag,
    )
    return subprocess.run(
        [sys.executable, str(driver_path()), config.to_json()],
        cwd=world.root,
        capture_output=True,
        text=True,
        check=False,
    )


def _records(world: _World) -> list[Mapping[str, object]]:
    """Every line every process in this world wrote, in the order they were written."""
    if not world.log.exists():
        return []
    found: list[Mapping[str, object]] = []
    for line in world.log.read_text(encoding="utf-8").splitlines():
        parsed: object = json.loads(line)
        assert isinstance(parsed, dict), f"the log holds a line that is not an object: {line!r}"
        found.append(parsed)
    return found


def _said(records: Sequence[Mapping[str, object]], tag: str, key: str) -> Mapping[str, object]:
    """The one record of `key` that process `tag` wrote. Absent is a failure with the log in it."""
    found = [record[key] for record in records if record.get("tag") == tag and key in record]
    assert len(found) == 1, (
        f"the {tag!r} process wrote {len(found)} {key!r} records where exactly one was expected. "
        f"The whole log is:\n" + "\n".join(json.dumps(record, sort_keys=True) for record in records)
    )
    reported = found[0]
    assert isinstance(reported, dict), f"{key!r} is not an object: {reported!r}"
    return reported


def _workers(records: Sequence[Mapping[str, object]], tag: str | None = None) -> list[str]:
    """The prompts every agent invocation was dispatched with, optionally only one process's.

    "The worker was not called" is the whole of what a replay hit *is* (§3.6) - there is no other
    observable difference between a replay and a re-run that happens to produce the same answer - so
    this list is how a resumed process's replay is told from a second run of the same programme.
    """
    return [
        str(record["worker"])
        for record in records
        if "worker" in record and (tag is None or record.get("tag") == tag)
    ]


def _markers(records: Sequence[Mapping[str, object]], tag: str) -> set[str]:
    """Which end-of-process markers one process left: `finally`, `atexit`, both, or neither."""
    return {
        str(record["marker"]) for record in records if "marker" in record and record.get("tag") ==
        tag }


# What a process that was allowed to finish leaves behind, and what a killed one does not.
FINISHED: Final = frozenset({"finally", "atexit"})


def _died_holding(world: _World) -> str:
    """Run one process to a conflicted landing and kill it there. The tip is the pre-merge head.

    Returns where `agl/<label>` stood when the merge stopped, which is what an `abort` promises to
    put the target back to - a conflicted `git merge` does not move `HEAD`, so this is read after
    the process is gone rather than reported by it.
    """
    took = _spawn(world, programme="conflict", tag="died", kill_at="integrated")
    assert took.returncode == 0, (
        f"the process that was meant to die holding exited {took.returncode} instead:\n"
        f"{took.stderr}"
    )
    records = _records(world)
    assert _markers(records, "died") == set(), (
        "the process that was meant to be killed ran a `finally` clause or an `atexit` hook on its "
        "way out, so it was unwound rather than killed - and an unwound run is the one case §3.4 "
        "does not have to survive, because `api.run`'s own `finally` is what gives the lease back"
    )
    assert _said(records, "died", "landed")["conflicted"] is True, (
        "the first process did not conflict, so there is no hold for a second one to find"
    )
    assert _holding(world.target), (
        "the target is not holding a merge after the process that took the hold died. §3.4: the "
        "hold must be durable, not in-memory - `MERGE_HEAD` in the worktree's own git directory is "
        "what makes a crash-during-conflict recoverable at all, and without it there is nothing "
        "for a resumed run to find and nothing an `abort` could ever release"
    )
    return _tip(world, run_branch(LABEL))


def test_a_second_process_meets_the_hold_the_first_one_died_holding(world: _World) -> None:
    """§3.4's recoverable state, followed through two real processes to the end that lands.

    *A resumed run must be able to find a hold it did not take. The durable hold is what makes a
    crash-during-conflict recoverable - but `integrate()` is not a step, so nothing journals it, and
    a resumed run calls `land()` into a target still holding the previous process's merge. Stage 14
    must resolve this ... Not exit 70 on resume.*

    Every clause of that is a fact about two processes and none of it is reachable from one. The
    first process is killed with `os._exit` the instant its landing conflicts - no `finally`, so
    `api.run`'s lease release never runs and neither does anything else - and the second is a fresh
    interpreter that re-drives the same workflow over the same `AGL_HOME` and the same repository.
    It has to be re-driven rather than resumed because `api.resume` is 16.2 and raises today, which
    is exactly the shape a resume will have: the same calls, in the same order, hitting the same
    entries.

    **"Not exit 70" is the number and not the class.** The driver maps whatever it caught through
    `cli/exit_codes.exit_status`, the function `cli/main.py` uses, so what is asserted is what `agl`
    would have printed. An `InternalError` out of `land` - which is what a pre-existing hold used to
    be - resolves to 70 there without the driver naming it.

    **And the resume really is a replay**, asserted by the workers: both steps hit their entries and
    no agent runs at all in the second process, which is what puts the second `integrate()` at the
    same call with the same source. A resume that re-ran them would be a different run reaching a
    similar place.

    Then the person resolves the collision in the target's checkout and stages it, and `retry()`
    concludes **the first process's merge** - the one it never took - and carries it down the same
    path a first landing takes: containment, gate, advance. What lands is what they staged.
    """
    before = _died_holding(world)
    built = _tip(world, worktree_branch(LABEL, Namespace(CHILD)))

    resumed = _spawn(world, programme="conflict", tag="resumed", decision="retry")

    records = _records(world)
    assert resumed.returncode == 0, (
        f"the resumed process exited {resumed.returncode}. §3.4 forbids exactly one answer here - "
        f"*Not exit 70 on resume* - and any non-zero status is a run that could not carry on from "
        f"a repository a person can still put right.\n"
        f"--- log ---\n"
        + "\n".join(json.dumps(record, sort_keys=True) for record in records)
        + f"\n--- stderr ---\n{resumed.stderr}"
    )
    assert exit_status(InternalError("")) != 0, "this test's negative is vacuous if 70 is 0"
    assert _markers(records, "resumed") == FINISHED, (
        "the resumed process left no end-of-process markers, so the assertion that a killed one "
        "leaves none is comparing against nothing"
    )
    assert _workers(records, "resumed") == [], (
        f"the resumed process ran {_workers(records, 'resumed')}. It walks the same calls the "
        f"first one did, over the same ledger, so every step must hit - a re-run means the second "
        f"`integrate()` is offering a different source and this test is no longer about a hold"
    )
    met = _said(records, "resumed", "landed")
    assert met["conflicted"] is True, (
        "landing into a target that was already holding somebody else's merge was not reported as "
        "a conflict. §3.4 names two acceptable exits and this is the first: the state *is* a "
        "conflict and the workflow already knows how to route one"
    )
    assert met["paths"], (
        f"the conflict a resumed run is handed names no files: {met}. This implementation can "
        f"enumerate the pending landing's unresolved paths, and a person sent to a conflict screen "
        f"with an empty tuple is a person sent nowhere"
    )
    settled = _said(records, "resumed", "settled")
    assert settled["conflicted"] is False, (
        f"the retry after a resolution did not land: {settled}. The collision the first process "
        f"was holding was resolved and staged in the target's checkout, so concluding it succeeds "
        f"- and what follows a conclusion is the same path a first landing takes"
    )
    assert settled["verdict"] is True, (
        "the landing a person concluded by hand carries no passing build verdict, so it reached "
        "the parent's chain without going through the one check §3.4 gives the framework"
    )
    assert not _holding(world.target), "the target is still holding a merge after it was concluded"
    assert _tip(world, run_branch(LABEL)) != before, "nothing was committed, so nothing landed"
    assert _contains(world, built, run_branch(LABEL)), (
        f"the run's own branch does not contain the child's {built!r} after a retry that reported "
        f"a landing - so what was concluded was not this child's work"
    )
    assert _read(world.target.joinpath(*CONTESTED.split("/"))) == RESOLVED.encode(), (
        "what the person put in the target's checkout is not what the target holds - `retry` "
        "concludes what they staged, and this port has no other opinion about their work"
    )
    assert _git(world.target, "status", "--porcelain") == "", (
        f"the target's tree is dirty after the landing was concluded:\n"
        f"{_git(world.target, 'status', '--porcelain')}"
    )


def test_a_second_process_can_abort_the_hold_the_first_one_died_holding(world: _World) -> None:
    """§3.4's other end of the same state: give up, and the target goes back where `land` found it.

    The half of the criterion that does not need a person to have fixed anything, and the one a
    workflow reaches when its conflict screen says "no". It matters separately from the retry
    because `abort` is the verb that would be a **silent no-op** against an in-memory hold: a
    resumed run would find nothing pending, release nothing, report success, and leave the target
    half-combined forever with `MERGE_HEAD` on disk and no run left that knows about it.

    So what is asserted is the repository afterwards: nothing holding, the branch where the merge
    stopped, the parent's own version of the contested file back in the checkout with no markers in
    it, and the child's work not in the run's line of work - because giving up on a landing means it
    did not happen. The outcome keeps its `Conflict`, which is the record of why nothing landed
    rather than a claim that the hold is still there.
    """
    before = _died_holding(world)
    built = _tip(world, worktree_branch(LABEL, Namespace(CHILD)))

    resumed = _spawn(world, programme="conflict", tag="resumed", decision="abort")

    records = _records(world)
    assert resumed.returncode == 0, (
        f"the resumed process exited {resumed.returncode} rather than releasing a hold it did not "
        f"take.\n--- stderr ---\n{resumed.stderr}"
    )
    assert _said(records, "resumed", "landed")["conflicted"] is True
    settled = _said(records, "resumed", "settled")
    assert settled["conflicted"] is True, (
        "the aborted outcome cleared its conflict. Giving up on a landing does not make the "
        "collision not have happened - the `Conflict` is the record of why nothing landed"
    )
    assert settled["head"] is None, "an aborted outcome reports a head, so something landed"
    assert not _holding(world.target), (
        "the target is still holding the merge after a second process aborted it. That is the "
        "silent failure §3.4 names: against an in-memory hold this `abort` finds nothing pending, "
        "releases nothing, reports success and leaves the target half-combined forever"
    )
    assert _tip(world, run_branch(LABEL)) == before, (
        f"the run's branch moved to {_tip(world, run_branch(LABEL))!r} over a landing that was "
        f"given up. `abort` puts the target back exactly where `land` found it"
    )
    assert not _contains(world, built, run_branch(LABEL)), (
        "the abandoned child's work landed anyway"
    )
    assert _read(world.target.joinpath(*CONTESTED.split("/"))) == PARENT_TEXT.encode(), (
        "the contested file does not hold what the target had before the landing, so the release "
        "put the head back and left the working tree mid-merge"
    )
    assert _git(world.target, "status", "--porcelain") == "", (
        f"the target's tree is dirty after the release:\n"
        f"{_git(world.target, 'status', '--porcelain')}"
    )


# --- the replay question: does an integration survive a kill, and does it land twice? -------------


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """Everything a run left behind, addressed so that two worlds are comparable.

    Entry paths are relative to `AGL_HOME` and branch names are git's own, which is what lets a run
    in one temporary directory be compared with a run in another. `at` is excluded from `entries`
    for `tests/sdk/test_kill_and_resume.py`'s reason: it is a clock reading, and an interrupted run
    legitimately takes longer than a straight one. Everything else not differing is what "never read
    for control flow" looks like from outside.
    """

    entries: Mapping[str, tuple[str, str, str]]
    branches: Mapping[str, str]
    merges: int


def _snapshot(world: _World) -> _Snapshot:
    """Read the ledger and the repository back. Opens nothing that AGL owns."""
    entries: dict[str, tuple[str, str, str]] = {}
    for path in sorted(world.home.rglob("*.json")):
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict), f"{path} is not a JSON object"
        data: Mapping[str, object] = parsed
        if "fingerprint" not in data:
            continue
        entries[path.relative_to(world.home).as_posix()] = (
            str(data["fingerprint"]),
            json.dumps(data["value"], sort_keys=True),
            str(data["head"]),
        )
    branches: dict[str, str] = {}
    listing = _git(world.repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/")
    for line in listing.splitlines():
        name, sha = line.split()
        branches[name] = sha
    return _Snapshot(
        entries,
        branches,
        int(_git(world.repo, "rev-list", "--count", "--merges", run_branch(LABEL)).strip()),
    )


def test_a_run_that_landed_replays_identically_after_being_killed(world: _World) -> None:
    """§3.6's own contract-test shape, applied to the one thing in a run that is not journalled.

    "Enforced by an SDK contract test: run to completion, kill at every step boundary, resume,
    assert identical final state." `tests/sdk/test_kill_and_resume.py` is that test for *steps*, and
    it stops where this begins: nothing under `steps/` records that a child went in, so a resumed
    run re-walks `integrate()` with the child's work already in the target and no entry to tell it
    so. Three things could go wrong there and every one of them is silent.

      * **It could land twice.** `--no-ff` makes every landing an event in the target's history, so
        a second real merge would be a second merge commit for one child's work. The merge count is
        asserted against the reference: one child, one merge, in a world that was killed and one
        that was not.
      * **It could destroy the first landing.** The resume rebuilds the parent's chain by walking
        entries, which reach only as far as the step before the integration - so if the landing did
        not re-advance it, the parent's next step misses and restores past it. That step is in the
        programme deliberately, after the integration.
      * **It could re-run the step after the landing.** That step's fingerprint is taken over the
        parent's chain, so a resume that arrived at a different chain misses, pays an agent again
        and records a second entry at a second address - which the entry comparison catches.

    The reference is a whole run of the same programme in a world of its own, uninterrupted. Commit
    ids are comparable across the two because the `world` fixture pins the author and committer
    dates, so a commit is a function of its tree, its parents and its message - which is what makes
    "the run branch's tip is identical" an assertion about a commit rather than about a tree.
    """
    reference = _new_world(world.root.parent / "reference")
    straight = _spawn(reference, programme="clean", tag="reference")
    assert straight.returncode == 0, f"the uninterrupted reference run failed:\n{straight.stderr}"
    assert _markers(_records(reference), "reference") == FINISHED
    expected = _snapshot(reference)

    killed = _spawn(world, programme="clean", tag="killed", kill_at="integrated")
    assert killed.returncode == 0, (
        f"the killed process failed before it could be killed:\n{killed.stderr}"
    )
    resumed = _spawn(world, programme="clean", tag="resumed")
    assert resumed.returncode == 0, (
        f"the process resuming a run whose child had already landed exited {resumed.returncode}:\n"
        f"{resumed.stderr}"
    )

    records = _records(world)
    assert _markers(records, "killed") == set(), (
        "the killed process was unwound rather than killed, so `api.run`'s own `finally` ran and "
        "this is not the state a resume has to survive"
    )
    assert sorted(_workers(records)) == sorted(_workers(_records(reference))), (
        f"across both processes the workers that ran were {sorted(_workers(records))}, and one "
        f"complete run of this programme is {sorted(_workers(_records(reference)))}. A repeat is a "
        f"step that re-ran because the resume computed a different digest for it - which for the "
        f"step *after* the integration means the parent's chain came back different - and an "
        f"absence is a step the resume skipped"
    )
    after = _snapshot(world)
    assert after.entries == expected.entries, (
        "the ledger a killed-and-resumed run left is not the one a straight run leaves. Extra "
        "paths are steps that re-ran under a digest the resume computed differently; a differing "
        "`head` at the same path is a step that ran against a different chain - which after an "
        "integration means the landing did not reach it"
    )
    assert after.branches == expected.branches, (
        f"a ref differs from the uninterrupted run's: {after.branches} against "
        f"{expected.branches}. The run's own line and the child's are commits AGL made, and a "
        f"resume that made a different one made different work"
    )
    assert after.merges == expected.merges == 1, (
        f"the resumed run's branch carries {after.merges} merge commits where the straight run's "
        f"carries {expected.merges}. Nothing journals an integration, so a resume re-walks the "
        f"same `integrate()` with the child's work already in the target - and a second merge "
        f"there is one child landed twice, which `git log agl/auth` then reports as two arrivals"
    )
    assert _read(world.target / "notes/after.md") is not None, (
        "the step after the landing left nothing in the target, so it did not run to its end"
    )


# --- two more paths out of an integration, neither of which the plan writes down ------------

@pytest.mark.asyncio
async def test_a_gate_that_raises_inside_retry_leaves_the_outcome_unsettled_and_abort_frees_it(
    tmp_path: Path,
) -> None:
    """The asymmetry between `integrate()` and `retry()`, and the recovery that makes it survivable.

    `integrate()` wraps its body in `except BaseException: lease.release(); raise`, so a first
    landing that blew up gives the target back. `retry()` has no such wrapper, and a gate that
    raises inside one therefore leaves the lease **held** and the outcome **unsettled**. That is the
    safe direction rather than a leak - the port says a failed `abort` keeps the lease for the same
    reason, because the target may still be held and nothing else may land into it - but it is
    silent, and its consequence is worth measuring: a workflow that catches the exception and
    carries on without settling has stopped every later landing into that parent for the life of the
    run, with nothing raising and no predicate to ask.

    Nothing in the port makes this common - `ports/verifier.py` is emphatic that a failing build is
    an outcome and not an exception, and the one thing that genuinely raises is a shell that could
    not be started at all. But that case exists, it arrives as `UpstreamUnavailable`, and a workflow
    is entitled to catch it and offer the person the same conflict screen again.

    So what is asserted is the path back: the outcome is still conflicted and still live, `abort()`
    settles it, and the target is usable afterwards. The queued landing in the middle is what shows
    the lease really was still held, and it is cancelled rather than awaited because waiting on it
    is the failure this test is describing.
    """
    gate = _Gate(passed=True)
    _, run, blocked, spare = await _held(tmp_path, verifier=gate)
    outcome = await blocked.integrate()
    assert outcome.conflicted is True, "this test needs a conflict to retry"
    target = _fake_target(tmp_path)
    target.joinpath(*CONTESTED.split("/")).write_bytes(RESOLVED.encode())
    gate.explodes = True

    with pytest.raises(UpstreamUnavailable):
        await outcome.retry()

    queued = asyncio.create_task(spare.integrate())
    waiting, _ = await asyncio.wait({queued}, timeout=_SERIALIZED)
    assert not waiting, (
        "a second landing into the target went through while an integration whose gate had raised "
        "was still unsettled - so `retry()` gave the lease back over an outcome that is still "
        "conflicted, and two workflows are now deciding about one target"
    )
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued

    assert outcome.conflicted is True, (
        "the outcome settled itself over an exception, so a workflow catching it has nothing left "
        "to abort and no way to release the hold the target is still carrying"
    )
    await outcome.abort()
    freed = await asyncio.wait_for(spare.integrate(), timeout=_LIVENESS)

    assert freed.conflicted is False, (
        f"the target could not be landed into after the failed retry was aborted: {freed.conflict}"
    )
    assert _read(target / _file(CHILDREN[1])) == _work(CHILDREN[1])


@pytest.mark.asyncio
async def test_integrating_one_child_twice_lands_it_once_and_says_so_both_times(
    tmp_path: Path,
) -> None:
    """The in-process half of what a replay depends on: a landing is idempotent.

    Nothing journals an integration (§3.6), so the *only* thing that keeps a second walk from
    landing a child twice is that `Integrator.land` reports work the target already holds as an
    ordinary landing at the unchanged head - "a landing that changed nothing is still a landing".
    The two-process replay test at the bottom of this file asserts the consequence in the medium
    that matters; this asserts the mechanism where it is cheap, and where a workflow that simply
    calls `integrate()` twice - a retry loop, a `drive` that lost track - meets it.

    What must be true is that both calls report the same head, neither conflicts, and the parent's
    chain ends where the first one put it. A second *landing* would move the head, which is the
    failure a replay would inherit: one child, two arrivals in `git log agl/auth`.
    """
    harness = _harness(tmp_path)
    run = await _tree(harness)
    child = run.worktree(CHILDREN[0])
    await child.step("implement", BUILDS[CHILDREN[0]], commit="implement T-01")

    first = await child.integrate()
    second = await child.integrate()

    assert (first.conflicted, second.conflicted) == (False, False), (
        f"integrating one child twice conflicted: {first.conflict}, {second.conflict}"
    )
    assert first.head is not None and second.head == first.head, (
        f"the second landing reports {second.head!r} where the first reported {first.head!r}, so a "
        f"child the target already held was landed a second time - which is what a resumed run "
        f"does on every `integrate()` it re-walks, there being no entry to tell it otherwise"
    )
    assert await _head(harness, None) == first.head, "the target moved over a second landing"
    assert _read(_fake_target(tmp_path) / _file(CHILDREN[0])) == _work(CHILDREN[0])
