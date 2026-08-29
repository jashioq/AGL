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
- **`src/` carries no comments and no docstrings.** That is deliberate and was done in one pass.
  The comment and naming conventions that replace them are being written separately and are
  pending, so do not invent one meanwhile. `tests/`, `scripts/check`, `.importlinter` and
  `pyproject.toml` keep their prose and are where the reasoning now lives.
- Do not commit unless you are asked to.

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
