import asyncio
import http.client
import threading
import urllib.error
import urllib.request
from typing import Final
from urllib.parse import urlsplit
from agl.adapters.github import _archive
from agl.ports.errors import AglError, NotFoundError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.fetch import FetchAnswer, Fetcher
from agl.ports.get_request import Fetch, RepositoryAtRef

__all__ = ["GitHubFetcher"]

_CODELOAD: Final = "https://codeload.github.com"

# Observed: codeload answers `HEAD` with the default branch's archive, whatever it is named.
_DEFAULT_BRANCH: Final = "HEAD"

# urllib waits forever by default. This bounds each wait - the connection, the status line, every
# read of the body - and not the whole download, which for a large repository is long and fine.
_TIMEOUT: Final = 30.0

_NOT_THERE: Final = 404
_THROTTLED: Final = frozenset({403, 429})
_FORBIDDEN: Final = 403
_FAILED_UPSTREAM: Final = 500

_RETRY_AFTER: Final = "Retry-After"

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
    def __init__(self, base_url: str = _CODELOAD, *, timeout: float = _TIMEOUT) -> None:
        self._base = base_url.rstrip("/")
        self._host = urlsplit(self._base).hostname or self._base
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

    # `RepositoryAtRef` admits only letters, digits, `.`, `_` and `-`, and never `.` or `..`, so
    # each part is one path segment as it stands - `tests/ports/test_get_request.py` holds that
    # over every value it accepts.
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
        f"a ref cannot hold '/', the first one after the '@' being where the path starts, and a "
        f"commit's full sha always works{hint}"
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
