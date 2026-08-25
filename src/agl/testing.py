"""The harness a workflow author tests against: an all-fakes bundle, a run, and a resume.

    from agl import testing
    from agl.testing import AgentTask, Call, Reply

    def agent(task: AgentTask) -> Reply:
        if any(tool.name == "report_findings" for tool in task.tools):
            return Reply(calls=[Call("report_findings", {"summary": "clean", "high": 0})])
        (task.workspace / "src/a.py").write_text("def authorise(): ...\n")
        return Reply(says="implemented it")

    async def test_it_reviews_what_it_implemented(tmp_path: Path) -> None:
        harness = testing.harness(tmp_path, agent=agent, files={"src/a.py": b"pass\\n"})
        await harness.run(fix, "-r", "add oauth")

        assert [entry.step for entry in harness.recorded] == ["implement", "review"]
        assert harness.recorded[-1].value == {"summary": "clean", "high": 0}

Measurable target #8 is that **every command runs end-to-end on fakes alone - no network, no git**,
and this is that made into something a person outside AGL can use: a workflow, a directory, and
three lines. Stages 17 and 18 build their end-to-end tests on it.

## The `write_text` in that example is the point of this section, not decoration

A `Reply` says what an agent *reported* - what it called, what it asked, what it said, how it
stopped - and **no field on it touches the worktree**. What a step commits is whatever is dirty in
the directory the task pointed at, and `Workspace.commit_all` is "a no-op when nothing is dirty",
returning the head unchanged. So an agent written as `Reply(says="implemented it")` and nothing
else runs, reports, and leaves an **empty branch**: the step records the head it started from, and
`commit="implement fix"`, `commit=f"implement {ticket.id}"` and no `commit=` at all become
indistinguishable in their effect.

**That is the single biggest trap in testing a `commit=`**, because the test that is written to
pin those three decisions is exactly the test that cannot see them: `harness.recorded` is
identical either way, the branch is identical either way, and a workflow that dropped every
`commit=` it had passes. Nothing warns, because nothing is wrong - §3.3's framework "does not
inspect whether HEAD moved", deliberately, and a fake that reported an empty commit as an error
would be inventing a rule the real one does not have.

**The fix is one line and it is the author's own**, which is what an `Agent` being a plain function
buys: `task.workspace` is an absolute `Path` to this step's checkout, so writing into it before
returning the `Reply` is the side effect the real agent would have had, and the commit, the
recorded head, the merge gate and `fakes.repository` then have something to be about. It is not a
shortage in the vocabulary and `Reply` grows no file-writing member for it: `ports/workspace.py`
exposes a `Path` because "a workspace genuinely is a directory", the git fake keeps that promise
with real files on disk, and so the seam is already there and is the one a real backend uses.

## Two modules, and the split is forced

`docs/agl-build-stages.md` records stage 9 finding `sdk/testing.py` unbuildable as one module, and
the reason is `.importlinter`'s contract 1: `sdk` sits below `config`, so nothing under `sdk/` can
import the composition root, and building an all-fakes bundle is a composition act. So the
*vocabulary* - `Agent`, `Reply`, `Call`, what an agent does for one task - stays in
`sdk/testing.py`, port-typed and reachable by a workflow; the *builder* is this module, top-level
beside `api.py`, importing `api` and `config` the way `cli/` does.

**Contract 1 gains `agl.testing` as a sibling of `agl.cli`**, and that placement is the argument
rather than a convenience: this module imports `agl.api` and `agl.config` and nothing imports it, so
it sits above the layer stack exactly where `cli` does. A layers contract says nothing about
siblings unless the level is spelled with `|`, and that is how the two are written. Nothing here
imports `agl.cli` and nothing there imports this, which is what the `|` asserts.

Both halves are re-exported here, so an author's test has one import line the way a workflow has
one: `Agent`, `Reply` and `Call` come from `sdk/testing.py`, and `AgentTask` and `StopReason` from
`ports/agent.py`, because an `Agent` takes the first and a `Reply` may carry the second.
`Question` and `Answer` are deliberately **not** re-exported here - they are on `agl.sdk`, where a
workflow's own `on_question` handler already takes them from, and a name on two front doors is a
name a reader has to choose between.

## What it is honest about: this is an interruption, and not a kill

`tests/instruments/replay.py` is §3.6's own acceptance criterion and it argues the difference at
length: "an exception would run `finally` blocks, `atexit` handlers, `__del__` methods and asyncio's
cancellation path; a process that is killed runs none of them", so a real kill is `os._exit` in a
separate process, and "a real repository is the only thing that survives its own process". That test
kills, resumes under a different `PYTHONHASHSEED`, and asserts the two ledgers are identical.

**This harness cannot do that and must not pretend to.** It runs in the caller's own process on
in-memory fakes, so `interrupt_after=` raises where a kernel would have stopped one:

  * `api.run`'s `finally` runs, so the integration leases really are released;
  * the terminal's `__aexit__` runs, so a display really is handed back;
  * the git fakes hold their commits in memory, so "the repository survived" is not being asked;
  * one interpreter runs both invocations, so a `frozenset`'s iteration order does not vary between
    them and rules 2 and 3 of §3.6's canonicalisation are trivially satisfied here.

What it *does* offer is the thing a workflow author actually wants to know, which is that **their
workflow is resumable and does not redo completed work**: k steps recorded, everything after them
abandoned, and a resume against the same store that replays the k and runs the rest. That is a real
property and it fails for real reasons - a step whose fingerprint moves between the two invocations
re-runs, and `recorded` counts it twice. For the version that is a kill, read
`tests/sdk/test_kill_and_resume.py` and the instrument under it.

The interruption derives from `BaseException` and not from `Exception`, which is as near as an
in-process instrument gets: a workflow's own `except Exception` around a retry loop would otherwise
swallow it and the run would carry on, turning this into a no-op nothing reports. A `TaskGroup` in
the workflow still wraps it in a group, so both shapes are unwrapped below.

## What it hands back, and why there is no recorder on any agent

`config/container.py` argues that there is deliberately no recorder on any agent fake, because "what
a test wants to know is already held by the tool handlers and question handler it supplied itself" -
and here the `Agent` is the author's own function, so counting dispatches or keeping the tasks it
was handed is one line in their own file rather than a surface here.

What is *not* already theirs is the ledger, and that is what `recorded` is. §3.3 gives AGL one write
path - "the agent calls it, the tool validates the payload and hands it back, and the *framework*
stores it as the step result. One write path, one ledger" - and `Store` has no member that lists a
step's entries, deliberately: the four lookups are by address and a digest is the journal's to
compose. So the harness observes the write instead, through a `Store` that wraps the bundle's own
and delegates every call to it. One mechanism, three jobs, and each is something an author asks for:

  * **what each step recorded**, which is the scripted payload arriving as the step result;
  * **which steps ran at all**, because a replayed step writes no entry - so "each step recorded
    exactly once across both invocations" is the resume property stated as an assertion;
  * **where to stop**, because §3.6's step boundary is "after that step's entry is on disk and
    before the next step begins", and that is this call returning.

Everything else the bundle holds is reachable through `Harness.fakes`, which is `container`'s own
`FakeServices`: `fakes.repository` for what the run committed, `fakes.verifier.answers(...)` to
close the merge gate, `fakes.clock.advance(...)` to move time, `fakes.terminal` for what was shown,
`fakes.services` to call `api` with directly. It is that object and not a copy of its fields,
because a second listing of them here would be a second thing to keep in step with the first.

## The workflow is handed over as an object, and reaches `api.run` as an entry point

`api.run` takes `points=` and `api.py`'s docstring names this caller: "a caller that has its own set
- this suite, and 16.5's harness running a workflow the author has not installed yet - supplies
one." An author has a `Workflow`, not an entry-point string, so this module composes the string
their `pyproject.toml` would have carried - `agl.workflows.fix:fix` - out of the decorated
function's own module and name, and then **loads it back through `config/registry.py` and checks it
is the same object**.

That check is not ceremony and it is not defensive. It is the same resolution an installed workflow
gets, so a workflow this harness can run is a workflow an entry point can reach - which is §3.3's
"one package, one entry-point line" tested for free, in front of the author, before they have
published anything. A workflow declared inside a function, or bound to a module attribute under a
different name, is refused here with the reason rather than discovered by an operator on the day
they install it.

## Params are flags, and that is the round trip

§3.3: params are "all named flags, no positionals ... Persisted into `run.json`, which is why `agl
resume auth` takes no flags." So `run(fix, "-r", "add oauth")` takes what a person types, and there
is no parameter here that takes an instance of the params dataclass.

The alternative was measured against the round trip and loses on it. `api.run` parses argv into an
instance, `params.to_json` writes the instance into the record, and `api.resume` rebuilds it with
`params.from_json` - so flags are the one shape that survives all three by construction. An instance
handed in here would either have to be reduced back to argv, which means this module guessing the
author's own `arg()` spellings, or injected past `params.parse`, which means the harness proving a
path no invocation takes and never finding out that two flags of theirs collide or that a default is
wrong. Passing flags tests the params declaration as well as the workflow, and that declaration is
one of §3.3's four things an author writes.

## The terminal: a board needs nothing, and a question needs `answering([...])`

`container.fakes()` builds a `HeadlessTerminal`, which drops a passive `Screen` and refuses a
`Screen[T]` with `UpstreamUnavailable` - correctly, since a workflow needing human input genuinely
cannot run with nobody there. So a workflow that shows a **board** needs nothing from you, and a
workflow whose `on_question` handler routes to an interactive screen needs a terminal that can
answer one, which is what `terminal=` takes and what `answering()` below builds:

    term = testing.answering([Press(1, "widen the scope first"), 0])
    harness = testing.harness(tmp_path, agent=agent, terminal=term)
    await harness.run(fix, "-r", "add oauth")

    assert not term.remaining          # every gesture was spent
    assert term.slot() is not None     # and the board was up behind them

A `Press` is one gesture - which of the screen's own responses, and what was typed into it - and a
bare `int` means `Press(int)`, so a list of approvals is `answering([0, 0])`. The list is spent in
order on whatever screen is in front of the terminal, which is the highest-priority queued one:
exactly what a person would have answered, so a conflict screen at priority 10 takes the next
gesture ahead of an agent question that was already up.

**The one trap, because it will cost you an afternoon otherwise.** A question with no gesture left
does not fail - it waits, forever, exactly as a real terminal with nobody at it does, because §3.7
has no timeouts anywhere. A test that hangs on a `run` is a script that ran out before the workflow
stopped asking. `remaining` catches the other direction, a script longer than the run that spent it.

**This is a third `Terminal` and it earns that by running the contract suite.** Answering a screen
used to mean the real `RichTerminal` (the `agl[terminal]` extra) over a `Keys` of your own plus an
import of `agl.adapters.rich_terminal.terminal`, a module contract 6 forbids a workflow to touch -
so the seam was there and it was tty-shaped, making every author re-derive "type the number, press
Enter" in order to say "approve". What replaced it is not a mock: `adapters/rich_terminal/
scripted.py` reuses the same slot and the same two queues `RichTerminal` uses and passes
`tests/contracts/terminal.py`'s input-capable half as a third class, which is why a workflow that
passes here queues, preempts and answers the way it will in front of a person.

## A view is tested by calling it, and a board's argument is a live `Run` - so `a_run` builds one

A view is a pure function of its arguments, so every claim about one is a call and a comparison
against the `Screen` it returned: no display, no redraw loop, nothing that could block. §3.7's
board is the one that costs something, because it takes the **live** `Run` - `Text(run.activity or
"")` is live precisely because `show` registers the function and its arguments and invokes them
again every frame, and a board handed `run.activity` as a value would be frozen at the moment of
the `show`.

Which leaves an author testing their own board needing a `Run`, and `agl.sdk` cannot give them one:
`services` is `_engine`'s, `scope` is `ports`', and both are the framework's to compose.
`a_run(harness, params)` below is that composition, taking the `Harness` because it already holds
the two.

**And `reports(run, line)` beside it, because the property is about a board that *moves*.** A
constructor argument can only say what was true when the object was made, so a board that read
`run.activity` once and cached it against the `Run` would satisfy every assertion an `activity=`
keyword can express. What says otherwise is the same object read twice with a report in between,
which is exactly what a step does - so the harness plays the adapter, and these two functions are
between them the one sanctioned write of the engine's activity cell in this repository, here once
rather than in every author's test file.

## The escape hatch is a function here, and not a hole to climb out of

A `Reply` cannot branch on the answer to a question it asked - `sdk/testing.py` states that plainly
rather than working around it - and the way out is a raw `Script` through `container.fakes(claude=
..., openai=...)`. **`over()` is what keeps that a way *through* the harness**: it takes a bundle
somebody else composed and gives back the same `Harness`, so a negotiating script still gets
`recorded`, `interrupt_after=` and a resume. Without it, reaching for the escape hatch would mean
giving up everything this module does, which is how an escape hatch becomes a fork.

It is also the seam for a bundle that is not all fakes - a real `GitWorkspaceProvider` and
`GitHistory` substituted into `container.fakes()`, which is what `tests/test_api.py` does when the
claim is about a git ref rather than about a workflow.

## Deliberately not built

**No `clear`, and no second way to reach `api`.** `harness.scope` carries the project and the label,
and `harness.fakes.services` is the bundle, so `api.clear(harness.fakes.services, ...)` is the
author's own line - and a wrapper here would be a second signature for each of AGL's five
operations, kept in step with the first by nobody. The two that are wrapped are wrapped because they
need something composed: an entry point, and an interruption.

**No assertion helpers.** No `assert_replayed`, no `assert_committed`. What an author asserts is
their own business and `pytest` already says it better; a helper here would be a vocabulary of
outcomes this module would have to keep true.

**No fixture, no plugin, no `conftest` entry point.** This is a function that takes a directory and
returns an object. `pytest`'s `tmp_path` is what an author passes it, and a harness that arrived as
a magic fixture name would tie AGL's testing surface to one test runner's discovery rules.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

from agl import api
from agl.config import container, registry
from agl.config.container import Press, ScriptedTerminal
from agl.ports.agent import AgentTask, StopReason
from agl.ports.errors import InputError
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.terminal import Terminal
from agl.ports.tree_layout import TreesRoot
from agl.sdk._engine.journal import Entry
from agl.sdk.testing import Agent, Call, Reply
from agl.sdk.workflow import Run, Workflow

__all__ = [
    "Agent",
    "AgentTask",
    "Call",
    "Harness",
    "Press",
    "Recorded",
    "Reply",
    "ScriptedTerminal",
    "StopReason",
    "a_run",
    "answering",
    "harness",
    "over",
    "reports",
]

# What a harness calls the project and the run when the author does not say. Both are `ids.py`
# names, so both are validated on the way in; they are parameters because a test about `clear`, or
# about two runs in one directory, has to be able to name a second one. Private, because
# `harness.scope` carries both afterwards and nothing needs the constant to read them back.
_PROJECT: Final = "project"
_LABEL: Final = "test"

# The subdirectory of the caller's directory that becomes the trees root. §3.5 keeps AGL's checkouts
# out of the repository, and here the "repository" is a `FakeRepository` with no directory at all -
# so what this buys is only that a caller handing over a `tmp_path` still has somewhere to put the
# store, a fixture file or an assertion of their own beside it.
_TREES: Final = "trees"

# Where a `Run` built by `a_run` starts, when the caller does not name a head. A well-formed
# 40-character sha and deliberately **not** a state the bundle's repository holds: nothing `a_run`
# builds takes a step, so this value is never resolved, never restored to and never hashed into a
# fingerprint - it is there because `Run.base` is required and a `Run` with an empty one is a lie
# about §3.6's chain. A caller whose test does reach a step passes `base=` the head it wants, which
# is why this is a parameter with a default rather than a value welded in below. Private for
# `_PROJECT`'s reason: `run.base` reads it back, so nothing needs the constant to compare against.
_BASE: Final = "4a91c07f2b3e8d15c6a0f31d8e2b47c9a6013f5e"


class _Interrupted(BaseException):
    """What `interrupt_after=` raises at a step boundary. Never seen by a caller.

    `BaseException` and not `Exception`, which the module docstring argues: a workflow driving a
    retry loop writes `except Exception` around a step, and an interruption it could swallow would
    make the instrument silently do nothing. It is private because it is never a caller's to catch -
    `Harness.run` and `Harness.resume` unwrap it, including out of the `BaseExceptionGroup` a
    `TaskGroup` in the workflow would wrap it in, and return normally.
    """


@dataclass(frozen=True, slots=True)
class Recorded:
    """One entry a run wrote: which step, in which worktree, and the value it recorded.

    §3.6's entry has four fields - `fingerprint`, `value`, `head` and `at` - and this carries one of
    them, because the other three are AGL's own bookkeeping and a workflow author asserting on a
    digest would be asserting about the framework. What they wrote the workflow for is the `value`.
    """

    step: str
    """The name the workflow passed to `run.step`, as a plain `str`.

    A `str` and not the `StepName` the store is addressed by, because the author typed a string:
    `run.step("review", reviewer)` compares against `"review"` and should not need a constructor to
    do it. §3.3 makes step names opaque - "rename `T-01` to `banana` and the framework behaves
    identically" - so nothing is lost by handing back what was written."""

    namespace: str | None
    """The worktree this step ran in - `run.worktree(name)`'s name - or `None` for the run's own.

    The innermost one, which is the whole of what identifies a checkout: §3.9 makes a namespace
    unique run-wide rather than sibling-wide and the trees root is flat, so `T-01`'s child `sub-b`
    and a top-level `sub-b` cannot both exist and the ancestry adds nothing to the answer."""

    value: JsonValue
    """What the step recorded: a reporting tool's payload, or `None` for an effect step.

    The payload as JSON and not as the dataclass the reporting tool declares, for `Call.payload`'s
    reason one direction over - this is the ledger's own value, and reading it back into a type is
    something `run.step` does for the workflow rather than something the ledger holds."""


class _Ledger(Store):
    """The bundle's `Store`, wrapped: it records what every step wrote and can stop a run.

    A decorator and not a second implementation. Every member delegates, so the ledger underneath is
    the one the bundle built and `container.fakes()`'s `MemoryStore` remains the whole of what
    persists anything - which is what keeps `tests/contracts/store.py` the only thing that says how
    a `Store` behaves, this class having no behaviour of its own to be wrong about.

    It hangs off `write_entry` and off nothing else, and that is §3.6's own boundary: "the counter
    advances when an entry is written, not when a step is called", and "a crashed step leaves no
    entry". So the write is the moment a step is done, and the moment after it returns is the moment
    before the next step begins - the only boundary the ledger makes any promise about.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self.recorded: list[Recorded] = []
        """Every entry written through this, oldest first, across every invocation."""

        self._after: int | None = None
        self._written = 0

    def interrupt_after(self, steps: int | None) -> None:
        """Stop the next run after `steps` entries, or `None` to stop stopping it.

        The count is reset here rather than carried, which is the difference between "the second
        step of this resume" and "the second step ever": `Harness._interrupting` arms this around
        one invocation, so an author interrupting a run at 1 and then a resume at 1 gets what they
        asked for both times.
        """
        self._after = steps
        self._written = 0

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
        """Delegate, record what landed, and stop the run if this was the boundary asked for.

        In that order, and the order is the boundary's definition. The entry is on the ledger before
        anything else happens here, so a run interrupted after it is a run whose k-th step is
        genuinely recorded and replayable - and the interruption is raised *after* the delegate
        returns rather than instead of it, which is what makes `interrupt_after=k` mean "k steps
        recorded" rather than "k-1 recorded and one thrown away".

        `Entry.from_json` rather than `value["value"]`, because the entry's wire shape is
        `sdk/_engine/journal.py`'s and a second reading of it here would be a second thing to keep
        true. It raises for a mapping that is not an entry, which is `InternalError` and correct:
        AGL wrote it and AGL is reading it back.
        """
        await self._store.write_entry(scope, step, digest, value)
        self.recorded.append(
            Recorded(
                step=str(step),
                namespace=_innermost(scope.namespaces),
                value=Entry.from_json(value).value,
            )
        )
        self._written += 1
        if self._after is not None and self._written >= self._after:
            raise _Interrupted(
                f"the harness interrupted this run after {self._written} step(s) recorded, which "
                f"is what `interrupt_after={self._after}` asked for"
            )

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        return await self._store.namespaces(scope)

    async def remove(self, scope: RunScope) -> None:
        await self._store.remove(scope)


@dataclass(frozen=True, slots=True)
class Harness:
    """One all-fakes bundle, one run label, and the two operations a workflow author drives.

    Built by `harness()` below and never directly: the constructor takes the wrapped ledger, which
    is this module's own and not a caller's to supply. Frozen for `Services`' reason - what a test
    was assembled with should not change halfway through it - and every method returns `None`, the
    things worth reading being `recorded`, `fakes` and whatever the workflow itself left behind.
    """

    fakes: container.FakeServices
    """The bundle every run here is on, and everything a test asks afterwards.

    `container.FakeServices` itself rather than a copy of its fields: `fakes.repository` is what the
    run committed into, `fakes.verifier.answers(...)` closes the merge gate, `fakes.clock.advance
    (...)` moves time, `fakes.terminal` is what screens were shown on, and `fakes.services` is the
    port-typed bundle to hand to `api` directly. Its `store` is the recording one this harness
    wrapped, which delegates every call - so reading `run.json` back through it reads the same
    ledger the run wrote."""

    scope: RunScope
    """Where this harness's runs are recorded: the project and the label, at depth zero.

    Exposed because it is what the other three `api` operations take. `api.clear(harness.fakes
    .services, harness.scope.project, harness.scope.label)` is the line, and this module wraps
    none of them."""

    _ledger: _Ledger = field(repr=False, compare=False)
    """The `Store` wrapping the bundle's own - what records entries and what stops a run.

    Private because it is a mechanism and not an answer: `recorded` below is the answer, and a
    caller holding this could arm an interruption outside a `run` or a `resume` and have it fire in
    whichever came next."""

    @property
    def recorded(self) -> tuple[Recorded, ...]:
        """Every entry this harness's runs have written, oldest first, across every invocation.

            assert [entry.step for entry in harness.recorded] == ["implement", "review"]

        **A replayed step is absent from this**, which is the property worth building a test on:
        §3.6's replay "returns the stored value without running", writing nothing, so a step that
        appears here twice across a run and a resume is a step whose fingerprint moved between them
        and whose agent was paid for twice. That is the whole of what "resume does not redo
        completed work" means, and it is one comparison.

        Across invocations and never cleared, deliberately: the interesting count spans a run and
        the resume after it, and a harness that reset here would make the two look like one.
        """
        return tuple(self._ledger.recorded)

    async def run[P](
        self,
        workflow: Workflow[P],
        *flags: str,
        base_ref: str | None = None,
        interrupt_after: int | None = None,
    ) -> None:
        """Start a run of `workflow` with `flags`: `agl run <workflow> -n <label> <flags>` (§3.10).

            await harness.run(fix, "-r", "add oauth")
            await harness.run(fix, "-r", "add oauth", interrupt_after=1)

        `flags` are the workflow's own, exactly as a person would type them, and are parsed by the
        very parser `agl run` uses - so a required flag left out is the `InputError` an operator
        would have got, before anything is written. The module docstring argues why there is no
        parameter taking an instance of the params dataclass instead.

        `base_ref` is `--from`, and `None` means the fake repository's default branch. `interrupt_
        after=k` lets exactly `k` steps record their results and then abandons the run at that
        boundary - the module docstring is emphatic that this is an interruption and not a kill, and
        names what a real one costs and where to find it.

        **`k` counts entries and not calls**, which is the same thing for a sequential workflow and
        is not for a concurrent one: a workflow whose children run under a `TaskGroup` decides by
        its own interleaving which step lands the k-th entry, so a sweep over kill points there is
        a sweep over *depths* rather than over named steps. §3.6 makes the same point from the other
        side about the fingerprint counter. A workflow that takes no step at all cannot be
        interrupted here, there being no entry to count.

        Raises whatever `api.run` raises, untouched and including a workflow's own `Stop`: the point
        of testing through the real entry point is that the refusals are the real ones. The single
        exception is the interruption this method armed itself, which is caught here because the
        caller asked for it.
        """
        point = _resolvable(workflow)
        with self._interrupting(interrupt_after):
            await api.run(
                self.fakes.services,
                self.scope.project,
                workflow.name,
                self.scope.label,
                flags,
                base_ref=base_ref,
                points=(point,),
            )

    async def resume[P](
        self, workflow: Workflow[P], *, interrupt_after: int | None = None
    ) -> None:
        """Continue the run from its record: `agl resume <label>` (§3.10). No flags, by design.

            await harness.run(fix, "-r", "add oauth", interrupt_after=1)
            await harness.resume(fix)

        The workflow is passed again because `api.resume` loads it from the registry by the name the
        record holds, and this harness has no installed package to load it from - the entry point is
        composed from the object exactly as `run` composes it. Everything else comes off the record,
        params included: §3.3's "persisted into `run.json`, which is why `agl resume auth` takes no
        flags", which is why this signature has none either.

        The same run, walked again. Steps with an entry replay and write nothing, so `recorded`
        after this holds one line per step that actually ran; `interrupt_after=` counts only what
        *this* invocation writes, so a sweep over kill points can interrupt a resume too.
        """
        point = _resolvable(workflow)
        with self._interrupting(interrupt_after):
            await api.resume(
                self.fakes.services, self.scope.project, self.scope.label, points=(point,)
            )

    @contextmanager
    def _interrupting(self, after: int | None) -> Iterator[None]:
        """Arm the ledger for this one invocation, and swallow the interruption it raises.

        A context manager because the arming and the disarming have to be one thing: an interruption
        left armed would fire inside the *next* call, at a boundary nobody asked about. The counter
        is reset here rather than accumulated, which is what makes `interrupt_after=` mean the same
        number on a resume as on a run.

        Two shapes are caught. A workflow that steps sequentially raises `_Interrupted` straight out
        of `api.run`; one that runs its children under a `TaskGroup` - which is what `split` does -
        has it wrapped in a `BaseExceptionGroup`, so the group is split and anything that is not
        this module's interruption is re-raised. `asyncio.gather` needs neither, propagating the
        first exception as itself.
        """
        if after is not None and after < 1:
            raise InputError(
                f"`interrupt_after={after}` asks for a run interrupted before its first step has "
                f"recorded anything, which is a run that did nothing - there would be no entry to "
                f"replay and a resume would walk the whole workflow again. The smallest one that "
                f"leaves something on the ledger is 1"
            )
        self._ledger.interrupt_after(after)
        try:
            yield
        except _Interrupted:
            return
        except BaseExceptionGroup as group:
            _, rest = group.split(_Interrupted)
            if rest is not None:
                # `from group` and not `from None`: what the harness stopped is part of why the
                # rest of the group happened, and a reader chasing a sibling failure wants both.
                raise rest from group
        finally:
            self._ledger.interrupt_after(None)


def harness(
    where: Path,
    *,
    agent: Agent | None = None,
    files: Mapping[str, bytes] | None = None,
    build: str = container.FAKE_BUILD,
    terminal: Terminal | None = None,
    project: str = _PROJECT,
    label: str = _LABEL,
) -> Harness:
    """A harness over a fresh all-fakes bundle, rooted at `where`. Nothing outside it is touched.

        harness = testing.harness(tmp_path, agent=agent, files={"src/a.py": b"pass\\n"})

    `where` is a directory this harness may use - `pytest`'s `tmp_path` is what it is written for -
    and the only thing that goes in it is `<where>/trees`, the checkouts the workspace fakes make.
    It must be absolute, which `TreesRoot` refuses otherwise and says why: a relative root resolves
    against whatever directory the process started in, and AGL spent a deliverable removing that
    read.

    `agent` is what every role's agent does, as one function of the task in front of it - see
    `agl.sdk.testing`. `None` means each provider's own unscripted default, which asks a question,
    calls every tool the task declares and says what it did: enough to run a whole workflow through
    without writing an agent first, and never a substitute for one when the payload matters.

    **An agent that returns only a `Reply` leaves an empty branch, and this is the trap to know
    about before writing one.** No field on a `Reply` touches the worktree and `commit_all` is a
    no-op on a clean one, so every `commit=` the workflow passes records the head it started from
    and the three ways of writing one - a literal message, a computed message, and no `commit=` at
    all - are indistinguishable in their effect. Write into `task.workspace`, an absolute `Path` to
    this step's checkout, before returning the `Reply`; that is the side effect a real agent would
    have had, and the module docstring argues it in full. The default agent has the same shape and
    the same silence: it calls tools and says things, and it changes no file.

    `files` seeds the fake repository, `{path: bytes}`, and is the only way in: `FakeRepository`'s
    mutators are that adapter package's private vocabulary, so seeding at construction is what
    `container.fakes()` offers and this passes through.

    `build` is the command the merge gate runs, defaulting to the same constant a test scripts a red
    gate against - `harness.fakes.verifier.answers(container.FAKE_BUILD, passed=False)`. A workflow
    that never integrates never reaches it.

    `terminal` replaces the headless one, and the module docstring says when that is needed and what
    the answer is: a board needs nothing, and an interactive screen needs a terminal that can answer
    one, which is `answering([...])` below.

    `project` and `label` name the run. Both are validated by `ids.py` on the way in, so a label
    with a slash in it is refused here rather than becoming a path.
    """
    fakes = container.fakes(TreesRoot(where / _TREES), files=files, build=build, agent=agent)
    if terminal is not None:
        # Both views at once - see `FakeServices.with_terminal`, which exists because the
        # `replace(harness.services, terminal=...)` this used to be left the sibling field naming
        # the terminal it had just discarded.
        fakes = fakes.with_terminal(terminal)
    return over(fakes, project=project, label=label)


def over(
    fakes: container.FakeServices,
    *,
    project: str = _PROJECT,
    label: str = _LABEL,
) -> Harness:
    """A harness over a bundle you built yourself. `harness()` above is this, with the bundle made.

        script = ...                                    # an adapters/*/fake.py `Script`
        harness = testing.over(container.fakes(TreesRoot(tmp_path / "trees"), claude=script))

    **This is the escape hatch, and it is a named one rather than an implied one.** A `Reply` is a
    value computed before the run, so it cannot branch on what a question was answered - §3.7's
    negotiation is N rounds inside one session and `sdk/testing.py` says plainly that the vocabulary
    does not reach it. What does reach it is a raw per-provider `Script`, which
    `container.fakes(claude=..., openai=...)` still takes; without this function that script could
    be run but not resumed, interrupted or read back, which would make the escape hatch a way out of
    the harness rather than a way through it.

    It is also how a bundle that is not all fakes gets driven: `container.fakes()` composes, and a
    caller who has substituted the real git ports into it - `harness.with_terminal(...)`, or the
    `replace(fakes.services, workspaces=GitWorkspaceProvider(...))` that `tests/test_api.py` does -
    hands the result here and gets the same two operations over it.

    The bundle's store is wrapped on the way in, which is what `recorded` and `interrupt_after=` are
    both built on, and `fakes.store` on the returned `Harness` is that wrapper - `FakeServices
    .with_store` keeping the two views of it in agreement. Everything else is the bundle's own
    object, by identity.
    """
    ledger = _Ledger(fakes.store)
    return Harness(
        fakes=fakes.with_store(ledger),
        scope=RunScope(ProjectName(project), RunLabel(label)),
        _ledger=ledger,
    )


def answering(responses: Sequence[Press | int] = ()) -> ScriptedTerminal:
    """A `Terminal` that answers `responses` in order. Hand it to `harness(terminal=...)`.

        term = testing.answering([0, Press(1, "not yet - land the other one first")])
        harness = testing.harness(tmp_path, agent=agent, terminal=term)

    **This is what a workflow that asks a person something is tested on.** The default harness
    builds a headless terminal, which refuses a `Screen[T]` with `UpstreamUnavailable` because there
    genuinely is nobody there - so a workflow whose `on_question` handler routes to §3.7's approval
    screen exits 6 until you pass one of these.

    `Press(response, typed)` is one gesture: which of the screen's own responses, by position in the
    order the view offered them, and what was typed into it - which matters only for a `TextInput`,
    exactly as it does for a person. **A bare `int` means `Press(int)`**, which is the port's own
    coercion rule ("anywhere a component is expected, a bare `str` means `Text`") applied one
    vocabulary over, so a script of approvals is `answering([0, 0, 0])`.

    Each gesture is spent on **whatever is displayed** when it is reached, which is the
    highest-priority queued screen - the same one a person would have answered, so a conflict at
    priority 10 takes the next gesture ahead of an agent question that was already waiting.

    **An exhausted script waits rather than failing**, which is honest and is the one thing that
    will surprise you: there are no timeouts anywhere in §3.7, so a question with no gesture left
    behaves like a real terminal nobody is sitting at, and the test hangs instead of failing. Assert
    `not term.remaining` afterwards to catch a script the run never fully spent.

    The terminal comes back at its own type rather than as a `Terminal`, because reading it back is
    half of what it is for: `remaining` is the script's leftovers, `displayed()` is what a person
    would be looking at now, `slot()` is the board still updating behind a question, and `respond()`
    drives one built from an empty list a gesture at a time. It is a `Terminal` wherever one is
    wanted, this module's `terminal=` included.

    The delegation is to `config/container.py` because that module is the only one allowed to
    construct an adapter, and this one is a sibling of `agl.cli` two layers above it (contract 5).
    So the class lives in `adapters/rich_terminal/scripted.py`, the `new` is in the composition
    root, and the name an author writes is here.
    """
    return container.answering(responses)


def a_run[P](
    harness: Harness,
    params: P,
    *,
    base: str = _BASE,
    activity: str | None = None,
) -> Run[P]:
    """A `Run` over a harness's bundle, to call a view with. Nothing it builds runs anything.

        run = testing.a_run(harness, FixParams(request=REQUEST))
        assert views.board(run, REQUEST) == Screen(
            Rows([Row("request", REQUEST), Row("agent", "")])
        )

        working = testing.a_run(harness, FixParams(request=REQUEST), activity="Bash: pytest -q")
        assert views.board(working, REQUEST) != views.board(run, REQUEST)

    **This exists because §3.7's board takes the live `Run` and not a string.** `show` registers a
    view function and its arguments and invokes them again every frame, which is what makes
    `Text(run.activity or "")` live with no component of its own - so a board that was handed
    `run.activity` as a value would be frozen at the moment of the `show`, which is exactly what
    per-frame re-invocation exists to avoid. An author testing their own board therefore needs a
    `Run`, and `agl.sdk` has no way to give them one: `Run` is on the front door as a *type*, and
    `services` is `sdk/_engine`'s bundle while `scope` is a `ports.home_layout.RunScope`. Both are
    the framework's to compose, and until this existed a workflow's own test file composed them by
    hand.

    **The name is `a_run` and it is module-level, not a `Harness` method.** `Harness.run` already
    means "drive `api.run`", and two members a keystroke apart meaning *start a whole run* and
    *build an object that runs nothing* is a worse cost than an unusual function name: the mistake
    would be silent in one direction, `harness.a_run(...)` reading as a typo for the operation. It
    is a function beside `harness()`, `over()` and `answering()` for the same reason those are -
    this module's public surface is functions that build things and one class that drives two.

    **It takes the `Harness` because that is what already holds both of the things a `Run` needs**
    and neither is a caller's to invent: `harness.fakes.services` is the all-fakes bundle and
    `harness.scope` is the project and label its runs are recorded under. Taking a `FakeServices`
    instead would leave the scope to be composed at the call site out of `ports.ids`, which is the
    reach this is here to remove.

    `params` is an instance of the workflow's own params dataclass, at the type it declared - the
    one argument that is genuinely the author's, and what makes the result a `Run[P]` their view
    can be annotated against. It is positional because a `Run` without params is not a thing this
    builds; there is no default, `P` having no value this module could invent.

    `base` is where this namespace's chain would start. It defaults to a well-formed sha that names
    no state in the bundle's repository, which is honest for everything this builds: nothing here
    takes a step, so the value is never resolved, never restored to and never fingerprinted. A test
    that does go on to take a step passes the head it wants.

    **`activity=` is where this `Run` starts, and it goes through `reports` below** - the two of
    them are between them the one sanctioned write of the engine's activity cell in this
    repository. `run.activity` is a property over `Steps._activity`, a private attribute of a
    private class under `sdk/_engine/`, and nothing public writes it - correctly, because the only
    thing that sets it for real is an adapter reporting a line from inside a running step, through
    a callback the port hands out for the duration of one call (§3.7: live-only, never persisted).
    A board is worth testing at an activity anyway, so the reach is here, once, where it can say
    what it is - rather than in every author's test file, which is what stage 17 recorded as the
    worst line in the stage. `None` is the ordinary value and means what it means everywhere else:
    nothing is running, and the cell has never been written.

    **A keyword and not only `reports(run, ...)` afterwards**, because the overwhelmingly common
    board test asserts one frame at one activity, and `a_run(harness, params, activity=line)` is
    that in one line rather than two. What a keyword cannot express is a board *moving*, which is
    the whole of why `reports` exists beside it rather than inside it.

    **Nothing this builds runs, commits or shows anything.** The bundle is here so that
    `Run.__post_init__` has something to build a `Steps` out of; no workspace is opened, no ledger
    is touched, no terminal is drawn on and `harness.recorded` stays exactly as long as it was. A
    `Run` this returns is a value to call a pure view with, and `harness.run(workflow, ...)` is
    still the only thing in this module that makes a run happen.
    """
    run: Run[P] = Run(
        params=params, services=harness.fakes.services, scope=harness.scope, base=base
    )
    # Through `reports` and not by reaching in here, so there is one writer of that cell in this
    # module rather than two. Unconditional, because the cell is `None` until something writes it
    # and `activity=None` is therefore what it already says.
    reports(run, activity)
    return run


def reports(run: Run[object], activity: str | None) -> None:
    """Say that the agent serving `run` is now doing `activity` - or `None`, that it stopped.

        run = testing.a_run(harness, params, activity="Read: src/retry.py")
        first = views.board(run, REQUEST)

        testing.reports(run, "Bash: pytest -q")

        assert views.board(run, REQUEST) != first        # the same object, read again
        assert views.board(run, REQUEST) == views.board(run, REQUEST)

    **This is `a_run`'s other half, and the same one sanctioned reach.** `run.activity` is a
    property over `Steps._activity`, a private attribute of a private class under `sdk/_engine/`,
    and this is what stands in for the thing that writes it for real: an adapter calling
    `on_activity` from inside a live step, through a callback the port hands out for the duration
    of one `AgentRunner.run` (§3.7 - the string is the adapter's own, live-only, never persisted).
    The whole of the framework's part in it is an assignment, and so is the whole of this.

    **A constructor argument cannot express the property §3.7's design rests on**, which is why
    this exists beside `a_run` rather than being folded into it. `show` registers a view function
    and its arguments and invokes them again every frame, so `Text(run.activity or "")` is live
    with no component of its own - and what makes that *true of a given board* is that the same
    `Run`, read twice with a report in between, yields two different screens. Two `Run`s built at
    two activities do not say that: they say the board is a function of its argument, which a board
    caching per object would satisfy too. A test that wants to watch a board move has to play the
    adapter twice, and this is that call.

    `None` is the ordinary value on both sides of it - nothing is running - and is what the cell
    holds between steps, before an adapter's first line, and for the whole of a step replayed from
    the journal. So `reports(run, None)` is how a test says the step ended, which is the other
    frame a board has to render honestly.

    Takes `Run[object]` rather than `Run[P]`: the activity cell knows nothing about a workflow's
    params, and `Run` is covariant in them, so a `Run[FixParams]` is accepted with no cast at the
    call site and nothing here is generic in a parameter it never reads.

    **Nothing else moves.** No entry, no fingerprint, no store write, no frame drawn - §3.7 keeps
    activity out of every one of those, and a function here that did any of them would be
    describing a mechanism the framework does not have. It writes one string and returns.
    """
    # The reach both this module's public builders make, in one line and in one place. Written
    # through `_steps` rather than through a public setter on `Steps`, because a setter there would
    # be a second way to report activity that no adapter goes through - and `sdk/_engine/steps.py`'s
    # "the only writer is a callback the port hands out during a live call" would stop being true
    # of the framework rather than merely of this harness.
    run._steps._activity = activity


def _innermost(namespaces: Sequence[Namespace]) -> str | None:
    """The worktree a scope addresses, or `None` for the run's own. See `Recorded.namespace`."""
    if not namespaces:
        return None
    return str(namespaces[-1])


def _resolvable[P](workflow: Workflow[P]) -> EntryPoint:
    """The entry point `workflow` would be registered as, checked by loading it back.

    §3.3's registration line is `fix = "agl.workflows.fix:fix"`, and this composes exactly that
    string out of the decorated function's own module and name - which is what makes the check
    below meaningful rather than circular: the resolution is `config/registry.py`'s, the same one an
    installed workflow gets, so a workflow this returns for is a workflow an entry point can reach.

    **The refusal is the interesting half.** `@workflow` returns a `Workflow` and the decorated
    *name* is what an entry point points at, so the two ways this fails are a workflow declared
    inside a function - whose `__qualname__` carries `<locals>` and names no module attribute - and
    one bound to an attribute spelled differently from its function. Both are refused here, with the
    reason, rather than discovered by whoever first tried to install the package.
    """
    where = workflow.fn.__module__
    named = workflow.fn.__qualname__
    if "." in named:
        raise InputError(
            f"the workflow {workflow.name!r} is declared as {named!r} inside something else, so "
            f"there is no module attribute for an entry point to name. A workflow is registered as "
            f"`<module>:<name>` (§3.3) and the harness resolves it the way an installed one is "
            f"resolved, so declare it at the top level of its module"
        )
    point = EntryPoint(name=workflow.name, value=f"{where}:{named}", group=registry.GROUP)
    resolved: Workflow[object] = registry.load((point,), workflow.name, Workflow)
    if resolved is not workflow:
        raise InputError(
            f"the workflow {workflow.name!r} was handed to the harness, but {point.value!r} - the "
            f"entry point its own module and function name compose - resolves to a different "
            f"object. `@workflow` returns the `Workflow` and the decorated name is what an entry "
            f"point points at, so this happens when the decorated function is bound to a name "
            f"other than its own. Register it as `{where}:<the attribute it is bound to>` and give "
            f"the harness that same object"
        )
    return point
