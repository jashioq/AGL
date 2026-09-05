# AGL architecture

Eight layers, one dependency rule, one composition root. For the gates, see `CLAUDE.md`.

## The layers

**`ports/`** — The ABCs AGL is written against and the plain types they speak: `Store`,
`Workspace`, `WorkspaceProvider`, `Integrator`, `History`, `Verifier`, `Terminal`, `Clock`,
`AgentRunner`, plus `RunSpec`, the `AglError` hierarchy with the one exception-to-exit-code table
in the codebase, and the id types in `ids.py`, which expose a casefold-then-NFC `collision_key` and
do **not** compare through it — `RunLabel("T-01") != RunLabel("t-01")`, and a caller that must not
collide asks for the key, because two names differing only in case are one directory on a
case-insensitive filesystem. It imports nothing but stdlib and its own ring: everything imports
`ports`, so what `ports` drags in reaches every layer at once.

**`adapters/`** — The implementations. Anything that imports a vendor SDK, opens a socket or
shells out lives here and only here. What holds of every one of them is the grading: each class
here that implements a port is subclassed into a suite under `tests/contracts/`, which is what
keeps a stand-in from drifting from the thing it stands in for. "A fake beside a real" does not.
Four packages spell one `fake.py`, `filesystem/`'s is `memory_store.py`, `system_clock.py` is one
module holding both clocks and no package at all, and `rich_terminal/` has none: it ships three
terminals across two suites — `RichTerminal` for `real()`, `ScriptedTerminal` for `answering()`,
`HeadlessTerminal` for `fakes()` — no one of them a stand-in for another. And a fake here fakes
the *port*, never the vendor: `openai/fake.py` starts no process at all.

**`sdk/`** — What a workflow author builds from: `@workflow`, the `Run` a workflow is handed,
`@role`, `Tool` and the `tool()` and `reporting_tool()` that derive one from a payload dataclass,
`arg()`, the terminal components, `Stop`. `sdk/__init__.py` is the front door and re-exports the
authoring surface with `__all__` typed out rather than computed; `_engine/` is the private
machinery behind `Run` and is not on it. That underscore names the **workflow author's** surface
and nothing narrower — `api`, `config` and `sdk`'s own modules import those seven modules freely,
so there is no import for a contract to forbid and this sentence is the whole of the rule, unlike
the same underscore under `adapters/`, which means private to that package and is enforced by
`tests/test_naming_convention.py`. Something belongs here when two workflows would otherwise
write it themselves.

**`workflows/`** — One package per workflow, found through the `agl.workflows` entry points in
`pyproject.toml`; no central table to edit. `fix` is one worktree run sequentially, Claude
implementing and OpenAI reviewing; `split` is N chunks run concurrently, each landed into the
run's base. A workflow imports `sdk` — never an adapter, never `config`. `ports` sits below it and
is permitted, and neither shipped workflow names it: the authoring surface re-exports what a
workflow speaks.

**`config/`** — Settings and the composition root. `sources.py` resolves flags > env > file >
defaults once into an immutable object, `toml_file.py` is the only module that knows TOML,
`registry.py` resolves entry points, **`workspace_path.py` is the only module in `src/` that writes
to `sys.path`** — it appends the operator's workspace, so AGL's own environment always wins and the
workspace can add names without displacing one — and **`container.py` is the only module that
constructs an adapter**.

**`cli/`** — argv in, exit code out. `main.py` dispatches to one module per subcommand (run,
resume, clear, init, workflows) and is the one place `Path.cwd()` is read. Composition is
per-command: the container sits behind a callable, so `init` and `workflows` never build one.
**Commands stay dumb.** A command declares its own arguments, reads them off the parsed namespace,
calls `api` and turns what comes back into output and an exit status; everything that decides
anything is one call away. So `clear` names one `api` function rather than a worktree walk and a
`shutil.rmtree` past the `Store` port, `init` one rather than build-tool detection and TOML
rendering, and `workflows` two only because the listing and the help are two operations — one of
them imports a package and the other must never. Each suite under `tests/cli/` scans its own
command's source for the `api.` names it reaches, so a use case moving back into the CLI fails a
test instead of passing review.

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
`config` may import everything under it and nothing above it, and only `config/container.py` may
name an adapter. `.importlinter` holds five contracts and `lint-imports` enforces them: the layering
above, the inner ring (a pure type never imports the ABC that speaks it), vendor containment,
adapter independence, and the composition root. A sixth said that a workflow builds on `sdk` alone
and never imports `agl.adapters` or `agl.config`; it went when AGL stopped shipping workflows, there
being no `agl.workflows` for it to be a rule about. **It was wholly implied when it existed** — its
config half by the layering and its adapters half by the composition root, whose `agl.*` source
covered it — so nothing stopped being enforced, and what was lost is the failure message a workflow
author would have read.

**One clause cannot be a contract.** "`ports` imports nothing but stdlib" is an *allow* list, and
every import-linter contract type names what is forbidden or how modules are ordered — saying it
there means enumerating every distribution that is not the standard library. It is enforced
instead by `tests/test_ports_stdlib_only.py`, an AST scan over every import under `ports/`. With
`import pydantic` in `ports/clock.py`, every contract still reports kept.

## Vendor containment

`claude_agent_sdk` may be imported only inside `agl.adapters.claude_code`, `rich` only inside
`agl.adapters.rich_terminal`; one contract holds both. The OpenAI adapter shells out to the Codex
CLI binary and has no import to contain, so its *name* is guarded by a grep gate in `scripts/check`
that fails on any mention in a `.py` under `src/` outside `agl/adapters/openai/`. The asymmetry is
deliberate: the two SDKs are unconditional base dependencies, present in every install, so the
contract is the only thing keeping each one to its own adapter package; the Codex CLI is a binary
installed separately and resolved at preflight, so it has no import statement for a contract to
hold.

## The terminal

**A view is a function, and `show` registers the function and its arguments rather than the
`Screen` they produce.** The adapter's redraw loop invokes a registered view again every frame,
compares the `Screen` it returns against the last one, and writes only on a change — so handing a
view the live dict of child runs is how a dashboard stays current, and a workflow re-`show`s only
to put a *different* view on screen. Every component is a frozen dataclass with value equality
because that comparison is the whole reason per-frame re-invocation is cheap: the expensive part is
the write, and the write is skipped when nothing moved.

`Screen`, `Rows`, `Row`, `Text`, `Choice` and `TextInput` live in `ports/terminal.py` and not
beside the authors who write views, because `Terminal.show` takes a view returning a `Screen[T]`
and a component under `sdk/` would invert the dependency rule on its lowest edge; `sdk/terminal.py`
is a re-export facade holding no logic. `Component` and `Response` are closed unions, so an adapter
can `match` them exhaustively and a fourth component is a build failure in every implementation
that has not learned to draw it. Anywhere a component is expected a bare `str` means `Text`,
coerced on the way in, which is why `Row`, `Rows` and `Screen` write their own `__init__` instead
of taking a generated one that would accept each field at the field's own type. `Screen` is a
dashboard and `Screen[T]` is a question — the parameter says which, and `responses` being empty is
what the terminal dispatches on at run time. Terminal-*shaped* is not
terminal-*implementation*-shaped: no styling, no colour, no sizes, no positions, no notion of a
screen having a size at all, because that is mechanism and mechanism is `adapters/`.

**One slot, two queues, and this is the whole contract that every implementation satisfies
identically.** A passive `Screen` goes to the slot — size one, replaced on write, no ordering, and
`priority` means nothing for one. A `Screen[T]` joins a queue at its priority, FIFO within a
priority, because a person answers one thing at a time. The highest-priority screen is always the
one shown, and the slot keeps updating while a question is up, so when the queue empties the
current dashboard reappears with no extra machinery. Preemption is not cosmetic: `integrate()`
leaves its target held mid-landing, so a conflict screen queued behind two agent questions would
stall the merge queue on something unrelated. Priority is a plain `int` and not named levels, which
would encode one workflow's concepts into the framework. Known and accepted: preemption loses text
somebody was part-way through typing, and there are no timeouts anywhere, so "stuck" and "waiting
for you" look alike from outside — `pending` exists because of the second, and reports every
priority the terminal has been asked for, zeroes included, excluding whatever is on screen.

`adapters/rich_terminal/queues.py` never dequeues in order to display. An entry joins its queue in
`queue()` and leaves it in `answer()`, and that is the whole of its movement; current is derived,
as the head of the highest non-empty queue, recomputed on every read. Preemption is then not an
operation at all — a higher-priority arrival changes what the derivation returns — and "the
displaced question keeps its place" becomes a thing the module could not express otherwise.
Identity is the `show` registration and never the `Screen` value, which is what `eq=False` on
`Registration` and `Queued` buys: a view returns a fresh equal `Screen` every frame, and two agents
asking the same question produce equal screens, so keying on the value would hand one agent the
answer to a question it never asked.

**Headless is this port's contract and not one adapter's quirk.** A terminal with no display no-ops
a passive screen and raises `UpstreamUnavailable` on an interactive one, because a workflow needing
human input genuinely cannot run without a person and saying so at the first question beats
blocking forever on nobody. That is what lets `HeadlessTerminal` double as the fake, and it shares
nothing with the terminal that draws — no queues, no slot, no loop, and no import of `rich`,
`terminal.py`, `queues.py`, `_display.py` or `_render.py`. `ScriptedTerminal` runs no loop either,
and a script that runs out idles rather than raising: a test that then shows a question hangs
instead of failing, which is what a real terminal with nobody sitting at it does, and is what lets
the contract suite show a question before any response exists.

**A `Terminal` is an async context manager, and the framework opens it around the workflow's
function and around nothing else.** `api._walk` holds the one `async with services.terminal`, so
`run` and `resume` cannot disagree about it. It opens after the record and after the base checkout
is provisioned, because the context is exactly the region in which `show` is legal
and the only thing there that can `show` is the workflow — opening earlier would widen that region
over code where a `show` is AGL's own bug, and would take a person's display over in order to draw
nothing across the refusals they have to read. A `show` outside it is `InternalError`. `__aexit__`
is annotated `-> None` on the port and suppressing an exception means returning something truthy,
so no conforming terminal can swallow a workflow's `Stop`.

**Agent activity is one string, held and handed back, and never written down.** Each adapter
formats its own line — `Bash: ./gradlew build`, `Edit: domain/usecase.kt` — and the router passes
it through untouched: no `Activity` type, no shared verb taxonomy, no framework lookup table, so no
later backend has to map its vocabulary onto another's and the cost is cosmetic inconsistency
between them. `Steps` holds the cell and `run.activity` reads it through a property; one `Steps`
per namespace means a child reports its own steps and not its parent's. It is `None` when nothing
is running, cleared in a `finally` around the dispatch alone — an assignment does not suspend, so a
`CancelledError` cannot land between deciding to clear the cell and clearing it. A replayed step
has no activity at all, structurally rather than by a check: `on_activity` is passed inside the
worker, and a hit returns the stored value without building one. Nothing about activity reaches an
`Entry`, a fingerprint or the store.

## Errors at the boundary

**An adapter translates what it catches — a `CalledProcessError`, an `OSError`, a vendor
exception — into the `AglError` hierarchy at its own boundary, and nothing above an adapter ever
handles anything else.** A workflow catches `UpstreamUnavailable`, never whatever the thing
underneath happened to throw; nothing above `adapters/git/` sees a porcelain exit status, a
`MERGE_HEAD` or an unmerged-path listing, and nothing above `adapters/claude_code/` sees an SDK
exception or a vendor's stop string. This is a different rule from vendor containment, which is
about where vendor *code* may live. Which subclass is chosen is decided by what the reader of an
exit code should do — `DeniedError` for a refusal that stands until something changes,
`UpstreamUnavailable` for a state of the world the same call may get past later,
`UpstreamUnexpected` for a far side that answered in terms the adapter cannot read — and
`adapters/git/_trees.py`'s `_translated` is that decision in four lines, pinned over both of its
callers by `tests/adapters/test_git_denied.py`. The rule holds one layer up wherever a module does
its own I/O rather than reaching through a port: `config/toml_file.py` and `sdk/roles.py`'s
`prompt_file` each turn an `OSError` into an `InputError` at the line that raised it.

**`ports/errors.py` holds the one exception-to-exit-code table and `cli/exit_codes.py` consumes it
without adding a number of its own.** An exception that is not an `AglError` arriving at the top of
the CLI is a translation that did not happen in our code, so it exits 70 — the same answer
`exit_code_for` gives an `AglError` on a branch nobody mapped, because the two are one fault seen
from either side and a script cannot act on them differently. Resolution walks the class tree
rather than indexing the table, so a workflow's own `ReviewNotConverging(Stop)` exits 7 without
appearing anywhere, and there is no clause order for a handler to get wrong.

**A `TaskGroup` hands back several answers at once, so a group has its own rule**: unwrap a
single-exception group and map its leaf; several leaves whose codes agree take that code; leaves
that disagree take 70, naming all of them, because a run that failed several different ways is
genuinely not attributable to one code and a guess would be this module inventing a precedence over
the table. `leaves` flattens recursively — a workflow that fans out opens a `TaskGroup` and a child
may open its own — so "a single-leaf group" is a fact about what the run did rather than about how
deeply the workflow nested its concurrency. Agreement is compared on the resolved *code* and never on the
class, which is why `UpstreamUnavailable` beside `UpstreamUnexpected` agrees at 6 with no second
rule to keep in step with the table. `exit_status` and `leaves` take `Exception` and walk
`ExceptionGroup`, deliberately not `BaseException` and `BaseExceptionGroup`: a Ctrl-C is the
operator taking the process back rather than an outcome to report, and the faithful way to end on
one is to die of the signal, which is what CPython does when nothing catches it. A shell tells the
two apart even though `$?` reads 130 for both — a child that *died of* `SIGINT` stops the enclosing
loop and one that merely exited 130 does not — so a handler answering 130 here would make
`for label in a b c; do agl run ...; done` unstoppable by the key that was pressed to stop it.
`mypy --strict` is the enforcement, since `except BaseException as error: return exit_status(error)`
will not type-check, and `tests/cli/test_exit_codes.py` pins both the annotation and the group rule.

## Invariants where a mistake is silent

No gate catches these and no exception announces them. Everything else in AGL fails by raising or
by costing a re-run. **Three of them destroy work.**

**A step with no `commit=` wipes its worktree.** `Journal._ending` in `sdk/_engine/journal.py`
ends every step by committing everything or calling `Workspace.restore(last_good)` — `git reset
--hard` then `git clean -ffd`. Tracked edits, untracked files and any commit the agent made itself
all go, and none of it is on the ledger either: an entry is still written, and the head it records
is the one the worktree was restored to. Nothing checks the pairing. A step whose role can touch
the worktree must pass `commit=`. A step that legitimately omits it is one whose role declares
`Restriction.NO_FILE_WRITES` — a reviewer, a planner — and that pairing is the author's to keep.

**A landing must be handed back to the parent's chain.** `Integration._conclude` in
`sdk/_engine/integration.py` settles a clean landing with `self._journal.advance(head)`. A child's
landing moves the parent's real head, but `last_good` is chained from step *entries* and
`integrate()` writes none, so skipping that call leaves the parent believing it is where its last
step ended. The next step to miss its fingerprint restores to that stale head and resets past every
landing at once.

**A red build gate discards a hand-resolved conflict.** `Integration._gated` reverts a landing
with `restore(self._before)` when the verifier fails. If a person resolved a merge by hand and
pressed retry, the text they typed lived only in that worktree — in no git object, on no entry —
and it goes. A known cost pinned by `tests/sdk/test_integrate_acceptance.py`: the gate has to run
on that landing too.

**Every path out of a hold must settle it.** `Integration.retry` and `Integration.abort` in
`sdk/_engine/integration.py` are the two verbs a workflow calls on a live conflict, and each reaches
an `Integrator` that may raise — `land` refuses over unrecorded work in the target, which is exactly
what a person editing that checkout at a refusal screen leaves behind. `integrate()` guards its own
construction with `except BaseException: lease.release()`, and `api.run` sweeps with `finally:
leases.release_all()`; neither covers a raise out of a verb called on an object the workflow is
already holding. The target's lease and its namespace's step lock then stay taken for the life of
the process, and the next landing into that parent blocks inside `Leases.claim` — a hang rather than
a failure, with nothing raised and no predicate to ask. So both verbs settle on the way out, and the
tests in `tests/sdk/test_run_integrate.py` bound the claim that follows rather than awaiting it.
Settling is also what ends the workflow's own loop: `Integration.conflicted` is *is there a conflict
here that has not settled*, so `while outcome.conflicted:` terminates for every path out of a hold
and never sends a workflow back to a `retry()` that would refuse it. The `Conflict` itself outlives
the settling — it is the record of why nothing landed, and a workflow reads it after the loop.

**A hold and a liveness claim are facts about the world, never about AGL's memory.**
`adapters/git/integrator.py` holds nothing of its own: a conflicted `git merge` writes `MERGE_HEAD`
into the target worktree's own git directory, and that file *is* the hold — no attribute records a
pending landing, and `_held` is the single predicate all three verbs ask. A `GitIntegrator` built
in a later process and handed the same target asks git the same question and gets the same answer,
so `abort` after a crash releases a hold this process never took. An in-memory hold makes a resumed
run's `abort()` a no-op that reports success and leaves the target half-combined forever, and no
contract suite catches it — both implementations pass with one — which is why
`tests/adapters/test_git_integrator.py` asserts it against the real adapter with a second
integrator over the same repository. Two consequences follow from `MERGE_HEAD` being per worktree:
a landing held in one run's `_base` is invisible to every other run, which is the isolation the
trees layout is built on, and only a merge is ever a hold, so a rebase or a cherry-pick somebody
left in the target is not something `abort` will touch. The run lock is the same primitive
answering a different question — `_trees.run_lock` is a non-blocking `flock` on `.trees/<label>/`,
taken by `run` and `resume` for the life of the process and briefly by `clear`, so a `clear` aimed
at a live run refuses at once rather than waiting hours for a lock or taking its checkouts away
underneath it. Both refuse the recorded alternative for the reason `ports/run.py` has no
`RunStatus`: a claim written down is a claim a crash leaves behind as a lie, and a claim the kernel
drops when its holder dies is the one kind no crash can falsify.

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

**A payload class's identity travels only inside its schema's `title`.** `_object_schema` in
`sdk/tools.py` writes `"title": f"{kind.__module__}.{kind.__qualname__}"` at every depth, and
`base_of` takes a tool's name, its description and its derived schema — so the payload *type* is a
fingerprint term reached through that one string and through nothing else. Both failure directions
are silent and they run opposite ways. Rename the payload class, move its module, or re-nest it,
and the digest moves although nothing about what the agent is asked has changed: every recorded step
that reported through it misses, and the run re-buys work it already had. Add a method to it — or a
`__post_init__` that *rejects values the old one accepted* — and the digest is byte-identical: a
vocabulary enforced in code and named nowhere else is invisible to the schema, so an entry recorded
under the old rules replays under the new ones, or stops converting with its fingerprint still
matching and surfaces as an `InternalError` out of `ReportingTool.read` on a resume.
A payload whose `__post_init__` enforces a vocabulary — a severity, a status, a set of permitted
strings — is exactly that case and takes the price; `describe()` is the way out of it, a vocabulary
interpolated into a field's description being schema and therefore fingerprint. Four tests in
`tests/sdk/test_tools.py` pin the pieces.

**Everything a step does must land inside its workspace.** A replayed step returns a recorded
value and never calls the worker, so an effect that is not a file in the checkout — an HTTP POST,
a write to `$HOME`, a database row — happens twice on a miss and not at all on a hit. The ledger
holds a value and a head, not what the world looked like.

**Bump `@workflow(version=…)` when a workflow's shape changes.** `api.resume` compares the
installed version against the one stamped in `run.json` and refuses a mismatch rather than
migrating — the only thing between edited code and a ledger replayed into reordered steps. Edits
reaching a fingerprint term merely re-run those steps; inserting, removing or reordering steps
without a bump is silently wrong.

**Preflight's registry scan is best-effort; containment at every step is the guarantee.**
`sdk/_engine/preflight.py`'s `check` runs once, before the record is written and before anything is
provisioned, and reads the `@role(model=…)` factories bound in the module the workflow's `def` ran
in and in any module bound there — exactly one level, never recursing — asking each distinct
model's backend `check_ready`. It over-approximates deliberately: a factory imported and never
stepped with demands its provider, and so does every other factory in a module imported for one of
them. That is a false refusal, which is loud, names its factory and both modules, and is one import
from being fixed. What the scan cannot see is the silent half — a factory held in a container, one
built at run time by a call or a comprehension, one bound two modules deep, one reached through
anything that is not a module — and there `Capabilities.require` at every `run.step` is what still
runs, over the role the workflow actually handed in. Delete that as a duplicate of preflight's work
and the failure has nothing to raise: the role a module declares and the role a workflow steps with
are different values wherever a workflow writes something like `implementer(ask=asking(run.terminal))`
inside its own function — a tool whose handler closes over a `Run` that did not exist when the
module was imported — and `Role.__post_init__` folds `TOOL_CALLING` into `requires` behind it. A role
reaching a backend that cannot call a tool then ends its step with `RoleIncompleteError` — the
reporting tool never reaches the model, so the agent cannot fire it — instead of the refusal it was
owed. `capabilities()` is contracted stable for the duration of a run, which is what makes one
memoised call per model per run the whole bill; `check_ready` is deliberately not repeated per
step, because it costs a turn to re-learn a state of the world preflight already asked about.
`tests/sdk/test_preflight.py` asserts the over-approximation as behaviour and measures the two
halves against each other rather than separately.

**`check` asks more than the backends now, and the order it asks in is chosen on what a question
costs.** First the repository, through `History.check_committer_identity`: `commit_all` invents no
identity, so where git can derive none it refuses inside `Journal._ending` — after the agent has
finished and before the entry is written, which is the one preflight failure a resume cannot
repair, there being no entry for it to hit. Then the backends, cheapest probe leading, ranked by
`Provider` inside `preflight.py` rather than by a third member on `AgentRunner`: the OpenAI
adapter's `check_ready` spawns `codex login status` and the Claude adapter's spends a turn, so a
machine logged into one and out of the other is refused without buying anything. `sorted` is stable,
so binding order in the workflow's module namespace still decides between two models whose probes
cost the same. Both refusals are `UpstreamUnavailable` — a state of the world the operator changes,
after which the same run works — so both leave on exit 6.

**A run's label is held in two places, and the repository has to be asked as well as the store.**
`api.run` asks `History.exists(run_branch(label))` beside reading the record, and refuses before it
has written anything. Without that check `WorkspaceProvider.open` takes its **attaching** path,
because `base` is consulted only when provisioning: the new run continues that branch from its tip
with `--from` silently ignored, and nothing anywhere says so. The two questions look like one and
are not. `clear` takes a run's records and every branch it held away together, and `api.run` writes
a record before it cuts a checkout, so nothing of AGL's leaves `agl/<label>` standing with nothing
recorded beside it — which is what makes the check look redundant and is exactly why it is not: what
it catches is somebody's own `git branch agl/auth`, or a name that outlived the repository AGL was
pointed at. `git branch -D` is what frees such a label, a second `agl clear` having no record to
address.
`tests/test_api.py::test_a_deliverable_branch_that_already_exists_refuses_the_run` pins the refusal,
and `tests/test_clear.py::test_a_cleared_label_starts_a_fresh_run_because_clear_left_no_branch_behind`
walks the round trip.

**A view must be pure, and `TextInput.maps` is excluded from comparison because it is.** A view is
re-invoked every frame and builds a fresh function object each time, and two lambdas are never
equal — so comparing `maps` would make every frame of an interactive screen differ from the last,
and the terminal would rewrite the screen ten times a second on exactly the screens somebody is
part-way through typing into. `field(compare=False, repr=False)` is what makes the frame diff work
at all, and it is sound only while purity holds: when two frames compare equal, the two `maps` were
built by the same function from the same arguments and are interchangeable, so the adapter may keep
either object. A view that returns a *different* mapping from the same inputs breaks here in
silence, as does one that reads a store, does I/O, or sorts a thousand items ten times a second. No
port can enforce any of it. `tests/ports/test_terminal.py` pins the exclusion, so a later reader
has to break an assertion before they can tidy that `compare=False` away.

## Deliberately not built

The reasoning is the point — without it these get re-proposed.

- **No `RunStatus` enum in `ports/run.py`.** A step is done when its entry file exists, so a
  stored status would be a second source of truth that nothing updates.
- **No `presentation/` layer or `Display` port.** A shared abstraction would be the intersection
  of a terminal and a browser, which is a worse terminal and a worse browser.
- **No config-level model override.** The choice is semantic — this role touches sensitive code,
  that one needs judgement — so it is bound by `@role(model=…)`; an override buys only *why is my
  Opus role running GPT-5?*
- **No scrubbed or replaced environment for an agent harness.** What each adapter closes is the
  *target repository* as a configuration channel: `claude_code/runner.py` passes
  `setting_sources=[]`, `strict_mcp_config=True`, `settings=None` and `add_dirs=[]`, and
  `openai/runner.py` passes `--ignore-rules`, `--ignore-user-config`,
  `-c project_doc_max_bytes=0` and `-c skills.include_instructions=false`, and hands the workspace
  as `cwd=` rather than on argv so that no path is interpolated into a configuration expression.
  What neither does is build an environment for the child — neither agent adapter passes `env=` at
  all, so a harness inherits this process's and the operator's own machine stays visible to it
  (`adapters/git/_runner.py` is the only adapter that touches the variable, and it *adds* one key
  to what it inherited rather than replacing anything). The one
  thing that would take that away is moving the harness's home directory, and that directory is
  where its credential lives, so an isolated environment is an unauthenticated one: the choice is
  between a run that inherits a machine and a run that cannot start. Two harnesses whose flags have
  nothing in common landing on the same boundary independently is what settles that it is the real
  one. `tests/contracts/_agent_hermeticity.py` asserts the half that is closed, against one
  repository poisoned for every harness at once with markers that ride three channels, and it reads
  no environment variable anywhere — deliberately, because the inherited half is not a thing it
  could assert about without pinning the decision it declines to make.
- **No CLI positionals.** `agl run <workflow>` already occupies that slot, so `arg()` refuses a
  flagless field where it is written rather than at the parse that would have gone wrong.
- **`@workflow` takes `version` and nothing else.** `params=`, `name=` and `roles=` each restated
  something the framework could already read, and the copy is the half free to be wrong — `Run` is
  covariant, so a `@workflow(params=SomeParams)` over an `async def wf(run: Run)` annotated with a
  *different* params type type-checked fine, the decorator's copy and the signature's disagreeing in
  silence.
- **No fan-out or parallelism helper.** The framework never spawns a task for a workflow; steps
  serialise within a namespace, so real concurrency is more worktrees, and a helper would wrap
  `asyncio.TaskGroup` while owning nothing.
- **No general subprocess helper.** Four modules run children — `shell/verifier.py`,
  `git/_runner.py`, `openai/runner.py`, `openai/_session.py` — and disagree on six axes of how one
  is *started and read*: shell or exec, buffered or streamed, stdin, stderr, deadline, failure
  signal. A helper would take a flag per axis to say which caller it was being. Stopping is not a
  seventh axis, because it is where all three of the modules that stop a child agree on purpose:
  the `_signal` in `verifier.py`, in `_session.py` and in `git/_runner.py` escalates SIGTERM,
  grace, SIGKILL; none of them signals a child whose `returncode` is already set,
  because a reaped pid is the kernel's to hand out again and what dies is then whatever holds that
  number now; and none of them lets a denied signal out of a stopping path, where a raw `OSError`
  would replace whatever was being reported — a deadline, or an unwinding `CancelledError`. They
  differ on the one line that names *what* is signalled, and that follows from how they start:
  `verifier.py` and `_session.py` gave their child a session, so they signal the group and fall
  back to the child itself when the group is denied; `git/_runner.py` gave its child none, so it
  signals the process and has no group to fall back from. All three were brought into line rather
  than born that way — a difference there was a defect, not a caller's business — and
  `openai/runner.py`'s readiness probe was given a session so that it could spend `_session.py`'s
  `_halt` and `_signal` unchanged rather than grow a fourth copy of them — a sibling module
  inside one adapter, which is the one place a stopping sequence can be shared for free. It stopped
  nothing at all until it was given both that session and a deadline. The helper would also have
  nowhere to live: the adapter-independence contract in `.importlinter` forbids one adapter
  importing another — the entry below is that sentence in its general form.
- **No shared module under `adapters/`.** The adapters repeat themselves, and every one of the
  repeats stays. The port fakes are the bulk of it: `claude_code/fake.py` (204 lines) and
  `openai/fake.py` (195) hold 182 lines in common line for line and the same four-name `__all__`,
  with `Conversation`, `_payload`, `_value` and `_said` byte-identical and `_as_json` differing in
  one clause of its error prose. All that differs is vendor-shaped: the model check — `_check_model`,
  Claude-only, against `translate.model_slug` — the backend's name in three message constants, and
  the activity line, `f"{declared.name}: {said}"` against `f"{_LABEL_CALLING}: {declared.name}"`,
  each fake keeping the shape of the line its own real adapter emits. Beside them, `Caller` with
  `_FAILED` and `_STOPPING` is 24 byte-identical lines in two `_tools.py` that are otherwise an MCP
  server registration and a JSON-RPC listener; `_shortened` is seven byte-identical lines in
  `claude_code/translate.py` and `openai/translate.py`; `_translated` is four lines that
  `git/_trees.py` writes and `filesystem/store.py` writes again with one parameter renamed —
  `git/_working.py` held a third copy and now imports `_trees.py`'s, a sibling inside one package
  being the one place that is free; and
  `_GRACE: Final = 5.0` stands in each of the three modules above that stop a child.
  `_ENCODING: Final = "utf-8"` stands three times inside `git/` alone — the free kind — and is
  refused anyway, at net zero lines: what each site decides is the handler beside it,
  `surrogatepass` where `_snapshots.py` encodes a path into a commit digest and two paths must not
  collapse into one, `replace` where `_patches.py` and `_runner.py` decode something only to be
  read. Folding the half they agree on would leave the half they do not, and `_runner.py` imports
  nothing from the package, so the real subprocess runner would be reaching into the fake
  repository's module for a string. Contract 4 forbids one adapter importing another, so an
  adapter-spanning duplicate folds into `ports/`, into
  something new under `adapters/`, or nowhere. `ports/` is wrong for all of it — it is the ABCs and
  the plain types they speak and everything imports it, so what lands there reaches every layer at
  once: a fake implements a port and is not one, `Caller` is adapter mechanics, and how a filesystem
  error or a vendor CLI's output line is phrased is that adapter's own business. **The peer package
  under `adapters/` is not an available shape.** `adapter_drift` in
  `tests/test_contract_listings.py` requires every *directory* under `src/agl/adapters/` to appear
  in contract 4's `modules =`, and a directory has no exemption route at all — `ADAPTER_EXEMPT`
  there is keyed by filename and holds only single-file members. The package would therefore be
  listed, and being listed is exactly what forbids the two adapters importing it. The one shape that
  folds is a top-level `.py` with an `ADAPTER_EXEMPT` entry — `routing.py`'s shape — and it has been
  refused in writing already, for a structurally identical case: that constant's comment carries a
  hypothetical shared `_process.py`, left there to say that nothing is pre-authorised, and warns
  against taking an exemption to spare an edit to `.importlinter`, an exemption removing a module
  from the rule where a listing applies it. `routing.py`'s own exemption is no precedent for a
  second. It *is* an adapter: it implements `AgentRunner`, and dispatching on `task.model.provider`
  to the vendor runners is its whole job, so importing them is the thing it does. A shared fake or a
  shared `Caller` would be the first module under `adapters/` that is neither an adapter nor the
  router — a library the adapters depend on, which is a different kind of thing and creates a
  dependency edge contract 4 would see in neither direction. `tests/test_contract_listings.py`'s
  docstring names that ending as the one contract 4 exists to catch: without the guard, "the first
  sign of it would have been two vendors quietly sharing a helper". **The price is paid rather than
  hidden.** Those 182 lines and those 24 get fixed twice, and both `_tools.py` have already been
  edited in parallel once. What holds the two fakes together is grading and not sharing: each is
  subclassed into the same `AgentContract` suite under `tests/contracts/`, so a divergence in what
  they *promise* fails the build, while a divergence in how they spell it does not.
- **No single `Tool` class.** `ReportingTool[P]` in `sdk/tools.py` reads as "a `ports/` `Tool` with
  a payload and no handler", and `tool()` beside it — an ordinary `Tool` whose schema is derived
  from a payload dataclass and whose handler is called with the built instance — makes the
  resemblance closer rather than weaker. What one class would buy is that resemblance written down.
  What it costs is the only static check `Role[P]` has: that parameter binds from the one member of
  `Sequence[Tool | ReportingTool[P]]` which carries a payload type, and it binds **because the two
  classes are disjoint** — make `ReportingTool` a subclass of one `Tool` and every mismatched
  declaration type-checks clean, a `ReportingTool[Other]` satisfying the bare `Tool` arm so that `P`
  is never bound at all. Four things pay for the merge. *The layering*:
  `tests/sdk/test_tools.py` already writes that half down — "`Tool` is a port type that must not
  learn what a payload class is" — and one class is that sentence reversed, with either ~205 lines
  of schema derivation following `payload` into `ports/`, or `payload: type[P]` going without them,
  which is the split that lets a bare `Tool(payload=…)` be written carrying no schema at all. *The
  price of recovering the check*: the one spelling that keeps it is
  `tools: Sequence[Tool[P] | Tool[None]]` — more machinery rather than less, `Tool[Any]` in
  `AgentTask.tools` and in `base_of`, and a hand-written overloaded `__init__` on a `ports/`
  dataclass, a generated one being public and reopening what the overloads closed. *A refusal
  deleted*: under that spelling a mixed **list** display quietly infers `Role[Findings | None]`
  where today it is refused at the declaration
  (`tests/sdk/test_roles.py::test_a_mixed_list_display_does_not_infer_p_and_says_so_at_the_declaration`,
  whose docstring says "the `type: ignore` is the assertion"). *A new hole on the shape `tool()`
  exists for*: a tool carrying both a payload and a handler binds `P`, so `Role(tools=(that_one,))`
  infers `Role[Findings]` while `run.step` returns `None` and the `.summary` after it is an
  `AttributeError` with mypy clean. And the distinction the merge would erase is not conventional.
  A reporting tool's payload is the only value a tool call can put on the journal —
  `sdk/_engine/steps.py`'s `return None if capture is None else capture.reported(outcome)` is the
  whole of it, and that value becomes `Entry.value`; every other tool answers with a `ToolResult`
  that each adapter turns into content for the model and that reaches no store. One class buries
  that in `handler is None`.
- **No safe mode on `agl clear`.** It takes the whole run — every checkout, every branch, the run's
  own included, and the records — whether the work is uncommitted, committed and unlanded, or
  already in the base ref, and no flag changes that. The obvious alternative is a `git branch -d`
  gate on the run's own branch, keeping it when `History.contains` says the base ref does not hold
  it yet, with a `-f` to override. What that buys is a label that reads as free to the `Store` and
  is taken in the repository; a warning an operator cannot act on, because the same call removed the
  record any second `agl clear` would need; and a `--force` everybody learns to type by reflex,
  which is a confirmation nobody reads. The honest ordering is the other way round — `git log
  agl/<label>` before the verb, and a listing of the branches and the checkouts after it, so what
  went is on the terminal rather than in a manual. `api.clear` therefore answers with a `Cleared`
  rather than printing anything, `api.py` starting no output.
- **No `Integrator.revert()`.** Undoing a landing that succeeded is `Workspace.restore(head)`,
  which already exists; a second spelling would be owed by every integrator.
- **No auto-generated commit message.** The message is domain vocabulary — `implement T-01` is
  something only the workflow knows — so `commit=` on `run.step` is the workflow author's one
  step-ending decision and the framework composes nothing to put beside it. Where AGL does need a
  message it spends one the tool already wrote rather than inventing a second voice:
  `adapters/git/integrator.py` merges and concludes with `--no-edit`, so a landing is called what
  git calls it, and `adapters/git/fake.py`'s `_merged` writes that same sentence in the same words
  — which is legitimate here because it describes an *event* and not a piece of work. What the
  refusal owes in return is a way to read the author's sentence back, and `History.message` is that
  member: without it a workflow's own test could assert that some commit happened, which is also
  what a *missing* `commit=` produces. It promises that trailing whitespace is not part of a
  message, because git stores one with a final newline and an implementation that kept what it was
  given would not, and it deliberately promises nothing about the interior of a multi-line one —
  requiring that would be the port asking every implementation for one program's text formatting.
- **No second `IntegrationOutcome` case for a build gate's refusal.** `Integration.conflicted` in
  `sdk/_engine/integration.py` is one shape over two causes — a textual collision the `Integrator`
  reported, and a landing that combined cleanly and was then reverted by `_gated` — because both
  hold the lease and end with the same two verbs, so a workflow's conflict loop is written once. A
  third case on the port would be a value no adapter can produce: the refusal is fabricated in the
  engine, after `land` has already answered. `Integration.refused_by_the_gate` is what tells the two
  apart, and it reads the verdict `_gated` sets and `_conclude` clears — never `paths == ()`, which
  `adapters/git/_conflicts.py` also emits when git names no unmerged file. It answers about the
  shape rather than about the record, so it is false wherever `conflicted` is: a settled outcome
  still carries the verdict that refused it, and there is no longer a conflict for it to be the
  cause of.
- **`Store` has six members and no more.** No `exists`, because a read returning `None` is that
  question already answered; no listing of entries, because replay computes the digest it wants; no
  transaction, because a batch needs a boundary and a flush would admit to a buffer.
- **No retry or exit-status cleverness on the build gate.** A dead daemon, an OOM kill and a real
  test failure are not distinguishable from an exit code, so an OOM reads as a failed build and
  the cost is a re-run.
- **No `auto()` on any enum.** Enum values reach the fingerprint as text and are therefore a
  stored format; `auto()` would hand that format to declaration order.
- **No lock in `adapters/filesystem/`.** Every document has its own address, so a write is one
  `os.replace`. A mutex would be correct, slower, and invisible — it leaves every store test
  green, so `tests/adapters/test_filesystem_no_lock.py` reads the source instead.
