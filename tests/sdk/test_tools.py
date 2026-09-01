"""What a reporting-tool declaration promises: one dataclass, one schema, one typed result.

Four properties carry this suite. **The schema is asserted structurally**, as the whole object a
vendor is handed, because it is a stored format - it goes into a step's fingerprint, so a change to
how it is derived re-runs every step ever recorded, and a test that checked only "it has a `type`"
would let that change through. **Every refused field type is pinned by its message**, naming the
field, since the reader of an `InputError` is a workflow author looking for the line they wrote -
`tests/sdk/test_params.py` pins the same module's other refusals the same way. **A malformed
payload does not raise**, which is asserted by there being no `pytest.raises` around any of it:
the tool rejects one back to the agent inside the same conversation, and a suite that accepted an
exception would pass against exactly the design this module exists to implement. And **the round
trip is measured through `json.dumps`**, not asserted about, because "survives JSON unchanged" is
the rule the supported field list is derived from.

The fingerprint half is measured against `journal.base_of` rather than restated:
`tests/sdk/test_journal.py` already pins that a hand-built `Tool`'s handler is not a term, and what
is new here is that a tool *derived* from a declaration behaves the same way - and that its
description is a term, which is the standing example of a change that must re-run a step.

**One test in that half carries a claim the others do not.**
`test_editing_a_fields_description_changes_the_steps_base` is what makes a `describe()` on a payload
field worth having: `test_journal.py`'s qualified type name has one open hole, a `__post_init__`
being invisible to a derived schema, and a rule interpolated into a field's description is not,
because it is schema and schema is fingerprint. Everything else about `describe()` is convenience;
that one is the hole being closed, so it is measured against `base_of` and against two payloads
built under one name.

## Two classes, and the check that exists only because they are two

`ReportingTool[P]` reads as "a `Tool` with a payload and no handler", so folding the two into one
parametrised class gets proposed about once per reader - `tool()` below, which derives the same
schema and hands its handler a typed instance, makes the resemblance closer rather than weaker.
It does not survive contact with `Role[P]`. That parameter binds from the one member of
`Sequence[Tool | ReportingTool[P]]` that carries a payload type, and it binds **because the two
classes are disjoint**: make `ReportingTool` a subclass of one `Tool` and every mismatched
declaration type-checks, because a `ReportingTool[Other]` satisfies the bare `Tool` arm and `P` is
never bound at all. Four things pay for the merge, and each has a home here:

  1. *The layering.* `test_two_payload_types_of_one_shape_are_two_schemas_and_two_fingerprints`
     already writes it down in as many words - "`Tool` is a port type that must not learn what a
     payload class is" - and one class is exactly that sentence reversed. The derivation is ~205
     lines and either follows `payload` into `ports/` or stays here while `payload: type[P]` goes
     without it, which is the split that lets a bare `Tool(payload=…)` be written with no schema.
  2. *The check is recoverable, at a price.* The one spelling that keeps it is
     `tools: Sequence[Tool[P] | Tool[None]]` - more machinery rather than less, `Tool[Any]` in
     `AgentTask` and in `base_of`, and a hand-written overloaded constructor on a `ports/`
     dataclass, since a generated `__init__` is public and reopens what the overloads closed.
  3. *It deletes a refusal that exists.* Under that spelling a mixed *list* display quietly infers
     `Role[Findings | None]` where today it is refused at the declaration -
     `tests/sdk/test_roles.py::test_a_mixed_list_display_does_not_infer_p_and_says_so_at_the_declaration`,
     whose docstring says "the `type: ignore` is the assertion".
  4. *It opens a new hole on the shape `tool()` exists for.* A tool carrying both a payload and a
     handler would bind `P`, so `Role(tools=(that_one,))` infers `Role[Findings]` while `run.step`
     returns `None`. Two classes cannot have that hole: a handled tool is a `Tool` and carries no
     `P`, which is what `test_a_handled_tool_is_an_ordinary_tool_and_binds_no_role_parameter`
     measures.

And the distinction is not conventional. A reporting tool's payload is **the only value a tool call
can put on the journal** - `sdk/_engine/steps.py`'s `return None if capture is None else
capture.reported(outcome)` is the whole of it, and that value becomes `Entry.value`. Every other
tool, `tool()`'s included, answers with a `ToolResult` that every adapter turns into content for the
model and that reaches no store. One class buries that in `handler is None`.

**What the two classes do share is one line, and it is not the line above.** Both call
`ports.agent.check_tool_declaration` for the two refusals every tool declaration owes - an empty
name cannot be called, an empty description cannot be chosen - which used to be a byte-identical
copy in each. That fold is not the merge this section refuses and does not start it: it moves no
`payload` into `ports/`, derives no schema there, and leaves the two classes as disjoint as they
were, which is the only property `Role[P]` binds through.
`test_two_payload_types_of_one_shape_are_two_schemas_and_two_fingerprints` still holds - validating
a name and a description is not learning what a payload class is - and
`test_a_role_promising_one_payload_refuses_a_tool_that_reports_another` still spends the check.

`ARCHITECTURE.md`'s "No single `Tool` class" carries the argument; what is here is the measurement.
`test_a_role_promising_one_payload_refuses_a_tool_that_reports_another` spends the check, so a merge
that lost it fails a line instead of passing a review.
"""

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import FrozenInstanceError, asdict, dataclass, field, make_dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, assert_type
import pytest
from agl.ports.agent import Claude, Tool, ToolResult
from agl.ports.errors import InputError, InternalError
from agl.ports.run import JsonValue
from agl.sdk._engine.journal import base_of, canonical_json
from agl.sdk.roles import Role
from agl.sdk.tools import ReportingTool, describe, reporting_tool, tool

_HEAD: Final = "4a91c07f2b3e8d15c6a0b7f31d92e8054c6a0f13"

@dataclass(frozen=True)
class Finding:
    """A nested payload dataclass, with an optional field and two required ones."""

    file: str
    severity: str
    line: int | None = None

@dataclass(frozen=True)
class Findings:
    """The `findings = await run.step(reviewer())` / `findings.high()` shape, as a payload:
    one field of every supported kind, and the method the workflow calls on what comes back."""

    summary: str
    findings: list[Finding]
    confidence: float = 1.0
    blocking: bool = False
    tags: tuple[str, ...] = ()

    def high(self) -> list[Finding]:
        return [found for found in self.findings if found.severity == "high"]

REPORT: Final = reporting_tool("report_findings", "report what the review found", Findings)

_ONE_HIGH: Final[Mapping[str, JsonValue]] = MappingProxyType(
    {
        "summary": "one thing to fix",
        "findings": [
            {"file": "a.py", "severity": "high", "line": 3},
            {"file": "b.py", "severity": "low"},
        ],
        "tags": ["review"],
    }
)

async def _never_called(payload: Mapping[str, JsonValue]) -> ToolResult:
    """A handler is a callable and a callable's `repr` carries an object id, so no fingerprint may
    hold one. Nothing in this suite runs an agent, which is why nothing calls this."""
    return ToolResult(text="")

_HANDLER: Final[Callable[[Mapping[str, JsonValue]], Awaitable[ToolResult]]] = _never_called

def _tool[P](
    declared: ReportingTool[P],
    handler: Callable[[Mapping[str, JsonValue]], Awaitable[ToolResult]] = _HANDLER,
) -> Tool:
    """A declaration converted the way `Run.step` converts one: the three declared terms,
    plus a handler bound at dispatch. This is the only place in the suite that builds a `Tool`."""
    return Tool(
        name=declared.name,
        description=declared.description,
        payload_schema=declared.payload_schema,
        handler=handler,
    )

def _base(tool: Tool) -> str:
    """One step's base fingerprint, with every term but the tool held still."""
    return base_of(
        instructions="review the worktree",
        model=Claude.SONNET,
        restrictions=frozenset(),
        tools=(tool,),
        inputs={},
        head=_HEAD,
    )

# --- the derived schema, asserted as the whole object -------------------------------------------

def test_the_derived_schema_is_the_object_a_vendor_is_handed() -> None:
    """The stored format, in full. Nested objects, an optional as `anyOf`, arrays with their item
    schema, `required` holding exactly the fields with no default, `additionalProperties`, and the
    `title` the qualified-type-name rule puts on every payload type at every depth.

    `__name__` rather than the literal `"test_tools"`, for `test_run_step.py`'s reason: that string
    is pytest's import mode talking and not this file's claim. What *is* this file's claim is the
    shape - module, a dot, and the qualified name - and dropping either half of it fails here."""
    assert dict(REPORT.payload_schema) == {
        "type": "object",
        "title": f"{__name__}.Findings",
        "properties": {
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "title": f"{__name__}.Finding",
                    "properties": {
                        "file": {"type": "string"},
                        "severity": {"type": "string"},
                        "line": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    },
                    "required": ["file", "severity"],
                    "additionalProperties": False,
                },
            },
            "confidence": {"type": "number"},
            "blocking": {"type": "boolean"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["findings", "summary"],
        "additionalProperties": False,
    }

def test_the_schema_carries_the_two_keys_both_adapters_look_for() -> None:
    """`claude_code/_tools.py::_schema` and `openai/_tools.py::_advertised` each supply `type` and
    `properties` when a schema omits them - the Claude SDK re-reads a dict without both as a
    `{name: python type}` shorthand. A derived schema needs neither supplied."""
    schema = dict(REPORT.payload_schema)
    assert schema["type"] == "object"
    assert isinstance(schema["properties"], dict)

def test_the_schema_is_wrapped_the_way_a_tools_is() -> None:
    """`Tool.__post_init__`'s proxy, one layer earlier: a caller that kept a reference cannot edit a
    schema already inside a fingerprint. `json.dumps` refusing it is the whole hazard behind
    `test_journal.py` on what a tool contributes, and `base_of` handling it anyway is that rule
    being kept."""
    assert isinstance(REPORT.payload_schema, MappingProxyType)
    with pytest.raises(TypeError):
        json.dumps(REPORT.payload_schema)
    assert len(_base(_tool(REPORT))) == 64

def test_a_field_with_a_default_is_not_required_and_one_without_it_is() -> None:
    schema = dict(REPORT.payload_schema)
    assert schema["required"] == ["findings", "summary"]

def test_reordering_two_fields_costs_no_agent_run() -> None:
    """`required` is sorted, so a cosmetic edit does not move the fingerprint. `properties` needs no
    sorting of its own: it is a JSON object and canonical JSON sorts an object's keys.

    **The two payloads are built through `make_dataclass` under one name**, and that is the whole
    arrangement rather than an affectation: a payload type contributes its qualified name
    to the schema, so two `class` statements spelled `OneWay` and `TheOther` would differ in their
    `title` before a single field was reordered, and this test would pass while measuring nothing.
    `make_dataclass("Payload", ...)` names both the same and leaves the field order as the only
    difference there is - which is what the claim is actually about, an author moving one line
    inside one dataclass."""
    one_way = make_dataclass("Payload", [("alpha", str), ("beta", str)], frozen=True)
    the_other = make_dataclass("Payload", [("beta", str), ("alpha", str)], frozen=True)
    assert one_way.__qualname__ == the_other.__qualname__, "the arrangement this test rests on"

    # Annotated because `make_dataclass` answers a bare `type`, so there is nothing for `P` to be
    # solved from - which is the price of building the two payloads under one name, and is paid
    # here rather than by giving them two names and measuring nothing.
    one: ReportingTool[Any] = reporting_tool("report", "report it", one_way)
    other: ReportingTool[Any] = reporting_tool("report", "report it", the_other)
    assert dict(one.payload_schema) == dict(other.payload_schema)
    assert _base(_tool(one)) == _base(_tool(other))

def test_a_payload_with_no_fields_is_a_declaration_and_not_a_refusal() -> None:
    """A reporting tool whose payload has no fields still captures the one fact a reporting step
    turns on: that the agent fired it at all."""

    @dataclass(frozen=True)
    class Done:
        pass

    declared = reporting_tool("done", "say that you have finished", Done)
    assert dict(declared.payload_schema)["properties"] == {}
    assert declared.read({}) == Done()

# --- a field that says what it is: `describe()` ---------------------------------------------------
#
# A gap found and closed late. `sdk/tools.py`'s `_schema_for` refuses an enum field with every
# other type outside `_SUPPORTED`, and until `describe()` existed there was nowhere in a derived
# schema to write a vocabulary down: it lived in the tool's description and in the prompt, and was
# enforced a third time in a `__post_init__` - which `test_journal.py`'s qualified type name says
# the digest cannot see.

# A fixed vocabulary, which is the case `sdk/tools.py` refuses an enum in favour of and the one
# `describe()` exists for. Held as a constant here for the reason `fix/findings.py` holds
# `SEVERITIES`: the test below that widens it has to widen one thing.
_VOCABULARY: Final = ("high", "medium", "low")

@dataclass(frozen=True)
class Described:
    """One described field of each interesting shape: required, optional-with-a-default, and one
    left undescribed so that the untouched case is measured in the same object."""

    severity: str = describe("one of high, medium, low")
    line: int | None = describe("where in the file, or null", default=None)
    file: str = "unknown"

DESCRIBED: Final = reporting_tool("report", "report what you found", Described)

def test_a_described_field_carries_its_description_in_the_derived_schema() -> None:
    """The whole object, because it is a stored format: what a description does to the shape is
    add one key beside the ones that were there, on the field it was declared on and on no other.

    The optional is the interesting one - `describe()` puts the text on whatever the annotation
    derived, so an `anyOf` carries it as an annotation keyword beside its two arms rather than
    inside one of them, which is what makes the mechanism orthogonal to every supported field type.
    """
    assert dict(DESCRIBED.payload_schema) == {
        "type": "object",
        "title": f"{__name__}.Described",
        "properties": {
            "severity": {"type": "string", "description": "one of high, medium, low"},
            "line": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "description": "where in the file, or null",
            },
            "file": {"type": "string"},
        },
        "required": ["severity"],
        "additionalProperties": False,
    }

def test_describing_a_field_does_not_make_it_optional_and_a_default_still_does() -> None:
    """Required-ness is `dataclasses`' answer and not this module's, exactly as `arg()` leaves it:
    `describe(text)` is a `field()` with no default, so the field stays required, and
    `describe(text, default=…)` is one with a default, so it does not."""
    assert dict(DESCRIBED.payload_schema)["required"] == ["severity"]
    assert DESCRIBED.read({"severity": "low"}) == Described(severity="low")

def test_a_described_payload_converts_and_rejects_exactly_as_an_undescribed_one_does() -> None:
    """A description is prose for the model and nothing to the walker. It must not become a rule:
    `_converted` never reads one, so the field is checked at its declared type and no further."""
    assert DESCRIBED.rejection({"severity": "not in the list", "line": 3}) is None
    assert DESCRIBED.read({"severity": "not in the list", "line": 3}) == Described(
        severity="not in the list", line=3
    )
    refusal = DESCRIBED.rejection({"severity": 3})
    assert refusal is not None and "`report.severity` should be a string" in refusal

def test_an_undescribed_payload_derives_exactly_what_it_derived_before() -> None:
    """Most payload fields need no description, and the mechanism must cost them nothing - not a
    `"description": null`, not an empty string, not a key at all. Asserted against the suite's own
    `Findings`, whose full schema is pinned at the top of this file with no `description` in it."""
    properties = dict(REPORT.payload_schema)["properties"]
    assert isinstance(properties, dict)
    for name, schema in properties.items():
        assert isinstance(schema, dict), f"{name} derived something that is not a schema object"
        assert "description" not in schema, (
            f"the undescribed field {name!r} derived a `description` anyway. Every digest ever "
            f"written over this payload holds the schema, so a key that appears for a field "
            f"nobody described re-runs every step that reports through it"
        )

def test_a_description_that_says_nothing_is_refused_where_it_is_written() -> None:
    """`ReportingTool.__post_init__`'s refusal of an empty *tool* description, one level down and
    for its reason: an empty string is a term in every digest this payload writes and is nothing at
    all to the model. Declaration time, like every other refusal in this module."""
    with pytest.raises(InputError) as refused:
        describe("   \n  ")
    assert "description" in str(refused.value)

# --- every refused field type, each naming the field ---------------------------------------------

class Severity(StrEnum):
    HIGH = "high"

@dataclass(frozen=True)
class HasMapping:
    counts: dict[str, int]

@dataclass(frozen=True)
class HasSet:
    files: set[str]

@dataclass(frozen=True)
class HasEnum:
    severity: Severity

@dataclass(frozen=True)
class HasFixedTuple:
    span: tuple[int, str]

@dataclass(frozen=True)
class HasBareList:
    items: list  # type: ignore[type-arg]  # the bare annotation is the point of this one

@dataclass(frozen=True)
class HasWideUnion:
    line: str | int

@dataclass(frozen=True)
class HasThreeArmedOptional:
    line: str | int | None

@dataclass(frozen=True)
class HasPath:
    where: Path

@dataclass(frozen=True)
class HasNothing:
    nothing: None

@dataclass(frozen=True)
class HasAny:
    anything: Any

@dataclass(frozen=True)
class Node:
    """A payload that contains itself, at module level so that the forward reference resolves and
    the refusal is the cycle's own rather than the annotation's."""

    children: list[Node]

@pytest.mark.parametrize(
    ("payload", "named"),
    [
        (HasMapping, "counts"),
        (HasSet, "files"),
        (HasEnum, "severity"),
        (HasFixedTuple, "span"),
        (HasBareList, "items"),
        (HasWideUnion, "line"),
        (HasThreeArmedOptional, "line"),
        (HasPath, "where"),
        (HasNothing, "nothing"),
        (HasAny, "anything"),
    ],
)
def test_an_unsupported_field_type_is_refused_naming_the_field(
    payload: type[object], named: str
) -> None:
    """Refused where it is declared, not at the call that would have gone wrong - `sdk/params.py`'s
    stance, and its reason: a package that cannot be invoked correctly should not import."""
    with pytest.raises(InputError) as refusal:
        reporting_tool("report", "report it", payload)
    assert named in str(refusal.value)

def test_a_payload_that_contains_itself_is_refused_rather_than_recursing() -> None:
    """Without this the derivation is a `RecursionError`, which names nothing an author can fix."""
    with pytest.raises(InputError) as refusal:
        reporting_tool("report", "report it", Node)
    assert "children" in str(refusal.value)

def test_an_annotation_that_cannot_be_resolved_is_refused_where_it_is_written() -> None:
    """`sdk/params.py`'s refusal, for the same reason: the fields are read for their types, so each
    has to name something importable from where the dataclass is. Built through `make_dataclass`
    because PEP 649 resolves a forward reference written the ordinary way, even a local one."""
    payload = make_dataclass("Payload", [("nested", "Nowhere")], frozen=True)
    with pytest.raises(InputError) as refusal:
        reporting_tool("report", "report it", payload)
    assert "cannot be resolved" in str(refusal.value)

def test_a_payload_that_is_not_a_dataclass_is_refused() -> None:
    with pytest.raises(InputError) as refusal:
        reporting_tool("report", "report it", str)
    assert "builtins.str" in str(refusal.value)

def test_a_payload_instance_where_the_class_belonged_is_refused() -> None:
    """`read` builds an instance of `payload`, so an instance is one the tool cannot build and
    whose fields already hold what the agent was going to be asked for. `sdk/workflow.py` refused
    this in the same words about a params class until that class was read off an annotation,
    where a type is all it can be - a payload is an argument, so this is the layer it survives."""
    with pytest.raises(InputError) as refusal:
        reporting_tool("report", "report it", Findings(summary="", findings=[]))  # type: ignore[arg-type]
    assert "never an instance" in str(refusal.value)

def test_an_empty_name_and_an_empty_description_are_refused_as_a_tools_would_be() -> None:
    """The same two checks a `Tool` makes, made where the declaration is written.

    "As a tool's would be" is now literal rather than a resemblance: both classes call
    `ports.agent.check_tool_declaration`, which is where the two `raise`s live and where
    `tests/ports/test_agent.py` argues why they are one implementation instead of two copies.
    This is the `ReportingTool` half of that claim, and it is what makes "one checker, two classes"
    measurable - a fold that quietly left this class checking nothing would pass over there.
    """
    with pytest.raises(InputError):
        reporting_tool("", "report it", Findings)
    with pytest.raises(InputError):
        reporting_tool("report", "", Findings)

# --- a valid payload, and the round trip ---------------------------------------------------------

def test_a_valid_payload_becomes_the_instance_the_workflow_declared() -> None:
    assert REPORT.rejection(_ONE_HIGH) is None
    assert REPORT.read(_ONE_HIGH) == Findings(
        summary="one thing to fix",
        findings=[Finding("a.py", "high", 3), Finding("b.py", "low")],
        tags=("review",),
    )

def test_an_absent_optional_field_leaves_the_dataclasss_own_default() -> None:
    """Nothing is passed for it, so the default written on the author's line is what stands."""
    read = REPORT.read({"summary": "nothing", "findings": []})
    assert (read.confidence, read.blocking, read.tags) == (1.0, False, ())

def test_an_instance_survives_the_round_trip_through_json_unchanged() -> None:
    """instance -> payload -> `json.dumps` -> payload -> instance, equal. This is the rule the
    supported field list is derived from, so it is measured rather than asserted about."""
    original = Findings(
        summary="two things",
        findings=[Finding("a.py", "high", 3), Finding("b.py", "low")],
        confidence=0.25,
        blocking=True,
        tags=("review", "spec"),
    )
    written = json.dumps(asdict(original))
    assert REPORT.read(json.loads(written)) == original

def test_a_json_array_comes_back_as_the_sequence_its_field_declared() -> None:
    """JSON has one bracket for a list and a tuple, so the declared type is the only thing that can
    tell them apart on the way back - which is what makes `tuple[X, ...]` round-trip at all."""
    read = REPORT.read({"summary": "x", "findings": [], "tags": ["a", "b"]})
    assert isinstance(read.tags, tuple)
    assert isinstance(read.findings, list)

def test_no_payload_this_module_accepts_is_one_the_journal_would_refuse() -> None:
    """A payload instance travels on into the next step's `**inputs` - the tickets example passes
    `findings=highs` - where `journal._canonical` fingerprints it and refuses what it cannot walk.
    The supported field list is drawn inside that walker's set, and this is the measurement."""
    assert canonical_json({"findings": REPORT.read(_ONE_HIGH)})

# --- the rejection path: every malformed shape answers, and none of them raises -------------------

def test_an_unknown_key_is_rejected_and_names_the_key_and_the_fields_there_are() -> None:
    refusal = REPORT.rejection({"summary": "x", "findings": [], "notes": "extra"})
    assert refusal is not None
    assert "notes" in refusal
    assert "summary" in refusal

def test_a_missing_required_key_is_rejected_and_says_what_was_expected() -> None:
    refusal = REPORT.rejection({"summary": "x"})
    assert refusal is not None
    assert "report_findings.findings" in refusal
    assert "required" in refusal

def test_a_wrongly_typed_value_is_rejected_naming_the_field_and_what_arrived() -> None:
    refusal = REPORT.rejection({"summary": 3, "findings": []})
    assert refusal is not None
    assert "report_findings.summary" in refusal
    assert "a string" in refusal
    assert "3" in refusal

def test_a_fault_nested_inside_an_array_is_rejected_at_its_own_path() -> None:
    refusal = REPORT.rejection({"summary": "x", "findings": [{"file": "a.py"}]})
    assert refusal is not None
    assert "report_findings.findings[0].severity" in refusal

def test_a_field_declared_as_an_object_and_sent_as_a_string_is_rejected() -> None:
    refusal = REPORT.rejection({"summary": "x", "findings": ["not an object"]})
    assert refusal is not None
    assert "report_findings.findings[0]" in refusal

def test_true_is_not_a_whole_number() -> None:
    """`bool` is an `int` in Python and `true` is not a number in JSON, so coercing here would let a
    model answer a count with a flag - `journal._canonical` takes the same care for the same reason.
    """
    refusal = REPORT.rejection(
        {"summary": "x", "findings": [{"file": "a.py", "severity": "high", "line": True}]}
    )
    assert refusal is not None
    assert "report_findings.findings[0].line" in refusal

def test_a_whole_number_is_accepted_for_a_float_field() -> None:
    """JSON writes `2.0` as `2`, so refusing an int here refuses a value this module produced."""
    assert REPORT.read({"summary": "x", "findings": [], "confidence": 1}).confidence == 1.0

def test_a_non_finite_number_is_rejected_rather_than_stored() -> None:
    """`json.loads` reads a bare `Infinity` token - which is not in JSON's grammar - as a float, and
    the store refuses to write one down as an `InternalError`. Caught here, the model is told."""
    refusal = REPORT.rejection(json.loads('{"summary": "x", "findings": [], "confidence": NaN}'))
    assert refusal is not None
    assert "report_findings.confidence" in refusal
    assert "a finite number" in refusal

def test_null_for_a_field_that_is_not_optional_is_rejected() -> None:
    refusal = REPORT.rejection({"summary": None, "findings": []})
    assert refusal is not None
    assert "report_findings.summary" in refusal

def test_null_for_an_optional_field_is_accepted() -> None:
    sent = {"file": "a.py", "severity": "low", "line": None}
    assert REPORT.read({"summary": "x", "findings": [sent]}).findings[0].line is None

def test_every_problem_in_one_payload_is_reported_at_once() -> None:
    """A model told about one fault per turn pays a turn per fault, and there is a live session
    holding the reasoning that produced the call - which is the whole of the argument."""
    refusal = REPORT.rejection(
        {"summary": 3, "notes": "extra", "findings": [{"severity": 1}], "blocking": "yes"}
    )
    assert refusal is not None
    assert refusal.count("\n  - ") == 5

def test_a_payload_dataclass_that_refuses_its_own_value_rejects_rather_than_raising() -> None:
    """A payload states its own rules in `__post_init__`, the way every dataclass here does. On a
    fresh call that belongs in front of the model with everything else."""

    @dataclass(frozen=True)
    class Bounded:
        score: int

        def __post_init__(self) -> None:
            if self.score < 0:
                raise InputError("a score is not negative")

    declared = reporting_tool("report", "report it", Bounded)
    refusal = declared.rejection({"score": -1})
    assert refusal is not None
    assert "a score is not negative" in refusal

# --- read, and what a failure means on the way back off the ledger -------------------------------

def test_a_recorded_value_that_no_longer_fits_the_payload_is_an_internal_error() -> None:
    """AGL wrote the value and AGL is reading it, so a disagreement is ours - `journal.py`'s test
    for whose fault an error is. The fingerprint is expected to have discarded this entry; the
    module docstring records the two ways it may not have."""
    with pytest.raises(InternalError) as fault:
        REPORT.read({"summary": "x"})
    assert "report_findings" in str(fault.value)

def test_a_recorded_value_that_is_not_an_object_at_all_is_an_internal_error() -> None:
    """`read` takes `object`: a parsed file is anything, an effect step's recorded `null` too."""
    with pytest.raises(InternalError):
        REPORT.read(None)

# --- the fingerprint consequences -----------------------------------------------------------------

def test_editing_a_derived_tools_description_changes_the_steps_base() -> None:
    """Why the role is in the fingerprint: halt, edit, resume, and you must not replay what the old
    wording produced. Measured against `base_of`, not restated."""
    reworded = reporting_tool(REPORT.name, "report every problem you found", Findings)
    assert _base(_tool(REPORT)) != _base(_tool(reworded))

def test_editing_a_fields_description_changes_the_steps_base() -> None:
    """**The whole point of `describe()`, and the measurement the gap above asked for.**

    The one open hole in `test_journal.py`'s qualified type name is that a `__post_init__` is
    invisible to a derived schema, so a payload whose vocabulary is enforced in code and named
    nowhere else changes what converts while moving no digest - and an entry recorded under the
    old vocabulary stops converting with its fingerprint still matching, which surfaces as
    `InternalError` out of `read` on a resume.
    `fix/findings.py` wrote that down as the accepted price of checking `SEVERITIES`.

    A field description is data, and data is in the schema, and the schema is in `base_of`. So a
    payload that interpolates its vocabulary into `describe()` moves the digest when the vocabulary
    moves, the stale entry is never read, and "a stale entry is discarded rather than failing
    to parse" is true of it. This is that sentence measured rather than asserted: the two payloads
    below differ in one field's description and in nothing else at all.

    Both halves, for `test_two_payload_types_of_one_shape_are_two_schemas_and_two_fingerprints`'
    reason: the schema because it is the stored format, and the base because that is the sentence
    anybody cares about - these are two steps, and the first one's result is not the second's.

    **The two payloads are built through `make_dataclass` under one name**, which is
    `test_reordering_two_fields_costs_no_agent_run`'s arrangement and is load-bearing here for the
    mirror-image reason. A payload type contributes its qualified name to the schema as `title`, so
    two `class` statements would already differ before a word of the description changed, and this
    test would be green while measuring the qualified type name instead of the thing `describe()`
    opened.
    """
    one = make_dataclass(
        "Payload", [("severity", str, describe(f"one of {', '.join(_VOCABULARY)}"))], frozen=True
    )
    widened = make_dataclass(
        "Payload",
        [("severity", str, describe(f"one of {', '.join((*_VOCABULARY, 'critical'))}"))],
        frozen=True,
    )
    assert one.__qualname__ == widened.__qualname__, "the arrangement this test rests on"

    before: ReportingTool[Any] = reporting_tool("report", "report it", one)
    after: ReportingTool[Any] = reporting_tool("report", "report it", widened)
    was, now = dict(before.payload_schema), dict(after.payload_schema)
    assert was["title"] == now["title"], "the two payloads differ in more than one field's wording"
    assert was["required"] == now["required"]
    assert was["properties"] != now["properties"]
    assert _base(_tool(before)) != _base(_tool(after))

def test_a_derived_tools_handler_is_not_a_term_in_the_base() -> None:
    """`tests/sdk/test_journal.py` pins this for a hand-built `Tool`; what is new is that a tool
    `Run.step` derives from a declaration behaves identically. It has to: the handler is bound per
    invocation, closing over that one call's capture cell, so a base holding one would differ from
    itself on the next call."""

    async def other(payload: Mapping[str, JsonValue]) -> ToolResult:
        return ToolResult(text="a different handler entirely")

    assert _base(_tool(REPORT)) == _base(_tool(REPORT, other))

def test_editing_the_payload_dataclass_changes_the_steps_base() -> None:
    """The cascade: change what the agent is asked to report, and the step re-runs."""

    @dataclass(frozen=True)
    class Wider:
        summary: str
        findings: list[Finding]
        confidence: float = 1.0
        blocking: bool = False
        tags: tuple[str, ...] = ()
        reviewed_at: str = ""

    widened = reporting_tool(REPORT.name, REPORT.description, Wider)
    assert _base(_tool(REPORT)) != _base(_tool(widened))

def test_two_payload_types_of_one_shape_are_two_schemas_and_two_fingerprints() -> None:
    """The second half of the qualified type name, and a leak found and closed during the build.

    Structurally identical payload types used to derive a byte-identical schema, so swapping
    `Findings` for a `Review` of the same shape left the fingerprint where it was and the old entry
    replayed **into the new type**: the expensive direction, a false cache hit rather than a re-run,
    with nothing failing to parse and the run carrying on with the wrong thing. "A stale
    entry is discarded rather than failing to parse" is only true once the qualified name is in the
    terms, and the `title` is where it is.

    Both halves are asserted. The schema, because it is the stored format and the only place a
    reporting tool can carry identity at all - `base_of` hashes a tool's name, its description and
    its schema, and `Tool` is a port type that must not learn what a payload class is. And the base,
    because that is the sentence anybody actually cares about: these are two steps."""

    @dataclass(frozen=True)
    class SameShape:
        summary: str
        findings: list[Finding]
        confidence: float = 1.0
        blocking: bool = False
        tags: tuple[str, ...] = ()

    twin = reporting_tool(REPORT.name, REPORT.description, SameShape)
    assert dict(twin.payload_schema)["properties"] == dict(REPORT.payload_schema)["properties"], (
        "the two payloads no longer have one shape, so this measures something else entirely"
    )
    assert dict(twin.payload_schema)["title"] != dict(REPORT.payload_schema)["title"]
    assert _base(_tool(REPORT)) != _base(_tool(twin))

def test_a_nested_payload_types_name_is_a_term_too_and_not_only_the_outermost() -> None:
    """The depth, which is the whole of the implementation - `test_journal.py`'s qualified type
    name as `journal._canonical` keeps it, word for word, one walker over an input and one over a
    payload.

    A name written once at the top of `payload_schema` would leave `Outer(inner=Inner)` and
    `Outer(inner=Other)` one fingerprint, which is the same false cache hit one level down. The two
    outer types are therefore built under **one** name through `make_dataclass`, so that the only
    difference between the two schemas is the type of a nested field: an implementation that tags
    the outermost payload and nothing else passes every version of this test that lets the outer
    names differ."""
    inner = make_dataclass("Inner", [("tokens", int)], frozen=True)
    other = make_dataclass("Other", [("tokens", int)], frozen=True)
    one = make_dataclass("Outer", [("nested", inner)], frozen=True)
    twin = make_dataclass("Outer", [("nested", other)], frozen=True)
    assert one.__qualname__ == twin.__qualname__, "the arrangement this test rests on"

    declared: ReportingTool[Any] = reporting_tool("report", "report it", one)
    swapped: ReportingTool[Any] = reporting_tool("report", "report it", twin)
    assert dict(declared.payload_schema)["title"] == dict(swapped.payload_schema)["title"]
    assert _base(_tool(declared)) != _base(_tool(swapped))

def test_the_name_in_a_title_is_the_qualified_one_and_not_the_bare_class_name() -> None:
    """Two payload classes spelled `Payload` in two scopes are two types, and a workflow that
    swapped one for the other changed what it asks for - `journal.py` says the same of two
    identically-named dataclasses in two modules. `__name__` would call these one type."""

    def one() -> type[object]:
        @dataclass(frozen=True)
        class Payload:
            summary: str

        return Payload

    def other() -> type[object]:
        @dataclass(frozen=True)
        class Payload:
            summary: str

        return Payload

    first, second = one(), other()
    assert first.__name__ == second.__name__, "the arrangement this test rests on"
    declared = reporting_tool("report", "report it", first)
    swapped = reporting_tool("report", "report it", second)
    assert dict(declared.payload_schema)["title"] != dict(swapped.payload_schema)["title"]
    assert _base(_tool(declared)) != _base(_tool(swapped))

# --- the type chain the SDK promises --------------------------------------------------------------

async def _step[P](declared: ReportingTool[P], payload: Mapping[str, JsonValue]) -> P:
    """A stand-in for `Run.step`, carrying the declaration's type parameter through the way
    that method must. Nothing here is the journal; the point is what mypy makes of the result."""
    return declared.read(payload)

@pytest.mark.asyncio
async def test_the_payload_type_carries_through_to_what_the_workflow_calls() -> None:
    """`findings = await run.step(reviewer())` then `findings.high()`. `assert_type`
    is the half `mypy --strict` checks; the call below is the half pytest checks."""
    findings = await _step(REPORT, _ONE_HIGH)
    assert_type(findings, Findings)
    assert [found.file for found in findings.high()] == ["a.py"]

# --- `tool()`: the same derivation, behind a handler the workflow wrote ---------------------------
#
# A reporting tool is a declaration the engine binds a handler to; `tool()` is the other half of the
# same machinery - an ordinary `agl.ports.agent.Tool` whose schema is derived from a payload
# dataclass and whose handler is the workflow's own, called with the payload already built. Nothing
# below is a second derivation: the assertions are written as equalities against `REPORT`, which is
# what makes "100% reuse" a measurement rather than a claim about the source.

def _applier(seen: list[Findings]) -> Callable[[Findings], Awaitable[ToolResult]]:
    """A workflow's own handler: it takes the payload *class* rather than a mapping, which is the
    whole of what `tool()` buys over a hand-built `Tool`. `seen` is how a test sees what arrived."""

    async def _apply(payload: Findings) -> ToolResult:
        seen.append(payload)
        return ToolResult(text=f"{len(payload.findings)} findings")

    return _apply

def test_a_handled_tool_derives_what_a_declaration_over_the_same_payload_derives() -> None:
    """One derivation serving both, asserted as equality rather than as a claim about the source.

    The schema is the stored format and `base_of` hashes it, so a `tool()` that had grown its own
    deriver would be a second format free to drift - and the drift would surface as two steps where
    an author wrote one. The base is asserted too, over a tool holding the same name and description
    as `REPORT`: equal digests are the sentence that the handler is not a term and the payload type
    reached the digest the one way it can, through the schema's `title`.
    """
    seen: list[Findings] = []
    handled = tool(REPORT.name, REPORT.description, Findings, _applier(seen))
    assert dict(handled.payload_schema) == dict(REPORT.payload_schema)
    assert _base(handled) == _base(_tool(REPORT))

@pytest.mark.asyncio
async def test_the_handler_is_handed_the_payload_dataclass_and_not_the_mapping() -> None:
    """`Tool.handler` takes a `Mapping[str, JsonValue]` because that is what a vendor delivers, and
    a workflow author should never write the walk from one to a dataclass. So the conversion is the
    factory's, and what the author's function is called with is the instance - methods, defaults,
    `tuple` fields and all, exactly what `ReportingTool.read` returns off the ledger."""
    seen: list[Findings] = []
    handled = tool("apply_findings", "act on what the review found", Findings, _applier(seen))

    answered = await handled.handler(_ONE_HIGH)

    assert seen == [REPORT.read(_ONE_HIGH)]
    assert isinstance(seen[0].tags, tuple), "the handler was given something JSON-shaped instead"
    assert [found.file for found in seen[0].high()] == ["a.py"]
    assert answered == ToolResult(text="2 findings")

@pytest.mark.asyncio
async def test_a_payload_the_handler_cannot_take_is_refused_in_the_declarations_own_words() -> None:
    """A model that sent the wrong shape gets one correctable message whichever kind of tool it
    called, which is why `_refusal` is shared rather than reimplemented here: asserted as equality
    against `ReportingTool.rejection`, so a second wording would fail this line.

    And the handler is not called at all. Half-built payloads never reach a workflow's code, so an
    author's function may read `payload.summary` without asking whether a summary arrived.
    """
    seen: list[Findings] = []
    handled = tool(REPORT.name, REPORT.description, Findings, _applier(seen))

    refused = await handled.handler({"summary": 3, "findings": [], "notes": "extra"})

    assert refused.rejected
    assert refused.text == REPORT.rejection({"summary": 3, "findings": [], "notes": "extra"})
    assert "report_findings.summary" in refused.text
    assert seen == [], "the handler ran on a payload that did not convert"

@pytest.mark.asyncio
async def test_a_handler_that_answers_is_content_for_the_model_and_never_an_entry() -> None:
    """The one runtime difference between the two kinds, from the tool's own side: an ordinary
    tool's answer is a `ToolResult`, which every adapter turns into content sent back into the
    session. Only a reporting tool's payload becomes `Entry.value`, and it does so in
    `sdk/_engine/steps.py` rather than here - `tests/sdk/test_run_step.py` is where that half is
    driven. What this pins is that `tool()` produces the ordinary shape and nothing more."""
    seen: list[Findings] = []
    handled = tool("apply_findings", "act on what the review found", Findings, _applier(seen))
    answered = await handled.handler(_ONE_HIGH)
    assert isinstance(answered, ToolResult)
    assert not answered.rejected

def test_a_handled_tools_payload_is_refused_by_the_same_rules_a_declarations_is() -> None:
    """`_check_payload` and the schema walk, reached through the other factory: refused where the
    tool is written, for `reporting_tool()`'s reason - a package that cannot be invoked correctly
    should not import.

    **Asserted as equality against the declaration's refusal, and that equality is the point.**
    Both factories reach one `_check_payload` and one schema walk, so the two messages are the same
    string over the same name - a `tool()` that grew a wording of its own would be a second
    vocabulary for one rule, and the two would be free to drift the way the schema derivation is
    not allowed to. Written this way rather than as a substring match so that the whole message is
    compared and not the half somebody remembered.

    **And neither of them may say "reporting tool"**, which is the clause that would silently drift
    back. Both messages named one until the shared helpers were reached by a second factory: an
    author who wrote `tool(...)` and handed it a class read a refusal about a concept their tool is
    not, and went looking for the reporting tool they had not declared. `_refusal` is deliberately
    not covered by this - a payload the model got wrong is refused in wording that is correct for
    both kinds and is asserted as shared, one section up.
    """

    async def _never(payload: object) -> ToolResult:
        raise AssertionError("a handler was called on a tool that should not have been built")

    with pytest.raises(InputError) as not_a_dataclass:
        tool("apply", "apply it", str, _never)
    with pytest.raises(InputError) as declared_not_a_dataclass:
        reporting_tool("apply", "apply it", str)
    assert "builtins.str" in str(not_a_dataclass.value)
    assert str(not_a_dataclass.value) == str(declared_not_a_dataclass.value)

    with pytest.raises(InputError) as unsupported:
        tool("apply", "apply it", HasMapping, _never)
    with pytest.raises(InputError) as declared_unsupported:
        reporting_tool("apply", "apply it", HasMapping)
    assert "counts" in str(unsupported.value)
    assert str(unsupported.value) == str(declared_unsupported.value)

    for refused in (not_a_dataclass, unsupported):
        assert "reporting tool" not in str(refused.value), (
            f"a payload refusal reached through `tool()` calls the thing a reporting tool: "
            f"{str(refused.value)!r}. These two messages are shared with `reporting_tool()` and "
            f"have to be true of both - an author of an ordinary handled tool who is told what a "
            f"reporting tool cannot do has been sent to look for a declaration they never wrote."
        )

# --- one tool class or two, and the check that rests on there being two ---------------------------
#
# The module docstring holds the argument and `ARCHITECTURE.md`'s "No single `Tool` class" holds it
# at length. These two are the mechanical half: the check the disjointness buys, and the hole it
# cannot have.

def test_a_role_promising_one_payload_refuses_a_tool_that_reports_another() -> None:
    """`Role[Findings]` declared with a `ReportingTool[Described]`, refused at the declaration.

    **The `type: ignore` is the assertion**, `tests/sdk/test_roles.py`'s idiom: `--strict` turns on
    `warn_unused_ignores`, so a mypy - or a `Tool`/`ReportingTool` merge - that stopped refusing
    this fails on this line rather than passing quietly and handing a workflow a `Described` under
    an `assert_type(…, Findings)`.

    The runtime half is asserted beside it for the same reason `test_roles.py` asserts it: nothing
    is wrong with the *value*, and a reader who met only the ignore would go looking for a refusal
    that does not exist. `Role.__post_init__` has no opinion here and could not have one - one
    reporting tool is one reporting tool, and which payload type a role was annotated with is not
    a thing a `Role` instance can see.
    """
    mismatched: Role[Findings] = Role(
        name="review",
        instructions="review the worktree",
        tools=(DESCRIBED,),  # type: ignore[arg-type]
    )
    assert [declared.name for declared in mismatched.tools] == [DESCRIBED.name]

def test_a_handled_tool_is_an_ordinary_tool_and_binds_no_role_parameter() -> None:
    """The hole one class would open, measured as absent.

    A tool with a payload *and* a handler is the shape the next deliverable wants, and under a
    single parametrised `Tool` it would bind `P` - so `Role(tools=(handled,))` would infer
    `Role[Findings]` while `run.step` returned `None`, and `.summary` on the result would be an
    `AttributeError` with mypy clean. Here it cannot: `tool()` returns an
    `agl.ports.agent.Tool`, which carries no payload type, so the role is `Role[None]` and a
    workflow that wanted a payload has to declare a reporting tool and say so.
    """
    seen: list[Findings] = []
    handled = tool("apply_findings", "act on what the review found", Findings, _applier(seen))
    assert_type(handled, Tool)
    assert isinstance(handled, Tool)
    assert not isinstance(handled, ReportingTool)

    offered = Role(name="apply", instructions="apply what the review found", tools=(handled,))
    assert_type(offered, Role[None])
    assert [declared.name for declared in offered.tools] == ["apply_findings"]

# --- the re-export half --------------------------------------------------------------------------

def test_tool_and_tool_result_are_the_ports_own_types_and_not_copies() -> None:
    """`sdk/tools.py` is a facade *and* a module with logic; this is the facade half. A workflow
    author's `Tool` has to be the one that crosses `AgentTask.tools`, or nothing it builds fits."""
    from agl.ports import agent
    from agl.sdk import tools

    assert tools.Tool is agent.Tool
    assert tools.ToolResult is agent.ToolResult

def test_a_declaration_is_not_a_tool_and_carries_no_handler() -> None:
    """The design constraint the module is built on: `AgentTask.tools` holds ordinary `Tool`s, so
    the adapter never learns which one is the reporting one, and a `Role` reused across concurrent
    runs holds nothing that belongs to one of them."""
    assert not isinstance(REPORT, Tool)
    assert not hasattr(REPORT, "handler")

def test_a_declaration_holds_the_three_terms_a_tool_contributes_to_a_fingerprint() -> None:
    """`test_journal.py` on what a tool contributes, and why a declaration without a handler is
    the honest shape."""
    derived = _tool(REPORT)
    assert (derived.name, derived.description) == (REPORT.name, REPORT.description)
    assert dict(derived.payload_schema) == dict(REPORT.payload_schema)

def test_a_declaration_is_frozen() -> None:
    """It is a module-level value shared across steps and across concurrent runs."""
    with pytest.raises(FrozenInstanceError):
        REPORT.name = "renamed"  # type: ignore[misc]

def test_the_default_factory_case_is_optional_too() -> None:
    """`dataclasses` insists on a field with neither a default nor a default factory, and that is
    the whole of what "required" means here - a sentinel of our own would answer it twice."""

    @dataclass(frozen=True)
    class Collected:
        names: list[str] = field(default_factory=list)

    declared = reporting_tool("collect", "report what you collected", Collected)
    assert dict(declared.payload_schema)["required"] == []
    assert declared.read({}) == Collected()

def test_a_sequence_of_declarations_is_ordinary_data() -> None:
    """Tools keep their declared order and are not sorted (`test_journal.py` on what a tool
    contributes), so a `Role` holding two of these is holding a sequence and nothing more."""
    declarations: Sequence[ReportingTool[Findings]] = (REPORT,)
    assert [declared.name for declared in declarations] == ["report_findings"]
