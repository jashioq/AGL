# Model and effort

Each [role](index.md) runs one model. Pick it in `@role`, with or without an effort.

```python
@role(model=Claude.OPUS)
@role(model=Claude.OPUS(effort=ClaudeEffort.HIGH))
@role(model=OpenAI.SOL(effort=OpenAIEffort.XHIGH))
```

Claude models run through Claude Code, and OpenAI models through Codex. One workflow can use both.
You only need to [log in to the tools your roles use](../../index.md#getting-started). Before a run
starts, AGL checks that each of them is ready, and refuses the run if one isn't.

- `Claude` - `OPUS`, `SONNET`, `HAIKU`.
- `OpenAI` - `SOL`, `TERRA`, `LUNA`.
- `ClaudeEffort` - `LOW`, `MEDIUM`, `HIGH`, `XHIGH`, `MAX`.
- `OpenAIEffort` - `LOW`, `MEDIUM`, `HIGH`, `XHIGH`, `MAX`, `ULTRA`.

Without an effort, a model runs at its tool's default.

## Reference

::: agl.sdk.ModelId
    options:
      members:
        - provider

::: agl.sdk.Claude
    options:
      members:
        - OPUS
        - SONNET
        - HAIKU
        - __call__

::: agl.sdk.ClaudeEffort
    options:
      members:
        - LOW
        - MEDIUM
        - HIGH
        - XHIGH
        - MAX

::: agl.sdk.OpenAI
    options:
      members:
        - SOL
        - TERRA
        - LUNA
        - __call__

::: agl.sdk.OpenAIEffort
    options:
      members:
        - LOW
        - MEDIUM
        - HIGH
        - XHIGH
        - MAX
        - ULTRA
