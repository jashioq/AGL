# Run.params

The parameters the workflow was run with, parsed into a class of your own. Declare each one with
`arg()`, and name the class in the workflow's [`Run`](index.md), as `Run[Params]`.

```python
@dataclass(frozen=True)
class Params:
    request: str = arg("-r", "--request", help="What to implement.")
    dry_run: bool = arg("--dry-run", default=False, help="Plan only.")

@workflow
async def implement(run: Run[Params]) -> None:
    await run.step(builder, run.params.request)
```

```
agl run implement -n login-page -r "Add a login page" --dry-run
```

A parameter can be a `str`, `int`, `float` or `bool`. One without a `default` is required. A
`bool` is a switch: declare it with `default=False`, and its flag sets it to true. `-n`, `--name`,
`--from`, `-h` and `--help` belong to AGL.

`agl workflows implement` shows a workflow's parameters. A resumed run keeps the ones it started
with.

## Reference

::: agl.sdk.Run.params

::: agl.sdk.arg
