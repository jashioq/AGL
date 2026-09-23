# Run.worktree

Lets agents work at the same time.

When pieces of work don't depend on each other, open a child [`Run`][agl.sdk.Run] for each one,
run the children with asyncio, and have each child land its work in its parent with
[`integrate`][agl.sdk.Run.integrate].

Even when asyncio starts steps on one `Run` together, they take turns.

## Where a child starts

Unless you pass a git ref as `base=`, a child starts from where its base stands when you open it,
not when its first step runs. Work that reaches the parent after that, by a step or a landing,
never reaches the child. To build on another child's work, open the new child once that work has
landed, or pass the other child as `base=` once its steps are done.

## Names

On a resume, a child opened under a different name from last time runs its steps again. Build
names from parameters and step results, as `issue-{number}` does in the example, never from the
clock or a random number.

Inside a child, [`run.namespaces`][agl.sdk.Run.namespaces] gives the names from the top-level
[`Run`][agl.sdk.Run] down to it, each a [`Namespace`][agl.sdk.Namespace].

## When a child raises

In an `asyncio.TaskGroup`, an error in one child cancels the others, and a step cancelled that way
while its agent works keeps nothing, as [What a step keeps](run-step.md#what-a-step-keeps) sets
out. The steps that finished stay recorded for `agl resume`.

## Where a child's work goes

A child's worktree sits beside your repository, never inside it, and its commits go on a branch of
its own.

When the workflow returns, AGL keeps the branch of each child whose work never reached the run's
branch, and prints a warning.

## Example

The example comes from a workflow that triages a list of issues in one step, then fixes each issue
in a separate child.

```python
--8<-- "fix_issues/__init__.py:parallel"
```

1. The `asyncio.TaskGroup` runs `fix` for every child at the same time, and waits until all of
   them return.
2. [`run.worktree`][agl.sdk.Run.worktree] opens a child for each issue, and `fix`, the workflow's
   own function, runs a step in it and lands the work.

::: agl.sdk.Run.worktree

::: agl.sdk.Namespace
    options:
      show_bases: false
      inherited_members:
        - value
      members:
        - value

## See also

- [`Run`][agl.sdk.Run]
- [`Run.step`][agl.sdk.Run.step]
- [`Run.integrate`][agl.sdk.Run.integrate]
