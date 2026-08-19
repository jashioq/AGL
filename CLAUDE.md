# AGL

Green-field build. `docs/agl-refactor-plan.md` is the architecture and the source of
truth for every design decision. `docs/agl-build-stages.md` is the build order.

## Rules for every session

- The main agent NEVER writes code. It spawns one subagent per deliverable, in series,
  and verifies mechanically (`scripts/check`) rather than by reading source.
- Verification is `pytest`, `mypy --strict`, `lint-imports`. Read the output, not the code.
- If a fixer subagent fails twice on the same deliverable: halt and report.
- `reference/` is read-only extracts from the previous implementation. Read a file ONLY
  when a deliverable cites it by name. Never browse it.
- Do not begin the next stage. One stage per session.
- Report ambiguity rather than resolving it silently.
