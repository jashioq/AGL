
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from agl.adapters.openai._reading import (
    activity,
    failure,
    launch_failure,
    unanswered,
    unreadable,
    unready,
)
from agl.ports.agent import ModelId, OpenAI, Restriction
from agl.ports.errors import InputError

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
