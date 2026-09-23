"""How a refusal names a type: by the path an author imports it from, and never by a private one.

**An author imports from `agl.sdk`**, so a refusal naming `agl.ports.integration.Conflict` or
`agl.sdk.roles.Role` names a path nobody wrote, and one naming `agl.sdk._workflow._NoParams` names a
class nobody can import. Every such refusal goes through `sdk/_declarations.py::named`, which may
not import `agl.sdk` to ask what it exports - `tests/sdk/test_front_door.py` forbids it - so the
exports are written out there, and the first two tests below hold that copy to the package both
ways.

**What a refusal prints is not what a record stores.** A dataclass is stored and fingerprinted under
the path it is defined at, and moving that path re-runs recorded steps, so the last test here pins
that the stored spelling of a front-door type and of `_NoParams` stays where it was.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import FunctionType
from typing import TypeAliasType
import pytest
import agl.sdk
from agl.ports.integration import Conflict
from agl.ports.run import JsonValue
from agl.sdk import Role, Run, reporting_tool, workflow
from agl.sdk._declarations import _EXPORTED, named
from agl.sdk._engine.integration import GatedIntegration
from agl.sdk._engine.journal import canonical_json

@workflow
async def takes_nothing(run: Run) -> None:
    """A bare `Run`, so `Workflow.params` hands out the empty class `agl.sdk` does not export."""

@dataclass(frozen=True)
class Ticket:
    """An author's own class, defined outside AGL."""

    title: str

def _defined_at(exported: object) -> str:
    """Where an exported name is defined, spelled the way `_EXPORTED` spells it."""
    assert isinstance(exported, type | TypeAliasType | FunctionType)
    return f"{exported.__module__}.{exported.__name__}"

@pytest.mark.parametrize("name", agl.sdk.__all__)
def test_every_export_of_agl_sdk_is_named_in_a_refusal_by_its_public_path(name: str) -> None:
    assert named(getattr(agl.sdk, name)) == f"agl.sdk.{name}"

def test_the_exports_written_out_for_refusals_are_exactly_the_ones_agl_sdk_has() -> None:
    """The other direction: a name taken off the door and left in `_EXPORTED` would go on being
    printed as `agl.sdk.<name>`, a path that no longer imports."""
    exported = {_defined_at(getattr(agl.sdk, name)) for name in agl.sdk.__all__}
    assert _EXPORTED == exported, (
        f"only in `_EXPORTED`: {sorted(_EXPORTED - exported)}; "
        f"only on `agl.sdk`: {sorted(exported - _EXPORTED)}"
    )

def test_a_type_defined_in_ports_is_named_by_its_agl_sdk_path() -> None:
    assert Conflict.__module__ == "agl.ports.integration"
    assert named(Conflict) == "agl.sdk.Conflict"

def test_a_type_defined_in_an_sdk_module_is_named_by_its_agl_sdk_path() -> None:
    assert Role.__module__ == "agl.sdk.roles"
    assert named(Role) == "agl.sdk.Role"

def test_an_annotation_built_from_exported_types_names_each_by_its_agl_sdk_path() -> None:
    assert named(Run | None) == "agl.sdk.Run | None"
    assert named(list[Role]) == "list[agl.sdk.Role]"
    assert named(Run[Ticket]) == f"agl.sdk.Run[{__name__}.Ticket]"
    assert named(Mapping[str, JsonValue]) == "collections.abc.Mapping[str, agl.sdk.JsonValue]"
    assert named(Callable[[Conflict], None]) == "collections.abc.Callable[[agl.sdk.Conflict], None]"

def test_a_type_agl_defines_and_does_not_export_is_described_rather_than_named() -> None:
    """`_NoParams` is what a bare `Run` hands out, and a `Role` walked as a payload reaches the
    private alias its model is held as - neither is a name an author could import."""
    assert named(takes_nothing.params) == "a type `agl.sdk` does not export"
    assert named(GatedIntegration) == "a type `agl.sdk` does not export"
    with pytest.raises(agl.sdk.InputError) as refusal:
        reporting_tool("report", "report it", Role)
    assert "_model is declared as a type `agl.sdk` does not export," in str(refusal.value)
    assert "ModelChoice" not in str(refusal.value)

def test_an_authors_own_types_keep_their_defining_path_and_python_spelling() -> None:
    assert named(Ticket) == f"{__name__}.Ticket"
    assert named(int) == "builtins.int"
    assert named(list[str]) == "list[str]"
    assert named(Ticket | None) == f"{__name__}.Ticket | None"
    assert named("Ticket") == "'Ticket'"

def test_a_front_door_type_is_stored_under_its_defining_path_whatever_a_refusal_prints() -> None:
    """The fingerprint reads `__module__` and `__qualname__` itself, in `sdk/_engine/journal.py` and
    in a payload schema's title, and neither goes through `named`."""
    conflict = Conflict(paths=("a.py",), summary="both edited it")
    assert '"__agl_type__":"agl.ports.integration.Conflict"' in canonical_json(conflict)
    assert reporting_tool("report", "report it", Conflict).payload_schema["title"] == (
        "agl.ports.integration.Conflict"
    )
    assert canonical_json(takes_nothing.params()) == (
        '{"__agl_type__":"agl.sdk._workflow._NoParams"}'
    )
