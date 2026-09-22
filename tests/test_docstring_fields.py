"""Structural test: a docstring's Google sections agree with its signature, over `src` and `tests`.

The docstring convention is one format and one place it is mandatory: a one-line summary, a blank
line, then Google sections - `Args:` with one `name: text` entry per parameter in signature order,
`Returns:` where something comes back, and `Raises:` with one `Error: when` entry per exception -
written on every public callable under `sdk/` and `ports/`, because those are the two packages a
workflow author hovers from their own file. Google, because it is the form Griffe's Google parser
turns into parameter, return and exception tables; a reST field or a Sphinx role reaches the
rendered page as literal text. This is the mechanism behind it.

## Why this convention gets a mechanism when the comment convention mostly does not

**It inverts the comment rule, deliberately, and the mechanism is what makes the inversion safe.**
`AGENTS.md`'s "Prose in `src/`" says a comment earns its place by carrying a fact from outside the
file, and an `Args:` entry necessarily restates the parameter name, which is the most
inside-the-file fact there is. Every other kind of prose in this repository would be refused for
that. An entry is exempt because it is *structural*: the restatement is not the content, it is the
anchor the description hangs on, and because it is structural it can be checked mechanically -
which is what this file does. Restating something a machine compares is cheap. Restating something
nobody compares is how a docstring comes to describe a signature that has moved, and that is the
failure the comment rule exists to prevent.

So the trade is explicit. The convention buys a tooltip at the call site, which no inline `#` can
give; it pays for it with prose that would otherwise be forbidden; and this file is the payment.
Delete it and the convention becomes exactly the thing the comment rule refuses.

## What is checked, and what is deliberately left to a reviewer

Everything here is a comparison between two artefacts in the same file - the sections and the
signature - and nothing here reads a description. Whether `payload: Dataclass the agent's arguments
are checked against and built into.` earns its line, and whether the summary says anything the name
does not, is a reviewer's. The one thing about a description this file does say is that there is
one: an entry with a name and no text is an anchor with nothing on it, which is structural rather
than editorial.

## A test and not a `scripts/check` gate

`tests/test_contract_listings.py`'s docstring settles where a rule of this kind goes - a shell gate
for a blunt textual rule, a test for anything that parses one thing and compares it against another
- and `tests/test_ports_stdlib_only.py` gives the three criteria. This lands on the same side on all
three. What is compared is parsed sections against a parsed signature, and neither end is text a
grep can hold: `name: text` under `Args:` is legal on one function and wrong on the next, and which
one it is depends on `posonlyargs`, `kwonlyargs`, a `staticmethod` decorator and whether the first
parameter is named `self`. It has to be proved to fire, and the scans here are pure functions over
source text, so the fabricated cases at the bottom hand each rule a violating snippet and watch it
answer. And `mypy --strict` covers `tests/` and does not cover a bash heredoc.

## The decisions inside the scan

**Sections are read the way Griffe reads them, because a section Griffe misreads does so in
silence.** A title needs a blank line above it and its first entry directly below, or Griffe
renders the title and its entries as text and says so only at debug level. A continuation line sits
at twice the entry's indentation: at the entry's own indentation Griffe starts a new entry with it,
which splits one `Returns:` into two values without a word, and anywhere in between it logs a
warning a docs build does not fail on. So each is reported here, where nothing else would.

**Order matters, and a set comparison would not catch the mutation that matters most.** Two
parameters swapped in a signature leaves every entry's name still present and still real, so a set
check stays green while every description now sits against the wrong name. `mypy --strict` does not
catch it either where the two are the same type, and `tool(name, description, ...)` is exactly that
shape. A renderer may reorder the entries back into signature order; the source does not, and the
source is where the next author reads them.

**A string above a `def` is reported, and that is a second defect with the same cause.** Python
evaluates it and throws it away: `__doc__` is `None` and no tooltip renders, while the source looks
right. Since the whole convention exists for that tooltip, the misplacement is silent in exactly the
place it costs everything. Two positions are excluded and each is a real construct rather than a
concession - the first statement of a module, a class or a function, which is the docstring, and a
string directly after an assignment or a `type` statement, which Griffe reads as an attribute's or
a type alias's docstring.

**A section on a class or a module docstring is reported too.** `Args:` describes a callable's
parameters; on a class it is documenting `__init__` from outside it, which is a second style this
repository does not have, and nothing here would compare it against anything. A reviewer governs
those two docstrings and this file does not.

**`-> NoReturn` takes no `Returns:`.** `RefusingParser.error` in `src/agl/sdk/params.py` raises for
a living; it does not return a value, and `Returns:` there would describe something no caller can
ever hold. `Never` is spelled differently and means the same thing. So the presence rule is stated
over three answers and not two: a value means the section is required, `None` and `NoReturn` mean
it is refused, and an unannotated return means this file has no opinion - `mypy --strict` refuses
that before the question reaches here.

**The implementation carries the docstring, and an `@overload` stub is not required to.** The
checkable half of this is asserted below: `typing.overload` returns a dummy that the final `def`
rebinds over, so a docstring written on a stub is not the function's `__doc__` at run time and
`help()` never shows it. What an IDE does with it is a vendor behaviour this repository cannot
check, so this file neither demands nor refuses one - what it does is check any sections a stub
*does* carry against that stub's own signature, which is a real signature and differs from the
implementation's by construction. `arg` in `src/agl/sdk/params.py` and `describe` in
`src/agl/sdk/tools.py` are the two overloaded callables here, three definitions each.

**`self` and `cls` are dropped, and a `staticmethod` keeps its first parameter.** Neither is passed
by a caller, so neither belongs in a list describing what a caller supplies, and a `self:` entry
reads as an extra rather than a missing one. Dropped by name and by position - the first
parameter, named `self` or `cls`, on a function directly inside a class body - because that is what
makes the rule wrong for a `staticmethod`, which is checked for by decorator.

**`*args` and `**kwargs` are parameters and are named without their stars.** A caller does supply
them, so they are in the list; `flags:` and not `*flags:`, because the star is signature syntax and
the entry names the parameter. Griffe matches either spelling to the signature, so two spellings
would both render and one name per concept is what picks one. Positional-only and keyword-only
parameters need no clause of their own: they are read in the order they are written, which is
`posonlyargs`, then `args`, then `*args`, then keyword-only, then `**kwargs`.

**A property with no parameters gets a summary and `Returns:`, and no clause makes that so.** Its
getter takes `self`, `self` is dropped, and the expected list is empty; it returns a value, so the
section is required. Griffe reads a property as an attribute and reads its `Returns:` all the same.
`Run.terminal` and `Terminal.pending` fall out of the general rules, and a special case for them
would be a second thing to keep in step.

**An `@abstractmethod` whose body is `...` is where the docstring matters most and is treated like
any other.** It is the port's contract and the implementer's tooltip, and it is the one kind of
callable whose body says nothing at all. A docstring and an `Ellipsis` after it, or a docstring
alone, both parse to the same first statement, so nothing here has an opinion about which is
written.

**No type in an entry.** `name (str): text` is Google's slot for a type, and it restates the
annotation `mypy --strict` already checks, in a place nothing checks, so the two are free to
disagree and one of them is not read by a machine. The first word is taken as the parameter name
and the rest is reported, so an entry written that way produces one complaint about the type rather
than a second about a name nothing recognises. `Returns:` is the same: Griffe reads a leading
`word:` or `(type):` as the value's name or type, so the entry opens on its text. The format has
three sections and every other title Griffe knows is refused - `Arguments:`, `Parameters:` and
`Exceptions:` as second spellings, on one name per concept, `Yields:`, `Attributes:`, `Examples:`
and the rest as sections this format does not have, and `Return:` as the near miss Griffe renders
as an admonition. `Raises:` is the one section permitted beyond the signature's two, because which
exception a call raises is a fact no annotation carries and `mypy --strict` does not check - the
opposite of a type restatement, and the reason the closed list is three sections rather than two.

## No reST under `src/`

A reST field line or a Sphinx role in any docstring under `src/` - a module's, a class's, a
function's, an attribute's or a type alias's, on the documented surface or off it - is reported by
a scan of its own. The format half reads only a docstring that writes a Google section, and a
`:param name:` block writes none, so without this one a field or a role would pass wherever a
docstring is not mandatory and render literally wherever it is read. A role in code font is prose
about roles and is left alone.

## The stronger half: a docstring is mandatory, and nothing is exempt

The format rules alone govern the docstrings somebody wrote. They say nothing about the public
callable somebody adds next year with no docstring at all, and a convention that only polices what
was written is one that decays by addition rather than by edit. So a public callable on the
documented surface must carry a docstring, and where its signature has parameters or hands
something back, the format rules run over that docstring whether or not it writes a section - which
is what stops a bare one-line summary from being a way out of them. Off that surface a one-line
summary is what the convention asks for and is left alone; a section written there anyway is
checked like any other.

**The documented surface is `agl.sdk` and `agl.ports`, public all the way down, and every module
`agl.sdk`'s front door imports from.** An underscore anywhere in a module's dotted name takes it off
the surface - `sdk/_engine/` and `sdk/_declarations.py` - unless `src/agl/sdk/__init__.py` imports
from it, because a name the front door exports is one an author hovers whatever module defines it.

**There is no exemption list, and the absence is the point.** A name is what somebody reaches for
when a callable is inconvenient to document, and a list holding one name holds the next one for
free; `tests/test_contract_listings.py` makes the same argument against a second hand-maintained
list, on the ground that agreement between two of them would mean only that somebody updated both.
The requirement standing alone has no such half-state: a public callable added to either package
either carries a docstring or fails the build, in the edit that added it.

**Which is what makes `PUBLIC_CALLABLES_TODAY` load-bearing rather than decorative.** With nothing
to compare the walk against, the emptiness assertion is green over a walk that found no callables
at all - a glob matching no files, a `_surface` yielding nothing, a package renamed out from under
`DOCUMENTED_PACKAGES`. Each of those reports nothing undocumented because it reports nothing, and
the floor is the whole of what separates that from a tree where every docstring is written. It is
stated as a floor and not as a measurement so that adding a documented callable never fails it.

## The presence half: on the front door, a name with no docstring renders as nothing

**mkdocstrings leaves out a name that carries no docstring, and says nothing about it.**
`DOCS_GUIDELINES.md` states it from the other end: every public field, enum member and exported
type alias has one, or it is absent from the page. That failure looks exactly like a page written
correctly, which is the same argument the two scans above make, so the third walk is a presence
check - every name `src/agl/sdk/__init__.py`'s `__all__` holds, followed to the module that really
writes it, and every public member of each. An attribute's and a type alias's docstring is read
where Griffe reads one, as a bare string standing directly below the binding.

**This half has an exemption list, and the argument against one does not reach it.** `PLUMBING`
holds the members a `Run`, a `Workflow` and a `ReportingTool` carry for the framework rather than
for a workflow, and having no docstring is precisely what keeps each of them off the page - so the
list is not a way out of writing one, it is the register of the places where writing one would be
the defect. Each entry says what the member is for, every entry is asserted to name a member that
is really there, and a member added to a front-door class is documented or named here in the edit
that adds it.

## What this does not close

**Dunder methods are out of the mandatory half.** `Row.__init__` and `Screen.__init__` in
`src/agl/ports/terminal.py` are public in every sense that matters, and they are excluded because a
dunder is invoked by syntax and never named at a call site: nobody writes `Row.__init__(...)`, so no
hover ever lands on it, and what renders for `Row(` is the class docstring, which a reviewer
governs and this file does not. That is a reason and not a proof, and it is the widest gap here.

**What a class, a module or an attribute docstring *says* is out of every half.** Whether one is
present is checked on `agl.sdk`'s front door and nowhere else, and a module docstring is nobody's
here. What any of the three says is a reviewer's, and the reST scan is the one thing that reads
them at all.

**Nothing here reads `api.py` or `testing.py`.** `src/agl/testing.py` is the workflow author's
harness, so it has as good a claim to the surface as `sdk/` does; it is left out because `AGENTS.md`
names two packages and widening the rule is a decision for whoever writes that sentence, not a thing
to slip in through a constant here.

**`sdk/_engine/` gets nothing and is not policed.** `AGENTS.md`'s "Layers" makes that underscore
mean off the workflow author's surface, and nobody hovers those modules from outside; a section
written there is still checked for format, because a wrong one is wrong wherever it is.

**The scan is a fence around the format, not a theory of documentation.** A description that lies, a
summary that restates the name, a `Raises:` entry naming an exception the function cannot raise -
all three pass here and all three are a reviewer's. The line between the two halves is whether a
second artefact in the same file can be compared against it.
"""

import ast
import difflib
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, overload

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SOURCE_ROOT: Final = REPO_ROOT / "src"

# The two trees that hold this repository's code, which is what the format half is stated about.
TREES: Final = ("src", "tests")

# The packages a workflow author hovers from their own file, where a docstring is mandatory.
DOCUMENTED_PACKAGES: Final = ("agl.sdk", "agl.ports")

# The front door, whose imports name the modules `agl.sdk` exports from.
FRONT_DOOR: Final = SOURCE_ROOT / "agl" / "sdk" / "__init__.py"

ARGS: Final = "Args"
RETURNS: Final = "Returns"
RAISES: Final = "Raises"
SECTIONS: Final = (ARGS, RETURNS, RAISES)

# Griffe 2.3.0's section titles, then the singular near misses it renders as admonitions.
TITLES: Final = frozenset(
    {
        *("args", "arguments", "params", "parameters", "keyword args", "keyword arguments"),
        *("other args", "other arguments", "other params", "other parameters"),
        *("type args", "type arguments", "type params", "type parameters"),
        *("raises", "exceptions", "returns", "yields", "receives", "examples", "attributes"),
        *("functions", "methods", "classes", "type aliases", "modules", "warns", "warnings"),
        *("arg", "argument", "param", "parameter", "return", "raise", "exception"),
    }
)

# Griffe's own pattern for a line that opens a section or an admonition.
_TITLE: Final = re.compile(r"^(?P<title>\w[\w\s-]*):(?P<rest>\s+\S.*)?\s*$")

# The start of a `Returns:` entry that Griffe reads a name or a type out of: `word:`, `(type):`.
_NAMED_OR_TYPED: Final = re.compile(r"^(?:\w+)?\s*(?:\(.+\))?:")

# How a `Raises:` entry names its exception: a class, bare or dotted.
_EXCEPTION: Final = re.compile(r"[A-Za-z_][\w.]*")

# A reST field line and a Sphinx role; the lookbehind spares a role written in code font.
_REST_FIELD: Final = re.compile(r"^\s*:[A-Za-z][^:`\n]*:(\s|$)", re.MULTILINE)
_SPHINX_ROLE: Final = re.compile(r"(?<![\w`]):[A-Za-z][\w-]*(?::[A-Za-z][\w-]*)*:`")

# What a return annotation promises, which is what decides whether `Returns:` belongs.
RETURNS_A_VALUE: Final = "a value"
RETURNS_NOTHING: Final = "nothing"
RETURNS_NEVER: Final = "never"
RETURNS_UNANNOTATED: Final = "unannotated"

# Spelled `None`, and the two spellings of a function that does not come back at all.
NEVER_RETURNS: Final = frozenset({"NoReturn", "Never"})

# The first parameter of a method, which the caller never passes and the docstring never names.
IMPLICIT_FIRST: Final = frozenset({"self", "cls"})

STATIC_DECORATOR: Final = "staticmethod"
OVERLOAD_DECORATOR: Final = "overload"

# Floors under what each walk finds: a walk of the wrong tree fails, and an addition never does.
FILES_TODAY: Final = 150
PUBLIC_CALLABLES_TODAY: Final = 63
SOURCE_DOCSTRINGS_TODAY: Final = 200
EXPORTED_MEMBERS_TODAY: Final = 100

# The members of a front-door class that carry no docstring on purpose, each because the framework
# holds it rather than a workflow, and having none is what keeps it off the rendered page.
PLUMBING: Final[Mapping[str, str]] = {
    "ReportingTool.payload_schema": "derived from `payload`; AGL writes it and AGL reads it",
    "Run.services": "the ports this run was built over",
    "Run.scope": "the run's address inside AGL's own layout",
    "Run.base": "the state this run was cut from, held for the framework",
    "Run.fingerprints": "the framework's own bookkeeping across a walk",
    "Run.worktrees": "the framework's own bookkeeping across a walk",
    "Run.leases": "the framework's own bookkeeping across a walk",
    "Run.capabilities": "the framework's own bookkeeping across a walk",
    "Workflow.fn": "the decorated function, which only an entry point calls",
}

# A definition as this file reads one: its dotted name inside the module, the node, and whether it
# sits directly in a class body - which is the only thing that makes a first `self` implicit.
type Definition = tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, bool]

@dataclass(frozen=True)
class Finding:
    """One disagreement between a docstring and the code it describes.

    `symbol` is the dotted name inside its module rather than the line the section is written on: a
    docstring's own lines shift under `inspect.cleandoc` and the definition's line does not, so the
    pair a reader is handed is the one that cannot be off by one.
    """

    line: int
    symbol: str
    problem: str

@dataclass(frozen=True)
class Section:
    """One section as Griffe reads it: its title, each entry's lines, and what Griffe would misread.

    An entry's first line has the entry indentation taken off and its continuation lines twice
    that, so `entries` holds what Griffe hands on as the entry's text. `layout` holds each way the
    section is written that Griffe would read differently from how it looks.
    """

    title: str
    entries: tuple[tuple[str, ...], ...]
    layout: tuple[str, ...]

def docstring_problems(source: str, *, documented: bool) -> list[Finding]:
    """Every way a docstring in `source` disagrees with the code around it, in the order written.

    `documented` says whether this module is on the surface where a docstring is mandatory: it turns
    the format rules on for every docstring rather than only for the ones already writing a section,
    which is what stops a one-line summary being a way out of them on a callable with parameters.

    Pure: takes text, returns findings, touches no disk. The fabricated cases at the bottom of this
    file depend on that, and they are what make the real comparison mean anything.
    """
    tree = ast.parse(source)
    found = list(_strings_in_the_wrong_place(tree.body, ""))
    found += _sections_outside_a_callable(ast.get_docstring(tree), "<module>", 1)
    for name, held in _classes(tree.body, ""):
        found += _sections_outside_a_callable(ast.get_docstring(held), name, held.lineno)
    for symbol, node, method in _definitions(tree.body, "", method=False):
        docstring = ast.get_docstring(node)
        if docstring is None or not (documented or sections(docstring)):
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

def rest_constructs(source: str) -> list[Finding]:
    """Every docstring in `source` still carrying a reST field line or a Sphinx role.

    Every docstring Griffe reads is read here: a module's, a class's and a function's at any depth,
    and the bare string after an assignment or a `type` statement, which is an attribute's or a type
    alias's. Pure, like the other scans.
    """
    found: list[Finding] = []
    for line, symbol, text in _docstrings(ast.parse(source).body, ""):
        if _REST_FIELD.search(text):
            found.append(Finding(line, symbol, _REST_FIELD_FOUND))
        if _SPHINX_ROLE.search(text):
            found.append(Finding(line, symbol, _SPHINX_ROLE_FOUND))
    return found

def sections(docstring: str) -> list[Section]:
    """Every section title in a cleaned docstring that Griffe would take up, with its entries.

    A title counts where Griffe counts one: a line of the title's shape with an indented line
    directly below it or one line further down, outside a fenced code block. The same line with
    nothing indented under it is text to Griffe, and it is text here.
    """
    lines = docstring.splitlines()
    found: list[Section] = []
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip(" ").startswith("```"):
            fenced = not fenced
        match = None if fenced else _TITLE.match(line)
        if match is None or match.group("title").lower() not in TITLES:
            continue
        below = lines[index + 1 : index + 3]
        if not any(one.strip() and one.startswith(" ") for one in below):
            continue
        layout: list[str] = []
        if index > 0 and lines[index - 1].strip():
            layout.append(
                f"`{match.group('title')}:` has no blank line above it, so Griffe renders it and "
                f"its entries as text rather than as a section"
            )
        if not below[0].strip():
            layout.append(
                f"a blank line stands between `{match.group('title')}:` and its first entry, so "
                f"Griffe renders both as text rather than as a section"
            )
        if match.group("rest") is not None:
            layout.append(
                f"`{match.group('title')}:` carries text after its colon. A title stands alone on "
                f"its line and its entries go below it"
            )
        entries, confusing = _entries(lines, index + 1)
        layout += [
            f"{shown!r} is indented further than its entry and less than twice as far. Griffe "
            f"joins it to the entry with a warning; a continuation line sits at twice the entry's "
            f"indentation"
            for shown in confusing
        ]
        found.append(Section(match.group("title"), entries, tuple(layout)))
    return found

def _entries(
    lines: Sequence[str], start: int
) -> tuple[tuple[tuple[str, ...], ...], list[str]]:
    """A section's entries from the line below its title, read the way Griffe reads block items.

    The first non-blank line sets the entry indentation. A line at twice it continues the entry, a
    line at it starts the next one, a line in between continues with a warning, and a line at less
    ends the section. Blank lines belong to the entry above them, as they do in Griffe.
    """
    offset = start
    while offset < len(lines) and not lines[offset].strip():
        offset += 1
    if offset == len(lines):
        return (), []
    indent = len(lines[offset]) - len(lines[offset].lstrip(" "))
    if indent == 0:
        return (), []
    entries = [[lines[offset][indent:]]]
    confusing: list[str] = []
    for line in lines[offset + 1 :]:
        if not line.strip():
            entries[-1].append("")
        elif line.startswith(" " * (indent * 2)):
            entries[-1].append(line[indent * 2 :])
        elif line.startswith(" " * (indent + 1)):
            entries[-1].append(line.strip())
            confusing.append(line.strip())
        elif line.startswith(" " * indent):
            entries.append([line[indent:]])
        else:
            break
    return tuple(_without_trailing_blanks(entry) for entry in entries), confusing

def _without_trailing_blanks(entry: list[str]) -> tuple[str, ...]:
    while entry and not entry[-1].strip():
        entry = entry[:-1]
    return tuple(entry)

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

def _docstrings(body: Sequence[ast.stmt], prefix: str) -> Iterator[tuple[int, str, str]]:
    """Every docstring in `body` at any depth: its line, the dotted name it documents, its text."""
    if body and _is_a_bare_string(body[0]):
        yield body[0].lineno, prefix.removesuffix(".") or "<module>", _text(body[0])
    for previous, statement in zip(body, body[1:], strict=False):
        if _is_a_bare_string(statement) and _names_a_binding(previous):
            yield statement.lineno, f"{prefix}{_bound(previous)}", _text(statement)
    for statement in body:
        if isinstance(statement, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _docstrings(statement.body, f"{prefix}{statement.name}.")

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
    """Every way one docstring's sections disagree with the signature they are written on."""
    lines = docstring.splitlines()
    if len(lines) > 1 and lines[1].strip():
        yield (
            f"its summary runs past one line. A summary is a single line, then a blank line, then "
            f"the sections; {lines[1].strip()[:60]!r} is on the line after it"
        )
    written: list[str] = []
    returned = 0
    seen: list[str] = []
    for section in sections(docstring):
        yield from section.layout
        if section.title not in SECTIONS:
            yield _not_a_section_of_this_format(section.title)
            continue
        if section.title in seen:
            yield f"it writes `{section.title}:` twice, and each section is written once"
        seen.append(section.title)
        if section.title == ARGS:
            for entry in section.entries:
                name, problems = _argument(entry)
                yield from problems
                written += [name] if name else []
        elif section.title == RETURNS:
            returned += 1
            yield from _returned_value_problems(section.entries)
        else:
            for entry in section.entries:
                yield from _raised_problems(entry)
    expected = _expected(node, method=method)
    if written != expected:
        yield _misdescribes_the_signature(expected, written)
    yield from _returns_presence_problems(_promised(node), returned)

def _argument(entry: tuple[str, ...]) -> tuple[str, list[str]]:
    """The parameter an `Args:` entry names, and what it got wrong writing it.

    The first word is taken as the name either way, so an entry carrying a type or a pair of stars
    produces one complaint about what it wrote rather than a second about a parameter nobody has.
    """
    head, colon, text = entry[0].partition(":")
    if not colon:
        return "", [
            f"{entry[0]!r} under `Args:` is not a `name: text` entry. A continuation line sits at "
            f"twice the entry's indentation; at the entry's own, Griffe reads it as the next entry"
        ]
    written = head.strip()
    words = written.split("(")[0].split()
    name = words[0] if words else ""
    problems: list[str] = []
    if not name:
        problems.append("an `Args:` entry names no parameter, and the name is what it hangs on")
    elif written != name:
        problems.append(
            f"`{written}:` writes a type into the entry. The annotation is the type and "
            f"`mypy --strict` checks it; a second copy here is checked by nothing and is free to "
            f"disagree with it. Write `{name.lstrip('*')}:`"
        )
    if name.startswith("*"):
        problems.append(
            f"`{name}:` keeps the stars. They are signature syntax and the entry names the "
            f"parameter, so it is `{name.lstrip('*')}:` - one spelling per thing"
        )
    if not (text.strip() or any(line.strip() for line in entry[1:])):
        problems.append(f"`{name}:` carries no description, which is an anchor with nothing on it")
    return name.lstrip("*"), problems

def _returned_value_problems(entries: tuple[tuple[str, ...], ...]) -> Iterator[str]:
    """What a `Returns:` section got wrong about the one value it describes."""
    if len(entries) > 1:
        yield (
            f"`Returns:` reads as {len(entries)} entries, and a call hands back one thing. A "
            f"continuation line sits at twice the entry's indentation; at the entry's own, Griffe "
            f"reads it as a second value"
        )
    if not entries or not any(line.strip() for line in entries[0]):
        yield "`Returns:` carries no description, which is an anchor with nothing on it"
    elif _NAMED_OR_TYPED.match(entries[0][0]):
        yield (
            f"`Returns:` opens {entries[0][0][:40]!r}, and Griffe reads what stands before that "
            f"colon as the value's name or type. The entry is the description alone"
        )

def _raised_problems(entry: tuple[str, ...]) -> Iterator[str]:
    """What a `Raises:` entry got wrong: it names an exception, then says when."""
    head, colon, text = entry[0].partition(":")
    if not colon or not _EXCEPTION.fullmatch(head.strip()):
        yield (
            f"{entry[0][:60]!r} under `Raises:` names no exception, and which one it is is the "
            f"whole content. An entry is `Error: when`"
        )
        return
    if not (text.strip() or any(line.strip() for line in entry[1:])):
        yield f"`{head.strip()}:` carries no description, which is an anchor with nothing on it"

def _returns_presence_problems(promised: str, returned: int) -> Iterator[str]:
    """Whether `Returns:` is present exactly where the signature says something comes back."""
    if promised == RETURNS_A_VALUE and not returned:
        yield (
            "it has no `Returns:` section and the signature hands something back. A docstring "
            "that stops at the parameters leaves the one value the caller is actually after "
            "undescribed"
        )
    if promised == RETURNS_NOTHING and returned:
        yield "it carries `Returns:` and the signature returns `None`, so there is no value"
    if promised == RETURNS_NEVER and returned:
        yield (
            "it carries `Returns:` and the signature is `NoReturn`. This call does not come back "
            "at all, so the section describes a value no caller can ever be handed"
        )

def _not_a_section_of_this_format(title: str) -> str:
    return (
        f"`{title}:` is not a section of this format, which has three: `Args:`, `Returns:` and "
        f"`Raises:`. `Arguments:`, `Parameters:` and `Exceptions:` are second spellings - one "
        f"name per thing - and `Return:` is one Griffe renders as an admonition. Anything else is "
        f"prose and belongs in the summary"
    )

def _misdescribes_the_signature(expected: list[str], written: list[str]) -> str:
    missing = [name for name in expected if name not in written]
    extra = [name for name in written if name not in expected]
    repeated = sorted({name for name in written if written.count(name) > 1})
    if not missing and not extra and not repeated:
        return (
            f"its `Args:` entries are the signature's parameters in a different order: the "
            f"docstring reads {written} and the signature reads {expected}. A set comparison would "
            f"have passed this, which is why the order is compared - two parameters of the same "
            f"type swapped leaves every name real, every name present, and every description "
            f"against the wrong one, with `mypy --strict` silent"
        )
    return (
        f"its `Args:` entries are {written} and the signature's parameters are {expected}"
        f"{f'; missing {missing}' if missing else ''}"
        f"{f'; named but not a parameter {extra}' if extra else ''}"
        f"{f'; written twice {repeated}' if repeated else ''}"
    )

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
    """What the return annotation says comes back, in the three answers `Returns:` turns on."""
    if node.returns is None:
        return RETURNS_UNANNOTATED
    if ast.unparse(node.returns) == "None":
        return RETURNS_NOTHING
    return RETURNS_NEVER if _spelled(node.returns) in NEVER_RETURNS else RETURNS_A_VALUE

def _strings_in_the_wrong_place(body: Sequence[ast.stmt], prefix: str) -> Iterator[Finding]:
    """Every bare string standing above a `def` or a `class`, which Python evaluates and discards.

    Two positions are excluded and neither is a concession: the first statement of any body, which
    is the docstring, and a string directly after an assignment or a `type` statement, which is an
    attribute's or a type alias's docstring.
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
        if _names_a_binding(body[index - 1]):
            continue
        yield Finding(
            statement.lineno,
            f"{prefix}{follows.name}",
            "a bare string stands above it rather than inside it. Python evaluates that string "
            "and throws it away, so `__doc__` is None and no tooltip renders - and the tooltip is "
            "the whole of what this convention buys. Move it below the `def` line",
        )

def _sections_outside_a_callable(docstring: str | None, symbol: str, line: int) -> list[Finding]:
    """A section on a module or a class docstring, which describes no signature at all."""
    if docstring is None or not sections(docstring):
        return []
    return [
        Finding(
            line,
            symbol,
            "its docstring carries a section, and it is not a callable. `Args:` describes the "
            "parameters of the `def` it sits inside; here there is no signature to compare it "
            "against. A module and a class docstring are each one line",
        )
    ]

_REST_FIELD_FOUND: Final = (
    "its docstring carries a reST field line, which Griffe's Google parser renders as literal "
    "text. `:param name:` is an `Args:` entry, `:return:` a `Returns:` section and "
    "`:raises Error:` a `Raises:` entry"
)

_SPHINX_ROLE_FOUND: Final = (
    "its docstring carries a Sphinx role, which Griffe's Google parser renders as literal text. "
    "A name `agl.sdk` exports is a cross-reference by its full public path, "
    "[`Role`][agl.sdk.Role]; a name it does not export is described in words"
)

def _is_a_bare_string(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )

def _names_a_binding(statement: ast.stmt) -> bool:
    """Whether a string after `statement` is the docstring of what it binds, as Griffe reads one."""
    return isinstance(statement, ast.Assign | ast.AnnAssign | ast.TypeAlias)

def _bound(statement: ast.stmt) -> str:
    """The name an assignment or a `type` statement binds, for a finding to be reported under."""
    if isinstance(statement, ast.TypeAlias):
        return ast.unparse(statement.name)
    if isinstance(statement, ast.AnnAssign):
        return ast.unparse(statement.target)
    return ast.unparse(statement.targets[0]) if isinstance(statement, ast.Assign) else ""

def _text(statement: ast.stmt) -> str:
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return statement.value.value if isinstance(statement.value.value, str) else ""
    return ""

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

def _front_door_sources(source: str) -> frozenset[str]:
    """The modules a front door's `from ... import` statements name, each of them on the surface."""
    return frozenset(
        node.module
        for node in ast.parse(source).body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

def _is_documented_surface(module: str, front_door: frozenset[str]) -> bool:
    """Whether a docstring is mandatory in this module: re-exported, or public all the way down."""
    if module in front_door:
        return True
    if not any(module == one or module.startswith(f"{one}.") for one in DOCUMENTED_PACKAGES):
        return False
    return not any(part.startswith("_") for part in module.split("."))

def _module_source(module: str) -> str:
    """The text of a module under `src/`, whether it is a file or a package's `__init__.py`."""
    base = SOURCE_ROOT.joinpath(*module.split("."))
    written = base.with_suffix(".py")
    return (written if written.is_file() else base / "__init__.py").read_text(encoding="utf-8")

def _front_door_exports(source: str) -> list[str]:
    """Every name a front door's `__all__` holds, in the order it writes them."""
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or _bound(node) != "__all__":
            continue
        if not isinstance(node.value, ast.List):
            continue
        return [
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return []

def _described(body: Sequence[ast.stmt]) -> dict[str, tuple[ast.stmt, bool]]:
    """Each name a body binds at its own level, with its node and whether a docstring stands there.

    A `def` and a `class` carry theirs inside. An attribute and a type alias are followed by a bare
    string, which is the only place Griffe reads one from. An `@overload` stub binds the name the
    implementation below it rebinds, and the implementation is the one that carries the docstring.
    """
    found: dict[str, tuple[ast.stmt, bool]] = {}
    for index, statement in enumerate(body):
        below = body[index + 1] if index + 1 < len(body) else None
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            if not _decorated(statement, OVERLOAD_DECORATOR):
                found[statement.name] = (statement, ast.get_docstring(statement) is not None)
        elif isinstance(statement, ast.ClassDef):
            found[statement.name] = (statement, ast.get_docstring(statement) is not None)
        elif _names_a_binding(statement) and _bound(statement):
            found[_bound(statement)] = (statement, below is not None and _is_a_bare_string(below))
    return found

def _written_where(module: str, name: str) -> tuple[ast.stmt, bool] | None:
    """A name the front door exports, found where it is written and not where it is passed on."""
    body = ast.parse(_module_source(module)).body
    here = _described(body).get(name)
    if here is not None:
        return here
    for statement in body:
        if not isinstance(statement, ast.ImportFrom) or statement.module is None:
            continue
        if any(alias.asname is None and alias.name == name for alias in statement.names):
            return _written_where(statement.module, name)
    return None

def _renders_as_nothing(missing: Sequence[str]) -> str:
    return (
        f"{len(missing)} name(s) on `agl.sdk`'s front door carry no docstring:\n"
        + "".join(f"    {name}\n" for name in missing)
        + "\n"
        "The API reference is these docstrings rendered word for word, and mkdocstrings leaves a "
        "name with none off the page - silently, and looking exactly like a page written "
        "correctly. So a field, an enum member and an exported type alias each carry one, which "
        "is what `DOCS_GUIDELINES.md` says from the other end.\n"
        "\n"
        "An attribute's docstring is a bare string on the line below the binding, which is the "
        "only place Griffe reads one from; a `def` and a `class` carry theirs inside. A member "
        "the framework holds rather than a workflow goes in `PLUMBING` above, with what it is "
        "for, because carrying no docstring is what keeps it off the page."
    )

def _describes_a_signature_that_moved(shown: str, finding: Finding) -> str:
    return (
        f"{shown}:{finding.line} {finding.symbol}: {finding.problem}.\n"
        f"\n"
        f"The docstring convention: a one-line summary, a blank line, then Google sections - "
        f"`Args:` with one `name: text` entry per parameter in the order the signature writes "
        f"them, `Returns:` exactly where something comes back, and `Raises:` with one "
        f"`Error: when` entry per exception. No type in an entry - the annotation is the type and "
        f"mypy --strict is what checks it.\n"
        f"\n"
        f"This is the one place the comment rule is inverted on purpose. An `Args:` entry "
        f"restates a name from inside the file, which a comment may not do anywhere else, and it "
        f"is allowed here because the restatement is structural: this test compares it against "
        f"the signature on every run. That is the whole trade - the convention buys a tooltip at "
        f"the call site and pays for it with prose that only stays honest while something checks "
        f"it.\n"
        f"\n"
        f"A rename is the failure this exists for. Rename a parameter and leave the docstring "
        f"alone and nothing else in the build says a word: ruff sees a docstring, mypy sees a "
        f"string, and the tooltip an author reads at the call site now names an argument that is "
        f"gone."
    )

def _went_undocumented(missing: Sequence[str]) -> str:
    return (
        f"{len(missing)} public callable(s) on the documented surface carry no docstring:\n"
        + "".join(f"    {name}\n" for name in missing)
        + "\n"
        "The docstring convention makes a docstring mandatory on `agl.sdk` and `agl.ports`, "
        "because they are what a workflow author hovers from their own file. There is no "
        "exemption list and nothing to add a name to: a public callable here is one an author "
        "reads at their own call site, and the docstring is what renders when they do.\n"
        "\n"
        "A one-line summary is not a way out of it. Where the signature takes parameters or hands "
        "something back, the format half above runs over whatever is written, whether or not it "
        "writes a section: the summary, a blank line, then `Args:` with one `name: text` entry "
        "per parameter in the order the signature writes them, and `Returns:` exactly where "
        "something comes back."
    )

def _carries_rest(shown: str, finding: Finding) -> str:
    return f"{shown}:{finding.line} {finding.symbol}: {finding.problem}."

# --- The real comparison -------------------------------------------------------------------------

def test_every_docstring_section_in_this_repository_agrees_with_its_signature() -> None:
    """`src/` and `tests/`, parsed, against the format the docstring convention sets out.

    Two assertions, and the second is what keeps the first honest. No docstring disagrees with the
    code around it - which covers an entry naming no parameter, a parameter with no entry, entries
    out of order, a type written into an entry, `Returns:` on a call that returns nothing or none
    where something comes back, a section Griffe would misread, a summary running past one line,
    and a string standing above a `def` rather than inside it. And the scan is asserted to have
    walked both trees, so a version of this file matching nothing could not be green while
    checking nothing.
    """
    front_door = _front_door_sources(FRONT_DOOR.read_text(encoding="utf-8"))
    problems: list[str] = []
    walked = 0
    for tree in TREES:
        for source in sorted((REPO_ROOT / tree).rglob("*.py")):
            walked += 1
            documented = tree == "src" and _is_documented_surface(_module_of(source), front_door)
            problems += [
                _describes_a_signature_that_moved(str(source.relative_to(REPO_ROOT)), finding)
                for finding in docstring_problems(
                    source.read_text(encoding="utf-8"), documented=documented
                )
            ]

    assert not problems, "\n\n".join(problems)
    assert walked >= FILES_TODAY, (
        f"only {walked} module(s) were found under {TREES} below {REPO_ROOT}, under the floor of "
        f"{FILES_TODAY}. Every assertion above is silent about a module holding no docstring, so "
        f"a walk that found none of them would be green and checking nothing"
    )

def test_every_public_callable_in_sdk_and_ports_carries_a_docstring_of_its_own() -> None:
    """The stronger half: the documented surface's public callables, all of which need a docstring.

    Nothing is exempt, so the first assertion is a plain emptiness and the floor beneath it is what
    keeps that honest. An empty walk reports no undocumented callables for exactly the reason a
    fully documented tree does, and `PUBLIC_CALLABLES_TODAY` is what tells the two apart.
    """
    front_door = _front_door_sources(FRONT_DOOR.read_text(encoding="utf-8"))
    undocumented: set[str] = set()
    walked = 0
    for source in sorted(SOURCE_ROOT.rglob("*.py")):
        module = _module_of(source)
        if not _is_documented_surface(module, front_door):
            continue
        surface = _surface(ast.parse(source.read_text(encoding="utf-8")).body, "")
        for symbol, node in surface:
            walked += 1
            if ast.get_docstring(node) is None:
                undocumented.add(f"{module}.{symbol}")

    assert not undocumented, _went_undocumented(sorted(undocumented))
    assert walked >= PUBLIC_CALLABLES_TODAY, (
        f"only {walked} public callable(s) were found on the documented surface, under the floor "
        f"of {PUBLIC_CALLABLES_TODAY}. Nothing above is exempt, so this assertion is the only "
        f"thing standing between a walk that found nothing and a green run"
    )

def test_every_name_the_sdk_exports_and_each_public_member_carries_a_docstring() -> None:
    """The presence half, over `agl.sdk`'s front door and every public member of what it exports.

    Three assertions. Nothing is undocumented outside `PLUMBING`; every `PLUMBING` key names a
    member the walk really reached, so a rename cannot leave a stale exemption standing; and the
    walk is held to a floor, because a front door it failed to follow reports nothing missing for
    the same reason a fully documented one does.
    """
    missing: list[str] = []
    reached: set[str] = set()
    walked = 0
    for name in _front_door_exports(_module_source("agl.sdk")):
        written = _written_where("agl.sdk", name)
        assert written is not None, (
            f"`agl.sdk.__all__` names {name!r}, and no module this front door imports from writes "
            f"it. Nothing below can say a word about a name it could not find"
        )
        node, documented = written
        walked += 1
        if not documented:
            missing.append(f"agl.sdk.{name}")
        if not isinstance(node, ast.ClassDef):
            continue
        for member, (_bound_at, described) in _described(node.body).items():
            if member.startswith("_") and member != "__call__":
                continue
            walked += 1
            reached.add(f"{name}.{member}")
            if not described and f"{name}.{member}" not in PLUMBING:
                missing.append(f"agl.sdk.{name}.{member}")

    assert not missing, _renders_as_nothing(sorted(missing))
    assert not sorted(set(PLUMBING) - reached), (
        f"`PLUMBING` exempts {sorted(set(PLUMBING) - reached)}, and this walk reached no such "
        f"member. An exemption naming nothing is one a rename left behind, and it would go on "
        f"exempting whatever is written under that name next"
    )
    assert walked >= EXPORTED_MEMBERS_TODAY, (
        f"only {walked} name(s) and member(s) were walked off `agl.sdk`'s front door, under the "
        f"floor of {EXPORTED_MEMBERS_TODAY}. The emptiness above is green over a walk that found "
        f"nothing, and this is what tells the two apart"
    )

def test_no_docstring_under_src_carries_a_rest_field_line_or_a_sphinx_role() -> None:
    """Every docstring under `src/`, on the surface and off it, attribute docstrings included.

    The format half reads only docstrings that write a Google section, so a reST block is invisible
    to it wherever a docstring is not mandatory. This walk reads every one, and the floor is what
    stops a walk that found none from passing.
    """
    carrying: list[str] = []
    read = 0
    for source in sorted(SOURCE_ROOT.rglob("*.py")):
        text = source.read_text(encoding="utf-8")
        read += sum(1 for _ in _docstrings(ast.parse(text).body, ""))
        carrying += [
            _carries_rest(str(source.relative_to(REPO_ROOT)), finding)
            for finding in rest_constructs(text)
        ]

    assert not carrying, "\n".join(carrying)
    assert read >= SOURCE_DOCSTRINGS_TODAY, (
        f"only {read} docstring(s) were read under {SOURCE_ROOT}, under the floor of "
        f"{SOURCE_DOCSTRINGS_TODAY}, so a walk reading none of them could not be told from a "
        f"tree with nothing to report"
    )

def test_an_overload_stub_docstring_never_reaches_the_function_at_run_time() -> None:
    """Why the implementation carries the docstring and a stub is not required to.

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
# over the whole tree. `_WORKED` is the docstring `src/agl/sdk/tools.py::tool` writes - held to that
# by `test_the_worked_example_here_and_the_tool_docstring_in_the_sdk_agree` and not by this
# sentence - and every violating case below is that same docstring with one thing changed.
# ---------------------------------------------------------------------------------------------

_WORKED: Final = '''
def tool(name: str, description: str, payload: type, handler: object) -> Tool:
    """Builds a tool an agent can call.

    Args:
        name: The name the agent calls it by, unique within a [`Role`][agl.sdk.Role].
        description: The whole of what the agent reads to decide this is the tool it wants.
        payload: The dataclass the agent's arguments are checked against and built into.
        handler: The coroutine awaited with the built payload; its result goes back to the agent.

    Returns:
        The tool to put on a `Role`.

    Raises:
        InputError: An empty name or description, or a payload that can't be saved as JSON.
    """
'''

# The file `_WORKED` is a copy of, by its path below `REPO_ROOT`, and the callable both of them
# write. `src/` is what an author hovers.
_WORKED_EXAMPLE_SOURCE: Final = "src/agl/sdk/tools.py"
_WORKED_EXAMPLE_SYMBOL: Final = "tool"

def _worked_example(source: str, shown: str) -> tuple[str, list[str]]:
    """One copy of the worked example: the docstring it writes and the parameters it names.

    The docstring comes back through `ast.get_docstring`, which cleans with `inspect.cleandoc`, so
    the common left margin of the continuation lines is the one thing normalised away. That margin
    says where a copy sits rather than what it says, and the cleaned text is what a tooltip renders
    - which is the whole of what the docstring exists for. Everything else is compared as written: a
    second space inside an entry is a difference and is reported as one.

    Annotations are not read. `_WORKED` writes simplified ones on purpose, so that its snippet
    needs no import to parse, and the parameter names are what every `Args:` entry hangs on.
    """
    written = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == _WORKED_EXAMPLE_SYMBOL
    ]
    assert len(written) == 1, (
        f"{shown} writes {len(written)} module-level `def {_WORKED_EXAMPLE_SYMBOL}`, and the "
        f"worked example is exactly one of them. Nothing below can compare two copies of a "
        f"docstring while one of the two is missing or doubled"
    )
    docstring = ast.get_docstring(written[0])
    assert docstring is not None, (
        f"{shown} writes `{_WORKED_EXAMPLE_SYMBOL}` with no docstring at all, and the docstring "
        f"is the whole of what the worked example is"
    )
    return docstring, _expected(written[0], method=False)

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
        f"The worked example is written out twice and the two are one text. "
        f"{_WORKED_EXAMPLE_SOURCE} is the callable an author hovers, and `_WORKED` in this file is "
        f"what every fabricated case below mutates. Edit one and the other is stale in the "
        f"same instant: the cases below mutate a docstring that exists nowhere. The edit goes in "
        f"both."
    )

def test_the_worked_example_here_and_the_tool_docstring_in_the_sdk_agree() -> None:
    """`_WORKED` above and `tool`'s own docstring, compared.

    Two copies exist because each is load-bearing where it sits and neither can be a reference to
    the other. Every fabricated case below is `_WORKED` with one thing changed, and a fixture that
    read its own text off disk at run time would mutate whatever the source happened to say rather
    than the docstring the cases were written against - which is why `_WORKED` is a literal here.
    And the source is the one an author hovers, which is what makes the copy worth keeping honest.

    So there is no single source to collapse them into, and what is left is to compare them. The
    comparison is over the two things both genuinely share, the cleaned docstring and the
    parameter names in signature order, and a failure diffs the copy that moved.
    """
    source = (REPO_ROOT / _WORKED_EXAMPLE_SOURCE).read_text(encoding="utf-8")
    docstring, parameters = _worked_example(source, _WORKED_EXAMPLE_SOURCE)
    shown = f"`_WORKED` in tests/{Path(__file__).name}"
    held, named = _worked_example(_WORKED, shown)
    assert held == docstring, _a_copy_of_the_worked_example_moved(
        shown, "docstring", docstring, held
    )
    assert named == parameters, _a_copy_of_the_worked_example_moved(
        shown, "parameter list", "\n".join(parameters), "\n".join(named)
    )

def _one_problem(source: str, *, documented: bool = False) -> str:
    """The single problem a fabricated snippet is written to produce, asserted to be single."""
    found = docstring_problems(source, documented=documented)
    assert len(found) == 1, [finding.problem for finding in found]
    return found[0].problem

def test_the_scan_is_silent_on_the_docstring_the_convention_is_written_around() -> None:
    """The agreeing case, and it is not a token one: the worked example `tool` itself writes."""
    assert not docstring_problems(_WORKED, documented=True)

def test_the_scan_reports_a_parameter_renamed_without_the_docstring_following_it() -> None:
    """The failure this whole file exists for, and the only one that costs a reader anything."""
    problem = _one_problem(_WORKED.replace("payload: type", "shape: type", 1))
    assert "'payload'" in problem and "'shape'" in problem

def test_the_scan_reports_a_parameter_the_docstring_never_names_at_all() -> None:
    """A parameter added to the signature and not to the docstring: the entry is simply missing."""
    assert "missing ['handler']" in _one_problem(
        _WORKED.replace("        handler: The coroutine awaited with the built payload; its "
                        "result goes back to the agent.\n", "")
    )

def test_the_scan_reports_an_args_entry_naming_something_that_is_not_a_parameter() -> None:
    """The other direction: an entry left behind after the parameter it described was deleted."""
    assert "named but not a parameter ['timeout']" in _one_problem(
        _WORKED.replace("\n\n    Returns:", "\n        timeout: How long to wait.\n\n    Returns:")
    )

def test_the_scan_reports_two_args_entries_written_in_the_wrong_order() -> None:
    """Both names real, both present, and every description against the wrong one."""
    swapped = _WORKED.replace(
        "        name: The name the agent calls it by, unique within a [`Role`][agl.sdk.Role].\n"
        "        description: The whole of what the agent reads to decide this is "
        "the tool it wants.\n",
        "        description: The whole of what the agent reads to decide this is "
        "the tool it wants.\n"
        "        name: The name the agent calls it by, unique within a [`Role`][agl.sdk.Role].\n",
    )
    assert "in a different order" in _one_problem(swapped)

def test_the_scan_reports_a_type_written_into_an_args_entry_beside_the_name() -> None:
    """`name (str): text` is a second copy of the annotation, and nothing compares the two."""
    problem = _one_problem(_WORKED.replace("        name: The", "        name (str): The"))
    assert "writes a type into the entry" in problem and "`name:`" in problem

def test_the_scan_reports_a_starred_spelling_of_a_parameter_it_would_otherwise_accept() -> None:
    """`*flags` is the signature's syntax; the entry names the parameter without them."""
    source = (
        'def arg(*flags: str) -> None:\n'
        '    """Declare a flag.\n'
        '\n'
        '    Args:\n'
        '        *flags: The flags a shell will spell.\n'
        '    """\n'
    )
    assert "keeps the stars" in _one_problem(source)

def test_the_scan_reports_a_returns_section_missing_where_the_signature_hands_one_back() -> None:
    """A docstring that stops at the parameters leaves the value the caller is after undescribed."""
    assert "no `Returns:` section" in _one_problem(
        _WORKED.replace("\n    Returns:\n        The tool to put on a `Role`.\n", "\n")
    )

def test_the_scan_reports_a_returns_section_on_a_callable_annotated_to_return_none() -> None:
    """There is no value, so the section describes nothing."""
    source = 'def act() -> None:\n    """Do it.\n\n    Returns:\n        Nothing much.\n    """\n'
    assert "returns `None`" in _one_problem(source)

def test_the_scan_reports_a_returns_section_on_a_callable_that_never_returns_at_all() -> None:
    """`RefusingParser.error` is the shape: it raises, so `Returns:` would be a lie."""
    source = (
        'def error(message: str) -> NoReturn:\n'
        '    """Refuse the parse.\n'
        '\n'
        '    Args:\n'
        '        message: What argparse was going to print.\n'
        '\n'
        '    Returns:\n'
        '        Never happens.\n'
        '    """\n'
    )
    assert "does not come back at all" in _one_problem(source)

def test_the_scan_is_silent_on_a_never_returning_callable_that_writes_no_returns() -> None:
    """The same signature done right, which is the half a one-sided rule would get wrong."""
    assert not docstring_problems(
        'def error(message: str) -> NoReturn:\n'
        '    """Refuse the parse.\n'
        '\n'
        '    Args:\n'
        '        message: What argparse was going to print.\n'
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
        '    Args:\n'
        '        value: The value.\n'
        '    """\n'
    )
    assert "runs past one line" in _one_problem(source)

def test_the_scan_reports_a_section_this_format_does_not_have_and_names_the_three() -> None:
    """Second spellings, sections this format does not write, and the singular near miss."""
    for title in ("Arguments", "Parameters", "Exceptions", "Yields", "Examples", "Return"):
        source = (
            'def read() -> int:\n'
            '    """Read.\n'
            '\n'
            f'    {title}:\n'
            '        value: A number.\n'
            '\n'
            '    Returns:\n'
            '        A number.\n'
            '    """\n'
        )
        assert "not a section of this format" in _one_problem(source), title

def test_the_scan_permits_a_raises_entry_and_reports_one_that_names_no_exception() -> None:
    """`Raises:` is the third section: no annotation carries it and mypy does not check it."""
    assert not docstring_problems(
        'def read() -> int:\n'
        '    """Read.\n'
        '\n'
        '    Raises:\n'
        '        InputError: When the text is not a number.\n'
        '\n'
        '    Returns:\n'
        '        A number.\n'
        '    """\n',
        documented=True,
    )
    source = (
        'def read() -> int:\n'
        '    """Read.\n'
        '\n'
        '    Returns:\n'
        '        A number.\n'
        '\n'
        '    Raises:\n'
        '        When the text is not a number.\n'
        '    """\n'
    )
    assert "names no exception" in _one_problem(source)

def test_the_scan_reports_an_entry_carrying_a_name_and_no_description() -> None:
    """An empty description is structural rather than editorial, which is why it is read here."""
    assert "no description" in _one_problem(
        _WORKED.replace(
            "handler: The coroutine awaited with the built payload; its result goes back "
            "to the agent.",
            "handler:",
        )
    )

def test_the_scan_reports_a_section_title_with_no_blank_line_above_it() -> None:
    """Griffe renders such a title and its entries as text, and says so only at debug level."""
    assert "no blank line above" in _one_problem(
        _WORKED.replace("the agent.\n\n    Returns:", "the agent.\n    Returns:")
    )

def test_the_scan_reports_a_blank_line_between_a_title_and_its_entries() -> None:
    """The other half of Griffe's rule for taking a title up, and just as silent when broken."""
    assert "a blank line stands between" in _one_problem(
        _WORKED.replace("    Returns:\n        The tool", "    Returns:\n\n        The tool")
    )

def test_the_scan_reports_a_returns_continuation_at_the_indentation_of_its_entry() -> None:
    """One value, read by Griffe as two, because the second line sits where an entry starts."""
    split = "        The tool to put\n        on a `Role`."
    assert "reads as 2 entries" in _one_problem(
        _WORKED.replace("        The tool to put on a `Role`.", split)
    )

def test_the_scan_reports_an_args_continuation_at_the_indentation_of_its_entry() -> None:
    """The same slip under `Args:`, where the stray line reads as an entry with no name."""
    split = "checked against\n        and built into."
    assert "is not a `name: text` entry" in _one_problem(
        _WORKED.replace("checked against and built into.", split)
    )

def test_the_scan_reports_a_continuation_indented_less_than_twice_its_entry() -> None:
    """Between the entry's indentation and twice it: Griffe joins the line, with a warning."""
    split = "checked against\n          and built into."
    assert "less than twice as far" in _one_problem(
        _WORKED.replace("checked against and built into.", split)
    )

def test_the_scan_is_silent_on_continuation_lines_at_twice_the_entry_indentation() -> None:
    """The layout done right, under `Args:` and `Returns:` both, which is how `src/` writes it."""
    argument = "checked against\n            and built into."
    returned = "        The tool to put\n            on a `Role`."
    assert not docstring_problems(
        _WORKED.replace("checked against and built into.", argument).replace(
            "        The tool to put on a `Role`.", returned
        ),
        documented=True,
    )

def test_the_scan_reports_a_returns_entry_that_opens_on_a_name_or_a_type() -> None:
    """Griffe takes what stands before a leading colon as the value's name or type."""
    for opening in ("tool: The tool to put", "(Tool): The tool to put"):
        problem = _one_problem(_WORKED.replace("        The tool to put", f"        {opening}"))
        assert "name or type" in problem, opening

def test_the_scan_reads_no_section_title_inside_a_fenced_code_block() -> None:
    """Griffe passes over a fence's lines without looking for titles, and so does this."""
    assert not docstring_problems(
        'def read() -> int:\n'
        '    """Read.\n'
        '\n'
        '    ```python\n'
        '    Examples:\n'
        '        read()\n'
        '    ```\n'
        '\n'
        '    Returns:\n'
        '        A number.\n'
        '    """\n',
        documented=True,
    )

def test_the_scan_reports_a_section_written_twice_in_one_docstring() -> None:
    """One section of each kind, which is the only way a reader finds all of one in one place."""
    assert "twice" in _one_problem(
        _WORKED.replace(
            "        The tool to put on a `Role`.\n",
            "        The tool to put on a `Role`.\n\n    Returns:\n        Another tool.\n",
        )
    )

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
    """An attribute docstring, the one string above a `def` that is exactly where it should be."""
    assert not docstring_problems(
        'class Held:\n'
        '    """What this is."""\n'
        '\n'
        '    value: int\n'
        '    """The value, in seconds."""\n'
        '\n'
        '    def read(self) -> int:\n'
        '        """Read it.\n'
        '\n'
        '        Returns:\n'
        '            The value.\n'
        '        """\n'
        '        return self.value\n',
        documented=True,
    )

def test_the_scan_is_silent_on_a_type_alias_docstring_that_precedes_a_class() -> None:
    """Griffe reads the string after a `type` statement as the alias's docstring, as does this."""
    assert not docstring_problems(
        'type Component = int | str\n'
        '"""What a screen\'s body can be."""\n'
        '\n'
        'class Screen:\n'
        '    """What a person sees."""\n',
        documented=True,
    )

def test_the_scan_is_silent_on_a_module_docstring_standing_above_a_definition() -> None:
    """The first statement of a body is the docstring, at module, class and function alike."""
    assert not docstring_problems('"""One line."""\n\n\ndef build() -> None:\n    pass\n',
                                  documented=False)

def test_the_scan_reports_a_section_on_a_class_docstring_where_no_signature_is() -> None:
    """`Args:` describes a `def`'s parameters; on a class there is nothing to compare it to."""
    source = (
        'class Held:\n'
        '    """What this is.\n'
        '\n'
        '    Args:\n'
        '        value: The value.\n'
        '    """\n'
    )
    assert "not a callable" in _one_problem(source)

def test_the_scan_drops_self_and_cls_and_keeps_what_a_static_method_is_passed() -> None:
    """Implicit by position and by name, which is what makes the rule wrong for a static one."""
    assert not docstring_problems(
        'class Held:\n'
        '    def read(self) -> int:\n'
        '        """Read it.\n'
        '\n'
        '        Returns:\n'
        '            The value.\n'
        '        """\n'
        '        return 1\n'
        '\n'
        '    @classmethod\n'
        '    def build(cls, value: int) -> "Held":\n'
        '        """Build one.\n'
        '\n'
        '        Args:\n'
        '            value: The value.\n'
        '\n'
        '        Returns:\n'
        '            A held value.\n'
        '        """\n'
        '        return cls()\n'
        '\n'
        '    @staticmethod\n'
        '    def doubled(self: int) -> int:\n'
        '        """Double it.\n'
        '\n'
        '        Args:\n'
        '            self: A number that is not an instance.\n'
        '\n'
        '        Returns:\n'
        '            Twice it.\n'
        '        """\n'
        '        return self * 2\n',
        documented=True,
    )

def test_the_scan_reports_a_self_entry_written_on_an_ordinary_method() -> None:
    """No caller passes it, so an entry for it is an extra rather than a missing one."""
    source = (
        'class Held:\n'
        '    def read(self) -> int:\n'
        '        """Read it.\n'
        '\n'
        '        Args:\n'
        '            self: This object.\n'
        '\n'
        '        Returns:\n'
        '            The value.\n'
        '        """\n'
        '        return 1\n'
    )
    assert "named but not a parameter ['self']" in _one_problem(source)

def test_the_scan_reads_positional_only_keyword_only_and_both_starred_forms_in_order() -> None:
    """`Terminal.show`'s shape: a positional-only view, a keyword-only priority, and `**params`."""
    assert not docstring_problems(
        'class Terminal:\n'
        '    async def show(\n'
        '        self, view: object, /, *, priority: int = 0, **params: object\n'
        '    ) -> int:\n'
        '        """Put a view on screen.\n'
        '\n'
        '        Args:\n'
        '            view: The function the redraw loop invokes again every frame.\n'
        '            priority: Where a question joins the queue; higher is shown first.\n'
        '            params: Handed to the view unchanged on every invocation.\n'
        '\n'
        '        Returns:\n'
        '            What the person answered.\n'
        '        """\n'
        '        return 1\n',
        documented=True,
    )

def test_the_scan_is_silent_on_a_property_that_takes_nothing_and_hands_one_thing_back() -> None:
    """`Run.terminal` and `Terminal.pending`: summary and `Returns:`, and no clause makes it so."""
    assert not docstring_problems(
        'class Run:\n'
        '    @property\n'
        '    def terminal(self) -> object:\n'
        '        """The terminal this run shows through.\n'
        '\n'
        '        Returns:\n'
        '            The terminal the framework opened around the workflow.\n'
        '        """\n'
        '        return None\n',
        documented=True,
    )

def test_the_scan_is_silent_on_an_abstract_method_whose_body_is_an_ellipsis() -> None:
    """A port's contract, which is the one callable whose body says nothing at all."""
    assert not docstring_problems(
        'class Store:\n'
        '    @abstractmethod\n'
        '    async def read_entry(self, key: str) -> object:\n'
        '        """Read one entry back, or nothing where none was written.\n'
        '\n'
        '        Args:\n'
        '            key: The entry\'s address, which is its whole identity.\n'
        '\n'
        '        Returns:\n'
        '            What was written there, or None.\n'
        '        """\n'
        '        ...\n',
        documented=True,
    )

def test_the_scan_leaves_a_one_line_summary_alone_off_the_documented_surface() -> None:
    """A one-line summary everywhere but the documented surface, where sections are asked for."""
    source = 'def build(value: int) -> int:\n    """Build one from a value."""\n    return value\n'
    assert not docstring_problems(source, documented=False)
    problems = [finding.problem for finding in docstring_problems(source, documented=True)]
    assert any("missing ['value']" in problem for problem in problems)
    assert any("no `Returns:` section" in problem for problem in problems)

def test_the_rest_scan_reports_fields_and_roles_but_not_prose_in_code_font() -> None:
    """A role on a class and on an attribute, a field on a method, and code font on an alias."""
    found = rest_constructs(
        'class Held:\n'
        '    """Held on a :class:`Screen`."""\n'
        '\n'
        '    value: int\n'
        '    """The value, as a :class:`Row`."""\n'
        '\n'
        '    def read(self, key: str) -> int:\n'
        '        """Read it.\n'
        '\n'
        '        :param key: The key.\n'
        '        """\n'
        '        return 1\n'
        '\n'
        'type Component = int\n'
        '"""What a `:class:` role and a `:param name:` field look like, in code font."""\n'
    )
    assert [(finding.symbol, finding.problem) for finding in found] == [
        ("Held", _SPHINX_ROLE_FOUND),
        ("Held.value", _SPHINX_ROLE_FOUND),
        ("Held.read", _REST_FIELD_FOUND),
    ]

def test_the_rest_scan_reports_return_raises_type_and_rtype_fields_each_alone() -> None:
    """`:return:`, `:raises Error:`, `:type name:` and `:rtype:`, each on a line of its own."""
    for written in (":return: A number.", ":raises InputError: Always.", ":type key: str",
                    ":rtype: int"):
        found = rest_constructs(f'def read() -> int:\n    """Read.\n\n    {written}\n    """\n')
        assert [finding.problem for finding in found] == [_REST_FIELD_FOUND], written

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
    """`sdk/_engine/` is off the workflow author's surface, and so is `_declarations`."""
    none: frozenset[str] = frozenset()
    assert _is_documented_surface("agl.sdk.tools", none)
    assert _is_documented_surface("agl.ports.store", none)
    assert not _is_documented_surface("agl.sdk._engine.journal", none)
    assert not _is_documented_surface("agl.sdk._declarations", none)
    assert not _is_documented_surface("agl.adapters.git.history", none)
    assert not _is_documented_surface("agl.api", none)

def test_the_surface_predicate_admits_a_private_module_the_front_door_imports_from() -> None:
    """An underscore does not take a module off the surface while `agl.sdk` exports from it."""
    front_door = _front_door_sources(
        'from agl.sdk._workflow import Run, workflow\nfrom agl.sdk.roles import Role\n'
    )
    assert front_door == frozenset({"agl.sdk._workflow", "agl.sdk.roles"})
    assert _is_documented_surface("agl.sdk._workflow", front_door)
    assert not _is_documented_surface("agl.sdk._engine.journal", front_door)
