
from collections.abc import Mapping
from typing import Any, Final

from claude_agent_sdk import McpServerConfig, SdkMcpTool, create_sdk_mcp_server

from agl.ports.agent import QuestionHandler, Tool
from agl.ports.questions import Question
from agl.ports.run import JsonValue

__all__ = ["ASKING_MECHANISMS_DENIED", "ASKING_TOOL", "Asking", "servers"]

ASKING_MECHANISMS_DENIED: Final = ("AskUserQuestion",)

_SUPPLIED: Final = "agl"
_ASKING: Final = "agl_ask"

_ASK: Final = "ask"

ASKING_TOOL: Final = f"mcp__{_ASKING}__{_ASK}"

_ASK_DESCRIPTION: Final = (
    "Ask the person running this task a question, and wait for their answer. Use it when a "
    "decision is genuinely theirs to make - which of two approaches to take, whether a proposal "
    "is acceptable - rather than guessing. You may call it as many times as you need; each call "
    "is one question and returns one answer. If no answer is available you will be told so, and "
    "you should then use your own judgement and carry on."
)

_ASK_SCHEMA: Final[Mapping[str, JsonValue]] = {
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
    "That call asked nothing: `question` was empty. A question is the whole of what a person "
    "sees, so write what you are asking in full and call this tool again."
)


def servers(tools: tuple[Tool, ...], asking: Asking) -> dict[str, McpServerConfig]:
    return {
        _SUPPLIED: create_sdk_mcp_server(
            name=_SUPPLIED, tools=[_wrapped(declared) for declared in tools]
        ),
        _ASKING: create_sdk_mcp_server(
            name=_ASKING,
            tools=[
                SdkMcpTool(
                    name=_ASK,
                    description=_ASK_DESCRIPTION,
                    input_schema=dict(_ASK_SCHEMA),
                    handler=asking.answered,
                )
            ],
        ),
    }


class Asking:

    def __init__(self, on_question: QuestionHandler | None) -> None:
        self._on_question = on_question
        self.asked = 0

        self.failure: Exception | None = None

    async def answered(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = payload.get("question")
        if not isinstance(prompt, str) or not prompt.strip():
            return _result(_NO_QUESTION, rejected=True)
        if self._on_question is None:
            return _result(_NOBODY_LISTENING)
        if self.failure is not None:
            return _result(_NOBODY_LISTENING)
        self.asked += 1
        try:
            answer = await self._on_question(_question(prompt, payload))
        except Exception as raised:
            self.failure = raised
            return _result(_NOBODY_LISTENING)
        return _result(answer.text if answer.text else _SAID_NOTHING)


def _question(prompt: str, payload: Mapping[str, Any]) -> Question:
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


def _wrapped(declared: Tool) -> SdkMcpTool[Any]:

    async def invoked(payload: dict[str, Any]) -> dict[str, Any]:
        outcome = await declared.handler(payload)
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
