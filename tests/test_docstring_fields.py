"""Structural test: a reST field block agrees with the signature it sits on, over `src` and `tests`.

`CLAUDE.md`'s docstring convention is one format and one place it is mandatory: a one-line summary,
a blank line, then `:param name:` per parameter in signature order and `:return:` where something
comes back - written on every public callable under `sdk/` and `ports/`, because those are the two
packages a workflow author hovers from their own file. This is the mechanism behind it.

## Why this convention gets a mechanism when the comment convention mostly does not

**It inverts C1, deliberately, and the mechanism is what makes the inversion safe.** C1 says a
comment earns its place by carrying a fact from outside the file, and a `:param name:` line
necessarily restates the parameter name, which is the most inside-the-file fact there is. Every
other kind of prose in this repository would be refused for that. A field line is exempt because it
is *structural*: the restatement is not the content, it is the anchor the description hangs on, and
because it is structural it can be checked mechanically - which is what this file does. Restating
something a machine compares is cheap. Restating something nobody compares is how a docstring comes
to describe a signature that has moved, and that is the failure C1 exists to prevent.

So the trade is explicit. The convention buys a tooltip at the call site, which no inline `#` can
give; it pays for it with prose that would otherwise be forbidden; and this file is the payment.
Delete it and the convention becomes exactly the thing C1 refuses.

## What is checked, and what is deliberately left to a reviewer

Everything here is a comparison between two artefacts in the same file - the field list and the
signature - and nothing here reads a description. Whether `:param payload: dataclass the arguments
are built into; its schema is a fingerprint term` earns its line, and whether the summary says
anything the name does not, is a reviewer's and is stated as such in `CLAUDE.md`. The one thing
about a description this file does say is that there is one: an empty `:param name:` is a line with
an anchor and no content, which is structural rather than editorial.

## A test and not a `scripts/check` gate

`tests/test_contract_listings.py`'s docstring settles where a rule of this kind goes - a shell gate
for a blunt textual rule, a test for anything that parses one thing and compares it against another
- and `tests/test_ports_stdlib_only.py` gives the three criteria. This lands on the same side on all
three. What is compared is a parsed field list against a parsed signature, and neither end is text a
grep can hold: `:param name:` is legal on one function and wrong on the next, and which one it is
depends on `posonlyargs`, `kwonlyargs`, a `staticmethod` decorator and whether the first parameter
is named `self`. It has to be proved to fire, and the scans here are pure functions over source
text, so the fabricated cases at the bottom hand each rule a violating snippet and watch it answer.
And `mypy --strict` covers `tests/` and does not cover a bash heredoc.

## The decisions inside the scan

**Order matters, and a set comparison would not catch the mutation that matters most.** Two
parameters swapped in a signature leaves every `:param:` name still present and still real, so a set
check stays green while every description now sits against the wrong name. `mypy --strict` does not
catch it either where the two are the same type, and `tool(name, description, ...)` is exactly that
shape. A tooltip renderer may reorder the lines back into signature order; the source does not, and
the source is where the next author reads them.

**A string above a `def` is reported, and that is a second defect with the same cause.** Python
evaluates it and throws it away: `__doc__` is `None` and no tooltip renders, while the source looks
right. Since the whole convention exists for that tooltip, the misplacement is silent in exactly the
place it costs everything. Two positions are excluded and each is a real construct rather than a
concession - the first statement of a module, a class or a function, which is the docstring, and a
string directly after an assignment, which is C5's attribute docstring and is legal.

**A field list on a class or a module docstring is reported too.** `:param:` describes a callable's
parameters; on a class it is documenting `__init__` from outside it, which is a second reST style
this repository does not have, and nothing here would compare it against anything. C2 and C3 govern
those two docstrings and this file does not.

**`-> NoReturn` takes no `:return:`.** `RefusingParser.error` in `src/agl/sdk/params.py` raises for
a living; it does not return a value, and `:return:` there would describe something no caller can
ever hold. `Never` is spelled differently and means the same thing. So the presence rule is stated
over three answers and not two: a value means the line is required, `None` and `NoReturn` mean it is
refused, and an unannotated return means this file has no opinion - `mypy --strict` refuses that
before the question reaches here.

**The implementation carries the block, and an `@overload` stub is not required to.** The checkable
half of this is asserted below: `typing.overload` returns a dummy that the final `def` rebinds over,
so a docstring written on a stub is not the function's `__doc__` at run time and `help()` never
shows it. What an IDE does with it is a vendor behaviour this repository cannot check, so under C10
this file neither demands nor refuses one - what it does is check any block a stub *does* carry
against that stub's own signature, which is a real signature and differs from the implementation's
by construction. `arg` in `src/agl/sdk/params.py` and `describe` in `src/agl/sdk/tools.py` are the
two overloaded callables here, three definitions each.

**`self` and `cls` are dropped, and a `staticmethod` keeps its first parameter.** Neither is passed
by a caller, so neither belongs in a list describing what a caller supplies, and `:param self:`
reads as an extra line rather than a missing one. Dropped by name and by position - the first
parameter, named `self` or `cls`, on a function directly inside a class body - because that is what
makes the rule wrong for a `staticmethod`, which is checked for by decorator.

**`*args` and `**kwargs` are parameters and are named without their stars.** A caller does supply
them, so they are in the list; `:param flags:` and not `:param *flags:`, because the star is
signature syntax and the field names the parameter. Two spellings for one thing is what N5 refuses,
and this is the cheap end of that rule. Positional-only and keyword-only parameters need no clause
of their own: they are read in the order they are written, which is `posonlyargs`, then `args`, then
`*args`, then keyword-only, then `**kwargs`.

**A property with no parameters gets a summary and a `:return:`, and no clause makes that so.** Its
getter takes `self`, `self` is dropped, and the expected list is empty; it returns a value, so the
line is required. `Run.terminal` and `Terminal.pending` fall out of the general rules, and a special
case for them would be a second thing to keep in step.

**An `@abstractmethod` whose body is `...` is where the block matters most and is treated like any
other.** It is the port's contract and the implementer's tooltip, and it is the one kind of callable
whose body says nothing at all. A docstring and an `Ellipsis` after it, or a docstring alone, both
parse to the same first statement, so nothing here has an opinion about which is written.

**No type in the line.** `:param str name:` restates the annotation `mypy --strict` already checks,
in a place nothing checks, so the two are free to disagree and one of them is not read by a machine.
The last word is taken as the parameter name and the rest is reported, so a line written that way
produces one complaint about the type rather than a second about a name nothing recognises.
`:type name:` and `:rtype:` are the same defect spelled as their own fields and are refused with
the rest of the fields this format does not have; `:returns:` is refused as a second spelling of
`:return:`, on N5 again. `:raises X:` is the one other field permitted, because which exception a
call raises is a fact no annotation carries and `mypy --strict` does not check - the opposite of a
type restatement, and the reason the closed list is three fields rather than two.

## The stronger half: a block is mandatory, and nothing is exempt

The format rules alone govern the docstrings somebody wrote. They say nothing about the public
callable somebody adds next year with no docstring at all, and a convention that only polices what
was written is one that decays by addition rather than by edit. So a public callable under `agl.sdk`
or `agl.ports` must carry a docstring, and where its signature has parameters or hands something
back, the format rules run over that docstring whether or not it uses the format - which is what
stops a bare one-line summary from being a way out of the block. Off that surface a one-line summary
is what C4 asks for and is left alone; a block written there anyway is checked like any other.

**There is no exemption list, and the absence is the point.** A name is what somebody reaches for
when a callable is inconvenient to document, and a list holding one name holds the next one for
free; `tests/test_contract_listings.py` makes the same argument against a second hand-maintained
list, on the ground that agreement between two of them would mean only that somebody updated both.
The requirement standing alone has no such half-state: a public callable added to either package
either carries a block or fails the build, in the edit that added it.

**Which is what makes `PUBLIC_CALLABLES_TODAY` load-bearing rather than decorative.** With nothing
to compare the walk against, the emptiness assertion is green over a walk that found no callables
at all - a glob matching no files, a `_surface` yielding nothing, a package renamed out from under
`DOCUMENTED_PACKAGES`. Each of those reports nothing undocumented because it reports nothing, and
the floor is the whole of what separates that from a tree where every block is written. It is
stated as a floor and not as a measurement so that adding a documented callable never fails it.

## What this does not close

**Dunder methods are out of the mandatory half.** `Row.__init__` and `Screen.__init__` in
`src/agl/ports/terminal.py` are public in every sense that matters, and they are excluded because a
dunder is invoked by syntax and never named at a call site: nobody writes `Row.__init__(...)`, so no
hover ever lands on it, and what renders for `Row(` is the class docstring, which C3 governs and
this file does not. That is a reason and not a proof, and it is the widest gap here.

**Classes, modules and attributes are out entirely.** C2, C3 and C5 hold those, and none of the
three is mechanical. A class on the documented surface with no docstring at all is not reported.

**Nothing here reads `api.py` or `testing.py`.** `src/agl/testing.py` is the workflow author's
harness by `ARCHITECTURE.md`'s own description, so it has as good a claim to the surface as
`sdk/` does; it is left out because `CLAUDE.md` names two packages and widening the rule is a
decision for whoever writes that sentence, not a thing to slip in through a constant here.

**`sdk/_engine/` gets nothing and is not policed.** N3 makes that underscore mean off the workflow
author's surface, and nobody hovers those modules from outside; a block written there is still
checked for format, because a wrong one is wrong wherever it is.

**The scan is a fence around the format, not a theory of documentation.** A description that lies, a
summary that restates the name, a `:raises:` naming an exception the function cannot raise - all
three pass here and all three are a reviewer's. The line between the two halves is whether a second
artefact in the same file can be compared against it.
"""

import ast
import difflib
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, overload

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SOURCE_ROOT: Final = REPO_ROOT / "src"

# The two trees that hold this repository's code, which is what the format half is stated about.
TREES: Final = ("src", "tests")

# The packages a workflow author hovers from their own file, where a block is mandatory. A module
# with an underscore anywhere in its dotted name is off the surface by N3 and is not on this list.
DOCUMENTED_PACKAGES: Final = ("agl.sdk", "agl.ports")

# The three fields this format has. `:raises:` earns its place where `:type:` and `:rtype:` do not:
# an annotation does not say what a call raises and `mypy --strict` does not check it.
PARAM_FIELD: Final = "param"
RETURN_FIELD: Final = "return"
RAISES_FIELDS: Final = frozenset({"raises", "raise"})
KNOWN_FIELDS: Final = frozenset({PARAM_FIELD, RETURN_FIELD, *RAISES_FIELDS})

# What a return annotation promises, which is what decides whether `:return:` belongs on the block.
RETURNS_A_VALUE: Final = "a value"
RETURNS_NOTHING: Final = "nothing"
RETURNS_NEVER: Final = "never"
RETURNS_UNANNOTATED: Final = "unannotated"

# Spelled `None`, and the two spellings of a function that does not come back at all.
NEVER_RETURNS: Final = frozenset({"NoReturn", "Never"})

# The first parameter of a method, which the caller never passes and the block never names.
IMPLICIT_FIRST: Final = frozenset({"self", "cls"})

STATIC_DECORATOR: Final = "staticmethod"
OVERLOAD_DECORATOR: Final = "overload"

# Floors, in the spirit of the hermeticity test's `sessions >= 2`. Every assertion below is silent
# about a file holding nothing to complain about, so each walk is asserted to have found the tree it
# was pointed at. Measured today: 233 modules under `src/` and `tests/`, and 89 public callables on
# the documented surface. Both numbers are floors and not measurements.
FILES_TODAY: Final = 150
PUBLIC_CALLABLES_TODAY: Final = 60

# A field line: a colon, a word, optional arguments, a closing colon, then the description. Anchored
# at the start of the line, so a colon inside a description is part of the description.
_FIELD_LINE: Final = re.compile(r"^:([A-Za-z][^:\n]*):(.*)$")

# A definition as this file reads one: its dotted name inside the module, the node, and whether it
# sits directly in a class body - which is the only thing that makes a first `self` implicit.
type Definition = tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, bool]

@dataclass(frozen=True)
class Finding:
    """One disagreement between a docstring and the code it describes.

    `symbol` is the dotted name inside its module rather than the line the field is written on: a
    docstring's own lines shift under `inspect.cleandoc` and the definition's line does not, so the
    pair a reader is handed is the one that cannot be off by one.
    """

    line: int
    symbol: str
    problem: str

@dataclass(frozen=True)
class DocField:
    """One `:field arguments: description` line: which field, what it was given, and what it says.

    `arguments` is every word between the field name and the closing colon, which is one word on a
    correct `:param name:` and two on a `:param str name:`.
    """

    field: str
    arguments: tuple[str, ...]
    description: str

def field_block_problems(source: str, *, documented: bool) -> list[Finding]:
    """Every way a docstring in `source` disagrees with the code around it, in the order written.

    `documented` says whether this module is on the surface where a block is mandatory: it turns the
    format rules on for every docstring rather than only for the ones already using fields, which is
    what stops a one-line summary being a way out of the block on a callable that has parameters.

    Pure: takes text, returns findings, touches no disk. The fabricated cases at the bottom of this
    file depend on that, and they are what make the real comparison mean anything.
    """
    tree = ast.parse(source)
    found = list(_strings_in_the_wrong_place(tree.body, ""))
    found += _fields_outside_a_callable(ast.get_docstring(tree), "<module>", 1)
    for name, held in _classes(tree.body, ""):
        found += _fields_outside_a_callable(ast.get_docstring(held), name, held.lineno)
    for symbol, node, method in _definitions(tree.body, "", method=False):
        docstring = ast.get_docstring(node)
        if docstring is None or not (documented or _fields(docstring)):
            continue
        found += [
            Finding(node.lineno, symbol, problem)
            for problem in _disagreements(node, docstring, method=method)
        ]
    return sorted(found, key=lambda finding: (finding.line, finding.symbol, finding.problem))

def undocumented_callables(source: str) -> list[str]:
    """Every public callable in `source` carrying no docstring, by its dotted name in the module.

    Module level and class level only, and no `@overload` stub: a nested function is not reachable
    from outside, and a stub's docstring is not the function's `__doc__` at run time. Dunders are
    out for the reason this file's docstring gives - nobody hovers a name syntax invokes.
    """
    return [
        symbol
        for symbol, node in _surface(ast.parse(source).body, "")
        if ast.get_docstring(node) is None
    ]

def _definitions(
    body: Sequence[ast.stmt], prefix: str, *, method: bool
) -> Iterator[Definition]:
    """Every function under `body` at any depth, with whether it sits directly in a class body."""
    for statement in body:
        if isinstance(statement, ast.ClassDef):
            yield from _definitions(statement.body, f"{prefix}{statement.name}.", method=True)
        elif isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            yield f"{prefix}{statement.name}", statement, method
            yield from _definitions(statement.body, f"{prefix}{statement.name}.", method=False)

def _classes(body: Sequence[ast.stmt], prefix: str) -> Iterator[tuple[str, ast.ClassDef]]:
    """Every class under `body` at any depth, by its dotted name inside the module."""
    for statement in body:
        if isinstance(statement, ast.ClassDef):
            yield f"{prefix}{statement.name}", statement
        if isinstance(statement, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _classes(statement.body, f"{prefix}{statement.name}.")

def _surface(
    body: Sequence[ast.stmt], prefix: str
) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """The public callables a package promises: module level and class level, and no stub."""
    for statement in body:
        if isinstance(statement, ast.ClassDef) and not statement.name.startswith("_"):
            yield from _surface(statement.body, f"{prefix}{statement.name}.")
        elif isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            if statement.name.startswith("_") or _decorated(statement, OVERLOAD_DECORATOR):
                continue
            yield f"{prefix}{statement.name}", statement

def _disagreements(
    node: ast.FunctionDef | ast.AsyncFunctionDef, docstring: str, *, method: bool
) -> Iterator[str]:
    """Every way one docstring's field block disagrees with the signature it is written on."""
    lines = docstring.splitlines()
    if len(lines) > 1 and lines[1].strip():
        yield (
            f"its summary runs past one line. A summary is a single line, then a blank line, then "
            f"the fields; {lines[1].strip()[:60]!r} is on the line after it"
        )
    written: list[str] = []
    returns = 0
    for one in _fields(docstring):
        if one.field not in KNOWN_FIELDS:
            yield _not_a_field_of_this_format(one)
            continue
        if not one.description:
            yield f"`:{one.field}:` carries no description, which is an anchor with nothing on it"
        if one.field == PARAM_FIELD:
            yield from _named_wrongly(one)
            written += [one.arguments[-1].lstrip("*")] if one.arguments else []
        elif one.field == RETURN_FIELD:
            returns += 1
            if one.arguments:
                yield (
                    f"`:return {' '.join(one.arguments)}:` takes an argument. `:return:` names "
                    f"nothing and describes what comes back; the type is the annotation's business"
                )
        elif not one.arguments:
            yield f"`:{one.field}:` names no exception, and which one it is is the whole content"
    expected = _expected(node, method=method)
    if written != expected:
        yield _misdescribes_the_signature(expected, written)
    yield from _return_line_problems(_promised(node), returns)

def _named_wrongly(one: DocField) -> Iterator[str]:
    """What a `:param:` line got wrong about the name it carries, the name itself set aside.

    The last word is taken as the name either way, so a line carrying a type or a pair of stars
    produces one complaint about what it wrote rather than a second about a parameter nobody has.
    """
    if not one.arguments:
        yield "`:param:` names no parameter at all, and the name is what the description hangs on"
        return
    if len(one.arguments) > 1:
        yield (
            f"`:param {' '.join(one.arguments)}:` writes a type into the line. The annotation is "
            f"the type and `mypy --strict` checks it; a second copy here is checked by nothing "
            f"and is free to disagree with it. Write `:param {one.arguments[-1]}:`"
        )
    name = one.arguments[-1]
    if name.startswith("*"):
        yield (
            f"`:param {name}:` keeps the stars. They are signature syntax and the field names the "
            f"parameter, so it is `:param {name.lstrip('*')}:` - one spelling per thing, under N5"
        )

def _return_line_problems(promised: str, returns: int) -> Iterator[str]:
    """Whether `:return:` is present exactly where the signature says something comes back."""
    if returns > 1:
        yield f"it carries {returns} `:return:` lines, and a call hands back one thing"
    if promised == RETURNS_A_VALUE and not returns:
        yield (
            "it has no `:return:` line and the signature hands something back. A block that stops "
            "at the parameters leaves the one value the caller is actually after undescribed"
        )
    if promised == RETURNS_NOTHING and returns:
        yield "it carries a `:return:` line and the signature returns `None`, so there is no value"
    if promised == RETURNS_NEVER and returns:
        yield (
            "it carries a `:return:` line and the signature is `NoReturn`. This call does not come "
            "back at all, so the line describes a value no caller can ever be handed"
        )

def _not_a_field_of_this_format(one: DocField) -> str:
    written = " ".join([one.field, *one.arguments])
    return (
        f"`:{written}:` is not a field of this format, which has three: `:param name:`, `:return:` "
        f"and `:raises Error:`. `:type:` and `:rtype:` restate an annotation nothing here would "
        f"compare them against, and `:returns:` is a second spelling of `:return:` - N5 takes one "
        f"name per thing. Anything else is prose and belongs in the summary"
    )

def _misdescribes_the_signature(expected: list[str], written: list[str]) -> str:
    missing = [name for name in expected if name not in written]
    extra = [name for name in written if name not in expected]
    repeated = sorted({name for name in written if written.count(name) > 1})
    if not missing and not extra and not repeated:
        return (
            f"its `:param:` lines are the signature's parameters in a different order: the block "
            f"reads {written} and the signature reads {expected}. A set comparison would have "
            f"passed this, which is why the order is compared - two parameters of the same type "
            f"swapped leaves every name real, every name present, and every description against "
            f"the wrong one, with `mypy --strict` silent"
        )
    return (
        f"its `:param:` lines are {written} and the signature's parameters are {expected}"
        f"{f'; missing {missing}' if missing else ''}"
        f"{f'; named but not a parameter {extra}' if extra else ''}"
        f"{f'; written twice {repeated}' if repeated else ''}"
    )

def _fields(docstring: str) -> list[DocField]:
    """Every field line in a docstring, read from its own left margin after `cleandoc`."""
    found: list[DocField] = []
    for line in docstring.splitlines():
        match = _FIELD_LINE.match(line)
        if match is not None:
            head = match.group(1).split()
            found.append(DocField(head[0], tuple(head[1:]), match.group(2).strip()))
    return found

def _expected(node: ast.FunctionDef | ast.AsyncFunctionDef, *, method: bool) -> list[str]:
    """The parameters a caller supplies, in the order the signature writes them.

    `self` and `cls` go only where they are implicit: first, named as one of the two, on a function
    directly inside a class body, and not on a `staticmethod` - which is passed everything it takes.
    """
    written = [one.arg for one in (*node.args.posonlyargs, *node.args.args)]
    if method and written[:1] and written[0] in IMPLICIT_FIRST:
        if not _decorated(node, STATIC_DECORATOR):
            written = written[1:]
    if node.args.vararg is not None:
        written.append(node.args.vararg.arg)
    written += [one.arg for one in node.args.kwonlyargs]
    if node.args.kwarg is not None:
        written.append(node.args.kwarg.arg)
    return written

def _promised(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """What the return annotation says comes back, in the three answers `:return:` turns on."""
    if node.returns is None:
        return RETURNS_UNANNOTATED
    if ast.unparse(node.returns) == "None":
        return RETURNS_NOTHING
    return RETURNS_NEVER if _spelled(node.returns) in NEVER_RETURNS else RETURNS_A_VALUE

def _strings_in_the_wrong_place(body: Sequence[ast.stmt], prefix: str) -> Iterator[Finding]:
    """Every bare string standing above a `def` or a `class`, which Python evaluates and discards.

    Two positions are excluded and neither is a concession: the first statement of any body, which
    is the docstring, and a string directly after an assignment, which is C5's attribute docstring.
    """
    for index, statement in enumerate(body):
        if isinstance(statement, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _strings_in_the_wrong_place(
                statement.body, f"{prefix}{statement.name}."
            )
        if index == 0 or index + 1 >= len(body) or not _is_a_bare_string(statement):
            continue
        follows = body[index + 1]
        if not isinstance(follows, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(body[index - 1], ast.Assign | ast.AnnAssign):
            continue
        yield Finding(
            statement.lineno,
            f"{prefix}{follows.name}",
            "a bare string stands above it rather than inside it. Python evaluates that string "
            "and throws it away, so `__doc__` is None and no tooltip renders - and the tooltip is "
            "the whole of what this convention buys. Move it below the `def` line",
        )

def _fields_outside_a_callable(docstring: str | None, symbol: str, line: int) -> list[Finding]:
    """A field block on a module or a class docstring, which describes no signature at all."""
    if docstring is None or not _fields(docstring):
        return []
    return [
        Finding(
            line,
            symbol,
            "its docstring carries a field block, and it is not a callable. `:param:` describes "
            "the parameters of the `def` it sits inside; here there is no signature to compare it "
            "against. C2 and C3 hold a module and a class docstring, and both are one line",
        )
    ]

def _is_a_bare_string(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )

def _decorated(node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    return any(_spelled(one) == name for one in node.decorator_list)

def _spelled(node: ast.expr) -> str:
    """The name a node spells, by its own last segment: `overload` and `typing.overload` alike."""
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""

def _module_of(path: Path) -> str:
    """The dotted module a source file under `src/` is imported as, package roots included."""
    dotted = ".".join(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    return dotted.removesuffix(".__init__")

def _is_documented_surface(module: str) -> bool:
    """Whether a block is mandatory in this module: on the two packages, and public all the way."""
    if not any(module == one or module.startswith(f"{one}.") for one in DOCUMENTED_PACKAGES):
        return False
    return not any(part.startswith("_") for part in module.split("."))

def _describes_a_signature_that_moved(shown: str, finding: Finding) -> str:
    return (
        f"{shown}:{finding.line} {finding.symbol}: {finding.problem}.\n"
        f"\n"
        f"CLAUDE.md's docstring convention: a one-line summary, a blank line, then one "
        f"`:param name:` per parameter in the order the signature writes them, and `:return:` "
        f"exactly where something comes back. No type in the line - the annotation is the type and "
        f"mypy --strict is what checks it.\n"
        f"\n"
        f"This is the one place the comment convention's C1 is inverted on purpose. A `:param:` "
        f"line restates a name from inside the file, which C1 refuses everywhere else, and it is "
        f"allowed here because the restatement is structural: this test compares it against the "
        f"signature on every run. That is the whole trade - the convention buys a tooltip at the "
        f"call site and pays for it with prose that only stays honest while something checks it.\n"
        f"\n"
        f"A rename is the failure this exists for. Rename a parameter and leave the block alone "
        f"and nothing else in the build says a word: ruff sees a docstring, mypy sees a string, "
        f"and the tooltip an author reads at the call site now names an argument that is gone."
    )

def _went_undocumented(missing: Sequence[str]) -> str:
    return (
        f"{len(missing)} public callable(s) under {DOCUMENTED_PACKAGES} carry no docstring:\n"
        + "".join(f"    {name}\n" for name in missing)
        + "\n"
        "CLAUDE.md's docstring convention makes a block mandatory on those two packages, because "
        "they are what a workflow author hovers from their own file. There is no exemption list "
        "and nothing to add a name to: a public callable here is one an author reads at their own "
        "call site, and the block is what renders when they do.\n"
        "\n"
        "A one-line summary is not a way out of it. Where the signature takes parameters or hands "
        "something back, the format half above runs over whatever is written, whether or not it "
        "uses the format: the summary, a blank line, then one `:param name:` per parameter in the "
        "order the signature writes them, and `:return:` exactly where something comes back."
    )

# --- The real comparison -------------------------------------------------------------------------

def test_every_docstring_field_block_in_this_repository_agrees_with_its_signature() -> None:
    """`src/` and `tests/`, parsed, against the format the docstring convention sets out.

    Two assertions, and the second is what keeps the first honest. No docstring disagrees with the
    code around it - which covers a name that is not a parameter, a parameter with no line, a line
    out of order, a type written into the line, a `:return:` on a call that returns nothing or has
    none where something comes back, a summary running past one line, and a string standing above a
    `def` rather than inside it. And the scan is asserted to have walked both trees, so a version of
    this file matching nothing could not be green while checking nothing.
    """
    problems: list[str] = []
    walked = 0
    for tree in TREES:
        for source in sorted((REPO_ROOT / tree).rglob("*.py")):
            walked += 1
            documented = tree == "src" and _is_documented_surface(_module_of(source))
            problems += [
                _describes_a_signature_that_moved(str(source.relative_to(REPO_ROOT)), finding)
                for finding in field_block_problems(
                    source.read_text(encoding="utf-8"), documented=documented
                )
            ]

    assert not problems, "\n\n".join(problems)
    assert walked >= FILES_TODAY, (
        f"only {walked} module(s) were found under {TREES} below {REPO_ROOT}, and there were 233 "
        f"when this was written. Every assertion above is silent about a module holding no "
        f"docstring, so a walk that found none of them would be green and checking nothing"
    )

def test_every_public_callable_in_sdk_and_ports_carries_a_docstring_of_its_own() -> None:
    """The stronger half: the two packages' public callables, all of which must carry a block.

    Nothing is exempt, so the first assertion is a plain emptiness and the floor beneath it is what
    keeps that honest. An empty walk reports no undocumented callables for exactly the reason a
    fully documented tree does, and `PUBLIC_CALLABLES_TODAY` is what tells the two apart.
    """
    undocumented: set[str] = set()
    walked = 0
    for source in sorted(SOURCE_ROOT.rglob("*.py")):
        module = _module_of(source)
        if not _is_documented_surface(module):
            continue
        surface = _surface(ast.parse(source.read_text(encoding="utf-8")).body, "")
        for symbol, node in surface:
            walked += 1
            if ast.get_docstring(node) is None:
                undocumented.add(f"{module}.{symbol}")

    assert not undocumented, _went_undocumented(sorted(undocumented))
    assert walked >= PUBLIC_CALLABLES_TODAY, (
        f"only {walked} public callable(s) were found under {DOCUMENTED_PACKAGES}, and there were "
        f"89 when this was written. Nothing above is exempt, so this assertion is the only thing "
        f"standing between a walk that found nothing and a green run"
    )

def test_an_overload_stub_docstring_never_reaches_the_function_at_run_time() -> None:
    """Why the implementation carries the block and a stub is not required to.

    `typing.overload` returns a dummy and the final `def` rebinds the name over it, so a docstring
    written on a stub is not the callable's `__doc__` and `help()` never shows it. Measured here
    rather than described, because it is the whole of the argument and it is one assertion long.
    """

    @overload
    def described(value: int) -> int: ...
    @overload
    def described(value: str) -> str:
        """A stub's own docstring, which nothing at run time can reach."""

    def described(value: int | str) -> int | str:
        """The implementation's, which is what `described.__doc__` holds."""
        return value

    assert described.__doc__ == "The implementation's, which is what `described.__doc__` holds."

# ---------------------------------------------------------------------------------------------
# Non-vacuity: the scans on fabricated source, one case per rule and one per decision, so that a
# rewrite which broke them into always answering "nothing here" fails below instead of passing
# over the whole tree. `_WORKED` is the block from CLAUDE.md's own convention - held to that by
# `test_claude_md_the_source_and_this_file_hold_one_worked_example_between_them` and not by this
# sentence - and every violating case below is that same block with one thing changed.
# ---------------------------------------------------------------------------------------------

_WORKED: Final = '''
def tool(name: str, description: str, payload: type, handler: object) -> Tool:
    """Build a tool an agent can call, validating its payload before the handler sees it.

    :param name: what the agent calls it; must be unique within a role
    :param description: what the agent is told the tool is for
    :param payload: dataclass the arguments are built into; edit a field and no entry replays
    :param handler: awaited with the built payload; no fingerprint term, so an edit re-runs nothing
    :return: a tool ready to go on a role
    """
'''

# The two files `_WORKED` is a copy of, by their path below `REPO_ROOT`, and the callable all three
# of them write. `CLAUDE.md` is where the convention is stated; `src/` is what an author hovers.
_WORKED_EXAMPLE_LAW: Final = "CLAUDE.md"
_WORKED_EXAMPLE_SOURCE: Final = "src/agl/sdk/tools.py"
_WORKED_EXAMPLE_SYMBOL: Final = "tool"

# A fenced Python block: ```python alone on a line, source, then ``` at the start of a line.
_PYTHON_FENCE: Final = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)

def _worked_example(source: str, shown: str) -> tuple[str, list[str]]:
    """One copy of the worked example: the docstring it writes and the parameters it names.

    The docstring comes back through `ast.get_docstring`, which cleans with `inspect.cleandoc`, so
    the common left margin of the continuation lines is the one thing normalised away. That margin
    says where a copy sits rather than what it says, and the cleaned text is what a tooltip renders
    - which is the whole of what the block exists for. Everything else is compared as written: a
    second space inside a field line is a difference and is reported as one.

    Annotations are not read. `_WORKED` writes simplified ones on purpose, so that its snippet
    needs no import to parse, and the parameter names are what every `:param:` line hangs on.
    """
    written = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == _WORKED_EXAMPLE_SYMBOL
    ]
    assert len(written) == 1, (
        f"{shown} writes {len(written)} module-level `def {_WORKED_EXAMPLE_SYMBOL}`, and the "
        f"worked example is exactly one of them. Nothing below can compare three copies of a "
        f"block while one of the three is missing or doubled"
    )
    docstring = ast.get_docstring(written[0])
    assert docstring is not None, (
        f"{shown} writes `{_WORKED_EXAMPLE_SYMBOL}` with no docstring at all, and the docstring "
        f"is the whole of what the worked example is"
    )
    return docstring, _expected(written[0], method=False)

def _fenced_worked_example(markdown: str) -> str:
    """The one fenced Python block in `CLAUDE.md` writing the worked example, as source text."""
    fenced: list[str] = [
        match.group(1)
        for match in _PYTHON_FENCE.finditer(markdown)
        if f"def {_WORKED_EXAMPLE_SYMBOL}" in match.group(1)
    ]
    assert len(fenced) == 1, (
        f"{_WORKED_EXAMPLE_LAW} holds {len(fenced)} fenced Python block(s) writing "
        f"`def {_WORKED_EXAMPLE_SYMBOL}`, and the docstring convention is written around one. If a "
        f"second one belongs there, this extraction has to be told which is the worked example"
    )
    return fenced[0]

def _a_copy_of_the_worked_example_moved(shown: str, part: str, written: str, copied: str) -> str:
    diff = "".join(
        difflib.unified_diff(
            f"{written}\n".splitlines(keepends=True),
            f"{copied}\n".splitlines(keepends=True),
            fromfile=f"{_WORKED_EXAMPLE_SOURCE}::{_WORKED_EXAMPLE_SYMBOL}",
            tofile=shown,
        )
    )
    return (
        f"{shown} and {_WORKED_EXAMPLE_SOURCE} no longer write one {part}:\n"
        f"\n"
        f"{diff}\n"
        f"The worked example is written out three times and the three are one text. "
        f"{_WORKED_EXAMPLE_LAW} states the convention and has to show it, "
        f"{_WORKED_EXAMPLE_SOURCE} is the callable an author hovers, and `_WORKED` in this file is "
        f"what every fabricated case below mutates. Edit one and the other two are stale in the "
        f"same instant: the law illustrates a block the code does not write, and the cases below "
        f"mutate a block that exists nowhere. The edit goes in all three."
    )

def test_claude_md_the_source_and_this_file_hold_one_worked_example_between_them() -> None:
    """`_WORKED` above, `CLAUDE.md`'s fenced block and `tool`'s own docstring, compared.

    Three copies exist because each is load-bearing where it sits and none can be a reference to
    another. `CLAUDE.md` states the convention and has to show it, and a document cannot import a
    docstring. Every fabricated case below is `_WORKED` with one thing changed, and a fixture that
    read its own text off disk at run time would mutate whatever the source happened to say rather
    than the block the cases were written against - which is the same reason `_WORKED` is a literal
    here. And the source is the only one of the three an author ever hovers, which is what makes
    the other two worth keeping honest at all.

    So there is no single source to collapse them into, and what is left is to compare them. The
    comparison is over the two things all three genuinely share, the cleaned docstring and the
    parameter names in signature order, and a failure names the copy that moved and diffs it.
    """
    law = (REPO_ROOT / _WORKED_EXAMPLE_LAW).read_text(encoding="utf-8")
    source = (REPO_ROOT / _WORKED_EXAMPLE_SOURCE).read_text(encoding="utf-8")
    docstring, parameters = _worked_example(source, _WORKED_EXAMPLE_SOURCE)
    for shown, copied in (
        (f"{_WORKED_EXAMPLE_LAW}'s fenced example", _fenced_worked_example(law)),
        (f"`_WORKED` in tests/{Path(__file__).name}", _WORKED),
    ):
        held, named = _worked_example(copied, shown)
        assert held == docstring, _a_copy_of_the_worked_example_moved(
            shown, "docstring", docstring, held
        )
        assert named == parameters, _a_copy_of_the_worked_example_moved(
            shown, "parameter list", "\n".join(parameters), "\n".join(named)
        )

def _one_problem(source: str, *, documented: bool = False) -> str:
    """The single problem a fabricated snippet is written to produce, asserted to be single."""
    found = field_block_problems(source, documented=documented)
    assert len(found) == 1, [finding.problem for finding in found]
    return found[0].problem

def test_the_scan_is_silent_on_the_block_the_convention_is_written_around() -> None:
    """The agreeing case, and it is not a token one: the worked example out of `CLAUDE.md`."""
    assert not field_block_problems(_WORKED, documented=True)

def test_the_scan_reports_a_parameter_renamed_without_the_docstring_following_it() -> None:
    """The failure this whole file exists for, and the only one that costs a reader anything."""
    problem = _one_problem(_WORKED.replace("payload: type", "shape: type", 1))
    assert "'payload'" in problem and "'shape'" in problem

def test_the_scan_reports_a_parameter_the_block_never_names_at_all() -> None:
    """A parameter added to the signature and not to the block: the line is simply missing."""
    assert "missing ['handler']" in _one_problem(
        _WORKED.replace("    :param handler: awaited with the built payload; no fingerprint "
                        "term, so an edit re-runs nothing\n", "")
    )

def test_the_scan_reports_a_param_line_naming_something_that_is_not_a_parameter() -> None:
    """The other direction: a line left behind after the parameter it described was deleted."""
    assert "named but not a parameter ['timeout']" in _one_problem(
        _WORKED.replace(":return: a tool", ":param timeout: how long to wait\n    :return: a tool")
    )

def test_the_scan_reports_two_param_lines_written_in_the_wrong_order() -> None:
    """Both names real, both present, and every description against the wrong one."""
    swapped = _WORKED.replace(
        "    :param name: what the agent calls it; must be unique within a role\n"
        "    :param description: what the agent is told the tool is for\n",
        "    :param description: what the agent is told the tool is for\n"
        "    :param name: what the agent calls it; must be unique within a role\n",
    )
    assert "in a different order" in _one_problem(swapped)

def test_the_scan_reports_a_type_written_into_a_param_line_beside_the_name() -> None:
    """`:param str name:` is a second copy of the annotation, and nothing compares the two."""
    problem = _one_problem(_WORKED.replace(":param name:", ":param str name:"))
    assert "writes a type into the line" in problem and "`:param name:`" in problem

def test_the_scan_reports_a_starred_spelling_of_a_parameter_it_would_otherwise_accept() -> None:
    """`*flags` is the signature's syntax; the field names the parameter, and N5 takes one."""
    source = (
        'def arg(*flags: str) -> None:\n'
        '    """Declare a flag.\n'
        '\n'
        '    :param *flags: the flags a shell will spell\n'
        '    """\n'
    )
    assert "keeps the stars" in _one_problem(source)

def test_the_scan_reports_a_return_line_missing_where_the_signature_hands_something_back() -> None:
    """A block that stops at the parameters leaves the value the caller is after undescribed."""
    assert "no `:return:` line" in _one_problem(
        _WORKED.replace("    :return: a tool ready to go on a role\n", "")
    )

def test_the_scan_reports_a_return_line_on_a_callable_annotated_to_return_none() -> None:
    """There is no value, so the line describes nothing."""
    source = 'def act() -> None:\n    """Do it.\n\n    :return: nothing much\n    """\n'
    assert "returns `None`" in _one_problem(source)

def test_the_scan_reports_a_return_line_on_a_callable_that_never_returns_at_all() -> None:
    """`RefusingParser.error` is the shape: it raises, so `:return:` would be a lie."""
    source = (
        'def error(message: str) -> NoReturn:\n'
        '    """Refuse the parse.\n'
        '\n'
        '    :param message: what argparse was going to print\n'
        '    :return: never happens\n'
        '    """\n'
    )
    assert "does not come back at all" in _one_problem(source)

def test_the_scan_is_silent_on_a_never_returning_callable_that_writes_no_return_line() -> None:
    """The same signature done right, which is the half a one-sided rule would get wrong."""
    assert not field_block_problems(
        'def error(message: str) -> NoReturn:\n'
        '    """Refuse the parse.\n'
        '\n'
        '    :param message: what argparse was going to print\n'
        '    """\n',
        documented=True,
    )

def test_the_scan_reports_a_summary_that_runs_past_the_line_it_is_allowed() -> None:
    """A summary wrapping onto the second line, which is also how a missing blank line reads."""
    source = (
        'def act(value: int) -> None:\n'
        '    """Do the thing,\n'
        '    and then some more of it.\n'
        '\n'
        '    :param value: the value\n'
        '    """\n'
    )
    assert "runs past one line" in _one_problem(source)

def test_the_scan_reports_a_field_this_format_does_not_have_and_names_the_three() -> None:
    """`:type:`, `:rtype:` and `:returns:` are the three near-misses, and all three are refused."""
    for written in (":type value: int", ":rtype: int", ":returns: a number"):
        source = (
            'def read() -> int:\n'
            '    """Read.\n'
            '\n'
            f'    {written}\n'
            '    :return: a number\n'
            '    """\n'
        )
        assert "not a field of this format" in _one_problem(source), written

def test_the_scan_permits_a_raises_line_and_reports_one_that_names_no_exception() -> None:
    """`:raises:` is the third field: an annotation does not carry it and mypy does not check it."""
    assert not field_block_problems(
        'def read() -> int:\n'
        '    """Read.\n'
        '\n'
        '    :raises InputError: when the text is not a number\n'
        '    :return: a number\n'
        '    """\n',
        documented=True,
    )
    source = (
        'def read() -> int:\n'
        '    """Read.\n'
        '\n'
        '    :raises: sometimes\n'
        '    :return: a number\n'
        '    """\n'
    )
    assert "names no exception" in _one_problem(source)

def test_the_scan_reports_a_field_line_carrying_an_anchor_and_no_description() -> None:
    """An empty description is structural rather than editorial, which is why it is read here."""
    assert "no description" in _one_problem(_WORKED.replace(":return: a tool ready to go on a role",
                                                            ":return:"))

def test_the_scan_reports_a_docstring_written_above_the_def_instead_of_inside_it() -> None:
    """Python discards it, `__doc__` is None, and the tooltip the convention buys never renders.

    Two shapes, because what sits above a `def` is usually an import or the end of the previous
    definition at module level, and the class docstring one line up inside a class body.
    """
    assert "stands above it" in _one_problem(
        'import ast\n'
        '\n'
        '"""Build the thing."""\n'
        'def build() -> None:\n'
        '    return None\n'
    )
    assert "stands above it" in _one_problem(
        'class Held:\n'
        '    """What this is."""\n'
        '\n'
        '    """Read it."""\n'
        '    def read(self) -> None:\n'
        '        return None\n'
    )

def test_the_scan_is_silent_on_an_attribute_docstring_that_precedes_a_method() -> None:
    """C5's shape, which is the one string above a `def` that is exactly where it should be."""
    assert not field_block_problems(
        'class Held:\n'
        '    """What this is."""\n'
        '\n'
        '    value: int\n'
        '    """The value, in seconds."""\n'
        '\n'
        '    def read(self) -> int:\n'
        '        """Read it.\n'
        '\n'
        '        :return: the value\n'
        '        """\n'
        '        return self.value\n',
        documented=True,
    )

def test_the_scan_is_silent_on_a_module_docstring_standing_above_a_definition() -> None:
    """The first statement of a body is the docstring, at module, class and function alike."""
    assert not field_block_problems('"""One line."""\n\n\ndef build() -> None:\n    pass\n',
                                    documented=False)

def test_the_scan_reports_a_field_block_on_a_class_docstring_where_no_signature_is() -> None:
    """`:param:` describes a `def`'s parameters; on a class there is nothing to compare it to."""
    source = (
        'class Held:\n'
        '    """What this is.\n'
        '\n'
        '    :param value: the value\n'
        '    """\n'
    )
    assert "not a callable" in _one_problem(source)

def test_the_scan_drops_self_and_cls_and_keeps_what_a_static_method_is_passed() -> None:
    """Implicit by position and by name, which is what makes the rule wrong for a static one."""
    assert not field_block_problems(
        'class Held:\n'
        '    def read(self) -> int:\n'
        '        """Read it.\n'
        '\n'
        '        :return: the value\n'
        '        """\n'
        '        return 1\n'
        '\n'
        '    @classmethod\n'
        '    def build(cls, value: int) -> "Held":\n'
        '        """Build one.\n'
        '\n'
        '        :param value: the value\n'
        '        :return: a held value\n'
        '        """\n'
        '        return cls()\n'
        '\n'
        '    @staticmethod\n'
        '    def doubled(self: int) -> int:\n'
        '        """Double it.\n'
        '\n'
        '        :param self: a number that is not an instance\n'
        '        :return: twice it\n'
        '        """\n'
        '        return self * 2\n',
        documented=True,
    )

def test_the_scan_reports_a_self_line_written_on_an_ordinary_method() -> None:
    """No caller passes it, so a line for it is an extra rather than a missing one."""
    source = (
        'class Held:\n'
        '    def read(self) -> int:\n'
        '        """Read it.\n'
        '\n'
        '        :param self: this object\n'
        '        :return: the value\n'
        '        """\n'
        '        return 1\n'
    )
    assert "named but not a parameter ['self']" in _one_problem(source)

def test_the_scan_reads_positional_only_keyword_only_and_both_starred_forms_in_order() -> None:
    """`Terminal.show`'s shape: a positional-only view, a keyword-only priority, and `**params`."""
    assert not field_block_problems(
        'class Terminal:\n'
        '    async def show(\n'
        '        self, view: object, /, *, priority: int = 0, **params: object\n'
        '    ) -> int:\n'
        '        """Put a view on screen.\n'
        '\n'
        '        :param view: the function the redraw loop invokes again every frame\n'
        '        :param priority: where a question joins the queue; higher is shown first\n'
        '        :param params: handed to the view unchanged on every invocation\n'
        '        :return: what the person answered\n'
        '        """\n'
        '        return 1\n',
        documented=True,
    )

def test_the_scan_is_silent_on_a_property_that_takes_nothing_and_hands_one_thing_back() -> None:
    """`Run.terminal` and `Terminal.pending`: summary and `:return:`, and no clause makes it so."""
    assert not field_block_problems(
        'class Run:\n'
        '    @property\n'
        '    def terminal(self) -> object:\n'
        '        """The terminal this run shows through.\n'
        '\n'
        '        :return: the terminal the framework opened around the workflow\n'
        '        """\n'
        '        return None\n',
        documented=True,
    )

def test_the_scan_is_silent_on_an_abstract_method_whose_body_is_an_ellipsis() -> None:
    """A port's contract, which is the one callable whose body says nothing at all."""
    assert not field_block_problems(
        'class Store:\n'
        '    @abstractmethod\n'
        '    async def read_entry(self, key: str) -> object:\n'
        '        """Read one entry back, or nothing where none was written.\n'
        '\n'
        '        :param key: the entry\'s address, which is its whole identity\n'
        '        :return: what was written there, or None\n'
        '        """\n'
        '        ...\n',
        documented=True,
    )

def test_the_scan_leaves_a_one_line_summary_alone_off_the_documented_surface() -> None:
    """C4's shape everywhere but `sdk/` and `ports/`, where a block is not asked for."""
    source = 'def build(value: int) -> int:\n    """Build one from a value."""\n    return value\n'
    assert not field_block_problems(source, documented=False)
    problems = [finding.problem for finding in field_block_problems(source, documented=True)]
    assert any("missing ['value']" in problem for problem in problems)
    assert any("no `:return:` line" in problem for problem in problems)

def test_the_surface_scan_reports_a_public_callable_that_carries_no_docstring() -> None:
    """The stronger half's input, on the shape it exists to catch: one added with nothing on it."""
    assert undocumented_callables(
        'class Store:\n'
        '    def read(self) -> int:\n'
        '        return 1\n'
        '\n'
        'def build() -> None:\n'
        '    """Build it."""\n'
    ) == ["Store.read"]

def test_the_surface_scan_skips_private_names_dunders_stubs_and_nested_definitions() -> None:
    """Four exclusions, each argued in this file's docstring, and all four asserted at once."""
    assert not undocumented_callables(
        'class Row:\n'
        '    def __init__(self, value: int) -> None:\n'
        '        pass\n'
        '\n'
        '    def _held(self) -> int:\n'
        '        return 1\n'
        '\n'
        '@overload\n'
        'def arg(flag: str) -> str: ...\n'
        'def arg(flag: str) -> str:\n'
        '    """Declare one."""\n'
        '    def inner() -> None:\n'
        '        pass\n'
        '    return flag\n'
    )

def test_the_surface_predicate_admits_the_two_packages_and_refuses_a_private_module() -> None:
    """`sdk/_engine/` is off the workflow author's surface by N3, and so is `_declarations`."""
    assert _is_documented_surface("agl.sdk.tools")
    assert _is_documented_surface("agl.ports.store")
    assert not _is_documented_surface("agl.sdk._engine.journal")
    assert not _is_documented_surface("agl.sdk._declarations")
    assert not _is_documented_surface("agl.adapters.git.history")
    assert not _is_documented_surface("agl.api")
