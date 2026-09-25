# Agents, Graphs, Loops

Run Claude Code and Codex agents as workflows you write in Python. AGL can use your subscription limits so API keys are optional.

```
uv tool install agents-gl
```

You write a workflow as an async Python function. Each [step](build/run/step.md) runs an
[agent role](build/role/index.md) on a git branch AGL makes for the run, so
your checkout stays as it is. When the run ends, its work waits for you on one branch,
`agl/<label>`.

## Features

- [Resume where you stopped](run-workflows/index.md#agl-resume). Every step is recorded, so a
  crashed or stopped run picks up where it left off, and finished steps don't run their agents
  again.
- [Agents never touch your checkout](build/run/worktree.md). Each run and each worktree works on a
  branch of its own.
- [Parallel agents land only when the build passes](build/run/integrate.md).
- [Claude Code and Codex in one workflow](build/role/model-and-effort.md). Pick the model and
  effort per role.
- [Typed in, typed out](build/role/tools-and-return-types.md). Pass dataclasses into prompts and
  get dataclasses back.
- [Questions mid-step](build/role/tools-and-return-types.md#asking-questions). Any agent can ask a
  question in the terminal and wait for the answer in the same session.

## Getting started

Before a run starts or resumes, AGL checks that each tool
the workflow's roles use is ready. If one isn't, AGL refuses the run before any agent spends tokens.

### Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/). If you don't have Python 3.14 or
  later, uv installs it for AGL.

- git, with your name and email set. AGL commits agents' work under your name.

    ```
    git config --global user.name "Your Name"
    git config --global user.email "you@example.com"
    ```

- Claude Code, Codex, or both. Either one is enough if your workflows only use its models.

### Claude Code

AGL runs Claude models through Claude Code. Log in once and AGL uses that login.

```
claude
```

Then follow the login steps. If `claude` isn't found,
[install Claude Code](https://code.claude.com/docs/en/setup#install-claude-code) first.

You can also set `ANTHROPIC_API_KEY` instead. When it is set, AGL uses the key, not your login.

### Codex

AGL runs OpenAI models through Codex. Install it and log in.

```
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex login
```

You can also log in with an API key:

```
printenv OPENAI_API_KEY | codex login --with-api-key
```

### Check the install

Check that AGL is installed:

```
agl --version
```

If your shell doesn't find `agl`, run `uv tool update-shell` and open a new terminal.

## Next

- [Run workflows](run-workflows/index.md) - run a workflow on your project.
- [Download workflows](download/index.md) - get workflows other people published.
- [Build workflows](build/index.md) - write your own.
