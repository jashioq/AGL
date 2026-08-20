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
drifting into fiction (§1.9). It is written here, at stage 3, before either exists, because a
subagent that writes its own tests writes tests that pass - and stage 5 ends with "the contract
suite passes", a sentence worth something only when the suite had no stake in the outcome.

`HistoryContract` is one class assembled from two modules, and only this name is public. Its own
tests are the three members that answer *where*: `default_ref`, `resolve` and `contains`, plus the
one refusal all five share. `_history_changes` holds `changed_files` and `diff`, the pair the port
keeps together, and argues there how far a suite may go in asserting what a patch looks like -
which is not far - and why rename detection is not required.

## Why this suite takes a `WorkspaceProvider`

`History` reads a repository's past and has no member that adds to one, deliberately: five questions
and nothing that changes anything. So a suite for it has to get its states from somewhere, and
across both of these ports there is exactly one way to record a state - `Workspace.commit_all`. The
alternative is an implementation-supplied fixture handing over a prepared history, which is a knob
whose whole job would be to be shaped by whoever also writes the implementation, and stage 5 would
end with a suite that passed because the fixture agreed with it.

This is not a liberty. The port says a commit id from `Workspace.head()` "is also the vocabulary
`History` accepts ... which is honest because one adapter package implements both ports over one
repository", and stage 5 builds exactly that. The cost is real and is listed in the gaps below: a
`History` whose repository is provisioned by a broken `WorkspaceProvider` fails this suite for the
other port's reason. Every test that builds a state asserts what it built before asking about it,
so a failure says which side of that line it came from.

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

3. **`clear`'s actual question.** §3.10 deletes a run's line of work only if it is already contained
   in the base ref, which in life means *merged*. Landing work is `integration.py`'s, this suite has
   no way to land anything, and so the ancestry asserted here is the kind that comes from committing
   in one place - a true case, a false case, a reflexive one and a divergence. The shape `clear`
   meets after a successful merge is not built here.

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

## Where the port is silent, and what this suite assumed

**That a state contains itself.** The port asks "is X already in Y", and its one consumer decides
between tidying up and destroying a run. A run whose workflow committed nothing sits exactly at its
base: there is nothing to lose and nothing to keep, so `clear` must tidy it, and the only way that
happens is `contains(head, head)` answering `True`. That is the port's answer, argued from the port,
and not a fact borrowed from one tool that happens to agree.

**That an empty patch is empty rather than exactly `""`.** Asserted as "nothing to read" after
stripping, because pinning the string would pin whether a trailing newline belongs to a patch with
no hunks in it.

**That `NotFoundError` covers a commit id and not only a ref.** The class docstring says "a ref or a
commit id that names nothing in this repository" for every member, which is read as binding all five
rather than only the one whose own docstring repeats it.
"""

from collections.abc import Iterator
from typing import Final

import pytest

from agl.ports.errors import NotFoundError
from agl.ports.history import History
from agl.ports.workspace import WorkspaceProvider

from ._history_changes import HistoryChangeContract
from ._workspace_files import ALPHA, BETA, CHILD, LABEL, SIBLING, body, record, write

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


class HistoryContract(HistoryChangeContract):
    """The suite. Five questions about one repository's past, and nothing that changes it.

    Its own tests are where a run starts (`default_ref`), what that resolved to (`resolve`), the
    one ancestry question AGL asks (`contains`), and the refusal all five share. The half it
    inherits is `_history_changes`, named in this module's docstring.

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
        """Where a run starts from when the user names none - §3.9's `--from`, defaulting to this.

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
            f"no --from, and it goes into the run's record as `base_ref` for a resume to read"
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

    async def test_contains_answers_the_one_ancestry_question_agl_asks(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """Is X already in Y - a true case, a false case, a reflexive one, and a divergence.

        Asked in one place: `clear` deletes a run's own line of work only if it is already
        contained in the base ref, and otherwise keeps it and says so (§3.10). The costs are
        asymmetric - a retained name is a stale ref, a deleted one is the entire run - so all four
        answers below decide between "tidy up" and "leave it alone", and an implementation that
        answers a constant is one that either never tidies or always destroys.

        **The reflexive case is the port's answer and not one tool's.** A run whose workflow
        committed nothing sits exactly at its base: there is nothing to lose, nothing to keep, and
        `clear` has to tidy it - which happens only if a state is already inside itself. That is
        the reading, argued from the consumer the port names.

        The divergence is the shape `clear` actually meets. Two children cut from one base, each
        with work of its own, and neither contains the other: that is the state a run is in before
        anything is integrated, and answering `True` there is how a `clear` deletes work nobody has
        landed. `is True` and `is False` rather than truthiness, because a `bool` is what the port
        answers with and a truthy string would satisfy everything else here.
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
            f"it. This is `clear`'s question with the answer that lets it tidy up"
        )
        assert await history.contains(start, second) is True
        assert await history.contains(first, start) is False, (
            f"contains says the state {first!r} was committed *from* already holds it. Ancestry "
            f"has a direction: an implementation that answers on membership of one repository "
            f"rather than on reachability would delete a run's work the moment `clear` asked"
        )
        assert await history.contains(first, second) is False, (
            "two lines of work that diverged from one base contain each other, which is the state "
            "every run is in before anything is integrated - and answering True there is how a "
            "`clear` deletes work nobody has landed"
        )
        assert await history.contains(second, first) is False
        assert await history.contains(first, first) is True, (
            "a state does not contain itself, so a run that committed nothing sits at its base "
            "with nothing to lose and `clear` keeps its line of work forever rather than tidying "
            "up. The question is 'is X already in Y', and X is in X"
        )
        assert await history.contains(start, start) is True

    async def test_every_method_refuses_a_ref_or_an_id_this_repository_does_not_hold(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """One refusal, from `errors.py`, so that a caller never learns what the thing underneath
        threw.

        The port says it of all five members at once: `NotFoundError` for a ref or a commit id that
        names nothing in this repository. It matters most for `resolve`, where the user typed
        something well-formed that this repository does not have and exit 3 is the answer they get
        - but the other three take ids too, and an implementation that answered a made-up id with
        an empty diff, or with every file in the repository, would be answering a question nobody
        asked. `changed_files` is the sharp one: "nothing differs from a state that does not exist"
        is a plausible-looking answer and a lie.

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
