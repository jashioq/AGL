# AGL

AGL runs AI agent workflows against a code repository. A workflow is ordinary Python that asks for
a worktree, hands roles to agents and lands what comes back: `fix` runs one worktree sequentially
with Claude implementing and OpenAI reviewing, `split` runs N chunks concurrently.

## Install

```bash
uv tool install "agl[all]"
```

The `[all]` extra pulls in the Claude adapter (`claude-agent-sdk`) and the rich terminal. Without
it you get the core, which is stdlib-only.

## Python 3.14 or newer

This is the one thing most likely to trip you up. AGL declares `requires-python = ">=3.14"`, so a
plain `pip install agl` on an older interpreter refuses before it downloads anything, and it
reports that as not finding a version rather than as your interpreter being too old. `uv tool
install` sidesteps it by fetching a matching interpreter itself.

## Status

Early. 0.0.1 is a name claim rather than a release, and the surface may still change.

## Licence

MIT — see [LICENSE](LICENSE).
