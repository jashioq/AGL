# AGL — Build Stages

Companion to `agl-refactor-plan.md`, which is the architecture and the source of truth for every
design decision. This document is only about **the order things get built and how each stage is
verified**.

Scope is v1.1 per Part 4 of the plan: complete framework surface, Claude Code + OpenAI, `fix` and
`split` workflows. Tickets is v1.2.

---

## How a stage runs

Each stage is one Claude Code session.

- The **main agent never writes code.** It spawns one subagent per deliverable, in series, and
  verifies each before starting the next.
- **Verification is mechanical, not by reading source**: run `scripts/check`, which gates on
  `pytest`, `mypy --strict`, `ruff`, `lint-imports`, Codex-binary containment, module size, and an
  import-free package root. The main agent reads *output*. Reading code is expensive in context and
  misses precisely the layer violations a linter catches.
- Failures spawn a **fixer subagent** with the failing output and the relevant deliverable only.
- **Stop rule: if a fixer fails twice on the same deliverable, halt and report.** Do not spiral.
- Every subagent receives `ARCHITECTURE.md` and the plan sections relevant to its deliverable. It
  does not receive the whole plan and does not browse the old repo.

### No test spends tokens. Ever.

**Hard rule for every stage: no automated test may make a paid model call.** Not gated, not
opt-in, not "only when you set the env var." Anything that would require one is **deferred to a
manual QA pass** at the end of the build (19.2) — record it where it arises, do not build it.

Found the hard way at stage 7, where four tests were green because the harness could not
authenticate — they asserted the run would fail, and would have passed with no harness installed at
all.

**Free, and covers most of what you want.** These need the CLI and possibly an auth check, but no
model call and no tokens:

- **The init message**, emitted when a session opens, before any model call. Lists registered tools,
  MCP servers, subagents, slash commands by name. This verifies hermeticity *and* that deny rules
  actually removed something — the two claims most worth checking.
- **A loopback endpoint** reading the composed request before it leaves. This is what settled the
  `CLAUDE.md` question, with two controls and one measurement.
- **Harness version, `--help`, config discovery** — pure CLI introspection.

**One that looks free and is not:** `check_ready` **makes a real turn**. Nothing cheaper
distinguishes logged-in from logged-out — the CLI's own `apiKeySource` reports `"none"` for a
working subscription. Stage 7.1 found it had been spending a token on every `scripts/check` run
since the machine was authenticated. Treat readiness as paid and gate it accordingly.
- **A scripted transport** through the SDK's own injection point: no CLI, no model, fully
  deterministic. Registration, payload mapping, handler invocation, answer serialised back into the
  same session — the adapter's entire half of `on_question` lives here.

**Deferred to manual QA.** Anything whose assertion depends on a *model* deciding something — the
agent asks a question, fires its reporting tool, edits a file — plus `stop_reason` mapping and
activity strings from real tool calls. These are nondeterministic or paid or both. Cover the
adapter's half with the scripted transport and record the rest.

**How a deferral is recorded.** A stage that hits a model-dependent claim appends an entry to
`docs/manual-qa.md` and moves on: what was assumed, the command a human would run to check it, and
what it would mean if it is wrong. 19.2 assembles those entries into the single ordered pass — it
does not go looking for them, so a stage that defers silently loses the item.

**The guard must be repo-wide, not per-file.** A loopback fixture scoped to one module protects one
module; the next adapter test file inherits nothing. Session-scoped autouse in `tests/conftest.py`,
an Authorization-header teardown (a redirected base URL with no API key makes the CLI send the
operator's real OAuth token to whatever is listening), and a `scripts/check` gate asserting no module
can reach a paid endpoint. A test that spends a token looks exactly like one that does not.

Three standing rules: a run that cannot happen is a **skip with a reason**, never a green; no test
may pass because something failed; and no test spends tokens.

**Deliverables are sized for the subagent (~200k). Stages are sized for the main agent**, which
accumulates review output across the whole stage — hence 3–6 deliverables each.

### Old-repo reference policy

Four deliverables are explicitly pointed at named files in the old codebase. Everything else is
written fresh. Referenced files are cited in the deliverable itself; no stage is told to "look at
how AGL does it."

---

## Stage 0 — Skeleton and enforcement

Nothing is built on an unenforced structure. Enforcement config exists before any code does, so a
subagent that reaches across a layer gets a failing build rather than a review comment.

| # | Deliverable |
|---|---|
| 0.1 | `pyproject.toml` — deps, `[claude]` extra (`claude-agent-sdk`) and `[terminal]` extra (`rich`); **no `[openai]` extra** — that adapter wraps the Codex CLI binary and needs no Python dependency (plan §3.2.1). `agl.workflows` entry-point group, `mypy --strict`, ruff, pytest config |
| 0.2 | Full directory tree per plan §3.0 with `__init__.py`, plus `ARCHITECTURE.md`: the layer table, the dependency rule, and where each kind of thing goes |
| 0.3 | `.importlinter` — layer contracts, vendor-SDK containment (`claude_agent_sdk` → `adapters/claude_code` only; `rich` → `adapters/rich_terminal` only), the pure-types-may-not-import-ABCs contract, module size ceiling. Plus a grep gate for the Codex CLI binary name, which has no Python import to contain. Plus `scripts/check` running all gates |
| 0.4 | Unrunnable skeletons of `fix` and `split` — signatures and docstrings only, marked `# STAGE 17/18`. Every later stage can read the thing it ultimately serves |

**Accept:** `scripts/check` passes on an empty tree. Contracts fail loudly when a deliberate
violation is introduced and removed.

---

## Stage 1 — Ports: foundation types

Pure, no I/O, no ABCs. Fast tests.

| # | Deliverable |
|---|---|
| 1.1 | `ports/errors.py` — the hierarchy per §3.1, with the exit-code mapping as data |
| 1.2 | `ports/ids.py` — `RunLabel`, `Namespace`, `ProjectName`, `StepName`; validation for filesystem- and git-ref-safety, narrowed charset, reserved names (§3.3) |
| 1.3 | `ports/home_layout.py` + `ports/tree_layout.py` — the two roots, never conflated (§3.5) |
| 1.4 | `ports/run.py` — `RunSpec`, `RunStatus` |

**Accept:** unit tests; `lint-imports` proves this stage imports nothing but stdlib.

---

## Stage 2 — Ports: the ABCs

Every ABC, no implementations. This is the stage that decides whether R2 holds.

| # | Deliverable |
|---|---|
| 2.1 | `ports/agent.py` — `AgentRunner`, `Provider`, `ModelId`/`Claude`/`OpenAI`, `Restriction`, `Capability`, `AgentTask`, `AgentOutcome`, and **`Tool`** — settled at stage 0: `Tool` crosses the port via `AgentTask.tools`, so it is defined here and `sdk/tools.py` re-exports it. Do **not** define `Tool` in `sdk/`. Plus `ports/questions.py` — `Question`, `Answer` |
| 2.2 | `ports/workspace.py` + `ports/history.py` (§3.4) |
| 2.3 | `ports/integration.py` + `ports/verifier.py` — `Integrator`, `IntegrationOutcome`, `Conflict`, `Verifier` |
| 2.4 | `ports/store.py` + `ports/clock.py` — store contract states atomic writes |
| 2.5 | `ports/terminal.py` — `Terminal` ABC **and the component types its own methods speak**: `Screen[T]`, `Rows`, `Row`, `Text`, `Choice`, `TextInput` (§3.7). They live here, not in `sdk/`, or `ports` would have to import `sdk`; the `sdk` modules of the same name are re-export facades added at stage 15 |

**Accept:** `mypy --strict`; no vendor **import or invocation** anywhere in the package, per target #5. Model members (`Claude.OPUS`) and prose naming a vendor in a workflow docstring are sanctioned and expected — the gate is on imports and on the harness binary name, not on the word.

---

## Stage 3 — Contract suites

**Written before the adapters, deliberately.** A subagent that writes its own tests writes tests
that pass. These suites are the objective answer to "did it work" for stages 4–8.

| # | Deliverable |
|---|---|
| 3.0 | **Stage-1 spec-drift fixes.** §3.3 and §3.9 were amended *after* stage 1 ran, so its code is correct against the old spec and wrong against the current one. Three fixes, all in `ports/`: (i) `tree_layout.worktree_branch` must compose `agl/_work/<label>/<ns>`, not `agl/<label>/<ns>` — the existing test that asserts git rejects the old pair must be **inverted** to assert git accepts the new triple; (ii) `ids.py` must enforce §3.3's allowlist `[A-Za-z0-9._-]` with no leading or trailing `.` or `-`, replacing the current blocklist that accepts `$(whoami)`, `a;b`, `a\|b`; (iii) `RunLabel("_work")` and `Namespace("_base")` must be refused in `ids.py` itself, not caught downstream |
| 3.1 | Store contract suite — including the atomic-write clause: a result exists complete or not at all |
| 3.2 | Agent contract suite — including the **hermeticity fixture**: a repo carrying a poisoned config for *every* harness (`CLAUDE.md`/`.claude/`, `AGENTS.md`/`.codex/`), asserting each adapter ignored its own (§3.5). **No credential-environment assertion** — deferred, see plan §3.11 |
| 3.3 | Workspace + History contract suites |
| 3.4 | Integrator + Verifier contract suites — merge, conflict, revert-on-gate-failure |
| 3.5 | Terminal contract suite — slot replacement, queue ordering, preemption, and the headless rule as **"a terminal that cannot take input raises `UpstreamUnavailable` on `Screen[T]`"** (§3.7 — phrased on input, not on TTY presence, so a log stream has a rule). Also pin the async-context-manager lifecycle |

*(A `ClockContract` is missing from this list and is added at 5.0 — target #7 admits no
exceptions, and the omission was found at stage 4.)*

**Accept:** every suite runs and fails cleanly against a null implementation. A suite that passes
against nothing is not testing anything. Plus, for 3.0: `agl/<label>` and `agl/_work/<label>/<ns>`
coexist in a real repo; every metacharacter §3.3 names is refused by `Namespace`; `_work` and
`_base` are refused at construction.

---

## Stage 4 — Store and Clock adapters

| # | Deliverable |
|---|---|
| 4.1 | `adapters/filesystem/store.py` — atomic via temp + `os.replace` |
| 4.2 | `adapters/filesystem/memory_store.py` — the fake |
| 4.3 | `adapters/system_clock.py` + fake clock |
| 4.4 | Test asserting every directory under `adapters/` appears in the `.importlinter` independence contract. That contract is a hand-maintained list and **fails open** — a package added at stage 5, 6, 7, or 8 is unpoliced until someone edits it (stage-0 finding). This is the first stage that adds an adapter package, so the guard lands here |

**Accept:** contract suite 3.1 passes for both real and fake. Adding a dummy `adapters/xyz/` fails
gate 4.4 until it is listed.

---

## Stage 5 — Git adapters

*Reference: old `core/vcs/impl/` for worktree edge cases and porcelain parsing.*

| # | Deliverable |
|---|---|
| 5.0 | **Stage-4 carry-overs.** (i) Generalise gate 4.4: contracts **1, 2 and 3 fail open the same way contract 4 did** — contract 2 has two hand-maintained lists so a new `ports/` module is unpoliced either way, contract 1's `layers =` would let a new top-level package sit outside the stack, contract 3's vendor list contains a third SDK not at all. One guard, all four contracts. (ii) `ports/run.py::_checked_json` refuses non-finite floats and non-str keys so they fail at write time, but passes a lone surrogate that then fails in the store — `ids.py` already handles surrogates for names; make the two agree. (iii) Add a two-assertion `ClockContract` (target #7 admits no exceptions). (iv) Comment in `.importlinter` that `unmatched_ignore_imports_alerting = none` must be flipped at 19.4 — the existing comment says only "none of them exists yet" |
| 5.1 | `adapters/git/_runner.py` — shared subprocess execution, timeouts, error mapping |
| 5.2 | `adapters/git/workspace.py` — provision, **reopen-if-exists**, remove; `flock` on the worktree registry (§3.9). Depends on 3.0(i): branch derivation must already be `agl/_work/<label>/<ns>` or every worktree this creates is unopenable |
| 5.3 | `adapters/git/history.py` — diff, changed files, ancestry; porcelain codes → `ChangeKind`. Its fixture necessarily drags in a `WorkspaceProvider`: `History` has no member that adds to a repository's past, correctly, so it must borrow `commit_all`. Sequence after 5.2 |
| 5.4 | `adapters/git/integrator.py` — merge, conflict detection, durable hold; git's merge state machine stays inside. **No `revert()`** — §3.11 records it as deliberately not built; revert-on-gate-failure is `Workspace.restore(head)` |
| 5.5 | `adapters/git/fake.py` — in-memory, no git |

**Accept:** contract suite 3.3 passes for real and fake, and **3.4's integrator half** — the
Verifier adapter is deliverable 6.1, and stage 6 claims the verifier half. The two suites were built
with no shared fixture precisely so this splits.

---

## Stage 6 — Verifier and Terminal adapters

*Reference: old `core/terminal/impl/` for `rich.Live` cadence handling — `auto_refresh=False` with an owned repaint task, the animate test, and stopping the display to read input. **Not** for a stderr workaround: stage 6 read all 244 lines and the file contains none. Rich's own `redirect_stdout`/`redirect_stderr` defaults are the real mechanism, and the obligation is that `stop()` runs on every exit path.*

| # | Deliverable |
|---|---|
| 6.1 | `adapters/shell/verifier.py` + fake — timeout, output capture, exit status. **Decide and record how the configured build command is executed**: a user writes `./gradlew build` or `npm test && npm run lint`, which wants a shell, but the working directory contains namespace names that originate as *agent output*. Pass the workspace via `cwd=`, never interpolated into a shell string; stage 1 narrowed the namespace charset as defence in depth |
| 6.2 | `adapters/rich_terminal/terminal.py` — redraw loop, per-frame re-invocation, `Screen` diff, write-on-change (§3.7) |
| 6.3 | `adapters/rich_terminal/queues.py` — slot, priority queues, FIFO within priority, preemption, `pending` |
| 6.4 | `adapters/rich_terminal/headless.py` — no-op passive, raise `UpstreamUnavailable` on `Screen[T]`; doubles as the fake |

**Accept:** contract suites 3.4 (verifier half) and 3.5 pass.

---

## Stage 7 — Claude Code adapter

*Reference: old `core/agent/impl/options.py` for hermeticity settings — `setting_sources=[]`,
`strict_mcp_config=True`, absolute settings path.*

| # | Deliverable |
|---|---|
| 7.1 | `adapters/claude_code/translate.py` — `Restriction` → deny patterns, `ModelId` → model string, vendor exceptions → `AglError`, tool calls → activity strings (§3.7) |
| 7.2 | `adapters/claude_code/runner.py` — session, tool supply, `Question` mapping, hermeticity, `capabilities()` |
| 7.3 | `adapters/claude_code/fake.py` — scripted replies, scripted questions |

**Accept:** contract suite 3.2 passes for the fake in full. **Six of its eight tests read a model's
conduct**, so under the no-tokens rule they skip for the real adapter and move to `docs/manual-qa.md`
— the two that remain (`capabilities`, and the free half of readiness) plus the free instruments
(init message, loopback) carry hermeticity, tool registration and deny-rule enforcement.

---

## Stage 8 — OpenAI adapter (Codex CLI) and routing

The stage that actually tests whether the port is vendor-neutral. If any deliverable here requires
changing `ports/agent.py`, **stop and fix the port** — that is the R2 checkpoint.

The adapter wraps the **Codex CLI binary via subprocess**, not the OpenAI completions API (plan
§3.2.1). `AgentTask` is harness-shaped, and Codex CLI is the true analogue of Claude Code: it owns
the tool loop, the file-edit protocol, and the sandbox the port assumes exist.

**Begin with 8.0, a written finding, before any code.** Determine from the Codex CLI's own
documentation and `--help`: the non-interactive invocation and its structured-output mode; how tool
calls surface in that stream; the sandbox/approval flags that `Restriction` maps onto; whether it
can ask the user a question mid-run (this decides `MID_RUN_QUESTIONS` in `capabilities()`); how it
reports session identity and stop reason. Report the findings. If the harness cannot satisfy some part of the port,
say so — `capabilities()` exists precisely to report that honestly rather than to fake it.

| # | Deliverable |
|---|---|
| 8.0a | Make the paid-endpoint guard repo-wide, before anything else. Stage 7.1's loopback and guard test are scoped to one module by a *module*-scoped autouse fixture; this stage adds a second adapter test file and Codex has the same redirectable-base-URL shape. Session-scoped fixture in `tests/conftest.py`, Authorization-header teardown generalised, and a `scripts/check` gate so the claim is verified rather than trusted |
| 8.0 | Codex CLI capability findings — written, no code. Blocks 8.1–8.3 |
| 8.1 | `adapters/openai/translate.py` — `Restriction` → sandbox/approval flags, `ModelId` → model string, CLI exit codes and stderr → `AglError`, tool-call events → activity strings |
| 8.2 | `adapters/openai/runner.py` — subprocess invocation, stream parsing, tool supply, hermeticity (ignore repo `AGENTS.md` / `.codex/`), `capabilities()` reporting whatever it genuinely cannot do |
| 8.3 | `adapters/openai/fake.py` — scripted replies, no subprocess |
| 8.4 | `adapters/routing.py` — `RoutingAgentRunner`, dispatch on `task.model.provider`, unknown provider fails loudly |

**Expect pressure to hoist the approval mode, and refuse it.** Stage 7 set
`permission_mode="bypassPermissions"` because a framework run has nobody to approve a tool call;
`--sandbox` / `--ask-for-approval` is the same decision here. Two harnesses agreeing will make
hoisting look obviously right — it is §1.1's charge verbatim, and the self-hosted HTTP backend that
has no approval concept at all is the third implementation that would pay for it. Measure the local
decision safe, as stage 7 did, rather than assuming it.

**Shared subprocess helper — decide, don't assume.** Stage 5 built `adapters/git/_runner.py`. This
stage is the second consumer of process execution, which by the plan's own rule (Part 2, rule 6) is
when the general case may be built. If extraction is warranted, add `adapters/_process.py` and
refactor git onto it in the same stage, and record it as the **one sanctioned exception** to
adapter independence in `.importlinter`. If the two needs differ enough that sharing would distort
either, say so and keep them separate. Either answer is acceptable; an unexamined default is not.

**Accept:** contract suite 3.2 passes for **both fakes** in full, and for the real adapters as far as
free instruments reach — the same six model-conduct tests that skip for Claude skip for Codex, and go
to `docs/manual-qa.md`. Routing dispatch test. `ports/agent.py` unchanged since stage 2 — a diff here is a design
failure worth reporting rather than absorbing.

---

## Stage 9 — Config, container, registry

| # | Deliverable |
|---|---|
| 9.1 | `config/schema.py` — typed settings, per-connector nested sections |
| 9.2 | `config/sources.py` — flags > env > file > defaults, resolved once into an immutable object |
| 9.3 | `config/toml_file.py` — the only module that knows TOML; project resolution by walking up to the git root (§3.6) |
| 9.4 | `config/container.py` — **the only place that says `new`**; builds the typed services bundle and assembles the routing runner from configured providers |
| 9.5 | `config/registry.py` — entry-point workflow discovery, no `importlib`, no `getattr` |

**Accept:** container builds an all-fakes bundle and an all-real bundle. Import-linter proves
nothing outside `container.py` constructs an adapter.

---

## Stage 10 — Walking skeleton

**`agl run noop -n x` exits 0 through the real wiring.** No steps, no worktrees, no persistence
beyond `run.json`. Everything after this stage is incremental on a running system, and wiring
problems surface here rather than at stage 19.

| # | Deliverable |
|---|---|
| 10.1 | `sdk/params.py` — `arg()`, dataclass → named flags, no positionals (§3.3) |
| 10.2 | `sdk/workflow.py` — `@workflow` decorator, `Stop`, minimal `Run` carrying `params` only |
| 10.3 | `cli/exit_codes.py` + `api.py` — the five operations, exceptions mapped in one table |
| 10.4 | `cli/main.py` + `cli/commands/run.py` — parse, resolve config, build container, dispatch |
| 10.5 | `workflows/noop/` — a workflow that does nothing, used as the wiring probe. Deleted at stage 19 |

**Accept:** `agl run noop -n x` exits 0. `agl run noop -n x` a second time exits 4 (label exists).
An unknown workflow exits 3. **A raised `Stop` exits 7, not 6 or 70** — `Stop` descends from
`AglError`, so the handler must catch it first, and a test must pin that ordering (§3.1).

---

## Stage 11 — Journal: fingerprinting and replay

The subtlest thing in the plan and the most expensive to get wrong quietly. Its own stage, with a
property test as the acceptance criterion.

| # | Deliverable |
|---|---|
| 11.1 | `sdk/_engine/journal.py` — fingerprint computation: canonical JSON over role/inputs/head, plus the per-invocation counter `n` and `digest = sha256(base:n)` (§3.6) |
| 11.2 | Entry read/write — `{fingerprint, value, head, at}`, atomic, path derivation, `steps/` and `worktrees/` sibling subtrees |
| 11.3 | Replay walk — `last_good` chained **logically from recorded entries, never the physical worktree**; reset-before-rerun |
| 11.4 | Kill-and-resume property test — run to completion, kill at every step boundary, resume, assert identical final state |

**Accept:** 11.4 passes. Specifically covered: a retry loop with identical role/inputs/head produces
`n = 0, 1, 2`; a changed prompt invalidates downstream entries; a run whose `_base` advanced does
**not** invalidate earlier root steps.

---

## Stage 12 — `run.step`

| # | Deliverable |
|---|---|
| 12.1 | `Run.step()` — journal lookup, `AgentTask` construction from a `Role`, dispatch, **commit-or-wipe per `commit=`**, entry write in that order (§3.3). `commit=` given → commit dirty state with that message; omitted → `reset --hard` to `last_good` plus `clean -fd`, on success and on failure alike. No check of what the role declared, no comparison of HEAD before and after |
| 12.2 | `sdk/roles.py` — `Role(instructions, model, restrictions, tools, requires, on_question)` |
| 12.3 | `sdk/tools.py` — re-export of `ports.agent.Tool` plus the reporting-tool declaration helper that derives a payload schema from a workflow dataclass; **reporting vs effect step**; malformed payload rejected back to the agent in-session (§3.3) |
| 12.4 | `Run.activity` — current string from the serving adapter, `None` when idle, never persisted |

**Accept:** a workflow of three sequential steps replays correctly against fakes. An agent that
never fires its reporting tool leaves no entry and re-runs. A step with `commit=` records a `head`
that includes the agent's changes; a step without it leaves the worktree byte-identical to
`last_good`, **including untracked files** — assert on a fake agent that writes both a tracked edit
and a new file. Changing only a commit message does not invalidate the entry.

---

## Stage 13 — `run.worktree`

| # | Deliverable |
|---|---|
| 13.1 | `Run.worktree(name, base=None)` — child `Run`, branch derivation `agl/_work/<label>/<name>` (**not** `agl/<label>/<name>` — that is a ref directory/file conflict, §3.9), idempotent reopen |
| 13.2 | `sdk/_engine/worktrees.py` — nested namespace storage, `worktrees/<name>/steps/…`, arbitrary depth |
| 13.3 | Per-namespace head chaining; concurrent lock-free entry writes from sibling children |
| 13.4 | `_base` worktree provisioning from the pinned `base_sha` (§3.9) |

**Accept:** two concurrent children write entries with no lock and no interference. Replay of a
nested run reproduces every namespace. A namespace reused anywhere in the run — not merely among
siblings — is refused, compared case- and normalisation-insensitively (§3.9). `agl/<label>` and
`agl/_work/<label>/<ns>` coexist in a real repo.

---

## Stage 14 — `run.integrate`

| # | Deliverable |
|---|---|
| 14.1 | `sdk/_engine/integration.py` — serialized integration per target; lease acquire/release, released on run exit |
| 14.2 | Merge → build gate → revert-on-failure, inside the lease |
| 14.3 | `Conflict` outcome — framework **emits**, holds the lease, never asks; `retry()` / `abort()` |
| 14.4 | `integrate()` raises on a parentless `Run` — `main` is unaddressable, not policy-protected |

**Accept:** concurrent children serialize into one `_base`. A failing gate leaves the branch
unmerged and the tree clean. Root `integrate()` raises.

---

## Stage 15 — Terminal surface and questions

| # | Deliverable |
|---|---|
| 15.1 | `Run.terminal` wiring — `show()` registers view + args; `pending` map. Plus `sdk/terminal.py` and `sdk/questions.py` as re-export facades over the `ports` types |
| 15.2 | `on_question` plumbing — framework supplies the asking tool, maps the vendor payload to `Question`, calls the handler, serializes the `Answer` back |
| 15.3 | Priority integration — agent questions and conflicts at distinct priorities; preemption verified end to end |

**Accept:** a fake agent asking mid-step reaches a workflow-defined screen and the answer returns
into the same session. A higher-priority screen preempts and restores.

---

## Stage 16 — Preflight, remaining commands, test harness

| # | Deliverable |
|---|---|
| 16.1 | Preflight — provider availability (**harness binary on `PATH`, version, authenticated session** — not merely a credential), capability match, `on_question` requires a provider that can ask (§3.2) |
| 16.2 | `cli/commands/resume.py` — label only, params from `run.json` |
| 16.3 | `cli/commands/clear.py` — `git branch -d` semantics, refuses while locked (§3.10) |
| 16.4 | `cli/commands/init.py` + `workflows.py` |
| 16.5 | `sdk/testing.py` — note the constraint stage 7 found: `sdk/` and `adapters/` are siblings and may not import each other, so this module **cannot name the fake's scripting types**. The workflow-facing scripting vocabulary lives here and `config/container.py` compiles it into the callable the fake consumes. The harness workflow authors test against: run a workflow on an all-fakes bundle, script agent replies and questions, drive kill-and-resume. Part of the public SDK surface, so it needs the same care as the rest of it |

**Accept:** a role naming a provider whose harness is missing, out of date, or logged out fails at
second zero with `UpstreamUnavailable`. `clear` on an unmerged branch warns and keeps it; `-f`
deletes. A trivial workflow written against `sdk/testing.py` runs green with no network and no git
— this is what stages 17 and 18 build their end-to-end tests on.

---

## Stage 17 — `fix`

**R1 is satisfied here if `fix` is ~8 lines.** If it is not, the SDK is wrong — report rather than
work around it.

| # | Deliverable |
|---|---|
| 17.1 | `workflows/fix/` — params, roles (**Claude implements, OpenAI reviews**), prompts with build commands written in literally |
| 17.2 | `workflows/fix/views/` — one board, one question screen |
| 17.3 | End-to-end on fakes: run, kill mid-step, resume, assert identical |

**Accept:** target #2 and target #4 from the plan.

---

## Stage 18 — `split`

| # | Deliverable |
|---|---|
| 18.1 | `workflows/split/` — params, roles, prompts, `TaskGroup` concurrency |
| 18.2 | `workflows/split/views/` — live board over N concurrent chunks reading `run.activity` |
| 18.3 | End-to-end on fakes: concurrent child worktrees, serialized integration, conflict path |

**Accept:** **no framework change was required by this stage.** A diff outside `workflows/split/`
means an abstraction was missing and should be reported, not patched around.

---

## Stage 19 — Hardening and target verification

| # | Deliverable |
|---|---|
| 19.1 | Three concurrent runs on one repo — two `split`, one `fix`, different base refs. **Fake agents, real git**: the claim is about worktree and ref concurrency, not model behaviour, so this spends nothing |
| 19.2 | Assemble `docs/manual-qa.md` into a single ordered checklist — every harness assumption accumulated since stage 7, each with what was assumed, the command to check it, and what to do if it is wrong. **Not an automated suite**: this is the one pass a human runs against real models, at the end, once |
| 19.3 | Verify all twelve measurable targets from plan Part 5, one assertion each |
| 19.4 | Enforcement audit — every contract in place and firing; delete `workflows/noop/`. Three stage-5 items: import-linter's `exhaustive = True` would close contract 1's hole natively (needs a `containers` rewrite); `src/agl/ports/__init__.py` is guarded by nothing; and module size is drifting badly — 14 over 300 at stage 3, 47 by stage 7 — so this is an audit of a backlog, not a check. Two debts carried from stage 0: flip `unmatched_ignore_imports_alerting` back to the default on the vendor-containment and composition-root contracts, now that the permitted vendor imports actually exist (it was set to `none` because the expressions matched nothing in an empty tree, which means a stale ignore is currently never reported); and confirm the adapter-independence list covers every package, including `adapters/_process.py` if stage 8 sanctioned it |

**Accept:** all twelve targets pass in CI.

---

## Notes on the shape

**Stage 8 is the R2 checkpoint.** If the Codex CLI adapter cannot satisfy `ports/agent.py`
unchanged, the port absorbed Claude Code's assumptions and the fix belongs there, not in the
adapter. This is the one place worth stopping the build. Note that both adapters now wrap CLI
harnesses, which makes the test slightly weaker than two structurally different backends would —
so scrutinise anything in the port that assumes a *session*, an *approval mode*, or a *config
file*, since those are harness concepts shared by both and could leak unnoticed.

**Stage 10 is the halfway wiring probe.** Everything before it is verified only by contract suites;
everything after runs end to end.

**Stage 18 is the R1 checkpoint.** `split` should be pure workflow code. A framework diff means the
abstraction is wrong.

**`workflows/noop/` is scaffolding** and is deleted at 19.4. It exists so stage 10 can prove wiring
before `Run.step` exists.
