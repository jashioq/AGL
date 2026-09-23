# AGL

A framework for running AI agent workflows against code repositories.

## How to work here

- Verify with `./scripts/check`, not by reading source.
- `reference/` is read-only, and opened only when a task names it.
- Report ambiguity rather than resolving it.
- Do not commit unless asked.

## The gates

`./scripts/check` runs all eight gates every time. Name a gate, never number it.

- Exit 0 is green, 1 a failure, 2 missing `.venv` tooling.
- The module size ceiling only warns.
- Green needs `Contracts: 5 kept, 0 broken.`, read as numbers.

## Traps

- `.venv` installs AGL editable against the real `src/`, and `tests/conftest.py` adds only
  `tests/` to `sys.path`. So rsync a scratch copy without `.git`, `reference`, `dist`, `.venv` and
  caches, symlink `.venv` in, export `PYTHONPATH=<copy>/src`, and check `agl.__file__`.
- `~/.agl` is the operator's live workspace. Diff
  `find ~/.agl -type f -print0 | xargs -0 shasum -a 256 | sort` before and after a gate run.
  Never `xargs -I{}`.

## Layers

`{cli, testing} → api → config → {sdk, adapters} → ports`

- Contract 1 is exhaustive: a new package under `src/agl/` breaks it until it is a layer.
- `ports` imports only the standard library and itself: `tests/test_ports_stdlib_only.py`.
- Only `config/container.py` constructs an adapter: contract 5.
- `api.py` has no `except`: `tests/test_api_no_except.py`.
- Only `adapters/openai/` names the Codex binary: the Codex CLI binary containment gate.
- `src/agl/__init__.py` holds no imports: the package-root gate.
- A command only parses, calls `api` and renders: the `tests/cli/` scans.
- `sdk/_engine/` is hidden from authors, not from the framework.

## Prose in `src/`

- Inline `#` everywhere. Google-style docstrings only on public callables of `sdk/` and `ports/`.
  Elsewhere, one line where the signature falls short, and none in `sdk/_engine/`.
- A comment carries a fact from outside the file, like vendor behaviour or a measurement.
  What thirty seconds of reading shows gets none.
- An inline `#` covers the line beneath, four lines at most. No comment passes ten.
- Record the outcome, never history or plans.
- A load-bearing fact belongs in a test, assertion or type.
- Ruff and `tests/`'s `test_docstring_fields.py`, `test_naming_convention.py`,
  `test_named_not_numbered.py` and `test_blank_line_convention.py` hold the rest.
  `src/agl/sdk/tools.py::tool` is the worked docstring.
- British English, but mirror vendor spellings.
- Parallel siblings share internal names deliberately.
- Spell words out. Domain short forms like `ref` and `sha` are fine.
- A test name is an 8-to-14-word claim.

## The voice

- `DOCS_GUIDELINES.md` governs SDK docstrings and `docs/`, `overrides/` and `tests/docs/`.
- Terminal output is one capitalised sentence of fact, then at most the next move or what is lost.
  Warnings open `WARNING:`.
- Names in double quotes. Versions and commits bare.
- Help is one sentence per description. Arguments add `If omitted, …`.
- Shorten a pinned message, never its tested claim.

## Invariants where a mistake is silent

- A step with no `commit=` wipes its worktree. Nothing checks the pairing.
- `GatedIntegration._conclude` hands a landing to the parent's chain, or the next miss resets
  past it.
- A red build gate discards a hand-resolved conflict.
- Resume re-runs every line, so a workflow branches only on step results.
- Replay skips the worker, so a step's effects must land in its workspace.
- Fingerprints must match across processes. Test under several `PYTHONHASHSEED` values.
- Every dataclass in a step's inputs, role or result, `agl.ports` ones included, is fingerprinted
  by its `module.qualname` and field names, and every enum by its value. Moving or renaming one
  re-runs recorded steps.
- Agent environments allowlist their vendor's namespace. A leaked `CLAUDE_CODE_EFFORT_LEVEL`
  beats `--effort`.
- Model-keyed tables take `model_of`'s bare `ModelId`. A chosen effort type-checks and misses.
- A placed workflow's hash exclusions never move, or `agl update` discards edits unasked.
- Overrides and removals leave `workflows/` by one rename; a failed override renames back.
  Never delete in place or follow a link.

## Deliberately not built

- No `on_question`. A question is an ordinary tool.
- No `Run.activity`. Activity goes to the role's `on_activity`.
- No harness helper for watching a run.
- No config-level model override.
- No cache or suppression flag on version notes.
- No Claude per-model effort probe, pending a decision.
- No environment scrubbing beyond the vendor's namespace.
- No default for a project setting.
- No fan-out helper.
- No general subprocess helper.
- No safe mode on `agl clear`. A `--force` becomes reflex.
- No `Integrator.revert()`. `Workspace.restore(head)` does it.
- No generated commit message.
- No second `IntegrationOutcome` case.
- `Store` keeps six members.
- No build-gate retry.
- No `auto()` on an enum.
