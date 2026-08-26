# AGL — Manual QA register

Every claim in this build that only a real model can settle, recorded where it arose.

**Who runs this.** A human, once, at the end of the build, on an authenticated machine, against
real models. It is not an automated suite and does not become one: `docs/agl-build-stages.md` puts
the rule as "no automated test may make a paid model call — not gated, not opt-in, not 'only when
you set the env var'", so anything whose evidence is a *model deciding something* lands here
instead of in `tests/`.

**How this file grows.** A stage that hits a model-dependent claim appends an entry and moves on.
Deliverable 19.7 assembles what is here into the single ordered pass; **it does not go looking for
entries**, so a stage that defers silently loses the item.

**What every entry carries**, because 19.7 turns them into a checklist and a reader decides per
entry whether it is worth the turn:

- **Raised by** — the stage that deferred it, and where the claim lives.
- **Assumed** — the claim being taken on trust.
- **Already covered, free** — what the automated suite really does verify, so that nobody spends a
  paid turn re-checking something a loopback already settled.
- **Command** — what to run.
- **What a pass looks like** — the literal thing to read off the output, so that a person with no
  context beyond the entry can tell a pass from a failure.
- **If it is wrong** — the consequence, named against the plan section that owns it. This is the
  part that decides whether anybody bothers.

**Step numbers and entry numbers are two different things, and both are load-bearing.** Entries are
numbered in the order they were *raised*, starting at 1, and are **never renumbered** — that number
is the entry's permanent identity, and entries cite each other by it (entry 9 cites entry 12; entry
12 cites entries 9 and 13; entries 8, 9 and 14 cite entry 2's honest boundary). **Steps** are the
order a person *runs* them in, assigned by 19.7 and free to change whenever the ordering argument
changes. Every heading below carries both: "Step 7 — Entry 12: …". Three entries — 16, 15 and 5 —
have a free half and a paid half that belong at different points in the running order, so they carry
two step numbers each; entry 13 is a record of a decision rather than a check and carries none.

**Ordering rule, so that a later reader can re-derive it rather than guess.** Cheapest first; and
anything whose failure would make `capabilities()` stop promising a member outranks anything that
merely confirms a mapping is right. That is why steps 1–5 are the free ones whatever they weigh,
why entry 12 — one turn, one tool call — precedes entry 9 rather than following it in raised order,
and why entries 1 and 8 sit at the end despite bearing on `capabilities()`: every clause they carry
has already been exercised by an earlier, cheaper step, so running them is the formal record and
not the discovery. **Step 17 is the one exception to "cheapest first", and it is not a cost
exception:** it spends nothing, but it needs the machine logged *out*, which would invalidate every
step above it.

---

## What this pass costs

**Seventeen steps: six free and eleven paid, 26 paid turns in total** if every step is run and
nothing needs a second attempt. The six free ones are steps 1–5 and step 17; step 17 is last not
because it is expensive but because it is the only step that needs the machine **logged out**, and
everything above it needs it logged in.

| | Steps | Paid turns | What it needs |
|---|---|---|---|
| **Free** | 1–5, and 17 | **0** | An installed CLI. No credential, no model, no tokens |
| **Paid, and it settles what `capabilities()` promises** | 6–10 | **5** | An authenticated machine |
| **Paid, and it confirms a mapping or a behaviour** | 11–14 | **5** | An authenticated machine |
| **Paid, and it is the formal contract-suite re-run** | 15–16 | **16** | An authenticated machine |

**Sixteen of the twenty-six are steps 15 and 16**, the two contract-suite re-runs, and a reader may
reasonably defer them: every clause in them is exercised more cheaply by steps 6–14, so what those
two add is the suite going green against a real adapter rather than a new fact. **The other ten
turns settle everything `capabilities()` promises on both backends.** All of them are on the cheap
tier — `Claude.HAIKU`, `OpenAI.LUNA` — except steps 9, 13 and half of 14, which ask for
`Claude.SONNET` because they are about a model's judgement rather than its plumbing.

Everything listed under "already covered, free" in an entry runs on every `scripts/check` with no
model behind it: `tests/instruments/loopback.py` binds `127.0.0.1` and answers a real `claude`
process out of canned data, a scripted `claude_agent_sdk` `Transport` drives that adapter with no
CLI at all, and a stub CLI drives the Codex adapter's own MCP server over real HTTP. **Do not spend
a paid turn on any of it.**

---

## The running order

Work down this table. The entry sections below are in the same order, headed by the step they are
first worked at.

| Step | Entry | What it settles | Cost |
|---|---|---|---|
| 1 | 16 (part one) | `tool_timeout_sec` still lands — the key AGL's `MID_RUN_QUESTIONS` rests on | **free**, needs `codex` |
| 2 | 15 (Claude half) | A payload schema carrying `title` registers with the Claude CLI | **free**, needs `claude` |
| 3 | 7 | The `AskUserQuestion` deny rule is still vacuous, so there is still one asking mechanism | **free**, needs `claude` |
| 4 | 11 | Codex's remaining configuration channels are still closed | **free**, needs `codex` |
| 5 | 6 | Where `setting_sources=[]` draws its line — repository or machine | **free**, needs `claude` and a plain shell |
| 6 | 5 (returning branch) | This machine is authenticated to Claude at all — the gate on steps 9, 11, 13, 14, 15 | 1 turn |
| 7 | 12 | Codex's MCP client accepts the server AGL runs for it. **Rides: entry 15's Codex half** | 1 turn |
| 8 | 9 | A live Codex agent calls an AGL tool, asks through it, and survives a long wait | 1 turn |
| 9 | 2 | A live Claude agent asks through `mcp__agl_ask__ask` and uses the answer | 1 turn |
| 10 | 16 (part two) | What Codex does *at* the deadline. **Must follow step 8** — it lowers `_TOOL_SECONDS` | 1 turn |
| 11 | 3 | `stop_reason` mapping against live Claude outcomes | 1 turn |
| 12 | 10 | `codex exec`'s terminal events against live outcomes | 1 turn |
| 13 | 4 | Activity strings from real tool calls. **Entry 3's `None` row rides here** | 1 turn |
| 14 | 14 | Whether a live agent reads the inputs block appended to its prompt | 2 turns |
| 15 | 1 | The eight deferred contract clauses, Claude Code | 8 turns |
| 16 | 8 | The eight deferred contract clauses, Codex CLI | 8 turns |
| 17 | 5 (refusing branch) | A logged-out machine refuses with `UpstreamUnavailable` and says so | **free**, needs a logged-out machine |
| — | 13 | *Not a check.* The record of what stage 8.2 did not build, and what it left open | — |

**Which steps would change a `capabilities()` promise if they fail**, which is the question rule 2
orders by:

| Step | Entry | Capability | Backend |
|---|---|---|---|
| 1 | 16 (part one) | `MID_RUN_QUESTIONS` | Codex |
| 7 | 12 | `TOOL_CALLING` **and** `MID_RUN_QUESTIONS` | Codex |
| 8 | 9 | `TOOL_CALLING` **and** `MID_RUN_QUESTIONS` | Codex |
| 9 | 2 | `MID_RUN_QUESTIONS` | Claude Code |
| 10 | 16 (part two) | `MID_RUN_QUESTIONS` | Codex |
| 15 | 1 | `TOOL_CALLING`, `FILE_EDIT`, `MID_RUN_QUESTIONS` | Claude Code |
| 16 | 8 | `TOOL_CALLING`, `FILE_EDIT`, `MID_RUN_QUESTIONS` | Codex |

Both adapters answer the same four members from a frozen `_CAPABILITIES` constant — `FILE_EDIT`,
`SHELL`, `MID_RUN_QUESTIONS`, `TOOL_CALLING` — so a member dropped is dropped for every task on
every machine, and §3.2's second and third preflight checks then refuse the roles that need it.
Nothing else in this file can move one.

**A note on the ordinals, because they are greppable and they disagree with §3.2's own count.**
§3.2's heading is "Two preflight checks, **before the run starts**" and it numbers two: provider
availability, then capability match. The implementation numbers **three**, consistently, across five
sites — `sdk/_engine/preflight.py` (twice), `sdk/_engine/steps.py`, `sdk/roles.py` and
`workflows/fix/roles.py` — where the third is "a role declaring `on_question` resolves to a provider
with `MID_RUN_QUESTIONS`" (`preflight.py`'s own words). §3.2 discusses exactly that implication and
declines to number it, saying it falls out of check 2 "rather than needing a check each". **Both are
internally consistent and this file follows the implementation's vocabulary**, since that is what a
reader greps. Reported, not resolved — see the note at the end of this file.

---

**Environment these entries were measured in**, so a later reader can tell a drift from a
disagreement:

```bash
claude --version && .venv/bin/python -c "import claude_agent_sdk as s; print(s.__version__)"
codex --version && codex login status
```

At the time of writing the first reports `2.1.220 (Claude Code)` — `/opt/homebrew/bin/claude`, a
symlink into `Caskroom/claude-code/2.1.220` — and `claude-agent-sdk` `0.2.140`, on macOS
(darwin 25.4.0). The second, added at stage 8, reports `codex-cli 0.149.0` —
`/opt/homebrew/bin/codex`, a symlink into `Caskroom/codex/0.149.0` — and `Logged in using ChatGPT`,
with `~/.codex/` holding `auth.json` and **no `config.toml`**, so every Codex default cited in
entries 8–11 is the packaged default rather than this operator's preference.

**Re-measured at 19.7, when this file was assembled: all four numbers are unchanged** — `2.1.220`,
`0.2.140`, `0.149.0`, same two symlinks, same macOS. So nothing below is a drift as of assembly,
and a later disagreement is a real one. The one number that was already known to move on its own is
the *running* CLI version announced in `init.claude_code_version`, which entry 7 records and
explains.

---

## Steps 1 and 10 — Entry 16: What Codex does when a tool call outlives `tool_timeout_sec`

**Raised by:** stage 16.1 — §3.7's "One place the design's unbounded wait meets a vendor clock"
(plan line ~1233) and `src/agl/adapters/openai/runner.py`'s "Tool supply" section, which sets
`tool_timeout_sec=86_400` through a `-c` override (`_TOOL_SECONDS`).

**This entry has a free half and a paid half, and they are two steps apart on purpose.**

- **Step 1 — part one, free, one second, and the first thing anybody should run in this pass.** Does
  the key still land? It is the cheapest check in the file and it guards the largest quiet failure
  in it, for the reason under "An unknown *key* is silent" below.
- **Step 10 — part two, paid, one turn.** What does Codex do *at* the deadline? It must follow
  **step 7** (entry 12 — nothing here is readable until the MCP client works) and **step 8** (entry
  9 — part two lowers `_TOOL_SECONDS` to 5, which would sabotage entry 9's 90-second wait if run
  first).

**This is a behavioural claim and there is no free instrument for the paid half.** 16.1 was asked
whether preflight could catch it and the answer is no; the reasoning is under "If it is wrong"
below, because it is the same reasoning that says what to do when it happens.

**Assumed.** Three things, and only the first is measured:

1. That this build's config loader accepts `mcp_servers.agl.tool_timeout_sec` and carries the value
   into the server configuration `codex exec` uses. **Measured, free — see the command.**
2. That a value it accepts is a value it *applies* to a streamable-HTTP MCP tool call. Nothing has
   watched a tool call outlive 60 seconds and survive.
3. That when a tool call does time out, the harness **returns an error to the model** rather than
   **aborting the turn**. `docs/codex-cli-findings.md` §4 names both as live possibilities and says
   8.2 "must check what Codex does when a tool call *does* time out, because … [they] are different
   outcomes for §3.7". Nobody has. §3.7 has no question timeouts by design, so on the backend with
   no second asking mechanism a timeout ends the question with nothing to fall back to.

**Already covered, free — and one of these corrects an assumption this file used to rest on.**

- **The key is accepted and its value is echoed back.** `codex mcp list --json` and
  `codex mcp get agl --json`, given the adapter's own override, both report
  `"tool_timeout_sec": 86400.0` on codex-cli 0.149.0 with an empty `CODEX_HOME`. Entry 12 records
  the same measurement from the other end.
- **A wrong *type* is loud.** `tool_timeout_sec="forever"` fails the load by name:
  `invalid type: string "forever", expected f64 in mcp_servers.agl.tool_timeout_sec`. So the
  integer AGL sends can never be silently coerced or dropped for being malformed.
- **An unknown *key* is silent, and that is the correction.** `mcp_servers.agl.nonsense_key=1` is
  accepted by `codex mcp list` **and** by the full config loader behind `codex debug prompt-input`,
  both exiting 0 with no mention of it; an unknown top-level key is ignored the same way. Entry 12
  and the findings' §0 say "a value its loader dislikes is refused by name", which is true of a bad
  value for a *known* key and **not** of a key the loader no longer knows. So a release that renamed
  or removed `tool_timeout_sec` would drop AGL's override in silence and put the timeout back at the
  documented default of 60 seconds — under a person's thinking time, which is exactly how
  `MID_RUN_QUESTIONS` dies quietly.
- **Everything below the harness is exercised on every `scripts/check`.**
  `tests/adapters/test_openai_runner.py` drives the real in-process MCP server over real HTTP from a
  stub CLI, so the asking tool, its handler and the round trip are covered; what is not covered is
  this vendor's clock on top of them.

**Command — STEP 1, part one. Free, no model, no tokens, one second.** Needs an installed `codex`
and nothing else — no credential, and `CODEX_HOME` is deliberately emptied so no login is consulted.
Confirm the key still lands, against whatever `codex` is installed now:

```bash
EMPTY=$(mktemp -d)
CODEX_HOME=$EMPTY codex mcp get agl --json \
  -c 'mcp_servers.agl={url="http://127.0.0.1:8765/mcp",tool_timeout_sec=86400,startup_timeout_sec=30,default_tools_approval_mode="auto"}'
```

**What a pass looks like.** The literal string `"tool_timeout_sec": 86400.0` in the output, and exit
0. A `null`, an absent field, or a load error naming the key is the silent-drop case above; it is a
change to `_TOOL_SECONDS`' spelling in `src/agl/adapters/openai/runner.py`, not a change to anything
in `sdk/`, and it means `MID_RUN_QUESTIONS` on this backend is a lie until the spelling is fixed —
so fix it before running steps 7, 8 and 10, which all rest on it.

**Command — STEP 10, part two. Paid, one turn, and it is the reason this entry exists.** The claim
is about what happens *at* the deadline, so it needs a real tool call that outlives one. A 24-hour
call cannot be waited on, so lower the number for the experiment and hold the tool. In a scratch git
repository, on an authenticated machine, with `_TOOL_SECONDS` temporarily set to `5` in
`src/agl/adapters/openai/runner.py` — **after step 7 has passed and after step 8 has been run**,
since lowering the deadline first would make step 8 fail for this reason rather than its own:

```bash
.venv/bin/python -c "
import asyncio, time
from pathlib import Path
from agl.adapters.openai.runner import OpenAiRunner
from agl.ports.agent import AgentTask, OpenAI, Tool, ToolResult

async def slow(payload):
    await asyncio.sleep(20)          # four times the lowered deadline
    return ToolResult(text='Answered, late. Say the single word: late')

tool = Tool(
    name='ask_the_person',
    description='Ask the person running this task a question and wait for their answer.',
    payload_schema={'type': 'object', 'properties': {'question': {'type': 'string'}},
                    'required': ['question']},
    handler=slow,
)
task = AgentTask(
    instructions='Call ask_the_person once with any question, wait for the answer, and then '
                 'reply with exactly the single word it tells you to say.',
    workspace=Path.cwd(),
    model=OpenAI.LUNA,
    restrictions=frozenset(),
    tools=(tool,),
)
print('OUTCOME:', asyncio.run(OpenAiRunner().run(task, on_activity=print)))
"
```

**What a pass looks like: there is no pass here, only three outcomes, and the run's whole value is
recording which one happened verbatim.** This step is a measurement rather than an assertion — that
is why it is worth a turn. Read the three apart:

- **The handler's answer arrives late and the agent uses it.** The deadline is advisory for a
  streamable-HTTP server and §3.7's collision is not real. Best case; nothing to change.
- **The tool call fails and the agent carries on**, closing its turn without the word. The deadline
  is enforced and reported to the model. This is the case the adapter is written for, and 86 400
  seconds is what keeps it from happening — but note what it means: a person who takes longer than
  the deadline gets an agent that guesses, which is the silent failure `sdk/roles.py` refuses.
- **The turn aborts** — a non-zero exit, a `turn.failed`, or a stream that stops. Then a timed-out
  question kills the step rather than degrading it. Loud, and the better of the two failures.

Restore `_TOOL_SECONDS` afterwards. **Run this in the same session as steps 7 and 8 if possible** —
the same scratch repository and the same login serve all three, and entry 12 (step 7) must pass
first or nothing here is readable.

**If it is wrong.** The repair depends on which outcome came back, and none of them is in `sdk/`:

- **Aborts the turn.** `MID_RUN_QUESTIONS` on this backend is then held together by a number, which
  is what `docs/codex-cli-findings.md` §9 pressure 3 already calls "a capability held together with
  tape" and carries to stage 17. The honest moves are to keep the day-long deadline and say so, or
  to drop the member from that adapter's `_CAPABILITIES` and let §3.2's preflight route asking roles
  to the other backend — which is a legal, tested position (`tests/contracts/_agent_questions.py`
  branches on the capability the adapter itself reported).
- **Errors the tool.** Nothing changes; the deadline stays where it is and this entry becomes a
  measurement rather than a risk.

**Why preflight does not check any of this, which 16.1 was asked to settle.** Part one's command is
free and local, so a check is *possible*; it is still the wrong place, for four reasons that stack:

- **It is not preflight's to make.** `sdk/_engine/preflight.py` takes an `AgentRunner` and roles and
  names no vendor, and the harness binary may appear only under `src/agl/adapters/openai/`
  (`scripts/check`'s containment gate). The only home is `OpenAiRunner.check_ready`, which is the
  adapter's readiness probe and fires for every run on that backend.
- **`check_ready` cannot see a role.** It takes a `ModelId`, so it cannot tell a run that asks
  questions from one that never will, and refusing the second over an asking mechanism it does not
  use is a false refusal. The member that *is* about asking is `capabilities()`, and the findings
  refuse to probe there by name: `_CAPABILITIES` is a frozen constant because "probing at preflight
  would make the answer depend on whether a network was up when it was asked".
- **It answers a narrower question than the one at stake.** It catches assumption 1 and is silent on
  2 and 3 — and 3 is the collision §3.7 actually names.
- **Its refusal is not one an operator can act on.** `AgentRunner.check_ready` asks for "a reason a
  person can act on — the harness is not on `PATH`, its version is too old, the session is not
  authenticated". "Your `codex` no longer parses a key AGL sends" is fixed by a released AGL, not by
  anything on their machine. It is drift detection, and drift detection belongs in a pass a human
  runs once — which is this file.

---

## Steps 2 and 7 — Entry 15: Whether both harnesses accept a payload schema carrying `title`

**Raised by:** stage 13 — 13.0(iii): `_object_schema` in `src/agl/sdk/tools.py`. The crossing is
`ports.agent.Tool.payload_schema`, and the two places it lands are
`src/agl/adapters/claude_code/_tools.py::_schema` and
`src/agl/adapters/openai/_tools.py::_advertised`.

**This entry is free on Claude Code and paid on Codex, and the two halves are two steps apart.**

- **Step 2 — the Claude half. Free, no model, no tokens; needs an installed `claude`.** Registration
  happens before any model call, so a rejected schema is visible without paying for one.
- **Step 7 — the Codex half. Costs nothing extra: it rides on entry 12's run.** There is no free
  instrument on that backend, and the acceptance point is a real `codex exec` start-up — which is
  exactly what entry 12 already pays for. **Do not spend a second turn on it.**

**Assumed.** That both vendors accept a derived payload schema carrying a JSON Schema `title`.
13.0(iii) writes `f"{module}.{qualname}"` into every payload schema **at every depth**, so that two
structurally identical payload types stop fingerprinting identically: `base_of` hashes a tool's
name, its description and its schema and nothing else, and `Tool` is a **port** type that must not
learn what a reporting tool's payload class is, so the schema is the one term the identity can
travel in. That schema is then handed straight across the port to both adapters and on to the
vendor. `title` was chosen over `$id` and `description` precisely because it is a standard
*annotation* keyword with no validating behaviour in any draft — no validator can reject a payload
over it and no backend has to be told about it — so the expectation is that both accept it without
comment. **Neither has been asked.**

**Already covered, free — and the gap in it is exact, which is what makes this cheap.**

- **The framework's half is settled three ways.** Two payload types of one shape derive two schemas
  and two fingerprints
  (`test_two_payload_types_of_one_shape_are_two_schemas_and_two_fingerprints`); a *nested* type's
  name is a term too, built under one outer name so that tagging only the outermost fails the test
  (`test_a_nested_payload_types_name_is_a_term_too_and_not_only_the_outermost`); and the name is the
  qualified one, so two classes both spelled `Payload` in two scopes are two types
  (`test_the_name_in_a_title_is_the_qualified_one_and_not_the_bare_class_name`). All in
  `tests/sdk/test_tools.py`.
- **Neither adapter rewrites it.** Both crossings only `setdefault` `type` and `properties` onto a
  copy — nothing is stripped, renamed or validated — and on the Codex side that is asserted rather
  than merely read off the source: the `inputSchema` a client reads off `tools/list` **is**
  `dict(tool.payload_schema)`,
  "nothing here is entitled to rewrite it"
  (`tests/adapters/test_openai_runner.py::test_a_tools_schema_reaches_the_model_as_the_workflow_declared_it`).
- **The fixture gap this entry was written around is closed, and that changes what is left to do.**
  When this entry was raised, the only tool the contract suite and both adapter suites ever declared
  was `Notes`, whose `_NOTE_SCHEMA` in `tests/contracts/_agent_tasks.py` is **hand-written** and
  carried no `title` — reasonably, since it was written before 13.0(iii) existed and a suite about a
  port has no business deriving one. So every free measurement of a tool reaching a real harness had
  been taken on a schema that did not exercise this: "not a missing instrument, a missing line in a
  fixture". **19.7 added that line**, permanently rather than as preparation to revert, and pointed
  two free assertions at it — one per adapter, both on every `scripts/check`, both with no CLI, no
  credential and no model:
  - `tests/adapters/test_claude_code_runner.py::test_a_tools_schema_reaches_the_wire_as_the_workflow_declared_it`
    reads the advertised `inputSchema` off the real in-process MCP server through a scripted
    transport, and asserts it **is** `dict(tool.payload_schema)` — annotation included;
  - `tests/adapters/test_openai_runner.py::test_a_tools_schema_reaches_the_model_as_the_workflow_declared_it`
    already asserted the same identity over real HTTP, and now carries a guard that fails loudly if
    the fixture ever stops carrying a `title`, rather than quietly becoming vacuous again.

  **So AGL's whole side of both crossings is now settled for free.** What is left is only the thing
  no free instrument on either backend can reach: *a vendor* accepting the annotation.

**Command — STEP 2, the Claude half. Free, no model, no tokens; needs an installed `claude` and
nothing else.** The init message a session emits when it opens lists registered tools by name
**before any model call**, so a harness that rejected the schema would fail at registration and be
visible with no paid turn. No preparation any more — `_NOTE_SCHEMA` carries the annotation, so this
is one command against the session-scoped loopback:

```bash
AGL_LIVE_AGENT=1 .venv/bin/pytest "tests/adapters/test_claude_code_runner.py::test_the_tools_a_task_carries_are_registered_and_the_denied_ones_are_gone"
```

**What a pass looks like.** The test passes rather than skipping. A **skip** is not a pass here and
means the CLI is not on `PATH` — the whole step is unrun, and the skip reason says which gate stopped
it. A pass means the SDK's in-process MCP server and the CLI both accepted the annotation and the
tool is registered under `mcp__agl__record_note`.

**Then read the annotation in the bytes that left, in the same free run, because registration is the
weaker of the two claims.** `harness.composed()` gives the request the CLI actually sent, and
`test_the_composed_request_carries_the_asking_tool_with_a_usable_schema` is the shape to copy: spawn
with `tools=(notes.tool,)`, build the same `offered` mapping off `composed.get("tools", [])`, and
print `offered["mcp__agl__record_note"]["input_schema"]`. **What a pass looks like:** a `title` key
in that printed dict, spelled `tests.contracts._agent_tasks.Note`. That is the annotation surviving
start-up, MCP enumeration, and the fold into the API's own `input_schema` spelling — three places it
could have been dropped without registration noticing.

**Command, Codex — there is no free instrument, and the findings say why.** State this rather than
reaching for the obvious wrong thing:

- **`codex debug prompt-input` cannot answer it.** It renders the model-visible prompt input list —
  developer and user messages — and **not the tool list** (`docs/codex-cli-findings.md` §0, restated
  in §3 and §6). It is the instrument most of that document rests on and it is silent here.
- **`codex mcp list` and `codex mcp get` report configuration, not a connection.** The installed
  binary's own `--help` calls `--json` "Output the configured servers as JSON" and "Output the
  server configuration as JSON" respectively; a server declared as `command="/bin/echo"` comes back
  configured (§0), so nothing there has spoken MCP to anything.
- **The nearest free evidence is entry 12's, and it is about the dialect rather than about this
  client.** `claude mcp add --transport http --scope local … && claude mcp list` against a live
  `_tools.Supply` performs a real `tools/list` and reported `✔ Connected`. Declaring that supply's
  tool through `reporting_tool` rather than by hand would put a `title`-carrying schema through a
  production MCP client for free — which is worth doing, and is a different vendor's client.

**Command — STEP 7, the Codex half. Paid, but it costs no extra turn: it rides on entry 12's run.**
The acceptance point for Codex is a real `codex exec` start-up, which is what entry 12 already pays
for. **Do not spend a second turn on it: run it as step 7.** In entry 12's command, replace the
hand-built `Tool(...)` with the derived declaration, leaving everything else as it stands:

```python
from dataclasses import dataclass
from agl.sdk.tools import reporting_tool

@dataclass(frozen=True)
class Note:
    note: str

declared = reporting_tool('record_note', 'Write down one note about what you found. Call it once.', Note)
tool = Tool(name=declared.name, description=declared.description,
            payload_schema=declared.payload_schema, handler=note)
```

**What a pass looks like.** The run reaches the model at all — that is the whole of it, because
registration happens at start-up. Entry 12 already reads the two outcomes this needs apart: a run
that fails at **start-up**, the harness reporting it could not initialise the server, is a rejected
schema and is *this* half failing; a run that completes without calling the tool is entry 9's
question and not this one. A payload in `PAYLOADS` is a pass here twice over, since the tool was
both advertised and callable.

**If it is wrong.** A reporting tool that fails to register is **a step whose agent can never
report**. §3.3 is explicit about what that costs: "If the agent returns without firing it, there is
no result and the step re-runs" — which the framework now raises automatically as
`RoleIncompleteError` — so every reporting step in every workflow pays for an agent, gets nothing,
records nothing, and re-runs on the next resume, forever. It is not a degradation: reporting steps
are how every value in this design gets into the ledger.

**The repair is genuinely awkward, and that is the reason this is worth the two minutes it costs.**
The identity has to stay in the fingerprint and stop reaching the vendor, and those are the same
term: `base_of` hashes exactly `name`, `description` and `payload_schema`, and giving `Tool` a
fourth field naming a payload class is `ports/agent.py` learning what a reporting tool is, which
§3.3 spends a paragraph forbidding and `_object_schema`'s docstring refuses by name. What is left is
to **strip `title` in each adapter on the way out** — two lines, no port change, the fingerprint
untouched — and it should be recorded as a trade rather than as a fix, because it makes the schema
the model is shown differ from the schema that was hashed. That is the same class of drift
`steps.py` refuses for the inputs block, arrived at from the other direction, and a later reader
should find the two arguments together.

**One softer question rides along on the same run and costs nothing extra.** `title` reaching the
model is deliberate — `_object_schema` calls it "acceptable and arguably useful", on the grounds
that the model is told the name of the thing it is filling in. Whether a model handed
`workflows.tickets.models.Findings` in its payload schema does anything odd with it — narrates it,
treats it as a field, refuses it as unfamiliar — is not something anybody has watched. Note anything
strange; a rewrite to a friendlier value is a **stored format** change and re-runs the ledger, so it
is worth knowing before somebody proposes one.

---

## Step 3 — Entry 7: `AskUserQuestion` is vacuous on the CLI version measured

**Raised by:** stage 7.1 — `ASKING_MECHANISMS_DENIED` in
`src/agl/adapters/claude_code/_tools.py`.

**This entry is free** — no model, no tokens, no credential. It needs an **installed `claude`** and
nothing else, which is the only reason it is not in the automated suite. It is a **re-check on a CLI
upgrade** rather than a one-time measurement: run it in this pass, and run it again whenever
`claude --version` moves.

**Assumed.** The adapter denies Claude Code's own `AskUserQuestion` for **every** run, so that an
agent has exactly one way to ask and it is the way that reaches `on_question`. Measured this stage:
**removing it from the deny list changes nothing**, because the CLI measured does not offer that
tool to an SDK session at all — a live probe with no deny rules read the session's registered tool
list off `init` and `AskUserQuestion` was absent, on a machine whose environment even carried
`CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL`. So the assertion that it is not registered is true
today whether or not the deny rule exists.

The rule is kept anyway, as a guard against a future version, and is therefore pinned where it
**can** actually fail: on `options.disallowed_tools`
(`test_the_options_the_run_actually_built_are_the_hermetic_ones`), rather than only on the
registered tool list, where it would be a tautology.

**Version note, resolved.** The two numbers in the tree are both real and were measured from
different instruments: `claude --version` reports **2.1.220** for the packaged binary (the only
version on disk — `/opt/homebrew/bin/claude` → `Caskroom/claude-code/2.1.220`), which is what
`translate.py` and `tests/instruments/loopback.py` cite, while the *running session* announces
**2.1.235** in `init`'s `claude_code_version` and on its `claude-cli/2.1.235` User-Agent, which is
what `_tools.py` cites — Claude Code updates its own bundle in place, so the packaged and running
versions have drifted apart. Neither is a typo, and a later `--version` disagreeing with
`init.claude_code_version` is that same drift rather than a behaviour change.

**Command.** Preparation: temporarily set `ASKING_MECHANISMS_DENIED = ()` in
`src/agl/adapters/claude_code/_tools.py`. Then:

```bash
AGL_LIVE_AGENT=1 .venv/bin/pytest "tests/adapters/test_claude_code_runner.py::test_the_tools_a_task_carries_are_registered_and_the_denied_ones_are_gone"
```

**What a pass looks like — and here both outcomes are acceptable, which is unusual, so read them
apart rather than looking for green.**

- **Still passing** means the CLI still does not offer the tool and the deny rule is still vacuous.
  Nothing to do; record the version it was true at.
- **Failing on `AskUserQuestion`** means the CLI has started offering it and the deny rule is now
  doing real work — which is the *good* outcome, because it means the guard is live and the
  assertion has teeth again. Record it and leave the deny rule exactly where it is.
- **Skipping** is the one non-answer: the CLI is not on `PATH` and the step is unrun.

Revert the edit either way.

**If it is wrong.** If a later CLI starts offering `AskUserQuestion` to SDK sessions *and* the deny
rule has drifted or been removed as dead weight, a model gets two asking mechanisms and one of them
talks to nobody. In a run with no interactive front end that is **a question waiting on an answer
that cannot arrive** — which §3.7 calls the worst outcome available, because there are no timeouts,
an unanswered question blocks its step indefinitely, and from outside "stuck" and "waiting for you"
look exactly alike. It looks precisely like work.

There is a second reason the deny is not negotiable, and it survives whatever the version does:
`AskUserQuestion` is unavailable to a subagent (§1.1), which is the vendor limitation that once
reshaped a workflow's concurrency. AGL's own asking tool is an MCP tool registered for the session,
so a `Task` subagent can call it — an adapter that adopted the built-in mechanism would inherit the
workaround along with it.

---

## Step 4 — Entry 11: Codex's remaining configuration channels

**Raised by:** stage 8.0 — `docs/codex-cli-findings.md` §6.

**This entry is free.** No model, no tokens, no credential — `CODEX_HOME` is emptied and
`codex debug prompt-input` contacts nothing. It needs an **installed `codex`** and nothing else,
which is the only reason it is not in the automated suite.

**Assumed.** That the two overrides this adapter emits still bound what a *repository* can
contribute, and that the channels stage 8.0 measured inert are still inert. Concretely: that
`project_doc_max_bytes=0` still disables the `AGENTS.md` mechanism rather than merely capping it,
that `skills.include_instructions=false` still removes every skill, and that a repository's own
`.codex/config.toml` still cannot configure Codex. Under all three sits §3.5's claim — the target
repo contributes source code and nothing else — and none of the three is promised by published
documentation, which is why they are re-checked rather than trusted.

**Two of the three parts are a re-check on a version bump** rather than a one-time measurement, and
the third cannot be run at all — see the command.

**What was measured at stage 8.0, and is settled.** Against a poisoned fixture repository, using
`codex debug prompt-input` — which renders the model-visible prompt as JSON and contacts no model —
`-c project_doc_max_bytes=0` removes every `AGENTS.md` the repository contributes at every depth
including `AGENTS.override.md`, and `-c skills.include_instructions=false` removes every skill. With
both applied, **the only marker still reaching the model is the operator's own
`$CODEX_HOME/AGENTS.md`.** That is §3.5's claim and it holds.

**Three things that are not settled.**

1. **Whether `--ignore-user-config` also suppresses `$CODEX_HOME/AGENTS.md`.** It could not be
   measured, because `codex debug prompt-input` does not take that flag; its own help says only that
   it skips `$CODEX_HOME/config.toml` and that auth still uses `CODEX_HOME`. Every other free
   candidate was tried and failed: `developer_instructions=""`, `include_environment_context=false`
   and `project_doc_fallback_filenames=[]` all leave the marker in place.
2. **`project_doc_max_bytes = 0` is measured, not documented.** The published documentation
   discusses only *raising* the cap. `0` is schema-legal and demonstrably disables the mechanism on
   0.149.0, but nobody has promised it will keep doing so.
3. **The repository's own `.codex/config.toml` was measured inert and is documented as a real
   layer.** Three instruments agree it does nothing on 0.149.0 — a `model` set there leaves
   `codex doctor --json` reporting `<default>`, an `mcp_servers` entry leaves `codex mcp list`
   empty, and a `project_doc_max_bytes = 0` there changes nothing — under **both** trust levels
   forced with `-c 'projects."<path>".trust_level=…'`. The documentation describes exactly such a
   layer, gated on project trust. Either the gate is something the fixture did not satisfy, or the
   layer is not in this build.

**Command. Item 1 cannot be run and this pass does not attempt it — read this before looking for a
way.** It was written against "8.2's Codex loopback", and **8.2 built no loopback** (entry 13
records the decision). It needs a real `codex exec` whose request can be read, which is free only
against a loopback that does not exist and must **not** be run against the real endpoint — a paid
turn would not answer it either, since the thing to inspect is the request rather than the reply.
So item 1 stays open, and it stays open harmlessly: it is the operator channel §3.11 puts out of
scope, exactly where Claude Code's line falls too (entry 6, at step 5). **Skip it.** What it would
have taken, if somebody builds that loopback later:

```bash
# In 8.2's own test module, with the loopback bound and CODEX_HOME emptied, add --ignore-user-config
# to the composed argv and grep the request that arrives for the marker planted in $CODEX_HOME/AGENTS.md.
```

**Items 2 and 3 are what this step actually runs.** Free, a few seconds, and a version re-check —
so run them here and again wherever `codex --version` is next observed to have moved:

```bash
codex --version
cd "$(mktemp -d)" && git init -q . \
  && printf 'AGL_RECHECK_AGENTS\n' > AGENTS.md \
  && printf 'model = "gpt-5.4"\n' > .codex/config.toml \
  && codex debug prompt-input -c project_doc_max_bytes=0 X | grep -c AGL_RECHECK_AGENTS
codex doctor --json | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['checks']['config.load']['details'])"
```

**What a pass looks like.** Two literal readings, and item 1 contributes nothing to either:

- **Item 2 passes** when the first command prints `0` — no occurrence of `AGL_RECHECK_AGENTS` in the
  rendered prompt, so `project_doc_max_bytes=0` still disables the mechanism. Any number above zero
  is a failure and is the serious one of the two.
- **Item 3 passes** when `codex doctor --json` still reports `model: "<default>"` and a single
  `config.toml` path under `$CODEX_HOME` — the repository's own `.codex/config.toml` still cannot
  configure Codex. A `gpt-5.4` there, or a second path, is the layer having activated.

Record `codex --version` beside whichever way they came out; that is what makes the next re-check
readable.

**If it is wrong.**

- **1 failing changes nothing and is not filed.** `$CODEX_HOME/AGENTS.md` surviving is the operator
  channel §3.11 puts out of scope — "v1.1 inherits the parent environment" — and it is *exactly*
  where Claude Code's line falls too (entry 6). It is recorded so that the next reader of the Codex
  adapter's options knows the overrides bound the **repository** and not the **machine**.
- **2 failing means the repository's `AGENTS.md` is reaching the model again**, which is §3.5's
  claim failing outright. The contract suite's poisoned-repository clause should catch it, which is
  the argument for keeping that clause pointed at the real adapter.
- **3 failing is the one that would matter**, and it has no flag behind it: `--ignore-user-config`
  closes `$CODEX_HOME/config.toml` and `--ignore-rules` closes `.rules`, but **nothing closes a
  project `.codex/config.toml` or a project `.codex/hooks/`**. If that layer ever activates, a
  target repository could contribute configuration and hooks AGL cannot turn off. Two structural
  mitigations already exist and should be checked before anything is built: AGL's workspaces are
  fresh worktrees at fresh paths (§3.9), so they are untrusted by default and the layer is skipped;
  and project-local config is documented as unable to override provider and auth keys, so a
  repository can never redirect the endpoint.

---

## Step 5 — Entry 6: The operator's own machine configuration reaches the session

**Raised by:** stage 7.1 —
`tests/adapters/test_claude_code_runner.py::test_no_configuration_in_the_workspace_reaches_the_session_it_composes`.

**This entry is free.** No model, no tokens, no credential — the CLI is pointed at the loopback. It
needs an **installed `claude`** *and* **a plain shell outside any Claude Code session**, which is
the whole reason it cannot be automated: no test can guarantee the shell it was launched from. It is
here because the measurement needs a shell nobody has run it from, not because it needs a paid turn.

**What was measured this stage, and is now verified for free.** With `setting_sources=[]` and
`strict_mcp_config=True`, the **target repository contributes nothing**: its `CLAUDE.md`, its
`.claude/agents/`, its `.claude/commands/` and its `.mcp.json` are all absent from the session the
CLI reports opening, and the session's MCP servers are exactly `["agl", "agl_ask"]`. That is §3.5's
claim — "the target repo contributes source code and nothing else" — and it holds.

**What was also measured, and is the fact nobody had written down.** `init.agents`,
`init.slash_commands` and `init.skills` come back **non-empty**, carrying the *operator's own*
machine-level subagents, commands and skills. §3.11 puts the inherited environment out of scope for
v1.1 deliberately — "v1.1 inherits the parent environment" — so this is **not a defect**. But a
reader of `setting_sources=[]` would reasonably assume otherwise, and the test asserts only that
the three *planted* names are absent for exactly this reason: `assert not announced["agents"]`
would be asserting something §3.5 never said, against a value that changes with whoever runs the
suite.

**Assumed, and this is the part to settle.** That those three lists are non-empty because of
**settings discovery**, and not because the measurement was taken from a test process that was
itself running inside a Claude Code session — a spawned CLI inherits an environment, and the two
explanations are indistinguishable from inside one.

**Command.** From a **plain shell, outside any Claude Code session** — that is the whole of what
distinguishes the two explanations, and it is why this deserves a line of its own. Preparation: in
`test_no_configuration_in_the_workspace_reaches_the_session_it_composes`, add one line after
`announced = watched.init()`:

```python
print({key: announced.get(key) for key in ("agents", "slash_commands", "skills")})
```

Then:

```bash
AGL_LIVE_AGENT=1 .venv/bin/pytest -s "tests/adapters/test_claude_code_runner.py::test_no_configuration_in_the_workspace_reaches_the_session_it_composes"
```

**What a pass looks like — this step answers a question rather than passing or failing, and the
answer is which of two explanations is true.** Run it twice, once from a plain shell and once from
inside a Claude Code session, and compare the three printed lists:

- **Identical** → it is **settings discovery**. This is the expected outcome. Nothing breaks and
  nothing is filed; record it, and see "If it is wrong" for what it is recorded *for*.
- **The plain shell's are empty or smaller** → the difference was **inherited environment**, and the
  fact this entry records was measured from inside a session and is not what it looked like.

The test itself passing is not the reading — it passes either way. The printed lists are.
Revert the print afterwards.

**If it is wrong** — that is, if the lists are non-empty from a plain shell too, which is the
expected outcome — nothing breaks and nothing is filed. It is recorded so that the next reader of
`options.py` knows that `setting_sources=[]` bounds the **repository** and not the **machine**, and
so that §3.11's "credential-environment isolation, not built" is understood to cover this too. The
consequence only becomes real the day AGL runs somewhere the operator does not control the shell,
which §3.11 names as the revisit condition.

---

## Steps 6 and 17 — Entry 5: Whether the Claude Code CLI is authenticated

**Raised by:** stage 7.1 — `check_ready` and `_READY_PROMPT` in
`src/agl/adapters/claude_code/runner.py`.

**This entry has two branches and they sit at opposite ends of the pass, because they need opposite
machines.** Nothing else in this file needs the machine logged *out*.

- **Step 6 — the returning branch. Paid, one turn, and it is the cheapest turn in the file.** Run it
  **first among the paid steps**: it is the gate on every Claude step below (9, 11, 13, half of 14,
  and 15), the same way entry 12 is the gate on the Codex ones. If this refuses you are logged out
  and nothing else on that backend is readable.
- **Step 17 — the refusing branch. Costs no tokens** (the probe never reaches a model), **but needs
  a logged-out machine** — which is why it is last. Do it after everything else is finished, then
  log back in.

**Do not read "the free branch" as "free of tokens" here.** Step 6 spends a real turn by design; it
is the *first* branch, not the free one. Step 17 is the one that spends nothing.

**Assumed.** Nothing, and that is the point of this entry: **there is no free instrument for
authentication state**, and the stage measured why. `init`'s `apiKeySource` reports `"none"` for a
perfectly good subscription session (recorded in the comment above `_READY_PROMPT`), and the CLI's
`init` message is byte-identical whether the far side authenticates or refuses. So nothing short of
asking the far side distinguishes logged in from logged out.

`check_ready` therefore **costs one real turn, by design** — no tools, no system prompt, a one-word
reply, a composed request measuring about 1 KB, so a few hundred tokens in and a handful out. §3.2's
first preflight check pays it **once per provider per run**, to kill a Claude+OpenAI run at second
zero on a logged-out session rather than forty minutes in at the review step.

**Consequence worth writing down.** The `AGL_LIVE_AGENT=1` gate on
`tests/adapters/test_claude_code_runner.py` means exactly two things — **the CLI is installed and
the operator opted in to having processes started on this machine** — and deliberately claims
nothing about authentication. It cannot: the two facts a free instrument can see are unrelated to
the third. The skip reasons in that module say so and claim no more.

**Already covered, free.** The **returning** branch of `check_ready` — the one where nothing is
wrong — is now exercised on every `scripts/check`, against the loopback, and it is checked
non-vacuously: the readiness probe is read back off the wire afterwards, so a `check_ready` that
returned by doing nothing would fail (`test_check_ready_returns_against_a_harness_that_answers`).
That branch had never been observed before this stage, because the machine the adapter was written
on was logged out.

**The untested half is the refusing branch against a genuinely logged-out machine.** What exists is
`translate.unready` as a unit, parametrised over all seven SDK exception classes and asserting
`UpstreamUnavailable` with a non-empty message for every one
(`tests/adapters/test_claude_code_translate.py::TestVendorExceptions::test_a_readiness_probe_always_answers_unavailable`),
plus the run path's error-result translation through a scripted transport. Nothing has watched a
real logged-out CLI go through `check_ready`. **A 401 loopback is not a substitute**: a loopback
answering 401 puts the CLI into a ten-attempt exponential backoff costing **3 min 09 s per run**,
measured — which is why `tests/instruments/loopback.py` has no refusal mode at all.

**Command — STEP 6, the returning branch. Paid, one turn, a few hundred tokens.** On the machine as
it stands, with the loopback's variables unset — this is the only branch that can be checked without
arranging the answer in advance:

```bash
env -u ANTHROPIC_BASE_URL -u ANTHROPIC_API_KEY .venv/bin/python -c "
import asyncio
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.ports.agent import Claude
asyncio.run(ClaudeCodeRunner().check_ready(Claude.HAIKU))
print('READY')
"
```

**What a pass looks like.** The literal word `READY` on standard output, and nothing else. Any
exception here means this machine is not authenticated: **stop, fix that, and do not run steps 9,
11, 13, 14 or 15 until it prints `READY`** — they would all fail for this reason rather than their
own. An `UpstreamUnavailable` naming authentication is step 17's *pass*, arriving at the wrong step.

**Command — STEP 17, the refusing branch. No tokens, but it needs the machine logged out, so do it
last.** Run `claude /logout` first, or run the same command as a user with no Claude Code session,
and read the refusal:

```bash
env -u ANTHROPIC_BASE_URL -u ANTHROPIC_API_KEY .venv/bin/python -c "
import asyncio
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.ports.agent import Claude
from agl.ports.errors import UpstreamUnavailable
try:
    asyncio.run(ClaudeCodeRunner().check_ready(Claude.HAIKU))
except UpstreamUnavailable as refusal:
    print('REFUSED:', refusal)
"
```

**What a pass looks like.** The line `REFUSED:` followed by a message that **names authentication**
— so that a person reading it knows which of *installed*, *current* and *authenticated* failed. Two
distinct failures to watch for, and they are not the same finding: a **traceback** (any other
exception class escaped, which is the exit-70 dead end below), or `REFUSED:` followed by an **empty
or uninformative message** (the right class, useless content — the same dead end more quietly).

**Log back in afterwards.** This is the last step; the pass is over when the CLI is authenticated
again.

**If it is wrong.** `check_ready`'s one legal refusal is `UpstreamUnavailable`, and §3.2's first
preflight check catches that class and nothing else. Any other exception escaping a logged-out
probe reaches the top of the CLI as **exit 70** and tells a person to file a bug about their own
logged-out session — which is precisely the outcome the port member exists to prevent, and the
reason `tests/contracts/_agent_preflight.py` fails an adapter that raises anything else by name. A
refusal with an empty or unhelpful message is the same dead end more quietly: preflight fires at
second zero so that somebody can fix the world and start again, and a message that does not say
which of *installed*, *current* and *authenticated* failed leaves them guessing.

---

## Step 7 — Entry 12: Whether this harness's own MCP client accepts the server AGL runs for it

**Raised by:** stage 8.2 — `src/agl/adapters/openai/_http.py` and `_tools.py`.

**This entry exists because entry 9 assumed something 8.2 did not deliver.** Entry 9 says
"everything in 1 and 2 above is settleable for free by 8.2's loopback"; **8.2 built no loopback**
(entry 13 records that decision and its cost), so the MCP round trip is unsettled at a lower layer
than entry 9 is written at. Entry 9 asks whether a *model* calls a tool. This asks whether the
harness's MCP client can talk to AGL's server at all — and if the answer is no, entry 9 cannot even
be attempted.

**Assumed.** That the harness's MCP client accepts four choices `_http.py` made, none of which its
own client has ever exercised:

1. **A single `application/json` response** to a `POST`, rather than `text/event-stream`. The
   specification permits both and this server always chooses the first.
2. **No `Mcp-Session-Id`.** The specification makes assigning one optional and this server does not.
3. **`405` on `GET`**, which is how a server says it offers no server-to-client stream.
4. **An echoed `protocolVersion`** — whatever the client proposed is what it gets back.

**Already covered, free — and it is more than nothing.**

- **A production MCP client from a different vendor connected to both servers and listed their
  tools.** Measured: `claude mcp add --transport http --scope local … && claude mcp list` against a
  live `_tools.Supply`, on Claude Code 2.1.220, reported `✔ Connected` for `agl` and for `agl_ask`.
  The request log shows the whole handshake — `HEAD`, `initialize`, `notifications/initialized`, a
  `GET` refused with 405, `tools/list` — with the client proposing `2025-11-25`. That is evidence
  about the *dialect* rather than about one implementation, which is exactly what makes it worth
  more than a self-test.
- **The configuration reaches the harness.** `codex mcp list --json` with the adapter's own
  override — both servers, the token-carrying URL, `tool_timeout_sec=86400`,
  `startup_timeout_sec=30`, `default_tools_approval_mode="auto"` — comes back as two configured
  `streamable_http` servers. A value its loader dislikes is refused by name (measured: a bogus
  approval mode names the four it accepts), so acceptance here is a real check and not a shrug.
- **`codex doctor` sends a bare `HEAD`** at a configured server's URL, which is why this server
  answers `HEAD` rather than letting it fall through to the 405 every other verb gets.
- **The whole tool path is exercised on every `scripts/check`** — `tests/adapters/`
  `test_openai_runner.py` drives the real server over real HTTP from a stub CLI that finds the
  address on its own command line. What that cannot be is *this vendor's client*.

**Command.** On an authenticated machine, in a scratch git repository. This is the cheapest paid
check in the file — one turn, one tool call — and it should be run **before** entry 9, because
entry 9's failure modes are unreadable until this one has passed:

```bash
.venv/bin/python -c "
import asyncio
from pathlib import Path
from agl.adapters.openai.runner import OpenAiRunner
from agl.ports.agent import AgentTask, OpenAI, Tool, ToolResult

seen = []

async def note(payload):
    seen.append(dict(payload))
    return ToolResult(text='Noted. Nothing else is needed from this tool.')

tool = Tool(
    name='record_note',
    description='Write down one note about what you found. Call it once.',
    payload_schema={'type': 'object', 'properties': {'note': {'type': 'string'}},
                    'required': ['note']},
    handler=note,
)
task = AgentTask(
    instructions='Call the record_note tool once with a note saying what this directory holds, '
                 'then reply with the single word: done',
    workspace=Path.cwd(),
    model=OpenAI.LUNA,
    restrictions=frozenset(),
    tools=(tool,),
)
print('OUTCOME:', asyncio.run(OpenAiRunner().run(task, on_activity=print)))
print('PAYLOADS:', seen)
"
```

**What a pass looks like.** Two things, both read off the printed output: a payload in `PAYLOADS`,
and `Calling: agl/record_note` among the activity lines. A run that fails at **startup** — the
harness reporting it could not initialise the server — is this entry failing; a run that completes
without calling the tool is entry 9's question (step 8), not this one.

**Two other things this same run settles, and it is the first paid run in the file, so read them
before blaming the model.**

- **That the prompt arrived at all.** The adapter passes `-` as the prompt argument and writes the
  instructions to standard input, on the strength of the installed binary's own `--help`: "if not
  provided as an argument (or if `-` is used), instructions are read from stdin". Nothing free can
  check it. If that reading is wrong the agent is handed the literal string `-` and does something
  unrelated to the task — which looks exactly like a model ignoring its instructions, and is not.
- **That the event stream is JSON and only JSON.** `_session.py` raises `UpstreamUnexpected` on a
  standard-output line it cannot parse, which is what the stage asked for and what
  `translate.unreadable` exists for. If this harness prints anything else on that stream under
  `--json` — a version notice, a banner, the final message in prose — **every run dies** with "the
  Codex CLI printed a line on its event stream that AGL cannot read", quoting the line. That
  message names its own fix: one branch in `_session._frame` to ignore a non-JSON line rather than
  raise on it. Record the line verbatim if it happens.

**If it is wrong.** The fix is in `_http.py` and never in the port, and the four assumptions fail
distinguishably:

- **Streaming required** — the harness rejects the `application/json` reply. `_http.py` writes one
  SSE event carrying the same JSON body instead. Perhaps twenty lines, and the shape is already
  measured on the client that does accept `application/json`, so nothing is lost by doing both.
- **A session id required** — the harness refuses the second request. `initialize` returns an
  `Mcp-Session-Id` header and later requests are checked against it.
- **The `GET` refusal fatal** — a client that treats 405 as an error rather than as "no stream".
  Then the server has to hold an open SSE stream per session, which is the largest of the four
  fixes and the only one that changes `_http.py`'s shape.
- **The echoed version refused** — answer with `2025-06-18` unconditionally.

Underneath all four: `TOOL_CALLING` and `MID_RUN_QUESTIONS` rest on this one mechanism, so a
failure that cannot be fixed takes both members out of `_CAPABILITIES`, and every workflow with a
reporting step (§3.3) is then routed to the other backend or does not run.

---

## Step 8 — Entry 9: A live Codex agent calling an AGL-supplied MCP tool, and asking through it

**Raised by:** stage 8.0 — `docs/codex-cli-findings.md` §0 and §4. **This is stage 8's counterpart to
entry 2 and it is the serious one**: for Codex, `TOOL_CALLING` and `MID_RUN_QUESTIONS` rest on the
same single mechanism, so one failure takes both.

**Assumed.** Three things, and they are worth separating because they fail differently:

1. That a `codex exec` session **starts** the MCP server AGL configured through `-c` and lists its
   tools to the model, under the name `mcp__agl__<tool>`.
2. That the model **calls** one, and that the handler's `ToolResult.text` gets back into the same
   session so the agent can act on it — §3.3's whole reporting mechanism.
3. That a call which **blocks for minutes** — an asking tool waiting on a person — survives.
   `mcp_servers.<id>.tool_timeout_sec` **defaults to 60 seconds**, and 8.2 is expected to raise it.
   What Codex does when a tool call does time out (returns an error to the model, or aborts the
   turn) is not established and matters: the first is a degraded run, the second is a dead one.

**Already covered, free — and the boundary is different from entry 2's.** Stage 8.0 established
without a model that MCP servers can be declared entirely on the command line, in both transports,
with no file on disk:

```bash
codex mcp list --json -c 'mcp_servers.agl={url="http://127.0.0.1:8765/mcp",tool_timeout_sec=600}'
```

and that `default_tools_approval_mode`, `enabled_tools` and `disabled_tools` are accepted keys. It
also established, from the binary and from `codex-rs/exec/src/lib.rs`, that Codex's **own** asking
mechanisms are dead in exec mode — `request_user_input is not supported in exec mode`, MCP
elicitation auto-cancelled, all seven approval paths rejected — which is why AGL's own MCP tool is
the only route and why this entry has no fallback.

**Everything in 1 and 2 above is settleable for free by 8.2's loopback** — the tool list is in the
composed request, and a scripted reply can make the "model" call the tool. What is left for a person
is the same pair entry 2 leaves: that a *live* agent asks rather than answering around the question,
and that the answer changes what it does next. **Item 3 is the one a loopback cannot fake**, because
a loopback does not wait.

**`capabilities()` reports `MID_RUN_QUESTIONS` on the mechanism being present, not on model
cooperation** — the same reading entry 2 fixed for Claude, and it should be read the same way for
both or the word means two things.

**Command.** On an authenticated machine, from a scratch git repository, with the same two halves as
entry 2 — did the handler get called, and did the answer land:

```bash
.venv/bin/python -c "
import asyncio
from pathlib import Path
from agl.adapters.openai.runner import OpenAiRunner
from agl.ports.agent import AgentTask, OpenAI
from agl.ports.questions import Answer, Question

asked = []

async def on_question(q: Question) -> Answer:
    asked.append(q)
    print('ASKED:', q.prompt, '| options:', q.options, '| free text:', q.allow_free_text)
    await asyncio.sleep(90)          # the 60s tool_timeout_sec is the point of this line
    return Answer(text='Call it agl_manual_qa_marker, exactly that.')

task = AgentTask(
    instructions=(
        'Create one empty file in this directory. You must not choose its name yourself: '
        'the name is the operator\'s decision, so ask them what to call it and use their answer.'
    ),
    workspace=Path.cwd(),
    model=OpenAI.LUNA,          # the cheap tier, as Claude.HAIKU is in entries 1-5
    restrictions=frozenset(),
    tools=(),
)
outcome = asyncio.run(OpenAiRunner().run(task, on_question=on_question))
print('OUTCOME:', outcome)
print('QUESTIONS ASKED:', len(asked))
"
```

**What a pass looks like.** Three things, and they map one-to-one onto the three assumptions above:
the handler was called (`QUESTIONS ASKED: 1` or more), the file on disk is named
`agl_manual_qa_marker`, and the **90-second sleep did not kill the call** — which is what proves
`tool_timeout_sec` was raised rather than merely intended. Drop the sleep and re-run if it fails, to
tell a timeout from a model that never asked; and read "The honest boundary" below before recording
a failure at all.

**If it is wrong.** Which of the three fails decides the damage, and only one of them is entry 2's.

- **Failure at 1 or 2 is the structural one and it is worse than entry 2's**, because
  `capabilities()` would be lying about `TOOL_CALLING` as well as `MID_RUN_QUESTIONS`. A reporting
  step (§3.3) could not work on this backend at all: the payload arrives by the agent calling a
  tool, and there is no second mechanism — `--output-schema` fires once at the end with no handler
  round trip, and the `DynamicToolSpec` channel is refused in exec mode. The honest response is to
  drop both members from `_CAPABILITIES`, at which point every workflow with a reporting step is
  routed to Claude or does not run.
- **Failure at 3 alone** leaves `TOOL_CALLING` true and makes `MID_RUN_QUESTIONS` a lie of a quieter
  kind: the tool exists, the agent calls it, and the call dies while a person is still reading the
  question. In a run with no interactive front end that is a negotiation that silently becomes a
  guess. Drop `MID_RUN_QUESTIONS` and raise the timeout; §3.2's third preflight check then refuses
  the roles that need it, which is the outcome the check exists for.
- **The honest boundary is entry 2's, verbatim.** Whether a particular prompt elicits a question is
  prompt engineering and belongs to the workflow. A model that solves the task without asking has
  not broken this contract. Record a failure when a question is asked and the answer does not come
  back, or when no wording gets the tool called at all.

---

## Step 9 — Entry 2: `on_question` end to end against a live agent

**Raised by:** stage 7.1 — `src/agl/adapters/claude_code/_tools.py` (the asking tool),
`src/agl/adapters/claude_code/runner.py` (`_MAY_ASK`, `_CAPABILITIES`).

**Assumed.** That a live Claude Code agent, told it may ask, **actually asks** through
`mcp__agl_ask__ask`, and that the answer returned into the same session changes what it then does.
This is §3.7's whole mid-run question path and the thing `Capability.MID_RUN_QUESTIONS` is supposed
to promise.

**Already covered, free — every part of this except the model's cooperation.** Say this out loud in
the pass, because the list is long and re-checking any of it by hand is a wasted turn:

- **The tool is registered.** `mcp__agl_ask__ask` appears in the tool list on the CLI's own `init`
  message, which arrives before any model call
  (`test_the_tools_a_task_carries_are_registered_and_the_denied_ones_are_gone`).
- **It reaches the composed request, with a schema a model could call.** Read off the request that
  actually left the machine: `input_schema` is an object, `question` is a required string,
  `options` is an array of strings, `allow_free_text` is a boolean
  (`test_the_composed_request_carries_the_asking_tool_with_a_usable_schema`). This is a different
  claim from the offline one — the MCP server has to be started, connected, enumerated, and its
  tools folded into the request under the API's `input_schema` spelling rather than MCP's
  `inputSchema` — which is why both tests exist.
- **The agent is told it may ask.** `_MAY_ASK` in `runner.py`, added this stage, and asserted
  through the loopback against the request that actually leaves: present when a handler was
  supplied, absent when none was, with `agl_ask` occurring exactly once (its own tool definition)
  on the run with no handler
  (`test_the_composed_request_names_the_asking_tool_when_somebody_can_answer`). This is the
  measurement `_MAY_ASK` exists because of: before it, the two requests were byte-identical, so the
  framework supplied the tool and instructed nobody.
- **The whole round trip, offline.** A vendor question payload maps to a `Question`, the handler is
  called, the `Answer` is serialised back into the same live session as an ordinary tool result,
  and a **second** question in the same run reaches the handler again
  (`test_two_questions_and_two_answers_inside_one_run`). Plus the degenerate paths: a question with
  no handler is answered at once and never waits, a question asking nothing is refused back into
  the conversation, and a handler that raises ends the run with its own exception. All through a
  scripted transport — no CLI, no model.

**What remains unverified.** Only two things, and they are the two a loopback cannot fake: that a
live agent *asks* through that tool rather than answering around the question, and that the answer
returning into the session changes what it does next.

**`capabilities()` reports `MID_RUN_QUESTIONS` on the mechanism being present, not on model
cooperation.** That is the honest reading of the flag and it should be read that way: `_CAPABILITIES`
in `runner.py` is a frozen constant, answered identically for every task on every machine, because
the port asks "what can you do" rather than "can you do it now" and requires the answer to be
stable for the duration of a run. The flag means AGL registered an asking tool and instructed the
agent to use it. It does not mean any model has been observed using it.

**Command.** On an authenticated machine, from a scratch directory:

```bash
.venv/bin/python -c "
import asyncio
from pathlib import Path
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.ports.agent import AgentTask, Claude
from agl.ports.questions import Answer, Question

asked = []

async def on_question(q: Question) -> Answer:
    asked.append(q)
    print('ASKED:', q.prompt, '| options:', q.options, '| free text:', q.allow_free_text)
    return Answer(text='Call it agl_manual_qa_marker, exactly that.')

task = AgentTask(
    instructions=(
        'Create one empty file in this directory. You must not choose its name yourself: '
        'the name is the operator\'s decision, so ask them what to call it and use their answer.'
    ),
    workspace=Path.cwd(),
    model=Claude.SONNET,
    restrictions=frozenset(),
    tools=(),
)
outcome = asyncio.run(ClaudeCodeRunner().run(task, on_question=on_question))
print('OUTCOME:', outcome)
print('QUESTIONS ASKED:', len(asked))
"
```

**What a pass looks like.** Two things: the handler was called at least once (`QUESTIONS ASKED: 1`
or more, and an `ASKED:` line printed), and the file on disk is named `agl_manual_qa_marker` — the
second is what proves the answer went back into the *same* session and was acted on, rather than the
agent asking and then ignoring the reply. Read "The honest boundary" below before recording a
failure: no question asked is not yet a failure, and the entry says exactly what is.

**If it is wrong.** This is the entry the stage was convened over, and the consequence is
structural rather than cosmetic.

- Every role declaring `on_question` would have to fail preflight against Claude. §3.2's **third**
  preflight check admits such a role only against a provider reporting `MID_RUN_QUESTIONS`, and
  `MID_RUN_QUESTIONS` would have to come out of `_CAPABILITIES` — which means every workflow that
  wants a human in the loop is routed to some other provider or does not run.
- Tickets' approval negotiation could not run on this backend at all. §3.7 puts propose, ask,
  revise, report **inside one step and one session** precisely so that a fresh session per round
  does not discard the reasoning behind the proposal; a workflow loop is explicitly not the
  fallback. There is no degraded mode here — the workflow "genuinely cannot run on a backend
  without it", in §3.7's words.

**The honest boundary, and the reason a single failure is not a verdict.** Whether a *particular
prompt* elicits a question is prompt engineering and belongs to the workflow, not to the adapter.
A model that solves the task without asking has not broken this contract. The adapter's obligation
is that **asking is possible** — the tool is there, the agent knows about it, a call reaches the
handler, and the answer gets back into the session. So if the command above produces no question,
sharpen the instructions and try again before recording a failure; record a failure when a question
is asked and the answer does not come back, or when no wording gets the tool called at all.

---

## Step 11 — Entry 3: `stop_reason` mapping against live outcomes

**Raised by:** stage 7.1 — `src/agl/adapters/claude_code/_session.py` (the three-field read) and
`src/agl/adapters/claude_code/translate.py` (exception translation).

**Assumed.** That a real Claude Code CLI emits the strings this adapter reads, **in the fields it
reads them in**, for the outcomes it maps them to: which real outcomes produce
`StopReason.COMPLETED`, which produce `StopReason.LIMIT`, and which produce `None`.

**Already covered, free.** The `STOPPED` table in
`tests/adapters/test_claude_code_runner.py` pins **every string the adapter claims to read**, in
thirteen rows driven through a scripted transport, including the precedence between fields — the
CLI's query loop outranks the model, so `terminal_reason="aborted_streaming"` with
`stop_reason="end_turn"` is `None` and not `COMPLETED`
(`test_why_a_run_stopped_is_read_off_three_fields_and_may_be_none`). So **the mapping is tested**.
What is unverified is the input side: that a real CLI puts those strings in those fields.

Two specifics belong in the pass.

**The SDK ships seven exception classes, not five.** Verified rather than repeated:

```bash
.venv/bin/python -c "import claude_agent_sdk._errors as e, inspect; print(sorted(n for n, o in vars(e).items() if inspect.isclass(o) and issubclass(o, Exception)))"
```

That printed, at the environment recorded at the top of this file:
`CLIConnectionError`, `CLIJSONDecodeError`, `CLINotFoundError`, `ClaudeSDKError`,
`MessageParseError`, `ProcessError`, `ResultError` — seven. The hierarchy matters as much as the
count, because `translate.translated` is a chain of `isinstance` checks and the order is only
correct if the children are tested before the parents: `ClaudeSDKError` is the root;
`CLINotFoundError` extends `CLIConnectionError`; and **`ResultError` extends `ProcessError`**.
All seven are already parametrised, as a unit, through both
`translate.translated` and `translate.unready` in
`tests/adapters/test_claude_code_translate.py::TestVendorExceptions` — so a new class in a later
SDK is the thing to look for, not a mistranslation of an existing one.

**`ResultError` is what a logged-out session raises, and it is not only that.** Claude Code exits
non-zero for *every* error result, so "ran out of turns" and "could not authenticate" arrive as the
same class. Only the first has a port member: `StopReason.LIMIT` is a fact about what happened, and
the adapter answers with an `AgentOutcome` where the SDK would have raised
(`test_a_run_the_backend_stopped_is_an_outcome_and_not_an_exception`); the second becomes
`UpstreamUnavailable` carrying the CLI's own words
(`test_an_error_result_that_is_not_a_limit_is_translated_and_raised`). Telling them apart at
runtime is a string comparison on `subtype` and `result`, and nothing in this build has watched a
real CLI produce both.

**Command.** Read the raw fields off a real `ResultMessage`, which is exactly what the mapping
consumes. On an authenticated machine:

```bash
.venv/bin/python -c "
import asyncio
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

async def main() -> None:
    options = ClaudeAgentOptions(cwd='.', model='haiku', setting_sources=[],
                                 strict_mcp_config=True, permission_mode='bypassPermissions')
    async for message in query(prompt='Say the single word: done', options=options):
        if isinstance(message, ResultMessage):
            print('terminal_reason=', message.terminal_reason)
            print('subtype=', message.subtype, 'is_error=', message.is_error)
            print('stop_reason=', message.stop_reason)

asyncio.run(main())
"
```

**What a pass looks like.** Three printed fields, and the pass is that **the literal strings and the
field each arrived in appear as a row of `STOPPED`** in `tests/adapters/test_claude_code_runner.py`
— that table is the mapping, and this step is checking its *input* side. Concretely, the expected
reading for this command is a `terminal_reason` or `stop_reason` that `STOPPED` maps to `COMPLETED`,
with `is_error=False`. **A string that is not in the table is a missing row, not a wrong one**, and
degrades to `None` safely; a string that is in the table against the *wrong* member is the failure
worth the turn. Copy the three lines verbatim into the record either way.

`COMPLETED` is all this command settles. The other two outcomes have no one-liner and should be
taken opportunistically during the rest of this pass — **step 13 (entry 4) is the natural place for
the second**, since it is the one run that does real work and can be interrupted:

- **`LIMIT`** by letting a long task run into the CLI's own turn limit or the model's `max_tokens`
  (`run` sets no `max_turns` — only `check_ready` does).
- **`None`** by interrupting a run mid-stream and reading back `terminal_reason`.

Record, for each, the literal string and the field it arrived in, and compare against `STOPPED`.

**If it is wrong — and which section of the plan changes is "none", which is the point.** The owning
section is **§3.2**, the agent port, and it survives either way: `StopReason` has exactly two members
(`ports/agent.py`: "a question with exactly two answers worth telling apart") and a third is not what
a wrong row asks for. The mapping is entirely adapter-local — the `STOPPED` table and
`src/agl/adapters/claude_code/_session.py`'s three-field read — so **the repair is a row in an
adapter and never a port change or a plan change.** That containment is itself what is being
confirmed here: §3.2 says "nothing above an adapter sees a vendor's stop strings", and this step is
the one place a person checks that the strings an adapter *does* see are the ones it was written
for.

A string the CLI emits that is not in the table reads as `None`, which the port
made legal on purpose — "this backend did not say anything this port can read" has a spelling that
is not a lie, and inventing `COMPLETED` for a cancelled turn is the lie it prevents. So a *missing*
row degrades gracefully. A **wrong** row does not: a limit read as `COMPLETED` tells a workflow the
agent finished when it was cut off, and the step's output is a truncated answer treated as a
finished one. That is the one failure mode here worth a paid turn to rule out.

---

## Step 12 — Entry 10: `codex exec`'s terminal events against live outcomes

**Raised by:** stage 8.0 — `docs/codex-cli-findings.md` §5, and whatever 8.1 writes as the
`stop_reason` mapping in `adapters/openai/translate.py`.

**Assumed.** That a real `codex exec --json` run ends with the terminal event the mapping expects,
and that the one outcome worth calling `StopReason.LIMIT` is recognisable when it happens.

The mapping stage 8.0 recommends is:

| What arrives | `StopReason` |
|---|---|
| `turn.completed` | `COMPLETED` |
| `turn.failed` whose `error.message` matches a usage-limit text | `LIMIT` |
| `turn.failed`, anything else | not a stop reason — raise `UpstreamUnavailable` |
| a top-level `error` event, or the stream ending with no terminal event | `None` |

**The `LIMIT` row is the assumption, and it is the weakest thing in the adapter.** `codex exec`'s
JSONL carries **no machine-readable stop reason at all** — `turn.completed` carries `usage` and
nothing else, `turn.failed` carries a free-text `message` — so `LIMIT` can only be recognised by
matching vendor prose. The strings in the 0.149.0 binary are `You've hit your usage limit. `,
`You've hit your usage limit for `, and upgrade and credit variants. Nothing in this build has
watched one arrive.

**Already covered, free.** The event and item schema itself is established twice over and does not
need a paid turn: the serde tag table in the 0.149.0 binary and `codex-rs/exec/src/exec_events.rs`
on `main` agree on all eight envelope types and all nine item types, and 8.2's loopback can drive
every row of the mapping table above from canned frames. **What no free instrument supplies is the
input side**: that a real run emits `turn.completed` on success, and what a real usage-limit failure
actually says.

Also free, and worth doing first because it costs nothing and removes a whole class of surprise:
`codex exec`'s **exit codes are undocumented**. The source shows `0` on success and
`std::process::exit(1)` for everything from a config-parse failure to `if error_seen`. 8.2 should
pin whatever it observes against the loopback rather than guessing, and this entry should not be
spent on it.

**Command.** On an authenticated machine, in a scratch git repository. Read the raw frames, which is
exactly what the mapping consumes:

```bash
codex exec --json --color never -C . -s read-only 'Say the single word: done' \
  | python3 -c "
import json, sys
for line in sys.stdin:
    try: event = json.loads(line)
    except ValueError: continue
    if event.get('type', '').startswith(('turn.', 'thread.')) or event.get('type') == 'error':
        print(event)
"; echo "exit=$?"
```

**What a pass looks like.** A `turn.completed` frame printed, and `exit=0` on the line after it —
those two together are the `COMPLETED` row of the mapping table above, confirmed on its input side.
**Also record the exit code as a fact in its own right**: `codex exec`'s exit codes are undocumented
and 8.1 pinned `1` and `2` for argument and loader failures without ever observing a *turn* failure,
so this is the first observation of the success code. Anything other than `turn.completed` arriving
last — a top-level `error`, or the stream simply ending — is the `None` row, which is legal and not
a failure; a `turn.failed` on a task this trivial is.

`COMPLETED` and the exit code are all this command settles. The other two outcomes have no one-liner
and should be taken opportunistically during the rest of the pass: **`LIMIT`** by running the same
command on an account that has actually exhausted its usage — which is not something to arrange
deliberately, but is worth capturing the moment it happens to anybody — and **`None`** by
interrupting a run mid-stream. Record, for each, the literal `type`, the literal `message`, and the
process exit code. **The `LIMIT` row is the one that matters**: it can only be recognised by matching
vendor prose, and nothing in this build has watched one arrive.

**If it is wrong — and, as in entry 3, the section of the plan that changes is "none".** The owning
section is **§3.2**, the agent port, and it survives: the repair is a row in
`src/agl/adapters/openai/translate.py` and never a port change. §3.2's containment is what makes
that true, and it is worth noticing that this backend is the harder test of it — Codex's JSONL
carries no machine-readable stop reason at all, so `LIMIT` is recognised by matching vendor prose,
and *that* is the thing kept below the port rather than allowed to leak into it.

Entry 3's asymmetry applies here unchanged and is the reason this entry is worth
a turn at all. A string the CLI emits that the mapping does not recognise reads as `None`, which the
port made legal on purpose. A **wrong** row does not degrade: a limit read as `COMPLETED` tells a
workflow the agent finished when it was cut off, and the step's output is a truncated answer treated
as a finished one.

There is one Codex-specific escape worth writing down for whoever revisits this. The information
AGL wants **exists in the product** — Codex's app-server protocol carries a turn `status` of
`completed`/`failed`/`interrupted` and a `codexErrorInfo` with values including
`ContextWindowExceeded` and `UsageLimitExceeded` — and is simply not on the surface AGL uses. If the
prose-matching ever proves unworkable, the fix is a different Codex surface, not a different port.
That would be a large change (`codex app-server` has no `--sandbox` flag and a different lifecycle)
and it is not v1.1's, but it means "Codex cannot say" is a statement about `codex exec` rather than
about Codex.

---

## Step 13 — Entry 4: Activity strings from real tool calls

**Raised by:** stage 7.1 — `translate.activity` in
`src/agl/adapters/claude_code/translate.py`.

**Assumed.** That `translate.activity`'s rule produces useful lines from the tool calls a real
agent actually makes. The rule is deliberately generic and names no tool: the tool's own name
passes through verbatim (including an MCP tool's `mcp__server__name`), and the payload is
summarised as **the first string value in it, in arrival order** — which is a tool's schema order,
which is assumed to put the argument the call is *about* first. Two further rules apply to the
value and not the tool: a value beginning with the task's workspace plus a path separator is shown
relative to it (a plain prefix test — no `Path` is built, nothing is resolved, no filesystem is
touched, because the value came from a model and is not a promise that anything exists), and the
result is collapsed to one line and capped at 120 characters with an ellipsis marking the cut. A
payload with no string value at all renders as the bare tool name.

**That rule was derived from the SDK's message shapes, not observed against real tool calls.** §3.7
gives three examples — `Bash: ./gradlew build`, `Edit: domain/usecase.kt`,
`Read: connectors/api/backend.ts`. The question is whether those actually come out.

**Already covered, free.** `tests/adapters/test_claude_code_translate.py::TestActivityStrings`
reproduces all three of §3.7's examples plus `Grep`, `WebFetch`, a path outside the workspace left
whole, an invented tool with an invented argument name, an MCP-qualified name, and a payload of
non-strings rendering as the bare name — from hand-built payloads. And
`test_activity_is_the_tools_own_name_and_one_line_of_its_payload` drives the same rule through the
adapter on a scripted transport. **Every one of those payloads was written by this project**, which
is the whole of what is unverified: the argument-order assumption is a claim about the vendor's
tool schemas, and no test in the build has seen one.

**Command.** On an authenticated machine, in a repository with a `README.md`:

```bash
.venv/bin/python -c "
import asyncio
from pathlib import Path
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.ports.agent import AgentTask, Claude

task = AgentTask(
    instructions=(
        'Do exactly these four things and then stop: read README.md; grep this repository for '
        'the word port; list this directory with ls -la; append one blank line to README.md.'
    ),
    workspace=Path.cwd(),
    model=Claude.SONNET,
    restrictions=frozenset(),
    tools=(),
)
asyncio.run(ClaudeCodeRunner().run(task, on_activity=lambda line: print('ACTIVITY:', line)))
"
```

**What a pass looks like.** Read the printed `ACTIVITY:` lines against §3.7's own three examples —
`Bash: ./gradlew build`, `Edit: domain/usecase.kt`, `Read: connectors/api/backend.ts`. Four
readings, each of which can fail on its own:

- `Bash: …` carries the **command**, not a flag or a description;
- `Read:` and `Edit:` carry a path **relative to the workspace** (the run's `cwd` here), not an
  absolute one;
- `Grep:` carries the **pattern** rather than the path — this is the argument-order assumption doing
  its work, and the one most likely to be wrong;
- nothing renders as a **bare tool name** (a payload with no string value) or leads with a large
  field whose first line is unhelpful.

Note anything that fails one of the four, verbatim. **This is a measurement, not a gate** — see "If
it is wrong". And since this is the one paid run in the pass that does real work over several tool
calls, it is the natural place to interrupt mid-stream and capture entry 3's `None` row (step 11).

**If it is wrong.** Cosmetic, by §3.7's own account, and this entry is here to be *cheap to skip*
rather than urgent. `run.activity` is a plain string the router passes through untouched, it is
never persisted, nothing branches on it, and a step replayed from cache correctly has none at all.
The known cost is already written down: a tool whose schema happens to lead with a large field
renders that field's first line. So a bad line is a dashboard cell that reads poorly, not a run
that goes wrong — the fix, if one is wanted, is a better generic rule and never a per-tool table,
which §3.7 forbids and `translate.py` is built to avoid.

---

## Step 14 — Entry 14: Whether a live agent reads the inputs block appended to its prompt

**Raised by:** stage 13 — 13.0(i): `_composed` and `_INPUTS_HEADING` in
`src/agl/sdk/_engine/steps.py`.

**Assumed.** That a real agent **attends to** the block `run.step(name, role, **inputs)` appends.
§3.3 settles how a value reaches an agent and it is not templating — `str.format` breaks on a brace
and these prompts carry JSON Schemas, `%` breaks on a percent sign — so the framework appends one
structured block under a fixed heading and "the author writes the prompt knowing inputs arrive at
the end". Four properties of that block are the assumption, and each is a separate way a model could
miss it:

- it is at the **end**, after however many hundred lines of role instructions;
- it is under a **markdown heading**, `## Inputs`, and nothing else marks it;
- it is **compact canonical JSON** — `journal.canonical_json`, so the separators carry no spaces
  and the keys are sorted, which is not how a human would lay an input out for a reader;
- `ensure_ascii=True`, so a non-ASCII input arrives as the escape `\u00ef` and not as the character
  it stands for, and every dataclass at every depth carries an `__agl_type__` tag naming its
  qualified type.

None of that is negotiable at the margin, which is why the question is "does a model read this"
rather than "should it be prettier": the block **is** the canonical text the fingerprint was taken
over, byte for byte, and a pretty-printer here would be a second answer to "what were these inputs",
free to drift from the digest in either direction.

**Already covered, free — the framework's whole half, and it is more than it looks.**
`tests/sdk/test_run_step.py` drives the real engine against a scripted fake and asserts the **whole
dispatched string** rather than a containment, because everything §3.3 fixes about the block is in
the parts a containment check cannot see:

- the block is composed, its keys sorted and its separators the compact ones the fingerprint was
  taken with (`test_the_inputs_a_step_passes_are_appended_to_what_the_agent_is_asked`);
- the author's own text survives **byte-identical** in front of a prompt carrying `{`, `}`,
  `{name}`, a JSON Schema and a literal `%s` — and both templating implementations were *measured*
  raising on that prompt rather than assumed to
  (`test_a_prompt_carrying_braces_and_percent_signs_reaches_the_agent_byte_identical`);
- a step with no inputs is dispatched the role's instructions and **nothing else** — no heading over
  an empty object, no trailing newline
  (`test_a_step_with_no_inputs_is_dispatched_the_roles_instructions_and_nothing_else`);
- two calls whose keywords are written in different orders compose one string and replay as one
  step (`test_the_same_inputs_in_a_different_keyword_order_compose_and_replay_the_same`);
- §3.3's own `findings=highs` reaches the dispatch as its fields **and** its `__agl_type__` tag
  (`test_a_dataclass_input_reaches_the_agent_as_its_fields_and_its_type`).

All five read the composed string off `AgentTask.instructions`, since the fake records the
instructions of every task it is handed. **What no free test can show is a model attending to it.**
A scripted fake cannot fail to read its prompt, and neither can a loopback: the block leaves this
machine correctly and what happens to it afterwards is the one thing on the far side.

**Command.** On an authenticated machine, in a scratch directory. The prompt is built by
`steps._composed` itself rather than by hand — the composition is already proven and a hand-built
copy would be measuring this file's typing, not the framework's output. The input is chosen so that
each of the four properties above fails visibly and separately: a dataclass for the `__agl_type__`
tag, a non-ASCII character for the `ensure_ascii` escaping, and a second key so that key order and
the end of the block are both readable in the answer.

```bash
.venv/bin/python -c "
import asyncio
from dataclasses import dataclass
from pathlib import Path
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.ports.agent import AgentTask, Claude
from agl.sdk._engine.steps import _composed

@dataclass(frozen=True)
class Finding:
    ticket: str
    severity: int
    note: str

instructions = (
    'You are triaging review findings. The findings you must triage are given to you in this '
    'prompt and nowhere else - do not read any file and do not run any command. Answer with '
    'exactly three lines and nothing else: (1) the ticket id of the single finding, (2) its '
    'note, copied character for character, (3) the deadline.'
)
inputs = {
    'findings': [Finding('T-01', 5, 'the naïve path is not naïve')],
    'deadline': 'Friday',
}
asked = _composed(instructions, inputs)
print('--- PROMPT AS DISPATCHED ---'); print(asked); print('--- END ---')

task = AgentTask(
    instructions=asked,
    workspace=Path.cwd(),
    model=Claude.SONNET,
    restrictions=frozenset(),
    tools=(),
)
print('OUTCOME:', asyncio.run(ClaudeCodeRunner().run(task)))
"
```

The diaeresis in that note is the whole of the third field's job, and it has to survive being copied
out of this file: the Python source carries the character, `canonical_json` renders it back as
`\u00ef`, and the escape is what the model is shown.

**What a pass looks like.** Three things, and they fail independently — which is why the reply is
asked for in exactly three lines:

- the **ticket id** (`T-01`) says the block was found and parsed at all;
- the **note copied character for character** — the diaeresis rendered as the character, not echoed
  back as the literal `\u00ef` — says the escape was decoded;
- the **deadline** (`Friday`) says the model read past the first key rather than stopping at the
  object it recognised.

**Record a partial pass as a partial pass** — the tag ignored, or the escape echoed, or the last key
never reached — because that is the likely shape, and "it worked" would lose it.

**This step is two turns, not one.** Run the same command against `OpenAI.LUNA` through
`OpenAiRunner` — it is one import and one enum away — because §3.3's block is composed once, above
the port, and is handed to whichever backend the role routes to. A result on one backend says
nothing about the other.

**A single failure is not a verdict, and the boundary is entry 2's.** Whether a *particular* prompt
gets a model to use its inputs is prompt engineering and belongs to the workflow. Run the cheap tier
after the strong one rather than instead of it: `Claude.HAIKU` failing where `Claude.SONNET`
succeeds is a fact about routing a role to a cheap model, not about the block. Record a failure when
the block is demonstrably in the prompt and the answer is demonstrably not taken from it — and
record a **partial** one, because that is the likely shape: the tag ignored, or the escape echoed,
or the last key never reached.

**If it is wrong.** §3.3's own `w.step("triage", triage, findings=highs)` fingerprints the findings
correctly, pays for an agent, and triages nothing. That is precisely the failure 13.0(i) closed one
layer down — before it, the inputs were a fingerprint term and were never sent at all — and the
remaining version of it is quieter, because the findings are now *in the prompt* and merely unread.
Nothing raises. The step records a result, the digest matches on resume, and the workflow carries on
with a triage of nothing.

**Two candidate repairs, and the property they share is the reason this entry exists.** A different
heading or a different position — inputs before the instructions rather than after, or a heading
that says more than two words — is one; a paragraph per input, each key named in prose with its
value under it, is the other, and it is the larger change because it stops being canonical JSON and
therefore stops being the text the digest was taken over. **Either one moves no digest.** The
heading and the composition are deliberately outside the fingerprint — `journal.step` is still
handed `instructions=role.instructions` and `inputs=inputs` as two separate terms, which is §3.6's
shape and a stored format — so a repair costs no re-runs, which is the good half, and is invisible
to every test and every resume in this repository, which is the other. A resume after such a repair
replays results the old heading produced, and nothing anywhere says so. Whoever makes that change
should write it down here.

---

## Step 15 — Entry 1: The eight contract-suite clauses deferred to this pass

**Raised by:** stage 7.1 — `tests/adapters/test_claude_code_runner.py::TestClaudeCodeRunner`,
which subclasses the port's agent contract suite in full.

**Assumed.** That `ClaudeCodeRunner` satisfies the eight clauses of `tests/contracts/agent.py` and
its siblings that this pass defers — seven of them because their evidence is a *model's* conduct,
and an eighth for a reason of its own. The `runner` fixture hands the suite a subclass whose `run`
calls `pytest.skip` unconditionally (the `_SKIPPED` constant in that module is the reason a reader
gets), so eight of the suite's **ten** tests do not run — anywhere, on any machine, with no switch
that changes it. The gate sits on the port member that starts an agent rather than on a list of
names, so the eight are exactly "the tests that start an agent":

| Test | Its evidence is that a model… |
|---|---|
| `test_a_run_answers_with_an_outcome_whose_stop_reason_may_be_none` (`tests/contracts/agent.py`) | ran at all and produced an outcome |
| `test_a_refused_tool_call_is_put_back_to_the_agent_inside_the_same_run` (`tests/contracts/agent.py`) | called a supplied tool, and called again after its result was rejected |
| `test_a_tool_handler_that_raises_is_a_refusal_and_not_the_end_of_the_run` (`tests/contracts/agent.py`) | called a supplied tool whose handler *failed*, and carried on rather than ending the run |
| `test_activity_lines_are_plain_strings_and_may_never_arrive_at_all` (`tests/contracts/agent.py`) | reported activity by calling tools |
| `test_a_question_and_its_answer_are_two_rounds_inside_one_run` (`tests/contracts/_agent_questions.py`) | asked, and then used the answer |
| `test_a_question_nobody_is_listening_for_does_not_block_the_run` (`tests/contracts/_agent_questions.py`) | asked when nobody was listening |
| `test_no_harness_configuration_in_the_workspace_reaches_the_agent` (`tests/contracts/_agent_hermeticity.py`) | ignored a poisoned repository |
| `test_an_activity_reporter_that_raises_ends_the_run_with_its_own_exception` (`tests/contracts/agent.py`) | **nothing — this is the eighth, and it needs no conduct at all** |

**The eighth is deferred for its own reason and is the cheapest thing here to believe.** It is
skipped only because the contract suite's one knob is the runner, and a real `ClaudeCodeRunner`
reports no activity without a session to read one off — so it rides along behind the same
`pytest.skip`. It is asserted for real, offline, against the same adapter, further down that same
module (`test_an_activity_reporter_that_raises_comes_out_of_this_adapters_run` in
`tests/adapters/test_claude_code_runner.py`). Nothing about it needs this pass.

Two of the ten were added after this entry was first written — the tool handler that raises at
stage 8.5, the activity reporter that raises at 19A — which is why an older reading of this entry
had a person hand-checking six things while eight were unverified. The authoritative current
statement is the `_SKIPPED` constant itself, and plan Part 5 target 7 records the same split:
"seven of the agent suite's ten clauses read a model's conduct and an eighth is deferred for its
own reason".

The suite's other two run unconditionally against the real adapter and need nothing here:
`test_capabilities_answers_for_the_model_it_was_asked_about` and
`test_check_ready_answers_with_nothing_or_says_why_it_cannot`, both in
`tests/contracts/_agent_preflight.py`. Verify the split yourself in one second, free — this is the
only counting anybody should ever do by hand here:

```bash
.venv/bin/pytest "tests/adapters/test_claude_code_runner.py::TestClaudeCodeRunner" -q
# 2 passed, 8 skipped
```

**Already covered, free — do not re-check these by hand.** What is left for a person is only
whether a *model* behaves as the port assumes; the mechanism underneath it is verified without one.

- **The poisoned repository, three ways, none of which needs a model.** `init`: the workspace's
  planted `.claude/agents/*.md` subagent, `.claude/commands/*.md` slash command and `.mcp.json`
  server are all absent from the session the CLI reports opening, and the session's MCP servers are
  exactly `["agl", "agl_ask"]`
  (`test_no_configuration_in_the_workspace_reaches_the_session_it_composes`). The composed request:
  no poison marker is in the bytes that left the machine, with the workspace's own `CLAUDE.md`
  asserted present as the control
  (`test_nothing_the_repository_wrote_reaches_the_model_in_the_request_that_leaves`). And the
  prompt: no marker from the contract suite's own poison is in what the agent is told
  (`test_no_marker_from_the_contract_suites_own_poison_is_in_what_the_agent_is_told`).
- **Tool and question plumbing, offline.** A tool call reaching its handler as a mapping and its
  text going back, a refused tool result carrying the mechanism's own error flag, a malformed
  payload never reaching the handler, activity strings, and two questions with two answers inside
  one run — all driven through a scripted `Transport`, with the real adapter, the real SDK message
  parsing and the real in-process MCP servers, and no CLI and no model anywhere.

**Command.** There is no flag for this and there is deliberately not going to be one. Preparation,
in `tests/adapters/test_claude_code_runner.py`: return `ClaudeCodeRunner()` from
`TestClaudeCodeRunner.runner` instead of `_NeverRuns()`, and delete the two `setenv` lines in the
`harness` fixture so that the CLI reaches the real API rather than the loopback. Then, on an
authenticated machine:

```bash
AGL_LIVE_AGENT=1 .venv/bin/pytest "tests/adapters/test_claude_code_runner.py::TestClaudeCodeRunner" -x
```

Revert both edits afterwards. `Claude.HAIKU` is what the `model` fixture supplies, so this is eight
one-shot errands and not eight real runs.

**What a pass looks like.** `10 passed` — every clause green against the real adapter, with no
skips left. A skip surviving the preparation means one of the two edits did not take. Read any
failure against the table above rather than against the test name: the clause that failed names the
thing a model did not do, and "If it is wrong" below prices each one separately.

**If it is wrong.** Which clause fails decides the damage.

- The tool-calling and refusal clauses failing means `capabilities()` is lying: it answers
  `TOOL_CALLING` and `FILE_EDIT` as a constant for every task on every machine, and §3.2's second
  preflight check admits a role against that answer. A role declaring `requires={FILE_EDIT}` would
  be admitted onto a backend that cannot serve it, and the run would die at the step rather than at
  second zero — the exact failure preflight exists to prevent.
- The tool handler that *raises* failing is the same finding one step further in: the port's answer
  is that a handler's exception becomes a refusal the model is told about and not the end of the
  run, so a failure here means a workflow tool that throws once kills the step instead of getting a
  second attempt. `TOOL_CALLING` is what promises this.
- The activity clause failing is cosmetic by §3.7's own account (`run.activity` is live-only, never
  persisted, and nothing branches on it) — see entry 4, at step 13.
- The question clauses failing is entry 2, at step 9, which is the serious one.
- The poisoned-repository clause failing would mean §3.5's "the target repo contributes source code
  and nothing else" is false through a channel none of the three free measurements above can see —
  neither registration nor the request bytes — which would be a new finding and not a regression.
- The activity reporter that raises failing would be a surprise rather than a finding, since the
  same claim is already asserted offline against this adapter. Read it as the live path diverging
  from the scripted one, and look at the session rather than at the model.

---

## Step 16 — Entry 8: The eight contract-suite clauses deferred to this pass — Codex CLI

**Raised by:** stage 8.0 — `docs/codex-cli-findings.md`, before the adapter exists. It is raised
here rather than left to 8.2 because this file "does not go looking for entries", and the stage that
established what is unverifiable is the stage that knows. **8.2 asked that the module path below be
corrected if it named its test file differently; it did not** — the module is
`tests/adapters/test_openai_runner.py` and the class is `TestOpenAiRunner`, both verified at 19.7,
so what is written here is what is there.

**Assumed.** That `OpenAiRunner` satisfies the same eight clauses of `tests/contracts/agent.py` and
its siblings that entry 1 defers for Claude Code, for the same reasons: seven have a *model's*
conduct as their evidence and no free instrument can supply it, and the eighth — the activity
reporter that raises — is deferred because the suite's one knob is the runner and a real
`OpenAiRunner` reports nothing without a harness to read. The shape is the one stage 7.1 settled and
8.2 reproduced: a `runner` fixture handing the suite a subclass whose `run` calls `pytest.skip`
unconditionally, so that the gate sits on the port member that starts an agent rather than on a list
of names.

The eight are the same eight, and the table in entry 1 applies verbatim. The other two —
`test_capabilities_answers_for_the_model_it_was_asked_about` and
`test_check_ready_answers_with_nothing_or_says_why_it_cannot` — run unconditionally against the real
adapter and need nothing here. **For Codex the second of those is genuinely free**, which it is not
for Claude: `codex login status` exits 0 printing `Logged in using ChatGPT` and exits 1 printing
`Not logged in`, measured both ways at stage 8.0, so `check_ready` costs no turn at all — which is
why step 6 (entry 5's returning branch) has no Codex counterpart and this backend needs no
authentication gate above it. Confirm the split for free, the same way entry 1 does:

```bash
.venv/bin/pytest "tests/adapters/test_openai_runner.py::TestOpenAiRunner" -q
# 2 passed, 8 skipped
```

**The eighth is asserted for real without this pass**, offline against the stub CLI further down
that same module, exactly as entry 1's is. Nothing about it needs a turn.

**Already covered, free — do not re-check these by hand.** Stage 8.0 measured the following without
a model, and `docs/codex-cli-findings.md` carries the reproductions:

- **The sandbox, directly.** `codex sandbox -- <command>` applies the same policy with no model and
  no approval channel. Under `workspace-write`, writes to `.git`, `.codex` and `.agents` are denied
  and network is denied; under `read-only` every write is denied; `writable_roots` lifts the first
  and `sandbox_workspace_write.network_access=true` lifts the second. So **`NO_VCS_WRITES`,
  `NO_FILE_WRITES` and `NO_NETWORK` rest on a measured mechanism**, not on a model's cooperation.
- **The policy the model is actually handed**, read off `codex debug prompt-input`, which renders
  the model-visible messages and contacts nothing. The `<permission_profile>` element names the
  `.git`, `.codex` and `.agents` exclusions explicitly under `workspace-write`, and is
  **byte-identical across all four loadable approval policies**, varying only with `sandbox_mode`
  (fifteen cells, three distinct hashes). That is the R2 evidence and it needs no turn — **do not
  spend one re-deriving it.** It also settles that `read-only` restricts the filesystem and the
  network and says nothing about running commands, so a reviewing role under `read-only` can still
  run a build.
- **The poisoned repository, without a model.** `codex debug prompt-input` renders the
  model-visible prompt as JSON and contacts nothing. With `-c project_doc_max_bytes=0` and
  `-c skills.include_instructions=false`, every marker a poisoned repository planted is absent and
  only the operator's own `$CODEX_HOME/AGENTS.md` remains. This is a **stronger** free instrument
  than the Claude side has, and it means the hermeticity clause is nearly settled before a model is
  involved.
- **No loopback, and saying so is the correction this bullet used to need.** This entry was written
  expecting 8.2 to build a Codex loopback — "everything the Claude suite gets from
  `tests/instruments/loopback.py` … is available to Codex through the same trick", the endpoint
  being redirectable by configuration (`-c chatgpt_base_url=…`), established free at stage 8.0. **It
  was not built**; entry 13 records the decision, its price and its five open questions. So yes:
  **this entry is doing more work than entry 1's**, and that is the honest reading of it.
- **What 8.2 built instead, and it covers more than the bullet above expected.**
  `tests/adapters/test_openai_runner.py` runs on every `scripts/check` and drives a stub CLI that
  records the argv, working directory and prompt it was handed, plays a scripted event stream back,
  and acts as a real MCP client against the servers the adapter started over real HTTP. That covers
  the composed command line, the composed prompt, every branch of the stream reading, and the whole
  tool and question round trip. It also runs `codex debug prompt-input` against a poisoned
  repository, with the overrides lifted off the command line the adapter itself composed and a
  control run proving the poison was there to find — so the hermeticity clause is nearer settled
  here than on the Claude side. What none of it reaches is *a model deciding anything*.

**Command.** Preparation, in `tests/adapters/test_openai_runner.py`: return `OpenAiRunner()` from
`TestOpenAiRunner.runner` instead of `_NeverRuns()`, and remove whatever points the CLI at the stub.
Then, on an authenticated machine:

```bash
AGL_LIVE_AGENT=1 .venv/bin/pytest "tests/adapters/test_openai_runner.py::TestOpenAiRunner" -x
```

Revert afterwards. `OpenAI.LUNA` is what the `model` fixture supplies — the cheapest tier this
adapter serves — so this is eight one-shot errands and not eight real runs. `codex debug models`
lists the catalog and is free, if the tiers have moved.

**What a pass looks like.** `10 passed`, no skips. A skip surviving the preparation means one of the
two edits did not take. **Read a failure against the four explanations below before blaming the
model** — that is the difference between this step and step 15.

**If it is wrong.** The consequences are entry 1's, against the same two plan sections — **§3.2**,
whose check 2 admits a role against `capabilities()`, so a failed tool-calling or refusal clause
means `TOOL_CALLING` and `FILE_EDIT` come out of this adapter's `_CAPABILITIES`; and **§3.5**, whose
"the target repo contributes source code and nothing else" is what a failed poisoned-repository
clause falsifies. Two Codex-specific differences on top of that.

- The tool-calling and refusal clauses failing means more here than there. Claude Code's asking tool
  and reporting tool are hosted in-process by its SDK; Codex's are an **MCP server the adapter runs**
  and Codex connects to. A failure could therefore be the model, the MCP handshake, the transport,
  or `tool_timeout_sec` — four explanations where the Claude side has one. Read
  `docs/codex-cli-findings.md` §0 before concluding it is the model.
- The poisoned-repository clause failing would be a **new finding rather than a regression**, and a
  specific one: stage 8.0 measured that the repository contributes nothing to the *prompt*. A leak
  would therefore have to arrive through a channel that reaches the request without reaching the
  prompt, which is exactly what `codex debug prompt-input` cannot see.
- If steps 7, 8 and 10 all passed, most of this step's failure modes are already excluded, which is
  the reason those steps come first: entry 12 settles the MCP handshake and the transport, entry 9
  settles the model calling a tool and asking through it, and entry 16 settles `tool_timeout_sec`.
  A failure here after all three is the model, or it is the contract suite's own poisoned fixture,
  and nothing else is left.

---

## Not a step — Entry 13: What stage 8.2 did not build — no loopback for this backend

**Raised by:** stage 8.2. **This entry is a record of a decision and a list of what it left open**,
not a check to run. It exists because `docs/codex-cli-findings.md` §10 told 8.2 to make four free
measurements against a loopback and entries 8, 9 and 11 were written assuming it would.

**What was decided.** 8.2 built **no loopback endpoint for this harness**. §7 of the findings
priced it honestly and the price is the reason: it would have to speak the OpenAI **Responses** API
over SSE — not the other vendor's message stream, which is what `tests/instruments/loopback.py`
serves — and, to drive a tool loop, emit tool calls in that format. That is a second wire protocol
implemented from the specification, in a deliverable that already hand-rolls an MCP server and an
HTTP listener because `dependencies = []`. The findings allowed for this: "if that turns out to be
more than 8.2 can carry, saying so and falling back to credential-removal alone is an acceptable
outcome — but it should be a stated decision". **It is stated here.**

**What was built instead, and what it does cover.** A stub CLI, written per test, which records the
argument list, working directory and prompt it was handed, plays a scripted event stream back, and
acts as an MCP client against the servers the adapter started. That covers the composed command
line, the composed prompt, every branch of the stream reading, and the whole tool and question path
over real HTTP. What it cannot cover is anything that needs *the real binary's* behaviour.

**What therefore remains unsettled**, each with what stands in its place:

| Question | What it needed | What stands instead |
|---|---|---|
| Does the request go where `chatgpt_base_url` points? | A listener at that URL | `codex doctor --json` resolves the endpoint to it (8.0 §7, free, with a working control). Nothing has watched a request arrive |
| Is an AGL tool in the model's tool list? | The composed request | Entry 12: a different vendor's MCP client enumerated both servers; the harness's configuration accepts them |
| Does `features.shell_tool=false` remove the shell? | The composed request | 8.1 measured the override reaching the feature registry (`codex features list -c …` reports it `false`). Nothing has established that a feature off in the registry removes a tool from the model's list — and `NO_SHELL` also goes to the agent in words, which is why the gap is a degradation rather than a dropped restriction |
| Does `--ignore-user-config` suppress `$CODEX_HOME/AGENTS.md`? | A real run's request | Entry 11, item 1, still open. `codex debug prompt-input` does not take that flag |
| What does a turn that ran and failed exit with? | A real run | Entry 10. 8.1 established 2 (the argument parser) and 1 (the loader, a missing home, a logged-out probe) for free; the *turn-failure* 1 is read off the harness's source and has not been observed |

**Two of these five are now cheaper than they were**, and whoever revisits this should know it. The
poisoned-repository question that a loopback would have answered is answered without one:
`codex debug prompt-input` renders the model-visible prompt and contacts nothing, and
`tests/adapters/test_openai_runner.py` runs it on every `scripts/check`, in a poisoned repository,
with the configuration overrides lifted off the command line the adapter itself composed — plus a
control run proving the poison was there to find. That test also settles, for free and on every
build, that **every override this adapter emits loads**, since one the harness rejects makes it
exit before rendering anything.

**If somebody builds the loopback later.** It belongs in `tests/instruments/` beside the existing
one, not in this adapter, and `tests/conftest.py`'s docstring should stop saying the redirect is
established-but-unused. Two guards must stay whatever happens: the emptied `CODEX_HOME`, which is
what makes a misconfigured redirect an authentication failure rather than a bill, and
`scripts/check`'s paid-endpoint gate.

---

## Reported, not resolved: §3.2 numbers two preflight checks and `src/` numbers three

Not a step and not a check — a discrepancy found while assembling this file, recorded here because
CLAUDE.md asks for ambiguity to be reported rather than resolved silently, and because it cost a
false alarm during 19.7 that the next reader should not have to repeat.

**The plan numbers two.** §3.2's heading is "Two preflight checks, **before the run starts**": check
1 is provider availability (`check_ready` per distinct model), check 2 is capability match. It then
declines to number a third by name — "**Capability implications are folded in at declaration**, so
they fall out of **check 2** rather than needing a check each" — while still describing per-step
containment as a real thing ("containment only, memoised, at every `run.step`").

**The implementation numbers three, consistently, at five sites.**

| Site | What it calls the third check |
|---|---|
| `src/agl/sdk/_engine/preflight.py` (~line 40) | "§3.2's third check is that a role declaring `on_question` resolves to a provider with `MID_RUN_QUESTIONS`" |
| `src/agl/sdk/_engine/preflight.py` (~line 184) | "§3.2's second and third checks in one containment" |
| `src/agl/sdk/_engine/steps.py` (~line 434) | the per-step containment is "what makes §3.2's third check real" |
| `src/agl/sdk/roles.py` (~line 54) | "§3.2's third preflight check", of the `on_question` folding |
| `src/agl/workflows/fix/roles.py` (~line 164) | "the precondition §3.2's third check exists to refuse" |

`src/agl/sdk/workflow.py` (~line 385) says "§3.2's **second** preflight check, at step time" of the
capability table — which is not a disagreement, since `preflight.py` states outright that checks 2
and 3 are one containment.

**Both are internally consistent, and this file follows the implementation's vocabulary** — that is
what a reader greps, and every "third preflight check" below resolves against those five sites.

**Why it is worth a note rather than a silent choice.** The ordinal is greppable and the gloss
usually is not, so a reader who checks two sites against §3.2's heading can conclude the code is
wrong about the plan when it is not. That happened during 19.7. Two things would have prevented it,
and neither is 19.7's to make:

1. **§3.2 naming its per-step containment**, so the code's five "third check" sites have a referent
   in the plan instead of only in each other. A single clause. This is the cheaper fix and the one
   worth taking.
2. **Citing the ordinal with its gloss** — "§3.2's third check, capability match at every
   `run.step`" — wherever the number appears alone. `sdk/workflow.py` already does this and is the
   house spelling; `sdk/roles.py:54` is the site where the bare ordinal reads most like a defect,
   because its paragraph is specifically about the folding and §3.2's own sentence about folding
   names check 2.

**Nothing was changed in `src/` for this**, deliberately: there is no defect behind it, and 19B is a
session that measures the tree rather than edits it.
