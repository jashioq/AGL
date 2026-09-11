"""The refusal every test inherits: no name looked up and no socket connected past this machine.

`tests/conftest.py` installs `refuse_everything_off_this_machine` for the whole session, so a test
file written next week is covered by something nobody remembered to ask for - the same argument, in
the same file, as the paid-endpoint guard's. What that guard polices is an environment variable a
vendor CLI reads; what this one polices is the interpreter's own doors, which is the only place an
in-process client can be stopped. `agl get` brought the first one into `src/`: an HTTP fetch made by
AGL itself, where no environment variable stands between a test and codeload.github.com.

## What is refused, and what is not

Every door `tests/test_measurable_targets.py::_poison` closes, opened again for this machine alone.
Name resolution - `getaddrinfo`, `gethostbyname`, `gethostbyname_ex`, and the reverse lookups
`gethostbyaddr` and `getnameinfo` - answers for a loopback or unspecified address and for
`localhost`, which RFC 6761 reserves for the host itself, and refuses every other name, because
looking a name up is itself a packet to a resolver. `connect`, `connect_ex` and `sendto` go through
for an `AF_UNIX` socket and for an IP one addressed to loopback, and refuse everything else - any
other address, any unresolved name, and any other family. `create_connection` is not replaced by
name: it resolves through the module-level `getaddrinfo` and connects through `socket.connect`, and
both of those are this module's by the time it runs. `socketpair` and `bind` are left alone, because
asyncio's self-pipe is a socket pair and a listener on 127.0.0.1 is how every instrument here works.

**What is raised is a `BaseException`, and that is the point of it.** An adapter translates what
it catches, so an `OSError` from a refused lookup would come back from the real fetcher as a
polished "could not reach codeload.github.com" - and a test asserting only that something was
answered would pass while its author believed the network had been exercised. Nothing under test
catches a `BaseException` it did not name, so a reached door arrives at the test as itself.
`tests/test_measurable_targets.py::_WentOutside` is the same decision for the same reason.

## What this cannot cover, said plainly

**A child process.** The patch lives in this interpreter; `git`, `uv`, `claude` and `codex` started
from a test resolve and connect with their own libc. The paid-endpoint guard's environment
variables are what point the two agent CLIs at a loopback, and nothing points `uv` or `git`
anywhere - they are kept offline by the tests that start them, not by this module.
**A reference taken before the session began.** `from socket import getaddrinfo`, run at import
time, keeps the original function; a connection made with it still goes through `socket.connect`
and is refused, but the lookup itself is not. **A module-level network call in a test file.** The
fixture that installs this is session-scoped, and pytest imports every test module to collect it
before any fixture runs. **A socket made from `_socket.socket` directly, or from a file
descriptor some C library opened.** Nothing in this repository does either.
"""

import ipaddress
import socket
from typing import Any, Final, NoReturn
import pytest

__all__ = ["OffTheMachine", "refuse_everything_off_this_machine"]

# The one name a resolver answers from the host's own table rather than by asking a server: RFC
# 6761 reserves it for the loopback interface, and `getaddrinfo("localhost", ...)` is how asyncio
# and `http.server` spell the address they are about to bind.
_THIS_MACHINE: Final = "localhost"

# An IPv6 literal may carry a zone after `%` - `fe80::1%en0` - which `ipaddress` does not parse.
_ZONE: Final = "%"

class OffTheMachine(BaseException):
    """What a test that reached past this machine raises, and nothing under test catches it."""

def refuse_everything_off_this_machine(doors: pytest.MonkeyPatch) -> None:
    """Replace every door out of this machine with one that opens for loopback alone.

    Handed a `MonkeyPatch` rather than making one, so that whoever installs this decides how long
    it lasts and undoes it: `tests/conftest.py` holds it open for the session.
    """
    getaddrinfo = socket.getaddrinfo
    gethostbyname = socket.gethostbyname
    gethostbyname_ex = socket.gethostbyname_ex
    gethostbyaddr = socket.gethostbyaddr
    getnameinfo = socket.getnameinfo
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    sendto = socket.socket.sendto

    def guarded_getaddrinfo(host: Any, *rest: Any, **named: Any) -> Any:
        _check_named(host, "socket.getaddrinfo")
        return getaddrinfo(host, *rest, **named)

    def guarded_gethostbyname(host: str) -> str:
        _check_named(host, "socket.gethostbyname")
        return gethostbyname(host)

    def guarded_gethostbyname_ex(host: str) -> tuple[str, list[str], list[str]]:
        _check_named(host, "socket.gethostbyname_ex")
        return gethostbyname_ex(host)

    def guarded_gethostbyaddr(address: str) -> tuple[str, list[str], list[str]]:
        _check_named(address, "socket.gethostbyaddr")
        return gethostbyaddr(address)

    def guarded_getnameinfo(address: Any, flags: int) -> tuple[str, str]:
        _check_named(address[0], "socket.getnameinfo")
        return getnameinfo(address, flags)

    def guarded_connect(sock: socket.socket, address: Any) -> None:
        _check_reached(sock, address, "socket.connect")
        connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: Any) -> int:
        _check_reached(sock, address, "socket.connect_ex")
        return connect_ex(sock, address)

    def guarded_sendto(sock: socket.socket, data: Any, *rest: Any) -> int:
        _check_reached(sock, rest[-1], "socket.sendto")
        return sendto(sock, data, *rest)

    doors.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    doors.setattr(socket, "gethostbyname", guarded_gethostbyname)
    doors.setattr(socket, "gethostbyname_ex", guarded_gethostbyname_ex)
    doors.setattr(socket, "gethostbyaddr", guarded_gethostbyaddr)
    doors.setattr(socket, "getnameinfo", guarded_getnameinfo)
    doors.setattr(socket.socket, "connect", guarded_connect)
    doors.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    doors.setattr(socket.socket, "sendto", guarded_sendto)

def _check_named(host: object, door: str) -> None:
    """Refuse a lookup of anything that is not this machine, before the resolver is asked."""
    if not _on_this_machine(host):
        _refuse(door, host)

def _check_reached(sock: socket.socket, address: object, door: str) -> None:
    """Refuse a connection, or a datagram, bound anywhere but this machine."""
    if sock.family == socket.AF_UNIX:
        return
    if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
        if _on_this_machine(address[0]):
            return
    _refuse(door, address)

def _on_this_machine(host: object) -> bool:
    """Whether a host names this machine without anybody else being asked to say so."""
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if not host or host.lower() == _THIS_MACHINE:
        return True
    try:
        address = ipaddress.ip_address(host.partition(_ZONE)[0])
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified

def _refuse(door: str, reached: object) -> NoReturn:
    raise OffTheMachine(
        f"a test reached {door} for {reached!r}, which is not this machine. No test may reach "
        f"the network: tests/conftest.py puts this refusal over every lookup and every "
        f"connection for the whole session. A test that needs a far side runs one on 127.0.0.1 "
        f"- tests/instruments/loopback.py and tests/instruments/codeload.py are two - and hands "
        f"its address to whatever is under test"
    )
