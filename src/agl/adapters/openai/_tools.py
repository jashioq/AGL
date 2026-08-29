
from collections.abc import Mapping
from types import MappingProxyType, TracebackType
from typing import Final, Self

from agl.adapters.openai._http import Answer, Listener, token
from agl.ports.agent import QuestionHandler, Tool, ToolResult
from agl.ports.questions import Question
from agl.ports.run import JsonValue

__all__ = ["ASKING_TOOL", "Asking", "Supply"]

_SUPPLIED: Final = "agl"
_ASKING: Final = "agl_ask"

_ASK: Final = "ask"

ASKING_TOOL: Final = f"mcp__{_ASKING}__{_ASK}"

_PROTOCOL: Final = "2025-06-18"

_NO_SUCH_METHOD: Final = -32601

_ASK_DESCRIPTION: Final = (
    "Ask the person running this task a question, and wait for their answer. Use it when a "
    "decision is genuinely theirs to make - which of two approaches to take, whether a proposal "
    "is acceptable - rather than guessing. You may call it as many times as you need; each call "
    "is one question and returns one answer. Waiting is expected and this call will not time out. "
    "If no answer is available you will be told so, and you should then use your own judgement "
    "and carry on."
)

_ASK_SCHEMA: Final[Mapping[str, JsonValue]] = MappingProxyType(
    {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What you are asking, in full, in your own words.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The answers you are suggesting, if any. Each one is the exact text that may "
                    "come back as the answer, so write them as answers and not as labels."
                ),
            },
            "allow_free_text": {
                "type": "boolean",
                "description": (
                    "Whether an answer other than the options you offered is acceptable. Defaults "
                    "to true; set it to false only when you are asking for a choice among them."
                ),
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    }
)

_NOBODY_LISTENING: Final = (
    "No answer is available: this task is running with nobody to ask. Nothing is wrong and this "
    "is not a failure - use your own judgement, decide it yourself, and carry on. Do not wait, "
    "and do not ask again."
)

_SAID_NOTHING: Final = (
    "The person answered with nothing at all. Take that as no preference either way, use your "
    "own judgement, and carry on."
)

_NO_QUESTION: Final = (
    "That call asked nothing: `question` was empty or missing. A question is the whole of what a "
    "person sees, so write what you are asking in full and call this tool again."
)


class Asking:

    def __init__(self, on_question: QuestionHandler | None) -> None:
        self._on_question = on_question
        self.asked = 0

        self.failure: Exception | None = None

    async def answered(self, payload: Mapping[str, JsonValue]) -> ToolResult:
        prompt = payload.get("question")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolResult(text=_NO_QUESTION, rejected=True)
        if self._on_question is None or self.failure is not None:
            return ToolResult(text=_NOBODY_LISTENING)
        self.asked += 1
        try:
            answer = await self._on_question(_question(prompt, payload))
        except Exception as raised:
            self.failure = raised
            return ToolResult(text=_NOBODY_LISTENING)
        return ToolResult(text=answer.text if answer.text else _SAID_NOTHING)


class Supply:

    def __init__(self, tools: tuple[Tool, ...], asking: Asking) -> None:
        self._offered = {
            _SUPPLIED: {tool.name: tool for tool in tools},
            _ASKING: {_ASK: _asker(asking)},
        }
        self._path = token()
        self._listener = Listener(
            {
                f"/{self._path}/{name}": _Route(name, offered)
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

    def __init__(self, name: str, offered: Mapping[str, Tool]) -> None:
        self._name = name
        self._offered = offered

    async def __call__(self, message: Mapping[str, JsonValue]) -> Answer:
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
        try:
            return await tool.handler(arguments)
        except Exception as raised:  # noqa: BLE001
            return ToolResult(text=f"{tool.name} failed: {raised}", rejected=True)


def _asker(asking: Asking) -> Tool:
    return Tool(
        name=_ASK,
        description=_ASK_DESCRIPTION,
        payload_schema=_ASK_SCHEMA,
        handler=asking.answered,
    )


def _question(prompt: str, payload: Mapping[str, JsonValue]) -> Question:
    offered = payload.get("options")
    options = (
        tuple(item for item in offered if isinstance(item, str) and item)
        if isinstance(offered, list)
        else ()
    )
    free = payload.get("allow_free_text")
    return Question(
        prompt=prompt,
        options=options,
        allow_free_text=True if not options or not isinstance(free, bool) else free,
    )


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
