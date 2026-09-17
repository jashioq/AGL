"""The three members preflight asks before a run: what a backend can do, what it runs on, if now.

Split out of `agent.py` along a line the port draws itself. One of its four members runs an agent;
these three are asked *about* one, all take a `ModelId`, and all are async for the same reason - the
answer depends on the world, and probing it at construction time would break the composition root
for every run, including the ones that never touch this backend.

They are deliberately not one member. Preflight asks them one after the other and does different
things with the answers: a missing capability is permanent and the workflow must change,
while not being ready is a state of the world that a login fixes in ten seconds. A single call
reporting both would have to invent a way of saying which of the two it meant, and the caller would
have to unpick it to know whether to tell the author or the operator. `installation` is a third
thing again, and the one that never refuses anything: what it reports is material for a warning, so
a backend at a version nobody tested runs, and the operator is told rather than stopped.

No test here asserts anything about another member's answer. In particular, nothing treats a
reported capability as a promise that a call using it succeeds - the port says in as many words that
it is not one, and a suite that quietly relied on it would be teaching the next adapter author that
`capabilities()` is a guarantee they have to honour. Nothing reads a reported *version* as a
promise either: an implementation reporting `None` for a tool it could not reach is correct, and the
clause below is about the shape of what comes back rather than about what is installed here.

`AgentContract` in `agent.py` inherits this class. Implementers subclass that one, never this one.
"""

import pytest
from agl.ports.agent import (
    AgentRunner,
    Capability,
    Installation,
    ModelEfforts,
    ModelId,
    Standing,
)
from agl.ports.errors import UpstreamUnavailable

class AgentPreflightContract:
    """What the three members asked *about* a backend answer, and how the port keeps them apart.

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
        where it belongs. The raise is what this test is for: the first preflight check is this
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

    async def test_the_installation_it_reports_is_one_a_version_warning_can_be_written_from(
        self, runner: AgentRunner, model: ModelId
    ) -> None:
        """"What are you running on" - answered, never refused, and answered even where nothing is.

        Nothing here asserts what is installed on the machine the suite runs on, because that is
        not a promise any implementation makes. What it asserts is that whatever came back is a
        report a warning could be built out of, which is four separate things.

        **The tool has a name.** `tool` is the only place a vendor's binary is spelled: the layer
        that writes the warning cannot spell one, `scripts/check`'s containment gate being what
        stops it, so a backend that leaves this empty leaves the operator reading a sentence about
        nothing. **A version is the tool's own text or it is `None`.** `None` is the honest report
        of a tool that could not be reached, and the empty string is a second spelling of it that
        `Standing` would then place as unreadable rather than as unreported. **The declared range
        is orderable**, which is asserted by placing the range's own floor inside it - an adapter
        that spells its tested versions in a grammar `Standing` cannot order would otherwise report
        `UNREADABLE` forever, and the reader would blame the tool for a string AGL wrote. **And
        every effort listing is levels the tool spells**, each one named once, with a default that
        is one of them, because a warning naming a level no listing carries is a warning about
        nothing and one naming a level twice is a sentence that reads as broken. Distinctness is
        asserted here and was free while `levels` was a set; it became an implementation's promise
        when the listing grew an order, which is the half of the change a contract can still hold.

        `efforts` being empty is correct and is not asserted against. The port says so - a tool
        that cannot enumerate what its models reason at reports nothing here - and an adapter whose
        tool *can* is not made to by any clause a suite could write against the port.
        """
        reported = await runner.installation(model)

        assert isinstance(reported, Installation), (
            f"installation answered with {type(reported).__name__}. The whole of a version warning "
            f"is read off this value, the name of the tool it is about included"
        )
        assert reported.tool, (
            "installation reported an empty tool name. This is the one place a backend's binary is "
            "named: nothing above this port may spell one, so a warning built from an empty name "
            "is a sentence with a hole where its subject goes"
        )
        assert reported.version is None or reported.version, (
            "installation reported an empty version string. A tool that could not be reached is "
            "reported as None, which stands apart from a tool that answered - an empty string is a "
            "second spelling of 'nothing' that gets placed as unreadable instead of unreported"
        )
        assert reported.where is None or reported.where, (
            "installation reported an empty name for the binary it read. A backend that identified "
            "none says so with None; an empty string reads as a binary called nothing at all"
        )
        floor = Installation(
            tool=reported.tool,
            version=reported.tested.lowest,
            tested=reported.tested,
            efforts={},
        )
        assert floor.standing is Standing.WITHIN, (
            f"the range {reported.tested} does not contain its own floor, standing "
            f"{floor.standing} instead. It is this adapter's own constant rather than anything a "
            f"machine reported, so either its ends are the wrong way round or they are spelled in "
            f"a grammar nothing here orders - and every run would then be warned about a tool that "
            f"is exactly the one AGL was tested against"
        )
        for named, efforts in reported.efforts.items():
            assert isinstance(named, ModelId) and isinstance(efforts, ModelEfforts), (
                f"the efforts mapping carries {named!r} -> {efforts!r}. It is keyed by the model "
                f"ids this port speaks and not by a backend's own slugs, because the caller "
                f"reading it has a `ModelId` and no way to translate one"
            )
            strange = [level for level in efforts.levels if not isinstance(level, str) or not level]
            assert not strange, (
                f"{str(named)!r} offers {strange} among its levels. A level is the tool's own "
                f"spelling as a non-empty string, deliberately not an effort enum's member: the "
                f"point of reporting them is to notice where the two have come apart"
            )
            twice = sorted({level for level in efforts.levels if efforts.levels.count(level) > 1})
            assert not twice, (
                f"{str(named)!r} lists {twice} more than once. A listing is ordered so that a "
                f"sentence can name its last level as the ceiling, and a level repeated in it is "
                f"one the reader is told about twice in a row"
            )
            assert efforts.default is None or efforts.default in efforts.levels, (
                f"{str(named)!r} falls back to {efforts.default!r}, which is not among the levels "
                f"it offers. A default outside its own listing describes no model, and a warning "
                f"naming what a task would be lowered to would name that"
            )
