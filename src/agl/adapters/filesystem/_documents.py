
import json
from collections.abc import Mapping
from typing import Final

from agl.ports.errors import InternalError
from agl.ports.home_layout import RunScope
from agl.ports.ids import StepName
from agl.ports.run import JsonValue

__all__ = ["_ENCODING", "_encoded", "_entry_address", "_record_address", "_scope_address"]


_ENCODING: Final = "utf-8"


def _encoded(value: Mapping[str, JsonValue], address: str, *, indent: int | None) -> bytes:
    try:
        text = json.dumps(dict(value), ensure_ascii=False, allow_nan=False, indent=indent)
        return text.encode(_ENCODING)
    except (TypeError, ValueError) as error:
        raise InternalError(
            f"{address} holds a value AGL cannot write down: {error}. A stored document is JSON, "
            f"and something above this port handed it one that is not"
        ) from error


def _scope_address(scope: RunScope) -> str:
    nesting = "/".join(str(namespace) for namespace in scope.namespaces)
    inside = f", inside {nesting}" if nesting else ""
    return f"project {str(scope.project)!r}, run {str(scope.label)!r}{inside}"


def _record_address(scope: RunScope) -> str:
    return f"the run record for {_scope_address(scope.run)}"


def _entry_address(scope: RunScope, step: StepName, digest: str) -> str:
    return f"the entry for step {str(step)!r} at digest {digest!r} in {_scope_address(scope)}"
