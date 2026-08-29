# AGL architecture

Eight layers, one dependency rule, one composition root. For the gates, see `CLAUDE.md`.

## The layers

**`ports/`** — The ABCs AGL is written against and the plain types they speak: `Store`,
`Workspace`, `WorkspaceProvider`, `Integrator`, `History`, `Verifier`, `Terminal`, `Clock`,
`AgentRunner`, plus `RunSpec`, the `AglError` hierarchy with the one exception-to-exit-code table
in the codebase, and the id types in `ids.py`, which compare through an NFC-plus-casefold
`collision_key` because two names differing only in case are one directory on a case-insensitive
filesystem. It imports nothing but stdlib: everything imports `ports`, so what `ports` drags in
reaches every layer at once.

**`adapters/`** — The implementations. Anything that imports a vendor SDK, opens a socket or
shells out lives here and only here. Each package ships a real implementation and a fake beside
it, and both are held to the same suite under `tests/contracts/`.

**`sdk/`** — What a workflow author builds from: `@workflow`, the `Run` a workflow is handed,
`@role`, `Tool`, `arg()`, the terminal components, `Stop`. `sdk/__init__.py` is the front door and
re-exports the authoring surface with `__all__` typed out rather than computed; `_engine/` is the
private machinery behind `Run` and is not on it. Something belongs here when two workflows would
otherwise write it themselves.

**`workflows/`** — One package per workflow, found through the `agl.workflows` entry points in
`pyproject.toml`; no central table to edit. `fix` is one worktree run sequentially, Claude
implementing and OpenAI reviewing; `split` is N chunks run concurrently, each landed into the
run's base. A workflow imports `sdk` and `ports` — never an adapter, never `config`.

**`config/`** — Settings and the composition root. `sources.py` resolves flags > env > file >
defaults once into an immutable object, `toml_file.py` is the only module that knows TOML,
`registry.py` resolves entry points, and **`container.py` is the only module that constructs an
adapter**.

**`cli/`** — argv in, exit code out. `main.py` dispatches to one module per subcommand (run,
resume, clear, init, workflows) and is the one place `Path.cwd()` is read. Composition is
per-command: the container sits behind a callable, so `init` and `workflows` never build one.

**`api.py`** — AGL's operations, callable without a terminal: `run`, `resume`, `clear`, `init`,
`list_workflows`, `workflow_help`.

**`testing.py`** — The workflow author's harness: `harness(tmp_path, agent=…)` builds an all-fakes
bundle, `run(...)` and `resume(...)` drive `api` over it, `recorded` is every journal entry,
`answering([...])` is a terminal that can answer a screen. A sibling of `cli/`, not a layer above
it — a second caller of `api`.

## The dependency rule

```
{cli, testing} → api → config → workflows → {sdk, adapters} → ports
```

`sdk` and `adapters` are siblings and may not import each other; so are `cli` and `testing`.
`config` may import anything. `.importlinter` holds six contracts and `lint-imports` enforces
them: the layering above, the inner ring (a pure type never imports the ABC that speaks it),
vendor containment, adapter independence, the composition root, and workflows-build-on-`sdk`-alone.

**One clause cannot be a contract.** "`ports` imports nothing but stdlib" is an *allow* list, and
every import-linter contract type names what is forbidden or how modules are ordered — saying it
there means enumerating every distribution that is not the standard library. It is enforced
instead by `tests/test_ports_stdlib_only.py`, an AST scan over every import under `ports/`. With
`import pydantic` in `ports/clock.py`, all six contracts still report kept.

## Vendor containment

`claude_agent_sdk` may be imported only inside `agl.adapters.claude_code`, `rich` only inside
`agl.adapters.rich_terminal`; both are contracts. The OpenAI adapter shells out to the Codex CLI
binary and has no import to contain, so its *name* is guarded by a grep gate in `scripts/check`
that fails on any mention in a `.py` under `src/` outside `agl/adapters/openai/`. The asymmetry is
deliberate: the two SDKs are pip extras, the Codex CLI is installed separately and resolved at
preflight, and installing one vendor never drags in the other's.

## Invariants where a mistake is silent

No gate catches these and no exception announces them. Everything else in AGL fails by raising or
by costing a re-run. **Three of them destroy work.**

**A step with no `commit=` wipes its worktree.** `Journal._ending` in `sdk/_engine/journal.py`
ends every step by committing everything or calling `Workspace.restore(last_good)` — `git reset
--hard` then `git clean -ffd`. Tracked edits, untracked files and any commit the agent made itself
all go, and none of it is on the ledger, because no entry was written. Nothing checks the pairing.
A step whose role can touch the worktree must pass `commit=`; the only two that omit it are `fix`'s
reviewer and `split`'s planner, and both roles declare `Restriction.NO_FILE_WRITES`.

**A landing must be handed back to the parent's chain.** `Integration._concluded` in
`sdk/_engine/integration.py` ends with `self._journal.advance(head)`. A child's landing moves the
parent's real head, but `last_good` is chained from step *entries* and `integrate()` writes none,
so skipping that call leaves the parent believing it is where its last step ended. The next step
to miss its fingerprint restores to that stale head and resets past every landing at once.

**A red build gate discards a hand-resolved conflict.** `Integration._gated` reverts a landing
with `restore(self._before)` when the verifier fails. If a person resolved a merge by hand and
pressed retry, the text they typed lived only in that worktree — in no git object, on no entry —
and it goes. A known cost pinned by `tests/sdk/test_integrate_acceptance.py`: the gate has to run
on that landing too.

**A workflow branches only on step results.** Resume is not a continuation — `api.resume`
re-invokes the workflow from its first line in a fresh process, so every line runs again and only
`run.step(...)` short-circuits. It fingerprints the role, its tools, the inputs and the head the
previous step ended at, appends an ordinal for repeats, and looks it up. A hit returns the
recorded value; **a miss just runs the step — a miss is not an error, it is the definition of a
new step**, so divergence has nothing to raise. Branch on wall-clock time, an environment
variable, a directory listing, randomness or a mutable global, and a resume can take another path:
paid-for work is silently redone, and where an off-branch fingerprint happens to match, a recorded
result comes back for a call that never produced it. The ordinal is never persisted — it is
rebuilt by re-walking — so order counts too: swap two same-fingerprint steps and each returns the
other's answer.

**Fingerprint canonicalisation must be order-stable.** `_canonical` walks a value before
`json.dumps(..., sort_keys=True)` hashes it with SHA-256. Mappings get sorted keys; lists and
tuples keep their order, because for a sequence order *is* meaning; sets are emitted as
`sorted(..., key=_dumps)`, by each element's own serialised text, because set iteration order is
not stable across processes. Get it wrong and a step fingerprints differently in the process that
resumes it — and a miss is not an error, so nothing complains: the run wipes the worktree, re-runs
every step it had already recorded, finishes, and returns the right answer, the symptoms being the
bill and the wall clock. Hence tests that spawn interpreters under several `PYTHONHASHSEED`
values; an in-process one passes just as happily against the bug.

**Everything a step does must land inside its workspace.** A replayed step returns a recorded
value and never calls the worker, so an effect that is not a file in the checkout — an HTTP POST,
a write to `$HOME`, a database row — happens twice on a miss and not at all on a hit. The ledger
holds a value and a head, not what the world looked like.

**Bump `@workflow(version=…)` when a workflow's shape changes.** `api.resume` compares the
installed version against the one stamped in `run.json` and refuses a mismatch rather than
migrating — the only thing between edited code and a ledger replayed into reordered steps. Edits
reaching a fingerprint term merely re-run those steps; inserting, removing or reordering steps
without a bump is silently wrong.

## Deliberately not built

The reasoning is the point — without it these get re-proposed.

- **No `RunStatus` enum in `ports/run.py`.** A step is done when its entry file exists, so a
  stored status would be a second source of truth that nothing updates.
- **No `presentation/` layer or `Display` port.** A shared abstraction would be the intersection
  of a terminal and a browser, which is a worse terminal and a worse browser.
- **No config-level model override.** The choice is semantic — this role touches sensitive code,
  that one needs judgement — so it is bound by `@role(model=…)`; an override buys only *why is my
  Opus role running GPT-5?*
- **No CLI positionals.** `agl run <workflow>` already occupies that slot, so `arg()` refuses a
  flagless field where it is written rather than at the parse that would have gone wrong.
- **`@workflow` takes `version` and nothing else.** `params=`, `name=` and `roles=` each restated
  something the framework could already read, and the copy is the half free to be wrong — `Run` is
  covariant, so `@workflow(params=FixParams)` over `async def fix(run: Run)` type-checked fine.
- **No fan-out or parallelism helper.** The framework never spawns a task for a workflow; steps
  serialise within a namespace, so real concurrency is more worktrees, and a helper would wrap
  `asyncio.TaskGroup` while owning nothing.
- **No general subprocess helper.** Three modules run children and disagree on seven axes — shell
  or exec, buffered or streamed, stdin, stderr, process or group signalling, deadline, failure
  signal — so a helper would take a flag per axis to say which caller it was being.
- **No `Integrator.revert()`.** Undoing a landing that succeeded is `Workspace.restore(head)`,
  which already exists; a second spelling would be owed by every integrator.
- **`Store` has six members and no more.** No `exists`, because a read returning `None` is that
  question already answered; no listing, because replay computes the digest it wants; no
  transaction, because a batch needs a boundary and a flush would admit to a buffer.
- **No retry or exit-status cleverness on the build gate.** A dead daemon, an OOM kill and a real
  test failure are not distinguishable from an exit code, so an OOM reads as a failed build and
  the cost is a re-run.
- **No `auto()` on any enum.** Enum values reach the fingerprint as text and are therefore a
  stored format; `auto()` would hand that format to declaration order.
- **No lock in `adapters/filesystem/`.** Every document has its own address, so a write is one
  `os.replace`. A mutex would be correct, slower, and invisible — it leaves every store test
  green, so `tests/adapters/test_filesystem_no_lock.py` reads the source instead.
