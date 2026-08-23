"""One run that lands a child, in a process of its own, killable while it is holding a conflict.

`tests/sdk/test_integrate_acceptance.py` needs two things no in-process test can arrange, and this
module is the half of them that has to live somewhere else.

**A hold that outlives the process that took it.** §3.4: *the hold must be durable, not in-memory. A
run that dies holding a target can only be released by a later invocation.* §3.4 then asks the
question this instrument exists to answer - *a resumed run must be able to find a hold it did not
take* - and forbids the answer that used to be given: `integrate()` is not a step, so nothing
journals it, and a run that resumes reaches the same `integrate()` with the target still held. That
state is a `Conflict` and never exit 70. Neither half of it exists inside one interpreter: an
`asyncio.Lock` keeps one process from ever meeting its own hold, and `adapters/git/fake.py` says
outright that a `FakeRepository` dies with its process, so the hold a resumed run would find was
never there to find.

**An integration that replays.** §3.6's one rule for authors is enforced by a contract test - "run
to completion, kill at every step boundary, resume, assert identical final state" - and
`tests/instruments/replay.py` is that test's driver for *steps*. Nothing journals an integration, so
a landing is the one thing in a run that a resume has to reproduce with no entry to read: it
re-walks the same `integrate()` call and offers the same child into a target that already has it.
Whether that lands twice, lands once, or destroys the first landing is a question about two
processes.

**The kill is `os._exit`, and the distinction is the whole point.** An exception would run `finally`
blocks, `atexit` handlers and asyncio's cancellation path - and `api.run`'s `finally` is precisely
what gives the lease back, so a driver that raised would be testing the tidy exit rather than the
one §3.4 is about. `_Driver.kill` returns to the kernel, and this module registers both an `atexit`
hook and a `finally` clause that append a marker to the log for the only reason such a marker is
ever worth writing: the parent asserts they are **absent** after a kill and present after a clean
finish.

**The exit status is mapped rather than reported.** `main` catches `Exception` and hands it to
`cli/exit_codes.exit_status`, which is the function `cli/main.py` uses, so the number the parent
reads is the number `agl` would have printed. "Not exit 70" is then a fact about this run rather
than about a class name a test chose to look for.

**Real git, a real store, a real shell for the gate, and a scripted agent.** The claim is about
worktrees, refs and a `MERGE_HEAD` on disk; it is not about a model, so the one port that would cost
money is the fake. `container.real()` is not used because it also builds a Claude runner and a rich
terminal, one of which wants an extra and neither of which a programme with no vendor in it has any
use for - which is `replay.py`'s reason, one adapter over.

**The `Run` is built the way `api.run` builds one**, and not through `api.run`, because `api.run`
refuses a label that already has a record (§3.10, exit 4) and `api.resume` is deliberately unbuilt
until 16.2. So the record is written, `_base` is provisioned, a `Leases` is constructed above the
workflow and released in a `finally` - the four things that function does around the workflow's own
body - and the second process does the identical four over the same `AGL_HOME`.

Run as `python tests/instruments/landing.py '<json>'`. The configuration arrives as one JSON object
on argv so that a reader of a failing test can copy the command out of the assertion and run it.
Importable as `instruments.landing` too - `tests/` is on `sys.path`, see `tests/conftest.py` - which
is how the parent shares this module's constants rather than restating them.
"""

import asyncio
import atexit
import json
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.adapters.claude_code import fake as claude_fake
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.rich_terminal.headless import HeadlessTerminal
from agl.adapters.routing import RoutingAgentRunner
from agl.adapters.shell.verifier import ShellVerifier
from agl.adapters.system_clock import SystemClock
from agl.cli.exit_codes import exit_status
from agl.ports.agent import AgentOutcome, Claude, Provider, Restriction, StopReason
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.run import RunSpec
from agl.ports.tree_layout import TreesRoot, base_worktree, run_branch
from agl.sdk._engine.integration import Integration, Leases
from agl.sdk._engine.services import Services
from agl.sdk.roles import Role
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run

__all__ = [
    "CHILD",
    "CHILD_TEXT",
    "CONTESTED",
    "GREEN",
    "PARENT_TEXT",
    "PROGRAMMES",
    "RED",
    "RESOLVED",
    "Config",
    "driver_path",
    "main",
]

# The one namespace every programme here opens, and the file the conflicting programme collides
# over. `CONTESTED` is created by the parent *and* by the child, from a base holding neither, which
# is the only shape no honest implementation can combine - it is also what the fakes-side tests in
# the parent module collide over, shared from here so the two cannot drift.
CHILD: Final = "T-01"
CONTESTED: Final = "src/contested.py"

# What a person puts in the target's checkout when they resolve the collision by hand. The port has
# no other vocabulary for "somebody fixed it" - `tests/adapters/test_git_integrator.py` simulates a
# resolution the same way and for the same reason.
RESOLVED: Final = "what a person decided\n"

# The two gate commands, real programs run by a real shell. `true` and `false` are POSIX utilities
# and builtins in every shell `create_subprocess_shell` could pick, so the verdict is the same on
# every machine and neither of them can do anything to the tree it runs in.
GREEN: Final = "true"
RED: Final = "false"

# The two bodies of `CONTESTED`, which the parent and the colliding child each create from a base
# holding neither. Twelve lines apiece and not one shared, so a merge that combined them would be a
# merge that guessed - `tests/contracts/_integration_targets.py` argues why a suite has to *cause* a
# conflict rather than declare one. Public, because the parent asserts what an `abort` puts back.
PARENT_TEXT: Final = "".join(f"the parent's own line {index}\n" for index in range(12))
CHILD_TEXT: Final = "".join(f"the child's own line {index}\n" for index in range(12))
_CHILD_FILE: Final = "src/child.py"
_CHILD_WORK: Final = "what the child built\n"
_AFTER: Final = "notes/after.md"
_AFTER_BODY: Final = "written by the parent's step after the landing\n"


@dataclass(frozen=True)
class Summary:
    """A reporting payload: one string, which is the whole of what these agents have to say."""

    text: str


REPORT: Final = reporting_tool("report", "report what you did", Summary)


def _role(instructions: str) -> Role[Summary]:
    """A reporting role. Module-level in the parent's sense: one object per prompt, and the prompt
    is the only thing a script is handed that says which step it is serving (§3.3)."""
    return Role(
        instructions=instructions,
        model=Claude.SONNET,
        restrictions=set[Restriction](),
        tools=(REPORT,),
    )


PREPARE: Final = _role("prepare the parent")
COLLIDE: Final = _role("implement over the same file the parent touched")
IMPLEMENT: Final = _role("implement the ticket")
AFTERWARDS: Final = _role("say what the run has landed so far")

# Which files each prompt's agent leaves behind. Keyed on the prompt, because `AgentTask` carries no
# namespace and no step name - deliberately (§3.3), and it is what makes one script serve a run.
_WRITES: Final[Mapping[str, Mapping[str, str]]] = {
    PREPARE.instructions: {CONTESTED: PARENT_TEXT},
    COLLIDE.instructions: {CONTESTED: CHILD_TEXT},
    IMPLEMENT.instructions: {_CHILD_FILE: _CHILD_WORK},
    AFTERWARDS.instructions: {_AFTER: _AFTER_BODY},
}


# --- the configuration one child process is handed ------------------------------------------------


@dataclass(frozen=True, slots=True)
class Config:
    """One child process's whole world: where to write, what to run, and when to die.

    A frozen record rather than a pile of argv flags, because the parent builds it, serialises it
    and then reads the same field names back out of the log when an assertion fails.

    `kill_at` is the parameter the durable half exists for: `None` runs the programme to its end,
    and `"integrated"` returns to the kernel the instant `integrate()` has answered - which for the
    conflicting programme is a process that dies **holding**, and for the clean one is a process
    that dies having landed and journalled nothing about it.

    `decision` is what the workflow does with a conflicted outcome, which is the half §3.3 gives to
    the workflow and stage 15 gives a screen: `retry` after resolving the collision by hand, `abort`
    to give up, or `none` for a run that walks away from it.
    """

    home: str
    repo: str
    trees: str
    project: str
    label: str
    base: str
    programme: str
    decision: str
    gate: str
    kill_at: str | None
    log: str
    tag: str

    def to_json(self) -> str:
        """The argv string. Written out by key rather than by `asdict`, so the child's parser and
        this method are readable against each other."""
        return json.dumps(
            {
                "home": self.home,
                "repo": self.repo,
                "trees": self.trees,
                "project": self.project,
                "label": self.label,
                "base": self.base,
                "programme": self.programme,
                "decision": self.decision,
                "gate": self.gate,
                "kill_at": self.kill_at,
                "log": self.log,
                "tag": self.tag,
            }
        )

    @classmethod
    def from_json(cls, text: str) -> Config:
        """The same record, back. Every field is narrowed rather than trusted: this runs in a child
        process whose only diagnostic channel is an exit status and a line on stderr."""
        parsed: object = json.loads(text)
        if not isinstance(parsed, dict):
            raise SystemExit(
                f"landing: configuration is a JSON object, not {type(parsed).__name__}"
            )
        data: Mapping[str, object] = parsed
        kill = data.get("kill_at")
        if not (kill is None or isinstance(kill, str)):
            raise SystemExit("landing: 'kill_at' is a phase name or null")
        return cls(
            home=_text(data, "home"),
            repo=_text(data, "repo"),
            trees=_text(data, "trees"),
            project=_text(data, "project"),
            label=_text(data, "label"),
            base=_text(data, "base"),
            programme=_text(data, "programme"),
            decision=_text(data, "decision"),
            gate=_text(data, "gate"),
            kill_at=kill,
            log=_text(data, "log"),
            tag=_text(data, "tag"),
        )


def _text(data: Mapping[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise SystemExit(f"landing: {key!r} is a string, not a {type(value).__name__}")
    return value


# --- one process's run ----------------------------------------------------------------------------


class _Driver:
    """The bundle, the `Run`, the log, and the kill.

    Everything a programme needs and nothing a programme decides. The two things worth reading twice
    are that the agent's script appends a line **per invocation** - "the worker was not called" is
    the whole of what a replay hit is (§3.6), so that list is how the parent tells a replayed step
    from a re-run one - and that `kill` is `os._exit` rather than anything that unwinds.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.label = RunLabel(config.label)
        self.scope = RunScope(ProjectName(config.project), self.label)
        self.trees = TreesRoot(Path(config.trees))
        self.services = Services(
            store=FilesystemStore(AglHome(Path(config.home))),
            workspaces=GitWorkspaceProvider(Path(config.repo), self.trees),
            history=GitHistory(Path(config.repo)),
            integrator=GitIntegrator(Path(config.repo)),
            verifier=ShellVerifier(build_timeout=60.0),
            terminal=HeadlessTerminal(),
            clock=SystemClock(),
            agents=RoutingAgentRunner(
                {Provider.CLAUDE: claude_fake.FakeAgentRunner(self._script)}
            ),
            build=GREEN if config.gate == "green" else RED,
        )

    async def _script(self, conversation: claude_fake.Conversation) -> AgentOutcome:
        """One agent for every role here: say that it ran, write what this prompt writes, report."""
        said = conversation.task.instructions
        self.log({"worker": said})
        for name, text in _WRITES.get(said, {}).items():
            where = conversation.task.workspace / name
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_text(text, encoding="utf-8")
        await conversation.call(REPORT.name, {"text": said})
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    @property
    def target(self) -> Path:
        """The run's own `_base` checkout - what every landing here goes into (§3.9)."""
        return base_worktree(self.trees, self.label)

    def resolve_by_hand(self) -> None:
        """Do what a person at the conflict screen does: fix the file, and stage the fix.

        Staging is the whole of it for `GitIntegrator`: `retry` asks the *index* which paths are
        still unresolved, because that is git's own record of the question and the only one that is
        not a guess about what is inside a file. Raw git rather than the adapter, because this is
        the human being simulated and there is no port member for one.
        """
        (self.target / CONTESTED).write_text(RESOLVED, encoding="utf-8")
        subprocess.run(
            ["git", "add", "--", CONTESTED], cwd=self.target, check=True, capture_output=True
        )

    def log(self, record: Mapping[str, object]) -> None:
        """One line on the log, on disk before this call returns.

        Opened, written, flushed and fsynced per line rather than held on a handle, because the
        process may cease to exist between any two lines and a buffered line is an event the parent
        would never learn about.
        """
        line = json.dumps({"tag": self.config.tag, **record}, sort_keys=True)
        with open(self.config.log, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def kill(self, phase: str) -> None:
        """Return to the kernel if this process was configured to die here, and otherwise carry on.

        `os._exit` and not `sys.exit`, not `raise`, not a signal to self: no `finally` runs, no
        `atexit` hook runs, no buffer is flushed and no asyncio task is cancelled. That is what a
        killed agent looks like, and it is the only way to leave `api.run`'s own `finally` - the
        line that gives the lease back - unexecuted.
        """
        if self.config.kill_at == phase:
            self.log({"killed_at": phase})
            os._exit(0)

    def report(self, what: str, outcome: Integration) -> None:
        """Everything about one outcome that the parent asserts on, in one line."""
        self.log(
            {
                what: {
                    "conflicted": outcome.conflicted,
                    "head": outcome.head,
                    "summary": "" if outcome.conflict is None else outcome.conflict.summary,
                    "paths": [] if outcome.conflict is None else list(outcome.conflict.paths),
                    "verdict": None if outcome.verdict is None else outcome.verdict.passed,
                }
            }
        )

    async def run(self, programme: Callable[[_Driver, Run[None]], Awaitable[None]]) -> None:
        """`api.run`'s four lines around a workflow's own body, and then the body.

        The record, the `_base` checkout, the `Leases` built above the workflow, and the `finally`
        that gives back whatever it was still holding. Written out rather than delegated because
        `api.run` refuses a label that already has a record and `api.resume` is 16.2 - the module
        docstring argues it - and because the second process has to do the identical four.
        """
        spec = RunSpec(
            workflow="landing",
            workflow_version="1",
            label=self.label,
            base_ref="HEAD",
            base_sha=self.config.base,
            branch=run_branch(self.label),
            # No params: the programmes below take none, and `params.to_json` refuses anything that
            # is not a dataclass instance - so an empty mapping is the honest record rather than a
            # dataclass invented to satisfy a call.
            params={},
            created_at=self.services.clock.now(),
        )
        if await self.services.store.read_record(self.scope) is None:
            await self.services.store.write_record(self.scope, spec.to_json())
        await self.services.workspaces.open(self.label, None, self.config.base)
        leases = Leases()
        try:
            await programme(
                self,
                Run(
                    params=None,
                    services=self.services,
                    scope=self.scope,
                    base=self.config.base,
                    leases=leases,
                ),
            )
        finally:
            leases.release_all()


# --- the programmes -------------------------------------------------------------------------------


async def _conflict(driver: _Driver, run: Run[None]) -> None:
    """A child whose work will not combine with its parent's, and a decision about it.

    The child is opened **before** the parent's own step, so the two lines of work share a base in
    which `CONTESTED` does not exist and neither has ever seen the other's version - the shape
    `tests/contracts/_integration_targets.py` requires of a conflict a suite causes on purpose.

    `kill_at="integrated"` leaves this process dead with the target held, which is §3.4's
    recoverable state. A second process walking these same calls replays both steps, reaches this
    same `integrate()`, and offers the same child into a target still holding the first process's
    merge.
    """
    child = run.worktree(CHILD)
    await run.step("prepare", PREPARE, commit="prepare the parent")
    await child.step("implement", COLLIDE, commit=f"implement {CHILD}")
    outcome = await child.integrate()
    driver.report("landed", outcome)
    driver.kill("integrated")
    if driver.config.decision == "retry":
        driver.resolve_by_hand()
        await outcome.retry()
        driver.report("settled", outcome)
    elif driver.config.decision == "abort":
        await outcome.abort()
        driver.report("settled", outcome)


async def _clean(driver: _Driver, run: Run[None]) -> None:
    """A child that lands, and a parent step after it - the replay question in its smallest shape.

    Nothing journals an integration (§3.6), so a resume re-walks this `integrate()` with the child's
    work already in the target. What that must not do is land it twice, and what the step after it
    must not do is re-run - its fingerprint is taken over the parent's chain, which the landing
    advanced, and a resume that rebuilt the chain differently would miss and restore past the
    landing.
    """
    child = run.worktree(CHILD)
    await run.step("prepare", PREPARE, commit="prepare the parent")
    await child.step("implement", IMPLEMENT, commit=f"implement {CHILD}")
    outcome = await child.integrate()
    driver.report("landed", outcome)
    driver.kill("integrated")
    await run.step("afterwards", AFTERWARDS, commit="record what landed")


PROGRAMMES: Final[Mapping[str, Callable[[_Driver, Run[None]], Awaitable[None]]]] = {
    "conflict": _conflict,
    "clean": _clean,
}


# --- the entry point ------------------------------------------------------------------------------


def driver_path() -> Path:
    """This file, absolutely - what the parent hands `sys.executable` to start a child."""
    return Path(__file__).resolve()


async def _drive(config: Config) -> None:
    programme = PROGRAMMES.get(config.programme)
    if programme is None:
        raise SystemExit(f"landing: no programme named {config.programme!r}")
    await _Driver(config).run(programme)


def main(argv: Sequence[str]) -> int:
    """Run one programme, map whatever it raised to an exit status, and leave the markers behind.

    **The status is `cli/exit_codes.exit_status`'s**, which is the function `cli/main.py` calls, so
    a parent asserting "not 70" is asserting about the number `agl` would have printed rather than
    about a class this file went looking for. An `InternalError` out of `integrate()` - which is
    what landing into an inherited hold used to be - resolves to 70 here without this module naming
    it.

    Both markers exist for one assertion in the parent, and the assertion is about their **absence**
    after a kill: `os._exit` runs neither an `atexit` hook nor a `finally` clause.
    """
    if len(argv) != 2:
        raise SystemExit("usage: landing.py '<configuration json>'")
    config = Config.from_json(argv[1])
    marker = _marker(config)
    atexit.register(marker, "atexit")
    try:
        asyncio.run(_drive(config))
    except Exception as raised:
        # `cli/main.py`'s own catch, one layer down and for its reason: `exit_status` branches on no
        # class at all, so a `Stop` subclass, an `InputError` and an untranslated bug all resolve
        # here without this file holding a table or an `except` order to get wrong.
        status = exit_status(raised)
        marker("finally")
        _record(config, {"raised": type(raised).__name__, "status": status, "said": str(raised)})
        return status
    marker("finally")
    return 0


def _marker(config: Config) -> Callable[[str], None]:
    """A one-argument writer for the two end-of-process markers, bound to this run's log."""

    def _write(what: str) -> None:
        _record(config, {"marker": what})

    return _write


def _record(config: Config, record: Mapping[str, object]) -> None:
    """One line on the log from outside a `_Driver` - the two markers and the mapped exit status."""
    line = json.dumps({"tag": config.tag, **record}, sort_keys=True)
    with open(config.log, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
