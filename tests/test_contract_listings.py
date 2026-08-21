"""Structural test: four contracts in `.importlinter` are lists somebody typed, and this is what
notices when a list and the thing it is meant to police stop agreeing.

Two of the six contracts are fail-closed by construction. Contract 5's source is `agl.*`, which
re-expands as packages are added, and contract 6's is `agl.workflows`, which re-expands as
workflows are - so a module introduced at a later stage is covered the moment it exists, and its
author need do nothing to be policed. The other four cannot be written that way, and each fails
open in its own direction:

  * **Contract 1** (`layers`) names the top-level members of `agl` in dependency order. A member
    nobody adds to `layers =` is not at the bottom of the stack, it is *outside* it: the contract
    has no opinion about a module it does not mention, so the new package may import `agl.ports`
    and `agl.adapters` directly and be imported by anything, with all six contracts still kept.
  * **Contract 2** (`forbidden`) has *two* hand-maintained lists - `source_modules`, the pure
    types, and `forbidden_modules`, the ABCs - and a new `ports/` module is unpoliced whichever it
    belonged in. Absent from `source_modules` it may import any ABC there is; absent from
    `forbidden_modules` every pure type in the ring is free to import it.
  * **Contract 3** (`forbidden`) names the two vendor SDKs AGL has. A third is contained by nothing
    at all - not by this contract, which has never heard of it, and not by contract 5, which
    governs who may import `agl.adapters` and has no opinion about what an adapter imports from
    outside.
  * **Contract 4** (`independence`) takes an explicit list of siblings - there is no expression in
    import-linter meaning "every child of `agl.adapters`" - so an adapter added at a later stage is
    simply absent from it and free to import any other adapter.

**The silence is the defect, not the gap.** A broken contract fails the build and names the import
that broke it; a contract that never heard of your module agrees with everything you do. Stage 0
found this on contract 4 and deferred it to the first stage that adds an adapter; stage 5 found
that the other three have the same shape, and one guard now covers all four. Without it, later
stages would be written under rules that were not being applied to them, and the first sign of it
would have been two vendors quietly sharing a helper.

`scripts/check`'s package-root gate is the precedent: a rule `.importlinter` cannot express,
enforced beside it rather than wished into it. This is a test rather than a shell gate only because
what it compares - a parsed config against a walked tree - is easier to say in Python than in grep.

## The file is the source of truth and the world is the check

Nothing below hardcodes which layers, ports, vendors or adapters exist. Each listing is parsed out
of the real `.importlinter` and compared against the real thing it polices: `src/agl/` for
contracts 1, 2 and 4, and `pyproject.toml`'s `[project.optional-dependencies]` for contract 3,
which is where a vendor SDK actually gets added. A test carrying its own copy of any of those four
lists would be a *second* hand-maintained list, free to drift from the first, and its agreement
would mean only that one person updated both at once. Here the two things compared are the artefact
that does the policing and the world it is meant to police, so agreement is the property wanted.

## `__init__.py` is out of two comparisons, for two different reasons

Contract 1 exempts `src/agl/__init__.py` because that file is held to something **stricter**: the
layer stack orders imports, and `scripts/check`'s package-root gate forbids it every import
statement there is. Ordering nothing is the right rule for a file that imports nothing.

Contract 2 exempts `src/agl/ports/__init__.py`, and that exemption is **forced rather than
chosen**. import-linter skips any source/forbidden pair where one module is inside the other's
package (`_modules_overlap`, in its `forbidden` contract), and `agl.ports` contains every module on
both of contract 2's lists - so the package root in `source_modules` would be skipped against every
ABC, and in `forbidden_modules` skipped against every pure type. No entry there would police it,
and requiring one would be requiring a decoration. Stated plainly, because it is a real gap rather
than a covered one: `ports/__init__.py` could import an ABC and contract 2 could not say so. It is
one line of docstring today and nothing in this repo guards it - unlike `agl/__init__.py`, which
has a gate of its own. The same blind spot, one ring further in.

Directories have no exemption route at all, in any of the three tree comparisons: `EXEMPT` mappings
here are keyed by filename and hold only single-file members. They are mappings and not sets so
that the reason travels with the name and a later reader can weigh it instead of guessing at it.

## A distribution name is not an import name, and contract 3's half of this only guesses

Contract 3 forbids *import* names (`claude_agent_sdk`); `pyproject.toml` declares *distribution*
names (`claude-agent-sdk`). The rule below is the obvious one - lowercase, with `-` and `.` becoming
`_` - and it is right for both of today's extras and for most others. It is not a derivation and
cannot be: a distribution may install a top-level module under any name it likes, which is how
`pyyaml` becomes `yaml` and `pillow` becomes `PIL`. What the rule guarantees is *noticing* a third
SDK, not naming it correctly; when it guesses wrong the guard still fires, and
`VENDOR_IMPORT_NAMES` is where the true name goes. `NOT_A_VENDOR` is the other escape, for an extra
that is not a vendor SDK at all. Both start empty, and neither pre-authorises anything: an extra
added at a later stage trips this guard first and is argued about here second.

The extras table is the whole of what this reads, and that is the second limit. A vendor SDK put
into `[project] dependencies` or into a `[dependency-groups]` entry would not be seen here - the
first is empty by design, AGL's core being stdlib-only, and the second is dev tooling, so an SDK in
either is already a design change big enough to bring somebody back to this file. What is asserted
is that the table where vendor SDKs *do* go cannot gain one unnoticed.

The asymmetry with OpenAI is deliberate and is not a gap here (ARCHITECTURE.md §4): that adapter
wraps the Codex CLI binary and has no Python import to contain, so it has no extra to declare and
is guarded by `scripts/check`'s grep gate instead.

## Why each comparison is a function and not four lines inside a test

`layer_drift`, `port_drift`, `vendor_drift` and `adapter_drift` take sets and return complaints,
touching no disk, so the fabricated tests at the bottom can hand each one a listing and a world
that disagree in every way that matters and watch it say so. A structural test that reads a
repository and finds it consistent looks identical whether it is checking anything or not; those
tests are what tell the difference. Each real test additionally refuses to pass on an empty tree, a
missing section or a missing list, which is the failure mode of a mistyped path.

## One module, well past the ceiling

This file is roughly three times `scripts/check`'s 300-line convention, and two ways of splitting
it were considered and refused rather than overlooked.

Splitting **per contract** would make four guards out of one, and what makes this one guard is
precisely what the four would then have to share: one parse of `.importlinter`, one way of walking
a directory, one shape of complaint, and one discipline of proving the comparison non-vacuous. The
only seam that split could follow is the contract numbers, which are not a seam - they are four
instances of one defect.

Splitting **pure from impure** - the comparisons and their complaints in one module, the readers
and the tests in another - is the seam this file genuinely draws, and it still does not pay. Both
halves land over the ceiling anyway, since the bulk here is the complaint texts and the fabricated
cases rather than any one mechanism; and it would put the paragraph a reader is chasing one file
away from the assertion that printed it. A split that buys no module under the ceiling and costs an
indirection is a split made for the warning rather than for the reader.

What the length actually is: four rules, each with a paragraph explaining itself to somebody who
has never seen this file, and each with fabricated cases proving it can still say so.
"""

import tomllib
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from configparser import ConfigParser
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
CONFIG_FILE: Final = REPO_ROOT / ".importlinter"
PYPROJECT_FILE: Final = REPO_ROOT / "pyproject.toml"

PACKAGE_DIR: Final = REPO_ROOT / "src" / "agl"
PORTS_DIR: Final = PACKAGE_DIR / "ports"
ADAPTERS_DIR: Final = PACKAGE_DIR / "adapters"

# Contract numbers are stable - `.importlinter`'s own header says so, and stage briefs cite them -
# and each section's `type` is what this file reads its list as. The pairing is asserted below, so
# a renumbering fails here rather than silently pointing a comparison at the wrong contract.
LAYERS_SECTION: Final = "importlinter:contract:1"
PURE_TYPES_SECTION: Final = "importlinter:contract:2"
VENDOR_SECTION: Final = "importlinter:contract:3"
ADAPTERS_SECTION: Final = "importlinter:contract:4"

CONTRACTS: Final[Mapping[str, str]] = {
    LAYERS_SECTION: "layers",
    PURE_TYPES_SECTION: "forbidden",
    VENDOR_SECTION: "forbidden",
    ADAPTERS_SECTION: "independence",
}

PACKAGE: Final = "agl"
PORTS_PACKAGE: Final = "agl.ports"
ADAPTERS_PACKAGE: Final = "agl.adapters"

# The one top-level member contract 1 does not order, because a stricter rule already covers it.
LAYER_EXEMPT: Final[Mapping[str, str]] = {
    "__init__.py": "the package root, which scripts/check's package-root gate holds to a stricter "
    "rule than any layer could state: it may contain no import statement at all",
}

# The one `ports/` member contract 2 cannot police from either list, whatever it were to say.
PORT_EXEMPT: Final[Mapping[str, str]] = {
    "__init__.py": "the ports package's own docstring, and the one module import-linter would "
    "skip in both of this contract's lists - see the docstring above",
}

# Top-level `.py` files under `adapters/` that are not adapters to be policed, each with the reason
# it is not. Everything else there belongs in contract 4's `modules =` instead. Do not add an entry
# to spare yourself an edit to `.importlinter`: an exemption here removes a module from the rule,
# while a listing there applies it. Nothing is pre-authorised - notably not `_process.py`, which
# stage 8 may or may not sanction and must decide about in this file if it does.
ADAPTER_EXEMPT: Final[Mapping[str, str]] = {
    "__init__.py": "the adapters package's own docstring; no adapter lives in it",
    "routing.py": "contract 4's one sanctioned exception: dispatching on task.model.provider "
    "to the vendor runners is its entire job, so it must import other adapters",
}

# Where the distribution-to-import-name rule below is known to be wrong. Empty, and expected to
# stay that way: both of today's SDKs import under the name they ship as.
VENDOR_IMPORT_NAMES: Final[Mapping[str, str]] = {}

# Optional dependencies that are not vendor SDKs, each with the reason. Empty: every extra AGL has
# is a vendor, which is the premise this comparison rests on. An extra that breaks that premise is
# argued about here, not quietly skipped.
NOT_A_VENDOR: Final[Mapping[str, str]] = {}

# Where a requirement string stops being a distribution name: a version, a marker, an extras list.
_REQUIREMENT_END: Final = frozenset("[<>=!~;(, \t")


# --- The four comparisons -----------------------------------------------------------------------


def _present(
    package: str,
    packages: AbstractSet[str],
    modules: AbstractSet[str],
    exempt: Mapping[str, str],
) -> dict[str, str]:
    """What is on disk under `package`, as `{how a complaint spells it: the dotted name it has}`.

    `packages` are directory names, `modules` are top-level `.py` filenames (with the suffix,
    because that is how `exempt` is keyed). A directory keeps its trailing slash in the key, so a
    message reads `src/agl/probe/` rather than leaving a reader to guess which kind it was.
    """
    present = {f"{name}/": f"{package}.{name}" for name in packages}
    present |= {
        name: f"{package}.{name.removesuffix('.py')}" for name in modules if name not in exempt
    }
    return present


def layer_drift(
    listed: AbstractSet[str],
    packages: AbstractSet[str],
    modules: AbstractSet[str],
    exempt: Mapping[str, str],
) -> list[str]:
    """Every disagreement between contract 1's `layers =` and the top level of `src/agl/`.

    The return is a list of complaints, empty when the two agree; each is written to be read by
    somebody who has never seen this file and says what to do about it rather than only what is
    wrong. Pure: no disk, no config, no repository. The fabricated tests below depend on that.
    """
    present = _present(PACKAGE, packages, modules, exempt)
    problems = [
        _unlayered(shown, dotted)
        for shown, dotted in sorted(present.items())
        if dotted not in listed
    ]
    problems += [_stale_layer(entry) for entry in sorted(listed - set(present.values()))]
    return problems


def port_drift(
    sources: AbstractSet[str],
    forbidden: AbstractSet[str],
    packages: AbstractSet[str],
    modules: AbstractSet[str],
    exempt: Mapping[str, str],
) -> list[str]:
    """Every disagreement between contract 2's two lists and what is under `src/agl/ports/`.

    Two lists, so three kinds of disagreement rather than two: a module on neither list, a module
    on both, and a listing with nothing behind it. Pure, for `layer_drift`'s reason.
    """
    present = _present(PORTS_PACKAGE, packages, modules, exempt)
    listed = set(sources) | set(forbidden)
    problems = [
        _unclassified_port(shown, dotted)
        for shown, dotted in sorted(present.items())
        if dotted not in listed
    ]
    problems += [_doubly_listed_port(entry) for entry in sorted(set(sources) & set(forbidden))]
    problems += [_stale_port(entry) for entry in sorted(listed - set(present.values()))]
    return problems


def vendor_drift(
    listed: AbstractSet[str],
    vendors: Mapping[str, str],
    exempt: Mapping[str, str],
) -> list[str]:
    """Every disagreement between contract 3's `forbidden_modules` and the extras AGL declares.

    `vendors` maps a distribution name to the import name it is expected to be contained under -
    the mapping this file guesses and the docstring qualifies. Pure, for `layer_drift`'s reason.
    """
    problems = [
        _uncontained_vendor(distribution, imported)
        for distribution, imported in sorted(vendors.items())
        if imported not in listed and distribution not in exempt
    ]
    problems += [_stale_vendor(entry) for entry in sorted(listed - set(vendors.values()))]
    return problems


def adapter_drift(
    listed: AbstractSet[str],
    packages: AbstractSet[str],
    modules: AbstractSet[str],
    exempt: Mapping[str, str],
) -> list[str]:
    """Every disagreement between contract 4's `listed` modules and what is on disk.

    Kept whole from the guard that covered contract 4 alone, down to the two complaints a
    single-file member can draw: a directory under `adapters/` is an adapter package and appears in
    contract 4 or this fails, while a top-level `.py` may instead be named in `exempt`, because two
    of them are not adapters standing behind a port. Pure, for `layer_drift`'s reason.
    """
    problems = [
        _unlisted_package(name)
        for name in sorted(packages)
        if f"{ADAPTERS_PACKAGE}.{name}" not in listed
    ]
    problems += [
        _unlisted_module(filename)
        for filename in sorted(modules)
        if f"{ADAPTERS_PACKAGE}.{filename.removesuffix('.py')}" not in listed
        and filename not in exempt
    ]
    on_disk = {f"{ADAPTERS_PACKAGE}.{name}" for name in packages} | {
        f"{ADAPTERS_PACKAGE}.{filename.removesuffix('.py')}" for filename in modules
    }
    problems += [_stale_listing(entry) for entry in sorted(listed - on_disk)]
    return problems


# --- What each complaint says -------------------------------------------------------------------


def _unlayered(shown: str, dotted: str) -> str:
    return (
        f"src/agl/{shown} is a top-level member of the agl package that contract 1 of "
        f".importlinter does not list.\n"
        f"\n"
        f"That contract's `layers =` is a hand-maintained list, so it fails open - and it fails "
        f"open upwards: a member missing from it is not at the bottom of the stack, it is outside "
        f"the stack. Nothing orders its imports, so it may import agl.ports and agl.adapters "
        f"directly and be imported by anything, with all six contracts still reported kept.\n"
        f"\n"
        f"Resolve it by adding this line to `layers =` under [{LAYERS_SECTION}], at the level "
        f"ARCHITECTURE.md §2's dependency rule puts it - the list runs high to low, and a level "
        f"naming two modules with `|` is two siblings that may not import each other:\n"
        f"    {dotted}\n"
        f"\n"
        f"There is one exemption and it is __init__.py, which is out of this comparison because it "
        f"is held to something stricter: scripts/check's package-root gate forbids it every import "
        f"statement, which is not a thing an ordering of layers can say."
    )


def _stale_layer(entry: str) -> str:
    return (
        f"contract 1 of .importlinter lists {entry}, which is not a top-level member of src/agl/.\n"
        f"\n"
        f"A layer naming a module that does not exist orders nothing, and the next reader counts "
        f"it as one more package held to the dependency rule. import-linter refuses a missing "
        f"layer outright and would normally say so first - unless the entry is wrapped in "
        f"parentheses, its spelling for a layer whose absence is tolerated, which is exactly the "
        f"case where nobody else is going to mention it.\n"
        f"\n"
        f"Resolve it by removing that line from `layers =` under [{LAYERS_SECTION}], or by "
        f"restoring the module it names."
    )


def _unclassified_port(shown: str, dotted: str) -> str:
    return (
        f"src/agl/ports/{shown} appears in neither of contract 2's two lists in .importlinter.\n"
        f"\n"
        f"That contract keeps a type an ABC speaks from importing the ABC that speaks it, and it "
        f"does so with two hand-maintained lists: `source_modules`, the pure types, and "
        f"`forbidden_modules`, the ABCs. A module missing from both is unpoliced whichever it "
        f"belonged in - absent from `source_modules` it may import any ABC there is, and absent "
        f"from `forbidden_modules` every pure type in the ring is free to import it - and neither "
        f"shows up as a broken contract.\n"
        f"\n"
        f"Resolve it by adding this line to exactly one of the two lists under "
        f"[{PURE_TYPES_SECTION}]:\n"
        f"    {dotted}\n"
        f"\n"
        f"Which list is ARCHITECTURE.md §6's question and not this test's: `source_modules` if the "
        f"module holds types an ABC speaks, `forbidden_modules` if it holds an ABC. There is no "
        f"exemption route here - __init__.py is out of the comparison because import-linter would "
        f"skip it in both lists, which is a fact about the tool and not a licence to add a second."
    )


def _doubly_listed_port(entry: str) -> str:
    return (
        f"contract 2 of .importlinter names {entry} in both `source_modules` and "
        f"`forbidden_modules`.\n"
        f"\n"
        f"import-linter skips the pair a module makes with itself, so nothing breaks and nothing "
        f"is reported - which is the problem. The two lists are the ring's inner edge: one is the "
        f"pure types and the other is the ABCs, and a module in both says there is no edge there. "
        f"A reader deciding where the next module goes has just been told both answers.\n"
        f"\n"
        f"Resolve it by deciding which one it is and removing the other entry under "
        f"[{PURE_TYPES_SECTION}]. A module that genuinely holds both a pure type and the ABC that "
        f"speaks it is two modules."
    )


def _stale_port(entry: str) -> str:
    return (
        f"contract 2 of .importlinter names {entry}, which is not a module under src/agl/ports/.\n"
        f"\n"
        f"A contract naming a module that does not exist is quietly protecting nothing: it reads "
        f"as coverage and enforces none. import-linter refuses a missing *source* module outright, "
        f"so an entry that got as far as this test is on the forbidden side, where a name with "
        f"nothing behind it is dropped in silence.\n"
        f"\n"
        f"Resolve it by removing that line under [{PURE_TYPES_SECTION}], or by restoring the "
        f"module it names."
    )


def _uncontained_vendor(distribution: str, imported: str) -> str:
    return (
        f"pyproject.toml declares {distribution!r} as an optional dependency, and contract 3 of "
        f".importlinter does not contain it.\n"
        f"\n"
        f"That contract is what keeps a vendor SDK visible to exactly one adapter package, so that "
        f"installing one vendor never drags in another's SDK (ARCHITECTURE.md §4). Its "
        f"`forbidden_modules` is a hand-maintained list of two, and a third SDK missing from it is "
        f"contained by nothing at all: contract 5 governs who may import agl.adapters and has no "
        f"opinion about what an adapter imports from outside, so any module in the tree could "
        f"import this one with all six contracts still reported kept.\n"
        f"\n"
        f"Resolve it by adding the SDK's *import* name to `forbidden_modules` under "
        f"[{VENDOR_SECTION}], plus one `ignore_imports` expression per module permitted to import "
        f"it, in the shape the four already there use. This test guessed that name to be:\n"
        f"    {imported}\n"
        f"\n"
        f"The guess is the distribution name lowercased with `-` and `.` turned into `_`, and "
        f"nothing cleverer - a distribution may ship a module under any name at all. If the real "
        f"import name is something else, put it in VENDOR_IMPORT_NAMES in this test so the two "
        f"sides agree; if this distribution is not a vendor SDK, name it in NOT_A_VENDOR with the "
        f"reason it is not."
    )


def _stale_vendor(entry: str) -> str:
    return (
        f"contract 3 of .importlinter forbids {entry}, which no extra in pyproject.toml "
        f"declares.\n"
        f"\n"
        f"A vendor contained but never depended on reads as coverage of an SDK AGL does not have, "
        f"and the adapter it was written for is either gone or was never written. import-linter "
        f"says nothing about it: a forbidden module absent from the graph is dropped in silence, "
        f"which is also what lets this contract keep working while the SDKs are uninstalled.\n"
        f"\n"
        f"Resolve it by removing that line and its `ignore_imports` expressions under "
        f"[{VENDOR_SECTION}], or by restoring the extra in pyproject.toml that declares it."
    )


def _unlisted_package(name: str) -> str:
    return (
        f"src/agl/adapters/{name}/ is an adapter package that contract 4 of .importlinter does "
        f"not list.\n"
        f"\n"
        f"That contract's `modules =` is a hand-maintained list, so it fails open: an adapter "
        f"missing from it may import any other adapter with all six contracts still reported "
        f"kept. Contract 5 skips the (agl.adapters, agl.adapters) pair as self-overlapping, "
        f"which is exactly why contract 4 exists, so nothing else in the repo would object.\n"
        f"\n"
        f"Resolve it by adding this line to `modules =` under [{ADAPTERS_SECTION}]:\n"
        f"    {ADAPTERS_PACKAGE}.{name}\n"
        f"\n"
        f"A package has no exemption route - ADAPTER_EXEMPT in this test is keyed by filename and "
        f"holds only single-file members. An adapter package that genuinely must import another "
        f"adapter is an architecture change: ARCHITECTURE.md changes first, .importlinter second."
    )


def _unlisted_module(filename: str) -> str:
    return (
        f"src/agl/adapters/{filename} is neither listed in contract 4 of .importlinter nor "
        f"exempted in this test.\n"
        f"\n"
        f"That contract's `modules =` is a hand-maintained list, so it fails open: a module "
        f"missing from it may import any other adapter with all six contracts still reported "
        f"kept, and nothing else in the repo would object.\n"
        f"\n"
        f"Two ways to resolve it, and they are not interchangeable:\n"
        f"  1. add `{ADAPTERS_PACKAGE}.{filename.removesuffix('.py')}` to `modules =` under "
        f"[{ADAPTERS_SECTION}] - the answer for an ordinary adapter that happens to be one file "
        f"rather than a directory, as system_clock.py is;\n"
        f'  2. add "{filename}" to ADAPTER_EXEMPT in this test with a one-line reason - the answer '
        f"only if the module is not an adapter behind a port at all, or is sanctioned to import "
        f"other adapters the way routing.py is."
    )


def _stale_listing(entry: str) -> str:
    return (
        f"contract 4 of .importlinter lists {entry}, which is not under src/agl/adapters/.\n"
        f"\n"
        f"A contract naming a module that does not exist is quietly protecting nothing: it reads "
        f"as coverage and enforces none, and the next reader counts it as one more adapter held "
        f"to the rule.\n"
        f"\n"
        f"Resolve it by removing that line from `modules =` under [{ADAPTERS_SECTION}], or by "
        f"restoring the adapter it names."
    )


# --- Reading the real config, the real tree and the real project metadata -----------------------


def _section(name: str) -> Mapping[str, str]:
    """One section of the real `.importlinter`, parsed."""
    parser = ConfigParser()
    with CONFIG_FILE.open(encoding="utf-8") as handle:
        parser.read_file(handle)
    assert name in parser, (
        f"{CONFIG_FILE} has no [{name}] section. Contract numbers are stable by policy - see that "
        f"file's header - so if a contract was renumbered, both the policy and this test need "
        f"revisiting, and every stage brief that cites a contract by number too."
    )
    return parser[name]


def _listing(section: str, key: str) -> frozenset[str]:
    """One contract's hand-maintained list, one entry per line."""
    raw = _section(section).get(key)
    assert raw is not None, (
        f"[{section}] in {CONFIG_FILE} has no `{key} =` key. A contract missing one of its lists "
        f"polices nothing that list covered, and every module in the tree it named is unguarded "
        f"until it returns."
    )
    return frozenset(line.strip() for line in raw.splitlines() if line.strip())


def _layer_listing() -> frozenset[str]:
    """Contract 1's `layers =`, which is not one name per line.

    A line is a *level*, and a level may name more than one module: `agl.sdk | agl.adapters` is two
    siblings that may not import each other, and `a : b` two that may, so either delimiter splits
    the line. A name in parentheses is import-linter's spelling for a layer whose absence is
    tolerated - still a listing, and the one spelling that can go stale without import-linter
    saying so, since it refuses a missing required layer outright.
    """
    raw = _section(LAYERS_SECTION).get("layers")
    assert raw is not None, (
        f"[{LAYERS_SECTION}] in {CONFIG_FILE} has no `layers =` key. A layers contract without one "
        f"orders nothing, and every top-level package is outside the dependency stack until it "
        f"returns."
    )
    names = {
        part.strip().strip("()").strip()
        for line in raw.splitlines()
        for part in line.replace(":", "|").split("|")
    }
    return frozenset(name for name in names if name)


def _members(directory: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Directory names and top-level `.py` filenames directly under `directory`."""
    children = sorted(directory.iterdir())
    packages = frozenset(p.name for p in children if p.is_dir() and p.name != "__pycache__")
    modules = frozenset(p.name for p in children if p.is_file() and p.suffix == ".py")
    return packages, modules


def _distribution(requirement: str) -> str:
    """The distribution name a requirement string starts with - `claude-agent-sdk>=0.2.140`."""
    for index, character in enumerate(requirement):
        if character in _REQUIREMENT_END:
            return requirement[:index].strip()
    return requirement.strip()


def _import_name(distribution: str) -> str:
    """The guess. See this file's docstring for what it cannot know."""
    return distribution.strip().lower().replace("-", "_").replace(".", "_")


def _declared_vendors() -> dict[str, str]:
    """Every distribution AGL's optional extras declare, by the import name this test expects.

    `all = ["agl[claude,terminal]"]` is a self-reference and not a vendor, and is dropped by
    comparing against the project's own name read from the same file rather than by being named
    here - a hardcoded `"agl"` would be one more thing free to drift.
    """
    parsed = tomllib.loads(PYPROJECT_FILE.read_text(encoding="utf-8"))
    project = parsed.get("project")
    assert isinstance(project, dict), (
        f"{PYPROJECT_FILE} has no [project] table, so this test cannot tell which distributions "
        f"AGL depends on or even what AGL itself is called. Check the path at the top of this file."
    )
    extras = project.get("optional-dependencies")
    assert isinstance(extras, dict) and extras, (
        f"{PYPROJECT_FILE} declares no [project.optional-dependencies], which is where a vendor "
        f"SDK is added (ARCHITECTURE.md §4). Either the table moved and this test is now comparing "
        f"contract 3 against nothing, or AGL has stopped having vendor extras and contract 3 and "
        f"this comparison both need revisiting."
    )
    own = _import_name(str(project.get("name", "")))
    found: dict[str, str] = {}
    for requirements in extras.values():
        for requirement in requirements:
            distribution = _distribution(str(requirement))
            if not distribution or _import_name(distribution) == own:
                continue
            found[distribution] = VENDOR_IMPORT_NAMES.get(distribution, _import_name(distribution))
    return found


# --- The real comparisons ------------------------------------------------------------------------


@pytest.mark.parametrize(("section", "expected"), sorted(CONTRACTS.items()))
def test_each_contract_is_still_the_kind_of_contract_this_file_reads(
    section: str, expected: str
) -> None:
    """Each section this file parses must be the one it thinks it is."""
    contract_type = _section(section).get("type")
    assert contract_type == expected, (
        f"[{section}] is a `{contract_type}` contract, not `{expected}`. This test reads that "
        f"section's own list as the set of modules it holds to a rule; if the contract now means "
        f"something else, this test is guarding the wrong thing - and so is every stage brief "
        f"that cites it by number."
    )


def test_every_top_level_member_of_agl_appears_in_contract_1() -> None:
    """The top level of `src/agl/` and contract 1's `layers =` name the same members."""
    packages, modules = _members(PACKAGE_DIR)
    assert packages and modules, (
        f"{PACKAGE_DIR} holds no packages or modules at all. This test walked the wrong directory "
        f"and is asserting nothing; check the path at the top of this file."
    )
    problems = layer_drift(_layer_listing(), packages, modules, LAYER_EXEMPT)
    assert not problems, "\n\n".join(problems)


def test_every_module_under_ports_appears_on_exactly_one_side_of_contract_2() -> None:
    """Every `ports/` module is a pure type or an ABC, and the contract says which."""
    packages, modules = _members(PORTS_DIR)
    assert modules, (
        f"{PORTS_DIR} holds no modules at all. This test walked the wrong directory and is "
        f"asserting nothing; check the path at the top of this file."
    )
    problems = port_drift(
        _listing(PURE_TYPES_SECTION, "source_modules"),
        _listing(PURE_TYPES_SECTION, "forbidden_modules"),
        packages,
        modules,
        PORT_EXEMPT,
    )
    assert not problems, "\n\n".join(problems)


def test_every_vendor_sdk_an_extra_declares_is_contained_by_contract_3() -> None:
    """`pyproject.toml` is where a vendor SDK arrives; contract 3 is what confines it."""
    vendors = _declared_vendors()
    assert vendors, (
        f"{PYPROJECT_FILE}'s extras declare no distribution other than AGL itself, so this test "
        f"is comparing contract 3 against an empty set and would pass on any listing at all."
    )
    problems = vendor_drift(_listing(VENDOR_SECTION, "forbidden_modules"), vendors, NOT_A_VENDOR)
    assert not problems, "\n\n".join(problems)


def test_every_adapter_appears_in_contract_4() -> None:
    """The tree under `src/agl/adapters/` and contract 4's `modules =` name the same adapters."""
    packages, modules = _members(ADAPTERS_DIR)
    assert packages and modules, (
        f"{ADAPTERS_DIR} holds no adapter packages or modules at all. This test walked the wrong "
        f"directory and is asserting nothing; check the path at the top of this file."
    )
    listed = _listing(ADAPTERS_SECTION, "modules")
    problems = adapter_drift(listed, packages, modules, ADAPTER_EXEMPT)
    assert not problems, "\n\n".join(problems)


# ---------------------------------------------------------------------------------------------
# Non-vacuity: the four comparisons on fabricated input, so that a refactor which broke one into
# always agreeing fails here instead of passing everywhere. Nothing below reads the repository.
# ---------------------------------------------------------------------------------------------

_FABRICATED_INIT_EXEMPT: Final[Mapping[str, str]] = {"__init__.py": "the package's own docstring"}
_FABRICATED_EXEMPT: Final[Mapping[str, str]] = {"routing.py": "the sanctioned exception"}


def test_layer_drift_is_silent_when_the_listing_and_the_tree_agree() -> None:
    """The case that makes the failing cases below mean something."""
    assert not layer_drift(
        frozenset({"agl.ports", "agl.api"}),
        frozenset({"ports"}),
        frozenset({"api.py", "__init__.py"}),
        _FABRICATED_INIT_EXEMPT,
    )


def test_layer_drift_reports_a_top_level_member_that_is_in_no_layer() -> None:
    """The failure this half exists for: a package added and never put in the stack."""
    problems = layer_drift(
        frozenset({"agl.ports"}),
        frozenset({"ports", "probe"}),
        frozenset({"probe.py"}),
        _FABRICATED_INIT_EXEMPT,
    )
    assert len(problems) == 2
    assert any("src/agl/probe/" in problem and "agl.probe" in problem for problem in problems)
    assert any("src/agl/probe.py" in problem for problem in problems)
    assert all("outside the stack" in problem for problem in problems)


def test_layer_drift_reports_a_layer_with_nothing_behind_it() -> None:
    """A parenthesised optional layer can go stale with import-linter saying nothing."""
    problems = layer_drift(
        frozenset({"agl.ports", "agl.gone"}),
        frozenset({"ports"}),
        frozenset(),
        _FABRICATED_INIT_EXEMPT,
    )
    assert len(problems) == 1
    assert "agl.gone" in problems[0]
    assert "not a top-level member" in problems[0]


def test_port_drift_is_silent_when_every_module_is_on_exactly_one_side() -> None:
    """The agreeing case: one pure type, one ABC, and the package root out of it."""
    assert not port_drift(
        frozenset({"agl.ports.ids"}),
        frozenset({"agl.ports.store"}),
        frozenset(),
        frozenset({"ids.py", "store.py", "__init__.py"}),
        _FABRICATED_INIT_EXEMPT,
    )


def test_port_drift_reports_a_module_on_neither_list() -> None:
    """The failure this half exists for: a `ports/` module nobody classified."""
    problems = port_drift(
        frozenset({"agl.ports.ids"}),
        frozenset({"agl.ports.store"}),
        frozenset(),
        frozenset({"ids.py", "store.py", "probe.py"}),
        _FABRICATED_INIT_EXEMPT,
    )
    assert len(problems) == 1
    assert "src/agl/ports/probe.py" in problems[0]
    assert "agl.ports.probe" in problems[0]
    assert "neither" in problems[0]


def test_port_drift_reports_a_module_claimed_by_both_lists() -> None:
    """Both lists at once is the ring saying it has no inner edge there."""
    problems = port_drift(
        frozenset({"agl.ports.ids"}),
        frozenset({"agl.ports.ids"}),
        frozenset(),
        frozenset({"ids.py"}),
        _FABRICATED_INIT_EXEMPT,
    )
    assert len(problems) == 1
    assert "agl.ports.ids" in problems[0]
    assert "both" in problems[0]


def test_port_drift_reports_a_listing_with_nothing_behind_it() -> None:
    """A forbidden module absent from the graph is dropped in silence by import-linter."""
    problems = port_drift(
        frozenset({"agl.ports.ids"}),
        frozenset({"agl.ports.gone"}),
        frozenset(),
        frozenset({"ids.py"}),
        _FABRICATED_INIT_EXEMPT,
    )
    assert len(problems) == 1
    assert "agl.ports.gone" in problems[0]
    assert "not a module under src/agl/ports/" in problems[0]


def test_vendor_drift_is_silent_when_every_declared_sdk_is_contained() -> None:
    """The agreeing case, including the one distribution whose name is not its import name."""
    assert not vendor_drift(
        frozenset({"claude_agent_sdk", "rich"}),
        {"claude-agent-sdk": "claude_agent_sdk", "rich": "rich"},
        {},
    )


def test_vendor_drift_reports_an_sdk_no_contract_contains() -> None:
    """The failure this half exists for: a third SDK added as an extra and confined nowhere."""
    problems = vendor_drift(
        frozenset({"rich"}),
        {"rich": "rich", "probe-sdk": "probe_sdk"},
        {},
    )
    assert len(problems) == 1
    assert "'probe-sdk'" in problems[0]
    assert "probe_sdk" in problems[0]
    assert "contained by nothing at all" in problems[0]


def test_vendor_drift_accepts_a_distribution_that_is_exempt_with_a_reason() -> None:
    """An extra that is not a vendor SDK is out of the rule, and says why it is."""
    assert not vendor_drift(
        frozenset({"rich"}),
        {"rich": "rich", "sphinx": "sphinx"},
        {"sphinx": "a documentation builder, not an SDK any adapter speaks to"},
    )


def test_vendor_drift_reports_a_containment_with_no_dependency_behind_it() -> None:
    """A vendor forbidden but never depended on reads as coverage of an SDK AGL has not got."""
    problems = vendor_drift(frozenset({"rich", "gone_sdk"}), {"rich": "rich"}, {})
    assert len(problems) == 1
    assert "gone_sdk" in problems[0]
    assert "no extra in pyproject.toml declares" in problems[0]


def test_adapter_drift_is_silent_when_the_listing_and_the_tree_agree() -> None:
    """The case that makes the failing cases below mean something."""
    assert not adapter_drift(
        frozenset({f"{ADAPTERS_PACKAGE}.git", f"{ADAPTERS_PACKAGE}.system_clock"}),
        frozenset({"git"}),
        frozenset({"system_clock.py", "routing.py"}),
        _FABRICATED_EXEMPT,
    )


def test_adapter_drift_reports_a_package_missing_from_the_listing() -> None:
    """The failure this half exists for: an adapter package added and never listed."""
    problems = adapter_drift(
        frozenset({f"{ADAPTERS_PACKAGE}.git"}),
        frozenset({"git", "xyz"}),
        frozenset(),
        _FABRICATED_EXEMPT,
    )
    assert len(problems) == 1
    assert "src/agl/adapters/xyz/" in problems[0]
    assert f"{ADAPTERS_PACKAGE}.xyz" in problems[0]
    assert "fails open" in problems[0]


def test_adapter_drift_reports_a_module_that_is_neither_listed_nor_exempt() -> None:
    """A single-file adapter is a member, not an exception - it is listed or it is explained."""
    problems = adapter_drift(
        frozenset(),
        frozenset(),
        frozenset({"_process.py"}),
        _FABRICATED_EXEMPT,
    )
    assert len(problems) == 1
    assert "src/agl/adapters/_process.py" in problems[0]
    assert f"{ADAPTERS_PACKAGE}._process" in problems[0]
    assert "ADAPTER_EXEMPT" in problems[0]


def test_adapter_drift_accepts_a_module_that_is_exempt_with_a_reason() -> None:
    """`routing.py` must import other adapters, so it is out of the contract and out of this."""
    exempt_only = frozenset({"routing.py"})
    assert not adapter_drift(frozenset(), frozenset(), exempt_only, _FABRICATED_EXEMPT)


def test_adapter_drift_reports_a_listing_with_nothing_behind_it() -> None:
    """A contract naming a deleted adapter reads as coverage and enforces none."""
    problems = adapter_drift(
        frozenset({f"{ADAPTERS_PACKAGE}.git", f"{ADAPTERS_PACKAGE}.gone"}),
        frozenset({"git"}),
        frozenset(),
        _FABRICATED_EXEMPT,
    )
    assert len(problems) == 1
    assert f"{ADAPTERS_PACKAGE}.gone" in problems[0]
    assert "not under src/agl/adapters/" in problems[0]


def test_every_comparison_reports_every_disagreement_at_once() -> None:
    """Separate edits are separate complaints in one run, not one discovered at a time.

    Three apiece, and for `port_drift` the three are one of each kind it can produce - a module on
    neither list, a module on both, and a listing with nothing behind it - which is the case that
    would break first if the three ever got written as an `elif`.
    """
    layers = layer_drift(
        frozenset({"agl.gone"}),
        frozenset({"probe"}),
        frozenset({"probe.py"}),
        _FABRICATED_INIT_EXEMPT,
    )
    ports = port_drift(
        frozenset({"agl.ports.ids"}),
        frozenset({"agl.ports.ids", "agl.ports.gone"}),
        frozenset(),
        frozenset({"ids.py", "probe.py"}),
        _FABRICATED_INIT_EXEMPT,
    )
    vendors = vendor_drift(frozenset({"gone_sdk"}), {"a-sdk": "a_sdk", "b-sdk": "b_sdk"}, {})
    adapters = adapter_drift(
        frozenset({f"{ADAPTERS_PACKAGE}.gone"}),
        frozenset({"xyz"}),
        frozenset({"_process.py"}),
        _FABRICATED_EXEMPT,
    )

    assert [len(layers), len(ports), len(vendors), len(adapters)] == [3, 3, 3, 3]
