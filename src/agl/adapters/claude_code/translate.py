import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, assert_never
from claude_agent_sdk import (
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    EffortLevel,
    ProcessError,
    ResultError,
    ToolUseBlock,
)
from agl.ports.agent import (
    ChosenClaude,
    ChosenOpenAI,
    Claude,
    ClaudeEffort,
    ModelChoice,
    ModelId,
    Restriction,
)
from agl.ports.errors import AglError, InputError, UpstreamUnavailable, UpstreamUnexpected

__all__ = [
    "CROSS_SESSION_DENIED",
    "Restraint",
    "activity",
    "effort_level",
    "last_words",
    "model_name",
    "restraint",
    "translated",
    "unready",
]

def _bash(*commands: str) -> tuple[str, ...]:
    # The space-star form and not `Bash(x:*)`: the harness classifies a rule ending `:*` as a prefix
    # rule and an unescaped `*` elsewhere as a glob, and matches the two differently.
    return tuple(f"Bash({command} *)" for command in commands)

_GIT_WRITES: Final = (
    "git add",
    "git am",
    "git apply",
    "git bisect",
    "git branch",
    "git checkout",
    "git cherry-pick",
    "git clean",
    "git commit",
    "git merge",
    "git mv",
    "git notes",
    "git rebase",
    "git reset",
    "git restore",
    "git revert",
    "git rm",
    "git stash",
    "git switch",
    "git tag",
    "git clone",
    # `config` is here although it is mostly a read: `pull.twohead = ours` makes a merge land none
    # of the child's work and exit 0, so an agent editing it edits what AGL's own integration means.
    "git config",
    "git fetch",
    "git filter-branch",
    "git gc",
    "git init",
    "git maintenance",
    "git prune",
    "git pull",
    "git push",
    "git reflog",
    "git remote",
    "git repack",
    "git replace",
    "git sparse-checkout",
    "git submodule",
    "git worktree",
    "git commit-tree",
    "git fast-import",
    "git hash-object",
    "git mktag",
    "git mktree",
    "git symbolic-ref",
    "git update-index",
    "git update-ref",
    "git write-tree",
)

_DENIALS: Final[Mapping[Restriction, tuple[str, ...]]] = MappingProxyType(
    {
        # `EnterWorktree`/`ExitWorktree` are the harness's own git-worktree management: writing to
        # version control through a tool rather than through `git`, which is what the pattern rules
        # cannot see.
        Restriction.NO_VCS_WRITES: ("EnterWorktree", "ExitWorktree", *_bash(*_GIT_WRITES)),
        # An output redirect's target is checked as a file write against `Edit` rules, and `//`
        # anchors at the filesystem root rather than at the settings source, so it reaches outside
        # the workspace too.
        Restriction.NO_FILE_WRITES: ("Edit", "Write", "NotebookEdit", "Edit(//**)"),
        # `Monitor` is here because the PowerShell tool's own refusal message says "Monitor runs
        # bash"; nothing in the permission reference mentions it.
        Restriction.NO_SHELL: ("Bash", "PowerShell", "Monitor"),
        Restriction.NO_NETWORK: ("WebFetch", "WebSearch"),
    }
)

# Denied on every run rather than under a `Restriction`, because none of the four is about this and
# an unrestricted role has no more business here than a restricted one. The CLI listens on a socket
# per process under `/tmp/cc-socks` that accepts injected user messages from anything running as the
# same user, so the reach is a local one and `NO_NETWORK` is the wrong word for it.
#
# `SendMessage` carries a recipient and `ListAgents` is what lists the recipients to it; the `Cron`
# three and `ScheduleWakeup` arm a turn that fires later, the two halves answering to
# `claude_agent_sdk.types.TaskNotificationOriginSubkind`'s two values. `CLAUDE_CODE_DISABLE_CRON` is
# what turns the `Cron` three off, and `_environment.withheld` blanks it.
CROSS_SESSION_DENIED: Final = (
    "CronCreate",
    "CronDelete",
    "CronList",
    "ListAgents",
    "ScheduleWakeup",
    "SendMessage",
)

_IN_WORDS: Final[Mapping[Restriction, str]] = MappingProxyType(
    {
        Restriction.NO_VCS_WRITES: (
            "Do not change version control in any way: no commits, no staging, no branches, "
            "tags, merges, rebases, resets, stashes, pushes, fetches, worktrees or changes to "
            "git configuration. Leave your work as edits in the working tree; AGL records it."
        ),
        Restriction.NO_FILE_WRITES: (
            "Do not create, modify, move or delete any file, by any route - not with an editing "
            "tool, not with a shell redirect, and not by running a program that writes one."
        ),
        Restriction.NO_SHELL: (
            "Do not run shell commands, by any route, including through another tool that runs "
            "one for you."
        ),
        Restriction.NO_NETWORK: (
            "Do not reach the network, by any route - no fetching pages, no downloads, no "
            "package installs, and no program that opens a connection for you."
        ),
    }
)

_PREAMBLE: Final = (
    "AGL places the following limits on this task. They hold whatever the tools available to you "
    "appear to allow, they are not negotiable, and working around one is a failed task rather "
    "than a solved one:"
)

_ACTIVITY_LIMIT: Final = 120

_MODEL_NAMES: Final[Mapping[ModelId, str]] = MappingProxyType(
    {
        Claude.OPUS: "opus",
        Claude.SONNET: "sonnet",
        Claude.HAIKU: "haiku",
    }
)

# `ClaudeAgentOptions.effort` in SDK 0.2.157 is typed as the `EffortLevel` literal and reaches the
# CLI as `--effort <level>` unvalidated; the CLI 2.1.277 it bundles lowers or drops a level the
# model does not offer rather than refusing it.
_EFFORT_LEVELS: Final[Mapping[ClaudeEffort, EffortLevel]] = MappingProxyType(
    {
        ClaudeEffort.LOW: "low",
        ClaudeEffort.MEDIUM: "medium",
        ClaudeEffort.HIGH: "high",
        ClaudeEffort.XHIGH: "xhigh",
        ClaudeEffort.MAX: "max",
    }
)

@dataclass(frozen=True, slots=True)
class Restraint:
    denied_tools: tuple[str, ...]

    in_words: str

def restraint(restrictions: frozenset[Restriction]) -> Restraint:
    denied: list[str] = []
    spoken: list[str] = []
    for member in Restriction:
        if member not in restrictions:
            continue
        for rule in _DENIALS[member]:
            if rule not in denied:
                denied.append(rule)
        spoken.append(f"- {_IN_WORDS[member]}")
    if not spoken:
        return Restraint((), "")
    return Restraint(tuple(denied), "\n".join([_PREAMBLE, *spoken]))

def model_name(model: ModelId) -> str:
    name = _MODEL_NAMES.get(model)
    if name is None:
        raise _unserved(model)
    return name

def effort_level(choice: ModelChoice) -> EffortLevel | None:
    match choice:
        case ChosenClaude():
            return _EFFORT_LEVELS[choice.effort]
        case ChosenOpenAI():
            raise _unserved(choice.model)
        case ModelId():
            return None
        case _:
            assert_never(choice)

def last_words(printed: str) -> str:
    return f"The CLI's last words were: {printed or '(it printed nothing)'}"

# `ProcessError.stderr` is the fixed string "Check stderr output for details" in SDK 0.2.157 and
# never the CLI's own: the SDK streams stderr to `options.stderr` instead of capturing it. So the
# exception says nothing an operator can act on, and what `_session.Stderr` collected is the answer.
def translated(error: ClaudeSDKError, printed: str) -> AglError:
    reading = _reading(error)
    return type(reading)(f"{reading}. {last_words(printed)}")

def _reading(error: ClaudeSDKError) -> AglError:
    if isinstance(error, CLINotFoundError):
        return UpstreamUnavailable(
            f"the Claude Code CLI is not installed or is not on PATH: {_said(error)}. Nothing "
            f"was attempted, so this is not a failed task - install Claude Code, or point AGL at "
            f"an existing installation, and the same call may well succeed"
        )
    if isinstance(error, CLIConnectionError):
        return UpstreamUnavailable(
            f"AGL could not open a session with the Claude Code CLI: {_said(error)}. Nothing "
            f"reached a model, so the same call may well succeed once the CLI can be started"
        )
    if isinstance(error, ResultError):
        return UpstreamUnavailable(
            f"the Claude Code CLI stopped and reported an error instead of a result: "
            f"{_said(error)}. A session that is not authenticated, an exhausted allowance and an "
            f"unusable request all arrive this way, so the message above is the part to act on"
        )
    if isinstance(error, ProcessError):
        return UpstreamUnavailable(
            f"the Claude Code CLI exited without answering: {_said(error)}. Nothing usable came "
            f"back from the far side, so the same call may well succeed once whatever stopped it "
            f"is fixed"
        )
    if isinstance(error, CLIJSONDecodeError):
        return UpstreamUnexpected(
            f"the Claude Code CLI answered with something AGL cannot read: {_said(error)}. The "
            f"CLI is working and this adapter's reading of it is not, so the same call will "
            f"answer the same way - this is a version mismatch or an AGL bug, not a busy backend"
        )
    return UpstreamUnexpected(
        f"the Claude Code SDK raised {type(error).__name__}, which this adapter has no specific "
        f"reading of: {_said(error)}. It is reported as an answer AGL could not act on rather "
        f"than as a backend that was unreachable, because promising that a retry may help is a "
        f"promise nothing here can keep for an error it has not seen before"
    )

def unready(error: ClaudeSDKError, printed: str) -> UpstreamUnavailable:
    reported = translated(error, printed)
    if isinstance(reported, UpstreamUnavailable):
        return reported
    return UpstreamUnavailable(
        f"the Claude Code CLI is installed but did not answer a readiness check in a way AGL "
        f"could use: {reported}"
    )

def activity(call: ToolUseBlock, workspace: Path) -> str:
    subject = _subject(call.input, workspace)
    return f"{call.name}: {subject}" if subject else call.name

def _subject(payload: Mapping[str, Any], workspace: Path) -> str:
    for value in payload.values():
        if isinstance(value, str) and value.strip():
            return _shortened(_relative(value.strip(), workspace))
    return ""

def _relative(text: str, workspace: Path) -> str:
    prefix = f"{workspace}{os.sep}"
    return text[len(prefix) :] if text.startswith(prefix) and len(text) > len(prefix) else text

def _shortened(text: str) -> str:
    first, newline, _ = text.partition("\n")
    line = " ".join(first.split())
    cut = bool(newline)
    if len(line) > _ACTIVITY_LIMIT:
        line, cut = line[:_ACTIVITY_LIMIT].rstrip(), True
    return f"{line}..." if cut else line

def _said(error: ClaudeSDKError) -> str:
    said = str(error).strip()
    return said or f"{type(error).__name__}, with nothing said about why"

def _unserved(model: ModelId) -> InputError:
    served = sorted(str(member) for member in _MODEL_NAMES)
    return InputError(
        f"the Claude Code adapter cannot run {str(model)!r}: it serves {served} and nothing "
        f"else. It will not stand in another model for this one - the model was named beside "
        f"the prompt because the choice was semantic, and substituting answers a different "
        f"question than the one the workflow asked"
    )
