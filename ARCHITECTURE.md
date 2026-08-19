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

## 2. The dependency rule

`cli` → `api` → `config` → `workflows` → {`sdk`, `adapters`} → `ports`

- `ports` imports **nothing but stdlib**.
- `adapters` and `sdk` both import `ports`. They are **siblings and may not import each other**.
- `workflows` import `sdk` and `ports`. Never `adapters`, never `config`.
- `config` may import everything.
- `cli` → `api` → `config`.

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

## 5. Two naming clarifications the tree does not make obvious

- **`ports/terminal.py` holds the `Terminal` ABC *and* the component types its own methods
  speak** (`Screen[T]`, `Rows`, `Row`, `Text`, `Choice`, `TextInput`). `sdk/terminal.py` and
  `sdk/questions.py` are **pure re-export facades** containing no logic, so workflow authors
  write `from agl.sdk import Screen` and never reach into `ports`. If the components lived in
  `sdk/`, `ports` would have to import `sdk` and the layering would invert.
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
| `workflow.py` | The `@workflow` decorator, the `Run` object a workflow is handed, and `Stop`. A workflow is a decorated async function, never a subclass |
| `roles.py` | `Role(instructions, model, restrictions, tools, requires, on_question)`. The author names the model per role; there is no config-level model override |
| `tools.py` | `Tool` and reporting-tool declaration. A reporting tool's payload becomes the step result |
| `params.py` | `arg()` — a workflow's params dataclass becomes named CLI flags. No positionals |
| `terminal.py` | Re-export facade over `ports.terminal` — no logic |
| `questions.py` | Re-export facade over `ports.questions` — no logic |
| `testing.py` | The harness workflow authors test against: run a workflow on an all-fakes bundle, script agent replies and questions, drive kill-and-resume |
| `_engine/journal.py` | Internal: fingerprints, entries and replay — the ledger under `steps/` that makes a run resumable |
| `_engine/worktrees.py` | Internal: namespace → worktree mapping, nested `worktrees/<name>/` storage, per-namespace head chaining |
| `_engine/integration.py` | Internal: per-target **serialized** merge, the lease, the build gate, and revert on failure |

### `workflows/` — one package per workflow, registered via the `agl.workflows` entry points

| Package | Holds |
|---|---|
| `fix/` | v1.1 — one worktree, sequential steps, two providers: Claude implements, OpenAI reviews |
| `split/` | v1.1 — N independent chunks, concurrent, each integrated into the run's base |

### `config/`, `cli/`, `api.py` — the edge

| Module | Holds |
|---|---|
| `config/schema.py` | Typed settings, with a nested section per connector |
| `config/sources.py` | Precedence: flags > env > file > defaults, resolved once into an immutable object |
| `config/toml_file.py` | The only module that knows TOML. Resolves the project by walking up to the git root |
| `config/container.py` | The composition root, the only module that constructs adapters. Builds the typed services bundle and assembles the routing runner |
| `config/registry.py` | Workflow discovery through the `agl.workflows` entry points. No `importlib`, no `getattr` |
| `cli/main.py` | Parse argv, resolve config, build the container, dispatch |
| `cli/exit_codes.py` | Re-exports `EXIT_CODES` and `exit_code_for` from `ports/errors.py` and holds no table of its own — the table is there, in exactly one place. What to do with an exception that is **not** an `AglError` is this module's only decision |
| `cli/commands/` | One module per subcommand: run, resume, clear, init, workflows |
| `api.py` | run · resume · clear · init · list_workflows |

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
