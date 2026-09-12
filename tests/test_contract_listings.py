"""Structural test: three contracts in `.importlinter` are lists somebody typed, and this is what
notices when a list and the thing it is meant to police stop agreeing.

Two of the contracts are fail-closed and need nothing from this file. Contract 5's source is
`agl.*`, which re-expands as packages are added, so a module introduced at a later stage is covered
the moment it exists and its author need do nothing to be policed. **Contract 1 was a
hand-maintained guard here and is now the second of those**: `containers = agl` plus
`exhaustive = True` makes an unlisted child of
`agl` break that contract natively and by name, which is what a hand-maintained comparison in this
file used to notice. A rule the linter enforces beats a rule a neighbour asserts, so the comparison
went; `.importlinter`'s own comment on contract 1 records what the rewrite does and does not still
reach. The three below cannot be written that way, and each fails open in its own
direction:

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
that broke it; a contract that never heard of your module agrees with everything you do. It was
found first on contract 4 and deferred to the first adapter that would need it; three others turned
out to have the same shape, and one guard covered all four until contract 1's share went back to
the linter. Without it, later work would be written under rules that were not being applied to it,
and the first sign of it would have been two vendors quietly sharing a helper.

`scripts/check`'s package-root gate is the precedent: a rule `.importlinter` cannot express,
enforced beside it rather than wished into it. This is a test rather than a shell gate only because
what it compares - a parsed config against a walked tree - is easier to say in Python than in grep.
`tests/test_ports_stdlib_only.py` is the other rule of that kind and was written to the same
criterion; `tests/test_contract_firing.py` is the neighbour that asks the opposite question, which
is whether a contract that *is* listed correctly refuses anything when a violation appears.

## The file is the source of truth and the world is the check

Nothing below hardcodes which ports, vendors or adapters exist. Each listing is parsed out
of the real `.importlinter` and compared against the real thing it polices: `src/agl/` for
contracts 2 and 4, and `pyproject.toml`'s `[project] dependencies` for contract 3,
which is where a vendor SDK actually gets added. A test carrying its own copy of any of those three
lists would be a *second* hand-maintained list, free to drift from the first, and its agreement
would mean only that one person updated both at once. Here the two things compared are the artefact
that does the policing and the world it is meant to police, so agreement is the property wanted.

## `ports/__init__.py` is out of contract 2's comparison, and the exemption is forced

import-linter skips any source/forbidden pair where one module is inside the other's package
(`_modules_overlap`, in its `forbidden` contract), and `agl.ports` contains every module on both of
contract 2's lists - so the package root in `source_modules` would be skipped against every ABC, and
in `forbidden_modules` skipped against every pure type. No entry there would police it, and
requiring one would be requiring a decoration. Stated plainly, because it is a real gap rather than
a covered one: `ports/__init__.py` could import an ABC and contract 2 could not say so. It is one
empty today, and what guards it is partial and worth knowing exactly:
`tests/test_ports_stdlib_only.py` holds it, like every module beside it, to importing stdlib and
`agl.ports` alone - so the reach is bounded, and an ABC is the one import it can still make
unremarked. The same blind spot `agl/__init__.py` has one ring out, narrowed rather than closed.

Directories have no exemption route at all, in either tree comparison: `EXEMPT` mappings
here are keyed by filename and hold only single-file members. They are mappings and not sets so
that the reason travels with the name and a later reader can weigh it instead of guessing at it.

## A distribution name is not an import name, and contract 3's half of this only guesses

Contract 3 forbids *import* names (`claude_agent_sdk`); `pyproject.toml` declares *distribution*
names (`claude-agent-sdk`). The rule below is the obvious one - lowercase, with `-` and `.` becoming
`_` - and it is right for both of today's dependencies and for most others. It is not a derivation
and cannot be: a distribution may install a top-level module under any name it likes, which is how
`pyyaml` becomes `yaml` and `pillow` becomes `PIL`. What the rule guarantees is *noticing* a third
SDK, not naming it correctly; when it guesses wrong the guard still fires, and
`VENDOR_IMPORT_NAMES` is where the true name goes. `NOT_A_VENDOR` is the other escape, for a
dependency that is not a vendor SDK at all. The first is empty and the second holds one name, and
neither pre-authorises anything: a dependency added at a later stage trips this guard first and is
argued about here second.

`[project] dependencies` is the whole of what this reads, and that is the second limit. Both of
today's vendor SDKs are unconditional entries in it, so that list is what an install of AGL gets
and is where a third one arrives. What would not be seen here is a vendor spelled out inside a
`[dependency-groups]` entry, a group being the one place a distribution can be named that no
built distribution carries and no `pip install` resolves; nothing does that today, and doing it
would be a design change big enough to bring somebody back to this file.

**Unconditional is not `ARCHITECTURE.md`'s "Vendor containment" walked back, and it is why this
comparison matters more rather than less.** What contains a vendor is contract 3 and
`config/container.py` importing each one inside the function that constructs it, and neither of
those reads package metadata at all. A base dependency is present in *every* install, so a module
that reaches for a vendor SDK it has no business with will find it there and import it: contract 3
is then the only thing standing between the two, and a third SDK missing from that contract is
guarded by nothing whatsoever.

The asymmetry with OpenAI is deliberate and is not a gap here: that adapter wraps the Codex CLI
binary and has no Python import to contain, so it has no distribution to declare and is guarded by
`scripts/check`'s grep gate instead.

## Why each comparison is a function and not three lines inside a test

`port_drift`, `vendor_drift` and `adapter_drift` take sets and return complaints,
touching no disk, so the fabricated tests at the bottom can hand each one a listing and a world
that disagree in every way that matters and watch it say so. A structural test that reads a
repository and finds it consistent looks identical whether it is checking anything or not; those
tests are what tell the difference. Each real test additionally refuses to pass on an empty tree, a
missing section or a missing list, which is the failure mode of a mistyped path.

## One module, well past the ceiling

At 452 code lines this file is half again `scripts/check`'s 300-line convention - one of the 37
modules over that ceiling, eighteen of which are larger - and two ways of splitting it were
considered and refused rather than overlooked.

Splitting **per contract** would make three guards out of one, and what makes this one guard is
precisely what the three would then have to share: one parse of `.importlinter`, one way of walking
a directory, one shape of complaint, and one discipline of proving the comparison non-vacuous. The
only seam that split could follow is the contract numbers, which are not a seam - they are three
instances of one defect.

Splitting **pure from impure** - the comparisons and their complaints in one module, the readers
and the tests in another - is the seam this file genuinely draws, and it still does not pay. It
would put the paragraph a reader is chasing one file away from the assertion that printed it, which
is the whole of the reason: the bulk here is complaint texts and fabricated cases rather than any
one mechanism, so both halves would be readable and neither would be *about* anything the other was
not. This paragraph used to carry a second reason - that both halves landed over the ceiling
regardless - and that arithmetic no longer holds now the gate counts code lines: halved, this file
would be two modules of roughly 220 and both would clear it. The reader cost was always the
load-bearing half, and it is now the only half.

What the length actually is: three rules, each with a paragraph explaining itself to somebody who
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

# Contract numbers are stable - `.importlinter`'s own header says so, and a number there is the
# section id import-linter reads - and each section's `type` is what this file reads its list as.
# The pairing is asserted below, so a renumbering fails here rather than silently pointing a
# comparison at the wrong contract.
# Contract 1 is absent because this file no longer reads it; `tests/test_contract_firing.py` pins
# every number to its type, that being the file that builds a contract object per number.
PURE_TYPES_SECTION: Final = "importlinter:contract:2"
VENDOR_SECTION: Final = "importlinter:contract:3"
ADAPTERS_SECTION: Final = "importlinter:contract:4"

CONTRACTS: Final[Mapping[str, str]] = {
    PURE_TYPES_SECTION: "forbidden",
    VENDOR_SECTION: "forbidden",
    ADAPTERS_SECTION: "independence",
}

PORTS_PACKAGE: Final = "agl.ports"
ADAPTERS_PACKAGE: Final = "agl.adapters"

# The one `ports/` member contract 2 cannot police from either list, whatever it were to say.
PORT_EXEMPT: Final[Mapping[str, str]] = {
    "__init__.py": "the ports package root, and the one module import-linter would "
    "skip in both of this contract's lists - see the docstring above",
}

# Top-level `.py` files under `adapters/` that are not adapters to be policed, each with the reason
# it is not. Everything else there belongs in contract 4's `modules =` instead. Do not add an entry
# to spare yourself an edit to `.importlinter`: an exemption here removes a module from the rule,
# while a listing there applies it. Nothing is pre-authorised, and one hypothetical name was left
# here early to say so - a shared `_process.py`, which the second vendor adapter was expected to
# want and did not write: the git package kept `_runner.py`, the shell verifier and the OpenAI
# runner each spawn their own, and no top-level module arrived. Two candidates that were written
# have since been weighed here and refused: the port fake, 182 lines of which `claude_code/` and
# `openai/` hold in common, and `Caller` with its two message constants, 24 byte-identical lines in
# both `_tools.py`. Both stay duplicated. An entry here is the only shape either could have taken -
# a directory cannot be exempted, and a listed peer package is forbidden to the very adapters that
# would import it - which is why the refusal is recorded here. ARCHITECTURE.md's "No shared module
# under `adapters/`" carries the argument in full. The list has been confirmed against the tree and
# both entries below are still the whole of it.
ADAPTER_EXEMPT: Final[Mapping[str, str]] = {
    "__init__.py": "the adapters package root; no adapter lives in it",
    "routing.py": "contract 4's one sanctioned exception: dispatching on task.model.provider "
    "to the vendor runners is its entire job, so it must import other adapters",
}

# Where the distribution-to-import-name rule below is known to be wrong. Empty, and expected to
# stay that way: both of today's SDKs import under the name they ship as.
VENDOR_IMPORT_NAMES: Final[Mapping[str, str]] = {}

# Declared dependencies that are not vendor SDKs, each with the reason. One entry, and it is the
# premise of the comparison being weakened rather than a name being waved through: every *other*
# distribution AGL depends on is a vendor, and one that is not is argued about here.
#
# `packaging` is a grammar and not a backend. Nothing behind it can be reached, spoken to or paid
# for - there is no endpoint, no credential and no process - so "installing one vendor drags in the
# other's SDK", which is the whole of what contract 3 exists to prevent, has nothing to be about
# here. `config/` reads versions and requirements with it, PEP 440 being what makes comparing two
# versions a parse rather than a string comparison. Contract 3 could name it and would then forbid
# imports that have to exist.
NOT_A_VENDOR: Final[Mapping[str, str]] = {
    "packaging": "PEP 440 and PEP 508 parsing, which config/ reads versions and requirements "
    "with; no endpoint behind it, so there is no vendor to contain",
}

# Where a requirement string stops being a distribution name: a version, a marker, an extras list.
_REQUIREMENT_END: Final = frozenset("[<>=!~;(, \t")

# --- The three comparisons ----------------------------------------------------------------------

def _present(
    package: str,
    packages: AbstractSet[str],
    modules: AbstractSet[str],
    exempt: Mapping[str, str],
) -> dict[str, str]:
    """What is on disk under `package`, as `{how a complaint spells it: the dotted name it has}`.

    `packages` are directory names, `modules` are top-level `.py` filenames (with the suffix,
    because that is how `exempt` is keyed). A directory keeps its trailing slash in the key, so a
    message reads `src/agl/ports/probe/` rather than leaving a reader to guess which kind it was.
    """
    present = {f"{name}/": f"{package}.{name}" for name in packages}
    present |= {
        name: f"{package}.{name.removesuffix('.py')}" for name in modules if name not in exempt
    }
    return present

def port_drift(
    sources: AbstractSet[str],
    forbidden: AbstractSet[str],
    packages: AbstractSet[str],
    modules: AbstractSet[str],
    exempt: Mapping[str, str],
) -> list[str]:
    """Every disagreement between contract 2's two lists and what is under `src/agl/ports/`.

    Two lists, so three kinds of disagreement rather than two: a module on neither list, a module
    on both, and a listing with nothing behind it. The return is a list of complaints, empty when
    the two agree; each is written to be read by somebody who has never seen this file and says what
    to do about it rather than only what is wrong. Pure: no disk, no config, no repository. The
    fabricated tests below depend on that.
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
    """Every disagreement between contract 3's `forbidden_modules` and AGL's declared dependencies.

    `vendors` maps a distribution name to the import name it is expected to be contained under -
    the mapping this file guesses and the docstring qualifies. Pure, for `port_drift`'s reason.
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
    of them are not adapters standing behind a port. Pure, for `port_drift`'s reason.
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
        f"Which list is a question for ARCHITECTURE.md's \"The layers\" and not for this test: "
        f"`source_modules` if the module holds types an ABC speaks, `forbidden_modules` if it "
        f"holds an ABC. There is no exemption route here - __init__.py is out of the comparison "
        f"because import-linter would skip it in both lists, which is a fact about the tool and "
        f"not a licence to add a second."
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
        f"pyproject.toml names {distribution!r} in [project] dependencies, and contract 3 of "
        f".importlinter does not contain it.\n"
        f"\n"
        f"That contract is what keeps a vendor SDK visible to exactly one adapter package, so that "
        f"no module outside that package can reach the SDK at all (ARCHITECTURE.md's \"Vendor "
        f"containment\"). Its `forbidden_modules` is a hand-maintained list of two, and a third "
        f"SDK missing from it is contained by nothing at all: contract 5 governs who may import "
        f"agl.adapters and has no opinion about what an adapter imports from outside, so any "
        f"module in the tree could import this one with every contract still reported kept. "
        f"That list is unconditional, so this SDK is installed alongside AGL in every environment "
        f"there is and the import would simply work.\n"
        f"\n"
        f"Resolve it by adding the SDK's *import* name to `forbidden_modules` under "
        f"[{VENDOR_SECTION}], plus one `ignore_imports` expression per module permitted to import "
        f"it, in the shape the two already there use. This test guessed that name to be:\n"
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
        f"contract 3 of .importlinter forbids {entry}, which nothing in pyproject.toml's "
        f"[project] dependencies declares.\n"
        f"\n"
        f"A vendor contained but never depended on reads as coverage of an SDK AGL does not have, "
        f"and the adapter it was written for is either gone or was never written. import-linter "
        f"says nothing about it: a forbidden module absent from the graph is dropped in silence, "
        f"which is also what lets this contract keep working while the SDKs are uninstalled.\n"
        f"\n"
        f"Resolve it by removing that line and its `ignore_imports` expressions under "
        f"[{VENDOR_SECTION}], or by restoring the dependency in pyproject.toml that declares it."
    )

def _unlisted_package(name: str) -> str:
    return (
        f"src/agl/adapters/{name}/ is an adapter package that contract 4 of .importlinter does "
        f"not list.\n"
        f"\n"
        f"That contract's `modules =` is a hand-maintained list, so it fails open: an adapter "
        f"missing from it may import any other adapter with every contract still reported "
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
        f"missing from it may import any other adapter with every contract still reported "
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
        f"revisiting, along with tests/test_contract_firing.py and "
        f"tests/test_measurable_targets.py's `_contract`, which resolve a number against that "
        f"file too."
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
    """Every distribution `[project] dependencies` names, by the import name this test expects.

    Nothing is filtered on the way through, and nothing in this list could ask to be. A base
    dependency is unconditional, so an entry naming AGL itself would say only that installing AGL
    requires installing AGL - there is no extra for it to pull in, which is the whole of what a
    self-reference is for. A distribution that turns out not to be a vendor goes in `NOT_A_VENDOR`
    with the reason, where a reader can weigh it, rather than being dropped where nobody sees it go.
    """
    parsed = tomllib.loads(PYPROJECT_FILE.read_text(encoding="utf-8"))
    project = parsed.get("project")
    assert isinstance(project, dict), (
        f"{PYPROJECT_FILE} has no [project] table, so this test cannot tell which distributions "
        f"AGL depends on. Check the path at the top of this file."
    )
    dependencies = project.get("dependencies")
    assert isinstance(dependencies, list) and dependencies, (
        f"{PYPROJECT_FILE} declares no [project] dependencies, which is where a vendor SDK is "
        f"added (ARCHITECTURE.md's \"Vendor containment\"). Either the list moved and this test is "
        f"now comparing contract 3 against nothing, or AGL has stopped depending on a vendor SDK "
        f"at all, in which case contract 3 and this comparison both need revisiting."
    )
    found: dict[str, str] = {}
    for requirement in dependencies:
        distribution = _distribution(str(requirement))
        if not distribution:
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
        f"something else, this test is guarding the wrong thing - and so is "
        f"tests/test_contract_firing.py's probe for that number, which pins the same pairing and "
        f"fails beside this one."
    )

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

def test_every_vendor_sdk_in_project_dependencies_is_contained_by_contract_3() -> None:
    """`pyproject.toml` is where a vendor SDK arrives; contract 3 is what confines it."""
    vendors = _declared_vendors()
    assert vendors, (
        f"{PYPROJECT_FILE}'s [project] dependencies yield no distribution name at all, so this "
        f"test is comparing contract 3 against an empty set and would pass on any listing at all."
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
# Non-vacuity: the three comparisons on fabricated input, so that a refactor which broke one into
# always agreeing fails here instead of passing everywhere. Nothing below reads the repository.
# ---------------------------------------------------------------------------------------------

_FABRICATED_INIT_EXEMPT: Final[Mapping[str, str]] = {"__init__.py": "the package's own docstring"}
_FABRICATED_EXEMPT: Final[Mapping[str, str]] = {"routing.py": "the sanctioned exception"}

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
    """The failure this half exists for: a third SDK added as a dependency and confined nowhere."""
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
    """A dependency that is not a vendor SDK is out of the rule, and says why it is."""
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
    assert "nothing in pyproject.toml's [project] dependencies declares" in problems[0]

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

    assert [len(ports), len(vendors), len(adapters)] == [3, 3, 3]
