"""A loopback HTTP/1.1 listener, hand-rolled, because the harness will only take tools over MCP.

`_tools.py` decides what the agent may call and what happens when it does; this module is the
socket underneath it and knows nothing about tools. The split is by obligation: one side speaks
MCP's method vocabulary, the other speaks request lines, `Content-Length` and status codes, and
neither has any business holding the other's rules. What crosses between them is one type - an
async callable taking a decoded JSON-RPC message and answering with one, or with `None` for a
notification - so this module never learns that `tools/call` exists.

**Why AGL is writing an HTTP server at all.** `pyproject.toml` says `dependencies = []` and means
it, and the harness offers no in-process route: it is the MCP *client* and it starts or connects to
the server itself, so a Python closure over the framework's `Run` cannot be handed over the way the
other adapter's SDK takes one. `docs/codex-cli-findings.md` §0 measured the configuration half -
an MCP server can be declared entirely through `-c` overrides, in the streamable-HTTP transport,
with no file on disk - and left the server itself to be built. This is that server. It is about a
hundred lines because the subset MCP needs is small: one path, `POST` with a JSON body, a reply
with a `Content-Length`, and nothing else.

## What a client actually asks for, measured

Against a production MCP client - Claude Code 2.1.220, a different vendor's, which is what makes it
evidence about the *dialect* rather than about one implementation - a whole session against this
module is four requests:

    HEAD /<path>                                            a reachability probe
    POST /<path>   initialize                 (id)          answered 200 application/json
    POST /<path>   notifications/initialized  (no id)       answered 202, no body
    GET  /<path>                                            the optional server-to-client stream
    POST /<path>   tools/list                 (id)          answered 200 application/json

and the client reported the server connected and listed its tool. So the three shapes below are not
guesses: **a single JSON response is enough** (the specification permits `application/json` beside
`text/event-stream` and this module always chooses the first, since nothing here ever sends the
client something it did not ask for), **a notification takes 202 with no body**, and **`GET` may be
refused with 405** - the client tried it, was told no, and carried on. Repeated against the real
`_tools.Supply` rather than a sketch of it: both of the servers this adapter runs, at their real
token-carrying paths, connected and enumerated their tools.

A second measurement, from the harness this adapter actually drives: `codex doctor` sends a bare
`HEAD` at a configured server's URL, which is why `HEAD` is answered rather than falling through to
the 405 the other unhandled verbs get.

**What is not measured is the harness's own client**, because reaching it means running a turn.
`docs/manual-qa.md` carries that.

## The path is a secret, and that is this module's only access control

A listener on `127.0.0.1` is reachable by every process on the machine, and what is behind this one
is the workflow's own tools - the reporting tool whose payload becomes a step's result, and the
asker that puts text in front of a person. So the routes are keyed by a path carrying an
unguessable token minted per run (`secrets.token_urlsafe`), the token never leaves the argument
list this process composes for its own child, and a request to any other path is a 404 that reaches
no handler. That is not authentication and is not claimed to be: it stops a process that guessed
the port, not one that can read another process's command line.

Two things follow and are deliberate. The listener binds `127.0.0.1` and never `0.0.0.0`, so
nothing off the machine can reach it at all. And it lives exactly as long as one run - `_tools.py`
brackets it around the child process - so there is no window in which a port is open with nothing
running behind it.
"""

import asyncio
import json
import secrets
from collections.abc import Awaitable, Callable, Mapping
from typing import Final

from agl.ports.run import JsonValue

__all__ = ["Answer", "Listener", "Rpc"]

type Answer = Mapping[str, JsonValue] | None
type Rpc = Callable[[Mapping[str, JsonValue]], Awaitable[Answer]]
"""One JSON-RPC message in, one answer out, or `None` when the message was a notification.

The whole of what this module knows about what it is carrying. A route is a callable of this type
and nothing else - no server object, no tool list, no session - which is what keeps MCP's rules on
the other side of the import."""


# How many bytes of entropy go into the path token. Sixteen is more than enough to be unguessable
# and short enough that the composed `-c` override stays readable in a failure message.
_TOKEN_BYTES: Final = 16


# The JSON-RPC codes this module can produce on its own. Everything else is the route's business:
# a method that does not exist is a fact about MCP, and this module has never heard of MCP.
_PARSE_ERROR: Final = -32700
_INVALID_REQUEST: Final = -32600


def token() -> str:
    """An unguessable path segment for one run's routes. The module docstring says what it buys."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


class Listener:
    """One listener on `127.0.0.1`, serving a fixed set of paths for the length of one run.

    Started and stopped explicitly rather than in `__init__`, so the socket has a visible beginning
    and end: `_tools.py` brackets it around a child process, and a leaked listener would be a port
    still answering after the run that opened it is over.

    Connections are handled concurrently, one task each, and that is load-bearing rather than
    incidental: a tool call may block for as long as a person takes to answer a question, and a
    client that opens a second connection in the meantime - to list tools, to ping - must not be
    made to wait behind it.
    """

    def __init__(self, routes: Mapping[str, Rpc]) -> None:
        self._routes = dict(routes)
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Bind port 0 on the loopback interface and begin serving.

        Port 0 rather than a number this module picked: a framework that chose one would fail on
        the machine where something else had chosen the same, and two AGL runs at once would be
        that machine.
        """
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)

    async def stop(self) -> None:
        """Stop serving, and cancel whatever was still in flight. Idempotent.

        Cancelling is the honest end for a handler that is still waiting on a question: by the time
        this is called the child process has gone, so there is nobody left to give the answer to,
        and a task left awaiting a person would hold the event loop open for as long as they took.
        """
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for connection in list(self._connections):
            connection.cancel()
        if self._connections:
            await asyncio.gather(*self._connections, return_exceptions=True)
            self._connections.clear()

    @property
    def origin(self) -> str:
        """`http://127.0.0.1:<port>`, once `start` has been awaited. Never a hostname.

        A literal address and not `localhost`, which resolves through whatever the machine's
        resolver says it means and can answer with an IPv6 address the listener is not bound to.
        """
        assert self._server is not None, "the listener was asked for its address before it started"
        host, port = self._server.sockets[0].getsockname()[:2]
        return f"http://{host}:{port}"

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """One connection, kept open for as many requests as the client sends down it."""
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        try:
            while await self._exchange(reader, writer):
                pass
        except (
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            ConnectionError,
            ValueError,
        ):
            # A client that hung up, or sent a request this module could not frame - a header block
            # larger than the read buffer, a `Content-Length` that is not a number - is a closed
            # connection and nothing more. There is no session to lose: the MCP client opens
            # another one, and a run's outcome is decided on the child's own event stream. What is
            # deliberately *not* caught is a cancellation, which is `stop` tearing this down.
            pass
        finally:
            if task is not None:
                self._connections.discard(task)
            writer.close()

    async def _exchange(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
        """Read one request, answer it, and say whether the connection may carry another."""
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        method, _, rest = lines[0].partition(" ")
        target = rest.partition(" ")[0].partition("?")[0]
        headers = {
            name.strip().lower(): value.strip()
            for name, _, value in (line.partition(":") for line in lines[1:])
            if name.strip()
        }
        body = await _body(reader, headers)

        if method == "HEAD":
            # `codex doctor` probes a configured server's URL this way before anything speaks MCP.
            await _write(writer, "200 OK", b"")
        elif method != "POST":
            # A `GET` is the optional server-to-client stream, which this module does not offer:
            # nothing here ever speaks first. Refusing it is what the specification says to do, and
            # a measured client tries it, is told no, and carries on.
            await _write(writer, "405 Method Not Allowed", b"")
        elif (route := self._routes.get(target)) is None:
            await _write(writer, "404 Not Found", b"")
        else:
            await self._dispatch(writer, route, body)
        return headers.get("connection", "").lower() != "close"

    async def _dispatch(self, writer: asyncio.StreamWriter, route: Rpc, body: bytes) -> None:
        """Decode one request body, hand it to its route, and write whatever comes back.

        A body carrying a batch is answered with a batch, and one carrying nothing but
        notifications is answered with 202 and no body at all - which is the shape the
        specification asks for and the shape a measured client sends after `initialize`.
        """
        try:
            decoded = json.loads(body)
        except ValueError:
            await _write(writer, "400 Bad Request", _encoded(_failed(_PARSE_ERROR, "not JSON")))
            return
        batch = decoded if isinstance(decoded, list) else [decoded]
        answers: list[Mapping[str, JsonValue]] = []
        for message in batch:
            if not isinstance(message, dict):
                answers.append(_failed(_INVALID_REQUEST, "a message that is not an object"))
                continue
            if (answer := await route(message)) is not None:
                answers.append(answer)
        if not answers:
            await _write(writer, "202 Accepted", b"")
            return
        payload = answers if isinstance(decoded, list) else answers[0]
        await _write(writer, "200 OK", _encoded(payload), content_type="application/json")


def _failed(code: int, why: str) -> dict[str, JsonValue]:
    """A JSON-RPC error for a message this module could not even read as one.

    `id` is `null`, which is what the protocol says to answer with when the request's own id could
    not be recovered - there is no honest alternative, since inventing one would correlate an error
    with a request nobody made.
    """
    return {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": why}}


def _encoded(payload: object) -> bytes:
    """One JSON body as bytes. `ensure_ascii=False` because a tool result is a person's prose."""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def _body(reader: asyncio.StreamReader, headers: Mapping[str, str]) -> bytes:
    """Whatever a request carried, by either of the two framings a client may choose.

    Chunked is handled as well as `Content-Length` because the framing is the client's choice and
    not ours: a server that read only one of them would work until the day a client changed its
    mind about a body's size, and would then hang rather than fail, which is the worse of the two.
    """
    length = headers.get("content-length")
    if length is not None:
        return await reader.readexactly(int(length))
    if headers.get("transfer-encoding", "").lower() != "chunked":
        return b""
    chunks: list[bytes] = []
    while size := int((await reader.readline()).strip() or b"0", 16):
        chunks.append(await reader.readexactly(size))
        await reader.readline()
    await reader.readline()
    return b"".join(chunks)


async def _write(
    writer: asyncio.StreamWriter, status: str, payload: bytes, *, content_type: str = ""
) -> None:
    """One response, always with a `Content-Length`, so the connection stays usable afterwards.

    Never chunked and never a stream: every answer this module gives is one JSON document that is
    already in memory, and a framing the client has to guess at is the one way a keep-alive
    connection turns into a client waiting forever for a body that already arrived.
    """
    head = [f"HTTP/1.1 {status}", f"Content-Length: {len(payload)}"]
    if content_type:
        head.append(f"Content-Type: {content_type}")
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + payload)
    await writer.drain()
