# Build workflows

A workflow is an async Python function that runs [agent roles](role/index.md) on a repository.
Start one with `agl new`.

## Create a workflow

```
agl new implement
```

This creates `~/.agl/workspace/workflows/implement/` with two files.

`__init__.py`:

```python
from agl.sdk import Run, workflow

@workflow
async def implement(run: Run) -> None:
    ...
```

`pyproject.toml`:

```toml
[project]
name = "implement"
version = "0.1.0"

[project.entry-points."agl.workflows"]
implement = "implement:implement"

[tool.agl]
requires = "agents-gl>=0.1.0"
config = []
```

The name is also the module AGL imports, so it is a Python identifier, such as `implement` or
`fix_issues`, and not the name of a standard-library module.

Open `~/.agl/workspace` in your editor, not the workflow's directory, so the editor finds AGL.

## What a workflow needs

- A directory in `~/.agl/workspace/workflows/`.
- A `pyproject.toml` with a `name`, a `version` and an entry under `agl.workflows`. The entry's
  name is what `agl run` takes.
- An `__init__.py`.
- An async function decorated with `@workflow` whose first parameter is annotated as a
  [`Run`](run/index.md).

`requires` sets the oldest AGL the workflow runs on, and `agl new` writes the version you have.
`config` lists the [repository settings it reads](run/config.md). Check that it loads with
`agl workflows implement`.

## A small workflow

This workflow does what you ask and commits the result. Its three files go in the directory
`agl new implement` made, beside its `pyproject.toml`.

`roles.py`:

```python
--8<-- "implement/roles.py"
```

`prompts/builder.md`:

```
--8<-- "implement/prompts/builder.md"
```

`__init__.py`:

```python
--8<-- "implement/__init__.py"
```

Run it:

```
agl run implement -n first-try -r "Add a health check endpoint"
```

When it finishes, its work is on the branch `agl/first-try`.
