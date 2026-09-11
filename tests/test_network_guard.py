"""The network guard every test inherits: nothing past this machine, and everything on it.

`tests/conftest.py` installs `instruments.offline` for the whole session, and `scripts/check`'s
paid-endpoint gate proves that a test file written today inherits it. This file holds the rest of
what that guard is for, in both directions, because a guard is worth exactly as much as the two
halves together: one that refused too little lets a test reach codeload.github.com, and one that
refused too much would break every instrument here - each of them a listener on 127.0.0.1 - and be
switched off by the first person it got in the way of.

The two addresses it tries are chosen so that a guard failing open costs nothing: `192.0.2.1` is
RFC 5737's documentation network, which is routed nowhere on the internet, and `.invalid` is the
name RFC 6761 reserves never to resolve. With the guard missing, the most any test here does is ask
a resolver about a name that cannot exist and send one packet to an address nobody holds - a lookup
that fails and a connection that times out, both ordinary `Exception`s, which is what the tests
below tell apart from the guard's own refusal.
"""

import socket
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Final, NoReturn
import pytest
from agl.adapters.github.fetcher import GitHubFetcher
from agl.ports.get_request import GetRequest
from instruments.offline import OffTheMachine

_TEST_NET: Final = "192.0.2.1"

_NEVER_A_HOST: Final = "agl-guard-probe.invalid"

_DISCARD: Final = 9

def _udp_to(host: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
        datagram.sendto(b"x", (host, _DISCARD))

def _connected_to(host: str) -> None:
    with socket.socket() as stream:
        stream.settimeout(1)
        stream.connect((host, _DISCARD))

def _connected_ex_to(host: str) -> None:
    with socket.socket() as stream:
        stream.settimeout(1)
        stream.connect_ex((host, _DISCARD))

def _refused_harder(*args: object, **kwargs: object) -> NoReturn:
    raise ConnectionRefusedError("closed harder, for one test")

_OFF_THE_MACHINE: Final[dict[str, Callable[[], object]]] = {
    "getaddrinfo": lambda: socket.getaddrinfo(_NEVER_A_HOST, 443),
    "gethostbyname": lambda: socket.gethostbyname(_NEVER_A_HOST),
    "gethostbyname_ex": lambda: socket.gethostbyname_ex(_NEVER_A_HOST),
    "gethostbyaddr": lambda: socket.gethostbyaddr(_TEST_NET),
    "getnameinfo": lambda: socket.getnameinfo((_TEST_NET, 80), 0),
    "create_connection by name": lambda: socket.create_connection((_NEVER_A_HOST, 443), 1),
    "create_connection by address": lambda: socket.create_connection((_TEST_NET, _DISCARD), 1),
    "connect by address": lambda: _connected_to(_TEST_NET),
    "connect by name": lambda: _connected_to(_NEVER_A_HOST),
    "connect_ex": lambda: _connected_ex_to(_TEST_NET),
    "sendto": lambda: _udp_to(_TEST_NET),
}

@pytest.mark.parametrize("door", sorted(_OFF_THE_MACHINE))
def test_every_door_to_a_host_off_this_machine_is_refused_before_anything_is_sent(
    door: str,
) -> None:
    """Every lookup and every connection `_poison` closes, refused here for a host that is not us.

    A name is refused at the lookup, because looking it up is itself a packet to a resolver; an
    address is refused at the connection, datagrams included; and a name handed straight to
    `connect` is refused too, since the C library would resolve that one without asking Python.
    """
    with pytest.raises(OffTheMachine):
        _OFF_THE_MACHINE[door]()

def test_what_the_guard_raises_is_no_exception_an_adapter_could_turn_into_an_answer() -> None:
    """An adapter translates what it catches, and a refused lookup must not come back polished.

    `GitHubFetcher` catches `OSError` and hands it back as "could not reach", which is right on an
    operator's machine and exactly wrong here: a test would see a tidy answer and never learn it
    had tried to reach codeload.github.com.
    """
    assert not issubclass(OffTheMachine, Exception)

@pytest.mark.asyncio
async def test_the_real_fetcher_at_its_default_address_is_stopped_rather_than_answered() -> None:
    """The case this guard was written for: the real adapter, built with nothing handed to it.

    It raises out of the fetch rather than returning a refusal, which is the whole difference
    between a test that reached for the network and was stopped and one that quietly passed.
    """
    (fetch,) = GetRequest.parsed(["octocat/Hello-World/wf"]).fetches

    with pytest.raises(OffTheMachine, match="codeload.github.com"):
        await GitHubFetcher().fetch(fetch)

def test_this_machine_is_reachable_by_address_by_name_and_over_ipv6() -> None:
    """Every instrument here is a listener on 127.0.0.1, and a guard refusing one breaks them."""
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        for host in ("127.0.0.1", "localhost"):
            with socket.create_connection((host, port), 1):
                pass
    if socket.has_ipv6:
        with socket.create_server(("::1", 0), family=socket.AF_INET6) as listener:
            with socket.create_connection(("::1", listener.getsockname()[1]), 1):
                pass

def test_a_datagram_to_this_machine_and_a_lookup_of_it_go_through() -> None:
    _udp_to("127.0.0.1")

    assert socket.gethostbyname("localhost") == "127.0.0.1"
    assert socket.getaddrinfo("127.0.0.1", 80)

def test_a_unix_socket_is_this_machine_whatever_path_it_is_bound_to() -> None:
    """`AF_UNIX` never leaves the host. Bound under `/tmp`, since macOS allows only 104 bytes."""
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        address = str(Path(directory) / "guard.sock")
        with socket.socket(socket.AF_UNIX) as server, socket.socket(socket.AF_UNIX) as client:
            server.bind(address)
            server.listen()
            client.connect(address)

def test_a_test_that_closes_the_doors_harder_puts_this_guard_back_and_not_the_originals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_poison` patches over the guard for one test, and its undoing must leave the guard up."""
    guarded = socket.getaddrinfo

    with monkeypatch.context() as harder:
        harder.setattr(socket, "getaddrinfo", _refused_harder)
        with pytest.raises(ConnectionRefusedError):
            socket.getaddrinfo("127.0.0.1", 80)

    assert socket.getaddrinfo is guarded
    with pytest.raises(OffTheMachine):
        socket.getaddrinfo(_NEVER_A_HOST, 443)
