
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from agl.ports.agent import ModelId, OpenAI, Restriction
from agl.ports.errors import AglError, InputError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.run import JsonValue

__all__ = [
    "APPROVAL",
    "Sandbox",
    "activity",
    "failure",
    "launch_failure",
    "model_slug",
    "sandbox",
    "unanswered",
    "unreadable",
    "unready",
]


_READ_ONLY: Final = "read-only"
_WORKSPACE_WRITE: Final = "workspace-write"


APPROVAL: Final[tuple[str, ...]] = ("-c", 'approval_policy="never"')


_NETWORK: Final = "sandbox_workspace_write.network_access"


_SHELL_FEATURES: Final = ("features.shell_tool", "features.unified_exec")


_IN_WORDS: Final[Mapping[Restriction, str]] = MappingProxyType(
    {
        Restriction.NO_VCS_WRITES: (
            "Leave version control alone. Do not commit, stage, branch, tag, merge, rebase, "
            "reset, stash, push, fetch, or write anything git keeps for itself. This workspace's "
            "history belongs to AGL, which records your work for you: change files, not the "
            "repository."
        ),
        Restriction.NO_FILE_WRITES: (
            "Change nothing on disk. Do not create, rewrite, move or remove a file by any route - "
            "not with an editing tool, not with a shell redirect, and not by running a program "
            "that writes one for you. Read, run, and report what you found."
        ),
        Restriction.NO_SHELL: (
            "Do not run commands. No shell, no build, no test run, and nothing that reaches a "
            "command line through some other tool. If the task cannot be finished without running "
            "something, say so and stop - working around this is a failed task, not a solved one."
        ),
        Restriction.NO_NETWORK: (
            "Do not reach the network. No fetching a page, no download, no package install, no "
            "clone, and no program that opens a connection on your behalf. Work with what is "
            "already in the workspace."
        ),
    }
)


_PREAMBLE: Final = (
    "AGL places the following limits on this task. They hold whatever the sandbox you are running "
    "under appears to allow, they are not open to negotiation, and finding a way around one is a "
    "failed task rather than a solved one:"
)


_ARGV_REJECTED: Final = 2


_ACTIVITY_LIMIT: Final = 120


_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "command_execution": "Running",
        "file_change": "Changing",
        "mcp_tool_call": "Calling",
        "web_search": "Searching",
    }
)


_MODEL_SLUGS: Final[Mapping[ModelId, str]] = MappingProxyType(
    {
        OpenAI.SOL: "gpt-5.6-sol",
        OpenAI.TERRA: "gpt-5.6-terra",
        OpenAI.LUNA: "gpt-5.6-luna",
    }
)


@dataclass(frozen=True, slots=True)
class Sandbox:

    mode: str

    options: tuple[str, ...]

    in_words: str


def sandbox(restrictions: frozenset[Restriction]) -> Sandbox:
    options: list[str] = []
    if Restriction.NO_FILE_WRITES in restrictions:
        mode = _READ_ONLY
    else:
        mode = _WORKSPACE_WRITE
        allowed = Restriction.NO_NETWORK not in restrictions
        options += ["-c", f"{_NETWORK}={'true' if allowed else 'false'}"]

    if Restriction.NO_SHELL in restrictions:
        for feature in _SHELL_FEATURES:
            options += ["-c", f"{feature}=false"]

    spoken = [f"- {_IN_WORDS[member]}" for member in Restriction if member in restrictions]
    return Sandbox(
        mode=mode,
        options=tuple(options),
        in_words="\n".join([_PREAMBLE, *spoken]) if spoken else "",
    )


def model_slug(model: ModelId) -> str:
    slug = _MODEL_SLUGS.get(model)
    if slug is None:
        served = sorted(str(member) for member in _MODEL_SLUGS)
        raise InputError(
            f"the OpenAI adapter cannot run {str(model)!r}: it serves {served} and nothing else. "
            f"It will not stand in another model for this one - the model was named beside the "
            f"prompt because the choice was semantic, and substituting answers a different "
            f"question than the one the workflow asked"
        )
    return slug


def launch_failure(error: OSError) -> UpstreamUnavailable:
    if isinstance(error, FileNotFoundError):
        return UpstreamUnavailable(
            f"the Codex CLI is not installed or is not on PATH: {_said(error)}. Nothing was "
            f"attempted, so this is not a failed task - install Codex, or point AGL at an "
            f"existing installation, and the same call may well succeed"
        )
    if isinstance(error, PermissionError):
        return UpstreamUnavailable(
            f"the Codex CLI was found and could not be executed: {_said(error)}. That is a file "
            f"mode or a quarantine attribute on the binary rather than anything about this run"
        )
    return UpstreamUnavailable(
        f"AGL could not start the Codex CLI: {_said(error)}. Nothing reached a model, so the same "
        f"call may well succeed once whatever stopped the process from starting is fixed"
    )


def unready(exit_code: int, output: str) -> UpstreamUnavailable:
    return UpstreamUnavailable(
        f"the Codex CLI is installed and is not ready to run: {_said(output)}. A session that was "
        f"never authenticated, one whose credentials have expired, and a configuration the CLI "
        f"refuses to load all arrive this way, so the message above is the part to act on - "
        f"{_status(exit_code)}"
    )


def unanswered(seconds: float) -> UpstreamUnavailable:
    return UpstreamUnavailable(
        f"the Codex CLI was asked whether it is ready to run and had not answered {seconds:g}s "
        f"later, so it was stopped along with everything it had started. An authentication server "
        f"that has wedged, a keychain prompt waiting on somebody who is not at the machine, and a "
        f"binary that never got as far as reading its own credential store all arrive this way. "
        f"Nothing reached a model and nothing was spent, so the same call may well succeed once "
        f"whatever the probe was waiting on is unblocked"
    )


def failure(*, reported: str | None, exit_code: int, stderr: str) -> AglError:
    said = (reported or "").strip()
    if said:
        return UpstreamUnavailable(
            f"the Codex CLI stopped and reported an error instead of finishing: {said}. A session "
            f"that is not authenticated, an exhausted allowance, a sandbox that refused something "
            f"the run needed and an unusable request all arrive this way, so the message above is "
            f"the part to act on"
        )
    if exit_code == _ARGV_REJECTED:
        return UpstreamUnexpected(
            f"the Codex CLI rejected the command line AGL built for it: {_said(stderr)}. That "
            f"status is the argument parser refusing to start, so nothing reached a model and "
            f"nothing will on a retry - this is a version mismatch or an AGL bug rather than a "
            f"backend that was busy"
        )
    return UpstreamUnavailable(
        f"the Codex CLI exited without answering and without saying why: {_said(stderr)}. Nothing "
        f"usable came back from the far side, so the same call may well succeed once whatever "
        f"stopped it is fixed - {_status(exit_code)}"
    )


def unreadable(line: str, reason: str) -> UpstreamUnexpected:
    return UpstreamUnexpected(
        f"the Codex CLI printed a line on its event stream that AGL cannot read: {reason}. The "
        f"line was {_shortened(line)!r}. The CLI is working and this adapter's reading of it is "
        f"not, so the same call will answer the same way - this is a version mismatch or an AGL "
        f"bug, not a busy backend"
    )


def activity(item: Mapping[str, JsonValue], workspace: Path) -> str | None:
    kind = item.get("type")
    if not isinstance(kind, str):
        return None
    label = _LABELS.get(kind)
    if label is None:
        return None
    shown = _shortened(_subject(kind, item, workspace).strip())
    return f"{label}: {shown}" if shown else label


def _subject(kind: str, item: Mapping[str, JsonValue], workspace: Path) -> str:
    if kind == "command_execution":
        return _relative(_text(item.get("command")), workspace)
    if kind == "file_change":
        return ", ".join(_relative(path, workspace) for path in _paths(item.get("changes")))
    if kind == "mcp_tool_call":
        named = (_text(item.get("server")), _text(item.get("tool")))
        return "/".join(part for part in named if part)
    return _relative(_text(item.get("query")), workspace)


def _paths(changes: JsonValue) -> list[str]:
    if not isinstance(changes, list):
        return []
    found = (_text(change.get("path")) for change in changes if isinstance(change, dict))
    return [path for path in found if path]


def _text(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


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


def _said(reported: object) -> str:
    said = str(reported).strip()
    return said or "it said nothing on either output stream"


def _status(exit_code: int) -> str:
    return f"it exited {exit_code}, a status this backend documents no meaning for"
