# AGL

A framework for running AI agent workflows against code repositories. The build is finished.
`ARCHITECTURE.md` is the map — the layers, the dependency rule, and the invariants where a
mistake is silent. Read it before you add a file.

## How to work here

- **Verify mechanically.** `./scripts/check` is the answer to "is this right". Read its output
  rather than reading source to convince yourself.
- **`reference/` is read-only** extracts from a previous implementation. Open a file there only
  when a task names it. Never browse it.
- **Report ambiguity rather than resolving it silently.** A guess that type-checks is worse than
  a question, because nothing downstream can tell the two apart.
- **`src/` carries two kinds of prose and they are there for two different reasons.** Inline `#`
  everywhere, under the comment convention below, and nothing else — no docstring earns its place
  as a comment, which is that convention's outcome rather than a gap waiting to be filled. On top
  of it, and only on the public callables of `sdk/` and `ports/`, a reST docstring under the
  docstring convention below. That layer is not a comment and is not judged as one: it is there
  because it renders in an author's IDE at the call site, where no `#` reaches, and it is held to
  its shape by `tests/test_docstring_fields.py` rather than by a reviewer. `tests/`,
  `scripts/check`, `.importlinter` and `pyproject.toml` still hold the reasoning that has no single
  line of code to sit on.
- Do not commit unless you are asked to.

## The naming convention

Nine rules, and what checks each one is the first thing to know about them. **Mechanical:** ruff's
`pep8-naming` — selected as `N` in `pyproject.toml`, where its exemptions are written with their
reasons — holds the casing of classes, functions, arguments, locals and class attributes;
`tests/test_naming_convention.py` holds N1, N2, N3's `adapters/` half, N5, N8's floor and N9.
**A reviewer's:** N4, N6, N7, N3's `sdk/_engine/` half, and N8's 8-to-14-word target.

- **N1. Grammar states the contract.** `_verb() -> None` acts, `_participle() -> X` transforms,
  `_noun() -> X` derives, `_sentence_fragment() -> str` builds a message. A past participle never
  names a function returning `None`.
- **N2.** `_check_x` raises and answers with nothing; `_checked_x` answers with what it validated.
- **N3.** A leading underscore on a *module* means "not on the surface this package promises", and
  the package must say which surface. `adapters/<pkg>/_x.py` is private to that package;
  `sdk/_engine/` is off the workflow author's surface and the framework imports it freely.
- **N4. British English** in prose and in AGL's own identifiers. Where a vendor or a protocol
  spells it American, mirror the vendor exactly and never translate.
- **N5. One name per concept, never one name for two.** A type defined in `ports/` is not
  redefined.
- **N6. Parallel siblings share names deliberately.** Two adapters implementing one port with the
  same internal names is not duplication.
- **N7. Spell words out.** Domain-standard short forms are fine — `ref`, `sha`, `repo`, `cli`,
  `json`, `http`, `rpc`, `toml`. No single-letter names outside a comprehension.
- **N8. A test name is a sentence** — subject, verb, object, 8 to 14 words, reading as a claim that
  is true when the test passes. Only the four-word floor is enforced; the target is judgement.
- **N9.** Constants `SCREAMING_SNAKE` and `Final`; classes and type aliases `CamelCase`; a private
  of either takes one leading underscore.

## The comment convention

Ten rules, and one test decides all of them: **if it can be figured out by looking at the code for
thirty seconds, it does not get a comment.** What is left earns its place only by carrying **a
fact from outside the file** — vendor behaviour, an OS or protocol guarantee, a measured number, a
units or lifetime fact the type does not encode. One of the ten is mechanical —
`tests/test_named_not_numbered.py` holds C8 — and the other nine are a reviewer's. The calibration,
which nobody can rederive cheaply: of the 1,500 entries the strip removed, **87 earned a line
back** — every one an inline `#`, and no docstring survived C1.

- **C1. Say what the code cannot.** The fact from outside the file is the whole of what a comment
  is for; everything else is the thirty-second test's business.
- **C2. Module docstring: one line. Two at the outside.**
- **C3. Class docstring: one line — "what this is: its parts".** A second paragraph only for a
  usage requirement a caller must obey.
- **C4. Function docstring: one line, and only when the signature does not already say it.**
- **C5. Attribute docstring: one line, and only where the type under-describes the value.**
- **C6. An inline `#` speaks for the line beneath it**, and runs to four lines at most.
- **C7. Ten lines is the ceiling for any comment, two for a module docstring.** Longer is one of
  three things with a home elsewhere: a requirement becomes a test, an architectural rule becomes
  an `ARCHITECTURE.md` section or an import contract, a design narrative leaves `src/` altogether.
  Workflows never get large explanatory comments.
- **C8. Named, not numbered.** Cite nothing that can be deleted without breaking a build. Refer to
  a module, a symbol, a test or an `ARCHITECTURE.md` heading, so a stale reference breaks loudly
  rather than quietly pointing at nothing.
- **C9. Record the outcome, not the history, and never the future.** Git holds the history.
- **C10. State no fact you cannot check, in a place that cannot check it.** A load-bearing
  sentence belongs in a test, an assertion or a type; a comment may summarise a guard and name it,
  but it may not be the guard.

## The docstring convention

Eight rules, and what checks each one is the first thing to know about them.
**Mechanical:** `tests/test_docstring_fields.py` holds D1 through D7 — the placement, the shape,
the surface where a block is mandatory, and every disagreement between a field list and the
signature it sits on. **A reviewer's:** D8 alone, which is the only half that reads a description.

**It exists for one thing no comment can do: it renders in the author's IDE at the call site.**
PyCharm parses `:param:` natively; VS Code needs `"python.analysis.supportRestructuredText": true`,
which is what `.vscode/settings.json` in this repository is for, and without it Pylance shows the
block as raw text. **The convention assumes that setting.** It also inverts C1 deliberately — a
`:param:` line restates a name from inside the file, which C1 refuses everywhere else, and it is
allowed to only because the restatement is *structural* and a test compares it against the
signature on every run. That trade is written out in `tests/test_docstring_fields.py`'s docstring,
and it is why this is a separate convention rather than a clause in the one above.

```python
def tool[P](
    name: str,
    description: str,
    payload: type[P],
    handler: Callable[[P], Awaitable[ToolResult]],
) -> Tool:
    """Build a tool an agent can call, validating its payload before the handler sees it.

    :param name: what the agent calls it; must be unique within a role
    :param description: what the agent is told the tool is for
    :param payload: dataclass the arguments are built into; edit a field and no entry replays
    :param handler: awaited with the built payload; no fingerprint term, so an edit re-runs nothing
    :return: a tool ready to go on a role
    """
```

- **D1. The block is the first statement inside the body.** A string written *above* the `def` is
  an expression Python evaluates and throws away: `__doc__` is `None` and no tooltip renders, while
  the source looks right.
- **D2. Summary, blank line, fields.** The summary is one line — not one sentence wrapped over two
  — then a blank line, then the field list.
- **D3. One `:param name:` per parameter, in the order the signature writes them.** None missing,
  none extra. `self` and `cls` are not passed by a caller and are not named; a `*flags` is named
  `flags` and a `**params` is named `params`, the stars being signature syntax.
- **D4. `:return:` exactly where something comes back.** Never on a `-> None`, and never on a
  `-> NoReturn`, which does not come back at all and has no value to describe.
- **D5. No type in the line, and three fields only.** `:param str name:` restates the annotation
  `mypy --strict` already checks, in a place nothing checks. The three are `:param name:`,
  `:return:` and `:raises Error:` — the last earns its place because no annotation carries it.
  `:type:`, `:rtype:` and `:returns:` are not among them.
- **D6. Every public callable in `sdk/` and `ports/` carries a block**, so a newly added one cannot
  ship without one. Nothing is exempt and there is no list to add a name to; what keeps an empty
  walk from passing as a documented tree is the floor `PUBLIC_CALLABLES_TODAY` in
  `tests/test_docstring_fields.py`. A dunder is out, because a name syntax invokes is never hovered.
- **D7. Everywhere else in `src/`, C4's one line and no field block.** `adapters/`, `config/`,
  `cli/`, `api.py` and `testing.py` take a one-line summary only where the signature does not
  already say it. `sdk/_engine/` takes nothing at all: nobody hovers it from outside.
- **D8. The description earns its place** — a constraint, a lifetime, a unit, a consequence — and
  is never a restatement of the name. This is C1's spirit surviving the inversion, and it is the
  half no gate reads.

## The blank-line convention

Four rules, and one file holds all four: `tests/test_blank_line_convention.py` parses both trees and
names the file and the line of anything it objects to, so none of this is a reviewer's. What that
file deliberately does *not* hold is the sorting — `I001`, configured under `pyproject.toml`'s
`[tool.ruff.lint.isort]`, orders the import block and decides where a separator goes inside it, and
the `no-lines-before` and `lines-after-imports` settings written there are what keep the lint gate
and the test from arguing about the same blank line. ruff's own blank-line rules are preview-only,
so a bare `ruff check` holds none of the four. Blank lines *inside* a function body are judgement
and the convention says nothing about them.

- **B1. The imports are one contiguous block.** One blank line is permitted and only directly above
  a standalone comment, because `I001` mandates that one and puts it back if it is removed.
- **B2. One blank line between top-level definitions, never two adjacent.** A blank, a `# ---`
  banner and a blank again is not two adjacent and is the layout; an `@overload` stack with no gap
  at all is idiomatic and stays.
- **B3. No blank line under a `class` statement.** The docstring, the first attribute or the first
  method sits directly under the header, however many lines the header itself takes.
- **B4. No blank line at the top of a file.** A zero-byte `__init__.py` has no first line and is not
  one of these.

## The gates

```
./scripts/check
```

Eight gates, seven of which can fail the build. Every gate runs every time — the run does not
stop at the first failure — and a summary repeats each verdict at the end. Exit status is 0 if
every gate passed, 1 if any failed, 2 if the `.venv` tooling is missing (`uv sync`).

- **tests** — `pytest` over `tests/`.
- **types** — `mypy --strict src tests`. Both trees, not just `src`.
- **lint** — `ruff check`. A finding fails the build, and there is no `--fix`.
- **import contracts** — `lint-imports` over `.importlinter`'s five contracts.
- **Codex CLI binary containment** — the binary's name may appear in no `.py` under `src/`
  outside `agl/adapters/openai/`.
- **module size ceiling** — **warning only; it never fails the build.** Counts *code* lines
  against a 300-line convention; docstrings, comments and blank lines count zero.
- **package root holds no imports** — `src/agl/__init__.py` must contain no import statement.
  This is the one import rule `.importlinter` cannot express.
- **paid-endpoint guard** — no test can reach a paid endpoint: an AST scan for a test writing a
  guarded environment variable outside `tests/conftest.py`, plus a probe module written into
  `tests/`, run with the real endpoints and a stand-in for the operator's AGL home poisoned into
  its environment, required to see a lookup and a connection off this machine refused by the
  guard, and deleted again.

Refer to gates by name, never by number — gates get inserted and the numbering shifts under any
cross-reference that names one.
