"""Discovery driven by `EntryPoint` values the test constructs, plus one look at the real group.

`EntryPoint` is a public, constructible type - `EntryPoint(name, value, group)` and nothing else -
so every branch of the pure core is reachable without installing a package, building a
distribution, or arranging `sys.path`. That is the whole reason `names` and `load` take the entry
points as an argument, and this file is what that split was for.

The values point at this module's own objects - a stand-in workflow, a string for the load that
succeeds into the wrong type - and at one module path that does not exist. Nothing here writes a
package or a `.dist-info` directory: an entry point is a name, a `module:attr` string and a group,
and resolving it is the interpreter's job rather than this file's.

The one impure function gets one test, and it asserts the honest thing. The `agl.workflows` group is
declared in `pyproject.toml` and is deliberately empty until stage 10, so what can be asserted today
is that reading it returns - a skip would assert nothing, and this catches a group name that has
drifted out of agreement with `pyproject.toml` into something unreadable.

Refusals are asserted on their class *and* on the name, the entry-point value or the list of
alternatives appearing in the message: "it raised" is satisfied by a refusal that leaves the
operator with nothing to do next.
"""

from importlib.metadata import EntryPoint
from typing import Final

import pytest

from agl.config.registry import GROUP, installed, load, names
from agl.ports.errors import ConflictError, InputError, NotFoundError

# What a registered workflow looks like from here: a name, a `module:attr` value, and the group.
# The targets are real objects in this repository, so a load that is supposed to succeed does.
_WORKFLOW: Final = "tickets"
_OTHER: Final = "split"


def _point(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=GROUP)


class _Workflow:
    """Stands in for the type `api.py` passes at stage 10.3. Any class does - that is the point."""


def _loadable(name: str) -> EntryPoint:
    """An entry point resolving to something this module can be asked to narrow to `_Workflow`."""
    return _point(name, f"{__name__}:_instance")


# The two objects the entry points below resolve to. Module level, because `EntryPoint.load`
# imports a module and reads a dotted attribute path in it - it cannot see a local.
_instance = _Workflow()
_not_a_workflow = "a workflow name is not a workflow"


# --- listing -----------------------------------------------------------------------------------


def test_names_lists_every_registered_workflow_sorted() -> None:
    """Sorted, so `agl workflows` prints the same list on two machines that scanned differently."""
    points = (_loadable(_WORKFLOW), _loadable(_OTHER), _loadable("noop"))
    assert names(points) == ("noop", "split", "tickets")


def test_names_of_an_empty_group_is_empty() -> None:
    assert names(()) == ()


def test_names_imports_nothing_so_a_broken_workflow_is_still_listed() -> None:
    """One package that will not import must not take down the command that lists what is there."""
    points = (_loadable(_WORKFLOW), _point("broken", "agl.no.such.module:anything"))
    assert names(points) == ("broken", "tickets")


# --- loading, and the narrowing that keeps `Any` out of the caller -----------------------------


def test_load_returns_the_registered_object_narrowed_to_the_expected_type() -> None:
    loaded = load((_loadable(_WORKFLOW),), _WORKFLOW, _Workflow)
    assert loaded is _instance


def test_load_picks_the_named_entry_point_out_of_several() -> None:
    points = (_loadable(_OTHER), _loadable(_WORKFLOW))
    assert load(points, _WORKFLOW, _Workflow) is _instance


# --- a name in no entry point: NotFoundError, exit 3 -------------------------------------------


def test_an_unknown_name_is_not_found_and_the_message_lists_what_is_registered() -> None:
    points = (_loadable(_WORKFLOW), _loadable(_OTHER))
    with pytest.raises(NotFoundError) as raised:
        load(points, "tickest", _Workflow)
    message = str(raised.value)
    assert "tickest" in message
    assert _WORKFLOW in message
    assert _OTHER in message


def test_an_unknown_name_in_an_empty_registry_says_nothing_is_installed() -> None:
    """A different situation from "not that one", and a refusal ending in an empty list is a bug."""
    with pytest.raises(NotFoundError) as raised:
        load((), _WORKFLOW, _Workflow)
    message = str(raised.value)
    assert "no workflow is installed at all" in message
    assert GROUP in message


# --- one name, two packages: ConflictError, exit 4 ---------------------------------------------


def test_two_packages_registering_one_name_is_refused_on_load() -> None:
    points = (_loadable(_WORKFLOW), _point(_WORKFLOW, "somewhere.else:tickets"))
    with pytest.raises(ConflictError) as raised:
        load(points, _WORKFLOW, _Workflow)
    message = str(raised.value)
    assert _WORKFLOW in message
    assert "somewhere.else:tickets" in message


def test_two_packages_registering_one_name_is_refused_when_listing_too() -> None:
    """The refusal is raised while indexing, so `agl workflows` refuses rather than printing one
    row for two installed workflows and letting the operator pick blind."""
    points = (_loadable(_WORKFLOW), _point(_WORKFLOW, "somewhere.else:tickets"))
    with pytest.raises(ConflictError):
        names(points)


# --- a declaration that does not hold up: InputError, exit 2 -----------------------------------


def test_an_entry_point_whose_module_is_missing_is_refused_with_the_original_chained() -> None:
    value = "agl.no.such.module:anything"
    with pytest.raises(InputError) as raised:
        load((_point(_WORKFLOW, value),), _WORKFLOW, _Workflow)
    assert value in str(raised.value)
    assert _WORKFLOW in str(raised.value)
    # The workflow author debugging their own package needs the real traceback, not a sentence
    # saying one happened.
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)


def test_an_entry_point_whose_attribute_is_missing_is_refused_with_the_original_chained() -> None:
    value = f"{__name__}:_no_such_attribute"
    with pytest.raises(InputError) as raised:
        load((_point(_WORKFLOW, value),), _WORKFLOW, _Workflow)
    assert value in str(raised.value)
    assert isinstance(raised.value.__cause__, AttributeError)


def test_an_entry_point_that_loads_the_wrong_kind_of_object_is_refused() -> None:
    """It imported fine and resolved to something. Being the wrong type is the remaining failure."""
    value = f"{__name__}:_not_a_workflow"
    with pytest.raises(InputError) as raised:
        load((_point(_WORKFLOW, value),), _WORKFLOW, _Workflow)
    message = str(raised.value)
    assert value in message
    assert _Workflow.__qualname__ in message
    assert "str" in message


# --- the one impure line ------------------------------------------------------------------------


def test_the_real_entry_point_group_is_readable_and_empty_today() -> None:
    """`pyproject.toml` declares `agl.workflows` and deliberately registers nothing in it yet.

    Asserting that reading it returns is the honest version of this test rather than a skip: it is
    the only case that touches the installed-distribution state of this environment, and it fails
    if `GROUP` and `pyproject.toml` ever stop naming the same group in a readable way.
    """
    assert names(installed()) == ()
