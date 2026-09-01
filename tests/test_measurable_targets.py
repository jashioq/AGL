"""The twelve measurable targets, one assertion each, and the two that resist one.

The twelve were written before the build started and are the project's own definition of done, and
this file is now where they are recorded, and where each of them is settled. Ten of them hold:
seven are asserted here (#1, #2, #3, #5, #6, #7, #8) and three are cited to the test that already
asserts them better than a copy would (#4, #9, #10). One is asserted here in its sharpest form and
**fails past a boundary this file records rather than hides** (#11). One cannot be asserted at all
today and says so in as many words (#12).

**The governing rule this module was written under.** A target that cannot be asserted mechanically
is a finding. No target below is softened to make it pass and no proxy is asserted for one. Where a
target's own words could not be reached, what is written here is the reason and what would have to
change - the code or the target - and not a neighbouring claim dressed up as the target.

That rule has teeth in three places, and they are the three worth reading first:

  * **#8** could have been settled with "a fakes-only test exists for each of the five commands",
    which is true today and is a proxy: it measures what somebody remembered to write rather than
    what the target says. What is asserted instead is the target's own words - every command the
    *real parser* declares, driven end-to-end on `container.fakes()` with `subprocess` and `socket`
    poisoned so any use raises. A sixth command added without fakes-only coverage fails it.
  * **#11** is asserted in its sharpest form - rename every namespace and every step name and every
    fingerprint is byte-identical - and that form is **true up to the first `integrate()` and false
    after it**. The mechanism is recorded and asserted below rather than accommodated: a landing's
    merge commit carries git's own message, which names the source branch, which names the
    namespace; the commit id therefore depends on the namespace, and `head` is a fingerprint term.
    So a namespace rename moves every fingerprint taken after a landing. That is a finding about
    the target, not a licence to weaken it.
  * **#12** claims tickets (v1.2) requires no framework change. This is v1.1 and tickets does not
    exist, so the claim is unverifiable today. Nothing here stands in for it. `fix` and `split`
    requiring no framework change between them is the strongest available evidence and is *not* a
    substitute; the test below asserts only that tickets is still absent, so the day it arrives this
    file fails and tells whoever added it to take the measurement.

## How to read this file

`SETTLED` is the index: target number to the tests that settle it, each spelled `path::name`. Every
one of those is resolved against the real file by `test_every_settlement_names_a_test_that_exists`,
so a citation that rots fails a test rather than quietly becoming prose. Five targets cite a test
written elsewhere - #3 and #5 alongside an assertion of their own, #4, #9 and #10 instead of one -
and each of those citations is re-run rather than re-implemented. #4 and #10 are the two that could
not be improved on here at all: re-writing either would have been a second copy of a claim that is
already made better, with more apparatus behind it, where it lives.

Everything structural is **derived from the tree**, never from a list typed here. The port/suite
parity of #7 walks `src/agl/ports/` and `tests/contracts/`; the connector mutation of #6 walks
`src/agl/adapters/`; the command enumeration of #8 walks the parser object `agl` itself builds. A
ninth port, a third connector or a sixth command is covered the moment it exists, and its author
need do nothing to be measured. That is `tests/test_contract_listings.py`'s rule applied one floor
up, and it is the difference between a measurement and a memo.

## No test here spends a token, and none of them can

Absolutely, and not behind a switch. Everything below is either a static read of files in this
repository or a run on `container.fakes()`, which is the all-fakes bundle - no network, no git, no
process. `#8` goes further and poisons the two ways out of the interpreter, which is the assertion
rather than a precaution.

## The mutation pass, and why it gets its own directory

#6 is the one target with no static form: "deleting a connector breaks nothing else" is a claim
about a tree that does not exist until something is deleted from one. So it copies `src/` into
`tmp_path` - a directory of its own per parametrisation, so two passes cannot see each other's
deletions - removes one adapter package, and asks what still names it. **The copy is counted as well
as the verdict**, because a mutation pass that copied nothing, or copied `.venv`, passes for the
wrong reason and looks identical from the summary line. `__pycache__` is excluded on the way in for
the same reason: a stale `.pyc` is not a module anybody imports and counting one would inflate the
number the assertion rests on.

## One module, and it is one of the longest in the repository

773 code lines against `scripts/check`'s 300-line convention, which is among the largest of the 36
modules over it and more than half again `tests/test_contract_listings.py`, the file whose rule
this one applies a floor up. The module size ceiling warns rather than fails, and this is the
warning answered rather than ignored.

**The seam a split would follow is the target numbers, and they are not a seam.** Twelve targets is
twelve instances of one job - read the target's sentence, find the mechanical form of it, assert
that form, and say what the assertion does not reach - and what makes them one module is precisely
what three or four modules would then have to share: one way of walking the tree, one way of
parsing an import, one shape of complaint, and one index. Split by number and the index becomes a
fourth file listing the other three, which is the hand-maintained list this whole file is written
to avoid.

**The other candidate seam - static reads in one module, runs in another - is worse**, and for the
reason the split of #11 makes obvious: that target is settled by a run and its *boundary* is
explained by a static fact about `base_of`, and the two belong on one screen or neither means
anything. #8 is the same shape from the other side, its enumeration static and its verdict a run.

What the length actually is: twelve sections, each with the target quoted, the mechanical form
argued for somebody meeting it for the first time, and a failure message that names the target
rather than the expression that failed. 148 of those 773 lines are assertion messages, which is this
repository's convention rather than this file's indulgence.

## The one instrument this file could not build

#5's pair is a `.importlinter` contract and a `scripts/check` grep gate. The contract's *refusal* is
already fabricated and asserted in `tests/test_contract_firing.py`, so this file cites it. The
gate's refusal is not fabricated here, and that is a stated limit rather than an oversight: the only
way to make it fire would be to write the grep a third time, and a third copy is free to drift from
the two it is meant to be checking - which is exactly the defect `tests/test_contract_listings.py`
exists to prevent one floor down. What is asserted instead is that the gate exists, that its scope
is the OpenAI adapter and no wider, and that it is **not vacuous**: the binary name really does
occur inside the one directory allowed to hold it, so the grep has something to find.
`scripts/check` is what runs the gate, and running it is how the gate is known to pass.
"""

import argparse
import ast
import asyncio
import json
import os
import shutil
import socket
import subprocess
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from configparser import ConfigParser
from dataclasses import dataclass, fields
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final, NoReturn
import pytest
from agl import testing
from agl.adapters.filesystem.store import FilesystemStore
from agl.cli import main
from agl.config import container, registry, sources
from agl.config.schema import AgentSettings
from agl.ports.agent import Provider
from agl.ports.home_layout import AglHome
from agl.ports.ids import ProjectName
from agl.ports.tree_layout import TreesRoot, run_branch, worktree_branch
from agl.sdk import Claude, Namespace, Role, Run, Workflow, arg, role, workflow
from agl.testing import AgentTask, Reply

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SRC: Final = REPO_ROOT / "src"
PACKAGE_DIR: Final = SRC / "agl"
PORTS_DIR: Final = PACKAGE_DIR / "ports"
ADAPTERS_DIR: Final = PACKAGE_DIR / "adapters"
WORKFLOWS_DIR: Final = PACKAGE_DIR / "workflows"
CONTRACTS_DIR: Final = REPO_ROOT / "tests" / "contracts"
PYPROJECT_FILE: Final = REPO_ROOT / "pyproject.toml"
IMPORTLINTER_FILE: Final = REPO_ROOT / ".importlinter"
CHECK_SCRIPT: Final = REPO_ROOT / "scripts" / "check"

WORKFLOWS_PACKAGE: Final = "agl.workflows"
ADAPTERS_PACKAGE: Final = "agl.adapters"
CONFIG_PACKAGE: Final = "agl.config"
CONTAINER_MODULE: Final = "agl/config/container.py"
REGISTRY_MODULE: Final = PACKAGE_DIR / "config" / "registry.py"
ENTRY_POINT_TABLE: Final = 'entry-points."agl.workflows"'

# Where each of the twelve is settled, spelled `path::name` so that a reader can go straight to the
# assertion and so that `test_every_settlement_names_a_test_that_exists` can resolve every one of
# them against the real file. Five targets cite a test written elsewhere rather than a copy of it
# made here, and each of those citations says in its own section why re-writing it would have been
# worse. Nothing is listed twice: a target settled here is settled here.
HERE: Final = "tests/test_measurable_targets.py"
CONTRACT_FIRING: Final = "tests/test_contract_firing.py"

SETTLED: Final[Mapping[int, tuple[str, ...]]] = {
    1: (
        f"{HERE}::test_nothing_outside_the_workflows_package_imports_a_workflow",
        f"{HERE}::test_the_registry_dispatches_through_no_name_it_was_handed",
        f"{HERE}::test_every_workflow_package_is_one_entry_point_line_and_no_more",
    ),
    2: (
        f"{HERE}::test_both_workflows_are_the_size_the_target_records",
        f"{HERE}::test_the_counting_method_reproduces_the_decomposition_the_target_recorded",
    ),
    3: (
        f"{HERE}::test_only_the_composition_root_names_an_adapter",
        f"{HERE}::test_there_is_one_config_section_per_agent_backend",
        f"{HERE}::test_no_workflow_reaches_an_adapter_or_the_configuration",
        "tests/config/test_schema.py::test_there_is_one_agent_section_per_provider_member",
    ),
    4: (
        "tests/workflows/test_fix.py::"
        "test_one_run_addresses_two_providers_and_both_preflight_checks_pass",
    ),
    5: (
        f"{HERE}::test_vendor_containment_is_a_pair_of_instruments",
        f"{CONTRACT_FIRING}::test_the_named_contract_breaks_on_the_violation_it_exists_to_catch",
    ),
    6: (f"{HERE}::test_deleting_an_adapter_package_dangles_the_container_alone",),
    7: (
        f"{HERE}::test_every_port_with_an_abc_has_a_contract_suite",
        f"{HERE}::test_every_contract_suite_is_run_by_at_least_two_implementations",
    ),
    8: (f"{HERE}::test_every_declared_command_runs_on_fakes_with_no_way_out",),
    9: (
        "tests/test_concurrent_runs.py::"
        "test_three_runs_on_one_repository_overlap_and_leave_three_independent_branches",
    ),
    10: (
        "tests/sdk/test_kill_and_resume.py::"
        "test_the_core_programme_is_identical_however_far_it_got_before_it_was_killed",
        "tests/sdk/test_kill_and_resume.py::"
        "test_the_kill_runs_no_finally_and_no_atexit_where_a_clean_finish_runs_both",
    ),
    11: (
        f"{HERE}::test_renaming_every_name_moves_no_fingerprint_at_all",
        f"{HERE}::test_a_landing_writes_the_namespace_into_the_history",
    ),
    12: (f"{HERE}::test_target_twelve_is_unverifiable_because_tickets_does_not_exist",),
}

# --- readers: everything structural is derived from the tree, never from a list typed here -----

def _modules(root: Path) -> list[Path]:
    """Every `.py` file under `root`, sorted, with `__pycache__` left out.

    Sorted so a failure names the same file every run, and `__pycache__` excluded because a stale
    `.pyc` directory is not source: nothing imports one by path, and counting one would inflate
    every number below it.
    """
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)

def _imported(source: str) -> set[str]:
    """Every module name `source` imports, from both statement shapes.

    Parsed rather than grepped, which is the whole point: a package name is spelled in string
    literals as well as in imports - `config/registry.py`'s `GROUP: Final = "agl.workflows"` is one
    - and a text search cannot tell a name in a message from an import of it.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
    return found

def _reaches(imported: str, package: str) -> bool:
    """Whether `imported` names `package` or something inside it."""
    return imported == package or imported.startswith(f"{package}.")

def _importers(root: Path, package: str, *, base: Path) -> dict[str, tuple[str, ...]]:
    """Every module under `root` that imports `package` or a descendant, and what it named.

    Keyed by the path relative to `base`, which is `src/` for the tree as it stands and the copy's
    own root for the mutation pass - so a failure always spells a module the way `src/` does, and
    the two readings are comparable. A reader chasing one wants a path to open, not a dotted name
    to translate.
    """
    found: dict[str, tuple[str, ...]] = {}
    for path in _modules(root):
        hits = tuple(
            sorted(name for name in _imported(path.read_text()) if _reaches(name, package))
        )
        if hits:
            found[str(path.relative_to(base))] = hits
    return found

def _own_adapter(relative: str) -> str:
    """The adapter package the module at `relative` belongs to, or `""` for one outside `adapters/`.

    `agl/adapters/git/workspace.py` belongs to `agl.adapters.git`, and `agl/adapters/routing.py` -
    a top-level module rather than a directory - belongs to `agl.adapters.routing`. A module is
    allowed to import inside its own package, and that is not what any rule here is about; a module
    outside `adapters/` has no own adapter, so every adapter it names is one it reached for.
    """
    parts = Path(relative).with_suffix("").parts
    if parts[:2] != ("agl", "adapters") or len(parts) < 3:
        return ""
    return ".".join(parts[:3])

def _statements(tree: ast.AST) -> Iterator[ast.stmt]:
    """Every statement in `tree`, nested ones included, with docstrings dropped.

    A docstring is an `ast.Expr` over a string constant, and this repository writes attribute
    docstrings too - a bare string after a dataclass field, which `ast.get_docstring` cannot see -
    so both are dropped by shape rather than by position. What is left is what the module *does*,
    which is the thing #2 is counting.
    """
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            for statement in getattr(node, field, []):
                if isinstance(statement, ast.stmt) and not _is_docstring(statement):
                    yield statement

def _is_docstring(statement: ast.stmt) -> bool:
    """Whether `statement` is a bare string expression - a docstring of either kind."""
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )

def _spanned(statement: ast.stmt) -> range:
    """The lines a statement's own header occupies - decorators in, the body it encloses out.

    A compound statement's `ast.unparse` renders everything inside it, so a function whose body
    happens to call `terminal.show` would match a test for `terminal.show` on the *function*. What
    is wanted is the lines the author wrote to open the statement - decorators included, since a
    decorator is part of the declaration - and this is them.

    A range rather than a string, because #2's counter needs both: `_header` renders these lines to
    match text in, and the wiring rule below also asks whether a *name* is referenced in them,
    which is a question about the parsed statement and not about its text.
    """
    decorators = [node.lineno for node in getattr(statement, "decorator_list", [])]
    start = min([statement.lineno, *decorators])
    body = getattr(statement, "body", None)
    end = body[0].lineno - 1 if body else (statement.end_lineno or statement.lineno)
    return range(start, end + 1)

def _header(statement: ast.stmt, lines: Sequence[str]) -> str:
    """A statement's own source, without the body it encloses - the lines `_spanned` names."""
    span = _spanned(statement)
    return "\n".join(lines[span.start - 1 : span.stop - 1])

def _entry_points() -> Mapping[str, str]:
    """`pyproject.toml`'s `agl.workflows` table: registered name to `module:attribute`.

    Read out of the file rather than off the installed distribution, deliberately. What #1 counts is
    the *edit* a workflow author makes, and that edit is a line in this table; whether the
    distribution has been rebuilt since is `tests/config/test_registry.py`'s question and it names
    the command that answers it.
    """
    project = tomllib.loads(PYPROJECT_FILE.read_text())["project"]
    table = project["entry-points"]["agl.workflows"]
    assert isinstance(table, dict)
    return {str(name): str(value) for name, value in table.items()}

def _contract(number: str) -> Mapping[str, str]:
    """One `.importlinter` contract, as the raw text of its keys. Numbers are stable by policy."""
    config = ConfigParser()
    config.read_string(IMPORTLINTER_FILE.read_text())
    section = f"importlinter:contract:{number}"
    assert config.has_section(section), (
        f"there is no contract {number} in {IMPORTLINTER_FILE}. Contract numbers are stable by "
        f"policy - see that file's header - so a renumbering is a change here, to "
        f"tests/test_contract_listings.py and to tests/test_contract_firing.py, which resolve a "
        f"number against that file too."
    )
    return dict(config[section])

def _shell_constant(name: str) -> str:
    """A `NAME="value"` assignment from `scripts/check`, read out of the script itself.

    The gate's scope is declared once, at the top of the script, and this reads that declaration
    rather than restating it. A test carrying its own copy of the binary name would agree with
    itself and with nothing else.
    """
    for line in CHECK_SCRIPT.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name}="):
            return stripped[len(name) + 1 :].strip().strip('"')
    raise AssertionError(
        f"{CHECK_SCRIPT} no longer declares {name}. That constant is how the Codex binary gate "
        f"states its own scope, and target #5's second instrument is that gate - so a gate whose "
        f"scope has moved somewhere this cannot read is a gate nothing here is measuring."
    )

# ================================================================================================
# Target 1 - adding a workflow touches one new package plus one entry-point line
# ================================================================================================

def test_nothing_outside_the_workflows_package_imports_a_workflow() -> None:
    """"No central dispatch to edit", read as a fact about the import graph.

    The target is that a workflow arrives as a package plus one line, with no edit to `cli/`,
    `api.py`, `sdk/` or `config/`. The mechanical form of that is the absence this asserts: if
    nothing outside `src/agl/workflows/` names a workflow module, then no module outside it can
    have been edited to learn about one, whatever anybody remembers about the diff.

    **Verified by entry point, not by dispatch**, which is the half worth stating. `config/
    registry.py` resolves a name through `importlib.metadata`, so the framework reaches a workflow
    through a table the *packaging system* holds - and the test for that is the neighbour below,
    which asks what the resolver is made of rather than who imports whom.

    Parsed and not grepped, because three lines under `src/` outside `src/agl/workflows/` spell
    `agl.workflows` in a string rather than in an import - `config/registry.py`'s
    `GROUP: Final = "agl.workflows"`, and the lines in `cli/commands/run.py` and
    `cli/commands/workflows.py` that name the entry-point group to an operator. None of the three
    is an import; a text search cannot tell the difference and reports three violations where there
    are none.
    """
    outsiders = {
        module: names
        for module, names in _importers(PACKAGE_DIR, WORKFLOWS_PACKAGE, base=SRC).items()
        if not module.startswith("agl/workflows/")
    }

    assert not outsiders, (
        f"{sorted(outsiders)} import a workflow module, and every one of them is outside "
        f"src/agl/workflows/: {outsiders}. Target #1 is that adding a workflow touches one new "
        f"package plus one entry-point line, and a framework module that names a workflow is a "
        f"module the next workflow's author has to edit. Workflows are reached through the "
        f"`agl.workflows` entry points and through nothing else."
    )

def test_the_registry_dispatches_through_no_name_it_was_handed() -> None:
    """The prohibition, read off the resolver's code and never off its prose.

    "No `importlib`, no `getattr`, no central dispatch to edit." `config/registry.py`'s own
    docstring reads that prohibition correctly and this asserts exactly what it claims: what the
    rule forbids is the *pair* - `import_module` with a path built from a string, and `getattr` with
    an attribute name built from a string - and `importlib.metadata.entry_points()` is not that. So
    the module names `importlib` legitimately, and the three things asserted absent here are the
    three that would make it a dispatch again.

    **The f-string clause is the sharp one.** `registry.py` holds f-strings - its refusals are
    written in them - so "no f-string" would be false and "no f-string at all" would be the wrong
    rule anyway. What cannot be there is an f-string that *composes a module path*, which is what
    the old code did and what the docstring quotes twice; the test is therefore for the literal
    `agl.workflows` inside an interpolation, and it is the module path being built that it catches.

    Every clause reads the parsed module, so the four prose quotations of the old code that live in
    the docstring are invisible here, which is the whole reason this is an AST walk.
    """
    tree = ast.parse(REGISTRY_MODULE.read_text())
    statements = list(_statements(tree))

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    named = {
        node.func.id
        for node in calls
        if isinstance(node.func, ast.Name)
    } | {
        node.func.attr
        for node in calls
        if isinstance(node.func, ast.Attribute)
    }
    assert "getattr" not in named, (
        f"{REGISTRY_MODULE} calls `getattr`. What is forbidden is the pair that makes a "
        f"dispatch out of a string the operator typed, and this is half of it: the old code did "
        f"`getattr(module, "
        f"'resume', None)` and a name resolved that way is a name nothing declares."
    )
    assert "import_module" not in named, (
        f"{REGISTRY_MODULE} calls `import_module`. That is the other half of that pair - the old "
        f"code did `importlib.import_module(f'agl.workflows.{{name}}.workflow')` - and it is the "
        f"line target #1 exists to have deleted. `EntryPoint.load()` is the sanctioned resolution."
    )

    interpolations = [
        node
        for statement in statements
        for node in ast.walk(statement)
        if isinstance(node, ast.JoinedStr)
        and any(
            isinstance(part, ast.Constant)
            and isinstance(part.value, str)
            and WORKFLOWS_PACKAGE in part.value
            for part in node.values
        )
    ]
    assert not interpolations, (
        f"{REGISTRY_MODULE} builds a module path by interpolation: {len(interpolations)} f-string"
        f"(s) in its code hold {WORKFLOWS_PACKAGE!r}. A path assembled from a string the operator "
        f"typed is the forbidden dispatch, however it is spelled. The module's own docstring "
        f"quotes the old line twice and that is prose - this walks the parsed statements, so a "
        f"hit here is code."
    )

def test_every_workflow_package_is_one_entry_point_line_and_no_more() -> None:
    """The other half of #1: one package, one line, and the two lists derived from each other.

    Nothing here is typed twice. The packages come from walking `src/agl/workflows/` and the lines
    come from parsing `pyproject.toml`, so a workflow package with no registration and a
    registration naming no package both fail, and a third workflow added later is covered the
    moment it exists.

    **The value's shape is asserted too**, because "one line" is a claim about what the line says
    as well as that it exists: `<name> = "agl.workflows.<name>:<name>"` is the registration form,
    and it is the form that makes the entry point resolvable without a central table. A line
    pointing somewhere else would be a workflow reached by a route this file has not measured.
    """
    packages = sorted(
        path.name
        for path in WORKFLOWS_DIR.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    registered = _entry_points()

    assert packages, (
        f"{WORKFLOWS_DIR} holds no workflow package at all, so this comparison is between two "
        f"empty lists and would pass against a repository that ships no workflows. That is the "
        f"failure mode of a mistyped path, not a green build."
    )
    assert sorted(registered) == packages, (
        f"the workflow packages under {WORKFLOWS_DIR} are {packages} and the "
        f"[project.{ENTRY_POINT_TABLE}] table registers {sorted(registered)}. Target #1 is one "
        f"package plus one entry-point line: a package with no line is a workflow `agl run` cannot "
        f"reach, and a line with no package is a registration that fails at load."
    )
    for name, value in sorted(registered.items()):
        assert value == f"{WORKFLOWS_PACKAGE}.{name}:{name}", (
            f"the entry point {name!r} points at {value!r} rather than at "
            f"`{WORKFLOWS_PACKAGE}.{name}:{name}`. A registration line names the package's "
            f"own decorated function, which is what makes the package plus the line the whole of "
            f"the edit - a value pointing elsewhere is a second convention to keep true."
        )

# ================================================================================================
# Target 2 - `fix` is ~8 lines, `split` is ~30
# ================================================================================================
#
# **One counting method, applied to both.** There are two defensible ones and they disagree, so
# choosing quietly would be choosing the flattering answer. The method here is:
#
#     logical statements in the workflow package's `__init__.py`, docstrings and import
#     statements excluded.
#
# It is chosen because it is the one that **reproduces the target's own recorded number**, which
# says of `fix` "8 logical statements for the workflow specified, plus 4 more to wire one
# interactive screen (a handler, its body, a `replace` for the asking role, and the board's
# `show`)", and under this method `fix` is 12 statements of which exactly those 4 are the screen
# wiring. Any method that cannot reproduce that decomposition is measuring something else.
#
# **The decomposition has changed and the floor has not.** The target is quoted above as it was
# written - "8 ... plus 4 more to wire one interactive screen (a handler, its body, a `replace` for
# the asking role, and the board's `show`)" - and two of those four are no longer in this package.
# A question used to be a callback the framework asked through: `fix` wrote an `async def answer`
# and its one-line body, put it on a role with `on_question=`, and AGL supplied the tool the agent
# called. A question is now an ordinary tool the *workflow* supplies, and `fix` writes it in
# `workflows/fix/asking.py` - a payload class, a handler, and a `tool()` call - so what is left in
# `__init__.py` is the statement that hands the role its tool and the board's `show`.
#
# So: **wiring went from 4 to 2, and the floor stayed at 8.** The floor is the number target #2 is
# about, it is the target's own, and it did not move - the two statements that left were both
# wiring, and neither was the workflow. The recorded decomposition below is updated to what is
# true rather than kept at what was recorded, because a count that no longer describes the file is
# a count nobody can check. What the two numbers now say is: `fix` is 10 logical statements, 2 of
# them putting a screen in front of a person, 8 of them the workflow the target specified.
#
# **That sentence is only worth anything under one rule, and the first rewrite was not one.** A
# widening is exactly where a count improves because the counter moved, so the rule below is run
# against `PREVIOUS_FIX` - the `__init__.py` as it stood when the decomposition was recorded - and
# has to answer 12 and 4 there. The first attempt at the rewrite did not: it matched a statement
# whose header names `.terminal` and nothing else, which scores the *old* file 2 as well, putting
# its floor at 10 and **failing this target on the tree the target was written against**. Under
# that rule the workflow contributed nothing at all to 4 -> 2; the whole of the delta was the
# rewrite, and the floor read 8 only because the total had dropped by 2 at the same time. So the
# clause it had dropped is kept: the old rule caught a handler by *name* and caught the statement
# that handed it over, and both survive with `on_question` generalised to "a nested function that
# reaches the terminal". What actually moved is then visible in one line - the handler and its body
# left this file for `asking.py`, and `implementer(ask=asking(run.terminal))` arrived.
#
# The statements that left did not vanish - they moved to `workflows/fix/asking.py`, which this
# method does not count, and which is bigger than the two lines it replaced because it carries the
# vocabulary two adapters used to carry twice: a schema, a blank-question refusal, an options
# normalisation, and a sentence for an answer that was empty. That is not hidden by the number and
# is not meant to be: #2 counts a workflow's `__init__.py`, which is the file an author writes the
# workflow *in*, and a package growing a module beside it is visible to anybody reading the package.
# `tests/workflows/test_fix.py` is where that module is measured.
#
# The method that was refused, and its numbers, because a reader deserves both: counting only the
# **decorated function's body** gives `fix` = 8 and `split` = 6. Those are smaller and they are the
# flattering pair, and they cannot reproduce the target's "8 plus 4" - the whole of `fix`'s body is
# 8 statements *including* the four the target adds on top, so under that method its arithmetic has
# nowhere to go.
#
# What the chosen method includes beyond the function body is what an author actually writes: the
# params dataclass and its `arg()` fields, the `@workflow` declaration itself, the `__all__` a
# package exports, and - in `split` - the module-level `_implement` that is one chunk's half of the
# workflow. Imports are excluded because an import is not a decision; docstrings are excluded for
# the reason `scripts/check`'s module size ceiling excludes them, which that gate argues at length.

FIX_PACKAGE: Final = WORKFLOWS_DIR / "fix" / "__init__.py"
SPLIT_PACKAGE: Final = WORKFLOWS_DIR / "split" / "__init__.py"

# The recorded decomposition of `fix`: the workflow, plus the interactive screen. `FIX_CORE` is the
# target's own number and has not moved. `FIX_SCREEN_WIRING` was 4 and is 2 - see the section header
# above for what left and where it went.
FIX_CORE: Final = 8
FIX_SCREEN_WIRING: Final = 2

# The target's word for `split`, which is a bound rather than a number: "`split` is ~30".
SPLIT_CEILING: Final = 30

# `src/agl/workflows/fix/__init__.py` as it stood when target #2's decomposition was recorded. The
# method's stated criterion is that it reproduces that decomposition, and a criterion nothing runs
# is how the wiring rule got narrower once already - so the criterion is run, below, against this.
# Frozen history rather than a copy of anything live: no edit under `src/` can move it, and the day
# `fix` changes again this still says 12 and 4.
PREVIOUS_FIX: Final = '''
from dataclasses import dataclass

from agl.sdk import Answer, Question, Run, arg, workflow
from agl.workflows.fix import views
from agl.workflows.fix.roles import implementer, reviewer

__all__ = ["FixParams", "fix"]


@dataclass(frozen=True)
class FixParams:

    request: str = arg("-r", "--request", help="what to fix, in your own words")


@workflow(version="1.1")
async def fix(run: Run[FixParams]) -> None:

    async def answer(question: Question) -> Answer:
        return await run.terminal.show(views.agent_question, question=question)

    asking = implementer(on_question=answer)
    await run.terminal.show(views.board, run=run, request=run.params.request)
    await run.step(asking, request=run.params.request, commit="implement fix")
    findings = await run.step(reviewer())
    if findings.high():
        await run.step(asking, findings=findings.high(), commit="address review findings")
'''

def _counted(module: Path) -> tuple[int, int]:
    """A workflow package's statement count, and how many of those are interactive-screen wiring.

    The wiring is identified structurally and not by line number, in three clauses:

      1. a statement whose own **header** names `.terminal` - that is `Run.terminal`, the one member
         a workflow reaches a person through, so `await run.terminal.show(views.board, ...)`,
         `if await w.terminal.show(views.conflict, ...)` and `implementer(ask=asking(run.terminal))`
         all count, the last of them handing a role a tool whose handler shows a screen;
      2. a **nested** function whose body reaches the terminal - a screen handler written inside the
         workflow, whose own header names nothing and which clause 1 therefore cannot see;
      3. a statement whose header **references** such a function - the line that hands the handler
         over to whatever is going to call it.

    **Clauses 2 and 3 are the old rule generalised, not new machinery, and dropping them is how a
    counter flatters.** The rule read "names `terminal.show` or `on_question`, or *is* the handler
    function some `on_question=` keyword points at" - three clauses, the same three - and
    `on_question` no longer exists, so the middle term had to be rewritten. Rewriting it to
    `.terminal` and stopping there was tried and refused: `.terminal` alone scores the *previous*
    `fix` 2 rather than 4, which puts that file's floor at 10 and fails target #2 on the very tree
    the target was written against - so the whole of the recorded 4 -> 2 would have been the
    counter moving rather than the workflow. `test_the_counting_method_reproduces_the_
    decomposition_the_target_recorded` is that check, kept as a test rather than as this paragraph.

    Clause 3 asks the *parsed* statement whether a handler's name is loaded inside `_spanned`'s
    lines, rather than searching the header's text for it, so a name that occurs as part of a longer
    word is not a hand-over. Clause 2 is restricted to a nested function because the module-level
    ones are the workflow itself and `split`'s `_implement`, and a rule that counted a def because
    something inside it reaches a screen would report the whole workflow as wiring.

    **What it deliberately does not do is follow the wiring out of the package.** `fix`'s asking
    tool lives in `workflows/fix/asking.py` and nothing here counts it; the section header above
    says so and says why. A rule that chased imports would be measuring a different thing from the
    one target #2 recorded, which is the size of the file the workflow is written in.

    `_header` and not `ast.unparse`, because unparsing a compound statement renders its whole body:
    the `@workflow` declaration would match `.terminal` on account of a call four lines inside it,
    and the count would then say the workflow function is a screen.
    """
    source = module.read_text()
    lines = source.splitlines()
    tree = ast.parse(source)
    statements = [
        node
        for node in _statements(tree)
        if not isinstance(node, ast.Import | ast.ImportFrom)
    ]
    handlers = {
        statement.name
        for statement in statements
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
        and statement not in tree.body
        and any(".terminal" in _header(inner, lines) for inner in _statements(statement))
    }

    def wiring(statement: ast.stmt) -> bool:
        if getattr(statement, "name", None) in handlers:
            return True
        if ".terminal" in _header(statement, lines):
            return True
        span = _spanned(statement)
        return any(
            isinstance(node, ast.Name) and node.id in handlers and node.lineno in span
            for node in ast.walk(statement)
        )

    return len(statements), sum(1 for statement in statements if wiring(statement))

def test_both_workflows_are_the_size_the_target_records() -> None:
    """#2, under the one method the section header above names, applied to both workflows.

    Three assertions and each is a different claim:

      * **`fix`'s floor is 8.** Take away the statements that wire one interactive screen and what
        is left is the workflow as specified - the two steps, the branch, and the repair - plus the
        params and the declaration an author cannot avoid writing. That is the number the target
        means by "~8 lines", it is the target's own, and it has not moved.
      * **The screen costs exactly 2**, where the target recorded 4. Two of those four were an
        `async def` question handler and its body, and they left this package when a question became
        an ordinary tool a workflow supplies - see the section header for where they went. The
        screen wiring sits on top of the floor; it does not move it, which is why the floor is
        unchanged by a change that halved the wiring.
      * **`split` is under 30.** The target's word for `split` is "~30", so what is asserted is the
        bound rather than a number, and the measured value is carried into the failure message so
        that a workflow which grew is reported as a size and not only as a breach.

    **`split` adds concurrency, child worktrees and integration with no framework change between
    them**, which is the other half of #2's sentence and is settled by #1's assertions rather than
    by a count: nothing outside `src/agl/workflows/` names either workflow, so whatever `split`
    needed, it did not get by editing the framework. The record of that is in
    `src/agl/workflows/split/__init__.py`'s docstring, which reports the one diff it deliberately
    did not make.
    """
    fix_total, fix_wiring = _counted(FIX_PACKAGE)
    split_total, split_wiring = _counted(SPLIT_PACKAGE)

    assert fix_wiring == FIX_SCREEN_WIRING, (
        f"{FIX_PACKAGE.parent.name} spends {fix_wiring} statements on interactive-screen wiring "
        f"and this file records {FIX_SCREEN_WIRING} - the statement that hands the asking role its "
        f"tool, and the board's `show`. The decomposition is what makes floor a floor: if the "
        f"wiring count moved, the number left under it is not the specified workflow any more."
    )
    assert fix_total - fix_wiring == FIX_CORE, (
        f"`fix` is {fix_total} logical statements of which {fix_wiring} are screen wiring, leaving "
        f"{fix_total - fix_wiring} where the target records {FIX_CORE}. Target #2 is that `fix` "
        f"is ~8 lines and gets fingerprinted replay, a worktree, preflight and exit codes free. "
        f"The floor is what is being measured; the question wiring sits on top of it."
    )
    assert split_total <= SPLIT_CEILING, (
        f"`split` is {split_total} logical statements against target #2's ~{SPLIT_CEILING}. It is "
        f"the workflow that adds concurrency, child worktrees and integration, and the claim is "
        f"that it adds them with no framework change between it and `fix` - a `split` that has "
        f"outgrown the number is either doing framework work or doing more than one thing. "
        f"({split_wiring} of those statements are screens.)"
    )

def test_the_counting_method_reproduces_the_decomposition_the_target_recorded(
    tmp_path: Path,
) -> None:
    """The criterion the counting method was chosen by, run instead of asserted in prose.

    The section header says it in as many words - "it is chosen because it is the one that
    reproduces the target's own recorded number ... any method that cannot reproduce that
    decomposition is measuring something else" - and until this test existed that was a sentence
    nothing checked. It went wrong exactly as an unchecked criterion does. When `on_question` was
    deleted the wiring rule had to be rewritten, the rewrite dropped two of the old rule's three
    clauses, and the recorded wiring went from 4 to 2 with the section header attributing the drop
    to two statements leaving the package. Under the rule that produced the 2, the *previous* file
    scores 2 as well: the workflow contributed nothing to the delta, and this assertion is what
    would have said so.

    So the method is run against `PREVIOUS_FIX` and has to answer with the decomposition the target
    recorded - `FIX_CORE` statements plus the four the target names, of which the four are the
    wiring. **`FIX_CORE` is on both sides on purpose.** The floor is the number target #2 is about,
    and what is being asserted is that it is the same floor here and in `fix` today - a rule that
    moved it under the old file would be a rule reporting a workflow that has not been edited in
    years as having changed size.

    The historical source is frozen in this module rather than read out of git, because a test that
    resolves a commit is a test a rebase can delete and this claim is about a file's *content*, not
    about a repository's history. Nothing under `src/` can drift from it either, which is what makes
    it safe to keep: it is the past, and the past does not need maintaining.
    """
    previous = tmp_path / "__init__.py"
    previous.write_text(PREVIOUS_FIX)

    total, wiring = _counted(previous)

    assert (total, wiring) == (FIX_CORE + 4, 4), (
        f"the counting method scores the `fix` that target #2's decomposition was recorded against "
        f"at {total} statements of which {wiring} are screen wiring, where the target records "
        f"{FIX_CORE + 4} and 4 - a handler, its body, the statement that puts it on the asking "
        f"role, and the board's `show`. The method is chosen *because* it reproduces that "
        f"decomposition, so a rule that cannot is measuring something else, and any number it "
        f"reports for the workflow as it stands today is a number about the rule rather than about "
        f"the workflow. Its floor here would be {total - wiring} against the target's {FIX_CORE}."
    )

# ================================================================================================
# Target 3 - adding an agent backend touches one adapter package, one container line, one config
#            section, and no workflow
# ================================================================================================

def test_only_the_composition_root_names_an_adapter() -> None:
    """The container is the one place a backend is wired in - the second half of #3, from the tree.

    Every import of `agl.adapters.*` from outside the importing module's own adapter package is
    collected and compared against the one module allowed to hold any: `config/container.py`. That
    is the mechanical form of "one line in the container" - not that the count of lines is one,
    which no rule could hold, but that there is exactly one *place* a new backend is wired into,
    and it is the composition root.

    This is `.importlinter`'s contract 5 asked from the other side and it is not redundant with it.
    The contract asks whether anything broke a rule; this asks *where the wiring lives*, and it is
    the answer to that question - one file - that makes #3's claim about what an author edits. A
    module inside its own adapter package importing its own siblings is not a hit here and is not
    what either rule is about.
    """
    reaching = {
        module: names
        for module, names in _importers(PACKAGE_DIR, ADAPTERS_PACKAGE, base=SRC).items()
        if not all(_reaches(name, _own_adapter(module)) for name in names)
    }

    assert set(reaching) == {CONTAINER_MODULE}, (
        f"the modules naming an adapter from outside their own package are {sorted(reaching)}, "
        f"and target #3 is that adding an agent backend touches one adapter package, one line in "
        f"the container and one config section. Every name of an adapter outside "
        f"{CONTAINER_MODULE} is a second place the next backend's author has to edit. What was "
        f"found: {reaching}"
    )

def test_there_is_one_config_section_per_agent_backend() -> None:
    """One config section per backend: the correspondence between `AgentSettings` and `Provider`.

    A provider with no section is a provider nothing can configure, which is the old flat
    single-sourced configuration recurring. Asserted here as part of #3's three-way claim and
    asserted again, on its own terms and with its own message, in `tests/config/test_schema.py` -
    which is where it belongs and which is cited in `SETTLED` beside this. The duplication is
    deliberate and is one line: this file's job is to show all twelve targets settled in one place,
    and a target settled by a citation alone reads as a target nobody measured here.
    """
    sections = {field.name for field in fields(AgentSettings)}
    providers = {str(member) for member in Provider}

    assert sections == providers, (
        f"`AgentSettings` holds sections {sorted(sections)} and `ports/agent.py`'s `Provider` has "
        f"members {sorted(providers)}. Target #3's third clause is one config section per backend: "
        f"a provider with no section ships unconfigurable, and a section with no provider "
        f"configures nothing."
    )

def test_no_workflow_reaches_an_adapter_or_the_configuration() -> None:
    """No workflow changes: the absence that makes that true whoever adds the next backend.

    A workflow that could name an adapter would be a workflow the next backend might have to edit.
    Nothing under `src/agl/workflows/` imports `agl.adapters` or `agl.config`, so the third clause
    of #3 holds structurally rather than by anybody's care.

    `.importlinter`'s contract 6 is the enforcement and `tests/test_contract_firing.py` fabricates
    both halves of it and watches it fire. This is the measurement beside it, in the vocabulary of
    the target: what #3 promises is about what an *author* has to touch, and that is a claim about
    the tree rather than about a config file.

    A workflow naming a **model** - `Claude.OPUS`, `OpenAI.SOL` - is correct and expected, and is
    not what this measures. Target #5 says so in as many words: those are the sanctioned way for a
    workflow to express provider choice without naming a harness, and no
    import of theirs reaches an adapter.
    """
    adapters = _importers(WORKFLOWS_DIR, ADAPTERS_PACKAGE, base=SRC)
    configuration = _importers(WORKFLOWS_DIR, CONFIG_PACKAGE, base=SRC)
    reaching = {
        module: adapters.get(module, ()) + configuration.get(module, ())
        for module in adapters.keys() | configuration.keys()
    }

    assert not reaching, (
        f"{sorted(reaching)} import `{ADAPTERS_PACKAGE}` or `{CONFIG_PACKAGE}` from inside "
        f"src/agl/workflows/: {reaching}. Target #3 promises that adding an agent backend changes "
        f"no workflow, and a workflow that names an adapter or the configuration is a workflow "
        f"the next backend can break."
    )

# ================================================================================================
# Target 4 - one run addresses two providers
# ================================================================================================
#
# **Cited, not re-implemented.** `tests/workflows/test_fix.py::
# test_one_run_addresses_two_providers_and_both_preflight_checks_pass` is the assertion, and it is
# better than a copy made here would be: it drives the real `fix` workflow through the real harness
# and reads the models off the tasks that came out of one run - Claude, OpenAI, Claude - so "two
# providers" is a fact about the dispatch rather than about a role declaration.
#
# **It records its own limit**, which is why it could not be improved on from here. Preflight
# passing leaves nothing behind: preflight's two checks run before the record is written, so a run
# with a `run.json` and three entries is a run that passed them and there is no artefact to assert
# on. That test therefore asks both questions again, explicitly, of the same runner the run used,
# and says in its docstring that this is the workaround for an invisible half rather than a second
# measurement of it. Re-asking them here would be a third copy of the same workaround.

# ================================================================================================
# Target 5 - vendor containment, tested two ways
# ================================================================================================

def test_vendor_containment_is_a_pair_of_instruments() -> None:
    """Two instruments, one per vendor, each shaped by how that vendor is reached.

    The target asks for containment "tested two ways", and the two are not two copies of one test.
    The Claude SDK is a Python import, so `.importlinter`'s contract 3 contains it and
    import-linter refuses the import. The Codex CLI is a **binary**, so there is no import for a
    contract to see and `scripts/check`'s grep gate stands in for one. This asserts that both
    exist, that each is scoped to its own adapter, and that the grep has something to find.

    **These are import-and-invocation tests, not name tests**, which the target states and which
    decides what is *not* asserted here. `Claude.OPUS` and `OpenAI.SOL` in a workflow are correct
    and are the sanctioned way to express provider choice; the rule is about who may `import
    claude_agent_sdk` and who may spawn the binary, not about who may say a vendor's name.

    **What is asserted and what is cited.** Contract 3's *refusal* is fabricated and watched in
    `tests/test_contract_firing.py` - one vendor's adapter importing the other vendor's SDK, which
    is the exact failure an `agl[terminal]` install dragging in `agl[claude]` would be - so that
    citation is the firing half and this is the existence half.

    **The gate's refusal is not fabricated here, and that is a limit rather than an oversight.**
    Making it fire would mean writing its grep a third time, and a third copy is free to drift from
    the two it is meant to be checking. What is asserted instead is non-vacuity: the binary name
    really does occur inside the one directory allowed to hold it, so the gate is looking at
    something. `scripts/check` is what runs it.
    """
    contract = _contract("3")
    forbidden = set(contract["forbidden_modules"].split())
    ignored = set(contract["ignore_imports"].split("\n"))

    assert "claude_agent_sdk" in forbidden, (
        f"`.importlinter` contract 3 forbids {sorted(forbidden)} and `claude_agent_sdk` is not "
        f"among them. That contract is the first of target #5's two instruments: without it a "
        f"vendor SDK is contained by nothing at all, and an `agl[terminal]` install can drag in "
        f"`agl[claude]`."
    )
    assert any(
        expression.strip().startswith("agl.adapters.claude_code") for expression in ignored
    ), (
        f"contract 3's exemptions are {sorted(e.strip() for e in ignored if e.strip())} and none "
        f"of them scopes `claude_agent_sdk` to `agl.adapters.claude_code`. The contract is only "
        f"containment if exactly one adapter is let through: an unscoped exemption forbids nothing."
    )

    binary = _shell_constant("CODEX_BINARY")
    directory = _shell_constant("CODEX_ADAPTER_DIR")

    assert directory == "src/agl/adapters/openai/", (
        f"`scripts/check`'s Codex gate is scoped to {directory!r}. Target #5's second instrument "
        f"is a gate over the OpenAI adapter, which wraps the binary because that vendor ships no "
        f"Python SDK to import - a scope pointing elsewhere is a gate for a different rule."
    )
    inside = [
        path
        for path in _modules(SRC / "agl" / "adapters" / "openai")
        if binary.casefold() in path.read_text().casefold()
    ]
    assert inside, (
        f"no module under {directory} names the {binary!r} binary, so `scripts/check`'s gate is "
        f"searching for something that does not exist and would report zero violations against "
        f"any tree at all. A gate that cannot find its own subject is not containing it - this is "
        f"the same non-vacuity `tests/test_contract_firing.py` takes once for all six contracts."
    )

    extras = tomllib.loads(PYPROJECT_FILE.read_text())["project"]["optional-dependencies"]
    assert "openai" not in extras, (
        f"`pyproject.toml` now declares an `openai` extra ({sorted(extras)}). The whole reason "
        f"target #5 needs two instruments rather than one is that the OpenAI adapter has no Python "
        f"dependency to contain - it shells out to a binary. An extra here means there is now an "
        f"import to contain, and contract 3 is where it goes."
    )

# ================================================================================================
# Target 6 - deleting a connector breaks nothing else
# ================================================================================================
#
# The one target with no static form. "Deleting a connector breaks nothing else" is a claim about a
# tree that does not exist until something has been deleted from one, so this is a **mutation
# pass**: copy `src/` into a directory of its own, remove one adapter package, and ask what still
# names it.
#
# Parametrised over **every adapter derived from the tree**, not over the two connectors alone. Part
# 5 words the target for a connector - "deleting its adapter package, its port, its config section,
# and its container entry" - and the property turns out to hold for every peer behind every port,
# which is contract 4's "adapters are peers" measured rather than asserted. An adapter added at a
# later stage is swept in the moment it exists.
#
# **Scope, stated so the verdict is not read for more than it says.** What is mutated is the adapter
# package and what is measured is the dangling *imports* in `src/`. The port, the config section and
# the container entry named in the target are deliberate edits an author makes, not references that
# dangle; `pyproject.toml`'s extras table is outside `src/` and outside this pass. What the pass
# answers is the target's own last clause - *nothing else breaks* - and the answer is a set of file
# paths.

def _adapter_packages() -> list[str]:
    """Every adapter under `src/agl/adapters/`, directories and single modules alike.

    A member is an adapter, not a directory: `agl.adapters.system_clock` is one file because its
    port is one method, and it is deleted here for the same reason every package is. `__init__.py`
    is the adapters package's own docstring and is not an adapter.
    """
    return sorted(
        path.stem if path.is_file() else path.name
        for path in ADAPTERS_DIR.iterdir()
        if (path.is_dir() and path.name != "__pycache__")
        or (path.is_file() and path.suffix == ".py" and path.name != "__init__.py")
    )

@pytest.mark.parametrize("adapter", _adapter_packages())
def test_deleting_an_adapter_package_dangles_the_container_alone(
    adapter: str, tmp_path: Path
) -> None:
    """Delete one adapter from a copy of the tree, and see exactly one module notice.

    **The copy is counted as well as the verdict**, and that is the assertion this pass would be
    worthless without. A `copytree` that copied nothing, or that swept in a `.venv`, produces a
    green verdict for the wrong reason and looks identical from the summary line - so the number of
    files copied is asserted against the number of files the real `src/` holds, and `__pycache__` is
    excluded on both sides because a stale `.pyc` is not a module anybody imports.

    **The deletion is asserted to have removed something**, for the same reason: an adapter name
    that no longer matches a directory would delete nothing, find nothing dangling, and pass.

    **The verdict is a set and not a count.** What dangles must be exactly `config/container.py` -
    the composition root, which is the one module target #3 already says names an adapter. Anything
    else in that set is a module that would have to be edited to remove a connector, and target #6
    is precisely that there is no such module.

    Cheaper than `mypy`, deliberately. A type check over the mutated tree would answer the same
    question in tens of seconds; an import scan answers it in milliseconds and answers it more
    exactly, since what is wanted is *which modules name the deleted one* rather than a count of
    errors that would also include everything downstream of them.
    """
    copy = tmp_path / "tree"
    shutil.copytree(SRC, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    copied = [path for path in copy.rglob("*") if path.is_file()]
    expected = [
        path
        for path in SRC.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    assert len(copied) == len(expected), (
        f"the mutation pass copied {len(copied)} files where src/ holds {len(expected)}. A pass "
        f"over a tree that is not the tree proves nothing about the tree, and a pass over an empty "
        f"one passes for the wrong reason - which is why this number is asserted and not printed."
    )

    package = copy / "agl" / "adapters" / adapter
    module = copy / "agl" / "adapters" / f"{adapter}.py"
    if package.is_dir():
        removed = len(_modules(package))
        shutil.rmtree(package)
    else:
        removed = 1
        module.unlink()
    assert removed >= 1, (
        f"deleting the adapter {adapter!r} removed no module, so nothing was mutated and the "
        f"verdict below is about an unchanged tree."
    )

    dotted = f"{ADAPTERS_PACKAGE}.{adapter}"
    dangling = _importers(copy, dotted, base=copy)

    assert set(dangling) == {CONTAINER_MODULE}, (
        f"with `{dotted}` deleted, the modules still importing it are {sorted(dangling)} where "
        f"target #6 says the only one should be {CONTAINER_MODULE}: 'deleting a connector means "
        f"deleting its adapter package, its port, its config section, and its container entry - "
        f"nothing else breaks'. Every other name in that list is a module somebody removing a "
        f"connector would have to find. What was found: {dangling}"
    )

# ================================================================================================
# Target 7 - every port has a contract suite both real and fake pass
# ================================================================================================
#
# Derived from the tree on both sides. The ports come from walking `src/agl/ports/` for a class with
# `ABC` in its bases; the suites come from walking `tests/contracts/` for its public modules. A
# ninth port added later fails this until it has a suite, and its author need do nothing to be
# policed - which is the property, since a hand-maintained list here would agree with whoever last
# edited it.
#
# **The honest exception, recorded rather than skipped past.** Six of the agent suite's eight
# clauses **skip** against the real adapters, and that is a fact about what a free instrument can
# reach rather than about coverage. Five of the six read a model's conduct as their evidence -
# that it called a tool, that it corrected a refused call, that it ignored a poisoned repository -
# which no instrument that spends no tokens can supply, so they are deferred to the manual QA pass.
# The sixth, the activity reporter that raised, needs no conduct at all and is deferred only
# because the suite's one knob is the runner; it is asserted for real offline, further down each
# adapter's own module. The target states this exception itself, and `tests/contracts/agent.py`'s
# docstring carries the argument in full. Everything a free instrument *can* reach - hermeticity,
# tool registration, deny-rule enforcement, the composed request - is covered for the real adapters
# too.

def _ports_with_an_abc() -> dict[str, tuple[str, ...]]:
    """Every `ports/` module declaring an ABC, and the ABCs it declares.

    An ABC is the thing a contract suite is written against: a port module of pure types promises
    nothing an implementation could get wrong, and `.importlinter`'s contract 2 is what keeps the
    two kinds apart. So the parity below is over the modules that declare a behaviour, derived by
    reading the bases rather than by listing the modules.
    """
    found: dict[str, tuple[str, ...]] = {}
    for path in sorted(PORTS_DIR.glob("*.py")):
        classes = tuple(
            node.name
            for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.ClassDef)
            and any("ABC" in ast.unparse(base) for base in node.bases)
        )
        if classes:
            found[path.stem] = classes
    return found

def _contract_suites() -> dict[str, tuple[str, ...]]:
    """Every public module in `tests/contracts/`, and the suite classes it declares.

    Public only: the `_`-prefixed modules beside them are halves of a suite that its port drew a
    seam in, and they are assembled into the public class rather than being suites of their own.
    `terminal.py` declares two - the whole port and the headless half of it - which is why this
    answers with a tuple per module and the counting below sums over it.
    """
    found: dict[str, tuple[str, ...]] = {}
    for path in sorted(CONTRACTS_DIR.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        classes = tuple(
            node.name
            for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.ClassDef) and node.name.endswith("Contract")
        )
        if classes:
            found[path.stem] = classes
    return found

def _implementations() -> dict[str, list[str]]:
    """Every class under `tests/` subclassing a contract suite, keyed by the suite it subclasses.

    The base is matched on its last dotted component, so a suite reached as `contracts.store
    .StoreContract` and one imported by name count the same. What this measures is the mechanism
    `tests/contracts/` rests on: a real adapter and its fake subclass one class, so a fake that
    drifts fails a suite the adapter passes.
    """
    suites = {name for classes in _contract_suites().values() for name in classes}
    found: dict[str, list[str]] = {name: [] for name in suites}
    for path in _modules(REPO_ROOT / "tests"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                name = ast.unparse(base).rpartition(".")[2]
                if name in found:
                    found[name].append(f"{path.relative_to(REPO_ROOT)}::{node.name}")
    return found

def test_every_port_with_an_abc_has_a_contract_suite() -> None:
    """The parity itself: one suite per port that promises something, and no suite without a port.

    "*Every* port, including ones that promise little" - `Clock`'s suite is two assertions and the
    value is the parity rather than the coverage, because a rule that admitted an exception would
    admit it exactly at the shortest port.

    Both directions, because they fail differently. A port with no suite is a promise nobody checks;
    a suite with no port is a suite asserting something the architecture no longer has, which passes
    forever and means nothing. Neither list is typed here.
    """
    ports = _ports_with_an_abc()
    suites = _contract_suites()

    assert ports, (
        f"no module under {PORTS_DIR} declares an ABC, so this comparison is between two empty "
        f"sets. That is a mistyped path, not a repository with no ports."
    )
    assert sorted(ports) == sorted(suites), (
        f"the ports declaring an ABC are {sorted(ports)} and the contract suites are "
        f"{sorted(suites)}. Target #7 is that every port has a contract suite its real adapter and "
        f"its fake both pass - a port with no suite is a promise nothing holds an implementation "
        f"to, and a suite with no port is a suite about something that no longer exists."
    )

def test_every_contract_suite_is_run_by_at_least_two_implementations() -> None:
    """The mechanism the parity is for: the real adapter and the fake subclass the same class.

    Two is the floor and it is the number that matters. The whole argument is that a fake which
    answers differently from the adapter is a fake that fails a suite the adapter passes - which
    needs the suite pointed at both, and a suite with one subclass is a suite that cannot catch
    drift because there is nothing to drift from.

    Summed **per port module** rather than per class, because `terminal.py` declares two suites -
    the whole port and its headless half - and a port whose promises are split across two classes
    is still one port with implementations behind it. The counts are carried into the failure
    message so that a suite that lost a subclass is reported as a number and not only as a breach.
    """
    suites = _contract_suites()
    implementations = _implementations()
    counted = {
        port: sum(len(implementations[name]) for name in classes)
        for port, classes in suites.items()
    }

    thin = {port: count for port, count in counted.items() if count < 2}
    assert not thin, (
        f"these contract suites are run by fewer than two implementations: {thin}. Target #7 is a "
        f"suite that a port's real adapter *and* its fake both pass, and that pairing is the whole "
        f"mechanism keeping a fake from drifting into fiction - a suite with one subclass has "
        f"nothing to compare. All counts: {counted}"
    )

# ================================================================================================
# Target 8 - every command runs end-to-end on fakes alone, no network and no git
# ================================================================================================
#
# **The proxy that was refused.** "A fakes-only test exists for each of the five commands" is true
# today and is not this target. It measures what somebody remembered to write, it names the number
# five in a file that should not know it, and it is silent about a sixth command added later. What
# is asserted instead is the target's own sentence: the commands are enumerated from the **real
# parser** - the object `agl` itself builds, whose subcommands are whatever the five `declare` calls
# in `cli/main.py::parser()` put there - and every one of them is driven end-to-end through
# `main.main` on `container.fakes()` with both ways out of the interpreter poisoned.
#
# **Poisoned, not merely unused.** `subprocess.Popen.__init__` is the chokepoint every process spawn
# in the standard library goes through, `asyncio.create_subprocess_exec` and `_shell` included -
# which is what the git runner, the shell verifier and the OpenAI runner use - and `socket`'s
# reach-out surface is the other door. Both are replaced with something that raises, and the poison
# is proved live before any command runs: a test that poisoned nothing would pass identically.
#
# `socket.socketpair` is deliberately **not** poisoned and neither is `socket.socket.__init__`:
# asyncio's own self-pipe is a socket pair, so poisoning either would break the event loop rather
# than the network. What is poisoned is `connect`, `connect_ex`, `sendto`, `create_connection`,
# `getaddrinfo` and `gethostbyname` - every way to reach something that is not this process.

@dataclass(frozen=True)
class _EightParams:
    """The one flag `agl run` needs to have something to hand a workflow."""

    request: str = arg("-r", "--request", help="what to do")

@role(model=Claude.SONNET)
def _eight_role() -> Role:
    """The one role the probe runs, so `agl run` has work to do."""
    return Role(name="only", instructions="do the work")

@workflow(version="1")
async def probe(run: Run[_EightParams]) -> None:
    """One step, so that `agl run` has work to do and `agl resume` has an entry to replay.

    Module-level, because `agl.testing` resolves a workflow the way an installed one is resolved -
    `<module>:<name>` - and a workflow declared inside a function names no module attribute.
    """
    await run.step(_eight_role(), request=run.params.request)

_EIGHT_POINT: Final = EntryPoint(name="probe", value=f"{__name__}:probe", group=registry.GROUP)

# One invocation per command, in an order that lets three of them address the same run: `run`
# starts it, `resume` replays it, `clear` takes it away. The names are compared against the parser's
# own subcommands below, so this table cannot silently fall behind the grammar.
_INVOCATIONS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("init", ("init",)),
    ("workflows", ("workflows",)),
    ("run", ("run", "probe", "-n", "auth", "-r", "add oauth")),
    ("resume", ("resume", "auth")),
    ("clear", ("clear", "auth", "-f")),
)

class _WentOutside(BaseException):
    """What a poisoned door raises, and it is a `BaseException` for `agl/testing.py`'s reason.

    `main.main` catches `Exception` and turns it into an exit status out of the one table in
    `src/agl/ports/errors.py`, and a library that reached a door and fell back would catch one too.
    Either would leave a command that went outside reported as a number rather than as the door it
    went out of - so this is a `BaseException`, which nothing under test catches, and a reached
    door arrives at the assertion as itself. `agl.testing._Interrupted` is the same decision for
    the same reason.
    """

def _refusing(door: str) -> object:
    """A stand-in for `door` that raises rather than doing what it was for."""

    def poisoned(*args: object, **kwargs: object) -> NoReturn:
        raise _WentOutside(
            f"a command reached {door}, so it did not run on fakes alone. Target #8 is that every "
            f"command runs end-to-end with no network and no git; this is the door it went out of."
        )

    return poisoned

def _poison(monkeypatch: pytest.MonkeyPatch) -> None:
    """Close both doors out of the interpreter for the duration of one test.

    `subprocess.Popen.__init__` rather than `subprocess.run`: `run`, `call`, `check_output` and
    asyncio's `create_subprocess_exec`/`_shell` all construct a `Popen` in the end, so one
    replacement covers every spawn the standard library makes. The two asyncio spellings are
    poisoned by name as well, because they are the ones the adapters actually write and a failure
    naming the line an author wrote is worth two lines here.
    """
    monkeypatch.setattr(subprocess.Popen, "__init__", _refusing("subprocess.Popen"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refusing("create_subprocess_exec"))
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _refusing("create_subprocess_shell"))
    for name in ("system", "popen", "posix_spawn", "posix_spawnp", "fork", "forkpty", "execv"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, _refusing(f"os.{name}"))
    monkeypatch.setattr(socket.socket, "connect", _refusing("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _refusing("socket.connect_ex"))
    monkeypatch.setattr(socket.socket, "sendto", _refusing("socket.sendto"))
    monkeypatch.setattr(socket, "create_connection", _refusing("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _refusing("socket.getaddrinfo"))
    monkeypatch.setattr(socket, "gethostbyname", _refusing("socket.gethostbyname"))

def _declared_commands() -> set[str]:
    """Every subcommand the real parser admits, read off the object `agl` itself builds.

    `cli/main.py::parser()` calls `declare` once per command module and hands back the root parser;
    what those calls put there is what an operator can type, and it is the only list of commands
    this file will accept. A sixth command is in here the moment it is declared, whether or not
    anybody added a row to `_INVOCATIONS`.
    """
    found: set[str] = set()
    for action in main.parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            found |= {str(name) for name in action.choices}
    return found

def _eight_agent(task: AgentTask) -> Reply:
    """An agent that says it did something and touches nothing - no worktree state is asserted."""
    return Reply(says="done")

def test_every_declared_command_runs_on_fakes_with_no_way_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#8 in the target's own words: every command, end-to-end, on fakes, with no way out.

    Three assertions, in this order, and the order is the argument:

      1. **The table covers the grammar.** The commands driven below are compared against the real
         parser's subcommands, so a sixth command declared without fakes-only coverage fails here
         rather than shipping unmeasured. This is the assertion that makes the target's word
         "every" mean something.
      2. **The poison is live.** A `subprocess.run` and a `socket.create_connection` are attempted
         and both must raise. Without this the whole test would pass identically if `monkeypatch`
         had done nothing, which is the failure mode a poisoning test has.
      3. **Every command completes.** `main.main` returns AGL's exit status out of the one table
         in `src/agl/ports/errors.py`, so zero is the whole claim - the real parser, the real
         dispatch, the real handler, and a status a script would branch on.

    **Substituted through `main`'s own seam and nothing is monkeypatched to get there.** `compose=`
    is the parameter `cli/main.py` declares for exactly this, so the bundle is `container.fakes()`,
    the entry points are this module's own, and `ask` is the canned answer `agl init` asks for.
    Nothing here reaches into a module's internals; the only patching in this test is the poison,
    which is the assertion rather than the arrangement.

    **`agl init` needs a git *root*, not git.** It walks up for a `.git` entry - a filesystem read,
    no subprocess - so a directory with an empty `.git` inside it is a repository as far as `init`
    is concerned, and the poison stays closed throughout. That is worth knowing rather than
    hiding: "no git" in target #8 means no git process, and `init` never wanted one.
    """
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "myapp"
    (repo / ".git").mkdir(parents=True)
    settings = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home)})
    fakes = container.fakes(
        TreesRoot(tmp_path / "trees"), files={"src/a.py": b"pass\n"}, agent=_eight_agent
    )

    def answer(question: str) -> str:
        return "pytest -q"

    def compose() -> main.Invocation:
        return main.Invocation(
            registered=lambda: (ProjectName(repo.name), fakes.services),
            settings=settings,
            cwd=repo,
            points=(_EIGHT_POINT,),
            ask=answer,
        )

    driven = {name for name, _ in _INVOCATIONS}
    declared = _declared_commands()
    assert driven == declared, (
        f"the parser declares {sorted(declared)} and this test drives {sorted(driven)}. Target #8 "
        f"is that *every* command runs end-to-end on fakes alone - a command declared without a "
        f"row here is a command nobody has run without a network, and a row here for a command "
        f"the parser does not declare is a test of a grammar AGL no longer has."
    )

    _poison(monkeypatch)
    with pytest.raises(_WentOutside):
        subprocess.run(["true"], check=False)
    with pytest.raises(_WentOutside):
        socket.create_connection(("127.0.0.1", 1))

    statuses = {name: main.main(argv, compose=compose) for name, argv in _INVOCATIONS}

    assert statuses == dict.fromkeys(driven, 0), (
        f"the commands answered {statuses}. Target #8 is that every one of them runs end-to-end on "
        f"fakes alone: anything but 0 is a command that did not finish, and it finished under a "
        f"poisoned `subprocess` and a poisoned `socket`, so it finished without leaving the "
        f"process."
    )

# ================================================================================================
# Target 9 - three runs, one repo, concurrently
# ================================================================================================
#
# **Cited, not re-implemented.** `tests/test_concurrent_runs.py::
# test_three_runs_on_one_repository_overlap_and_leave_three_independent_branches` is that whole
# claim: two `split` runs and one `fix`, different base refs, overlapping in time, and three
# independent local branches at the end. A copy made here would be the same test with less of the
# apparatus that proves the runs actually overlapped, which is the hard half of that claim.

# ================================================================================================
# Target 10 - kill-and-resume is a property test
# ================================================================================================
#
# **Cited, and the citation is stronger than the target.** It asks for "run any workflow to
# completion, kill at every step boundary, resume, assert identical final state".
# `tests/sdk/test_kill_and_resume.py` does that with a **real** kill - `os._exit(0)` in a second
# process, so no `finally` and no `atexit` runs - sweeps every step boundary, and compares every
# entry path, every fingerprint, every value, every head, every branch tip and the user's own HEAD
# against a run that was never interrupted. The one field excluded is `at`, for a stated reason, and
# it is still examined rather than dropped.
#
# Two tests are cited rather than one, because the second is what makes the first mean something: it
# asserts that the killed process left neither end-of-process marker and that the process allowed to
# finish left both. That is the difference between a kill and an unwind, measured rather than
# claimed - and without it a "kill" that was really an exception would sweep every boundary and
# pass.

# ================================================================================================
# Target 11 - renaming every namespace and step name changes only that workflow
# ================================================================================================
#
# **The sharp form of this claim, and where it stops.** `sdk/_engine/journal.py::base_of` hashes
# instructions, model, restrictions, tools, inputs and head - **no step name and no namespace** -
# and `Fingerprints.digest` is `sha256(base + ":" + n)`, where `n` is a per-`(scope, step, base)`
# count and not a term. So the target's vague "the framework behaves identically" has an exact
# version: rename every namespace and every step name and **every fingerprint is byte-identical**,
# with only paths and branch names changing. That is what the first test below asserts, and it
# holds.
#
# **And here is the finding.** It holds *up to the first `integrate()`* and not past it. A landing
# records a merge commit carrying git's own message - `Merge branch '<source>' into <target>` - and
# the source branch is `agl/_work/<label>/<namespace>`. So the namespace is written into the
# repository's history; the commit id depends on it (in the fake, which hashes tree, parents and
# message; and in real git, whose commit object contains the message); and `head` **is** a
# fingerprint term, deliberately, and `ARCHITECTURE.md`'s "Invariants where a mistake is silent" is
# where that is stated - a `review` step takes no inputs, so without `head` a re-run of `implement`
# would leave review's fingerprint unchanged. Chain those and a namespace rename moves every
# fingerprint taken after a landing.
#
# This is reported rather than accommodated. The second test below asserts the mechanism directly -
# that the namespace really is inside the run branch's tip message - so the boundary is a measured
# fact in this file rather than a caveat in a paragraph. What would have to change for the target to
# hold in full is a decision about `head`, not a decision about names: either the merge message
# stops naming the branch (which departs from git's own wording, deliberately kept), or `head`
# stops being fingerprinted (which that invariant argues against). Neither is this deliverable's to
# take, and softening the assertion to "fingerprints match unless something landed" would have
# hidden the choice.
#
# **Why `split` is not the vehicle.** `split`'s namespaces come from `chunk.id`, so renaming
# `T-01` to `banana` is a scripted-agent change with no source edit - but that same `chunk` goes
# into the implement step as `chunk=chunk`, and inputs *are* fingerprint terms by design. Renaming a
# chunk id there moves a digest because an **input** moved, which says nothing about namespaces. The
# workflow below is declared twice instead, so the rename is of names and of nothing else.

@dataclass(frozen=True)
class _RenameParams:
    """One flag, identical in both declarations, so that no input differs between the two runs."""

    request: str = arg("-r", "--request", help="what to do")

_RENAME_PROMPT: Final = "do the work"

@role(model=Claude.SONNET)
def _renamed(name: str) -> Role[None]:
    """One role under whichever name it is asked for, and identical in every term a fingerprint
    takes.

    A step is recorded under `role.name` and the call carries none of its own, so "rename a step"
    is "declare the same role under another name" - which is what this makes cheap. `name` is
    deliberately no term of `base_of`, and that is the whole of what the test below measures. The
    model is on the decorator and therefore *cannot* differ between the two sets below, which is
    the other half of what makes them comparable.
    """
    return Role(name=name, instructions=_RENAME_PROMPT)

_RENAME_REQUEST: Final = "the same request, twice"

_FIRST_STEPS: Final = (_renamed("alpha"), _renamed("beta"), _renamed("gamma"))
_SECOND_STEPS: Final = (_renamed("banana"), _renamed("coconut"), _renamed("durian"))
_FIRST_SPACES: Final = ("one", "two")
_SECOND_SPACES: Final = ("three", "four")

async def _renameable(
    run: Run[_RenameParams],
    *,
    steps: tuple[Role[None], Role[None], Role[None]],
    spaces: tuple[str, str],
) -> None:
    """One programme, spelled once, parametrised by the names that are meant not to matter.

    Two worktrees and three roles alike but for their names, and **nothing derived from either**:
    the inputs are plain integers, so no name reaches a fingerprint through the one door that is
    open. That is what makes the comparison a rename rather than a change of inputs wearing one.

    No `commit=` and no `integrate()`, which is not an omission: this is the half of the target that
    holds, and the half that does not is measured by its own test below rather than by making this
    one quieter.
    """
    await run.step(steps[0], order=1)
    for index, space in enumerate(spaces):
        await run.worktree(space).step(steps[1], order=10 + index)
    await run.step(steps[2], order=99)

@workflow(version="1")
async def named_one(run: Run[_RenameParams]) -> None:
    """The workflow under one set of names."""
    await _renameable(run, steps=_FIRST_STEPS, spaces=_FIRST_SPACES)

@workflow(version="1")
async def named_two(run: Run[_RenameParams]) -> None:
    """The same workflow under a different name for every namespace and every step."""
    await _renameable(run, steps=_SECOND_STEPS, spaces=_SECOND_SPACES)

async def _landing(run: Run[_RenameParams], *, space: str) -> None:
    """One child worktree, one committing step, one landing, then one step on the parent.

    The smallest programme that crosses the boundary the finding is about: something has to land
    before the namespace can be written into the parent's history, and something has to run after
    the landing for a fingerprint to be taken over the head that landing produced.
    """
    child = run.worktree(space)
    await child.step(_renamed("work"), order=1, commit="land the work")
    outcome = await child.integrate()
    assert not outcome.conflicted
    await run.step(_renamed("work"), order=2)

@workflow(version="1")
async def landing_one(run: Run[_RenameParams]) -> None:
    """The landing programme under one namespace."""
    await _landing(run, space="one")

@workflow(version="1")
async def landing_two(run: Run[_RenameParams]) -> None:
    """The landing programme under a different namespace, and nothing else different."""
    await _landing(run, space="three")

def _writing_agent(task: AgentTask) -> Reply:
    """An agent that leaves a file behind, so `commit=` records something and a landing carries it.

    A `Reply` touches no worktree, and `commit_all` on a clean one records the head it started from
    - so an agent that only speaks makes the three ways of writing a `commit=` indistinguishable.
    The content is fixed, so two runs of the same programme commit the same tree.
    """
    (task.workspace / "left-behind.py").write_bytes(b"the agent's own work\n")
    return Reply(says="done")

async def _ledger(
    where: Path, wf: Workflow[_RenameParams]
) -> dict[str, Mapping[str, object]]:
    """Run `wf` on its own fakes bundle over a real on-disk ledger, and read back what it wrote.

    A `FilesystemStore` rather than the bundle's in-memory one, and that substitution is the whole
    instrument: the store's addresses *are* directories, so the path of every entry carries the
    namespace and the step name it was filed under, and the file it names carries the fingerprint.
    Comparing two of these compares paths and digests at once, which is exactly the pair the target
    separates - "only paths and branch names change".

    Substituted through `FakeServices.with_store`, which `agl/testing.py` itself uses, so both views
    of the bundle name the same store and the harness wraps the one the run wrote to.
    """
    where.mkdir(parents=True, exist_ok=True)
    home = AglHome(where / "home")
    fakes = container.fakes(
        TreesRoot(where / "trees"), files={"src/a.py": b"pass\n"}, agent=_writing_agent
    )
    harness = testing.over(fakes.with_store(FilesystemStore(home)))
    await harness.run(wf, "-r", _RENAME_REQUEST)
    return {
        str(path.relative_to(home.path)): json.loads(path.read_text())
        for path in sorted(home.path.rglob("*.json"))
        if path.name != "run.json"
    }

def _fingerprints(entries: Mapping[str, Mapping[str, object]]) -> list[str]:
    """Every entry's fingerprint, sorted - the ledger with its paths taken away."""
    return sorted(str(entry["fingerprint"]) for entry in entries.values())

@pytest.mark.asyncio
async def test_renaming_every_name_moves_no_fingerprint_at_all(tmp_path: Path) -> None:
    """#11 in its sharp form: rename everything nameable and every digest is byte-identical.

    One workflow, declared twice with three differently-named roles and two different namespace
    names and nothing else different - same prompt, same model, same inputs, same seeded
    repository. A step's name is its role's, so renaming one *is* declaring the role under another
    name, and `Role.name` is deliberately no term of `base_of`. Both are run on their own bundle
    over their own on-disk ledger, and then three things are asserted:

      * **The fingerprints are equal as multisets.** Not "the same number of entries", not "the same
        values" - the same digests, byte for byte. `base_of` hashes no name, and `digest` is
        `sha256(base + ":" + n)` where `n` is a count keyed by a scope and a step but is not itself
        a term, so a rename must move nothing. This is the assertion the target reduces to.
      * **The paths are not equal.** Otherwise the rename did not happen and the first assertion is
        a comparison of a thing with itself. The entry addresses carry the namespace and the step
        name, so two ledgers with identical paths are two runs of the same names.
      * **The branches differ too**, which is the other half of "only paths and branch names
        change": each namespace gets `agl/_work/<label>/<namespace>`, and both sets exist in their
        own repository afterwards.

    A rename that moved a digest would mean something is keying on a name, and this file would be
    the place that said so.
    """
    first = await _ledger(tmp_path / "first", named_one)
    second = await _ledger(tmp_path / "second", named_two)

    assert len(first) == 4, (
        f"the first run wrote {len(first)} entries and the programme takes four steps, so the two "
        f"ledgers being compared below are not the ledgers of the programme this test declares."
    )
    assert set(first) != set(second), (
        f"both runs filed their entries at the same addresses, so nothing was renamed and the "
        f"comparison below is a value against itself. Paths: {sorted(first)}"
    )
    assert _fingerprints(first) == _fingerprints(second), (
        f"renaming every namespace and every step name moved a fingerprint. Target #11 is that "
        f"such a rename changes only that workflow, and `base_of` hashes instructions, "
        f"model, restrictions, tools, inputs and head - no name of any kind. A digest that moved "
        f"means something is keying on a name, and every run recorded under the old names will "
        f"miss and pay an agent again.\n"
        f"  first:  {_fingerprints(first)}\n"
        f"  second: {_fingerprints(second)}"
    )

@pytest.mark.asyncio
async def test_a_landing_writes_the_namespace_into_the_history(tmp_path: Path) -> None:
    """The finding, asserted rather than written up: past `integrate()`, a namespace *is* a term.

    The mechanism, in one chain: `integrate()` records a merge commit whose message is git's own -
    `Merge branch '<source>' into <target>` - the source branch is
    `agl/_work/<label>/<namespace>`, a commit's identity covers its message, and `head` is a
    fingerprint term by deliberate choice. So the namespace reaches the digest of every step
    taken after a landing, by a route that has nothing to do with the journal hashing a name.

    Two assertions and the first is the explanation of the second:

      * **The run branch's tip names the namespace.** Read through the `History` port - `resolve`
        then `message` - so this is a fact about what a landing writes and not about a fake's
        internals. Real git writes the same sentence and `--no-edit` accepts it.
      * **The two runs' fingerprints differ.** The same programme, the same inputs, one namespace
        renamed, and the ledgers no longer match. This is the boundary of the test above, measured.

    **This test is the finding and not the target.** If a later deliverable decides that the merge
    message should not name the branch, or that `head` should be spelled some other way, this test
    fails - and that failure is the repair being noticed, at which point the assertion above it
    should be widened to cover a landing and this one deleted. It is written to be deleted.
    """
    first = await _ledger(tmp_path / "first", landing_one)
    second = await _ledger(tmp_path / "second", landing_two)

    fakes = container.fakes(
        TreesRoot(tmp_path / "third" / "trees"), files={"src/a.py": b"pass\n"}, agent=_writing_agent
    )
    harness = testing.over(fakes)
    await harness.run(landing_one, "-r", _RENAME_REQUEST)
    history = harness.fakes.services.history
    tip = await history.resolve(run_branch(harness.scope.label))
    message = await history.message(tip)
    branch = worktree_branch(harness.scope.label, Namespace("one"))

    assert branch in message, (
        f"the run branch's tip says {message!r} and does not name {branch!r}. This test exists to "
        f"record *why* a namespace reaches a fingerprint past a landing; if the merge message no "
        f"longer carries the branch, that route is closed and the assertion below should be a "
        f"widening of test_renaming_every_name_moves_no_fingerprint_at_all rather than a test of "
        f"its own."
    )
    assert _fingerprints(first) != _fingerprints(second), (
        "a namespace rename across a landing left every fingerprint identical, which is target "
        "#11 holding further than this file recorded. That is a repair, not a failure: fold this "
        "programme into test_renaming_every_name_moves_no_fingerprint_at_all and delete this "
        "test, and amend the section header above it - the finding it describes is gone."
    )

# ================================================================================================
# Target 12 - tickets (v1.2) requires no framework change
# ================================================================================================

def test_target_twelve_is_unverifiable_because_tickets_does_not_exist() -> None:
    """#12 cannot be verified today, and nothing here stands in for it.

    The twelfth target is "**Tickets (v1.2) requires no framework change.** If it does, the
    framework was wrong", and tickets was called "a genuine test of R1". This is v1.1. Tickets is
    deferred in full - the backlog and its cycle detection, the ready-set loop, the halt policy, the
    triage roles, the findings model and the board - so there is nothing to measure and no
    measurement is made.

    **What this test asserts is only that the premise still holds**: no `tickets` package, no
    `tickets` entry point. It is a tripwire, not evidence. The day tickets arrives, this fails, and
    what it asks for is the measurement rather than a green line - take the diff, and report whether
    anything under `src/agl/sdk/`, `src/agl/config/`, `src/agl/cli/`, `src/agl/api.py` or
    `src/agl/ports/` had to move.

    **The strongest available evidence, and why it is not a substitute.** `fix` and `split` are two
    consumers of genuinely different shape - one worktree and sequential steps against N concurrent
    children each integrated - and they required no framework change between them; that was
    recorded as its own measurement when `split` was built, and targets #1 and #3 above assert the
    structural half of it today. That is evidence the framework generalises across two shapes. It
    is not evidence about a third that does not exist, and the difference matters exactly where
    tickets differs from both: a workflow-owned scheduler with retries, dynamic work addition and a
    halt policy asks the SDK questions neither of these two has asked. Anyone reading this in v1.2
    should treat #12 as open until they have taken the diff.
    """
    packages = {
        path.name
        for path in WORKFLOWS_DIR.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }
    registered = set(_entry_points())

    assert "tickets" not in packages | registered, (
        f"tickets now exists (packages: {sorted(packages)}, registered: {sorted(registered)}), so "
        f"target #12 is measurable for the first time and is still unmeasured. Take the diff that "
        f"added it and report whether anything under src/agl/sdk/, src/agl/config/, src/agl/cli/, "
        f"src/agl/api.py or src/agl/ports/ had to change. If any of it did, the target's own "
        f"answer applies: the framework was wrong. Then replace this test with that measurement - "
        f"it was "
        f"written to be deleted by whoever adds tickets."
    )

# ================================================================================================
# The index itself - twelve targets, and every citation resolved against the real file
# ================================================================================================

def _test_names(path: Path) -> set[str]:
    """Every test function `path` declares, at module level or on a class."""
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }

def test_all_twelve_targets_are_accounted_for() -> None:
    """There are twelve targets and this file answers for all twelve, by number.

    The index is the deliverable as much as the assertions are: a reader should be able to open one
    file and see where each of the twelve is settled. A missing number would be a target nobody
    answered for, which is the state this file exists to end.
    """
    assert sorted(SETTLED) == list(range(1, 13)), (
        f"`SETTLED` answers for targets {sorted(SETTLED)}. There are twelve, numbered 1 to 12, "
        f"and a number missing here is a target this file does not account for."
    )
    empty = [number for number, where in SETTLED.items() if not where]
    assert not empty, (
        f"targets {empty} are listed with nothing settling them. A number with an empty tuple is a "
        f"target recorded as answered and not answered - worse than one left out, because it reads "
        f"as covered."
    )

@pytest.mark.parametrize(
    "citation", sorted({one for where in SETTLED.values() for one in where})
)
def test_every_settlement_names_a_test_that_exists(citation: str) -> None:
    """Every `path::name` in the index resolves to a real test in a real file.

    Without this the index is prose, and prose rots: a test renamed three stages from now leaves a
    target pointing at nothing and the file still says all twelve are settled. Resolved by parsing
    the cited file rather than by importing it, so a citation into a module with an expensive import
    costs nothing and a citation into a module that will not import fails as a bad citation rather
    than as a collection error.
    """
    path_text, _, name = citation.partition("::")
    path = REPO_ROOT / path_text

    assert path.is_file(), (
        f"the index cites {citation}, and {path} does not exist. Every target in `SETTLED` has to "
        f"name a test somebody can open."
    )
    assert name, f"the index cites {citation} with no test name after `::`."
    assert name in _test_names(path), (
        f"the index cites {citation} and {path_text} declares no test called {name!r}. A renamed "
        f"test leaves a target pointing at nothing while this file still reports it settled."
    )
