"""Structural test: `ports/` imports nothing but the standard library and its own ring.

`ARCHITECTURE.md`'s "The layers" says it from both ends in one bullet: `ports` "imports nothing but
stdlib", and a `ports/` module is an ABC or a plain type an ABC speaks, neither of which has any
business knowing what is installed. It is the load-bearing half of the dependency rule - everything
else in AGL is allowed to import `ports`, so whatever `ports` drags in is dragged into every ring at
once, and a `pydantic` model in a port signature is one every adapter, every workflow and every test
of either has to have installed to type-check.

**Nothing enforced it until this file, and that is a measurement rather than a reading.** With
`import pydantic` written into `src/agl/ports/clock.py`, `lint-imports` reports six contracts kept.
Contract 1 orders the `agl` layers and has no opinion about anything outside `agl`. Contract 3
forbids `claude_agent_sdk` and `rich` *by name*, which is the only thing a `forbidden` contract can
do. Contract 2 governs the ring's inside. So the stdlib-only rule was the one rule in
`ARCHITECTURE.md` with no mechanism behind it at all.

## Why `.importlinter` cannot express it, rather than nobody having written it down

Every contract type import-linter has names the thing it forbids or the order it requires:
`forbidden` takes the modules that may not be imported, `layers` an ordering, `independence` a set
of siblings, `protected` the modules and who may import them. None of them takes an *allow* list of
what a module may import. Stating this rule in that vocabulary means enumerating the complement -
every distribution on PyPI that is not the standard library - which is not a list anybody can write
or keep. The rule is only sayable the other way round, as "the root of every import here is in
`sys.stdlib_module_names`", and that is a sentence about source text rather than about a graph.

## A test and not a `scripts/check` gate

`scripts/check` holds the other two import rules `.importlinter` cannot express - the Codex binary
grep and the package-root gate - and it would have taken this one. Three things decided otherwise.

The rule needs judgement, and the judgements are the point: what counts as stdlib, what a relative
import resolves to, whether a `TYPE_CHECKING` import is an import. The package-root gate can be a
grep because its rule has no judgement in it - *no* import statements, of any kind - and a grep
draft of this one proved the difference immediately: `^\\s*(import|from)` matches the prose lines in
`ports/store.py` and `ports/workspace.py` that begin "from whether its entry exists" and "from its
own records". Parsing is not an optimisation here, it is the only version that is correct.

Second, and decisively: this rule has to be proved to fire. `scripts/check` has one gate that proves
itself - the paid-endpoint gate - and it costs a probe module written into `tests/`, run, and
deleted again, because a shell gate has no cheap way to be handed a fabricated world. Here the scan
is a pure function over source text, so the fabricated cases at the bottom hand it nine violating
snippets and two clean ones and watch it answer. That discipline belongs to
`tests/test_contract_listings.py`, whose own docstring settles where a rule of this kind goes: a
shell gate for a blunt textual rule, a test for anything that parses one thing and compares it
against another.

Third, `mypy --strict` covers `tests/` and does not cover a bash heredoc.

## Three decisions inside the scan

**A `TYPE_CHECKING`-only import is an import and is governed.** `ast.walk` descends into the `if`
block, so governing it is also the cheaper implementation - an exemption would be code somebody had
to write on purpose. It is the right rule regardless. A type imported under `TYPE_CHECKING` in a
`ports/` module is a type in a port's signature, which every implementer and every caller must then
have installed to type-check against; the import being invisible at runtime does not make the
dependency less real, it makes it harder to notice. `.importlinter` agrees by omission - it does not
set `exclude_type_checking_imports`, so import-linter counts these too, and a neighbour rule that
did not would be disagreeing with the file it sits beside.

**Relative imports are resolved, not skipped.** There are none under `ports/` today. `from . import
ids` is inside the ring and legal; `from ..sdk import Run` is not, and would be caught by contract 1
as well - the overlap is fine, and a scan that silently ignored every dotted import because today's
tree has none would be a hole shaped exactly like the one this file exists to close.

**`agl.ports` itself is allowed, and nothing else under `agl` is.** The ring's members speak to each
other - `ports/agent.py` imports `ports/errors.py` - and which of those imports are legal is
contract 2's question, not this one. An `agl.sdk` or `agl.adapters` import from here is reported,
even though contract 1 would also catch it, because the sentence this file is enforcing is "stdlib
and its own ring", and a scan that answered "not my department" would leave the reader to work out
which department it was.

## What this does not close

`ports/__init__.py` is exempt from contract 2 in both directions - import-linter skips a
source/forbidden pair where one module is inside the other's package, and `agl.ports` contains every
module on both of that contract's lists. This file narrows that gap without closing it: the package
root is scanned like every other module here, so it cannot reach outside the ring, but an ABC is
inside the ring and so an import of one is not something this scan has any opinion about. It holds a
docstring and nothing else today. `tests/test_contract_listings.py` states the same gap from the
other side.

The file is a little over three hundred lines to scroll through and well inside the ceiling, which
counts code lines: 150 of them. The rest is this argument, one complaint written to be read by
somebody who has never opened the file, and eleven fabricated cases. There is no seam in that worth
cutting.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SOURCE_ROOT: Final = REPO_ROOT / "src"
PORTS_DIR: Final = SOURCE_ROOT / "agl" / "ports"

# The one package a `ports/` module may name besides the standard library: its own.
RING: Final = "agl.ports"


@dataclass(frozen=True)
class Foreign:
    """One import in a `ports/` module that is neither stdlib nor inside the ring.

    `imported` is the module as resolved - `agl.sdk` rather than `..sdk` - because that is the name
    a reader has to go and look for. A relative import that runs off the top of the tree keeps its
    written spelling, there being nothing to resolve it to.
    """

    line: int
    imported: str


def foreign_imports(source: str, *, package: str) -> list[Foreign]:
    """Every import in `source` whose root is neither stdlib nor `agl.ports`, in the order written.

    `package` is the module's own `__package__` - `agl.ports` for both `ports/clock.py` and
    `ports/__init__.py` - and is what a relative import is resolved against. Pure: takes text,
    returns findings, touches no disk. The fabricated cases at the bottom of this file depend on
    that, and they are what make the real comparison mean anything.
    """
    found: list[Foreign] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [
                Foreign(node.lineno, alias.name)
                for alias in node.names
                if not _is_permitted(alias.name)
            ]
        elif isinstance(node, ast.ImportFrom):
            imported = _resolve(node, package)
            if not _is_permitted(imported):
                found.append(Foreign(node.lineno, imported))
    return sorted(found, key=lambda finding: (finding.line, finding.imported))


def _resolve(node: ast.ImportFrom, package: str) -> str:
    """The dotted module `node` names, with a relative import resolved against `package`.

    `level` is how many packages up to start from: 1 is `package` itself, 2 its parent. A level that
    runs off the top has nothing to resolve to and keeps the spelling it was written with, which is
    a syntax error Python would refuse anyway - reported rather than crashed on, because this scan
    should not be the thing that hides a broken module.
    """
    if not node.level:
        return node.module or ""
    parts = package.split(".")
    if node.level > len(parts):
        return "." * node.level + (node.module or "")
    base = ".".join(parts[: len(parts) - node.level + 1])
    return f"{base}.{node.module}" if node.module else base


def _is_permitted(imported: str) -> bool:
    """Whether a `ports/` module may name `imported`: the standard library, or its own ring."""
    if imported == RING or imported.startswith(f"{RING}."):
        return True
    root = imported.partition(".")[0]
    return bool(root) and root in sys.stdlib_module_names


def _reaches_outside_the_ring(shown: str, finding: Foreign) -> str:
    return (
        f"{shown}:{finding.line} imports {finding.imported}, which is neither the standard library "
        f"nor part of agl.ports.\n"
        f"\n"
        f"ARCHITECTURE.md's \"The layers\" says `ports` imports nothing but stdlib, and this is "
        f"the only thing in the repository that says it: no contract in .importlinter can, because "
        f"every contract type there names what is forbidden or how modules are ordered, and the "
        f"rule here is an allow list whose complement is every distribution there is.\n"
        f"\n"
        f"It is the load-bearing half of the dependency rule. Everything in AGL may import ports, "
        f"so a dependency taken here is taken by every ring at once - a third-party type in a port "
        f"signature is one every adapter, every workflow and every test of either must have "
        f"installed before it can be type-checked, and AGL's core is declared stdlib-only in "
        f"pyproject.toml.\n"
        f"\n"
        f"Two ways to resolve it, and they are not interchangeable:\n"
        f" 1. move the code that needs {finding.imported} into the adapter that stands behind "
        f"this port - ARCHITECTURE.md's \"The layers\" is explicit that a module belongs in "
        f"adapters/ if it imports a vendor SDK, and the port keeps speaking in types it can "
        f"define itself;\n"
        f" 2. change ARCHITECTURE.md first and this file second, which is the order the "
        f".importlinter header sets for a rule that has genuinely moved. Two places there state "
        f"it: the `ports` bullet under \"The layers\", and \"One clause cannot be a contract\", "
        f"which quotes it and names this file as the thing that enforces it.\n"
        f"\n"
        f"A `TYPE_CHECKING` guard is not a third way. It is still an import, it is still in the "
        f"signature, and this scan reads the whole module."
    )


def _package_of(path: Path) -> str:
    """The dotted package a source file lives in - `agl.ports` for `src/agl/ports/clock.py`."""
    return ".".join(path.relative_to(SOURCE_ROOT).parts[:-1])


# --- The real comparison -------------------------------------------------------------------------


def test_every_module_under_ports_imports_nothing_but_stdlib_and_its_own_ring() -> None:
    """`src/agl/ports/`, module by module, against `ARCHITECTURE.md`'s "The layers"."""
    sources = sorted(PORTS_DIR.rglob("*.py"))
    assert sources, (
        f"{PORTS_DIR} holds no modules at all. This test walked the wrong directory and is "
        f"asserting nothing; check the path at the top of this file."
    )
    problems = [
        _reaches_outside_the_ring(str(source.relative_to(REPO_ROOT)), finding)
        for source in sources
        for finding in foreign_imports(
            source.read_text(encoding="utf-8"), package=_package_of(source)
        )
    ]
    assert not problems, "\n\n".join(problems)


def test_the_scan_reaches_the_ports_package_root_as_well_as_its_modules() -> None:
    """`ports/__init__.py` is in the walk above, which is the half contract 2 cannot reach.

    Stated as its own assertion because it is easy to lose: an `iterdir` filtered to submodules, or
    a glob that skipped dunder filenames, would drop exactly the one file no import contract in this
    repository has an opinion about, and the real comparison above would look identical.
    """
    assert (PORTS_DIR / "__init__.py") in set(PORTS_DIR.rglob("*.py"))


# ---------------------------------------------------------------------------------------------
# Non-vacuity: the scan on fabricated source, so that a rewrite which broke it into always
# answering "nothing foreign here" fails below instead of passing over the whole tree.
# ---------------------------------------------------------------------------------------------


def test_the_scan_is_silent_on_the_imports_ports_modules_actually_use() -> None:
    """The agreeing case, and it is not a token one: every form in `src/agl/ports/` today."""
    assert not foreign_imports(
        "from __future__ import annotations\n"
        "import string\n"
        "import unicodedata\n"
        "from abc import ABC, abstractmethod\n"
        "from collections.abc import Callable, Mapping, Sequence\n"
        "from contextlib import AbstractAsyncContextManager\n"
        "from dataclasses import dataclass, field\n"
        "from datetime import UTC, datetime, timedelta\n"
        "from enum import StrEnum\n"
        "from math import isfinite\n"
        "from pathlib import Path\n"
        "from types import MappingProxyType, TracebackType\n"
        "from typing import ClassVar, Final, Self\n"
        "from agl.ports.errors import InputError\n"
        "from agl.ports.ids import Namespace\n"
        "import agl.ports.run\n"
        "from . import ids\n"
        "from .errors import InternalError\n",
        package=RING,
    )


def test_the_scan_reports_a_third_party_import() -> None:
    """The failure this file exists for, in the shape that proved the hole: `import pydantic`."""
    findings = foreign_imports("import pydantic\nfrom abc import ABC\n", package=RING)
    assert findings == [Foreign(1, "pydantic")]


def test_the_scan_reports_a_third_party_from_import() -> None:
    """`from x import y` and `import x` are one rule; a scan reading only one is half a rule."""
    findings = foreign_imports("from attrs import define\n", package=RING)
    assert findings == [Foreign(1, "attrs")]


def test_the_scan_reports_a_type_checking_only_import() -> None:
    """Guarded by `TYPE_CHECKING`, invisible at runtime, and still in the port's signature."""
    findings = foreign_imports(
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from pydantic import BaseModel\n",
        package=RING,
    )
    assert findings == [Foreign(4, "pydantic")]


def test_the_scan_reports_an_import_nested_inside_a_function() -> None:
    """A deferred import is the other way a dependency hides, and `ast.walk` sees it."""
    findings = foreign_imports(
        "def build() -> None:\n    import pydantic\n",
        package=RING,
    )
    assert findings == [Foreign(2, "pydantic")]


def test_the_scan_reports_a_relative_import_that_leaves_the_ring() -> None:
    """Resolved rather than skipped, and reported under the name a reader can go and look for."""
    findings = foreign_imports("from ..sdk import Run\n", package=RING)
    assert findings == [Foreign(1, "agl.sdk")]


def test_the_scan_permits_a_relative_import_that_stays_inside_the_ring() -> None:
    """Level 1 is the ring itself, from a submodule and from the package root alike."""
    assert not foreign_imports("from .ids import Namespace\nfrom . import errors\n", package=RING)


def test_the_scan_reports_an_absolute_agl_import_from_another_ring() -> None:
    """Contract 1 catches this too. Reported anyway - see this file's docstring for why."""
    findings = foreign_imports("from agl.adapters.git.history import GitHistory\n", package=RING)
    assert findings == [Foreign(1, "agl.adapters.git.history")]


def test_the_scan_reports_a_dotted_third_party_import_by_what_was_written() -> None:
    """`import a.b` names `a`, and the message says the whole of what the line said."""
    findings = foreign_imports("import pydantic.dataclasses\n", package=RING)
    assert findings == [Foreign(1, "pydantic.dataclasses")]


def test_the_scan_reports_every_offending_import_at_once() -> None:
    """Separate lines are separate findings in one run, not one discovered per fix."""
    findings = foreign_imports(
        "import pydantic\nfrom abc import ABC\nfrom attrs import define\n",
        package=RING,
    )
    assert findings == [Foreign(1, "pydantic"), Foreign(3, "attrs")]


def test_a_relative_import_that_runs_off_the_top_is_reported_and_not_crashed_on() -> None:
    """Python refuses it too. This scan should not be what hides a module that will not import."""
    findings = foreign_imports("from ..... import something\n", package=RING)
    assert findings == [Foreign(1, ".....")]
