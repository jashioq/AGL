"""What a fingerprint promises: the same step twice is one digest, and a different step is another.

Every rule this module is built on fails as **replay never hits** - a digest that differs from the
one on disk, an entry that is not found, an agent that runs again and a bill nobody asked for. None
of them raises. So there is no test here of the form "it did not crash": each one below is either
two computations that must agree, or two that must differ, and the interesting half of the suite is
the agreements.

**Two of those agreements cannot be proved inside one interpreter, and are the reason this file
spawns processes.** A `frozenset`'s iteration order is fixed for the life of a process and one
object's `id()` never moves while it is alive, so a same-process test of rule 2 (sort every set) or
rule 3 (no `repr()` shortcut) passes exactly as happily against the bug it exists to catch. Both are
therefore run in fresh interpreters under `PYTHONHASHSEED` values measured to produce different
iteration orders, and both carry a **second** assertion: that the thing being varied actually
varied. Without it, a day when the seeds stop differing is a day these two tests silently stop
proving anything while staying green - which is the move `scripts/check`'s paid-endpoint gate makes
when it poisons the environment before running its probe rather than reading a fixture's tick.

The counter is pinned against §3.6's own arithmetic, `sha256(base + ":" + str(n))`, written out here
rather than imported, so the suite is not checking the module against itself. And the fingerprint's
terms are pinned exhaustively: every one of role, instructions, model, restrictions, each of a
tool's three contributed fields, every input and the head changes the base, and the same arguments
twice do not - because a term that quietly stopped counting would be a step that replays across an
edit that should have re-run it, which is the failure §3.6 says fingerprinting exists to prevent.
"""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from agl.ports.agent import Claude, ModelId, Restriction, Tool, ToolResult
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome, RunScope, step_entry
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.sdk._engine.journal import Fingerprints, base_of, canonical_json

_SCOPE: Final = RunScope(ProjectName("myapp"), RunLabel("auth"))
_STEP: Final = StepName("implement")
_HEAD: Final = "4a91c07f2b3e8d15c6a0b7f31d92e8054c6a0f13"

# Any string at all: the counter never looks inside a base. A real-shaped one so that what the
# assertions print when they fail looks like what the journal actually passes.
_BASE: Final = "9f2c4e" + "b" * 54 + "a71b"


async def _never_called(payload: Mapping[str, JsonValue]) -> ToolResult:
    """A handler is a callable and a callable's `repr` carries an object id, so no fingerprint may
    hold one. Nothing in this suite runs an agent, which is why nothing calls this."""
    return ToolResult(text="")


_HANDLER: Final[Callable[[Mapping[str, JsonValue]], Awaitable[ToolResult]]] = _never_called
_SCHEMA: Final[Mapping[str, JsonValue]] = MappingProxyType(
    {"type": "object", "properties": {"tickets": {"type": "array"}}}
)
_INPUTS: Final[Mapping[str, object]] = MappingProxyType({"request": "add oauth", "concurrent": 4})
_RESTRICTIONS: Final[AbstractSet[Restriction]] = frozenset(
    {Restriction.NO_VCS_WRITES, Restriction.NO_NETWORK}
)


def _tool(
    *,
    name: str = "report_tickets",
    description: str = "report the tickets you decomposed the request into",
    payload_schema: Mapping[str, JsonValue] = _SCHEMA,
) -> Tool:
    """A tool built the ordinary way, so `payload_schema` really is a `MappingProxyType`."""
    return Tool(
        name=name, description=description, payload_schema=payload_schema, handler=_HANDLER
    )


def _base(
    *,
    instructions: str = "implement the ticket and leave the tree building",
    model: ModelId = Claude.SONNET,
    restrictions: AbstractSet[Restriction] = _RESTRICTIONS,
    tools: Sequence[Tool] | None = None,
    inputs: Mapping[str, object] = _INPUTS,
    head: str = _HEAD,
) -> str:
    """One base, with every term at a baseline value and any one of them overridable."""
    return base_of(
        instructions=instructions,
        model=model,
        restrictions=restrictions,
        tools=(_tool(),) if tools is None else tools,
        inputs=inputs,
        head=head,
    )


def _digest(base: str, count: int) -> str:
    """§3.6's third line, written out rather than imported: `sha256(base + ":" + str(n))`."""
    return hashlib.sha256(f"{base}:{count}".encode()).hexdigest()


# --- Rule 1: the counter is scoped per (namespace, step name) ----------------------------------


def test_two_concurrent_siblings_both_get_n_zero_rather_than_racing_for_it() -> None:
    """The failure a per-invocation counter produces, and the one §3.6 spells out.

    `T-01` and `T-02` both call `step("implement", implementer)` with the same role, no inputs of
    their own and the same parent head, so their bases are identical by construction. A counter
    that did not know about namespaces would hand `n = 0` to whichever arrived first, and on resume
    the other one arrives first - so each child looks in its own `worktrees/<id>/steps/implement/`
    for a digest that is not there and both re-run, forever, silently.
    """
    counter = Fingerprints()
    first = counter.next(_SCOPE.inside(Namespace("T-01")), _STEP, _BASE)
    second = counter.next(_SCOPE.inside(Namespace("T-02")), _STEP, _BASE)
    assert first == _digest(_BASE, 0)
    assert second == _digest(_BASE, 0)


def test_the_order_two_siblings_happen_to_run_in_does_not_decide_either_digest() -> None:
    """The same claim from the angle that actually differs between a run and its resume.

    Concurrency does not reorder anything on disk; it reorders the calls. So the test is that the
    interleaving is not an input: A-then-B on one counter and B-then-A on another must give A the
    same digest both times, and B the same digest both times.
    """
    t01, t02 = _SCOPE.inside(Namespace("T-01")), _SCOPE.inside(Namespace("T-02"))
    forwards = Fingerprints()
    one_way = {
        "T-01": forwards.next(t01, _STEP, _BASE),
        "T-02": forwards.next(t02, _STEP, _BASE),
    }
    backwards = Fingerprints()
    other_way = {
        "T-02": backwards.next(t02, _STEP, _BASE),
        "T-01": backwards.next(t01, _STEP, _BASE),
    }
    assert one_way == other_way


def test_a_retry_loop_in_one_scope_counts_up_so_it_cannot_hit_its_own_cache() -> None:
    """§3.6's "why the counter": same role, no inputs, no commits, and nothing else varying."""
    counter = Fingerprints()
    digests = [counter.next(_SCOPE, _STEP, _BASE) for _ in range(3)]
    assert digests == [_digest(_BASE, 0), _digest(_BASE, 1), _digest(_BASE, 2)]
    assert len(set(digests)) == 3


def test_two_step_names_in_one_scope_count_independently() -> None:
    """`steps/review_quality/` and `steps/review_security/` are two directories, so two ledgers.

    Identical role, identical inputs, identical head - which is an ordinary thing for two reviewers
    of the same worktree - and each must start at `n = 0` in its own directory. One shared count
    would give the second one `n = 1` and a digest no entry it ever wrote will match.
    """
    counter = Fingerprints()
    quality = counter.next(_SCOPE, StepName("review_quality"), _BASE)
    security = counter.next(_SCOPE, StepName("review_security"), _BASE)
    assert quality == security == _digest(_BASE, 0)


def test_a_digest_is_a_filename_the_layout_will_spend_without_asking_again() -> None:
    """The consumer: `home_layout._checked_digest` refuses anything that is not 64 lowercase hex."""
    digest = Fingerprints().next(_SCOPE, _STEP, _base())
    entry = step_entry(AglHome(Path("/agl-home")), _SCOPE, _STEP, digest)
    assert entry.name == f"{digest}.json"


# --- Rules 2 and 3, which only a second process can prove ----------------------------------------

# Measured on this machine while this was written: these six produce several different iteration
# orders of `frozenset(Restriction)` between them. They are asserted to still differ, below.
_SEEDS: Final = ("1", "3", "5", "11", "13", "31337")

_SORTED_SETS: Final = """
import json

from agl.ports.agent import Claude, Restriction
from agl.sdk._engine.journal import base_of

restrictions = frozenset(Restriction)
print(base_of(instructions="review", model=Claude.SONNET, restrictions=restrictions,
              tools=(), inputs={}, head="4a91c07f"))
print(json.dumps([str(restriction) for restriction in restrictions]))
"""

_UNPACKED_DATACLASSES: Final = """
from dataclasses import dataclass

from agl.ports.agent import Claude
from agl.sdk._engine.journal import base_of


@dataclass(frozen=True, repr=False)
class Finding:
    ticket: str
    severity: int


findings = [Finding("T-01", 3), Finding("T-02", 1)]
print(base_of(instructions="fix", model=Claude.SONNET, restrictions=frozenset(),
              tools=(), inputs={"findings": findings}, head="4a91c07f"))
print(repr(findings[0]))
"""


def _under_seeds(script: str) -> list[list[str]]:
    """`script` run once per seed in a fresh interpreter, each run's stdout split into lines.

    `sys.executable` is this repository's venv python and `agl` is importable from it at any cwd,
    so the child needs no path setup and inherits nothing this file had to arrange. The only thing
    changed about the environment is `PYTHONHASHSEED`; everything the repo-wide guard puts there
    is passed straight through untouched.
    """
    runs: list[list[str]] = []
    for seed in _SEEDS:
        finished = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        assert finished.returncode == 0, f"PYTHONHASHSEED={seed} child failed:\n{finished.stderr}"
        runs.append(finished.stdout.splitlines())
    return runs


def test_a_set_of_restrictions_fingerprints_the_same_in_every_process() -> None:
    """Rule 2, and it cannot be shown here: within one interpreter the order never changes.

    `Restriction` is a `StrEnum`, `Enum.__hash__` hashes the member name, and `PYTHONHASHSEED`
    randomises that - so a role declaring `frozenset(Restriction)` is the same role tomorrow and a
    journal that iterated the set would compute a different base for it. The second assertion is
    what makes the first mean anything: if these seeds ever stop varying the raw order, the first
    assertion holds for free and proves nothing at all.
    """
    runs = _under_seeds(_SORTED_SETS)
    digests = {lines[0] for lines in runs}
    orders = {lines[1] for lines in runs}
    assert len(digests) == 1, (
        f"{len(digests)} different bases over {len(_SEEDS)} interpreters: a set reached the "
        f"canonical text in iteration order, so every resume in a new process re-runs the step"
    )
    assert len(orders) > 1, (
        f"these seeds no longer vary the iteration order of frozenset(Restriction) - every one of "
        f"them gave {orders} - so this test proves nothing and needs new seeds"
    )


def test_a_dataclass_in_inputs_fingerprints_the_same_in_every_process() -> None:
    """Rule 3, and the same argument: one object's `id()` does not move while it is alive.

    §3.3's tickets example passes `findings=highs`, a list of the workflow's own dataclasses, and
    `repr()` is the one-line way to make that hashable. `@dataclass(repr=False)` gives these
    instances `object.__repr__`, which is what the default `repr` of anything without one embeds -
    a heap address. The second assertion is again the non-vacuous half: a `repr()` shortcut is only
    unstable if the address actually moved between these interpreters.
    """
    runs = _under_seeds(_UNPACKED_DATACLASSES)
    digests = {lines[0] for lines in runs}
    reprs = {lines[1] for lines in runs}
    assert len(digests) == 1, (
        f"{len(digests)} different bases over {len(_SEEDS)} interpreters: something unstable "
        f"across processes reached the canonical text of a workflow's own dataclass"
    )
    assert len(reprs) > 1, (
        f"every interpreter printed the same repr - {reprs} - so the heap address did not move "
        f"and this test cannot tell a repr() shortcut apart from dataclasses.asdict"
    )


# --- Rule 3, in this process: what the refusal has to say ----------------------------------------


def test_a_value_the_walker_cannot_take_names_its_type_and_the_path_to_it() -> None:
    """`inputs.findings[0].deadline is a datetime` - the type alone would not be findable.

    A value three levels down a list of the workflow's own dataclasses is the shape §3.3 actually
    passes, and `dataclasses.asdict` deep-copies a `datetime` field out as a `datetime`. It is an
    `InputError` and not an `InternalError`: this came from a workflow author's `**inputs`, so exit
    2 sends them to their own declaration rather than to a bug report about the framework.
    """

    @dataclass(frozen=True)
    class Finding:
        ticket: str
        deadline: datetime

    with pytest.raises(InputError) as caught:
        _base(inputs={"findings": [Finding("T-01", datetime(2026, 8, 18, tzinfo=UTC))]})
    message = str(caught.value)
    assert "inputs.findings[0].deadline" in message, message
    assert "datetime" in message, message
    assert "fingerprint" in message, "the message has to say why, not only what"


def test_a_plain_object_in_inputs_is_refused_at_the_key_that_holds_it() -> None:
    """The shallow case, which is the one somebody actually hits first."""
    with pytest.raises(InputError) as caught:
        _base(inputs={"handle": object()})
    assert "inputs.handle is a object" in str(caught.value)


def test_the_walkers_other_refusals_each_name_what_they_found() -> None:
    """Non-finite floats, non-string keys, surrogates, and a dataclass class rather than one of it.

    A `dataclass` *class* is refused rather than unpacked: `asdict` cannot take one, and a workflow
    that passed the class where it meant an instance wants to hear so rather than to be handed a
    fingerprint over something else.
    """

    @dataclass(frozen=True)
    class Finding:
        ticket: str

    with pytest.raises(InputError, match="no spelling for"):
        canonical_json({"ratio": float("nan")})
    with pytest.raises(InputError, match="no spelling for"):
        canonical_json({"ratio": float("inf")})
    with pytest.raises(InputError, match="keyed by"):
        canonical_json({"counts": {1: "one"}})
    with pytest.raises(InputError, match="surrogate"):
        canonical_json({"text": chr(0xD83D) + chr(0xDE00)})
    with pytest.raises(InputError, match="cannot be canonicalised"):
        canonical_json({"finding": Finding})


# --- Rule 4: what a tool contributes, and what it must not --------------------------------------


def test_a_tool_built_the_ordinary_way_fingerprints_although_json_cannot_take_its_schema() -> None:
    """`Tool.__post_init__` wraps the schema in a `MappingProxyType`, and `json.dumps` refuses one.

    The `isinstance` is asserted rather than assumed, so that a day when `Tool` stops wrapping is a
    day this test says so instead of quietly becoming a test of nothing.
    """
    tool = _tool()
    assert isinstance(tool.payload_schema, MappingProxyType), "the hazard this test is about"
    with pytest.raises(TypeError):
        json.dumps(tool.payload_schema)
    assert len(_base(tools=(tool,))) == 64


def test_a_mapping_is_rebuilt_at_every_depth_and_not_only_at_the_top() -> None:
    """One `dict()` at the top level would leave a proxy nested inside a schema raising `TypeError`.

    JSON Schema nests by nature - `properties`, `items`, `$defs` - so the depth is not hypothetical
    the moment anything but `Tool.__post_init__` builds part of a schema.
    """
    nested = MappingProxyType({"properties": MappingProxyType({"id": {"type": "string"}})})
    with pytest.raises(TypeError):
        json.dumps(nested)
    assert canonical_json(nested) == '{"properties":{"id":{"type":"string"}}}'


def test_two_tools_differing_only_in_their_handler_are_one_fingerprint() -> None:
    """The handler is a callable whose `repr` embeds an object id, so it is not a term at all.

    A framework handler is built per invocation - it closes over the store and the entry being
    written - so a fingerprint containing one would differ from itself on the very next call.
    """

    async def other(payload: Mapping[str, JsonValue]) -> ToolResult:
        return ToolResult(text="a different handler entirely")

    declared = _tool()
    rebuilt = Tool(
        name=declared.name,
        description=declared.description,
        payload_schema=dict(declared.payload_schema),
        handler=other,
    )
    assert declared.handler is not rebuilt.handler
    assert _base(tools=(declared,)) == _base(tools=(rebuilt,))


def test_tools_keep_their_declared_order_rather_than_being_sorted_like_a_set() -> None:
    """A tuple's order is the author's and is stable across processes, so it is a real term."""
    first, second = _tool(name="report_tickets"), _tool(name="ask_the_operator")
    assert _base(tools=(first, second)) != _base(tools=(second, first))


# --- Rule 5: what "canonical" means ------------------------------------------------------------


def test_insertion_order_is_not_part_of_the_canonical_text() -> None:
    """`sort_keys=True`. Two dicts built by different code paths hold the same pairs, not the same
    order, and a workflow assembling inputs in a loop is exactly that case."""
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1}) == '{"a":2,"b":1}'
    assert _base(inputs={"request": "add oauth", "concurrent": 4}) == _base(
        inputs={"concurrent": 4, "request": "add oauth"}
    )


def test_the_separators_are_the_compact_ones_at_every_depth() -> None:
    """`separators=(",", ":")`. Under `json.dumps`'s defaults this same value carries `", "` and
    `": "`, so their absence is the assertion and the whole text is pinned beside it."""
    value: JsonValue = {"outer": {"a": [1, 2], "b": "x"}}
    text = canonical_json(value)
    assert ", " in json.dumps(value) and ": " in json.dumps(value), "the default this replaces"
    assert ", " not in text and ": " not in text
    assert text == '{"outer":{"a":[1,2],"b":"x"}}'


def test_a_non_ascii_value_is_escaped_because_the_escaping_is_a_stored_format_too() -> None:
    """`ensure_ascii=True`, pinned - and nothing else in this file can see which spelling was used.

    Both spellings parse back to the same value, so every other assertion in this suite holds under
    either one; and the two are different text, so they are different fingerprints. Flip the flag
    and every base ever computed over a single non-ASCII character silently reformats, and every
    step recorded under one re-runs its agent. That is rule 5's own failure arriving through the
    one flag rule 5 does not otherwise pin, which is why it gets an assertion of its own rather
    than being left to the flags in `_dumps`.

    Why the flag is `True` rather than `False`, and what refusing surrogates has to do with it, is
    argued in `journal.py::_checked_text`; this only holds the answer still.
    """
    text = canonical_json({"who": "caf\xe9"})
    assert text == '{"who":"caf\\u00e9"}'
    assert text.isascii(), "the text exists to be UTF-8 encoded and hashed, and ASCII always can be"
    assert json.loads(text) == {"who": "caf\xe9"}, "an escape is a spelling, not a different value"
    assert text != json.dumps(
        {"who": "caf\xe9"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ), "the other spelling of the same value, which would fingerprint as a different step"


def test_a_bool_and_the_int_it_equals_are_not_one_fingerprint() -> None:
    """`bool` is an `int`, so the two are taken by one branch and returned untouched. A branch that
    coerced would make a workflow passing a flag where it used to pass a count replay silently."""
    assert canonical_json({"x": True}) == '{"x":true}'
    assert canonical_json({"x": 1}) == '{"x":1}'
    assert _base(inputs={"concurrent": True}) != _base(inputs={"concurrent": 1})


def test_a_set_nested_inside_inputs_is_sorted_too_and_not_only_restrictions() -> None:
    """The shape claim; the cross-process claim is the one made under seeds above.

    Sorting only `restrictions` would leave a set that arrived through `**inputs` - including one
    `dataclasses.asdict` copies out of a frozen dataclass field as a `frozenset` - unsorted, which
    is the identical defect in a place nobody thought to look.
    """
    assert canonical_json({"t": {"b", "a"}}) == '{"t":["a","b"]}'
    assert canonical_json({"t": frozenset({"b", "a"})}) == '{"t":["a","b"]}'
    # Sorted on each element's own canonical text, which is what makes the order total without the
    # elements having to be comparable with each other - `1 < "a"` raises, `'1' < '"a"'` does not.
    assert canonical_json({"t": {2, 1, 10}}) == '{"t":[1,10,2]}'
    assert canonical_json([{"a", 1}]) == '[["a",1]]'


# --- Every term of the fingerprint, and the complement -------------------------------------------


def test_every_term_of_the_role_inputs_and_head_changes_the_fingerprint() -> None:
    """Nine terms, each varied alone. A term that stopped counting is a step that replays across
    the edit it should have re-run for - which is the whole of what §3.6 says fingerprints buy."""
    schema: Mapping[str, JsonValue] = {"type": "object", "properties": {"tickets": {}}}
    bases = {
        "baseline": _base(),
        "instructions": _base(instructions="implement the ticket, and stop at the first failure"),
        "model": _base(model=Claude.OPUS),
        "restrictions": _base(restrictions=frozenset({Restriction.NO_VCS_WRITES})),
        "tool name": _base(tools=(_tool(name="report_findings"),)),
        "tool description": _base(tools=(_tool(description="report what you found"),)),
        "tool payload_schema": _base(tools=(_tool(payload_schema=schema),)),
        "an input's value": _base(inputs={"request": "add oauth", "concurrent": 5}),
        "an input's key": _base(inputs={"request": "add oauth", "parallel": 4}),
        "head": _base(head="8c19f7ae4d2b0913e5f6a1c7d40b28e3f95a6d17"),
    }
    collisions = {
        name for name, base in bases.items() if name != "baseline" and base == bases["baseline"]
    }
    assert not collisions, f"these terms do not reach the fingerprint at all: {sorted(collisions)}"
    assert len(set(bases.values())) == len(bases), "two different steps share one fingerprint"


def test_the_same_role_inputs_and_head_are_the_same_base_twice() -> None:
    """The complement, and the half that replay actually depends on: nothing here is a nonce."""
    assert _base() == _base()
    assert len(_base()) == 64
