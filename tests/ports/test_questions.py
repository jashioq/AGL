"""What `Question` and `Answer` promise: the poorest shape that still carries the exchange.

Three things here are more than dataclass machinery. The **defaults** are load-bearing - naming
only a prompt has to produce the open question every backend can ask, because that is the shape an
adapter falls back to when its payload carries no choices. The **refusals** are the three ways a
`Question` can arrive unanswerable, each of which would otherwise surface as a handler staring at
something it cannot act on. And `Answer`'s **single field** is pinned by hand, because "one string,
and deliberately nothing else" is the whole of that type's design: a second field should have to be
argued for in the docstring rather than merely added.
"""

from dataclasses import FrozenInstanceError, fields

import pytest

from agl.ports.errors import InternalError
from agl.ports.questions import Answer, Question


def test_naming_only_a_prompt_gives_the_open_question_every_backend_can_ask() -> None:
    """No suggestions, and anything may be said back - which is what an open question is."""
    question = Question(prompt="Which ticket first?")
    assert question.options == ()
    assert question.allow_free_text is True


def test_an_agent_may_ask_for_a_choice_among_what_it_offered() -> None:
    """The restricting value is the one that has to be typed, and it is legal with options."""
    question = Question(prompt="Approve?", options=("yes", "no"), allow_free_text=False)
    assert question.options == ("yes", "no"), "in the order the agent suggested them"


@pytest.mark.parametrize(
    "question",
    [
        pytest.param({"prompt": ""}, id="nothing to read"),
        pytest.param({"prompt": "Approve?", "options": ("yes", "")}, id="an unpickable option"),
        pytest.param({"prompt": "Approve?", "allow_free_text": False}, id="no way to answer"),
    ],
)
def test_a_question_nobody_could_answer_is_refused(question: dict[str, object]) -> None:
    """`InternalError`, not `InputError`: an adapter built this out of what a model produced."""
    with pytest.raises(InternalError):
        Question(**question)  # type: ignore[arg-type]


def test_an_answer_is_one_string_and_the_empty_one_means_nothing_was_said() -> None:
    """The empty answer is legal, which is exactly why no option may be spelled that way."""
    assert [field.name for field in fields(Answer)] == ["text"]
    assert Answer(text="").text == ""
    assert Answer(text="yes") == Answer(text="yes")


def test_both_types_are_frozen() -> None:
    """A question the handler can edit before answering it is not the question that was asked."""
    question = Question(prompt="Approve?")
    with pytest.raises(FrozenInstanceError):
        question.prompt = "Something else"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        Answer(text="yes").text = "no"  # type: ignore[misc]
