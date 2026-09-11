"""`GitHubFetcher` and `FakeFetcher` against the `Fetcher` contract, and what that suite cannot see.

The first two classes are the port in full: `FetchContract` with its three fixtures overridden and
nothing else touched, once against the real adapter and once against the fake. What follows them is
everything the suite lists as beyond it, asserted here where the far side is in scope - the request
the adapter makes, each answer the far side can give that is not an archive, the network failing,
and a fetch cancelled halfway. `tests/adapters/test_github_archive.py` holds the other half: every
archive an honest far side never sends, and what a workflow may hold.

**The adapter has two far sides.** A download goes to codeload.github.com; which commit a ref names
now is asked of api.github.com's commits endpoint, one request per question, which GitHub counts
against 60 an hour for an address nobody is signed in from. The section on resolving holds that
request - its path, its one `Accept` header and no token - and each answer that endpoint was seen
to give: the sha as the whole body, 422 for a ref with no commit, 404 for a repository that is not
there or not public, and a limit run out.

**No test here reaches either host.** The real adapter is handed the addresses of
`instruments.codeload` and `instruments.github_api`, listeners on 127.0.0.1 that answer what each
test scripted, and `tests/conftest.py` refuses every lookup and connection off this machine for the
whole session - `tests/test_network_guard.py` shows the real adapter at its default addresses
stopped by it. What the stand-ins imitate is only what was observed of the real services, and one
test below reads a body the real codeload sent, byte for byte, which is the check that the
imitation and the original agree.

Named `test_github_fetcher.py` for the module it covers, and unique across `tests/` because pytest's
module names are the bare filenames here - see `tests/conftest.py`.
"""

import asyncio
import base64
import random
import socket
from collections.abc import Iterator
from typing import Final
import pytest
from agl.adapters.github.fake import FAKE_COMMIT, FakeFetcher
from agl.adapters.github.fetcher import GitHubFetcher
from agl.config import container
from agl.ports.errors import AglError, NotFoundError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.fetch import FetchedFile, Fetcher, Resolution, ResolvedRef, UnresolvedRef
from agl.ports.get_request import RepositoryAtRef
from contracts.fetch import COMMIT, TREE, FetchContract, fetch_of, fetched, held_below, refused
from instruments.codeload import Codeload, Scripted, archive, tree
from instruments.github_api import NOT_FOUND, GitHubApi, commits_of, no_commit

_HELLO: Final = RepositoryAtRef("octo", "hello", None)

_NOWHERE: Final = RepositoryAtRef("octo", "nothing-here", None)

_RELEASED: Final = RepositoryAtRef("octo", "hello", "release/1.0")

# An `X-RateLimit-Reset` the real service sent, in epoch seconds, and the moment it names in UTC.
_RESET: Final = "1789107232"
_RESET_AT: Final = "2026-09-11 06:13:52 UTC"

# The whole body codeload.github.com sent for `GET /octocat/Hello-World/tar.gz/HEAD`, saved from a
# real request in September 2026: 255 bytes, `application/x-gzip`, one directory and a README.
_OBSERVED: Final = base64.b64decode(
    "H4sIAAAAAAAAA+3UsW6DMBAGYOY+RfoAUX3gs2HoEClILFmydIxMbdLBiSNKpT5+HLqB0i7QCvX/Bg5hpDs43V3M"
    "5+HoQ2384c0Z69pkeiJSSvUxGsZ4KBMinTKTTCmNz0lyjMcZahn5eO9MG1O2IXTfvffT+fDjFoLT1Ws4ndy5e9aN"
    "JaNELagpqM5INlwUzEY6aaXLhc2dbYjsw1/XDNOpnPdh/RJab9dVudk+zZDjNg9a8/35j/eD+c+04IRnqGXkn8//"
    "qP/7eNmVk+b42v/yfv+Jx/tfUfIrPxH992HV9/8Rix0AAAAAAAAAAAAAAAAAAGCZrsNhWK4AKAAA"
)

_OBSERVED_COMMIT: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

# How long a test polls for something another thread does, and how often. A bound, not a pause.
_PATIENCE: Final = 3.0
_POLL: Final = 0.02

def _codeload_tree() -> dict[str, tuple[bytes, bool]]:
    """`TREE` as the stand-in's archive builder takes it."""
    return {path: (held.content, held.executable) for path, held in TREE.items()}

def _resolved(answer: Resolution) -> ResolvedRef:
    """`answer`, which the test needs to have been a commit and not a refusal."""
    assert isinstance(answer, ResolvedRef), f"refused where a commit was answered: {answer!r}"
    return answer

def _unresolved(answer: Resolution) -> AglError:
    """The refusal `answer` carries, which the test needs it to have been."""
    assert isinstance(answer, UnresolvedRef), f"resolved where it should be refused: {answer!r}"
    return answer.refusal

@pytest.fixture
def codeload() -> Iterator[Codeload]:
    """A fresh stand-in per test, so no test reads another's requests."""
    with Codeload() as stand_in:
        yield stand_in

@pytest.fixture
def api() -> Iterator[GitHubApi]:
    """A fresh stand-in for the commits endpoint per test, for `codeload`'s reason."""
    with GitHubApi() as stand_in:
        yield stand_in

# --- The port, asserted of both -----------------------------------------------------------------

class TestTheGitHubFetcher(FetchContract):
    """The real adapter against the `Fetcher` contract, its far sides stand-ins on 127.0.0.1.

    `served` is the suite's `TREE` at its `COMMIT`, archived the way codeload archives a repository,
    under a top-level directory named for the repository and the ref as it was asked for - and
    answered as `COMMIT` by the commits endpoint, the way that endpoint answers a ref.
    """

    @pytest.fixture
    def fetcher(self, codeload: Codeload, api: GitHubApi, served: RepositoryAtRef) -> Fetcher:
        return GitHubFetcher(codeload.url, api_url=api.url)

    @pytest.fixture
    def served(self, codeload: Codeload, api: GitHubApi) -> RepositoryAtRef:
        body = archive(tree("hello-HEAD", _codeload_tree()), commit=COMMIT)
        codeload.serves(_HELLO.owner, _HELLO.repo, "HEAD", body)
        api.resolves(_HELLO.owner, _HELLO.repo, "HEAD", COMMIT)
        return _HELLO

    @pytest.fixture
    def missing(self) -> RepositoryAtRef:
        return _NOWHERE

class TestTheFakeFetcher(FetchContract):
    """The fake against the same tests, scripted with the suite's own `TREE` and nothing else."""

    @pytest.fixture
    def fetcher(self, served: RepositoryAtRef) -> Fetcher:
        fake = FakeFetcher()
        fake.serves(served, TREE, commit=COMMIT)
        return fake

    @pytest.fixture
    def served(self) -> RepositoryAtRef:
        return _HELLO

    @pytest.fixture
    def missing(self) -> RepositoryAtRef:
        return _NOWHERE

# --- The request --------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_four_workflows_from_one_repository_are_one_request_for_its_archive(
    codeload: Codeload,
) -> None:
    """The port takes a `Fetch` so that one download serves them all, which only the far side sees.

    The contract suite cannot tell one download from four - the answers are identical - so it is
    counted here, on the stand-in's own record of what it was handed.
    """
    body = archive(tree("hello-HEAD", _codeload_tree()), commit=COMMIT)
    codeload.serves("octo", "hello", "HEAD", body)

    await GitHubFetcher(codeload.url).fetch(
        fetch_of(_HELLO, "workflows/mine/implement,review,reviewer", "at_the_root")
    )

    assert [(seen.method, seen.path) for seen in codeload.requests] == [
        ("GET", "/octo/hello/tar.gz/HEAD")
    ]

@pytest.mark.asyncio
async def test_no_ref_asks_for_head_and_a_written_ref_is_asked_for_exactly_as_written(
    codeload: Codeload,
) -> None:
    """`None` is the default branch, which codeload answers to as `HEAD` - observed, not assumed.

    The written ref goes through untouched, which is what makes a tag, a branch and a full sha all
    work: the far side resolves it, and the commit comes back out of the archive either way. A `/`
    and a `+` go through raw, the way codeload was seen to answer them exactly as it answers `%2F`
    and `%2B`. A base URL with a trailing slash is asked the same, so a misconfigured one still
    addresses the same paths.
    """
    fetcher = GitHubFetcher(codeload.url + "/")

    await fetcher.fetch(fetch_of(_HELLO, "wf"))
    for ref in ("v1.2.0", "release/1.0", "v1.0.0+build.5"):
        await fetcher.fetch(fetch_of(RepositoryAtRef("octo", "hello", ref), "wf"))

    assert [seen.path for seen in codeload.requests] == [
        "/octo/hello/tar.gz/HEAD",
        "/octo/hello/tar.gz/v1.2.0",
        "/octo/hello/tar.gz/release/1.0",
        "/octo/hello/tar.gz/v1.0.0+build.5",
    ]

@pytest.mark.asyncio
async def test_a_slash_ref_is_read_from_an_archive_whose_top_directory_flattens_it(
    codeload: Codeload,
) -> None:
    """Codeload writes a ref's `/` as `-` in the top directory: `checkout-releases-v1`, observed.

    So this archive's is `hello-release-1.0`. Nothing is read off that name, which is what lets
    the `/` become a `-`: every entry need only share the one top directory, whatever it is called.
    """
    body = archive(tree("hello-release-1.0", _codeload_tree()), commit=COMMIT)
    codeload.serves("octo", "hello", "release/1.0", body)
    released = RepositoryAtRef("octo", "hello", "release/1.0")

    (answer,) = await GitHubFetcher(codeload.url).fetch(fetch_of(released, "workflows/mine/review"))

    assert dict(fetched(answer).files) == held_below("workflows/mine/review")
    assert fetched(answer).commit == COMMIT

@pytest.mark.asyncio
async def test_the_body_codeload_really_sent_is_read_as_its_commit_and_its_one_file(
    codeload: Codeload,
) -> None:
    """Bytes the real service sent, read by the real adapter: the imitation is checked against it.

    `octocat/Hello-World` holds one file, `README`, and no directory - so asking for `README` and
    for a directory it lacks are the two answers that archive can give, and both carry the commit
    out of its pax header, `7fd1a60b…` - what GitHub's commits API answered for `HEAD` that day.
    """
    codeload.serves("octocat", "Hello-World", "HEAD", _OBSERVED)
    hello_world = RepositoryAtRef("octocat", "Hello-World", None)

    readme, absent = await GitHubFetcher(codeload.url).fetch(fetch_of(hello_world, "README,absent"))

    assert isinstance(refused(readme).refusal, NotFoundError)
    assert "is not a directory" in str(refused(readme).refusal)
    assert _OBSERVED_COMMIT in str(refused(absent).refusal)

# --- Answers that are not an archive ------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_404_says_public_repositories_only_and_how_a_ref_is_written(
    codeload: Codeload,
) -> None:
    """One message for three causes, because codeload answers all three identically - observed.

    A repository that does not exist, a ref it does not have and a private repository are one
    `404` with one body, so the message names all three rather than guessing, and says the two
    things an operator can act on: public repositories only, and how a ref is read - everything
    after the `@` - with a full sha that always works.
    """
    (answer,) = await GitHubFetcher(codeload.url).fetch(fetch_of(_NOWHERE, "wf"))

    refusal = refused(answer).refusal
    said = str(refusal)
    assert isinstance(refusal, NotFoundError)
    assert "octo/nothing-here at its default branch" in said
    assert "public" in said and "private repository" in said
    assert "everything after an argument's '@' is its ref" in said
    assert "full sha always works" in said
    assert "host name" not in said

@pytest.mark.asyncio
async def test_a_404_for_an_owner_that_looks_like_a_host_says_where_an_argument_starts(
    codeload: Codeload,
) -> None:
    """`github.com/o/r/wf` parses - the owner is `github.com` - and can only ever 404."""
    pasted = RepositoryAtRef("github.com", "octo", None)

    (answer,) = await GitHubFetcher(codeload.url).fetch(fetch_of(pasted, "wf"))

    assert "'github.com' reads like a host name" in str(refused(answer).refusal)

@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.asyncio
async def test_a_refusal_to_serve_waits_and_promises_no_time_it_was_never_given(
    codeload: Codeload, status: int
) -> None:
    """`UpstreamUnavailable`, and no reset time: codeload sends no rate-limit header, observed.

    Unavailable rather than unexpected because waiting is the fix. The message says the limit's
    lifting was never announced rather than inventing a time, and a `403` says the second thing it
    can mean - a repository GitHub will not serve to anybody - which waiting does not fix.
    """
    codeload.answers("/octo/hello/tar.gz/HEAD", Scripted(status=status, body=b"slow down"))

    (answer,) = await GitHubFetcher(codeload.url).fetch(fetch_of(_HELLO, "wf"))

    refusal = refused(answer).refusal
    said = str(refusal)
    assert isinstance(refusal, UpstreamUnavailable)
    assert str(status) in said and "it sent no word of when that lifts" in said
    assert ("will not serve this repository to anybody" in said) is (status == 403)

@pytest.mark.asyncio
async def test_a_retry_after_it_was_sent_is_quoted_rather_than_interpreted(
    codeload: Codeload,
) -> None:
    """A time the far side did give is repeated as it was given, and nothing is worked out of it."""
    codeload.answers(
        "/octo/hello/tar.gz/HEAD", Scripted(status=429, headers={"Retry-After": "120"})
    )

    (answer,) = await GitHubFetcher(codeload.url).fetch(fetch_of(_HELLO, "wf"))

    assert "it asked for '120' before the next try" in str(refused(answer).refusal)

@pytest.mark.parametrize(
    ("status", "kind"),
    [(500, UpstreamUnavailable), (503, UpstreamUnavailable), (410, UpstreamUnexpected)],
)
@pytest.mark.asyncio
async def test_any_other_status_is_named_and_filed_by_whether_the_far_side_failed(
    codeload: Codeload, status: int, kind: type[Exception]
) -> None:
    """A `5xx` is GitHub failing and may pass; anything else is an answer AGL has no reading of."""
    codeload.answers("/octo/hello/tar.gz/HEAD", Scripted(status=status))

    (answer,) = await GitHubFetcher(codeload.url).fetch(fetch_of(_HELLO, "wf"))

    refusal = refused(answer).refusal
    assert type(refusal) is kind and str(status) in str(refusal)

# --- The network failing ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_host_that_refuses_the_connection_is_an_answer_naming_the_host_and_why() -> None:
    """Nothing listening is the network's answer, and the operator is told whose, and what."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    (answer,) = await GitHubFetcher(f"http://127.0.0.1:{port}").fetch(fetch_of(_HELLO, "wf"))

    refusal = refused(answer).refusal
    said = str(refusal)
    assert isinstance(refusal, UpstreamUnavailable)
    assert "from 127.0.0.1" in said and "refused" in said.lower()

@pytest.mark.asyncio
async def test_a_far_side_that_never_answers_is_given_up_on_rather_than_waited_on_forever(
    codeload: Codeload,
) -> None:
    """urllib's default is no timeout at all, which is a command that hangs instead of failing."""
    codeload.answers("/octo/hello/tar.gz/HEAD", Scripted(stall=30.0))

    (answer,) = await GitHubFetcher(codeload.url, timeout=0.3).fetch(fetch_of(_HELLO, "wf"))

    refusal = refused(answer).refusal
    assert isinstance(refusal, UpstreamUnavailable) and "timed out" in str(refusal)

@pytest.mark.asyncio
async def test_a_body_cut_short_of_its_declared_length_is_an_answer_and_never_an_eof_error(
    codeload: Codeload,
) -> None:
    """The connection closing early is a download that failed, so it is retried, not misread.

    `EOFError` in particular must not escape: that is what `input()` raises at the end of stdin,
    and a caller treating one as a declined question would read a network failure as a "no".
    """
    whole = archive(tree("hello-HEAD", _codeload_tree()), commit=COMMIT)
    half = whole[: len(whole) // 2]
    codeload.answers("/octo/hello/tar.gz/HEAD", Scripted(body=half, declared=len(whole)))

    (answer,) = await GitHubFetcher(codeload.url).fetch(fetch_of(_HELLO, "workflows/mine/review"))

    refusal = refused(answer).refusal
    assert isinstance(refusal, UpstreamUnavailable)
    assert f"ended after {len(half)} bytes, before the archive did" in str(refusal)

@pytest.mark.asyncio
async def test_cancelling_a_fetch_halfway_stops_the_download_instead_of_finishing_it(
    codeload: Codeload,
) -> None:
    """A cancelled fetch hangs up, because `asyncio.run` waits for the thread a download runs on.

    The download is dripped a kilobyte at a time over several seconds, the fetch is cancelled once
    it has begun, and the stand-in is watched for the client closing its end while there was
    body left to send. A fetcher that let its thread finish would keep reading to the last byte -
    and a Ctrl-C at the terminal would wait for exactly that before the process could exit.
    """
    noise = random.Random(7).randbytes(400_000)
    body = archive(tree("hello-HEAD", {"wf/noise": (noise, False)}), commit=COMMIT)
    codeload.answers("/octo/hello/tar.gz/HEAD", Scripted(body=body, drip=0.01))
    fetching = asyncio.create_task(GitHubFetcher(codeload.url).fetch(fetch_of(_HELLO, "wf")))
    while not codeload.requests:
        await asyncio.sleep(_POLL)
    await asyncio.sleep(0.2)

    fetching.cancel()
    with pytest.raises(asyncio.CancelledError):
        await fetching

    async with asyncio.timeout(_PATIENCE):
        while not codeload.hung_up:
            await asyncio.sleep(_POLL)

# --- Which commit a ref names -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_resolve_is_one_request_for_the_bare_sha_and_downloads_nothing(
    codeload: Codeload, api: GitHubApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One GET, asking for the sha alone, carrying no token - and codeload is never asked at all.

    Public repositories only, so no credential is ever sent, whatever this machine holds: a token
    in the environment is set here and must not arrive, since a request carrying one would be
    counted against its owner and could reach what they alone may read.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_never_sent")
    monkeypatch.setenv("GH_TOKEN", "ghp_never_sent_either")
    api.resolves("octo", "hello", "HEAD", COMMIT)

    answer = await GitHubFetcher(codeload.url, api_url=api.url).resolve(_HELLO)

    assert _resolved(answer) == ResolvedRef(_HELLO, COMMIT)
    (seen,) = api.requests
    assert (seen.method, seen.path) == ("GET", "/repos/octo/hello/commits/HEAD")
    assert seen.headers["accept"] == "application/vnd.github.sha"
    assert "authorization" not in seen.headers
    assert codeload.requests == ()

@pytest.mark.asyncio
async def test_no_ref_is_asked_as_head_and_a_written_ref_is_asked_raw_as_it_was_written(
    api: GitHubApi,
) -> None:
    """The default branch as `HEAD`, and a `/` or a `+` sent raw, as codeload is sent them.

    Observed of the real endpoint: a raw `/` answered as `%2F` did, and a raw `+` answered with
    the commit the tag holding it points at. A base URL with a trailing slash asks the same paths.
    """
    fetcher = GitHubFetcher(api_url=api.url + "/")

    for ref in (None, "v1.2.0", "release/1.0", "v1.0.0+build.5"):
        await fetcher.resolve(RepositoryAtRef("octo", "hello", ref))

    assert [seen.path for seen in api.requests] == [
        "/repos/octo/hello/commits/HEAD",
        "/repos/octo/hello/commits/v1.2.0",
        "/repos/octo/hello/commits/release/1.0",
        "/repos/octo/hello/commits/v1.0.0+build.5",
    ]

@pytest.mark.asyncio
async def test_a_404_names_the_repository_and_says_public_ones_only(api: GitHubApi) -> None:
    """The one answer the endpoint gives a repository that does not exist and a private one."""
    refusal = _unresolved(await GitHubFetcher(api_url=api.url).resolve(_NOWHERE))

    said = str(refusal)
    assert isinstance(refusal, NotFoundError)
    assert "no public repository octo/nothing-here" in said
    assert "private" in said and "public ones only" in said

@pytest.mark.asyncio
async def test_a_ref_the_repository_has_no_commit_for_is_not_found_naming_the_ref(
    api: GitHubApi,
) -> None:
    """422, observed for a plain name and for one holding `/` alike: not there, so exit 3."""
    api.answers(commits_of("octo", "hello", "release/1.0"), no_commit("release/1.0"))

    refusal = _unresolved(await GitHubFetcher(api_url=api.url).resolve(_RELEASED))

    assert isinstance(refusal, NotFoundError)
    assert "no commit for 'release/1.0' in octo/hello" in str(refusal)

@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.asyncio
async def test_an_allowance_run_out_names_the_moment_github_says_it_lifts(
    api: GitHubApi, status: int
) -> None:
    """`X-RateLimit-Remaining: 0` beside a reset in epoch seconds, printed in UTC: wait, not fix.

    `UpstreamUnavailable`, exit 6, because the same command gets past it later - and the time is
    GitHub's own, never one worked out here.
    """
    api.answers(
        commits_of("octo", "hello", "HEAD"),
        Scripted(
            status=status,
            headers={
                "X-RateLimit-Limit": "60",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": _RESET,
            },
        ),
    )

    refusal = _unresolved(await GitHubFetcher(api_url=api.url).resolve(_HELLO))

    said = str(refusal)
    assert isinstance(refusal, UpstreamUnavailable)
    assert f"it says that lifts at {_RESET_AT}" in said
    assert "60 times an hour where nobody is signed in" in said

@pytest.mark.parametrize(
    ("status", "headers", "when"),
    [
        (403, {"Retry-After": "90"}, "it asked for '90' before the next try"),
        (429, {"Retry-After": "90"}, "it asked for '90' before the next try"),
        (429, {}, "it sent no word of when that lifts"),
        (429, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "soon"}, "no word of when"),
    ],
)
@pytest.mark.asyncio
async def test_a_limit_with_no_reset_to_name_quotes_what_was_sent_or_promises_no_time(
    api: GitHubApi, status: int, headers: dict[str, str], when: str
) -> None:
    """A `Retry-After` is repeated as given, and a reset that is no number is not guessed at."""
    api.answers(commits_of("octo", "hello", "HEAD"), Scripted(status=status, headers=headers))

    refusal = _unresolved(await GitHubFetcher(api_url=api.url).resolve(_HELLO))

    assert isinstance(refusal, UpstreamUnavailable)
    assert when in str(refusal)

@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (403, UpstreamUnexpected),
        (410, UpstreamUnexpected),
        (500, UpstreamUnavailable),
        (503, UpstreamUnavailable),
    ],
)
@pytest.mark.asyncio
async def test_any_other_status_is_named_and_filed_by_whether_github_failed(
    api: GitHubApi, status: int, kind: type[Exception]
) -> None:
    """A 403 carrying no limit is some other refusal, which waiting does not get past."""
    api.answers(commits_of("octo", "hello", "HEAD"), Scripted(status=status))

    refusal = _unresolved(await GitHubFetcher(api_url=api.url).resolve(_HELLO))

    assert type(refusal) is kind and str(status) in str(refusal)

@pytest.mark.parametrize(
    "body",
    [
        b"<html>sign in to this network</html>",
        COMMIT[:7].encode(),
        COMMIT.upper().encode(),
        b"",
        b'{"sha": "' + COMMIT.encode() + b'"}',
    ],
)
@pytest.mark.asyncio
async def test_a_200_whose_body_is_not_a_full_sha_is_refused_rather_than_resolved(
    api: GitHubApi, body: bytes
) -> None:
    """A captive portal answers 200 as readily as GitHub does, and what it sends is no commit."""
    api.answers(commits_of("octo", "hello", "HEAD"), Scripted(body=body))

    refusal = _unresolved(await GitHubFetcher(api_url=api.url).resolve(_HELLO))

    assert isinstance(refusal, UpstreamUnexpected)
    assert "not a commit's full sha" in str(refusal)

def test_the_stand_ins_error_bodies_are_the_ones_the_real_endpoint_sent_byte_for_byte() -> None:
    """Saved from real requests in September 2026, so the imitation is checked against them."""
    documented = b'"documentation_url":"https://docs.github.com/rest/commits/commits#get-a-commit"'

    assert NOT_FOUND.body == b'{"message":"Not Found",' + documented + b',"status":"404"}'
    assert no_commit("releases/agl-d4-absent-1").body == (
        b'{"message":"No commit found for SHA: releases/agl-d4-absent-1",'
        + documented
        + b',"status":"422"}'
    )

@pytest.mark.asyncio
async def test_a_sha_with_a_newline_after_it_is_still_the_commit_it_spells(api: GitHubApi) -> None:
    """Observed with none; one added in transit is whitespace around a sha, not another answer."""
    api.answers(commits_of("octo", "hello", "HEAD"), Scripted(body=COMMIT.encode() + b"\n"))

    answer = await GitHubFetcher(api_url=api.url).resolve(_HELLO)

    assert _resolved(answer).commit == COMMIT

@pytest.mark.asyncio
async def test_a_commits_endpoint_refusing_the_connection_is_answered_naming_its_host() -> None:
    """Nothing listening: the operator is told which host could not be asked, and why."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    refusal = _unresolved(await GitHubFetcher(api_url=f"http://127.0.0.1:{port}").resolve(_HELLO))

    said = str(refusal)
    assert isinstance(refusal, UpstreamUnavailable)
    assert "could not ask 127.0.0.1" in said and "refused" in said.lower()

@pytest.mark.asyncio
async def test_a_commits_endpoint_that_never_answers_is_given_up_on(api: GitHubApi) -> None:
    """The fetcher's one timeout bounds this wait too, so a stalled far side is an answer."""
    api.answers(commits_of("octo", "hello", "HEAD"), Scripted(stall=30.0))

    answer = await GitHubFetcher(api_url=api.url, timeout=0.3).resolve(_HELLO)

    refusal = _unresolved(answer)
    assert isinstance(refusal, UpstreamUnavailable) and "timed out" in str(refusal)

# --- The fake, and what only it can be asked ----------------------------------------------------

@pytest.mark.asyncio
async def test_the_fake_resolves_to_the_commit_it_serves_and_records_each_ref_asked() -> None:
    """What a caller's test counts to know one question was asked per repository and ref."""
    fake = FakeFetcher()
    fake.serves(_HELLO, {}, commit=COMMIT)

    first = await fake.resolve(_HELLO)
    second = await fake.resolve(_NOWHERE)

    assert _resolved(first).commit == COMMIT
    assert isinstance(_unresolved(second), NotFoundError)
    assert fake.resolved == (_HELLO, _NOWHERE)
    assert fake.fetched == ()

@pytest.mark.asyncio
async def test_the_fake_answers_a_scripted_refusal_when_a_ref_is_resolved_too() -> None:
    """One refusal scripted for a repository answers both questions that can be asked of it."""
    fake = FakeFetcher()
    throttled = UpstreamUnavailable("throttled, as scripted")
    fake.refuses(_HELLO, throttled)

    assert _unresolved(await fake.resolve(_HELLO)) is throttled

@pytest.mark.asyncio
async def test_the_fake_answers_a_scripted_refusal_for_every_workflow_asked_of_it() -> None:
    """Any refusal a real far side can give, scripted, so a caller meets one with no far side."""
    fake = FakeFetcher()
    throttled = UpstreamUnavailable("throttled, as scripted")
    fake.refuses(_HELLO, throttled)

    answers = await fake.fetch(fetch_of(_HELLO, "a,b"))

    assert [refused(answer).refusal for answer in answers] == [throttled, throttled]

@pytest.mark.asyncio
async def test_the_fake_records_every_fetch_it_was_handed_in_the_order_it_was_handed_them() -> None:
    """What a caller's test counts to know that one repository was one download, not four."""
    fake = FakeFetcher()
    fake.serves(_HELLO, {"wf/__init__.py": FetchedFile(b"")})
    first, second = fetch_of(_HELLO, "wf"), fetch_of(_NOWHERE, "wf")

    await fake.fetch(first)
    await fake.fetch(second)

    assert fake.fetched == (first, second)

@pytest.mark.asyncio
async def test_the_fake_serves_its_own_commit_unless_it_was_handed_one() -> None:
    """A caller scripting files alone still gets a commit, and a full one the port accepts."""
    fake = FakeFetcher()
    fake.serves(_HELLO, {"wf/__init__.py": FetchedFile(b"")})

    (answer,) = await fake.fetch(fetch_of(_HELLO, "wf"))

    assert fetched(answer).commit == FAKE_COMMIT

# --- The container ------------------------------------------------------------------------------

def test_the_container_builds_both_fetchers_without_reaching_anything() -> None:
    """Inert, like every constructor there: building the real one opens nothing and asks nothing.

    `tests/conftest.py` refuses every lookup off this machine, so the real one resolving a host
    at construction would fail here rather than pass.
    """
    assert isinstance(container.real_fetcher(), Fetcher)
    assert isinstance(container.fake_fetcher(), FakeFetcher)

def test_both_are_fetchers_and_the_port_itself_cannot_be_constructed() -> None:
    """The ABC is two abstract methods, and an ABC with an abstract method is not instantiable."""
    assert isinstance(GitHubFetcher(), Fetcher)
    assert isinstance(FakeFetcher(), Fetcher)
    assert Fetcher.__abstractmethods__ == frozenset({"fetch", "resolve"})

    with pytest.raises(TypeError):
        Fetcher()  # type: ignore[abstract]
