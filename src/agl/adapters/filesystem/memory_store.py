
import json
from collections.abc import Mapping
from typing import Final

from agl.ports.errors import InternalError
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store

__all__ = ["MemoryStore"]


_ENCODING: Final = "utf-8"


type _EntryAddress = tuple[RunScope, StepName, str]


class MemoryStore(Store):

    def __init__(self) -> None:
        self._records: dict[RunScope, bytes] = {}
        self._entries: dict[_EntryAddress, bytes] = {}

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        return _decoded(self._records.get(scope.run))

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        payload = _encoded(value, _record_address(scope))
        self._records[scope.run] = payload

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        return _decoded(self._entries.get((scope, step, digest)))

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        payload = _encoded(value, _entry_address(scope, step, digest))
        self._entries[(scope, step, digest)] = payload

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        depth = len(scope.namespaces)
        found = {
            recorded.namespaces[depth]
            for recorded, _, _ in self._entries
            if _within(recorded, scope) and len(recorded.namespaces) > depth
        }
        return tuple(sorted(found, key=str))

    async def remove(self, scope: RunScope) -> None:
        if not scope.namespaces:
            self._records.pop(scope.run, None)
        for address in [address for address in self._entries if _within(address[0], scope)]:
            del self._entries[address]


def _within(address: RunScope, scope: RunScope) -> bool:
    return (
        address.project == scope.project
        and address.label == scope.label
        and address.namespaces[: len(scope.namespaces)] == scope.namespaces
    )


def _encoded(value: Mapping[str, JsonValue], address: str) -> bytes:
    try:
        return json.dumps(dict(value), ensure_ascii=False, allow_nan=False).encode(_ENCODING)
    except (TypeError, ValueError) as error:
        raise InternalError(
            f"{address} holds a value AGL cannot write down: {error}. A stored document is JSON, "
            f"and something above this port handed it one that is not"
        ) from error


def _decoded(payload: bytes | None) -> dict[str, JsonValue] | None:
    if payload is None:
        return None
    document: dict[str, JsonValue] = json.loads(payload.decode(_ENCODING))
    return document


def _scope_address(scope: RunScope) -> str:
    nesting = "/".join(str(namespace) for namespace in scope.namespaces)
    inside = f", inside {nesting}" if nesting else ""
    return f"project {str(scope.project)!r}, run {str(scope.label)!r}{inside}"


def _record_address(scope: RunScope) -> str:
    return f"the run record for {_scope_address(scope.run)}"


def _entry_address(scope: RunScope, step: StepName, digest: str) -> str:
    return f"the entry for step {str(step)!r} at digest {digest!r} in {_scope_address(scope)}"
