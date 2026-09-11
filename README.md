# AGL

AGL runs AI agent workflows against a code repository. A workflow is ordinary Python that asks for
a worktree, hands roles to agents and lands what comes back — with fingerprinted replay, git
worktree isolation, preflight checks and exit codes supplied by the framework rather than written
into the workflow.

**This release ships no workflows.** The ones AGL runs are the ones you write, and the ones you
download from public GitHub repositories with `agl get`, below. `agl new <name>` writes a workflow
into your own workspace under AGL_HOME — a directory holding a module and a pyproject.toml, which
runs as it stands — and `agl run <name>` runs it against a repository, which `agl init` registers
from inside once; `agl workflows` lists what that workspace declares. AGL reads workflows from
there and from nowhere else: the `agl.workflows` entry-point group is the table key each workflow
directory's own pyproject.toml writes, rather than a group a distribution installed beside AGL
registers into.

A workflow that imports nothing beyond `agl` needs no environment of its own and runs as it stands.
One declaring third-party dependencies in its own pyproject.toml just works too: AGL keeps the
workspace's environment current with what its workflows declare, and does it as part of running
them. `agl new` installs on its way out, `agl get` too whenever it placed something, and `agl run`
and `agl resume` each install before they import anything, so there is no install command to
remember and no moment at which you would have had to remember it. What is installed is your
workflows' dependencies and never the workflows themselves, so importing a workflow still resolves
from the source you are editing. This needs `uv` on your PATH. An install that succeeds says
nothing at all; one that is refused stops the command on uv's own words, unless your workspace
already has an environment, in which case AGL warns and carries on against what the last
successful install left.

`agl new` also writes one line about AGL itself into the workflow it scaffolds —
`[tool.agl] requires = "agents-gl>=<version>"`, naming the AGL that wrote it. AGL reads that line
back and refuses a workflow written against a newer AGL than the one you are running, *before*
importing the workflow, so what you are told about is a version rather than whichever name moved
inside your own file. It is a floor and not a pin, so any later AGL satisfies it. The table is
`[tool.agl]` and deliberately not `[project] dependencies`: uv walks past a `[tool]` table it does
not own, so nothing ever goes off to an index looking for that version.

## Getting workflows from GitHub

`agl get` downloads workflows from public GitHub repositories into your workspace, where
`agl workflows` lists them and `agl run` runs them like any you wrote:

```bash
agl get owner/repo/workflows/triage
agl get owner/repo@v1.2.0/workflows/triage
agl get owner/repo/workflows/triage,review,release
```

Each argument is `owner/repo[@ref]/path/to/workflow`: the owner, the repository, and the path from
the repository's root to the workflow's own directory, whose name is the one the workflow is placed
under. An `@ref` on the repository asks for a branch, a tag or a commit's full sha, and without one
you get the default branch. The last segment may be a comma list of sibling directories, and the
command takes as many arguments as you give it, so shell brace expansion works too. A ref
containing `/`, such as `release/1.2`, cannot be written — the first `/` after the `@` is where the
path begins — but the full sha of the commit it points at always works in its place. An argument
that does not fit the shape refuses the whole command before anything is downloaded.

Public repositories only: `agl get` sends no token and signs in to nothing, so a private repository
is refused exactly as one that does not exist. It makes one download from codeload.github.com per
repository and ref, however many workflows you ask of it, from AGL's own process and with no git
involved. That makes it the first AGL command to send an HTTP request itself rather than through uv
or an agent CLI, and the first whose job is to fetch code somebody else wrote — code that `agl run`
then runs as you.

Everything is downloaded and checked before anything is placed. A download that is not a workflow
this AGL can run as it stands — no pyproject.toml declaring one, no `__init__.py`, a bound on a
newer AGL, a name another workflow in your workspace already declares — is refused, and nothing of
it is placed. Then every question is asked, one after another, and only then is anything written.
There are two, and each is asked only where it applies:

- **The workflow is already there.** Where your workspace's `workflows/` already holds that name,
  matched without regard to case, `agl get` says that it exists and asks whether to override it:
  `<path> already exists. Override it with <owner/repo[@ref]/path>? [y/n]`. Yes replaces what is
  there with the download; no leaves it as it is.
- **It declares third-party dependencies.** Where the download's pyproject.toml lists
  `[project] dependencies`, `agl get` says that uv will install them into your workspace, names
  each of them quoted — `'httpx>=0.27', 'rich'` — and asks `Continue? [y/n]`. A workflow that
  declares none is not asked about, and `[tool.agl] requires`, the line about AGL itself, is not
  one of them. A download with an extra, a dependency group, a `[tool.uv]` table or metadata left
  to a build is refused rather than asked about, since each can have uv install something that list
  does not name — so the list you are shown is everything the download asks uv to install.

A no skips that one workflow and nothing else. An answer is a line reading `y`, `Y`, `n` or `N`,
and anything else asks again. Where there is nothing left to read an answer from — stdin at its
end, as under `< /dev/null` or in a script whose input has run out — every question is answered no,
and a workflow that raises no question is placed all the same.

Each workflow gets one line: `placed`, `declined` or `refused`, the name it is placed under, and
where it came from, a declined or refused one ending in a few words on why and each refusal's full
reason following. Only the `placed` lines go to stdout, so a script reading it sees what it got;
the questions and everything else go to stderr. The exit status is 0 unless a workflow was
refused, because declining is an answer and not a failure. A refusal exits with AGL's code for
that kind of failure — 3 where a repository, a ref or a directory is not there, 6 where the
download itself failed — and refusals that would exit differently exit 70 together, with a line
saying so. What was placed is then installed as `agl new` installs; the summary is printed before
that install starts, so an install that is refused still leaves it on your terminal.

Each workflow `agl get` places holds one file it did not arrive with, `.agl-provenance.json`: the
owner, repository, path and ref it was asked for — `null` for the default branch — the full sha of
the commit it came from, and a hash of its files as they were placed. AGL writes its own every
time, and one that arrives at the top of a download is dropped rather than kept.

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
