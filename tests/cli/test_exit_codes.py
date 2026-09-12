"""One table, consumed - and the one decision this module makes on top of it.

Three properties carry this file.

**The re-exported names are the port's own objects**, asserted by identity rather than by value. A
copy of `EXIT_CODES` would compare equal on the day it was made and would then be a second table,
free to drift from the first with nothing to notice; a copy of `exit_code_for` would answer
correctly about everything except the classes that arrived after it.

**The published numbers are pinned by hand.** They are the API a script branches on, so a change to
one should have to be typed twice - `tests/ports/test_errors.py` says the same about the table where
it lives, and this file says it again through the door `cli/` actually opens. Exhaustiveness is not
pinned by hand: the hierarchy is walked, so a branch added to `errors.py` and forgotten here fails.

**The decision is asserted structurally, not only behaviourally.** That a non-`AglError` exits 70 is
one assertion; that this module holds no table of its own is a scan of its source for an integer
literal, because "70 is not written here" is the actual claim and a passing behaviour test would go
on passing the moment somebody typed it. `KeyboardInterrupt` is settled the same way: the parameter
is annotated `Exception`, so `except BaseException` at the call site is a type error rather than a
convention, and the pair of assertions below is what makes that annotation load-bearing.

**The group rule is asserted on constructed groups, and that is the honest register for it.** A
`BaseExceptionGroup` is a value, so a group holding two `UpstreamError`s says everything about the
rule that a real `TaskGroup` would - the leaves are the same objects either way. What a constructed
group cannot say is that a group *reaches* the handler at all, which is a fact about `cli/main.py`
and is asserted there, through the console entry point, on workflows that open a `TaskGroup` for
real: `tests/cli/test_main.py`. Both halves are needed, and neither is the other's duplicate.

**A run and a command answer by that one rule, and one test holds them to it.** `joint_status` is
the rule over a set of codes: `exit_status` hands it a group's leaves, and `_refusal_status` in
`cli/commands/__init__.py` the refusals `agl get` and `agl update` went on past. `_OUTCOMES` hands
both the same outcomes, a 70 among some, so a second rule written into either caller fails there.
"""

import ast
import inspect
from typing import Final, get_type_hints
import pytest
from agl.cli import exit_codes
from agl.cli.commands import _refusal_status
from agl.cli.exit_codes import EXIT_CODES, exit_code_for, exit_status, joint_status, leaves
from agl.ports import errors
from agl.ports.errors import (
    AglError,
    ConflictError,
    DeniedError,
    DisagreeingRefusals,
    InputError,
    InternalError,
    NotFoundError,
    Stop,
    UpstreamError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)

# Every class the hierarchy defines, and the code a script sees for it. Written out, including the
# three that inherit rather than introduce one - `UpstreamUnavailable`, `UpstreamUnexpected` and the
# unmapped base - because what a caller of this module needs pinned is the answer, not the route.
_PUBLISHED: Final[tuple[tuple[type[AglError], int], ...]] = (
    (AglError, 70),
    (InputError, 2),
    (NotFoundError, 3),
    (ConflictError, 4),
    (DeniedError, 5),
    (UpstreamError, 6),
    (UpstreamUnavailable, 6),
    (UpstreamUnexpected, 6),
    (Stop, 7),
    (DisagreeingRefusals, 8),
    (InternalError, 70),
)

# Outcomes that arrive together, and the one status each set comes to whether a run's concurrent
# children raised them or a command went on past them. Written out for `_PUBLISHED`'s reason.
_OUTCOMES: Final[tuple[tuple[tuple[AglError, ...], int], ...]] = (
    ((NotFoundError("a"),), 3),
    ((NotFoundError("a"), NotFoundError("b")), 3),
    ((UpstreamUnavailable("a"), UpstreamUnexpected("b")), 6),
    ((NotFoundError("a"), InputError("b")), 8),
    ((NotFoundError("a"), InputError("b"), NotFoundError("c")), 8),
    ((Stop("a"), UpstreamError("b")), 8),
    ((DisagreeingRefusals("a"), NotFoundError("b")), 8),
    ((InternalError("a"),), 70),
    ((InternalError("a"), NotFoundError("b")), 70),
    ((InternalError("a"), NotFoundError("b"), InputError("c")), 70),
    ((Stop("a"), InternalError("b")), 70),
    ((DisagreeingRefusals("a"), InternalError("b")), 70),
)

class ReviewNotConverging(Stop):
    """A workflow's own reason to stop - in no table, and still worth 7."""

def _hierarchy() -> list[type[AglError]]:
    """Every class `agl.ports.errors` itself defines, walked rather than listed.

    The same discovery `tests/ports/test_errors.py` uses, for the same reason: a list is what goes
    stale the day somebody adds a branch. The `__module__` filter keeps `ReviewNotConverging` above,
    and any workflow's own subclass, out of the module's exhaustiveness.
    """
    seen: set[type[AglError]] = set()
    queue: list[type[AglError]] = [AglError]
    while queue:
        cls = queue.pop()
        if cls in seen:
            continue
        seen.add(cls)
        queue.extend(cls.__subclasses__())
    return sorted(
        (cls for cls in seen if cls.__module__ == AglError.__module__), key=lambda cls: cls.__name__
    )

# --- the re-export ------------------------------------------------------------------------------

def test_the_re_exported_names_are_the_ports_own_objects() -> None:
    """Not copies: a second `EXIT_CODES` is the second table this module exists not to have."""
    assert EXIT_CODES is errors.EXIT_CODES
    assert exit_code_for is errors.exit_code_for

def test_this_module_writes_no_number_of_its_own() -> None:
    """The claim "holds no table of its own", made mechanical.

    An integer literal anywhere in this module would be a code decided here rather than read out of
    `ports/errors.py` - which is how a second table starts, one number at a time. The answer for a
    non-`AglError` is `exit_code_for(InternalError)` precisely so that nothing has to be typed.
    """
    written = [
        node.value
        for node in ast.walk(ast.parse(inspect.getsource(exit_codes)))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ]
    assert not written, (
        f"agl/cli/exit_codes.py writes {written}, and it may write no number at all: the one "
        f"exception-to-exit-code table is `ports/errors.py`'s, and this module consumes it"
    )

# --- every class in the hierarchy ----------------------------------------------------------------

def test_every_published_class_resolves_to_its_published_code() -> None:
    """The numbers, through the door `cli/` opens, on an instance and on the class alike."""
    for cls, code in _PUBLISHED:
        assert exit_code_for(cls) == code, cls.__name__
        assert exit_status(cls("something happened")) == code, cls.__name__

def test_the_published_list_covers_every_class_the_hierarchy_defines() -> None:
    """Exhaustiveness by walking: a branch added to `errors.py` cannot skip the list above."""
    listed = {cls for cls, _ in _PUBLISHED}
    missing = sorted(cls.__name__ for cls in _hierarchy() if cls not in listed)
    assert not missing, f"error classes with no published code asserted here: {missing}"

def test_a_workflows_own_stop_subclass_resolves_to_seven_without_being_listed() -> None:
    """The MRO walk, from this side: 7 is how a script tells "needs you" from "broken"."""
    assert exit_status(ReviewNotConverging("two rounds and no convergence")) == 7

# --- the one decision ----------------------------------------------------------------------------

def test_an_exception_that_is_not_an_agl_error_is_our_bug() -> None:
    """The module's only decision. An adapter that failed to translate is what 70 reports."""
    assert exit_status(ValueError("something an adapter did not translate")) == 70
    assert exit_status(ValueError("x")) == exit_code_for(InternalError)

def test_an_unmapped_branch_and_an_untranslated_exception_agree() -> None:
    """One meaning for 70, arrived at from both sides - an unmapped `AglError` and no `AglError`
    at all are the same fault seen twice, and a script can act on neither differently."""

    class _UnmappedBranch(AglError):
        """A branch of the hierarchy nobody remembered to map."""

    assert exit_status(_UnmappedBranch("no code")) == exit_status(OSError("not ours to see"))

# --- the group rule -----------------------------------------------------------------------------

def test_a_single_leaf_group_is_worth_exactly_what_its_leaf_is_worth() -> None:
    """"Unwrap a single-exception group and map its leaf" - the parity, stated as one.

    The number is the point only in as much as it is the *same* number: `split` is written as a
    `TaskGroup`, so a chunk that could not reach the agent has to cost what `fix` costs when the
    same adapter raises the same class, or a script cannot tell one workflow's failures from the
    other's.
    """
    alone = UpstreamUnavailable("the agent backend could not be reached")

    assert exit_status(ExceptionGroup("unhandled errors in a TaskGroup", [alone])) == exit_status(
        alone
    )

def test_leaves_agree_when_their_codes_agree_and_not_when_their_classes_do() -> None:
    """"Several leaves that agree" is about the resolved code, which is the only thing published.

    `UpstreamUnavailable` and `UpstreamUnexpected` appear in no table - both inherit
    `UpstreamError`'s 6, deliberately, "so a caller that does not care which it was catches this
    and a script still sees one code". Two classes and one answer is therefore agreement, and a
    rule comparing classes would answer 8 for a run that failed one way twice.
    """
    unreachable = UpstreamUnavailable("its CLI is not on PATH")
    unparseable = UpstreamUnexpected("it finished with no reporting-tool payload")

    assert exit_status(ExceptionGroup("two chunks", [unreachable, unparseable])) == 6

def test_leaves_that_disagree_are_eight_because_no_one_of_them_is_the_answer() -> None:
    """"For leaves that disagree, 8" - a code of their own, and neither leaf's.

    A run that failed several different ways is genuinely not attributable to one code. The pair
    below is the smallest version of that: both are refusals a user can act on, they say to do
    different things, and any rule picking one of them would publish a number that named one
    failure and hid the other. 70 would hide both, sending an operator to report a bug in AGL about
    a run in which AGL had a name for everything that happened.
    """
    group = ExceptionGroup("two chunks", [UpstreamError("no answer"), ConflictError("taken")])

    assert exit_status(group) == 8
    assert exit_status(group) == exit_code_for(DisagreeingRefusals)

def test_a_deliberate_stop_beside_a_failure_is_eight_like_any_other_disagreement() -> None:
    """7 says the workflow ended on purpose and 6 that something broke, and no answer is both.

    A `Stop` is named as surely as a failure is, so it is compared like any other leaf rather than
    excused for being deliberate - a workflow's own subclass of it included, which reaches 7 up
    the class tree before it is compared at all.
    """
    stopped = Stop("nothing left to pick up")
    broke = UpstreamError("no answer")

    assert exit_status(ExceptionGroup("two chunks", [stopped, broke])) == 8
    assert exit_status(ExceptionGroup("two", [ReviewNotConverging("x"), ConflictError("y")])) == 8

def test_a_leaf_that_resolves_to_seventy_keeps_the_whole_group_at_seventy() -> None:
    """70 is not one answer among the others: it says AGL had no name for what was raised.

    So a group holding one is 70 whatever sits beside it - an untranslated exception, an
    `InternalError` or a branch nobody mapped, beside a failure, a deliberate end or several of
    them. 8 in its place would tell a script that every failure in the run had a name, and the one
    that had none is the one a report is for.
    """

    class _UnmappedBranch(AglError):
        """A branch of the hierarchy nobody remembered to map."""

    beside: tuple[list[Exception], ...] = (
        [OSError("not ours"), UpstreamError("no answer")],
        [InternalError("an invariant"), ConflictError("taken")],
        [_UnmappedBranch("no code"), InputError("unusable")],
        [Stop("done"), OSError("not ours")],
        [InternalError("an invariant"), UpstreamError("no answer"), ConflictError("taken")],
    )

    for mixed in beside:
        assert exit_status(ExceptionGroup("chunks", mixed)) == 70, mixed

def test_a_deliberate_stop_inside_a_group_is_still_seven() -> None:
    """The group rule's other half, and the half a `Stop` subclass reaches too.

    A workflow that raises `ReviewNotConverging` from inside a chunk has ended deliberately, and 7
    is how a script tells "needs you" from "broken" wherever the raise happened. Both spellings are
    asserted because the MRO walk and the group flattening are two separate resolutions and this is
    the case that needs both of them to hold at once.
    """
    assert exit_status(ExceptionGroup("one chunk", [Stop("nothing left to pick up")])) == 7
    assert exit_status(ExceptionGroup("one chunk", [ReviewNotConverging("no convergence")])) == 7

def test_a_leaf_resolves_the_same_however_deeply_its_group_is_nested() -> None:
    """Groups nest because `TaskGroup`s do, so the rule is about leaves and not about children.

    `split` opens a `TaskGroup` and a chunk may open its own, which makes "a single-exception
    group" a claim that has to survive one wrapper or twenty. A rule reading `group.exceptions` once
    would answer 70 for the deeper of the two below while answering 6 for the shallower, and the
    only difference between them is how the workflow spelled its concurrency.
    """
    leaf = UpstreamUnavailable("the agent backend could not be reached")
    shallow = ExceptionGroup("outer", [leaf])
    deep = ExceptionGroup("outer", [ExceptionGroup("inner", [ExceptionGroup("inmost", [leaf])])])

    assert exit_status(deep) == exit_status(shallow) == exit_status(leaf)

def test_a_disagreement_and_a_seventy_count_from_whatever_depth_the_leaf_sits_at() -> None:
    """The rule reads leaves, so both of its decisions are made about leaves and not about children.

    A rule reading `group.exceptions` once would resolve the inner group itself - no `AglError` - to
    70, and then hold at 70 a run in which every failure was named. The second assertion is the
    other direction: the leaf nobody translated is one group down, and it still decides the run.
    """
    upstream = UpstreamError("no answer")
    taken = ConflictError("taken")
    untranslated = OSError("not ours")

    assert exit_status(ExceptionGroup("outer", [ExceptionGroup("inner", [upstream]), taken])) == 8
    assert exit_status(ExceptionGroup("outer", [ExceptionGroup("in", [untranslated]), taken])) == 70

def test_a_leaf_nobody_translated_takes_part_in_agreement_like_any_other() -> None:
    """The module's one decision, reaching inside a group: an untranslated exception is our bug.

    So it resolves to 70 as a leaf exactly as it does on its own, and it is compared like any other
    leaf rather than excused from the comparison: it agrees with an `InternalError` beside it, and
    beside a named failure its 70 holds the group, as any leaf's 70 would - which is what keeps a
    failure nobody named from hiding behind a disagreement with one somebody did.
    """
    ours = ExceptionGroup("two chunks", [InternalError("an invariant"), OSError("not ours")])

    assert exit_status(ours) == 70
    assert exit_status(ExceptionGroup("one chunk", [OSError("not ours")])) == 70
    assert exit_status(ExceptionGroup("two chunks", [OSError("x"), InputError("y")])) == 70

def test_leaves_hands_back_every_exception_a_group_holds_and_nothing_else() -> None:
    """The walk `cli/main.py` names all of them with, asserted by identity and in order.

    Public for one reason: "naming all of them" is the half of the group rule that is a message, and
    the messages are written in `cli/main.py`. A second flattening over there would be free to
    disagree with this one about what a leaf is, so there is one walk and this is it - and the
    groups themselves are deliberately absent from what it yields, a group being the wrapper rather
    than something that happened.
    """
    first = UpstreamUnavailable("the agent backend could not be reached")
    second = ConflictError("another run holds the lease")
    group = ExceptionGroup("outer", [ExceptionGroup("inner", [first]), second])

    assert list(leaves(group)) == [first, second]
    assert list(leaves(first)) == [first]

def test_a_group_carrying_a_keyboard_interrupt_is_not_this_modules_to_answer_for() -> None:
    """The Ctrl-C decision, inherited whole by the group rule rather than restated in it.

    A `TaskGroup` whose children all raised `Exception`s hands back an `ExceptionGroup`, which is an
    `Exception`; one whose child took a Ctrl-C hands back a `BaseExceptionGroup`, which is not - so
    it cannot be passed to `exit_status` under `mypy --strict` and never becomes a number. That is
    the same mechanical enforcement the bare `KeyboardInterrupt` gets, and it is what makes a Ctrl-C
    during a `split` end the process the way a Ctrl-C during a `fix` does.
    """
    interrupted = BaseExceptionGroup("one chunk", [KeyboardInterrupt()])
    ordinary = BaseExceptionGroup("one chunk", [UpstreamError("no answer")])

    assert not isinstance(interrupted, Exception)
    assert isinstance(ordinary, ExceptionGroup)

def test_a_keyboard_interrupt_is_not_this_modules_to_answer_for() -> None:
    """The decision, enforced by the annotation rather than by a sentence.

    `KeyboardInterrupt` and `SystemExit` are `BaseException`, so the `except Exception` a top-level
    handler writes never sees one and the interpreter's own ending stands: `SIG_DFL` restored and
    `SIGINT` re-raised, so the process dies of the signal instead of exiting with a number that
    merely looks like it. Passing one here is a `mypy --strict` error at the call site.
    """
    assert get_type_hints(exit_status)["error"] is Exception
    assert not isinstance(KeyboardInterrupt(), Exception)
    assert not isinstance(SystemExit(), Exception)

# --- one rule, for a run and for a command -------------------------------------------------------

@pytest.mark.parametrize(("outcomes", "status"), _OUTCOMES)
def test_a_run_and_a_command_come_to_one_status_over_the_same_outcomes(
    outcomes: tuple[AglError, ...], status: int
) -> None:
    """The same outcomes cost the same whether a run's children raised them or a command refused.

    `agl get` and `agl update` go on past each refusal, so refusals whose codes differ are an ending
    both are built to reach, as chunks failing different named ways are for a run. So both answer by
    `joint_status`, and a rule of its own written into `_refusal_status` fails here rather than in
    any `agl get` test - no refusal site builds a 70 today, so only the rows holding one tell a
    precedence kept by one caller from the same rule dropped by the other.
    """
    assert exit_status(ExceptionGroup("chunks", outcomes)) == status
    assert _refusal_status(outcomes) == status
    assert joint_status({exit_code_for(one) for one in outcomes}) == status
