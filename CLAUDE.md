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
- **`src/` carries comments again**, under the comment convention below: inline `#` and nothing
  else. There are no docstrings in `src/` at all, and that is the convention's outcome rather than
  a gap waiting to be filled. `tests/`, `scripts/check`, `.importlinter` and `pyproject.toml`
  still hold the reasoning that has no single line of code to sit on.
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
units or lifetime fact the type does not encode. None of it is mechanical; every rule is a
reviewer's. The calibration, which nobody can rederive cheaply: of the 1,500 entries the strip
removed, **87 earned a line back** — every one an inline `#`, and no docstring survived C1.

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
- **import contracts** — `lint-imports` over `.importlinter`'s six contracts.
- **Codex CLI binary containment** — the binary's name may appear in no `.py` under `src/`
  outside `agl/adapters/openai/`.
- **module size ceiling** — **warning only; it never fails the build.** Counts *code* lines
  against a 300-line convention; docstrings, comments and blank lines count zero.
- **package root holds no imports** — `src/agl/__init__.py` must contain no import statement.
  This is the one import rule `.importlinter` cannot express.
- **paid-endpoint guard** — no test can reach a paid endpoint: an AST scan for a test writing a
  guarded environment variable outside `tests/conftest.py`, plus a probe module written into
  `tests/`, run with the real endpoints poisoned, and deleted again.

Refer to gates by name, never by number — gates get inserted and the numbering shifts under any
cross-reference that names one.
