# Download workflows

Get workflows other people published on GitHub.

## agl get

```
agl get owner/repo/path
agl get owner/repo/path@v1.2
```

Downloads a workflow from a public GitHub repository into your workspace,
`~/.agl/workspace/workflows/`, under the name of its directory. `path` is that directory in the
repository, and `@ref` a branch, a tag or a commit. Without `@ref`, it takes the repository's
default branch.

To get workflows that sit side by side in one directory, separate their names with commas:

```
agl get owner/repo/implement,review
```

AGL asks before installing a workflow's dependencies or replacing one you already have. When
nothing can answer, as in a script with its input closed, the answer is no.

Then set the [settings it needs](../build/run/config.md), and see how to run it with
[`agl workflows <name>`](../run-workflows/index.md#agl-workflows).

## agl update

```
agl update
agl update implement
```

Downloads the latest version of workflows you got with `agl get`, or of the one whose directory you
name. It asks before throwing away changes you made to them, and before installing new
dependencies. A workflow you got at a tag or a commit stays there.

A run that started before its workflow was updated can't be
[resumed](../run-workflows/index.md#agl-resume).

## agl remove

```
agl remove implement
```

Deletes a workflow after asking. It takes the name of the workflow's directory. Runs it started can't be resumed after that.
