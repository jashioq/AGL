from typing import Final
from agl.sdk import Choice, Response, Screen, TextInput
from agl.workflows.fix.questions import Answer, Question

__all__ = ["FREE_TEXT", "agent_question"]

FREE_TEXT: Final = "Answer in your own words"

def agent_question(question: Question) -> Screen[Answer]:
    responses: list[Response[Answer]] = [
        Choice(option, value=Answer(option)) for option in question.options
    ]
    if question.allow_free_text:
        responses.append(TextInput(FREE_TEXT, maps=Answer))
    return Screen(question.prompt, responses)
