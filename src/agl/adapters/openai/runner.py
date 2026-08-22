"""`OpenAiRunner` - AGL's `AgentRunner` over the Codex CLI, and the session it composes.

`translate.py` holds the harness's vocabulary, `_tools.py` holds what the agent may call and the
server that carries it, `_http.py` is the socket under that server, and `_session.py` reads one
child's event stream to its end. This module is the port's three members and the one thing none of
the others may decide: what a session *is* - which command line it is opened with, what the agent
is told, and what a readiness probe costs.

## No general process helper

The third module in this repository to run a child process, and the third to keep its own. §3.4's
git runner is argv-only, buffered, and classifies by exit code; stage 6's shell verifier is a
*shell* by design, signals a process group, and carries a deadline; this one is argv-only like the
first, group-signalling like the second, and unlike either it is **streamed** - it consumes its
child's output as it arrives, because `on_activity` is "what is happening right now" and a step can
run for an hour (`_session.py` argues that at length, as its own finding).

Seven axes and no two of the three agree on all of them: shell or exec, buffered or streamed,
`DEVNULL` or `PIPE` on standard input, merged or separate standard error, process or group
signalling, deadline or none, exit code or stream as the failure signal. This module alone
disagrees with itself on the fourth - the readiness probe merges the child's two streams so that
one string carries the reason, and a run keeps them apart so that a diagnostic cannot be mistaken
for an event.

A helper covering all three would take a flag per axis and each flag would exist to say which of
three callers it was being, which is the definition of an abstraction that has not found anything
in common. So the decision is taken and recorded rather than deferred again: **there is no
`adapters/_process.py`, and a fourth consumer arriving is not by itself a reason to build one.**
The same paragraph, under the same heading, is in `adapters/git/_runner.py` and
`adapters/shell/verifier.py`; three modules carrying it is the index a fourth would need.

## Hermeticity (§3.5): the target repo contributes source code and nothing else

Six values carry it, and each closes a channel that was measured open. The measurement is free and
was reproduced for this module: a repository carrying a marked `AGENTS.md`, a marked
`AGENTS.override.md`, a marked `AGENTS.md` in a subdirectory and a marked `.codex/skills/*/SKILL.md`
is rendered with `codex debug prompt-input`, which prints the model-visible prompt as JSON and
contacts no model. Without the overrides three of those markers reach the model. With them, none
does.

  * **`-c project_doc_max_bytes=0`** - no `AGENTS.md` the repository contributes, at any depth,
    including the `.override.md` form that takes precedence over it and the fallback filenames.
  * **`-c skills.include_instructions=false`** - no skills. **This is the row the contract suite's
    Codex configuration does not carry.** A repository's `.codex/skills/*/SKILL.md` reaches the
    model - its name and its description - which is a repo-contributed instruction channel outside
    `AGENTS.md`, and `tests/contracts/_agent_hermeticity.py`'s Codex row lists `AGENTS.md` and
    `.codex/config.toml` and not that file. The suite may not be edited from here, so the row is
    carried by this adapter's own test instead, planted and asserted there.
  * **`--ignore-rules`** - no execpolicy `.rules` file, the operator's or the repository's. Those
    decide whether a command is allowed, prompted for or forbidden, and a repository that shipped
    one would be deciding what the agent may run.
  * **`--ignore-user-config`** - no `$CODEX_HOME/config.toml`. Not a repository channel and passed
    anyway: it is the operator's own file, and a run whose model, provider or tool set depends on
    it is a run that behaves differently on two machines for a reason no workflow declared.
  * **`--color never`** - nothing here parses terminal escapes, and a harness that decides to
    colour its output because a terminal is attached would be putting them in the one stream this
    adapter reads.
  * **`--json`** - the event stream this adapter is written against, rather than prose for a human.

**What that does not cover, stated rather than left to be discovered.** Those settings suppress the
*target repository's* configuration; they do not make the operator's machine invisible. The
operator's own `$CODEX_HOME/AGENTS.md` still reaches the model, every knob discoverable for free
leaves it in place, and the only thing that would remove it - moving `CODEX_HOME` - is where the
credential lives. That is the second channel §3.5 names and §3.11 puts out of scope for v1.1,
"v1.1 inherits the parent environment", and it is exactly where the other adapter's line falls too.
Two harnesses landing on the same boundary independently is mild evidence that the boundary is
real.

**One channel with no flag at all, and the structural reasons it is closed anyway.** This harness
documents a *project* configuration layer - `.codex/config.toml` from the project root down, for
trusted projects - and nothing suppresses it: `--ignore-user-config` closes the operator's file and
`--ignore-rules` closes `.rules`, and neither closes this. On the version measured it is inert
under both trust levels. Three things stand behind that: AGL's workspaces are fresh worktrees at
fresh paths (§3.9), so they are untrusted by default and the layer is skipped; project-local
configuration is documented as unable to override the provider and auth keys, so a repository can
never redirect the endpoint; and this harness will not run a repository's hooks without persisted
trust, which a directory made moments ago does not have - `--dangerously-bypass-hook-trust` is what
would grant it, and AGL must never pass that.

**And the workspace is not written into a configuration expression.** Forcing the trust level down
explicitly would mean interpolating the workspace's own path into a TOML key on the command line,
where a path holding a quote produces a document that means something else. That is §3.5's rule
arriving from the other direction - the danger is not only what a value does on argv, it is what a
value does inside a syntax - so the path stays off the command line entirely.

## Argv discipline (§3.5): every value reaching a command line is hostile

The child is started with an argument **list** and no shell, so nothing here is program text and no
quoting is involved. What that leaves is the two-token form: `["-m", value]` puts `value` where a
leading `-` makes it a flag of its own rather than the flag's value. Stage 5's finding is the
precedent - a git ref spelled `--output=/path` made a read-only port write a file.

What actually reaches this command line, and what is done about each:

  * **the model slug** - `translate.model_slug` answers out of a closed table, so today it cannot
    begin with `-`. It is checked anyway. `translate.py` declined to put the check inside that
    function and said why: a closed table in the same module makes the branch unreachable there,
    and the guarantee belongs where the value reaches a command line. This is that place.
  * **the CLI path** - a constructor argument, so it comes from the composition root and ultimately
    from configuration. Checked identically, at construction, where the reader can still see who
    supplied it.
  * **the sandbox mode and its overrides** - literals from `translate.py`, which interpolates
    nothing a caller supplied. Nothing to check, and that is a property of that module rather than
    a hope about this one.
  * **the MCP server addresses** - composed here out of a loopback address, a port the OS assigned
    and a token this process minted. No part of them comes from a caller.
  * **the workspace - is not on the command line at all.** The harness offers `-C <DIR>` for it and
    this adapter does not use it: the directory is passed as `cwd=` to the process spawn, which is
    a `chdir` in the child between fork and exec and never a string anything parses. Nothing is
    lost, because that flag's own default is the working directory. It also closes a second thing
    the flag would leave open - a child inheriting AGL's own working directory would resolve the
    project root, and every `AGENTS.md` above it, from whatever repository a person happened to run
    `agl` in.

**And the caller's own text never reaches argv either.** The instructions, the standing context and
the restrictions in words are composed into one prompt and written to the child's **standard
input**, which the harness reads when the prompt argument is `-`. It is the largest untrusted
string in the system: a prompt beginning with `-` would parse as a flag and a long one would meet
`ARG_MAX`.

## Tool supply, and the one number that decides whether `MID_RUN_QUESTIONS` is real

`_tools.py` runs two MCP servers on one loopback listener and this module renders their addresses
into `-c mcp_servers.<name>={...}` overrides - measured to be accepted from the command line alone,
in this transport, with no file on disk. Three keys go with each address and each is deliberate:

  * **`tool_timeout_sec`** defaults to **60**, and AGL's asking tool waits on a person. A default
    that expires under somebody's thinking time is the specific way `MID_RUN_QUESTIONS` dies
    quietly - the call fails, the agent is told the tool errored, and it carries on guessing - so
    this is not a tuning knob, it is the thing that makes the capability true. A day is not a
    deadline AGL chose either: `AgentTask` carries no timeout because "a framework-level clock on
    that is a framework-level opinion", and this is the closest this harness gets to none while
    still being a number.
  * **`startup_timeout_sec`** is stated rather than inherited. The servers are bound before the
    child is spawned, so the handshake is a loopback round trip and the value is generous; what it
    buys is that a packaged default moving between releases cannot quietly shorten it.
  * **`default_tools_approval_mode="auto"`** - the value that does not ask. Measured against the
    loader itself, which names four (`auto`, `prompt`, `writes`, `approve`) and refuses anything
    else by name; in this harness's non-interactive mode no approval can ever be granted, so a
    server in a mode that asks is a tool call that dies waiting for a person who cannot be reached.

## The approval setting, and why choosing it here is safe

`translate.APPROVAL` carries it, as a `-c` override rather than a flag, because this build's
non-interactive command has no `--ask-for-approval` at all. The R2 argument is in that module: the
policy handed to the model is byte-identical across every approval policy that loads and varies
only with the sandbox mode, so the approval setting cannot widen or narrow what the agent may
attempt. What it decides is whether the agent is *taught to try* an escalation that this mode
refuses with a protocol error, and `never` is the value that tells it not to.

**One thing an operator can do to all of this without saying so.** A managed or enterprise
requirements file can pin the sandbox modes a machine allows, and this harness's behaviour then is
a *fallback* rather than a refusal - it substitutes the required value and says so in a message
nobody is reading. Contrast the other adapter, where a forbidden permission mode produces a CLI
that will not start. So on such a machine the restrictions in words are the only part of a
`Restriction` still standing, which is one of `translate.py`'s reasons for always sending them.

## Why `plan_only` is said in words and enforced by nothing

This harness has a plan mode and does not expose it on the command this adapter drives, so words
are what is available. The findings suggest pairing them with the read-only sandbox; that is
declined, on the port's own instruction. `plan_only` "is **not** derived from `restrictions` and
does not imply them ... inferring would mean deciding which restrictions 'mean' planning, a policy
this port has no standing to invent", and the port says what a workflow wanting both does: it
states both. So a role that wants a plan-only step which also cannot write files declares
`NO_FILE_WRITES` beside `plan_only` and gets the read-only sandbox from `translate.sandbox`. This
module renders the intent; the restrictions render the prevention.

## Why the session is not ephemeral

This harness can be told to run without persisting a session file, and is not. The rollout it
leaves behind is a transcript of an unattended run, written by the operator's own harness into the
operator's own directory - which is precisely the environment §3.11 says v1.1 inherits - and it is
the only record of what an agent actually did on a run nobody watched. AGL never reads it: §3.7
accepts in writing that a crash mid-negotiation re-runs the step, so nothing here resumes anything.
A person does, by hand, on the day a run went wrong, and taking the transcript away would leave
them with an exit status and fifty lines of standard error.

That decision settles a second one. The event stream carries a session identity on its first frame,
and `_session.py` ignores it: `AgentOutcome` excludes vendor session identity in writing, this
framework has no log to put one in, and the transcript being on disk means a person resumes the
most recent session without needing a number from us.

## No state between calls, and no lifetime to manage

The port has no `close()`, no session handle and no settings-file parameter, and argues that each
would be a harness concept a model behind a plain HTTP API could only implement as a no-op. Nothing
here needs one: a run is one child process, the MCP servers are built per run because `on_question`
is a per-call parameter and their listener is bracketed around that child by `async with`, and the
runner itself holds only the CLI path it was constructed with. One instance therefore serves a
workflow's two concurrent reviewers without either of them being able to see the other.
"""

import asyncio
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from agl.adapters.openai._session import outcome_of
from agl.adapters.openai._tools import ASKING_TOOL, Asking, Supply
from agl.adapters.openai.translate import (
    APPROVAL,
    Sandbox,
    launch_failure,
    model_slug,
    sandbox,
    unready,
)
from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    ModelId,
    QuestionHandler,
)
from agl.ports.errors import InputError

__all__ = ["OpenAiRunner"]

# The binary this adapter drives, when the composition root has nothing to hand over. A bare name
# rather than a path, resolved through `PATH` at spawn time, which is what an ordinary installation
# wants; an operator with one somewhere else passes a path to the constructor.
_CLI: Final = "codex"

# What this backend can be asked for at all, which is all four: it edits files, runs commands, and
# - because `_tools.py` runs a server of AGL's own rather than depending on the harness's asking
# mechanism, which this mode refuses by name - calls tools and asks mid-run on every build. A
# constant and not a probe: the port calls this "what can you do" rather than "can you do it now",
# requires the answer to be stable for the duration of a run, and gives `check_ready` the other
# question. Probing here would make a preflight answer depend on whether a network was up when it
# was asked.
_CAPABILITIES: Final = frozenset(
    {
        Capability.FILE_EDIT,
        Capability.SHELL,
        Capability.MID_RUN_QUESTIONS,
        Capability.TOOL_CALLING,
    }
)

# The readiness probe, and the whole of it. Free on this backend: it exits 0 printing that it is
# logged in and 1 printing that it is not, both measured, the second against a credential-free home
# directory. The other adapter cannot answer the same question without spending a turn - two
# backends, one port member, costs differing by three orders of magnitude, which is the clearest
# available vindication of keeping `check_ready` separate from `capabilities()`.
_READY: Final = ("login", "status")

# The non-interactive command, and the prompt argument that means "read it from standard input".
# Passed explicitly rather than left off: omitting the positional argument reads stdin too, and a
# reader of this list should be able to see where the prompt went rather than infer it from a gap.
_EXEC: Final = "exec"
_FROM_STDIN: Final = "-"

# Everything about a session that never varies with the task. Ordered so that a person reading a
# composed command line meets the output format first, then hermeticity, then the approval
# setting - the module docstring argues each. `--skip-git-repo-check` is here because a `Workspace`
# is a directory the port describes as absolute and nothing more: AGL's own are worktrees (§3.9)
# and the check would pass for them, but a harness refusing to start in a directory the port
# permits would be this adapter inventing a precondition the port does not have.
_ALWAYS: Final[tuple[str, ...]] = (
    "--json",
    "--color",
    "never",
    "--skip-git-repo-check",
    "--ignore-rules",
    "--ignore-user-config",
    "-c",
    "project_doc_max_bytes=0",
    "-c",
    "skills.include_instructions=false",
    *APPROVAL,
)

# How long an MCP tool call may take, in seconds, and how long the harness waits for a server to
# come up. The first is the number `MID_RUN_QUESTIONS` rests on; the module docstring argues both.
_TOOL_SECONDS: Final = 86_400
_STARTUP_SECONDS: Final = 30

# What `plan_only` says to the agent. In AGL's terms, naming the intent rather than a mechanism,
# and saying explicitly that it is not a limit - a model that can see its editing tools and is told
# to change nothing should read that as one statement rather than as a contradiction to resolve.
_PLAN_ONLY: Final = (
    "AGL is asking you to examine and propose, and to change nothing: work out what should be "
    "done and report it, rather than doing it. This is what is being asked of you, not a "
    "restriction placed on you - anything you are actually forbidden to do is listed separately."
)

# What a run that has somewhere to send a question tells the agent, and the one place §3.7's
# "agents are instructed to use it" is said in the prompt rather than left to a tool's own
# `description` - which a model reads once it is already considering that tool, and which therefore
# cannot be what makes it consider it.
#
# The qualified name is `mcp__<server>__<tool>` and both halves of it are `_tools.py`'s, which is
# why it arrives from there rather than being written out again here: naming a tool the session
# does not register is worse than naming none, and a copy of a name is a copy that can drift.
_MAY_ASK: Final = (
    "There is a person running this task and you can put a question to them and wait for their "
    f"answer: call the tool `{ASKING_TOOL}`. It will wait as long as they take. Use it when a "
    "decision is genuinely theirs to make rather than guessing at what they would want."
)

# How a composed prompt introduces the standing context it was given. `AgentTask.context` is kept
# apart from `instructions` by the port so that a backend which distinguishes them can honour the
# distinction; this harness takes one prompt, so this one joins them, which the port allows in as
# many words - and the heading is what keeps the join legible to the agent reading it.
_CONTEXT_HEADING: Final = "AGL is running this task with the following standing context:"


class OpenAiRunner(AgentRunner):
    """`AgentRunner` over the Codex CLI, driven as a child process rather than through an SDK.

    Built by `config/container.py` and addressed only through the port. The one constructor
    argument is the CLI to drive: `None` resolves the ordinary installation from `PATH`, and a path
    is for an operator who has one somewhere else. There is nothing else to configure - the model,
    the workspace, the tools and the restrictions all arrive per call on an `AgentTask`, and the
    settings that make a session hermetic are not settings at all but this adapter's obligations
    under §3.5.
    """

    def __init__(self, cli_path: Path | None = None) -> None:
        """`cli_path` is where the CLI lives, or `None` to resolve it from `PATH`.

        Checked here and not at first use, because it reaches a command line and a value that
        cannot be used should be refused where the reader can still see who supplied it. Nothing
        else happens: a constructor cannot await, and a CLI that is not there is `check_ready`'s
        answer one moment later rather than a composition root that fails for every run including
        the ones that never touch this backend.
        """
        self._cli = _CLI if cli_path is None else _not_a_flag(str(cli_path), "cli_path")

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        """What this backend can be asked for when serving `model`. The same answer every time.

        The model is checked and then not consulted: this adapter serves three models and there is
        no capability one of them has and another lacks, so answering the same thing for all three
        is the truth rather than an implementation that ignores its argument. `model_slug` is what
        makes the argument load-bearing - a `ModelId` this adapter does not serve is an
        `InputError` here as it is everywhere else (§3.2), and answering "I can do all four" for a
        model this runner would refuse to run is the kind of preflight answer that gets a run
        admitted and then killed.
        """
        model_slug(model)
        return _CAPABILITIES

    async def check_ready(self, model: ModelId) -> None:
        """Whether this backend can serve `model` right now: installed, on `PATH`, authenticated.

        All three for free, which is this backend's one clear advantage over the other: the CLI
        answers the authentication question locally, out of its own credential store, without
        contacting anything. §3.2 pays for this once per provider per run to kill a run at second
        zero rather than forty minutes in at the review step, and here that costs a process start.

        **`UpstreamUnavailable` and nothing else**, which is `translate.unready`'s whole job: the
        port allows this member one refusal, `tests/contracts/_agent_preflight.py` fails any other
        exception by name, and §3.2's preflight catches that class alone - so a different one would
        reach the top of the CLI as exit 70 and tell a person to file a bug about their own
        logged-out session. The one exception is an unserved `ModelId`, refused before anything is
        attempted, which is the port's own `InputError` and not a statement about the backend.

        The two output streams are merged here and kept apart during a run. A probe has one thing
        to say and a person needs it in one string, whichever stream the CLI chose to say it on; a
        run has an event stream on one and diagnostics on the other, and merging those would put a
        warning in the middle of the thing this adapter parses.

        It runs in a temporary directory of its own rather than wherever AGL happens to be
        standing. Readiness is a fact about the harness, and a probe that inherited a working
        directory would be asking it inside whatever repository the operator ran `agl` from.
        """
        model_slug(model)
        with tempfile.TemporaryDirectory(prefix="agl-ready-") as elsewhere:
            try:
                child = await asyncio.create_subprocess_exec(
                    self._cli,
                    *_READY,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=elsewhere,
                )
            except OSError as error:
                raise launch_failure(error) from error
            said, _ = await child.communicate()
            status = await child.wait()
        if status != 0:
            raise unready(status, said.decode("utf-8", errors="replace").strip())

    async def run(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        """Run `task` in its workspace and report what happened.

        The order is the safety property. The model is rendered and checked **first**, so a value
        that would parse as a flag is refused before a socket is bound or a process exists; then
        the servers are started, because the harness connects to them while it is coming up; then
        the child runs inside that bracket, so there is no path out of here that leaves a port
        open. `on_question` is bound into an `Asking` built for this call alone, which is what lets
        one runner serve a workflow's two concurrent reviewers without either seeing the other's
        handler.
        """
        slug = _not_a_flag(model_slug(task.model), "model")
        limits = sandbox(task.restrictions)
        asking = Asking(on_question)
        async with Supply(task.tools, asking) as supply:
            return await outcome_of(
                _argv(self._cli, slug, limits, supply.urls),
                prompt=_prompt(task, limits, may_ask=on_question is not None),
                workspace=task.workspace,
                asking=asking,
                on_activity=on_activity,
            )


def _argv(cli: str, slug: str, limits: Sandbox, urls: Mapping[str, str]) -> list[str]:
    """The whole command line, in one expression, so that all of it is readable in one place.

    Written out rather than assembled by a series of appends for the reason the other adapter
    writes out its options: a setting that is present because nobody set it is one nobody can see,
    and every token here closes something the module docstring names.

    The prompt is not in this list. It is the last argument's *meaning* - `-` says the instructions
    come from standard input - and §3.5 is why.
    """
    return [
        cli,
        _EXEC,
        *_ALWAYS,
        "-s",
        limits.mode,
        *limits.options,
        "-m",
        slug,
        *_supplied(urls),
        _FROM_STDIN,
    ]


def _supplied(urls: Mapping[str, str]) -> list[str]:
    """The MCP servers, as configuration overrides, one `-c` pair each.

    Sorted by name so that two runs of the same task produce the same command line but for the
    port and the token: a mapping's order is not something to put in front of a person comparing
    two failures.

    The value is a TOML inline table built entirely out of this process's own strings - a loopback
    address, a port the OS assigned, a token minted here, and three numbers written above. Nothing
    a caller supplied is interpolated into it, which is what keeps §3.5's rule about what a value
    does *inside a syntax* from having any work to do here.
    """
    return [
        token
        for name in sorted(urls)
        for token in (
            "-c",
            f"mcp_servers.{name}={{"
            f'url="{urls[name]}",'
            f"tool_timeout_sec={_TOOL_SECONDS},"
            f"startup_timeout_sec={_STARTUP_SECONDS},"
            f'default_tools_approval_mode="auto"'
            f"}}",
        )
    ]


def _prompt(task: AgentTask, limits: Sandbox, *, may_ask: bool) -> str:
    """What the agent is asked, as one string: the standing parts first, the task last.

    **A task with no context, no restrictions and no `plan_only`, run with no question handler,
    produces the instructions verbatim**, byte for byte, with nothing added. That is deliberate
    rather than an optimisation: a workflow author's prompt is the whole of what they wrote, and a
    framework that always wrapped it in headings would be editing every prompt in the system to say
    something about four things that were not there.

    **`may_ask` is the fourth, and it is a parameter rather than a field of `task` because it is
    not one**: whether a question can be answered is decided per call, by whoever passed
    `on_question` to `run`. §3.7 puts the asking tool in the framework's hands and says in the same
    sentence that agents are *instructed* to use it. So a run given a handler is told here that it
    can ask and what to call; a run given none is told nothing - the tool is registered either way,
    and an agent that asks with nobody listening spends a turn to be told no answer is available.

    The task goes last because it is what the agent acts on and the closest thing to its first
    move; the standing parts go above it in the order they constrain - context, then limits, then
    what the session makes available, then what is being asked for.
    """
    standing = [
        f"{_CONTEXT_HEADING}\n\n{task.context}" if task.context else "",
        limits.in_words,
        _MAY_ASK if may_ask else "",
        _PLAN_ONLY if task.plan_only else "",
    ]
    return "\n\n".join([*(part for part in standing if part), task.instructions])


def _not_a_flag(value: str, what: str) -> str:
    """`value`, or `InputError` if it would parse as a flag when it reached argv as its own token.

    §3.5, and the module docstring at length: options are appended as two tokens, and a value
    beginning with `-` is then not the flag's value but a flag of its own. `InputError` because
    both values this is applied to come from a caller - a workflow naming a model, an operator
    configuring a CLI path - nothing has been attempted when it refuses, and exit 2 sends the
    reader to what they wrote rather than to a bug report against AGL.

    `translate.model_slug` cannot produce such a value today, which is the argument for checking it
    here rather than an argument against: the reason it cannot is a closed table in another module,
    and nothing in this one would notice that module gaining an entry.
    """
    if value.startswith("-"):
        raise InputError(
            f"the OpenAI adapter will not use {value!r} as its {what}: it begins with '-', and "
            f"this value reaches the CLI as its own argument, where a leading dash makes it a flag "
            f"rather than a value. §3.5: every value reaching a command line is hostile regardless "
            f"of where it came from"
        )
    return value
