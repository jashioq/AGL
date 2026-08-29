"""The bundle moved to `sdk/_engine/`, and the composition root re-exports it - one class, not two.

`tests/config/test_container.py` covers everything about `Services` that this move did not change,
and covers it through `container.Services`, the name every existing caller uses. That is exactly
why it cannot notice the one thing the move could get wrong. A **second** `Services` declared in
`container.py` beside the imported one would satisfy every assertion in that file -
`get_type_hints(container.Services) == _PORTS` included - while `Run.services` referred to a
different class and no bundle the container ever built would be one of them. Identity is the claim
that file cannot make, so it is made here and nothing else is repeated.

The other half is that the type stayed a shape. It may live under `sdk/` while being constructed in
`config/` only because it holds no decision about how a bundle is assembled; a method on it would
be a second place that knows, and the composition root's whole argument is that there is one.
"""

from dataclasses import fields
from typing import get_type_hints

from agl.config import container
from agl.sdk._engine.services import Services
from agl.sdk.workflow import Run


def test_the_composition_root_re_exports_the_bundle_rather_than_declaring_a_second_one() -> None:
    """The one assertion `tests/config/test_container.py` is structurally unable to make."""
    assert container.Services is Services


def test_the_bundle_a_run_carries_is_the_bundle_the_container_builds() -> None:
    """The other end of the same claim: what `api.py` gets from `container.real()` is what
    `Run.services` is declared to hold, so the walking skeleton's wiring has somewhere to go."""
    assert get_type_hints(Run)["services"] is Services


def test_the_bundle_holds_a_shape_and_no_behaviour() -> None:
    """Eight fields and not one member beside them.

    This is what makes the split between the type and its construction hold: `config/container.py`
    knows how a bundle is assembled and nothing else does, so a `Services.default()` or a
    `with_store()` here would be a second answer to a question the composition root closed.
    """
    public = {name for name in vars(Services) if not name.startswith("_")}
    assert public == {declared.name for declared in fields(Services)}
