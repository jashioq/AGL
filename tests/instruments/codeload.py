"""A stand-in for codeload.github.com on `127.0.0.1`: it serves archives a test built, and records.

**It opens no outbound socket.** It binds a listener, answers each request out of what a test
scripted, and forwards nothing anywhere - so the real fetcher, pointed here by its constructor, is
exercised end to end without a packet leaving the machine, which `tests/conftest.py`'s network
guard would refuse anyway.

What it imitates is what was observed of the real service in September 2026, and no more:

  * `GET /{owner}/{repo}/tar.gz/{ref}` answers `200` with `application/x-gzip`, a gzip-compressed
    pax archive whose global header carries the commit as `comment`, and whose entries all sit
    under one top-level directory named `<repo>-<ref as requested>`. `archive` and `tree` build
    exactly that shape.
  * Anything it does not have - a repository, a ref, a private repository - is one identical `404`
    with the body `404: Not Found`, which is what an unscripted path gets here.
  * It sends no rate-limit headers. A test that wants one scripts it.

The far side misbehaving is scripted too, because those are the answers a real network hands back
and no free instrument could otherwise produce: a body cut short under a `Content-Length` that
promised more, a stall before the status line, and a body dripped slowly enough for a test to
cancel a fetch halfway through it. Written on `socketserver` rather than `http.server` so that it
can send what `http.server` would tidy away - and so that it needs no `do_GET`, a name the naming
convention would have to be told about.
"""

import io
import socketserver
import tarfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from types import TracebackType
from typing import Final, Self, cast

__all__ = [
    "NOT_FOUND",
    "Codeload",
    "Scripted",
    "Seen",
    "archive",
    "directory",
    "link",
    "regular",
    "special",
    "tree",
]

# The body the real service answered a missing repository and a missing ref with, observed.
NOT_FOUND: Final = b"404: Not Found"

_GIT_FILE: Final = 0o664
_GIT_EXECUTABLE: Final = 0o775
_GIT_DIRECTORY: Final = 0o775

_LINE: Final = 65537
_DRIP: Final = 1024
_POLL_INTERVAL: Final = 0.01

type Entry = tuple[tarfile.TarInfo, bytes]

@dataclass(frozen=True, slots=True)
class Scripted:
    """One answer: a status, a body, headers, and whether it arrives cut short, late or slowly."""

    status: int = HTTPStatus.OK

    body: bytes = b""

    headers: Mapping[str, str] = field(default_factory=dict)

    declared: int | None = None
    """The `Content-Length` sent, when it is not the body's: more than the body is a cut-off."""

    stall: float = 0.0
    """Seconds of silence before the status line, which is what a client's timeout is for."""

    drip: float = 0.0
    """Seconds between each kilobyte of the body, so that a fetch is mid-download for a while."""

@dataclass(frozen=True, slots=True)
class Seen:
    """One request the stand-in was handed: its method, its path, and its headers, names lowered."""

    method: str

    path: str

    headers: Mapping[str, str]

class Codeload:
    """A listener on `127.0.0.1` answering scripted paths, recording each request it was handed.

    Started explicitly and usable as a context manager, like `instruments.loopback.Loopback`, so
    the thread it serves on has a visible beginning and end.
    """

    def __init__(self) -> None:
        self._scripted: dict[str, Scripted] = {}
        self._seen: list[Seen] = []
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._hung_up = 0
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> Self:
        """Bind port 0 and serve on a daemon thread, so nothing a test left behind holds pytest.

        `serve_forever` notices a shutdown only between polls, every half second by default -
        which is half a second of teardown in every test that starts one of these.
        """
        server = _Server(self)
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": _POLL_INTERVAL},
            name="agl-codeload",
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
        """What the real fetcher is handed as its base URL."""
        assert self._server is not None, "the stand-in was asked for its address before it started"
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def requests(self) -> tuple[Seen, ...]:
        """Every request handed over so far, oldest first."""
        with self._lock:
            return tuple(self._seen)

    @property
    def hung_up(self) -> int:
        """How many answers the client closed its end on before the whole body had been sent."""
        with self._lock:
            return self._hung_up

    def _hang_up(self) -> None:
        with self._lock:
            self._hung_up += 1

    def answers(self, path: str, scripted: Scripted) -> None:
        """Answer `path` with `scripted` from now on, in place of the observed 404."""
        self._scripted[path] = scripted

    def serves(self, owner: str, repo: str, ref: str, body: bytes) -> None:
        """Serve an archive at the one path the real service would serve it from."""
        self.answers(f"/{owner}/{repo}/tar.gz/{ref}", Scripted(body=body))

    def _answer_to(self, seen: Seen) -> Scripted:
        with self._lock:
            self._seen.append(seen)
        return self._scripted.get(
            seen.path,
            Scripted(
                status=HTTPStatus.NOT_FOUND,
                body=NOT_FOUND,
                headers={"Content-Type": "text/plain; charset=utf-8"},
            ),
        )

class _Server(socketserver.ThreadingTCPServer):
    """The listener, carrying a typed reference back to the `Codeload` its handlers report to."""

    daemon_threads = True
    block_on_close = False

    def __init__(self, stand_in: Codeload) -> None:
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
            headers[name.strip().lower()] = value.strip()
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
        if "Content-Type" not in scripted.headers:
            lines.append("Content-Type: application/x-gzip")
        piece = _DRIP if scripted.drip else max(len(scripted.body), 1)
        try:
            self.wfile.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            for start in range(0, len(scripted.body), piece):
                if stand_in._stopping.wait(scripted.drip):
                    return
                self.wfile.write(scripted.body[start : start + piece])
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            stand_in._hang_up()

def archive(entries: Sequence[Entry], *, commit: str | None) -> bytes:
    """A gzip-compressed pax archive laid out as `git archive` lays one out, commit and all.

    The commit goes in the global header under `comment`, which is where the real service puts it;
    `None` leaves the header out altogether, which it never does.
    """
    buffer = io.BytesIO()
    headers = {"comment": commit} if commit is not None else {}
    with tarfile.open(
        fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers=headers
    ) as made:
        for info, data in entries:
            made.addfile(info, io.BytesIO(data) if info.isreg() else None)
    return buffer.getvalue()

def tree(top: str, files: Mapping[str, tuple[bytes, bool]]) -> list[Entry]:
    """Every directory and file of a repository under `top`, a directory ahead of its contents."""
    entries: list[Entry] = [directory(top)]
    made: set[str] = set()
    for path in sorted(files):
        *parents, _ = path.split("/")
        for depth in range(1, len(parents) + 1):
            above = "/".join(parents[:depth])
            if above not in made:
                made.add(above)
                entries.append(directory(f"{top}/{above}"))
        content, executable = files[path]
        entries.append(
            regular(f"{top}/{path}", content, mode=_GIT_EXECUTABLE if executable else _GIT_FILE)
        )
    return entries

def regular(name: str, data: bytes = b"", *, mode: int = _GIT_FILE) -> Entry:
    """A regular file, with the mode `git archive` gives one unless told otherwise."""
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    return info, data

def directory(name: str) -> Entry:
    """A directory entry, which `git archive` writes ahead of everything the directory holds."""
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = _GIT_DIRECTORY
    return info, b""

def link(name: str, target: str, *, hard: bool = False) -> Entry:
    """A symbolic link to `target`, or a hard link to the entry of that name."""
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
    info.linkname = target
    return info, b""

def special(name: str, kind: bytes) -> Entry:
    """A device or a FIFO, which no tree git records can hold: `tarfile.CHRTYPE` and the rest."""
    info = tarfile.TarInfo(name)
    info.type = kind
    return info, b""
