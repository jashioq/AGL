from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final
from agl.ports.agent import AgentTask, StopReason
from agl.ports.errors import InputError
from agl.ports.run import JsonValue

__all__ = ["Agent", "Call", "Reply"]

_NO_PAYLOAD: Final[Mapping[str, JsonValue]] = MappingProxyType({})

@dataclass(frozen=True, slots=True)
class Call:
    """One tool call an `Agent` makes: the name the role declared it under, and the arguments."""

    tool: str

    payload: Mapping[str, JsonValue] = _NO_PAYLOAD

    def __post_init__(self) -> None:
        if not self.tool:
            raise InputError(
                "a `Call` with an empty tool name names nothing a session could route: a model "
                "calls a tool by the name the role declared it under, and both agent fakes refuse "
                "a call to a tool the task does not declare - refused here, the line that needs "
                "fixing is the one on screen rather than one inside a run"
            )
        # A plain `dict` and never a `MappingProxyType`: a payload goes through `json.dumps` inside
        # both fakes on its way to a handler, and `json.dumps` has no encoder for a proxy.
        object.__setattr__(self, "payload", dict(self.payload))

@dataclass(frozen=True, slots=True)
class Reply:
    """One `Agent`'s answer to a task: its calls, its activity, what it says and why it stopped."""

    calls: Sequence[Call] = ()

    activity: Sequence[str] = ()

    says: str = ""

    stop_reason: StopReason | None = StopReason.COMPLETED

    def __post_init__(self) -> None:
        object.__setattr__(self, "calls", tuple(self.calls))
        object.__setattr__(self, "activity", tuple(self.activity))

type Agent = Callable[[AgentTask], Reply | Awaitable[Reply]]
