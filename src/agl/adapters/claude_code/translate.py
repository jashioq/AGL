
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from claude_agent_sdk import (
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
    ResultError,
    ToolUseBlock,
)

from agl.ports.agent import Claude, ModelId, Restriction
from agl.ports.errors import AglError, InputError, UpstreamUnavailable, UpstreamUnexpected

__all__ = [
    "Restraint",
    "activity",
    "model_name",
    "restraint",
    "translated",
    "unready",
]


def _bash(*commands: str) -> tuple[str, ...]:
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
        Restriction.NO_VCS_WRITES: ("EnterWorktree", "ExitWorktree", *_bash(*_GIT_WRITES)),
        Restriction.NO_FILE_WRITES: ("Edit", "Write", "NotebookEdit", "MultiEdit", "Edit(//**)"),
        Restriction.NO_SHELL: ("Bash", "PowerShell", "Monitor"),
        Restriction.NO_NETWORK: ("WebFetch", "WebSearch"),
    }
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
        served = sorted(str(member) for member in _MODEL_NAMES)
        raise InputError(
            f"the Claude Code adapter cannot run {str(model)!r}: it serves {served} and nothing "
            f"else. It will not stand in another model for this one - the model was named beside "
            f"the prompt because the choice was semantic, and substituting answers a different "
            f"question than the one the workflow asked"
        )
    return name


def translated(error: ClaudeSDKError) -> AglError:
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


def unready(error: ClaudeSDKError) -> UpstreamUnavailable:
    reported = translated(error)
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
