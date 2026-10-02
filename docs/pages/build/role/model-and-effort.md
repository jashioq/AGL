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

`Claude` and `OpenAI` each have two kinds of member:

- Family member - Runs the newest model of its family, as `Claude.OPUS` runs the newest Opus.
- Versioned member - Runs one model, as `Claude.OPUS_4_7` runs Claude Opus 4.7.

```python
@role(model=Claude.OPUS_4_7(effort=ClaudeEffort.HIGH))
```

- `Claude` - `OPUS`, `SONNET`, `HAIKU`, `FABLE`, and the versioned `OPUS_4_5`, `OPUS_4_6`,
  `OPUS_4_7`, `OPUS_4_8`, `OPUS_5`, `OPUS_5_5`, `SONNET_4_5`, `SONNET_4_6`, `SONNET_5`,
  `SONNET_5_5`, `HAIKU_4_5`, `FABLE_5`, `FABLE_5_1`.
- `OpenAI` - `SOL`, `TERRA`, `LUNA`, `ASTRA`, and the versioned `GPT_5_6_SOL`, `GPT_5_6_TERRA`,
  `GPT_5_6_LUNA`, `GPT_6_ASTRA`, `GPT_6_SOL`, `GPT_6_LUNA`, `GPT_6_1_SOL`.
- `ClaudeEffort` - `LOW`, `MEDIUM`, `HIGH`, `XHIGH`, `MAX`.
- `OpenAIEffort` - `LOW`, `MEDIUM`, `HIGH`, `XHIGH`, `MAX`, `ULTRA`.

Without an effort, a model runs at its tool's default.

## Reference

::: agl.sdk.ModelId
    options:
      members: false

::: agl.sdk.Claude
    options:
      show_attribute_values: false
      members:
        - OPUS
        - SONNET
        - HAIKU
        - FABLE
        - OPUS_4_5
        - OPUS_4_6
        - OPUS_4_7
        - OPUS_4_8
        - OPUS_5
        - OPUS_5_5
        - SONNET_4_5
        - SONNET_4_6
        - SONNET_5
        - SONNET_5_5
        - HAIKU_4_5
        - FABLE_5
        - FABLE_5_1
        - __call__

::: agl.sdk.ClaudeEffort
    options:
      show_attribute_values: false
      members:
        - LOW
        - MEDIUM
        - HIGH
        - XHIGH
        - MAX

::: agl.sdk.OpenAI
    options:
      show_attribute_values: false
      members:
        - SOL
        - TERRA
        - LUNA
        - ASTRA
        - GPT_5_6_SOL
        - GPT_5_6_TERRA
        - GPT_5_6_LUNA
        - GPT_6_ASTRA
        - GPT_6_SOL
        - GPT_6_LUNA
        - GPT_6_1_SOL
        - __call__

::: agl.sdk.OpenAIEffort
    options:
      show_attribute_values: false
      members:
        - LOW
        - MEDIUM
        - HIGH
        - XHIGH
        - MAX
        - ULTRA
