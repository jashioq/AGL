# Run.worktree()

Open a worktree: a separate checkout on a branch of its own, starting from where this
[`Run`](index.md) is. It returns a new `Run` for that worktree. [Steps](step.md) on the new
`Run` work there and never touch the parent's branch.

```python
child = run.worktree("issue-42")
await child.step(fixer, issue, commit="Fix issue 42")
```

Steps on one `Run` take turns. To run agents at the same time, give each one its own worktree and
run them with asyncio.

```python
async with asyncio.TaskGroup() as group:
    for issue in triage.issues:
        group.create_task(fix(run.worktree(f"issue-{issue.number}"), issue))
```

A worktree's work stays on its branch, `agl/_work/<label>/<name>`, until you land it in its parent
with [`Run.integrate()`](integrate.md).

Names use the letters A to Z and a to z, digits, `.`, `_` and `-`, and are unique across the whole
run, ignoring case. Opening a name again from the same `Run` returns the same worktree. Build names
from parameters and step results, never from the clock or a random number, so a resumed run finds
the same worktrees again.

A worktree can open worktrees of its own. [`Run.namespaces`](namespaces.md) tells a worktree where
it sits.

To start from somewhere else, pass `base`: another `Run`, or a git ref.

```python
docs = run.worktree("docs", base="main")
```

## Reference

::: agl.sdk.Run.worktree
