# AGL

AGL runs AI agent workflows against a code repository. A workflow is ordinary Python that asks for
a worktree, hands roles to agents and lands what comes back — with fingerprinted replay, git
worktree isolation, preflight checks and exit codes supplied by the framework rather than written
into the workflow.

**This release ships no workflows.** The ones AGL runs are the ones you write, and the ones you
download from public GitHub repositories with `agl get` and bring up to date with `agl update`,
below. `agl new <name>` writes a workflow into your own workspace under AGL_HOME — a directory
holding a module and a pyproject.toml, which runs as it stands — and `agl run <name>` runs it
against a repository, which `agl init` registers from inside once; `agl workflows` lists what that
workspace declares, and `agl remove` takes a workflow out of it. AGL reads workflows from there and
from nowhere else: the `agl.workflows` entry-point group is the table key each workflow
directory's own pyproject.toml writes, rather than a group a distribution installed beside AGL
registers into.

A workflow that imports nothing beyond `agl` needs no environment of its own and runs as it stands.
One declaring third-party dependencies in its own pyproject.toml just works too: AGL keeps the
workspace's environment current with what its workflows declare, and does it as part of running
them. `agl new` installs on its way out, `agl get` and `agl update` too whenever they placed
something, and `agl run` and `agl resume` each install before they import anything, so there is no
install command to remember and no moment at which you would have had to remember it. `agl remove`
installs nothing: the next install is what uninstalls whatever only the removed workflow needed.
What is installed is your workflows' dependencies and never the workflows themselves, so importing
a workflow still resolves from the source you are editing. This needs `uv` on your PATH. An install
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

## Getting workflows from GitHub

`agl get` downloads workflows from public GitHub repositories into your workspace, where
`agl workflows` lists them and `agl run` runs them like any you wrote:

```bash
agl get owner/repo/workflows/triage
agl get owner/repo/workflows/triage@v1.2.0
agl get owner/repo/workflows/triage,review,release
```

Each argument is `owner/repo/path/to/workflow[@ref]`: the owner, the repository, and the path from
the repository's root to the workflow's own directory, whose name is the one the workflow is placed
under. An `@ref` at the end asks for a branch, a tag or a commit's full sha — everything after the
`@` is the ref, so `@release/1.2` asks for `release/1.2`, slash and all — and without one you get
the default branch. The workflow's own directory may be a comma list of siblings, written before any
`@ref`, and the command takes as many arguments as you give it, so shell brace expansion works too.
A ref holding anything but letters, digits, `.`, `_`, `-`, `+` and `/` — an `@`, as in a tag such
as `@scope/pkg@1.0`, or a `#` — cannot be written, but the full sha of the commit it points at
always works in its place; and no directory on the path may hold an `@`, since that is where the
ref begins. An argument that does not fit the shape refuses the whole command before anything is
downloaded.

Public repositories only: `agl get` sends no token and signs in to nothing, so a private repository
is refused exactly as one that does not exist. It makes one download from codeload.github.com per
repository and ref, however many workflows you ask of it, from AGL's own process and with no git
involved. It and `agl update`, below, are the only AGL commands that send an HTTP request
themselves rather than through uv or an agent CLI, and the only ones whose job is to fetch code
somebody else wrote — code that `agl run` then runs as you.

Everything is downloaded and checked before anything is placed. A download that is not a workflow
this AGL can run as it stands — no pyproject.toml declaring one, no `__init__.py`, a bound on a
newer AGL, a name another workflow in your workspace already declares — is refused, and nothing of
it is placed. Then every question is asked, one after another, and only then is anything written.
There are two, and each is asked only where it applies:

- **The workflow is already there.** Where your workspace's `workflows/` already holds that name,
  matched without regard to case, `agl get` says that it exists and asks whether to override it:
  `<path> already exists. Override it with <owner/repo/path[@ref]>? [y/n]`. Yes replaces what is
  there with the download; no leaves it as it is.
- **It declares third-party dependencies.** Where the download's pyproject.toml lists
  `[project] dependencies`, `agl get` says that uv will install them into your workspace, names
  each of them quoted — `'httpx>=0.27', 'rich'` — and asks `Continue? [y/n]`. A workflow that
  declares none is not asked about, and `[tool.agl] requires`, the line about AGL itself, is not
  one of them. A download with an extra, a dependency group, a `[tool.uv]` table or metadata left
  to a build is refused rather than asked about, since each can have uv install something that list
  does not name — so the list you are shown is everything the download asks uv to install.

A no skips that one workflow and nothing else. An answer is a line reading `y`, `Y`, `n` or `N`,
and anything else asks again. Where no answer can be read — stdin at its end, as under
`< /dev/null` or in a script whose input has run out, or any standard stream closed outright, as
`<&-` closes stdin — every question is answered no, and a workflow that raises no question is
placed all the same.

Each workflow gets one line: `placed`, `declined` or `refused`, the name it is placed under, and
where it came from, a declined or refused one ending in a few words on why and each refusal's full
reason following. Only the `placed` lines go to stdout, so a script reading it sees what it got;
the questions and everything else go to stderr. The exit status is 0 unless a workflow was
refused, because declining is an answer and not a failure. A refusal exits with AGL's code for
that kind of failure — 3 where a repository, a ref or a directory is not there, 6 where the
download itself failed — and refusals that would exit differently exit 8 together, a code kept for
exactly that. What was placed is then installed as `agl new` installs; the summary is printed
before that install starts, so an install that is refused still leaves it on your terminal. One
that fails — uv missing, or refused with no environment to fall back on — exits 6, or 8 beside a
refusal that would exit differently: its code joins the refusals' rather than replacing them.

Each workflow `agl get` places holds one file it did not arrive with, `.agl-provenance.json`: the
owner, repository, path and ref it was asked for — `null` for the default branch — the full sha of
the commit it came from, and a hash of its files as they were placed. AGL writes its own every
time, and one that arrives at the top of a download is dropped rather than kept. It is what
`agl update` reads, and writes afresh for each workflow it replaces; delete it, and `agl update`
takes the workflow for one of your own and passes it over.

## Updating downloaded workflows

`agl update` checks the workflows `agl get` placed against the repositories they came from, and
downloads again each one whose ref has moved:

```bash
agl update
agl update triage
```

With no name it checks every workflow `agl get` placed; with one, only that one. The name is the
one its entry in your workspace's `workflows/` has — the directory it was placed under — which need
not be a name `agl run` takes. A workflow written by hand or by `agl new` has no provenance file
and is left alone: nothing is said about it, and naming it is refused.

For each workflow, `agl update` compares the commit its `.agl-provenance.json` records with the one
its ref names now. Finding that out is one request to api.github.com for each repository and ref,
however many workflows share it, and none at all for a ref that is a commit's full sha, which
cannot move. Those requests sign in to nothing either, so they count against the 60 an hour GitHub
allows an address that is not signed in, and once those are spent each workflow whose ref is asked
about is refused, naming the time GitHub says the limit lifts. When every ref still names the
commit its workflows were placed from, `agl update` says `already up to date` and nothing else, and
downloads nothing.

Whatever moved goes through `agl get`'s three phases: each workflow is downloaded again at the ref
it was placed from — so one placed from a branch goes on following that branch — and checked as
`agl get` checks a download, then every question is asked, and only then is anything replaced.
`agl get`'s question about a workflow that is already there is not among them, replacing it being
what `agl update` is for. Two others are, each only where it applies:

- **Your copy has changed since it was placed.** Where its files no longer measure to the hash its
  provenance file records — an edit, a file added or deleted — replacing the copy would discard
  those changes for good, so `agl update` asks first:
  `<path> has changed since it was placed from 0b496e9, and updating it to f548e57 replaces it
  whole, discarding those changes. Update it? [y/n]`. No keeps your copy exactly as it is. A
  file's mode, anything under `__pycache__` and the `.DS_Store` Finder leaves in a folder it opens
  are not measured, so a change to those alone is replaced without the question. A `.git` in the
  copy is measured like the rest of it, since replacing the copy deletes the repository too.
- **The new version declares third-party dependencies your copy does not.** Each one the download
  writes that your copy does not write the same way is named, quoted, as `agl get` names them, and
  asked about; one your copy already writes the same way is not asked about again.

Each question is answered as under `agl get`, so where no answer can be read a changed copy is
kept. A copy standing under another name than the one it was placed as — renamed, or copied with
its provenance file — and a copy that is a link are refused rather than replaced, and nothing is
downloaded for them. Each copy is measured once more just before it is replaced, and one that
changed after it was first measured — an edit saved while a question was on screen, or while the
downloads were fetched — is refused rather than replaced and left exactly as it stands, and so is
one that is gone, or is a link or no directory at all, by then; the next `agl update` measures it
afresh. A `.DS_Store` Finder writes while you look is not a change. What is replaced gets a
provenance file of its own, keeping the ref and recording the commit it came from now, and
everything replaced is installed once, after the summary, as `agl get` installs.

A workflow still current gets no line. Every other gets one, as under `agl get`: `updated`,
`declined` or `refused`, its name and where it came from, an `updated` line ending in the commit it
was placed from and the one it is at now — `0b496e9 -> f548e57` — and a declined or refused one in
a few words on why, each refusal's full reason following. Only the `updated` lines go to stdout.
The exit status is `agl get`'s: 0 unless a workflow was refused, whichever phase refused it, and
then the code those refusals share, or 8 where they disagree. A copy that changed after it was
measured, or is gone or no longer a directory by then, refuses with 4, and its line ends
`(not written)`. A name that reaches nothing `agl get` placed exits 3 before anything is asked or
downloaded.

## Removing a workflow

```bash
agl remove triage
```

`agl remove` takes one entry out of your workspace's `workflows/`: a workflow's directory and
everything in it, whether you wrote it, `agl new` scaffolded it or `agl get` placed it, or a link,
of which the link alone goes and never what it names. It takes the entry's own name, which need
not be a name `agl run` takes — one directory can declare several workflows, each under a name of
its own — so the question it asks first names every workflow the entry declares:
`<path> declares 'triage'. Remove it? [y/n]`. The answer is read as `agl get` reads one: `y` or `Y`
removes it, and `n`, `N`, stdin at its end or a standard stream closed outright keeps it, and the
command exits 0. An entry another workflow in your workspace depends on is refused, naming each one
that does, and so is any dot-led name: AGL stages what it places or removes in a dot-led directory
inside `workflows/`, and one a crash left behind can hold the only copy of a workflow, so that is
yours to look inside and delete by hand. A name nothing in `workflows/` answers to exits 3, naming
what does.

What is removed leaves `workflows/` in one rename before any of it is deleted, and `removed <name>`
on stdout says it went; a delete that stops part-way says on stderr where what is left now stands,
somewhere neither uv nor `agl workflows` reads. Nothing is installed or uninstalled: `agl workflows`
stops listing it at once, and the next install uninstalls whatever only it needed. A run it started
cannot be resumed while it is gone, and `agl clear <label>` still takes that run away.

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
