"""The two members preflight asks before a run: what a backend can do, and whether it can now.

Split out of `agent.py` along a line the port draws itself. One of its three members runs an agent;
these two are asked *about* one, both take a `ModelId`, and both are async for the same reason - the
answer depends on the world, and probing it at construction time would break the composition root
for every run, including the ones that never touch this backend.

They are deliberately not one member. §3.2 asks them at preflight one after the other and does
different things with the answers: a missing capability is permanent and the workflow must change,
while not being ready is a state of the world that a login fixes in ten seconds. A single call
reporting both would have to invent a way of saying which of the two it meant, and the caller would
have to unpick it to know whether to tell the author or the operator.

Neither test here asserts anything about the other member's answer. In particular, nothing treats a
reported capability as a promise that a call using it succeeds - the port says in as many words that
it is not one, and a suite that quietly relied on it would be teaching the next adapter author that
`capabilities()` is a guarantee they have to honour.

`AgentContract` in `agent.py` inherits this class. Implementers subclass that one, never this one.
"""

import pytest

from agl.ports.agent import AgentRunner, Capability, ModelId
from agl.ports.errors import UpstreamUnavailable


class AgentPreflightContract:
    """What `capabilities` and `check_ready` answer, and the difference the port draws between them.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_capabilities_answers_for_the_model_it_was_asked_about(
        self, runner: AgentRunner, model: ModelId
    ) -> None:
        """"What can you do" - permanent, per model, and not a promise the next call succeeds.

        Per model because the routing runner is an `AgentRunner` like any other and one answer for
        "some provider" would be a lie in the shape of an answer; the signature carries that, and
        this test is what fails an implementation that ignores the argument and answers for itself.

        The membership check is the one with teeth. `frozenset[Capability]` is proved by `mypy` for
        an adapter that writes the members out, and proved by nothing at all for one that builds
        the set out of strings its backend printed - and a set holding `"file_edit"` compares equal
        to one holding `Capability.FILE_EDIT` everywhere preflight would look, because `Capability`
        is a `StrEnum`. It stops comparing equal the day a member's value is spelled differently,
        which is a run refused for a capability the backend has, months after the suite went green.

        Asking twice is a reading the port does not spell out, argued in `agent.py`'s docstring:
        the answer may depend on what is installed, which is a fact about restarts, and preflight
        asks once and then runs a workflow for an hour on what it was told.
        """
        reported = await runner.capabilities(model)
        assert isinstance(reported, frozenset), (
            f"capabilities answered with {type(reported).__name__}, and preflight compares what a "
            f"role requires against a frozenset of what this backend can be asked for"
        )
        strange = [member for member in reported if not isinstance(member, Capability)]
        assert not strange, (
            f"capabilities answered with {strange}, which are not Capability members. Capability "
            f"is a StrEnum, so a set of the equivalent strings passes every comparison preflight "
            f"makes today and stops passing them the day a member's value is spelled differently"
        )
        assert await runner.capabilities(model) == reported, (
            "the same model answered differently twice in a row, and preflight asks once before a "
            "run that may last an hour: an answer that moves between two calls is not one a "
            "workflow can be admitted or refused on"
        )

    async def test_check_ready_answers_with_nothing_or_says_why_it_cannot(
        self, runner: AgentRunner, model: ModelId
    ) -> None:
        """"Can you do it now" - a state of the world, and the other half of preflight.

        Two legal outcomes and no third. Returning is checked by `mypy`, which is why nothing here
        assigns the result - a value out of a `-> None` member is a type error, in the adapter,
        where it belongs. The raise is what this test is for: §3.2's first preflight check is this
        call over every provider a workflow's roles name, and it can only kill a run at second zero
        if the exception is the one the framework catches. Anything else escapes to the top of the
        CLI as exit 70, telling the reader to file a bug about their own logged-out session.

        The message is asserted non-empty because the port asks for a reason a person can act on -
        the harness is not on `PATH`, its version is too old, the session is not authenticated -
        and an `UpstreamUnavailable()` carrying nothing is the same dead end as no message at all.
        """
        try:
            await runner.check_ready(model)
        except UpstreamUnavailable as unavailable:
            assert str(unavailable), (
                "check_ready refused without saying why. It is raised at second zero of a run so "
                "that somebody can fix the world and start again, and an empty refusal leaves "
                "them to guess which of installed, current and authenticated failed"
            )
        except Exception as wrong:
            raise AssertionError(
                f"check_ready raised {type(wrong).__name__}: {wrong}. An adapter translates what "
                f"its backend throws into errors.py at its own boundary, and this member's one "
                f"refusal is UpstreamUnavailable - preflight catches that and nothing else, so "
                f"anything else here is a run that dies as a framework bug instead of as a "
                f"backend that is not ready"
            ) from wrong
