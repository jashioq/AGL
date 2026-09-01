"""Structural test: every directory under src/agl/ that holds Python is a package.

**The rule has one clause and it is about importability, not about tidiness.** A directory holding
a `.py` file - at any depth beneath it - is a directory some module's dotted name runs through, so
without an `__init__.py` that name is not a regular package and `agl.<that>.<module>` is not an
import anybody should be relying on. A directory holding no `.py` at all anywhere beneath it cannot
make the tree unimportable, because there is nothing under it to import.

## Why that clause is written here rather than the one that was here before

This file used to assert that **every** directory under `src/agl/` carried an `__init__.py`, full
stop - and the sanctioned prompt layout is a `prompts/` subdirectory of markdown inside the
workflow's own package, which every workflow has and no workflow can import. `fix` and `split` each
carried a `prompts/__init__.py` whose docstring existed to explain that it existed, and
`fix/prompts/__init__.py` assigned the finding rather than living with it: "The finding belongs to
`tests/test_tree.py` rather than to this file: what it means to say is that the tree is
*importable*, and a directory holding no `.py` at all cannot make it otherwise."

**The repair is that restatement and deliberately not a loosening**, which is the distinction that
file also drew - the cheap fix it refused was "editing an assertion to accommodate the thing it
caught". The two are told apart by what they do to a directory that holds Python: a loosening would
have exempted `prompts/` by name, or by "directories with no `__init__.py` we happen to have", and
would have gone on exempting a `src/agl/adapters/postgres/` somebody forgot to make a package.
This clause exempts nothing of the kind. It is *stricter* than its predecessor in the one place
that matters, because `rglob` reaches a directory whose own contents are only subdirectories - a
`src/agl/a/` holding nothing but `b/mod.py` is caught here and was caught before, and would not be
by a rule about `.py` files sitting directly inside.

So the two prompt packages are gone, and that layout needs no apology beside it. Nothing else had
to move: `prompt_file()` resolves a relative path against the directory of the module that called
it, which is `workflows/fix/roles.py`, and a directory does not have to be a package to have a file
in it. `tests/workflows/test_fix.py` and `test_split.py` read both workflows' prompts by importing
their roles, so the resolution is exercised by every one of those files.

**The packaging half was measured rather than reasoned about, and it is a gap in this suite.**
`[tool.hatch.build.targets.wheel] packages = ["src/agl"]` is a rule about a *directory*, not about
importable packages: hatchling copies what is under it. A wheel built with these two files deleted
carries `agl/workflows/fix/prompts/review.md`, `implement.md` and `split`'s two. Nothing in this
suite would notice if that stopped being true, because noticing costs a build; that is stated here
rather than covered, since a workflow whose prompts did not ship would fail at import with
`prompt_file`'s own `InputError` naming the missing path, which is a legible failure and not a
silent one.

## Deleting the `__init__.py` files under `src/` was proposed, measured and refused

The proposal was to delete the twelve zero-byte `__init__.py` files below `src/agl/`, let PEP 420
namespace packages carry the tree, and delete this file with them - keeping only
`src/agl/__init__.py`, which the package-root gate requires to exist. It is refused on the tooling
and not on taste, and the measurement lives here because this file is the assertion somebody
removes in order to do it. A survey that reported "`lint-imports`: fine, all six contracts kept"
reached that answer by measuring a *thirteen*-file deletion, which is a different tree and one the
gates already refuse; everything below is the twelve-file tree, measured twice.

**`grimp` stops descending the moment a directory has no `__init__.py` and something above it
does.** `_get_python_files_and_namespace_dirs_inside_package`, in
`grimp/adaptors/modulefinder.py`, treats the first directory holding an `__init__.py` as a
*portion*, and from there down prunes any directory without one - its own comment calls what it
drops "orphans". `src/agl/__init__.py` stays, so `src/agl` is that portion root and every namespace
subpackage beneath it leaves the graph entirely. `grimp` holds 106 `agl` modules today and 12 with
the twelve deleted, of which three are `agl`'s eight children: `api` and `testing`, which are
single modules, and `sdk`, which carries an `__init__.py` of its own. `lint-imports` - which
reports `Analyzed 141 files, 670 dependencies` and six contracts kept today - then exits 1 on
`Missing layer in container 'agl': module <one of them> does not exist` and evaluates **no contract
at all**. Which one it names varies between runs, the layers being checked in set order, so the
message is not a fingerprint to match on - what is stable is that it stops there. Not five kept and
one broken: a layers contract naming a module the graph does not hold
fails before a single import is looked at, and the other five are never reached. The fourteen
tests `tests/test_contract_firing.py` collects fail with it, that file existing to fire each
contract at the real graph.

**The one tree `grimp` reads correctly is the tree that drops `src/agl/__init__.py` too** - all
eight children back, and the whole package in the graph. That tree fails the package-root gate,
which prints that the file "does not exist. This gate has nothing to check, which is itself wrong."
The gate is not tradable for this, and `.importlinter`'s comment on contract 5 is where the reason
is written: `agl.*` does not include `agl` itself, adding it changes nothing because the pair
(agl, agl.adapters) is skipped as overlapping, so that file - and only that file - could import an
adapter with all six contracts still reported kept. That comment ends "Do not drop that gate."

**`explicit_package_bases` is not the enabler it was taken for; it runs the other way.** With the
twelve deleted, `mypy --strict` passes clean *without* it - over every `.py` under `src` and
`tests` bar those twelve, and no `Duplicate module named "fake"` anywhere - because
`src/agl/__init__.py` is what `_crawl_up_helper` in `mypy/find_sources.py` climbs to, and it names
every module below it against `src`. Turning the flag on replaces that anchor with `MYPYPATH`,
`mypy_path` and the working directory, which makes the repo root the base for everything under
`tests/`, renames those modules `tests.contracts.store` and takes `tests/` off the search path:
68 errors in 29 files, most of them `Cannot find implementation or library stub for module named
"contracts.store"`. That is precisely the resolution `tests/conftest.py`'s first paragraph depends
on, broken by the setting proposed to protect it. The `Duplicate module named "fake"` the survey
reported is real and reproduces only on the thirteen-file deletion - the one that takes
`src/agl/__init__.py` with it.

**Packaging was the one question the survey could not settle, and it is not the obstacle.** Two
wheels built from this tree, before the deletion and after: 114 entries and 102, the difference
exactly the twelve `__init__.py` files and nothing else. The post-deletion wheel installs into a
clean environment and works from outside the repository - every module imports, both
`agl.workflows` entry points resolve and load, both workflows' `prompts/` markdown ships, and the
`agl workflows` console script prints its two names. Recorded so nobody buys that measurement
twice: what refuses the deletion is the import graph, never the distribution.
"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "src" / "agl"

def _directories() -> list[Path]:
    """Every directory in the tree, the root included and `__pycache__` left out.

    `__pycache__` holds no `.py` and would be exempt anyway; it is skipped explicitly so that a
    reader does not have to work that out, and so the exemption does not silently become the only
    thing holding a real directory out of the answer.
    """
    found = [PACKAGE_ROOT, *(path for path in PACKAGE_ROOT.rglob("*") if path.is_dir())]
    return [path for path in found if path.name != "__pycache__"]

def test_every_directory_holding_python_under_src_agl_is_a_package() -> None:
    """A directory some module's dotted name runs through must carry an `__init__.py`.

    `rglob` rather than `glob`, so an intermediate directory that holds only subdirectories is
    covered: `agl/a/b/mod.py` needs `agl/a/__init__.py` as much as it needs `agl/a/b/__init__.py`,
    and only the recursive form sees the first one.
    """
    missing = sorted(
        str(directory.relative_to(PACKAGE_ROOT.parent))
        for directory in _directories()
        if any(directory.rglob("*.py")) and not (directory / "__init__.py").is_file()
    )
    assert not missing, (
        f"these directories hold Python and are not packages: {missing}. Every module underneath "
        f"one of them has a dotted name that runs through a directory the import system does not "
        f"treat as a regular package"
    )

def test_a_directory_holding_no_python_is_left_alone() -> None:
    """The other half of the clause, asserted rather than left as an absence.

    A workflow's prompts live in a `prompts/` subdirectory of its own package, so every workflow
    there will ever be has at least one directory of data files under `src/agl/`. The rule above
    has to be indifferent to those, and a test that only ever asserted the positive would go on
    passing if somebody restored the blanket version - with the evidence being two `__init__.py`
    files nobody could explain, which is how this was found.
    """
    data = [
        directory
        for directory in _directories()
        if not any(directory.rglob("*.py")) and any(directory.iterdir())
    ]
    assert data, (
        "there is no directory of data files under src/agl/ any more, so the clause above is not "
        "being exercised by anything and this test cannot tell a restatement from a loosening"
    )
    for directory in data:
        assert not (directory / "__init__.py").is_file(), (
            f"{directory.relative_to(PACKAGE_ROOT.parent)} holds no Python and carries an "
            f"`__init__.py` anyway. A package that exists to satisfy this file is this file "
            f"asking for something it does not mean"
        )
