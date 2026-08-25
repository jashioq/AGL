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
declared in `pyproject.toml` and holds the workflows AGL ships, so what is asserted is that reading
it returns those names - a skip would assert nothing, and this catches a group name that has drifted
out of agreement with `pyproject.toml` into something unreadable.

## It is the one test in the suite that can fail for a reason outside the repository

`entry_points.txt` is a *build artifact*. An edit to `pyproject.toml`'s table is invisible until the
distribution is rebuilt, so between that edit and the next `uv pip install -e . --no-deps` the group
this environment reports and the group this repository declares are two different lists - and stage
19.1, which deleted a workflow, is the case that happened. Nothing refreshes the install: not
`scripts/check`, deliberately. A gate that repaired the environment before measuring it would be a
gate that could no longer report the drift at all, which is the opposite of the header's "everything
that can say this build is wrong says it here"; gate 8 writes and deletes a probe file, but that
file *is* the measurement rather than a repair of the thing being measured. And `scripts/check` is
not the only way this test runs - a bare `pytest` would be left with the same confusing failure.

So the drift is diagnosed here instead, first, and named for what it is. The test reads the table
out of `pyproject.toml` and compares it against the entry points this environment attributes to the
`agl` distribution; a mismatch is reported as a stale install with the one command that fixes it,
before anything is said about which workflows are registered. That is the actual complaint: not
that the failure was hard to fix, but that it named the wrong thing - a workflow-registration
failure, for an environment that had simply not been rebuilt.

Refusals are asserted on their class *and* on the name, the entry-point value or the list of
alternatives appearing in the message: "it raised" is satisfied by a refusal that leaves the
operator with nothing to do next.
"""

import tomllib
from importlib.metadata import EntryPoint
from pathlib import Path
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
    """Sorted, so `agl workflows` prints the same list on two machines that scanned differently.

    Three names, handed over in reverse of the order asserted, so a `names` that returned its input
    unchanged fails here. The third is invented, as `tickets` is. It read `noop` until 19.1 deleted
    that workflow, and the deletion cost this case nothing - which is the point worth leaving
    behind: nothing in this half resolves a name, so what is registered in `pyproject.toml` is not
    a fact any assertion here rests on.
    """
    points = (_loadable(_WORKFLOW), _loadable(_OTHER), _loadable("backlog"))
    assert names(points) == ("backlog", "split", "tickets")


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

# This repository's own `pyproject.toml`, and the distribution the build makes out of it. The path
# is walked up from this file rather than from the working directory, so it is the same file
# whichever directory `pytest` was started in. The name is read back out of `[project]` below rather
# than written here twice.
_PYPROJECT: Final = Path(__file__).resolve().parents[2] / "pyproject.toml"

# The one command that turns a stale editable install into a fresh one. Spelled once, because it
# goes into two failure messages and a command retyped wrong is a command that did not help.
_REFRESH: Final = "uv pip install -e . --no-deps"


def _declared() -> tuple[str, ...]:
    """The workflow names `pyproject.toml`'s own entry-point table holds, read from the file.

    The *source* side of the comparison, and the reason it is read rather than imported: the whole
    failure being diagnosed is a build artifact that has fallen behind this table, so a reading that
    went through anything the build produced would agree with the build by construction.
    """
    assert _PYPROJECT.is_file(), (
        f"{_PYPROJECT} is not there, so this test cannot tell what workflows this repository "
        f"declares. It walks up from this file's own path; a tests/ tree that moved relative to "
        f"the project root is what breaks it."
    )
    parsed = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = parsed.get("project")
    assert isinstance(project, dict), f"{_PYPROJECT} has no [project] table"
    groups = project.get("entry-points")
    assert isinstance(groups, dict), (
        f"{_PYPROJECT} declares no [project.entry-points] at all, so AGL registers no workflow and "
        f"`agl run` can find none. That is where a workflow's one line goes (see agl/config/"
        f"registry.py) - either the table moved and this test is comparing against nothing, or the "
        f"shipped workflows have stopped being registered."
    )
    table = groups.get(GROUP)
    assert isinstance(table, dict) and table, (
        f"{_PYPROJECT} declares no {GROUP} entry points. `GROUP` is spelled in registry.py and in "
        f"that table and nowhere else, so the two drifting apart is exactly the failure this "
        f"comparison exists to name."
    )
    return tuple(sorted(table))


def _ours() -> tuple[str, ...]:
    """The names this environment's installed `agl` distribution contributes to the group.

    Filtered by distribution rather than taken whole, so that a workflow registered by some *other*
    installed package - which is the entire point of an entry-point group - is not read as this
    repository's install having gone stale.
    """
    return tuple(
        sorted(
            point.name
            for point in installed()
            if point.dist is not None and point.dist.name == "agl"
        )
    )


def test_the_real_entry_point_group_is_readable_and_holds_fix_and_split() -> None:
    """`pyproject.toml` declares `agl.workflows`, and stages 17 and 18 registered `fix` and `split`.

    Three artefacts have to agree for this to pass and no two of them are the same thing: the table
    in `pyproject.toml`, the `entry_points.txt` the build wrote from it, and the group `GROUP` names
    when `installed()` reads it. It is the only case in this file that touches the installed state
    of this environment at all - everything above hands `names` and `load` entry points it built
    itself - so it is also the only one that can catch `GROUP` and `pyproject.toml` drifting apart,
    or a `pyproject.toml` edited without the editable install being refreshed.

    **The two assertions are in this order because the second one lies about the first.** A stale
    install is not a workflow that failed to register - it is a build artifact that has not been
    rebuilt - and a reader told "`fix` is missing from the group" goes looking in `agl/workflows/`
    for a package that is sitting right there. So the source table and the installed table are
    compared first, by themselves, and a divergence is reported as what it is with the command that
    ends it. Only then is the claim about `fix` and `split` made, and by then it can only fail for
    the reason it is written for: a `pyproject.toml` that has stopped registering them.

    It named `noop` from stage 10 until 19.1, which deleted that workflow and its line together. The
    claim survived the name: what is being asserted is that the group is readable and holds the
    workflows AGL ships, and `fix` and `split` are those. Membership rather than equality, so a
    workflow registered by a later stage - or by a package installed beside AGL, which is the whole
    point of an entry-point group - does not fail a test about these two.
    """
    declared = _declared()
    ours = _ours()
    assert ours == declared, (
        f"this environment's installed `agl` contributes {list(ours)} to the {GROUP} group and "
        f"{_PYPROJECT.name} declares {list(declared)}. **Your editable install is stale**, and "
        f"nothing about the code in this repository is wrong: entry_points.txt is written when the "
        f"distribution is built and does not see an edit to the table it came from. Run "
        f"`{_REFRESH}` and this passes. (Nothing refreshes it for you - a gate that repaired the "
        f"environment before measuring it could no longer report this at all.)"
    )

    registered = names(installed())
    missing = sorted({"fix", "split"} - set(registered))
    assert not missing, (
        f"the {GROUP} group holds {registered}, and {missing} is missing. The install is not stale "
        f"- it agrees with {_PYPROJECT.name}, which is asserted above - so {_PYPROJECT.name} has "
        f"stopped registering a workflow AGL ships. A workflow is a package and one line in that "
        f"table; put the line back and refresh with `{_REFRESH}`"
    )
