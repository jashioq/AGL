from dataclasses import dataclass
from typing import Final
from agl.sdk import Terminal, Tool, ToolResult, describe, tool
from agl.workflows.fix import views
from agl.workflows.fix.questions import Question

__all__ = ["ASK", "Asked", "NO_QUESTION", "SAID_NOTHING", "asking"]

ASK: Final = "ask_the_operator"

_DESCRIPTION: Final = (
    "Ask the person running this task a question, and wait for their answer. Use it when a "
    "decision is genuinely theirs to make - which of two approaches to take, whether a proposal "
    "is acceptable - rather than guessing. You may call it as many times as you need; each call "
    "is one question and returns one answer."
)

NO_QUESTION: Final = (
    "That call asked nothing: `question` was blank. A question is the whole of what a person "
    "sees, so write what you are asking in full and call this tool again."
)

SAID_NOTHING: Final = (
    "The person answered with nothing at all. Take that as no preference either way, use your "
    "own judgement, and carry on."
)

@dataclass(frozen=True, slots=True)
class Asked:
    question: str = describe("What you are asking, in full, in your own words.")

    options: tuple[str, ...] = describe(
        "The answers you are suggesting, if any. Each one is the exact text that may come back "
        "as the answer, so write them as answers and not as labels.",
        default=(),
    )

    allow_free_text: bool = describe(
        "Whether an answer other than the options you offered is acceptable. Defaults to true; "
        "set it to false only when you are asking for a choice among them.",
        default=True,
    )

def asking(terminal: Terminal) -> Tool:

    async def answered(asked: Asked) -> ToolResult:
        if not asked.question.strip():
            return ToolResult(text=NO_QUESTION, rejected=True)
        offered = tuple(option for option in asked.options if option)
        answer = await terminal.show(
            views.agent_question,
            question=Question(
                prompt=asked.question,
                options=offered,
                allow_free_text=asked.allow_free_text or not offered,
            ),
        )
        return ToolResult(text=answer.text if answer.text else SAID_NOTHING)

    return tool(ASK, _DESCRIPTION, Asked, answered)
