"""A stand-in for api.github.com on `127.0.0.1`: it answers the commits endpoint, and records.

**It opens no outbound socket**, for `instruments.codeload`'s reason: it binds a listener, answers
each request out of what a test scripted and forwards nothing anywhere - so the real fetcher, handed
this address as its `api_url`, asks which commit a ref names without a packet leaving the machine.
**It records a credential only as `instruments.loopback.redacted` describes one**: the fetcher sends
none, which a test asserts, and one that did arrive would be a live token on a developer machine.

What it imitates is what was observed of the real service in September 2026, and no more:

  * `GET /repos/{owner}/{repo}/commits/{ref}`, sent with `Accept: application/vnd.github.sha`,
    answers `200` with `application/vnd.github.sha; charset=utf-8` and a body that is the commit's
    40-character sha and nothing else - no JSON, no newline. A branch, a tag (the commit an
    annotated one points at, as codeload's archive of it records), an abbreviated sha, `HEAD`, and
    a ref holding `/` or `+` written raw were each answered that way.
  * A ref the repository has no commit for is `422` with a JSON body, a ref holding `/` included,
    and a repository that does not exist or is private is one `404` with a JSON body - which is
    what an unscripted path gets here.
  * Every answer of the real service carries `X-RateLimit-Limit: 60`, `-Remaining`, `-Used`,
    `-Resource` and `-Reset`, in epoch seconds, and spends one of the 60 - a 404 and a 422 too.
    This sends none unless a test scripts them, as it scripts an allowance run out.

Its answers are `instruments.codeload.Scripted` and its record `instruments.codeload.Seen`, each
meaning here exactly what it means there, rather than a second pair of types for the same things.
"""

import socketserver
import threading
from http import HTTPStatus
from types import TracebackType
from typing import Final, Self, cast
from instruments.codeload import Scripted, Seen
from instruments.loopback import redacted

__all__ = ["NOT_FOUND", "GitHubApi", "commits_of", "no_commit"]

_SHA_MEDIA: Final = "application/vnd.github.sha; charset=utf-8"
_JSON: Final = "application/json; charset=utf-8"

_DOCUMENTED: Final = "https://docs.github.com/rest/commits/commits#get-a-commit"

_LINE: Final = 65537
_DRIP: Final = 1024
_POLL_INTERVAL: Final = 0.01

def _refusal(status: HTTPStatus, message: str) -> Scripted:
    """An error answer as the real service shapes one: its message, its docs and its status."""
    body = f'"message":"{message}","documentation_url":"{_DOCUMENTED}","status":"{status.value}"'
    return Scripted(status=status, body=f"{{{body}}}".encode(), headers={"Content-Type": _JSON})

# What the real service answered a repository that is not there with, byte for byte, observed.
NOT_FOUND: Final = _refusal(HTTPStatus.NOT_FOUND, "Not Found")

def commits_of(owner: str, repo: str, ref: str) -> str:
    """The path the real fetcher asks at, the ref written raw, as the real service takes it."""
    return f"/repos/{owner}/{repo}/commits/{ref}"

def no_commit(ref: str) -> Scripted:
    """The `422` the real service answered a ref it has no commit for with, observed."""
    return _refusal(HTTPStatus.UNPROCESSABLE_ENTITY, f"No commit found for SHA: {ref}")

class GitHubApi:
    """A listener on `127.0.0.1` answering as api.github.com was seen to, recording each request.

    Started explicitly and usable as a context manager, like `instruments.codeload.Codeload`, so
    the thread it serves on has a visible beginning and end.
    """

    def __init__(self) -> None:
        self._scripted: dict[str, Scripted] = {}
        self._seen: list[Seen] = []
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> Self:
        """Bind port 0 and serve on a daemon thread, polling for a shutdown as codeload's does."""
        server = _Server(self)
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": _POLL_INTERVAL},
            name="agl-github-api",
            daemon=True,
        )
        thread.start()
        self._server, self._thread = server, thread
        return self

    def stop(self) -> None:
        """Stop serving and release the port, waking any answer still stalled. Idempotent."""
        self._stopping.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server, self._thread = None, None

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.stop()

    @property
    def url(self) -> str:
        """What the real fetcher is handed as its `api_url`."""
        assert self._server is not None, "the stand-in was asked for its address before it started"
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def requests(self) -> tuple[Seen, ...]:
        """Every request handed over so far, oldest first."""
        with self._lock:
            return tuple(self._seen)

    def answers(self, path: str, scripted: Scripted) -> None:
        """Answer `path` with `scripted` from now on, in place of the observed 404."""
        self._scripted[path] = scripted

    def resolves(self, owner: str, repo: str, ref: str, commit: str) -> None:
        """Answer that `ref` names `commit`, in the shape the real service answers that in."""
        self.answers(
            commits_of(owner, repo, ref),
            Scripted(body=commit.encode(), headers={"Content-Type": _SHA_MEDIA}),
        )

    def _answer_to(self, seen: Seen) -> Scripted:
        with self._lock:
            self._seen.append(seen)
        return self._scripted.get(seen.path, NOT_FOUND)

class _Server(socketserver.ThreadingTCPServer):
    """The listener, carrying a typed reference back to the `GitHubApi` its handlers report to."""

    daemon_threads = True
    block_on_close = False

    def __init__(self, stand_in: GitHubApi) -> None:
        self.stand_in = stand_in
        super().__init__(("127.0.0.1", 0), _Handler)

class _Handler(socketserver.StreamRequestHandler):
    """One request: read it, record it, answer it as scripted, and close the connection."""

    def handle(self) -> None:
        stand_in = cast(_Server, self.server).stand_in
        request = self.rfile.readline(_LINE).decode("latin-1").split(" ", 2)
        if len(request) != 3:
            return
        method, path, _ = request
        headers: dict[str, str] = {}
        while (line := self.rfile.readline(_LINE)).strip():
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = redacted(name.strip(), value.strip())
        scripted = stand_in._answer_to(Seen(method, path, headers))
        if stand_in._stopping.wait(scripted.stall):
            return
        status = HTTPStatus(scripted.status)
        lines = [
            f"HTTP/1.1 {status.value} {status.phrase}",
            f"Content-Length: {scripted.declared or len(scripted.body)}",
            "Connection: close",
            *(f"{name}: {value}" for name, value in scripted.headers.items()),
        ]
        piece = _DRIP if scripted.drip else max(len(scripted.body), 1)
        try:
            self.wfile.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            for start in range(0, len(scripted.body), piece):
                if stand_in._stopping.wait(scripted.drip):
                    return
                self.wfile.write(scripted.body[start : start + piece])
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
