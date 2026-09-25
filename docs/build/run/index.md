# Run

`Run` is the workflow. It runs [agent roles](../role/index.md), opens [worktrees](worktree.md),
displays data in the [terminal](terminal.md) and more. Each workflow builds from a single instance
of `Run`.

## How it works

AGL hands the top-level `Run` a branch, `agl/<label>`. All agents work on it, or on branches of
their own, which start from it by default.

- [`Run.step()`](step.md) - Run an agent on `Run`'s branch.
- [`Run.worktree()`](worktree.md) - Create a worktree whose base points to `Run`'s branch. Returns
  a new instance of `Run`. Chain with `Run.step()` to work in parallel.
- [`Run.integrate()`](integrate.md) - Merge changes from a worktree to its parent.
- [`Run.verify()`](verify.md) - Run a command and return a `VerifierOutcome`.
- [`Run.terminal`](terminal.md) - Display data in the terminal and ask questions in it.
- [`Run.config`](config.md) - Read your repository's settings for the workflow, like its build
  command.
- [`Run.params`](params.md) - The parameters the workflow was run with.
- [`Run.label`](label.md) - The label given to this run with `-n`.
- [`Run.namespaces`](namespaces.md) - The names of the worktrees from the top-level `Run` down to
  this one.

## See also

- [`Role`](../role/index.md)
- [Build workflows](../index.md)
- [Download workflows](../../download/index.md)
