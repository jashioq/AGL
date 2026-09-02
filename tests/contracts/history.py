"""`HistoryContract` - what every `History` owes, asserted before an implementation of one exists.

Subclass it once per implementation, override the three fixtures, and add nothing:

    class TestTheHistoryIWrote(HistoryContract):
        @pytest.fixture
        def history(self, repository: Path) -> History:
            return TheHistoryIWrote(repository, ...)

        @pytest.fixture
        def provider(self, repository: Path) -> WorkspaceProvider:
            return TheProviderIWrote(repository, ...)   # over that same repository

        @pytest.fixture
        def base(self, repository: Path) -> str:
            return "..."

The real adapter and the fake both run this class, which is the whole mechanism keeping a fake from
drifting into fiction. It is written against the port alone, before either implementation exists,
because a subagent that writes its own tests writes tests that pass - and an adapter ships only
once "the contract suite passes", a sentence worth something only when the suite had no stake in
the outcome.

`HistoryContract` is one class assembled from two modules, and only this name is public. Its own
tests are the members that answer *where* - `default_ref`, `resolve`, `exists` and `contains` -
plus `message`, which answers *what one commit was called*, plus the one refusal they all share.
`_history_changes` holds `changed_files` and `diff`, the pair the port keeps together, and argues
there how far a suite may go in asserting what a patch looks like - which is not far - and why
rename detection is not required.

## Why this suite takes a `WorkspaceProvider`

`History` reads a repository's past and has no member that adds to one, deliberately: seven
questions and nothing that changes anything. So a suite for it has to get its states from
somewhere, and across both of these ports there is exactly one way to record a state -
`Workspace.commit_all`. The alternative is an implementation-supplied fixture handing over a
prepared history, which is a knob whose whole job would be to be shaped by whoever also writes the
implementation, and the suite would then pass because the fixture agreed with it.

This is not a liberty. The port says a commit id from `Workspace.head()` "is also the vocabulary
`History` accepts ... which is honest because one adapter package implements both ports over one
repository", and `adapters/git/` is exactly that. The cost is real and is listed in the gaps below:
a `History` whose repository is provisioned by a broken `WorkspaceProvider` fails this suite for
the other port's reason. Every test that builds a state asserts what it built before asking about
it, so a failure says which side of that line it came from.

## Written against the port, never against one tool

There is **no porcelain anywhere in this suite**. Nothing here parses a status line, matches a
status code, or asserts how a patch spells a hunk - `ChangeKind` exists precisely so that no
consumer sees a program's human-facing output, and a suite that reintroduced it would defeat the
type it is testing. A commit id is an opaque string that came out of `head()` or out of `resolve`.
The one shape ever asserted of one is `resolve`'s, because `run.py`'s `_check_sha` refuses anything
that is not forty or sixty-four characters of lowercase hexadecimal, and the two have to agree.

## What this suite does NOT prove

An honest gap is worth more than a test that looks like coverage, so here is what a green run does
not entitle anybody to believe.

1. **That renames are detected.** `_history_changes` accepts either legal answer to a move and
   argues at length why requiring the heuristic would be inventing a clause the port declines to
   make. Against an implementation that does not detect them, **`ChangeKind.RENAMED` and
   `FileChange.previous_path` are exercised by nothing in this suite.**

2. **That a patch is parseable, or useful.** `diff`'s format is explicitly not this port's, so what
   is asserted is that it is text, that it is not empty when something changed, that it names every
   path `changed_files` named, and that identical states leave nothing to read. A patch in a format
   no reviewer has seen passes all four.

3. **The actual question `contains` is asked.** `Integration._conclude` asks it of a landing - is
   the source's head in what `land` reported - which in life means *merged*. Landing work is
   `integration.py`'s, this suite has no way to land anything, and so the ancestry asserted here is
   the kind that comes from committing in one place - a true case, a false case, a reflexive one
   and a divergence. The shape the engine meets after a successful merge is not built here, and
   that is the whole of the gap, there being exactly one consumer and its question being the merge.

4. **`UpstreamUnavailable`.** Nothing here can make a repository unreachable, and inventing a member
   that could would be inventing a port. `NotFoundError` is the one refusal this suite provokes.

5. **Any ordering from `changed_files`.** The port declines to promise one and so does this suite.

6. **That `default_ref` names what a person would call the default branch.** It is asserted to name
   a state of this repository that resolves, twice the same way. There is no second source for what
   the default *is*: the configuration does not record one and the command line has no view of the
   repository, which is the reason this member exists at all.

7. **That the `History` and the `WorkspaceProvider` are over one repository.** Nothing can check it
   from out here. A pair over two repositories fails these tests as though the implementation were
   broken, which is why the fixtures say it in as many words.

8. **Anything about a second repository.** No method takes one, nothing here asks about one, and the
   port refuses the parameter that would make it possible.

9. **What `message` does to the interior of a multi-line message.** The port promises that trailing
   whitespace is not part of a message and deliberately promises nothing else about how one is
   stored, because git cleans one - trailing whitespace off every line, runs of blank lines
   collapsed to one - and requiring that of every implementation would be this port asking for one
   program's text formatting. So `AWKWARD_MESSAGE` is asserted through a round trip *because* it is
   a shape every implementation holds identically: two lines, one blank line between them, no
   trailing whitespace anywhere. The half the port *does* promise is therefore measured on a
   message of its own, `PADDED_MESSAGE`, which is one line with padding to lose. That test exists
   because the clause was stated in prose on both sides of the port and asserted by nothing: the
   fake's `rstrip` could be deleted with every test in the repository still passing. A message with
   a run of blank lines in it, or with padding on an interior line, is still asserted against
   neither implementation, and AGL writes neither - a `commit=` template renders one line.

## Where the port is silent, and what this suite assumed

**That a state contains itself.** The port asks "is X already in Y", and its one consumer decides
whether a merge it just asked for actually happened. A source that has committed nothing since the
target last took its work is already in it, so the landing is settled rather than re-attempted, and
the only way that happens is `contains(head, head)` answering `True`. That is the port's answer,
argued from the port, and not a fact borrowed from one tool that happens to agree.

**That an empty patch is empty rather than exactly `""`.** Asserted as "nothing to read" after
stripping, because pinning the string would pin whether a trailing newline belongs to a patch with
no hunks in it.

**That `NotFoundError` covers a commit id and not only a ref.** The class docstring says "a ref or a
commit id that names nothing in this repository" for every member, which is read as binding all of
them that refuse - which is six of the seven, `exists` being the one whose answer to that case is
a `False`.
"""

from collections.abc import Iterator
from typing import Final
import pytest
from agl.ports.errors import NotFoundError
from agl.ports.history import History
from agl.ports.workspace import WorkspaceProvider
from ._history_changes import HistoryChangeContract
from ._workspace_files import (
    ALPHA,
    AWKWARD_MESSAGE,
    BETA,
    CHILD,
    LABEL,
    SIBLING,
    body,
    record,
    write,
)

# `run.py`'s `_check_sha`, restated as what `resolve` has to answer with. Forty characters is a
# sha1 object id and sixty-four a sha256 one, and requiring one of the two says "not abbreviated"
# without this suite knowing which hash the repository under it uses. Lowercase because a resume
# compares strings, and an abbreviation because a short id is unique when it is printed and stops
# being unique as the repository grows - so an abbreviated pin comes loose exactly when it matters.
_ID_LENGTHS: Final = frozenset({40, 64})
_ID_CHARACTERS: Final = frozenset("0123456789abcdef")

# Something well-formed that this repository does not have. A name rather than a path expression,
# so that nothing turns on how a particular implementation spells a ref, and one nobody would use.
ABSENT_REF: Final = "agl-contract-suite-names-no-such-thing"

# Forty characters of lowercase hexadecimal that name no state anywhere. Well-formed on purpose:
# an id this suite made up must be refused for not existing, not for being malformed, or the test
# would pass against an implementation that never looks.
ABSENT_ID: Final = "dead" * 10

# One line of ordinary prose with trailing whitespace stuck to it, and the same line without: what
# `message` promises is that the first goes in and the second comes back, out of every
# implementation.
#
# **Content and not only padding**, because `commit_all` refuses a message that is nothing but
# whitespace - so a message made entirely of this padding is a refusal on both implementations
# rather than a round trip, and the clause below would never reach `message` at all.
#
# **One line and not several.** Padding at the end of the *message* is what the port speaks about;
# padding at the end of an interior line is the interior of a multi-line message, which git strips
# and an implementation that stored what it was handed keeps, and which the port declines to require
# of anybody. So it is at the end and nowhere else. Both kinds of trailing whitespace an
# implementation can be wrong about are here at once - a run of spaces and a tab, which is what a
# caller wrote, and a line feed, which is what git adds.
PADDED_MESSAGE: Final = "implement fix \t \n"
TRIMMED_MESSAGE: Final = "implement fix"

class HistoryContract(HistoryChangeContract):
    """The suite. Seven questions about one repository's past, and nothing that changes it.

    Its own tests are where a run starts (`default_ref`), what that resolved to (`resolve`),
    whether a name is held at all (`exists`), the one ancestry question AGL asks (`contains`), what
    one commit was called (`message`), and the refusal six of the seven share. The half it inherits
    is `_history_changes`, named in this module's docstring.

    `pytestmark` is on the class rather than on each method because subclasses inherit it, and
    because `asyncio_mode = "strict"` makes the marker the difference between a test that runs and
    a test pytest quietly skips - which is exactly how a suite passes against nothing at all.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def history(self) -> History | Iterator[History]:
        """The implementation under test, bound to one repository by construction.

        Bound by construction is the port's own design - no method takes a repository - so this
        fixture is the only place the repository is named, exactly as the container names it once
        and hands the same instance to everything.

        The return type is a union so that `mypy --strict` accepts either shape of override:
        return a history, or `yield` one and tear it down after. pytest takes both, and an
        override narrowing a plain `-> History` to `-> Iterator[History]` would not typecheck. An
        `async def` fixture (`@pytest_asyncio.fixture`) is a third shape no annotation here can
        cover; if an implementation needs one, a `# type: ignore[override]` on it is the honest
        escape and costs this suite nothing.
        """
        raise NotImplementedError(
            "the History contract suite has no implementation to run against: subclass "
            "HistoryContract and override the `history` fixture to hand back the History under test"
        )

    @pytest.fixture
    def provider(self) -> WorkspaceProvider | Iterator[WorkspaceProvider]:
        """A provider **over the same repository**, because that is how this suite makes a past.

        `History` reads and never writes, so every state these tests ask about has to be recorded
        through `Workspace.commit_all` - the only member across both ports that adds to a
        repository's past. This module's docstring argues why that is better than a fixture handing
        over a prepared history, and states its cost.

        The same repository as `history`, which nothing here can check: make both fixtures depend
        on whichever one builds it. A pair over two repositories fails these tests as though the
        implementation were broken.

        Function-scoped, like every fixture in this package. Each test records states under the
        same label, so a provider carried between tests would hand the second one the first one's
        line of work.
        """
        raise NotImplementedError(
            "the History contract suite has no way to record a state to ask about: subclass "
            "HistoryContract and override the `provider` fixture with a WorkspaceProvider over "
            "the same repository the History under test reads"
        )

    @pytest.fixture
    def base(self) -> str:
        """A state of that repository for the workspaces this suite records into to be cut from.

        The same value `WorkspaceContract` asks for and for the same reason: `open` takes one, and
        a provider is addressed by name rather than by anything a caller computed, so nothing here
        can ask it what is in the repository it is over.

        Deliberately not derived from `default_ref()`. That member is under test in this very
        suite, and a suite that built every one of its states on top of one of its own answers
        would report a single broken member as every test failing at once.
        """
        raise NotImplementedError(
            "the History contract suite has nothing to cut a workspace from: subclass "
            "HistoryContract and override the `base` fixture with a ref or commit id that exists "
            "in the repository under test"
        )

    async def test_default_ref_names_a_state_of_this_repository_and_says_the_same_thing_twice(
        self, history: History
    ) -> None:
        """Where a run starts from when the user names none - `--from`, defaulting to this.

        It exists because nothing else in AGL can answer it: a project's settings hold a
        repository, a trees root and a build command, none of which implies a starting point, and
        the command line has no view of the repository at all. So the repository is asked.

        A ref *expression*, which is why nothing here holds it to `ids.py`'s rules: what comes back
        may well have a `/` in it, and every type in `ids.py` refuses one, being single path
        segments. What is asserted is that it is a name this repository can act on - `resolve`
        takes it and answers - and that asking twice does not move, since a run resolves this once
        and pins the answer for its whole life.
        """
        ref = await history.default_ref()

        assert isinstance(ref, str) and ref, (
            f"default_ref answered {ref!r}. It is what `agl run` starts from when the user passes "
            f"no --from, and it goes into the run's record as `base_ref`, the name a run says "
            f"it started from"
        )
        assert await history.default_ref() == ref, (
            "default_ref answered differently twice in a row. A run asks once, pins what it "
            "resolved to, and lives on that pin for hours"
        )
        resolved = await history.resolve(ref)
        assert resolved, (
            f"the default ref {ref!r} does not resolve to anything in the repository that named "
            f"it. Every run starts by resolving this, so a default nothing can resolve is a "
            f"repository no run can start in"
        )

    async def test_resolve_answers_with_a_full_unabbreviated_commit_id(
        self, history: History
    ) -> None:
        """What pins `RunSpec.base_sha`, and the one place a commit id's shape is constrained.

        `run.py`'s `_check_sha` refuses anything that is not forty characters of lowercase
        hexadecimal, or sixty-four, and this is where the value it checks comes from - so the two
        have to agree, and this test is what makes them. The reason is `_check_sha`'s: a shortened
        id is unique when it is printed and stops being unique as the repository grows, so an
        abbreviated pin comes loose exactly when a project gets big enough for the pin to matter.

        The cost is worth restating because it is the one demand these ports make of a second
        implementation that is not purely structural: whatever identifies a state has to be
        spellable as hexadecimal of one of those two lengths. An implementation built on content
        hashes has that already; one built on ascending revision numbers has to hash rather than
        count, and this is the test that tells it so.

        Nothing here resolves a resolved id back through this member. Whether an id is itself a ref
        expression is a thing the port does not say, and a suite that assumed it would be refusing
        an implementation for keeping its names and its ids in two namespaces.
        """
        resolved = await history.resolve(await history.default_ref())

        assert len(resolved) in _ID_LENGTHS, (
            f"resolve answered with {resolved!r}, which is {len(resolved)} characters. A resolved "
            f"id is a full object name - forty characters or sixty-four - because `RunSpec` "
            f"refuses an abbreviation: it is unique when it is printed and stops being unique as "
            f"the repository grows, so it pins nothing exactly when the pin starts to matter"
        )
        assert _ID_CHARACTERS.issuperset(resolved), (
            f"resolve answered with {resolved!r}, which is not lowercase hexadecimal. A resume "
            f"compares this string against the one it recorded, so a spelling that varies is a "
            f"pin that comes loose between two invocations of the same run"
        )
        assert await history.resolve(await history.default_ref()) == resolved, (
            "resolving one ref twice in a row gave two different ids, and a run records the first "
            "answer and compares every later one against it"
        )

    async def test_exists_answers_for_exactly_the_refs_resolve_answers_for(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """The port defines this member against `resolve`, so that is what is asserted.

        "`True` for exactly the refs `resolve` answers for, and `False` for exactly the refs
        `resolve` refuses" is the clause, and it is written that way because the two are one
        question asked for two different reasons: `api.run` needs to know whether the deliverable
        branch is already there, and `NotFoundError` is not an answer it may catch. An
        implementation whose two members disagreed would refuse a run over a name nothing could
        ever have been cut from, or start one over a branch that is still standing.

        Three refs, and each one is a different way of being present or absent: a branch this suite
        made, a ref expression the repository does not hold, and a well-formed commit id nothing
        recorded. The third is the one an implementation built on a name table gets wrong - a
        recorded id is something `resolve` answers for and is not a name in any listing - so it
        is asserted rather than assumed.

        `is True` and `is False` rather than truthiness, because a `bool` is what the port answers
        with and a truthy string would satisfy everything else here.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        write(workspace, ALPHA, body("something to record"))
        recorded = await record(workspace, "something to record")

        assert await history.exists(workspace.branch) is True, (
            f"exists says this repository holds nothing under {workspace.branch!r}, which is a "
            f"line of work it has just recorded a state onto. This is the answer `api.run` refuses "
            f"a taken deliverable branch on, and a False here is how a run silently attaches to "
            f"somebody else's work"
        )
        assert await history.exists(recorded) is True, (
            "exists says this repository holds nothing under an id it answered with a moment ago. "
            "The port defines this member as `resolve` with the answer thrown away, and `resolve` "
            "takes a recorded id as a name for itself"
        )
        assert await history.exists(ABSENT_REF) is False, (
            f"exists answered True for {ABSENT_REF!r}, which nothing in this repository has ever "
            f"recorded. A member that answers True for everything makes `api.run` refuse every "
            f"label there is"
        )
        assert await history.exists(ABSENT_ID) is False, (
            "exists answered True for a well-formed commit id nothing recorded. It is well-formed "
            "on purpose: an implementation refusing it for its shape rather than for its absence "
            "would pass a test built on a malformed one without ever looking"
        )

    async def test_contains_answers_the_one_ancestry_question_agl_asks(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """Is X already in Y - a true case, a false case, a reflexive one, and a divergence.

        Asked in one place: `Integration._conclude` puts it to a landing the `Integrator` has just
        reported clean - is the source's head in the head that came back - and lands once more if
        the answer is no, then raises `InternalError`. So all four answers below decide between
        "settled" and "that merge did not happen", and an implementation answering a constant either
        never settles a landing or settles one that moved nothing.

        **The reflexive case is the port's answer and not one tool's.** A source that has committed
        nothing since the target last took its work is already inside it, and the landing is done -
        which holds only if a state is already inside itself. That is the reading, argued from the
        consumer the port names.

        The divergence is the state a landing starts from. Two children cut from one base, each with
        work of its own, and neither contains the other: answering `True` there is how a merge that
        never moved anything is recorded as one that did, and the parent's chain advances to a head
        its work is not on. `is True` and `is False` rather than truthiness, because a `bool` is
        what the port answers with and a truthy string would satisfy everything else here.
        """
        child = await provider.open(LABEL, CHILD, base)
        sibling = await provider.open(LABEL, SIBLING, base)
        start = await child.head()
        assert await sibling.head() == start, (
            "two workspaces cut from one base started at different states, so this test has no "
            "common ancestor to ask about"
        )

        write(child, ALPHA, body("the child's own work"))
        first = await record(child, "the child's own work")
        write(sibling, BETA, body("the sibling's own work"))
        second = await record(sibling, "the sibling's own work")
        assert len({start, first, second}) == 3, (
            "two lines of work committing different files reported the same head, so there is no "
            "ancestry here to ask about"
        )

        assert await history.contains(start, first) is True, (
            f"{start!r} is where {first!r} was committed from and contains says it is not part of "
            f"it. This is the question a settled landing has to answer yes"
        )
        assert await history.contains(start, second) is True
        assert await history.contains(first, start) is False, (
            f"contains says the state {first!r} was committed *from* already holds it. Ancestry "
            f"has a direction: an implementation that answers on membership of one repository "
            f"rather than on reachability would settle a landing that moved nothing"
        )
        assert await history.contains(first, second) is False, (
            "two lines of work that diverged from one base contain each other, which is the state "
            "every landing starts from - and answering True there is how a merge that moved "
            "nothing is concluded as one that landed"
        )
        assert await history.contains(second, first) is False
        assert await history.contains(first, first) is True, (
            "a state does not contain itself, so a source with nothing new on it is landed, landed "
            "again and then reported as AGL's own bug. The question is 'is X already in Y', and X "
            "is in X"
        )
        assert await history.contains(start, start) is True

    async def test_message_answers_with_what_the_commit_was_called(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """The other half of `Workspace.commit_all(message)`, and the only member of either port
        that reads one back.

        `commit=` is the workflow author's one step-ending decision, and the message stays the
        *workflow's* domain vocabulary rather than something AGL generates - so this is the one
        such decision a test for a workflow could not previously see. Before `History.message`
        existed, a suite that wanted to assert a commit message either asserted that *some* commit
        happened, which
        is what a missing `commit=` also produces, or reached into a fake's internal vocabulary and
        recomputed the id from the tree and the message it expected.

        **`AWKWARD_MESSAGE` and not a plain sentence**, because the message is the one argument
        neither port may interpret: quotes, an ampersand, a pipe, a semicolon, `$(...)`, a blank
        line and two non-ASCII scripts, all asserted through a round trip rather than only into a
        `commit_all` that swallowed them. `WorkspaceContract` records "that a commit message was
        recorded" as something it cannot see; this is where it becomes visible.

        **Asserted as equality, and the port is what makes that legal.** Trailing whitespace is not
        part of a message - git stores a cleaned message with a final newline, so an implementation
        over it that handed back what it stored would answer one line feed longer than the caller
        passed, and a workflow comparing against its own template would pass on one implementation
        and fail on another. The interior of a multi-line message is not promised and is not
        asserted: `AWKWARD_MESSAGE` has no trailing whitespace on any line and no run of blank
        lines, which is the shape every implementation holds identically and the shape a `commit=`
        template renders.

        A branch name is asked as well as an id, because the port takes a ref expression here
        exactly as `resolve` does, and an implementation that resolved only one of the two would
        make `message(workspace.branch)` a refusal for a line of work that plainly has a tip.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        write(workspace, ALPHA, body("work worth a sentence"))
        recorded = await workspace.commit_all(AWKWARD_MESSAGE)

        assert await history.message(recorded) == AWKWARD_MESSAGE, (
            "the message this commit was recorded under did not come back as it was written. It "
            "is the workflow author's own prose and the one argument neither port may "
            "interpret, so an implementation that escapes, truncates, re-wraps or re-encodes it is "
            "handing back a sentence nobody wrote"
        )
        assert await history.message(workspace.branch) == AWKWARD_MESSAGE, (
            "asking by branch name gave a different answer from asking by id. This member takes a "
            "ref expression exactly as `resolve` does, so a branch answers about the state at its "
            "tip"
        )

    async def test_trailing_whitespace_is_not_part_of_a_message(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """The one rule the port takes off the implementations, asked of each of them.

        The port holds this rather than leaving it to whoever writes an implementation, and says
        why: git cleans a message and stores it with a final newline, so an adapter over git that
        handed back what it stored answers one line feed longer than an implementation that kept
        what it was given - and a workflow comparing `message(head)` against its own `commit=`
        template would pass on one and fail on the other, which is fake-against-adapter drift in
        the form that costs the most. Both implementations keep the rule with one `rstrip`.

        The test above *argues* that clause and this one is what measures it. `AWKWARD_MESSAGE`
        carries no trailing whitespace, so an implementation that dropped the rule answers it
        correctly and the equality above holds anyway; the message here has padding to lose. It has
        both kinds at once, which is what makes one clause enough for two implementations: the
        spaces and the tab are what a caller wrote and only an implementation that stores what it
        was handed still has them, and the line feed is what git adds and only an implementation
        over git ever sees. Each of the two is answered wrong by exactly one of them.

        **The message is one line, and that is the port's limit rather than this suite's
        convenience.** Padding at the end of an interior line is the interior of a multi-line
        message: git strips it off every line, an implementation that stored what it was given
        keeps it, and the port declines to require either - so nothing here asks. Gap 9 in this
        module's docstring is the same statement from the other side.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        write(workspace, ALPHA, body("work worth a padded sentence"))
        recorded = await workspace.commit_all(PADDED_MESSAGE)

        assert await history.message(recorded) == TRIMMED_MESSAGE, (
            f"a commit recorded under {PADDED_MESSAGE!r} answered with something other than "
            f"{TRIMMED_MESSAGE!r}. Trailing whitespace is not part of a message, which is the "
            f"port's clause and not one implementation's habit: an implementation handing back "
            f"what it stored answers a run of spaces or a line feed longer than the caller wrote, "
            f"and a workflow comparing this against its own `commit=` template then gets equality "
            f"on one implementation and an inequality on the other"
        )

    async def test_two_commits_under_two_messages_are_told_apart(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """One line of work, two states, two sentences - the shape a workflow's own test meets.

        `fix` commits `implement fix` and then `address review findings` onto one branch, and what
        it needs to know is that the second is what the branch is at and the first is what it was
        at. An implementation answering with the branch's *first* message, or with whatever it last
        recorded anywhere, passes a test that only ever asks about one commit.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        write(workspace, ALPHA, body("the first thing"))
        first = await workspace.commit_all("implement fix")
        write(workspace, BETA, body("the second thing"))
        second = await workspace.commit_all("address review findings")
        assert first != second, "two commits of different trees reported one id"

        assert await history.message(first) == "implement fix"
        assert await history.message(second) == "address review findings"
        assert await history.message(workspace.branch) == "address review findings", (
            "the branch answered with a message from a commit it has moved past. This member is "
            "about the state a name resolves to *now*, which for a line of work is its tip"
        )

    async def test_every_method_refuses_a_ref_or_an_id_this_repository_does_not_hold(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """One refusal, from `errors.py`, so that a caller never learns what the thing underneath
        threw.

        The port says it of six of the seven members at once: `NotFoundError` for a ref or a
        commit id that names nothing in this repository. `exists` is the one exception and is
        deliberately not in the list below - answering rather than refusing is the whole of what
        it is for, and the test above is where that is pinned. It matters most for `resolve`, where
        the user typed something well-formed that this repository does not have and exit 3 is the
        answer they get - but the other four take ids too, and an implementation that answered a
        made-up id with an empty diff, with every file in the repository, or with no message at
        all, would be answering a question nobody asked. `changed_files` is the sharp one:
        "nothing differs from a state that does not exist" is a plausible-looking answer and a lie.

        The id below is well-formed on purpose. An implementation refusing it for its shape rather
        than for its absence would pass a test built on a malformed one without ever looking.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        head = await workspace.head()

        with pytest.raises(NotFoundError):
            await history.resolve(ABSENT_REF)
        with pytest.raises(NotFoundError):
            await history.contains(ABSENT_ID, head)
        with pytest.raises(NotFoundError):
            await history.changed_files(ABSENT_ID, head)
        with pytest.raises(NotFoundError):
            await history.diff(head, ABSENT_ID)
        with pytest.raises(NotFoundError):
            await history.message(ABSENT_ID)
