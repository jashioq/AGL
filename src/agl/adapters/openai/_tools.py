from collections.abc import Mapping
from types import TracebackType
from typing import Final, Self
from agl.adapters.openai._http import Listener, RpcAnswer, token
from agl.ports.agent import Tool, ToolResult
from agl.ports.run import JsonValue

__all__ = ["Caller", "Supply"]

_SUPPLIED: Final = "agl"

_PROTOCOL: Final = "2025-06-18"

_NO_SUCH_METHOD: Final = -32601

_FAILED: Final = (
    "{name} could not do what it was asked: {raised}. This task is being stopped because of it. "
    "Nothing you do from here is kept, so do not call it again and do not work around it."
)

_STOPPING: Final = (
    "{name} was not called. This task is already being stopped because a tool could not do what "
    "it was asked: {raised}. Nothing you do from here is kept."
)

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

class Supply:
    def __init__(self, tools: tuple[Tool, ...], caller: Caller) -> None:
        self._offered = {_SUPPLIED: {tool.name: tool for tool in tools}}
        self._path = token()
        self._listener = Listener(
            {
                f"/{self._path}/{name}": _Route(name, offered, caller)
                for name, offered in self._offered.items()
            }
        )

    async def __aenter__(self) -> Self:
        await self._listener.start()
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self._listener.stop()

    @property
    def urls(self) -> Mapping[str, str]:
        return {name: f"{self._listener.origin}/{self._path}/{name}" for name in self._offered}

class _Route:
    def __init__(self, name: str, offered: Mapping[str, Tool], caller: Caller) -> None:
        self._name = name
        self._offered = offered
        self._caller = caller

    async def __call__(self, message: Mapping[str, JsonValue]) -> RpcAnswer:
        if "id" not in message:
            return None
        ident = message["id"]
        method = message.get("method")
        if method == "initialize":
            return _ok(ident, self._initialize(message.get("params")))
        if method == "tools/list":
            return _ok(ident, {"tools": [_advertised(tool) for tool in self._offered.values()]})
        if method == "tools/call":
            return _ok(ident, _content(await self._called(message.get("params"))))
        if method == "ping":
            return _ok(ident, {})
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "error": {"code": _NO_SUCH_METHOD, "message": f"no method {method!r} on this server"},
        }

    def _initialize(self, params: JsonValue) -> dict[str, JsonValue]:
        proposed = params.get("protocolVersion") if isinstance(params, dict) else None
        return {
            "protocolVersion": proposed if isinstance(proposed, str) else _PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self._name, "version": "1"},
        }

    async def _called(self, params: JsonValue) -> ToolResult:
        if not isinstance(params, dict):
            return ToolResult(text="that call carried no parameters object.", rejected=True)
        name = params.get("name")
        tool = self._offered.get(name) if isinstance(name, str) else None
        if tool is None:
            offered = sorted(self._offered)
            return ToolResult(
                text=f"there is no tool called {name!r} here. This server offers {offered}.",
                rejected=True,
            )
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return ToolResult(
                text=(
                    f"the arguments for {tool.name} arrived as {type(arguments).__name__} and this "
                    f"tool takes a JSON object. Send one and call it again."
                ),
                rejected=True,
            )
        return await self._caller.handled(tool, arguments)

def _advertised(tool: Tool) -> dict[str, JsonValue]:
    schema: dict[str, JsonValue] = dict(tool.payload_schema)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return {"name": tool.name, "description": tool.description, "inputSchema": schema}

def _content(result: ToolResult) -> dict[str, JsonValue]:
    return {
        "content": [{"type": "text", "text": result.text}],
        "isError": result.rejected,
    }

def _ok(ident: JsonValue, result: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {"jsonrpc": "2.0", "id": ident, "result": dict(result)}
