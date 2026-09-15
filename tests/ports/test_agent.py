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
    ChosenClaude,
    ChosenOpenAI,
    Claude,
    ClaudeEffort,
    ModelId,
    OpenAI,
    OpenAIEffort,
    Provider,
    Restriction,
    StopReason,
    Tool,
    ToolResult,
    model_of,
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
        "SOL": "openai:sol",
        "TERRA": "openai:terra",
        "LUNA": "openai:luna",
    }
    assert {member.name: member.value for member in ClaudeEffort} == {
        "LOW": "low",
        "MEDIUM": "medium",
        "HIGH": "high",
        "XHIGH": "xhigh",
        "MAX": "max",
    }
    assert {member.name: member.value for member in OpenAIEffort} == {
        "LOW": "low",
        "MEDIUM": "medium",
        "HIGH": "high",
        "XHIGH": "xhigh",
        "MAX": "max",
        "ULTRA": "ultra",
    }

def test_a_chosen_effort_is_recorded_under_its_class_path_and_two_field_names() -> None:
    """The rest of the stored format a composite contributes, pinned beside the enum values.

    `sdk/_engine/journal.py`'s canonicaliser tags a dataclass with its `module.qualname` and writes
    every field under its name, so moving either class, renaming it or renaming a field moves the
    digest of every step recorded at a chosen effort - and every one of them would re-run.
    """
    for chosen in (ChosenClaude, ChosenOpenAI):
        assert chosen.__module__ == "agl.ports.agent"
        assert [field.name for field in fields(chosen)] == ["model", "effort"]
    assert ChosenClaude.__qualname__ == "ChosenClaude"
    assert ChosenOpenAI.__qualname__ == "ChosenOpenAI"

# --- A model with its effort chosen --------------------------------------------------------------

def test_a_member_called_with_an_effort_is_that_member_and_that_level_and_not_a_string() -> None:
    """The author's spelling, and the value it builds.

    Not a `str`: a composite that subclassed one would be its bare member's text through `str()`,
    and `tests/sdk/test_journal.py` measures that collision. `model_of` is the one derivation of the
    bare member, walked here over every member of both enums so a new model is covered on arrival.
    """
    assert Claude.OPUS(effort=ClaudeEffort.XHIGH) == ChosenClaude(Claude.OPUS, ClaudeEffort.XHIGH)
    assert OpenAI.LUNA(effort=OpenAIEffort.ULTRA) == ChosenOpenAI(OpenAI.LUNA, OpenAIEffort.ULTRA)
    assert not isinstance(Claude.OPUS(effort=ClaudeEffort.LOW), str)
    for model in _model_ids():
        assert model_of(model) is model
    for claude in Claude:
        assert model_of(claude(effort=ClaudeEffort.MAX)) is claude
    for openai in OpenAI:
        assert model_of(openai(effort=OpenAIEffort.MAX)) is openai

def test_every_effort_level_is_accepted_on_every_model_of_its_provider() -> None:
    """AGL holds no table of which model has which level, and this is the measurement of that.

    Level sets differ per model and move whenever a vendor ships one - a Haiku with no effort at
    all, a model without `xhigh` - and the vendor's tool clamps a level a model lacks. A table here
    would refuse, on the day a model gained a level, a choice the tool would already have honoured.
    """
    for claude in Claude:
        for claude_level in ClaudeEffort:
            assert claude(effort=claude_level).effort is claude_level
    for openai in OpenAI:
        for openai_level in OpenAIEffort:
            assert openai(effort=openai_level).effort is openai_level

def test_a_choice_mypy_refuses_is_refused_at_run_time_as_well() -> None:
    """A string spelling a level, another provider's effort, and another provider's model.

    Each `type: ignore` is half the assertion - `--strict` warns on an unused one, so a signature
    that stopped refusing one of these fails this file at the type level - and the `InputError` is
    the other half, because a workflow is not always type-checked and this is what its author meets
    at the declaration instead.
    """
    with pytest.raises(InputError):
        Claude.OPUS(effort="max")  # type: ignore[arg-type]
    with pytest.raises(InputError):
        OpenAI.SOL(effort=ClaudeEffort.MAX)  # type: ignore[arg-type]
    with pytest.raises(InputError):
        ChosenClaude(OpenAI.SOL, ClaudeEffort.MAX)  # type: ignore[arg-type]

def test_a_member_called_without_an_effort_is_a_type_error_and_not_the_bare_member() -> None:
    """`Claude.OPUS()` could have meant "the default effort", and that is spelled `Claude.OPUS`."""
    with pytest.raises(TypeError):
        Claude.OPUS()  # type: ignore[call-arg]

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
    """A tool with no name cannot be called, and one with no description cannot be chosen.

    **The two refusals are `check_tool_declaration`'s, and it is on `__all__` although it is not
    a type.** `ports/run.py`'s `checked_text` is the precedent and the argument is the same one:
    `sdk/tools.py`'s `ReportingTool` had a byte-identical copy of both `raise`s, error prose
    included, because it declares the same two fields for the same reader - a model choosing which
    tool to call. Two spellings of one rule is one spelling free to be wrong, and the way it would
    be wrong here is quiet: a `ReportingTool` that accepted an empty description would hand a
    vendor a tool the model has nothing to choose it by, and every test about payloads would still
    pass. One implementation with two call sites, folded into `ports/` because that is the only
    direction contract 1 permits.

    This test is one of the two that reach it - `tests/sdk/test_tools.py`'s
    `test_an_empty_name_and_an_empty_description_are_refused_as_a_tools_would_be` is the other, and
    both are needed: a checker only one class actually called would leave the other silently
    unchecked with this file still green.
    """
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
    with pytest.raises(FrozenInstanceError):
        Claude.OPUS(effort=ClaudeEffort.LOW).effort = ClaudeEffort.MAX  # type: ignore[misc]
