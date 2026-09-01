"""Structural test: the naming convention in `CLAUDE.md`, over `src/` and `tests/`.

`CLAUDE.md`'s "The naming convention" is nine rules, and it says which mechanism holds each. Casing
is ruff's, and selecting `pep8-naming` as `N` in `pyproject.toml` is what put it there - N801 for
classes, N802 for functions, N803 for arguments, N806 for locals, N815 for class attributes.
Mirroring a vendor's spelling, letting parallel siblings share names, spelling words out and the
8-to-14-word target are a reviewer's, and are labelled as such. **This file is the six in between:
N1, N2, N3's `adapters/` half, N5, N8's floor and N9.** Each compares one thing in the source
against another thing in the source, which is the shape `tests/test_contract_listings.py`'s
docstring settles as a test rather than a `scripts/check` gate: it needs judgement, it has to be
proved to fire, and `mypy --strict` covers `tests/` and does not cover a bash heredoc.

**The rule this file exists for is the one that already rotted once.** `adapters/git/_trees.py`
held `def made(directory: Path) -> None` - a past participle naming an action - through a pass
whose whole job was to find them, because the pass was carrying a list of exceptions that spelled
the irregular participles with a leading underscore and `made` was written without one. Nothing
below is a rule somebody could not have followed by hand. Every one of them is a rule somebody did
not.

## N1 - a past participle never names a function returning `None`

Grammar states the contract: `_verb() -> None` acts, `_participle() -> X` transforms, `_noun() -> X`
derives. So the head word of a function whose annotated return is `None` must not be a participle -
`made(...)` reads as a value and is a `mkdir`.

The head word and not every word, because a participle is perfectly good English further in: a
`_write_recorded_entry` would modify a noun with one and would not be the mistake. Three function
names under `src/` carry a word past the first that ends in `-ed` - `adapters/git/fake.py`'s
`_still_unresolved`, `config/toml_file.py`'s `check_unregistered` and
`sdk/_engine/integration.py`'s `_gate_refused` - and not one of the three returns `None`, so the
two readings agree on this tree; they are not the same rule, and the head is the one N1 states.

**Two exclusion sets, and they are part of the rule rather than data behind it.**

*Verbs whose past participle is spelled the same as the base form.* `run`, `split`, `read`, `set`,
`put`, `cut`, `let`, `hit`, `spread`, `cost`, `hurt`. `api.run`, `testing.run`, `workflows/split`'s
`split` and `system_clock`'s `set_to` are imperatives, and no scan can tell them from participles,
because in English there is nothing to tell. This is the rule's honest limit: a genuine
`read() -> None` that meant *having been read* would go unreported, and saying so is the point. The
set is the closed English class and not the members that happen to be in the tree - `run`, `split`
and `set` are the only three that fire today.

*Words ending in `-ed` that are not participles at all.* `feed`, `seed`, `need`, `speed`, `exceed`,
`proceed`, `succeed`. `openai/_session.py`'s `_feed` is the one that fires, and without this set the
rule would report it.

Irregular participles are listed in both spellings, bare and underscored, which is the miss that
let `made` through. The scan strips the underscores off a name before it reads the head, so a
single entry covers both, and `_made` cannot be legal where `made` is not.

## N2 - `_check_x` raises, `_checked_x` returns

Both directions, because half of it is not a rule: every private `_check…` has an annotated return
of `None`, and every private `_checked…` has an annotated return that is not. Seven and seven
today, and both sets are asserted non-empty, since a scan that found neither family would be green
over a tree that had abandoned the convention entirely.

Private, which is where the convention states it. The public `check_ready` on `AgentRunner` and its
five implementations conform, and `config/toml_file.py`'s `check_unregistered` does not - it raises
`ConflictError` and returns the `Path` it validated. That is a name on a module's own surface, read
by its callers rather than by whoever is editing the module, and widening this rule to reach it
would be deciding a question this file was not asked. `git/_snapshots.py`'s `checkout_of` is the
other reason the head word is compared whole rather than by prefix: `checkout` is a git noun, and a
`startswith("check")` draft reported it.

## N3 - a private adapter module is private to its package

`adapters/<pkg>/_x.py` is not on the surface `<pkg>` promises, so no module outside
`src/agl/adapters/<pkg>/` may import `agl.adapters.<pkg>._<anything>`. Sixteen private modules
today and no leaks.

Imports are parsed and not grepped, because `from agl.adapters.git._runner import GitRunner` and
`import agl.adapters.git._runner` are two syntaxes for one thing and a third spelling would be
along shortly. Relative imports are resolved rather than skipped, on
`test_ports_stdlib_only.py`'s reasoning: there are none under `src/` today, and a scan that ignored
every dotted import because of that would be a hole shaped exactly like the one it exists to close.

**Why this is a test and not a seventh `.importlinter` contract.** import-linter could express it -
`protected` is the contract type - and the cost is not in writing it. `CLAUDE.md`, and
`tests/test_contract_listings.py` and `tests/test_contract_firing.py` in their docstrings and in
their data, all argue about *the six*. A seventh means editing every one of those to say seven, and
`CLAUDE.md`'s own instruction to refer to gates by name and never by number is the warning that a
count is the thing that goes stale. The strength is identical either way. So it lands here, next to
the five other rules about what the source says.

**The other half of N3 is not here and cannot be.** `sdk/_engine/`'s seven modules are imported
freely by `api`, by `config` and by `sdk`'s own modules: the underscore there names the *workflow
author's* surface, not the framework's, so there is no import that would be a violation and nothing
for a scan to find. It is stated in prose instead, in `ARCHITECTURE.md`'s `sdk/` paragraph. The two
halves of the rule mean different things, which is why one is mechanical and the other is not.

## N5 - a type defined in `ports/` is not redefined

Fifty-five classes and type aliases are defined at module level under `src/agl/ports/`, and no
module elsewhere under `src/agl/` defines a name from that list. One name per concept: `ports/` is
the ring everything imports, so a second `Text` or a second `Conflict` in an adapter is two things
one word means, and every reader after that has to check which. `rich_terminal/_display.py` and
`_render.py` import `rich.text.Text` as `RichText` for exactly that reason.

## N8 - a test name is a sentence

Over the 1,480 `test_*` functions under `tests/`. The convention says 8 to 14 words, and **that is a
target rather than the corpus**: measured, the distribution runs 4:10, 5:14, 6:39, 7:78, 8:129,
9:164, 10:217, 11:241, 12:240, 13:176, 14:98, 15:54, 16:15, 17:5, so 215 of 1,480 sit outside it.
Asserting it would fail on 215 names that are not defects, and there is no version of "mostly
8 to 14" a test can hold. **8 to 14 is judgement a reviewer applies, and this test does not apply
it.**

What is asserted is the floor that holds: at least four words after `test_`. Ten tests sit exactly
on it - `test_a_role_is_frozen`, `test_both_types_are_frozen` and eight of that shape - so it is a
tight gate rather than a generous one, and the next `test_it_works` fails it. Three words cannot be
a subject, a verb and an object, which is the whole of what "reads as a claim" requires.

## N9 - constants are `SCREAMING_SNAKE` and `Final`

Two things are asserted about module-level bindings under `src/`, and the first is the stronger.
**Every one of the 269 is annotated `Final`.** There is no module-level mutable state in AGL and
this is where that is written down: a bare `X = 5` fails, and so does `X: str = "a"`. The other 93
module-level assignments are all `__all__`, which is a dunder and a Python protocol rather than a
constant, and is exempt by name.

Second, the name: `SCREAMING_SNAKE`, with one leading underscore where it is private. **Two
bindings are exempt and they are listed by dotted name at the top of this file** -
`workflows/fix/findings.py`'s `report_findings` and `workflows/split/chunks.py`'s `report_chunks`,
each a `Final` holding a `ReportingTool` whose wire name is the string on the line below it. The
binding is spelled the way the model calls it. That is the convention's own "mirror the vendor
exactly and never translate" pointed at a tool name rather than at a protocol method, and the
exemption is keyed by the whole dotted name so that a third one arrives as a failure and not as a
coincidence.

Type aliases are `CamelCase`, all 22 of them. **Classes are not checked here**: ruff's N801 covers
them under `pep8-naming` and a second copy would be a rule with two spellings free to disagree.

## What this does not close

`tests/` is held to N8 and to nothing else. Thirty-nine helpers there are named with participles
over a `-> None` return - `qualified`, `unstaffed`, `flagged`, `_landed_children` - and they are
fixtures and stand-ins named for the state they arrange rather than for what they do, which is a
different corpus and would be a different rule. N9 is `src/`-only for the same reason: a test module
binds fabricated data at module level, and holding that to `Final` is not this convention.

Two test modules import a private adapter module on purpose - `tests/adapters/test_git_changes.py`
and `tests/adapters/test_git_runner.py` - which is a test of the private module and exactly what
`tests/` is for. So N3's walk is `src/`-only, and the rule it states is about the framework's own
imports.

Neither half of N1's exclusion sets can be complete, and both are meant to be widened rather than
narrowed - `test_filesystem_no_lock.py`'s sentence about its own closed set applies here word for
word: the next irregular participle goes in as a string, and what must not happen instead is an
entry being taken out to make a name legal.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SOURCE_ROOT: Final = REPO_ROOT / "src"
TESTS_ROOT: Final = REPO_ROOT / "tests"
PACKAGE_ROOT: Final = SOURCE_ROOT / "agl"
PORTS_DIR: Final = PACKAGE_ROOT / "ports"
ADAPTERS_DIR: Final = PACKAGE_ROOT / "adapters"

# Verbs whose past participle is spelled the same as the base form. A head word from this set is
# not reported, because nothing in the text says which of the two it is - see this file's docstring
# for why that is the rule's limit rather than a gap in it.
SAME_AS_BASE: Final = frozenset(
    {"run", "split", "read", "set", "put", "cut", "let", "hit", "spread", "cost", "hurt"}
)

# Words that end in `-ed` and are not participles. `openai/_session.py`'s `_feed` is the one that
# fires; the rest are the same trap waiting.
NOT_PARTICIPLES: Final = frozenset(
    {"feed", "seed", "need", "speed", "exceed", "proceed", "succeed"}
)

# The irregular participles, which is the half that rotted: `made` sat in `adapters/git/_trees.py`
# through a pass looking for exactly this, because the list it carried held `_made` and the name
# was written bare. Underscores are stripped before the head is read, so one entry covers both.
IRREGULAR_PARTICIPLES: Final = frozenset(
    {
        "held", "built", "kept", "left", "sent", "told", "written", "drawn", "taken", "given",
        "made", "found", "known", "shown", "spent", "gone", "done", "lost", "meant", "paid",
        "said", "sold", "won", "brought", "bought", "caught", "taught", "thought", "sought",
    }
)

# `__all__` is a Python protocol and not a constant AGL named. Every module-level assignment under
# `src/` that is not annotated is one of these.
PROTOCOL_BINDINGS: Final = frozenset({"__all__"})

# The two module-level constants deliberately not `SCREAMING_SNAKE`, by dotted name. Each holds a
# `ReportingTool` and is spelled the way the model calls the tool, which is the string on the line
# below it. Keyed whole so that a third arrives as a failure rather than as a coincidence.
WIRE_NAMED_CONSTANTS: Final = frozenset(
    {
        "agl.workflows.fix.findings.report_findings",
        "agl.workflows.split.chunks.report_chunks",
    }
)

# The floor under a name that is meant to read as a claim. Four is where ten tests already sit, so
# it fires on the next three-word name; 8 to 14 is the target a reviewer applies and is not here.
WORD_FLOOR: Final = 4

# Floors, in the spirit of the hermeticity test's `sessions >= 2`. Every assertion below is silent
# about a module holding nothing to complain about, so each walk is asserted to have found the tree
# it was pointed at. Measured today: 106 modules under `src/`, 128 under `tests/`, 1,480 test
# functions, 55 names in `ports/`, 16 private adapter modules, 269 constants and 22 type aliases.
SOURCE_MODULES_TODAY: Final = 80
TEST_MODULES_TODAY: Final = 100
TEST_FUNCTIONS_TODAY: Final = 1200
PORTS_NAMES_TODAY: Final = 40
PRIVATE_ADAPTER_MODULES_TODAY: Final = 12
CONSTANTS_TODAY: Final = 200
TYPE_ALIASES_TODAY: Final = 15
CHECK_FAMILY_TODAY: Final = 5

@dataclass(frozen=True)
class Finding:
    """One name a scan objects to, with the line it is written on."""

    line: int
    name: str

@dataclass(frozen=True)
class CheckFunction:
    """One private function whose head word is `check` or `checked`, and what it does about it.

    `promises_a_value` is what the *name* says - `_checked…` rather than `_check…`.
    `returns_a_value` is what the *signature* says. N2 is the assertion that they agree.
    """

    line: int
    name: str
    promises_a_value: bool
    returns_a_value: bool

# --- The scans, every one of them a pure function over source text -------------------------------

def past_participles_naming_a_procedure(source: str) -> list[Finding]:
    """Every function in `source` whose annotated return is `None` under a participle's name."""
    return [
        Finding(node.lineno, node.name)
        for node in _functions(source)
        if _returns_none(node) and is_past_participle(_head(node.name))
    ]

def is_past_participle(word: str) -> bool:
    """Whether one word names a state rather than an action, by the two sets above.

    Underscores are stripped first, so `made` and `_made` are one entry and the miss that let
    `made` through cannot recur. A word in either exclusion set is not a participle here whatever
    it is in English: the first set holds words that are both, the second words that are neither.
    """
    bare = word.strip("_").lower()
    if not bare or bare in SAME_AS_BASE or bare in NOT_PARTICIPLES:
        return False
    return bare in IRREGULAR_PARTICIPLES or bare.endswith("ed")

def private_check_functions(source: str) -> list[CheckFunction]:
    """Every private `_check…` and `_checked…` in `source`, with what its name and signature say.

    Compared by head *word* and not by prefix: `checkout_of` is a git noun and a
    `startswith("check")` draft reported it.
    """
    found: list[CheckFunction] = []
    for node in _functions(source):
        if not node.name.startswith("_"):
            continue
        head = _head(node.name)
        if head in ("check", "checked"):
            found.append(
                CheckFunction(node.lineno, node.name, head == "checked", not _returns_none(node))
            )
    return found

def private_module_leaks(source: str, *, package: str, private: frozenset[str]) -> list[Finding]:
    """Every import in `source` naming a module in `private` that `package` is not inside.

    `private` is dotted module names - `agl.adapters.git._runner` - and an import of anything under
    one counts, so a submodule of a private module cannot be the way round it.
    """
    return [
        Finding(line, imported)
        for line, imported in _imports(source, package=package)
        for held in private
        if (imported == held or imported.startswith(f"{held}."))
        and package != held.rsplit(".", 1)[0]
    ]

def module_level_type_names(source: str) -> list[Finding]:
    """Every class and `type` alias defined at `source`'s module level, in the order written."""
    found: list[Finding] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef):
            found.append(Finding(node.lineno, node.name))
        elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            found.append(Finding(node.lineno, node.name.id))
    return found

def short_test_names(source: str) -> list[Finding]:
    """Every `test_*` function in `source` whose name is fewer than `WORD_FLOOR` words long."""
    return [
        Finding(node.lineno, node.name)
        for node in _functions(source)
        if node.name.startswith("test_") and len(_words_after_the_prefix(node.name)) < WORD_FLOOR
    ]

def module_constants(source: str) -> list[tuple[Finding, bool]]:
    """Every module-level binding in `source` that is not a protocol dunder, and whether it is
    `Final`.

    A `type` alias is a statement of its own and is not one of these; it is read by
    `module_type_aliases` below. Both the annotated and the bare form are returned, because the
    bare form failing to be `Final` is the larger half of what N9 says.
    """
    found: list[tuple[Finding, bool]] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            found += [
                (Finding(node.lineno, target.id), False)
                for target in node.targets
                if isinstance(target, ast.Name) and target.id not in PROTOCOL_BINDINGS
            ]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id not in PROTOCOL_BINDINGS:
                final = _spelled(node.annotation) == "Final"
                found.append((Finding(node.lineno, node.target.id), final))
    return found

def module_type_aliases(source: str) -> list[Finding]:
    """Every `type X = ...` written at `source`'s module level."""
    return [
        Finding(node.lineno, node.name.id)
        for node in ast.parse(source).body
        if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name)
    ]

def is_screaming_snake(name: str) -> bool:
    """`AGL_HOME` and `_AGL_HOME` yes, `report_findings` and `AglHome` no."""
    bare = name.lstrip("_")
    return bool(bare) and bare[0].isalpha() and bare.upper() == bare

def is_camel_case(name: str) -> bool:
    """`JsonValue` and `_Commands` yes, `json_value` and `JSON_VALUE` no."""
    bare = name.lstrip("_")
    return bool(bare) and bare[0].isupper() and "_" not in bare

# --- The plumbing under them ---------------------------------------------------------------------

def _functions(source: str) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every `def` and `async def` in `source`, methods and nested ones included."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node

def _returns_none(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the annotated return is `None` itself, rather than something that can be one.

    `-> AsyncIterator[None]` and `-> str | None` are not this: the first yields and the second
    answers, and a participle names either of them correctly.
    """
    written = node.returns
    if isinstance(written, ast.Constant):
        return written.value is None
    return isinstance(written, ast.Name) and written.id == "None"

def _head(name: str) -> str:
    """A name's grammatical head: `made` for `made`, `check` for `_check_payload`."""
    return name.strip("_").split("_")[0]

def _words_after_the_prefix(name: str) -> list[str]:
    """`["a", "role", "is", "frozen"]` for `test_a_role_is_frozen`."""
    return [word for word in name[len("test_") :].split("_") if word]

def _imports(source: str, *, package: str) -> Iterator[tuple[int, str]]:
    """Every module `source` imports, with relative imports resolved against `package`."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.lineno, _resolve(node, package)

def _resolve(node: ast.ImportFrom, package: str) -> str:
    """The dotted module `node` names. `test_ports_stdlib_only.py`'s `_resolve`, in its words."""
    if not node.level:
        return node.module or ""
    parts = package.split(".")
    if node.level > len(parts):
        return "." * node.level + (node.module or "")
    base = ".".join(parts[: len(parts) - node.level + 1])
    return f"{base}.{node.module}" if node.module else base

def _spelled(node: ast.expr) -> str:
    """The name an annotation spells by its own last segment: `Final` for `Final` and `Final[X]`."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _spelled(node.value)
    return ""

def _package_of(path: Path) -> str:
    """The dotted package a source file lives in - `agl.ports` for `src/agl/ports/clock.py`."""
    return ".".join(path.relative_to(SOURCE_ROOT).parts[:-1])

def _dotted(path: Path) -> str:
    """The dotted module a source file is - `agl.ports.clock` for `src/agl/ports/clock.py`."""
    return ".".join(path.relative_to(SOURCE_ROOT).with_suffix("").parts)

def _sources(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))

def _shown(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))

# --- The real comparisons ------------------------------------------------------------------------

def test_no_past_participle_names_a_function_that_returns_nothing() -> None:
    """`src/`, parsed, against N1. `adapters/git/_trees.py`'s `made` is what this is for.

    A participle names a value; a function returning `None` produces none, so the name is a promise
    the signature does not keep. Both spellings of every irregular are covered by stripping the
    underscores, which is the half that rotted the last time this was checked by hand.
    """
    walked = _sources(SOURCE_ROOT)
    problems = [
        f"{_shown(source)}:{finding.line} is `{finding.name}`, a past participle naming a "
        f"function whose annotated return is `None`.\n"
        f"\n"
        f"A participle names a value - `_translated(error)` is the error it built - and a function "
        f"returning None has none to name. `adapters/git/_trees.py` held `def made(directory) -> "
        f"None` for a `mkdir` and it read as one; it is `make` now. Rename it to the imperative "
        f"the function actually is.\n"
        f"\n"
        f"If the head word is not a participle at all, add it to NOT_PARTICIPLES at the top of "
        f"this file and say why there - `feed` is already in it. If it is a verb whose participle "
        f"is spelled the same as its base form, add it to SAME_AS_BASE beside `run` and `split`. "
        f"Do not take an entry out to make a name legal."
        for source in walked
        for finding in past_participles_naming_a_procedure(source.read_text(encoding="utf-8"))
    ]
    assert not problems, "\n\n".join(problems)
    assert len(walked) >= SOURCE_MODULES_TODAY, _found_nothing(walked, SOURCE_ROOT)

def test_a_check_raises_and_a_checked_returns_the_value_it_validated() -> None:
    """`src/`, parsed, against N2, in both directions and with both families asserted non-empty.

    One direction alone is not the rule: `_check_x` that returns something is as wrong as
    `_checked_x` that returns `None`, and a tree with neither family in it would satisfy either
    half by having abandoned the convention.
    """
    found = [
        (source, function)
        for source in _sources(SOURCE_ROOT)
        for function in private_check_functions(source.read_text(encoding="utf-8"))
    ]
    problems = [
        f"{_shown(source)}:{function.line} is `{function.name}`, which "
        + (
            "returns `None`. A `_checked_x` is the value it validated - "
            "`ports/run.py`'s `_checked_params` answers with the params - so a name spelled that "
            "way and returning nothing is a promise the signature does not keep. It raises, so "
            "call it `_check_...`."
            if function.promises_a_value
            else "returns a value. A `_check_x` raises and answers with nothing - "
            "`sdk/tools.py`'s `_check_payload` is the shape - so a name spelled that way and "
            "handing something back is the other half of the rule broken. Call it `_checked_...`."
        )
        for source, function in found
        if function.promises_a_value != function.returns_a_value
    ]
    assert not problems, "\n\n".join(problems)

    raising = [function for _, function in found if not function.promises_a_value]
    returning = [function for _, function in found if function.promises_a_value]
    assert len(raising) >= CHECK_FAMILY_TODAY, (
        f"only {len(raising)} private `_check…` function(s) were found under {SOURCE_ROOT} and "
        f"there were 7 when this was written. The assertion above is silent about a tree holding "
        f"none, so a scan that found none would be green and checking nothing"
    )
    assert len(returning) >= CHECK_FAMILY_TODAY, (
        f"only {len(returning)} private `_checked…` function(s) were found under {SOURCE_ROOT} and "
        f"there were 7 when this was written. Same reason as the assertion above it"
    )

def test_no_module_outside_an_adapter_package_imports_that_packages_private_modules() -> None:
    """`src/`, parsed, against N3's mechanical half.

    The private set is derived from the tree rather than listed, so a private module added
    tomorrow is covered without an edit here - which is the half a listing gets wrong.
    """
    private = frozenset(
        _dotted(source)
        for source in _sources(ADAPTERS_DIR)
        if source.name.startswith("_") and source.name != "__init__.py"
    )
    assert len(private) >= PRIVATE_ADAPTER_MODULES_TODAY, (
        f"only {len(private)} private module(s) were found under {ADAPTERS_DIR} - {sorted(private)}"
        f" - and there were 16 when this was written. The assertion below is silent about a tree "
        f"with none, so a scan that found none would be green and checking nothing"
    )
    problems = [
        f"{_shown(source)}:{finding.line} imports {finding.name}, which is private to the adapter "
        f"package it lives in.\n"
        f"\n"
        f"A leading underscore on a module means it is not on the surface its package promises, "
        f"and for an adapter that surface is the port implementation and its fake. Reaching past "
        f"it makes an adapter's internals someone else's dependency, and the next edit inside that "
        f"package breaks a module that never named it.\n"
        f"\n"
        f"Import what the package exports, or - if the thing being reached for genuinely belongs "
        f"to more than one caller - move it onto the package's own surface first. "
        f"ARCHITECTURE.md's \"No shared module under adapters/\" is what a fold across two "
        f"adapters costs, and it is not a route around this."
        for source in _sources(SOURCE_ROOT)
        for finding in private_module_leaks(
            source.read_text(encoding="utf-8"),
            package=_package_of(source),
            private=private,
        )
    ]
    assert not problems, "\n\n".join(problems)

def test_no_type_defined_in_ports_is_defined_again_anywhere_else_under_src() -> None:
    """`ports/` against the rest of `src/agl/`, on N5's one name per concept.

    `ports/` is the ring everything imports, so a name defined there is a name every layer already
    has. A second definition of it is one word meaning two things, and every reader after that has
    to work out which one is in front of them.
    """
    ports = {
        finding.name: source
        for source in _sources(PORTS_DIR)
        for finding in module_level_type_names(source.read_text(encoding="utf-8"))
    }
    assert len(ports) >= PORTS_NAMES_TODAY, (
        f"only {len(ports)} module-level type name(s) were found under {PORTS_DIR} and there were "
        f"55 when this was written. The assertion below compares against this set, so a scan that "
        f"built an empty one would be green and checking nothing"
    )
    problems = [
        f"{_shown(source)}:{finding.line} defines `{finding.name}`, and "
        f"{_shown(ports[finding.name])} already defines that name in `ports/`.\n"
        f"\n"
        f"One name per concept, never one name for two. Everything in AGL imports `ports`, so the "
        f"name is already in scope wherever this is read, and two definitions of it are two things "
        f"one word means. Import the `ports/` one, or name this one for what it actually is."
        for source in _sources(PACKAGE_ROOT)
        if not source.is_relative_to(PORTS_DIR)
        for finding in module_level_type_names(source.read_text(encoding="utf-8"))
        if finding.name in ports
    ]
    assert not problems, "\n\n".join(problems)

def test_every_test_name_is_long_enough_to_be_a_sentence() -> None:
    """`tests/`, parsed, against N8's floor - and against N8's floor only.

    Four words after `test_`, which is where ten names already sit. The convention's 8 to 14 is a
    target a reviewer applies: 215 of 1,480 names are outside it and are not defects, so asserting
    it here would fail on the corpus rather than on a mistake. See this file's docstring for the
    measured distribution.
    """
    walked = _sources(TESTS_ROOT)
    counted = 0
    problems: list[str] = []
    for source in walked:
        text = source.read_text(encoding="utf-8")
        counted += sum(1 for node in _functions(text) if node.name.startswith("test_"))
        problems += [
            f"{_shown(source)}:{finding.line} is `{finding.name}`, which is fewer than "
            f"{WORD_FLOOR} words after `test_`.\n"
            f"\n"
            f"A test name is a sentence - subject, verb, object - reading as a claim that is true "
            f"when the test passes, because the name is what a reader of a failure sees first. "
            f"Three words cannot be all three. `test_a_role_is_frozen` is four and is the shortest "
            f"shape that works.\n"
            f"\n"
            f"The convention asks for 8 to 14 words and this only asks for four, so clearing it "
            f"is not the same as satisfying the rule; that part is a reviewer's."
            for finding in short_test_names(text)
        ]
    assert not problems, "\n\n".join(problems)
    assert len(walked) >= TEST_MODULES_TODAY, _found_nothing(walked, TESTS_ROOT)
    assert counted >= TEST_FUNCTIONS_TODAY, (
        f"only {counted} test function(s) were found under {TESTS_ROOT} and there were 1,480 when "
        f"this was written. Every assertion above is silent about a name that is long enough, so "
        f"a walk that found none of them would be green and checking nothing"
    )

def test_every_module_level_constant_under_src_is_final_and_screaming_snake() -> None:
    """`src/`, parsed, against N9 - and the `Final` half is the one that carries the weight.

    There is no module-level mutable state in AGL, and nothing else says so: a bare `X = 5` type
    checks, lints clean and imports fine. Classes are ruff's N801 and are deliberately not
    re-checked here.
    """
    walked = _sources(SOURCE_ROOT)
    counted = 0
    aliases = 0
    problems: list[str] = []
    for source in walked:
        text = source.read_text(encoding="utf-8")
        dotted = _dotted(source)
        for finding, final in module_constants(text):
            counted += 1
            if not final:
                problems.append(
                    f"{_shown(source)}:{finding.line} binds `{finding.name}` at module level "
                    f"without `Final`.\n"
                    f"\n"
                    f"Every module-level binding under src/ is a constant - there is no module "
                    f"state in AGL - and `Final` is what says so to mypy and to the next reader. "
                    f"Annotate it `Final`, or `Final[T]` where the inferred type is narrower than "
                    f"the one callers need. If it genuinely has to be mutable, that is a design "
                    f"change and not an annotation somebody forgot."
                )
            if not is_screaming_snake(finding.name) and f"{dotted}.{finding.name}" not in (
                WIRE_NAMED_CONSTANTS
            ):
                problems.append(
                    f"{_shown(source)}:{finding.line} binds `{finding.name}` at module level, and "
                    f"a constant is SCREAMING_SNAKE with one leading underscore where it is "
                    f"private.\n"
                    f"\n"
                    f"Two bindings are exempt and both are listed in WIRE_NAMED_CONSTANTS at the "
                    f"top of this file: each holds a `ReportingTool` and is spelled the way the "
                    f"model calls the tool. If this is a third of those, add its dotted name there "
                    f"with the reason. Otherwise rename it."
                )
        for alias in module_type_aliases(text):
            aliases += 1
            if not is_camel_case(alias.name):
                problems.append(
                    f"{_shown(source)}:{alias.line} declares the type alias `{alias.name}`, and a "
                    f"type alias is CamelCase - `JsonValue`, `_Commands` - because it names a type "
                    f"and a reader should not have to look it up to know that."
                )
    assert not problems, "\n\n".join(problems)
    assert counted >= CONSTANTS_TODAY, (
        f"only {counted} module-level constant(s) were found under {SOURCE_ROOT} and there were "
        f"269 when this was written. Every assertion above is silent about a module holding none, "
        f"so a walk that found none of them would be green and checking nothing"
    )
    assert aliases >= TYPE_ALIASES_TODAY, (
        f"only {aliases} module-level type alias(es) were found under {SOURCE_ROOT} and there were "
        f"22 when this was written. Same reason as the assertion above it"
    )

def _found_nothing(walked: list[Path], root: Path) -> str:
    return (
        f"only {len(walked)} module(s) were found under {root}. Every assertion in this test is "
        f"silent about a module with nothing wrong in it, so a walk that found the wrong directory "
        f"would be green and checking nothing"
    )

# ---------------------------------------------------------------------------------------------
# Non-vacuity: every scan above on fabricated source, one case per rule for the edit it exists to
# catch, so that a rewrite which broke it into always answering "nothing here" fails below instead
# of passing over the whole tree.
# ---------------------------------------------------------------------------------------------

def test_the_participle_scan_reports_the_irregular_that_actually_rotted() -> None:
    """`made` in both spellings, which is the exception list that held only `_made`."""
    assert past_participles_naming_a_procedure(
        "from pathlib import Path\ndef made(directory: Path) -> None:\n    directory.mkdir()\n"
    ) == [Finding(2, "made")]
    assert past_participles_naming_a_procedure(
        "from pathlib import Path\ndef _made(directory: Path) -> None:\n    directory.mkdir()\n"
    ) == [Finding(2, "_made")]

def test_the_participle_scan_reports_a_regular_ed_head_and_reaches_a_method() -> None:
    """`-ed` is the common case, and a method is a function - `ast.walk` sees both."""
    assert past_participles_naming_a_procedure(
        "class K:\n    async def _cleaned_away(self, message: str) -> None:\n        return None\n"
    ) == [Finding(2, "_cleaned_away")]

def test_the_participle_scan_is_silent_on_the_two_exclusion_sets() -> None:
    """`run` and `split` are imperatives nothing can tell from participles; `feed` is neither."""
    assert not past_participles_naming_a_procedure(
        "def run() -> None:\n    return None\n"
        "def split() -> None:\n    return None\n"
        "def _feed(line: str) -> None:\n    return None\n"
    )

def test_the_participle_scan_is_silent_where_the_participle_is_the_answer() -> None:
    """`_translated(error) -> X` is N1 working: a participle names the value it built."""
    assert not past_participles_naming_a_procedure(
        "def _translated(error: OSError) -> Exception:\n    return error\n"
        "def _held() -> str | None:\n    return None\n"
        "def _made_lock() -> object:\n    return object()\n"
    )

def test_the_check_scan_reports_a_checked_that_returns_nothing() -> None:
    """The half `ports/agent.py`'s `check_tool_declaration` was on the wrong side of under its
    older spelling."""
    found = private_check_functions("def _checked_name(name: str) -> None:\n    return None\n")
    assert found == [CheckFunction(1, "_checked_name", True, False)]

def test_the_check_scan_reports_a_check_that_returns_a_value() -> None:
    """The other half: a name that says it raises, handing something back."""
    found = private_check_functions("def _check_name(name: str) -> str:\n    return name\n")
    assert found == [CheckFunction(1, "_check_name", False, True)]

def test_the_check_scan_reads_the_head_word_whole_and_skips_public_names() -> None:
    """`checkout_of` is a git noun, and `check_ready` is a port's vocabulary rather than N2's."""
    assert not private_check_functions(
        "from pathlib import Path\n"
        "def _checkout_of(branch: str) -> Path | None:\n    return None\n"
        "def check_unregistered(name: str) -> Path:\n    return Path(name)\n"
    )

def test_the_private_module_scan_reports_a_reach_into_another_adapters_internals() -> None:
    """Both syntaxes, because they are two spellings of one dependency."""
    private = frozenset({"agl.adapters.git._runner"})
    assert private_module_leaks(
        "from agl.adapters.git._runner import GitRunner\n",
        package="agl.config",
        private=private,
    ) == [Finding(1, "agl.adapters.git._runner")]
    assert private_module_leaks(
        "import agl.adapters.git._runner\n", package="agl.config", private=private
    ) == [Finding(1, "agl.adapters.git._runner")]

def test_the_private_module_scan_resolves_a_relative_import_rather_than_skipping_it() -> None:
    """There are none under `src/` today, which is exactly why the scan must not assume it."""
    assert private_module_leaks(
        "from .._runner import GitRunner\n",
        package="agl.adapters.openai",
        private=frozenset({"agl.adapters._runner"}),
    ) == [Finding(1, "agl.adapters._runner")]

def test_the_private_module_scan_is_silent_inside_the_package_that_owns_the_module() -> None:
    """`git/fake.py` imports `git/_trees.py`, which is what a package-private module is for."""
    assert not private_module_leaks(
        "from agl.adapters.git._trees import make\nfrom agl.adapters.git.fake import FakeHistory\n",
        package="agl.adapters.git",
        private=frozenset({"agl.adapters.git._trees"}),
    )

def test_the_type_name_scan_reads_classes_and_aliases_and_not_what_is_nested() -> None:
    """N5 is about a name a module defines, and a class inside a function defines nothing anybody
    can collide with."""
    assert module_level_type_names(
        "class Entry:\n    pass\n"
        "type JsonValue = str | int\n"
        "def build() -> None:\n    class Entry:\n        pass\n"
    ) == [Finding(1, "Entry"), Finding(3, "JsonValue")]

def test_the_test_name_scan_reports_a_three_word_name_and_spares_a_four_word_one() -> None:
    """Four is where ten names already sit, so the gate fires on the next one written short."""
    assert short_test_names("def test_it_just_works() -> None:\n    pass\n") == [
        Finding(1, "test_it_just_works")
    ]
    assert not short_test_names("def test_a_role_is_frozen() -> None:\n    pass\n")

def test_the_constant_scan_reports_a_module_binding_with_no_final() -> None:
    """The half nothing else in the build can see: `X = 80` type checks and lints clean."""
    assert module_constants("_SHOWN = 80\n") == [(Finding(1, "_SHOWN"), False)]
    assert module_constants("_SHOWN: int = 80\n") == [(Finding(1, "_SHOWN"), False)]

def test_the_constant_scan_accepts_both_spellings_of_final_and_skips_dunders() -> None:
    """`Final` and `Final[T]` are one annotation, and `__all__` is a protocol rather than a name
    AGL chose."""
    assert module_constants("_SHOWN: Final = 80\n") == [(Finding(1, "_SHOWN"), True)]
    assert module_constants("_NOTHING: Final[RenderableType] = RichText('')\n") == [
        (Finding(1, "_NOTHING"), True)
    ]
    assert not module_constants('__all__ = ["Display"]\n')

def test_the_case_predicates_answer_about_the_names_this_repository_actually_holds() -> None:
    """Both directions of both halves, since a predicate that answered `True` to everything would
    leave the walk above green over a tree that had stopped following the rule."""
    assert is_screaming_snake("AGL_HOME")
    assert is_screaming_snake("_GRACE")
    assert not is_screaming_snake("report_findings")
    assert not is_screaming_snake("AglHome")
    assert is_camel_case("JsonValue")
    assert is_camel_case("_Commands")
    assert not is_camel_case("json_value")
    assert not is_camel_case("JSON_VALUE")

def test_the_alias_scan_reads_the_type_statement_and_nothing_that_looks_like_one() -> None:
    """`type X = ...` is its own node; an assignment holding a type expression is a constant."""
    assert module_type_aliases("type JsonValue = str | int\n_ALIAS: Final = str\n") == [
        Finding(1, "JsonValue")
    ]
