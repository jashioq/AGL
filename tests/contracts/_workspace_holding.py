"""§3.10's run claim: what `hold` excludes, when it lets go, and the half no suite can reach.

Split out of `workspace.py` along the line the port draws itself. The three verbs beside this one
make and unmake isolated places; this one makes no place and unmakes none - it says that this
process is walking this run, for as long as the context is open, so that a `clear` aimed at a run
live in another `agl` refuses instead of taking its checkouts away underneath it. §3.10 wrote that
sentence and had no mechanism behind it: "there is no durable 'this run is live' record, and §3.11
refuses stored status by name ... The fix is a `flock` on the run directory held for the life of
the process: an OS lock that releases on death, the same shape §3.9 already uses, and not stored
status."

## What is asserted here, and it is exactly what the port states

The clause is an **exclusion** and its **end**: a second claim on one label fails while a first is
open, the same claim succeeds once that first is closed, and the failure is `ConflictError` and not
some other refusal an operator would read as a different problem. A third test asserts that two
labels are two claims, because an implementation with one global lock would pass everything above
and serialise every run on the machine against every other - which is not a thing the port says and
is a thing an operator would meet on their second concurrent run.

The release is asserted twice, from the ordinary way out and from an exception, because those are
two different lines in an implementation: a release written after the body rather than in a
`finally` passes the first and locks a crashed run's label out for the life of the process.

## What a green run here does NOT entitle anybody to believe

**That the claim is released when the holder dies.** That is the property §3.10 asks for and the
reason it asks for an OS lock rather than a record: a run killed at the wall socket must not leave
its label claimed forever, and nothing a `finally` does can be relied on for that. It is
unassertable from inside one process - a suite that killed the process would have nothing left to
assert with - so the real adapter carries it and states it in `_trees.py`, and the fake states
plainly that its in-process holder set is the exclusion and not the release-on-death.

**That two processes exclude each other.** `workspace.py` already concedes this for the whole
suite: the fixture hands over one built provider and there is no way to ask for a second over the
same repository, let alone in a second process. What is exercised here is two claims in one
process, which is what a `flock` on two descriptions of one inode refuses and what an in-process
set refuses. A provider that excluded only within one Python object would pass this and fail the
thing §3.10 wants; a provider that excluded across processes is not distinguishable from it here.

**That the claim is non-blocking.** The port says a second claim must refuse rather than wait, and
a suite cannot tell a refusal from a wait that happened to be short. What it can tell is that
control does not enter the second body, which is what these tests assert. A timeout would be the
instrument, and `tests/adapters/test_filesystem_no_lock.py` argues at length why a stopwatch is the
wrong one - a threshold fails on a loaded machine and teaches a reader to re-run the suite.

**That taking a claim leaves nothing behind.** Both implementations make the run's own directory on
the way, which is what lets `api.run` claim a run before it has provisioned anything, and neither
port member reports a directory for this suite to look at.

`WorkspaceContract` in `workspace.py` inherits this class. Implementers subclass that one, never
this one, and the `provider` fixture these tests take is declared there.
"""

import pytest

from agl.ports.errors import ConflictError
from agl.ports.workspace import WorkspaceProvider

from ._workspace_files import LABEL, SECOND_LABEL


class WorkspaceHoldingContract:
    """`hold`: one claim per run, refused while it is held, and let go of however the body ends.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_a_second_claim_on_one_run_is_refused_while_the_first_is_open(
        self, provider: WorkspaceProvider
    ) -> None:
        """The exclusion itself, which is the whole of what §3.10's sentence needs.

        `ConflictError` and not merely "something raised": the class is what `cli/exit_codes.py`
        turns into exit 4, and §3.10's two neighbouring refusals - a label that already has a
        record, a line of work something still has open - are that class already, so a run and a
        `clear` that collide with a live invocation answer alike. An implementation raising
        `UpstreamUnavailable` here would tell an operator their repository was unreachable.

        The inner `async with` is written out rather than hidden behind a helper because what is
        being asserted is that control never reaches its body: the flag below is set inside it, and
        an implementation that let a second claim through would leave the refusal unraised and the
        flag `True`, which fails on its own line rather than on `pytest.raises`.

        Nothing is provisioned first. A claim is what `api.run` takes before it has written or cut
        anything, so a provider that could only be asked about a run it had already made a checkout
        for would be one `api.run` could not call at all.
        """
        entered = False

        async with provider.hold(LABEL):
            with pytest.raises(ConflictError) as caught:
                async with provider.hold(LABEL):
                    entered = True

        assert not entered, (
            "a second claim on a run that was already claimed opened its body. §3.10's sentence is "
            "that a `clear` refuses while a run holds the claim, and a claim two callers can hold "
            "at once excludes nobody from anything"
        )
        assert str(LABEL) in str(caught.value), (
            f"the refusal does not name {str(LABEL)!r}. It is the one thing an operator acts on - "
            f"which run to wait for, or which `agl` to stop - and a message about a path they "
            f"never typed leaves them to work out which of their runs it belongs to"
        )

    async def test_the_claim_is_available_again_once_the_first_holder_has_let_go(
        self, provider: WorkspaceProvider
    ) -> None:
        """The other half, and the half that makes the first one a claim rather than a wall.

        Without this, an implementation that refused every claim after the first - or one that
        never released at all - would pass the exclusion test and make the second `agl run` of any
        session impossible until somebody restarted the machine. It is asserted twice over, so that
        a claim taken and let go of twice is exercised rather than a single reuse.
        """
        async with provider.hold(LABEL):
            pass

        async with provider.hold(LABEL):
            pass

        async with provider.hold(LABEL):
            with pytest.raises(ConflictError):
                async with provider.hold(LABEL):
                    pass

    async def test_the_claim_is_let_go_of_when_the_body_raises(
        self, provider: WorkspaceProvider
    ) -> None:
        """A crashed run must not leave its own label claimed for the life of the process.

        This is a different line in an implementation from the one the test above exercises: a
        release written after the body rather than in a `finally` passes that test and fails this
        one, and the state it leaves is a run nobody can resume and nobody can clear without
        restarting `agl`. It is also the nearest a suite in one process can get to §3.10's real
        requirement, which is that the *kernel* lets go when a process dies - see this module's
        docstring for why that half is a stated gap rather than a test.

        The exception is a plain `RuntimeError` on purpose. An `AglError` would let an
        implementation pass by special-casing AGL's own hierarchy, and what is being asserted is
        that the claim ends however the body does.
        """
        with pytest.raises(RuntimeError, match="the run died holding its claim"):
            async with provider.hold(LABEL):
                raise RuntimeError("the run died holding its claim")

        async with provider.hold(LABEL):
            pass

    async def test_two_runs_are_two_claims(self, provider: WorkspaceProvider) -> None:
        """One claim per run, and not one per machine.

        §3.9's whole requirement is "several workflows - or several instances of one - running
        against a repo simultaneously", and an implementation that took one global lock would
        satisfy every assertion above while making the second concurrent run wait for the first to
        finish. The claim is addressed by `RunLabel` because a run is what is being claimed.

        Both are held at once and each is asserted to still refuse a second claim of its own, so
        that this cannot pass against an implementation whose claims are per-label and also
        entirely absent.
        """
        async with provider.hold(LABEL), provider.hold(SECOND_LABEL):
            with pytest.raises(ConflictError):
                async with provider.hold(LABEL):
                    pass
            with pytest.raises(ConflictError):
                async with provider.hold(SECOND_LABEL):
                    pass
