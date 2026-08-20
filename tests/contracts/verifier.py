"""`VerifierContract` - what every `Verifier` owes, asserted before an implementation of one exists.

Subclass it once per implementation, override the four fixtures, and add nothing:

    class TestTheVerifierIWrote(VerifierContract):
        @pytest.fixture
        def verifier(self) -> Verifier:
            return TheVerifierIWrote(...)

        @pytest.fixture
        def workdir(self, tmp_path: Path) -> Path:
            return tmp_path                       # a directory this runner can actually run in

        @pytest.fixture
        def passing_command(self) -> str:
            return "..."                          # this runner answers `passed`

        @pytest.fixture
        def failing_command(self) -> str:
            return f"echo {ANNOUNCEMENT}; exit 1"  # answers `not passed`, and says ANNOUNCEMENT

The real adapter and the fake both run this class, which is the whole mechanism keeping a fake from
drifting into fiction (§1.9). It is written here, at stage 3, before either exists, because a
subagent that writes its own tests writes tests that pass - and stage 6 ends with "the contract
suite passes", a sentence worth something only when the suite had no stake in the outcome.

One class in one module, because the port is one method and draws no seam to split along. Every
other suite in this package is assembled out of two or three modules; this one would be inventing
a division `Verifier` does not have.

## Written against the port, and **this suite must not assume a subprocess**

The rule binding this package is that nothing here assumes a backend. Here it is sharper than
usual, because the obvious implementation is so obvious: the port names three that must all be
able to pass - one that runs the command on this machine, one that runs it in an isolated image,
and one that hands it to a service that runs it elsewhere and waits. So nothing below starts a
process, spells a command, reads a stream, names a shell, waits on a pid, or knows that any of
those things exist. **Every command in this suite came from a fixture**, because a command that
passes is a fact about the runner and not about this port, and a suite that wrote `exit 1` for
itself would be a suite only one of those three implementations could ever pass.

The one `Path` here is the port's own: `verify` **accepts** a working directory, so a directory is
part of the vocabulary rather than a backdoor into one - and it is a fixture for the same reason
the commands are. Which directories a runner can be pointed at is the implementation's business:
`tmp_path` is the right answer for a runner on this machine and the wrong answer for one whose
work happens somewhere else.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe. Every one of these is a limit of what the port's own surface can be
made to reveal, not a test somebody forgot.

1. **That `workdir` is never interpolated into the command text.** This is the port's one security
   clause and **this suite cannot assert it.** The shape of a test is obvious enough - hand over a
   working directory whose path holds something that would misbehave if it were pasted into a
   command line, and see whether the answer changes - and it fails on two counts. This suite does
   not choose `workdir`: it is handed one by a fixture the implementation's own author writes, so
   the test would be armed by the party it is meant to catch, and an author who supplies a tame
   path disarms it silently. And a green result could not be read: "nothing interpolated this
   path" and "this path had nothing in it to interpolate" produce the same `VerifierOutcome`, and
   the port hands back nothing else to tell them apart. Where the clause is enforceable is at the
   implementation - stage 6.1 records how the configured command is executed and passes the
   workspace by `cwd=` - and that is where an assertion has a witness. The half that *is* pinned
   here without any test at all is structural: `verify` takes one `str`, so an adapter reaching a
   working directory into that argument has to compose it on purpose.

2. **That the command reaches the runner unaltered.** "Exactly as the user wrote it, operators and
   all" is asserted by the signature and by `mypy --strict` at every call site - one `str`, never a
   program plus arguments - and by nothing here. Both commands below came from the implementation's
   own fixtures, so an implementation that rewrote, split or escaped what it was handed would be
   marking its own paper.

3. **`UpstreamUnavailable`, and `UpstreamUnexpected` with it.** The first is for a command that
   cannot be **started**, which is a fact about the runner rather than about the command: with a
   shell in the picture every string starts, and a name no program answers to comes back as a
   failed build with some number on it, which is the correct answer and not this error. Provoking
   it means breaking the runner itself - unsetting a binary, stopping a daemon, cutting a network -
   and the port offers no member that does any of that. A fixture for "a command that cannot be
   started" would be asking each implementation to describe its own failure, which is the thing a
   contract suite exists not to do.

4. **Any numeric convention for `status`.** Nothing here compares it to `0`, to `1`, or to
   anything else. The port warns in as many words that a reader who takes this field for one
   runner's convention starts writing comparisons against remembered magic numbers, and its
   agreement clause is conditional - *an implementation with no number of its own* says `0` or `1`
   agreeing with `passed` - so a suite cannot tell which kind of implementation it is looking at.
   What is asserted is that the field is an `int` and not a second verdict.

5. **That an empty `output` is accepted.** Empty is legal and passing builds routinely print
   nothing; the way that clause is honoured here is by nothing ever demanding text of a passing
   build. But the reverse - an implementation that refused, or crashed on, a command that printed
   nothing - would not be caught, because every command here is one an implementer supplied.

6. **That a deadline is enforced, or what an expired one reports.** `build_timeout` is project
   configuration reaching an implementation where implementations are configured, so it is not on
   this port's surface at all; and the port settles that whatever an expired deadline reports
   arrives as an ordinary rejected outcome. Nothing here waits long enough to find out.

7. **That the output is everything the command produced.** A local runner has two streams and this
   port has one, deliberately, and a service returning one blob of log has nothing to split. What
   is asserted is that a marker the failing command announced comes back; an implementation
   dropping one stream, truncating, or interleaving differently is not visible from out here.

8. **Anything about two builds at once.** §3.4 has the gate serial because the queue in front of
   it serialises it, and that queue is the framework's. Nothing here starts two.

## Where the port is silent, and what this suite assumed

**That a verifier answers more than once.** The port describes one call and says nothing about the
next. The consumer settles it: there is one call site and a run lands many children through it, so
an implementation good for a single answer is one no run could use. The test that pins it also
pins the sharper half - a failed build must not poison the runner - which is the ordinary case in
a merge train and would otherwise be discovered on the second child.

**That "passed" and "failed" are things an implementer can name in advance.** Both command fixtures
ask for a command whose verdict is already known. That is not asking an implementation to predict
itself: it is the same demand `WorkspaceContract` makes with `base`, where the suite has no way to
ask an implementation what it is over and so is told.
"""

from pathlib import Path
from typing import Final

import pytest

from agl.ports.verifier import Verifier, VerifierOutcome

# What the failing command below announces, so that this suite can see that output was carried
# rather than invented. One token, no spaces and no quoting hazards, because an implementer has
# to be able to paste it into whatever their runner takes without thinking about it.
ANNOUNCEMENT: Final = "agl-contract-suite-build-gate-ran"


def assert_carried(outcome: VerifierOutcome) -> None:
    """The three fields, in the shapes the framework and the failure screen rely on.

    Checked on every outcome this suite gets back rather than written out three times, because it
    is the same claim each time and none of it is what any one test is about. `passed` is a `bool`
    and not something truthy, because it is the one thing the framework branches on; `status` is an
    `int` that is *not* a `bool`, because a second verdict is exactly what that field must not be
    and `bool` is an `int` in Python; `output` is a `str`, because the failure screen puts it
    straight in front of a person and a `None` there is a screen that cannot be drawn.
    """
    assert isinstance(outcome.passed, bool), (
        f"a verifier answered with passed={outcome.passed!r}, which is not a bool. It is the one "
        f"thing the framework branches on - a landing that fails the gate is undone and one that "
        f"passes is kept - and something merely truthy makes that branch depend on a value the "
        f"port never described"
    )
    assert isinstance(outcome.status, int) and not isinstance(outcome.status, bool), (
        f"a verifier answered with status={outcome.status!r}. It is the number the runner "
        f"reported, carried so that a person can see it, and a bool there is a second verdict "
        f"wearing the field's name - an implementation with no number of its own says 0 or 1"
    )
    assert isinstance(outcome.output, str), (
        f"a verifier answered with output={outcome.output!r}, which is not text. It goes on the "
        f"failure screen as it stands, so empty is legal and absent is not"
    )


class VerifierContract:
    """The suite. One method, three fields, and the two answers the framework tells apart.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and
    a test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def verifier(self) -> Verifier:
        """The implementation under test, already built with whatever it needs.

        Built by construction is the port's own design - `verify` takes a command and a directory
        and nothing else, and the deadline is configuration - so this fixture is the only place
        the runner is named, exactly as the container names it once and hands the same instance to
        `integrate()`.

        Function-scoped, like every fixture in this package: one test runs a build that fails, and
        a verifier carried between tests would let one test's failure be another test's starting
        state.
        """
        raise NotImplementedError(
            "the Verifier contract suite has no implementation to run against: subclass "
            "VerifierContract and override the `verifier` fixture to hand back the Verifier "
            "under test"
        )

    @pytest.fixture
    def workdir(self) -> Path:
        """A directory this runner can be pointed at, standing in for a `Workspace.path`.

        What the framework passes is a workspace's directory - absolute, existing, and holding a
        checkout - so that is the shape to hand over here. `return tmp_path` is the whole override
        for a runner that works on this machine, and it is deliberately not what this suite does
        for itself: which directories a runner can reach is the implementation's business, and a
        suite that fabricated one would have decided that every verifier runs locally.

        Nothing below reads or writes anything in it. It is passed to every call because the port
        requires one, and what an implementation does with it is the clause this suite cannot see -
        the module docstring's first gap says why at length.
        """
        raise NotImplementedError(
            "the Verifier contract suite has nowhere to run a build: subclass VerifierContract "
            "and override the `workdir` fixture with a directory the Verifier under test can be "
            "pointed at - `return tmp_path` for a runner on this machine"
        )

    @pytest.fixture
    def passing_command(self) -> str:
        """A build command this runner runs to completion and reports as passed.

        It cannot be derived and it cannot be guessed: what makes a build pass is a fact about the
        runner, and a suite that wrote one for itself would have written one only a local shell
        could answer.

        **It may print nothing.** Empty output is legal and passing builds routinely produce it, so
        nothing here asks this command's output to say anything - which is the only way a suite can
        honour a clause whose whole content is a permission.
        """
        raise NotImplementedError(
            "the Verifier contract suite has no build that passes: subclass VerifierContract and "
            "override the `passing_command` fixture with a command the Verifier under test "
            "reports as passed"
        )

    @pytest.fixture
    def failing_command(self) -> str:
        """A build command this runner runs to completion and reports as **not** passed, whose
        output holds `ANNOUNCEMENT`.

        Two things at once, because the failure screen is what `output` exists for and a red build
        is the moment a person reads it. An implementation that answers the verdict correctly and
        hands back nothing to look at has lost the only channel AGL has for "why".

        Which stream the announcement is written to is the implementer's choice and the point of
        leaving it one: a local runner has two and this port has one, deliberately, so a runner
        that keeps only the tidy stream is one this fixture can be pointed at to catch.

        Not a command that fails to *start* - that is `UpstreamUnavailable` and a different clause
        this suite cannot reach at all (see the gaps). This one runs, and answers no.
        """
        raise NotImplementedError(
            "the Verifier contract suite has no build that fails: subclass VerifierContract and "
            f"override the `failing_command` fixture with a command the Verifier under test "
            f"reports as failed and whose output holds {ANNOUNCEMENT!r}"
        )

    async def test_a_build_that_passed_answers_with_a_verdict_a_number_and_whatever_text_it_made(
        self, verifier: Verifier, workdir: Path, passing_command: str
    ) -> None:
        """The ordinary answer, and the shape every field of it has to arrive in.

        `passed` is the whole of what the framework does with this port: §3.4 keeps a landing that
        passes the gate and undoes one that does not, and there is no third branch for it to take.

        The two carried fields are asserted for their shapes and for nothing else. **No number
        appears in this test** - not `0`, not anything - because the port promises no convention
        and warns that a reader who assumes one starts writing comparisons against remembered magic
        numbers. And no text is demanded, because a passing build that printed nothing is the
        common case rather than a broken one.
        """
        outcome = await verifier.verify(passing_command, workdir)

        assert_carried(outcome)
        assert outcome.passed is True, (
            f"a build the implementer named as passing came back with passed={outcome.passed!r} "
            f"and output {outcome.output!r}. This is the verdict `integrate()` keeps a landing "
            f"on, and there is nothing else on this port for it to read"
        )

    async def test_a_build_that_failed_is_the_answer_and_never_an_exception(
        self, verifier: Verifier, workdir: Path, failing_command: str
    ) -> None:
        """A red build is the gate working, not the gate breaking.

        The port says it in as many words: raising would put "your tests are red" in the same
        bucket as "the runner is not installed", and the framework would then be catching an
        exception to learn the ordinary second answer to the only question it asks. This test
        contains no `pytest.raises`, and that absence is the assertion - an implementation that
        raises here fails before reaching a line of its own.

        The announcement is what makes this more than a verdict. Output exists for the person
        reading the failure screen, and a failing build is when they read it, so an implementation
        that reports the right verdict with nothing attached has kept the answer and thrown away
        the only reason AGL can give for it.
        """
        outcome = await verifier.verify(failing_command, workdir)

        assert_carried(outcome)
        assert outcome.passed is False, (
            f"a build the implementer named as failing came back with passed={outcome.passed!r}. "
            f"A failing build is the answer rather than an error, and it is the one that costs "
            f"something: §3.4 undoes the landing that produced it"
        )
        assert ANNOUNCEMENT in outcome.output, (
            f"the failing build announced {ANNOUNCEMENT!r} and the outcome came back with output "
            f"{outcome.output!r}. What the command produced is carried for the person at the "
            f"failure screen, and a verdict with none of it attached leaves them nothing to read"
        )

    async def test_the_gate_answers_every_time_it_is_asked_and_a_red_build_does_not_poison_it(
        self, verifier: Verifier, workdir: Path, passing_command: str, failing_command: str
    ) -> None:
        """One call site, called once per landing, and a run lands children all afternoon.

        The port describes a single call and says nothing about the next one, so this is a reading
        rather than a quotation - and it is settled by the consumer: `integrate()` is the only
        thing that calls `verify`, every child a run lands goes through it, and an implementation
        good for one answer is one no run could use past its first ticket.

        The order below is the one that bites. A failing build first, then a passing one on the
        same verifier: a runner that kept the failure - a session it did not reopen, a directory it
        did not clean, an outcome it cached - answers the second call with the first call's
        verdict, and that is a merge train that rejects every remaining child for a fault the
        first one had.
        """
        failed = await verifier.verify(failing_command, workdir)
        passed = await verifier.verify(passing_command, workdir)
        again = await verifier.verify(failing_command, workdir)

        assert_carried(failed)
        assert_carried(passed)
        assert_carried(again)
        assert failed.passed is False, "the first build failed, which is this test's premise"
        assert passed.passed is True, (
            "a build the implementer named as passing was reported failed when it followed a "
            "build that failed. Each call is one gate over one momentary combined state, and a "
            "verifier carrying anything from the last one decides this landing on the last "
            "landing's evidence"
        )
        assert again.passed is False, (
            "the same failing build reported two different verdicts in one process, so what this "
            "port answers depends on how many times it has been asked"
        )
