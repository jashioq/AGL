# Run.step()

Run an [agent role](../role/index.md) on an instance of [`Run`](index.md).

Run a `builder` agent and wait for it to finish.

```python
await run.step(builder)
```

Agent roles can [declare the parameters](../role/accept-input-parameters.md) their agents need to
receive. `Run.step()` passes these parameters from the call site to the role. It accepts any number
of them, and checks at runtime that they match what the role declares. Here `request`, `spec` and
`review` are parameters the `builder` role asks for. Each one is written into the agent's prompt as
JSON, where the [prompt](../role/prompt.md) names it.

```python
await run.step(builder, request, spec, review)
```

After an agent finishes, the changes it made can be committed on its branch or cleared. Use the
`commit` parameter to commit its work. This is the only way to keep an agent's work. Without
`commit`, every change made during the step is wiped, and its branch goes back to what it was when
`Run.step()` was called. Changes committed by earlier steps stay untouched.

```python
await run.step(builder, request, spec, review, commit="Implement what the run was asked for")
```

A `commit` that isn't a `str`, or is empty or only spaces, tabs and line breaks, is refused with
[`InputError`](../../run-workflows/exit-codes.md#agl.sdk.InputError) before the agent starts. A
step that raises an exception commits nothing, even with `commit`.

Leaving `commit` out is useful for agents that don't build but investigate and report. If a role
has a [`reporting_tool()`](../role/tools-and-return-types.md), `Run.step()` returns that tool's
payload. This runs the `reviewer` agent with `design_spec` written into its prompt as JSON,
collects the payload from its `reporting_tool()`, and wipes every change it made on its branch,
including commits it made on its own.

```python
findings = await run.step(reviewer, design_spec)
```

Steps on one `Run` take turns. To run agents at the same time, give each one its own
[worktree](worktree.md).

## Recorded steps

Every `Run.step()` is recorded. When a run crashes or is stopped,
[`agl resume`](../../run-workflows/index.md#agl-resume) runs the workflow again, and each step
that finished returns its recorded result without running its agent. A step runs again when its
role, its parameters or the work before it changed.

A step that returns its recorded result also keeps its commit on the branch.

## Reference

::: agl.sdk.Run.step
