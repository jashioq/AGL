# AGL

AGL runs AI agent workflows against a code repository. A workflow is ordinary Python that asks for
a worktree, hands roles to agents and lands what comes back — with fingerprinted replay, git
worktree isolation, preflight checks and exit codes supplied by the framework rather than written
into the workflow.

**This release ships no workflows.** The ones AGL runs are the ones you write. `agl new <name>`
writes a workflow into your own workspace under AGL_HOME — a directory holding a module and a
pyproject.toml, which runs as it stands — and `agl run <name>` runs it; `agl workflows` lists what
that workspace declares. AGL reads workflows from there and from nowhere else: the `agl.workflows`
entry-point group is the table key each workflow directory's own pyproject.toml writes, rather than
a group a distribution installed beside AGL registers into.

A workflow that imports nothing beyond `agl` needs no environment of its own and runs as it stands.
One declaring third-party dependencies in its own pyproject.toml needs `agl sync`, which installs
what your workspace's workflows declare — their dependencies and never the workflows themselves, so
importing a workflow still resolves from the source you are editing. It requires `uv` on your PATH,
and nothing runs it for you: `agl new` stays offline.

## Install

```bash
uv tool install agents-gl
```

The distribution on PyPI is `agents-gl`; the command it installs and the package you import are
both `agl`.

## Python 3.14 or newer

This is the one thing most likely to trip you up. AGL declares `requires-python = ">=3.14"`, so a
plain `pip install agents-gl` on an older interpreter refuses before it downloads anything, and it
reports that as not finding a version rather than as your interpreter being too old. `uv tool
install` sidesteps it by fetching a matching interpreter itself.

## Status

Early. 0.0.1 is a name claim rather than a release, and the surface may still change.

## Licence

MIT — see [LICENSE](LICENSE).
