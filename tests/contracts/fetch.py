"""`FetchContract` - what every `Fetcher` owes, asserted against the port and against nothing else.

Subclass it once per implementation, override the three fixtures, and add nothing:

    class TestTheFetcherIWrote(FetchContract):
        @pytest.fixture
        def fetcher(self, served: RepositoryAtRef) -> Fetcher:
            return TheFetcherIWrote(...)   # built however it has to be to serve `served`

        @pytest.fixture
        def served(self) -> RepositoryAtRef:
            return ...   # a repository at a ref this fetcher serves, holding TREE at COMMIT

        @pytest.fixture
        def missing(self) -> RepositoryAtRef:
            return ...   # one this fetcher answers as not there at all

The real adapter and the fake both run this class, which is the whole mechanism keeping a fake
from drifting into fiction: a fake answering differently from the adapter fails a suite the adapter
passes, and the drift surfaces here rather than in whichever `agl get` test believed the fake.

## Written against the port, so **this suite must not assume a far side**

Nothing here names a host, a service, a protocol, an archive format or a status code. The port says
a fetcher downloads one repository at one ref and takes directories out of it, and says nothing
about how - so an implementation reading a local mirror, a cache, or a service nobody has built yet
owes exactly what is asserted below. **What the repository holds is data this suite owns**: `TREE`
and `COMMIT` are the repository at its ref, and each implementation arranges to serve them however
its far side is arranged - the fake is scripted with them, and the real adapter's test module
builds the archive its far side would send. No test here writes a file, lists a directory or takes
a `Path`.

## What this suite does NOT prove

1. **That one download serves every workflow asked of it.** It is the port's reason for taking a
   `Fetch` rather than a workflow, and the answers are identical whether an implementation
   downloaded once or once per workflow. The real adapter's own tests count the requests its far
   side was handed.

2. **Any refusal but "not there".** A far side that is throttling, a network that is down, an
   archive cut short or one no honest far side would send are each an answer the port promises is
   handed back rather than raised - and provoking one means breaking the far side itself, which
   the port offers no member to do. They are asserted where the far side is in scope, beside the
   adapter.

3. **That a downloaded file is safe to place.** The port's own type refuses a path that would climb
   out of the workflow's directory, and `tests/ports/test_fetch.py` holds that; what an
   implementation refuses beyond it - links, names a case-insensitive volume would merge - is a
   policy of that implementation's, asserted with it.

4. **Anything about two fetches at once.** Nothing here starts two, and the port promises nothing
   about what happens if somebody does.

## Where the port is silent, and what this suite assumed

**That a fetcher answers more than once.** An operator whose first `agl get` named a repository
that does not exist types the right one next, on the same process's fetcher in any caller that
keeps one - so the test that pins it asks for the refusal first and the repository that is there
second, which is the order a refusal that stuck would bite in.

**Nothing about the case of an owner's or a repository's name.** A far side may answer every
spelling or only one, and the port does not say; every fetch here spells `served` exactly as its
fixture did.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final
import pytest
from agl.ports.errors import NotFoundError
from agl.ports.fetch import FetchAnswer, FetchedFile, FetchedWorkflow, Fetcher, RefusedWorkflow
from agl.ports.get_request import Fetch, GetRequest, RepositoryAtRef

# The commit `served` is at. Not a real one anywhere, which is what makes it this suite's own: an
# implementation that answered with some other commit it happened to know could not match it.
COMMIT: Final = "5eed5eed0f1e2d3c4b5a69788796a5b4c3d2e1f0"

# The whole of the repository `served` names, path from its root to file. Three workflow directories
# under one parent, one of them with a name the next one begins; one at the root; a file where a
# directory might be asked for; and, inside `review`, a nested file, an executable, an empty file,
# every byte value, and a name outside ASCII - each a way for an implementation to hand back
# something other than what the repository holds.
TREE: Final[Mapping[str, FetchedFile]] = MappingProxyType(
    {
        "README.md": FetchedFile(b"# a repository holding workflows\n"),
        "workflows/mine/review/pyproject.toml": FetchedFile(b'[project]\nname = "review"\n'),
        "workflows/mine/review/__init__.py": FetchedFile(b"async def review(run):\n    ...\n"),
        "workflows/mine/review/prompts/reviewer.md": FetchedFile(b"Read the diff first.\n"),
        "workflows/mine/review/prompts/café.md": FetchedFile("un café\n".encode()),
        "workflows/mine/review/bin/lint": FetchedFile(b"#!/bin/sh\nexit 0\n", executable=True),
        "workflows/mine/review/empty": FetchedFile(b""),
        "workflows/mine/review/every-byte": FetchedFile(bytes(range(256))),
        "workflows/mine/reviewer/__init__.py": FetchedFile(b"# begins with the other's name\n"),
        "workflows/mine/implement/__init__.py": FetchedFile(b"async def implement(run): ...\n"),
        "workflows/mine/notes": FetchedFile(b"a file, where a directory might be asked for\n"),
        "at_the_root/__init__.py": FetchedFile(b"# a workflow at the repository's root\n"),
    }
)

def held_below(directory: str) -> dict[str, FetchedFile]:
    """What `TREE` holds below one directory, keyed the way the port keys a workflow's files."""
    within = f"{directory}/"
    return {
        path.removeprefix(within): held for path, held in TREE.items() if path.startswith(within)
    }

def fetch_of(repository: RepositoryAtRef, *specs: str) -> Fetch:
    """The one fetch that arguments naming directories of `repository` add up to."""
    (fetch,) = GetRequest.parsed([f"{repository}/{spec}" for spec in specs]).fetches
    return fetch

def fetched(answer: FetchAnswer) -> FetchedWorkflow:
    """`answer`, which the test needs to have been a workflow's files and not a refusal of it."""
    assert isinstance(answer, FetchedWorkflow), (
        f"{answer.workflow} was refused where the repository holds it: {answer!r}"
    )
    return answer

def refused(answer: FetchAnswer) -> RefusedWorkflow:
    """`answer`, which the test needs to have been a refusal and not a workflow's files."""
    assert isinstance(answer, RefusedWorkflow), (
        f"{answer.workflow} came back with files where it should have been refused: {answer!r}"
    )
    return answer

class FetchContract:
    """The suite. One method, two kinds of answer, and the order and the commit they come in.

    `pytestmark` is on the class for `SyncContract`'s reason: `asyncio_mode = "strict"` makes the
    marker the difference between a test that runs and one pytest quietly skips.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def fetcher(self, served: RepositoryAtRef) -> Fetcher:
        """The implementation under test, already able to serve `served`.

        Function-scoped, like every fixture in this package: a fetcher carried between tests would
        let one test's refusal be another's starting state.
        """
        raise NotImplementedError(
            "the Fetcher contract suite has no implementation to run against: subclass "
            "FetchContract and override the `fetcher` fixture to hand back the Fetcher under test"
        )

    @pytest.fixture
    def served(self) -> RepositoryAtRef:
        """A repository at a ref the fetcher serves, holding exactly `TREE` at `COMMIT`."""
        raise NotImplementedError(
            "the Fetcher contract suite has no repository to fetch: subclass FetchContract and "
            "override the `served` fixture with one the Fetcher under test serves, holding TREE at "
            "COMMIT"
        )

    @pytest.fixture
    def missing(self) -> RepositoryAtRef:
        """A repository at a ref the fetcher answers as not there at all."""
        raise NotImplementedError(
            "the Fetcher contract suite has no repository that is not there: subclass "
            "FetchContract and override the `missing` fixture with one the Fetcher under test "
            "answers as not found"
        )

    async def test_every_workflow_asked_for_gets_one_answer_in_the_order_it_was_asked(
        self, fetcher: Fetcher, served: RepositoryAtRef
    ) -> None:
        """One answer per workflow, and each one says which workflow it answers.

        The caller walks the answers beside what it asked for, so an implementation that dropped
        a refused workflow, answered twice, or answered in the order the far side happened to list
        directories would have its caller place one workflow's files under another's name.
        """
        fetch = fetch_of(served, "workflows/mine/implement,review,notes", "at_the_root")

        answers = await fetcher.fetch(fetch)

        assert [answer.workflow for answer in answers] == list(fetch.workflows)

    async def test_a_directory_the_repository_holds_comes_back_as_every_file_below_it_exactly(
        self, fetcher: Fetcher, served: RepositoryAtRef
    ) -> None:
        """Every file, keyed by its path below the directory, its bytes and its mode as they were.

        One comparison over the whole mapping, because every way to get this wrong is a
        difference in it: a nested file keyed by its name alone, an executable handed back as
        not, an empty file dropped, a byte altered on its way through a text codec, a name
        outside ASCII respelled - and the directory's own name left on the front of every key.
        """
        (answer,) = await fetcher.fetch(fetch_of(served, "workflows/mine/review"))

        assert dict(fetched(answer).files) == held_below("workflows/mine/review")

    async def test_every_workflow_from_one_download_carries_the_commit_it_was_taken_from(
        self, fetcher: Fetcher, served: RepositoryAtRef
    ) -> None:
        """The commit, and not the ref: what was got, where the ref is only what was asked for.

        Asked here at the ref `served` names, which for any far side worth using moves - so an
        implementation that echoed the ref, or a commit it resolved some other time, has handed
        back something other than the commit the files came from.
        """
        answers = await fetcher.fetch(fetch_of(served, "workflows/mine/implement,review"))

        assert [fetched(answer).commit for answer in answers] == [COMMIT, COMMIT]

    async def test_a_directory_holds_its_own_files_and_none_of_a_sibling_whose_name_it_begins(
        self, fetcher: Fetcher, served: RepositoryAtRef
    ) -> None:
        """`review` and `reviewer` are two directories, whichever way a prefix is compared.

        Asked for together and apart, because the mistake - matching on the name without the
        separator after it - puts `reviewer`'s files into `review` and leaves `reviewer` right.
        """
        together = await fetcher.fetch(fetch_of(served, "workflows/mine/review,reviewer"))
        (alone,) = await fetcher.fetch(fetch_of(served, "workflows/mine/review"))

        review, reviewer = (dict(fetched(answer).files) for answer in together)
        assert review == held_below("workflows/mine/review") == dict(fetched(alone).files)
        assert reviewer == held_below("workflows/mine/reviewer")

    async def test_a_workflow_at_the_repository_root_needs_no_directory_above_it(
        self, fetcher: Fetcher, served: RepositoryAtRef
    ) -> None:
        """The shortest path a workflow can have, which is where an off-by-one in the path lands."""
        (answer,) = await fetcher.fetch(fetch_of(served, "at_the_root"))

        assert dict(fetched(answer).files) == held_below("at_the_root")

    async def test_a_directory_the_repository_does_not_hold_is_refused_and_spares_the_others(
        self, fetcher: Fetcher, served: RepositoryAtRef
    ) -> None:
        """`NotFoundError`, naming the directory and the repository, and only for that directory.

        The port's own clause, and the reason a refusal is an answer: a comma list with one
        mistyped name in it still yields the rest. The message is held to naming both halves,
        because a person with three workflows from two repositories needs to know which one.
        """
        absent, present = await fetcher.fetch(fetch_of(served, "workflows/mine/absent,review"))

        refusal = refused(absent).refusal
        assert isinstance(refusal, NotFoundError), f"refused with {refusal!r}"
        assert "workflows/mine/absent" in str(refusal) and str(served) in str(refusal)
        assert dict(fetched(present).files) == held_below("workflows/mine/review")

    async def test_a_path_the_repository_holds_as_a_file_is_refused_as_not_a_directory(
        self, fetcher: Fetcher, served: RepositoryAtRef
    ) -> None:
        """A workflow is a directory, so a file at its path is a workflow that is not there."""
        (answer,) = await fetcher.fetch(fetch_of(served, "workflows/mine/notes"))

        refusal = refused(answer).refusal
        assert isinstance(refusal, NotFoundError), f"refused with {refusal!r}"
        assert "workflows/mine/notes" in str(refusal)

    async def test_a_repository_that_is_not_there_refuses_every_workflow_asked_of_it(
        self, fetcher: Fetcher, missing: RepositoryAtRef
    ) -> None:
        """One refusal per workflow, each `NotFoundError` and each naming the repository.

        Answered rather than raised, which is what lets the caller carry on with the next
        repository; and one per workflow, so the caller's summary has a line for each thing the
        operator typed rather than for each download it happened to group them into.
        """
        answers = await fetcher.fetch(fetch_of(missing, "workflows/mine/a,b"))

        assert len(answers) == 2
        for answer in answers:
            refusal = refused(answer).refusal
            assert isinstance(refusal, NotFoundError), f"refused with {refusal!r}"
            assert str(missing) in str(refusal)

    async def test_a_fetcher_answers_every_time_and_a_refusal_does_not_poison_it(
        self, fetcher: Fetcher, served: RepositoryAtRef, missing: RepositoryAtRef
    ) -> None:
        """A refusal first, then a repository that is there, then the refusal again, on one fetcher.

        The order is the one that bites: an implementation that kept the first answer - a
        connection it did not reopen, a cache keyed too loosely - answers the second with it.
        """
        first = await fetcher.fetch(fetch_of(missing, "workflows/mine/review"))
        second = await fetcher.fetch(fetch_of(served, "workflows/mine/review"))
        third = await fetcher.fetch(fetch_of(missing, "workflows/mine/review"))

        assert [type(answer) for answer in (*first, *second, *third)] == [
            RefusedWorkflow,
            FetchedWorkflow,
            RefusedWorkflow,
        ]
