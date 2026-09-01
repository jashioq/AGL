from dataclasses import dataclass
from agl.sdk import InternalError

__all__ = ["Answer", "Question"]

@dataclass(frozen=True, slots=True)
class Question:
    prompt: str

    options: tuple[str, ...] = ()

    allow_free_text: bool = True

    def __post_init__(self) -> None:
        if not self.prompt:
            raise InternalError("a question with an empty prompt asks nothing and shows nothing")
        for index, option in enumerate(self.options):
            if not option:
                raise InternalError(
                    f"option {index} is the empty string, and an option is the exact text that "
                    f"goes back as the answer - an empty one is indistinguishable from saying "
                    f"nothing at all, and unpickable in any view that shows it"
                )
        if not self.options and not self.allow_free_text:
            raise InternalError(
                "this question offers no options and forbids free text, so there is no answer "
                "anyone could give it: an adapter mapping a payload with no choices in it leaves "
                "free text allowed, or raises for the payload it could not read"
            )

@dataclass(frozen=True, slots=True)
class Answer:
    text: str
