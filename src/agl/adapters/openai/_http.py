
import asyncio
import json
import secrets
from collections.abc import Awaitable, Callable, Mapping
from typing import Final

from agl.ports.run import JsonValue

__all__ = ["Listener", "Rpc", "RpcAnswer"]

type RpcAnswer = Mapping[str, JsonValue] | None
type Rpc = Callable[[Mapping[str, JsonValue]], Awaitable[RpcAnswer]]


_TOKEN_BYTES: Final = 16


_PARSE_ERROR: Final = -32700
_INVALID_REQUEST: Final = -32600


def token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


class Listener:

    def __init__(self, routes: Mapping[str, Rpc]) -> None:
        self._routes = dict(routes)
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)

    async def stop(self) -> None:
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
        assert self._server is not None, "the listener was asked for its address before it started"
        host, port = self._server.sockets[0].getsockname()[:2]
        return f"http://{host}:{port}"

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
            pass
        finally:
            if task is not None:
                self._connections.discard(task)
            writer.close()

    async def _exchange(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
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

        # `codex doctor` sends a bare `HEAD` at a configured server's URL before anything speaks
        # MCP.
        if method == "HEAD":
            await _write(writer, "200 OK", b"")
        elif method != "POST":
            await _write(writer, "405 Method Not Allowed", b"")
        elif (route := self._routes.get(target)) is None:
            await _write(writer, "404 Not Found", b"")
        else:
            await self._dispatch(writer, route, body)
        return headers.get("connection", "").lower() != "close"

    async def _dispatch(self, writer: asyncio.StreamWriter, route: Rpc, body: bytes) -> None:
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
    return {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": why}}


def _encoded(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def _body(reader: asyncio.StreamReader, headers: Mapping[str, str]) -> bytes:
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
    head = [f"HTTP/1.1 {status}", f"Content-Length: {len(payload)}"]
    if content_type:
        head.append(f"Content-Type: {content_type}")
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + payload)
    await writer.drain()
