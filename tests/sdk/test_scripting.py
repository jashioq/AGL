"""`sdk/testing.py`'s vocabulary: what a `Call` and a `Reply` are, before any run has one.

The values a workflow author writes an agent out of. `config/container.py` is where they are
compiled into the callable each fake consumes and `tests/config/test_container.py` is what asserts
that compilation; what is left for this file is the three things these types decide on their own -
what they refuse, what they copy, and what they default to - because each of them is a decision that
would otherwise only show up as a failure somewhere else.

**The `MappingProxyType` test is the one worth explaining.** `Tool.payload_schema` is a proxy, which
costs the journal's walker a recursive `Mapping` case at every depth; `Call.payload` deliberately is
not, and the reason is two layers away from where it is declared: both agent fakes put a payload
through
`json.dumps(payload, allow_nan=False)` on its way to the handler, and `json.dumps` has no encoder
for a proxy. So a frozen payload would make every scripted tool call an `InputError` naming the
payload rather than the freezing. It was found by writing a `Reply` and running it, which is the
only way it could have been, and the test below is what keeps it found.
"""

import json
from dataclasses import FrozenInstanceError

import pytest

from agl.ports.agent import StopReason
from agl.ports.errors import InputError
from agl.ports.questions import Question
from agl.ports.run import JsonValue
from agl.sdk.testing import Call, Reply


def test_a_call_with_no_tool_name_is_refused_where_it_is_written() -> None:
    """`InputError` at declaration time, which is `arg()`'s register and `reporting_tool()`'s.

    Both fakes refuse a call to a tool the task does not declare, one layer down and after a run has
    started; the empty name is refused here, where the line that needs fixing is on screen.
    """
    with pytest.raises(InputError, match="names nothing a session could route"):
        Call("")


def test_a_calls_payload_is_copied_off_the_dict_it_was_handed() -> None:
    """`ports/store.py`'s rule about any mapping a caller hands over, at the other end of the run.

    An author building two calls out of one dict would otherwise find both of them holding whatever
    that dict said last - and the second one is the payload that reaches the reporting tool.
    """
    building: dict[str, JsonValue] = {"summary": "the first thing"}
    first = Call("report", building)
    building["summary"] = "the second thing"

    assert first.payload == {"summary": "the first thing"}
    assert first.payload is not building


def test_a_calls_payload_is_json_serialisable_and_not_a_mapping_proxy() -> None:
    """The trap the module docstring names, pinned rather than left to be re-found.

    A `MappingProxyType` here reads as the safe choice and is the one thing that cannot work: the
    payload is `json.dumps`ed inside both fakes on its way to the handler, and there is no encoder
    for a proxy. Asserted by dumping it, which is the operation that would fail, rather than by
    comparing the type - a second immutable mapping would fail this too, and should.
    """
    assert json.dumps(Call("report", {"summary": "clean", "high": 0}).payload, allow_nan=False)


def test_a_call_is_frozen_once_it_is_built() -> None:
    """A `Reply` is routinely a module-level constant shared by every task a test dispatches, so a
    call one of them could edit would be a call edited for all of them - `Role`'s own reason."""
    with pytest.raises(FrozenInstanceError):
        Call("report").tool = "something else"  # type: ignore[misc]


def test_a_reply_normalises_every_sequence_to_a_tuple() -> None:
    """A list the author goes on appending to must not change what an agent already did.

    All three, because each is a separate `object.__setattr__` and two of them being right is what a
    partial normalisation looks like.
    """
    calls = [Call("report")]
    asks = [Question(prompt="anything to add?")]
    activity = ["Edit: src/a.py"]

    reply = Reply(calls=calls, asks=asks, activity=activity)
    calls.append(Call("report_again"))
    asks.append(Question(prompt="and now?"))
    activity.append("Read: src/b.py")

    assert reply.calls == (Call("report"),)
    assert reply.asks == (Question(prompt="anything to add?"),)
    assert reply.activity == ("Edit: src/a.py",)


def test_an_empty_reply_is_an_agent_that_reported_nothing_and_completed() -> None:
    """`Reply()` is the shape a test about a reporting step whose agent never reported writes.

    `AgentOutcome` refuses defaults so that an adapter has to state both fields; this defaults both,
    because an author describing an effect step's agent genuinely has nothing to say. `COMPLETED`
    rather than `None`, because the agent ending its own turn is what happened.
    """
    reply = Reply()

    assert (reply.calls, reply.asks, reply.activity) == ((), (), ())
    assert (reply.says, reply.stop_reason) == ("", StopReason.COMPLETED)
