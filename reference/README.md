# Reference extracts — read-only

Five files from the previous AGL implementation. They are here for one reason: they
contain hard-won details that are expensive to rediscover.

| File | What to take from it | Cited by |
|---|---|---|
| `options.py` | Claude Code hermeticity: `setting_sources=[]`, `strict_mcp_config=True` | stage 7 |
| `git_runner.py` | subprocess execution, timeouts | stage 5 |
| `git.py` | worktree edge cases, porcelain parsing | stage 5 |
| `git_merges.py` | merge state machine, conflict detection | stage 5 |
| `rich_terminal.py` | the `rich.Live` stderr-corruption workaround | stage 6 |

## Rules

- Read a file ONLY when a deliverable explicitly cites it.
- Take the specific detail. Do NOT copy structure, naming, or approach — the new
  architecture is deliberately different, and the old code's danger is that it is
  coherent enough to pattern-match against.
- Never browse this directory. Never read a file no deliverable cited.
