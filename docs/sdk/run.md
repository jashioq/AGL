# Run

For steps that go in order, use the [`Run`][agl.sdk.Run] your workflow receives. For work in
parallel, open a child `Run` for each line of work with [`run.worktree`][agl.sdk.Run.worktree],
and run the children with asyncio, because the steps of one `Run` take turns.

## Example

The example is a workflow that carries out a request, checks the work, has it reviewed, and fixes
what the review finds.

```python
--8<-- "implement_and_check/__init__.py:workflow"
```

1. `@workflow` makes the function a workflow that `agl run` can start.
2. [`run.terminal`][agl.sdk.Run.terminal] shows a board with the run's label, which asks nothing,
   so the workflow carries on at once.
3. [`run.params`][agl.sdk.Run.params] is a `Parameters`, so `request` holds what `--request` was
   given.
4. [`run.step`][agl.sdk.Run.step] runs `implementing` with the request, and commits what its agent
   changed under the message when the step ends.
5. [`run.verify`][agl.sdk.Run.verify] runs the project's build command, which the workflow declares
   as its `build` setting.
6. This step's agent judges the work rather than changing it, so the step has no `commit=`, and
   returns the `Review` the agent reported through `reviewing`'s reporting tool.
7. This step runs `implementing` again with the `Review` as well, a type the role's `@role` lists
   in `accepts=`, and commits the fix.

## How it works

The top-level [`Run`][agl.sdk.Run] works on the run's branch, `agl/<label>`, which keeps the run's
work after the run ends. A child's work reaches its parent's worktree only through
[`integrate`][agl.sdk.Run.integrate].

When you resume a run, AGL calls your workflow again from its first line, and each step that
matches the run's record returns its recorded result without running an agent.

[`verify`][agl.sdk.Run.verify] writes nothing to the record, so a resume runs its command again on
the worktree as it is then, which can be ahead of the steps replayed so far.

## Members

Find a member by what you need it for.

- Run a step: [`step`][agl.sdk.Run.step], with `commit=`, and [`params`][agl.sdk.Run.params].
- Work in parallel: [`worktree`][agl.sdk.Run.worktree] and [`integrate`][agl.sdk.Run.integrate].
- Check the work: [`verify`][agl.sdk.Run.verify], with [`VerifierOutcome`][agl.sdk.VerifierOutcome].
- Talk to the person: [`terminal`][agl.sdk.Run.terminal].
- Project settings: [`config`][agl.sdk.Run.config].
- Where the run is: [`label`][agl.sdk.Run.label] and [`namespaces`][agl.sdk.Run.namespaces].

::: agl.sdk.Run
    options:
      group_by_category: false
      members:
        - params
        - verify
        - terminal
        - config
        - label
        - namespaces

::: agl.sdk.VerifierOutcome
    options:
      members:
        - passed
        - status
        - output

## See also

- `workflow`
- `arg`
- `Role`
- `Terminal`
