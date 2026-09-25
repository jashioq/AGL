# Run workflows

Run a workflow on the directory you are in. AGL works on branches of its own, so your checkout
stays as it is.

## agl run

```
agl run implement -n login-page -r "Add a login page"
```

Runs the `implement` workflow. `-n` names the run. The name is its
[label](../build/run/label.md). Every flag that isn't AGL's own, like `-r`, goes to the workflow as
its [parameters](../build/run/params.md).

When the run finishes, its work is on the branch `agl/login-page`. AGL pushes nothing and never
changes your checkout. Agents work in [worktrees](../build/run/worktree.md) next to your
repository, in `.agl-trees/<project>`.

The first run in a repository registers it with AGL and writes its
[project file](configuration.md). The project is named after the repository's directory. If
another repository already has that name, AGL adds a number, as in `web-1`, and prints the name it
chose.

A run starts from the last commit on the branch you have checked out. Changes you haven't
committed aren't part of it.

Start from another branch than the one you have checked out, or from a tag or a commit, with
`--from`:

```
agl run implement -n login-page --from main -r "Add a login page"
```

## agl workflows

```
agl workflows
agl workflows implement
```

Lists the workflows you have. With a name, it shows how to run that workflow and which parameters
it takes.

## agl resume

```
agl resume login-page
```

Continues a run that crashed or was stopped. AGL runs the workflow again from the top, and every
step that finished returns its [recorded result](../build/run/step.md#recorded-steps) without
running its agent again. The run carries on from the first step that didn't finish, with the same
parameters and the same starting commit.

If you changed the workflow's files since the run started, `agl resume` refuses. Put them back, or
clear the run and start again. Any file you add, change or remove in the workflow's directory
counts, apart from `__pycache__` directories and `.DS_Store` files.

A finished run is refused too, with [exit code 4](exit-codes.md). Its work is already on
`agl/<label>`, and nothing is left to continue. To run the workflow again under that label, clear
the run first.

## agl clear

```
agl clear login-page
```

Deletes a run: its record, its worktrees and its branches, including `agl/login-page`, and any
uncommitted work in them. Merge or copy what you want to keep first. After that, the label is free
for a new run.
