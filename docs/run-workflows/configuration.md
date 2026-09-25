# Configuration

AGL keeps its files in `~/.agl`. Set `AGL_HOME` to an absolute path to use another place.

Each repository gets a project file, `~/.agl/projects/<project>.toml`, written on its
[first run](index.md#agl-run). [Workflow settings](../build/run/config.md) like the build command
go there.

The first run writes the project's name, the repository's path, and `trees_root` as
`.agl-trees/<project>` beside the repository:

```toml
name = "web"
repo = "/Users/you/code/web"
trees_root = "/Users/you/code/.agl-trees/web"
```

`trees_root` is an absolute path outside the repository.

`~/.agl/config.toml` turns a tool off or points AGL at another copy of it:

```toml
[agent.openai]
enabled = false

[agent.claude]
cli_path = "/opt/claude/bin/claude"
```

Both tables take `enabled`, true by default, and `cli_path`, an absolute path. Without `cli_path`,
Claude models run on the Claude Code that comes with AGL, and OpenAI models on the `codex` your
`PATH` finds. An [agent role](../build/role/index.md) whose model's tool is off is refused.

An environment variable wins over the setting it matches in either file: `AGL_BUILD_TIMEOUT`,
`AGL_AGENT_CLAUDE_ENABLED`, `AGL_AGENT_CLAUDE_CLI_PATH`, `AGL_AGENT_OPENAI_ENABLED` and
`AGL_AGENT_OPENAI_CLI_PATH`.
