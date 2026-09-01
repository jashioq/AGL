"""Structural test: the blank-line convention in `CLAUDE.md`, over `src/` and `tests/`.

`CLAUDE.md`'s "The blank-line convention" is four clauses and this file is all four of them. The
half that is deliberately *not* here is the sorting: `I001`, configured under `pyproject.toml`'s
`[tool.ruff.lint.isort]`, orders the import block and decides where a separator goes inside it. The
two settings written there - `no-lines-before` and `lines-after-imports` - are there so that the
lint gate and this file never argue about the same blank line, and the comment above them says so
from the other end. Neither half is the convention on its own.

**Layout is the one thing about this source no gate could see.** ruff states most of it itself -
`E301` and `E302` for the gap between two definitions, `E303` for a run of blanks, `E305` for what
follows a body - and every rule in that family is preview-only, so a bare `ruff check` reports none
of them and the select list in `pyproject.toml` does not ask for them. `mypy --strict` has no
opinion about whitespace. `lint-imports` reads a graph. The module size gate counts *code* lines and
scores a blank one zero, so padding a module is the one edit that cannot move it. A tree written
with three blank lines between every definition passes every gate in this build.

## The import block is one contiguous run

No blank line between two import statements. Adjacency is read in `tree.body` and not in the text,
which is what makes an `if TYPE_CHECKING:` block *end* the import block rather than something the
rule reaches across: an `ast.If` is not an import, so the pair it sits between is never compared.
There is no such block under either tree today and the scan must not start misfiring on the first
one written. `from __future__` needs nothing special - it is an ordinary `ImportFrom` at the head of
the body.

**One blank line is permitted, and only immediately above a standalone comment.** This is not a
softening; it is the boundary where the rule would otherwise be fighting the lint gate, and the lint
gate wins. `I001` puts a blank line above a comment inside the import block and puts it straight
back when it is removed, so a version of this rule that forbade it would make the two gates
unsatisfiable together. `tests/instruments/preflight/unused.py` and `tests/workflows/test_fix.py`
are where that shape is written, each comment explaining an import that looks like a mistake.
`test_the_import_scan_is_silent_on_the_blank_line_isort_puts_above_a_comment` is the case that pins
it, and `test_the_import_scan_reports_a_bare_blank_line_between_two_imports` is the other side.

## Two adjacent blank lines never sit between two top-level definitions

**The rule is "no two *adjacent* blanks", and both of the obvious tightenings of it are wrong.**

Not "at most one blank line in the gap". Hundreds of gaps in this tree hold a blank, a `# ---`
section banner and a blank again - the shape `tests/test_naming_convention.py` and this file both
use to divide a module into parts - which is two blank lines that are not next to each other, and
they are the layout the convention asks for rather than a defect in it.

Not "at least one blank line" either. Every `@overload` stack has none: `src/agl/sdk/params.py`'s
`arg` and `src/agl/sdk/tools.py`'s `describe` each write `def f(...) -> T: ...` directly on top of
the next overload and then on top of the implementation, which is idiomatic and reads as one
declaration. A rule demanding a gap would report all four halves of two correct signatures.

**Top-level only.** A gap between two members inside a class is not this rule's business, and
`src/agl/adapters/git/_snapshots.py` is why that has to be said rather than assumed: it holds
several two-blank member gaps, and a scan that walked class bodies would report every one of them.
Blank lines inside a body are judgement, and this convention says nothing about them.

A decorator belongs to the definition below it, so a definition's first physical line is the first
line of its decorator list where it has one. That matters most in the clause below, where the member
under a `class` statement is often a decorated one.

## No blank line under a `class` statement

Walked *upward* from the first physical line of the first member, over comment lines and blank
lines, until the class header's last physical line is reached. Two things make the upward walk the
implementation rather than a test of the line after `node.lineno`. A header spans lines -
`tests/contracts/terminal.py` and `tests/contracts/workspace.py` both write `class C(` over several
- so the line after the `class` keyword is not reliably the one the rule is about. And a comment may
sit between the header and the first member, in which case a blank above *it* is the same defect and
a downward test would pass over it. No class in either tree has a comment there today, so the tree
does not exercise that half and the walk is the only thing covering it;
`test_the_class_scan_reports_a_blank_line_above_a_comment_under_the_header` is where it is checked.

A class docstring is the first member like any other, so the blank line *after* it is a member gap
and out of scope, exactly as the clause above says.

## A file does not start with a blank line

Line one of a non-empty module is not blank. The zero-byte `__init__.py` files under `src/` have no
line one at all and are not sites: they are skipped rather than reported, and they contribute
nothing to the floor, which is what keeps "skipped" from quietly meaning "unchecked".

## The floors, and why every one of the four carries one

`tests/test_naming_convention.py`'s reasoning applies here word for word: every complaint below is
silent about a site with nothing wrong at it, so a scan pointed at the wrong directory - or
rewritten into always answering "nothing here" - would be green over a tree that had abandoned the
convention entirely. So each scan reports the number of sites it looked at as well as the lines it
objects to, and each test asserts both the module count and its own site count against a floor. The
floors are floors and not measurements: an ordinary edit never moves one, and a walk that found the
wrong tree cannot clear one.

## What this does not close

The gap *above* the first statement of a module is not read - only line one is, under the clause
above - so a module opening with a comment and then three blank lines is not reported. Nor are
trailing blank lines at the end of a file, which `ruff`'s `W391` would hold if the select list asked
for it. Blank lines inside a function body are judgement and are deliberately unstated: nothing here
asserts anything about them, and a rule that did would be a different convention.
"""

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

# The two trees the convention governs, which is the whole of the Python in this repository.
TREES: Final = ("src", "tests")

# Floors, in the spirit of the hermeticity test's `sessions >= 2` and of `test_named_not_numbered`'s
# `FILES_TODAY`. Every one of these is well under what the tree holds today, so an ordinary edit
# never moves one and a walk that found the wrong directory cannot clear one.
MODULES_TODAY: Final = 150
IMPORT_PAIRS_TODAY: Final = 1200
TOP_LEVEL_GAPS_TODAY: Final = 4000
CLASS_BODIES_TODAY: Final = 300
FILE_HEADS_TODAY: Final = 150

@dataclass(frozen=True)
class Scan:
    """What one rule saw in one module: the sites it looked at, and the lines it objects to.

    `sites` is the half that makes the other half mean anything. A scan is silent about a clean
    site, so `offending` being empty says nothing on its own about whether anything was read.
    """

    sites: int
    offending: tuple[int, ...]

@dataclass(frozen=True)
class Walk:
    """One scan carried over both trees: modules read, sites examined, and every line reported."""

    modules: int
    sites: int
    found: tuple[tuple[Path, int], ...]

# --- The scans, every one of them a pure function over source text -------------------------------

def blank_lines_splitting_the_import_block(source: str) -> Scan:
    """Every blank line between two adjacent imports, bar the one `I001` puts above a comment.

    A site is a pair of import statements adjacent in `tree.body`, so anything else between two
    imports - an `if TYPE_CHECKING:` block, an `__all__` - ends the block instead of being spanned.
    """
    lines = source.splitlines()
    sites = 0
    offending: list[int] = []
    for one, two in _adjacent(ast.parse(source).body):
        if not isinstance(one, ast.Import | ast.ImportFrom):
            continue
        if not isinstance(two, ast.Import | ast.ImportFrom):
            continue
        sites += 1
        gap = list(_gap(lines, one, two))
        offending += [
            number
            for position, (number, line) in enumerate(gap)
            if not line.strip() and not _introduces_a_comment(gap, position)
        ]
    return Scan(sites, tuple(offending))

def doubled_blank_lines_between_top_level_definitions(source: str) -> Scan:
    """The first line of every run of two or more blank lines in a gap at a module's top level."""
    lines = source.splitlines()
    sites = 0
    offending: list[int] = []
    for one, two in _adjacent(ast.parse(source).body):
        sites += 1
        blank = {number for number, line in _gap(lines, one, two) if not line.strip()}
        offending += [
            number for number in sorted(blank) if number + 1 in blank and number - 1 not in blank
        ]
    return Scan(sites, tuple(offending))

def blank_lines_under_a_class_statement(source: str) -> Scan:
    """Every blank line between a `class` header and the first member of its body.

    Walked upward from the member over comments and blanks, so a header written over several lines
    and a comment sitting under one are both read correctly. See this file's docstring.
    """
    lines = source.splitlines()
    sites = 0
    offending: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef) or not node.body:
            continue
        sites += 1
        cursor = _first_line(node.body[0]) - 1
        while cursor > node.lineno:
            line = lines[cursor - 1]
            if not line.strip():
                offending.append(cursor)
            elif not line.lstrip().startswith("#"):
                break
            cursor -= 1
    return Scan(sites, tuple(sorted(offending)))

def blank_lines_at_the_head_of_a_file(source: str) -> Scan:
    """Whether line one is blank, a file with no line one at all being no site rather than clean."""
    lines = source.splitlines()
    if not lines:
        return Scan(0, ())
    return Scan(1, () if lines[0].strip() else (1,))

# --- The plumbing under them ---------------------------------------------------------------------

def _adjacent(body: list[ast.stmt]) -> Iterator[tuple[ast.stmt, ast.stmt]]:
    """Every consecutive pair of statements in a body, which is where a gap between two lives."""
    return zip(body, body[1:], strict=False)

def _gap(lines: list[str], one: ast.stmt, two: ast.stmt) -> Iterator[tuple[int, str]]:
    """Every physical line strictly between two statements, each with its own line number."""
    for number in range((one.end_lineno or one.lineno) + 1, _first_line(two)):
        yield number, lines[number - 1]

def _first_line(node: ast.stmt) -> int:
    """The first physical line a statement occupies, a decorator counting as part of what it
    decorates."""
    decorated = ast.AsyncFunctionDef | ast.ClassDef | ast.FunctionDef
    if isinstance(node, decorated) and node.decorator_list:
        return min(one.lineno for one in node.decorator_list)
    return node.lineno

def _introduces_a_comment(gap: list[tuple[int, str]], position: int) -> bool:
    """Whether the line after `gap[position]` is a standalone comment, which is `I001`'s blank."""
    rest = gap[position + 1 :]
    return bool(rest) and rest[0][1].lstrip().startswith("#")

def _walked(scan: Callable[[str], Scan]) -> Walk:
    """Every module under `src/` and `tests/` handed to one scan, with what it saw added up."""
    modules = 0
    sites = 0
    found: list[tuple[Path, int]] = []
    for tree in TREES:
        for source in sorted((REPO_ROOT / tree).rglob("*.py")):
            modules += 1
            seen = scan(source.read_text(encoding="utf-8"))
            sites += seen.sites
            found += [(source, line) for line in seen.offending]
    return Walk(modules, sites, tuple(found))

def _check_the_walk_found_the_tree(walk: Walk, *, floor: int, counted: str) -> None:
    """Assert one walk read both trees and that the rule it carried had something to look at."""
    assert walk.modules >= MODULES_TODAY, (
        f"only {walk.modules} module(s) were found under {TREES} below {REPO_ROOT}. Every "
        f"complaint above is silent about a module with nothing wrong in it, so a walk that found "
        f"the wrong directory would be green and checking nothing"
    )
    assert walk.sites >= floor, (
        f"only {walk.sites} {counted}(s) were examined across {walk.modules} module(s), and the "
        f"floor is {floor}. The complaint above is silent about a site that is clean, so a scan "
        f"that found no sites at all would be green over a tree that had stopped following the "
        f"convention entirely"
    )

def _shown(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))

def _splits_the_import_block(path: Path, line: int) -> str:
    return (
        f"{_shown(path)}:{line} is a blank line inside the import block.\n"
        f"\n"
        f"The imports are one contiguous run. The blank line reads as a boundary the sorting does "
        f"not draw - `I001` under pyproject.toml's [tool.ruff.lint.isort] is told "
        f"`no-lines-before` for every section precisely so that it draws none - and the next "
        f"reader takes the two halves for two groups that mean something.\n"
        f"\n"
        f"Delete it. The one exception is a blank line directly above a standalone comment inside "
        f"the block, which isort mandates and re-adds the moment it is removed; that one is "
        f"permitted here and is not what this is reporting."
    )

def _doubles_a_top_level_gap(path: Path, line: int) -> str:
    return (
        f"{_shown(path)}:{line} is the first of two or more blank lines between two top-level "
        f"statements.\n"
        f"\n"
        f"One blank line between top-level definitions, not two. Two is PEP 8's spacing and this "
        f"repository does not use it: the file is read as a whole and the wider gap buys nothing "
        f"the single one does not.\n"
        f"\n"
        f"Delete the extra one. A gap holding a blank, a `# ---` section banner and a blank again "
        f"is *not* this - those two blanks are not adjacent, they are how a module is divided into "
        f"parts, and hundreds of them are correct. Neither is an `@overload` stack written with no "
        f"gap at all, which this rule does not ask for."
    )

def _sits_under_a_class_statement(path: Path, line: int) -> str:
    return (
        f"{_shown(path)}:{line} is a blank line between a `class` statement and the first member "
        f"of its body.\n"
        f"\n"
        f"A class header and what it opens are one thing, and a gap between them reads as though "
        f"the member below belongs to something else. The docstring, the first attribute or the "
        f"first method goes directly under the header.\n"
        f"\n"
        f"Delete it. If the blank is above a comment that is above the first member, it is the "
        f"same defect and the comment moves up with the member rather than the blank staying. The "
        f"blank line *after* a class docstring is a gap between two members and is not this."
    )

def _pushes_a_file_down(path: Path, line: int) -> str:
    return (
        f"{_shown(path)}:{line} is blank, and it is the first line of the file.\n"
        f"\n"
        f"A module opens on its docstring or its first import. A leading blank line is invisible "
        f"in a diff, survives every other gate in this build, and is the one whitespace defect a "
        f"reader never sees while editing the part of the file they came for.\n"
        f"\n"
        f"Delete it. An empty file has no first line and is not reported here: the zero-byte "
        f"`__init__.py` files under src/ are packages and nothing else, and tests/test_tree.py is "
        f"what has an opinion about them."
    )

# --- The real comparisons ------------------------------------------------------------------------

def test_no_blank_line_splits_an_import_block_except_before_a_comment_isort_mandates() -> None:
    """`src/` and `tests/`, parsed, against the contiguous import block and its one carve-out.

    The carve-out is the whole reason this clause is stated the way it is: `I001` mandates a blank
    above a comment inside the block, so forbidding it would put this test in a fight with the lint
    gate that the lint gate wins on the next `ruff check`.
    """
    walk = _walked(blank_lines_splitting_the_import_block)
    problems = [_splits_the_import_block(path, line) for path, line in walk.found]
    assert not problems, "\n\n".join(problems)
    _check_the_walk_found_the_tree(walk, floor=IMPORT_PAIRS_TODAY, counted="adjacent import pair")

def test_no_two_adjacent_blank_lines_sit_between_two_top_level_definitions() -> None:
    """`src/` and `tests/`, parsed, against one blank line between definitions rather than two.

    Adjacent, not "at most one in the gap": a blank, a section banner and a blank is the layout the
    convention asks for and is written hundreds of times over. Top-level, not every body: the
    member gaps in `adapters/git/_snapshots.py` are out of scope and are not defects.
    """
    walk = _walked(doubled_blank_lines_between_top_level_definitions)
    problems = [_doubles_a_top_level_gap(path, line) for path, line in walk.found]
    assert not problems, "\n\n".join(problems)
    _check_the_walk_found_the_tree(walk, floor=TOP_LEVEL_GAPS_TODAY, counted="top-level gap")

def test_no_class_statement_is_followed_by_a_blank_line_before_its_first_member() -> None:
    """`src/` and `tests/`, parsed, against the gap under a `class` header.

    Read by walking up from the member, because the header is not reliably one line and a comment
    may sit under it. Neither shape is a defect; both make the line the rule is about somewhere
    other than the one after the `class` keyword.
    """
    walk = _walked(blank_lines_under_a_class_statement)
    problems = [_sits_under_a_class_statement(path, line) for path, line in walk.found]
    assert not problems, "\n\n".join(problems)
    _check_the_walk_found_the_tree(walk, floor=CLASS_BODIES_TODAY, counted="class body")

def test_no_module_under_src_or_tests_begins_with_a_blank_first_line() -> None:
    """`src/` and `tests/`, read, against the first line of every module that has one.

    The zero-byte `__init__.py` files have no first line and are not sites. They are skipped rather
    than passed, so they do not count towards the floor either.
    """
    walk = _walked(blank_lines_at_the_head_of_a_file)
    problems = [_pushes_a_file_down(path, line) for path, line in walk.found]
    assert not problems, "\n\n".join(problems)
    _check_the_walk_found_the_tree(walk, floor=FILE_HEADS_TODAY, counted="module with a first line")

# ---------------------------------------------------------------------------------------------
# Non-vacuity: every scan above on fabricated source, one case for the edit each clause exists to
# catch and one for each boundary a later reader would tighten by mistake, so that a rewrite which
# broke a scan into always answering "nothing here" fails below instead of passing over both trees.
# ---------------------------------------------------------------------------------------------

def test_the_import_scan_reports_a_bare_blank_line_between_two_imports() -> None:
    """The defect the clause exists for, and the site count that says it looked at the pair."""
    assert blank_lines_splitting_the_import_block("import ast\n\nimport re\n") == Scan(1, (2,))

def test_the_import_scan_is_silent_on_the_blank_line_isort_puts_above_a_comment() -> None:
    """The carve-out, which is where this rule stops rather than where it is soft."""
    assert blank_lines_splitting_the_import_block(
        "import ast\n\n# Imported and never called: the line this module is about.\nimport re\n"
    ) == Scan(1, ())

def test_the_import_scan_stops_at_a_statement_that_is_not_an_import_at_all() -> None:
    """An `if TYPE_CHECKING:` block ends the import block; there is none in the tree to prove it."""
    assert blank_lines_splitting_the_import_block(
        "import ast\n\nif TYPE_CHECKING:\n    import re\n\nimport sys\n"
    ) == Scan(0, ())

def test_the_gap_scan_reports_two_adjacent_blanks_and_spares_two_a_banner_divides() -> None:
    """Both boundaries of the clause in one place, since it is the pair that states the rule."""
    assert doubled_blank_lines_between_top_level_definitions(
        "def one() -> None: ...\n\n\ndef two() -> None: ...\n"
    ) == Scan(1, (2,))
    assert doubled_blank_lines_between_top_level_definitions(
        "def one() -> None: ...\n\n# --- A banner ---\n\ndef two() -> None: ...\n"
    ) == Scan(1, ())

def test_the_gap_scan_is_silent_on_an_overload_stack_written_with_no_gap() -> None:
    """`sdk/params.py`'s `arg` and `sdk/tools.py`'s `describe`, which have no blank between them."""
    assert doubled_blank_lines_between_top_level_definitions(
        "@overload\ndef arg(one: int) -> int: ...\n@overload\ndef arg(one: str) -> str: ...\n"
    ) == Scan(1, ())

def test_the_gap_scan_reads_a_decorator_as_the_first_line_of_what_it_decorates() -> None:
    """The two blanks are the gap, and the decorator is the definition below rather than in it."""
    assert doubled_blank_lines_between_top_level_definitions(
        "def one() -> None: ...\n\n\n@cache\ndef two() -> None: ...\n"
    ) == Scan(1, (2,))

def test_the_gap_scan_does_not_reach_the_member_gaps_inside_a_class_body() -> None:
    """`adapters/git/_snapshots.py` holds these, and reporting them would be a different rule."""
    assert doubled_blank_lines_between_top_level_definitions(
        "class Held:\n    one = 1\n\n\n    two = 2\n"
    ) == Scan(0, ())

def test_the_class_scan_reports_a_blank_line_between_a_header_and_its_first_member() -> None:
    """The defect the clause exists for, on the shortest class that can hold it."""
    assert blank_lines_under_a_class_statement("class Held:\n\n    one = 1\n") == Scan(1, (2,))

def test_the_class_scan_reports_a_blank_line_above_a_comment_under_the_header() -> None:
    """The half no class in either tree exercises, and the reason the walk goes upward."""
    assert blank_lines_under_a_class_statement(
        "class Held:\n\n    # A note about the member below.\n    one = 1\n"
    ) == Scan(1, (2,))

def test_the_class_scan_is_silent_where_the_header_itself_is_written_over_several_lines() -> None:
    """`tests/contracts/terminal.py` and `workspace.py` write one, and neither is a defect."""
    assert blank_lines_under_a_class_statement(
        "class Held(\n    Base,\n):\n    one = 1\n"
    ) == Scan(1, ())

def test_the_class_scan_leaves_the_blank_line_after_a_class_docstring_alone() -> None:
    """A docstring is the first member, so the gap under it is a member gap and is not this rule."""
    assert blank_lines_under_a_class_statement(
        'class Held:\n    """What this is."""\n\n    one: int\n'
    ) == Scan(1, ())

def test_the_file_head_scan_reports_a_leading_blank_and_gives_an_empty_file_no_site() -> None:
    """The zero-byte `__init__.py` files are the second half: skipped, and not counted as clean."""
    assert blank_lines_at_the_head_of_a_file("\nimport ast\n") == Scan(1, (1,))
    assert blank_lines_at_the_head_of_a_file("import ast\n") == Scan(1, ())
    assert blank_lines_at_the_head_of_a_file("") == Scan(0, ())
