"""`Tool`, `ToolResult`, and `reporting_tool()` - what makes a step a reporting step.

**This is not one of `ARCHITECTURE.md` §5's pure re-export facades.** `sdk/terminal.py` and
`sdk/questions.py` are, and hold no logic; this module re-exports `ports.agent.Tool` - and
`ToolResult`, which anybody writing a handler needs - *and* carries the reporting-tool declaration,
which derives a JSON Schema from a dataclass and validates payloads against it. §5's sentence is
about those two modules and this one is the exception to it, said here so that a reader who arrives
from that table is not surprised to find code.

## The two step kinds, which this module's presence or absence decides

§3.3 gives `run.step` exactly two shapes, and the difference is whether the Role declares one of
these:

- **Reporting step** - declares a reporting tool. Its result is that tool's payload, and if the
  agent returns without firing it there is no result and the step re-runs. That is
  `RoleIncompleteError`, which lives in `sdk/roles.py` (12.2) - the name says Role, and `roles.py`
  imports this module, so defining it here would be a cycle. Nothing below needs it.
- **Effect step** - no reporting tool. The result is `null` and the effect is commits.

**Agents never write to the store.** A reporting tool is a *capture* mechanism: the agent calls it,
the tool validates the payload and hands it back, and the framework stores it as the step result.
One write path, one ledger.

## The declaration is a distinct type from `Tool`, and it carries no handler

`ReportingTool` is structurally a `Tool` minus its handler, plus the payload type, and the missing
handler is the whole reason it is its own type rather than a `Tool` with a convenient constructor.

**A `Role` is a module-level value.** It is declared once beside the prompt and reused across steps
and across concurrent runs - §3.3's own tickets example gives every child worktree the same
`implementer`. Capturing a payload means writing it somewhere, so a handler built *here* would close
over a cell shared by every invocation that role ever serves, and two siblings reporting at once
would each read the other's findings. `Run.step` (12.1) converts a declaration into an ordinary
`ports.agent.Tool` at dispatch time, binding a handler that closes over that one invocation's
capture cell, and the shared-state failure is then unrepresentable rather than avoided.

**And `AgentTask.tools` must hold ordinary `Tool`s**, which is what keeps §3.3's rule that the
adapter must not learn which tool is the reporting one. `ports/agent.py` spends a paragraph on it
and both adapters are built around it: every tool is wrapped identically, the handler is invoked,
its `text` goes back into the conversation. Nothing here may require either of them to change, and
nothing here does - a declaration never crosses the port.

So the fields below are the three terms a tool contributes to a fingerprint (§3.6 rule 4: `name`,
`description`, `payload_schema` - and *not* `handler`, which is a callable whose `repr` embeds an
object id), plus the payload type the framework deserializes with. A declaration without a handler
is the honest shape of exactly that list.

**Generic in its payload type**, so that the chain §3.3 promises type-checks: 12.2's `Role[P]`
carries it, 12.1's `Run.step` returns it, and `findings = await run.step("review", reviewer)`
followed by `findings.high()` is checked rather than hoped for.

## What a payload field may be, and what is refused

A payload becomes an entry's `value`, and an entry's `value` is JSON (`ports/run.py::JsonValue`).
It has to survive dataclass -> JSON -> dataclass unchanged, and a payload instance also travels on
into the next step's `**inputs`, where `_engine/journal.py`'s walker fingerprints it. Both rules
point the same way and the list is short:

    str  bool  int  float          a nested payload dataclass
    list[X] and tuple[X, ...] of any of these        X | None

Everything else is refused where it is declared, naming the field and its type, exactly as
`sdk/params.py` refuses a field type nothing can parse. What is left out, and why:

* **`dict`** - a payload is a shape a model is *told* to produce, and every key it will hold is a
  field the author can name. An open map is where the schema stops describing the payload: the
  model gets no guidance about the keys and the workflow gets a mapping it must re-check by hand,
  which is the validation this module exists to have done once, in one place.
* **Enums, including `StrEnum`** - an enum member is not a JSON value; it is a Python object whose
  `value` happens to be one. `StrEnum` and `IntEnum` round-trip by accident of inheritance and
  every other `Enum` does not, so admitting them would make the list a rule a reader has to test
  rather than read. A field whose values are a fixed set is a `str` field declared
  `severity: str = describe(f"one of {', '.join(SEVERITIES)}")` - see the next section, which is
  where that advice acquired a spelling.
* **Fixed-length tuples** (`tuple[int, str]`) - JSON Schema spells one with `prefixItems`, which is
  draft 2020-12, and the schema crosses to two vendors untouched with no promise about which draft
  either reads. A heterogeneous fixed-length array is also a record whose parts have no names, and
  a record with named parts is a nested dataclass.
* **Unions other than `X | None`** - a payload whose shape depends on which arm the model picked is
  one the workflow has to ask about before it can use it, which is the check this module exists to
  have already made.
* **A payload dataclass that contains itself** - it has no finite schema, and the refusal is what
  stops the derivation being a `RecursionError` instead.

## A field may say what it is, and what it says is a fingerprint term

`describe()` puts a `description` on one field's schema. Every field without one derives exactly
what it derived before, which is the ordinary case: most payload fields are named well enough that
a sentence about them would be the field name again.

**What it is for is the sentence above about enums.** Until 19.2 that advice - *a field whose
values are a fixed set is a `str` field whose description names them* - had nowhere to be written.
`_schema_for` rendered a `str` as `{"type": "string"}` and nothing else, so a payload's own
vocabulary could only be stated in the *tool's* description and in the prompt, and enforced a third
time in the payload's `__post_init__`. `fix/findings.py` wrote all three and priced the third: §3.6
rule 6 makes a `__post_init__` invisible to the derived schema, so editing `SEVERITIES` changed
what converts while moving no digest, and an entry recorded under the old vocabulary could stop
converting with its fingerprint still matching - `InternalError` out of `read`, on a resume. A
description is a schema term and a schema term is a `base_of` term, so a vocabulary interpolated
into one moves every digest that depends on it, and the price is not paid at all.

**Where the text comes from: `dataclasses.field(metadata=...)`, which is `sdk/params.py`'s
mechanism read twice.** `arg()` already attaches a declaration to a dataclass field this way, under
one namespaced key, with typeshed's own overload trick keeping `request: str = arg(...)` legal
under `--strict`; `describe()` is the same three lines against the same `dataclasses` feature, and a
second mechanism for *attach a declaration to a field* would be one more thing for a reader to hold.
Two candidates were weighed against it:

* **`typing.Annotated[str, <marker>]`** is the near miss. It is static, needs no I/O, survives
  `from __future__ import annotations`, and it is orthogonal to defaults where `field(metadata=)`
  has to keep `default=` reachable through an overload. What it costs is that the marker then rides
  on the *annotation*, so `_hints` needs `include_extras=True` and all three walkers that dispatch
  on an annotation - `_schema_for`, `_converted` and `_wording` - have to peel a wrapper that is
  not a type before they can ask what the type is. That is the type-reading path learning about
  something that is not a type, in three places, to hold a string that belongs to a field.
* **The attribute docstring** - the bare string expression after a field, which this repository
  uses on every field there is - reads best of the three at the call site and is refused for the
  one reason that outranks that: it would make **every docstring under a payload a stored format**.
  A schema is hashed into every digest ever written, so tightening the prose on `Finding.summary`
  would re-run the review step. Docstrings here are load-bearing and edited often, and a mechanism
  that charges an agent run for improving one is a mechanism that teaches people not to. (It also
  needs `ast` or `inspect` over the payload's source at import, which a zipimport or a `-OO` build
  does not have to be able to hand over.)

So the description is opt-in and explicit, and the thing that costs a re-run is the thing the author
wrote *in order to* be read by the model.

## The derived schema is a stored format

It goes into `base_of`'s `role.tools[].payload_schema`, so **changing how a schema is derived
re-runs every step ever recorded** - the same warning `ports/agent.py` puts on its enum values and
`journal.py` puts on `_TYPE_KEY`. Three consequences are built in rather than left to be found:
`required` is **sorted**, so that reordering two fields - which changes nothing anyone can observe -
does not cost an agent run; `properties` is left in declaration order, because it is a JSON object
and canonical JSON sorts an object's keys anyway, so the order is free to be the one the model reads
best; and `title` holds the payload type's **qualified name**, at every depth, which is §3.6 rule 6
reaching the one place a reporting tool can carry it. `_object_schema` argues that one where it is
written. A field's `description` is in the format on the same terms and the section above says what
that buys: editing one re-runs every step that reports through the payload, which is the point of it
rather than a cost of it.

`additionalProperties: false` is included because the alternative is a schema that permits what the
handler refuses. An unknown key is a rejection below whatever the schema says, so saying `false` is
what lets a backend that validates before the handler - Claude Code's SDK does - reach the same
answer one step earlier, in the same conversation either way.

`payload_schema` is wrapped in a `MappingProxyType`, one level, exactly as `Tool.__post_init__`
does, so a caller cannot edit a schema already inside a fingerprint. Everything below the top level
is a plain `dict`, which is what `json.dumps` and both adapters want, and what the journal's walker
rebuilds at every depth regardless.

## A malformed payload is a rejection, not an exception

§3.3: it is rejected by the tool **back to the agent within the same conversation**, so the model
corrects itself - not an adapter retry, not a workflow retry, and not an exception. `rejection`
answers that question and `ToolResult.rejected` is the channel 12.1 puts the answer on. Every
problem in a payload is reported at once, with its path, what was expected and what arrived: a model
told about one fault at a time pays a turn per fault.

Value-level refusals stop at the JSON line. This module refuses a payload value that **is not
JSON** - a non-finite float, which `json.loads` produces from a bare `Infinity` token that is not in
the grammar. It does not scan strings for lone surrogates, which are valid JSON that AGL cannot
write down: `adapters/filesystem/store.py::_encoded` makes that refusal deliberately, at the write,
and names an agent's reporting-tool payload as the way one arrives. A second copy here would be a
second source of truth about a rule that module already argues at length. See the note below.

## On replay the same conversion runs, and there a failure is ours

§3.6: "the Role declares the payload type and the framework deserializes on read". `read` is that
one function, used on a fresh run - after `rejection` has already answered `None` - and on replay
against a recorded value. A recorded value that will not convert is AGL's ledger disagreeing with
AGL's code, which is `journal.py`'s own test for who a fault belongs to, so `read` raises
`InternalError` and `rejection` is the only path that produces prose for a model.

**§3.6 says a stale entry is discarded rather than failing to parse, and that this "falls out
free": changing the dataclass changes the schema, which changes the fingerprint. It was not
airtight.** 12.3 reported two leaks. 13.0 closed one and left the other, and both are worth reading
together, because the one that is left is the one nothing can close from here:

1. **Closed at 13.0: the schema carried the payload's shape and not its identity.** Swapping
   `Findings` for a structurally identical `Review` derived byte-identical schemas, so the
   fingerprint did not move and the old entry replayed into the new type - `journal.py`'s rule 6
   (`Finding("T-01", 3)` against `Ticket("T-01", 3)`) with the qualified type name missing, and the
   expensive direction of it: a false cache hit rather than a re-run, with nothing failing to parse
   and the wrong type handed back to a run that carries on. `_object_schema` now writes that
   qualified name into the derived schema as `title`, at every depth, which puts it in
   `base_of`'s terms without `Tool` growing a field the port has no use for.
2. **Open in general, and payable per rule since 19.2: the schema describes shape, and a dataclass
   validates in `__post_init__`.** That is how every dataclass in this repository states its rules,
   and adding or tightening one changes what converts while changing nothing in the derived schema -
   so a recorded value really can stop converting with its fingerprint still matching. That is the
   case §3.6 says cannot happen, and §3.6 rule 6 names this exception itself: a `__post_init__` "is
   invisible to a derived schema". `read` turns it into an `InternalError` naming the payload type,
   which is the honest report and not a fix.

   **What `describe()` changes is that a payload can now buy its way out of this one rule at a
   time.** A `__post_init__` is invisible because it is code and the schema is data; a rule
   *interpolated into a field's description* is data, so it moves the digest and the stale entry is
   discarded exactly as §3.6 promises. `fix/findings.py` is the worked example - one `SEVERITIES`,
   read by the field description and by the check - and the general leak is still open for every
   rule an author does not state where the model can read it. That is a bearable shape for it: a
   check the model is never told about is one the model cannot satisfy on purpose anyway.

What *does* fall out free is now every structural change and every change of identity: a field
added, removed, renamed or retyped moves `properties` or `required`, and renaming or moving the
payload class moves `title`, so the fingerprint moves and the entry is never read. The argument
holds for the shape of a payload and for which type it is, and not for what a payload means.
"""

from collections.abc import Callable, Mapping
from dataclasses import MISSING, Field, dataclass, field, fields, is_dataclass
from math import isfinite
from types import MappingProxyType, UnionType
from typing import Any, Final, get_args, get_origin, get_type_hints, overload

from agl.ports.agent import Tool, ToolResult
from agl.ports.errors import InputError, InternalError
from agl.ports.run import JsonValue

__all__ = ["ReportingTool", "Tool", "ToolResult", "describe", "reporting_tool"]

# The four field types that are a JSON scalar, each with the word JSON Schema uses for it and the
# words a *model* is told when it sends something else. One table and not two, so that a type
# cannot be supported by the schema and unmentionable in a refusal, or the reverse.
_SCALARS: Final[Mapping[object, tuple[str, str]]] = MappingProxyType(
    {
        str: ("string", "a string"),
        bool: ("boolean", "true or false"),
        int: ("integer", "a whole number"),
        float: ("number", "a finite number"),
    }
)

# The whole of what a payload field may be, in one sentence, spelled once because it is the tail of
# every refusal this module makes at declaration time. The module docstring argues each omission.
_SUPPORTED: Final = (
    "a payload field is a str, a bool, an int, a float, another payload dataclass, a `list[X]` or "
    "`tuple[X, ...]` of any of those, or `X | None`"
)

# How much of an offending value goes into a message the model reads. Long enough to identify what
# it sent, short enough that a payload holding a whole file does not become the refusal.
_SHOWN = 80

# Where `describe()` leaves a field's description, and where `_description` looks for it. Namespaced
# for `sdk/params.py::_METADATA_KEY`'s reason and spelled the same way: `Field.metadata` is one open
# mapping shared with whatever else an author puts there, so a bare `"description"` would be a name
# this module has no claim on. A payload dataclass reaching this key by hand rather than through
# `describe()` is not a case worth a refusal - the key says whose it is - so anything under it that
# is not a `str` is simply not a description.
_METADATA_KEY: Final = "agl.sdk.tools"


@dataclass(frozen=True, slots=True)
class ReportingTool[P]:
    """A reporting tool as the workflow declares it: a `Tool` minus its handler, plus its payload
    type. Built by `reporting_tool` below, carried by 12.2's `Role`, converted into a real `Tool`
    by 12.1's `Run.step` - see the module docstring for why the handler is not here.

    Frozen and slotted for `Role`'s reason: this is a module-level value, shared across steps and
    across concurrent runs, and the one thing it must never hold is state belonging to one of them.
    """

    name: str
    """What the model calls it - `Tool.name`, and one of the three terms in the fingerprint."""

    description: str
    """What the model reads to decide whether to call it. Prose, in the author's own words."""

    payload: type[P]
    """The dataclass the payload is read into. The *class*: `read` builds an instance of it, and
    that instance is what `run.step` hands back to the workflow at the type it declared."""

    payload_schema: Mapping[str, JsonValue] = field(init=False)
    """The JSON Schema object derived from `payload`, and the third fingerprint term.

    Derived in `__post_init__` rather than passed in, so that the schema and the payload type
    cannot come apart: a hand-written schema promising the model one shape while `read` enforced
    another would be a rejection loop nobody could read their way out of."""

    def __post_init__(self) -> None:
        # `Tool.__post_init__`'s two checks, one layer earlier and in its words - a declaration
        # that could not become a usable `Tool` should be refused where it is written, not at the
        # dispatch that would have gone wrong.
        if not self.name:
            raise InputError("a tool with an empty name cannot be named by anything calling it")
        if not self.description:
            raise InputError(
                f"tool {self.name!r} has an empty description, and the description is the whole of "
                f"what the model reads to decide whether this tool is the one it wants"
            )
        _check_payload(self.payload, self.name)
        object.__setattr__(
            self, "payload_schema", MappingProxyType(_object_schema(self.payload, self.name, ()))
        )

    def rejection(self, payload: Mapping[str, JsonValue]) -> str | None:
        """What the model must be told about `payload`, or `None` when there is nothing to tell.

        §3.3's rejection path, and the reason it answers rather than raises: by the time a call is
        malformed there is a session in flight holding all the reasoning that produced it, and the
        cheap fix is for the model to send another one. 12.1 puts this text on a
        `ToolResult(rejected=True)`; nothing here decides how it is framed.

        Every problem at once, each with its path inside the payload, what was expected and what
        arrived - a model told about one fault per turn pays a turn per fault.
        """
        _, problems = self._read(payload)
        return None if not problems else _refusal(self.name, problems)

    def read(self, value: object) -> P:
        """`value` as an instance of the payload dataclass, or `InternalError`.

        Takes `object` because on replay the value came off the ledger, and a parsed file is
        anything - `Entry.from_json` takes `object` for the same reason.

        **Both callers have already been given the chance to disagree politely.** On a fresh run
        `rejection` answered `None` moments ago, so a failure here is a walker that disagrees with
        itself; on replay the value is one AGL wrote and AGL is reading, so a failure is our ledger
        disagreeing with our code. `journal.py`'s module docstring is the argument for both being
        `InternalError` - the class names whose fault it is, and this one is nobody else's. The
        module docstring says why the second is reachable at all when §3.6 says it is not.
        """
        instance, problems = self._read(value)
        if instance is None:
            raise InternalError(
                f"a recorded {self.name} payload does not fit {_describe(self.payload)}: "
                f"{_refusal(self.name, problems)}. AGL wrote this value and AGL is reading it, so "
                f"the ledger and the payload type have come apart - §3.6 expects the fingerprint "
                f"to have discarded this entry, and `sdk/tools.py` records why it may not have"
            )
        return instance

    def _read(self, value: object) -> tuple[P | None, tuple[str, ...]]:
        """The instance, or the problems that stopped there being one. Never both, never neither.

        One walk serving both public answers, which is what makes "the same conversion runs on
        replay" a fact about the code rather than a promise about it. The `isinstance` is how the
        walker's `object` becomes a `P` without a `cast`: `_instance` answers `None` in exactly the
        cases where it appended a problem, so the check is a narrowing and not a second opinion.
        """
        problems: list[str] = []
        built = _instance(self.payload, value, self.name, problems)
        if not isinstance(built, self.payload):
            return None, tuple(problems)
        return built, ()


def reporting_tool[P](name: str, description: str, payload: type[P]) -> ReportingTool[P]:
    """Declare the tool a reporting step reports through. §3.3's capture mechanism, in one line.

        report_findings = reporting_tool(
            "report_findings", "report what the review found", Findings
        )

    `payload` is a dataclass of the fields the module docstring lists, and the schema the model is
    shown is derived from it - so the shape the agent is asked for and the shape the workflow reads
    are one declaration and cannot drift.

    Refuses with `InputError`, naming the field and its type, anything the list does not cover.
    Declaration-time, like `arg()` and `@workflow`: a package that cannot be invoked correctly
    should fail when it is imported.

    Positional, where `@workflow` is keyword-only. Its argument - that a positional triple is a
    thing to get in the wrong order once and be wrong about for the life of a run's records - does
    not reach here: these two strings are read by a *model*, on the first call of the first run, and
    a tool named "report what the review found" announces itself immediately.
    """
    return ReportingTool(name=name, description=description, payload=payload)


@overload
def describe[T](text: str, *, default: T) -> T: ...
@overload
def describe(text: str) -> Any: ...
def describe(text: str, *, default: Any = MISSING) -> Any:
    """Say what one payload field is, in the schema the model is shown. One line, at the field:

        @dataclass(frozen=True, slots=True)
        class Finding:
            severity: str = describe(f"one of {', '.join(SEVERITIES)}")
            file: str

    The text becomes that field's `description` in the derived schema, which every backend puts in
    front of the model beside the field name. A field declared without one is unchanged and that is
    the ordinary case; this is for the fields whose *values* have a rule the name cannot carry -
    the module docstring's fixed vocabulary above all, since `sdk/tools.py` refuses an enum and
    this is what it refuses one in favour of.

    **It is a fingerprint term, and that is the half worth knowing.** The schema goes into
    `base_of`, so editing this text re-runs every step that reports through the payload - the same
    bargain `Role.instructions` makes, and for the same reason: a description is what the agent was
    asked for, so a replayed result produced under the old wording is not this step's result. It is
    also what makes a rule stated here immune to §3.6 rule 6's `__post_init__` hole, which the
    module docstring argues at length.

    `dataclasses.field(metadata=...)` under one namespaced key, exactly as `sdk/params.py::arg()`
    declares a flag, down to typeshed's overload trick: `severity: str = describe(...)` is a
    **required** field because a `field()` with no `default` is one `dataclasses` insists on, and
    `describe(..., default=1.0)` is an optional one for the same reason. Required-ness is not a
    concept either function has. `_required` reads the same two attributes it always did.

    `InputError` at declaration time for text that is empty or nothing but whitespace, which is
    `ReportingTool.__post_init__`'s refusal of an empty *tool* description one level down: a field
    that asked to say something and said nothing puts an empty string in the fingerprint and in
    front of the model, and neither reader is better off for it.
    """
    if not text.strip():
        raise InputError(
            f"a field was described with {text!r}, and a description is what the model reads "
            f"beside the field name to know what belongs in it. Give it a sentence or leave the "
            f"field undescribed - an empty one is a term in every digest this payload writes and "
            f"is nothing at all to the model"
        )
    described = {_METADATA_KEY: text}
    if default is MISSING:
        return field(metadata=described)
    return field(default=default, metadata=described)


def _object_schema(
    kind: type[Any], where: str, inside: tuple[type[Any], ...]
) -> dict[str, JsonValue]:
    """One payload dataclass as a JSON Schema object. `inside` is the chain that got here.

    `required` is sorted and `properties` is not - the module docstring argues both, and the reason
    for the asymmetry is that canonical JSON sorts an object's keys and leaves an array's order
    alone, so only one of the two costs an agent run when an author moves a line.

    **`title` is the payload type's qualified name, and it is here to be fingerprinted.** §3.6 rule
    6 puts a dataclass's qualified name in the digest at every depth, and its second half says the
    same of "a reporting tool's payload type": two structurally identical payload types derive a
    byte-identical schema, so the old entry replays into the new one, and §3.6's claim that a stale
    entry "is discarded rather than failing to parse" holds only once the name is in the terms. It
    is the expensive direction of this module's failures - a false cache **hit**, one type handed
    back another's recorded result, nothing raised - which is why it is closed by refusing to be
    ambiguous rather than by checking anything.

    **It goes in the schema because there is nowhere else to put it.** `base_of` hashes a tool's
    `name`, its `description` and its `payload_schema` and nothing else, and `Tool` is a **port**
    type: a field carrying an SDK declaration's payload class would be `ports/agent.py` learning
    what a reporting tool is, which §3.3 spends a paragraph forbidding. So the identity travels
    inside the one term that already crosses.

    **And it is written here, not once at the top, which is the whole of the depth.** `_schema_for`
    reaches this function again for every nested dataclass, so a name written here names every type
    in the payload rather than only the outermost - `Outer(inner=Inner)` and `Outer(inner=Other)`
    must not be one fingerprint either. That is exactly `journal._canonical`'s shape and it is the
    same argument: `dataclasses.asdict` erases the type, so tagging what it returns names the outer
    one and erases every one below it. The two walkers close the same rule at the same depth, one
    over an input and one over a payload.

    **`title` and not `$id` or `description`.** `title` is a JSON Schema *annotation*: it has no
    validating behaviour in any draft, so no vendor's validator can reject a payload over it and no
    backend has to be told about it. `$id` would be read as a base URI and change how `$ref` is
    resolved in a schema that grew one; `description` is the author's own prose and putting a
    qualified type name there would have put a second voice in it. That last sentence has a
    consequence now that `describe()` exists: a `description` on this object would be prose about
    *the payload*, which is what the tool's own `description` already is, so nothing writes one
    here. The key that is written is one level down, on a field, where the prose is about the field.

    **What it costs, stated rather than discovered.** The value reaches the model, which is
    acceptable and arguably useful - the model is told the name of the thing it is filling in, and
    a qualified name is what the workflow itself calls it. And renaming or moving a payload class
    re-runs every step that reports through it, which is correct rather than a price: the workflow
    will read that result back as a different type, so the recorded one is not this step's result.
    Like everything else this function returns, the string is a **stored format** - its shape is
    hashed into every digest ever written - so respelling the key or the name re-runs the ledger.
    """
    if kind in inside:
        raise InputError(
            f"{where} is {_describe(kind)}, which is already being derived - a payload dataclass "
            f"that contains itself has no finite schema, and a model has no way to know when to "
            f"stop nesting one"
        )
    hints = _hints(kind)
    nested = (*inside, kind)
    properties: dict[str, JsonValue] = {}
    required: list[JsonValue] = []
    for spec in fields(kind):
        # The description is written onto whatever the annotation derived rather than passed down
        # into the derivation, which is what keeps `describe()` orthogonal to every field type
        # there is: an optional derives an `anyOf` and an array derives `items`, and `description`
        # is an annotation keyword JSON Schema allows beside either. It goes on last so a reader
        # of the object meets the shape before the prose, and the key order is free - canonical
        # JSON sorts an object's keys before anything is hashed.
        schema = _schema_for(hints.get(spec.name), _at(where, spec.name), nested)
        described = _description(spec)
        if described is not None:
            schema["description"] = described
        properties[spec.name] = schema
        if _required(spec.default, spec.default_factory):
            required.append(spec.name)
    return {
        "type": "object",
        # Spelled out rather than taken from `_describe`, although that function says the same
        # words: `_describe` exists to word refusals and is free to be reworded for one, and this
        # string is hashed into every digest ever written. It is `journal.py`'s `_WIRE_TIME`
        # argument - two copies of one format, on purpose, where sharing would tie a stored format
        # to a name whose owner may change it - and it is the identical expression `_canonical`
        # writes for rule 6, so the two rules read as the one rule they are.
        "title": f"{kind.__module__}.{kind.__qualname__}",
        "properties": properties,
        "required": sorted(required, key=str),
        "additionalProperties": False,
    }


def _schema_for(hint: object, where: str, inside: tuple[type[Any], ...]) -> dict[str, JsonValue]:
    """One field's annotation as JSON Schema, or `InputError` naming the field and the type.

    `X | None` is spelled `anyOf` rather than a two-member `type` array, because the second cannot
    describe an optional object at all and one spelling for every optional is one thing to read.

    A `dict` and not a `JsonValue`, which every branch below already answered with and which is
    what lets `_object_schema` write a described field's `description` onto the result without
    narrowing something it just built.
    """
    optional = _optional(hint)
    if optional is not None:
        return {"anyOf": [_schema_for(optional, where, inside), {"type": "null"}]}
    scalar = _SCALARS.get(hint)
    if scalar is not None:
        return {"type": scalar[0]}
    item = _item(hint)
    if item is not None:
        return {"type": "array", "items": _schema_for(item, f"{where}[]", inside)}
    if isinstance(hint, type) and is_dataclass(hint):
        return _object_schema(hint, where, inside)
    raise InputError(
        f"{where} is a {_describe(hint)}, which a reporting tool cannot carry: {_SUPPORTED}. A "
        f"payload is stored as the step's result and read back as this dataclass, so a field type "
        f"that does not survive JSON unchanged is one the ledger could not return"
    )


def _instance(kind: type[Any], value: object, where: str, problems: list[str]) -> object:
    """`value` as an instance of `kind`, or `None` with the reasons appended to `problems`.

    Answers `None` if and only if it appended at least one problem, which is what `_read` narrows
    on. The dataclass is constructed last and inside a `try`, because a payload dataclass states
    its own rules in `__post_init__` - the way every dataclass in this repository does - and a
    value the walker accepted can still be one the type refuses. On a fresh run that belongs in
    front of the model with everything else; on replay `read` turns it into `InternalError`.
    """
    before = len(problems)
    given = _given(kind, value, where, problems)
    if len(problems) != before:
        return None
    # The class is used as a factory of itself, as `sdk/params.py::parse` does: `dataclasses`
    # generates `__init__` at runtime, so no static type describes what it takes.
    factory: Callable[..., object] = kind
    try:
        return factory(**given)
    except Exception as raised:
        problems.append(f"`{where}` is not a valid {_describe(kind)}: {raised}")
        return None


def _given(kind: type[Any], value: object, where: str, problems: list[str]) -> dict[str, object]:
    """The keyword arguments `kind` would be built from, checking `value` field by field.

    An absent field with a default is simply not passed, so the dataclass's own default stands -
    the same stance `sdk/params.py` takes with `argparse.SUPPRESS`, and for the same reason: the
    default is written on the author's one line and nothing here should be able to disagree with it.
    """
    if not isinstance(value, Mapping):
        problems.append(f"`{where}` should be an object and {_shown(value)} arrived")
        return {}
    hints = _hints(kind)
    declared = {spec.name: spec for spec in fields(kind)}
    for key in value:
        if key not in declared:
            problems.append(
                f"`{_at(where, key)}` is not one of this payload's fields. They are: "
                f"{', '.join(declared) or '(none)'}"
            )
    given: dict[str, object] = {}
    for name, spec in declared.items():
        hint, at = hints.get(name), _at(where, name)
        if name in value:
            given[name] = _converted(hint, value[name], at, problems)
        elif _required(spec.default, spec.default_factory):
            problems.append(f"`{at}` is missing, and it is required: {_wording(hint)}")
    return given


def _converted(hint: object, value: object, where: str, problems: list[str]) -> object:
    """One payload value at the type its field declares, or `None` with a problem appended.

    The branch order is `_schema_for`'s, so a field type the schema describes is one this reads and
    the two cannot come apart. A JSON array becomes a `list` or a `tuple` by what the field
    declared, which is what makes `tuple[X, ...]` survive the round trip that JSON's one bracket
    would otherwise flatten.
    """
    optional = _optional(hint)
    if optional is not None:
        return None if value is None else _converted(optional, value, where, problems)
    if hint in _SCALARS:
        return _scalar(hint, value, where, problems)
    item = _item(hint)
    if item is not None:
        if not isinstance(value, list):
            _wrong(hint, value, where, problems)
            return None
        built = [
            _converted(item, element, f"{where}[{index}]", problems)
            for index, element in enumerate(value)
        ]
        return tuple(built) if get_origin(hint) is tuple else built
    if isinstance(hint, type) and is_dataclass(hint):
        return _instance(hint, value, where, problems)
    _wrong(hint, value, where, problems)
    return None


def _scalar(hint: object, value: object, where: str, problems: list[str]) -> object:
    """One JSON scalar at the type its field declares.

    A `bool` is excluded from the `int` and `float` branches for `journal.py`'s reason: `bool` is
    an `int` in Python and `true` is not a number in JSON, so coercing would let a model answer a
    count with a flag. An `int` **is** accepted for a `float` field, because JSON writes `2.0` as
    `2` and refusing it would refuse a value this module had just produced.

    `isfinite` is the one value-level refusal here: `json.loads` reads a bare `Infinity` or `NaN`
    token - neither of which is in JSON's grammar - as a float, and `ports/run.py` and the store
    both refuse to write one down. Caught here so the model is told, rather than at the write,
    where the run is already paid for and the fault would read as AGL's.
    """
    if hint is str and isinstance(value, str):
        return value
    if hint is bool and isinstance(value, bool):
        return value
    if hint is int and isinstance(value, int) and not isinstance(value, bool):
        return value
    if (
        hint is float
        and isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(value)
    ):
        return float(value)
    _wrong(hint, value, where, problems)
    return None


def _wrong(hint: object, value: object, where: str, problems: list[str]) -> None:
    """Record what this value should have been and what it was, in words a model can act on."""
    problems.append(f"`{where}` should be {_wording(hint)} and {_shown(value)} arrived")


def _wording(hint: object) -> str:
    """A field's type as the model is told it - JSON's vocabulary, never Python's.

    `_SCALARS` holds both halves, so a type cannot be describable in a schema and undescribable in
    the refusal that mentions it. An annotation this module does not support reaches here only
    through a payload dataclass edited after it was declared, and says so rather than guessing.
    """
    optional = _optional(hint)
    if optional is not None:
        return f"{_wording(optional)} or null"
    scalar = _SCALARS.get(hint)
    if scalar is not None:
        return scalar[1]
    item = _item(hint)
    if item is not None:
        return f"an array of {_wording(item)}"
    if isinstance(hint, type) and is_dataclass(hint):
        return f"an object with the fields of {hint.__qualname__}"
    return f"a {_describe(hint)}, which is not a payload type at all"


def _optional(hint: object) -> object | None:
    """The `X` in `X | None`, or `None` when the annotation is not exactly that.

    Exactly two members and one of them `None`: a wider union is refused, because a payload whose
    shape depends on which arm the model picked is one the workflow has to ask about before it can
    use it. `Optional[X]` and `X | None` are one type as of 3.14, so one branch covers both.
    """
    if get_origin(hint) is not UnionType:
        return None
    args: tuple[object, ...] = get_args(hint)
    real = [arg for arg in args if arg is not type(None)]
    return real[0] if len(args) == 2 and len(real) == 1 else None


def _item(hint: object) -> object | None:
    """The element type of `list[X]` or `tuple[X, ...]`, or `None` for anything else.

    A fixed-length `tuple[X, Y]` deliberately answers `None` and is refused - the module docstring
    argues it - and so does a bare `list`, which names no element type to derive one from.
    """
    origin = get_origin(hint)
    args: tuple[object, ...] = get_args(hint)
    if origin is list and len(args) == 1:
        return args[0]
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        return args[0]
    return None


def _check_payload(payload: object, name: str) -> None:
    """That the payload is a dataclass *class*. Takes `object` so that `is_dataclass`'s type guard
    narrows nothing in the caller, where `payload` has to stay the `type[P]` it was declared -
    `sdk/workflow.py::_check_params` is the same check for the same reason."""
    if isinstance(payload, type) and is_dataclass(payload):
        return
    raise InputError(
        f"the reporting tool {name!r} was declared with {_describe(payload)}, and a payload is a "
        f"dataclass (§3.3) - the class itself, never an instance of it. Its fields are what the "
        f"schema is derived from and what the agent is asked to fill in"
    )


def _hints(kind: type[Any]) -> Mapping[str, object]:
    """Every field's annotation, resolved: `Field.type` holds a *string* under `from __future__`."""
    try:
        return get_type_hints(kind)
    except (NameError, TypeError) as error:
        raise InputError(
            f"{_describe(kind)} has an annotation that cannot be resolved: {error}. Its fields are "
            f"read for their types, so each has to name something importable where it is"
        ) from error


def _refusal(name: str, problems: tuple[str, ...]) -> str:
    """Every problem in one payload, as one thing to read and act on."""
    listed = "\n".join(f"  - {problem}" for problem in problems)
    return (
        f"{name} was not given a payload it can accept, and nothing has been recorded. Fix all of "
        f"these and call it again:\n{listed}"
    )


def _required(default: object, factory: object) -> bool:
    """Whether a field has to be in the payload at all.

    Required-ness is not a concept this module has, for `sdk/params.py`'s reason: a field with
    neither a default nor a default factory is one `dataclasses` insists on at construction, and
    that *is* the required list. A sentinel of our own would answer a settled question twice, and
    would be free to disagree with the constructor about which fields it applies to."""
    return default is MISSING and factory is MISSING


def _description(spec: Field[Any]) -> str | None:
    """What `describe()` left on this field, or `None` for a field that was not described.

    `Field.metadata` is a mapping over whatever the author passed, so the value under our key is
    `object` until something narrows it. The `isinstance` is that narrowing and is also the whole
    of what this module does about a payload that wrote the key by hand: the key is namespaced,
    `describe()` is the one thing that writes it, and anything under it that is not a string is
    not a description rather than an error - `_METADATA_KEY` argues that.
    """
    held = spec.metadata.get(_METADATA_KEY)
    return held if isinstance(held, str) else None


def _at(where: str, name: object) -> str:
    """One step further into a payload, as a path a model can find in what it just sent."""
    return f"{where}.{name}"


def _shown(value: object) -> str:
    """An offending value, capped: a payload holding a whole file must not become the refusal."""
    text = repr(value)
    return text if len(text) <= _SHOWN else f"{text[:_SHOWN]}..."


def _describe(thing: object) -> str:
    """A class as `grep` finds it; an annotation that is not one, `list[str]` say, as written.
    `sdk/params.py` and `sdk/workflow.py` describe the same thing the same way."""
    if not isinstance(thing, type):
        return repr(thing)
    return f"{thing.__module__}.{thing.__qualname__}"
