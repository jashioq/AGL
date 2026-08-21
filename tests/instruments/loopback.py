"""A stand-in for the Anthropic API, on `127.0.0.1`, that a real `claude` process is run against.

**This module opens no outbound socket, and that is the whole of why the tests using it are free.**
It binds a listener, answers what is asked of it out of canned data, and forwards nothing anywhere;
there is no client, no proxy and no upstream URL in this file. So "no test in
`tests/adapters/test_claude_code_runner.py` reaches a paid endpoint" is not a promise a reader has
to audit test by test - it is a property of the one process every test in that module points its CLI
at, and this is that process. `docs/agl-build-stages.md` names this instrument by name: "a loopback
endpoint reading the composed request before it leaves. This is what settled the `CLAUDE.md`
question, with two controls and one measurement."

## What a session actually asks for, which is less than you would guess

Measured against `claude` 2.1.220+ (what `claude --version` reports for the packaged binary; the
session it starts calls itself 2.1.235, and that is the number on the User-Agent of every request
below) and `claude-agent-sdk` 0.2.140. A whole run - session start, one assistant turn, exit -
touches **two paths**:

  * `HEAD /api/hello`, a connectivity probe. Anything well-formed satisfies it.
  * `POST /v1/messages?beta=true`, which needs a `text/event-stream` reply.

and it makes **two** of the second, in parallel: the turn AGL asked for, and a **session-title**
side call whose prompt begins "You are naming a coding session so the user can pick it out of a long
list". The title call carries AGL's prompt inside it too, quoted in a `<session>` element, so
"the request with our prompt in it" matches both and `composed()` is the helper that does not:
it filters on the title prompt's own system block. **Never index `turns()[0]` and hope** - the two
requests race and either can arrive first.

Six SSE events are emitted for every served turn. Individually, `content_block_delta`,
`content_block_stop`, `message_delta` and `message_stop` each turn out to be droppable and
`message_start` and `content_block_start` do not - but combinations of the droppable four are not
droppable, so the measurement does not reduce to a smaller stream worth shipping. All six, always.

## Serve, never deny

A loopback answering 401 puts the CLI into a ten-attempt exponential backoff: **3 min 09 s** per
run, measured. A served run is ~1.8 s and `check_ready` ~1.1 s. So there is no "refuse
authentication" mode here at all - the refusal path is not worth three minutes a test, and nothing
in AGL's suite needs one that a scripted `Transport` cannot produce in microseconds.

## The two environment variables, and why the second is not belt-and-braces

A caller points the CLI here with `ANTHROPIC_BASE_URL`, and **must** also set `ANTHROPIC_API_KEY`.
With the base URL redirected and the key left unset, the CLI falls back to the operator's own
subscription credential and sends `Authorization: Bearer sk-ant-…` - a live token - to whatever is
listening on that port. Setting any non-empty dummy makes it send `x-api-key: <dummy>` and nothing
else. `DUMMY_KEY` below is that dummy, and `redacted()` is the second line of defence: every header
this module records or prints has credential values replaced by a description of one, so a token
that does arrive cannot end up in a log, an assertion message or a pytest capture buffer.

This is also why nothing here needs authentication to be *working*. The CLI's `init` message - the
tool list, the MCP servers, the subagents, the slash commands - is byte-identical whether the far
side authenticates or refuses, differing only in `session_id`, `uuid`, `cwd` and a socket path. A
test reading `init` is reading a fact about the session the adapter composed, settled before a model
is consulted at all.
"""

import json
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any, Final, Self, cast

__all__ = ["DUMMY_KEY", "MESSAGES", "REPLY", "Loopback", "Request", "redacted", "wire_text"]

# The key a caller puts in `ANTHROPIC_API_KEY`. Its value is irrelevant to this module, which never
# looks at it; what matters is that it is set at all, because an unset one makes the CLI reach for
# the operator's real OAuth token instead. Anyone deleting the line that exports this is handing a
# live credential to a socket - see the module docstring.
DUMMY_KEY: Final = "agl-loopback-dummy-key-not-a-credential"

# What a served turn says when a caller does not choose. Deliberately unlike anything a model would
# produce, so a test asserting on it cannot be satisfied by an accident.
REPLY: Final = "the loopback answered"

# The one path with a body worth reading. Compared against the path with its query string removed,
# because the CLI asks for `/v1/messages?beta=true` and the query is not part of what it is.
MESSAGES: Final = "/v1/messages"

# The connectivity probe. Answered with an empty 200; the CLI reads the status and nothing else.
HELLO: Final = "/api/hello"

# How the session-title side call announces itself, in the first of its system blocks. Matching on
# the CLI's own words rather than on a structural difference (that request also carries
# `temperature` and no `context_management`) because the words are what a reader can check against a
# capture, and a wording change breaks `composed()` loudly rather than silently returning the wrong
# request.
TITLING: Final = "You are naming a coding session"

# Header names whose values must not be written down. `authorization` is the one that matters and
# the rest are here because an instrument that redacts only the header it has already been surprised
# by is an instrument that will be surprised again.
CREDENTIALS: Final = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "cookie", "set-cookie"}
)


def redacted(name: str, value: str) -> str:
    """`value`, or a description of it when `name` is one nothing may record.

    The description keeps the length and the first few characters, which is enough to tell an
    `sk-ant-oat…` from a dummy while being useless to anyone who reads it. A bare `<redacted>` would
    make the one measurement this instrument exists to support - *which* credential the CLI decided
    to send - impossible to make.
    """
    if name.lower() in CREDENTIALS:
        return f"<redacted {len(value)} chars starting {value[:8]!r}>"
    return value


def wire_text(body: Mapping[str, Any]) -> str:
    """Everything in a recorded body, as one string, for asking whether some text left the machine.

    A request is a nest of messages, system blocks, tool schemas and reminders, and the questions
    worth asking of it - is this marker in there, is this instruction in there - are questions about
    the whole of it. Searching the serialised form answers them without this module having to own an
    opinion about which of a vendor's fields counts as "what the model was told".
    """
    return json.dumps(body, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class Request:
    """One request the loopback was handed: what it asked for, and what it carried.

    `body` is the parsed JSON when it parsed, the decoded text when it did not, and `None` when
    there was none. Headers are already redacted - there is no unredacted copy anywhere, which is
    the point.
    """

    method: str
    path: str
    headers: Mapping[str, str]
    body: Mapping[str, Any] | str | None

    @property
    def titling(self) -> bool:
        """Whether this is the CLI's session-title side call rather than the turn AGL asked for."""
        if not isinstance(self.body, Mapping):
            return False
        system = self.body.get("system")
        if isinstance(system, str):
            return TITLING in system
        blocks = system if isinstance(system, list) else []
        return any(
            TITLING in str(block.get("text", "")) for block in blocks if isinstance(block, dict)
        )

    @property
    def to_messages(self) -> bool:
        """Whether this is a turn at all, as opposed to the connectivity probe."""
        return self.method == "POST" and self.path.split("?", 1)[0].endswith(MESSAGES)

    @property
    def kind(self) -> str:
        """`probe`, `titling` or `turn` - which of the three this is, for a failure to name it."""
        if not self.to_messages:
            return "probe"
        return "titling" if self.titling else "turn"


class Loopback:
    """A listener on `127.0.0.1`, serving canned turns and recording what it was asked.

    Started explicitly rather than in `__init__`, and usable as a context manager, so the thread it
    runs on has a visible beginning and end: a module-scoped fixture holds one open for a whole
    file, and a leaked listener would be a port that outlives the run that bound it.

    `says` is a plain mutable attribute because a test wanting a different answer wants it for the
    run it is about to start, and reaching for a second constructor argument to change one string
    would make the common case - take the fixture's loopback, run something, read `composed()` -
    read as though it were configuration.
    """

    def __init__(self, *, says: str = REPLY) -> None:
        self.says = says
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._seen: list[Request] = []

    # -- lifetime ---------------------------------------------------------------------------------

    def start(self) -> Self:
        """Bind port 0, hand the assigned port back, and serve on a background thread.

        Port 0 rather than a fixed one: a test suite that picks a number is a test suite that fails
        on the machine where something else picked the same one. The thread is a daemon so that a
        pytest run which dies mid-test cannot be held open by a listener nobody is going to close.
        """
        server = _Server(self)
        thread = threading.Thread(target=server.serve_forever, name="agl-loopback", daemon=True)
        thread.start()
        self._server, self._thread = server, thread
        return self

    def stop(self) -> None:
        """Stop serving and release the port. Idempotent: a failed test cannot leak a listener."""
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
    def port(self) -> int:
        """The port the OS assigned, once `start` has been called."""
        assert self._server is not None, "the loopback was asked for its port before it was started"
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        """What goes in `ANTHROPIC_BASE_URL`. Loopback: this address is not routable off-box."""
        return f"http://127.0.0.1:{self.port}"

    # -- what was asked ---------------------------------------------------------------------------

    @property
    def requests(self) -> tuple[Request, ...]:
        """Everything recorded so far, oldest first. A snapshot: requests arrive on other threads.

        Copied under the lock rather than handed out live, because the two turns a run makes arrive
        on two of the server's threads and a test reading the list while one lands would see it
        change under itself.
        """
        with self._lock:
            return tuple(self._seen)

    def clear(self) -> None:
        """Forget every recorded request, so one test cannot read another's traffic."""
        with self._lock:
            self._seen.clear()

    def turns(self) -> tuple[Mapping[str, Any], ...]:
        """Every composed `/v1/messages` body except the session-title side calls."""
        return tuple(
            seen.body
            for seen in self.requests
            if seen.to_messages and not seen.titling and isinstance(seen.body, Mapping)
        )

    def composed(self) -> Mapping[str, Any]:
        """The one request carrying AGL's own prompt, or a failed assertion saying what did arrive.

        Asserting there is exactly one is the point rather than a convenience. Two mean the caller
        started two sessions and any answer here would be arbitrary; none means the CLI never got as
        far as composing a request, which is a failure to report and not a test to skip past.
        """
        composed = self.turns()
        recorded = [(seen.method, seen.path, seen.kind) for seen in self.requests]
        assert len(composed) == 1, (
            f"the loopback was handed {len(composed)} composed turn(s) and exactly one was "
            f"expected. Everything it recorded: {recorded}. Nothing at all here means the CLI "
            f"never reached the point of composing a request, which is a failure and not a test "
            f"with nothing to say"
        )
        return composed[0]

    # -- the answers, called on the server's own threads -------------------------------------------

    def _record(self, request: Request) -> None:
        with self._lock:
            self._seen.append(request)

    def _stream(self, model: str) -> bytes:
        """One canned assistant turn as SSE: all six events, in order, as one body.

        Written out in full rather than assembled from a template because this is a wire format
        somebody will one day have to check against a capture, and a reader can only do that if the
        events are here to read.
        """
        identifier = f"msg_agl_{uuid.uuid4().hex[:16]}"
        events: tuple[tuple[str, dict[str, Any]], ...] = (
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": identifier,
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {
                            "input_tokens": 11,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "output_tokens": 1,
                        },
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": self.says},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 8},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )
        return b"".join(
            f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in events
        )


class _Server(ThreadingHTTPServer):
    """The listener, carrying a typed reference back to the `Loopback` its handlers report to."""

    daemon_threads = True

    def __init__(self, endpoint: Loopback) -> None:
        self.endpoint = endpoint
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    """One request: read it, record it redacted, answer it from canned data, forward it nowhere."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        """Silence. The record is `Loopback.requests`, and stderr noise inside pytest is not one."""

    def _handle(self) -> None:
        endpoint = cast(_Server, self.server).endpoint
        raw = self._body()
        parsed: Mapping[str, Any] | str | None
        if not raw:
            parsed = None
        else:
            try:
                loaded = json.loads(raw.decode("utf-8"))
                parsed = loaded if isinstance(loaded, dict) else raw.decode("utf-8", "replace")
            except (ValueError, UnicodeDecodeError):
                parsed = raw.decode("utf-8", "replace")
        endpoint._record(
            Request(
                method=self.command,
                path=self.path,
                headers={name: redacted(name, value) for name, value in self.headers.items()},
                body=parsed,
            )
        )
        path = self.path.split("?", 1)[0]
        if path.endswith(MESSAGES):
            model = parsed.get("model") if isinstance(parsed, Mapping) else None
            self._answer(
                endpoint._stream(str(model or "claude-haiku-4-5")),
                content_type="text/event-stream; charset=utf-8",
            )
        elif path.endswith(HELLO):
            self._answer(b"")
        else:
            self._answer(b"{}")

    do_HEAD = _handle
    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle
    do_OPTIONS = _handle

    def _body(self) -> bytes:
        """Whatever the request carried, by whichever of the two framings the CLI used.

        Chunked is handled because the SDK's own HTTP client is free to choose it for a 140 KB
        request, and a loopback that read only `Content-Length` bodies would hang on the day it did.
        """
        length = self.headers.get("Content-Length")
        if length is not None:
            return self.rfile.read(int(length))
        if (self.headers.get("Transfer-Encoding") or "").lower() != "chunked":
            return b""
        chunks: list[bytes] = []
        while size := int(self.rfile.readline().strip() or b"0", 16):
            chunks.append(self.rfile.read(size))
            self.rfile.readline()
        self.rfile.readline()
        return b"".join(chunks)

    def _answer(self, payload: bytes, *, content_type: str = "application/json") -> None:
        """A 200 carrying `payload`, and no body at all when the verb was HEAD.

        The `Content-Length` still goes out on a HEAD - it is what the response *would* have been -
        and writing the bytes as well would leave them in the connection for the client to read as
        the start of the next response.
        """
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("request-id", f"req_agl_{uuid.uuid4().hex[:16]}")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)
