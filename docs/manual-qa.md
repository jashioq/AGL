# AGL — Manual QA register

Every claim in this build that only a real model can settle, recorded where it arose.

**Who runs this.** A human, once, at the end of the build, on an authenticated machine, against
real models. It is not an automated suite and does not become one: `docs/agl-build-stages.md` puts
the rule as "no automated test may make a paid model call — not gated, not opt-in, not 'only when
you set the env var'", so anything whose evidence is a *model deciding something* lands here
instead of in `tests/`.

**How this file grows.** A stage that hits a model-dependent claim appends an entry and moves on.
Deliverable 19.2 assembles what is here into the single ordered pass; **it does not go looking for
entries**, so a stage that defers silently loses the item.

**What every entry carries**, because 19.2 turns them into a checklist and a reader decides per
entry whether it is worth the turn:

- **Raised by** — the stage that deferred it, and where the claim lives.
- **Assumed** — the claim being taken on trust.
- **Already covered, free** — what the automated suite really does verify, so that nobody spends a
  paid turn re-checking something a loopback already settled.
- **Command** — what to run.
- **If it is wrong** — the consequence, named against the plan section that owns it. This is the
  part that decides whether anybody bothers.

Entries are numbered in the order they were raised, starting at 1, and are never renumbered.

**Cost.** Everything listed under "already covered, free" runs on every `scripts/check` with no
model behind it: `tests/instruments/loopback.py` binds `127.0.0.1` and answers a real `claude`
process out of canned data, and a scripted `claude_agent_sdk` `Transport` drives the adapter with
no CLI at all. Every command below **spends real tokens unless the entry says otherwise** — that
is what makes it a manual entry. Entries 6, 7 and 11 are the exceptions and are free.

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

---

## 1. The six contract-suite clauses that read a model's conduct

**Raised by:** stage 7.1 — `tests/adapters/test_claude_code_runner.py::TestClaudeCodeRunner`,
which subclasses the port's agent contract suite in full.

**Assumed.** That `ClaudeCodeRunner` satisfies the six clauses of `tests/contracts/agent.py` whose
evidence is a *model's* conduct. The `runner` fixture hands the suite a subclass whose `run` calls
`pytest.skip` unconditionally (the `_SKIPPED` constant in that module is the reason a reader gets),
so six of the suite's eight tests do not run — anywhere, on any machine, with no switch that
changes it. The gate sits on the port member that starts an agent rather than on a list of names,
so the six are exactly "the tests that start an agent":

| Test | Its evidence is that a model… |
|---|---|
| `test_a_run_answers_with_an_outcome_whose_stop_reason_may_be_none` (`tests/contracts/agent.py`) | ran at all and produced an outcome |
| `test_a_refused_tool_call_is_put_back_to_the_agent_inside_the_same_run` (`tests/contracts/agent.py`) | called a supplied tool, and called again after its result was rejected |
| `test_activity_lines_are_plain_strings_and_may_never_arrive_at_all` (`tests/contracts/agent.py`) | reported activity by calling tools |
| `test_a_question_and_its_answer_are_two_rounds_inside_one_run` (`tests/contracts/_agent_questions.py`) | asked, and then used the answer |
| `test_a_question_nobody_is_listening_for_does_not_block_the_run` (`tests/contracts/_agent_questions.py`) | asked when nobody was listening |
| `test_no_harness_configuration_in_the_workspace_reaches_the_agent` (`tests/contracts/_agent_hermeticity.py`) | ignored a poisoned repository |

The suite's other two run unconditionally against the real adapter and need nothing here:
`test_capabilities_answers_for_the_model_it_was_asked_about` and
`test_check_ready_answers_with_nothing_or_says_why_it_cannot`, both in
`tests/contracts/_agent_preflight.py`.

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

Revert both edits afterwards. `Claude.HAIKU` is what the `model` fixture supplies, so this is six
one-shot errands and not six real runs.

**If it is wrong.** Which clause fails decides the damage.

- The tool-calling and refusal clauses failing means `capabilities()` is lying: it answers
  `TOOL_CALLING` and `FILE_EDIT` as a constant for every task on every machine, and §3.2's second
  preflight check admits a role against that answer. A role declaring `requires={FILE_EDIT}` would
  be admitted onto a backend that cannot serve it, and the run would die at the step rather than at
  second zero — the exact failure preflight exists to prevent.
- The activity clause failing is cosmetic by §3.7's own account (`run.activity` is live-only, never
  persisted, and nothing branches on it) — see entry 4.
- The question clauses failing is entry 2, which is the serious one.
- The poisoned-repository clause failing would mean §3.5's "the target repo contributes source code
  and nothing else" is false through a channel none of the three free measurements above can see —
  neither registration nor the request bytes — which would be a new finding and not a regression.

---

## 2. `on_question` end to end against a live agent

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

Two things pass: the handler was called at least once, and the file on disk is named
`agl_manual_qa_marker` — the second is what proves the answer went back into the *same* session and
was acted on, rather than the agent asking and then ignoring the reply.

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

## 3. `stop_reason` mapping against live outcomes

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

That settles `COMPLETED` and which of the three fields carried it. The other two outcomes have no
one-liner and should be taken opportunistically during the rest of this pass: **`LIMIT`** by
letting a long task run into the CLI's own turn limit or the model's `max_tokens` (`run` sets no
`max_turns` — only `check_ready` does), and **`None`** by interrupting a run mid-stream and reading
back `terminal_reason`. Record, for each, the literal string and the field it arrived in, and
compare against `STOPPED`.

**If it is wrong.** A string the CLI emits that is not in the table reads as `None`, which the port
made legal on purpose — "this backend did not say anything this port can read" has a spelling that
is not a lie, and inventing `COMPLETED` for a cancelled turn is the lie it prevents. So a *missing*
row degrades gracefully. A **wrong** row does not: a limit read as `COMPLETED` tells a workflow the
agent finished when it was cut off, and the step's output is a truncated answer treated as a
finished one. That is the one failure mode here worth a paid turn to rule out.

---

## 4. Activity strings from real tool calls

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

Read the printed lines against §3.7's three examples: `Bash: ...` should carry the command,
`Read:`/`Edit:` should carry a path **relative to the workspace** (the run's `cwd` here), and
`Grep:` should carry the pattern rather than the path. Note anything that renders as a bare tool
name, or renders a large leading field, or renders an absolute path that should have been
shortened.

**If it is wrong.** Cosmetic, by §3.7's own account, and this entry is here to be *cheap to skip*
rather than urgent. `run.activity` is a plain string the router passes through untouched, it is
never persisted, nothing branches on it, and a step replayed from cache correctly has none at all.
The known cost is already written down: a tool whose schema happens to lead with a large field
renders that field's first line. So a bad line is a dashboard cell that reads poorly, not a run
that goes wrong — the fix, if one is wanted, is a better generic rule and never a per-tool table,
which §3.7 forbids and `translate.py` is built to avoid.

---

## 5. Whether the Claude Code CLI is authenticated

**Raised by:** stage 7.1 — `check_ready` and `_READY_PROMPT` in
`src/agl/adapters/claude_code/runner.py`.

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

**Command.** Free half first, on the machine as it stands, with the loopback's variables
unset — this is the only branch that can be checked without knowing the answer in advance:

```bash
env -u ANTHROPIC_BASE_URL -u ANTHROPIC_API_KEY .venv/bin/python -c "
import asyncio
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.ports.agent import Claude
asyncio.run(ClaudeCodeRunner().check_ready(Claude.HAIKU))
print('READY')
"
```

Then the half that needs a logged-out machine — run `claude /logout` first, or run the same command
as a user with no Claude Code session, and read the refusal:

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

What passes: the second prints `REFUSED:` followed by a message naming authentication — not a
traceback, and not any other exception class. Log back in afterwards.

**If it is wrong.** `check_ready`'s one legal refusal is `UpstreamUnavailable`, and §3.2's first
preflight check catches that class and nothing else. Any other exception escaping a logged-out
probe reaches the top of the CLI as **exit 70** and tells a person to file a bug about their own
logged-out session — which is precisely the outcome the port member exists to prevent, and the
reason `tests/contracts/_agent_preflight.py` fails an adapter that raises anything else by name. A
refusal with an empty or unhelpful message is the same dead end more quietly: preflight fires at
second zero so that somebody can fix the world and start again, and a message that does not say
which of *installed*, *current* and *authenticated* failed leaves them guessing.

---

## 6. The operator's own machine configuration reaches the session

**Raised by:** stage 7.1 —
`tests/adapters/test_claude_code_runner.py::test_no_configuration_in_the_workspace_reaches_the_session_it_composes`.

**This entry is free.** No model, no tokens. It is here because the measurement needs a shell
nobody has run it from, not because it needs a paid turn.

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

Compare the three lists against the same command run from inside a Claude Code session. If they are
identical, it is settings discovery; if the plain shell's are empty or smaller, the difference was
inherited environment. Revert the print afterwards.

**If it is wrong** — that is, if the lists are non-empty from a plain shell too, which is the
expected outcome — nothing breaks and nothing is filed. It is recorded so that the next reader of
`options.py` knows that `setting_sources=[]` bounds the **repository** and not the **machine**, and
so that §3.11's "credential-environment isolation, not built" is understood to cover this too. The
consequence only becomes real the day AGL runs somewhere the operator does not control the shell,
which §3.11 names as the revisit condition.

---

## 7. `AskUserQuestion` is vacuous on the CLI version measured

**Raised by:** stage 7.1 — `ASKING_MECHANISMS_DENIED` in
`src/agl/adapters/claude_code/_tools.py`.

**This entry is free**, and it is a **re-check on a CLI upgrade** rather than part of the one-time
pass.

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

Still passing means the CLI still does not offer the tool and the deny rule is still vacuous.
Failing on `AskUserQuestion` means the CLI has started offering it and the deny rule is now doing
real work — which is the good outcome, because it means the guard is live and the assertion has
teeth again. Revert the edit either way.

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

## 8. The contract-suite clauses that read a model's conduct — Codex CLI

**Raised by:** stage 8.0 — `docs/codex-cli-findings.md`, before the adapter exists. It is raised
here rather than left to 8.2 because this file "does not go looking for entries", and the stage that
established what is unverifiable is the stage that knows. **8.2 should correct the module path below
if it names its test file differently**; everything else in this entry survives whatever it is
called.

**Assumed.** That `OpenAiRunner` satisfies the same six clauses of `tests/contracts/agent.py` and its
siblings that entry 1 defers for Claude Code, for the same reason: their evidence is a *model's*
conduct and no free instrument can supply it. The expected shape is the one stage 7.1 settled — a
`runner` fixture handing the suite a subclass whose `run` calls `pytest.skip` unconditionally, so
that the gate sits on the port member that starts an agent rather than on a list of names.

The six are the same six, and the table in entry 1 applies verbatim. The other two —
`test_capabilities_answers_for_the_model_it_was_asked_about` and
`test_check_ready_answers_with_nothing_or_says_why_it_cannot` — run unconditionally against the real
adapter and need nothing here. **For Codex the second of those is genuinely free**, which it is not
for Claude: `codex login status` exits 0 printing `Logged in using ChatGPT` and exits 1 printing
`Not logged in`, measured both ways at stage 8.0, so `check_ready` costs no turn at all and entry 5
has no Codex counterpart.

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
- **Whatever 8.2's loopback settles.** Everything the Claude suite gets from
  `tests/instruments/loopback.py` — the composed request, the registered tools, the frames — is
  available to Codex through the same trick, and stage 8.0 established for free that the endpoint is
  redirectable by configuration (`-c chatgpt_base_url=…`). If 8.2 builds that loopback, this entry
  shrinks to the model's conduct alone; if it does not, this entry is doing more work than entry 1's
  and should say so.

**Command.** Preparation, in `tests/adapters/test_openai_runner.py`: return the real runner from the
`runner` fixture instead of the skipping subclass, and remove whatever points the CLI at the
loopback. Then, on an authenticated machine:

```bash
AGL_LIVE_AGENT=1 .venv/bin/pytest "tests/adapters/test_openai_runner.py::TestOpenAiRunner" -x
```

Revert afterwards. Use the cheapest model in the catalog that the `model` fixture can supply —
`codex debug models` lists what is available and is free.

**If it is wrong.** The consequences are entry 1's, with two Codex-specific differences.

- The tool-calling and refusal clauses failing means more here than there. Claude Code's asking tool
  and reporting tool are hosted in-process by its SDK; Codex's are an **MCP server the adapter runs**
  and Codex connects to. A failure could therefore be the model, the MCP handshake, the transport,
  or `tool_timeout_sec` — four explanations where the Claude side has one. Read
  `docs/codex-cli-findings.md` §0 before concluding it is the model.
- The poisoned-repository clause failing would be a **new finding rather than a regression**, and a
  specific one: stage 8.0 measured that the repository contributes nothing to the *prompt*. A leak
  would therefore have to arrive through a channel that reaches the request without reaching the
  prompt, which is exactly what `codex debug prompt-input` cannot see.

---

## 9. A live Codex agent calling an AGL-supplied MCP tool, and asking through it

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

Three things pass: the handler was called, the file on disk is named `agl_manual_qa_marker`, and the
**90-second sleep did not kill the call** — which is what proves `tool_timeout_sec` was raised
rather than merely intended. Drop the sleep and re-run if it fails, to tell a timeout from a model
that never asked.

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

## 10. `codex exec`'s terminal events against live outcomes

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

That settles `COMPLETED` and the exit code beside it. The other two outcomes have no one-liner and
should be taken opportunistically during the rest of the pass: **`LIMIT`** by running the same
command on an account that has actually exhausted its usage — which is not something to arrange
deliberately, but is worth capturing the moment it happens to anybody — and **`None`** by
interrupting a run mid-stream. Record, for each, the literal `type`, the literal `message`, and the
process exit code.

**If it is wrong.** Entry 3's asymmetry applies here unchanged and is the reason this entry is worth
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

## 11. Codex's remaining configuration channels

**Raised by:** stage 8.0 — `docs/codex-cli-findings.md` §6.

**This entry is free.** No model, no tokens. It is here because two of its three parts need an
instrument that did not exist when the finding was made, and one is a **re-check on a version
bump** rather than part of the one-time pass.

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

**Command.** The first, once 8.2's Codex loopback exists — it needs a real `codex exec`, which is
free against a loopback and must **not** be run against the real endpoint:

```bash
# In 8.2's own test module, with the loopback bound and CODEX_HOME emptied, add --ignore-user-config
# to the composed argv and grep the request that arrives for the marker planted in $CODEX_HOME/AGENTS.md.
```

The second and third are a version re-check and belong wherever `codex --version` is next observed
to have moved:

```bash
codex --version
cd "$(mktemp -d)" && git init -q . \
  && printf 'AGL_RECHECK_AGENTS\n' > AGENTS.md \
  && printf 'model = "gpt-5.4"\n' > .codex/config.toml \
  && codex debug prompt-input -c project_doc_max_bytes=0 X | grep -c AGL_RECHECK_AGENTS
codex doctor --json | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['checks']['config.load']['details'])"
```

What passes: the first prints `0` (the suppression still works), and the second still reports
`model: "<default>"` and a single `config.toml` path under `$CODEX_HOME` (the repository still
cannot configure Codex).

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

## 12. Whether this harness's own MCP client accepts the server AGL runs for it

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

What passes: a payload in `PAYLOADS`, and `Calling: agl/record_note` among the activity lines. A run
that fails at **startup** — the harness reporting it could not initialise the server — is this
entry failing; a run that completes without calling the tool is entry 9's question, not this one.

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

## 13. What stage 8.2 did not build: no loopback for this backend

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
