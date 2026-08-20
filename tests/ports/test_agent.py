"""What the agent port promises: routable models, stored enum values, and tasks that could run.

`AgentRunner` itself is not touched here - not even a null implementation - because a suite that
writes its own subject writes a subject that passes. The contract belongs to the stage that writes
the first real adapter, checked against both of them.

What is left is genuine logic, and three properties carry it. **`ModelId.provider`** is derived,
not stored, so it is checked over every member by walking the subclasses rather than by listing
them - a model added in a later stage is covered the moment it exists - and the malformed case is
constructed here, since no member of the shipped enums can be one. **The enum values are pinned by
hand**, one at a time, for `test_errors.py`'s reason: they sit inside a step's fingerprint, which
is written down, so a change to one should have to be typed twice. And **`AgentOutcome`'s field
list** is pinned because the port's design lives in what that type does not carry: a session id or
a token count appearing there is the failure this whole module was written to prevent, and it would
arrive looking like a helpful addition.
"""

from collections.abc import Mapping
from dataclasses import MISSING, FrozenInstanceError, fields
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from agl.ports.agent import (
    AgentOutcome,
    AgentTask,
    Capability,
    Claude,
    ModelId,
    OpenAI,
    Provider,
    Restriction,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.errors import InputError, InternalError
from agl.ports.run import JsonValue


async def _reply(payload: Mapping[str, JsonValue]) -> ToolResult:
    """A handler nothing here calls: `Tool` requires one, and no test in this file runs an agent."""
    return ToolResult(text=str(payload))


_TOOL: Final = Tool(
    name="report_tickets",
    description="Hand the framework the tickets you decided on.",
    payload_schema={"type": "object"},
    handler=_reply,
)

_TASK: Final = AgentTask(
    instructions="Decompose the request into tickets.",
    workspace=Path("/trees/auth/_base"),
    model=Claude.OPUS,
    restrictions=frozenset({Restriction.NO_VCS_WRITES}),
    tools=(_TOOL,),
)


def _model_ids() -> list[ModelId]:
    """Every model id AGL ships, found by subclass rather than listed - see the module docstring.

    Filtered by `__module__`, `test_errors.py`'s technique for the same hazard: the malformed enum
    a test below declares is a `ModelId` subclass too, and it is not one of the module's own.
    """
    return [
        member
        for enum in ModelId.__subclasses__()
        if enum.__module__ == ModelId.__module__
        for member in enum
    ]


# --- Models are routable ------------------------------------------------------------------------


def test_every_model_id_names_a_provider_it_can_be_routed_to() -> None:
    """The property routing dispatches on, over every member: prefix, separator, and a model."""
    assert set(_model_ids()) == {*Claude, *OpenAI}, "both shipped enums are in the sweep"
    for model in _model_ids():
        provider, separator, name = model.value.partition(":")
        assert separator == ":", f"{model.value!r} has no provider prefix"
        assert model.provider == Provider(provider)
        assert name, f"{model.value!r} names a provider and then no model"


def test_a_model_id_whose_prefix_names_no_provider_is_our_bug() -> None:
    """`InternalError` and not `InputError`: nobody types a model id, so this file wrote it wrong.

    Both malformed shapes are here - no prefix at all, and a prefix naming nothing - because one
    `partition` covers both and a test that only tries one would not notice if it stopped.
    """

    class _Malformed(ModelId):
        UNPREFIXED = "banana"
        UNKNOWN_PROVIDER = "banana:split"

    for model in _Malformed:
        with pytest.raises(InternalError):
            _ = model.provider


# --- The values that get written down -----------------------------------------------------------


def test_the_enum_values_are_the_strings_a_fingerprint_holds() -> None:
    """Pinned by hand, because these are a stored format and not an implementation detail."""
    assert {member.name: member.value for member in Provider} == {
        "CLAUDE": "claude",
        "OPENAI": "openai",
    }
    assert {member.name: member.value for member in Restriction} == {
        "NO_VCS_WRITES": "no_vcs_writes",
        "NO_FILE_WRITES": "no_file_writes",
        "NO_SHELL": "no_shell",
        "NO_NETWORK": "no_network",
    }
    assert {member.name: member.value for member in Capability} == {
        "FILE_EDIT": "file_edit",
        "SHELL": "shell",
        "MID_RUN_QUESTIONS": "mid_run_questions",
        "TOOL_CALLING": "tool_calling",
    }
    assert {member.name: member.value for member in StopReason} == {
        "COMPLETED": "completed",
        "LIMIT": "limit",
    }
    assert {member.name: member.value for member in _model_ids()} == {
        "OPUS": "claude:opus",
        "SONNET": "claude:sonnet",
        "HAIKU": "claude:haiku",
        "GPT5": "openai:gpt-5",
    }


def test_an_outcome_carries_two_fields_and_an_adapter_states_both() -> None:
    """The list this module is most likely to grow a vendor assumption into, pinned.

    No defaults, either: `None` means "the backend did not say" and `""` means "it said nothing",
    and both are things an adapter should have to state rather than fall into.
    """
    assert [field.name for field in fields(AgentOutcome)] == ["stop_reason", "text"]
    assert all(field.default is MISSING for field in fields(AgentOutcome))
    assert AgentOutcome(stop_reason=None, text="") == AgentOutcome(stop_reason=None, text="")


# --- Defaults, and what a task refuses -----------------------------------------------------------


def test_a_task_defaults_to_no_context_and_to_changing_things() -> None:
    """The two optional fields, and the one on `ToolResult`. Planning has to be asked for."""
    assert _TASK.context is None
    assert _TASK.plan_only is False
    assert ToolResult(text="done").rejected is False


@pytest.mark.parametrize(
    "task",
    [
        pytest.param({"instructions": ""}, id="asks for nothing"),
        pytest.param({"workspace": Path("trees/auth")}, id="a workspace found, not carried"),
        pytest.param({"tools": (_TOOL, _TOOL)}, id="a call resolving to two handlers"),
    ],
)
def test_a_task_that_could_not_be_run_is_refused(task: dict[str, object]) -> None:
    """`InputError`: a workflow author declared this, and nothing has been attempted yet."""
    fields_ = {
        "instructions": _TASK.instructions,
        "workspace": _TASK.workspace,
        "model": _TASK.model,
        "restrictions": _TASK.restrictions,
        "tools": _TASK.tools,
        **task,
    }
    with pytest.raises(InputError):
        AgentTask(**fields_)  # type: ignore[arg-type]


@pytest.mark.parametrize("blank", ["name", "description"])
def test_a_tool_the_model_could_not_choose_is_refused(blank: str) -> None:
    """A tool with no name cannot be called, and one with no description cannot be chosen."""
    declared = {
        "name": _TOOL.name,
        "description": _TOOL.description,
        "payload_schema": {},
        "handler": _reply,
        blank: "",
    }
    with pytest.raises(InputError):
        Tool(**declared)  # type: ignore[arg-type]


def test_a_declared_schema_cannot_be_edited_afterwards() -> None:
    """It goes into a fingerprint, so a caller keeping the dict it passed must not be able to move
    what that fingerprint was taken over."""
    schema: dict[str, JsonValue] = {"type": "object"}
    tool = Tool(name="t", description="d", payload_schema=schema, handler=_reply)
    schema["type"] = "string"
    assert tool.payload_schema == {"type": "object"}
    assert isinstance(tool.payload_schema, MappingProxyType)


def test_the_values_are_frozen() -> None:
    """Every type here is a value: checked once on the way in, and not editable afterwards."""
    with pytest.raises(FrozenInstanceError):
        _TASK.plan_only = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _TOOL.name = "something_else"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ToolResult(text="done").rejected = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        AgentOutcome(stop_reason=StopReason.COMPLETED, text="").text = "x"  # type: ignore[misc]
