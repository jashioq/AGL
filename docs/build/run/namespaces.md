# Run.namespaces

The names of the [worktrees](worktree.md) from the top-level [`Run`](index.md) down to this one,
each a `Namespace`. The top-level `Run` has none.

```python
child = run.worktree("issue-42")
tests = child.worktree("tests")
```

Here `tests.namespaces` holds `issue-42` and `tests`, outermost first. Use it to name a worktree's
[boards](terminal.md) and [commits](step.md) after where it sits.

```python
where = "/".join(name.value for name in tests.namespaces)
await tests.step(tester, commit=f"Add tests in {where}")
```

## Reference

::: agl.sdk.Run.namespaces

::: agl.sdk.Namespace
    options:
      show_bases: false
      inherited_members:
        - value
      members:
        - value
