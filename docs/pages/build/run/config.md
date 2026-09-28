# Run.config

Read your repository's settings for the workflow, like its build command. The workflow declares
the names it reads, and each repository sets the values.

The workflow's `pyproject.toml`:

```toml
[tool.agl]
config = ["build"]
```

The repository's [project file](../../run-workflows/configuration.md),
`~/.agl/projects/<project>.toml`:

```toml
build = "npm run build && npm test"
```
If `~/.agl/projects/<project>.toml` doesn't exist, run [agl run](../../run-workflows/index.md) command to generate it.

In the workflow:

```python
outcome = await run.verify(run.config["build"])
```

AGL checks that every declared setting is set before the run starts. Reading a name the workflow
didn't declare raises an error. [`Run.integrate()`](integrate.md) always needs `build`.

Each value is a TOML string, which `Run.config` gives as written. A workflow can't declare AGL's
own keys: `name`, `repo`, `trees_root` and `build_timeout`.

`<project>` is the name AGL gave the repository on its
[first run](../../run-workflows/index.md#agl-run).

## Reference

::: agl.sdk.Run.config
