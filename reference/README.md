# Reference extracts — read-only

Five files from the previous AGL implementation. They are here for one reason: they contain
hard-won details that are expensive to rediscover.

> **These citations were written from memory, and stage 5 proved two of five wrong.**
> Verify a claim before relying on it. If a file does not contain what its row promises, say so in
> the stage report and write from the tool's own documentation instead — do not invent a
> justification for whatever happens to be in the file.

| File | What to take from it | Cited by | Status |
|---|---|---|---|
| `options.py` | Claude Code hermeticity: `setting_sources=[]`, `strict_mcp_config=True`, absolute settings path | stage 7 | unverified |
| `git_runner.py` | subprocess invocation shape only — **see warning below** | stage 5 | ⚠ partly wrong |
| `git.py` | worktree edge cases, and the **worktree** porcelain parser | stage 5 | ⚠ partly wrong |
| `git_merges.py` | merge state machine, conflict detection | stage 5 | verified at stage 5 |
| `rich_terminal.py` | the `rich.Live` stderr-corruption workaround | stage 6 | unverified |

## Corrections found at stage 5

**`git_runner.py` contains no timeout handling.** The original row cited it for "subprocess
execution, timeouts." It delegates timeouts to a module that was never extracted, so there is
nothing here to take on that subject.

**`git_runner.py` carries `FileStatus.code: str`.** This is the defect §1.3 of the plan names by
name — raw git porcelain codes crossing a port boundary. It is the single thing in this directory
that must not be copied. It is left in place rather than edited, because these are extracts and
editing them would make the remaining rows untrustworthy in a different way.

**`git.py` holds the worktree porcelain parser, not the status-code parser.** The original row cited
it for "porcelain parsing" without qualification. Stage 5.3's `ChangeKind` mapping was written fresh
from git's documentation and verified against git 2.50.

## Rules

- Read a file **only** when a deliverable explicitly cites it. Never browse this directory.
- Take the specific detail. Do **not** copy structure, naming, or approach — the new architecture is
  deliberately different, and the old code's danger is that it is coherent enough to pattern-match
  against. The old `Vcs` is one 27-method class; the new one is three narrow adapters.
- If what you find contradicts the row above, the row is wrong. Report it.
