"""What a `Role` declaration promises: a name, four terms, a handler, a model from its factory,
and one typed result per step.

Five properties carry this suite.

**A role is declared by a `@role(model=…)` factory and the model is nowhere in the `Role(...)`**
(UF1.2), which reaches this file in two ways. The two roles it measures are built by factories at
the top, so the values below are the values a workflow would hold; and most other declarations here
are about `Role.__post_init__` - a refusal, a fold, an inference - and name no model at all, which
is legal and is what `Role.model`'s refusal is for. `_base` is where the difference is visible: it
takes an optional `model=` because a bare `Role` cannot be fingerprinted without one, and its own
docstring says so.

**The typing chain is asserted at the type level**, with `assert_type`, because §3.3's promise is
about what *mypy* knows - `findings = await run.step(reviewer())` then `findings.high()`.
`mypy --strict` runs over `tests/` too, so these are gates and not documentation, and a runtime
assertion would pass against a `Role` that had erased `P` to `Any`, which is precisely the version
worth catching. `tests/sdk/test_tools.py` asserts the same chain one link earlier.

**Where inference does not reach, the failure is pinned rather than hidden.** A list display mixing
a plain `Tool` with a `ReportingTool` cannot be solved for `P`, and the pin is a `# type: ignore`
whose *unusedness* would fail the build: `--strict` turns on `warn_unused_ignores`, so if a later
mypy learns to infer that shape, the ignore goes stale and this suite says so. The two spellings
that do work are asserted beside it, and the explicit parameter is checked in both directions -
`Role[Findings]` accepted, `Role[Tickets]` refused - because an explicit parameter that was believed
rather than checked would be worse than no fallback at all.

**Every refusal is an `InputError` pinned by the part of its message a reader acts on next**, since
that reader is a workflow author looking for the line they wrote. `tests/sdk/test_tools.py` and
`tests/sdk/test_params.py` pin the same module's neighbours the same way.

**`prompt_file` is measured against the file it read, never against itself.** Its section pins what
a declaration holds afterwards - the text, not the path - what a relative path is resolved against,
and each of the five refusals. What it cannot pin from here is the claim §3.7 actually makes, that
the *agent* is asked what the file says; `tests/sdk/test_run_step.py` drives a real step for that,
and for the edit that must re-run one.

**`RoleIncompleteError` is asserted through `exit_code_for` and through its absence from
`EXIT_CODES`**, together. Either alone would pass against the wrong design: the code alone would
survive somebody adding a table entry for it, and the absence alone would survive it resolving to
70. The pair is the mechanism - a class that gets its meaning by inheritance, from a table it is not
in.
"""

import importlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
from typing import Final, assert_type, cast

import pytest

from agl.ports.agent import (
    Capability,
    Claude,
    ModelId,
    OpenAI,
    Restriction,
    Tool,
    ToolResult,
)
from agl.ports.errors import EXIT_CODES, AglError, InputError, UpstreamError, exit_code_for
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue
from agl.sdk._engine.journal import base_of
from agl.sdk.roles import Role, RoleIncompleteError, prompt_file, role
from agl.sdk.tools import ReportingTool, reporting_tool

_HEAD: Final = "4a91c07f2b3e8d15c6a0b7f31d92e8054c6a0f13"

_REVIEW: Final = "Review the worktree against the spec and report what you found."
_IMPLEMENT: Final = "Implement the ticket. Run the tests until they pass."

# What a prompt file holds, for the `prompt_file` section below: §3.7's own `prompts/decompose.md`,
# written out so that "the text arrived" and "a path arrived" cannot be confused for each other.
_DECOMPOSE: Final = "Propose tickets, ask for approval, revise until approved, then report.\n"


@dataclass(frozen=True)
class Finding:
    file: str
    severity: str


@dataclass(frozen=True)
class Findings:
    """§3.3's `findings = await run.step(reviewer())` / `findings.high()`, as a payload."""

    summary: str
    findings: list[Finding]

    def high(self) -> list[Finding]:
        return [found for found in self.findings if found.severity == "high"]


@dataclass(frozen=True)
class Tickets:
    """A second payload type, so the wrong explicit parameter has something to be wrong with."""

    ids: list[str]


REPORT: Final = reporting_tool("report_findings", "report what the review found", Findings)
REPORT_TICKETS: Final = reporting_tool("report_tickets", "report the tickets you propose", Tickets)

_ONE_HIGH: Final[Mapping[str, JsonValue]] = {
    "summary": "one thing to fix",
    "findings": [{"file": "a.py", "severity": "high"}],
}


async def _never_called(payload: Mapping[str, JsonValue]) -> ToolResult:
    """Nothing in this suite runs an agent, so no handler here is ever invoked."""
    return ToolResult(text="")


def _plain(name: str) -> Tool:
    """An ordinary `Tool` - the kind a role offers beside its reporting tool, and the kind an
    adapter is handed."""
    return Tool(
        name=name,
        description=f"{name}, which the agent may call",
        payload_schema={"type": "object", "properties": {}},
        handler=_never_called,
    )


async def _answer(question: Question) -> Answer:
    """§3.7's handler shape: one `Question` in, one `Answer` out, async because answering may mean
    waiting on a person."""
    return Answer(text=question.options[0] if question.options else "carry on")


def _reporting_of[P](role: Role[P]) -> ReportingTool[P] | None:
    """The scan 12.1's `Run.step` makes to decide which of §3.3's two step kinds this is.

    `Role` deliberately offers no accessor for it: the at-most-one rule is enforced at declaration,
    so this scan is total, and `run.step` is its only caller - which is not ARCHITECTURE.md §1's
    "two or more workflows would otherwise write it themselves". Asserted here at the type level,
    because leaving it out is only safe if the `isinstance` narrows to `ReportingTool[P]`.
    """
    for declared in role.tools:
        if isinstance(declared, ReportingTool):
            return declared
    return None


async def _step[P](role: Role[P], payload: Mapping[str, JsonValue] | None = None) -> P:
    """A stand-in for 12.1's `Run.step`, carrying `Role[P]`'s parameter through the way that method
    must. Nothing here is the journal; the point is what mypy makes of the result.

    The `cast` is the one thing 12.1 inherits from this shape and should know about in advance: `P`
    is unbounded inside the body, so an effect step's `null` is not assignable to it even on a call
    where `P` has already resolved to `None`. It is one line, in the framework, where no workflow
    author ever sees it.
    """
    reporting = _reporting_of(role)
    if reporting is None:
        return cast("P", None)
    return reporting.read(payload if payload is not None else {})


def _base[P](built: Role[P], *, model: ModelId | None = None) -> str:
    """One step's base fingerprint, built from the four terms §3.6 takes off a role.

    A declaration becomes an ordinary `Tool` the way `Run.step` will convert one - the adapter must
    never learn which tool is the reporting one - and `tests/sdk/test_tools.py` pins that
    conversion. What is measured here is only which of a role's fields reach the digest.

    **`model` is the one term that can be supplied here**, and it is the shape UF1.2 left behind:
    a role's model is bound by `@role(model=…)`, so a declaration written to exercise
    `Role.__post_init__` - which is most of this file - names none and `Role.model` refuses to
    invent one. Passing it is how such a value is fingerprinted at all. Left out, this reads the
    role's own, which is what `Run.step` does and what the tests about the model term measure.
    """
    tools: list[Tool] = []
    for declared in built.tools:
        if isinstance(declared, ReportingTool):
            tools.append(
                Tool(
                    name=declared.name,
                    description=declared.description,
                    payload_schema=declared.payload_schema,
                    handler=_never_called,
                )
            )
        else:
            tools.append(declared)
    return base_of(
        instructions=built.instructions,
        model=built.model if model is None else model,
        restrictions=built.restrictions,
        tools=tools,
        inputs={},
        head=_HEAD,
    )


def _review() -> Role[Findings]:
    """The `Role` both factories below return, so that the only thing that differs between them is
    the model their decorator binds - which is what makes the model term measurable at all."""
    return Role(
        name="review",
        instructions=_REVIEW,
        restrictions={Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES},
        tools=[REPORT],
        requires={Capability.SHELL},
    )


@role(model=OpenAI.SOL)
def reviewer() -> Role[Findings]:
    """§3.3's reporting role, declared the one way a role is declared."""
    return _review()


@role(model=Claude.OPUS)
def _reviewer_on_claude() -> Role[Findings]:
    """`reviewer()` with one term different, and that term is on the decorator: the model."""
    return _review()


@role(model=Claude.OPUS)
def implementer() -> Role:
    """§3.3's effect role: no reporting tool, so its result is `null`."""
    return Role(name="implement", instructions=_IMPLEMENT, requires={Capability.SHELL})


REVIEWER: Final = reviewer()
IMPLEMENTER: Final = implementer()
"""The two roles this suite measures, built once. A `Role` is what a factory returns and what a
step is handed, so a suite about `Role` holds values rather than factories - and the section on
`@role` below is where the factories themselves are measured."""


@role(model=OpenAI.LUNA)
def _unservable() -> Role:
    """A role naming a model no installed backend serves and requiring every capability there is.

    Declared without complaint, which is this file's "nothing here is checked against a provider":
    `@role` validates nothing, `Role.__post_init__` asks no port, and the deaths §3.2 arranges for
    this both need a runner - `check_ready` on its model at second zero, and containment of what it
    requires at the first step it is handed to."""
    return Role(
        name="review",
        instructions=_REVIEW,
        requires=frozenset(Capability),
        on_question=_answer,
    )


@role(model=Claude.HAIKU)
def _never_called_factory() -> Role:
    """A factory whose body would fail the suite if anything ever ran it.

    It exists to make "preflight never invokes the function" (§3.2) a measured fact rather than a
    promise: the two attributes below are read off this object, and the `raise` is what would say
    so if reading one had cost a call."""
    raise AssertionError("a factory was invoked to read the `(name, model)` it carries")


# --- `@role(model=…)`: what the decorator registers, and where the model lives --------------------
#
# UF1.2. §3.3's table says a role *is* "a `@role(model=…)` factory returning a frozen `Role`", and
# §3.11 rejects what it replaced by name: "a bare `replace()` on a module-level `Role` ... lets a
# call site change the model or the restrictions - a mutation with pleasant syntax". The two halves
# of that are measured separately below, because they fail differently: a decorator that forgot to
# bind the model gives every step a role that refuses at the first read, and a factory whose
# parameter list is wider than the author wrote gives a call site knobs the author never offered.


def test_the_factory_binds_the_model_its_decorator_names() -> None:
    """One declaration, not two: `model=` appears on the decorator and nowhere in the `Role(...)`
    the function returns, and the value that comes back has it all the same."""
    assert reviewer().model is OpenAI.SOL
    assert implementer().model is Claude.OPUS
    assert _reviewer_on_claude().model is Claude.OPUS


def test_the_name_and_the_model_are_readable_without_invoking_the_factory() -> None:
    """§3.2's whole provider check, and the sentence it rests on: preflight "collects providers
    from the registry and **never invokes the function**, which it could not do without arguments
    it does not have".

    `_never_called_factory` is the measurement rather than the illustration - its body raises, so a
    reading that cost a call would fail this line instead of passing quietly and costing a prompt
    file read per role at preflight.

    **`.name` is the factory's own name and not `Role.name`**, which the second pair pins: the
    factory is `implementer` and the role it builds is `implement`. It could not be otherwise, the
    role's name being unreachable without the call this test is about - so this half is for
    diagnostics and the model is the half preflight acts on.
    """
    assert (_never_called_factory.name, _never_called_factory.model) == (
        "_never_called_factory",
        Claude.HAIKU,
    )
    assert implementer.name == "implementer"
    assert implementer().name == "implement"


def test_a_role_that_never_went_through_a_factory_refuses_to_name_a_model() -> None:
    """The loud half of "the model lives on the decorator". A bare `Role(...)` is a legal value -
    `__post_init__` has nothing to object to - right up until something asks what runs it, and
    `base_of`, `AgentTask` and `Capabilities.require` all do. Preflight is not among them and since
    UF1.3 never could be: it reads the model off the factory, which is how it asks about a role it
    is forbidden to build.

    The refusal names `@role(model=…)`, because the line that is wrong is the one that is missing:
    a reader who is told only "no model" goes looking for a field that no longer exists.
    """
    undeclared = Role(name="review", instructions=_REVIEW)
    with pytest.raises(InputError) as refusal:
        _ = undeclared.model
    assert "@role(model=" in str(refusal.value)
    assert "review" in str(refusal.value)


def test_replace_on_a_built_role_carries_the_model_across() -> None:
    """`_model` is an `init` field rather than `init=False`, and this is the difference: `replace`
    copies init fields and re-defaults the rest, so a role that went through a factory and then
    through a `replace` still knows what runs it. With `init=False` the model would be silently
    dropped and the refusal would arrive at the step instead of at the line."""
    assert replace(REVIEWER, name="second_opinion").model is OpenAI.SOL
    assert replace(REVIEWER, tools=()).model is OpenAI.SOL


def test_the_override_surface_is_the_factorys_own_parameter_list() -> None:
    """§3.11's rejected member, measured as a type error rather than as an argument.

    `reviewer` takes nothing, so there is nothing a call site can vary. Each `type: ignore` below
    is half the assertion - `--strict` warns on an unused one, so a `RoleFactory` that ever grew a
    `**kwargs` or lost its `ParamSpec` fails this file at the type level - and the `TypeError` is
    the other half, because a suite that only checked the types would pass against a decorator that
    accepted anything at runtime and quietly ignored it.

    The third is the spelling this replaced: `replace(role, model=…)` reached a term §3.6
    fingerprints, and it is refused now because `model` is no field of `Role` at all.
    """
    with pytest.raises(TypeError):
        reviewer(model=Claude.HAIKU)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        reviewer(restrictions=frozenset())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        replace(REVIEWER, model=Claude.HAIKU)  # type: ignore[call-arg]


def test_two_calls_of_one_factory_are_equal_values_and_not_one_value() -> None:
    """A factory builds a fresh frozen `Role` per call, which is what makes an override surface a
    surface: `implementer(...)` cannot be handed the object a previous call produced, so nothing a
    call site does can reach a role another call site is using."""
    assert reviewer() == reviewer()
    assert reviewer() is not reviewer()


def test_the_factory_keeps_the_declarations_name_and_docstring() -> None:
    """`update_wrapper`, for the ordinary reason: the argument an author writes under a role
    declaration is still that name's docstring, and a traceback through a factory still says where
    it was written."""
    assert implementer.__name__ == "implementer"
    assert implementer.__doc__ is not None
    assert "effect role" in implementer.__doc__
    assert implementer.__module__ == __name__


# --- the name, which is the address and not a term ------------------------------------------------
#
# UF1.1: `run.step` lost its `name=`, so the entry path is `steps/<role name>/` and the role is the
# only place the name is written. The two claims worth pinning are the two halves of that sentence -
# the name is checked by the type the path is composed out of, and it is checked *here* rather than
# at the step; and it reaches no digest, so renaming a role moves its ledger without moving one
# fingerprint inside it.


def test_a_role_carries_the_name_its_entries_are_recorded_under() -> None:
    """§3.11: "a `name=` on `run.step`" is a rejected member, because "the role already carries
    one". So this field is where the address is written, and it is written once."""
    assert REVIEWER.name == "review"
    assert IMPLEMENTER.name == "implement"


@pytest.mark.parametrize("unusable", ["", "   ", "has a space", "steps/review", "..", "con"])
def test_a_name_that_cannot_be_a_path_segment_is_refused_where_it_is_written(
    unusable: str,
) -> None:
    """`StepName` is the rule `steps/<name>/` is composed under, and it is asked here rather than
    copied - which is what keeps §3.3's allowlist in one place. `sdk/_engine/steps.py` builds the
    same type on the way into a step, so refusing at the declaration only moves the refusal
    earlier: to the line the author wrote, from a run that had already started."""
    with pytest.raises(InputError) as refusal:
        Role(name=unusable, instructions=_REVIEW)
    assert "step name" in str(refusal.value)


def test_the_name_is_the_address_and_reaches_no_fingerprint() -> None:
    """The division of labour UF1.1 rests on: the name says *which directory*, and the digest is
    what is compared inside it. Two roles alike in everything but the name therefore hash
    identically, which is also what makes "two calls on one role separate by their inputs" the only
    thing that can separate them.

    Asserted against `base_of` rather than against a list of terms, so that adding `name` to the
    fingerprint fails this line instead of quietly re-running every recorded step in existence.
    """
    renamed = replace(REVIEWER, name="second_opinion")
    assert renamed.name != REVIEWER.name
    assert _base(renamed) == _base(REVIEWER)


# --- the four terms, and what the declaration normalises them to ---------------------------------


def test_a_role_holds_the_terms_section_3_3_lists_and_nothing_else() -> None:
    """§3.3's "instructions + restrictions + tools + required capabilities", plus §3.7's handler,
    the name its steps are recorded under, and the model its factory bound. Slotted, so an
    attribute nobody declared cannot be attached to one."""
    assert (REVIEWER.name, REVIEWER.instructions, REVIEWER.model) == ("review", _REVIEW, OpenAI.SOL)
    assert REVIEWER.on_question is None
    with pytest.raises(AttributeError):
        object.__getattribute__(REVIEWER, "__dict__")


def test_the_declared_sets_are_stored_as_frozensets() -> None:
    """Declared as `AbstractSet` so that `{Restriction.NO_SHELL}` is the spelling an author writes,
    and normalised on the way in to what `AgentTask.restrictions` takes."""
    assert isinstance(REVIEWER.restrictions, frozenset)
    assert isinstance(REVIEWER.requires, frozenset)
    assert REVIEWER.restrictions == frozenset(
        {Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES}
    )


def test_a_mutable_set_handed_in_cannot_be_edited_afterwards() -> None:
    """The copy `frozenset()` makes is the point: a caller that kept the set it passed cannot add a
    restriction to a role already in use by a step that has run."""
    declared = {Restriction.NO_SHELL}
    role = Role(name="review", instructions=_REVIEW, restrictions=declared)
    declared.add(Restriction.NO_NETWORK)
    assert role.restrictions == frozenset({Restriction.NO_SHELL})


def test_the_tools_become_a_tuple_in_declaration_order() -> None:
    """`AgentTask.tools` is "in declaration order", and `base_of` reads the sequence as given
    without sorting it, so the order is a fingerprint term rather than a presentation choice."""
    role = Role(
        name="review",
        instructions=_REVIEW,
        tools=(_plain("grep_notes"), _plain("read_spec"), REPORT),
    )
    assert isinstance(role.tools, tuple)
    assert [declared.name for declared in role.tools] == ["grep_notes", "read_spec", REPORT.name]


def test_reordering_two_tools_moves_the_steps_fingerprint() -> None:
    """Not asserted as a good thing - asserted as the behaviour §3.6 rule 4 specifies, so that a
    later change to it is a decision somebody makes rather than one that happens."""
    one_way = Role(name="review", instructions=_REVIEW, tools=[_plain("a"), _plain("b")])
    the_other = Role(name="review", instructions=_REVIEW, tools=[_plain("b"), _plain("a")])
    assert _base(one_way, model=Claude.SONNET) != _base(the_other, model=Claude.SONNET)


def test_an_effect_role_declares_no_tools_and_that_is_ordinary() -> None:
    """§3.3's effect step: no reporting tool, result `null`, and the effect is commits."""
    assert IMPLEMENTER.tools == ()
    assert _reporting_of(IMPLEMENTER) is None


def test_a_role_is_frozen() -> None:
    """It is declared once and used by many steps - §3.3 hands every child worktree the same
    `implementer` - so a role one step could edit is a role every step has edited.

    Measured on `name`, which is a field, and then on `model`, which since UF1.2 is a read-only
    property over a private one. Both refuse and they refuse *differently* - `FrozenInstanceError`
    from the dataclass, `AttributeError` from the property - and both are pinned, because a `model`
    that became settable would be the override surface the factory exists to close, reopened one
    attribute at a time."""
    with pytest.raises(FrozenInstanceError):
        REVIEWER.name = "second_opinion"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        REVIEWER.model = Claude.HAIKU  # type: ignore[misc]


def test_two_providers_in_one_workflow_is_the_ordinary_case() -> None:
    """§3.2's requirement, in the shape an author writes it: the model is named per role, beside the
    prompt, and nothing here holds an opinion about which adapter serves it."""
    assert REVIEWER.model.provider != IMPLEMENTER.model.provider


# --- instructions are the prompt, not a path to it -----------------------------------------------


def test_a_role_stores_its_instructions_verbatim_and_opens_nothing() -> None:
    """§3.7's `instructions="prompts/decompose.md"` read as shorthand: what a role holds is the
    prompt text, so a string that looks like a path is stored as the prompt it is not. The path here
    does not exist, and the declaration succeeds anyway, which is the whole assertion."""
    looks_like_a_path = "prompts/decompose.md"
    assert not Path(looks_like_a_path).exists()
    role = Role(name="review", instructions=looks_like_a_path)
    assert role.instructions == looks_like_a_path


def test_editing_the_prompt_moves_the_steps_fingerprint() -> None:
    """§3.6's reason for putting the role in the digest at all: halt, edit the prompt, resume, and
    you must not replay what the old wording produced. This is what a role holding a *filename*
    could not do - the filename would be unchanged, the digest would match, and the stale result
    would come back as a cache hit with nothing to notice it."""
    edited = replace(REVIEWER, instructions=_REVIEW + " Check the tests too.")
    assert _base(REVIEWER) != _base(edited)


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_instructions_are_refused_where_they_are_written(blank: str) -> None:
    """`AgentTask` refuses an empty prompt at the dispatch, which is after the journal missed and
    the worktree was reset; refused here, the author is looking at the line."""
    with pytest.raises(InputError) as refusal:
        Role(name="review", instructions=blank)
    assert "instructions" in str(refusal.value)


# --- `prompt_file`, which is how the text gets there ---------------------------------------------
#
# §3.7: "`prompt_file()` reads at declaration time and is the sanctioned spelling". The tests below
# are the declaration half - what it reads, what it resolves against, and what it refuses.
# `tests/sdk/test_run_step.py` holds the half that cannot be measured here: that the text reaches
# the agent, and that editing the file re-runs the step rather than replaying the old wording.
#
# **UF1.2 moved "declaration time" without changing the sentence**: it was a module's import and it
# is now each call of a factory. Two tests below are about that move rather than about the function
# - that the read really does happen per call, and that a relative path written inside a factory
# still resolves against the module the factory was *written* in and not the one that called it.


def _declared(where: Path) -> Role[None]:
    """A role whose prompt is a file - §3.7's own shape, with the path already absolute."""
    return Role(name="review", instructions=prompt_file(where))


def test_a_role_declared_with_prompt_file_holds_the_text_and_not_the_path(tmp_path: Path) -> None:
    """The point of the whole function: `Role.instructions` is still a `str` of prompt, so §3.6
    fingerprints the prompt. A `prompt_file` that answered with the path it was given would satisfy
    the type and nothing else, and the failure would be a silent replay a run later."""
    where = tmp_path / "review.md"
    where.write_text(_REVIEW, encoding="utf-8")

    role = _declared(where)

    assert role.instructions == _REVIEW
    assert str(where) not in role.instructions


def test_the_text_is_handed_back_exactly_as_it_was_written(tmp_path: Path) -> None:
    """Verbatim, trailing newline and all. Trimming would be this function editing the author's
    prompt, and a whitespace rule two people could remember differently is a moved digest."""
    where = tmp_path / "review.md"
    where.write_text(f"  {_REVIEW}\n\n", encoding="utf-8")
    assert prompt_file(where) == f"  {_REVIEW}\n\n"


def test_editing_the_prompt_file_moves_the_steps_fingerprint(tmp_path: Path) -> None:
    """§3.7's named failure, closed: "a role holding a filename would fingerprint the filename, so
    editing the prompt would move nothing and a resume would replay what the old wording produced".
    The path here is identical across the two declarations; only the file's contents differ."""
    where = tmp_path / "review.md"
    where.write_text(_REVIEW, encoding="utf-8")
    before = replace(REVIEWER, instructions=prompt_file(where))

    where.write_text(f"{_REVIEW} Check the tests too.", encoding="utf-8")
    after = replace(REVIEWER, instructions=prompt_file(where))

    assert _base(before) != _base(after)


def test_a_relative_prompt_path_is_read_from_beside_the_module_that_declared_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3.7 writes `prompt_file("prompts/decompose.md")` and means the file beside that module.

    A real module on disk, imported, because that is the only honest form of this: the resolution is
    made from the *calling frame's* `__file__`, so a helper in this file calling `prompt_file` on
    this file's behalf would measure this file's directory and prove nothing about a workflow
    package installed somewhere else.

    The working directory is moved to `tmp_path` first, where `prompts/decompose.md` does not exist.
    That is the assertion's other half: an implementation resolving against `Path.cwd()` - the
    ambient read stage 11.0 removed - fails here rather than passing by coincidence of where pytest
    was started.
    """
    package = tmp_path / "tickets"
    (package / "prompts").mkdir(parents=True)
    (package / "prompts" / "decompose.md").write_text(_DECOMPOSE, encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "roles.py").write_text(
        "from agl.sdk.roles import prompt_file\n\n"
        'DECOMPOSE = prompt_file("prompts/decompose.md")\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "prompts").exists(), "the cwd must not be able to answer this"
    importlib.invalidate_caches()

    try:
        declared = importlib.import_module("tickets.roles")
        assert declared.DECOMPOSE == _DECOMPOSE
    finally:
        # This test is the only thing that puts these two in `sys.modules`, and a second test
        # importing the same name would otherwise be handed this one's module.
        for name in ("tickets.roles", "tickets"):
            sys.modules.pop(name, None)


def test_a_factory_resolves_its_prompt_inside_its_own_package_when_called_from_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half of the resolution rule UF1.2 put at risk, measured rather than argued.

    `prompt_file` resolves against the calling *frame's* `__file__`, and since UF1.2 that frame is
    a factory body rather than a module body - so the question is whose module it belongs to. It
    belongs to the module the code was written in, which this measures by writing a package to
    disk, importing it, and calling its factory from *here*, with the working directory somewhere
    else again. Two wrong implementations fail: one resolving against the caller looks in
    `tests/sdk/`, and one resolving against `Path.cwd()` looks in `tmp_path`.

    This is `workflows/fix/roles.py`'s own situation - a factory in `roles.py`, called from
    `__init__.py` and from a test, naming `prompts/implement.md` - with the package built here so
    that the claim is about installation rather than about this repository's layout.
    """
    package = tmp_path / "stories"
    (package / "prompts").mkdir(parents=True)
    (package / "prompts" / "decompose.md").write_text(_DECOMPOSE, encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "roles.py").write_text(
        "from agl.ports.agent import Claude\n"
        "from agl.sdk.roles import Role, prompt_file, role\n"
        "\n"
        "@role(model=Claude.OPUS)\n"
        "def decompose() -> Role:\n"
        '    return Role(name="decompose", instructions=prompt_file("prompts/decompose.md"))\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "prompts").exists(), "the cwd must not be able to answer this"
    importlib.invalidate_caches()

    try:
        declared = importlib.import_module("stories.roles")
        built = declared.decompose()
        assert built.instructions == _DECOMPOSE
        assert built.model is Claude.OPUS
    finally:
        for name in ("stories.roles", "stories"):
            sys.modules.pop(name, None)


def test_a_factory_reads_its_prompt_file_on_every_call(tmp_path: Path) -> None:
    """"Declaration time" is each call now, and this is the difference from a module-level `Role`.

    A module-level declaration read its prompt once, at import, so a file edited afterwards was
    never seen again in that process. A factory reads it per call - which is what keeps the digest
    honest for a workflow that edits a prompt between two runs of the same interpreter, and is why
    `sdk/roles.py` bothers to say what the extra reads cost.

    Written as two calls with an edit in between, so the assertion is about *when* the read happens
    and not merely about `prompt_file` working twice.
    """
    where = tmp_path / "review.md"

    @role(model=Claude.SONNET)
    def declared() -> Role:
        return Role(name="review", instructions=prompt_file(where))

    where.write_text(_REVIEW, encoding="utf-8")
    before = declared()
    where.write_text(f"{_REVIEW} Check the tests too.", encoding="utf-8")
    after = declared()

    assert before.instructions == _REVIEW
    assert after.instructions.endswith("Check the tests too.")
    assert _base(before) != _base(after)


def test_a_missing_prompt_file_is_refused_at_the_declaration_naming_the_path(
    tmp_path: Path,
) -> None:
    """`arg()`'s stance and `reporting_tool()`'s: a package that cannot be invoked correctly should
    fail when it is imported. The alternative is a run that pays for two agents and then discovers
    that the third role has no prompt."""
    where = tmp_path / "prompts" / "decompose.md"
    with pytest.raises(InputError) as refusal:
        prompt_file(where)
    assert str(where) in str(refusal.value)


def test_a_directory_where_a_prompt_belongs_is_refused(tmp_path: Path) -> None:
    """`read_text` on one raises `IsADirectoryError` on this platform and `PermissionError` on
    another, so it is caught by name and answered in this module's words either way."""
    with pytest.raises(InputError) as refusal:
        prompt_file(tmp_path)
    assert str(tmp_path) in str(refusal.value)


@pytest.mark.parametrize("blank", ["", "   ", "\n\t\n"])
def test_an_empty_prompt_file_is_refused_where_the_role_is_declared(
    tmp_path: Path, blank: str
) -> None:
    """`Role.__post_init__`'s check, made one line earlier and for its reason: the instructions are
    the whole of what an agent is asked to do, and an empty file is the way to have none by
    accident - `touch prompts/review.md` and then forget to write it."""
    where = tmp_path / "review.md"
    where.write_text(blank, encoding="utf-8")
    with pytest.raises(InputError) as refusal:
        prompt_file(where)
    assert str(where) in str(refusal.value)


def test_a_prompt_that_is_not_utf_8_is_refused_rather_than_read_with_holes_in_it(
    tmp_path: Path,
) -> None:
    """No `errors=` argument, deliberately: a prompt read with replacement characters in it is a
    prompt nobody wrote, fingerprinted as though somebody had, and answered by a model anyway."""
    where = tmp_path / "review.md"
    where.write_bytes(b"review the caf\xe9 module\n")
    with pytest.raises(InputError) as refusal:
        prompt_file(where)
    assert "UTF-8" in str(refusal.value)


def test_a_caller_with_no_file_is_told_to_pass_an_absolute_path(tmp_path: Path) -> None:
    """A REPL, an `exec`, a frozen import: there is no module directory, so there is nothing for a
    relative path to be relative to.

    Refused rather than resolved against `Path.cwd()`, which would find *a* file often enough to be
    trusted and then read somebody else's on the day it did not. The second half is asserted too:
    an absolute path from the same caller is read, because the refusal is about resolution and not
    about who is asking.
    """
    namespace: dict[str, object] = {"prompt_file": prompt_file}
    assert "__file__" not in namespace

    with pytest.raises(InputError, match="absolute"):
        exec('prompt_file("prompts/decompose.md")', namespace)

    where = tmp_path / "decompose.md"
    where.write_text(_DECOMPOSE, encoding="utf-8")
    namespace["where"] = str(where)
    exec("read = prompt_file(where)", namespace)
    assert namespace["read"] == _DECOMPOSE


# --- rule one: at most one reporting tool --------------------------------------------------------


def test_a_second_reporting_tool_is_refused_naming_both() -> None:
    """§3.3 defines a reporting step's result as *that tool's payload*, singular. With two,
    `run.step` would have to pick, and the pick would be framework policy over a workflow's own
    declaration."""
    with pytest.raises(InputError) as refusal:
        Role(name="review", instructions=_REVIEW, tools=(REPORT, REPORT_TICKETS))
    assert "report_findings" in str(refusal.value)
    assert "report_tickets" in str(refusal.value)


def test_one_reporting_tool_beside_plain_tools_is_ordinary() -> None:
    role = Role(
        name="review",
        instructions=_REVIEW, tools=(_plain("read_spec"), REPORT, _plain("grep"))
    )
    found = _reporting_of(role)
    assert found is not None
    assert found.name == "report_findings"


def test_a_duplicate_tool_name_is_refused_as_an_agent_task_would_refuse_it() -> None:
    """`AgentTask.__post_init__`'s check, one layer earlier and in its words - `ReportingTool` does
    the same for `Tool`'s two. A model names the tool it is calling, so a duplicate is a call no
    backend can resolve to one handler."""
    with pytest.raises(InputError) as refusal:
        Role(
            name="review",
            instructions=_REVIEW,
            tools=[_plain("read"), _plain("read")],
        )
    assert "read" in str(refusal.value)


def test_a_plain_tool_colliding_with_the_reporting_tool_is_refused_too() -> None:
    """The collision that only this layer can see as a collision: downstream the declaration has
    already become an ordinary `Tool`, so the two are indistinguishable by then."""
    with pytest.raises(InputError) as refusal:
        Role(
            name="review",
            instructions=_REVIEW,
            tools=(_plain(REPORT.name), REPORT),
        )
    assert REPORT.name in str(refusal.value)


# --- rule two: on_question implies MID_RUN_QUESTIONS ----------------------------------------------


def test_declaring_on_question_requires_mid_run_questions() -> None:
    """§3.7: "This makes `MID_RUN_QUESTIONS` load-bearing." Folded in here so that preflight is one
    containment with no special case, and so that the check cannot be lost by not being typed."""
    decompose = Role(
        name="decompose",
        instructions="Propose tickets, ask for approval, revise until approved, then report.",
        tools=[REPORT_TICKETS],
        on_question=_answer,
    )
    assert Capability.MID_RUN_QUESTIONS in decompose.requires


def test_the_capability_is_added_beside_the_ones_the_author_declared() -> None:
    """Folded in, not substituted for: an author who also needs `FILE_EDIT` keeps it."""
    role = Role(
        name="implement",
        instructions=_IMPLEMENT,
        requires={Capability.FILE_EDIT, Capability.SHELL},
        on_question=_answer,
    )
    assert role.requires == frozenset(
        {Capability.FILE_EDIT, Capability.SHELL, Capability.MID_RUN_QUESTIONS}
    )


def test_declaring_it_as_well_as_the_handler_changes_nothing() -> None:
    """A set, so saying it twice says it once. An author who prefers to write it stays right."""
    stated = Role(
        name="review",
        instructions=_REVIEW,
        requires={Capability.MID_RUN_QUESTIONS},
        on_question=_answer,
    )
    implied = Role(name="review", instructions=_REVIEW, on_question=_answer)
    assert stated.requires == implied.requires


def test_the_implication_runs_one_way_only() -> None:
    """`requires={MID_RUN_QUESTIONS}` with no handler says the prompt may invite the agent to ask
    and the author wants a backend that can. Over-declaring is the author's business; refusing it
    would be this module inventing a policy about what a requirement means."""
    role = Role(
        name="review",
        instructions=_REVIEW,
        requires={Capability.MID_RUN_QUESTIONS},
    )
    assert role.on_question is None
    assert role.requires == frozenset({Capability.MID_RUN_QUESTIONS})


def test_a_role_with_no_handler_requires_nothing_it_was_not_given() -> None:
    assert Capability.MID_RUN_QUESTIONS not in REVIEWER.requires


@pytest.mark.asyncio
async def test_the_handler_is_the_ports_own_shape_and_is_called_as_one() -> None:
    """`QuestionHandler` rather than a respelled `Callable`, so that what a role declares and what
    `AgentRunner.run` accepts are one type and cannot drift apart."""
    role = Role(name="review", instructions=_REVIEW, on_question=_answer)
    assert role.on_question is not None
    answer = await role.on_question(Question(prompt="Ship it?", options=("yes", "no")))
    assert answer == Answer(text="yes")


def test_neither_the_handler_nor_the_requirements_reach_the_fingerprint() -> None:
    """`base_of` takes instructions, model, restrictions and tools. So a closure is safe on a role
    where `AgentTask` refuses one, and the capability folded in above cannot move a digest."""
    asking = replace(REVIEWER, on_question=_answer, requires={Capability.FILE_EDIT})
    assert _base(asking) == _base(REVIEWER)


def test_nothing_here_is_checked_against_a_provider() -> None:
    """Preflight is stage 16 and it needs a runner to ask; nothing in `sdk/` may touch a port. A
    role that no installed backend could serve is declared without complaint, and dies at second
    zero later - which is where §3.2 puts that death."""
    impossible = _unservable()
    assert impossible.requires == frozenset(Capability)
    assert impossible.model is OpenAI.LUNA


# --- rule three: tools implies TOOL_CALLING -------------------------------------------------------
#
# Stage 17's finding, closed at 19.2 on the three arguments the section above is written on: a
# second declaration carries no information and can only be forgotten, the implication runs one way
# only, and a derived member cannot move a digest. The third is re-measured here rather than
# inherited, because this implication's trigger *is* a fingerprint term where `on_question` is not.


def test_declaring_a_reporting_tool_requires_tool_calling() -> None:
    """A role that offers a tool needs a backend able to call one, and there is no role for which
    that is false. Forgetting to say so used to be accepted here and refused at preflight - far
    from the line that needs fixing - or, worse, run: an agent never offered its reporting tool
    cannot fire it, so the step ends with no payload and `RoleIncompleteError` at exit 6."""
    assert Capability.TOOL_CALLING in REVIEWER.requires


def test_a_plain_tool_implies_it_too_and_not_only_a_reporting_one() -> None:
    """The implication is about `tools`, not about reporting: `AgentTask.tools` holds ordinary
    `Tool`s either way, and a backend that cannot call one has nowhere to put either kind."""
    role = Role(name="review", instructions=_REVIEW, tools=[_plain("read_spec")])
    assert role.requires == frozenset({Capability.TOOL_CALLING})


def test_tool_calling_is_added_beside_the_ones_the_author_declared() -> None:
    """Folded in, not substituted for. `REVIEWER` typed `requires={SHELL}` and keeps it."""
    assert REVIEWER.requires == frozenset({Capability.SHELL, Capability.TOOL_CALLING})


def test_declaring_tool_calling_as_well_as_the_tool_changes_nothing() -> None:
    """A set, so saying it twice says it once. An author who prefers to write it stays right."""
    stated = Role(
        name="review",
        instructions=_REVIEW,
        tools=[REPORT],
        requires={Capability.TOOL_CALLING},
    )
    implied = Role(name="review", instructions=_REVIEW, tools=[REPORT])
    assert stated.requires == implied.requires == frozenset({Capability.TOOL_CALLING})


def test_the_tool_calling_implication_runs_one_way_only() -> None:
    """`requires={TOOL_CALLING}` with no tools is left exactly as written - the prompt may tell the
    agent to use its harness's own, and over-declaring is the author's business. Refusing it would
    be this module inventing the third policy in a row it has declined to invent."""
    role = Role(
        name="review",
        instructions=_REVIEW,
        requires={Capability.TOOL_CALLING},
    )
    assert role.tools == ()
    assert role.requires == frozenset({Capability.TOOL_CALLING})


def test_a_role_with_no_tools_requires_nothing_it_was_not_given() -> None:
    """An effect step's role, which is §3.3's other step kind: no tools, result `null`."""
    assert IMPLEMENTER.tools == ()
    assert Capability.TOOL_CALLING not in IMPLEMENTER.requires


def test_folding_tool_calling_in_moves_no_digest_although_its_trigger_is_a_term() -> None:
    """The one argument that had to be checked again rather than inherited from `on_question`.

    `base_of` fingerprints instructions, model, restrictions and tools, so `tools` **is** a term
    where `on_question` is not - and a fold behind a term looks, at a glance, like it could move a
    digest. It cannot, because what the fold writes is a member of `requires`, and `requires` is
    not a term. Both halves are measured: declaring the capability by hand and letting the fold do
    it are one digest, and the tool itself is what moved the digest all along. So no role's digest
    is different today from what it was before this implication existed.
    """
    typed = replace(REVIEWER, requires={Capability.TOOL_CALLING})
    folded = replace(REVIEWER, requires=frozenset())
    toolless = replace(REVIEWER, tools=(), requires=frozenset())

    assert _base(typed) == _base(folded), (
        "a role that typed `requires={TOOL_CALLING}` and one that had it folded in fingerprint "
        "differently, so `requires` has become a term and every existing role's digest has moved"
    )
    assert _base(folded) != _base(toolless), (
        "declaring a tool did not move the digest, so §3.6 rule 4's three tool terms are not "
        "reaching `base_of` and this test measures nothing about the fold riding behind them"
    )


# --- the type chain §3.3 promises ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_reporting_roles_payload_type_survives_into_a_variable() -> None:
    """§3.3: `findings = await run.step(reviewer())` then `findings.high()`. `assert_type`
    is the half `mypy --strict` checks; the call below is the half pytest checks."""
    assert_type(REVIEWER, Role[Findings])
    findings = await _step(REVIEWER, _ONE_HIGH)
    assert_type(findings, Findings)
    assert [found.file for found in findings.high()] == ["a.py"]


@pytest.mark.asyncio
async def test_an_effect_roles_result_is_none() -> None:
    """§3.3: "Result is `null`; the effect is commits." `None` rather than `object` because that is
    the true statement, and because mypy then refuses to let the value be bound to a name at all."""
    assert_type(IMPLEMENTER, Role[None])
    assert_type(await _step(IMPLEMENTER), None)


def test_the_reporting_tool_is_found_at_its_payload_type_by_an_ordinary_scan() -> None:
    """Which is why `Role` carries no accessor for it. If the `isinstance` did not narrow to
    `ReportingTool[P]`, leaving one out would be a landmine for 12.1 rather than a choice."""
    assert_type(_reporting_of(REVIEWER), ReportingTool[Findings] | None)
    assert_type(_reporting_of(IMPLEMENTER), ReportingTool[None] | None)
    assert (_reporting_of(REVIEWER), _reporting_of(IMPLEMENTER)) == (REPORT, None)


def test_the_shapes_that_infer_p_from_the_declared_tools() -> None:
    """Measured, not assumed. A homogeneous list, an empty one, a list of plain tools, and a tuple
    of any mixture: all four solve `P` from what `tools=` was given."""
    only_reporting = Role(name="review", instructions=_REVIEW, tools=[REPORT])
    assert_type(only_reporting, Role[Findings])

    nothing_declared = Role(name="implement", instructions=_IMPLEMENT)
    assert_type(nothing_declared, Role[None])

    empty = Role(name="implement", instructions=_IMPLEMENT, tools=[])
    assert_type(empty, Role[None])

    plain_only = Role(
        name="implement",
        instructions=_IMPLEMENT,
        tools=[_plain("read")],
    )
    assert_type(plain_only, Role[None])

    mixed_tuple = Role(
        name="review",
        instructions=_REVIEW,
        tools=(_plain("read"), REPORT),
    )
    assert_type(mixed_tuple, Role[Findings])

    assert [role.instructions for role in (only_reporting, mixed_tuple)] == [_REVIEW, _REVIEW]


def test_a_mixed_list_display_does_not_infer_p_and_says_so_at_the_declaration() -> None:
    """The one shape that does not solve: mypy must choose a single item type for a list before it
    can solve `P`, and the join of two unrelated classes is `object`, so the default stands and the
    item is refused against `Tool | ReportingTool[None]`.

    The `type: ignore` is the assertion. `--strict` warns on an unused one, so a mypy that learns to
    infer this shape fails this line and sends somebody back to the module docstring."""
    mixed_list = Role(
        name="review",
        instructions=_REVIEW,
        tools=[_plain("read"), REPORT],  # type: ignore[list-item]
    )
    assert_type(mixed_list, Role[None])
    found = _reporting_of(mixed_list)
    assert_type(found, ReportingTool[None] | None)  # only the static type went to the default
    assert found is not None and found.name == REPORT.name  # the value itself is exactly right


def test_the_explicit_parameter_is_the_fallback_and_it_is_checked() -> None:
    """Both directions. Naming the right parameter recovers the mixed-list spelling at its real
    type; naming the wrong one is an error, so the fallback is checked rather than believed."""
    stated = Role[Findings](
        name="review",
        instructions=_REVIEW,
        tools=[_plain("read"), REPORT],
    )
    assert_type(stated, Role[Findings])

    wrong = Role[Tickets](
        name="review",
        instructions=_REVIEW,
        tools=[REPORT],  # type: ignore[list-item]
    )
    assert wrong.instructions == _REVIEW


def test_a_bare_role_annotation_is_legal_under_disallow_any_generics() -> None:
    """The reason the parameter has a default at all, and `Run[P = object]`'s reason before it: a
    workflow that never reads a step's result should not have to spell the parameter."""
    roles: Sequence[Role] = [IMPLEMENTER]
    assert_type(roles[0], Role[None])
    assert roles[0] is IMPLEMENTER


# --- RoleIncompleteError -------------------------------------------------------------------------


def test_role_incomplete_resolves_to_six_through_exit_code_for() -> None:
    """`UpstreamUnexpected`: it answered something we don't understand. The far side worked; our
    expectation of what it would do is what failed, which sends the reader to the prompt."""
    assert exit_code_for(RoleIncompleteError) == 6
    assert exit_code_for(RoleIncompleteError("the reviewer never called report_findings")) == 6


def test_it_gets_that_code_by_inheritance_and_appears_in_no_table() -> None:
    """The pair is the mechanism, and neither half is the claim on its own: a table entry would
    make the code survive a broken MRO walk, and absence alone would survive it resolving to 70."""
    assert RoleIncompleteError not in EXIT_CODES
    assert issubclass(RoleIncompleteError, UpstreamError)


def test_a_workflow_catching_upstream_errors_catches_it() -> None:
    """Which is the whole point of it descending from that branch rather than standing alone: a
    workflow's retry loop written against the hierarchy does not need to know this class exists."""
    with pytest.raises(UpstreamError):
        raise RoleIncompleteError("the reviewer never called report_findings")
    with pytest.raises(AglError):
        raise RoleIncompleteError("the reviewer never called report_findings")


def test_it_carries_a_message_and_nothing_else() -> None:
    """12.1 builds the message, out of `AgentOutcome.stop_reason` and `AgentOutcome.text`; this
    module supplies the name and the exit code and holds no vocabulary of its own for either."""
    raised = RoleIncompleteError("report_findings was never called; the agent ran out of turns")
    assert "report_findings" in str(raised)


# --- the terms a role contributes to a step's fingerprint ----------------------------------------


def test_the_four_terms_of_a_role_are_the_four_base_of_takes() -> None:
    """Not a restatement of `base_of`: the measurement is that a role's own fields are exactly what
    12.1 hands it, so a role can be fingerprinted without anything being derived on the way."""
    assert len(_base(REVIEWER)) == 64
    assert _base(REVIEWER) != _base(_reviewer_on_claude())
    assert _base(REVIEWER) != _base(replace(REVIEWER, restrictions=frozenset()))
    assert _base(REVIEWER) != _base(replace(REVIEWER, tools=()))


def test_a_roles_reporting_tool_reaches_the_digest_through_its_derived_schema() -> None:
    """The cascade §3.6 promises, one link out from `tests/sdk/test_tools.py`: change what the agent
    is asked to report and the step that asked re-runs."""

    @dataclass(frozen=True)
    class Wider:
        summary: str
        findings: list[Finding]
        reviewed_at: str = ""

    widened = Role(
        name="review",
        instructions=REVIEWER.instructions,
        restrictions=REVIEWER.restrictions,
        tools=[reporting_tool(REPORT.name, REPORT.description, Wider)],
    )
    assert _base(REVIEWER) != _base(widened, model=REVIEWER.model)


def test_a_roles_declared_schema_is_json_the_way_an_adapter_needs_it() -> None:
    """A role is handed straight to `AgentTask` and on to a vendor, so what it carries has to be
    writable. The proxy wrapping is `ReportingTool`'s; this is the measurement that it survives."""
    found = _reporting_of(REVIEWER)
    assert found is not None
    assert json.loads(json.dumps(dict(found.payload_schema)))["type"] == "object"


def test_a_model_id_is_the_only_vendor_word_a_role_carries() -> None:
    """§3.2's line: model *names* cross, and vendor syntax, types, exceptions and option objects do
    not. Every other term is AGL's own vocabulary, which is what lets one workflow name two."""
    assert isinstance(REVIEWER.model, ModelId)
    assert all(isinstance(named, Restriction) for named in REVIEWER.restrictions)
    assert all(isinstance(named, Capability) for named in REVIEWER.requires)
