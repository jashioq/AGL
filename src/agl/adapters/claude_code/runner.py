"""`ClaudeCodeRunner` - AGL's `AgentRunner` over Claude Code, and the session it composes.

`translate.py` holds Claude Code's vocabulary, `_tools.py` holds what the agent may call, and
`_session.py` reads one stream to its end. This module is the port's three members and the one
thing none of the others may decide: what a session *is* - which options it is opened with, what
the agent is told, and what a readiness probe costs.

## Hermeticity (§3.5): the target repo contributes source code and nothing else

Three options carry it, and the SDK's default for two of them is the leaky value - which is why
they are named and argued rather than left out:

  * **`setting_sources=[]`** - read no settings file anywhere. `ClaudeAgentOptions`' default is
    `None`, which the SDK forwards by passing no `--setting-sources` flag at all, leaving the CLI
    to discover what it likes.
  * **`strict_mcp_config=True`** - ignore the repository's `.mcp.json`. The dataclass default is
    `False`.
  * **`settings` left unset** - see "Why no settings file" below.

**Verified rather than assumed, and the claim it was verifying is the old implementation's.** That
`setting_sources=[]` also keeps a repository's `CLAUDE.md` out of the session is a *consequence*
rather than something either option says, so it was measured: a repository carrying a `CLAUDE.md`
with a unique marker in it, and a local HTTP endpoint standing in for the model API so that the
request Claude Code composes could be read before anything answered it. The marker appears in the
composed request under `setting_sources=None` and under `setting_sources=["user","project","local"]`
- injected as `<system-reminder> ... # claudeMd ... Contents of <repo>/CLAUDE.md (project
instructions, checked into the codebase)` - and is absent under `setting_sources=[]`. Two controls
and one measurement, so a green result cannot be read as "there was nothing to find". The same runs
confirm `strict_mcp_config=True` keeps a planted `.mcp.json` server out of the session's MCP list,
and that a planted `.claude/agents/*` and `.claude/commands/*` register under neither.

**What that does not cover, stated rather than left to be discovered.** `setting_sources=[]`
suppresses the *target repository's* configuration; it does not make the machine's own
configuration invisible, and the operator's installed skills and subagent listings still reach the
model. That is the second channel §3.5 names and §3.11 puts out of scope for v1.1 - "v1.1 inherits
the parent environment" - and closing it is not this deliverable's to decide. The contract suite
says the same of itself: nothing in it reads or asserts an environment variable, deliberately.

**One trap worth naming, since it is invisible at the call site.** The SDK's `skills` option
silently defaults `setting_sources` to `["user", "project"]` when it is left unset. Passing `[]`
explicitly is what makes that default unreachable - so the empty list is load-bearing twice over,
and a later edit that "tidied" it to `None` would reopen the repository.

## Why no settings file

The reference implementation passed an absolute `settings` path, and the absoluteness was the
point: `cwd` is the target repository, so a relative path resolves inside it and the repository
gets to substitute AGL's own configuration. This module goes one step further and passes no
settings document at all, because there is nothing left for one to carry - deny rules ride on
`disallowed_tools`, the model on `model`, the tools on `mcp_servers` - and `--settings` is the one
flag whose whole job is to *add* a configuration document to a session that has just been told to
read none. A path that cannot be wrong is better than a path that has to be absolute, and one fewer
value reaches a command line (see below).

## Argv discipline (§3.5): every value reaching a command line is hostile

The SDK spawns the CLI with an argument *list* and no shell (`anyio.open_process(cmd, ...)`), so
nothing here is program text and no quoting is involved. That removes one class of bug and leaves
another, which the SDK names in its own source: most options are appended as **two tokens**
(`["--model", value]`), and "in the two-token form a value beginning with `-` is not consumed as
the flag's value; it parses as a separate CLI flag". The SDK closes that for exactly four options
it expects to hold untrusted values (`resume`, `session_id`, and two more) by writing them as
`--flag=value`; every other option, `--model` and `--settings` and `--add-dir` among them, is left
in the two-token form. So the guard is this module's, and stage 5's finding is the precedent: a git
ref spelled `--output=/path` made a read-only port write a file.

What this module actually puts on that command line, and what is done about each:

  * **`model`** - `translate.model_name` returns a member of a closed table, so today it cannot
    begin with `-`. It is checked anyway, because "it cannot" is a property of another module that
    nothing here would notice changing, and §3.5's rule is about the value's *position* and not its
    provenance.
  * **`cli_path`** - a constructor argument, so it comes from the composition root and ultimately
    from configuration. Checked identically.
  * **`disallowed_tools`** - joined on commas into a single token, so a rule holding a comma would
    become two rules and a rule beginning with `-` would make the whole token parse as a flag.
    Refused as an `InternalError`, because these are AGL's own strings.
  * **`cwd` - is not on the command line at all.** It is passed as `cwd=` to the process spawn,
    which is a `chdir` in the child between fork and exec and never a string anything parses. That
    is verified rather than assumed: a run whose workspace is named
    `agl $(touch MARKER); echo leaked | cat & 'q' "d" --output=x tree` starts, the CLI echoes that
    exact directory back on its `init` message, and no marker file appears anywhere.
  * **Nothing else.** `add_dirs`, `extra_args` and `settings` are all left at their empty defaults,
    which is three fewer values on a command line than the same session could have had.

**And the caller's own text never reaches argv either.** The instructions, the standing context and
the restrictions in words are composed into the *prompt*, which the SDK writes to the CLI's standard
input as JSON. The alternative was `system_prompt`, which is `["--system-prompt", text]` - a
workflow author's context beginning with `--` would be a flag, and a long one would meet `ARG_MAX`.
So `system_prompt` carries the vendor's own preset and nothing of ours: a dict with no `append` key
puts no token on the command line at all.

## Why the `claude_code` preset system prompt

`system_prompt=None` is not "the default" - the SDK forwards it as `--system-prompt ""`, and the
session then runs on a one-sentence system prompt ("You are a Claude agent, built on Anthropic's
Claude Agent SDK") with none of the harness's own instructions about how to work in a repository.
Measured on the composed request: the preset is ~28 KB of software-engineering instruction, and
selecting it costs nothing on the command line. AGL runs coding agents in checkouts, so the harness
being a coding harness is the point of choosing this harness.

## Why `permission_mode="bypassPermissions"`

Every tool call in a Claude Code session is checked against a permission decision, and in the
default mode an unapproved call waits for a person. There is no person: `AgentRunner.run` has no
interactive channel, and a run that stalls on an approval prompt is the outcome the port calls the
worst one available, because it looks exactly like work. The alternative - an allowlist naming
every tool a workflow might use - is a list that goes stale against a vendor's tool registry and
fails closed by silently refusing the framework's own reporting tool.

**The deny rules still bite, which is the part that had to be checked rather than believed.** A
bare tool name in a deny rule removes the tool from the session, and the `init` message's registered
tool list shows that happening identically under `default`, `plan`, `acceptEdits`,
`bypassPermissions` and `dontAsk` - with `ExitWorktree`, left undenied, present in every one of them
as the control. So the mode decides what happens to a call that was *not* denied, and AGL's
restrictions are decided before the mode is consulted.

Two things this rests on and states rather than hides: the workspace is a throwaway worktree
provisioned by `WorkspaceProvider` (§3.9), so "unattended" is scoped to a directory AGL made; and an
operator whose managed policy forbids the mode gets a CLI that refuses to start, which arrives here
as `UpstreamUnavailable` with the CLI's own message.

## Why `plan_only` is said in words and enforced by nothing

Claude Code has a plan mode and this module does not select it, which needs a reason. Two, and they
are about this session rather than about the mode: its exit is an *approval* - the model proposes a
plan and something has to accept it - which is the same absent person as above; and a mode that
gates tool calls would gate AGL's own reporting tool, so a `plan_only` reporting step could never
report and would fail as a step that produced nothing.

Denying the write tools instead was rejected on the port's own instruction. `plan_only` "is **not**
derived from `restrictions` and does not imply them ... inferring would mean deciding which
restrictions 'mean' planning, a policy this port has no standing to invent", and the port says what
a workflow that wants both does: "A workflow wanting both prevention and intent states both". So a
role wanting a plan-only step that also cannot write files declares `NO_FILE_WRITES` beside
`plan_only`, and gets deny rules for it from `translate.restraint`. This module renders the intent,
in words, and lets the restrictions render the prevention.

## No state between calls, and no lifetime to manage

The port has no `close()` and no session handle, and argues that each would be a harness concept a
model behind a plain HTTP API could only implement as a no-op. Nothing here needs one: a run is one
`query()` call whose generator owns the subprocess and terminates it on the way out, the asking
bridge and the tool servers are built per run because `on_question` is a per-call parameter, and the
runner itself holds only the CLI path it was constructed with. One instance therefore serves a
workflow's two concurrent reviewers without either of them being able to see the other.
"""

import tempfile
from pathlib import Path
from typing import Final

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    McpServerConfig,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import SystemPromptPreset

from agl.adapters.claude_code._session import Stderr, outcome_of
from agl.adapters.claude_code._tools import ASKING_MECHANISMS_DENIED, Asking, servers
from agl.adapters.claude_code.translate import Restraint, model_name, restraint, unready
from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    ModelId,
    QuestionHandler,
)
from agl.ports.errors import InputError, InternalError, UpstreamUnavailable

__all__ = ["ClaudeCodeRunner"]

# What this backend can be asked for at all, which for Claude Code is all four: it edits files,
# runs a shell, calls tools, and - because `_tools.py` registers an asker of AGL's own rather than
# depending on the harness's - asks mid-run on every build. A constant and not a probe: the port
# calls this "what can you do" rather than "can you do it now", requires the answer to be stable
# for the duration of a run, and gives `check_ready` the other question. Probing here would make a
# preflight answer depend on whether a network was up when it was asked.
_CAPABILITIES: Final = frozenset(
    {
        Capability.FILE_EDIT,
        Capability.SHELL,
        Capability.MID_RUN_QUESTIONS,
        Capability.TOOL_CALLING,
    }
)

# The harness's own instructions, selected by name. A dict with no `append` key, which is what puts
# nothing on the command line - see the module docstring. The type is imported from the SDK's
# `types` submodule rather than from its package root, which does not re-export it: a `TypedDict`
# is the SDK's own statement of which keys this option takes, and spelling it as a bare dict would
# have needed a `type: ignore` at the call site - which is the checker being told to stop reading
# the one option here whose shape decides what the agent is.
_PRESET: Final[SystemPromptPreset] = {"type": "preset", "preset": "claude_code"}

# What a readiness probe says and how far it is allowed to go. One turn, no tools, no system prompt
# and a reply of one word: the composed request measures ~1 KB against the installed CLI, which is
# a few hundred tokens in and a handful out. That is the cost of the only honest test of "is this
# session authenticated" - the `init` message's `apiKeySource` reports `"none"` for a perfectly good
# subscription session, so nothing short of asking the far side distinguishes logged in from logged
# out. §3.2 pays it once per provider per run, to kill a run at second zero rather than forty
# minutes in at the review step.
_READY_PROMPT: Final = "Reply with the single word: ready"

# What `plan_only` says to the agent. In AGL's terms, naming the intent rather than a mechanism,
# and saying explicitly that it is not a limit - a model that can see its editing tools and is told
# to change nothing should read that as one statement rather than as a contradiction to resolve.
_PLAN_ONLY: Final = (
    "AGL is asking you to examine and propose, and to change nothing: work out what should be "
    "done and report it, rather than doing it. This is what is being asked of you, not a "
    "restriction placed on you - anything you are actually forbidden to do is listed separately."
)

# How a composed prompt introduces the standing context it was given. `AgentTask.context` is kept
# apart from `instructions` by the port so that a backend which distinguishes them can honour the
# distinction; this one joins them, which the port allows in as many words, and the heading is what
# keeps the join legible to the agent reading it.
_CONTEXT_HEADING: Final = "AGL is running this task with the following standing context:"


class ClaudeCodeRunner(AgentRunner):
    """`AgentRunner` over the Claude Code CLI, through `claude_agent_sdk`.

    Built by `config/container.py` and addressed only through the port. The one constructor
    argument is the CLI to drive: `None` lets the SDK find `claude` on `PATH`, which is what an
    ordinary installation wants, and a path is for an operator who has one somewhere else. There is
    nothing else to configure - the model, the workspace, the tools and the restrictions all arrive
    per call on an `AgentTask`, and the settings that make a session hermetic are not settings at
    all but this adapter's obligations under §3.5.
    """

    def __init__(self, cli_path: Path | None = None) -> None:
        """`cli_path` is where the Claude Code CLI lives, or `None` to resolve it from `PATH`.

        Checked here and not at first use, because it reaches a command line and a value that
        cannot be used should be refused where the reader can still see who supplied it. Nothing
        else happens: a constructor cannot await, and a CLI that is not there is `check_ready`'s
        answer one moment later rather than a composition root that fails for every run including
        the ones that never touch this backend.
        """
        self._cli_path = None if cli_path is None else Path(_inert(str(cli_path), "cli_path"))

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        """What Claude Code can be asked for when serving `model`. The same answer every time.

        The model is checked and then not consulted: this adapter serves three models and there is
        no capability any one of them has and another lacks, so answering the same thing for all
        three is the truth rather than an implementation that ignores its argument. `model_name`
        is what makes the argument load-bearing - a `ModelId` this adapter does not serve is an
        `InputError` here as it is everywhere else (§3.2), and answering "I can do all four" for a
        model this runner would refuse to run is the kind of preflight answer that gets a run
        admitted and then killed.
        """
        model_name(model)
        return _CAPABILITIES

    async def check_ready(self, model: ModelId) -> None:
        """Whether Claude Code can serve `model` right now: installed, on `PATH`, authenticated.

        One turn against the far side, because the first two are answerable from this process and
        the third is not - see `_READY_PROMPT` for what it costs and why nothing cheaper is honest.

        **`UpstreamUnavailable` and nothing else**, which is `translate.unready`'s whole job: the
        port allows this member one refusal, `tests/contracts/_agent_preflight.py` fails any other
        exception by name, and §3.2's preflight catches that class alone - so a different one would
        reach the top of the CLI as exit 70 and tell a person to file a bug about their own
        logged-out session. The one exception is an unserved `ModelId`, refused before anything is
        attempted, which is the port's own `InputError` and not a statement about the backend.

        The probe runs in a temporary directory of its own rather than wherever AGL happens to be
        standing. Readiness is a fact about the harness, and a probe that inherited a working
        directory would be asking it inside whatever repository the user ran `agl` from.
        """
        name = model_name(model)
        with tempfile.TemporaryDirectory(prefix="agl-ready-") as elsewhere:
            options = ClaudeAgentOptions(
                cwd=elsewhere,
                model=name,
                system_prompt="",
                tools=[],
                setting_sources=[],
                strict_mcp_config=True,
                permission_mode="bypassPermissions",
                max_turns=1,
                cli_path=self._cli_path,
                stderr=Stderr(),
            )
            try:
                async for message in query(prompt=_READY_PROMPT, options=options):
                    if isinstance(message, ResultMessage) and message.is_error:
                        raise UpstreamUnavailable(
                            f"the Claude Code CLI answered a readiness check with an error "
                            f"instead of a result: {message.result or message.subtype}. A session "
                            f"that is not authenticated, an exhausted allowance and an unusable "
                            f"request all arrive this way, so the message above is what to act on"
                        )
            except ClaudeSDKError as error:
                raise unready(error) from error

    async def run(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        """Run `task` in its workspace and report what happened.

        Everything that makes this session AGL's rather than the machine's is in `_options`, and
        everything the agent is told is in `_prompt`; the reading of the stream is `_session.py`'s.
        `on_question` is bound into an `Asking` built for this call alone, which is what lets one
        runner serve a workflow's two concurrent reviewers without either seeing the other's
        handler.
        """
        limits = restraint(task.restrictions)
        asking = Asking(on_question)
        stderr = Stderr()
        return await outcome_of(
            task,
            _prompt(task, limits),
            _options(task, limits, servers(task.tools, asking), self._cli_path, stderr),
            asking=asking,
            on_activity=on_activity,
            stderr=stderr,
        )


def _options(
    task: AgentTask,
    limits: Restraint,
    supplied: dict[str, McpServerConfig],
    cli_path: Path | None,
    stderr: Stderr,
) -> ClaudeAgentOptions:
    """Everything the session is opened with, in one expression, so the whole of it is readable.

    Every field the module docstring argues for is written out here even where it repeats the
    SDK's own default - `add_dirs`, `extra_args` and `settings` especially. A hermeticity setting
    that is present because nobody set it is one nobody can see, and two of the three that matter
    most have a leaky default; the empty ones are the record that they were considered.
    """
    return ClaudeAgentOptions(
        cwd=task.workspace,
        model=_inert(model_name(task.model), "model"),
        system_prompt=_PRESET,
        setting_sources=[],
        strict_mcp_config=True,
        settings=None,
        add_dirs=[],
        extra_args={},
        mcp_servers=supplied,
        disallowed_tools=_rules(limits, ASKING_MECHANISMS_DENIED),
        permission_mode="bypassPermissions",
        cli_path=cli_path,
        stderr=stderr,
    )


def _prompt(task: AgentTask, limits: Restraint) -> str:
    """What the agent is asked, as one string: the standing parts first, the task last.

    **A task with no context, no restrictions and no `plan_only` produces the instructions
    verbatim**, byte for byte, with nothing added. That is deliberate rather than an optimisation:
    a workflow author's prompt is the whole of what they wrote, and a framework that always wrapped
    it in headings would be editing every prompt in the system to say something about three fields
    that were empty.

    The task goes last because it is what the agent acts on and the closest thing to its first
    move; the standing parts go above it in the order they constrain - context, then limits, then
    what is being asked for.
    """
    standing = [
        f"{_CONTEXT_HEADING}\n\n{task.context}" if task.context else "",
        limits.in_words,
        _PLAN_ONLY if task.plan_only else "",
    ]
    return "\n\n".join([*(part for part in standing if part), task.instructions])


def _inert(value: str, what: str) -> str:
    """`value`, or `InputError` if it would parse as a flag when it reached argv as its own token.

    §3.5, in this module's docstring at length: the SDK appends most options as two tokens, and a
    value beginning with `-` is then not the flag's value but a flag of its own - the SDK says so
    in its own source and closes it for four options that are not these. `InputError` because both
    values this is applied to come from a caller (a workflow naming a model, an operator
    configuring a CLI path), nothing has been attempted when it refuses, and exit 2 sends the
    reader to what they wrote rather than to a bug report.
    """
    if value.startswith("-"):
        raise InputError(
            f"the Claude Code adapter will not use {value!r} as its {what}: it begins with '-', "
            f"and this value reaches the CLI as its own argument, where a leading dash makes it a "
            f"flag rather than a value. §3.5: every value reaching a command line is hostile "
            f"regardless of where it came from"
        )
    return value


def _rules(limits: Restraint, also: tuple[str, ...]) -> list[str]:
    """The deny rules for this run, checked for the two shapes the CLI's own tokenizer would ruin.

    The rules are joined on commas into one argument, so a rule holding a comma silently becomes
    two rules and a rule beginning with `-` makes the whole argument parse as a flag - in a deny
    list, either one is a restriction that stopped applying without anything saying so, which is
    the outcome `translate.py` exists to prevent.

    `InternalError` and not `InputError`, which is the difference between this and `_inert`: a
    workflow author names restrictions, but the *strings* are AGL's own, produced by
    `translate.restraint` out of a closed table. A rule that cannot be spelled is our bug in that
    table, not something anybody typed.
    """
    rules = [*limits.denied_tools, *also]
    unusable = sorted(rule for rule in rules if "," in rule or rule.startswith("-"))
    if unusable:
        raise InternalError(
            f"these deny rules cannot be passed to the Claude Code CLI: {unusable}. Deny rules "
            f"are joined on commas into one argument, so a rule holding a comma becomes two rules "
            f"and a rule beginning with '-' turns the argument into a flag - either way the "
            f"restriction stops being enforced while still appearing to be"
        )
    return rules
