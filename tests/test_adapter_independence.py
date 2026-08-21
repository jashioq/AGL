"""Structural test: contract 4 is a hand-maintained list, and this is what notices when it isn't.

Five of the six contracts in `.importlinter` are fail-closed by construction. Contract 3's source
is the whole `agl` tree and contract 5's is `agl.*`, which re-expands as packages are added, so a
package introduced at a later stage is covered the moment it exists and its author need do nothing
to be policed. Contract 4 cannot be written that way. `independence` takes an explicit list of
siblings - there is no expression in import-linter meaning "every child of `agl.adapters`" - so its
`modules =` is a list somebody typed, and it **fails open**: an adapter added at stage 5, 6, 7 or 8
is simply absent from it, free to import any other adapter, with `lint-imports` still reporting six
contracts kept.

**The silence is the defect, not the gap.** A broken contract fails the build and names the import
that broke it; a contract that never heard of your module agrees with everything you do. Stage 0
found this and deferred it to the first stage that adds an adapter, which is this one. Without a
guard here, four stages of adapters would have been written under a rule that was not being
applied to them, and the first sign of it would have been two vendors quietly sharing a helper.

`scripts/check`'s package-root gate is the precedent: a rule `.importlinter` cannot express,
enforced beside it rather than wished into it. This is the second such rule, and it is a test
rather than a shell gate only because what it compares - a parsed config against a walked tree - is
easier to say in Python than in grep.

## The file is the source of truth and the filesystem is the check

Nothing below hardcodes which adapters exist. The listing is parsed out of the real `.importlinter`
and compared against the real `src/agl/adapters/`, because a test carrying its own copy of the
adapter list would be a *second* hand-maintained list, free to drift from the first, and its
agreement would mean only that one person updated both at once. Here the two things being compared
are the artefact that does the policing and the tree it is meant to police, so agreement between
them is the property actually wanted.

## Directories have no way out; single files have exactly one, and it is documented

A directory under `adapters/` is an adapter package: it appears in contract 4 or this test fails.
A top-level `.py` may instead be named in `EXEMPT` below, because two of them are not adapters
standing behind a port - `__init__.py` is the package's docstring, and `routing.py` is contract 4's
one sanctioned exception, whose entire job is dispatching to the vendor runners. The exemption is a
mapping and not a set so that the reason travels with the name and a later reader can weigh it
instead of guessing at it. `system_clock.py` shows the ordinary case: a single-module adapter is
not an exception at all, it is a peer that happens not to need a directory, and it is listed.

**`_process.py` is deliberately not pre-authorised.** Stage 8 may sanction a shared subprocess
helper under `adapters/`; if it does, it comes here and writes the reason. Listing it in advance
would hand that stage the exact silence this test exists to break.

## Why the comparison is a function and not four lines inside the test

`drift` takes sets and returns complaints, touching no disk, so the fabricated tests at the bottom
can hand it a tree and a listing that disagree in each of the ways that matter and watch it say so.
A structural test that reads a repository and finds it consistent looks identical whether it is
checking anything or not; those tests are what tell the difference. The real test additionally
refuses to pass on an empty tree, which is the failure mode of a mistyped path.
"""

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from configparser import ConfigParser
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
ADAPTERS_DIR: Final = REPO_ROOT / "src" / "agl" / "adapters"
CONFIG_FILE: Final = REPO_ROOT / ".importlinter"

# Contract numbers are stable - `.importlinter`'s own header says so, and stage briefs cite them.
CONTRACT_SECTION: Final = "importlinter:contract:4"
PACKAGE: Final = "agl.adapters"

# Top-level `.py` files under `adapters/` that are not adapters to be policed, each with the reason
# it is not. Everything else there belongs in contract 4's `modules =` instead. Do not add an entry
# to spare yourself an edit to `.importlinter`: an exemption here removes a module from the rule,
# while a listing there applies it. Nothing is pre-authorised - notably not `_process.py`, which
# stage 8 may or may not sanction and must decide about in this file if it does.
EXEMPT: Final[Mapping[str, str]] = {
    "__init__.py": "the adapters package's own docstring; no adapter lives in it",
    "routing.py": "contract 4's one sanctioned exception: dispatching on task.model.provider "
    "to the vendor runners is its entire job, so it must import other adapters",
}


def drift(
    listed: AbstractSet[str],
    packages: AbstractSet[str],
    modules: AbstractSet[str],
    exempt: Mapping[str, str],
) -> list[str]:
    """Every disagreement between contract 4's `listed` modules and what is on disk.

    `packages` are directory names under `adapters/`, `modules` are top-level `.py` filenames
    (with the suffix, because that is how `exempt` is keyed). The return is a list of complaints,
    empty when the two agree; each one is written to be read by somebody who has never seen this
    file and says what to do about it rather than only what is wrong.

    Pure: no disk, no config, no repository. The fabricated tests below depend on that.
    """
    problems = [
        _unlisted_package(name) for name in sorted(packages) if f"{PACKAGE}.{name}" not in listed
    ]
    problems += [
        _unlisted_module(filename)
        for filename in sorted(modules)
        if f"{PACKAGE}.{filename.removesuffix('.py')}" not in listed and filename not in exempt
    ]
    on_disk = {f"{PACKAGE}.{name}" for name in packages} | {
        f"{PACKAGE}.{filename.removesuffix('.py')}" for filename in modules
    }
    problems += [_stale_listing(entry) for entry in sorted(listed - on_disk)]
    return problems


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
        f"Resolve it by adding this line to `modules =` under [{CONTRACT_SECTION}]:\n"
        f"    {PACKAGE}.{name}\n"
        f"\n"
        f"A package has no exemption route - EXEMPT in this test is keyed by filename and holds "
        f"only single-file members. An adapter package that genuinely must import another "
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
        f"  1. add `{PACKAGE}.{filename.removesuffix('.py')}` to `modules =` under "
        f"[{CONTRACT_SECTION}] - the answer for an ordinary adapter that happens to be one file "
        f"rather than a directory, as system_clock.py is;\n"
        f'  2. add "{filename}" to EXEMPT in this test with a one-line reason - the answer only '
        f"if the module is not an adapter behind a port at all, or is sanctioned to import other "
        f"adapters the way routing.py is."
    )


def _stale_listing(entry: str) -> str:
    return (
        f"contract 4 of .importlinter lists {entry}, which is not under src/agl/adapters/.\n"
        f"\n"
        f"A contract naming a module that does not exist is quietly protecting nothing: it reads "
        f"as coverage and enforces none, and the next reader counts it as one more adapter held "
        f"to the rule.\n"
        f"\n"
        f"Resolve it by removing that line from `modules =` under [{CONTRACT_SECTION}], or by "
        f"restoring the adapter it names."
    )


def _contract_4() -> Mapping[str, str]:
    """Contract 4's section of the real `.importlinter`, parsed."""
    parser = ConfigParser()
    with CONFIG_FILE.open(encoding="utf-8") as handle:
        parser.read_file(handle)
    assert CONTRACT_SECTION in parser, (
        f"{CONFIG_FILE} has no [{CONTRACT_SECTION}] section. Contract numbers are stable by "
        f"policy - see that file's header - so if contract 4 was renumbered, both the policy and "
        f"this test need revisiting, and every stage brief that cites a contract by number too."
    )
    return parser[CONTRACT_SECTION]


def _listed_modules() -> frozenset[str]:
    """The dotted module names in contract 4's `modules =`, one per line."""
    raw = _contract_4().get("modules")
    assert raw is not None, (
        f"[{CONTRACT_SECTION}] in {CONFIG_FILE} has no `modules =` key. An independence contract "
        f"without one polices nothing; every adapter in the tree is unguarded until it returns."
    )
    return frozenset(line.strip() for line in raw.splitlines() if line.strip())


def _adapters_on_disk() -> tuple[frozenset[str], frozenset[str]]:
    """Directory names and top-level `.py` filenames under `src/agl/adapters/`."""
    children = sorted(ADAPTERS_DIR.iterdir())
    packages = frozenset(p.name for p in children if p.is_dir() and p.name != "__pycache__")
    modules = frozenset(p.name for p in children if p.is_file() and p.suffix == ".py")
    return packages, modules


def test_contract_4_is_still_the_independence_contract() -> None:
    """The section this test parses must be the one it thinks it is."""
    contract_type = _contract_4().get("type")
    assert contract_type == "independence", (
        f"[{CONTRACT_SECTION}] is a `{contract_type}` contract, not `independence`. This test "
        f"reads that section's `modules =` as the list of adapters held apart from each other; "
        f"if contract 4 now means something else, this test is guarding the wrong thing."
    )


def test_every_adapter_appears_in_contract_4() -> None:
    """The tree under `src/agl/adapters/` and contract 4's `modules =` name the same adapters."""
    packages, modules = _adapters_on_disk()
    assert packages and modules, (
        f"{ADAPTERS_DIR} holds no adapter packages or modules at all. This test walked the wrong "
        f"directory and is asserting nothing; check the path at the top of this file."
    )
    problems = drift(_listed_modules(), packages, modules, EXEMPT)
    assert not problems, "\n\n".join(problems)


# ---------------------------------------------------------------------------------------------
# Non-vacuity: `drift` on fabricated input, so that a refactor which broke it into always
# agreeing fails here instead of passing everywhere. Nothing below reads the repository.
# ---------------------------------------------------------------------------------------------

_FABRICATED_EXEMPT: Final[Mapping[str, str]] = {"routing.py": "the sanctioned exception"}


def test_drift_is_silent_when_the_listing_and_the_tree_agree() -> None:
    """The case that makes the failing cases below mean something."""
    assert not drift(
        frozenset({f"{PACKAGE}.git", f"{PACKAGE}.system_clock"}),
        frozenset({"git"}),
        frozenset({"system_clock.py", "routing.py"}),
        _FABRICATED_EXEMPT,
    )


def test_drift_reports_a_package_missing_from_the_listing() -> None:
    """The failure this test exists for: an adapter package added and never listed."""
    problems = drift(
        frozenset({f"{PACKAGE}.git"}),
        frozenset({"git", "xyz"}),
        frozenset(),
        _FABRICATED_EXEMPT,
    )
    assert len(problems) == 1
    assert "src/agl/adapters/xyz/" in problems[0]
    assert f"{PACKAGE}.xyz" in problems[0]
    assert "fails open" in problems[0]


def test_drift_reports_a_module_that_is_neither_listed_nor_exempt() -> None:
    """A single-file adapter is a member, not an exception - it is listed or it is explained."""
    problems = drift(
        frozenset(),
        frozenset(),
        frozenset({"_process.py"}),
        _FABRICATED_EXEMPT,
    )
    assert len(problems) == 1
    assert "src/agl/adapters/_process.py" in problems[0]
    assert f"{PACKAGE}._process" in problems[0]
    assert "EXEMPT" in problems[0]


def test_drift_accepts_a_module_that_is_exempt_with_a_reason() -> None:
    """`routing.py` must import other adapters, so it is out of the contract and out of this."""
    assert not drift(frozenset(), frozenset(), frozenset({"routing.py"}), _FABRICATED_EXEMPT)


def test_drift_reports_a_listing_with_nothing_behind_it() -> None:
    """A contract naming a deleted adapter reads as coverage and enforces none."""
    problems = drift(
        frozenset({f"{PACKAGE}.git", f"{PACKAGE}.gone"}),
        frozenset({"git"}),
        frozenset(),
        _FABRICATED_EXEMPT,
    )
    assert len(problems) == 1
    assert f"{PACKAGE}.gone" in problems[0]
    assert "not under src/agl/adapters/" in problems[0]


def test_drift_reports_every_disagreement_at_once() -> None:
    """Three separate edits are three complaints in one run, not one discovered at a time."""
    problems = drift(
        frozenset({f"{PACKAGE}.gone"}),
        frozenset({"xyz"}),
        frozenset({"_process.py"}),
        _FABRICATED_EXEMPT,
    )
    assert len(problems) == 3
