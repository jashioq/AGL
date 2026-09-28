# Prompt

A [role](index.md)'s instructions are its prompt. Keep it in a file and load it with
`prompt_file()`, relative to the file that calls it.

```python
Role(name="builder", instructions=prompt_file("prompts/builder.md"))
```

Write each type the role [accepts](accept-input-parameters.md) into the prompt as `{{TypeName}}`,
with no spaces inside the braces. When the step runs, AGL fills it in with the value as JSON.

`prompts/builder.md`:

```
Implement this request: {{Request}}

A reviewer found these problems, if any: {{Review}}
```

The prompt and `accepts` must name the same types. AGL checks this when you call the role's
function.

## Reference

::: agl.sdk.prompt_file
