# Run.step

Starts a step, the only way a workflow runs an agent.

To keep what the agent changes, pass `commit=`. To get only what it reports, such as a triage or a
review, leave `commit=` out.

Steps on one [`Run`][agl.sdk.Run] take turns, so to run steps side by side, open a worktree for
each with [`run.worktree`][agl.sdk.Run.worktree].

## What a step keeps

These rules say which changes in a worktree are still there after a step.

- With `commit=`, AGL commits when the step ends and, if nothing changed, makes no commit.
- Nothing checks that a step whose agent changes files has `commit=`, and nothing warns about such
  a step without it.
- A step that raises or is cancelled while its agent works keeps nothing, even with `commit=`.
- Before its agent starts, a step throws away every change made in its worktree since the last step
  or landing there, such as one made by a command you ran with [`verify`][agl.sdk.Run.verify].
- A step never commits or throws away a file that `.gitignore` covers.

## Inputs and the payload

AGL matches each input to whichever type in `accepts=` it is an instance of, so the order of the
inputs doesn't matter. For two values of one type, have the role accept one type that holds both.

When a role has no reporting tool, its role factory still passes mypy with the annotation
`-> Role[Triage]`.

## Examples

Both examples come from one workflow, which triages a list of issues and then fixes each one in a
worktree of its own.

### Without `commit=`

The first example is the triage, which runs in the top-level [`Run`][agl.sdk.Run].

```python
--8<-- "fix_issues/__init__.py:triage"
```

1. `triaging`'s reporting tool has a `Triage` payload, so the step returns the `Triage` its agent
   reported.

### With `commit=`

The second example is the workflow's `fix` function.

```python
--8<-- "fix_issues/__init__.py:fix"
```

1. The workflow calls `fix` once for each `Issue` in the `Triage`, with the child that
   [`run.worktree`][agl.sdk.Run.worktree] opened for that issue.
2. `fixing` has no reporting tool, so the step returns `None`, and commits what the agent changed
   in the child's worktree under a message naming the issue.
3. `land` is this workflow's own function, which lands the fix in the parent's worktree with
   [`integrate`][agl.sdk.Run.integrate].

::: agl.sdk.Run.step

## See also

- [`Run`][agl.sdk.Run]
- [`Run.worktree`][agl.sdk.Run.worktree]
- [`Run.integrate`][agl.sdk.Run.integrate]
- `role`
- `reporting_tool`
