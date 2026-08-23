"""A step programme that can be killed at a step boundary, run in a process of its own.

`tests/sdk/test_kill_and_resume.py` is §3.6's own acceptance criterion - "run to completion, kill at
every step boundary, resume, assert identical final state" - and this module is the half of it that
has to be somewhere else. The test cannot kill itself: what a killed agent does is stop, mid-run,
without unwinding, and the only way to watch that from a test is to do it to somebody else.

**The kill is `os._exit`, and the distinction is the whole point.** An exception would run `finally`
blocks, `atexit` handlers, `__del__` methods and asyncio's cancellation path; a process that is
killed runs none of them, and §3.6's design rests on that - "a crashed step leaves no entry, so the
next run resets to the last good head and starts clean" is a claim about a process that got no
chance to tidy up. So `_Programme._maybe_exit` calls `os._exit(0)` at the k-th step boundary, and
this module registers both an `atexit` hook and a `finally` clause that append a marker to the log
for the only reason a marker like that is ever worth writing: the parent asserts the markers are
**absent** after a kill and present after a clean finish, which is how "this was a kill and not an
unwind" becomes something measured rather than something claimed.

**Why a subprocess buys the other half at the same time.** Three things §3.6 rests on fail only
across a process boundary, and every one of them fails silently:

  * a `frozenset[Restriction]` reaching the canonical text in iteration order rather than sorted
    (rule 2) has a *fixed* order for the life of one interpreter, so a same-process resume computes
    the digest it wrote and hits;
  * a dataclass in `**inputs` canonicalised with `repr()` rather than walked field by field
    (rule 3) carries an object id that does not move while the object is alive, likewise;
  * `Fingerprints` really being rebuilt from nothing on a resume - `n` is never persisted - is
    trivially true here and merely conventional in a same-process test, which is free to reuse the
    counter object it already had.

The parent therefore runs the killed process and the resuming process under **different**
`PYTHONHASHSEED` values, and the roles below carry the two terms that make that matter: a
`restrictions` set holding *all four* `Restriction` members, and an input that is a list of the
workflow's own dataclasses with a `frozenset[str]` field inside it. Without those two the seeds vary
nothing and the second process proves only that the first one wrote some files.

**Two more things a second process is what makes visible, and neither is about hash seeds.** A
*replay* is a value read back off a real ledger written by a process that no longer exists, so the
two claims deliverable 12.0 corrects are stated here in their end-to-end form. The `crash`
programme raises inside a step and retries it within one run, and the second process must hit the
retry's entry and run nothing at all - which only holds if the crashed attempt claimed no slot. And
the `retyped` and `renested` variants hand the same field names and the same values under a
*different type*, and the second process must **re-run** rather than replay - which is rule 6, and
the one correction whose failure hands back a wrong answer instead of costing a re-run.

**The workspace is real git, and that is the one place the fake is not good enough.** The git fakes
keep their commits in memory and re-seed themselves per process, so a commit made before the kill
would simply not exist afterwards - the resuming process would be looking at a different repository
and every assertion about a chained `head` would be about nothing. A real repository is the only
thing that survives its own process.

**Everything is constructed here rather than through `config.container`.** `container.real()` also
builds agent runners, a routing runner and a terminal, none of which a programme with no agent in it
has any use for, and two of which would want credentials. What a programme needs is the three ports
§3.6's loop actually touches - a `Store`, a `WorkspaceProvider` and a `Clock` - so those three are
named here directly. Tests are outside `agl.*`, so contract 5 has nothing to say about it, and
`tests/adapters/` already imports adapters the same way.

**Two shapes this instrument stands in for, and neither is being built here.**

  * *A worker is a function, not an agent.* Stage 12's `Run.step` dispatches an `AgentTask`; the
    workers below write files and hand back JSON, because what is under test is the ledger and not
    the vendor. Each invocation appends one line to the log, which is how the parent counts what
    ran - "the worker was not called" is the whole of what a replay hit *is*.
  * *A child worktree is opened at the run's pinned base, and its `Journal` starts there too.*
    Stage 13.1 derives a child's base properly and 13.4 resolves the run's own from its record;
    neither exists. The pinned base is used for both because it is the one value that is the same
    string in every process at every kill point, which is exactly what a property test over kill
    points needs. §3.9's "a child is cut from the run's branch by name" is the shape 13.1 will
    build; using it here would make a child's starting head depend on how far the *root* had got
    before the kill, which would be this instrument deciding the answer to the question being asked.

Run as `python tests/instruments/replay.py '<json>'`. The configuration arrives as one JSON object
on argv so that a reader of a failing test can copy the command out of the assertion and run it.
Importable as `instruments.replay` as well - `tests/` is on `sys.path` (see `tests/conftest.py`) -
which is how the parent reads `PROGRAMMES` for the labels it expects rather than restating them.
"""

import asyncio
import atexit
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.system_clock import SystemClock
from agl.ports.agent import Claude, Restriction, Tool, ToolResult
from agl.ports.clock import Clock
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace, WorkspaceProvider
from agl.sdk._engine.journal import Fingerprints, Journal

__all__ = ["Config", "PROGRAMMES", "Programme", "SIBLINGS", "driver_path", "main"]


# --- what a role is made of ----------------------------------------------------------------------


@dataclass(frozen=True)
class Budget:
    """A dataclass **nested** inside the one a workflow passes, and rule 6's sharpest term.

    One integer field, because the value is not the point: the point is that this sits one level
    down. `dataclasses.asdict` recurses, so a type name attached to what `asdict` returned names
    the outer type and erases this one entirely - which is the half of rule 6 that a walker tagging
    only the top level gets wrong while looking correct. `Ceiling` below is what makes that
    measurable across a process boundary.
    """

    tokens: int


@dataclass(frozen=True)
class Ceiling:
    """`Budget`'s twin: the same one field, the same value, a different type.

    Swapped in behind variant `renested`, inside a `Constraint` that does **not** change - so the
    only thing that moved between the two runs is a type name one level down. A journal that
    fingerprinted the shape and not the type finds the first run's entry, replays it, and answers
    a question nobody asked.
    """

    tokens: int


@dataclass(frozen=True)
class Constraint:
    """A workflow's own dataclass, passed in `**inputs` exactly as §3.3's tickets example does.

    Three fields and each is deliberate. `area` is ordinary text. `tags` is a `frozenset[str]`, and
    it is the term that makes rule 3 falsifiable across processes: the canonical walker hands a
    frozen dataclass's set field on **as a set**, so it has to sort at that depth too - and the
    one-line shortcut, `repr()`, renders the set in iteration order, which `PYTHONHASHSEED`
    randomises. So the `repr` of one of these is a different string in the next process even when
    nothing about the value changed, which is rule 2's failure arriving through rule 3's door, and
    it is measured rather than assumed: the parent asserts the two seeds it uses really do render
    this differently before it believes anything else. `budget` is rule 6's nested term.

    The default `repr` is kept, rather than `repr=False`'s heap address, because an address is only
    unstable if the allocator happens to move - a real effect, but a weaker lever than a set whose
    order is randomised by construction. `test_journal.py` takes the address route for rule 3 in
    isolation; this file wants the term that cannot quietly stop varying.

    `budget` is annotated as either twin so that one declaration carries both variants. The
    annotation is not enforced at runtime and the fingerprint never sees it; what it buys is that
    `renested` swaps a *nested* type while the outer type is held identical, which is the only
    arrangement in which the nested half of rule 6 can fail on its own.
    """

    area: str
    tags: frozenset[str]
    budget: Budget | Ceiling


@dataclass(frozen=True)
class Requirement:
    """`Constraint`'s twin - identical field names in identical order, and a different type.

    Swapped in behind variant `retyped`, which is §3.6's own pair (`Finding` and `Ticket`) wearing
    this file's names. Declared beside `Constraint` rather than derived from it, because two
    dataclasses are what the rule is about and a factory would leave a reader wondering whether
    the types really were distinct.
    """

    area: str
    tags: frozenset[str]
    budget: Budget | Ceiling


async def _unused(payload: Mapping[str, JsonValue]) -> ToolResult:
    """No agent runs in this instrument, so no tool handler is ever called. A `Tool` needs one all
    the same, and `base_of` must keep it out of the fingerprint - `test_journal.py` pins that."""
    return ToolResult(text="")


# All four members, which is rule 2's term. A role declaring `frozenset(Restriction)` is the same
# role tomorrow, and a journal that iterated it rather than sorting it would compute a different
# base in the resuming process and re-run every step in silence.
RESTRICTIONS: Final = frozenset(Restriction)

TOOL: Final = Tool(
    name="report",
    description="report what this step produced",
    payload_schema=MappingProxyType({"type": "object"}),
    handler=_unused,
)

# The values, once, so that the three tuples below cannot drift apart. "Identical field names and
# identical values, under different types" is the whole of what makes a retyped run's re-run mean
# what it is claimed to mean, and building all three from one source makes that structural rather
# than something a reader has to check character by character. Four tags rather than two, and that
# is not decoration: a two-element set has only two iteration orders, so no choice of hash seeds
# could make three processes render it three different ways - and the parent's non-vacuity check
# would be asking for something arithmetic forbids.
_VALUES: Final = (
    ("auth", frozenset({"oauth", "callback", "session", "refresh"}), 40_000),
    ("api", frozenset({"routes", "handlers", "schemas", "errors"}), 25_000),
)

# The dataclass input, on the first step of every programme. A list of them, because §3.3 passes a
# list and because a list is what makes the walker recurse before it reaches the set.
CONSTRAINTS: Final = tuple(
    Constraint(area=area, tags=tags, budget=Budget(tokens=tokens)) for area, tags, tokens in _VALUES
)

# Variant `retyped`: the **outer** type swapped, which is §3.6's `Finding`/`Ticket` pair.
RETYPED: Final = tuple(
    Requirement(area=area, tags=tags, budget=Budget(tokens=tokens))
    for area, tags, tokens in _VALUES
)

# Variant `renested`: the outer type held identical and only the **nested** one swapped, which is
# the half `dataclasses.asdict` erases. Two variants and not one, because a single input carrying
# both swaps would re-run under a walker that tagged only the top level - and that walker is
# exactly the wrong one this pair exists to catch.
RENESTED: Final = tuple(
    Constraint(area=area, tags=tags, budget=Ceiling(tokens=tokens))
    for area, tags, tokens in _VALUES
)

# The two child namespaces §3.6 names when it explains why the counter is scoped per namespace.
SIBLINGS: Final = ("T-01", "T-02")


# --- the configuration one child process is handed -----------------------------------------------


@dataclass(frozen=True, slots=True)
class Config:
    """One child process's whole world: where to write, what to run, and when to die.

    A frozen record rather than a pile of argv flags, because the parent builds it, serialises it
    and then reads the same field names back out of the log when an assertion fails. `kill_after` is
    the parameter the whole file exists for: `None` runs the programme to its end, and `k` exits the
    process the moment the k-th step has returned - which is after that step's entry is on disk and
    before the next step begins, the only boundary §3.6's ledger makes any promise about.
    """

    home: str
    repo: str
    trees: str
    project: str
    label: str
    base: str
    programme: str
    variant: str
    kill_after: int | None
    order: tuple[str, ...]
    log: str
    tag: str

    def to_json(self) -> str:
        """The argv string. Written out by key rather than by `asdict` so the child's parser and
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
                "variant": self.variant,
                "kill_after": self.kill_after,
                "order": list(self.order),
                "log": self.log,
                "tag": self.tag,
            }
        )

    @classmethod
    def from_json(cls, text: str) -> Config:
        """The same record, back. Every field is narrowed rather than trusted: this runs in a child
        process whose only diagnostic channel is a non-zero exit and a line on stderr."""
        parsed: object = json.loads(text)
        if not isinstance(parsed, dict):
            raise SystemExit(f"replay: configuration is a JSON object, not {type(parsed).__name__}")
        data: Mapping[str, object] = parsed
        kill = data.get("kill_after")
        if not (kill is None or isinstance(kill, int)):
            raise SystemExit("replay: 'kill_after' is an integer step count or null")
        order = data.get("order")
        if not isinstance(order, list):
            raise SystemExit("replay: 'order' is a list of namespace names")
        return cls(
            home=_text(data, "home"),
            repo=_text(data, "repo"),
            trees=_text(data, "trees"),
            project=_text(data, "project"),
            label=_text(data, "label"),
            base=_text(data, "base"),
            programme=_text(data, "programme"),
            variant=_text(data, "variant"),
            kill_after=kill,
            order=tuple(str(name) for name in order),
            log=_text(data, "log"),
            tag=_text(data, "tag"),
        )


def _text(data: Mapping[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise SystemExit(f"replay: {key!r} is a string, not a {type(value).__name__}")
    return value


# --- the programme runner ------------------------------------------------------------------------


class _Programme:
    """One process's journals, its kill counter, and the log the parent counts workers from.

    Journals are cached per namespace, which is not an optimisation: §3.6 keeps `last_good` per
    namespace and in memory, so a second `Journal` over one scope would be a second chain starting
    at the base again - and a `Fingerprints` shared with it would then be the only thing keeping
    the counts straight. One `Fingerprints` for the whole run and one `Journal` per namespace is the
    composition `sdk/_engine/worktrees.py` will have at stage 13.
    """

    def __init__(
        self,
        config: Config,
        store: Store,
        provider: WorkspaceProvider,
        clock: Clock,
    ) -> None:
        self.config = config
        self._store = store
        self._provider = provider
        self._clock = clock
        self._label = RunLabel(config.label)
        self._scope = RunScope(ProjectName(config.project), self._label)
        self._fingerprints = Fingerprints()
        self._journals: dict[str | None, Journal] = {}
        self._workspaces: dict[str | None, Workspace] = {}
        self._done = 0

    async def journal(self, namespace: str | None = None) -> Journal:
        """The journal for one namespace, opening its checkout the first time it is asked for.

        Both the checkout and the journal start at the run's **pinned** base, for the reason the
        module docstring gives at length: it is the one head that is the same string in every
        process at every kill point, and a child whose starting head depended on how far the root
        had got before the kill would be this instrument answering the question under test.
        """
        if namespace not in self._journals:
            workspace = await self._provider.open(
                self._label,
                None if namespace is None else Namespace(namespace),
                self.config.base,
            )
            scope = self._scope if namespace is None else self._scope.inside(Namespace(namespace))
            self._workspaces[namespace] = workspace
            self._journals[namespace] = Journal(
                self._store, scope, workspace, self._clock, self._fingerprints, self.config.base
            )
        return self._journals[namespace]

    def workspace(self, namespace: str | None = None) -> Workspace:
        """The checkout `journal` opened. Only a worker asks, and only to put a file in it."""
        return self._workspaces[namespace]

    async def step(
        self,
        label: str,
        name: str,
        *,
        namespace: str | None = None,
        instructions: str,
        inputs: Mapping[str, object],
        commit: str | None = None,
        does: Callable[[JsonValue], None] | None = None,
        value: JsonValue = None,
        waits: asyncio.Event | None = None,
    ) -> JsonValue:
        """One journalled step, and the boundary after it.

        `label` is what the log records and is unique within a programme - `review#1`, or
        `T-01/implement` - because "which worker ran" is the only observation the parent makes and
        two calls to one step name are two different answers to it.

        The worker writes its line as soon as it is released and before it does anything else, so
        that a process killed at a later boundary still has the line for this one on disk:
        `os._exit` flushes nothing, and each line is written, flushed and fsynced on its own for
        the same reason.

        `waits` holds the worker - and only the worker - until something opens the gate. The step
        around it has already looked its entry up and already restored, so a gated step is a step
        genuinely in flight rather than one that has not started, which is what the concurrent
        siblings programme needs it to be.
        """
        journal = await self.journal(namespace)

        async def _worker() -> JsonValue:
            # Two lines and not one, and the gap between them is the whole of what makes the
            # siblings programme's concurrency visible from outside. `reached` says this step is in
            # flight - its counter is taken, its entry has been looked up and its worktree has been
            # restored - and `worker` says it actually did something. A gated sibling logs the
            # first and, if the process is killed at the other sibling's boundary, never the second.
            self._log({"reached": label})
            if waits is not None:
                await waits.wait()
            self._log({"worker": label})
            if does is not None:
                does(value)
            return value

        result = await journal.step(
            StepName(name),
            instructions=instructions,
            model=Claude.SONNET,
            restrictions=RESTRICTIONS,
            tools=(TOOL,),
            inputs=inputs,
            worker=_worker,
            commit=commit,
        )
        self._completed()
        return result

    def writes(self, name: str, text: str, *, namespace: str | None = None) -> Callable[
        [JsonValue], None
    ]:
        """A worker that puts one file in its checkout - what an agent leaves behind.

        Handed to `step(does=...)`. On an effect step the following `commit_all` records it; on a
        read-only step the following `restore` takes it away again, which is §3.6's wipe and is
        worth having a programme actually provoke rather than describe.
        """

        def _write(_: JsonValue) -> None:
            target = self.workspace(namespace).path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        return _write

    def at_start(self) -> None:
        """The `k = 0` boundary: nothing has run yet, and a run can be killed there too."""
        self._maybe_exit()

    def _completed(self) -> None:
        self._done += 1
        self._maybe_exit()

    def _maybe_exit(self) -> None:
        if self.config.kill_after is not None and self.config.kill_after == self._done:
            self._log({"killed_after": self._done})
            # The kill. Not `sys.exit`, not `raise`, not `SIGTERM` to self: `os._exit` returns to
            # the kernel from here, so no `finally` below runs, no `atexit` hook registered in
            # `main` runs, no buffer is flushed and no asyncio task is cancelled. That is what a
            # killed agent looks like, and the markers this module writes elsewhere are how the
            # parent proves it is what happened.
            os._exit(0)

    def _log(self, record: Mapping[str, object]) -> None:
        """One line on the log, on disk before this call returns.

        Opened, written, flushed and fsynced per line rather than held on a handle, because the
        process may cease to exist between any two lines and a buffered line is a worker the parent
        would never learn about.
        """
        line = json.dumps({"tag": self.config.tag, **record}, sort_keys=True)
        with open(self.config.log, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


# --- the programmes ------------------------------------------------------------------------------

# The one prompt edit the `edited` variant makes, and the step it lands on. `decompose` is
# deliberately a *read-only* step: its head does not move, so a downstream step that re-runs after
# the edit re-ran because its **inputs** changed and for no other reason. Editing an effect step's
# prompt would change its commit as well, and "inputs or head" is not the claim §3.6 makes.
EDITED_STEP: Final = "decompose"
EDIT: Final = " Group them by area, smallest first."

# The `reworded` variant's wording change, appended to every `commit=` message and to nothing else.
REWORD: Final = ": add the oauth callback route"


def _instructions(config: Config, step: str, text: str) -> str:
    """A step's prompt, with the `edited` variant's edit applied to exactly one step."""
    if config.variant == "edited" and step == EDITED_STEP:
        return text + EDIT
    return text


def _constraints(config: Config) -> list[Constraint | Requirement]:
    """The dataclass inputs, under the types this variant declares.

    Three tuples built from one list of values, so the only difference a variant makes here is a
    type name - which is the whole of rule 6. `retyped` swaps the outer type and `renested` swaps
    the type one level down while holding the outer one still; the parent asserts that each of them
    re-runs the step that carries these, because a step that *replayed* would be handing back a
    result produced from inputs of another type entirely.
    """
    if config.variant == "retyped":
        return list(RETYPED)
    if config.variant == "renested":
        return list(RENESTED)
    return list(CONSTRAINTS)


def _message(config: Config, text: str) -> str:
    """A step's commit message, with variant 3's rewording applied to all of them.

    §3.6 keeps this out of the fingerprint on purpose - "including it would mean editing the wording
    re-runs the agent, which is the opposite of what fingerprinting is for" - so a programme run
    twice, differing only here, must not run a single worker the second time.
    """
    return text + REWORD if config.variant == "reworded" else text


async def _core(run: _Programme) -> None:
    """Five steps, two namespaces, both endings, and one value-carrying edge per step.

    This is the programme the kill-point sweep runs, so its shape is the acceptance criterion's:

      1. `spec`       root, read-only  - carries the dataclass inputs and the four restrictions
      2. `decompose`  root, read-only  - takes `spec`'s value; the step variant 2 edits
      3. `plan`       root, effect     - takes `decompose`'s value, commits a file
      4. `implement`  T-01, effect     - takes `plan`'s value, in a namespace of its own
      5. `report`     root, read-only  - takes `implement`'s value, and scribbles

    **Every step's value carries the value it was given**, and every step's inputs hold the
    previous step's value. That pair is what makes the cascade observable at all: an edit that
    changed a step's answer but not what the next step was told would stop at that step, and a
    fingerprint whose inputs never change cannot show that an upstream edit reached it.

    **What the effect steps write is deliberately *not* a function of the variant.** The commit
    plan makes is byte-identical under either prompt, so its recorded `head` is the same commit id
    both times - which leaves `inputs` as the only term that moved, and lets variant 2 say "this
    re-ran because its inputs changed" rather than "because its inputs or its head changed". Step 4
    is in a child namespace for the same reason from the other direction: its head is chained from
    *its own* ledger, so a commit in the root's line cannot reach it at all.
    """
    config = run.config
    spec = await run.step(
        "spec",
        "spec",
        instructions=_instructions(config, "spec", "state what the request needs"),
        inputs={"request": "add oauth", "constraints": _constraints(config)},
        value={"needs": ["a callback route", "a session store"]},
    )
    tickets = await run.step(
        "decompose",
        EDITED_STEP,
        instructions=_instructions(config, EDITED_STEP, "break the spec into tickets"),
        inputs={"spec": spec},
        # The value is a function of the prompt, so that the edit reaches downstream inputs. A real
        # agent's answer changes when its prompt does; this is the smallest honest stand-in.
        value={"tickets": ["T-01"], "grouped": config.variant == "edited", "from": spec},
    )
    plan = await run.step(
        "plan",
        "plan",
        instructions=_instructions(config, "plan", "order the tickets"),
        inputs={"tickets": tickets},
        commit=_message(config, "plan the work"),
        does=run.writes("plan.md", "the order to do it in\n"),
        value={"order": ["T-01"], "from": tickets},
    )
    built = await run.step(
        "T-01/implement",
        "implement",
        namespace=SIBLINGS[0],
        instructions=_instructions(config, "implement", "implement the ticket"),
        inputs={"plan": plan},
        commit=_message(config, "implement T-01"),
        does=run.writes("src/oauth.py", "the callback route\n", namespace=SIBLINGS[0]),
        value={"built": "T-01", "from": plan},
    )
    await run.step(
        "report",
        "report",
        instructions=_instructions(config, "report", "say what was done"),
        inputs={"built": built},
        # A read-only step that leaves a file behind, so the ending `restore` has something to take
        # away. §3.6: "a read-only role cannot leave anything behind - not a scratch file".
        does=run.writes("scratch/notes.md", "half a thought\n"),
        value={"done": True, "from": built},
    )


async def _retry(run: _Programme) -> None:
    """§3.6's "why the counter": three identical calls in one namespace, `n = 0, 1, 2`.

    Same role, same inputs, same head, no commits - so the three share one `base` and are separated
    only by the counter. A per-`base`-only cache collapses them to one entry and loops forever; what
    this programme adds to `test_journal_walk.py`'s in-process version is that the three addresses
    are reproduced by a **different process**, walking the same three calls in the same order, with
    `n` rebuilt from nothing because it was never persisted.
    """
    for attempt in range(3):
        await run.step(
            f"review#{attempt}",
            "review",
            instructions="review the worktree",
            inputs={"request": "add oauth", "constraints": _constraints(run.config)},
            value={"attempt": attempt},
        )


async def _siblings(run: _Programme) -> None:
    """§3.6's `T-01`/`T-02`: one root step, then two children under one `asyncio.gather`.

    Both siblings call `step("implement", ...)` with the same role, no inputs and the same parent
    head, so their `base` values are identical by construction and only the namespace in the
    counter's key keeps their entries apart. The parent runs the resume with the two **completing**
    in the opposite order, because rule 1's whole point is that the interleaving must not decide who
    gets `n = 0`, and a test that always interleaves the same way cannot see it.

    **The order is a chain and never a timing.** Both `step` calls are started at once and both get
    as far as their worker - counter taken, entry looked up, worktree restored - and then each one
    waits on a gate that the *previous* sibling's completed step opens. Letting the event loop
    settle for a fixed number of turns instead, which is how `test_journal_walk.py` does it against
    the in-memory fakes, does not survive contact with real git: one step here is half a dozen
    `git` subprocesses and hundreds of loop turns, so a fixed number of `sleep(0)`s releases the
    second sibling long before the first has finished and the completion order becomes a race. The
    kill is what makes that sharp - `step` takes its boundary before it returns, so a process killed
    at the first sibling's boundary never opens the second's gate at all.
    """
    await run.step(
        "spec",
        "spec",
        instructions="state what the request needs",
        inputs={"request": "add oauth", "constraints": _constraints(run.config)},
        value={"needs": ["a callback route"]},
    )
    order = run.config.order
    # Both checkouts are provisioned **before** the gather, and that is not a tidiness: a
    # `provider.open` inside a sibling is a suspension before `journal.step` is even called, so the
    # two coroutines would take their counters in whichever order real git finished in - a race,
    # and one that decides who gets `n = 0`. Opening them first leaves `journal.step` with no
    # suspension before the counter's `digest`, which is the precondition that class's docstring
    # states, and makes the counter order the order the coroutines were created in: the programme's
    # own order, and therefore `order`.
    for name in order:
        await run.journal(name)
    gates = {name: asyncio.Event() for name in order}
    gates[order[0]].set()

    async def _sibling(position: int) -> None:
        name = order[position]
        await run.step(
            f"{name}/implement",
            "implement",
            namespace=name,
            instructions="implement the ticket",
            inputs={},
            commit="implement the ticket",
            does=run.writes("src/work.py", f"done by {name}\n", namespace=name),
            value={"by": name},
            waits=gates[name],
        )
        if position + 1 < len(order):
            gates[order[position + 1]].set()

    await asyncio.gather(*(_sibling(position) for position in range(len(order))))


class Refused(Exception):
    """What a worker that fails looks like from the journal's side.

    Any exception would do - §3.6's walk has no opinion about which and lets it out untouched - and
    a named one is only so that `_crash` catches its own worker rather than any bug that happens to
    pass through. What matters is what does **not** happen: the step wrote no entry, so nothing on
    the ledger says it ever ran.
    """


def _refuses(_: JsonValue) -> None:
    """The failing worker's body. Runs after the `worker` line is already on the log, deliberately:
    the agent was called and the call was paid for, and only the recording did not happen."""
    raise Refused("the agent refused the task")


# The crash programme's two calls, which are two labels at **one** address. The step name, the
# instructions and the inputs are shared between them by construction below, because the retry only
# means anything if it is the same call: a different role or different inputs would be a different
# `base` and a different address, and the counter would never have been asked the question.
CRASHED: Final = "implement#raised"
RETRIED: Final = "implement#retried"


async def _crash(run: _Programme) -> None:
    """A step that raises and is retried **inside one run** - §3.6's reason for advancing on write.

    "A step that crashes and is retried within one run must not consume a slot - the crash is not
    journalled, so a retry landing at `n = 1` is a slot a later resume asks for at `n = 0`, misses,
    and pays an agent for again."

    **The retry is in an `except` and that is the whole design of this programme.** The second
    process walks the same code: it reaches the first call, and if the retry's entry is where a
    resume looks - `n = 0` - that call *hits*, returns the recorded value, raises nothing, and the
    `except` body is never entered. One call, one hit, no worker. Advance the counter on the call
    instead and the entry sits at `n = 1`: the second process misses at `n = 0`, runs the worker
    that raises, pays for it, falls into the `except` and only then hits. The observable difference
    is one worker line in the resuming process's half of the log, which is exactly what the parent
    counts.

    Note where the kill boundary is not: `_Programme.step` counts a boundary after `journal.step`
    *returns*, and a step that raised never gets there. That is the honest reading rather than an
    oversight - `Config.kill_after`'s boundary is "after that step's entry is on disk and before
    the next step begins", and a step that raised put nothing on disk, so killing "after" it would
    be killing at a ledger state indistinguishable from killing before it. This programme is
    therefore run to completion twice and swept over no kill points at all.
    """
    inputs: Mapping[str, object] = {
        "request": "add oauth",
        "constraints": _constraints(run.config),
    }
    instructions = "implement the ticket"
    try:
        await run.step(
            CRASHED,
            "implement",
            instructions=instructions,
            inputs=inputs,
            does=_refuses,
            value={"built": "T-01"},
        )
    except Refused:
        # Same name, same role, same inputs, same head - so the same `base`, and the address is the
        # counter's alone to decide. `commit=` differs and is allowed to: §3.6 keeps the message
        # out of the fingerprint, so the retry writing a commit does not move it to another slot.
        await run.step(
            RETRIED,
            "implement",
            instructions=instructions,
            inputs=inputs,
            commit="implement T-01",
            does=run.writes("src/oauth.py", "the callback route\n"),
            value={"built": "T-01"},
        )


@dataclass(frozen=True, slots=True)
class Programme:
    """One runnable programme and the worker labels a complete run of it produces, in order.

    The labels live here rather than in the test so that the two cannot drift: "every step's worker
    ran exactly once in total, across both processes" is checked against this tuple, and a step
    added below without a label added beside it fails the very next run.

    `crash` is the one programme whose labels are not one complete run's worth spread over two
    processes: both of its workers run in the *first* process, because the second one hits and
    never enters the retry at all. The tuple is still what the parent asserts against - it is just
    asserted of one process rather than of the pair.
    """

    run: Callable[[_Programme], Awaitable[None]]
    labels: tuple[str, ...]


PROGRAMMES: Final[Mapping[str, Programme]] = MappingProxyType(
    {
        "core": Programme(
            _core, ("spec", "decompose", "plan", "T-01/implement", "report")
        ),
        "retry": Programme(_retry, ("review#0", "review#1", "review#2")),
        "siblings": Programme(
            _siblings, ("spec", f"{SIBLINGS[0]}/implement", f"{SIBLINGS[1]}/implement")
        ),
        "crash": Programme(_crash, (CRASHED, RETRIED)),
    }
)


# --- the entry point -----------------------------------------------------------------------------


def driver_path() -> Path:
    """This file, absolutely - what the parent hands `sys.executable` to start a child."""
    return Path(__file__).resolve()


async def _drive(config: Config) -> None:
    """Build the three ports §3.6's loop touches, then walk the programme.

    `FilesystemStore` and `GitWorkspaceProvider` and `SystemClock` by name, and nothing else: the
    container's `real()` would additionally build agent runners and a terminal that a programme
    with no agent in it has no use for.
    """
    programme = PROGRAMMES.get(config.programme)
    if programme is None:
        raise SystemExit(f"replay: no programme named {config.programme!r}")
    run = _Programme(
        config,
        FilesystemStore(AglHome(Path(config.home))),
        GitWorkspaceProvider(Path(config.repo), TreesRoot(Path(config.trees))),
        SystemClock(),
    )
    run.at_start()
    await programme.run(run)


def main(argv: Sequence[str]) -> int:
    """Run one programme, and leave a marker behind if the process was allowed to finish.

    Both markers exist for one assertion in the parent, and the assertion is about their **absence**
    after a kill: `os._exit` runs neither an `atexit` hook nor a `finally` clause, so a run that
    was killed leaves no `finally` line and no `atexit` line on the log. That is the difference
    between a kill and an unwind, made mechanical - and it is the difference §3.6's design depends
    on, because a workflow engine that got to tidy up is not the one a person Ctrl-C'd.
    """
    if len(argv) != 2:
        raise SystemExit("usage: replay.py '<configuration json>'")
    config = Config.from_json(argv[1])
    run_marker = _marker(config)
    atexit.register(run_marker, "atexit")
    try:
        asyncio.run(_drive(config))
    finally:
        run_marker("finally")
    return 0


def _marker(config: Config) -> Callable[[str], None]:
    """A one-argument writer for the two end-of-process markers, bound to this run's log."""

    def _write(what: str) -> None:
        line = json.dumps({"tag": config.tag, "marker": what}, sort_keys=True)
        with open(config.log, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    return _write


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
