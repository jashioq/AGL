# Codex CLI capability findings — deliverable 8.0

What the OpenAI Codex CLI can and cannot be asked for, measured against `src/agl/ports/agent.py`.
Written for the implementers of 8.1 (`adapters/openai/translate.py`), 8.2
(`adapters/openai/runner.py`) and 8.3 (`adapters/openai/fake.py`), who should be able to build
against this document without re-deriving any of it.

**No paid call was made to produce any of it.** `codex exec` was never run — not once, not with a
trivial prompt. Everything below comes from `--help` on the installed binary, from commands that
provably reach no model (`codex sandbox`, `codex doctor`, `codex login status`, `codex mcp list`,
`codex debug prompt-input`, `codex debug models`, `codex features list`), from string literals
inside the shipped executable, from OpenAI's published documentation, or from reasoning over those.
Where a claim genuinely needs a paid turn it is deferred to `docs/manual-qa.md` entries 8–11 and
named here as deferred.

## How to read the evidence labels

Five labels, and they are not interchangeable. The point of separating them is that an implementer
should always know how much weight a line will bear.

- **Measured.** A command was run on this machine and its output read. Every measured claim has a
  reproduction in the appendix, and every one of them is free.
- **Documented.** `codex --help` on the installed binary, or OpenAI's published documentation.
  **The docs moved**: every `developers.openai.com/codex/*` URL now redirects to
  `learn.chatgpt.com/docs/*`, and the useful machine-readable artefacts are
  `learn.chatgpt.com/docs/config-schema.json` and `learn.chatgpt.com/docs/codex-manual.md`. The site
  is **unversioned and tracks the current release**, so a documented claim is not automatically a
  claim about 0.149.0 — where the two disagree, this document says so.
- **Read off the binary.** A string literal extracted with `strings` from
  `/opt/homebrew/Caskroom/codex/0.149.0/bin/codex`. This says what is *written in the shipped
  program* — a serde field name, an error message, a match arm's text — for **this exact version**.
  It is strong on vocabulary and on which code paths exist, and it is **not** evidence that a path
  is reached at runtime.
- **Read off the source.** `openai/codex` on GitHub, principally `codex-rs/exec/src/exec_events.rs`
  and `codex-rs/exec/src/lib.rs`. Same caveat as documentation: `main`, not 0.149.0.
- **Inferred.** Reasoning from the above. Always labelled, never blurred into the others.

Several claims below are supported by more than one label reaching the same answer from different
directions — a serde tag in the 0.149.0 binary and the same tag in `exec_events.rs` on `main`, say.
Where that happens it is said, because independent agreement is most of what makes a finding safe to
build on.

## Environment these findings were taken in

```bash
codex --version && codex login status && sw_vers -productVersion
```

At the time of writing: `codex-cli 0.149.0`, `/opt/homebrew/bin/codex` → a symlink into
`Caskroom/codex/0.149.0`, `Logged in using ChatGPT`, macOS (darwin 25.4.0). `~/.codex/` contains
`auth.json` and nothing else — **no `config.toml`**, which matters: every default quoted below is
the packaged default and not this operator's preference.

Sandbox findings are macOS Seatbelt findings. Linux/WSL2 requires `bubblewrap` and Windows has a
native sandbox; the *policy names* are the same and the enforcement is not the same code. Nothing
below has been checked on any other platform.

---

# 0. The headline: caller-supplied tools work, but not the way Claude's do

`AgentTask.tools` carries framework-defined tools with JSON Schema payloads and async handlers, and
the adapter must invoke the handler and feed `ToolResult.text` back **inside the same session**
(§3.3). This is the finding the stage asked to be stated first, so here it is first.

**Codex CLI accepts caller-supplied tools. The channel is MCP, it needs no file on disk, and it
works from the command line alone.** Measured: an MCP server can be declared entirely through `-c`
overrides, in both transports, with no `config.toml` anywhere —

```bash
codex mcp list --json -c 'mcp_servers.agl.command="/bin/echo"' -c 'mcp_servers.agl.args=["hi"]'
codex mcp list --json -c 'mcp_servers.agl={url="http://127.0.0.1:8765/mcp"}'
```

— and both come back as a configured server, the first as `"transport": {"type": "stdio", …}` and
the second as `"transport": {"type": "streamable_http", …}`. `-c` is present on `codex exec` with
the same one-line help as on `codex mcp`, so the same overrides are available to a run. The
documentation covers `mcp_servers` as a config table and covers `-c` as a generic override, but
**never shows the two combined** — the combination is measured here rather than documented, which
is the stronger of the two but is also a shape nobody has promised to keep.

**MCP works in `codex exec`.** Documented indirectly but unambiguously: an enabled server with
`required = true` that fails to initialise makes `codex exec` exit with an error. Corroborated by
`mcp_tool_call` being one of the exec stream's own item kinds (§1) — a frame kind for a thing that
could not happen would be dead code.

**But the shape of the bridge is different from Claude's and 8.2 must budget for it.** Claude Code's
SDK hosts an MCP server *in the adapter's own process*, which is why `_tools.py` can hand the SDK a
Python object and have `Tool.handler` invoked directly. Codex has no in-process option: **Codex is
the MCP client and it starts the server itself**, either as a subprocess it spawns (stdio) or as an
HTTP endpoint it connects to. A closure over the framework's `Run`, store and terminal cannot be
serialised into a subprocess, so the honest architecture is:

> The adapter runs a **streamable-HTTP MCP server bound to `127.0.0.1` on an ephemeral port, inside
> the AGL process**, exposes `task.tools` on it, and passes
> `-c 'mcp_servers.agl={url="http://127.0.0.1:<port>/mcp"}'` to `codex exec`. The handler runs where
> it already lives; only the transport changes.

That is a recommendation, not a measurement. What is measured is that the configuration reaches
Codex; that a live Codex session then lists and calls the tool is deferred to `manual-qa.md`
entry 9, and 8.2 can settle most of it against a loopback for free (§7).

**And it cannot be settled with `codex debug prompt-input`**, which is the free instrument most of
the rest of this document rests on. That command renders the model-visible **prompt input list** —
developer and user messages — and **not the tool list**. It is silent on which tools a configuration
offers the model, so it can neither confirm nor refute that `mcp__agl__*` is registered. Reaching
for it here is the obvious wrong turn and it would produce a confident non-answer.

**Four consequences worth knowing before writing any code.**

- **Tool names are prefixed `mcp__<server>__<tool>`.** Documented (the hooks reference gives
  `mcp__fs__read` as an example) and corroborated by the binary's own embedded prompt text. Same
  convention as Claude Code, arrived at independently — which is convenient and is *not* a reason to
  put the convention in the port. Note that the docs now call `mcp__` the **legacy** prefix and ship
  `features.non_prefixed_mcp_tool_names` (with `enabled` and a `server_names` list) to drop it;
  measured **off** on this build. A future default flip would rename every AGL tool the model sees.
- **The default tool timeout is 60 seconds.** Documented: `mcp_servers.<id>.tool_timeout_sec`
  defaults to 60, `startup_timeout_sec` to 10. **This is the number that decides whether
  `MID_RUN_QUESTIONS` is real** — an asking tool waits on a person, and a person takes longer than a
  minute. 8.2 must raise it deliberately. See §4.
- **Approval on MCP tool calls has to be neutralised.** `RawMcpServerConfig` carries
  `default_tools_approval_mode`, `tools.<tool>.approval_mode`, `enabled_tools` and `disabled_tools`
  (documented; the extra keys were confirmed accepted by
  `codex mcp list --json -c 'mcp_servers.agl={…,enabled_tools=["ask"],tool_timeout_sec=600}'`). The
  approval-mode values in the binary are `auto`, `writes`, `approve`, `auth`, `required`. In
  `codex exec` **no approval can ever be granted** (§3), so an AGL server must not be in a mode that
  asks. `auto` is the value to reach for; that it is the never-ask value is **inferred** from the
  name and 8.2 should confirm it against a loopback before relying on it.
- **A repository could ship an MCP server of its own** through project-level configuration. On this
  build it cannot — see §6, where that is measured — but the mechanism is documented and the
  measurement is of one version.

**What does not work, and it is worth knowing why the obvious thing is the wrong thing.** Codex has
a second, richer caller-tool mechanism — `DynamicToolSpec` / `DynamicToolCallRequest`, with
`inputSchema` and `deferLoading`, driven over the app-server JSON-RPC protocol (read off the
binary). It is exactly the shape `AgentTask.tools` wants. It is also unavailable: the 0.149.0 binary
contains the literal string

> `dynamic tool calls are not supported in exec mode for thread `

alongside six siblings refusing every approval path in the same mode, and the source confirms these
are JSON-RPC error `-32000` rejection handlers installed by exec itself. **MCP is the only tool
channel `codex exec` has**, and an implementer who finds `DynamicToolSpec` in the app-server
documentation should stop rather than switch to `codex app-server`, which would be a different
harness with a different lifecycle and no `--sandbox` flag.

**Recommendation:** `capabilities()` reports `TOOL_CALLING`. The mechanism exists, is reachable from
argv alone, and is the same mechanism the reporting step (§3.3) needs. Confidence: high on the
configuration, medium on the round trip until a loopback or entry 9 has watched a tool result go
back into a session.

---

# 1. Non-interactive invocation and structured output

## The argv shape

```
codex exec [OPTIONS] [PROMPT]
```

`codex e` is an alias. The prompt is either the positional argument, or `-`, or absent — in the last
two cases "instructions are read from stdin", and "if stdin is piped and a prompt is also provided,
stdin is appended as a `<stdin>` block" (documented, `codex exec --help`).

**Send the prompt on stdin, not as argv.** §3.5's rule is that every value reaching a command line
is hostile, and a workflow author's instructions are the largest untrusted string in the system: a
prompt beginning with `-` parses as a flag, and a long one meets `ARG_MAX`. The Claude adapter took
the same decision for the same reason and recorded it in `runner.py`. Codex offers the stdin route
explicitly, so 8.2 has no excuse for the other one.

The options that matter here, all documented on `codex exec --help` for **this** build:

| Flag | What it is for |
|---|---|
| `--json` | JSONL event stream on stdout. `--experimental-json` is an alias for the same argument, not a second mode (read off the binary; confirmed in `exec/src/cli.rs`). |
| `-C, --cd <DIR>` | The working root. **This is `AgentTask.workspace`.** A directory, not a string anything parses — but it *is* on argv, so the `-`-prefix guard applies. |
| `-m, --model <MODEL>` | Model slug. See "Ambiguity" for which slug. |
| `-s, --sandbox <MODE>` | `read-only` \| `workspace-write` \| `danger-full-access`. §3. |
| `-a, --ask-for-approval <POLICY>` | `on-request` \| `never`. §3 — and read §3 before assuming it does anything. |
| `-c, --config <key=value>` | Arbitrary config override, dotted path, value parsed as TOML with a literal-string fallback. Hermeticity and tool supply both ride on this. |
| `-o, --output-last-message <FILE>` | Writes the agent's final message to a file (and still prints it). A second route to `AgentOutcome.text`. |
| `--output-schema <FILE>` | JSON Schema for the model's final response shape. Not used — §9, pressure 8. |
| `--ephemeral` | "Run without persisting session files to disk". |
| `--ignore-user-config` | "Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`". |
| `--ignore-rules` | "Do not load user or project execpolicy `.rules` files". §6. |
| `--skip-git-repo-check` | Allow running outside a git repository. AGL's workspaces are worktrees, so this should not be needed. |
| `--color <always\|never\|auto>` | Set to `never`. Nothing here parses ANSI. |

There is **no `--max-turns`**, no timeout flag and no budget flag. That is consistent with
`AgentTask` having no timeout and no budget by design (§3.7), and it is why `StopReason.LIMIT` is
nearly unreachable for this backend — see §5.

One discrepancy to know about: the current documentation describes `codex exec` as having
`--full-auto` and as *not* having `-a/--ask-for-approval`. The installed 0.149.0 has the opposite:
`-a` is present, `--full-auto` is not. **Trust `codex exec --help` on the installed binary over the
docs for flag existence**, and see §3 for what `-a` actually achieves.

## The JSONL schema

Established twice, independently: from the serde tag table `exec/src/lib.rs` contributes to the
0.149.0 binary's string pool, and from `codex-rs/exec/src/exec_events.rs` on `main`. **The two
agree**, which is why the field names below are stated plainly rather than hedged.

Envelope: eight `type` values.

| `type` | Payload |
|---|---|
| `thread.started` | `thread_id` |
| `turn.started` | — |
| `turn.completed` | `usage` |
| `turn.failed` | `error` |
| `item.started` | `item` |
| `item.updated` | `item` |
| `item.completed` | `item` |
| `error` | `message` |

`usage`: `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`,
`reasoning_output_tokens`. `error` is a `ThreadErrorEvent`, i.e. `{ "message": … }`.

An item is `{ "id": …, "type": <kind>, …kind's fields }` — the discriminator inside the item is
**`type`**, flattened, not `item_type` (read off the source: `ThreadItem` flattens
`ThreadItemDetails`, which is `#[serde(tag = "type", rename_all = "snake_case")]`). Nine kinds:

| Item `type` | Fields |
|---|---|
| `agent_message` | `text` |
| `reasoning` | `text` |
| `command_execution` | `command`, `aggregated_output`, `exit_code`, `status` |
| `file_change` | `changes[]` (`path`, `kind` ∈ `add`/`delete`/`update`), `status` |
| `mcp_tool_call` | `server`, `tool`, `arguments`, `result`, `error`, `status` |
| `collab_tool_call` | `tool`, `sender_thread_id`, `receiver_thread_ids`, `prompt`, `agents_states`, `status` |
| `web_search` | `id`, `query`, `action` |
| `todo_list` | `items[]` (`text`, `completed`) |
| `error` | `message` |

`status` ∈ `in_progress` (default) / `completed` / `failed`, plus `declined` for `command_execution`
only.

**What a reader is not entitled to believe.** `collab_tool_call` is Codex's multi-agent item and is
in the same enum; it appears in neither the prose documentation nor the 0.149.0 binary's visible tag
run. **The rule for 8.2 is the rule stage 7 arrived at:** parse the frames you consume, ignore the
rest, and never treat an unknown tag as an error. An adapter that raises on an unrecognised item
kind will one day fail on a feature it never asked for.

## Exit codes

**Not documented anywhere**, and not established here, because establishing them means running
`codex exec`. What the source shows is `0` on success and `std::process::exit(1)` for config-parse
failures, a missing Codex home, execpolicy failures, the git-repo check, a bad input schema, and
`if error_seen { exit(1) }` when a turn fails. **Treat "non-zero means 1" as an implementation
detail, never as a contract.**

Exit codes are free for 8.2 to establish against a loopback and should be established there rather
than guessed. Until then, 8.1's error translation should key on **what the stream said** —
`turn.failed`, a top-level `error` event, or no terminal event at all — and treat a non-zero exit
with no explanatory frame as the fallback that produces `UpstreamUnavailable` carrying stderr.

---

# 2. How tool calls surface, and what activity strings are available

They surface, in detail, and this is one of the places Codex is *better* served than Claude Code.

Every tool call produces `item.started` and `item.completed` frames (and possibly `item.updated`)
carrying a **typed** item whose payload is the argument the call is about:

| Item kind | What an activity line can say |
|---|---|
| `command_execution` | the `command` itself — §3.7's `Bash: ./gradlew build` example, exactly |
| `file_change` | each change's `path` and `kind` |
| `mcp_tool_call` | the `server` and `tool`, and the `arguments` |
| `web_search` | the `query` — §3.7's `Grep:` example is the same shape |
| `reasoning` / `agent_message` | `text`, which is content and not activity |

So `on_activity` is not merely possible, it is possible **without** the Claude adapter's
first-string-value-in-schema-order heuristic, because Codex's frames are typed rather than opaque
tool payloads. `translate.activity` for Codex should be a small match on item kind, formatting the
field that kind is about. That is a per-*frame-kind* rule and not a per-*tool* table, so it does not
run into what §3.7 forbids: it never names `Bash` or `Grep`, it names `command_execution` and
`web_search`, which are the harness's own frame kinds and the only vocabulary the stream has.

The workspace-relative path rule from the Claude adapter carries over unchanged and for the same
reason: `file_change.changes[].path` is a string a model produced, not a promise that a file exists,
so a plain prefix test against `task.workspace` is right and building a `Path` is not.

Confidence: high on the frames and their fields (binary and source agree). Nothing has watched one
arrive, so the *behaviour* — how often `item.updated` fires, whether `aggregated_output` is
populated before `item.completed` — is unestablished. `on_activity` may never be called and the port
allows that, so a wrong guess here is a cosmetic loss (entry 4's argument applies verbatim), not a
run that goes wrong.

---

# 3. Restrictions → sandbox and approval flags

## What Codex offers, and the one thing that is not what it looks like

`codex exec` exposes two knobs plus a bypass:

- **`-s, --sandbox`**: `read-only`, `workspace-write`, `danger-full-access`.
- **`-a, --ask-for-approval`**: `on-request`, `never`.
- **`--dangerously-bypass-approvals-and-sandbox`**: skip both. **AGL must never pass this**, because
  the sandbox *is* the restriction mechanism; throwing it away throws away `NO_FILE_WRITES`,
  `NO_NETWORK` and `NO_VCS_WRITES` at once.

**`codex exec` forces approvals off regardless of the flag.** `exec/src/lib.rs` sets the policy to
`AskForApproval::Never` with the comment *"Default to never ask for approvals in headless mode"*,
and installs rejection handlers returning JSON-RPC `-32000` for every approval channel. The 0.149.0
binary carries all seven refusals as literal strings:

> `command execution approval is not supported in exec mode for thread `
> `exec command approval is not supported in exec mode for thread `
> `apply_patch approval is not supported in exec mode for thread `
> `file change approval is not supported in exec mode for thread `
> `permissions approval is not supported in exec mode for thread `
> `request_user_input is not supported in exec mode for thread `
> `dynamic tool calls are not supported in exec mode for thread `

MCP elicitation is auto-cancelled on the same path (`McpServerElicitationAction::Cancel`, read off
the source).

**So there is no approval mode for the adapter to choose.** What `-a never` still buys is the
sentence in its own help — "Execution failures are immediately returned to the model" — a *graceful*
denial the agent can react to, rather than an approval request rejected with a JSON-RPC error.
Passing it explicitly is cheap and makes the intent legible. That is the whole of the decision, and
it matters for §9.

For completeness, because an implementer will meet the wider vocabulary and should know what is real
in it — **the parser advertises five variants and only four load**:

| `approval_policy` | Loads? |
|---|---|
| `untrusted` | **no** — `Error: approval_policy = "untrusted" is no longer supported; remove this setting` |
| `on-failure` | yes (deprecated in the published schema) |
| `on-request` | yes; one of the two the CLI exposes |
| `never` | yes; the other one, and what `codex exec` forces anyway |
| `granular` | yes; a newtype variant taking **three** booleans — `{granular={sandbox_approval=…, rules=…, mcp_elicitations=…}}` |

Measured by feeding each value to the loader and reading what it said back — `untrusted`'s refusal
is a real error message, and `granular`'s three fields were found by satisfying the parser's own
`missing field` complaints one at a time. **An adapter must not emit `untrusted`**: it is in the
binary's enum, it is in older documentation, and it is a hard startup failure.

Codex additionally carries a separate `permissions` profile system (`permissions.<name>`,
`default_permissions`, `permission_profile`, inheritance with cycle detection) exposed on
`codex sandbox` as `-P` and on `codex exec` not at all.

## What each sandbox value actually governs — measured

`codex sandbox -- <command>` runs an arbitrary command under the same policy with **no model, no
approval channel and no tokens**. That is the free instrument this section rests on. Results, on
macOS, inside a git repository:

| Probe | `read-only` | `workspace-write` | `danger-full-access` |
|---|---|---|---|
| write a file in the workspace | denied | **allowed** | allowed |
| write a file in `/tmp` | denied | **allowed** | allowed |
| write a file in `$HOME` | denied | denied | allowed |
| `curl https://example.com` | denied | **denied** | allowed |
| `git commit --allow-empty` | denied | **denied** (`Unable to create .git/index.lock`) | allowed |
| `touch .git/x`, `.codex/x`, `.agents/x` | denied | **denied** (`Operation not permitted`) | allowed |
| execute a program at all | **allowed** | allowed | allowed |

Four of those rows are the interesting ones.

**`workspace-write` denies writes to `.git`, `.codex` and `.agents` by default.** Measured three
ways, which is why `NO_VCS_WRITES` is the most solidly established row in this document. First,
behaviourally: `touch .git/x` is `Operation not permitted` and `git commit` dies on
`.git/index.lock`. Second, it is documented: inside a writable root those paths "stay read-only",
recursively, and a `.git` that is a `gitdir:` pointer file has its resolved target protected too.
Third — and this is the one that turns a documented claim into a read policy — **the profile handed
to the model spells the exclusions out**:

```xml
<permission_profile type="managed"><file_system type="restricted">
  <entry access="read"><special>:root</special></entry>
  <entry access="write"><path>/private/tmp/codexprobe</path></entry>
  <entry access="write"><special>:slash_tmp</special></entry>
  <entry access="write"><special>:tmpdir</special></entry>
  <entry access="read"><path>/private/tmp/codexprobe/.git</path></entry>
  <entry access="read"><path>/private/tmp/codexprobe/.agents</path></entry>
  <entry access="read"><path>/private/tmp/codexprobe/.codex</path></entry>
</file_system></permission_profile>
```

So the mechanism is the *default*, and the adapter opts back *in* rather than out. Measured both
ways: with `-c 'sandbox_workspace_write.writable_roots=["<workspace>/.git"]'` the same `git commit`
succeeds (`[main bcbcbc3] probe2`), and the same trick lifts the `.codex` protection. Compare what
this costs the Claude adapter — twenty-odd enumerated git subcommands in `translate._GIT_WRITES`, a
pattern language, and a docstring explaining why `curl` is not enumerated. Codex needs none of it.
As a bonus, `.codex` being read-only means an agent cannot write itself a configuration file
mid-run.

**And read the two lines in that profile a reader would not guess from the name.**
`workspace-write` makes **`:slash_tmp` and `:tmpdir` writable**, in addition to the working root.
That is outside the `Workspace` AGL handed the agent. It is **not** a breach of §3.5's "AGL never
writes into the target repo except through a `Workspace`" — `/tmp` is not the target repo, and the
sentence is about the repo — but "workspace-write" names a policy that is wider than a workspace,
and 8.2 should know that before it reasons about what an agent can leave behind. `exclude_slash_tmp`
and `exclude_tmpdir_env_var` (both documented, both defaulting `false`) narrow it; the first was
measured to work. Whether AGL should set them is a judgement call for 8.2 — agents legitimately use
`/tmp` for scratch work, and taking it away is the kind of restriction nobody declared.

**Both non-bypass modes deny network by default**, and only `workspace-write` can re-enable it:
`-c sandbox_workspace_write.network_access=true` makes `curl` succeed under `workspace-write` and
makes **no difference** under `read-only` (measured: still exit 6). Documented default is `false`.

**`writable_roots` cannot make the working root itself read-only.** Measured with
`writable_roots=["/nonexistent"]` under `workspace-write`: the working directory stayed writable.
The workspace is unconditionally writable in that mode. The other two `sandbox_workspace_write`
keys, both documented and both defaulting `false`, are `exclude_tmpdir_env_var` and
`exclude_slash_tmp`; the latter was measured to work.

**`read-only` does not remove command execution.** This was the one contested row in an earlier
draft of this document — the OS sandbox permits execution under `read-only` (measured), while the
published approvals table says that under `read-only` Codex "requires approval to make edits, run
commands, or access network", which with approvals forced off would have meant no commands at all.
**It resolves in favour of the OS-layer measurement, and it resolves for free.**

Diffing the rendered prompt between `read-only` and `workspace-write`, the only differences are
filesystem and network. Under `read-only` the model is told, verbatim:

> Filesystem sandboxing defines which files can be read or written. `sandbox_mode` is `read-only`:
> The sandbox only permits reading files. Network access is restricted.

Nothing removes the shell, nothing mentions approval for running a command, and the profile carries
one entry and no exclusions:

```xml
<file_system type="restricted"><entry access="read"><special>:root</special></entry></file_system>
```

**The residual limit, stated rather than glossed:** this is what the model is *told* and what the
profile *encodes*. It is not a live observation of a registered tool list, because
`codex debug prompt-input` renders **messages only** (see below). A tool could in principle be
withheld without the prompt saying so. That possibility is now the only thing standing, it is
cheap for 8.2 to close off a loopback, and it is no longer a reason to design the adapter two ways.

**One limit of this instrument, since it is used four times in this document.**
`codex debug prompt-input` renders the model-visible **prompt input list** — developer and user
messages — and **not the tool list**. So it cannot answer "which tools is the model offered under
this configuration": not for `mcp__agl__*` (§0), not for `features.shell_tool=false` (below), not
for `request_user_input` (§4). Every question of that shape needs the composed *request*, which is
what a loopback gives you and what stage 7 used on the Claude side. Do not reach for
`prompt-input` to settle question 9.

## The mapping, restriction by restriction

| `Restriction` | Codex mechanism | Exact, approximate, or none |
|---|---|---|
| `NO_FILE_WRITES` | `--sandbox read-only` | **Exact** for file writes; also removes network, which is the one gap below. Does **not** remove the shell |
| `NO_VCS_WRITES` | `--sandbox workspace-write` with `.git` **absent** from `sandbox_workspace_write.writable_roots` | **Exact** for the workspace's own repository, and measured three ways |
| `NO_NETWORK` | `--sandbox read-only`, or `workspace-write` with `sandbox_workspace_write.network_access` left `false` | **Exact** |
| `NO_SHELL` | `-c features.shell_tool=false` (equivalently `--disable shell_tool`), and probably `unified_exec` with it | **Approximate, and unverified.** See below |

A recommended composition for 8.1, offered as a starting point and not a decree:

```
if NO_FILE_WRITES in restrictions:  -s read-only
else:                               -s workspace-write
                                    -c sandbox_workspace_write.network_access=<NO_NETWORK not in restrictions>
                                    -c sandbox_workspace_write.writable_roots=[<workspace>/.git]   # only when NO_VCS_WRITES absent
if NO_SHELL in restrictions:        --disable shell_tool --disable unified_exec   # plus the sentence in words
always:                             -a never  --color never  --json
```

`writable_roots` carrying the workspace's `.git` when `NO_VCS_WRITES` was **not** declared is the
part most likely to be argued about, and the argument for it is the port's own sentence:
restrictions "are a set and not a level … nothing here implies anything else." A workflow that did
not ask for `NO_VCS_WRITES` has not asked to be prevented from committing. Against it: §3.3 has the
framework commit through `commit=`, so no v1.1 workflow needs the agent to commit, and adding a
writable root is a real widening of a sandbox. **A decision for 8.1 to take deliberately rather than
by accident**, and worth a sentence in `translate.py` either way.

## `NO_SHELL`, and why the mechanism is only probably a mechanism

`features.shell_tool` is documented — "Enable the default `shell` tool for running commands (stable;
on by default)" — and is measured **on** by default (`codex features list`). `--disable <FEATURE>`
is documented on `codex exec` as equivalent to `-c features.<name>=false`. So there *is* a switch.

Two reasons it is "approximate" and not "exact":

- **`unified_exec` is a separate stable-on feature** (measured), and a harness whose whole working
  model is running commands plausibly has a second route. Disabling both is the obvious move and
  nothing here has verified that the pair is exhaustive.
- **A tool removed is not a capability removed.** `apply_patch` may still run, `view_image` may
  still run, and the harness may degrade in ways that make the run useless rather than restricted.

So `NO_SHELL` must **also** go to the agent as words, which is the second of the two honest moves
`Restriction`'s docstring permits and which the Claude adapter's `_IN_WORDS` already has a form for.
Silently dropping it is not available and must not happen.

**And `codex debug prompt-input` cannot settle it**, which is worth saying because it settles so much
else in this document: it renders messages, not the tool list, so a tool that vanished when the flag
was set would leave no trace in it. 8.2 verifies the tool-removal half by reading the composed
request off a loopback, exactly as stage 7 verified that a bare-name deny rule removes a tool from a
Claude session — and that measurement is worth doing, because "the flag exists" is precisely the
evidence `manual-qa.md` entry 7 exists to warn about.

## The one honest gap

**`{NO_FILE_WRITES}` without `NO_NETWORK` is over-restricted.** `read-only` forces network off and
there is no knob — `sandbox_workspace_write.network_access=true` makes no difference under
`read-only` (measured). The alternative, `workspace-write` with network on, would *drop*
`NO_FILE_WRITES`, which the port forbids outright. So the adapter must take the over-restriction.

**It is one gap and not two, and that is a change from an earlier draft.** A role declaring only
`NO_FILE_WRITES` — "look at this and tell me what is wrong, but change nothing" — is exactly the
role that most wants to run the test suite, and for a while it looked as though `read-only` might
take that away too. It does not: `read-only` restricts the filesystem and the network and says
nothing about running commands (see above). So the cost of the over-restriction is network access
and nothing else, which is a cost most reviewing roles will never notice, and `plan_only` roles
compose the obvious way after all.

The gap is not a shape the port has vocabulary for: an adapter can say "I could not enforce that"
(by putting it in words) but not "I enforced more than you asked". §9, pressure 4 — which is now a
smaller pressure than it was.

## The R2 measurement: why choosing these flags inside the adapter is safe

Stage 7's equivalent was that bare-name deny rules remove tools from a Claude Code session
identically under all five permission modes, so the mode governs only calls that were never denied.
It measured the local decision safe rather than asserting it. **The Codex analogue exists, it is
free, and it is the same shape.**

**The measurement.** Render the model-visible prompt for each `(sandbox_mode, approval_policy)` pair,
extract the `<permission_profile>…</permission_profile>` element from the developer message, and
hash it:

```bash
codex debug prompt-input -c 'sandbox_mode="<mode>"' -c 'approval_policy=<policy>' "x" \
  | python3 -c "import json,re,sys,hashlib; d=json.load(sys.stdin)
t=''.join(c.get('text','') for m in d for c in (m.get('content') or []) if isinstance(c,dict))
p=re.search(r'<permission_profile[^>]*>.*?</permission_profile>', t, re.S)
print(hashlib.sha256(p.group(0).encode()).hexdigest()[:12] if p else 'ABSENT')"
```

(The `[^>]*` is load-bearing: the element is `<permission_profile type="managed">`, and a pattern
without it matches nothing and prints `ABSENT` for every cell — a table of fifteen identical
non-answers that looks exactly like a result. Found by running it.)

The profile is **byte-identical across every approval policy that loads**, and varies only with
`sandbox_mode`:

| `sandbox_mode` | `never` | `on-failure` | `on-request` | `granular` (all off) | `granular` (all on) |
|---|---|---|---|---|---|
| `read-only` | `5d2937a4a5a7` | `5d2937a4a5a7` | `5d2937a4a5a7` | `5d2937a4a5a7` | `5d2937a4a5a7` |
| `workspace-write` | `aeccca3a99ce` | `aeccca3a99ce` | `aeccca3a99ce` | `aeccca3a99ce` | `aeccca3a99ce` |
| `danger-full-access` | `d26091693415` | `d26091693415` | `d26091693415` | `d26091693415` | `d26091693415` |

Three distinct values, one per sandbox mode, fifteen cells.

**Non-vacuous in three directions, which is more than the argument needs and worth having.** The
rows differ, so the instrument can see a change at all. The columns do not, which is the finding.
And the table was produced twice, in two different workspaces on this machine: the `read-only` and
`danger-full-access` hashes came out **byte-identical both times**, while `workspace-write` differed
(`a069f228c0a9` in the other workspace) — which is exactly what the profile predicts, because only
the `workspace-write` profile embeds the working root's path. A measurement that reproduces where it
should and moves where it should is a measurement of the thing it claims to measure. **Reproduce the
`workspace-write` row rather than comparing its hash to the one above.**

**The reading.** What a role is permitted is decided entirely by `--sandbox`. The approval policy
does not appear in the policy the model is handed, so it cannot widen or narrow what the agent may
attempt — it can only decide what happens to a call the sandbox was going to refuse anyway. **That
is stage 7's conclusion reproduced through a completely different mechanism**, which is worth more
than either measurement alone: on Claude Code the invariant is about a *tool list*, on Codex it is
about a *filesystem policy*, and the two harnesses have nothing structural in common except that
both keep the approval concept out of the thing that actually governs the agent.

Two further facts, both free, both corroborating rather than load-bearing:

1. **The sandbox is enforced with no approval concept in the picture at all.** `codex sandbox` has
   no approval flag, no model and no session, and it still denies `.git`, `.codex` and `.agents`
   writes and all network under `workspace-write`, and all writes under `read-only`. That denial is
   a kernel-level Seatbelt decision about a process. **Measured.**
2. **In `codex exec` an approval can never be granted.** Exec forces `Never` and installs seven
   named rejection handlers. **Read off the binary and off the source, agreeing.**

Together: choosing `-a never` inside the adapter is **measured-safe rather than merely convenient**.
What it buys is only whether a denied call comes back to the agent as a result it can react to, or
arrives as a protocol error. That is a decision about calls the restrictions never covered, and it
belongs to the adapter.

---

# 4. Mid-run questions — the answer is no, and then it is yes for a different reason

**Treat the two halves of this section separately. They reach opposite conclusions and only the
second one is `MID_RUN_QUESTIONS`.**

## Codex's own asking mechanism does not exist in `codex exec`

Codex has a `request_user_input` tool. Its description, read off the binary, is
"Request user input for one to three short questions and wait for the response" — a real
question-asking mechanism, not an approval, and exactly shape (a). It has a documented config key
(`tools.experimental_request_user_input.enabled`, schema default **true**), a feature flag
(`default_mode_request_user_input`, measured **off**, "under development"), a TUI renderer
(`tui/src/bottom_pane/request_user_input/`) and an app-server response type
(`ToolRequestUserInputResponse`).

**And it is refused in exec mode by name**: `request_user_input is not supported in exec mode for
thread `. Its own description continues "This tool is only available in `<…>` mode" and
"request_user_input is unavailable in `<…>` mode", where the mode is a *collaboration mode* — an
interactive-session concept `codex exec` does not select.

**This is precisely the stage-7 trap in a new costume, and it is worse than stage 7's.** Entry 7
records that Claude Code's `AskUserQuestion` looked present on paper and turned out to be absent
from the registered tool list. Codex's `request_user_input` has a **published config key whose
schema default is `true`**. Anyone reading the config reference would conclude the capability is on
by default. It is vacuous here.

Two neighbouring mechanisms that must **not** be counted:

- **Approvals are not questions.** All seven approval paths are refused in exec mode anyway, but
  even if they were not, `on-request` is yes/no on an action, not a question whose answer re-enters
  the reasoning. `MID_RUN_QUESTIONS` is not that.
- **MCP elicitation is a real question mechanism and is auto-cancelled in exec.** Codex is an
  elicitation-capable MCP client (`rmcp-client/src/elicitation_client_service.rs`,
  `codex-mcp/src/elicitation.rs`, `core/src/elicitation.rs`, feature `tool_call_mcp_elicitation`
  measured **on**, and a documented `approval_policy.granular.mcp_elicitations` switch). In exec
  mode elicitations are cancelled (`McpServerElicitationAction::Cancel`), the JSONL schema has no
  event type that could surface one, and `codex exec` reads stdin only as the initial prompt so
  there is no channel to answer on. **Do not build on elicitation.**

## But the mechanism AGL needs is one AGL supplies

Stage 7 did not use Claude Code's asking mechanism either. It registered `mcp__agl_ask__ask`, an MCP
tool of AGL's own, told the agent about it in the prompt, and answered it out of the adapter. That
architecture does not need the harness to have a question feature — it needs the harness to call a
caller-supplied tool and wait for its result, which is the same requirement as `TOOL_CALLING`.

Codex satisfies that requirement through MCP (§0). So `MID_RUN_QUESTIONS` for this backend
**collapses into the tool-supply question** and is not a separate capability of the harness.

## Recommendation for `capabilities()`

**Report `MID_RUN_QUESTIONS`, on the same reading `manual-qa.md` entry 2 already fixed for Claude:
the flag means AGL registered an asking tool and instructed the agent to use it, not that any model
has been observed using it.** If 8.2 registers an asking tool on the AGL MCP server, the capability
is true in exactly the sense the Claude adapter reports it, and reporting it differently for the two
backends would mean the same word means two things.

**Confidence: medium, and this is the finding an implementer should most expect to be told is
wrong.** Three things would change it:

- **The 60-second tool timeout.** `tool_timeout_sec` defaults to 60 (documented). An asking tool
  waits on a human. **A default that expires under a person's thinking time is the specific way this
  capability dies quietly** — the tool call fails, the agent is told the tool errored, and it
  carries on guessing. 8.2 must raise it explicitly, and must check what Codex does when a tool call
  *does* time out, because "returns an error to the model" and "aborts the turn" are different
  outcomes for §3.7.
- **Whether an MCP tool result reaches the model at all.** If it does not, `MID_RUN_QUESTIONS` and
  `TOOL_CALLING` go together. They stand or fall on one measurement.
- **Whether 8.2 builds the asker.** If it does not, `capabilities()` must not report the capability,
  and that is a legal, tested position: `test_a_question_and_its_answer_are_two_rounds_inside_one_run`
  branches on the capability the adapter itself reported and asserts the handler was *never* called.
  A perfectly respectable place for 8.2 to stop.

---

# 5. Session identity, stop reason, and closing text

## Session identity — adapter-internal, for the log, and nowhere near `AgentOutcome`

`thread.started` carries `thread_id`, and it is the **only** place it appears — `turn.*` and
`item.*` do not repeat it. Codex persists a rollout per session under `$CODEX_HOME` and can resume
it (`codex exec resume <uuid|thread-name>`, `--last`, `--all`); `--ephemeral` runs "without
persisting session rollout files to disk". The human-readable mode prints a `session id` label. The
on-disk layout is **not** documented; do not depend on a path.

**That is where this stops.** §1.1 names vendor session identity in the result as one of the
original violations, and `AgentOutcome` excludes it in writing. Nothing in AGL resumes a session, and
§3.7 accepts in writing that a crash mid-negotiation re-runs the step. So: **log the `thread_id`
beside the run in the adapter, and put it nowhere else.** It is useful exactly once — when a person
reading a failure wants to open `codex exec resume` by hand.

`--ephemeral` deserves a thought and probably a pass: an AGL workspace is a throwaway worktree, the
rollout will never be resumed by AGL, and every run leaving a persisted session in the operator's
`$CODEX_HOME` is state AGL created outside `AGL_HOME`, which §3.5 dislikes on principle. Against it:
a persisted rollout is exactly what a person debugging a failed run wants. **A genuine judgement
call for 8.2, flagged rather than settled here.**

## Stop reason — Codex does not say, and `None` is the honest answer for most of it

**The exec stream carries no machine-readable reason for why a turn ended.** `turn.completed` carries
`usage` and nothing else; `turn.failed` carries an `error` with a free-text `message`. There is no
stop-reason field, no max-tokens flag, no interrupted flag, no turn-limit field. The two possible
endings arrive as two *event types*, and only one of them is unambiguous.

Worth knowing, because it explains the shape rather than excusing it: **Codex's app-server protocol
does have this** — turn `status` of `completed` / `failed` / `interrupted`, and a `codexErrorInfo`
with values including `ContextWindowExceeded`, `UsageLimitExceeded`, `HttpConnectionFailed`. The
information exists in the product and is not exposed on the surface AGL uses. That is a fact about
`codex exec`, not about the model.

| What arrives | `StopReason` | Why |
|---|---|---|
| `turn.completed` | `COMPLETED` | The turn ended with no error. In a harness with no turn limit and no timeout flag, that is the agent deciding it was done. |
| `turn.failed` with a usage-limit message | `LIMIT` — *if* 8.1 chooses to match | The binary carries the literal texts: `You've hit your usage limit. `, `You've hit your usage limit for `, plus upgrade and credit variants. This is string-matching vendor prose. |
| `turn.failed`, anything else | not a `StopReason` — raise | An error is an exception (§3.1). `UpstreamUnavailable` carrying the CLI's own words. |
| a top-level `error` event, or the stream ending with no terminal event | `None` | "The backend did not say" is a fact about the backend, and the port made that spelling legal precisely for this. |

**The recommendation, and the reasoning, because 8.1 will have to defend it.** The port's consumer
for `stop_reason` is one error message: when a reporting step ends with no payload, "it ran out of
turns" and "it decided it was finished" send a reader to different fixes. A wrong `COMPLETED` is the
only genuinely damaging answer — it tells a workflow the agent finished when it was cut off, and a
truncated answer gets treated as a finished one (entry 3 makes exactly this argument for Claude).
`None` degrades gracefully. So:

> Map `turn.completed` → `COMPLETED`. Map an absent terminal event → `None`. Treat `turn.failed` as
> an error and translate it, **except** for a recognised usage-limit message, which is `LIMIT`. If
> 8.1 would rather not string-match vendor prose at all, dropping the `LIMIT` row is defensible and
> costs only the quality of one error message — but then say so in the module, because a reader who
> finds `StopReason.LIMIT` unreachable in an adapter deserves to know it was a decision and not an
> oversight.

Codex has **no `--max-turns`**, auto-compacts rather than stopping at the context window, and gates
its budget features off by default (`token_budget`, `rollout_budget`, both measured off, both "under
development"). So `LIMIT` for this backend really is only about the subscription's usage cap. That is
a fact about how little there is to map, not a gap in the mapping.

Deferred to `manual-qa.md` entry 10: which terminal event a real run emits, and what a real
usage-limit failure looks like on the wire.

## Closing text

Two routes, and 8.2 should probably use both:

- the last `item.completed` whose item is an `agent_message`, taking its `text`;
- `-o, --output-last-message <FILE>`, which writes the final message to a file the adapter names in
  a temp directory it owns, and still prints it.

The file is the more robust — it does not depend on frame parsing and it is a documented flag rather
than a parsed field — and the stream avoids a filesystem round trip. `""` is the honest value when
the agent said nothing, and the port says so.

---

# 6. Hermeticity — the repository can be silenced, and it takes two overrides

§3.5's contract is that **the target repo contributes source code and nothing else**. This is the
most heavily measured section in the document, because `codex debug prompt-input` renders "the
model-visible prompt input list as JSON" **without contacting any model** — a free instrument with
no analogue on the Claude side, where stage 7 had to read the composed request off a loopback to
answer the same question.

**What it does and does not see, since this document leans on it four times.** It renders the
developer and user **messages**: instructions, `AGENTS.md` content, skill listings, the
`<permission_profile>` element, the environment context. It does **not** render the tool list, and
it is not the composed request. So it settles every "does this text reach the model" question
completely, and no "is this tool offered" question at all.

## What Codex discovers, measured

A poisoned fixture repository was built carrying a uniquely-marked file at every plausible path, and
`codex debug prompt-input` run against it with `CODEX_HOME` pointed at an empty directory, so the
operator's real configuration could not confuse the result. Markers that reached the model-visible
prompt are in bold.

| Path | Reaches the model? |
|---|---|
| `<repo>/AGENTS.md` | **yes** |
| `<repo>/AGENTS.override.md` | **yes — and it replaces that directory's `AGENTS.md`** |
| `AGENTS.md` in every directory between the project root and cwd | **yes**, all of them, concatenated root-down |
| ancestor `AGENTS.md` above the project root, when there is no `.git` | **yes** |
| `<repo>/.codex/skills/*/SKILL.md` | **yes** (name and description) |
| `<repo>/.codex/config.toml` | **no — see below, this is the one that needs care** |
| `<repo>/.codex/AGENTS.md`, `.codex/prompts/`, `.codex/hooks/`, `.codex/plugins/`, `.codex/rules/` | no |
| `<repo>/CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md`, `.agents/` | no |
| `$CODEX_HOME/AGENTS.md` | **yes** |
| `$CODEX_HOME/skills/*/SKILL.md` | **yes** |

Two rows deserve more than a line.

**`.codex/skills/` in the repository *is* read**, and the skill's name and description reach the
model. That is a repo-contributed instruction channel outside `AGENTS.md`, it is not covered by
`tests/contracts/_agent_hermeticity.py`'s current Codex row, and §3.5 says it should not be there.
It is suppressible (below). **The hermeticity row should grow a `.codex/skills/agl-leak/SKILL.md`**
so that a regression is caught by the suite rather than by this document.

**`.codex/config.toml` in the repository was measured absent and is documented present, and the
disagreement is the most important caveat in this section.** The documentation describes a
**project config layer** — `.codex/config.toml` from the project root down to cwd, closest wins,
**for trusted projects only**, with untrusted projects skipping "project-scoped `.codex/` layers,
including project-local config, hooks, and rules". On 0.149.0 it did not load, through three
independent instruments and under **both** trust levels forced via `-c
'projects."<path>".trust_level=…'`:

- a repo `.codex/config.toml` setting `project_doc_max_bytes = 0` changed nothing in
  `codex debug prompt-input`;
- a repo `.codex/config.toml` setting `model = "gpt-5.4"` left `codex doctor --json`'s
  `config.load` reporting `model: "<default>"`;
- a repo `.codex/config.toml` declaring an `mcp_servers.poison` entry left `codex mcp list` saying
  "No MCP servers configured yet", and `doctor` reporting exactly one `config.toml` path — the one
  under `$CODEX_HOME`.

So on this version, this fixture, this machine, the repository cannot configure Codex. **A reader is
not entitled to conclude that it never can.** The gate may be a trust mechanism this fixture did not
satisfy (a `trusted_hash`, an interactive trust prompt, a project registration), or the layer may
not be in 0.149.0 at all. The consequences either way:

- **There is no flag that suppresses a project `.codex/config.toml`.** `--ignore-user-config` closes
  `$CODEX_HOME/config.toml`; `--ignore-rules` closes `.rules`; nothing closes project config or
  project hooks. If the layer ever activates, a target repository could contribute configuration and
  hooks that AGL cannot turn off.
- **Two structural mitigations already exist and are worth writing down.** AGL's workspaces are
  fresh worktrees at fresh paths (§3.9), so they are untrusted by default and the layer is skipped;
  and project-local config is documented as *unable* to override provider and auth keys —
  `openai_base_url`, `chatgpt_base_url`, `model_provider`, `model_providers`, `notify`, `profile`,
  `otel` are ignored there — so a repository can never redirect the endpoint.
- Keeping `.codex/config.toml` in the contract suite's Codex row is therefore right, and the reason
  is now precise: a settings file that is inert today is exactly the thing a version bump changes.

## Precedence and the full channel list

Documented precedence, highest first, with what is measured about each on 0.149.0:

1. **CLI flags and `-c/--config` overrides.** Highest, available on `codex exec`, TOML-parsed with a
   literal-string fallback. **This is the whole of AGL's configuration surface; no file is needed.**
2. **Project config** — `.codex/config.toml`, root → cwd, trusted projects only. Measured inert
   (above).
3. **Profile** — `-p/--profile <name>` → `$CODEX_HOME/<name>.config.toml`.
4. **User config** — `$CODEX_HOME/config.toml` (default `~/.codex`; the directory must already exist
   if `CODEX_HOME` is set). Absent on this machine. Suppressed by `--ignore-user-config`, which
   leaves auth still using `CODEX_HOME`.
5. **System config** — `/etc/codex/config.toml` on Unix.
6. **Managed / MDM / enterprise layers.** The binary's own layer names are `packaged defaults`,
   `MDM`, `system`, `enterprise-managed`, `user`, `project`, `legacy managed_config.toml`. A
   `requirements.toml` can pin `allowed_sandbox_modes`, `allowed_approval_policies`, an MCP
   allowlist and `features.*`. **An adapter's chosen sandbox value can be overridden by a managed
   policy it cannot see**, and the binary shows it failing *quietly*: `Configured value for
   `permission_profile` is disallowed by requirements; falling back from `<x>` to required value
   `<y>``. Contrast the Claude adapter, where a forbidden permission mode produces a CLI that
   refuses to start. **Worth a sentence in 8.2's docstring**, because a silent substitution of a
   sandbox mode is a silently dropped restriction.
7. **Packaged defaults**, embedded in the binary: `project_doc_max_bytes = 32768`,
   `project_doc_fallback_filenames = []`, `chatgpt_base_url = "https://chatgpt.com/backend-api/"`,
   `project_root_markers = [".git"]`.
8. **`.rules` execpolicy files** — Starlark, scanned from `rules/` under every active config layer
   including `~/.codex/rules/` and (trusted) `<repo>/.codex/rules/`. Decisions are
   `allow`/`prompt`/`forbidden`, most restrictive wins. Suppressed by `--ignore-rules`.
9. **`AGENTS.md`** — global first (`$CODEX_HOME/AGENTS.override.md`, else `$CODEX_HOME/AGENTS.md`,
   first non-empty only), then from the project root down to cwd, at most one file per directory
   (`AGENTS.override.md`, then `AGENTS.md`, then `project_doc_fallback_filenames`), concatenated
   root-down so closer files come later in the prompt.
10. **Skills**, from `$CODEX_HOME/skills/` and from the repository's `.codex/skills/`.

## What suppresses what — measured

```
-c project_doc_max_bytes=0            removes every AGENTS.md the repository contributes,
                                      at every depth, including AGENTS.override.md
-c skills.include_instructions=false  removes every skill, the repository's and the operator's
--ignore-rules                        does not load user or project .rules       (documented)
--ignore-user-config                  does not load $CODEX_HOME/config.toml      (documented)
```

With the first two applied to the fully poisoned fixture, **the only marker still reaching the model
is `$CODEX_HOME/AGENTS.md`** — the operator's own global instructions. Everything the *repository*
planted is gone.

**`project_doc_max_bytes = 0` is measured, not documented.** The published documentation discusses
only *raising* the cap; `0` is schema-legal and demonstrably disables the mechanism here, but nobody
has promised it will. That makes it exactly the kind of claim to pin with a test, and the contract
suite's poisoned-repository clause already is that test.

## Where Codex's line falls, against stage 7's

Exactly where Claude Code's does, and the parity is the useful part of the finding.

- **The repository can be silenced.** Two `-c` overrides plus two flags, no file on disk.
- **The operator's own machine cannot be.** `$CODEX_HOME/AGENTS.md` survives every knob discoverable
  for free: `developer_instructions=""`, `include_environment_context=false` and
  `project_doc_fallback_filenames=[]` all leave it in place (measured), and `model_instructions_file`
  is a different mechanism the documentation itself says users are "STRONGLY DISCOURAGED" from
  using. `--ignore-user-config` is the remaining candidate and could **not** be measured, because
  `codex debug prompt-input` does not take that flag — 8.2 can settle it against a loopback for
  free, and it is `manual-qa.md` entry 11 until then.
- **Repointing `CODEX_HOME` would close it and must not be done in production**: `CODEX_HOME` is
  where `auth.json` lives, so moving it removes the credential. That is precisely what
  `tests/conftest.py` does *on purpose*, and it is a test guard, not a strategy.

So: the repository's configuration can be suppressed; the operator's cannot; the second channel is
deferred by §3.11 ("v1.1 inherits the parent environment"). **The same sentence stage 7 wrote about
Claude Code is true of Codex, for a different set of files.** Two harnesses landing on the same line
independently is mild evidence that §3.5's boundary is a real boundary rather than one vendor's
quirk — and it is the only place in this document where two harnesses agreeing is *not* a warning.

---

# 7. The endpoint-redirect question 8.0a deferred

8.0a protected Codex by emptying `CODEX_HOME` rather than redirecting the endpoint, because it could
not establish a redirect variable for free. **It can now be established, for free, and the answer
has two halves.**

**There is no environment variable, and this is now positively established rather than merely not
found.** Measured: `OPENAI_BASE_URL=http://127.0.0.1:9/v1 codex doctor --json` resolves its
inference URL to `https://chatgpt.com/backend-api/` — unchanged. The single occurrence of the string
`OPENAI_BASE_URL` in the binary sits inside the network-proxy MITM module's secret-redaction list,
beside `sk-`, `GITHUB_TOKEN` and `api.openai.com`; it is a name the proxy redacts, not a variable the
config layer reads. Neither `CODEX_BASE_URL` nor `OPENAI_API_BASE` appears anywhere in the binary.
And the documented environment-variable list — `CODEX_HOME`, `CODEX_SQLITE_HOME`, `CODEX_API_KEY`,
`CODEX_ACCESS_TOKEN`, `CODEX_CA_CERTIFICATE`, `SSL_CERT_FILE`, `CODEX_NON_INTERACTIVE`,
`CODEX_INSTALL_DIR`, three `OPENAI_*` identity variables and `RUST_LOG` — contains no base URL.
**The endpoint is configuration.**

One consequence for whoever reads `scripts/check` before reading this. Gate 8's `GUARDED_VARS` lists
`OPENAI_BASE_URL` and `OPENAI_API_KEY` beside the two Anthropic variables and `CODEX_HOME`, and a
reader could reasonably take that as a statement that `OPENAI_BASE_URL` is Codex's redirect. **It is
not**, and the guard is not wrong: naming a variable no test file may set costs nothing and protects
against a version that starts reading it. But 8.2 must not reach for it expecting an effect. The two
variables that do something to `codex` today are `CODEX_HOME` (which is where the credential lives,
and is why 8.0a's guard works) and `OPENAI_API_KEY` (which selects API-key billing over the
subscription — §3.11's "keep it unset" applies to Codex exactly as it does to Claude).

**Three config keys redirect it, and all three work from `-c` alone.** `codex doctor --json` reports
the endpoint it resolved under `checks["network.provider_reachability"].details`, which makes this
free and non-vacuous — a wrong key leaves the URL untouched, and one did.

| Override | Resolved inference URL reported by `doctor` |
|---|---|
| *(none)* | `https://chatgpt.com/backend-api/…` — "reachability mode: ChatGPT auth" |
| `-c chatgpt_base_url="http://127.0.0.1:9/backend-api/"` | `http://127.0.0.1:9/backend-api/…` — still ChatGPT auth |
| `-c openai_base_url="http://127.0.0.1:9/v1"` | `http://127.0.0.1:9/v1/…` — the built-in `openai` provider's URL |
| `-c 'model_providers.loop={name="loop",base_url="http://127.0.0.1:9/v1",wire_api="responses"}' -c 'model_provider="loop"'` | `http://127.0.0.1:9/v1/…` — "reachability mode: provider auth" |

So **yes, a `model_providers` entry can be injected wholly on the command line**, and it switches the
run off ChatGPT auth onto provider auth in the same stroke. Documented `ModelProviderInfo` fields:
`name`, `base_url`, `env_key`, `env_key_instructions`, `experimental_bearer_token`, `aws`,
`wire_api`, `query_params`, `http_headers`, `env_http_headers`, `request_max_retries`,
`stream_max_retries`, `stream_idle_timeout_ms`, `websocket_connect_timeout_ms`,
`requires_openai_auth`, `supports_websockets`, `supports_standalone_web_search`, plus an `auth`
sub-table.

**`wire_api` has exactly one value now: `responses`.** The schema's `WireApi` is a one-variant enum
and the config reference says "Protocol used (`responses` only supported)". Any note anywhere saying
`chat` is a valid value is stale. This matters for §8.2's loopback, below.

**For this machine, `chatgpt_base_url` is the one that matters**, because `auth_mode` is `chatgpt`
and that is the URL the ChatGPT-auth path resolves.

**What a reader is not entitled to believe.** `doctor` reports the URL Codex *resolved as the
inference endpoint*. It is not proof that `codex exec` sends its request there — the two could in
principle resolve differently, and proving otherwise means running `codex exec`, which this
deliverable may not do.

**That measurement is free for 8.2, not a paid turn, which is why it is not in `manual-qa.md`.**
Point a loopback listener at `chatgpt_base_url`, run the adapter, and read the bytes that arrive —
exactly `tests/instruments/loopback.py`'s existing job. If the redirect works, nothing paid happens.
If it does **not** work, `tests/conftest.py`'s emptied `CODEX_HOME` means there is no credential to
send, so the failure is an authentication error and not a bill. **Keep both guards.** The stronger
statement 8.2 can then make is the one 8.0a wanted and could not: not merely "there was nothing to
leak" but "the request went where we sent it, and we read it".

One caveat on cost, so nobody is surprised: standing a Codex loopback up is more work than the
Claude one. It must speak the OpenAI **Responses** API over SSE, not Anthropic's message stream, and
to drive the tool loop it must emit tool calls in that format. If that turns out to be more than 8.2
can carry, saying so and falling back to credential-removal alone is an acceptable outcome — but it
should be a stated decision, and `tests/conftest.py`'s docstring should be updated to say the
redirect is *established* even if it is not *used*.

---

# 8. What Codex genuinely cannot do

A straight list, no hedging.

1. **It cannot ask the user a question in `codex exec` using any mechanism of its own.**
   `request_user_input` is refused by name; MCP elicitation is auto-cancelled; approvals are not
   questions and are refused too.
2. **It cannot accept caller-supplied tools by any route except MCP.** The `DynamicToolSpec` channel
   is refused by name in exec mode. MCP means a real server process or a real HTTP endpoint; there
   is no in-process option, so the adapter must run one.
3. **It cannot say why a turn ended.** `turn.completed` and `turn.failed` carry `usage` and a
   free-text error respectively. The information exists on the app-server surface and is not on this
   one.
4. **It cannot be given a set of restrictions.** `--sandbox` is a scalar and one value has to serve;
   `{NO_FILE_WRITES}` without `NO_NETWORK` is not expressible without over-restricting.
5. **It cannot cleanly be denied a shell.** `features.shell_tool=false` exists and is documented;
   `unified_exec` is a second stable-on route; neither has been verified to remove command
   execution, and the free instrument that settles most things here cannot see a tool list.
6. **It cannot be made to ignore the operator's `$CODEX_HOME/AGENTS.md`** by any knob discoverable
   for free, short of moving `CODEX_HOME` and losing the credential with it.
7. **It cannot pause for approval at all in exec mode** — listed because it is a *feature* here and
   nobody should build on the opposite assumption.

**One item that was on this list and has come off it.** "It probably cannot run commands under
`read-only`" was here on the strength of the published approvals table. It is wrong: the prompt
Codex renders under `read-only` restricts the filesystem and the network and says nothing about
running commands, and the profile carries a single read entry. `read-only` is therefore usable for a
reviewing role that still needs to run a build. Recorded rather than quietly deleted, because a
reader who met the earlier claim elsewhere should know which way it went.

## `capabilities()` — the recommendation

| Member | Report? | Why |
|---|---|---|
| `FILE_EDIT` | **yes** | Codex's entire model is editing files in a workspace; `file_change` is a first-class item kind in its own event stream, `apply_patch` is a first-class tool, and `workspace-write` exists to permit exactly this. High confidence. |
| `SHELL` | **yes** | It runs commands under `workspace-write`. High confidence. (Whether it does so under `read-only` is §3's open question and does not change the capability, which is "can this backend be asked for shell work at all".) |
| `TOOL_CALLING` | **yes** | MCP servers are configurable from argv alone (measured), MCP is documented to work in `codex exec`, and `mcp_tool_call` is one of the stream's own item kinds. Medium-high: configuration measured, round trip not. |
| `MID_RUN_QUESTIONS` | **yes, conditionally** | Only if 8.2 registers an asking tool on the AGL MCP server *and* raises `tool_timeout_sec`, on the same reading as entry 2. Codex's own asking mechanism is vacuous in exec mode. If 8.2 does not build the asker, report it absent — the contract suite handles that correctly. Medium confidence, and the one most likely to move. |

`_CAPABILITIES` should be a frozen constant, exactly as the Claude adapter's is, for the reason the
port gives: `capabilities()` is "what can you do", it must be stable for the duration of a run, and
probing at preflight would make the answer depend on whether a network was up when it was asked.

**`check_ready` is free for Codex, and that asymmetry is worth noticing.** `codex login status`
exits 0 printing `Logged in using ChatGPT` and exits 1 printing `Not logged in` — both measured, the
second against an empty `CODEX_HOME`. The Claude adapter's `check_ready` costs a real turn because
nothing short of asking the far side distinguishes the two. Two backends, same port member, costs
differing by three orders of magnitude: **the clearest available vindication of keeping `check_ready`
separate from `capabilities()`**, since the two questions turn out to differ in cost as well as in
lifetime.

`codex doctor --json` is a richer free instrument for the same purpose — 20 named checks including
`auth.credentials`, `config.load` and `network.provider_reachability` — and is the candidate if
`check_ready` ever needs to say *why* more precisely than "not logged in". It also makes network
requests, which `login status` does not, so it is slower and less predictable.

---

# 9. The R2 checkpoint: every pressure on `ports/agent.py`

`ports/agent.py` has not changed since stage 2 and nothing in this deliverable proposes changing it.
This section is where the pressure gets reported — exhaustively, including pressures that should be
resisted and the one that might one day be legitimate.

## Pressure 1 — hoist an approval or sandbox mode to the port. **Resist.**

The predicted one. A framework run has nobody to approve a tool call, so the Claude adapter sets
`permission_mode="bypassPermissions"`; two harnesses needing the same decision makes a port-level
field look obviously right.

**It is §1.1's charge verbatim** — "an approval mode, as an unvalidated string" — and Codex supplies
two arguments stage 7 could not have made.

**First: the two harnesses do not actually face the same decision.** `codex exec` **hard-forces**
`AskForApproval::Never` and installs seven named rejection handlers. There is no approval mode for
this adapter to pick. The "identical decision" that made hoisting look obvious is not identical; it
is not even present. What the Codex adapter picks is a *sandbox*, which is an OS-level policy about
a process, and what the Claude adapter picks is a *permission mode*, which is a harness-level policy
about tool calls. Naming one field after both would be naming it after neither.

**Second: Codex does not have *an* approval mode. It has four overlapping ones.**

- `sandbox_mode`, three values;
- `approval_policy` — five variants the parser advertises, of which **four load** (`untrusted` is
  rejected outright) and the CLI exposes two, with `granular` being an *object* of three booleans
  rather than a value at all;
- a `permissions` profile system with inheritance and cycle detection, exposed on `codex sandbox`
  and not on `codex exec`;
- per-MCP-server `default_tools_approval_mode` and per-tool `approval_mode`, five more values.

Claude Code has one axis with five values. There is no common shape, let alone a common value set,
and any field hoisted to the port would be one vendor's spelling wearing a neutral name — while the
third implementation, a self-hosted model behind a plain HTTP API, would implement it as a no-op,
which is the definition of a field that lies.

**Third, and this is the one the stage asked for: the local decision is *measured* safe.** §3 has
the table in full. The policy Codex hands the model — the `<permission_profile>` element in its
developer message — is **byte-identical across all four loadable approval policies** and varies only
with `sandbox_mode`: three distinct hashes over fifteen cells, rows differing and columns not. So
the approval setting is not in the thing that governs the agent, and cannot widen or narrow what it
may attempt. It decides only whether a call the sandbox was going to refuse returns gracefully to
the model or arrives as a protocol error.

**That is stage 7's invariant reproduced through a mechanism with nothing in common with it.** On
Claude Code the measurement is about a *tool list*; on Codex it is about a *filesystem policy*. Two
harnesses arriving at the same separation by different routes is the strongest form this argument
can take — and note that it argues *against* hoisting rather than for it. What the two harnesses
share is the invariant "the approval concept is kept out of what actually governs the agent", which
is a reason the port needs no approval field, not a shape for one.

## Pressure 2 — add a third `StopReason` member, or a raw stop string. **Resist.**

Codex says nothing machine-readable about why a turn ended, so an implementer will find nothing to
put in `stop_reason` and may reach for `UNKNOWN`, or `raw_stop: str`, or an `error` field on
`AgentOutcome`. The port already answers this: `StopReason | None`, with `None` documented as "the
backend did not say" and deliberately *not* a third member, because "did not say" is a fact about a
backend and not a way of stopping.

Worth recording as **evidence for** the design rather than pressure against it: the `None`-able field
was written speculatively at stage 2 against a hypothetical backend, and the second real backend
turned out to be that backend.

## Pressure 3 — `MID_RUN_QUESTIONS` means something adapter-relative. **Report, do not act.**

Both adapters will report `MID_RUN_QUESTIONS` on the strength of an asking tool **AGL itself
supplies**, not on the strength of anything the harness offers. Claude Code's `AskUserQuestion` is
vacuous (entry 7); Codex's `request_user_input` is refused in exec mode. So on both backends the
capability reduces to "this adapter registered an asker over a caller-supplied-tool mechanism", and
`MID_RUN_QUESTIONS` and `TOOL_CALLING` are not independent for either of them.

This is a **shared-harness-concept risk of exactly the kind the stage warned about**: two CLI
backends agreeing that a capability is really a property of the adapter is not evidence that the
port's two members are well separated. The case that keeps them distinct is a backend that can call
tools but cannot host a long-blocking one — an HTTP completions API with a request timeout, which is
the third implementation. Note that **Codex nearly is that backend already**: `tool_timeout_sec`
defaults to 60 seconds, and a capability that survives only because the adapter remembered to raise
a timeout is a capability held together with tape. **Nothing to change; something to carry to
stage 17.**

## Pressure 4 — a way to say "I enforced more than you asked". **Possibly legitimate. Not now.**

`Restriction`'s docstring gives an adapter two honest moves for something it cannot enforce —
mechanism, or words — and forbids the third, silently dropping it. It says nothing about the
opposite. `{NO_FILE_WRITES}` forces Codex to `read-only`, which also removes network. The port has
no vocabulary for reporting that, and unlike an unenforceable restriction there is nothing useful to
say to the agent about it.

**This pressure got smaller during the deliverable and it is worth saying why**, because the
direction is the point. It was written when it looked as though `read-only` might also remove
command execution, which would have meant a reviewing role silently losing the ability to run a
build — a real cost, worth arguing about. Measured, `read-only` restricts the filesystem and the
network and nothing else, so the whole of the over-restriction is network access for a role that
declared `NO_FILE_WRITES` and not `NO_NETWORK`. A port change was never going to be worth that, and
now it is obviously not.

It remains a genuine gap in the port's shape and the only one this deliverable found. **Not** worth
acting on in v1.1: no workflow declares that combination, the failure is over- rather than
under-restriction, and any fix would put an adapter-fidelity concept into a port whose whole
discipline is not carrying adapter concepts. **Recorded so that the day a workflow does declare it,
the reader knows this was seen and priced.** If it is ever acted on, the shape to resist is a
per-restriction "how strictly" enum; the shape that might work is nothing in the port at all and a
preflight warning from the adapter.

## Pressure 5 — a session handle, a config-file parameter, a `close()`. **Resist. Nothing needed.**

Codex would have carried all of them happily: `thread_id`, `codex exec resume`, `--profile`,
`CODEX_HOME`, a `config.toml` path, `-c` overrides, `--ephemeral`. `AgentRunner` has none and needs
none. Verified rather than assumed: nothing in §§1–8 required a port member that does not exist.

The one thing to watch is the constructor. Both adapters now want "where is the binary", and the
Codex adapter will additionally want "which port did the MCP server bind to". Those are
composition-root business and must stay there; the moment either appears as a parameter on `run()`
or a field on `AgentTask`, §1.1 has happened again.

## Pressure 6 — make `Tool.handler` serialisable, or add a tool-transport concept. **Resist.**

Codex starts MCP servers itself; a Python closure over the framework's `Run` cannot be sent into a
subprocess. The temptation is to make `Tool` carry something transportable — a command line, a
schema-plus-endpoint — so an adapter can hand it straight to a harness.

That would put the harness's plumbing into the port and break the port's actual promise, which is
that the handler runs on the framework's side and its `text` goes back to the agent. The right
answer is that the adapter bridges: an in-process HTTP MCP server on loopback, `-c
mcp_servers.agl={url=…}`, handlers untouched. **This is real work for 8.2 and should be budgeted,
not designed away.**

## Pressure 7 — `AgentTask.context` and `plan_only`. **No pressure; both survive intact.**

`codex exec` takes one prompt and has no standing-context slot, so the adapter joins `context` onto
`instructions` — which the port permits in writing and explains why. Codex has a Plan mode (a
collaboration mode; the binary carries "update_plan is a TODO/checklist tool and is not allowed in
Plan mode") but **does not expose it on `codex exec`**, so `plan_only` becomes prompt text plus
`--sandbox read-only`, which is exactly the case its docstring anticipated: "a harness without one
says so in the prompt and enforces it with what it has." Do **not** reach for `-c` to force a
collaboration mode; it is an internal with no CLI surface and no stability promise.

## Pressure 8 — `AgentOutcome` should carry a structured payload, because Codex can produce one. **Resist.**

`codex exec --output-schema <FILE>` takes a JSON Schema "describing the model's final response
shape". Genuinely attractive, and the wrong shape for §3.3: it fires once, at the end, with no
handler round trip, so a malformed payload cannot be rejected back into the same conversation.
`AgentOutcome` carries no payload deliberately, and `Tool.handler`'s docstring explains why an
adapter must not know which of its tools is the reporting one. Listed because it is the most
plausible-looking wrong turn available to anyone reading `codex exec --help`.

## Pressure 9 — `Restriction` is a set and `--sandbox` is a scalar. **No change.**

Sixteen possible restriction sets collapse onto three sandbox values plus three config keys. That is
the adapter's arithmetic, done once in `translate.py`, and it is what "each adapter renders it in
whatever its own backend offers" means. Recorded only because a set-to-scalar collapse is the kind
of thing that later gets blamed on the port.

## Pressure 10 — `OpenAI.GPT5` named a model Codex does not publish. **This one became a port change. Reported.**

This section reported an ambiguity and predicted no port change. **A port change is what happened**,
concurrently with this deliverable and by another hand: `OpenAI.GPT5 = "openai:gpt-5"` has been
replaced by `SOL`, `TERRA` and `LUNA` (`"openai:sol"`, `"openai:terra"`, `"openai:luna"`). The stage
says a diff in `ports/agent.py` is "a design failure worth reporting rather than absorbing", so it
is reported here rather than folded silently into the rest of the document.

**The factual basis is sound and was re-verified for this report.** `codex debug models` — free,
local — returns exactly the ordering the new docstring cites: `gpt-5.6-sol` at priority 1 ("Latest
frontier agentic coding model."), `gpt-5.6-terra` at 2 ("Balanced agentic coding model for everyday
work."), `gpt-5.6-luna` at 3 ("Fast and affordable agentic coding model."), all three
`visibility: "list"` and `supported_in_api: true`. There is no `gpt-5`. So the three tiers are the
vendor's own ordering rather than somebody's reading of it, and the member that was there named a
model that does not exist.

**Assessed against what R2 is actually watching for, this is not that failure.** R2 is about vendor
*syntax, types, exceptions and option objects* crossing the port, and `ModelId` is the one place
where vendor names are explicitly correct — "naming a model is a domain choice, like naming a
database." The port's shape is untouched: same class, same enum, same `<provider>:<model>` spelling,
no new field, no new concept, nothing an adapter must now ignore or invent. What changed is a
**placeholder corrected against a fact nobody could have had at stage 2**, because learning it
requires the harness to be installed. §3.2's sketch showed `GPT5 = "openai:gpt-5"` as an
illustration rather than as a measurement, and has since been brought in line with the port.

**Two costs, and they are permanent rather than large.**

- **These values are a stored format** (§3.6: a step's fingerprint is canonical JSON over its role).
  Changing them now costs nothing because nothing has been recorded yet. Changing them *later*
  re-runs every step recorded under one — so this is the last cheap moment, which is an argument for
  having done it now rather than after stage 10.
- **The asymmetry with `Claude` is real and the docstring names it honestly**: Anthropic resolves
  `opus`/`sonnet`/`haiku` server-side, so the Claude adapter never needs a release-driven edit,
  while the OpenAI adapter's slug table does. That edit is in an adapter, which is where a vendor's
  release schedule belongs.

**One risk worth writing down rather than leaving to be discovered**, and it is not an objection.
`sol`, `terra` and `luna` are the vendor's own codenames with the version stripped. The docstring
calls them AGL's own, which is true of the *spelling* and not of the *words*. If that provider
retires the naming scheme wholesale — as it retired `o3` and never shipped a plain `gpt-5` — AGL is
left with three enum members named after a scheme that no longer exists, and they cannot be renamed,
because they are a stored format. The tiering they encode (deep / everyday / cheap) survives that;
the words do not. Nothing to do about it today, and a reader of these three members in two years
should know why they are called this.

---

# 10. What 8.1, 8.2 and 8.3 should build

Not a design, but the shape the findings imply, so that three deliverables do not each re-derive it.

**8.1 `adapters/openai/translate.py`.**

- `Restriction` → the sandbox composition in §3. The whole of it is one function returning argv
  tokens; no pattern language, no per-command enumeration.
- The four restrictions in words, mandatory for `NO_SHELL` and belt-and-braces for the others.
  `_IN_WORDS` is the right shape; the sentences must be AGL's own and must not describe a mechanism
  this harness does not have.
- `ModelId` → a Codex model slug from a closed table: `SOL` → `gpt-5.6-sol`, `TERRA` →
  `gpt-5.6-terra`, `LUNA` → `gpt-5.6-luna` (priorities 1, 2 and 3 in `codex debug models`, all three
  `visibility: "list"` and `supported_in_api: true`). Pinned rather than priority-following — see
  "Ambiguity". Guard the value against a leading `-` even though a closed table cannot produce one,
  for §3.5's reason: the rule is about the value's position, not its provenance.
- Frames → activity strings: a match on item kind, formatting the field that kind is about (§2).
- Failures → `AglError`: `turn.failed`'s `error.message`, a top-level `error` event's `message`, a
  non-zero exit with stderr, a missing binary. `UpstreamUnavailable` for everything that is a state
  of the world.

**8.2 `adapters/openai/runner.py`.**

- Prompt on **stdin**, workspace via `-C`, everything else via flags and `-c`.
- Hermeticity: `-c project_doc_max_bytes=0`, `-c skills.include_instructions=false`,
  `--ignore-rules`, `--ignore-user-config`, `--color never`, `--json`. Each is load-bearing and each
  should carry the sentence saying what it closes, the way `runner.py` does on the Claude side.
- Tools: an in-process streamable-HTTP MCP server on `127.0.0.1`, injected with
  `-c 'mcp_servers.agl={url="http://127.0.0.1:<port>/mcp", tool_timeout_sec=<generous>,
  default_tools_approval_mode="auto"}'`. Names arrive at the model as `mcp__agl__<tool>`.
- Stream parsing: consume what you recognise, ignore what you do not, never raise on an unknown tag.
- `capabilities()` a frozen constant; `check_ready` via `codex login status`, which is free.
- **Four free measurements, in this order, before the adapter is finished.** All four need the
  composed *request*, which is what a loopback gives you — `codex debug prompt-input` settles a
  great deal in this document and can settle none of these, because it renders messages and not the
  tool list. They are: whether the loopback receives the request at all (§7); whether an MCP tool is
  registered and its result reaches the model (§0); whether `--disable shell_tool` actually removes
  the shell (§3); and whether `--ignore-user-config` also suppresses `$CODEX_HOME/AGENTS.md`
  (§6, entry 11).

**8.3 `adapters/openai/fake.py`.** Nothing here constrains it beyond the obvious: it should be able
to produce all four outcomes (`COMPLETED`, `LIMIT`, `None`, and a raised `UpstreamUnavailable`), call
tools, and never start a subprocess.

## What an implementer should treat as provisional

| Finding | Confidence | Why it might move |
|---|---|---|
| Sandbox write/network/`.git` semantics (§3 table) | **High** — measured behaviourally, documented, *and* read off the profile handed to the model | macOS only; Linux and Windows use different enforcement |
| The approval policy does not affect what the agent may do (§3, R2) | **High** — measured, fifteen cells, non-vacuous in both directions | It is a fact about `codex exec` 0.149.0's rendered policy, not a promise |
| `read-only` leaves the shell alone (§3) | **High** — measured off the rendered prompt and profile, and off the OS sandbox | It is what the model is *told*; a withheld tool would not show. Free to close off a loopback |
| `approval_policy` has four loadable values, `granular` takes three booleans (§3) | **High** — measured against the loader itself | — |
| `codex login status` as `check_ready` | **High** — measured both ways | — |
| Repository configuration channels and their suppression (§6) | **High** — measured against a poisoned fixture | `codex debug prompt-input` renders messages, not the request and not the tool list; a channel reaching either without reaching a message would be invisible here |
| Endpoint is config, not env (§7) | **High** — measured with a working control, and the env-var list is documented | `doctor` resolves; `exec` sends. See §7 |
| MCP servers configurable from argv (§0) | **High** — measured | The `-c` + `mcp_servers` combination is not documented |
| JSONL event and item schema (§1) | **High** — 0.149.0 binary and `main` source agree independently | `collab_tool_call` is source-only; behaviour of `item.updated` is unobserved |
| An MCP tool result reaching the model in `codex exec` | **Medium** — documented that MCP works in exec, and `mcp_tool_call` is an exec item kind | Nothing has watched it happen. Entry 9 |
| `MID_RUN_QUESTIONS` (§4) | **Medium** | Depends on 8.2 building the asker and on `tool_timeout_sec` |
| `NO_SHELL` via `features.shell_tool=false` | **Low-medium** — documented switch, unverified effect, `unified_exec` unaccounted for | Free to verify off a loopback — and **not** off `prompt-input`, which cannot see a tool list |
| `LIMIT` from a usage-limit message (§5) | **Low** — string-matching vendor prose | Entry 10 |
| `default_tools_approval_mode="auto"` being the never-ask value | **Low** — inferred from the name | Free to confirm off a loopback |
| Repository `.codex/config.toml` being inert | **Medium** — measured three ways on 0.149.0, documented as a real trust-gated layer | A trust mechanism this fixture did not satisfy, or a version change |
| Exit codes | **Not established** | Deliberately. 8.2 measures them free |

---

# Ambiguity, reported rather than resolved

**Which Codex model slug is `OpenAI.GPT5`? — resolved, and not by this deliverable.** It was raised
here because `codex debug models` lists `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`,
`gpt-reserve`, `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `codex-auto-review` and **no `gpt-5`**, leaving
the enum member naming a model that does not exist. It has since been settled in `ports/agent.py`
itself: `GPT5` is gone and `SOL`, `TERRA` and `LUNA` are the three tiers. §9, pressure 10 reports
that change, its factual basis (re-verified free), and the two costs it carries.

**What is left for 8.1 is the smaller half, and it is still a decision.** Three enum members now
have to map to three slugs, and the mapping can be **pinned** (`SOL` → `gpt-5.6-sol`; a model
retired upstream then breaks loudly, which is the good failure) or **follow the catalog's
`priority`** (`SOL` → whatever is priority 1 today; the model silently changes under a fingerprint
that says it did not, which interacts badly with §3.6 and is probably wrong for that reason). The
port's own docstring anticipates the pinned answer — it says this adapter "needs an edit on a
release where the Claude one does not", which is only true if the table is pinned. Worth stating
in `translate.py` either way rather than leaving the reader to infer it from a literal.

**Whether to pass `--ephemeral`.** §5 sets out both sides. Not decided here.

**Whether 8.2 builds the asking tool at all.** §4 sets out both sides and both are legal against the
contract suite. It decides what `capabilities()` reports, so it should be decided deliberately and
first, not discovered at the end.

**What `read-only` means to a `codex exec` agent** was listed here as the most consequential
unsettled question in an earlier draft. **It is settled** (§3): filesystem and network, not the
shell. Left in place rather than deleted so that a reader who saw the earlier claim knows it was
answered and which way.

---

# Appendix — reproducing every measurement

All free. `$SCRATCH` is any temporary directory; `$EMPTY` is an empty directory used as a
credential-free `CODEX_HOME`.

```bash
# Version, auth, and the packaged defaults quoted above.
codex --version
codex login status                                   # -> "Logged in using ChatGPT", exit 0
CODEX_HOME=$EMPTY codex login status                 # -> "Not logged in",           exit 1
codex features list                                  # -> the flag table quoted in §0, §3, §4
CODEX_HOME=$EMPTY codex debug models                 # -> the model catalog quoted under Ambiguity

# The poisoned fixture (§6).
mkdir -p $SCRATCH/repo/sub && cd $SCRATCH/repo && git init -q .
printf 'AGL_POISON_REPO_ROOT_AGENTS\n'   > AGENTS.md
printf 'AGL_POISON_AGENTS_OVERRIDE\n'    > AGENTS.override.md
printf 'AGL_POISON_SUBDIR_AGENTS\n'      > sub/AGENTS.md
mkdir -p .codex/skills/poison && printf -- '---\nname: poison\ndescription: AGL_POISON_REPO_SKILL\n---\n' \
    > .codex/skills/poison/SKILL.md
printf 'AGL_POISON_GLOBAL_HOME_AGENTS\n' > $EMPTY/AGENTS.md

# What reaches the model, with no model involved.
CODEX_HOME=$EMPTY codex debug prompt-input "X" | grep -o 'AGL_POISON[A-Z_]*' | sort -u
CODEX_HOME=$EMPTY codex debug prompt-input -c project_doc_max_bytes=0 \
                                           -c skills.include_instructions=false "X" \
    | grep -o 'AGL_POISON[A-Z_]*' | sort -u          # -> only AGL_POISON_GLOBAL_HOME_AGENTS

# Whether the repository's own .codex/config.toml is a channel (§6). Three instruments, both trusts.
printf 'model = "gpt-5.4"\n\n[mcp_servers.poison]\ncommand = "/bin/echo"\n' > .codex/config.toml
for trust in trusted untrusted; do
  CODEX_HOME=$EMPTY codex doctor --json -c "projects.\"$PWD\".trust_level=\"$trust\"" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['checks']['config.load']['details'])"
done                                                  # -> model '<default>', mcp servers '0', both times
CODEX_HOME=$EMPTY codex mcp list -c "projects.\"$PWD\".trust_level=\"trusted\""   # -> none configured

# What each sandbox value governs (§3). No model, no tokens.
for m in read-only workspace-write danger-full-access; do
  codex sandbox -c "sandbox_mode=\"$m\"" -- /bin/sh -c 'echo x > ./p.txt   && echo WROTE_WORKSPACE'
  codex sandbox -c "sandbox_mode=\"$m\"" -- /bin/sh -c "echo x > \$HOME/p  && echo WROTE_HOME"
  codex sandbox -c "sandbox_mode=\"$m\"" -- /usr/bin/curl -s -m 5 -o /dev/null https://example.com
  for p in .git .codex .agents; do
    codex sandbox -c "sandbox_mode=\"$m\"" -- /bin/sh -c "touch $p/probe   && echo WRITABLE"
  done
  codex sandbox -c "sandbox_mode=\"$m\"" -- /bin/sh -c '/usr/bin/env >/dev/null && echo EXEC_OK'
done
codex sandbox -c 'sandbox_mode="workspace-write"' -c 'sandbox_workspace_write.network_access=true' \
    -- /usr/bin/curl -s -m 5 -o /dev/null https://example.com          # succeeds
codex sandbox -c 'sandbox_mode="read-only"'       -c 'sandbox_workspace_write.network_access=true' \
    -- /usr/bin/curl -s -m 5 -o /dev/null https://example.com          # still fails
codex sandbox -c 'sandbox_mode="workspace-write"' -c "sandbox_workspace_write.writable_roots=[\"$PWD/.git\"]" \
    -- git commit --allow-empty -m probe                                # succeeds

# The R2 measurement (§3): the policy handed to the model, per (sandbox_mode, approval_policy).
# `prompt-input` renders messages only - it cannot show a tool list, which is why the four
# measurements listed in §10 all need a loopback instead.
profile() {                    # $1 = sandbox_mode, $2 = approval_policy as TOML
  codex debug prompt-input -c "sandbox_mode=\"$1\"" -c "approval_policy=$2" "x" | python3 -c "
import json, re, sys, hashlib
d = json.load(sys.stdin)
t = ''.join(c.get('text','') for m in d for c in (m.get('content') or []) if isinstance(c, dict))
p = re.search(r'<permission_profile[^>]*>.*?</permission_profile>', t, re.S)   # [^>]* matters
print(hashlib.sha256(p.group(0).encode()).hexdigest()[:12] if p else 'ABSENT')"
}
for m in read-only workspace-write danger-full-access; do
  for a in '"never"' '"on-failure"' '"on-request"' \
           '{granular={sandbox_approval=false,rules=false,mcp_elicitations=false}}' \
           '{granular={sandbox_approval=true,rules=true,mcp_elicitations=true}}'; do
    printf '%-19s %-12s\n' "$m" "$(profile "$m" "$a")"
  done
done                                  # -> three distinct hashes, one per mode, constant across policies
codex debug prompt-input -c 'approval_policy="untrusted"' x
      # -> Error: approval_policy = "untrusted" is no longer supported; remove this setting
codex debug prompt-input -c 'approval_policy={granular={sandbox_approval=true}}' x
      # -> Error: missing field `rules` in `approval_policy`   (three fields, found this way)

# What read-only actually restricts (§3): diff the rendered messages between the two modes.
for m in read-only workspace-write; do
  codex debug prompt-input -c "sandbox_mode=\"$m\"" "x" > "/tmp/pi-$m.json"
done
diff <(python3 -m json.tool /tmp/pi-read-only.json) <(python3 -m json.tool /tmp/pi-workspace-write.json)
                                      # -> filesystem and network only; nothing about the shell

# MCP servers from argv alone (§0).
CODEX_HOME=$EMPTY codex mcp list --json -c 'mcp_servers.agl.command="/bin/echo"' -c 'mcp_servers.agl.args=["hi"]'
CODEX_HOME=$EMPTY codex mcp list --json -c 'mcp_servers.agl={url="http://127.0.0.1:8765/mcp",tool_timeout_sec=600}'

# Where the request would go (§7). `doctor` reports the endpoint it resolved.
CODEX_HOME=$EMPTY codex doctor --json | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['checks']['network.provider_reachability']['details'])"
CODEX_HOME=$EMPTY OPENAI_BASE_URL=http://127.0.0.1:9/v1 codex doctor --json | …    # unchanged
CODEX_HOME=$EMPTY codex doctor --json -c 'chatgpt_base_url="http://127.0.0.1:9/backend-api/"' | …
CODEX_HOME=$EMPTY codex doctor --json \
  -c 'model_providers.loop={name="loop",base_url="http://127.0.0.1:9/v1",wire_api="responses"}' \
  -c 'model_provider="loop"' | …

# The strings this document reads off the binary.
strings -n 4 /opt/homebrew/Caskroom/codex/0.149.0/bin/codex | grep -c 'is not supported in exec mode'
```
