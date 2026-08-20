"""`WorkspaceContract` - what every `WorkspaceProvider` and `Workspace` owes, before either exists.

Subclass it once per implementation, override the two fixtures, and add nothing:

    class TestTheProviderIWrote(WorkspaceContract):
        @pytest.fixture
        def provider(self, repository: Path) -> WorkspaceProvider:
            return TheProviderIWrote(repository, ...)

        @pytest.fixture
        def base(self, repository: Path) -> str:
            return "..."          # a state of that repository to cut from

The real adapter and the fake both run this class, which is the whole mechanism keeping a fake from
drifting into fiction (§1.9). It is written here, at stage 3, before either exists, because a
subagent that writes its own tests writes tests that pass - and stage 5 ends with "the contract
suite passes", a sentence worth something only when the suite had no stake in the outcome.

`WorkspaceContract` is one class assembled from three modules, and only this name is public. Its own
tests are `open` - provisioning, reopening, and the two addresses a run has. The halves it inherits
follow seams the ports draw themselves: `_workspace_steps` is `Workspace`, "one isolated checkout,
already provisioned: where it is, what it is called, and the three things a step does to it", and
`_workspace_teardown` is the two verbs that unmake one, which `clear` needs apart (§3.10).
`_workspace_files` under both holds the names and the files every test is built from, and argues
there why a suite for this port writes into a directory when the store suite refuses to.

## Written against the port, never against one tool

The audience is an implementation nobody has written yet, and the port names two it must not shut
out: a snapshot or overlay filesystem, where a line of work is a chain of snapshots and an isolated
place is a mount, and a service that hands out isolated checkouts on request. So there is **no
porcelain anywhere in this suite**. Nothing here runs a command, parses a status line, reads a
program's human-facing output, or knows what a line of work is made of. A commit id is an opaque
string that came out of `head()` and goes back into `restore()`; a branch is an opaque string that
is compared to other branches and to nothing else.

The one thing this suite does assume is the one thing the port states: `Workspace.path` is a `Path`,
because a workspace genuinely is a directory that an agent runs in. Every file below is written and
read through that, and `_workspace_files` says so at more length.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe. Every one of these is a limit of what the port's own surface can be
made to reveal, not a test somebody forgot.

1. **That `open` ever raises `ConflictError`.** The clause is real - §3.10 has `run` refuse an
   existing label rather than adopt it, because adopting it is how a typo'd label silently continues
   somebody else's work - and **this suite cannot provoke the state it names**. It needs a line of
   work under this name that is *not* this workspace's, and the only thing making lines of work here
   is the provider under test, under a label and namespace for which `open` is required to hand back
   what is already there. Reaching the state would mean either a second provider over the same
   repository, which the fixtures do not offer, or writing a line of work directly, which means
   knowing what one is made of - the exact knowledge this suite must not have. An implementation
   that never raises `ConflictError` passes this suite. Refusing a taken label is asserted where the
   framework actually does it, at stage 10, whose acceptance criterion is a second `agl run` on one
   label exiting 4.

2. **Anything about two processes.** Two `agl` invocations sharing one repository are what §3.9's
   cross-process `flock` on the worktree registry exists for, and this suite drives one provider
   object in one process. It cannot start a second, because the fixture hands over an already-built
   provider and there is no way to ask it for another over the same repository.

3. **Anything about two things happening at once.** The port states no concurrency clause, so
   nothing here starts two `open` calls together. A provider that serialises every operation behind
   one global lock and a provider with no lock at all are the same observation from out here, and a
   suite asserting a difference would be asserting a clause nobody wrote down.

4. **That `remove` freed anything.** "Take the isolated place back" is asserted by what a reopen
   afterwards holds - the committed work, and none of the uncommitted work. A provider that merely
   forgot the checkout and left it on the disk satisfies that. Nothing here measures disk, and the
   port hands back no size to measure.

5. **What an existing `Workspace` object does after its place has been removed.** The port says
   nothing about it, so nothing here touches one afterwards.

6. **That a commit message was recorded.** Neither port reads a message back - `History` has no
   member for one, deliberately - so what is asserted is that an awkward message is *taken*, never
   that it was stored or that it is what a person later reads.

7. **That a workspace is isolated from the user's own checkout.** §3.9's "AGL never touches the
   user's working directory" is a promise about a directory this suite has no handle on. Isolation
   is asserted between the checkouts the suite provisioned, which is the half it can see.

8. **That `restore` is atomic, or what one racing a write does.** The port says nothing about that
   ordering and nothing here provokes it.

## Where the port is silent, and what this suite assumed

Three readings had to be settled to write a test at all, and each is argued at the test that depends
on it.

**That an `open` after a `remove` re-attaches to the surviving line of work rather than cutting a
new one from `base`.** The port says `base` is consulted "only when provisioning", and does not say
which of the two a post-`remove` `open` is. The reading is forced by the other two sentences:
`remove` promises the line of work survives, and `discard` is the verb that deletes it - so an
`open` that went back to `base` would make `remove` destructive in the one way the port denies,
and would leave the two verbs indistinguishable from outside.

**That reopening after a `remove` does not carry the previous checkout's uncommitted work.** "Take
the isolated place back" is what makes that true, and it is the only thing separating `remove` from
a no-op through this interface.

**That two workspaces of one run are separate places.** The port's sentence is that work in one is
"invisible to every other checkout until somebody lands it"; the test reads that as being about
contents rather than about timing, which is the half a suite in one process can see.
"""

from collections.abc import Iterator

import pytest

from agl.ports.errors import InputError
from agl.ports.ids import Namespace
from agl.ports.workspace import WorkspaceProvider

from ._workspace_files import (
    ALPHA,
    BETA,
    CHILD,
    LABEL,
    SCRATCH,
    SIBLING,
    TRACKED,
    assert_absent,
    body,
    read,
    record,
    write,
)
from ._workspace_steps import WorkspaceStepContract
from ._workspace_teardown import WorkspaceTeardownContract

# The run's own worktree directory in the trees layout (§3.9), spelled here because the test below
# asserts that no `Namespace` can spell it. That is what makes `namespace=None` a name rather than
# an encoding: `ids.py` refuses this word at construction, in every spelling, so a caller cannot
# build the value that would otherwise be the obvious way to address the run's own workspace.
_RESERVED_BASE_NAME = "_base"


class WorkspaceContract(WorkspaceStepContract, WorkspaceTeardownContract):
    """The suite. Everything these two ports promise, and nothing an implementation gets to pick.

    Its own tests are `open`: that reopening hands back the same place with whatever the last
    attempt left in it, that `base` is honoured once and ignored afterwards, that `None` addresses
    the run's own workspace and nothing else can, and that two places of one run are two places.
    The two halves it inherits are named in this module's docstring.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and
    a test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def provider(self) -> WorkspaceProvider | Iterator[WorkspaceProvider]:
        """The implementation under test, over a repository nothing has provisioned into yet.

        Every test opens under the same label, so a provider carried between tests would answer
        the second test with the first one's leavings and the reopen clause would assert itself.
        Hand over a provider over a fresh repository per test - the same demand `StoreContract`
        makes of a store, and the reason this fixture is function-scoped like every other in this
        package. Tearing that repository down belongs to whoever built it: `yield` here, or make
        this fixture depend on one that does.

        Two knobs on this suite, and the second one only because a provider cannot be asked what
        it is over. Everything else - the label, the namespaces, the files, the messages - this
        suite builds out of the ports' own types, so pointing it at an implementation is two
        visible overrides and there is no third place to point it somewhere else by accident.

        The return type is a union so that `mypy --strict` accepts either shape of override:
        return a provider, or `yield` one and tear it down after. pytest takes both, and an
        override narrowing a plain `-> WorkspaceProvider` to `-> Iterator[WorkspaceProvider]`
        would not typecheck. An `async def` fixture (`@pytest_asyncio.fixture`) is a third shape
        no annotation here can cover; if an implementation needs one, a `# type: ignore[override]`
        on it is the honest escape and costs this suite nothing.
        """
        raise NotImplementedError(
            "the Workspace contract suite has no implementation to run against: subclass "
            "WorkspaceContract and override the `provider` fixture to hand back the "
            "WorkspaceProvider under test"
        )

    @pytest.fixture
    def base(self) -> str:
        """A state of that same repository for a workspace to be cut from.

        It cannot be derived and it cannot be guessed. `open` takes one and this suite has no way
        to ask a provider what repository it is over, let alone what is in it - and the port
        deliberately keeps it that way, a provider being addressed by name and never by anything
        the caller computed. So the fixture that builds the repository is what says this, and
        making this fixture depend on that one is how the two stay the same repository.

        A ref expression or a resolved commit id: the port takes both, because a run's own place is
        cut from the pinned `RunSpec.base_sha` while a child is cut from the run's branch by name,
        and forcing one form would make one of those two callers resolve on the port's behalf.
        Nothing here cares which was supplied.
        """
        raise NotImplementedError(
            "the Workspace contract suite has nothing to cut a workspace from: subclass "
            "WorkspaceContract and override the `base` fixture with a ref or commit id that "
            "exists in the repository the provider under test is over"
        )

    async def test_reopening_a_namespace_hands_back_the_same_place_uncommitted_work_and_all(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """The clause replay is built on, and the one a careless implementation passes weakly.

        A resume walks the same workflow again and asks for the same workspaces; if the second ask
        were an error, every step would need an existence check in front of it, and the check and
        the provisioning would race with the run's own concurrency. So opening twice must not
        raise - but "does not raise" is the weak half of the clause and the half that is easy. The
        port's sentence is that **an existing workspace is returned exactly as it stands, with
        whatever the previous attempt left in it**, and §3.6's replay is what then decides whether
        to keep that state or `restore` past it.

        That is why the assertions below are about a file nobody committed. An implementation that
        quietly re-provisions a clean checkout passes "opening twice does not raise", passes a
        comparison of paths, and destroys a resume: replay would find no entry for the crashed
        step, reset to the last recorded head - and everything the crashed attempt had done would
        already be gone, along with any work a person went and looked at.

        Object identity is deliberately not asserted. The port says "hand back the one already
        there", which is a claim about the place and the line of work, not about a Python object;
        a provider that constructs a fresh `Workspace` over the same checkout is doing exactly
        what was asked.
        """
        first = await provider.open(LABEL, CHILD, base)
        assert_absent(first, TRACKED, SCRATCH)
        write(first, TRACKED, body("committed by the first attempt"))
        committed = await record(first, "the first attempt")
        write(first, TRACKED, body("edited by the attempt that then crashed"))
        write(first, SCRATCH, body("left behind by the attempt that then crashed"))

        again = await provider.open(LABEL, CHILD, base)

        reopened = await again.head()
        assert reopened == committed, (
            f"opening an existing workspace a second time handed back one at {reopened!r} rather "
            f"than at {committed!r}, where the first attempt left it. Reopening is what makes "
            f"replay possible, and a reopen that re-provisions is a resume that starts over"
        )
        assert read(again, TRACKED) == body("edited by the attempt that then crashed"), (
            "an edit the previous attempt had not committed is gone from the reopened workspace. "
            "An existing workspace is returned exactly as it stands - §3.6's replay is what "
            "decides whether to keep that state or restore past it, and it cannot decide about "
            "something already thrown away"
        )
        assert read(again, SCRATCH) == body("left behind by the attempt that then crashed"), (
            f"{SCRATCH} was created by the previous attempt and never committed, and reopening "
            f"lost it. This is the assertion that separates reopening from re-provisioning: a "
            f"clean checkout has the committed work and none of the leavings, and passes every "
            f"weaker version of this test"
        )
        assert again.path == first.path, "the same place, so an agent already in it is still in it"
        assert again.branch == first.branch, "and the same line of work, under the same name"

    async def test_base_is_honoured_when_provisioning_and_ignored_on_every_reopen(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """Said plainly by the port rather than left as a parameter that looks honoured and is not.

        Checking it on reopen would be the dishonest option, and the port gives the case: a child's
        base is the run's own line of work, which advances with every integration, so a workspace
        cut an hour ago was correctly cut from an earlier state of the very ref being passed now.
        An implementation that compared would refuse healthy replays; one that *re-cut* would throw
        away the child's work in the middle of a resume.

        The reopen below is handed a base that would be visible if it were honoured - the run's own
        head, which carries a file the child has never seen - so an implementation that consulted
        it cannot pass by coincidence. A resolved commit id is a legal `base`, which is why this
        test can pass one at all.
        """
        child = await provider.open(LABEL, CHILD, base)
        assert_absent(child, TRACKED, ALPHA)
        cut_from_base = await child.head()
        write(child, TRACKED, body("the child's own work"))
        childs_head = await record(child, "the child's own work")

        run = await provider.open(LABEL, None, base)
        write(run, ALPHA, body("the run's own work"))
        runs_head = await record(run, "the run's own work")
        assert len({cut_from_base, childs_head, runs_head}) == 3, (
            "two lines of work committing different files reported the same head, so this test "
            "has nothing to tell apart"
        )

        again = await provider.open(LABEL, CHILD, runs_head)

        reopened = await again.head()
        assert reopened == childs_head, (
            f"reopening a workspace with a different base handed back one at {reopened!r} rather "
            f"than at {childs_head!r}, where its own work sits. `base` is consulted only when "
            f"provisioning: a child's base advances with every integration, so an implementation "
            f"that re-cuts on reopen loses that child's work on any resume after the first merge"
        )
        assert read(again, TRACKED) == body("the child's own work"), "and its work is still there"
        assert read(again, ALPHA) is None, (
            "the reopened workspace carries a file that exists only in the base it was handed, so "
            "that base was honoured on a reopen - the one place the port says it is not"
        )

    async def test_the_run_s_own_workspace_is_addressed_by_none_and_by_nothing_else(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """§3.9's `_base`, and `None` is the only way to name it.

        The first assertion is about a pure type rather than about the implementation, and it is
        here because it is what makes `None` a name instead of an arbitrary encoding: §3.3 reserves
        that word for the run's own checkout, `ids.py` refuses it at construction in every
        spelling, and so there is deliberately no `Namespace` value a caller could pass instead.
        A reader who wonders why this parameter is `Namespace | None` gets the answer in one line,
        and an implementation that grew a magic namespace of its own would be reachable by nobody.

        Everything after it is that the two addresses are two: different places, different lines of
        work, and work in one invisible in the other. `None` reopens like any other address, which
        is asserted here rather than repeated in the reopen test above.
        """
        with pytest.raises(InputError):
            Namespace(_RESERVED_BASE_NAME)

        run = await provider.open(LABEL, None, base)
        child = await provider.open(LABEL, CHILD, base)
        assert_absent(run, ALPHA)

        assert run.path != child.path, (
            "the run's own workspace and a child of it are at one path. They are two checkouts of "
            "one repository, and §3.9 is explicit that a checkout inside another checkout's "
            "working tree shows up in that one's changes"
        )
        assert run.branch != child.branch, (
            "the run's own workspace and a child of it are on one line of work, so a child's "
            "commits would land on the deliverable branch without anything integrating them"
        )

        write(run, ALPHA, body("the run's own"))
        assert read(child, ALPHA) is None, "a child cannot see the run's uncommitted work"

        again = await provider.open(LABEL, None, base)
        assert again.path == run.path, "and `None` reopens the same place, like any other address"
        assert read(again, ALPHA) == body("the run's own")

    async def test_two_workspaces_of_one_run_are_separate_places(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """The whole point of the port: two agents editing one file at the same time is an
        ordinary afternoon rather than a race.

        Work done in an isolated place is invisible to every other checkout until somebody lands
        it - which is `integration.py`'s job and not this port's - so a step that leaves a scratch
        file behind cannot contaminate the next one. Both halves are asserted, in both directions,
        because an implementation that shared one working tree between two namespaces would pass
        any test that only ever looked at one of them.

        Two children cut from one base start at one head, which is asserted as the precondition it
        is: without it, "the sibling did not see this commit" would be satisfied by two workspaces
        that were never in the same place to begin with.
        """
        child = await provider.open(LABEL, CHILD, base)
        sibling = await provider.open(LABEL, SIBLING, base)
        assert_absent(child, ALPHA, BETA)

        assert child.path != sibling.path, "two lines of work, two places"
        assert child.branch != sibling.branch, "and two names for them"
        start = await child.head()
        assert await sibling.head() == start, (
            "two workspaces cut from one base started at two different states, so nothing below "
            "would be evidence about isolation"
        )

        write(child, ALPHA, body("the child's"))
        landed = await record(child, "the child's own work")
        write(sibling, BETA, body("the sibling's"))
        await record(sibling, "the sibling's own work")

        assert read(sibling, ALPHA) is None, "the sibling never saw the child's file"
        assert read(child, BETA) is None, "nor the child the sibling's"
        assert await sibling.head() != landed, (
            "a commit in one workspace moved the head of the other, so the two share a line of "
            "work and neither one is isolated from anything"
        )
        assert read(child, ALPHA) == body("the child's"), "and each still holds its own work"
        assert read(sibling, BETA) == body("the sibling's")
