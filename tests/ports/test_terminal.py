"""What the components promise a redraw loop: one coercion rule, stored tuples, and two frames of
one view that compare equal.

`Terminal` itself is not touched here - not subclassed, not instantiated, not even as a null
implementation - for `test_integration.py`'s reason: a suite that writes its own subject writes a
subject that passes. The slot, the queues and preemption are asserted by the contract suite both
implementations must pass, which is stage 3.5's, deliberately.

That leaves the components, and three things in them that are genuine logic rather than a dataclass
doing its job. **The `str` -> `Text` coercion**, at both sites that take one, because "a bare string
means `Text`" is a rule a reader has to be able to rely on without checking which site they are at.
**Tuple normalisation**, because a view builds its rows by comprehension and its responses as a
list, and two frames that differ only in which container the author reached for must not read as a
change. And **that two invocations of one view compare equal though each builds a fresh lambda** -
which is `TextInput.maps`' exclusion from comparison made executable, and the assertion a later
reader has to break before they can "clean up" that `field(compare=False)`.
"""

from dataclasses import FrozenInstanceError, dataclass
from typing import get_args

import pytest

from agl.ports.terminal import Choice, Component, Row, Rows, Screen, Text, TextInput


@dataclass(frozen=True, slots=True)
class Approval:
    """A workflow's own answer type, standing in for §3.7's."""

    ok: bool
    feedback: str = ""


def approve(prompt: str) -> Screen[Approval]:
    """§3.7's interactive view, in shape: a `Choice`, a `TextInput`, and a lambda built per call."""
    return Screen(
        body=Text(prompt),
        responses=[
            Choice("Approve", value=Approval(ok=True)),
            TextInput("Suggest changes", maps=lambda s: Approval(ok=False, feedback=s)),
        ],
    )


def test_two_frames_of_one_view_compare_equal_although_their_lambdas_differ() -> None:
    """The whole reason per-frame re-invocation is affordable. If these two were unequal, the diff
    would report a change every frame and the terminal would rewrite the screen ten times a second
    for as long as somebody was typing into it."""
    first, second = approve("Ship it?"), approve("Ship it?")
    assert first == second

    # And the two mappings really are different objects, or the assertion above proves nothing.
    first_input, second_input = first.responses[1], second.responses[1]
    assert isinstance(first_input, TextInput)
    assert isinstance(second_input, TextInput)
    assert first_input.maps is not second_input.maps
    assert first_input.maps("late") == Approval(ok=False, feedback="late")


def test_a_mapping_is_left_out_of_the_repr_as_well() -> None:
    """For the same reading: a lambda's `repr` carries its address, so two equal screens would
    print differently in a log or an error message."""
    shown = repr(TextInput("Suggest changes", maps=lambda s: Approval(ok=False, feedback=s)))
    assert "Suggest changes" in shown
    assert "maps" not in shown and "lambda" not in shown


def test_a_choice_s_value_is_compared() -> None:
    """The other half of the decision: `value` is data, not a callable, so a frame in which it
    changed is a frame that genuinely changed."""
    assert Choice("Approve", value=Approval(ok=True)) == Choice("Approve", value=Approval(ok=True))
    assert Choice("Approve", value=Approval(ok=True)) != Choice("Approve", value=Approval(ok=False))


def test_a_bare_string_cell_is_a_text() -> None:
    """§3.7's own board writes `Row(t.id, t.title, Text(...))` - both spellings in one call."""
    assert Row("T-01", Text("wire the port")) == Row(Text("T-01"), Text("wire the port"))
    assert Row("T-01").cells == (Text("T-01"),)


def test_a_bare_string_body_is_a_text() -> None:
    """The same rule at the other site that takes one, which is what makes it a rule."""
    assert Screen("nothing to do") == Screen(Text("nothing to do"))
    assert Screen("nothing to do").body == Text("nothing to do")


def test_a_row_takes_its_cells_one_by_one_and_none_is_ordinary() -> None:
    """The hand-written `__init__` a `*cells` signature needs, doing what the generated one would:
    order kept, an empty row legal, and equality over the cells it stored."""
    assert Row("a", "b").cells == (Text("a"), Text("b"))
    assert Row("b", "a") != Row("a", "b")
    assert Row().cells == ()


def test_a_table_built_by_comprehension_equals_one_built_by_hand() -> None:
    """`Rows` takes a sequence where `Row` takes varargs - §3.7's asymmetry - so a list arrives
    here routinely and must be kept as the same tuple a hand-written one is."""
    built = Rows([Row(name) for name in ("a", "b")])
    assert built.rows == (Row("a"), Row("b"))
    assert built == Rows((Row("a"), Row("b")))


def test_responses_are_kept_as_a_tuple_and_empty_means_passive() -> None:
    """Empty `responses` is the discriminator `show` dispatches on at runtime, so the default
    matters: a screen nobody gave responses to is passive, not half-built."""
    asked = Screen(Text("Ship it?"), responses=[Choice("Approve", value=Approval(ok=True))])
    assert asked.responses == (Choice("Approve", value=Approval(ok=True)),)
    assert Screen(Rows([Row("a")])).responses == ()


def test_the_component_union_is_the_three_an_adapter_must_cover() -> None:
    """Pinned by hand because `Component` being closed is the design: an adapter matches it
    exhaustively and `mypy` proves it covered every case, so a fourth member is a build failure
    everywhere that has not learned to draw it - and should have to be argued for, not merely
    added."""
    assert get_args(Component.__value__) == (Text, Row, Rows)


@pytest.mark.parametrize(
    "component",
    [
        pytest.param(Text("a"), id="Text"),
        pytest.param(Row("a"), id="Row"),
        pytest.param(Rows([Row("a")]), id="Rows"),
        pytest.param(Screen("a"), id="Screen"),
        pytest.param(Choice("a", value=1), id="Choice"),
    ],
)
def test_every_component_is_frozen(component: object) -> None:
    """Values, compared by value. One a view could edit after building it is one the diff cannot
    trust, since the object the terminal kept from the last frame would change underneath it."""
    with pytest.raises(FrozenInstanceError):
        component.label = "edited"  # type: ignore[attr-defined]
