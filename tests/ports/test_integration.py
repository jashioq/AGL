"""What `IntegrationOutcome` and `Conflict` promise: one answer, and enough of it to act on.

`Integrator` itself is not touched here - not even a null implementation - for `test_history.py`'s
reason: a suite that writes its own subject writes a subject that passes. The contract belongs to
the stage that writes the first real adapter.

That leaves two types and three genuine things. **The exactly-one invariant** is checked in both
directions, because the two failures mean opposite things: neither field set is an outcome that says
nothing happened at all, and both set is one that says the work landed and also did not. **The
`conflicted` property** is what §3.3's worked example reads off `run.integrate()`, so it is pinned
against both shapes rather than assumed to follow from the invariant. And **an empty `paths`** is
asserted to be legal, because it is a design decision an implementation depends on - an integrator
that cannot enumerate what collided has to be able to say so - and a later reader tightening it into
a refusal would break exactly the implementation the port exists to allow.
"""

from dataclasses import FrozenInstanceError, fields

import pytest

from agl.ports.errors import InternalError
from agl.ports.integration import Conflict, IntegrationOutcome

HEAD = "9d0c1c4b0a2f1e6d5c4b3a29187f6e5d4c3b2a19"


def test_work_that_landed_reports_where_the_target_is_now() -> None:
    """A head and no conflict: the one shape the framework carries on from."""
    outcome = IntegrationOutcome(head=HEAD)
    assert outcome.conflicted is False
    assert outcome.head == HEAD
    assert outcome.conflict is None


def test_a_landing_that_changed_nothing_still_landed() -> None:
    """Work already contained in the target reports the target's unchanged head - not a conflict,
    and not a third case."""
    before = IntegrationOutcome(head=HEAD)
    assert IntegrationOutcome(head=HEAD) == before
    assert before.conflicted is False


def test_work_that_did_not_land_carries_what_stopped_it() -> None:
    """A conflict and no head - the shape that leaves the target held, owing a retry or abort."""
    conflict = Conflict(paths=("src/agl/ports/integration.py",), summary="both sides edited it")
    outcome = IntegrationOutcome(conflict=conflict)
    assert outcome.conflicted is True
    assert outcome.head is None
    assert outcome.conflict is conflict


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param({}, id="neither: nothing happened at all"),
        pytest.param({"head": None, "conflict": None}, id="neither, said out loud"),
        pytest.param(
            {"head": HEAD, "conflict": Conflict(paths=(), summary="cannot be combined")},
            id="both: landed and also did not",
        ),
    ],
)
def test_an_outcome_that_is_not_exactly_one_answer_is_refused(outcome: dict[str, object]) -> None:
    """`InternalError`, not `InputError`: the framework built this out of what an adapter said."""
    with pytest.raises(InternalError):
        IntegrationOutcome(**outcome)  # type: ignore[arg-type]


def test_an_empty_head_names_no_state() -> None:
    """Distinct from the invariant above: exactly one answer, and that answer is unreadable."""
    with pytest.raises(InternalError):
        IntegrationOutcome(head="")


def test_the_fields_are_the_two_answers_and_nothing_else() -> None:
    """Pinned by hand, because "exactly one of two" is the whole design of this type: a third field
    should have to be argued for in the docstring rather than merely added."""
    assert [field.name for field in fields(IntegrationOutcome)] == ["head", "conflict"]
    assert [field.name for field in fields(Conflict)] == ["paths", "summary"]


def test_an_integrator_that_cannot_list_what_collided_says_so_in_the_summary() -> None:
    """The empty tuple is legal and load-bearing: a far side that can only answer "these cannot be
    combined cleanly" is a real implementation, and `()` is how it stays honest."""
    conflict = Conflict(paths=(), summary="the change request cannot be combined cleanly")
    assert conflict.paths == ()
    assert IntegrationOutcome(conflict=conflict).conflicted is True


def test_a_conflict_lists_the_paths_in_the_repository_s_own_words() -> None:
    """Repository-relative, forward slashes - `history.FileChange.path`'s convention and type."""
    conflict = Conflict(
        paths=("src/agl/ports/integration.py", "docs/agl-refactor-plan.md"),
        summary="2 files could not be combined",
    )
    assert conflict.paths == ("src/agl/ports/integration.py", "docs/agl-refactor-plan.md")
    assert conflict == Conflict(paths=conflict.paths, summary=conflict.summary)


@pytest.mark.parametrize(
    "conflict",
    [
        pytest.param({"paths": (), "summary": ""}, id="explains nothing at all"),
        pytest.param({"paths": ("a.py",), "summary": ""}, id="paths, and no line for a person"),
        pytest.param({"paths": ("",), "summary": "something collided"}, id="a path naming no file"),
        pytest.param(
            {"paths": ("a.py", ""), "summary": "something collided"}, id="one empty among several"
        ),
    ],
)
def test_a_conflict_nobody_could_act_on_is_refused(conflict: dict[str, object]) -> None:
    """The person at the workflow's screen is choosing between `retry` and `abort`; this is what
    they are choosing on."""
    with pytest.raises(InternalError):
        Conflict(**conflict)  # type: ignore[arg-type]


def test_both_types_are_frozen() -> None:
    """Values: checked once on the way in, and not editable afterwards. An outcome a caller can
    edit is one that can be made to say it landed after it did not."""
    outcome = IntegrationOutcome(head=HEAD)
    with pytest.raises(FrozenInstanceError):
        outcome.head = None  # type: ignore[misc]
    conflict = Conflict(paths=(), summary="cannot be combined")
    with pytest.raises(FrozenInstanceError):
        conflict.summary = "something else"  # type: ignore[misc]
