# STAGE 17
"""The `fix` workflow: one worktree, sequential steps - Claude implements, OpenAI reviews.

v1.1. This is an unrunnable skeleton written at stage 0 so that every stage in between has
the thing it is ultimately serving in front of it. Nothing it needs exists yet: there is no
`Run`, no `@workflow`, no `Role`, no reporting tool. Importing this module does nothing and
raises nothing; awaiting `fix` raises `NotImplementedError`.

## What it does

One run, one worktree, three sequential steps. Claude implements the change, OpenAI reviews
what Claude wrote, and if the review comes back with high-severity findings Claude repairs
them. Two providers inside a single run is the entire point of the workflow.

## Target shape

```python
@workflow(name="fix", params=FixParams)
async def fix(run: Run) -> None:
    await run.step("implement", implementer)
    findings = await run.step("review", reviewer)
    if findings.high():
        await run.step("repair", implementer, findings=findings.high())
```

`FixParams` is this package's params dataclass - `arg()` in `sdk/params.py` turns its fields
into named CLI flags, no positionals. `implementer` and `reviewer` are `Role`s declared in
this package (`sdk/roles.py`): the implementer names a `Claude.*` model, the reviewer an
`OpenAI.*` one, and the author names the model per role - there is no config-level override.
`findings` is the payload of the reviewer's reporting tool (`sdk/tools.py`), because a
reporting tool's payload is what a step returns.

There is no `worktree()` here and no `integrate()`. Several agents working in one worktree is
just several steps on the same `Run`; the `await`s are the sequencing, and the second step
sees what the first one left behind. Commits land on `agl/<label>` directly and that branch
is the deliverable - nothing is merged into anything.

## Framework paths it exercises

- `adapters/routing.py` - `RoutingAgentRunner` dispatching on `task.model.provider`, so one
  run reaches two different vendor runners.
- Both vendors' preflight checks in a single run: the Claude SDK, which arrives as a pip
  extra, and the OpenAI binary, which is installed separately and resolved at preflight.
- Restriction translation across vendors: one `Restriction`/`Capability` vocabulary in
  `ports/agent.py`, two unrelated vendor permission models on the far side of it.
- `sdk/_engine/journal.py` - three sequential steps in one namespace, fingerprinted so a
  killed run resumes at the step it died in rather than at the start.

## Acceptance

The plan's target is that `fix` is about six lines. That number measures the SDK, not this
file: if stage 17 cannot write this workflow in roughly six lines, the SDK is wrong. Report
that rather than working around it here.
"""


async def fix(run: object) -> None:
    """The fix workflow. Written at stage 17; raises `NotImplementedError` until then.

    The eventual signature, once `agl.sdk.workflow` exists:

    ```python
    @workflow(name="fix", params=FixParams)
    async def fix(run: Run) -> None: ...
    ```

    `run` is annotated `object` because `Run` does not exist yet, and deliberately not `Any`:
    `Any` would let future call sites typecheck against a placeholder and hide the fact that
    the real type never landed, whereas `object` cannot be used for anything and so forces
    stage 17 to replace this annotation on purpose.
    """
    raise NotImplementedError("The fix workflow is written at stage 17.")
