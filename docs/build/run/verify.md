# Run.verify()

Run a shell command in this [`Run`](index.md)'s worktree and get its result as a
`VerifierOutcome`: whether it passed, its exit status and its output. A failing command doesn't
raise.

```python
outcome = await run.verify("npm test")
```

Pass the outcome to a [step](step.md), so the agent sees what failed.

```python
if not outcome.passed:
    await run.step(fixer, outcome, commit="Fix the failing tests")
```

To run your repository's own build, read it from [`Run.config`](config.md).

```python
outcome = await run.verify(run.config["build"])
```

A command may take 600 seconds unless the project sets
[`build_timeout`](../../run-workflows/configuration.md). A command that runs longer is stopped, and
its outcome doesn't pass.

A command's changes to files aren't committed. A step on this `Run` wipes them before its agent
starts, apart from files `.gitignore` covers.

`Run.verify()` is [recorded](step.md#recorded-steps) like a step. On a resume, it returns its
recorded outcome without running the command, unless the command or the work before it changed.

## Reference

::: agl.sdk.Run.verify

::: agl.sdk.VerifierOutcome
    options:
      members:
        - passed
        - status
        - output
