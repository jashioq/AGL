
from collections.abc import Mapping
from typing import Any, Final

from claude_agent_sdk import McpServerConfig, SdkMcpTool, create_sdk_mcp_server

from agl.ports.agent import Tool, ToolResult
from agl.ports.run import JsonValue

__all__ = ["ASKING_MECHANISMS_DENIED", "Caller", "servers"]

# Absent from a probed session even on a machine carrying
# `CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL`, and denied anyway: a rule naming a tool that is not
# there costs a startup warning, and a tool that is there and unnamed costs the restriction.
ASKING_MECHANISMS_DENIED: Final = ("AskUserQuestion",)

_SUPPLIED: Final = "agl"

_FAILED: Final = (
    "{name} could not do what it was asked: {raised}. This task is being stopped because of it. "
    "Nothing you do from here is kept, so do not call it again and do not work around it."
)

_STOPPING: Final = (
    "{name} was not called. This task is already being stopped because a tool could not do what "
    "it was asked: {raised}. Nothing you do from here is kept."
)


def servers(tools: tuple[Tool, ...], caller: Caller) -> dict[str, McpServerConfig]:
    return {
        _SUPPLIED: create_sdk_mcp_server(
            name=_SUPPLIED, tools=[_wrapped(declared, caller) for declared in tools]
        )
    }


class Caller:

    def __init__(self) -> None:
        self.failure: Exception | None = None

    def fail(self, raised: Exception) -> None:
        if self.failure is None:
            self.failure = raised

    async def handled(self, tool: Tool, payload: Mapping[str, JsonValue]) -> ToolResult:
        if self.failure is not None:
            return ToolResult(
                text=_STOPPING.format(name=tool.name, raised=self.failure), rejected=True
            )
        try:
            return await tool.handler(payload)
        except Exception as raised:
            self.fail(raised)
            return ToolResult(text=_FAILED.format(name=tool.name, raised=raised), rejected=True)


def _wrapped(declared: Tool, caller: Caller) -> SdkMcpTool[Any]:

    async def invoked(payload: dict[str, Any]) -> dict[str, Any]:
        outcome = await caller.handled(declared, payload)
        return _result(outcome.text, rejected=outcome.rejected)

    return SdkMcpTool(
        name=declared.name,
        description=declared.description,
        input_schema=_schema(declared.payload_schema),
        handler=invoked,
    )


def _schema(payload_schema: Mapping[str, JsonValue]) -> dict[str, Any]:
    schema = dict(payload_schema)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def _result(text: str, *, rejected: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "is_error": rejected}
