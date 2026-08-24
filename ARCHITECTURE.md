# AGL architecture

The working reference for anyone adding a file to this repo. Three rings, one dependency
rule, one composition root.

## 1. The three rings

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
| `api.py` | AGL's own operations | it's run / resume / clear / init / list_workflows |
| `testing.py` | How does a workflow author test one? | it composes an all-fakes bundle and drives `api` over it |

## 2. The dependency rule

{`cli`, `testing`} → `api` → `config` → `workflows` → {`sdk`, `adapters`} → `ports`

- `ports` imports **nothing but stdlib**.
- `adapters` and `sdk` both import `ports`. They are **siblings and may not import each other**.
- `workflows` import `sdk` and `ports`. Never `adapters`, never `config`.
- `config` may import everything.
- `cli` → `api` → `config`, and `testing` → `api` → `config`. `cli` and `testing` are **siblings and
  may not import each other**: the harness is a second caller of `api`, not a layer above one.

This is enforced by `.importlinter`, not by convention. A violation is a failing build.

## 3. The composition root

**The only place that says `new` is `config/container.py`.** Nothing else constructs an
adapter. No module outside it may import from `agl.adapters.*`. Enforced by contract.

## 4. Vendor containment

- `claude_agent_sdk` may be imported only inside `agl.adapters.claude_code`.
- `rich` may be imported only inside `agl.adapters.rich_terminal`.
- The OpenAI adapter wraps the **Codex CLI binary** via subprocess and has no Python import
  to contain, so the binary name is guarded by a **grep gate** in `scripts/check` instead,
  asserting it appears only under `agl/adapters/openai/`.
- Intended asymmetry: `agl[claude]` is a pip extra; OpenAI support is a separately installed
  binary resolved at preflight. Installing one vendor never drags in the other's SDK.

## 5. Three naming clarifications the tree does not make obvious

- **`ports/terminal.py` holds the `Terminal` ABC *and* the component types its own methods
  speak** (`Screen[T]`, `Rows`, `Row`, `Text`, `Choice`, `TextInput`). `sdk/terminal.py` and
  `sdk/questions.py` are **pure re-export facades** containing no logic, and `sdk/__init__.py`
  re-exports those in turn, so workflow authors write `from agl.sdk import Screen` and never reach
  into `ports`. If the components lived in `sdk/`, `ports` would have to import `sdk` and the
  layering would invert.
- **`sdk/__init__.py` is the SDK's front door and re-exports the whole authoring surface** — every
  name from `workflow`, `roles`, `tools`, `params`, `terminal` and `questions` that a workflow is
  written out of, `__all__` typed out and never computed. Per-submodule imports go on working and
  name the same objects; `_engine` is not on it and does not become so. `sdk/roles.py` carries the
  port enums a `Role` is declared out of (`Claude`, `OpenAI`, `ModelId`, `Restriction`,
  `Capability`, `QuestionHandler`) for the same reason `sdk/tools.py` carries `Tool`, so the front
  door takes every name from a module in its own package.
- **There is no `presentation/` layer.** Components live in `ports/terminal.py`, re-exported
  through `sdk/terminal.py`; rendering lives in `adapters/rich_terminal/`. A neutral layer
  between them was considered and rejected: forcing a terminal and a websocket into one shape
  yields a worse terminal and a worse browser.

## 6. Where each kind of thing goes

### `ports/` — ABCs and the types they speak, stdlib only

| Module | Holds |
|---|---|
| `errors.py` | The `AglError` hierarchy, organised by meaning, **and the one exception → exit-code table in the codebase**: `EXIT_CODES` as the data, plus `exit_code_for()`, which walks the MRO so a workflow's own `Stop` subclass resolves without being listed |
| `ids.py` | `RunLabel`, `Namespace`, `ProjectName`, `StepName` — validated filesystem- and git-ref-safe names |
| `run.py` | `RunSpec` — what `run.json` holds — and `JsonValue`, the shape a stored value keeps. **No `RunStatus`, deliberately**: status is derivable from which entries exist, so the only honest one is a computed view over entries that will live in `sdk/_engine/journal.py`, not here — and contract 2 forbids `ports.run` from importing `ports.store`. The module docstring makes the argument; do not add a placeholder enum |
| `home_layout.py` | Paths under `AGL_HOME` — what `Store` addresses |
| `tree_layout.py` | Paths under the trees root — what `Workspace` addresses. Never conflated with `home_layout` |
| `questions.py` | `Question` and `Answer` — the lowest-common-denominator shape of a mid-run agent question, across vendors |
| `agent.py` | The `AgentRunner` ABC plus the vocabulary it speaks: `Provider`, `ModelId` (`Claude.*`, `OpenAI.*`), `Restriction`, `Capability`, `AgentTask`, `AgentOutcome`, `Tool` |
| `workspace.py` | `WorkspaceProvider` and `Workspace` — "give me an isolated place to work from this base; take it back" |
| `integration.py` | `Integrator`, `IntegrationOutcome`, `Conflict` — "land this workspace into the target, or tell me why not" |
| `history.py` | `History` — "what changed, and is X already in Y". Diffs, changed files, ancestry over the target repo. **Not a run log** |
| `verifier.py` | `Verifier` — runs the build gate. One call site: inside integration |
| `store.py` | `Store` — persists run records and step entries. The contract states atomic writes |
| `terminal.py` | The `Terminal` ABC plus its component types (see §5) |
| `clock.py` | `Clock` — the only source of the current time |

### `adapters/` — the concrete implementations, constructed only by the container

| Module | Holds |
|---|---|
| `routing.py` | `RoutingAgentRunner` — dispatches on `task.model.provider`. The one adapter module permitted to import other adapters |
| `claude_code/` | `AgentRunner` over Claude Code via `claude_agent_sdk` — the only place that SDK is imported. Real + fake |
| `openai/` | `AgentRunner` over the Codex CLI binary via subprocess — the only place that binary is named. Real + fake |
| `git/` | `WorkspaceProvider`, `Integrator` **and** `History`, over a shared internal git runner. Real + fake |
| `shell/` | `Verifier`, running the build command as a subprocess. Real + fake |
| `filesystem/` | `Store`, atomic via temp file + `os.replace`, plus the in-memory store that is its fake |
| `rich_terminal/` | `Terminal` rendering — the only place `rich` is imported. The headless terminal doubles as the fake |

### `sdk/` — what workflow authors build from

| Module | Holds |
|---|---|
| `workflow.py` | The `@workflow` decorator, the `Run` object a workflow is handed, and `Stop`. A workflow is a decorated async function, never a subclass. `roles=` is the one thing the decorator takes that is not a fact about the function: roles are module-level declarations inside the workflow's own package, so preflight has no other way to find them |
| `roles.py` | `Role(instructions, model, restrictions, tools, requires, on_question)`. The author names the model per role; there is no config-level model override |
| `tools.py` | `Tool` and reporting-tool declaration. A reporting tool's payload becomes the step result |
| `params.py` | `arg()` — a workflow's params dataclass becomes named CLI flags. No positionals |
| `terminal.py` | Re-export facade over `ports.terminal` — no logic |
| `questions.py` | Re-export facade over `ports.questions` — no logic |
| `testing.py` | The **scripting vocabulary** a workflow author writes an agent in: `Reply` (what an agent does for one task), `Call`, and `Agent = (AgentTask) -> Reply`. Port-typed, and it names no vendor and no fake — `sdk/` and `adapters/` are siblings, so `Script` and `Conversation` are not names it may write, and `config/container.py` compiles a `Reply` into the callable each fake consumes. The *builder* is `agl/testing.py`: contract 1 puts `sdk` below `config`, so nothing here can build a bundle |
| `_engine/journal.py` | Internal: fingerprints, entries and replay — the ledger under `steps/` that makes a run resumable |
| `_engine/steps.py` | Internal: what `run.step` is a delegate to — the journal lookup, the `AgentTask` a `Role` becomes, the dispatch, the commit-or-wipe and the entry write, in that order. It lives here and not in `workflow.py` because `sdk/` keeps its plumbing under `_engine/`, and because the one member that persists anything should not be read past on the way to the decorator. Also holds the cell behind `run.activity`: the last string the serving adapter reported, live-only and never persisted, which a frozen `Run` has nowhere to keep. And the one place a namespace's base is resolved — `WorkspaceProvider.open` takes a ref expression or a commit id, `Journal` takes only the second, so one `History.resolve` feeds both and the cut and the chain cannot disagree |
| `_engine/worktrees.py` | Internal: what `run.worktree` is a delegate to — the run's table of taken namespaces and the child `Run` each one carries. **Unique run-wide, not sibling-wide** (§3.9: `AGL_HOME` nests and the trees root is flat, so `T-01`'s child `sub-b` and a top-level `sub-b` are two scopes and one checkout), compared by `Namespace.collision_key`. It computes no path and holds no head: the nested `worktrees/<name>/` storage is `home_layout.scope_dir`'s one loop, and the head a child starts at is the chain in `_engine/journal.py`, read synchronously through `Steps.last_good` |
| `_engine/integration.py` | Internal: per-target **serialized** merge, the lease, the build gate, and revert on failure |
| `_engine/preflight.py` | Internal: §3.2's two questions - is this backend ready, and can it do what the role requires - asked at **two moments**. `api.run` asks both over the roles `@workflow(roles=…)` declares, before it writes anything; `run.step` asks the containment half again over the role it was actually handed, because §3.7's handler is a closure over the `Run` and a negotiating role is therefore `replace(declared, on_question=…)` and not the value preflight saw. Takes an `AgentRunner` and roles, never a `Services` |

### `workflows/` — one package per workflow, registered via the `agl.workflows` entry points

| Package | Holds |
|---|---|
| `fix/` | v1.1 — one worktree, sequential steps, two providers: Claude implements, OpenAI reviews |
| `split/` | v1.1 — N independent chunks, concurrent, each integrated into the run's base |

### `config/`, `cli/`, `api.py`, `testing.py` — the edge

| Module | Holds |
|---|---|
| `config/schema.py` | Typed settings, with a nested section per connector |
| `config/sources.py` | Precedence: flags > env > file > defaults, resolved once into an immutable object |
| `config/toml_file.py` | The only module that knows TOML — reading both file shapes and **writing** the project file `agl init` produces, so the two round-trip. Resolves the project by walking up to the git root. Also the one refusal that compares two settings against each other rather than checking one: a `trees_root` resolving to somewhere inside `repo` would put AGL's checkouts in the user's working tree (§3.5), and it is here rather than in `schema.py` because seeing it needs `Path.resolve()` and those types are pure |
| `config/container.py` | The composition root, the only module that constructs adapters. Builds the typed services bundle and assembles the routing runner. Also the one module that may name both `sdk/testing.py`'s vocabulary and an adapter's `Conversation`, so **it compiles a `Reply` into the callable each agent fake consumes** — `fakes(agent=…)`, one provider-blind agent, one raw `claude=`/`openai=` script per provider as the escape hatch. `FakeServices.with_terminal` / `with_store` swap a fake in both of that class's views at once |
| `config/registry.py` | Workflow discovery through the `agl.workflows` entry points. No `importlib`, no `getattr` |
| `cli/main.py` | Parse argv, resolve settings, dispatch. **Composition is per-command** (§3.10): the project and the container are deferred into a callable the dispatch hands on, and only a command addressed to a repository calls it — `init` writes the project file a container needs, and `workflows` needs neither. Also **the one place `Path.cwd()` is read** in AGL: `_compose` reads it, the `Invocation` carries it, and both readers — `_registered` and `agl init` — receive it |
| `cli/exit_codes.py` | Re-exports `EXIT_CODES` and `exit_code_for` from `ports/errors.py` and holds no table of its own — the table is there, in exactly one place. What to do with an exception that is **not** an `AglError` is this module's only decision |
| `cli/commands/` | One module per subcommand: run, resume, clear, init, workflows |
| `testing.py` | The harness a workflow author tests against: `harness(tmp_path, agent=…)` builds an all-fakes bundle, `run(workflow, *flags)` and `resume(workflow)` drive `api` over it, `recorded` is every entry the ledger took. A sibling of `cli/` (§2): a second caller of `api`, not a layer above one. Composes the entry point a `Workflow` object *would* be registered as and resolves it through `config/registry.py`, so the harness runs a workflow the way an installed one runs. **`interrupt_after=` is an interruption and not a kill** — in-process, `finally` blocks run — and says so; `tests/instruments/replay.py` is the version that is a kill |
| `api.py` | run · resume · clear · init · list_workflows, plus `workflow_help` behind `agl workflows <name>`. Each takes what it needs and no more: the first three a `Services` and a project, `init` the settings plus the directory it was invoked in and how to ask one question, the last two neither. **`init` grows a `cwd` where §3.10 says "settings alone"** — that sentence is about needing no *container*, and a library whose one operation could only be driven by `os.chdir` would be worse for keeping it literally |

## 7. How to run the gates

```
scripts/check
```

It runs `pytest`, `mypy --strict`, `ruff check` and `lint-imports`, plus a grep gate asserting
the Codex CLI binary name appears only under `agl/adapters/openai/`, plus a gate asserting
`src/agl/__init__.py` holds no import statements (the one blind spot `.importlinter` cannot
express — see contract 5), plus a warning for any `.py` over 300 lines (the project's own
convention). It exits non-zero if any gate fails.

`ruff check` is a failing gate, not advice: unused imports and undefined names are cheap to
catch and cheaper to fix early, and a lint that only warns stops being read. Its rules live in
`pyproject.toml` under `[tool.ruff]`.

Every gate runs every time — the run does not stop at the first failure — and a summary at the
end repeats each verdict. Refer to gates by name, not by number: gates get inserted, and the
numbering shifts under any cross-reference that names one.
