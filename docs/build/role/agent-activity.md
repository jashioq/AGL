# Agent activity

Follow what an agent does. [`on_activity`](index.md#agl.sdk.Role.on_activity) gets one line for
each thing the agent does, like each tool call.

```python
lines: list[str] = []

Role(name="builder", instructions=prompt_file("prompts/builder.md"), on_activity=lines.append)
```

Show the lines on a [board](../run/terminal.md) to watch agents work.

```python
def watching(lines: list[str]) -> Screen:
    return Screen(Rows([Row(line) for line in lines[-10:]]))

await run.terminal.show(watching, lines=lines)
```

The function must not be async or block, and it isn't called when a step
[replays](../run/step.md#recorded-steps).

## Reference

::: agl.sdk.ActivityReporter
