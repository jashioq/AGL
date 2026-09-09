# AGL

AGL runs AI agent workflows against a code repository. A workflow is ordinary Python that asks for
a worktree, hands roles to agents and lands what comes back — with fingerprinted replay, git
worktree isolation, preflight checks and exit codes supplied by the framework rather than written
into the workflow.

**This release ships no workflows.** The ones AGL runs are the ones you write. `agl new <name>`
writes a workflow into your own workspace under AGL_HOME — a directory holding a module and a
pyproject.toml, which runs as it stands — and `agl run <name>` runs it against a repository, which
`agl init` registers from inside once; `agl workflows` lists what that workspace declares. AGL
reads workflows from there and from nowhere else: the `agl.workflows` entry-point group is the
table key each workflow directory's own pyproject.toml writes, rather than a group a distribution
installed beside AGL registers into.

A workflow that imports nothing beyond `agl` needs no environment of its own and runs as it stands.
One declaring third-party dependencies in its own pyproject.toml just works too: AGL keeps the
workspace's environment current with what its workflows declare, and does it as part of running
them. `agl new` installs on its way out, and `agl run` and `agl resume` each install before they
import anything, so there is no install command to remember and no moment at which you would have
had to remember it. What is installed is your workflows' dependencies and never the workflows
themselves, so importing a workflow still resolves from the source you are editing. This needs
`uv` on your PATH. An install
that succeeds says nothing at all; one that is refused stops the command on uv's own words, unless
your workspace already has an environment, in which case AGL warns and carries on against what the
last successful install left.

`agl new` also writes one line about AGL itself into the workflow it scaffolds —
`[tool.agl] requires = "agents-gl>=<version>"`, naming the AGL that wrote it. AGL reads that line
back and refuses a workflow written against a newer AGL than the one you are running, *before*
importing the workflow, so what you are told about is a version rather than whichever name moved
inside your own file. It is a floor and not a pin, so any later AGL satisfies it. The table is
`[tool.agl]` and deliberately not `[project] dependencies`: uv walks past a `[tool]` table it does
not own, so nothing ever goes off to an index looking for that version.

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

Early, and the surface may still change.

## Licence

MIT — see [LICENSE](LICENSE).
