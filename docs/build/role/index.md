# Role

A role is an agent your workflow runs: a model, a prompt, and what the agent may use. Define it
with `@role`, and run it with [`Run.step()`](../run/step.md).

```python
@role(model=Claude.OPUS(effort=ClaudeEffort.HIGH), accepts=(Request,))
def builder_role() -> Role:
    return Role(name="builder", instructions=prompt_file("prompts/builder.md"))

builder = builder_role()
```

`@role` wraps a function that builds the `Role`. Call it to get the role you pass to `Run.step()`.
The function can take arguments, to build a role for each task.

A `Role` built with `Role(...)` outside a `@role` function has no model, and `Run.step()` refuses
it before the agent starts.

## How it works

- [Model and effort](model-and-effort.md) - Pick a Claude or OpenAI model, and how hard it thinks.
- [Accept input parameters](accept-input-parameters.md) - Declare what `Run.step()` may pass to the
  agent.
- [Prompt](prompt.md) - Write what the agent is asked to do, with its parameters filled in.
- [Restrict agent permissions](restrict-agent-permissions.md) - Take away what the agent may not
  use.
- [Tools and return types](tools-and-return-types.md) - Give the agent tools, and get a typed result
  back.
- [Agent activity](agent-activity.md) - Follow what the agent does, line by line.

## See also

- [`Run.step()`](../run/step.md)
- [`Run`](../run/index.md)

## Reference

::: agl.sdk.role

::: agl.sdk.RoleFactory
    options:
      members:
        - __call__

::: agl.sdk.Role
    options:
      members:
        - name
        - instructions
        - restrictions
        - tools
        - requires
        - on_activity

::: agl.sdk.Capability
    options:
      show_attribute_values: false
      members:
        - FILE_EDIT
        - SHELL
        - TOOL_CALLING
