"""Structural test: every directory under src/agl/ that holds Python is a package.

**The rule has one clause and it is about importability, not about tidiness.** A directory holding
a `.py` file - at any depth beneath it - is a directory some module's dotted name runs through, so
without an `__init__.py` that name is not a regular package and `agl.<that>.<module>` is not an
import anybody should be relying on. A directory holding no `.py` at all anywhere beneath it cannot
make the tree unimportable, because there is nothing under it to import.

**The clause is a restatement and deliberately not a loosening**, and the two are told apart by
what they do to a directory that holds Python: a loosening would have exempted a directory by name,
or by "directories with no `__init__.py` we happen to have", and would have gone on exempting a
`src/agl/adapters/postgres/` somebody forgot to make a package. This clause exempts nothing of the
kind. It is *stricter* than a rule about `.py` files sitting directly inside, because `rglob`
reaches a directory whose own contents are only subdirectories - a `src/agl/a/` holding nothing but
`b/mod.py` is caught here and would not be by that one.

## The other half of the clause is currently unexercised, and this is the note to act on

The clause has two halves and only the positive one is asserted below. The negative half - *a
directory holding no Python is left alone* - had a test of its own, and that test asserted first
that some data-only directory existed to exercise it, because a rule with nothing in its scope
cannot tell a restatement from a loosening. **`src/agl/` now holds no such directory.** The only
two were `workflows/fix/prompts/` and `workflows/split/prompts/`, and they went when AGL stopped
shipping workflows; the test could not pass against a tree with nothing for it to be about, so it
was deleted rather than weakened into one that would pass on an empty set.

**What is lost, in the terms somebody would need to restore it.** Nothing now notices if the
positive clause is widened back into the blanket "every directory under `src/agl/` carries an
`__init__.py`" that this file used to assert - the widening would be green, because the tree it
would wrongly catch is empty. So: **the moment a directory of data files appears under `src/agl/`
again, the negative half has a subject and should come back with it.** It is six lines - collect
the directories with no `.py` anywhere beneath them and some content, assert the collection is
non-empty, then assert none of them carries an `__init__.py`. The workspace stage puts workflows
under `~/.agl/workspace/workflows/` rather than here, so this may stay unexercised for good; that
is the outcome to check before assuming the guard is merely missing.

## Deleting the `__init__.py` files under `src/` was proposed, measured and refused

The proposal was to delete the zero-byte `__init__.py` files below `src/agl/` - twelve of them when
this was measured, eleven now that the workflows package has gone - let PEP 420 namespace packages
carry the tree, and delete this file with them, keeping only `src/agl/__init__.py`, which the
package-root gate requires to exist. It is refused on the tooling and not on taste, and the
measurement lives here because this file is the assertion somebody removes in order to do it. A
survey that reported "`lint-imports`: fine, every contract kept" reached that answer by measuring a
deletion that took `src/agl/__init__.py` too, which is a different tree and one the gates already
refuse; everything below is the tree that keeps it, measured twice.

**Every number in this section was taken while AGL still shipped `fix` and `split`**, and they are
left as measured rather than re-derived against a tree nobody has run the experiment on. What the
section is for is the *shape* of the result, and no count below carries it.

**`grimp` stops descending the moment a directory has no `__init__.py` and something above it
does.** `_get_python_files_and_namespace_dirs_inside_package`, in
`grimp/adaptors/modulefinder.py`, treats the first directory holding an `__init__.py` as a
*portion*, and from there down prunes any directory without one - its own comment calls what it
drops "orphans". `src/agl/__init__.py` stays, so `src/agl` is that portion root and every namespace
subpackage beneath it leaves the graph entirely. `grimp` held 106 `agl` modules then and 12 with
the twelve deleted, of which three were `agl`'s children: `api` and `testing`, which are single
modules, and `sdk`, which carries an `__init__.py` of its own. `lint-imports` - which reports
`Analyzed 131 files, 652 dependencies` and five contracts kept today - then exits 1 on
`Missing layer in container 'agl': module <one of them> does not exist` and evaluates **no contract
at all**. Which one it names varies between runs, the layers being checked in set order, so the
message is not a fingerprint to match on - what is stable is that it stops there. Not four kept and
one broken: a layers contract naming a module the graph does not hold
fails before a single import is looked at, and the rest are never reached. Every test
`tests/test_contract_firing.py` collects fails with it, that file existing to fire each
contract at the real graph.

**The one tree `grimp` reads correctly is the tree that drops `src/agl/__init__.py` too** - all
eight children back, and the whole package in the graph. That tree fails the package-root gate,
which prints that the file "does not exist. This gate has nothing to check, which is itself wrong."
The gate is not tradable for this, and `.importlinter`'s comment on contract 5 is where the reason
is written: `agl.*` does not include `agl` itself, adding it changes nothing because the pair
(agl, agl.adapters) is skipped as overlapping, so that file - and only that file - could import an
adapter with every contract still reported kept. That comment ends "Do not drop that gate."

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
wheels built from the tree of the day, before the deletion and after: 114 entries and 102, the
difference exactly the twelve `__init__.py` files and nothing else. The post-deletion wheel
installed into a clean environment and worked from outside the repository - every module imported,
both shipped workflows' entry points resolved and loaded, their `prompts/` markdown shipped, and
the `agl workflows` console script printed their names. Recorded so nobody buys that measurement
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

