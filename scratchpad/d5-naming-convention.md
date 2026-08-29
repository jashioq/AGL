# AGL naming convention

**N1. Grammar states the contract. (Keep this - it is real, not noise.)**
  - `_verb(...) -> None`      an action. Does the thing; returns nothing.
  - `_participle(...) -> X`   a transformation. Gives back the value, named for what it now is.
  - `_noun(...) -> X`         a derivation. Named for the thing it returns.
  - `_sentence_fragment(...) -> str`  a message builder (`_because`, `_not_ready`, `_unmet`).
  A past participle must never name a function that returns `None`.
  Checkable: any `def _*ed(` or irregular participle whose return annotation is `None`.

**N2. `_check_x` raises; `_checked_x` returns.** Already perfectly held (4 and 8 of each).

**N3. Modules: `_name` means "not on the surface this package promises".**
State which surface in the package `__init__.py` one-liner, because there are two:
  - `adapters/*/_x.py` - private to that adapter package. Enforceable, and held 16/16.
  - `sdk/_engine/` - not on the *workflow author's* surface; freely imported by the
    framework. Say so, or the mark reads as a lie 7 times.
Enforce the adapter half with a `.importlinter` forbidden contract.

**N4. British English in prose and in AGL's own identifiers**
(`normalise`, `serialise`, `behaviour`, `recognise`). Where a vendor, protocol or stdlib
spells it American, mirror the vendor exactly and never translate - `_initialize` at
`adapters/openai/_tools.py:159` is correct because the MCP method is `"initialize"`.

**N5. One name per concept, and never one name for two.**
`label` = a run label. `name` = the name of some other thing. `digest`, `project`,
`namespace` as spelled. A type name defined in `ports/` may not be redefined elsewhere.

**N6. Parallel siblings share names deliberately.** Two adapters implementing one port
should use the same internal names (`Asking`, `Conversation`, `Script`, `FakeAgentRunner`,
`_Place`). This is not duplication; keep it.

**N7. Spell words out.** No invented abbreviations. Domain-standard short forms are fine
(`ref`, `sha`, `repo`, `cli`, `json`, `http`, `rpc`, `toml`). No single-letter names
except a comprehension index.

**N8. Test names are sentences.** `test_<subject>_<verb>_<object/condition>`, 8-14 words,
reading as a claim that is true when the test passes. Never `test_<what>_<condition>`.
Regex: `^test_[a-z0-9_]{25,}$` with >= 6 underscores.

**N9. Constants SCREAMING_SNAKE + `Final`; classes and type aliases CamelCase;
private of either takes one leading underscore.** Already held 272/272, 149/149, 23/23.

## Enforcement
Add to `pyproject.toml` `[tool.ruff.lint] select` (currently `["E","F","I","UP","B"]`):
  `"N"`  - pep8-naming: N801/N802/N803/N806/N815/N818. Covers N9 and most of N7.
  `"D"` is NOT recommended: it mandates docstrings, which C4/C5 deliberately do not.
N1, N2, N8 need a repo test (the repo already has five of this shape, e.g.
`tests/adapters/test_filesystem_no_lock.py`). N3-N6 are reviewer judgement.
