"""Structural test: no lone surrogate reaches `mypy`'s cache as a `Literal`, over `src` and `tests`.

`tests/sdk/test_journal.py`'s `_LONE_SURROGATE` is written as `chr(0xD800)` and not as the escape
`"\\ud800"`, and the comment above it says why: **a module-level `Final` holding a surrogate
*literal* crashes `mypy --strict` outright.** A `Final` keeps its value as a `Literal` type, mypy
writes that type into its own cache as UTF-8, a lone surrogate has no UTF-8 encoding, and the
process exits with `INTERNAL ERROR` naming no file at all. That is the types gate failing with the
worst diagnostic in the build: no line, no module, no clue which of 234 files moved.

That comment is necessary and it is not sufficient, which is what this file is.

## What the comment cannot do

It sits above one constant. `chr(0xD800)` is an obvious thing to "tidy" back into an escape - it
reads as the long way round of writing a character - and a reader who never opens
`tests/sdk/test_journal.py` never meets the paragraph. Worse, the comment states the rule slightly
narrower than the rule is: it says a module constant, and by that it means the scalar it guards.
Measured against `mypy 2.3.1` on Python 3.14, the crash is wider, and the two other module-level
surrogates in this repository - the `"\\ud800"` in `tests/ports/test_ids.py`'s `_NON_ASCII` and the
one in `tests/ports/_corpus.py`'s `_NON_ASCII` - are safe only by an accident of container choice
that nothing anywhere writes down.

## The boundary, measured rather than reasoned about

Each of these was written to a scratch file and run through the real `.venv/bin/mypy --strict`. The
question a row answers is whether the value's inferred type still holds a `Literal` when the module
is serialised; `reveal_type` is what makes the pattern legible.

| Written as                              | Inferred                          | Verdict |
|-----------------------------------------|-----------------------------------|---------|
| `X: Final = "\\ud800"`                   | `Literal['\\ud800']?`              | crash   |
| `X: Final[str] = "\\ud800"`              | keeps the literal                 | crash   |
| `X: Final = ("\\ud800", "a")`            | `tuple[Literal[...]?, Literal[…]?]` | crash |
| `class K: X: Final = "\\ud800"`          | keeps the literal                 | crash   |
| `class K(StrEnum): A = "\\ud800"`        | an enum member's value            | crash   |
| `def f(x: Literal["\\ud800"]) -> None`   | the annotation itself             | crash   |
| `X: Final = ["\\ud800", "a"]`            | `list[str]`                       | fine    |
| `X: Final = {"\\ud800": 1}`              | `dict[str, int]`                  | fine    |
| `X: Final = frozenset({"\\ud800"})`      | `frozenset[str]`                  | fine    |
| `X: Final[tuple[str, ...]] = ("\\ud800",)` | the declared type                | fine    |
| `X = "\\ud800"` (no `Final`)             | `str`                             | fine    |
| `def f() -> None: X: Final = "\\ud800"`  | a local, never cached             | fine    |
| `X: Final = chr(0xD800)`                 | `str`                             | fine    |
| `X: Final = "\\ud83d\\ude00"`             | two lone surrogates               | crash   |

Two readings fall out. A **join erases a literal and a tuple does not**: a list, a dict and a set
widen their members to `str` on the way in, so the surrogate survives as a value and not as a type,
while a tuple is typed element by element and every element keeps its own `Literal`. And **the cache
is the mechanism, not the checker**: the same file under `--cache-dir=/dev/null` reports success,
which is why nothing about this is visible in an error message.

So both `_NON_ASCII` tables are green because somebody wrote `[` and not `(`. Both are frozen
tables of constants in a repository that reaches for immutability everywhere else -
`tests/sdk/test_tools.py`'s `_VOCABULARY: Final = ("high", "medium", "low")` is the same shape
written the other way - so "make this constant a tuple" is a one-character edit somebody will
eventually propose, and it fails the types gate with no file named.

## Why a test rather than a `scripts/check` gate

`test_ports_stdlib_only.py`'s docstring settles where a rule of this kind goes, and this one lands
on the same side for the same three reasons. The rule needs judgement - which positions keep a
literal is the whole content of the table above, and a grep for `\\ud800` would flag every
docstring in this file. It has to be proved to fire, and here the scan is a pure function over
source text, so the fabricated cases at the bottom hand it the whole table and watch it answer.
And `mypy --strict` covers `tests/` and does not cover a bash heredoc.

## What this does not close

The scan is a fence around the positions that were measured, not a proof about the type checker. A
`Literal` reached some other way - a `TypeVar` bound, a `TypedDict` key's declared type, an alias
assigned to a `Literal[...]` and used elsewhere - would crash and is not read here. Widening it is
the same one-line change `test_filesystem_no_lock.py` describes: a new position goes in
`_cacheable`, and what must not happen instead is a position being taken *out* to make a crash
legal.

It is also silent about a mypy that fixes this. The crash is a bug in a version, not a promise of
the language, and the day it is fixed this file is a rule with no cost behind it - at which point
the honest edit is to delete it and the comment together, and to say in the commit which mypy
release made it safe.

The scan runs over `src` and `tests` both, because that is what the types gate runs over: `mypy
--strict src tests`. `src/` carries no surrogate today and has no reason to; being in the walk costs
one glob and means the rule is stated about the thing the gate actually checks.

Named for the invariant rather than for the module it protects, on
`test_filesystem_no_lock.py`'s reasoning: the rule is about every file mypy caches, and a test
asserting it from inside `tests/sdk/test_journal.py` would be a test about the journal that is not.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

# The two trees `mypy --strict src tests` is pointed at, which is the whole of what gets cached.
TREES: Final = ("src", "tests")

# The surrogate block, by codepoint. A `str` can hold one of these and UTF-8 cannot encode it,
# which is the whole of the bug: a paired-looking `"\ud83d\ude00"` is two of them in Python and
# crashes exactly as one does, while the emoji it looks like is a single ordinary codepoint.
SURROGATE_FIRST: Final = 0xD800
SURROGATE_LAST: Final = 0xDFFF

# Bases that make a class body's assignments enum members, whose values mypy keeps as literals.
# By name alone, the way `test_filesystem_no_lock.py` reads its primitives: `enum.StrEnum` and a
# bare `StrEnum` imported from it are the same declaration.
ENUM_BASES: Final = frozenset({"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag", "ReprEnum"})

# The floor, in the spirit of the hermeticity test's `sessions >= 2`. 105 modules under `src/` and
# 126 under `tests/` when this was written; 150 is a floor and not a measurement, so an ordinary
# edit never moves it and a walk that found the wrong directory cannot clear it.
FILES_TODAY: Final = 150

# What `_cacheable` yields: how the position would read in a complaint, the expression whose type
# is written to the cache, and whether a tuple around a literal there preserves it.
type Position = tuple[str, ast.expr, bool]

@dataclass(frozen=True)
class Finding:
    """One lone surrogate written where `mypy` will keep it as a `Literal` and then cache it.

    `position` is the shape that makes it dangerous rather than the value's own syntax, because
    that is what a reader has to change: the same escape is fine one line lower inside a function
    and fine inside a list on the same line.
    """

    line: int
    position: str
    codepoint: int

def literal_surrogates(source: str) -> list[Finding]:
    """Every lone surrogate in `source` sitting in a position that survives into mypy's cache.

    Pure: takes text, returns findings, touches no disk. The fabricated cases at the bottom of this
    file depend on that, and they are what make the real comparison mean anything.
    """
    tree = ast.parse(source)
    found = {
        Finding(line, position, codepoint)
        for position, value, through_tuples in _cacheable(tree, in_enum=False)
        for line, codepoint in _surrogates_in(value, through_tuples=through_tuples)
    }
    return sorted(found, key=lambda finding: (finding.line, finding.position, finding.codepoint))

def _cacheable(node: ast.AST, *, in_enum: bool) -> Iterator[Position]:
    """Every expression under `node` whose literal type is written to the cache, and how far in.

    The third element says whether a tuple around the literal preserves it, which is the one
    structural distinction the measured table draws: a `Final` scalar and a `Final` tuple both
    crash, a `Final` list does not, and a `Final[...]` with a declared type keeps a literal only
    where the declared type is the scalar itself.

    Function bodies are not descended into and neither are lambdas: a local is checked and thrown
    away, never serialised. A `Literal[...]` annotation is the exception and is read wherever it
    appears, including in the signature of a function whose body is skipped, because an annotation
    is part of the function's own type and that is cached.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Subscript) and _spelled(child.value) == "Literal":
            yield "a `Literal[...]` annotation", child.slice, True
            continue
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _in_signature(child)
            continue
        if isinstance(child, ast.Lambda):
            continue
        if isinstance(child, ast.ClassDef):
            yield from _cacheable(child, in_enum=_is_enum(child))
            continue
        if isinstance(child, ast.AnnAssign) and child.value is not None:
            annotation = _spelled(child.annotation)
            if annotation == "Final":
                yield "a bare `Final` binding", child.value, True
                continue
            if isinstance(child.annotation, ast.Subscript):
                if _spelled(child.annotation.value) == "Final":
                    yield "a `Final[...]` binding", child.value, False
                yield from _cacheable(child.annotation, in_enum=False)
                continue
        if isinstance(child, ast.Assign) and in_enum:
            yield "an enum member", child.value, True
            continue
        yield from _cacheable(child, in_enum=in_enum)

def _in_signature(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[Position]:
    """The annotations on a function, read while its body is not.

    Reached explicitly rather than by descending, so that the rule stays "a body is a local and a
    signature is a type" instead of resting on which node kinds happen to sit where.
    """
    written = [node.annotation for node in ast.walk(function.args) if isinstance(node, ast.arg)]
    for annotation in [*written, function.returns]:
        if annotation is not None:
            yield from _cacheable(ast.Expression(body=annotation), in_enum=False)

def _surrogates_in(value: ast.expr, *, through_tuples: bool) -> Iterator[tuple[int, int]]:
    """Each surrogate codepoint in `value`, with the line it is written on.

    A tuple is walked and nothing else is, which is the measured boundary: a list, a dict and a set
    join their members to `str` on the way in and the literal type is gone before anything is
    cached. `Literal["a", "b"]` arrives here as a tuple too, which is why the same walk serves both.
    """
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        for character in value.value:
            if SURROGATE_FIRST <= ord(character) <= SURROGATE_LAST:
                yield value.lineno, ord(character)
    elif through_tuples and isinstance(value, ast.Tuple):
        for element in value.elts:
            yield from _surrogates_in(element, through_tuples=True)

def _spelled(node: ast.expr) -> str:
    """The name a node spells, by its own last segment: `Final` for `Final` and for `typing.Final`.

    An alias is not resolved. `from typing import Final as F` would go unread, and it is not a
    spelling anything in this repository uses - the same trade `test_filesystem_no_lock.py` makes
    in the other direction, where an import's real name is read and its alias never is.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""

def _is_enum(node: ast.ClassDef) -> bool:
    """Whether a class body's plain assignments are enum members."""
    return any(_spelled(base) in ENUM_BASES for base in node.bases)

def _crashes_the_types_gate(shown: str, finding: Finding) -> str:
    return (
        f"{shown}:{finding.line} writes U+{finding.codepoint:04X}, a lone surrogate, as a string "
        f"literal in {finding.position}.\n"
        f"\n"
        f"mypy keeps that value as a `Literal` type and encodes the type as UTF-8 when it writes "
        f"its cache. A lone surrogate has no UTF-8 encoding, so `mypy --strict src tests` exits "
        f"with INTERNAL ERROR and names no file - the types gate fails with nothing in it to read. "
        f"The same escape one line further in, inside a function body, is fine; so is the same "
        f"escape inside a list, a dict or a set, because those widen their members to `str` before "
        f"anything is cached. A tuple does not: it is typed element by element.\n"
        f"\n"
        f"Write it as `chr(0x{finding.codepoint:04X})`. That is a call and not a literal, so no "
        f"literal type is stored and nothing reaches the encoder; `tests/sdk/test_journal.py`'s "
        f"`_LONE_SURROGATE` is the constant this rule was written for and the comment above it "
        f"has the history. If the value must stay a literal, put it in a list rather than a "
        f"tuple - which is why `tests/ports/test_ids.py` and `tests/ports/_corpus.py` are "
        f"green - or annotate the binding with a declared type rather than a bare `Final`.\n"
        f"\n"
        f"If mypy has since fixed this, the honest edit is to delete this file and that comment "
        f"together and to say which release made it safe. Do not exempt one line."
    )

# --- The real comparison -------------------------------------------------------------------------

def test_no_lone_surrogate_is_written_where_mypy_would_cache_it_as_a_literal() -> None:
    """`src/` and `tests/`, parsed, against the positions measured in this file's docstring.

    Two assertions, and the second is what keeps the first honest. No module writes a surrogate in
    a caching position - which fails for a `Final` scalar, for a `Final` tuple, for a class-level
    `Final`, for an enum member and for a `Literal[...]` annotation, because what is forbidden is
    the position and not the file it is in. And the scan is asserted to have walked both trees, so
    that a version of this file matching nothing could not be green while checking nothing.
    """
    problems: list[str] = []
    walked = 0
    for tree in TREES:
        root = REPO_ROOT / tree
        for source in sorted(root.rglob("*.py")):
            walked += 1
            problems += [
                _crashes_the_types_gate(str(source.relative_to(REPO_ROOT)), finding)
                for finding in literal_surrogates(source.read_text(encoding="utf-8"))
            ]

    assert not problems, "\n\n".join(problems)
    assert walked >= FILES_TODAY, (
        f"only {walked} module(s) were found under {TREES} below {REPO_ROOT}, and there were 231 "
        f"when this was written. Every assertion above is silent about a module holding no "
        f"surrogate, so a walk that found none of them would be green and checking nothing"
    )

def test_the_scan_reaches_the_constant_this_rule_was_written_for() -> None:
    """`tests/sdk/test_journal.py` is in the walk, and its constant is the `chr` spelling.

    Stated as its own assertion because it is the one line the rule exists to protect and the one
    whose rewrite the scan is here to catch. A glob that stopped short of `tests/sdk/`, or a walk
    over `src/` alone, would leave the real comparison above looking identical.
    """
    journal = REPO_ROOT / "tests" / "sdk" / "test_journal.py"
    source = journal.read_text(encoding="utf-8")
    assert "_LONE_SURROGATE: Final = chr(0xD800)" in source, (
        f"{journal} no longer spells its lone surrogate with `chr`. If it was rewritten as the "
        f"escape `\\ud800`, `mypy --strict` will crash with no file named; see this file's "
        f"docstring and the comment above that constant"
    )
    assert not literal_surrogates(source)

# ---------------------------------------------------------------------------------------------
# Non-vacuity: the scan on fabricated source, one case per row of the measured table, so that a
# rewrite which broke it into always answering "nothing here" fails below instead of passing over
# the whole tree. Every source string below writes the surrogate as an escaped escape - `\\ud800`
# in this file, `\ud800` in the text handed to `ast.parse` - so that this module holds no surrogate
# of its own and cannot be the thing it forbids.
# ---------------------------------------------------------------------------------------------

def test_the_scan_reports_a_bare_final_holding_a_surrogate_literal() -> None:
    """The measured crash this whole file is about, in the shape somebody would tidy it into."""
    findings = literal_surrogates('from typing import Final\nX: Final = "\\ud800"\n')
    assert findings == [Finding(2, "a bare `Final` binding", 0xD800)]

def test_the_scan_reports_a_final_with_a_declared_scalar_type() -> None:
    """`Final[str]` does not help - the value is still tracked - and the comment says so."""
    findings = literal_surrogates('from typing import Final\nX: Final[str] = "\\ud800"\n')
    assert findings == [Finding(2, "a `Final[...]` binding", 0xD800)]

def test_the_scan_reports_a_final_tuple_which_is_the_trap_the_comment_does_not_name() -> None:
    """A tuple is typed element by element, so every element keeps its own `Literal`."""
    findings = literal_surrogates('from typing import Final\nX: Final = ("a", "\\ud800")\n')
    assert findings == [Finding(2, "a bare `Final` binding", 0xD800)]

def test_the_scan_reports_a_class_level_final() -> None:
    """A class attribute is cached exactly as a module one is."""
    findings = literal_surrogates(
        'from typing import Final\nclass K:\n    X: Final = "\\ud800"\n'
    )
    assert findings == [Finding(3, "a bare `Final` binding", 0xD800)]

def test_the_scan_reports_an_enum_member() -> None:
    """No `Final` and no annotation: an enum member's value is a stored format either way."""
    findings = literal_surrogates(
        'from enum import StrEnum\nclass K(StrEnum):\n    A = "\\ud800"\n'
    )
    assert findings == [Finding(3, "an enum member", 0xD800)]

def test_the_scan_reports_a_literal_annotation_in_a_signature() -> None:
    """The body is skipped and the annotation is not, because the annotation is the type."""
    findings = literal_surrogates(
        'from typing import Literal\ndef f(x: Literal["\\ud800"]) -> None:\n    return None\n'
    )
    assert findings == [Finding(2, "a `Literal[...]` annotation", 0xD800)]

def test_the_scan_reports_both_halves_of_a_surrogate_pair_written_as_escapes() -> None:
    """`"\\ud83d\\ude00"` is two lone surrogates in Python and crashes exactly as one does."""
    findings = literal_surrogates('from typing import Final\nX: Final = "\\ud83d\\ude00"\n')
    assert findings == [
        Finding(2, "a bare `Final` binding", 0xD83D),
        Finding(2, "a bare `Final` binding", 0xDE00),
    ]

def test_the_scan_is_silent_on_a_final_list_which_is_why_two_files_here_are_green() -> None:
    """`tests/ports/test_ids.py`'s and `tests/ports/_corpus.py`'s `_NON_ASCII`, in miniature."""
    assert not literal_surrogates(
        'from typing import Final\nX: Final = ["\\x85", "\\ud800", "\\ue000"]\n'
    )

def test_the_scan_is_silent_on_a_final_dict_and_a_final_set() -> None:
    """Both join their members to `str` on the way in, which is the same erasure a list makes."""
    assert not literal_surrogates('from typing import Final\nX: Final = {"\\ud800": 1}\n')
    assert not literal_surrogates(
        'from typing import Final\nX: Final = frozenset({"\\ud800"})\n'
    )

def test_the_scan_is_silent_on_a_tuple_with_a_declared_type() -> None:
    """A declared type is what mypy stores, and it holds no literal to encode."""
    assert not literal_surrogates(
        'from typing import Final\nX: Final[tuple[str, ...]] = ("\\ud800",)\n'
    )

def test_the_scan_is_silent_on_a_surrogate_inside_a_function_body() -> None:
    """A local is checked and thrown away. Half the surrogates in this suite are one of these."""
    assert not literal_surrogates(
        'from typing import Final\ndef f() -> str:\n    X: Final = "\\ud800"\n    return X\n'
    )
    assert not literal_surrogates(
        'def f() -> bool:\n    return all(c != "\\ud800" for c in "ab")\n'
    )

def test_the_scan_is_silent_on_a_module_binding_with_no_final() -> None:
    """Without `Final` the inferred type is `str`, and there is no literal to write."""
    assert not literal_surrogates('X = "\\ud800"\nY: str = "\\ud800"\n')

def test_the_scan_is_silent_on_the_chr_spelling_that_is_the_fix() -> None:
    """A call is not a literal, which is the entire reason the workaround works."""
    assert not literal_surrogates("from typing import Final\nX: Final = chr(0xD800)\n")

def test_the_scan_is_silent_on_prose_and_on_ordinary_non_ascii() -> None:
    """A docstring naming the escape is not a literal in a caching position, and neither is 😀.

    The first half is why this rule cannot be a grep: this file's own docstring is full of the
    thing it forbids. The second is the boundary being surrogates and not non-ASCII - the emoji
    that `"\\ud83d\\ude00"` looks like is one ordinary codepoint and encodes fine.
    """
    assert not literal_surrogates(
        "from typing import Final\n"
        '"""A module docstring naming \\ud800."""\n'
        'X: Final = "\\U0001f34c"\n'
    )
