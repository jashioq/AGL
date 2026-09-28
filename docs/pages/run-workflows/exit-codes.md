# Exit codes

The code `agl` exits with says how the command ended.

- 0 - done.
- 2 - a wrong command, flag or value.
- 3 - something wasn't found, like a run to resume or a workflow to run.
- 4 - a conflict, like a label that's already taken.
- 5 - something was refused that retrying won't change, like a file the filesystem won't let AGL
  use.
- 6 - a tool AGL uses failed or wasn't ready, like an agent, git or uv.
- 7 - the workflow [stopped on purpose](../build/stop.md).
- 8 - several of the above at once.
- 70 - a bug in AGL, or an exception from the workflow's own code. The message under the traceback
  says which.

When several errors end a command at once, as [worktrees](../build/run/worktree.md) working at the
same time can, AGL exits with their code if they share one, 70 if any of them is 70, and 8
otherwise.

The errors below carry these codes: `InputError` 2, `NotFoundError` 3, `ConflictError` 4,
`DeniedError` 5, `UpstreamError` and both its kinds 6, and `InternalError` 70. A workflow that
raises one of them exits with its code.

## Reference

::: agl.sdk.AglError

::: agl.sdk.InputError

::: agl.sdk.NotFoundError

::: agl.sdk.ConflictError

::: agl.sdk.DeniedError

::: agl.sdk.UpstreamError

::: agl.sdk.UpstreamUnavailable

::: agl.sdk.UpstreamUnexpected

::: agl.sdk.InternalError
