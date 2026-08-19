"""One `AgentSpec` turned into one `ClaudeAgentOptions`. Pure — no I/O.

Layer: core. Where hermetic configuration is decided: the target project must
contribute source code and nothing else. Three load-bearing options do it, and
all three are easy to lose by accident:

- `setting_sources=[]` — read no settings file anywhere. `None` reads them all.
- `strict_mcp_config=True` — ignore the project's `.mcp.json`.
- `settings` — our own file, absolute, because `cwd` is the target repository.

Nothing is pre-allowed; `disallowed_tools` passes through, since deny rules
resolve ahead of the permission callback. Skipping `project` settings also
skips the repo's `CLAUDE.md` — a caller that wants it passes it through
`system_prompt_append`, where it is visible in the prompt.
"""

from pathlib import Path
from typing import Any, cast, get_args

from claude_agent_sdk import ClaudeAgentOptions, McpServerConfig, PermissionMode
from claude_agent_sdk.types import SystemPromptPreset

from agl.core.agent.api import AgentSpec

__all__ = ["QUESTION_TOOL", "build_options"]

PERMISSION_MODES: frozenset[str] = frozenset(get_args(PermissionMode))

QUESTION_TOOL = "AskUserQuestion"


def build_options(
    spec: AgentSpec,
    settings_path: Path | None,
    mcp_servers: dict[str, Any],
) -> ClaudeAgentOptions:
    """The options for one call, with every configuration source pinned shut.

    param: mcp_servers - separate from the spec, so a caller can add one the
        spec never asked for, such as the keep-alive server
    return: ClaudeAgentOptions - raises `ValueError` on a permission mode the SDK
        does not know, which the spec's `str` typing cannot catch
    """
    if spec.permission_mode not in PERMISSION_MODES:
        raise ValueError(
            f"unknown permission mode {spec.permission_mode!r}: "
            f"expected one of {', '.join(sorted(PERMISSION_MODES))}"
        )

    system_prompt: SystemPromptPreset = {"type": "preset", "preset": "claude_code"}
    if spec.system_prompt_append is not None:
        system_prompt["append"] = spec.system_prompt_append

    return ClaudeAgentOptions(
        cwd=spec.cwd,
        add_dirs=list(spec.add_dirs),
        system_prompt=system_prompt,
        disallowed_tools=list(spec.disallowed_tools),
        permission_mode=cast(PermissionMode, spec.permission_mode),
        model=spec.model.value if spec.model is not None else None,
        mcp_servers=cast(dict[str, McpServerConfig], mcp_servers),
        setting_sources=[],
        strict_mcp_config=True,
        settings=str(settings_path) if settings_path is not None else None,
    )
