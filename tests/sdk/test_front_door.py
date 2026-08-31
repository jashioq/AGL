"""The SDK's front door: `agl.sdk` re-exports the authoring surface, and this is what keeps it true.

`from agl.sdk import Screen` became true late: for most of the build there was no package-level
re-export and that line raised `ImportError`, so an author reached for `agl.ports` instead. What a
package-level re-export costs is a second list to keep in step with eight
others - the `__all__` of every module directly under `src/agl/sdk/`, `_declarations.py` now among
them - and this file is what notices when they stop agreeing. `tests/test_contract_listings.py` is
the precedent and the argument is its own: "the silence is the defect, not the gap" - a name missing
from `sdk/__init__.py` is not an error, it is a name an author imports from `agl.ports` instead,
which is the thing the facades exist to prevent.

## Four claims about the door, and none of them hardcodes the surface

**Nothing below carries a copy of what is on the door.** `_DOOR` maps each submodule to *how much*
of it the door takes - all of it, or a named few - and every comparison is between `agl.sdk.__all__`
and the submodules' own `__all__`. A test holding its own list of the door's forty-three names would
be a second hand-maintained list, free to drift from the first, and its agreement would mean only
that one person updated both at once.

  1. **Every name on the door is the submodule's own object**, compared with `is` and not with `==`.
     `sdk/terminal.py` states the property for its own nine - "every name below **is** the object
     `agl.ports.terminal` defines - `is`-identical, not merely compatible" - because a facade that
     wrapped anything would be a second definition free to drift, and the drift would surface as a
     `Screen` an adapter could not draw. One indirection later, the same claim.
  2. **A submodule whose whole surface is authoring has all of it on the door**, so a name added to
     `sdk/roles.py` and forgotten here fails on the commit that added it rather than on the day
     somebody needed it.
  3. **Nothing else is on the door**, which is the half that keeps the omissions deliberate.
     `_ABSENT` names each one with the reason it is out; a name that arrives on the door without
     being claimed by a submodule in `_DOOR` fails, and so does one of `_ABSENT`'s that appears.
  4. **No module under `agl.sdk` imports `agl.sdk`.** A package `__init__` that imports its
     submodules is a cycle waiting for the first submodule that imports the package, and the failure
     is an `ImportError` from whichever module happened to be imported first - at a distance from
     the line that caused it. Parsed rather than grepped, because `from agl.sdk.tools import X` and
     `from agl.sdk import X` differ by two characters.

## What `sdk/params.py` costs, and why it is the only partial one

Five of the six submodules put their whole `__all__` on the door. `sdk/params.py` puts one name of
six, and the other five are framework: `parse` is what `api.run` does to argv, `from_json` what
`api.resume` does to a record, `parser_for` and `RefusingParser` what `agl workflows <name>`
formats, `to_json` what the record is written with. An author declares fields with `arg()` and reads
`run.params`. So the door takes `arg` and the drift check for that module is written the other way
round - the five are named in `_ABSENT`, so adding a seventh name to `sdk/params.py` and leaving it
unclassified fails here.

## And a fifth claim, about the facade that takes part of its port

`sdk/errors.py` arrived late and is whole-on-the-door like the other four, so the four claims
above cover it - but it is the first facade whose *port* module it takes only part of, `ports/
errors.py` holding the hierarchy and the exit-code table both. That cut is checked separately and
in both directions, over `ports.errors.__all__` rather than over a list here, so a tenth class on
the hierarchy fails on the commit that adds it. `Stop` is the interesting entry: it is in the
hierarchy, it is on the door, and it gets there through `sdk/workflow.py` instead - which is a
claim worth pinning rather than a gap, one name having one import path into one front door.
"""

import ast
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

import agl.sdk
from agl.ports import errors as ports_errors
from agl.ports import terminal as ports_terminal
from agl.sdk import errors as sdk_errors

PACKAGE: Final = "agl.sdk"
SDK_DIR: Final = Path(agl.sdk.__file__).resolve().parent

# Every submodule the door takes names from, and how much of it. `None` means "the whole of that
# module's `__all__`", which is the claim that makes a name added there and forgotten here a
# failure. A `frozenset` means "these, and the rest are in `_ABSENT` with a reason".
_DOOR: Final[Mapping[str, frozenset[str] | None]] = {
    "agl.sdk.workflow": None,
    "agl.sdk.roles": None,
    "agl.sdk.tools": None,
    "agl.sdk.terminal": None,
    "agl.sdk.errors": None,
    "agl.sdk.params": frozenset({"arg"}),
}

# What `ports/errors.py` exports that `sdk/errors.py` deliberately does not, each with the reason.
# That facade is the one whose port module holds two vocabularies rather than one - "the `AglError`
# hierarchy ... **and** the one exception -> exit-code table in the codebase" - so it is the one
# facade that takes a part, and this is the machine-checkable half of the argument it makes for
# where the cut falls. It is also what makes a *tenth* class on the hierarchy a failure here rather
# than a name an author quietly imports from `agl.ports` instead.
_NOT_ON_THE_ERROR_FACADE: Final[Mapping[str, str]] = {
    "EXIT_CODES": "the CLI's half of `ports/errors.py`: an exit code is what a process answers "
    "with, and `cli/exit_codes.py` re-exports that table and holds none of its own",
    "exit_code_for": "the CLI's, for the same reason, and the only supported way to read that "
    "table",
    "Stop": "already on the door through `sdk/workflow.py`, beside the `Run` it is raised out of "
    "- the surface is `Run`'s six members, plus `Stop` - one name does not get two import paths "
    "into one door",
}

# Names a submodule in `_DOOR` exports that the door deliberately does not, each with the reason.
# `sdk/__init__.py` argues them at length; this is the machine-checkable half, and it is what makes
# a *seventh* name in `sdk/params.py` a failure rather than a silent omission.
_ABSENT: Final[Mapping[str, str]] = {
    "parse": "what `api.run` does to argv; an author declares fields and reads `run.params`",
    "from_json": "what `api.resume` rebuilds a params instance from the record with",
    "to_json": "what `api.run` writes `RunSpec.params` with",
    "parser_for": "what `agl workflows <name>` formats, and what a caller inspecting a parser uses",
    "RefusingParser": "the parser type `parser_for` returns, for the same two callers",
}

# Modules under `agl.sdk` that are not part of the authoring surface at all. Not in `_DOOR`, so
# nothing from either may appear on the door - and the assertion is written over the module rather
# than over a list of names, so a name added to one of them is covered without being mentioned.
_OFF_THE_SURFACE: Final[Mapping[str, str]] = {
    "agl.sdk.testing": "the scripting vocabulary, re-exported by `agl/testing.py` beside the "
    "`harness` that is useless without it - one front door for a test, one for a workflow",
    "agl.sdk._declarations": "internal: the two helpers `params.py`, `tools.py` and `workflow.py` "
    "read an author's declaration with - `annotations_of` resolves its annotations and `named` "
    "names a class in the refusal when they will not resolve. Both are public spellings, as every "
    "private module's members are: the underscore is on the module and is what says the surface, "
    "so this listing is what keeps them off the door and not the names themselves",
    "agl.sdk._engine.services": "internal: `sdk/_engine/__init__.py` says it is not part of the "
    "surface a workflow author imports",
    "agl.sdk._engine.journal": "internal, for the same reason",
    "agl.sdk._engine.steps": "internal, for the same reason",
    "agl.sdk._engine.worktrees": "internal, for the same reason",
    "agl.sdk._engine.integration": "internal, for the same reason",
    "agl.sdk._engine.preflight": "internal, for the same reason",
}


def _exported(module: ModuleType) -> frozenset[str]:
    """A module's own `__all__`, which every module under `src/agl/` has."""
    names = getattr(module, "__all__", None)
    assert isinstance(names, list) and names, (
        f"{module.__name__} declares no `__all__`. Every module under `src/agl/` has one, and this "
        f"file compares the door against them - so without it there is nothing here to compare."
    )
    return frozenset(names)


def _claimed() -> dict[str, str]:
    """Every name the door is expected to carry, mapped to the module it must come from."""
    claimed: dict[str, str] = {}
    for name, taken in _DOOR.items():
        exported = _exported(import_module(name))
        for exposed in exported if taken is None else taken:
            assert exposed in exported, (
                f"{name} does not export {exposed!r}, which `_DOOR` in this test says the front "
                f"door takes from it. Either the name moved or this listing is stale."
            )
            claimed[exposed] = name
    return claimed


@pytest.mark.parametrize("name", sorted(_exported(agl.sdk)))
def test_every_name_on_the_door_is_the_submodules_own_object(name: str) -> None:
    """`is`-identical, not merely equal - `sdk/terminal.py`'s rule, one indirection later.

    A re-export that wrapped, aliased or rebuilt anything would be a second definition of that name,
    free to drift from the first, and the drift would show up as a `Screen` an adapter could not
    draw or a `Role` `run.step` could not read.
    """
    claimed = _claimed()
    assert name in claimed, (
        f"`agl.sdk.__all__` carries {name!r}, and no module in `_DOOR` in this test claims it. A "
        f"name on the front door comes from a module in this package and from nowhere else - that "
        f"is what keeps `from agl.sdk import {name}` and `from agl.sdk.<module> import {name}` one "
        f"surface. Add the module to `_DOOR`, or take the name off the door."
    )
    assert getattr(agl.sdk, name) is getattr(import_module(claimed[name]), name)


def test_every_authoring_name_a_submodule_exports_is_on_the_door() -> None:
    """The drift check, in the direction that fails open: a name added and never re-exported.

    Five of the six submodules put their whole surface on the door, so this is what notices a tenth
    terminal component or a second declaration helper. `sdk/params.py` is the partial one and its
    five framework names are in `_ABSENT` with a reason each, so it is checked here too - just from
    the other side.
    """
    door = _exported(agl.sdk)
    missing = [
        f"src/{name.replace('.', '/')}.py exports {exposed!r}, which is neither on `agl.sdk`'s "
        f"front door nor named in `_ABSENT` in this test.\n"
        f"\n"
        f"A name left off the door is not an error and nothing reports it: it is a name a workflow "
        f"author imports from `agl.ports` or from a submodule instead, which is what the facades "
        f"and the door exist to prevent. Resolve it by adding {exposed!r} to `sdk/__init__.py`'s "
        f"imports and its `__all__`, or - if it is framework rather than authoring surface - by "
        f"naming it in `_ABSENT` here with the reason it is out."
        for name in _DOOR
        for exposed in _exported(import_module(name))
        if exposed not in door and exposed not in _ABSENT
    ]
    assert not missing, "\n\n".join(missing)


def test_nothing_absent_by_decision_is_on_the_door() -> None:
    """The other half of `_ABSENT`: a name explained as out must actually be out.

    Without this, `_ABSENT` would be a place to silence the check above rather than a record of a
    decision - a name could be added to the door and left in `_ABSENT` saying it is not.
    """
    door = _exported(agl.sdk)
    on_it = sorted(name for name in _ABSENT if name in door)
    assert not on_it, (
        f"{on_it} are on `agl.sdk`'s front door and are also named in `_ABSENT` in this test as "
        f"deliberately absent from it. One of the two is wrong: either the decision changed and "
        f"the entry should go, or the re-export was added by mistake."
    )


@pytest.mark.parametrize(("module", "reason"), sorted(_OFF_THE_SURFACE.items()))
def test_nothing_off_the_authoring_surface_reaches_the_door(module: str, reason: str) -> None:
    """`_engine` stays internal and the testing vocabulary stays on its own door.

    Written over the whole module rather than over a list of names, so a class added to
    `sdk/_engine/journal.py` is covered without anybody mentioning it here.
    """
    leaked = sorted(_exported(agl.sdk) & _exported(import_module(module)))
    assert not leaked, (
        f"{leaked} appear on `agl.sdk`'s front door and are exported by {module}, which is off the "
        f"authoring surface: {reason}."
    )


def test_the_error_facade_takes_the_hierarchy_and_names_everything_it_leaves() -> None:
    """`sdk/errors.py` is the one facade over a port module that holds two vocabularies.

    Written over `ports.errors.__all__` rather than over a list of nine here, so a class added to
    the hierarchy and forgotten fails on the commit that adds it. Both directions, for `_ABSENT`'s
    reason one section up: without the second half this mapping would be a place to silence the
    first rather than a record of a decision.
    """
    facade = _exported(sdk_errors)
    unclassified = sorted(
        name
        for name in _exported(ports_errors)
        if name not in facade and name not in _NOT_ON_THE_ERROR_FACADE
    )
    assert not unclassified, (
        f"src/agl/ports/errors.py exports {unclassified}, which `sdk/errors.py` does not re-export "
        f"and `_NOT_ON_THE_ERROR_FACADE` in this test does not explain.\n\n"
        f"A class in the `AglError` hierarchy that is not on the front door is a class a workflow "
        f"author imports from `agl.ports` in order to assert how their run refused, which is what "
        f"that facade exists to prevent. Add it to `sdk/errors.py` and to `sdk/__init__.py`, or "
        f"name it here with the reason it is out."
    )
    claimed_out = sorted(name for name in _NOT_ON_THE_ERROR_FACADE if name in facade)
    assert not claimed_out, (
        f"{claimed_out} are re-exported by `sdk/errors.py` and are also named in "
        f"`_NOT_ON_THE_ERROR_FACADE` in this test as deliberately not. One of the two is wrong."
    )


@pytest.mark.parametrize("name", sorted(_exported(sdk_errors)))
def test_the_error_facade_re_exports_the_class_ports_defines(name: str) -> None:
    """`is`-identical, and here that is load-bearing rather than a matter of hygiene.

    `except` and `pytest.raises` compare identity up the MRO, so a facade that wrapped, aliased or
    re-declared an exception would hand an author a class that never catches what AGL raised - a
    failure that looks like the framework not refusing at all.
    """
    assert getattr(sdk_errors, name) is getattr(ports_errors, name)


def test_stop_reaches_the_door_through_the_workflow_module_and_not_through_the_facade() -> None:
    """The one class in the hierarchy that is on the door from somewhere else, and stays that way.

    `sdk/errors.py` holds what a workflow catches or asserts on; `Stop` is the one class a workflow
    *raises*, and it is a declaration made beside `@workflow` and `Run`. What this pins is the
    consequence: one name, one import path into the door, and `agl.sdk.Stop` is still the port's
    own class either way.
    """
    assert agl.sdk.Stop is ports_errors.Stop
    assert "Stop" not in _exported(sdk_errors)


def test_the_sentence_the_repository_writes_about_the_terminal_is_true() -> None:
    """`ARCHITECTURE.md`'s "The layers" spells it: a workflow author writes `from agl.sdk import
    Screen` and never reaches into `agl.ports` for a view's vocabulary.

    Asserted as identity against `ports/` rather than as "the attribute exists", because what that
    sentence promises is that an author never reaches into `ports` - which is only worth anything if
    what they get instead is the same object.

    **There was a second half and it is gone rather than relaxed.** The same two lines stood for
    `Question` and `Answer`, which `sdk/questions.py` re-exported off `ports/questions.py`. Neither
    module exists: no port ABC spoke those two types and no adapter named them, so they followed
    their one caller into `workflows/fix/questions.py` and the door stopped carrying them. A
    workflow that asks a person a question now declares what a question is, exactly as it already
    declared the tool that asks one.
    """
    assert agl.sdk.Screen is ports_terminal.Screen
    assert agl.sdk.Terminal is ports_terminal.Terminal


def test_no_module_under_the_package_imports_the_package() -> None:
    """The cycle guard, parsed rather than grepped.

    `sdk/__init__.py` executes every re-export when the package is first imported, so a submodule
    that imported `agl.sdk` at package level would deadlock the import of whichever of the two was
    reached first - and the failure is an `ImportError` naming a module that looks innocent. The
    rule is therefore blunt: submodules import each other directly, `from agl.sdk.tools import
    ReportingTool`, never `from agl.sdk import ReportingTool`.

    Every `.py` under `src/agl/sdk/` except the package root itself, at any depth, and every import
    statement in each - including the ones inside functions, which would be legal but would leave
    the next reader deciding whether this rule has exceptions.
    """
    found = [
        f"agl/sdk/{source.relative_to(SDK_DIR)}:{node.lineno} imports {PACKAGE!r}"
        for source in sorted(SDK_DIR.rglob("*.py"))
        if source != SDK_DIR / "__init__.py"
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Import | ast.ImportFrom) and _imports_the_package(node)
    ]
    assert not found, (
        "these import `agl.sdk` from inside `agl.sdk`, which is a cycle: the package's own "
        "`__init__.py` imports every one of them.\n\n"
        + "\n".join(found)
        + "\n\nImport the submodule directly instead - `from agl.sdk.tools import ReportingTool`."
    )


def _imports_the_package(node: ast.Import | ast.ImportFrom) -> bool:
    """Whether `node` is an import of `agl.sdk` itself, in either spelling.

    `from agl.sdk import x` is an `ImportFrom` whose module is the package and whose level is 0; a
    relative `from . import x` inside `agl.sdk` is the same import spelled differently and is caught
    by the level. `import agl.sdk` is an `Import` naming it, and `import agl.sdk.tools` is not - it
    binds the top-level package and reaches the submodule, which no module here writes.
    """
    if isinstance(node, ast.ImportFrom):
        return node.module == PACKAGE or (node.level == 1 and node.module is None)
    return any(alias.name == PACKAGE for alias in node.names)


def test_the_cycle_guard_can_see_both_spellings() -> None:
    """Non-vacuity: the walk above finds nothing today, so this is what says it could.

    A structural test that reads a tree and finds it clean looks identical whether it is checking
    anything or not. Four fabricated statements, two that must be reported and two that must not.
    """
    statements = [
        ast.parse(line).body[0]
        for line in (
            "from agl.sdk import Screen",
            "import agl.sdk",
            "from agl.sdk.terminal import Screen",
            "import agl.sdk.terminal",
        )
    ]
    assert all(isinstance(one, ast.Import | ast.ImportFrom) for one in statements)
    reported = [
        _imports_the_package(one)
        for one in statements
        if isinstance(one, ast.Import | ast.ImportFrom)
    ]
    assert reported == [True, True, False, False]
