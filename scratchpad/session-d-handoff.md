# AGL session D — repair handoff

**Repo:** `/Users/jan/Desktop/agl` · **Branch:** `main` · **Date:** 2026-08-29
**State:** uncommitted working tree, holding work from several deliverables. Nothing was committed.

This session was **investigative**. It changed exactly one thing in the repository (§1) and produced
three things a later session owns: a census of dangling citations in `tests/contracts/` (§3), a
settled decision about `--dry-run` (§4), and a settled reading of `HeadlessTerminal` (§5). **Nothing
in §3, §4 or §5 was repaired.** That is deliberate: all three are prose, and prose is the thing this
session was told not to touch.

`scratchpad/review-handoff.md` is the earlier document in this series and this one follows its
format. Read §0 of that file if you have not.

---

## 0. How to read the citations in this document

| Source | Line numbers are… | To resolve them |
|---|---|---|
| §1, §2 (the change) | current working tree | read the file |
| §3 (the census), §4, §5 | current working tree, **post-strip** | read the file |
| Quoted `src/` prose | **pre-strip** | `scratchpad/stripped-comments.md`, or `git show HEAD:<path>` |

Every `file:line` below was resolved with `sed -n` after it was written down. A citation that rots
is the exact failure §3 is about, so they were checked rather than remembered.

**Provenance.** The §3 reading was done by four subagents, one per port family, each given the same
rubric and each required to check every fragment mechanically against `src/` and against the
corpus. I re-adjudicated every disputed row myself against one rule (§3.1) and re-verified all 65
line numbers. §4's and §5's supporting facts I verified myself. Tags as in the earlier handoff:

- **[verified]** — I ran the check and reproduced it.
- **[reported]** — a subagent's finding, cited, not independently re-derived.

---

## 1. What this session changed

**One file added: `tests/test_no_literal_surrogates.py`.** Nothing else in `src/` or `tests/` was
touched. `src/` was not modified at all.

It is a source-reading guard, in the shape `tests/test_ports_stdlib_only.py` and
`tests/adapters/test_filesystem_no_lock.py` established: an AST scan over `src/` and `tests/` that
fails if a lone surrogate is written as a string literal in a position where `mypy` keeps it as a
`Literal` type. §6.1 has the reasoning and the measured table.

**[verified]** `./scripts/check` after the addition:

```
  PASS  pytest
  PASS  mypy --strict
  PASS  ruff check
  PASS  lint-imports
  PASS  codex containment
  WARN  module size      35 of 232 over 300 code lines
  PASS  package root
  PASS  paid-endpoint guard

All 8 gates passed, with 1 warning(s) above - nothing to fix, only to know.
```

`2168 passed, 24 skipped in 164.85s`. The new file contributes 16 of those.

## 2. Acceptance — verify these first

```bash
# the only tree change
git status --short -- src tests | grep test_no_literal_surrogates   # expect: ?? one file
git status --short -- src                                            # expect: nothing new from this session

# the guard is not vacuous: it fires on the two rewrites it exists to catch
.venv/bin/python - <<'PY'
import pathlib, sys
sys.path.insert(0, "tests")
from test_no_literal_surrogates import literal_surrogates
j = pathlib.Path("tests/sdk/test_journal.py").read_text()
print(literal_surrogates(j.replace('Final = chr(0xD800)', 'Final = "\\ud800"')))  # expect: one Finding at 459
i = pathlib.Path("tests/ports/test_ids.py").read_text()
print(literal_surrogates(i.replace('_NON_ASCII: Final = [', '_NON_ASCII: Final = (', 1)
                          .replace(']  # fmt: skip', ')  # fmt: skip', 1))[:1])  # expect: one at 66
PY

# and that the crash is real, not folklore
mkdir -p /tmp/x && printf 'from typing import Final\nX: Final = "\\ud800"\n' > /tmp/x/c.py
cd /tmp/x && rm -rf .mypy_cache && /path/to/agl/.venv/bin/mypy --strict c.py   # expect: INTERNAL ERROR
```

---

## 3. Census: `tests/contracts/` quoting prose that no longer exists

### 3.1 The rule the count is under

`tests/contracts/` argues in a recurring shape — *"the port says X in as many words"*, followed by
a quotation of the port's docstring, which the strip deleted. There is no `§` to grep for, so this
was found by reading all 30 modules (7,811 lines).

Three classes, and the boundary between the first and the third is genuinely fuzzy, so the rule is
written out rather than left to taste:

- **(A) Dangling.** The passage puts text in quotation marks (or uses an explicit citation idiom —
  *"in as many words"*, *"in its own words"*, *"quoted from the port"*, *"`X`'s docstring says"*)
  and attributes it, explicitly or by immediate context, to `src/` prose; and that text is not in
  `src/` today. **This is the defect.**
- **(B)** Same, but the quoted text still exists in `src/` — as an error-message string literal or
  as an identifier, neither of which was stripped. Fine as-is; do not "repair" it.
- **(C)** Everything else: unquoted paraphrase (*"the port says so and gives the reason"*), a
  self-coined gloss in quotes that was never `src/` prose (*"why did this re-run"*), or a quotation
  of a sibling `tests/` module's prose, which is intact.

Two sub-rules, because they decide about twenty rows between them:

1. **A quoted fragment with no attribution counts as (A) if it is verbatim stripped `src/` prose.**
   The reader meets quotation marks and cannot find the source; that is the defect regardless of
   whether the sentence names the port.
2. **Bold or italic standing in for quotation marks counts as (A) when an explicit attribution
   formula precedes it** — *"The port's sentence is that **…**"*, *"the case the port names by
   hand: **…**"*. It is a quotation in everything but punctuation. Where verbatim `src/` prose is
   reproduced with *neither* quotation marks *nor* an attribution formula — the module simply
   writing the port's sentence as its own argument — it is **(C)**.

### 3.2 The hard count

**65 occurrences of (A), across 24 of the 30 modules.**

| file | (A) |
|---|---|
| `tests/contracts/workspace.py` | 7 |
| `tests/contracts/integration.py` | 5 |
| `tests/contracts/history.py` | 4 |
| `tests/contracts/_workspace_steps.py` | 4 |
| `tests/contracts/_history_changes.py` | 4 |
| `tests/contracts/store.py` | 4 |
| `tests/contracts/_agent_preflight.py` | 4 |
| `tests/contracts/clock.py` | 4 |
| `tests/contracts/verifier.py` | 3 |
| `tests/contracts/terminal.py` | 3 |
| `tests/contracts/_agent_tasks.py` | 3 |
| `tests/contracts/_integration_protocol.py` | 3 |
| `tests/contracts/_workspace_files.py` | 2 |
| `tests/contracts/_store_concurrency.py` | 2 |
| `tests/contracts/_terminal_queues.py` | 2 |
| `tests/contracts/agent.py` | 2 |
| `tests/contracts/__init__.py` | 2 |
| `tests/contracts/_store_scopes.py` | 1 |
| `tests/contracts/_terminal_driver.py` | 1 |
| `tests/contracts/_terminal_registration.py` | 1 |
| `tests/contracts/_terminal_slot.py` | 1 |
| `tests/contracts/_terminal_views.py` | 1 |
| `tests/contracts/_agent_questions.py` | 1 |
| `tests/contracts/_agent_hermeticity.py` | 1 |
| **total** | **65** |

Six modules carry none: `_terminal_headless.py`, `_terminal_lifecycle.py`, `_store_documents.py`,
`_workspace_holding.py`, `_workspace_teardown.py`, `_integration_targets.py`. Several of those argue from the port
constantly and simply never put quotation marks round it, so a zero here is not evidence the module
is clean — only that it is (C) throughout. §3.4 lists the four that came closest.

**19 of the 65 are judgement calls** (marked `JC` in §3.3). A strict reading — explicit quotation
marks *and* an explicit attribution to a `src/` module, nothing else — yields **46**. The loosest
defensible reading, which also counts unattributed verbatim reuse of port prose, yields **71**.
**46 / 65 / 71** is the honest band; 65 is the number under the stated rule.

**Zero (B) rows.** Not one fragment quoted from a port survives in `src/` today, as an error message
or otherwise. Three near-misses were checked and are all (C) glosses of *code*, not of prose:
`"file a bug"` (`src/agl/cli/main.py:170`), the exit codes in `src/agl/ports/errors.py:62-70`, and
`_checked_digest` (`src/agl/ports/home_layout.py:122`).

**Two of the 65 are gone entirely** — not in `src/`, and *not in `scratchpad/stripped-comments.md`
either*, so the port never said them in the surviving record. Those two cannot be restored by
quotation and must be rewritten or dropped:

- `tests/contracts/_agent_tasks.py:118` — the port's `"may be omitted"`
- `tests/contracts/_history_changes.py:231` — `"Nothing a person would read"` is the promise

The other 63 are all recoverable verbatim from the corpus.

### 3.3 The table

Status is `REC(<module>)` — recoverable from `scratchpad/stripped-comments.md`, attributed to that
`src/` module — or `GONE` where the corpus has it nowhere. Attribution is what the citing sentence
names: a specific module, or just "the port".

#### `agent` family

| file:line | fragment | attribution | status | |
|---|---|---|---|---|
| `_agent_tasks.py:112` | "the adapter must not block" | the port | REC(`ports/agent.py`) | |
| `_agent_tasks.py:118` | the port's "may be omitted" | the port | **GONE** | |
| `_agent_tasks.py:223` | "N rounds inside one run" | "the clause" | REC(`ports/agent.py`) | JC |
| `agent.py:223` | "the agent said nothing" | "what the port says" | REC(`ports/agent.py`) | |
| `agent.py:414` | "the port explicitly allows - 'an adapter with nothing to report calls it never'" | the port | REC(`ports/agent.py`) | JC — lives in a `pytest.skip()` argument, not in prose |
| `_agent_questions.py:17` | "The two edge cases, **quoted from the port**" + the two bullets at 19-22 | the port | REC(`ports/agent.py`, `AgentRunner.run`) | |
| `_agent_preflight.py:15` | "the port says **in as many words** that it is not one" | the port | REC(`ports/agent.py`, `capabilities`) | |
| `_agent_preflight.py:41` | "What can you do" | none | REC(`ports/agent.py`) | JC |
| `_agent_preflight.py:44` | "some provider" … "a lie in the shape of an answer" | the routing runner | REC(`ports/agent.py`, `AgentRunner`) | JC |
| `_agent_preflight.py:78` | "Can you do it now" | none | REC(`ports/agent.py`) | JC |
| `_agent_hermeticity.py:3` | "The rule, **in as many words**: **the target repo contributes source code and nothing else.**" | "the rule" (§3.5) | REC(`adapters/claude_code/runner.py`, `adapters/openai/runner.py`) | JC — the corpus puts it in two adapters, not the port |

#### `clock`

| file:line | fragment | attribution | status | |
|---|---|---|---|---|
| `clock.py:41` | "the port **spends a section on it** - "Aware, never naive"" | the port | REC(`ports/clock.py`) | |
| `clock.py:59-60` | "The port refuses that clause **in as many words** - "Nothing is promised about two readings… Nor are they promised to increase"" | the port | REC(`ports/clock.py`, `Clock.now`) | |
| `clock.py:72` | "The port grants every one: "any offset will do; UTC is not required here"" | the port | REC(`ports/clock.py`, `Clock.now`) | |
| `clock.py:150` | ""Aware, always" is the whole of the clause" | "the clause" | REC(`ports/clock.py`, `Clock.now`) | |

#### `terminal` family — every one recoverable from `src/agl/ports/terminal.py`

| file:line | fragment | attribution | status | |
|---|---|---|---|---|
| `terminal.py:36` | "the port's own line, "one slot, two queues"" | the port | REC | |
| `terminal.py:350-353` | "**every priority the terminal has been asked for is reported, including the ones with nothing waiting**" + "The port says the second one **in as many words**" | the port | REC(`Terminal.pending`) | |
| `terminal.py:363` | that is what "has been asked for" means | none | REC(`Terminal.pending`) | JC |
| `_terminal_driver.py:26` | "in the order offered" | `Screen.responses` | REC(`Screen.responses`) | |
| `_terminal_queues.py:3` | "the port's own line - "one slot, two queues"" | the port | REC | |
| `_terminal_queues.py:64` | The other half of "always awaited" | the port | REC(`Terminal.show`) | JC |
| `_terminal_registration.py:76` | "`Text`'s **own docstring calls** an empty label ordinary" | `Text` | REC(`Text.value`) | |
| `_terminal_slot.py:3` | "the line the port draws itself - "one slot, two queues"" | the port | REC | |
| `_terminal_views.py:111` | "`Text`'s **docstring says** a blank one is the honest thing to show" | `Text` | REC(`Text.value`) | |

#### `store` family and `verifier`

| file:line | fragment | attribution | status | |
|---|---|---|---|---|
| `store.py:39` | "Exists complete or not at all" | "the clause" | REC(`ports/store.py`) | |
| `store.py:90` | ("a read hands back something the caller owns") | "The port stated the read-side half" | REC(`ports/store.py`) | |
| `store.py:94` | "the port states the copy-in clause and the *when* of it **in its own words**" | `ports/store.py` | REC(`ports/store.py`) | JC — idiom variant, no quote marks |
| `store.py:96` | the paragraph after "`Mapping` on the way in" | the port | REC(`ports/store.py`) | |
| `_store_concurrency.py:5` | "a written value exists complete or not at all" | "one clause" | REC(`ports/store.py`) | |
| `_store_concurrency.py:274-275` | "a reader sees either the whole of a value or nothing recorded at that address" … "never a mixture of two values" | "The port's sentence" | REC(`ports/store.py`) | |
| `_store_scopes.py:4-5` | "which **the port's own docstring calls** the one place it asks an implementation for more" | the port's docstring | REC(`ports/store.py`, `namespaces`) | |
| `verifier.py:69` | "Exactly as the user wrote it, operators and all" | the port | REC(`ports/verifier.py`, `verify`) | |
| `verifier.py:85-86` | "The port **warns in as many words** that a reader who takes this field for one runner's convention…" | the port | REC(`ports/verifier.py`, `VerifierOutcome.status`) | JC — the continuation at :87 is italics, not quotes |
| `verifier.py:280-281` | "The port says it **in as many words**: raising would put "your tests are red" in the same bucket as "the runner is not installed"" | the port | REC(`ports/verifier.py`) | |

#### `tests/contracts/__init__.py`

| file:line | fragment | attribution | status | |
|---|---|---|---|---|
| `__init__.py:27` | "the target repo contributes source code and nothing else" | "the port" (loosely) | REC(both `runner.py`s) | JC — grammar points at the port, corpus puts it in two adapters |
| `__init__.py:29-30` | "that port **exposes** a `Path` on purpose and **says why** - "a workspace genuinely is a directory: an agent is pointed at one and a verifier's working directory is one"" | the `Workspace` port | REC(`ports/workspace.py`) | |

#### `workspace` family — every one recoverable from `src/agl/ports/workspace.py`

| file:line | fragment | attribution | status | |
|---|---|---|---|---|
| `workspace.py:22-23` | "one isolated checkout, already provisioned: where it is, what it is called, and the three things a step does to it" | `Workspace` | REC(class docstring) | |
| `workspace.py:73` | "Take the isolated place back" | the port (`remove`) | REC(`WorkspaceProvider.remove`) | |
| `workspace.py:100` | "The port says `base` is consulted "only when provisioning"" | the port | REC(`open`) | |
| `workspace.py:106-107` | "Take the isolated place back" (second occurrence) | the port (`remove`) | REC(`remove`) | |
| `workspace.py:110-111` | "The port's sentence is that … "invisible to every other checkout until somebody lands it"" | the port | REC(module docstring) | |
| `workspace.py:224-225` | "port's sentence is that **an existing workspace is returned exactly as it stands, with whatever the previous attempt left in it**" | the port | REC(`open`) | JC — bold, not quotes |
| `workspace.py:234` | "The port says "hand back the one already there"" | the port | REC(`open`) | |
| `_workspace_files.py:11-12` | "`path` is a `Path` because "a workspace genuinely is a directory: …"" | this port | REC(module docstring) | |
| `_workspace_files.py:20` | "`Workspace.head` says the value it answers with "is also the vocabulary `History` accepts"" | `Workspace.head` | REC(`Workspace.head`) | |
| `_workspace_steps.py:3-4` | "`Workspace` is "one isolated checkout, already provisioned: …"" | the port | REC(class docstring) | |
| `_workspace_steps.py:12-13` | "restored but not cleaned" | implicit | REC(`restore`) | JC — attribution implicit |
| `_workspace_steps.py:19` | "**`commit_all` is a no-op when nothing is dirty.** The port says so **in as many words**" | the port | REC(`commit_all`) | |
| `_workspace_steps.py:147` | what "the workspace is the unit of isolation" means | implicit | REC(`commit_all`) | JC — attribution implicit |

#### `history` family

| file:line | fragment | attribution | status | |
|---|---|---|---|---|
| `history.py:40-41` | "The port says a commit id from `Workspace.head()` "is also the vocabulary `History` accepts … which is honest because one adapter package implements both ports over one repository"" | the port | REC(`ports/workspace.py`, `Workspace.head`) | |
| `history.py:109` | "The port asks "is X already in Y"" | the port | REC(`ports/history.py`, `contains`) | |
| `history.py:119-120` | "**The class docstring says** … "a ref or a commit id that names nothing in this repository"" | the class docstring | REC(`ports/history.py`, `History`) | |
| `history.py:334` | ""`True` for exactly the refs `resolve` answers for, and `False` for exactly the refs `resolve` refuses" is the clause" | the port (`exists`) | REC(`ports/history.py`, `exists`) | |
| `_history_changes.py:7-9` | "The port pairs this last two explicitly - "one is for deciding, the other is for reading. …"" | the port | REC(`ports/history.py`, `diff`) | |
| `_history_changes.py:33` | "`changed_files` is careful to say what it does *not* fix - "its order is the implementation's, and nothing here promises one"" | `changed_files` | REC(`ports/history.py`) | |
| `_history_changes.py:197` | ""Directional, `base` to `head`" - and the port says swapping is a question" | the port | REC(`ports/history.py`, `changed_files`) | |
| `_history_changes.py:231` | ""Nothing a person would read" is the promise." | "the promise" | **GONE** | JC |

#### `integration` family — every one recoverable from `src/agl/ports/integration.py`

| file:line | fragment | attribution | status | |
|---|---|---|---|---|
| `integration.py:28` | "the port itself sets apart as "a protocol they share"" | the port | REC(`Integrator`) | |
| `integration.py:72` | "in the same place **the port's own docstring sends them**" | the port's docstring | REC(module docstring) | JC — no quoted text; the signpost it names is gone |
| `integration.py:121-122` | "The port accepts that cost **in as many words** … no third outcome for "opened, and waiting"" | the port | REC(module docstring) | |
| `integration.py:132-133` | "The port says `land` puts what the source holds into the target … "the target's state after the work landed"" | the port | REC(`IntegrationOutcome.head`) | |
| `integration.py:353` | where "not resolved by guessing" is asserted | "the port's clause" | REC(`Integrator`) | JC |
| `_integration_protocol.py:3-4` | "`land` is the question "is this work in the target now, or not"" | "the line the port draws itself" | REC(module docstring) | |
| `_integration_protocol.py:5-7` | "**…the run must call `retry` or `abort` on every path out of that hold…**" + "**The port calls that** a contract rather than a convention" | the port | REC(`Integrator`) | JC — bold, not quotes |
| `_integration_protocol.py:109-111` | "the case **the port names by hand**: **a person who finished the held landing themselves lands in this same state…**" | the port | REC(`Integrator.abort`) | JC — bold, not quotes |

### 3.4 The six rows that a different rule would add

Excluded under §3.1's sub-rule 2, and each defensibly (A) if unattributed verbatim reuse counts:

| file:line | why excluded |
|---|---|
| `agent.py:195` | `a runner asked "what can you do" with no model named` — verbatim port prose, but the whole sentence is reproduced as the module's own argument and the quote marks are the port's own scare-quotes |
| `_terminal_headless.py:87` | `"stuck" and "waiting for you" look alike from outside` — verbatim `ports/terminal.py`, quote marks included, no attribution at all |
| `history.py:382-384` | `decide between "tidy up" and "leave it alone"` — verbatim from `contains`, but reads as scare-quoted option labels |
| `_workspace_holding.py:7` | `"this run is live"` — verbatim (`adapters/git/_trees.py`, `api.py`), no attribution |
| `_store_documents.py:24` | `"reads back equal"` — quoted, attributed to a port promise, but **matches nothing** in `src/` or the corpus; an invented shorthand |
| `_store_documents.py:71` | `the "nothing recorded is not a recorded null" clause` — same; the nearest real sentence is `sdk/_engine/journal.py`'s "A `None` here is a recorded null, not an absence" |

The last two are their own small finding: quoted *clause names* the suite coined and attributed to
the port. They were never citations, but they read as ones, and a repair session will hit them.

### 3.5 A second defect class the reading exposed — dangling **pointers**

Not counted in the 65, because nothing is quoted, but the same rot:

- **[reported]** `tests/contracts/agent.py:388` — "`ports/agent.py` carries the argument in full."
  The argument (four paragraphs on a raising `on_activity`) is gone from `src/`.
- **[reported]** `tests/contracts/integration.py:72` is the same shape and *is* counted, because it
  uses the "the port's own docstring" formula. The two should be repaired together either way.
- Any sentence of the form "see the module docstring" that points at a `src/` module is now a
  pointer to nothing. This census did not enumerate them; a repair session should.

**One disambiguation the repair depends on.** `tests/contracts/` cites `store.py`, `terminal.py`,
`workspace.py`, `history.py`, `integration.py`, `agent.py` and `verifier.py` constantly, and each
name is *both* a `tests/contracts/` sibling and a `src/agl/ports/` module. The split is by subject:
a citation about **the suite** ("`store.py` says why at more length", "`terminal.py`'s gaps say so",
"`WorkspaceContract` in `workspace.py` inherits this class") means the sibling and is intact; a
citation about **the port** ("the port says", "`ports/store.py`") means `src/` and is dangling.
Roughly a dozen rows were classed (C) on this basis. **[verified]** for the `terminal.py` and
`store.py` cases — `tests/contracts/terminal.py` really does carry the "gaps" and "assumptions"
sections it is cited for, and `tests/contracts/store.py:146` really does carry the "one knob"
argument. Getting this backwards is the easiest way for a repair to break something that works.

---

## 4. Decision: stop citing `--dry-run`; do not build it

**Settled and ratified by the user. Recorded here because the repair is prose and belongs to a
later session.** Do not reopen it; do not build the flag.

> **Decision: stop citing `--dry-run`; do not build it.** `agl run` declares only `<workflow>`,
> `-n/--name` and `--from`. 39 citations across 12 test files argue from a `--dry-run` that does
> not exist. Building it was rejected on evidence: (1) it would ship broken on both shipped
> workflows — `fix` hits `HeadlessTerminal`'s refusal because it routes its implementer's questions
> to an interactive screen, already recorded at `tests/workflows/test_fix.py:746`; `split` never
> reaches its conflict screen because the default fake's `report_chunks` payload gives an empty
> `items`, which `Chunks.__post_init__` refuses; (2) `agl run` forwards unrecognised flags to the
> workflow via `parse_known_args`, and `tests/sdk/test_params.py:167` asserts `--dry-run` is a
> spelling a workflow may legally declare — so shipping it silently makes any such workflow
> unreachable; (3) `tests/cli/test_run_command.py:201` asserts `vars(parsed)` whole, and the prose at
> `:193-195` says a fourth key would be the generic parser having learned something about a
> workflow; (4) it
> would read none of the user's code (`FakeRepository` is one empty commit on `main`), ignore
> `--from`, and be neither resumable nor clearable (`MemoryStore` persists nothing).
>
> **The replacement anchor is `agl.testing`** — a shipped, public, documented layer whose entire
> surface is `container.fakes()`, used by workflow authors on their own machines. That is a genuine
> non-test consumer, which is what "a product feature, not a test artifact" was reaching for.
> Target #8 supplies the mechanical half.
>
> **Work: 23 mechanical rewords** (substitute "a run on fakes" / "`agl.testing`"), **4 that are
> wrong today regardless** — the two "`--dry-run` dashboard" claims at
> `tests/adapters/test_openai_fake.py:990` and `:1017` assume a terminal that draws, and
> `tests/adapters/test_git_fake.py:190` and `tests/adapters/test_memory_store.py:86` argue
> per-process isolation that process isolation already supplies — and **12 that need genuinely new
> reasoning**, of which the four "install story" ones are the hard core:
> `tests/config/test_container.py:190`, `tests/adapters/test_openai_fake.py:38` and `:801`,
> `tests/adapters/test_claude_code_fake.py:662`. Those argue about an *operator's* machine with no
> pip extras installed, and a workflow author running pytest has a dev environment. If it turns out
> there is no operator-facing reason for the no-extras property, those tests are pinning something
> nobody needs — and that is a finding, not a reword.

### 4.1 Every fact above, re-checked

**[verified]** unless noted.

| Claim | Where it resolves |
|---|---|
| `agl run` declares only `<workflow>`, `-n/--name`, `--from` | `src/agl/cli/commands/run.py:22-23` (`_LABEL_FLAGS = ("-n", "--name")`, `_BASE_REF_FLAGS = ("--from",)`) and the three `add_argument` calls at `:42`, `:47`, `:54` |
| `parse_known_args` forwards the tail | `src/agl/cli/main.py:60` |
| `fix` routes to an interactive screen and `HeadlessTerminal` refuses | `tests/workflows/test_fix.py:746` — "**It asks nothing.** The harness builds a `HeadlessTerminal`, `fix` routes its implementer's questions to an interactive screen, and that pairing is a refusal" |
| the default fake answers an array field with `[]` | `src/agl/adapters/claude_code/fake.py:196-197` (`if kind == "array": return []`) |
| `Chunks.__post_init__` refuses an empty `items` | `src/agl/workflows/split/chunks.py:42-49` |
| `--dry-run` is a legal workflow flag spelling | `tests/sdk/test_params.py:167` — the `parametrize` row |
| the whole-namespace assertion and its "fourth key" prose | **prose at `tests/cli/test_run_command.py:193-195`, assertion at `:201`** |
| `FakeRepository` is one empty commit on the default branch | `src/agl/adapters/git/_snapshots.py:50-59` — `default_branch="main"`, `self._branches[default_branch] = self.record(dict(files or {}), (), _INITIAL)` |
| `MemoryStore` persists nothing | `src/agl/adapters/filesystem/memory_store.py:23-25` — two dicts, no disk |
| `agl.testing.harness` is the only non-test caller of `container.fakes()` | `src/agl/testing.py:185`, inside `harness` (defined at `:175`). No other `container.fakes(` call exists under `src/` |
| the four "wrong today regardless" rows | `tests/adapters/test_openai_fake.py:990`, `:1017`; `tests/adapters/test_git_fake.py:190`; `tests/adapters/test_memory_store.py:86` — all four resolve to `--dry-run` prose |
| the four "install story" rows | `tests/config/test_container.py:190`, `tests/adapters/test_openai_fake.py:38`, `:801`, `tests/adapters/test_claude_code_fake.py:662` — all four resolve |

**Both corrections have been applied to the decision text above.** They are recorded here because
this document's whole subject is citations that rot, and it would be a poor advertisement for the
census if its own two errors were silently overwritten:

1. The decision first cited `tests/cli/test_run_command.py:200`, which is a **blank line**. It now
   cites the assertion at **`:201`** and the prose at **`:193-195`** separately.
2. The decision first said **five** "install story" rows and listed **four**. There is no fifth; it
   now says four.

**The 39/12 arithmetic, reproduced.** `grep -rn -- "--dry-run" tests/` gives **40 occurrences across
13 files**. The thirteenth file is `tests/sdk/test_params.py`, whose single occurrence is the
`parametrize` row asserting `--dry-run` is a legal *workflow* flag — evidence *for* the decision,
not a citation arguing from the feature. Exclude it and the count is exactly **39 across 12 files**.
The twelve, with counts: `test_openai_fake.py` 13, `test_git_parity.py` 8, `test_claude_code_fake.py`
6, `test_store_parity.py` 3, `test_git_fake.py` 2, and one each in `test_filesystem_no_lock.py`,
`test_headless_terminal.py`, `test_memory_store.py`, `test_shell_verifier.py`,
`tests/config/test_container.py`, `tests/contracts/agent.py`, `tests/sdk/test_journal_entries.py`.

Note the last two of those: **`tests/contracts/agent.py` is in the list**, so the `--dry-run` repair
and the §3 repair overlap in one file. And `tests/adapters/test_filesystem_no_lock.py` — the guard
this session took as its house-style precedent — carries one, in its own test docstring.

---

## 5. `HeadlessTerminal`, settled

**The wiring is right and the suite's premise is wrong.** Settled; recorded for the repair session.

`tests/contracts/terminal.py:25` calls it "the one that runs unattended", and
`tests/adapters/test_headless_terminal.py:26-27` builds three cost assertions on "an ordinary hour"
— but `container.fakes()` is its only construction site, its only non-test caller is
`agl.testing.harness`, and a run on fakes cannot take hours: the agent fakes return synchronously
and `ManualClock` does not move. The genuinely unattended need — AGL in CI against real agents with
no TTY — is a different thing, and `ARCHITECTURE.md`'s "No `presentation/` layer or `Display` port"
already declines it.

**The three assertions are good and must not move.** The repair is two docstrings: say it is the
terminal every `container.fakes()` bundle gets, and that a workflow shows its board on every pass
through its loop, so a per-`show` retention is a leak in the bundle every AGL command is driven
end-to-end on. `BOARDS = 1_000` survives as "a workflow loop's worth", not "an hour". **No `src/`
change.**

### 5.1 Every fact above, re-checked — all **[verified]**

| Claim | Where it resolves |
|---|---|
| "the one that runs unattended" | `tests/contracts/terminal.py:25` |
| "runs unattended for hours" and the three cost claims under it | `tests/adapters/test_headless_terminal.py:26-27`; the three bullets at `:29-33`, `:34-37`, `:38-41` |
| "an ordinary hour" | **also `tests/adapters/test_headless_terminal.py:87-88`** — the attribute docstring on `BOARDS`. Two places, not one; both need the edit |
| `BOARDS: Final = 1_000` | `tests/adapters/test_headless_terminal.py:86` |
| `container.fakes()` is the only construction site | `src/agl/config/container.py:105` is the only `HeadlessTerminal()` in `src/`; the only other mentions are its own module and the import at `container.py:23` |
| the only non-test caller is `agl.testing.harness` | `src/agl/testing.py:185` |
| `ARCHITECTURE.md` declines the CI case | `ARCHITECTURE.md:159`, "Deliberately not built" |

**One thing that makes the repair easier than it looks:** the replacement wording already exists in
the file. `tests/adapters/test_headless_terminal.py:31` already says "a workflow loop's worth of
boards and a hundred refused questions". The docstring at `:26-27` and the `BOARDS` docstring at
`:87-88` are the two places still saying "hours" and "an ordinary hour"; the assertion prose
underneath them is already right.

---

## 6. Other things this session exposed — named, not fixed

### 6.1 The `mypy` surrogate crash is wider than the comment says (this one *was* acted on)

The comment at `tests/sdk/test_journal.py:448-458` is **accurate and insufficient**. Accurate: a
module-level `Final` holding a lone-surrogate literal really does crash `mypy --strict` with an
`INTERNAL ERROR` naming no file, `Final[str]` really does not help, and `chr(0xD800)` really is the
fix. Insufficient in two ways, both measured against `mypy 2.3.1` on Python 3.14 by writing scratch
files and running the real checker:

| Written as | `reveal_type` | Verdict |
|---|---|---|
| `X: Final = "\ud800"` | `Literal['\ud800']?` | **crash** |
| `X: Final[str] = "\ud800"` | keeps the literal | **crash** |
| `X: Final = ("\ud800", "a")` | `tuple[Literal[…]?, Literal[…]?]` | **crash** |
| `class K: X: Final = "\ud800"` | keeps the literal | **crash** |
| `class K(StrEnum): A = "\ud800"` | an enum member's value | **crash** |
| `def f(x: Literal["\ud800"]) -> None` | the annotation itself | **crash** |
| `X: Final = ["\ud800", "a"]` | `list[str]` | fine |
| `X: Final = {"\ud800": 1}` | `dict[str, int]` | fine |
| `X: Final = frozenset({"\ud800"})` | `frozenset[str]` | fine |
| `X: Final[tuple[str, ...]] = ("\ud800",)` | the declared type | fine |
| `X = "\ud800"` (no `Final`) | `str` | fine |
| `def f() -> None: X: Final = "\ud800"` | a local, never cached | fine |
| `X: Final = chr(0xD800)` | `str` | fine |
| `--cache-dir=/dev/null`, any of the above | — | fine |

**First**, the comment says "only a module constant is affected". A class-level `Final`, an enum
member and a `Literal[...]` annotation crash too.

**Second, and this is the one that matters for this repo:** a `Final` **tuple** crashes and a
`Final` **list** does not — a join erases the literal, a tuple keeps one per element.
`tests/ports/test_ids.py:66` and `tests/ports/_corpus.py:44` both hold `"\ud800"` inside a
module-level `Final` **list**, so they are green *because somebody wrote `[` and not `(`*, and
nothing anywhere writes that down. Both are frozen tables of constants in a repository that reaches
for immutability everywhere else — `ANSWER_TOKENS: Final = ("alpha-K41", "bravo-Q73")` at
`tests/contracts/_agent_tasks.py:217` is the same shape written the other way — so "make this
constant a tuple" is a one-character edit somebody will propose, and it fails the types gate with no
file named.

That is why this got a mechanical guard and not another paragraph. A comment sits above one
constant; the two files that are safe by accident carry no comment at all; and the failure mode is
the worst diagnostic in the build. **`tests/test_no_literal_surrogates.py`** is the guard, with the
table above in its docstring and one non-vacuity case per row. It fires on exactly the two edits it
exists to catch and is silent on the tree as it stands (§2 has the check). The comment at
`test_journal.py:448-458` was **left alone** — it carries the history and the guard's message points
at it — but it is now not the only thing holding the rule.

### 6.2 `tests/contracts/` cites `--dry-run`

`tests/contracts/agent.py` carries one of the 39. A suite whose own docstring forbids naming an
adapter is arguing from a CLI flag. Not repaired; it belongs to §4's sweep.

### 6.3 The census's judgement calls are a convention question, not a reading question

19 of 65 turn on punctuation — whether bold, italics or bare verbatim reuse counts as a quotation.
`CLAUDE.md` says the comment convention that replaces the stripped docstrings is "being written
separately and pending". **That convention should settle this**, and the §3 count should be re-run
against it rather than the repair session re-litigating each row. If bold-with-attribution stops
counting, the number is 46; if unattributed verbatim reuse starts counting, it is 71.

---

## 7. Artefacts

| Path | What it is | Tracked? |
|---|---|---|
| `tests/test_no_literal_surrogates.py` | the one change this session made; §1, §6.1 | **yes — this is the deliverable to review** |
| `scratchpad/session-d-handoff.md` | this document | no |
| `scratchpad/stripped-comments.md` | the recovery corpus every §3 row resolves against | no |
| `scratchpad/review-handoff.md` | the earlier handoff in this series | no |

## 8. Scope note

The session was told: investigate, do not repair, do not touch `src/`. It did not touch `src/`.
The single write outside `scratchpad/` is `tests/test_no_literal_surrogates.py`, which the brief
explicitly sanctioned if the recommendation came out in favour of a guard. Everything in §3, §4, §5
and §6.2–§6.3 is **report only** — no prose was reworded, no citation was repaired, and no
`--dry-run` reference was touched.

```bash
git status --short   # expect: this session adds exactly one ?? file under tests/
./scripts/check      # expect: all 8 gates pass, one module-size warning
```
