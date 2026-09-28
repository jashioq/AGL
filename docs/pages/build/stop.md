# Stop

End a run on purpose. Raise `Stop` anywhere in a workflow, and the run ends with your message.

```python
raise Stop("Nothing to fix: the review found no problems.")
```

AGL prints `Stopped: <message>` and exits with [code 7](../run-workflows/exit-codes.md). Work
committed so far stays on `agl/<label>`, the same as when a workflow returns.

A `Stop` raised in a [worktree](run/worktree.md) or in a
[tool's function](role/tools-and-return-types.md) ends the whole run too.

Use it when there is nothing left to do, or when a [question in the terminal](run/terminal.md) is
answered no:

```python
if not await run.terminal.show(approve, plan=plan.text):
    raise Stop("Plan rejected.")
```

A stopped run isn't finished, so [`agl resume`](../run-workflows/index.md#agl-resume) can continue
it. Its finished steps return their [recorded results](run/step.md#recorded-steps), and a question
is asked again when the resumed run reaches it.

## Reference

::: agl.sdk.Stop
