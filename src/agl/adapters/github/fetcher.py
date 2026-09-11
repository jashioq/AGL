import asyncio
import http.client
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlsplit
from agl.adapters.github import _archive
from agl.ports.errors import AglError, NotFoundError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.fetch import FetchAnswer, Fetcher, Resolution, ResolvedRef, UnresolvedRef
from agl.ports.get_request import Fetch, RepositoryAtRef

__all__ = ["GitHubFetcher"]

_CODELOAD: Final = "https://codeload.github.com"

_API: Final = "https://api.github.com"

# Observed: codeload and the commits endpoint both answer `HEAD` as the default branch, whatever
# that branch is named.
_DEFAULT_BRANCH: Final = "HEAD"

# urllib waits forever by default. This bounds each wait - the connection, the status line, every
# read of the body - and not the whole download, which for a large repository is long and fine.
_TIMEOUT: Final = 30.0

# Observed: the commits endpoint answers this media type with the commit's full sha as the whole
# body, no JSON and no newline. GitHub counts every answer against the 60 an hour it allows an
# address nobody is signed in from - a 404 and a 422, and a 304 to a conditional request as well,
# so asking conditionally would save nothing.
_SHA_MEDIA: Final = "application/vnd.github.sha"

# GitHub names every commit by its SHA-1, forty characters of lowercase hexadecimal.
_SHA_LENGTH: Final = 40
_SHA_CHARACTERS: Final = frozenset("0123456789abcdef")

# More than a sha and its newline, so a longer answer shows as one, and nothing past it is read.
_MOST_READ: Final = 80

_NOT_THERE: Final = 404
_NO_COMMIT: Final = 422
_THROTTLED: Final = frozenset({403, 429})
_FORBIDDEN: Final = 403
_TOO_MANY: Final = 429
_FAILED_UPSTREAM: Final = 500

_RETRY_AFTER: Final = "Retry-After"
_RATE_LIMIT: Final = "X-RateLimit-Limit"
_RATE_REMAINING: Final = "X-RateLimit-Remaining"
_RATE_RESET: Final = "X-RateLimit-Reset"
_SPENT: Final = "0"

class _Severed(Exception):
    """A read of the body failed on the connection, which is the network and not the archive."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause = cause

class _Abandoned(Exception):
    """The fetch this download was for was cancelled, so there is nobody left to read it for."""

class _Received:
    """The body as it arrives, stopping once abandoned and naming a failed read as the network's."""

    def __init__(self, response: http.client.HTTPResponse, abandoned: threading.Event) -> None:
        self._response = response
        self._abandoned = abandoned

    def read(self, size: int) -> bytes:
        if self._abandoned.is_set():
            raise _Abandoned
        try:
            return self._response.read(size)
        except (OSError, http.client.HTTPException) as error:
            raise _Severed(error) from error

class GitHubFetcher(Fetcher):
    def __init__(
        self, base_url: str = _CODELOAD, *, api_url: str = _API, timeout: float = _TIMEOUT
    ) -> None:
        self._base = base_url.rstrip("/")
        self._host = urlsplit(self._base).hostname or self._base
        self._api = api_url.rstrip("/")
        self._api_host = urlsplit(self._api).hostname or self._api
        self._timeout = timeout

    # A cancelled `to_thread` leaves its thread running, and `asyncio.run` waits for it on the way
    # out - measured: a Ctrl-C during an 8-second worker returned after 8.5s, and after 1.1s once
    # the worker was told to stop. The event is how it is told.
    async def fetch(self, fetch: Fetch) -> tuple[FetchAnswer, ...]:
        abandoned = threading.Event()
        try:
            return await asyncio.to_thread(self._fetched, fetch, abandoned)
        finally:
            abandoned.set()

    def _fetched(self, fetch: Fetch, abandoned: threading.Event) -> tuple[FetchAnswer, ...]:
        repository = fetch.repository
        try:
            response = urllib.request.urlopen(self._address(repository), timeout=self._timeout)
        except urllib.error.HTTPError as error:
            with error:
                return _archive.refused(fetch, self._answered(repository, error))
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            return _archive.refused(fetch, UpstreamUnavailable(self._unreached(repository, reason)))
        with response:
            try:
                return _archive.unpacked(fetch, _Received(response, abandoned).read, self._host)
            except _Severed as severed:
                unreached = self._unreached(repository, severed.cause)
                return _archive.refused(fetch, UpstreamUnavailable(unreached))

    # `RepositoryAtRef` admits nothing a URL's path would escape, decode or resolve: owner and
    # repository are one segment each, and a ref's `/` separates segments, none empty, `.` or `..`
    # - `tests/ports/test_get_request.py` holds that over every value it accepts. Codeload answers
    # a raw `/` and `+` just as it answers `%2F` and `%2B`, observed.
    def _address(self, repository: RepositoryAtRef) -> str:
        ref = repository.ref if repository.ref is not None else _DEFAULT_BRANCH
        return f"{self._base}/{repository.owner}/{repository.repo}/tar.gz/{ref}"

    def _answered(self, repository: RepositoryAtRef, error: urllib.error.HTTPError) -> AglError:
        if error.code == _NOT_THERE:
            return NotFoundError(_not_public(self._host, repository))
        if error.code in _THROTTLED:
            return UpstreamUnavailable(
                _throttled(self._host, repository, error, error.headers.get(_RETRY_AFTER))
            )
        if error.code >= _FAILED_UPSTREAM:
            return UpstreamUnavailable(_unanswered(self._host, repository, error))
        return UpstreamUnexpected(_unanswered(self._host, repository, error))

    def _unreached(self, repository: RepositoryAtRef, reason: object) -> str:
        return (
            f"AGL could not download {repository} from {self._host}: {reason}. Nothing from it is "
            f"used - check this machine's connection, and run the same command again once it has "
            f"one"
        )

    # No event, as `fetch` has: the answer is forty bytes and there is no body to abandon halfway,
    # so a cancelled resolve's thread ends when its request does, each wait bounded by the timeout.
    async def resolve(self, repository: RepositoryAtRef) -> Resolution:
        return await asyncio.to_thread(self._resolved, repository)

    def _resolved(self, repository: RepositoryAtRef) -> Resolution:
        request = urllib.request.Request(
            self._commit_address(repository), headers={"Accept": _SHA_MEDIA}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read(_MOST_READ)
        except urllib.error.HTTPError as error:
            with error:
                return UnresolvedRef(repository, self._unresolved(repository, error))
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            return UnresolvedRef(repository, UpstreamUnavailable(self._unasked(repository, reason)))
        commit = body.strip().decode("latin-1")
        if len(commit) != _SHA_LENGTH or not _SHA_CHARACTERS.issuperset(commit):
            unread = _not_a_commit(self._api_host, repository, body)
            return UnresolvedRef(repository, UpstreamUnexpected(unread))
        return ResolvedRef(repository, commit)

    # Raw, as `_address` writes a ref for codeload: the commits endpoint answered a raw `/` just as
    # it answered `%2F`, and a raw `+` as the tag holding it - observed.
    def _commit_address(self, repository: RepositoryAtRef) -> str:
        ref = repository.ref if repository.ref is not None else _DEFAULT_BRANCH
        return f"{self._api}/repos/{repository.owner}/{repository.repo}/commits/{ref}"

    def _unresolved(self, repository: RepositoryAtRef, error: urllib.error.HTTPError) -> AglError:
        if error.code == _NOT_THERE:
            return NotFoundError(_no_public_repository(self._api_host, repository))
        if error.code == _NO_COMMIT:
            return NotFoundError(_no_commit(self._api_host, repository))
        if _limiting(error):
            return UpstreamUnavailable(_rate_limited(self._api_host, repository, error))
        if error.code >= _FAILED_UPSTREAM:
            return UpstreamUnavailable(_unresolvable(self._api_host, repository, error))
        return UpstreamUnexpected(_unresolvable(self._api_host, repository, error))

    def _unasked(self, repository: RepositoryAtRef, reason: object) -> str:
        return (
            f"AGL could not ask {self._api_host} which commit {_at(repository)} names: {reason}. "
            f"Check this machine's connection, and run the same command again once it has one"
        )

def _not_public(host: str, repository: RepositoryAtRef) -> str:
    branch = " at its default branch" if repository.ref is None else ""
    hint = (
        f" - and {repository.owner!r} reads like a host name, where an argument starts with the "
        f"owner itself"
        if "." in repository.owner
        else ""
    )
    return (
        f"{host} has no public repository {repository}{branch}: it gives that one answer for a "
        f"repository that does not exist, a ref it does not have and a private repository, and "
        f"`agl get` reaches public ones only. Check the owner, the repository's name and the ref - "
        f"everything after an argument's '@' is its ref, and a commit's full sha always works{hint}"
    )

def _throttled(
    host: str, repository: RepositoryAtRef, error: urllib.error.HTTPError, retry: str | None
) -> str:
    when = (
        f"it asked for {retry!r} before the next try"
        if retry is not None
        else "it sent no word of when that lifts"
    )
    forbidden = (
        ". A 403 can also mean GitHub will not serve this repository to anybody, which no amount "
        "of waiting changes"
        if error.code == _FORBIDDEN
        else ""
    )
    return (
        f"{host} refused to send {repository}: {error.code} {error.reason}. GitHub answers that "
        f"way when it is limiting how often one address may download, and {when} - wait, then "
        f"run the same command again{forbidden}"
    )

def _unanswered(host: str, repository: RepositoryAtRef, error: urllib.error.HTTPError) -> str:
    cause = (
        "a failure on GitHub's side, which the same command may get past later"
        if error.code >= _FAILED_UPSTREAM
        else "an answer AGL has no reading of for a download, so nothing was taken from it"
    )
    return (
        f"{host} answered the download of {repository} with {error.code} {error.reason} where an "
        f"archive was expected - {cause}"
    )

# As GitHub documents its limits: a 403 or a 429, with `X-RateLimit-Remaining` at 0 where the
# hourly allowance is spent and `Retry-After` where a shorter limit was hit. A 403 with neither is
# some other refusal, and is not waited out.
def _limiting(error: urllib.error.HTTPError) -> bool:
    if error.code == _TOO_MANY:
        return True
    spent = error.headers.get(_RATE_REMAINING) == _SPENT
    return error.code == _FORBIDDEN and (spent or error.headers.get(_RETRY_AFTER) is not None)

def _at(repository: RepositoryAtRef) -> str:
    return f"{repository} at its default branch" if repository.ref is None else str(repository)

def _no_public_repository(host: str, repository: RepositoryAtRef) -> str:
    return (
        f"{host} has no public repository {repository.owner}/{repository.repo}: it gives that one "
        f"answer for a repository that does not exist and for a private one, and AGL reaches "
        f"public ones only"
    )

def _no_commit(host: str, repository: RepositoryAtRef) -> str:
    ref = repository.ref if repository.ref is not None else _DEFAULT_BRANCH
    return (
        f"{host} has no commit for {ref!r} in {repository.owner}/{repository.repo}: no branch, tag "
        f"or commit there answers to that name now, which is how a ref deleted or renamed looks"
    )

def _rate_limited(host: str, repository: RepositoryAtRef, error: urllib.error.HTTPError) -> str:
    allowance = error.headers.get(_RATE_LIMIT)
    hourly = f" - {allowance} times an hour where nobody is signed in -" if allowance else ""
    lifts = _lifted(error.headers.get(_RATE_RESET))
    retry = error.headers.get(_RETRY_AFTER)
    if lifts is not None and error.headers.get(_RATE_REMAINING) == _SPENT:
        when = f"it says that lifts at {lifts}"
    elif retry is not None:
        when = f"it asked for {retry!r} before the next try"
    else:
        when = "it sent no word of when that lifts"
    return (
        f"{host} refused to say which commit {_at(repository)} names: {error.code} "
        f"{error.reason}. GitHub limits how often one address may ask it{hourly} and {when}. "
        f"Nothing was downloaded - wait, then run the same command again"
    )

# Epoch seconds, observed, and printed in UTC so that the time reads the same on every machine.
def _lifted(reset: str | None) -> str | None:
    if reset is None:
        return None
    try:
        return datetime.fromtimestamp(int(reset), UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, OverflowError, OSError):
        return None

def _unresolvable(host: str, repository: RepositoryAtRef, error: urllib.error.HTTPError) -> str:
    cause = (
        "a failure on GitHub's side, which the same command may get past later"
        if error.code >= _FAILED_UPSTREAM
        else "an answer AGL has no reading of for that question"
    )
    return (
        f"{host} answered the question of which commit {_at(repository)} names with "
        f"{error.code} {error.reason} - {cause}"
    )

def _not_a_commit(host: str, repository: RepositoryAtRef, body: bytes) -> str:
    return (
        f"{host} answered the question of which commit {_at(repository)} names with {body!r}, "
        f"which is not a commit's full sha. A proxy or a captive portal answering in {host}'s "
        f"place does this, and nothing is taken from it"
    )
