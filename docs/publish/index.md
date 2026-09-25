# Publish workflows

Share a workflow by pushing it to a public GitHub repository. Others get it with
[`agl get`](../download/index.md#agl-get).

## What it needs

- The workflow's directory, as [`agl new` makes it](../build/index.md#create-a-workflow): an
  `__init__.py` and a `pyproject.toml`.
- In `pyproject.toml`: a `name`, a `version` and the `agl.workflows` entry.
- `[tool.agl] requires`, so people on an older AGL get a clear refusal instead of an error.
- `dependencies` under `[project]`, if it has any. People are asked before they're installed.

`agl get` places the directory under its own name, so the `agl.workflows` entry imports from the
package of that name, as `implement = "implement:implement"` does in `implement/`. It refuses an
entry that imports from anywhere else.

`agl get` refuses a workflow with optional dependencies, `[dependency-groups]`, `[tool.uv]` or
dynamic metadata. It also refuses one that holds a link or more than 64 MiB of files, or whose
`name` or entry another workflow in the workspace already has.

List the settings it reads in `config`, and tell people [what to set](../build/run/config.md).

Give people the line to run:

```
agl get you/your-repo/implement
```

Tag releases so people can pin one with `@tag`. [`agl update`](../download/index.md#agl-update)
brings everyone else your latest.

One repository can hold many workflows, one directory each, and people can get several at once. A
workflow's directory sits inside the repository, never at its root.
