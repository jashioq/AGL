from agl.sdk import Claude, ClaudeEffort, Restriction, Role, prompt_file, role

@role(model=Claude.OPUS(effort=ClaudeEffort.HIGH), accepts=(str,))
def builder_role() -> Role:
    return Role(
        name="builder",
        instructions=prompt_file("prompts/builder.md"),
        restrictions={Restriction.NO_NETWORK, Restriction.NO_VCS_WRITES},
    )

builder = builder_role()
