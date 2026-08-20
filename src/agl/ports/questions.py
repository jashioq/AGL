"""`Question` and `Answer` - the least a mid-run question can be and still be answerable.

An agent stops in the middle of a run and asks something. Plan §3.7: the adapter maps whatever
payload its backend produced into a `Question`, awaits the workflow's handler, and serialises the
`Answer` back into the same live session. This pair is the whole of what crosses the port for that
exchange, and it is deliberately the poorest pair that still carries it - what is being asked, the
answers the agent suggested, and whether anything else may be said. Every backend that can ask at
all can produce those three. Anything more elaborate and exactly one backend produces it honestly
while the rest fabricate it or quietly drop it - the failure the agent port exists to prevent.

Four things a fuller question would carry, each left out against the same test - could a second,
structurally different backend fill this in without inventing it?

  * **A header, or a title.** One backend's asking mechanism carries a short label above the
    prompt. A backend whose question is simply the next turn of a conversation has nothing to
    derive one from, so the field would be the prompt's first sentence copied, or empty - two
    spellings of "we do not know", in a field that claims to. A caller who wants a heading writes
    one into the prompt, which every backend already carries.
  * **A description beside each option.** Same test, same answer, and one step worse: an option is
    the exact string that has to go back to the agent, so a description is a second string with
    nowhere to go on any backend whose mechanism carries only the choice itself.
  * **Multi-select.** The answer is one string. A set of answers can only be reported by a
    mechanism that can return a set, and a workflow that genuinely needs several answers asks
    several questions - which every backend can do, in the order it asked them.
  * **An id correlating a question to its answer.** The handler takes one question and is awaited;
    the answer is that call's return value, so the correspondence *is* the call. An id would be a
    second and weaker way to say the same thing, and the adapter - which holds the correspondence
    already, because it is the thing doing the awaiting - would be the one to get it wrong.

Everything refused below is an `InternalError`. Nobody types a `Question`: an adapter builds one
out of what a model produced, so a `Question` that cannot be answered means either that we mapped
it wrong or that the backend said something we have no reading for, and at this layer those are
indistinguishable. `run.py` makes the same argument about a record only AGL writes and reads.
"""

from dataclasses import dataclass

from agl.ports.errors import InternalError

__all__ = ["Answer", "Question"]


@dataclass(frozen=True, slots=True)
class Question:
    """What the agent stopped to ask, in the words it used, with nothing added and nothing implied.

    The framework has no opinion on how it is shown. The handler routes it to a view, or to a log,
    or answers it from a policy without showing anybody anything - all three are a workflow's
    business, and none of them is this type's.
    """

    prompt: str
    """What is being asked, as the agent phrased it. Plain text, and the one required field.

    Not marked up and not templated: whatever the agent said is what a person needs to read, and a
    port that reserved a syntax here would be reserving it in every backend at once."""

    options: tuple[str, ...] = ()
    """The answers the agent suggested, in the order it suggested them. Empty is ordinary.

    Each is the exact string that goes back - `Answer.text` repeats one of these verbatim - so
    these are not labels for something else, and there is no id, index or key beside them. Empty
    means the agent suggested nothing, which is what an open question looks like, and not that the
    backend supports no options."""

    allow_free_text: bool = True
    """Whether an answer that is not one of `options` may be given.

    Defaults to allowing it, because the alternative default makes the no-options question - the
    one every backend can ask - unanswerable, and because the restricting value is the one worth
    having to type. `False` says the agent asked for a choice among what it offered; it is a
    statement about the question, not about what the handler is capable of returning."""

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
    """What goes back to the agent: one string, and deliberately nothing else.

    One field because the adapter has to serialise this into a live session, and text is the only
    thing every backend can carry. A structured answer would be a shape one backend accepts and the
    rest flatten into text anyway - and flattening at the boundary, invisibly, is worse than
    flattening in the workflow, deliberately.

    The workflow's own answer type carries more than this and goes on carrying it: a `Screen[T]`
    returns its `T`, and the workflow's handler maps that down to a string on the way out. That
    mapping is a workflow's own business, in a language it chose, and not this port's to guess.
    """

    text: str
    """The answer. Either one of the offered option strings, verbatim, or free text.

    Which of the two it is, is not recorded - the agent reads the string and knows, and a flag
    saying so would be a second thing to keep true. The empty string is allowed and means nothing
    was said, which is exactly why no option may be spelled that way."""
