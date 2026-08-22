# AGL — Architecture Audit & Refactor Plan

*Version 3. Supersedes all previous drafts.*

Measured against *Architecture Rules for a Mature Multi-Service CLI*, and against three
non-technical requirements that drive every decision below:

- **R1 — Many workflows.** New workflows must be cheap and fast to build. Primary driver.
- **R2 — Swappable, mixable connectors.** Claude, OpenAI, and later a self-hosted model — *within a
  single run*, different models for different roles.
- **R3 — AGL lives outside the target repo.** It sees code changes and git state. Nothing else.

Where a rule from the rules document is changed, the justification is R1/R2/R3 — never "that would
be hard to change."

---

## Part 0 — Framing

The codebase is disciplined: import-linter contracts, `mypy --strict`, a real ABC/impl split, fakes
instead of mocks, pure functions where it counts. Almost nothing in Part 1 is sloppiness.

The problem is systematic and singular: **every seam was drawn around what exists today** — one
workflow, one agent vendor, one VCS, one output format. The abstractions are shaped like their
implementations rather than their consumers. That reads fine at N=1 and gets expensive at N=2,
which is exactly where R1 and R2 take the project.

Two consequences dominate everything else. **The agent port cannot be implemented by a non-Claude
backend.** And **adding a workflow requires editing shared code in five places.** The rest is
downstream.

---

## Part 1 — Violations

### 1.1 The agent port is Claude Code wearing an ABC (breaks R2)

Rule 3: *"Port method names and argument types are in your vocabulary, never the vendor's."*
`core/agent/api.py` fails on nearly every field:

| Port surface | Why it's the vendor's vocabulary |
|---|---|
| `AgentSpec.disallowed_tools: tuple[str, ...]` | Claude Code's permission DSL. The docstring admits it: *"speak the CLI's own pattern language (`Bash(git commit:*)`)"* |
| `AgentSpec.permission_mode: str` | Claude Code's modes (`"default"`, `"plan"`), as an unvalidated string |
| `AgentSpec.system_prompt_append` | Presupposes Claude Code's system-prompt preset model |
| `AgentSpec.add_dirs` | A Claude Code option |
| `Model` enum: `HAIKU/SONNET/OPUS/FABLE` | Anthropic product names, in the port |
| `AgentResult.session_id`, `terminal_reason` | Vendor session identity, vendor stop strings |
| `AgentQuestion` | A modelling of Claude Code's `AskUserQuestion` tool |

The leak reaches two layers up. `workflows/tickets/agents.py` contains
`GIT_WRITES = ("Bash(git commit:*)", …)`, `permission_mode="plan"`, and `model=Model.OPUS`.

Worse, the vendor's *limitations* have shaped control flow. From that same file: *"Both reviewers
run as top-level calls, never subagents: `AskUserQuestion` is unavailable to a subagent."* A Claude
Code implementation detail is determining a workflow's concurrency structure.

No fake agent exists in product code, no config selects a backend, `ClaudeRunner(settings_path=None)`
is hard-constructed in `cli.py`. There is no `--dry-run`, no `--offline`, no `--agent`.

### 1.2 Adding a workflow is not mechanical (breaks R1)

- **Duck-typed discovery.** `importlib.import_module(f"agl.workflows.{name}.workflow")` then
  `getattr(module, "resume", None)`. No `Workflow` type, nothing mypy can check. `CLAUDE.md`
  forbids dynamic imports; `cli.py` is built on them.
- **A workflow cannot declare its own inputs.** `--max-concurrent` sits on the *generic* `run`
  parser with the help text "how many tickets to work on at once," then persists into the shared
  `RunRecord`.
- **Preflight is fixed policy.** `runtime/context.py` hardcodes `_TRUNK = ("main", "master")` and
  refuses a dirty repo. A read-only workflow has no way to opt out.
- **`Board` and `Display` are the tickets dashboard in the shared layer** (`runtime/display.py`
  carries its own TODO saying so).
- **Document handling is re-implemented per workflow** — `state_document.py`,
  `tickets_document.py`, `review_documents.py`, `store_keys.py`, `runtime/json_fields.py`.
- **Roles are five hand-written near-duplicate functions** differing only in prompt, model, tools,
  and denials. That's data, written as code.
- **Resumability is authoring discipline.** `stage_of`, `step_for`, `reconcile_on_resume.py`, and
  an `if store.exists(KEY): return` guard at roughly eight sites. Every future workflow re-derives it.

### 1.3 `Vcs` is an undecomposed service boundary

**27 abstract members** spanning repo inspection, refs, worktrees, commits, diffs, and merges.
Rule 2: *"A twenty-method port is an undecomposed service boundary."*

It is git's vocabulary: `rev_parse`, `merge_base`, `is_ancestor`, `merge_in_progress`,
`unmerged_paths`, `abort_merge`, `commit_merge`. `FileStatus.code: str` carries raw porcelain codes
through the boundary (already TODO'd). The merge state machine *in the port* is git's, so a
PR-based integrator cannot implement it.

### 1.4 The composition root is not one place; commands do real work

- `Git(Path.cwd())` constructed **four times**, once per command.
- `ClaudeRunner`, `FileStore`, `RichTerminal` and the whole `RunContext` assembled **twice**,
  duplicated between `_cmd_run` and `_cmd_resume`.
- **`_cmd_clean` is a use case in the CLI** — iterating worktrees, deleting branches, calling
  `shutil.rmtree` directly, bypassing the `Store` port.
- **`_cmd_init` is a use case in the CLI** — build-tool detection (`_BUILD_GUESSES` is domain
  policy), TOML rendering, template writing. ~150 lines.
- `cli.py` is **546 lines**, against both Rule 2 and the project's own ~300-line ceiling.

### 1.5 No error hierarchy; exit codes are meaningless

**34 exception classes; 30 inherit directly from `Exception`.** Nothing is organized by meaning.

Every failure path returns `1`. A missing label, malformed config, a git refusal, an exhausted
budget, a workflow waiting on a human, and an internal bug are indistinguishable to a caller.
`_cmd_run` ends in a bare `except Exception` rendering any bug as `error: <str>`. Nothing can
script against AGL. Rule 10: exit codes are public API.

### 1.6 `RunContext` is a god-object

It mixes run identity (`label`, `request`, `base_branch`), a tickets-specific knob
(`max_concurrent`), project settings, and four live connectors — then threads through nearly every
function in `workflows/` and most of `runtime/`.

The coupling is structural: `runtime/worktrees.py` (a generic pool) imports `runtime/context.py`;
`context.py` imports `runtime/merge.py` and `core/command.py`. So `context.py` is simultaneously a
data bundle, a factory, and a policy module, and everything routes through it.

### 1.7 The build gate is an adapter with no port

`runtime/context.build_gate()` closes over `core.command.run_async` — the runtime layer reaching a
raw subprocess runner. A build can therefore only ever be a local subprocess.

### 1.8 No presenter layer; no machine-readable output

The only output path is a live Rich TUI plus bare `print()` in `cli.py`. The `Terminal` port ships
an entire component tree (`Text`/`Timer`/`Row`/`Rows`/`Screen`/`Color`) — a UI framework
masquerading as a connector. No `--json`, no plain mode, no non-interactive mode.

`main()` *is* the composition; there is no importable `agl.api`. Rule 10: *"The CLI is a thin shell
over an importable library."*

### 1.9 Fakes are test artifacts; no contract suites

- Fakes live in `tests/fakes.py`, so they cannot power product modes.
- **There is no fake `Vcs` at all.**
- `tests/fakes.py` imports `agl.core.terminal.impl.render` — reaching into `impl` from outside the
  composition root, breaking the project's own Rule 6.
- **No port has a contract suite** both its real adapter and its fake must pass. Rule 8 calls this
  *"the only thing that keeps fakes from drifting into fiction."*
- Six files under `tests/integration/` covering core flows.

### 1.10 Configuration is flat and single-sourced

- `config.toml` is flat. **No `[agent]` section**, so R2 is unreachable by configuration.
- No precedence: `AGL_HOME` is env-only, `--max-concurrent` flag-only, `build` file-only.
- Not resolved once: `agl_home()` and `load_project()` are called inside each `_cmd_*`, and
  `load_project` glob-scans and parses *every* project's config on every invocation.
- `paths.run_dir(home, label)` computes a filesystem path handed to `FileStore`, so the `Store`
  port's location is decided by a filesystem-shaped helper.

### 1.11 Enforcement gaps

The existing import-linter contracts are genuinely ahead of most codebases, but nothing enforces
what matters for R1/R2:

- No contract confining vendor SDKs to their own adapter package.
- No contract preventing `workflows` from importing `core.command`.
- `claude-agent-sdk` and `rich` are **hard dependencies**, not optional extras.
---

## Part 2 — Rules changed

1. **"One adapter per external service" → "one adapter *package* per external service; one port per
   *capability* it provides."** *(R2)* Users will want to swap how work is isolated independently
   of how it's landed. One port per adapter would recreate the 27-method `Vcs`.

2. **New rule: the workflow SDK is a public API with its own semantic version.** *(R1)* If
   workflows are the unit of growth, the surface they're written against is the most important
   interface in the project — more stable than the CLI. The rules document has nothing on this and
   it is the highest-leverage rule for the stated priority.

3. **Every operation returns data; rendering is strictly downstream.** *(R1, future frontends)*
   The rules document frames this as "machine-readable output," and that half no longer follows:
   run presentation is workflow-owned and terminal-shaped (§3.7), so there is no `--json` rendering
   of a run. What survives — and matters more — is that nothing above an adapter computes and
   renders in the same function. A machine-readable surface is therefore a *second surface object*
   (`run.web`, `run.events`) alongside `run.terminal`, not a renderer bolted onto the first. AGL's
   own commands (`workflows`, `clear`) keep plain machine-readable output.

4. **Optional dependencies are mandatory, not advisory.** *(R2)* Installing one vendor must never
   drag in another's SDK. Note the asymmetry this produces once adapters wrap CLI harnesses
   (§3.2.1): `agl[claude]` is a pip extra, while OpenAI support is a separately installed binary
   resolved at preflight.

5. **New rule: the framework owns every side effect, and workflows branch only on step results.**
   *(R1)* This single constraint is what makes resumption, memoization, and determinism free.
   Everything in §3.6 is a consequence of it.

6. **New rule: build the general case only on the second consumer.** *(R1)* The framework must not
   grow to fit one workflow's shape. Decomposition, dependency graphs, ready-sets, and parallel
   scheduling stay in `workflows/tickets` until a second workflow needs them.

---

## Part 3 — Target architecture

### 3.0 The layers

Three rings. Each answers one question and has a test for what belongs in it.

**Ring 1 — code that doesn't know the outside world exists.**

| Layer | Question | Belongs here if… |
|---|---|---|
| `ports/` | What does AGL need done, and in what words? | it's an ABC, or a type an ABC speaks. Imports nothing but stdlib. |

**Ring 2 — the work.**

| Layer | Question | Belongs here if… |
|---|---|---|
| `adapters/` | Who actually does it? | it imports a vendor SDK, touches the network, or shells out |
| `sdk/` | What do workflow authors build *from*? | **two or more** workflows would otherwise write it themselves |
| `workflows/` | What does AGL do? | it's specific to one workflow, however reusable it looks |

**Ring 3 — the edge, thin by construction.**

| Layer | Question | Belongs here if… |
|---|---|---|
| `config/` | What did the user configure, and which classes satisfy it? | it knows a file format, reads the environment, or says `new` |
| `cli/` | How does a human invoke it? | it parses argv or maps an exception to an exit code |
| `api.py` | AGL's own operations | it's run / resume / clear / init / list |

```
src/agl/
│
├── ports/                  contracts + vocabulary. imports nothing.
│   ├── errors.py               AglError hierarchy (§3.1)
│   ├── ids.py                  RunLabel · Namespace · ProjectName
│   ├── run.py                  RunSpec · RunStatus
│   ├── home_layout.py          paths under AGL_HOME       ─┐ two roots,
│   ├── tree_layout.py          paths under trees_root     ─┘ never conflated (§3.5)
│   ├── agent.py                AgentRunner · Provider · ModelId · Claude.* · OpenAI.*
│   │                           · Restriction · Capability · AgentTask · AgentOutcome
│   │                           · Tool          (crosses the port — see below)
│   ├── workspace.py            WorkspaceProvider · Workspace
│   ├── integration.py          Integrator · IntegrationOutcome · Conflict
│   ├── history.py              History
│   ├── verifier.py             Verifier
│   ├── store.py                Store          (atomic writes — §3.6)
│   ├── terminal.py             Terminal ABC + the types it speaks:
│   │                           Screen[T] · Rows · Row · Text · Choice · TextInput
│   ├── questions.py            Question · Answer  (lowest common denominator)
│   └── clock.py                Clock
│
├── adapters/               real + fake, always paired.
│   ├── claude_code/            runner · translate · models · fake
│   ├── openai/                 runner · translate · fake   (wraps Codex CLI)
│   ├── routing.py              RoutingAgentRunner — dispatch on model.provider
│   ├── git/                    _runner · workspace · integrator · history · fake
│   ├── shell/                  verifier · fake
│   ├── system_clock.py         clock · fake clock
│   ├── filesystem/             store · memory_store (= the fake)
│   └── rich_terminal/          terminal · headless (= the fake)
│
├── sdk/                    ★ PUBLIC API, own semver.
│   ├── workflow.py             @workflow · Run · Stop
│   ├── roles.py                Role(instructions, model, restrictions, tools,
│   │                                requires, on_question)
│   ├── tools.py                re-exports ports Tool + the reporting-tool
│   │                           declaration helper (§3.3) — this one has logic
│   ├── params.py               arg()
│   ├── terminal.py             re-export of ports.terminal ─┐ so authors import from
│   ├── questions.py            re-export of ports.questions ─┘ agl.sdk, never agl.ports
│   ├── testing.py              harness: workflow vs. fakes, scripted agent replies
│   └── _engine/                PRIVATE. authors never import from here.
│       ├── journal.py              fingerprints, entries, replay (§3.6)
│       ├── worktrees.py            namespace → worktree, head chaining
│       └── integration.py          per-target serialized merge + build gate
│
├── workflows/              vertical slices. registered by entry point.
│   ├── fix/                    v1.1 — one worktree, sequential, two providers
│   ├── split/                  v1.1 — N chunks, concurrent, each integrated
│   └── tickets/                v1.2 — models · findings · backlog(dag) · drive
│                               · halting · roles · tools · prompts · views/
│
├── config/                 schema · sources (flags>env>file>defaults) · toml_file
│                           · container (the only place that says `new`) · registry
│
├── cli/                    main · exit_codes · commands/{run,resume,clear,init,workflows}
│
└── api.py                  run · resume · clear · init · list_workflows
```

**Why `Screen`, `Question`, and `Tool` live in `ports/`, not `sdk/`.** The ports layer test is *"it's an ABC,
or a type an ABC speaks."* `Terminal.show()` takes a view returning `Screen[T]`, and `AgentRunner`
maps a vendor payload into `Question` — so both types cross a port and must sit below it, or
`ports` would import `sdk` and invert the layering. The `sdk` modules of the same name are pure
re-export facades, present so workflow authors write `from agl.sdk import Screen` and never reach
into `ports` directly. `Tool` is the same case — `AgentTask.tools` carries it across the agent port
— with one difference: `sdk/tools.py` is not a pure facade, because it also holds the ergonomic
reporting-tool declaration that derives a payload schema from the workflow's dataclass. Re-export
plus helper, no port types redefined.

`ports/` absorbed what would otherwise be a `domain/` package, and `config/` absorbed the
composition root. Recover both boundaries with import-linter `forbidden` contracts rather than
directories: pure types may not import ABCs; nothing outside `config/container.py` may construct an
adapter.

**One gap, found empirically at stage 0 and closed outside import-linter.** A `forbidden` contract
cannot police a package importing its own descendant — import-linter skips source/forbidden pairs
where the forbidden module descends from the source, so `src/agl/__init__.py` could import an
adapter with every contract green. Grimp sees the import; import-linter declines to judge it. The
rule therefore lives in `scripts/check` as a separate gate: **the package root holds no imports at
all.** Keep it that strict — authors import from `agl.sdk`, and a root that re-exports nothing is
one less place for a cycle to start.

The three that must never merge are `ports/`, `adapters/`, and `sdk/`.

### 3.1 The error hierarchy

One base, organized by meaning, mapped to exit codes in exactly one table — declared **as data
alongside the hierarchy in `ports/errors.py`**, so a class and its code cannot drift apart.
`cli/exit_codes.py` consumes that table and adds nothing to it.
Adapters translate vendor exceptions at their boundary; nothing above an adapter sees one.

```
AglError
├── InputError            → 2   bad flags, malformed config, invalid label
├── NotFoundError         → 3   unknown run, workflow, or project
├── ConflictError         → 4   label exists, `agl/<label>` exists, run locked
├── PermissionError       → 5   denied by policy or upstream
├── UpstreamError         → 6
│   ├── UpstreamUnavailable     agent / git / build unreachable
│   └── UpstreamUnexpected      it answered something we don't understand
├── Stop                  → 7   run ended deliberately; results persist, resume continues
└── InternalError         → 70  our bug
```

**`Stop` descends from `AglError`, so any handler must catch it first.** A bare `except AglError`
swallows a deliberate stop and reports exit 6 or 70 where the contract promises 7. That ordering is
a stage-10 acceptance criterion, not a convention.

`Stop` is the framework's terminal-end mechanism and carries no domain vocabulary. Workflows raise
their own subclasses (`ReviewNotConverging`, `BacklogStalled`). Exit 7 lets a script tell "needs
you" from "broken."

### 3.2 The agent port — multi-vendor within one run (R2)

**Requirement:** one workflow, one run, several vendors. Model choice is a **workflow-level
declaration** sitting next to the prompt, because the reason for the choice is semantic: this role
touches sensitive code, that one needs deep judgement, this one is cheap and high-volume.

Model identity is **data flowing through the port**, not a type dependency:

```python
class Provider(StrEnum):
    CLAUDE, OPENAI                      # LOCAL later

class ModelId(StrEnum):
    @property
    def provider(self) -> Provider: ...  # derived from the prefix

class Claude(ModelId):
    OPUS = "claude:opus"; SONNET = "claude:sonnet"; HAIKU = "claude:haiku"

class OpenAI(ModelId):
    SOL = "openai:sol"; TERRA = "openai:terra"; LUNA = "openai:luna"
```

One `AgentRunner` port. `adapters/routing.py` holds one adapter per provider and dispatches on
`task.model.provider`, built once at the composition root from whatever is configured and
installed. Workflows see one `AgentRunner` and never learn which adapter served them.

**The line:** model *names* crossing the port is fine — naming a model is a domain choice, like
naming a database. Vendor **syntax, types, exceptions, and option objects** never cross.

```python
class Restriction(StrEnum):          # workflow intent; adapter renders the syntax
    NO_VCS_WRITES, NO_FILE_WRITES, NO_SHELL, NO_NETWORK

class Capability(StrEnum):           # what a provider can actually do
    FILE_EDIT, SHELL, MID_RUN_QUESTIONS, TOOL_CALLING

@dataclass(frozen=True)
class AgentTask:
    instructions: str
    workspace: Path
    model: ModelId
    restrictions: frozenset[Restriction]
    tools: tuple[Tool, ...]
    context: str | None = None       # was system_prompt_append
    plan_only: bool = False          # was permission_mode="plan"
```

`GIT_WRITES = ("Bash(git commit:*)", …)` leaves the workflow and becomes
`Restriction.NO_VCS_WRITES`. Claude Code renders deny patterns; Codex CLI a sandbox policy.

**Note the spelling, verified against the shipped matcher at stage 7:** `Bash(git commit:*)` is a
*legacy prefix rule matched literally*, so `git  commit` with two spaces bypasses it. `Bash(git
commit *)` is a wildcard rule matched with whitespace collapsed, and is the correct form. The old
code's spelling is quoted in §1.1 as history; it must not be built.

**Three preflight checks, before the run starts:**

1. **Provider availability.** Collect the providers named by the workflow's roles; for each, verify
   its harness is **installed, on `PATH`, and authenticated** (§3.2.1) via
   `AgentRunner.check_ready(model)`. Only an adapter can answer that question — config cannot — so
   it is a port member rather than preflight logic. Both `check_ready` and `capabilities` take a
   `ModelId` and are async: `RoutingAgentRunner` implements the same ABC, and with no model
   argument it could only answer for "some provider," which is a lie in either direction. A Claude+OpenAI run dies at
   second zero on a missing binary or a logged-out session — not forty minutes in at the review
   step.
An adapter handed a `ModelId` it does not serve raises `InputError`; it never silently substitutes.
`capabilities()` must be **stable for the duration of a run** — preflight asks once and a workflow
then runs for an hour on that answer.

2. **Capability match.** A role declaring `requires={FILE_EDIT, MID_RUN_QUESTIONS}` is checked
   against `runner.capabilities()`. This is the principled version of *"reviewers are never
   subagents because `AskUserQuestion` isn't available"* — a vendor limitation becomes a checked
   precondition instead of a structural workaround in a docstring.
3. **Question handling.** A role declaring `on_question` must resolve to a provider with
   `MID_RUN_QUESTIONS`; the workflow genuinely cannot run on a backend without it (§3.7).

#### 3.2.1 Both adapters wrap an agent harness, not a completion API

`AgentTask` is harness-shaped — instructions, a workspace, tools, restrictions. That is the shape of
Claude Code and of Codex CLI, not of a raw chat-completions endpoint. Building the OpenAI adapter
against the bare API would mean re-implementing the tool loop, the file-edit protocol, and the
sandbox that the port already assumes exist.

So both adapters drive a CLI harness:

| | Harness | Python dependency |
|---|---|---|
| Claude | Claude Code, via `claude-agent-sdk` | `agl[claude]` |
| OpenAI | Codex CLI, via subprocess | none — the binary is installed separately |

Three consequences:

- **Extras are asymmetric, and that is fine.** `agl[claude]` pulls the Anthropic SDK; OpenAI support
  needs no pip install at all. The rule that installing one vendor never drags in the other still
  holds (Part 2, rule 4).
- **Availability is a runtime check, not an import check.** Preflight resolves each harness binary,
  checks its version, and confirms an authenticated session. A missing binary is
  `UpstreamUnavailable`, not `InputError`.
- **Billing follows the harness.** Both CLIs authenticate against a subscription by default, and
  against per-token API billing when a key is present in the environment. v1.1 inherits the parent
  environment and does not manage this; the operator keeps `ANTHROPIC_API_KEY` unset (§3.11).

**An approval mode is the leak to watch, and stage 7 confirmed the pressure is real.** A framework
run has nobody to approve a tool call, so the Claude adapter sets `permission_mode` to bypass and
Codex CLI faces the identical decision through `--sandbox` / `--ask-for-approval`. Two harnesses
agreeing is the strongest possible argument for hoisting it to the port — and hoisting it is exactly
§1.1's charge, *"an approval mode, as an unvalidated string."* It stays in each adapter. Stage 7
measured the local decision safe rather than assuming it: bare-name deny rules remove tools from a
session identically under all five modes, so the mode governs only calls that were never denied.

**Capability differences become real rather than hypothetical.** Whether Codex CLI can ask the user
a question mid-run in non-interactive mode determines whether it satisfies `MID_RUN_QUESTIONS`. That
is exactly what `capabilities()` exists to report, and a role declaring `on_question` against a
harness that cannot ask fails preflight instead of hanging.

**No config-level model override.** A workflow's model choice is a one-line edit in code the author
owns. An override mechanism would cost a config schema, resolution, validation, and a real
confusion source — *why is my Opus role running GPT-5?* It only earns its keep once workflows are
distributed and retargeted without forking. Not now.

Prompts stay in the workflow, duplication accepted, because a workflow should read as one
self-contained description of its agents. Build and test commands are written **literally into
prompts**, hand-tuned per project — no framework plumbing and no `run.project` accessor. The two
build commands are therefore independent by design: the prompt's drive the agent's TDD loop, while
`config.toml`'s `build` drives the merge gate through the `Verifier` port.

### 3.3 The workflow authoring model (R1)

**Target: one package, one entry-point line, one readable function.**

#### What an author writes

| | What it is |
|---|---|
| **Params** | a dataclass of `arg()` fields — all named flags, no positionals |
| **Roles** | instructions + model + restrictions + tools + required capabilities |
| **Tools** | the payload schemas agents report through |
| **Views** | pure functions of state, in `views/`. Nothing renders without them (§3.7) |
| **Shape** | one async function |

Everything else is framework: fingerprinting, replay, worktrees, branch naming, integration,
preflight, CLI registration, exit codes, provider routing.

#### Params — named flags only

```python
@dataclass(frozen=True)
class TicketsParams:
    request:    str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)
```

`agl run tickets -n auth -r "add oauth" -c 4`. Persisted into `run.json`, which is why
`agl resume auth` takes no flags.

#### Steps and the two step kinds

Agents never write to the store. A **reporting tool** is a capture mechanism: the agent calls it,
the tool validates the payload and hands it back, and the *framework* stores it as the step result.
One write path, one ledger.

- **Reporting step** — declares a reporting tool. Its result is that tool's payload. If the agent
  returns without firing it, there is no result and the step re-runs. (This is
  `RoleIncompleteError`, now automatic.)
- **Effect step** — no reporting tool. Result is `null`; the effect is commits in the worktree,
  made by the framework at step end when `commit=` is given (below).

A malformed payload is rejected by the tool **back to the agent within the same conversation**, so
the model corrects itself. Not an adapter retry, not a workflow retry.

#### `commit=` decides what happens to the worktree

Every step ends with the framework doing one of exactly two things, chosen by whether the call
passed `commit=`:

| | Framework does | Then |
|---|---|---|
| `commit="implement T-01"` | commits anything dirty with that message | records `head` |
| omitted | `git reset --hard` to `last_good`, then `git clean -fd` | records `head` (unchanged) |

**Why it is a parameter and not a separate call.** A `run.commit()` after the step would run *after*
the entry was written, so the recorded `head` would predate the commit — and `head` is the reset
target, so the next step to miss its fingerprint would delete the work. Committing has to be inside
the step's atomic unit.

**Why omitting it wipes rather than errors.** It makes read-only genuinely read-only. A reviewer that
scribbles a scratch file, or an agent that leaves a `.pytest_cache`, cannot contaminate the next step
or reach the merge. The absence of the parameter becomes a guarantee instead of a convention. Note
that `reset --hard` alone is not enough — untracked files survive it, which is exactly the case this
exists for, hence `clean -fd` as well. The wipe runs whether the step succeeded or raised.

This is the same reset primitive §3.6 already uses before re-running a step, applied at a second
moment. One operation, used consistently.

**Pairing is the author's job, by convention and not enforcement.** A step without `commit=` should
use a role declaring `Restriction.NO_VCS_WRITES`; otherwise an agent that commits during its own run
will have that work discarded. The framework does not check the combination and does not inspect
whether HEAD moved — it does the one predictable thing either way. This is the single place in AGL
where a mistake destroys work rather than merely costing a re-run, so the SDK docs state it plainly,
and an IDE lint plugin is the right place to catch it.

**The message is outside the fingerprint** (§3.6). It is cosmetic, so changing it must not invalidate
a step and re-run an agent. Consequence: edit the message, replay, and the existing commit keeps the
old one.

#### The whole public surface

```
run.params                        the workflow's typed params
run.step(name, role, commit=None, **inputs)
                                  the only unit of work — fingerprinted and replayed
run.worktree(name, base=None)     a child Run: new worktree, new namespace
run.integrate()                   land this Run's branch into its parent's — serialized, gated
run.activity                      current agent activity string, or None
run.terminal                      the terminal: show(), pending (§3.7)
```

Six members, plus `Stop`. There is no `ask`, no `scope`, no `workspace`, no `show`, no `view`
attribute.

**`run.params`** — the typed dataclass, parsed and validated. mypy knows `run.params.concurrent` is
an `int`. Validation failure is `InputError` → exit 2, before anything runs.

**`run.step(name, role, commit=None, **inputs)`** — the only thing that persists anything. Resolves an entry from
`(label, namespace, name)` plus a fingerprint (§3.6). On a hit it returns the stored value without
running. On a miss it resets the worktree to the last good head, builds an `AgentTask` from the
Role, dispatches to that model's provider, commits or wipes per `commit=`, and stores the result.
`**inputs` are ordinary Python values interpolated into the prompt, and they *are* part of the
fingerprint; `commit` is a real keyword on the signature, not an input, and is not.

**`run.worktree(name, base=None)`** — a child `Run` on branch `agl/_work/<label>/<name>`, cut from `base`
(another `Run`, or a ref string) or, when `base` is omitted, from this Run's branch. A workflow with
a dependency graph resolves its own blockers and passes the resulting `Run`; the framework never
reads a `blocked_by` field and never learns that a graph exists. Its own worktree and its own namespace, so `implement` in two children
never collides. Idempotent: an existing name reopens rather than recreates, which is what makes
replay work. A plain call, **not a context manager** — a context manager would tear the worktree
down on exit, destroying exactly what you want to inspect after a failure. Worktrees persist until
`clear`.

**`run.integrate()`** — merge this Run's branch into its **parent's** worktree, serialized per
target, then run the build gate and revert on failure. The root Run has no parent, so calling it
there raises, and there is no argument to point it elsewhere. **AGL never checks out or writes to
any ref outside `agl/*`** — your branches aren't protected by policy, they're unaddressable.

**`run.terminal`** — a concrete terminal, not an abstract display. `show(view, **params,
priority=0)` registers a view function and its arguments; the redraw loop re-invokes it every
frame, so anything the arguments reach renders live. `pending` reports queued questions per
priority. A future web module would be `run.web` with its own shape, live alongside it. §3.7.

**`run.activity`** — the current agent activity string for this Run, formatted by whichever adapter
is serving it, or `None` when nothing is running. Never persisted; purely visual.

#### Single-worktree workflow — a first-class shape

```python
@workflow(name="fix", params=FixParams)
async def fix(run: Run) -> None:
    await run.step("implement", implementer, commit="implement fix")
    findings = await run.step("review", reviewer)          # no commit= — worktree wiped
    if findings.high():
        await run.step("repair", implementer, findings=findings.high(),
                       commit="address review findings")
```

No `worktree()`, no `integrate()`. Multiple agents working in one worktree is just multiple steps
on the same `Run`. Commits land on `agl/hotfix` directly — that branch is the deliverable.

#### Tickets — decomposition owned entirely by the workflow

```python
@workflow(name="tickets", params=TicketsParams)
async def tickets(run: Run) -> None:
    spec = await run.step("spec", interview)

    # decompose negotiates approval inside its own session via on_question (§3.7) —
    # it returns only once the human has approved the proposal
    proposed = await run.step("tickets", decompose, spec=spec)

    backlog = Backlog(proposed.tickets)                # cycle check HERE, before any agent runs
    await drive(run, backlog, limit=run.params.concurrent)
    if left := backlog.unfinished():
        raise BacklogStalled(left)


# workflows/tickets/drive.py — the workflow's own scheduler
async def drive(run: Run, backlog: Backlog, limit: int) -> None:
    children: dict[str, Run] = {}
    await run.terminal.show(views.board, tickets=backlog.tickets, runs=children)  # once; live
    sem = Semaphore(limit)
    ...                                                # ready-set loop, retries, halt policy
                                                       # each child registers itself in `children`


async def ticket_pass(parent: Run, backlog: Backlog, ticket: Ticket,
                      children: dict[str, Run]) -> None:
    blocker = children.get(ticket.blocked_by[0]) if ticket.blocked_by else None
    w = parent.worktree(ticket.id, base=blocker)       # workflow resolves its own graph;
                                                       # framework only derives the branch name
    await w.step("implement", implementer,             # prompt instructs TDD; the agent runs
                 commit=f"implement {ticket.id}")      # its own tests, repeatedly, unbounded
    findings = await gather(                           # reviewers take no commit= — their
        w.step("review_quality", review_quality),      # worktree is restored on the way out
        w.step("review_spec",    review_spec),
    )
    if highs := high(findings):
        backlog.add(await w.step("triage", triage, findings=highs))
        return
    outcome = await w.integrate()
    if outcome.conflicted:
        ...                                            # workflow shows its own conflict view
```

`drive` owns the semaphore, the ready-set loop, retries, halt policy, and dynamic bug tickets.
`Backlog` owns the graph.

#### Namespace and step names are opaque strings

`T-01` reaches disk because the workflow passed `ticket.id` to `worktree()`. The framework stores
it as a string and concatenates it into a path — it has no ticket vocabulary, exactly as
`steps/spec/` involves no notion of what a spec is. **The test: rename `T-01` to `banana` and the
framework behaves identically.** Contrast `runtime/display.py`'s `Board`, which has ticket-shaped
*fields* — that is a genuine leak, because framework code would have to change to serve another
workflow.

Two constraints, validated on the way in: names must be filesystem- and ref-safe (no slashes, no
traversal, nonempty), and unique **within the run** — see §3.9 for why run-wide rather than
sibling-wide. `worktree()` is the only thing that creates path depth in `AGL_HOME`.

**Character set is deliberately narrower than git's.** Namespace names are frequently *agent
output* — `decompose` invents ticket IDs — and `$`, backtick, `;` and `|` are all legal in a git
ref and a POSIX filename. Restrict to `[A-Za-z0-9._-]`, non-empty, no leading or trailing `.` or
`-`, capped at `NAME_MAX`. Nobody needs a shell metacharacter in a namespace, and the cost of
allowing one is a class of problem rather than a bug.

**Reserved names.** `_base` is refused as a namespace (it is the run's own worktree directory), and
`_work` is refused as a label (it is the child-branch prefix). Both compared case- and
normalisation-insensitively, per §3.9.

#### Registration

```toml
[project.entry-points."agl.workflows"]
tickets = "agl.workflows.tickets:tickets"
```

No `importlib`, no `getattr`, no central dispatch to edit.

#### What this moves or deletes in `workflows/tickets/`

| Moves *into* tickets from shared code | Deleted outright |
|---|---|
| `runtime/dag.py` → `backlog.py` | `steps.py` — `Stage`, `stage_of`, `Step`, `step_for` |
| `runtime/scheduler.py` → `drive.py` | `ticket_claims.py` — the whole `Claims` protocol |
| `runtime/display.py` `Board` → `views/` | `reconcile_on_resume.py` |
| `runtime/agents.py` `Prompts` → prompt files | `documents/*` — four modules |
| | `Ticket.status` field |
| | the `run` / `resume` / `loop` triple |
| | the claim/release half of `run_state.py` |
| | five near-duplicate functions in `agents.py` → `Role` declarations |

What remains is `models.py`, `findings.py`, `backlog.py`, `drive.py`, halt policy, role and tool
declarations, prompts, and views — exactly this workflow's own business.

### 3.4 Splitting `Vcs`

One `adapters/git/` package; three narrow consumer-defined ports over a shared internal runner:

| Port | ~Methods | Consumer question |
|---|---|---|
| `WorkspaceProvider` | 5 | "give me an isolated place to work from this base; take it back" |
| `Integrator` | 5 | "land this workspace into the target, or tell me why not" |
| `History` | 5 | "what changed, and is X already in Y" |

Git's merge state machine stays inside `adapters/git/integrator.py`. `FileStatus.code` becomes a
`ChangeKind` enum.

**The framework runs exactly one build: the merge gate**, inside `integrate()`. It is serial
because the merge queue serializes it, and it must be — it tests a combined state that exists only
momentarily. If another item lands mid-build, the tree verified is not the tree being decided
about, and a failure cannot be attributed. It is also the only thing that catches semantic
conflicts, where two items each work alone, merge without textual conflict, and the combination is
broken. That is what a merge train is for.

**Agent self-verification is not a framework concern.** An implementation agent doing TDD runs the
test suite in its own worktree via its own shell tool, as often as its loop requires. Those runs
are side effects inside the `implement` step — the framework never sees, counts, or schedules them,
exactly as it doesn't track the agent's file writes. They are unbounded by design: an agent must
never wait to verify its own work. The only thing limiting them is the workflow's `concurrent`
knob, which is what that knob is for.

The `Verifier` port therefore has a single call site — the integration gate. One consumer, several
implementations (shell now; container, remote runner, or CI later), plus a fake.

**Landing is synchronous, and that is a real limit.** `IntegrationOutcome` has two cases —
landed, or conflicted. There is no spelling for *"opened, and waiting for a human reviewer,"* so a
pull-request integrator must either block inside the landing call or misreport an open request as a
conflict. The second is a lie. A third case was considered and rejected: it would put a scheduling
concept the framework has no vocabulary for into the port, and it collides with the same boundary
§3.11 closes on — a PR is a non-idempotent external write, so it breaks the memoization model
independently. Note the distinction from §1.3: that criticism was about git's *merge state machine*
leaking into the port, which this split fixes. Synchronous landing is a different axis, and it is
the one v1.1 accepts.

**On conflict the framework does not ask.** It returns a `Conflict` outcome and holds the lease;
the workflow shows its own screen and decides. The lease is scoped to this run's integration
target, so a human deliberating in one run never blocks another.

**The hold must be durable, not in-memory.** A run that dies holding a target can only be released
by a later invocation, so the hold has to be readable from the repository — an in-memory hold makes
a resumed run's `abort()` a silent no-op and leaves the target half-combined forever. A contract
suite cannot catch this, since both implementations pass. The requirement binds the real integrator
only — for the fake, in-memory is the premise rather than a defect.

### 3.5 AGL lives outside the target repo (R3)

**Two filesystem roots, never conflated.** `AGL_HOME` holds AGL's own state; the target repo and
its sibling `trees_root` hold the code. Split `paths.py` into `home_layout.py` (what `Store`
addresses) and `tree_layout.py` (what `Workspace` addresses). **AGL never writes into the target
repo except through a `Workspace`** — including its own integration branch, which lives in a
`_base` worktree rather than the user's checkout (§3.9).

**AGL has exactly four sensors on the target**, all out-of-process: git state, file reads, verifier
exit status and output, and whatever an agent reports through a tool.

**This is why `Verifier` must be a port.** Verification is the only channel for "is this code
actually good," it is necessarily out-of-band, and the useful implementations vary.

**Hermeticity is a port contract, not a Claude Code quirk.** `options.py` already pins
`setting_sources=[]` and `strict_mcp_config=True`. That obligation belongs to every agent adapter,
and each harness discovers its own configuration differently — `CLAUDE.md` and `.claude/` for one,
`AGENTS.md` and `.codex/` for the other. The contract is the same regardless: **the target repo
contributes source code and nothing else.**

Put it in the agent port's **contract suite**: a fixture repo carrying a poisoned config for *every*
harness, asserting each adapter ignored its own.

**What `setting_sources=[]` does and does not cover**, measured at stage 7: it suppresses the
*target repository's* configuration — a marker planted in `CLAUDE.md` reaches the composed request
under `None` and under `["user","project","local"]`, and is absent under `[]`. It does **not**
suppress the operator's own installed skills and subagent listings, which still reach the model.
That is the second channel, deferred by §3.11 and therefore consistent — but the boundary is
narrower than "the target repo contributes nothing else" sounds. `skills=[]` would close half of it
and was deliberately not adopted in v1.1.

Environment isolation is a *second* channel and is deliberately out of scope for v1.1 (§3.11).

**The same rule binds the git adapter, and it is not theoretical.** A user's own git configuration
changes what a merge means, found by experiment at stage 5: `pull.twohead = ours` makes a merge exit
0, report a head, and land **none** of the child's work — silent loss; `merge.verifySignatures`
refuses every landing; `rerere.enabled` replays a resolution recorded on another machine and lands a
combination nobody in the run ever saw. Every invocation therefore pins the settings it depends on
rather than inheriting them.

**Refs are arguments, and arguments are an injection surface.** `--end-of-options` is load-bearing
beyond shell safety: a ref spelled `--output=/path` makes `diff-tree` write a file from a port whose
whole promise is that it changes nothing, and a branch spelled `--file=…` makes `merge` land
somebody else's upstream and report success. Both reproduced at stage 5. Namespace values are
constrained by §3.3's allowlist, but `--from` is user input and is not.

**The generalisation, which governs every adapter and not only git:** every value reaching a command
line is hostile regardless of where it came from. Stage 6's verifier passes the workspace via `cwd=`
and never interpolates it into a shell string; stages 7 and 8's harness adapters inherit the same
obligation.

### 3.6 Persistence, fingerprints, and replay

#### Layout

```
AGL_HOME/
  projects/myapp.toml
  projects/myapp/runs/auth/
    run.json
    steps/
      spec/9f2c4e…a71b.json
      tickets/3d81f0…4c92.json
    worktrees/T-01/
      steps/
        implement/1d80ba…3f47.json
        review_quality/aa71c9…08de.json
      worktrees/…                       ← nests arbitrarily
```

**Runs are stored per project.** Labels are scoped to a repo, so `agl resume feat1` finds repo A's
run and reports no such label in repo B. The project is resolved from cwd by walking up to the git
root and looking it up by path — which also removes the current glob-scan-every-config behaviour.

`steps/` and `worktrees/` are sibling subtrees so `worktree("review")` and `step("review", …)` in
the same Run cannot collide.

#### `run.json`

```json
{
  "workflow": "tickets",
  "workflow_version": "1.0.0",
  "label": "auth",
  "base_ref": "main",
  "base_sha": "8c19f7ae4d2b0913e5f6",
  "branch": "agl/auth",
  "params": { "request": "add oauth", "concurrent": 4 },
  "created_at": "2026-08-18T09:14:02Z"
}
```

**`base_sha` is a full 40- or 64-character object name**, not an abbreviation — abbreviations stop
being unique exactly when a repo is large enough for it to matter. **It pins the resolved commit,
not just the ref name.** Otherwise a commit landing on `main`
between run and resume changes the first step's starting head and invalidates the entire run.

#### The entry

Every step file holds the same four fields:

```json
{
  "fingerprint": "9f2c4e…a71b",
  "value": { "tickets": [ { "id": "T-01", "title": "…", "blocked_by": [] } ] },
  "head": "4a91c07f2b3e8d15c6a0",
  "at": "2026-08-18T09:16:41Z"
}
```

The `Store` **copies any mapping it is handed** and returns copies on read, matching `Tool`'s
handling of `payload_schema`. Otherwise a caller reusing a builder dict silently edits an entry
already on the ledger.

- **`value`** — always JSON, because it can only come from a reporting tool's payload (JSON by
  construction — it arrived as a tool call), a human response, or `null` for an effect step. The
  workflow sees a typed dataclass; the Role declares the payload type and the framework
  deserializes on read. Changing that dataclass changes the tool schema, which changes the
  fingerprint, so a stale entry is discarded rather than failing to parse — that falls out free.
- **`head`** — worktree HEAD **after** this step completed. The reset target.
- **`fingerprint`** — see below. Compared on read.
- **`at`** — debugging and the view. Never read for control flow.

#### Fingerprints

```
base    = sha256(canonical_json({
              role:   (prompt text, model, restrictions, tool schemas),
              inputs: inputs,
              head:   worktree head BEFORE this step runs,
          }))
n       = times `base` was used earlier in this invocation (0, 1, 2, …)
digest  = sha256(base + ":" + str(n))        ← the filename
```

Match on path **and** fingerprint, else re-run.

**Why the role is in it.** Halt, edit the implement prompt, resume — without this you replay results
produced by the old prompt, which is exactly when you are iterating and least want stale output.
This gives proper build-system cascade: edit `decompose`'s prompt → its fingerprint changes → it
re-runs → different tickets → downstream input fingerprints change → those re-run.

**Why the starting head is in it.** `review` takes no inputs — it reviews the worktree. Without the
head term, a re-run of `implement` producing different code would leave review's fingerprint
unchanged and it would wrongly replay. The workspace *is* an input; it just isn't a named one.

**The starting head is chained logically, not read from disk.** It comes from the previous step's
recorded `head` in that namespace, never from the physical worktree. Otherwise: root runs `spec` at
H0, children integrate and advance `_base` to H5, and on resume `spec` recomputes against H5,
mismatches, and re-runs.

**Why the commit message is not in it.** A message is cosmetic. Including it would mean editing the
wording re-runs the agent, which is the opposite of what fingerprinting is for. The trade is that a
replayed step keeps the commit it already made, message and all.

**Why the counter.** A retry loop with nothing varying — same role, no inputs, no commits — would
otherwise produce an identical fingerprint every iteration and hit its own cache forever. `n` is
per-invocation and never persisted; replay walks the same calls in the same order and reproduces
the same values. Where inputs genuinely vary, each call is `n=0` and the counter is invisible.

**What it costs:** a genuinely stuck loop no longer fails loudly — it writes `n=0,1,2,…` until
something else stops it. Loop termination is therefore the workflow's job, which tickets' `drive`
wants anyway. A per-`base` ceiling in the hundreds is a cheap later safety valve; the failure mode
is financial, not an exception.

#### Replay

```
for each step, in replay order:
    entry = read(steps/<name>/<digest>.json) or None

    if entry:                                   # digest already encodes role+inputs+head+n
        last_good = entry.head
        return deserialize(entry.value)

    if last_good and worktree.head != last_good:
        worktree.reset_hard(last_good)          # discard a crashed step's leavings
        worktree.clean()

    result = run_worker()

    if commit is not None:                      # effect step
        worktree.commit_all(message=commit)     # no-op if nothing is dirty
    else:                                       # read-only step
        worktree.reset_hard(last_good)          # same primitive, second moment
        worktree.clean()

    write_atomic(path, {fingerprint, value: result, head: worktree.head, at: now()})
    last_good = worktree.head
    return result
```

Ordering is free — replay walks the workflow in order, so nothing needs sequence numbers on disk.
`last_good` is per namespace and held in memory. A crashed step leaves no entry, so the next run
resets to the last good head and starts clean.

**Accepted cost:** an agent that commits and dies before its entry is written loses that commit.
The window is milliseconds; the alternative is nondeterministic retries.

**The wipe is the same operation.** A step without `commit=` resets to `last_good` and cleans
untracked files on the way out, so a read-only role cannot leave anything behind — not a scratch
file, not a cache directory, not a partial edit. Uncommitted work is invisible to every other
worktree anyway (they share an object store, not a working tree), so nothing outside that worktree
could have observed it.

#### One file per step, and why

`T-01/implement/…json` and `T-02/implement/…json` are written by two concurrent children. Separate
paths mean each write is one `os.replace` — atomic, no lock, no coordination. A single `steps.json`
would need read-modify-write under a mutex on every completion, serializing something with no
reason to be serial. Replay reads the directory once.

Superseded entries stay on disk, which is useful when asking "why did this re-run." `clear` removes
the run directory wholesale.

#### The one rule this places on authors

**Branch only on step results.** `if findings.high()` is fine; `if datetime.now().hour < 18` breaks
replay. Enforced by an SDK contract test: run to completion, kill at every step boundary, resume,
assert identical final state.

#### Deliberately removed

`events.jsonl` (nothing reads it for control flow; OTel later) · `Document[T]` and all four
document modules (schema *is* the tool's payload type) · `done_when` predicates and completion
receipts · stored status (derived from which entries exist) · schema migration (stamp the version,
refuse on mismatch — runs live hours) · `run.request` (a param like any other) · persistent retry
counters.

### 3.7 The terminal, questions, and activity

#### `run.terminal` is a terminal, not an abstract display

Presentation reaches the workflow as a concrete object with terminal concepts on it. A future web
module is `run.web`, with websocket concepts on it — **a different shape, because it is a different
thing**, and both can be live at once (a websocket for a UI plus a terminal for local monitoring).

No `Display` port, no `--display` flag, no selection. A shared abstraction would have to be the
intersection of a terminal and a browser, which is a worse terminal and a worse browser.

**Cost, accepted deliberately:** views are terminal-shaped. `Screen`, `Rows`, `Text` are the
terminal's own component vocabulary, so they live in `sdk/terminal.py` beside `show`, free to be as
terminal-specific as they like. There is no neutral `presentation/` layer. A web module later means
writing web views alongside the terminal ones.

```
term = run.terminal

term.show(view, **params, priority=0)     awaited; priority only meaningful on Screen[T]
term.pending                              {5: 2, 10: 0} — priority → queued count
```

**Headless.** A terminal that **cannot take input** no-ops a passive `Screen` and raises
`UpstreamUnavailable` on a `Screen[T]` — a workflow needing human input genuinely cannot run that
way, and saying so immediately beats blocking forever. The rule is phrased on input rather than on
"no TTY attached" deliberately: a plain log stream has output and no input, and the TTY wording
gives it no rule at all. That behaviour doubles as the fake, so every command runs end-to-end
without a terminal.

**The terminal is an async context manager.** A redraw loop has to be started and stopped and a
display handed back; an ABC with no way to stop it pushes terminal restoration into an exit handler
outside the port.

#### One slot, two queues

The view's return type decides which, and it decides whether ordering exists at all:

| Return type | Handling |
|---|---|
| `Screen` | **the slot** — size 1, replace on write. Ordering a dashboard is meaningless, so no priority argument |
| `Screen[T]` | **a queue** — a human answers one thing at a time, so it must queue |

Priority is a plain **integer**, default 0, and only selects which queue an interactive view joins.
Not named levels: `MEDIUM` and `HIGH` would encode "agent question" and "merge conflict," which are
tickets' concepts, not the framework's. An int keeps the terminal comparing numbers and leaves room
between levels.

```python
await term.show(views.agent_question, question=q,          priority=5)
await term.show(views.conflict,       outcome=out,         priority=10)
```

Queues are FIFO within a priority, so simultaneous questions from several agents stack and wait.
The highest-priority screen is always the one rendered; when it is dismissed the terminal falls
back to the next queued question, and finally to the slot.

**Preemption is not cosmetic.** `integrate()` holds the target lease while a conflict is
unresolved, so a conflict screen queued behind two agent questions would stall the merge queue on
something unrelated. That is the entire justification for one level of preemption.

The slot keeps updating while a question is displayed — `show` re-registers, the terminal simply
isn't drawing it — so when the queue empties, the current dashboard appears. No extra machinery.

**`term.pending`** is a map of priority to queued count, excluding whatever is on screen (that is
displayed, not pending). Without it, three simultaneous questions mean two wait invisibly and the
user may walk away from a fully blocked run. The workflow renders it however it likes.

No second passive layer is needed for banners: the workflow knows it is halted, so
`board(halted=True)` renders it.

**Known and accepted:** preemption loses text a user was part-way through typing unless the
renderer preserves per-screen input state. And there are no timeouts — an unanswered question
blocks its step indefinitely, so "stuck" and "waiting for you" look alike from outside.

#### Views are pure functions, re-invoked per frame

`show` registers the view function **and its arguments**; the terminal's redraw loop calls it again
every frame (~10 Hz), diffs the resulting `Screen` against the last, and writes only on a change.

```python
# workflows/tickets/views/board.py
def board(tickets: list[Ticket], runs: dict[str, Run]) -> Screen:
    return Screen(Rows([
        Row(t.id, t.title,
            Text(runs[t.id].activity if t.id in runs else ""),
            Text(elapsed(t.started_at)))
        for t in tickets
    ]))
```

**Per-frame rather than change-detection, because it is simpler.** Detecting change would mean the
terminal knowing when `run.activity` mutated, when a `Ticket` field was assigned, when a dict gained
a key — observable wrappers or dirty flags pushed into workflow-owned data. Per-frame needs none of
that: call, diff, redraw-if-different. The diff is what makes it cheap, since the expensive part is
the terminal write and that is skipped when nothing changed.

This is why arguments need not be values. Passing `runs` — the live dict of child Runs — works
because `runs[id].activity` is evaluated again each invocation, and mutating a `Ticket` in place
shows up for the same reason. The workflow re-`show`s only to change *which* view is on screen.

**Purity is a requirement, not a convention.** Ten times a second is forgiving but not free: no
I/O, no store reads, no sorting a thousand items. This belongs in the SDK docs as a rule, since it
is the only thing making the design work.

**Composition never interleaves with workflow code.** Single-threaded asyncio, and the redraw loop
is another task; neither yields part-way, so a half-updated backlog cannot be observed. A view may
be composed before every child exists, so the workflow guards its own lookups (`runs.get(id)`).

**No default view.** A workflow that shows nothing renders nothing. Duplicated screens between
workflows are accepted, for the same reason as duplicated prompts.

#### Interactive screens

```python
# workflows/tickets/views/approval.py
def approve_backlog(question: Question) -> Screen[Approval]:
    return Screen(
        body=Text(question.prompt),
        responses=[
            Choice("Approve", value=Approval(ok=True)),
            TextInput("Suggest changes", maps=lambda s: Approval(ok=False, feedback=s)),
        ],
    )
```

`show` is always awaited: a passive `Screen` returns `None` immediately, a `Screen[T]` blocks until
the user responds and yields a `T`.

#### Agent questions are a callback on the Role

The framework supplies the asking tool (agents are instructed to use it), maps whatever payload the
vendor produced into a `Question`, and calls the workflow's handler. The handler routes it to a
view through the same single entry point. The framework has no opinion on presentation.

```python
async def approve(q: Question) -> Answer:
    return await run.terminal.show(views.approve_backlog, question=q, priority=5)

decompose = Role(
    instructions="prompts/decompose.md",
    model=Claude.OPUS,
    tools=[report_tickets],
    on_question=approve,                 # async (Question) -> Answer
)
```

`Question` and `Answer` are lowest-common-denominator across vendors — prompt text, options,
whether free text is allowed. Anything richer and only one backend could produce it. The callback
is a closure over the workflow's `Run`, keeping its signature to one parameter.

**This makes `MID_RUN_QUESTIONS` load-bearing.** A role declaring `on_question` against a provider
that cannot ask mid-run fails preflight, because that workflow genuinely cannot run on that backend.

#### Negotiation stays inside one step and one session

An approval loop is **not** a workflow loop re-invoking a step. That would start a fresh agent
session per round, discarding the reasoning that produced the proposal and re-deriving from the
spec each time.

```python
backlog = Backlog((await run.step("tickets", decompose, spec=spec)).tickets)
```

The prompt instructs: propose, ask for approval, revise until approved, then call `report_tickets`.
The step returns only once the agent reports, and it only reports once approved. One step, one
session, N rounds inside it.

**Consequence, deliberately accepted:** the fingerprint covers the final outcome only. A crash
mid-negotiation leaves no entry, so resume re-runs the step and re-asks from scratch. The
alternative is fingerprinting each round, which means persisting mid-session state no vendor session
ID reliably reconstructs. A long human negotiation is lost work if the process dies.

#### Activity is a plain string from the adapter

Each adapter formats its own activity line from the tool calls it sees — `Bash: ./gradlew build`,
`Edit: domain/usecase.kt`, `Read: connectors/api/backend.ts` — and the router passes it through
untouched. No shared verb taxonomy, no `Activity` type, no framework lookup table. The cost is
cosmetic inconsistency between vendors; the gain is that no future backend maps onto another's
vocabulary.

`run.activity` exposes the current string, `None` when nothing is running. A child Run may have two
steps in flight — the two reviewers — in which case it returns the most recent; `activity_for(step)`
can be added if per-step granularity turns out to matter.

**Never persisted.** Live-only, derived from an in-flight call; a step replayed from cache has no
activity at all, correctly, since nothing is running. Purely visual sugar.

Because views are re-invoked per frame, `Text(run.activity)` is live with no special component.
`Timer(since=…)` survives only as optional sugar for smooth sub-second ticking; at 10 Hz a plain
formatted string suffices, so it is no longer the mechanism for anything.

### 3.8 The responsibility split

**Startup and wiring**

| Framework | Workflow |
|---|---|
| Parse argv; dispatch | — |
| Discover workflows via entry points | One entry-point line |
| Turn `Params` into named flags | Declare `Params` with `arg()` |
| Resolve config: flags > env > file > defaults, once, typed | Declare a config section if needed |
| Construct every adapter; build the routing runner | — |
| Verify every named model has a credentialed provider | Name models on roles |
| Verify role capabilities, and that `on_question` roles resolve to a provider that can ask | Declare `requires` and `on_question` |
| All preflight: repo valid, `base_ref` resolves, label free, config valid | — |

**Persistence**

| Framework | Workflow |
|---|---|
| Allocate and validate the label; refuse if it exists | — |
| Write `run.json` including the pinned `base_sha` | — |
| Compute fingerprints; read and write entries; manage the counter | — |
| Write atomically | — |
| Namespace entries per `worktree()` | Choose namespace names |
| **Persist nothing else** | Persist nothing directly |

**Worktrees and branches**

| Framework | Workflow |
|---|---|
| Provision the run's `_base` worktree from `base_sha` | Decide how many worktrees exist, and their shape |
| Provision a child worktree per `worktree()` call | Choose each child's base |
| Derive branch names: `agl/<label>` (deliverable), `agl/_work/<label>/<name>` (children) | — |
| Validate names are filesystem- and ref-safe, and unique **within the run** | — |
| Commit dirty state when `commit=` is given; wipe to `last_good` when it is not | Supply the commit message, or omit it deliberately |
| Record head at each step completion; reset before a re-run | — |
| Reopen existing worktrees on replay | — |
| Remove worktrees and scope branches on `clear` | — |

**Agents and models**

| Framework | Workflow |
|---|---|
| One `AgentRunner`; dispatch on `model.provider` | Role declarations |
| Translate `Restriction` into each vendor's syntax | Say *what* is forbidden, never how it's spelled |
| Translate vendor exceptions into `AglError` | — |
| Hermeticity | — |
| Format an activity string per adapter; expose it as `run.activity` | Decide whether to render it |
| Retry **transport** failures inside the adapter | Retry **semantic** failures |
| Provide the `Tool` type; store a reporting tool's payload as the entry value | Define tools and payload schemas; reject malformed payloads back to the agent |
| Supply the asking tool; map the vendor payload to `Question`; call `on_question`; serialize the `Answer` back | Write the handler and the screen it shows |

**Decomposition and concurrency**

| Framework | Workflow |
|---|---|
| `run.worktree(name, base=…)` → a child `Run` | Splitting work into items, if it splits at all |
| | Dependency structure, and cycle detection at construction |
| | Ready-set computation |
| | Semaphore / `TaskGroup` / concurrency limit |
| | Adding work mid-run |
| | Judging whether everything finished |
| | Loop termination |

**Cycle detection belongs to the workflow because construction-time detection is strictly better:**
by the time a scheduler notices nothing is runnable, independent items have already run and burned
tokens. `Backlog(...)` raises before a single agent starts.

**Integration**

| Framework | Workflow |
|---|---|
| Serialize merges per integration target | Decide *when* to call `integrate()` |
| Merge the child branch into the parent's worktree | — |
| Run the build gate; revert on failure | — |
| Refuse `integrate()` on a parentless Run | — |
| Detect conflict; hold the lease; **emit** a `Conflict` outcome | Decide, show a screen, retry or abort |

**Failure and stopping**

| Framework | Workflow |
|---|---|
| Catch `Stop`; exit 7 | Raise its own `Stop` subclasses with domain reasons |
| Map exception → exit code, one table | — |
| Leave all entries on disk on any exit | — |
| — | Halt policy: stop admitting items, quiesce, wait, resume in place |
| — | Retry budgets, in-memory |

Halt is a **sustained mode within a running process** — stop admitting new items, let in-flight work
land, wait for a human, continue. Nothing exits. That is a scheduling policy over a backlog, so it
is entirely tickets'. The framework's `Stop` is only for terminal ends.

**Presentation**

| Framework | Workflow |
|---|---|
| The `Terminal`: components, redraw loop, slot and priority queues | **All** run presentation |
| Re-invoke the registered view every frame; diff; write on change | Write every view function, and keep it pure and cheap |
| Order interactive screens by priority, FIFO within one; preempt | Choose each screen's priority |
| Report `pending` per priority | Decide whether to render it |
| Rendering for AGL's own commands (`clear`, `init`, `workflows`) | — |
| Logs to stderr, data to stdout | — |

**Project and cleanup** — entirely framework: `init`, `clear`, project config, store layout,
`AGL_HOME`.

### 3.9 Concurrent runs on one repository

**Requirement:** several workflows — or several instances of one — running against a repo
simultaneously, each landing as a local branch the user pushes manually.

The obstacle is not locking. It is that AGL currently merges in the *user's working directory*, so
every run contends over one checked-out branch.

```
repo/                     ← user's working dir. AGL never touches it.
.trees/
  auth/
    _base/                ← worktree, branch agl/auth, cut from base_sha
    T-01/  T-02/          ← child worktrees, cut from agl/auth
  billing/
    _base/                ← worktree, branch agl/billing
    T-01/
```

`git worktree add -b agl/auth .trees/auth/_base <sha>` succeeds while `main` is checked out
elsewhere — a branch may be *started from* anywhere, it just cannot be *checked out* twice.
Concurrent runs share an object store and nothing else.

**Branch names: `agl/<label>` for the deliverable, `agl/_work/<label>/<namespace>` for children.**
The obvious scheme — `agl/auth` for the run and `agl/auth/T-01` for a child — **cannot exist in
git**, in either creation order:

```
fatal: cannot lock ref 'refs/heads/agl/auth/T-01': 'refs/heads/agl/auth' exists
fatal: cannot lock ref 'refs/heads/agl/auth': 'refs/heads/agl/auth/T-01' exists
```

Refs are files under `refs/heads/`, so `agl/auth` cannot be both a file and a directory.
`git check-ref-format` passes each name individually, which is why "must be a legal ref" does not
catch it. Routing children under `agl/_work/` keeps the deliverable branch cleanly named — the user
pushes `agl/auth`, not `agl/auth/_base` — keeps everything under the `agl/*` invariant, and costs
one extra glob at `clear`.

**Worktree directories are flat; memo namespaces nest.** `AGL_HOME` nests `worktrees/` arbitrarily
(§3.6), because it is recording the parent-child structure of the run. The trees root does **not**
nest, because a worktree inside another worktree's working tree appears as untracked files to the
parent — its `git status` and its build gate would both see the child's entire checkout.

```
.trees/<label>/_base/          .trees/<label>/T-01/          .trees/<label>/sub-b/
```

**Therefore namespace names are unique within the run, not merely among siblings.** A flat trees
root cannot distinguish `T-01`'s child `sub-b` from a top-level `sub-b`; in `AGL_HOME` they are two
scopes, in the trees root they are one directory. Uniqueness is checked run-wide, and the
comparison is case-insensitive (casefold): `T-01` and `t-01` are two refs to git and one directory
on macOS. The NFC half of `collision_key` is **vestigial** — §3.3's ASCII allowlist admits no
character with two spellings, so it can never fire. Keep it only if the allowlist is ever widened.

**Base ref is a framework-level run parameter, not a workflow param.** `agl run tickets -n auth
--from main`, defaulting to the repo's default branch. Every code-producing workflow needs one and
the framework needs it independently. It costs a non-code workflow nothing.

**Two preflight checks are deleted, not made configurable.** `_TRUNK = ("main", "master")` and the
dirty-repo refusal exist only because AGL worked in the user's directory. A worktree is created
from a *ref*, so what the user has checked out, and whether it is dirty, are both irrelevant.
`Preflight` as a workflow-declared policy object disappears entirely.

**One contention point.** `git worktree add`, `prune` **and `remove`** all mutate
`.git/worktrees/`, so a short repo-level mutex guards those operations only — milliseconds, never across a merge or a human
decision. It must be **cross-process**: two `agl run` invocations are two processes, so use
`flock(2)` on a file in the trees root, which releases automatically when the holder dies.

**No build concurrency limit.** The framework's only build is the merge gate, already serialized by
the queue. Agents running their own test suites are unbounded on purpose, governed solely by the
workflow's `concurrent`. Across concurrent runs a limiter would bind, but that is the advanced case
and the operator discovers their machine's limits faster than a config knob teaches them.

Documented consequence: if a build dies from machine exhaustion, the gate reads it as a failed
build and reverts the merge — an OOM presents as a rejected item. Gradle daemon death, exit 137,
and a genuine test failure are not cleanly distinguishable, so no attempt is made to be clever.

**Visibility during a run.** The user's working directory is never touched, so `git status` in
`repo/` stays clean. But `agl/<label>` is a real ref from run start and advances with each
`integrate()`, so progress is inspectable live — `git log agl/auth`, `git diff main..agl/auth`. Git
refuses a direct checkout of a branch held by `_base`, which is the correct guardrail.

**Cost:** worktrees share history but not working files, so three runs of five children is eighteen
checkouts of the source tree.

### 3.10 Commands

```
agl init                                          once per repo
agl run <workflow> -n <label> [workflow flags] [--from <ref>]
agl resume <label>
agl clear <label> [-f]
agl workflows                                     list what's registered
```

**`run` refuses an existing label**: *"run 'auth' already exists — `agl resume auth` or `agl clear
auth`."* `resume` takes the label only; params come from `run.json`. `resume` on a missing label
errors symmetrically. Keeping both verbs makes a typo'd label a loud error rather than a silent
replay of something unrelated.

**`init`** is lightweight and runs once per repo. It detects the git root, asks for the build
command (`_BUILD_GUESSES` exists because inferring it is unreliable), picks a trees root, and
writes `AGL_HOME/projects/<name>.toml`:

```toml
name = "myapp"
repo = "/Users/jan/dev/myapp"
trees_root = "/Users/jan/dev/.agl-trees/myapp"
build = "./gradlew build"
build_timeout = 600
```

Stored in `AGL_HOME`, not the repo, so AGL never appears in `git status`. Afterwards every workflow
works with no further setup. The standards-template writing in the current `_cmd_init` is dropped —
that content is tickets-specific and belongs to the workflow.

**`clear`** removes `.trees/<label>/`, the `agl/_work/<label>/*` child branches, and the run
directory. Note that removing the run's whole trees directory is **not expressible through
`WorkspaceProvider`** — `remove` takes back one checkout, `discard` deletes one branch. Stage 9
either gains a verb or does it directly; either way it is a decision, not an oversight. It
deletes `agl/<label>` **only if merged into the base ref**; otherwise it warns and keeps it. `-f`
deletes regardless — exactly `git branch -d` versus `-D`. The rationale is asymmetric cost: a
retained branch costs a stale ref, a deleted one costs the entire run. It refuses while a run holds
a lock.

**No `status` command.** `git log agl/<label>` and the live view cover it.

### 3.11 What was deliberately not built

| Not built | Why |
|---|---|
| `fan_out` | Decomposes into primitives each independently generic. Only the supply protocol was irreducibly fan-out-shaped, and it served one workflow. |
| `Claims` (four-callable protocol) | Three of four dissolve: completion and failure are `await` returning or raising; stalled-detection moved to the workflow. The fourth, atomic `next()`, existed only because a supply callable could double-hand-out an item. |
| `blocked_by` read by the framework | Reading it makes the framework own a schedulability question and inherit the stuck state. Half-in is the worst version. |
| Framework cycle/deadlock detection | Fires after independent items have burned tokens. Construction-time detection in the workflow is strictly better-timed. |
| `ModelTier` (FAST/BALANCED/DEEP) | Assumes the *user* picks a vendor globally. The real requirement is that the *author* picks per role, for semantic reasons. |
| Credential-environment isolation | An inherited `ANTHROPIC_API_KEY` silently redirects a harness off subscription billing onto per-token API billing. Managing which environment variables reach a spawned agent is real work — it interacts with proxies, cloud provider credentials, and each harness's own precedence rules — and it protects against a mistake the operator can simply not make. v1.1 inherits the parent environment; **keep `ANTHROPIC_API_KEY` unset.** Revisit when AGL runs somewhere the operator does not control the shell. |
| An OpenAI adapter over the raw completions API | `AgentTask` is harness-shaped. The bare API would mean re-implementing the tool loop, file-edit protocol, and sandbox the port already assumes. Codex CLI is the true analogue of Claude Code, and it also authenticates against a subscription rather than per-token billing. |
| Config-level model override | A one-line code edit in code the author owns. Costs schema, resolution, validation, and a confusion source. Revisit if workflows get distributed. |
| `Document[T]` | Schema is the reporting tool's payload type. A parallel document system is a second source of truth. |
| `done_when` / completion receipts | Every step stores its return value, even `null`. |
| Stored status | Derivable from which entries exist. Two sources of truth is what forces `reconcile_on_resume.py` to exist. |
| `Verify()` as a step worker | The framework runs one build, at the gate. Agent self-verification is a shell call inside a step, invisible by design. |
| `run.commit()` as a separate call | It would run after the entry was written, so the recorded `head` would predate the commit — and `head` is the reset target, so the next fingerprint miss would delete the work. Committing belongs inside the step's atomic unit, hence `commit=`. |
| Framework enforcement of the `commit=` / `NO_VCS_WRITES` pairing | Neither a call-site check nor a HEAD-moved detector. The framework does one predictable thing either way; the pairing is the author's judgement, documented in the SDK and catchable by an IDE lint plugin. Consistent with `blocked_by`, cycle detection, and loop termination all being the workflow's. |
| A third `IntegrationOutcome` case for asynchronous landing | Would put a scheduling concept the framework has no vocabulary for into the port, and a PR is a non-idempotent external write that breaks memoization independently (§3.4). v1.1 lands synchronously. |
| `Integrator.revert()` | Revert-on-gate-failure undoes a successful landing, which is `Workspace.restore(head)` — the same primitive at a third moment, alongside reset-before-rerun and wipe-on-omitted-`commit=`. |
| A timeout parameter on `Verifier.verify` | `build_timeout` is project configuration and reaches an implementation where implementations are configured. A hosted verifier with its own deadline would otherwise carry a parameter it can only ignore. |
| An auto-generated commit message | The message is domain vocabulary — "implement T-01" is something only the workflow knows. Auto-generating it would cost readable history to save one keyword argument. |
| `run.ask()` | Dissolved into `run.terminal.show()` with an interactive view. One entry point. |
| `question_view` on the Role | Replaced by an `on_question` callback, so the workflow routes questions through the same single `show` entry point. |
| Workflow-level approval loops | A loop re-invoking a step starts a fresh agent session per round, discarding the reasoning behind the proposal. Negotiation stays inside one step and one session. |
| An `Activity` domain type and verb taxonomy | Each adapter formats its own string. No future backend has to map onto another vendor's vocabulary. |
| `activity` as a view parameter | Views are re-invoked every frame, so `Text(run.activity)` is already live. No framework-supplied argument on any view signature. |
| `Activity(step=…)` / `Live(step=…)` components | Same reason. Re-invocation is the mechanism; components stay plain. |
| An abstract `Display` port | Forcing a terminal and a websocket into one shape yields a worse terminal and a worse browser, and blocks running both at once. `run.terminal` now, `run.web` later, each with its own concepts. |
| `--display` flag / display selection | Nothing to select: a workflow uses whichever surfaces it wants, and they coexist. |
| Named priority levels | `MEDIUM`/`HIGH` would encode "agent question" and "merge conflict" — tickets' concepts. A plain int keeps the terminal comparing numbers. |
| Change-detection for re-rendering | Would need observable wrappers or dirty flags inside workflow-owned data. Per-frame call-and-diff needs none, and the diff makes it cheap. |
| Screen input preservation across preemption, and question timeouts | Known and accepted for v1.1. |
| `run.scope` / `run.workspace` | Memo namespacing and worktree provisioning are the same act; `worktree()` does both. |
| `@workflow(view=…)` | Workflows switch views freely, so views are pushed, not declared once. |
| Default progress view | Presentation is the workflow's ownership. |
| Positional CLI args | All params are named flags via `arg()`. |
| Schema migration | Stamp the version, refuse on mismatch. Runs live hours. |
| `events.jsonl` | Nothing reads it for control flow. OTel later. |
| `run.request` / `run.project` | Impose shape. A request is a param; build commands live in prompts. |
| Persistent retry counters | A human drives resume, so a runaway loop has a person in it. |
| Per-item `Stop` semantics | Only needed because `fan_out` owned the item loop. |
| Build gate concurrency limit | One framework build, already serialized. Agent builds are deliberately unbounded. |
| Speculative merge batching | Trades compute for latency — a bad trade on one developer machine. The answer if serial integration ever becomes the bottleneck. |
| `status` command | `git log agl/<label>` and the live view cover it. |
| A shared concurrency helper | The second workflow wanting parallel isolated work rewrites ~30 lines of semaphore-and-gather. Extract on the **third** consumer. |

**The boundary this rests on:** every side effect in AGL is framework-owned — git commits (reset
handles them), agent calls (re-running costs money, nothing worse), worktree writes. A future
connector with a **non-idempotent external write** (opening a PR, posting to Slack) breaks it: a
crash between "PR created" and "entry stored" duplicates the effect. No memoization scheme fixes
that without at-most-once semantics on the external side. Not a v1.1 problem — but the day the
first such connector arrives, this design needs a new idea.

---

## Part 4 — v1.1 scope

**Green-field build.** Almost nothing in the current codebase survives intact — `RunContext` dies,
every port is respecified, `cli.py` splits five ways, and fingerprinted replay did not exist at
all. The old repo stays as a **read-only reference that specific stages are pointed at for specific
files**, never browsed: the Claude Code hermeticity settings (`setting_sources=[]`,
`strict_mcp_config=True`), git worktree edge cases, and `rich.Live`'s cadence handling
(`auto_refresh=False` plus an owned repaint task, the `is_terminal and not is_dumb_terminal`
animate test, and stopping the display to read input) are hard-won and expensive to rediscover.
Note that this list has been **wrong three times out of five** — stage 5 corrected two rows and
stage 6 found the third citation described something the file does not contain at all. Verify
before relying on a citation; the extracts are a starting point, not a specification. Everything else is written fresh, because the
danger in the old code is not that it is bad — it is that it is *coherent*, and a subagent that
browses will pattern-match to a well-written `RunContext`.

### In scope

| | Why |
|---|---|
| **The complete framework surface** | `worktree()`, `integrate()`, nested namespaces, concurrent entry writes, and priority queues are all framework-owned. Deferring them means retrofitting the storage model and the `Vcs` split rather than extending them. |
| **Both vendors — Claude Code and OpenAI** | R2 was the entire justification for the agent port's shape. One vendor and the port absorbs that vendor's assumptions, which is violation §1.1 recurring in a fresh repo. A fake does not help: whoever writes the port writes the fake to fit it. |
| **`fix`** — single worktree, sequential steps, two providers | Proves routing, both preflight checks, and restriction translation across vendors, in six lines. |
| **`split`** — N independent chunks, concurrent, each integrated | Proves child worktrees, nested namespaces, lock-free concurrent writes, the integration queue, the build gate, and the conflict path. |

`fix` and `split` are two consumers of genuinely different shape, which is what pays for
`worktree()` and `integrate()` under Rule 1. Building them with no consumer would be speculative
generality, which this plan forbids.

```python
# workflows/split — ~30 lines, and every framework path is exercised
@workflow(name="split", params=SplitParams)
async def split(run: Run) -> None:
    chunks = await run.step("plan", planner)
    async with TaskGroup() as tg:
        for c in chunks.items:
            tg.create_task(do_chunk(run, c))

async def do_chunk(parent: Run, c: Chunk) -> None:
    w = parent.worktree(c.id)
    await w.step("implement", implementer, commit=f"implement {c.id}")
    await w.integrate()
```

### Deferred to v1.2 (tickets)

All of it workflow-owned, which is the correct line: `Backlog`/dag and cycle detection, `drive`'s
ready-set loop and retries, halt policy and quiescing, dynamic work addition from triage, the
multi-round negotiation prompt, the review and triage roles, the findings model, and the board view.

**Tickets is then a genuine test of R1.** If it requires a framework change, the framework was
wrong.

### Build process

See `agl-build-stages.md`. Twenty stages, each executed by a Claude Code session in which the main
agent **never writes code** — it spawns one subagent per deliverable, in series, and verifies
mechanically (test suite, `mypy --strict`, import-linter) rather than by reading source.

Two rules that matter more than the stage list:

- **Contract suites are written by an earlier stage than the adapters they test.** A subagent
  writing its own tests writes tests that pass.
- **Enforcement config exists before any code does.** A subagent reaching across a layer should get
  a failing build, not a review comment.

---

## Part 5 — Measurable targets

1. **Adding a workflow** touches one new package plus one entry-point line. No edits to `cli/`,
   `api.py`, `sdk/`, `config/`.
2. **`fix` is ~8 lines** and gets fingerprinted replay, a worktree, preflight, and exit codes free;
   **`split` is ~30** and adds concurrency, child worktrees, and integration with no framework
   change between them.
3. **Adding an agent backend** touches one adapter package, one line in the container, one config
   section. No workflow changes.
4. **One run addresses two providers** — `fix` uses Claude to implement and OpenAI to review, in
   one run, with both preflight checks passing.
5. **Vendor containment, tested two ways.** `grep -rn "^from claude_agent_sdk\|^import
   claude_agent_sdk" src/` hits only `adapters/claude_code/`; the Codex binary name appears in no
   `.py` file under `src/` outside `adapters/openai/`. Scope matters: docs *must* name the binary to
   document the rule, so the gate covers source only. These are *import and invocation* tests, not
   name tests — `Claude.OPUS` and `OpenAI.SOL` in a workflow are correct and expected, and are the
   sanctioned way for a workflow to express provider choice without naming a harness.
6. **Deleting a connector** means deleting its adapter package, its port, its config section, and
   its container entry — nothing else breaks.
7. **Every port has a contract suite** its real adapter and its fake both pass — *every* port,
   including ones that promise little. `Clock`'s suite is two assertions; the value is the parity,
   not the coverage. **One honest exception:** six of the agent suite's eight clauses read a model's
   conduct, so under the no-paid-tests rule they run against fakes only and the real adapters are
   checked once in the manual QA pass. Everything a free instrument can reach — hermeticity, tool
   registration, deny-rule enforcement, the composed request — is covered for real adapters too.
8. **Every command runs end-to-end on fakes alone** — no network, no git.
9. **Three runs, one repo, concurrently** — two `split` and one `fix`, different base refs —
   complete without contention and leave three independent local branches.
10. **Kill-and-resume is a property test:** run any workflow to completion, kill at every step
    boundary, resume, assert identical final state.
11. **Renaming every namespace and step name** in a workflow changes only that workflow.
12. **Tickets (v1.2) requires no framework change.** If it does, the framework was wrong.
