# Run.integrate()

Land a worktree's work in its parent. AGL merges the worktree's branch into the parent's worktree,
then runs your repository's build there. The work lands only if the build passes. The parent is
either the top-level [`Run`](index.md) or another [worktree](worktree.md).

```python
landing = await child.integrate()
```

The build is your repository's [`build` setting](config.md). A workflow that integrates must list
`build` in its `[tool.agl] config`. An empty `build` passes every landing.

If the build fails, AGL undoes the merge. `landing.refused_by_the_gate` is true, and
`landing.verdict` holds the build's [`VerifierOutcome`](verify.md), with its output. Fix the work
in the worktree with another [step](step.md), then try again.

```python
while landing.refused_by_the_gate:
    await child.step(fixer, landing.verdict, commit="Fix the build")
    await landing.retry()
```

If the merge conflicts, `landing.conflicted` is true, `landing.conflict` lists the files, and its
`summary` names the worktree that holds the merge. Resolve them in the parent's worktree, stage
them, and call `retry()`. Or give up with `abort()`.

```python
if landing.conflicted:
    await landing.abort()
```

A resolved merge goes through the build too. If the build fails, AGL undoes the merge, and the
resolution with it.

Landings into one parent take turns. Until a landing lands or you `abort()` it, it holds the
parent: steps on the parent, and other landings into it, wait. The top-level `Run` has no parent,
so it can't integrate.

## Reference

::: agl.sdk.Run.integrate

::: agl.sdk.Integration
    options:
      show_bases: false
      group_by_category: false
      members:
        - conflicted
        - refused_by_the_gate
        - verdict
        - conflict
        - head
        - retry
        - abort

::: agl.sdk.Conflict
    options:
      members:
        - paths
        - summary
