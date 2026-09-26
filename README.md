# AGL

Agents, Graphs, Loops

AGL runs Claude Code and Codex agents as workflows you write in Python. Each step runs an agent on
a git branch AGL makes for the run, so your checkout stays as it is, and the run's work waits for
you on one branch. AGL can use your subscription limits, so API keys are optional.

## Quick start

Install AGL with [uv](https://docs.astral.sh/uv/getting-started/installation/):

```
uv tool install agents-gl
```

Download the
[implement and review](https://github.com/jashioq/AGL-workflows/tree/main/implement_and_review)
workflow. Claude implements your request, Codex reviews the change after your build runs, and
Claude fixes what the review finds, for up to three rounds.

```
agl get jashioq/AGL-workflows/implement_and_review
```

Run it from your repository:

```
cd path/to/your/repo
agl run implement_and_review -n verbose-flag -r "Add a --verbose flag"
```

The first run registers the repository and stops to ask for its build command. Add it to the
project file the message names, `~/.agl/projects/<project>.toml`, and run the same command again:

```toml
build = "npm run build && npm test"
```

`build = ""` skips the build. When the run finishes, its work is on the branch `agl/verbose-flag`.

## Log in to Claude Code and Codex

AGL runs agents through Claude Code and Codex on your machine and uses their logins, so log in to
the ones your workflows use before you run them. Implement and review uses both:

```
claude
codex login
```

`claude` walks you through its login. To install either tool, see
[Getting started](https://agents-gl.org/#getting-started).

## Documentation

The full documentation is at [agents-gl.org](https://agents-gl.org).

## Issues

Found a bug, or have a request or a suggestion?
[Open an issue](https://github.com/jashioq/AGL/issues).
