"""The twelve measurable targets, one assertion each, and the three that no longer have one.

The twelve were written before the build started and are the project's own definition of done, and
this file is now where they are recorded, and where each of them is settled or recorded as not.
Six are asserted here (#1, #3, #5, #6, #7, #8), one is cited to a test that asserts it better than
a copy would (#10), one is asserted here in its sharpest form and **fails past a boundary this file
records rather than hides** (#11), and one cannot be asserted at all today and says so in as many
words (#12). **Three are settled by nothing** (#2, #4, #9), and `UNSETTLED` is where each says why.

**The governing rule this module was written under.** A target that cannot be asserted mechanically
is a finding. No target below is softened to make it pass and no proxy is asserted for one. Where a
target's own words could not be reached, what is written here is the reason and what would have to
change - the code or the target - and not a neighbouring claim dressed up as the target.

That rule has teeth in four places, and they are the four worth reading first:

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
    exist, so the claim is unverifiable today. Nothing here stands in for it; the two tests below
    assert only that tickets is absent from this tree and that no project file in this repository
    declares a workflow at all, and both say in their own words that the operator's own workspace
    - the one place a workflow now comes from - is a place no test here may look.
  * **#2, #4 and #9 settle to nothing**, and that is the rule's hardest case rather than an
    exception to it. All three were measured against the workflows AGL used to ship, and when those
    were deleted every one of those measurements became either impossible or vacuous - a walk over
    a directory that is not there answers `{}` and passes. Keeping any of them would have been a
    green line standing in for a target, which is the one thing this file exists not to do. So the
    settlements went and `UNSETTLED` took their place, saying for each whether the *capability* went
    with the workflow or is still there waiting to be measured again.

## How to read this file

`SETTLED` is the index: target number to the tests that settle it, each spelled `path::name`. Every
one of those is resolved against the real file by `test_every_settlement_names_a_test_that_exists`,
so a citation that rots fails a test rather than quietly becoming prose. `UNSETTLED` is the other
half of the index, keyed by the same numbers: a target may settle to nothing **only** if it is
written up there, which is what
`test_every_one_of_the_twelve_targets_carries_a_settlement_or_a_stated_reason` holds. Three targets
cite a test written elsewhere - #1 and #3 alongside assertions of their own, #10 instead of one -
and each of those citations is re-run rather than re-implemented. #10 could not be improved on here:
re-writing it would have been a second copy of a claim that is already made better, with more
apparatus behind it, where it lives.

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

699 code lines against `scripts/check`'s 300-line convention, which is among the largest of the 35
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
rather than the expression that failed. 142 of those 699 lines are assertion messages, which is this
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
from collections.abc import Iterator, Mapping
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
CONTRACTS_DIR: Final = REPO_ROOT / "tests" / "contracts"
PYPROJECT_FILE: Final = REPO_ROOT / "pyproject.toml"
IMPORTLINTER_FILE: Final = REPO_ROOT / ".importlinter"
CHECK_SCRIPT: Final = REPO_ROOT / "scripts" / "check"

# The entry-point group, which outlives every workflow that was ever registered into it: it is what
# `config/registry.py` scans, and the name is spelled here for the two assertions that read it.
WORKFLOWS_PACKAGE: Final = "agl.workflows"
ADAPTERS_PACKAGE: Final = "agl.adapters"
CONTAINER_MODULE: Final = "agl/config/container.py"
REGISTRY_MODULE: Final = PACKAGE_DIR / "config" / "registry.py"

# Where each of the twelve is settled, spelled `path::name` so that a reader can go straight to the
# assertion and so that `test_every_settlement_names_a_test_that_exists` can resolve every one of
# them against the real file. Five targets cite a test written elsewhere rather than a copy of it
# made here, and each of those citations says in its own section why re-writing it would have been
# worse. Nothing is listed twice: a target settled here is settled here.
HERE: Final = "tests/test_measurable_targets.py"
CONTRACT_FIRING: Final = "tests/test_contract_firing.py"

SETTLED: Final[Mapping[int, tuple[str, ...]]] = {
    1: (
        f"{HERE}::test_the_registry_dispatches_through_no_name_it_was_handed",
        "tests/config/test_registry.py::"
        "test_a_workspace_directory_declaring_one_workflow_yields_that_one_entry_point",
    ),
    2: (),
    3: (
        f"{HERE}::test_only_the_composition_root_names_an_adapter",
        f"{HERE}::test_there_is_one_config_section_per_agent_backend",
        "tests/config/test_schema.py::test_there_is_one_agent_section_per_provider_member",
    ),
    4: (),
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
    9: (),
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
    12: (
        f"{HERE}::test_target_twelve_is_unverifiable_because_tickets_does_not_exist",
        f"{HERE}::"
        f"test_a_workflow_declaration_is_found_where_one_is_planted_and_nowhere_in_this_repository",
    ),
}

# Why a target above settles to nothing. A number may carry an empty tuple **only** if it is keyed
# here, which is what keeps "unsettled" a thing somebody wrote down rather than a tuple that got
# emptied. Every reason below is the same event - AGL stopped shipping `fix` and `split`, so the
# tests that measured these three went with the workflows they measured - and each says whether the
# capability went with them, because that is the difference between a target to resettle and a
# target to withdraw.
UNSETTLED: Final[Mapping[int, str]] = {
    2: (
        "`fix` is ~8 lines, `split` is ~30. The two workflows this counted are deleted, and with "
        "them the counting method, its recorded decomposition and the frozen `fix` it was "
        "calibrated against. Nothing measures a workflow's size today because the distribution "
        "holds no workflow to measure. The framework half of the claim - that a workflow gets "
        "replay, a worktree, preflight and exit codes without asking - is untouched and is what a "
        "later stage would re-measure, against whatever the first workspace workflow turns out to "
        "be."
    ),
    4: (
        "One run addresses two providers. Was settled by a since-deleted `tests/workflows/"
        "test_fix.py`, which drove "
        "the shipped `fix` - Claude implementing, OpenAI reviewing - and read the models off the "
        "tasks one run produced. **The capability is intact**: `adapters/routing.py` still "
        "dispatches on `task.model.provider`, `tests/adapters/test_routing.py` still asserts it, "
        "and `sdk/_engine/preflight.py` still ranks two providers' probes. What was deleted is the "
        "workflow that demonstrated the two together end to end, so this is a target to resettle "
        "against a two-provider workflow rather than one to withdraw."
    ),
    9: (
        "Three runs, one repository, concurrently. Was settled by a since-deleted "
        "`tests/test_concurrent_runs.py`, "
        "which ran two `split`s and one `fix` over one real repository and asserted three "
        "independent branches. **The capability is intact**: the `flock` in "
        "`adapters/git/_trees.py` is what makes it safe, `tests/adapters/test_git_workspace.py` "
        "provokes it from a second process, and `tests/sdk/test_concurrent_namespaces.py` holds "
        "the rendezvous argument one layer down. What was deleted is the only test that took the "
        "claim at the level the target words it - whole runs, not namespaces - so this too is a "
        "target to resettle."
    ),
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

    **Each node is asked what it is, rather than each node's `body`, `orelse` and `finalbody` being
    read.** Those three names do not always hold a list: an `ast.IfExp` and an `ast.Lambda` carry a
    single expression under them, so a reader that iterated whatever it found there raised
    `TypeError: 'Name' object is not iterable` on one ternary anywhere in the module being parsed -
    an error in place of the assertion the caller was written to make. `_nested` in
    `src/agl/config/registry.py` is written as a ternary so that this stays fixed.

    A docstring is an `ast.Expr` over a string constant, and this repository writes attribute
    docstrings too - a bare string after a dataclass field, which `ast.get_docstring` cannot see -
    so both are dropped by shape rather than by position. What is left is what the module *does*.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and not _is_docstring(node):
            yield node

def _is_docstring(statement: ast.stmt) -> bool:
    """Whether `statement` is a bare string expression - a docstring of either kind."""
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )

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
#
# **Two of this target's three assertions went with the shipped workflows, and one of the two has
# since been asked again elsewhere.** Both of the deleted ones were about a tree: that nothing
# outside `src/agl/workflows/` imported a workflow, and that every package under it was one
# entry-point line in `pyproject.toml`. Neither could be asked of a distribution that ships no
# workflow - `rglob` over a directory that is not there answers `[]` and both would have passed on
# the empty set, which is a green line and not a measurement.
#
# **The entry-point half has a workspace form and is cited rather than copied.** "One new package
# plus one entry-point line" is now one directory in the operator's workspace holding one
# declaration in its own project file, and `tests/config/test_registry.py`'s
# `test_a_workspace_directory_declaring_one_workflow_yields_that_one_entry_point` is that sentence
# asserted against the walk `agl` actually does. `SETTLED` carries it; re-writing it here would be a
# second copy of a claim already made where the apparatus for it lives, which is #10's argument
# applied to a nearer case. The other half has no workspace form: it was about a tree that no longer
# exists, and a workflow the test wrote into `tmp_path` itself would be a tautology rather than a
# measurement.
#
# What survives here is the half that was never about the tree: the resolver. Target #1's own words
# are "no `importlib`, no `getattr`, no central dispatch to edit", and that is a claim about
# `config/registry.py`, which now reads a workflow's own declaration and synthesises an entry point
# from it rather than asking the installed distributions for one. A workflow reaches the framework
# through that walk and through nothing else, and the assertion below is what holds the resolver to
# it.

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

# ================================================================================================
# Target 2 - `fix` is ~8 lines, `split` is ~30
# ================================================================================================
#
# **Nothing here measures it, and `UNSETTLED` at the top of this file is where that is recorded.**
# The counting method, the decomposition it reproduced and the frozen `fix` it was calibrated
# against all went with the two workflows they were about; a counter with nothing to count is not a
# measurement, and keeping one that scored a string held in this module would have been the proxy
# this file's governing rule refuses.

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

# **#3's third clause - that adding a backend changes no workflow - is no longer asserted here.** It
# was asserted by walking `src/agl/workflows/` for an import of `agl.adapters` or `agl.config`.
# That walk answers `{}` against a tree with no workflows in it, which is a green line rather than a
# measurement, so it went with them. The clause itself is not in doubt and is not unmeasured: a
# workflow now arrives from outside this distribution entirely, so what would have to hold is that
# the SDK a workflow is written against never obliges it to name an adapter - which is the two
# assertions above, plus `.importlinter` contract 5 refusing every `agl.* -> agl.adapters` that is
# not the composition root.

# ================================================================================================
# Target 4 - one run addresses two providers
# ================================================================================================
#
# **Unsettled, and `UNSETTLED` at the top of this file carries the reason.** This was cited rather
# than re-implemented, to a test that drove the shipped `fix` end to end - Claude implementing,
# OpenAI reviewing - and read the models off the tasks one run produced, so "two providers" was a
# fact about the dispatch rather than about a role declaration. That workflow is gone and the
# citation with it.
#
# **What a resettlement would have to do, so nobody re-derives it.** Preflight passing leaves
# nothing behind - its checks run before the record is written, so a finished run is the only
# evidence it passed and there is no artefact to assert on. The deleted test worked around that by
# asking both readiness questions again, explicitly, of the same runner the run had used, and said
# in its own docstring that this was a workaround for an invisible half rather than a second
# measurement of it. Any replacement needs the same two halves and the same admission.

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
    `tests/test_contract_firing.py` - the rich terminal's adapter importing the Claude SDK, one
    vendor's adapter reaching for the other vendor's SDK - so that citation is the firing half and
    this is the existence half. Both SDKs being unconditional dependencies is what makes that the
    whole guard: the SDK is installed in every environment there is, so the import the contract
    refuses is one that would otherwise succeed.

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
        f"vendor SDK is contained by nothing at all, and any module in the tree may import it - "
        f"an SDK `pyproject.toml` installs unconditionally, so the import would simply work."
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

    declared = tomllib.loads(PYPROJECT_FILE.read_text())["project"]["dependencies"]
    from_openai = [
        requirement for requirement in declared if requirement.lower().startswith("openai")
    ]
    assert not from_openai, (
        f"`pyproject.toml` declares {from_openai} in [project] dependencies, and every entry there "
        f"is installed with AGL unconditionally. The whole reason target #5 needs two instruments "
        f"rather than one is that the OpenAI adapter has no Python dependency to contain - it "
        f"shells out to a binary, which is why its instrument is a grep over a directory and not a "
        f"contract over an import. A distribution here means there is now an import to contain, "
        f"and contract 3 is where it goes."
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
# dangle; `pyproject.toml`'s dependency list is outside `src/` and outside this pass. What the pass
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

    Module-level, because `agl.testing` resolves a workflow the way a workspace declaration is -
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
    ("clear", ("clear", "auth")),
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
# **Unsettled, and `UNSETTLED` at the top of this file carries the reason.** This was cited rather
# than re-implemented, to a test that ran two `split`s and one `fix` over one real repository from
# different base refs and found three independent local branches at the end. Both workflows are
# gone and that test with them.
#
# **What a resettlement would have to do, so nobody re-derives it.** Three runs that finish and
# leave three ledgers prove nothing, because a framework that ran them strictly in order leaves
# exactly that. The only arrangement that separates the two is one where **none can finish until
# all of them have started** - a barrier reached from inside each run's agent, with every await
# bounded so that the failure is an expiry rather than a hang. That is the apparatus, and it is the
# hard half of the claim rather than the assertion at the end of it.
# `tests/sdk/test_concurrent_namespaces.py` holds the same argument one layer down, over namespaces
# inside one run, and is the nearest thing to a model for it.

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

    **What this test asserts is only that the premise still holds**: this distribution ships no
    workflow named `tickets`, and no workflow at all. It is a tripwire, not evidence. The day
    tickets arrives here, this fails, and what it asks for is the measurement rather than a green
    line - take the diff, and report whether anything under `src/agl/sdk/`, `src/agl/config/`,
    `src/agl/cli/`, `src/agl/api.py` or `src/agl/ports/` had to move.

    **This tripwire watches `src/` and a workflow no longer arrives there.** A workflow is a
    directory in the operator's own workspace now, outside this tree entirely, so tickets could be
    written, run and finished without this test ever firing. That is stated rather than papered
    over: the premise it guards is "this *distribution* has not grown a workflow", which is worth
    holding on its own, and the second tripwire below -
    `test_a_workflow_declaration_is_found_where_one_is_planted_and_nowhere_in_this_repository` - is
    pointed at the shape a workflow has now rather than at this tree, and writes out the limit both
    of them share. Reading a green line here as "tickets does not exist anywhere" is the mistake
    this paragraph exists to stop.

    **The strongest available evidence, and why it is not a substitute.** `fix` and `split` were two
    consumers of genuinely different shape - one worktree and sequential steps against N concurrent
    children each integrated - and they required no framework change between them; that was
    recorded as its own measurement when `split` was built. That is evidence the framework
    generalises across two shapes. It is not evidence about a third that does not exist, and the
    difference matters exactly where tickets differs from both: a workflow-owned scheduler with
    retries, dynamic work addition and a halt policy asks the SDK questions neither of those two
    ever asked. Anyone reading this in v1.2 should treat #12 as open until they have taken the diff.
    """
    packages = sorted(
        path.name
        for path in PACKAGE_DIR.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    groups = tomllib.loads(PYPROJECT_FILE.read_text())["project"].get("entry-points", {})
    registered = sorted(groups.get(WORKFLOWS_PACKAGE, {}))

    assert "tickets" not in set(packages) | set(registered), (
        f"tickets now exists (packages under src/agl/: {packages}, registered in the "
        f"{WORKFLOWS_PACKAGE} group: {registered}), so target #12 is measurable for the first time "
        f"and is still unmeasured. Take the diff that added it and report whether anything under "
        f"src/agl/sdk/, src/agl/config/, src/agl/cli/, src/agl/api.py or src/agl/ports/ had to "
        f"change. If any of it did, the target's own answer applies: the framework was wrong. Then "
        f"replace this test with that measurement - it was written to be deleted by whoever adds "
        f"tickets."
    )
    assert not registered, (
        f"the {WORKFLOWS_PACKAGE} group in pyproject.toml registers {registered}. AGL ships no "
        f"workflow, so this table is empty by design and a line in it is a workflow this "
        f"distribution has grown - which is the premise above changing, whatever the new workflow "
        f"is called."
    )

def _declarations(root: Path) -> dict[str, tuple[str, ...]]:
    """Every project file under `root`, and the workflow names each one declares.

    This is the reading `agl` itself does of a workspace directory: a workflow is a directory
    holding a `pyproject.toml` whose entry-point table declares it, which is `config/registry.py`'s
    `_declared`, so a declaration is what a tripwire can look for wherever one has been written.

    Keyed by the path relative to `root`, so a failure names a file to open, and a project file
    that declares nothing is kept with an empty tuple - which is what lets a caller tell "nothing
    here declares a workflow" from "no project file was read at all".

    Dot-prefixed directories are pruned rather than walked, and that is what keeps the answer about
    this repository: `.venv` holds other people's distributions, `.git` holds the history as
    objects, and the tool caches hold copies of what the walk has already read.
    """
    found: dict[str, tuple[str, ...]] = {}
    for parent, directories, _ in root.walk():
        directories[:] = [name for name in directories if not name.startswith(".")]
        path = parent / PYPROJECT_FILE.name
        if not path.is_file():
            continue
        groups = tomllib.loads(path.read_text()).get("project", {}).get("entry-points", {})
        found[str(path.relative_to(root))] = tuple(sorted(groups.get(WORKFLOWS_PACKAGE, {})))
    return found

def test_a_workflow_declaration_is_found_where_one_is_planted_and_nowhere_in_this_repository(
    tmp_path: Path,
) -> None:
    """#12's second tripwire, pointed at the shape a workflow has now rather than at `src/`.

    A workflow is no longer a package in this tree, so the scan above cannot see one arriving. What
    a workflow *is* now is a directory with a project file declaring it, and that shape is the same
    wherever the directory sits - so this looks for the declaration, over the whole repository.

    **The scan is shown firing before it is believed.** A `tickets` workflow is built under
    `tmp_path`, in the layout a workspace holds one in, and the same reader that answers about this
    repository is run over it and must find it by name. Without that half this would be a tripwire
    nobody has watched fire, which is the defect the test above records about itself and which a
    second one repeating it would only double.

    **What it catches.** Any workflow declared anywhere in this repository - a template, an
    example, a fixture, a workspace checked in beside the source - and `tickets` among them. That
    is strictly more than the package scan above, which a workflow arriving in any directory but
    `src/agl/` walks straight past.

    **What it does not catch, and this is the whole of the limit.** A `tickets` written in the
    operator's own workspace, which is where a workflow actually lives and where no test in this
    repository may look: `tests/conftest.py` pins `AGL_HOME` to a temporary directory precisely so
    that no test reads the machine it is running on. `config/registry.py` reads workflows from that
    workspace and from nowhere else, so the one place a workflow can arrive from is the one place
    this cannot see. A green line here means "nothing in this repository declares a workflow", and
    it means nothing whatever about the operator's workspace or about tickets existing in the
    world.

    It answers none of #12's own claim either. Whether tickets required a framework change is still
    settled by taking the diff, which is what the test above asks whoever adds it to do.
    """
    planted = tmp_path / "workspace" / "workflows" / "ticket-directory"
    planted.mkdir(parents=True)
    (planted / PYPROJECT_FILE.name).write_text(
        f'[project]\nname = "planted"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{WORKFLOWS_PACKAGE}"]\ntickets = "tickets:tickets"\n',
        encoding="utf-8",
    )

    assert list(_declarations(tmp_path).values()) == [("tickets",)], (
        f"the reader was shown a workspace holding one workflow called tickets and answered "
        f"{_declarations(tmp_path)}. It is asserted to fire here so that the assertion below means "
        f"something: a reader that found nothing in a tree with tickets in it would report this "
        f"repository clean whatever this repository held. The directory is deliberately not called "
        f"`tickets` either - a workflow's name is the key its declaration writes, not the name of "
        f"the directory holding it, and that is what is being read."
    )

    here = _declarations(REPO_ROOT)
    assert str(PYPROJECT_FILE.relative_to(REPO_ROOT)) in here, (
        f"the walk of {REPO_ROOT} read {sorted(here)} and AGL's own project file is not among "
        f"them, so the assertion below is about a tree this did not reach."
    )
    declaring = {path: declared for path, declared in here.items() if declared}
    assert not declaring, (
        f"project files in this repository declare workflows: {declaring}. Target #12's premise is "
        f"that tickets does not exist and that this distribution ships no workflow at all, so a "
        f"declaration here is that premise changing - and if `tickets` is among those names it is "
        f"changing in the exact way #12 is about. Take the diff that added it and report whether "
        f"anything under src/agl/sdk/, src/agl/config/, src/agl/cli/, src/agl/api.py or "
        f"src/agl/ports/ had to move; if any of it did, the target's own answer applies. A "
        f"template or an example workflow shipped deliberately is the other way this fires, and it "
        f"is a real change to the premise rather than a false alarm: decide what #12 means then, "
        f"and rewrite this rather than exempting the path."
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

def test_every_one_of_the_twelve_targets_carries_a_settlement_or_a_stated_reason() -> None:
    """There are twelve targets and this file answers for all twelve, by number.

    The index is the deliverable as much as the assertions are: a reader should be able to open one
    file and see, for each of the twelve, either where it is settled or why it is not. A missing
    number would be a target nobody answered for, which is the state this file exists to end.

    **An empty tuple used to be refused outright and now costs a reason instead**, which is the
    same rule under a case that arrived: three targets were settled by tests that measured the
    workflows AGL shipped, and when those were deleted the settlements went with them. The choice
    was between a number carrying nothing, a proxy assertion dressed up as the target - which this
    module's governing rule refuses - and a number carrying the reason it settles to nothing. The
    third is what `UNSETTLED` is, and this is the assertion that keeps it honest: an empty tuple is
    legal **only** where a reason is written down, so emptying one is still an edit somebody has to
    make in two places and defend in prose.
    """
    assert sorted(SETTLED) == list(range(1, 13)), (
        f"`SETTLED` answers for targets {sorted(SETTLED)}. There are twelve, numbered 1 to 12, "
        f"and a number missing here is a target this file does not account for. The numbering is "
        f"load-bearing beyond this file: tests/test_named_not_numbered.py exempts a target cited "
        f"by number only while `SETTLED` is keyed by a run from one, so a hole here turns every "
        f"`target #N` in the repository into a citation of nothing."
    )
    unexplained = sorted(
        number for number, where in SETTLED.items() if not where and number not in UNSETTLED
    )
    assert not unexplained, (
        f"targets {unexplained} settle to nothing and `UNSETTLED` says nothing about them. A "
        f"number with an empty tuple and no reason is a target recorded as answered and not "
        f"answered - worse than one left out, because it reads as covered."
    )
    stale = sorted(number for number, where in SETTLED.items() if where and number in UNSETTLED)
    assert not stale, (
        f"targets {stale} carry both a settlement and an entry in `UNSETTLED`. A target that has "
        f"been resettled keeps its reason only as prose nobody reads against anything - delete the "
        f"`UNSETTLED` entry when the settlement lands."
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
