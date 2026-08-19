# STAGE 18
"""The `split` workflow: N independent chunks, concurrent, each integrated into the run's base.

v1.1. This is an unrunnable skeleton written at stage 0 so that every stage in between has
the thing it is ultimately serving in front of it. Nothing it needs exists yet: there is no
`Run`, no `@workflow`, no `worktree()`, no `integrate()`. Importing this module does nothing
and raises nothing; awaiting `split` raises `NotImplementedError`.

## What it does

A planner divides the job into N independent chunks. Each chunk gets its own child worktree,
all of them run concurrently, and each integrates into the run's base as it finishes. Where
`fix` proves that two vendors fit in one run, `split` proves that N agents fit in one run
without stepping on each other.

## Target shape

```python
@workflow(name="split", params=SplitParams)
async def split(run: Run) -> None:
    chunks = await run.step("plan", planner)
    async with TaskGroup() as tg:
        for c in chunks.items:
            tg.create_task(do_chunk(run, c))


async def do_chunk(parent: Run, c: Chunk) -> None:
    w = parent.worktree(c.id)
    await w.step("implement", implementer)
    await w.integrate()
```

`SplitParams` is this package's params dataclass (`arg()` in `sdk/params.py`); `planner` and
`implementer` are `Role`s declared in this package (`sdk/roles.py`); `chunks` is the payload
of the planner's reporting tool (`sdk/tools.py`), so `Chunk` is a type this package owns, not
a framework type. `TaskGroup` is `asyncio.TaskGroup` - concurrency is the author's, written
in plain structured-concurrency Python, and the framework never spawns tasks on their behalf.

`do_chunk` is deliberately absent from this module as real code: it needs `parent.worktree()`
and `w.integrate()`, neither of which exists. It belongs to stage 18 along with the rest.

## Framework paths it exercises

- `sdk/_engine/worktrees.py` - `parent.worktree(c.id)` is the whole child-worktree path:
  namespace to worktree mapping, nested `worktrees/<name>/` storage, per-namespace head
  chaining. Nested namespaces are what keep N concurrent chunks from colliding.
- `sdk/_engine/journal.py` - N namespaces writing step entries at the same time, with no
  lock. Concurrent entry writes have to be safe by layout, not by mutual exclusion.
- `sdk/_engine/integration.py` - `w.integrate()` enters the queue: merges into one target are
  serialized behind a lease, the build gate runs, and a failure reverts.
- `ports/workspace.py`, `ports/integration.py`, `ports/verifier.py` - `Workspace`,
  `IntegrationOutcome`/`Conflict` and the `Verifier` behind that queue. The conflict path is
  a first-class outcome of this workflow, not an error case bolted on afterwards.

## Acceptance

The plan's target is that `split` is about thirty lines *and that writing it requires no
framework change*. That second half is the real test: if stage 18 produces a diff outside
`workflows/split/`, an abstraction was missing from the SDK. Report it as a missing
abstraction rather than patching around it here.
"""


async def split(run: object) -> None:
    """The split workflow. Written at stage 18; raises `NotImplementedError` until then.

    The eventual signature, once `agl.sdk.workflow` exists:

    ```python
    @workflow(name="split", params=SplitParams)
    async def split(run: Run) -> None: ...
    ```

    `run` is annotated `object` because `Run` does not exist yet, and deliberately not `Any`:
    `Any` would let future call sites typecheck against a placeholder and hide the fact that
    the real type never landed, whereas `object` cannot be used for anything and so forces
    stage 18 to replace this annotation on purpose.
    """
    raise NotImplementedError("The split workflow is written at stage 18.")
