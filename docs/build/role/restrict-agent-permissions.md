# Restrict agent permissions

List what a [role](index.md)'s agent may not do in `restrictions`.

```python
Role(
    name="reviewer",
    instructions=prompt_file("prompts/review.md"),
    restrictions={Restriction.NO_FILE_WRITES, Restriction.NO_VCS_WRITES},
)
```

- `NO_FILE_WRITES` - Takes away the agent's file-editing tools.
- `NO_VCS_WRITES` - Takes away git commands that change the repository.
- `NO_SHELL` - Takes away the agent's shell.
- `NO_NETWORK` - Takes away the agent's network tools.

Restrictions limit the agent only. AGL's own work, like `commit` and
[`Run.verify()`](../run/verify.md), isn't limited. Nor is the function of a
[tool](tools-and-return-types.md) you give the agent, so a tool can do what a restriction takes
away from the agent.

## Reference

::: agl.sdk.Restriction
    options:
      members:
        - NO_VCS_WRITES
        - NO_FILE_WRITES
        - NO_SHELL
        - NO_NETWORK
