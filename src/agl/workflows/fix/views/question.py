"""The screen a person answers the agent on: the question as the agent phrased it, and the ways
back.

§3.7's `approve_backlog`, at this workflow's own scale. The framework supplies the asking tool, the
adapter maps whatever payload its backend produced into a `Question` and awaits the role's
`on_question`; the handler in `agl/workflows/fix/__init__.py` routes it here and hands back what
this screen returns. Everything between those two points is this module.

## `Screen[Answer]`, and why there is no workflow answer type in front of it

§3.7's example returns a `Screen[Approval]` and its handler maps the `Approval` down to a string on
the way out, because that workflow's answer carries a second thing - a flag and some feedback - and
the port's `Answer` carries one string and deliberately nothing else. **`fix` has no second thing.**
The agent asked a question in the middle of writing a change and what goes back is what the person
said; there is no verdict to record, no field for the workflow to read afterwards, and no branch
anywhere in `fix` that turns on it (§3.6's one rule: branch only on step results, and an answer is
not one). So the `T` here is `Answer` itself, the handler is `return await ...show(...)` with
nothing in between, and the mapping §3.7 performs is the identity.

That is worth stating rather than leaving as a shortcut, because it is the case where the two types
would otherwise be one type spelled twice. A later version of this workflow that wanted to record
*that* a question was asked, or to answer some questions from a policy without showing anybody
anything, would grow its own type here and map it down in the handler - and would be §3.7's example
exactly.

## The responses are built out of the question, because only the question knows what it will accept

`Question` carries three things and two of them decide the shape of this screen:

* **`options`** are "the answers the agent suggested, in the order it suggested them", and each is
  *the exact string that goes back* - not a label for something else, with no id, index or key
  beside it. So each becomes a `Choice` whose label is the option and whose value is `Answer(that
  same option)`, verbatim. Nothing here reorders, deduplicates or prettifies them: two identical
  options are the agent having said the same thing twice, and a view that quietly merged them would
  be editing the question.
* **`allow_free_text`** decides whether the `TextInput` is offered at all. `False` is the agent
  saying it asked for a choice among what it offered, and honouring it here is the difference
  between a constraint and a suggestion. It is a statement about the question and not about what
  this handler could return - so this view offers no field, and the person picks.

**The empty case cannot reach this function**, and that is a fact about `Question` rather than a
gap here. A question with no options and no free text has no answer anybody could give it, and
`ports/questions.py` refuses to construct one - `InternalError`, at the adapter that built it,
before any of this. That refusal is what this module rests on and it is the difference between a
screen and a hang: §3.7 has **no timeouts anywhere**, so a `Screen[Answer]` with an empty
`responses` tuple would be shown, would be un-dismissable, and would block its step until somebody
killed the run - and it would do it at the moment a person is standing there wanting to help.
Re-checking it here would be this view deciding what to do about a value it has already been
promised cannot arrive; what it does instead is name the promise, here and in a test that pins it.

## What the person reads is the prompt, unaltered

The body is `question.prompt` and nothing else - no heading, no framing sentence, no "the agent
asks:". `ports/questions.py` refuses a header field for a reason that applies twice over here: what
the agent said is what a person needs to read, and a workflow adding its own words above it would
be answering for the backend that did not carry one. A caller wanting a heading writes one into the
prompt.

## Re-invoked per frame, like every view, and here that matters more

This function is re-invoked ten times a second **while somebody is part-way through typing into
it**, which is the screen where a needless redraw costs the most. It is cheap for the ordinary
reason - the terminal diffs the `Screen` against the last frame and writes only on a change - and
that diff works only because `TextInput.maps` is excluded from comparison: a fresh `Answer`
constructor reference is bound every frame, two functions are never equal, and a compared `maps`
would make every frame differ from the last one forever. `ports/terminal.py` calls that paragraph
the one most likely to be cleaned up by someone who has not read it. This is the view that would
pay for it.
"""

from typing import Final

from agl.sdk import Answer, Choice, Question, Response, Screen, TextInput

__all__ = ["FREE_TEXT", "agent_question"]

FREE_TEXT: Final = "Answer in your own words"
"""The label beside the free-text field - the prompt for it, not the text a person types.

Written in the second person and naming what the field is *for*, because it sits underneath the
agent's own prompt and next to the agent's own suggestions: "Other" would say what it is not, and
anything shorter reads as a caption on the options above it rather than as a third way to answer."""


def agent_question(question: Question) -> Screen[Answer]:
    """The question as a screen: its prompt as the body, its options and free text as the ways back.

        await run.terminal.show(views.agent_question, question=question)

    Interactive, because `responses` is non-empty - which is what the terminal dispatches on, the
    `Screen[Answer]` annotation being invisible at run time. `show` therefore queues this screen,
    displays it ahead of the board, and blocks the step that asked until a person picks a `Choice`
    or types into the `TextInput`; the `Answer` that produces is what the framework serialises back
    into the same live agent session, in the same step, without the workflow taking a second turn.

    The mutable list is local and is built fresh on every invocation, so nothing is shared between
    frames and the purity rule holds: same question in, equal `Screen` out, every time.
    """
    responses: list[Response[Answer]] = [
        Choice(option, value=Answer(option)) for option in question.options
    ]
    if question.allow_free_text:
        responses.append(TextInput(FREE_TEXT, maps=Answer))
    return Screen(question.prompt, responses)
