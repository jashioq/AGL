# AGL

AGL runs AI agent workflows against a code repository. A workflow is ordinary Python that asks for
a worktree, hands roles to agents and lands what comes back — with fingerprinted replay, git
worktree isolation, preflight checks and exit codes supplied by the framework rather than written
into the workflow.

**This release ships no workflows.** `agl run` therefore has nothing to run and says so. The
`agl.workflows` entry-point group is how a workflow is registered, and a distribution installed
beside AGL can register into it today; a user workspace for workflows you write yourself is the
next thing being built. Install this version to read the surface, not to run anything.

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
