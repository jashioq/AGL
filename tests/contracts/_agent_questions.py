"""The mid-run question path: an answer returning into the same session, and one that never comes.

Split out of `agent.py` because §3.7's negotiation is one clause with two edge cases the port
settles explicitly - so that no adapter decides them alone - and because both are easy to satisfy
in a way that looks right and is not. An adapter that asks once per run and starts a new one for
the second question is a working adapter by every assertion except the one below; an adapter that
waits forever on a question nobody is listening for is a *hanging* adapter that a suite without a
deadline reports as a slow one.

**The framework supplies the asking tool.** The adapter wires whatever mechanism its backend has to
the callback: it maps the payload into a `Question`, awaits the handler, and serialises the `Answer`
back into the same live session. Nothing here knows what that mechanism is - a tool, a turn of a
conversation, a control frame - and nothing here may, since the point of `Question` and `Answer`
being the poorest pair that still carries an exchange is that every backend that can ask at all can
produce them.

The two edge cases, quoted from the port because they are what these two tests are:

* An adapter that cannot ask mid-run **says so through `capabilities()`** and may simply never call
  the handler. It does not pretend to ask and it does not block on a mechanism it does not have.
* If the agent asks while `on_question` is `None`, the adapter **must not block**. It tells the
  agent that no answer is available and lets it carry on with its own judgement.

That second one is why `outcome_of` runs everything under a deadline. A run hanging on a question
nobody is listening for is the worst outcome available, because it looks exactly like work - and a
test for it that waited indefinitely would fail in precisely the way the bug does.

`AgentContract` in `agent.py` inherits this class. Implementers subclass that one, never this one.
"""

from pathlib import Path

import pytest

from agl.ports.agent import AgentRunner, Capability, ModelId
from agl.ports.questions import Question

from ._agent_tasks import (
    ANSWER_TOKENS,
    ASK_TWICE,
    ASK_WITH_NOBODY_LISTENING,
    Answers,
    outcome_of,
    task,
    workspace,
)


class AgentQuestionContract:
    """Two rounds inside one run, and a question with nobody listening that still comes back.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_a_question_and_its_answer_are_two_rounds_inside_one_run(
        self, runner: AgentRunner, model: ModelId, tmp_path: Path
    ) -> None:
        """§3.7: the answer returns into the same session, so a negotiation is rounds, not runs.

        Two questions and not one, because one cannot tell an adapter that answers into the live
        session from one that would have to start a fresh run per question - and N rounds inside
        one run is the whole of the clause. Two *different* answers for the same reason: an adapter
        that asked twice while replaying the first answer into both would satisfy a single token.
        The last one is what is looked for in the closing text, since that is the round the prompt
        asks the agent to finish on.

        The branch is on a capability the adapter itself reported, never on which adapter it is.
        Preflight has already refused any role that needs an asker, so a backend that cannot ask
        is not lying by never calling the handler - it is doing the one thing the port allows.
        """
        answers = Answers()
        can_ask = Capability.MID_RUN_QUESTIONS in await runner.capabilities(model)
        outcome = await outcome_of(
            runner, task(workspace(tmp_path), model, ASK_TWICE), on_question=answers
        )

        if not can_ask:
            assert not answers.asked, (
                f"this backend reports no MID_RUN_QUESTIONS and then called the handler "
                f"{len(answers.asked)} time(s). Preflight admits and refuses roles on that answer, "
                f"so a backend that can ask says so rather than surprising a workflow with it"
            )
            return

        assert len(answers.asked) >= 2, (
            f"the handler was called {len(answers.asked)} time(s) in one run against a prompt that "
            f"asks two questions one after the other. The answer goes back into the same session "
            f"so the agent can ask again - an adapter that carries one exchange per run turns a "
            f"negotiation into N runs, and §3.7 accepts a crash mid-negotiation replaying the "
            f"whole step precisely because that session is not reconstructible from anything"
        )
        for asked in answers.asked:
            assert isinstance(asked, Question), (
                f"the handler was handed {type(asked).__name__}. The adapter maps whatever payload "
                f"its backend produced into a Question at its own boundary; a workflow's handler "
                f"is a closure over its own Run and speaks no backend's vocabulary"
            )
            assert asked.prompt, (
                "a question arrived with an empty prompt, which asks nothing and shows nothing - "
                "an adapter that cannot read its backend's payload raises rather than passing on "
                "a question no view could render and nobody could answer"
            )
        assert ANSWER_TOKENS[-1] in outcome.text, (
            f"the agent was answered {ANSWER_TOKENS[-1]!r} and its closing text does not contain "
            f"it. The prompt asks it to reply with the answers it was given, copied exactly, so "
            f"either the answer never reached the session or the run ended before the agent could "
            f"act on it - asking and then dropping the answer is worth less than not asking"
        )

    async def test_a_question_nobody_is_listening_for_does_not_block_the_run(
        self, runner: AgentRunner, model: ModelId, tmp_path: Path
    ) -> None:
        """`on_question` is `None` and the agent asks anyway: the adapter must **not** block.

        It tells the agent that no answer is available and lets it carry on with its own judgement.
        The port settles this explicitly and gives the reason: from outside, a blocked step and a
        thinking step are one observation, so a run waiting on nobody is indistinguishable from a
        run doing the work.

        The deadline lives in `outcome_of`, which turns a run that never comes back into a failed
        assertion naming this clause rather than into a suite somebody eventually kills by hand.
        Without it this test would be the bug rather than the test for it.

        No capability branch. An adapter that cannot ask mid-run never puts the agent in this
        position and passes by never being asked, which is correct and is not something the suite
        needs to know in advance.
        """
        outcome = await outcome_of(
            runner, task(workspace(tmp_path), model, ASK_WITH_NOBODY_LISTENING)
        )
        assert isinstance(outcome.text, str), (
            "the run came back inside the deadline, which is the clause, and then answered with "
            "something that is not the agent's closing text"
        )
