
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Final, cast

from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    Claude,
    ModelId,
    QuestionHandler,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.errors import InputError
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue

__all__ = ["Conversation", "FakeAgentRunner", "Script", "unscripted"]

_CAPABILITIES: Final = frozenset(
    {
        Capability.FILE_EDIT,
        Capability.SHELL,
        Capability.MID_RUN_QUESTIONS,
        Capability.TOOL_CALLING,
    }
)

_ROUNDS: Final = 8

_QUESTION: Final = (
    "AGL is running this task on its Claude Code fake, with a script where the model would be. "
    "Is there anything this run should be told before it goes on?"
)

_PLACEHOLDER: Final = "AGL's Claude Code fake produced this: no model was involved."

_CLOSING: Final = (
    "AGL's Claude Code fake ran this task with a script where the model would be. It read nothing "
    "in the workspace and changed nothing there."
)


class Conversation:

    def __init__(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> None:
        self.task = task

        self.failure: Exception | None = None

        self._on_question = on_question
        self._on_activity = on_activity
        self._tools: dict[str, Tool] = {declared.name: declared for declared in task.tools}

    async def ask(self, question: Question) -> Answer | None:
        if self._on_question is None or self.failure is not None:
            return None
        try:
            return await self._on_question(question)
        except Exception as raised:
            self.failure = raised
            return None

    async def call(self, tool: str, payload: Mapping[str, JsonValue]) -> ToolResult:
        declared = self._tools.get(tool)
        if declared is None:
            known = sorted(self._tools)
            raise InputError(
                f"this task declares no tool called {tool!r}: it declares {known}. A session "
                f"registers exactly the tools the task carries, so a call to anything else is not "
                f"a move any agent could have made, and a script that can make it is a script that "
                f"proves a workflow works with a tool the workflow never declared"
            )
        arguments = _as_json(payload, tool)
        try:
            return await declared.handler(arguments)
        except Exception as raised:
            return ToolResult(text=f"{declared.name} failed: {raised}", rejected=True)

    def report(self, line: str) -> None:
        if self._on_activity is not None:
            self._on_activity(line)


type Script = Callable[[Conversation], Awaitable[AgentOutcome]]


async def unscripted(conversation: Conversation) -> AgentOutcome:
    heard: list[str] = []
    while len(heard) < _ROUNDS:
        conversation.report("Ask: whether there is anything this run should be told")
        answer = await conversation.ask(Question(prompt=_QUESTION))
        if answer is None or answer.text in heard:
            break
        heard.append(answer.text)

    called: list[str] = []
    for declared in conversation.task.tools:
        if conversation.failure is not None:
            break
        said = _PLACEHOLDER
        for _ in range(_ROUNDS):
            conversation.report(f"{declared.name}: {said}")
            result = await conversation.call(declared.name, _payload(declared.payload_schema, said))
            called.append(declared.name)
            if not result.rejected:
                break
            said = result.text

    return AgentOutcome(stop_reason=StopReason.COMPLETED, text=_said(heard, called))


class FakeAgentRunner(AgentRunner):

    def __init__(self, script: Script | None = None) -> None:
        self._script: Final = script if script is not None else unscripted

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        _served(model)
        return _CAPABILITIES

    async def check_ready(self, model: ModelId) -> None:
        _served(model)

    async def run(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        _served(task.model)
        conversation = Conversation(task, on_question=on_question, on_activity=on_activity)
        outcome = await self._script(conversation)
        if conversation.failure is not None:
            raise conversation.failure
        return outcome


def _served(model: ModelId) -> None:
    if not isinstance(model, Claude):
        served = sorted(str(member) for member in Claude)
        raise InputError(
            f"the Claude Code fake cannot run {str(model)!r}: it serves {served} and nothing "
            f"else. It will not stand in another model for this one - the model was named beside "
            f"the prompt because the choice was semantic, and substituting answers a different "
            f"question than the one the workflow asked"
        )


def _as_json(payload: Mapping[str, JsonValue], tool: str) -> dict[str, JsonValue]:
    try:
        return cast(dict[str, JsonValue], json.loads(json.dumps(payload, allow_nan=False)))
    except (TypeError, ValueError) as unwritable:
        raise InputError(
            f"the payload for tool {tool!r} is not JSON: {unwritable}. A tool call reaches a real "
            f"handler as JSON a model produced, and a step's result is written down as JSON "
            f"(§3.6), so a payload that cannot be one is a call no run could have made"
        ) from unwritable


def _payload(schema: Mapping[str, JsonValue], said: str) -> dict[str, JsonValue]:
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        return {}
    return {
        name: _value(properties[name], said)
        for name in required
        if isinstance(name, str) and name in properties
    }


def _value(described: JsonValue, said: str) -> JsonValue:
    if not isinstance(described, dict):
        return said
    choices = described.get("enum")
    if isinstance(choices, list) and choices:
        return choices[0]
    kind = described.get("type")
    if isinstance(kind, list):
        kind = next((one for one in kind if isinstance(one, str)), None)
    if kind == "object":
        return _payload(described, said)
    if kind == "array":
        return []
    if kind in ("integer", "number"):
        return 0
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return said


def _said(heard: list[str], called: list[str]) -> str:
    parts = [_CLOSING]
    if heard:
        parts.append(f"The last answer it was given was: {heard[-1]}")
    if called:
        parts.append(f"It called: {', '.join(called)}.")
    return " ".join(parts)
