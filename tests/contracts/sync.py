"""`SyncContract` - what every `Syncer` owes, asserted before an implementation of one exists.

Subclass it once per implementation, override the three fixtures, and add nothing:

    class TestTheSyncerIWrote(SyncContract):
        @pytest.fixture
        def syncer(self) -> Syncer:
            return TheSyncerIWrote(...)

        @pytest.fixture
        def workspace(self, tmp_path: Path) -> Path:
            return ...          # a workspace this syncer installs from and reports as synced

        @pytest.fixture
        def refused_workspace(self, tmp_path: Path) -> Path:
            return ...          # one it reports as **not** synced, saying ANNOUNCEMENT

The real adapter and the fake both run this class, which is the whole mechanism keeping a fake from
drifting into fiction. It is written against the port alone, because an adapter ships once "the
contract suite passes", and that sentence is worth something only where the suite had no stake in
the outcome.

One class in one module, for `verifier.py`'s reason: the port is one method and draws no seam to
split along.

## Written against the port, and **this suite must not assume an installer**

Nothing here names uv, a package index, a virtual environment, a lock file or a subprocess. The
port says a sync installs what a workspace's workflows declare and says nothing about how, and an
implementation that installed into an image, or asked a service to prepare an environment
elsewhere, owes exactly what is asserted below. **Both workspaces come from fixtures**, because
what makes a sync succeed is a fact about the installer rather than about this port, and a suite
that built one for itself would be a suite only one implementation could pass.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe.

1. **That anything was installed.** The port hands back a verdict, a number and some text, and no
   member of it says where a package landed or whether one did. An implementation that answers
   `synced` and installs nothing passes here, and what catches that lives with the implementation:
   `tests/adapters/test_uv_syncer.py` reads the command line the real adapter composes, because the
   flags on it are the whole of what decides what gets installed.

2. **That the workflows themselves are left uninstalled.** It is the port's own clause and the
   reason for the flag the adapter carries, and it is invisible from here for the same reason as
   above: the outcome is the same either way. It is asserted where the command line is.

3. **Any numeric convention for `status`.** Nothing here compares it to `0` or to anything else.
   The field carries the number the installer reported so that a person can see it, and an
   implementation with no number of its own is free to say `0` and `1` agreeing with `synced` - so
   a suite cannot tell which kind of implementation it is looking at. What is asserted is that the
   field is an `int` and not a second verdict.

4. **`UpstreamUnavailable` when the installer cannot be started.** Provoking it means breaking the
   installer itself - unsetting a binary, cutting a network - and the port offers no member that
   does any of that. A fixture for it would be asking each implementation to describe its own
   failure, which is the thing a contract suite exists not to do.

5. **That a refused sync leaves the workspace as it was.** Half of a resolution is a real state of
   a real machine, and the port hands back nothing to see it with.

6. **Anything about two syncs at once.** Nothing here starts two, and the port promises nothing
   about what happens if somebody does.

## Where the port is silent, and what this suite assumed

**That a syncer answers more than once.** The port describes one call and says nothing about the
next; a person who fixes a typo in a dependency and syncs again is the ordinary case, so an
implementation good for a single answer is one no operator could use. The test that pins it also
pins the sharper half - a refused sync must not poison the syncer - which is exactly the order the
second sync arrives in.
"""

from pathlib import Path
from typing import Final
import pytest
from agl.ports.sync import Syncer, SyncOutcome

# What the refused workspace's sync announces, so that this suite can see that output was carried
# rather than invented. One token, no spaces and no quoting hazards, because an implementer has to
# be able to arrange for it without thinking about how their installer quotes things.
ANNOUNCEMENT: Final = "agl-contract-suite-sync-ran"

def assert_carried(outcome: SyncOutcome) -> None:
    """The three fields, in the shapes the command that calls this port relies on.

    Checked on every outcome this suite gets back rather than written out three times, because it
    is the same claim each time and none of it is what any one test is about. `synced` is a `bool`
    and not something truthy, because it is the one thing a caller branches on; `status` is an
    `int` that is *not* a `bool`, because a second verdict is exactly what that field must not be
    and `bool` is an `int` in Python; `output` is a `str`, because a person reads it as it stands
    and a `None` there is nothing anybody can print.
    """
    assert isinstance(outcome.synced, bool), (
        f"a syncer answered with synced={outcome.synced!r}, which is not a bool. It is the one "
        f"thing a caller branches on - a workspace that did not sync is one whose workflows "
        f"cannot import what they declare - and something merely truthy makes that branch depend "
        f"on a value the port never described"
    )
    assert isinstance(outcome.status, int) and not isinstance(outcome.status, bool), (
        f"a syncer answered with status={outcome.status!r}. It is the number the installer "
        f"reported, carried so that a person can see it, and a bool there is a second verdict "
        f"wearing the field's name - an implementation with no number of its own says 0 or 1"
    )
    assert isinstance(outcome.output, str), (
        f"a syncer answered with output={outcome.output!r}, which is not text. It is what a "
        f"person is shown when a sync is refused, so empty is legal and absent is not"
    )

class SyncContract:
    """The suite. One method, three fields, and the two answers a caller tells apart.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and
    a test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def syncer(self) -> Syncer:
        """The implementation under test, already built with whatever it needs.

        Built by construction is the port's own design - `sync` takes a directory and nothing else,
        so whatever an installer needs to be pointed at is settled before this fixture hands it
        back, exactly as the container settles it once.

        Function-scoped, like every fixture in this package: one test asks for a sync that is
        refused, and a syncer carried between tests would let one test's refusal be another test's
        starting state.
        """
        raise NotImplementedError(
            "the Syncer contract suite has no implementation to run against: subclass "
            "SyncContract and override the `syncer` fixture to hand back the Syncer under test"
        )

    @pytest.fixture
    def workspace(self) -> Path:
        """A workspace this syncer installs from and reports as synced.

        What the framework passes is the operator's own workspace directory - absolute, existing,
        and holding the project file that names its workflows - so that is the shape to hand over
        here. It cannot be derived and it cannot be guessed: what makes a sync succeed is a fact
        about the installer, and a suite that wrote one for itself would have decided that every
        syncer installs onto this machine.

        **Its sync may print nothing.** Empty output is legal - an installer with nothing left to
        do routinely says so in no words at all - so nothing here asks this workspace's sync to say
        anything, which is the only way a suite can honour a clause whose whole content is a
        permission.
        """
        raise NotImplementedError(
            "the Syncer contract suite has no workspace to sync: subclass SyncContract and "
            "override the `workspace` fixture with a workspace directory the Syncer under test "
            "reports as synced"
        )

    @pytest.fixture
    def refused_workspace(self) -> Path:
        """A workspace this syncer runs against and reports as **not** synced, saying
        `ANNOUNCEMENT`.

        Two things at once, because output is what a person reads the moment a sync is refused. A
        dependency that resolves to nothing, a version nothing satisfies and a project file that
        does not parse all arrive this way, and an implementation that answers the verdict
        correctly while handing back nothing to look at has lost the only channel AGL has for
        "why".

        Which stream the announcement is written to is the implementer's choice and the point of
        leaving it one: an installer on this machine has two and this port has one, deliberately,
        so one that keeps only the tidy stream is one this fixture can be pointed at to catch.

        Not a workspace the installer refuses to *start* on - that is a raise and a clause this
        suite cannot reach at all (see the gaps). This one is run against, and answers no.
        """
        raise NotImplementedError(
            "the Syncer contract suite has no workspace whose sync is refused: subclass "
            "SyncContract and override the `refused_workspace` fixture with a workspace the "
            f"Syncer under test reports as not synced, saying {ANNOUNCEMENT!r}"
        )

    async def test_a_workspace_that_synced_answers_with_a_verdict_a_number_and_any_text_it_made(
        self, syncer: Syncer, workspace: Path
    ) -> None:
        """The ordinary answer, and the shape every field of it has to arrive in.

        `synced` is the whole of what a caller does with this port: a workspace that synced is one
        whose workflows can import what they declare, and there is no third branch to take.

        The two carried fields are asserted for their shapes and for nothing else. **No number
        appears in this test** - not `0`, not anything - because the port promises no convention.
        And no text is demanded, because a sync with nothing left to do printing nothing is the
        common case rather than a broken one.
        """
        outcome = await syncer.sync(workspace)

        assert_carried(outcome)
        assert outcome.synced is True, (
            f"a workspace the implementer named as syncing came back with synced="
            f"{outcome.synced!r} and output {outcome.output!r}. This is the verdict a caller "
            f"reads, and there is nothing else on this port for it to read"
        )

    async def test_a_sync_that_was_refused_is_the_answer_and_never_an_exception(
        self, syncer: Syncer, refused_workspace: Path
    ) -> None:
        """A refused sync is the installer working, not the installer breaking.

        Raising would put "this dependency does not resolve" in the same bucket as "uv is not
        installed", and a caller would then be catching an exception to learn the ordinary second
        answer to the only question it asks. This test contains no `pytest.raises`, and that
        absence is the assertion - an implementation that raises here fails before reaching a line
        of its own.

        The announcement is what makes this more than a verdict. A refusal a person cannot read is
        one they cannot act on, and the resolver's own words are the only account of it anybody
        gets.
        """
        outcome = await syncer.sync(refused_workspace)

        assert_carried(outcome)
        assert outcome.synced is False, (
            f"a workspace the implementer named as refused came back with synced="
            f"{outcome.synced!r}. A refused sync is the answer rather than an error, and it is "
            f"the one that costs something: the workflows in that workspace go on importing "
            f"whatever was installed last"
        )
        assert ANNOUNCEMENT in outcome.output, (
            f"the refused sync announced {ANNOUNCEMENT!r} and the outcome came back with output "
            f"{outcome.output!r}. What the installer said is carried for the person who has to "
            f"fix it, and a verdict with none of it attached leaves them nothing to read"
        )

    async def test_a_syncer_answers_every_time_it_is_asked_and_a_refusal_does_not_poison_it(
        self, syncer: Syncer, workspace: Path, refused_workspace: Path
    ) -> None:
        """One syncer, asked as often as an operator edits a dependency and asks again.

        The port describes a single call and says nothing about the next one, so this is a reading
        rather than a quotation - and the operator settles it: a refused sync is followed by a fix
        and another sync, which is the whole loop this port exists to serve.

        The order below is the one that bites. A refusal first, then a workspace that syncs, on the
        same syncer: an implementation that kept the failure - a resolver session it did not
        reopen, a directory it did not clean, an outcome it cached - answers the second call with
        the first call's verdict, and the operator is then fixing something they already fixed.
        """
        refused = await syncer.sync(refused_workspace)
        synced = await syncer.sync(workspace)
        again = await syncer.sync(refused_workspace)

        assert_carried(refused)
        assert_carried(synced)
        assert_carried(again)
        assert refused.synced is False, "the first sync was refused, which is this test's premise"
        assert synced.synced is True, (
            "a workspace the implementer named as syncing was reported refused when it followed a "
            "sync that was refused. Each call is one answer about one workspace, and a syncer "
            "carrying anything from the last one is answering about the last one"
        )
        assert again.synced is False, (
            "the same refused workspace reported two different verdicts in one process, so what "
            "this port answers depends on how many times it has been asked"
        )
