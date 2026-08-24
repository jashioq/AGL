"""The only module that knows TOML: two file shapes, and the walk that finds your project.

If a second module learns what a settings file looks like, this one has failed. Everything TOML
here: the `tomllib` import, the key names, the nesting, the suffix a project's file carries, and
the refusals a file earns. What leaves is typed data - `FileSettings` and `FileProject` - and what
comes back in is a `Path` and an `AglHome`. `sources.py` (9.2) composes what these return with
flags, environment and defaults; it imports this module and this module does not import it.

**This module has no opinion about what any value should be.** It reports what the file said. A
default is a precedence layer, and a layer applied here would be invisible to the module composing
the other three - so every field below except one is `T | None`, and `None` means "the file was
silent", never "off" or "empty". Which is also why nothing here returns `schema.Settings` or
`schema.Project`: 9.1 made every field on those required precisely so that only the module applying
precedence can build one.

## The global settings file, whose shape is decided here

§1.10 says the old `config.toml` was flat and had **no `[agent]` section**, which put R2 - several
vendors inside one run - out of reach of configuration. It does not print the repaired file, so
this is it:

    [agent.claude]
    enabled = true
    cli_path = "/opt/homebrew/bin/claude"

    [agent.openai]
    enabled = true
    cli_path = "/opt/homebrew/bin/harness"

(That second path is generic because the harness binary's real name is spelled only inside its
own adapter package - `scripts/check`'s containment gate, ARCHITECTURE.md §4.)

One nested section per connector, matching `schema.AgentSettings`. **The table is `agent` and the
field it fills is `agents`**, and that mismatch is deliberate rather than an oversight: §1.10 names
the missing section `[agent]`, the file's vocabulary is the operator's, the object's vocabulary is
the code's, and this module is the one place the two are mapped. `trees_root` in a project file
becoming `Project.trees` is the same act (9.1's own field docstring hands it over), and both
mappings live here so a reader has exactly one place to look.

**`AGL_HOME` is never a key in this file.** The file lives *inside* `AGL_HOME`, so a home setting
written here could only be read after home had already been resolved - the value would decide where
to look for the file that holds it. That is why home has three precedence layers, flag > env >
default, and everything else has four. An operator who writes it anyway gets a refusal saying so
rather than a silently ignored line.

**A missing file is not an error.** It means the operator configured nothing, which is the ordinary
case: both connectors resolve their CLI from `PATH`, and `agl init` writes a project file rather
than this one. `read_settings` answers with a `FileSettings` that says nothing.

## Project resolution, and the one place the plan pushes two ways

§3.6: runs are stored per project, labels are scoped to a repo - `agl resume feat1` finds repo A's
run and reports no such label in repo B - and the project is "resolved from cwd by walking up to
the git root and looking it up by path, which also removes the current glob-scan-every-config
behaviour". §1.10's complaint is that `load_project` "glob-scans and parses *every* project's
config on every invocation".

Those two clauses do not fully cohere. A project's identity on disk is its **name**
(`projects/<name>.toml`) and the thing being looked up is its **path**, so nothing short of a
second file - a path-to-name index - could make this an O(1) lookup. **The decision taken, and not
to be re-opened:** read `projects/` once, parse each candidate, stop at the first whose `repo`
matches, and resolve **once per invocation** instead of inside every `_cmd_*`. An index was
considered and rejected: it would be a second source of truth about which repository a project is,
free to go stale the moment somebody renames or deletes a project file by hand, and this plan
rejects second sources of truth everywhere else it meets one (§3.11 on "Stored status" and on
`Document[T]`). The repair §1.10 actually asks for is *resolved once*, and that is what is
delivered. The scan is bounded by how many projects the operator has; it is one directory listing
plus a parse of files of five keys; and it happens exactly once.

Two consequences worth stating rather than discovering. The scan stops at the first match, so a
malformed file *after* it is never read - resolution is not a validation pass over the directory.
And a malformed file *before* it refuses the whole resolution rather than being skipped, because a
skipped file is a project that silently stops existing, and "no project is registered for this
repository - run `agl init`" would then be a lie told to somebody who already did.

**The git root is found by walking the filesystem, not by asking git.** No subprocess, no
`adapters.git`: config resolves the project *before* the container exists, so an adapter answer
would need the object that has not been built yet - and constructing adapters is 9.4's exclusive
privilege, enforced by import-linter contract 5. `.git` is tested for existence and not for being a
directory, because a linked worktree or a submodule writes a `gitdir:` *file* there. Paths are
compared resolved, so a repository reached through a symlink and the same repository reached
directly are one project.

## The writer sits beside the reader, and the pair is one round trip (16.4)

`agl init` writes `AGL_HOME/projects/<name>.toml`, and rendering it is TOML, so it is this module's
- ARCHITECTURE.md §6, "the only module that knows TOML". `write_project` is that renderer, and the
whole of what it owes is stated as a property rather than as care: **a file it writes is one
`read_project` accepts**, asserted in `tests/config/test_toml_file.py` by writing one and reading it
back into a `FileProject`. Written anywhere else, the escaping rule and the key names would be a
second copy of this file's vocabulary, kept in agreement by nobody - which is the exact failure the
first line of this docstring is about.

**It writes all five of §3.10's keys, `build_timeout` included, and the value is read rather than
restated.** `api.init` passes `sources.DEFAULT_BUILD_TIMEOUT`, so that line stays "the fourth layer,
and the only place in AGL that states any of it" and simply gains a second reader; there is no
number in this module and none in `api.py`. Leaving the key out would have cost no code and would
have cost the operator the knob - a project file is an editing surface rather than a serialisation,
`build_timeout` is the one value on it people revisit, and a key that is not in the file is a knob
nobody discovers. The property that follows is `sources.py`'s to state and is stated there: a
project keeps the timeout it was registered with when AGL's own default moves.

**It never overwrites.** The file is created exclusively, so a second `agl init` in a repository
that already has one is a `ConflictError` rather than a silent replacement of settings somebody
edited. `check_unregistered` is the same refusal asked for free, in front of the question `init`
puts to a person; `api.init` calls it there, and the exclusive create is what makes the answer
race-free rather than merely early. Both raise the one message `_already` writes, exactly as
`check_trees_root` is one rule serving the reader and the writer.

## What is refused, and with which class

`InputError` (exit 2, "a config file that is malformed or unreadable" in `errors.py`'s own words)
for malformed TOML, an unreadable file, a value of the wrong type, a value the 9.1 types would
reject, and a project file that cannot be written - every message naming the file and the key.
`ConflictError` (exit 4) for the one thing `write_project` refuses: a project file that is already
there, "the world already holds something this operation would have to take or overwrite"
(`ports/errors.py`) said about a file rather than about a run label. **Unknown keys and unknown
tables are refused too**, listing what was expected: a typo'd `build_timout` that silently keeps
the default is exactly the failure a configuration file exists to prevent, and ignoring it costs an
operator an afternoon. `NotFoundError` (exit 3) for the two absences that are not malformations -
not inside a git repository, and inside one no project file names - with distinct messages, both
pointing at `agl init`.

**One refusal here is not about a single value, and it is the only one: a `trees_root` that
resolves to somewhere inside `repo`.** §3.5 is "AGL lives outside the target repo" and §3.10 keeps
AGL's state under `AGL_HOME` "so AGL never appears in `git status`"; a nested trees root breaks both
by putting AGL's checkouts in the operator's own working tree. Stage 9 declined the check because
seeing it needs `Path.resolve()` and `schema.Project.__post_init__` is a pure type.
`check_trees_root` is where it landed - exported, so that 16.4's `init` refuses it when the file is
written and this module refuses it when the file is read - and its own docstring argues why it is
here and not in `sdk/_engine/preflight.py`.

`tomllib.load` hands back `dict[str, Any]`. It is narrowed to `object` at the one call site and
never re-widened, so nothing typed `Any` leaves this module: every value is read through one of
the small readers below, which is also where the type refusals get their wording.

**Every path read here comes out of `ports/home_layout.py`**: `settings_file` for the global file,
`projects_dir` for the listing the resolution scans, `project_config` for one named project's file.
That module is where AGL_HOME's layout is written down, and this one holds no copy of it - not the
`projects/` segment and not the top-level filename. What this module owns is the *format*, which is
also the one thing that keeps `.toml` spelled in both places: there it is a path segment composed
onto a name, here it is the suffix the listing filters on and the stem a project's name is read
off, and neither module could drop it and still do its job.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.home_layout import AglHome, project_config, projects_dir, settings_file
from agl.ports.ids import ProjectName
from agl.ports.tree_layout import TreesRoot

__all__ = [
    "FileAgent",
    "FileProject",
    "FileSettings",
    "check_trees_root",
    "check_unregistered",
    "git_root",
    "read_project",
    "read_settings",
    "resolve_project",
    "write_project",
]


# The file format's whole vocabulary. All of it is this module's; the suffix alone is also
# `home_layout`'s, where it is a segment of a composed path rather than a filter and a stem.
_PROJECT_SUFFIX: Final = ".toml"
_AGENT: Final = "agent"
_CLAUDE: Final = "claude"
_OPENAI: Final = "openai"
_ENABLED: Final = "enabled"
_CLI_PATH: Final = "cli_path"
_NAME: Final = "name"
_REPO: Final = "repo"
_TREES_ROOT: Final = "trees_root"
_BUILD: Final = "build"
_BUILD_TIMEOUT: Final = "build_timeout"
_SECTIONS: Final = (_CLAUDE, _OPENAI)
_AGENT_KEYS: Final = (_ENABLED, _CLI_PATH)
_PROJECT_KEYS: Final = (_NAME, _REPO, _TREES_ROOT, _BUILD, _BUILD_TIMEOUT)

# The spellings an operator reaches for when trying to set AGL_HOME in the file that lives inside
# it. They are unknown keys like any other; they get a refusal that says why, because "expected
# agent" would not explain to somebody who thought this was the place.
_HOME_KEYS: Final = frozenset({"home", "agl_home", "AGL_HOME"})

# What git leaves in the root of a working tree - a directory in a plain clone, a file holding a
# `gitdir:` line in a linked worktree or a submodule.
_GIT: Final = ".git"

# The escapes a TOML basic string requires, as the format defines them. Every other control
# character is written `\u00xx` by `_quoted`, which is the format's own fallback. This table is the
# write side of `tomllib`'s read side, and the round-trip test is what holds the two together.
_ESCAPED: Final = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}

# Below this, a character is a control character and needs the `\u00xx` form; `\x7f` needs it too.
_FIRST_PRINTABLE: Final = 0x20
_DELETE: Final = 0x7F


@dataclass(frozen=True, slots=True)
class FileAgent:
    """One `[agent.<connector>]` section, as the file spelled it. `None` is silence, not `off`.

    Named for the layer it came from, like its two siblings: a reader holding one of these knows
    it is looking at a file's contribution to a decision and not at the decision. The fields
    correspond to `schema.ClaudeSettings` / `schema.OpenAiSettings`, which have the same two names
    and no optionality - filling those in is 9.2's whole job.

    An absent section produces one of these with both fields `None`, which is the same answer as a
    section present and empty. That equivalence is deliberate: there is no fact a precedence layer
    could take from the difference, and a `FileAgent | None` would make every read site narrow for
    nothing.
    """

    enabled: bool | None
    """What `enabled` said. `None` where the file was silent - 9.2 decides what silence means."""

    cli_path: Path | None
    """What `cli_path` said, absolute (see `_absolute`). `None` is silence, not "resolve from PATH".

    The two are the same instruction downstream and different facts here: `schema.ClaudeSettings`
    spells "resolve it" as `cli_path=None`, and it reaches that value through 9.2's defaults rather
    than by this module having guessed.
    """


@dataclass(frozen=True, slots=True)
class FileSettings:
    """`AGL_HOME/config.toml`, as the file spelled it: the agent sections and nothing else.

    The field is `agents` and the table is `[agent]` - see the module docstring; this class is one
    half of that mapping. There is no `home` field, and there cannot be one: this file is found
    *under* `AGL_HOME`, so a home written in it would be a value deciding where its own file is.
    """

    claude: FileAgent
    openai: FileAgent


@dataclass(frozen=True, slots=True)
class FileProject:
    """`AGL_HOME/projects/<name>.toml`, as the file spelled it: §3.10's five keys and no others.

    Four fields are optional for the reason the module docstring gives. `name` is not, and the
    exception is the point rather than a slip: a project's identity on disk is its *filename*, this
    module is the only one that ever sees that filename, and a `None` here would leave 9.2 owing an
    answer it has no source for. So the name is read off the file's stem, and the `name` key §3.10
    prints inside the file is held to agreeing with it - two spellings of one fact, reconciled in
    the one place that can see both, exactly as `trees_root` and `Project.trees` are.
    """

    name: ProjectName
    """Which project this is, from the filename, with the in-file `name` key checked against it."""

    repo: Path | None
    """What `repo` said, absolute. The repository AGL never writes into (§3.5), and the key
    `resolve_project` matches a git root against."""

    trees_root: TreesRoot | None
    """What `trees_root` said. Wrapped, because `Project.trees` is a `TreesRoot` and this module is
    where the file's name for it is mapped onto the object's."""

    build: str | None
    """What `build` said - the merge gate's command, handed to a shell by the verifier adapter."""

    build_timeout: float | None
    """What `build_timeout` said, as a `float`. §3.10's example writes `600`, an integer, and
    `Project.build_timeout` is a `float`; widening the one to the other is this module's job, and
    9.1's field docstring says so rather than hiding a coercion in a constructor."""


# What a file that does not exist says, which is nothing. A shared instance because it is frozen,
# holds no path, and is therefore the same object for every home that has no settings file.
_NOTHING_SAID: Final = FileSettings(
    claude=FileAgent(enabled=None, cli_path=None),
    openai=FileAgent(enabled=None, cli_path=None),
)


def read_settings(home: AglHome) -> FileSettings:
    """`AGL_HOME/config.toml`, or a `FileSettings` that says nothing if there is no such file.

    Absence is the ordinary case and not a refusal - an installation that configured nothing is a
    working installation. Everything else about the file is strict: an unknown table, an unknown
    key, a value of the wrong type and a relative path are each an `InputError` naming the file and
    the key.
    """
    path = settings_file(home)
    document = _document(path)
    if document is None:
        return _NOTHING_SAID
    intruders = sorted(_HOME_KEYS & document.keys())
    if intruders:
        raise InputError(
            f"{path}: {intruders[0]} cannot be set here. This file lives inside AGL_HOME, so a "
            f"home written in it could only be read once home had already been resolved. Set the "
            f"AGL_HOME environment variable instead, or pass it on the command line"
        )
    _only(document, (_AGENT,), path, "")
    agents = _sub_table(document, _AGENT, path, "")
    _only(agents, _SECTIONS, path, f"{_AGENT}.")
    return FileSettings(
        claude=_agent(_sub_table(agents, _CLAUDE, path, f"{_AGENT}."), path, _CLAUDE),
        openai=_agent(_sub_table(agents, _OPENAI, path, f"{_AGENT}."), path, _OPENAI),
    )


def read_project(home: AglHome, project: ProjectName) -> FileProject:
    """One named project's file. `NotFoundError` if it does not exist - a name is not a guess.

    Unlike the settings file, absence here is a refusal: the caller named a project, and a project
    with no file is not registered. `resolve_project` is the other way in, by repository.
    """
    path = project_config(home, project)
    document = _document(path)
    if document is None:
        raise NotFoundError(
            f"no project named {str(project)!r} is registered: AGL looked for {path} and there is "
            f"no such file. `agl init` inside the repository writes it"
        )
    return _project(path, document)


def check_unregistered(home: AglHome, project: ProjectName) -> Path:
    """Where a new project's file goes, refusing a name that already has one. §3.10's "once".

    Answers with the path `write_project` will write, so that the caller has the file a refusal
    would name *before* it does anything a person can see - `api.init` needs it for
    `check_trees_root`'s message, and needs this refusal in front of the question it asks the
    operator. `api.py`'s cheapest-refusal-first rule is what puts it there: a build command typed
    into a prompt and then thrown away is the same waste as a `check_ready` spent before a free
    comparison, one command earlier in the day.

    **Not the whole of the refusal, and deliberately not.** This is a check and then a write, so two
    `agl init` runs at once could both pass it; `write_project` creates the file exclusively and
    raises the same `ConflictError` out of the operating system's own answer. One message, two
    call sites, exactly as `check_trees_root` serves the reader and the writer.

    `ConflictError` - exit 4 - because the file is found and is fine and AGL will not take it:
    `ports/errors.py`'s "the world already holds something this operation would have to take or
    overwrite ... the exact mirror of `NotFoundError`", which is also the class `api.run` answers a
    label that already exists with. The message covers both ways a name is held, because from here
    they are indistinguishable: this repository registered already, or a different repository whose
    directory happens to carry the same name.
    """
    path = project_config(home, project)
    if path.exists():
        raise ConflictError(_already(path, project))
    return path


def write_project(
    home: AglHome,
    project: ProjectName,
    repo: Path,
    trees_root: TreesRoot,
    build: str,
    build_timeout: float,
) -> Path:
    """Write `AGL_HOME/projects/<name>.toml` and answer with where it went. `agl init`'s one write.

    §3.10 prints the file this renders and all five of its keys are written. `build_timeout` is a
    parameter rather than a number here for the reason the module docstring gives: the value is read
    off `sources.DEFAULT_BUILD_TIMEOUT` by the caller, so this module renders a float it was handed
    and states none.

    **Created exclusively**, so this never overwrites; a file already there is `ConflictError` with
    `check_unregistered`'s message. The exclusive create *is* the check, taken from the operating
    system rather than from a `stat` this module made a decision on.

    **No `Project` and no `FileProject` in the signature.** The first is 9.2's to build and belongs
    to the module that applies precedence; building one here would put a `schema` type in the
    writer's signature and make `agl init` construct the object every *other* command resolves. The
    second is what this module hands *out*, with every field optional because "the file was silent"
    is a thing a reader has to be able to say - and a writer that took one would be able to say it
    too, which is a file with a key missing and no caller who meant it. So the arguments are the
    five values that are written, at the types the rest of AGL already carries them at, and a caller
    that has not got one of them cannot call this.

    **The timeout is rendered as the `float` it is** - `600.0` where §3.10's example prints `600` -
    because coercing it to an integer when it happens to be whole would be this module deciding what
    a settings value meant, which is the one thing `_wrong` says it does not do. `_seconds` reads
    either back, so an operator who edits it to `900` is writing a file this reader already accepts.
    Range is not checked, for `_seconds`' own reason: `schema.Project` refuses a non-finite or
    non-positive timeout and one copy of that rule is enough.

    `InputError` if the write itself fails, for `_document`'s reason read the other way: "there is
    no such file" is a fact two readers interpret differently, and a home directory that cannot be
    written to is a broken installation either way.
    """
    path = project_config(home, project)
    document = "".join(
        f"{key} = {_quoted(value)}\n"
        for key, value in (
            (_NAME, str(project)),
            (_REPO, str(repo)),
            (_TREES_ROOT, str(trees_root.path)),
            (_BUILD, build),
        )
    ) + f"{_BUILD_TIMEOUT} = {build_timeout!r}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
    except FileExistsError as error:
        raise ConflictError(_already(path, project)) from error
    except OSError as error:
        raise InputError(
            f"{path} cannot be written: {error}. That is where AGL keeps this project's settings, "
            f"so `agl init` has nowhere to record the repository it was run in"
        ) from error
    return path


def git_root(start: Path) -> Path:
    """The working tree `start` is inside, found by walking up for a `.git` entry.

    A pure filesystem walk: no subprocess, no `adapters.git` - see the module docstring. The result
    is resolved, so it compares equal to any other route to the same directory. `.git` is tested
    for existence rather than for being a directory, because a linked worktree or a submodule
    writes a file there.
    """
    directory = start.resolve()
    for candidate in (directory, *directory.parents):
        if (candidate / _GIT).exists():
            return candidate
    raise NotFoundError(
        f"{directory} is not inside a git repository: AGL walked up from it to "
        f"{directory.anchor} looking for a {_GIT} entry and found none. AGL works on a "
        f"repository, so run it from inside one - and `agl init` there to register it"
    )


def check_trees_root(path: Path, repo: Path, trees_root: Path) -> None:
    """Refuse a trees root that resolves to somewhere inside the repository. §3.5's whole rule.

    "AGL lives outside the target repo" (§3.5) and everything of AGL's own lives under `AGL_HOME`
    "so AGL never appears in `git status`" (§3.10). A `trees_root` under `repo` breaks both at once
    and breaks them quietly: `.trees/<label>/_base/` is a real checkout with a real working tree, so
    what the operator gets is AGL's worktrees inside their own repository, in every `git status`,
    in every `git add -A`, and inside whatever their build walks.

    **Exported, and read by both directions**, which is the reason it is a named function rather
    than four lines inside `_project`. This module is where a `Project` comes into existence out of
    a file, and 16.4's `init` is what writes that same file - so one helper serves the reader and
    the writer, and a nested trees root is refused when it is written as well as when it is read.

    **This lives here and not in `sdk/_engine/preflight.py`**, and the reason is that no path ever
    reaches preflight. That module takes an `AgentRunner` and roles; `api.run` takes a `ProjectName`
    and deliberately not a `Project` (its docstring argues that at length); and `Services` holds
    ports and one build command. Widening any of those three signatures to carry two `Path`s would
    undo a decision each of them already argues for, in order to move a check into a module that
    would then have a second reason to exist. `toml_file.py` already walks the filesystem to find a
    git root, so this is not a new kind of work here either.

    **Resolution is what kept it out of `schema.py`.** Stage 9 declined this check because
    `Project.__post_init__` is a pure function of its arguments - "the same values answer the same
    way on any machine, with any filesystem underneath" - and a nested trees root cannot be seen
    without following symlinks: `/tmp` is a link on macOS, a repository reached through one and the
    same repository reached directly must compare equal, and `..` in either path has to be spent
    before the comparison means anything. `Path.resolve()` reads the filesystem, so the check is
    impure by construction and belongs in the module that already reads files.

    `InputError`, like every other refusal a settings file earns: the operator's file is wrong and
    they can fix it, and exit 2 sends them to the file rather than to a bug report. The message
    names the file, both keys and both resolved paths, because a symlinked or `..`-carrying value
    looks innocent as written and the resolved pair is what makes the overlap visible.
    """
    inside = trees_root.resolve()
    around = repo.resolve()
    if not inside.is_relative_to(around):
        return
    raise InputError(
        f"{path}: {_TREES_ROOT} is inside {_REPO}. {_TREES_ROOT} resolves to {inside} and {_REPO} "
        f"to {around}, so AGL's working checkouts would be cut inside the repository they are cut "
        f"*from* - present in your `git status`, swept up by `git add -A`, and walked by whatever "
        f"your build walks. AGL lives outside the target repository (§3.5) and keeps its own state "
        f"under AGL_HOME so that it never appears there (§3.10). Point {_TREES_ROOT} at a "
        f"directory beside the repository rather than under it"
    )


def resolve_project(home: AglHome, start: Path) -> FileProject:
    """Which project `start` is in: up to the git root, then the file whose `repo` is that root.

    §3.6's rule, and what makes labels per-project. Call it **once** per invocation and pass the
    answer down - the behaviour §1.10 complains about is `load_project` being called inside every
    command, and the scan below is bounded and cheap exactly once.

    Both paths are resolved before they are compared, so a repository reached through a symlink and
    the same repository reached directly are one project. Files are read in sorted order and the
    first match wins.
    """
    root = git_root(start)
    for candidate in _project_files(home):
        document = _document(candidate)
        if document is None:
            continue  # Deleted between the listing and the read. Not this invocation's business.
        project = _project(candidate, document)
        if project.repo is not None and project.repo.resolve() == root:
            return project
    raise NotFoundError(
        f"no project is registered for the repository at {root}: AGL read every project settings "
        f"file under {home.path} and none of them names it as its repo. Run `agl init` inside "
        f"{root} to write one"
    )


def _document(path: Path) -> Mapping[str, object] | None:
    """One file's tables, or `None` if there is no such file. The only `tomllib` call in AGL.

    Binary read and `tomllib.load`, from the standard library: AGL takes no third-party dependency
    for a file format, which `pyproject.toml` states as a design decision rather than an accident.
    `dict[str, Any]` in, `Mapping[str, object]` out - the one narrowing that keeps `Any` from
    leaking anywhere else.

    `FileNotFoundError` is answered and every other `OSError` is refused, because "there is no such
    file" is a fact two callers read differently while "it is a directory" or "permission denied"
    is a broken installation either way.
    """
    try:
        with path.open("rb") as handle:
            document: dict[str, object] = tomllib.load(handle)
    except FileNotFoundError:
        return None
    except tomllib.TOMLDecodeError as error:
        raise InputError(
            f"{path} is not valid TOML: {error}. AGL will not guess at what a half-parsed "
            f"settings file meant to say"
        ) from error
    except (OSError, UnicodeDecodeError) as error:
        raise InputError(f"{path} cannot be read: {error}") from error
    return document


def _project(path: Path, document: Mapping[str, object]) -> FileProject:
    """§3.10's five keys, read out of one already-parsed project file."""
    _only(document, _PROJECT_KEYS, path, "")
    trees = _absolute(document, _TREES_ROOT, path, "")
    repo = _absolute(document, _REPO, path, "")
    # Both or neither: `None` means the file was silent about that key, and a rule about how two
    # paths sit relative to each other has nothing to say when there is only one of them. Which
    # of the two silences is itself a problem is 9.2's to decide - this module reports what the
    # file said, and a default is a precedence layer.
    if repo is not None and trees is not None:
        check_trees_root(path, repo, trees)
    return FileProject(
        name=_project_name(path, _text(document, _NAME, path, "")),
        repo=repo,
        # `TreesRoot` refuses a relative root; `_absolute` has already refused it here, with the
        # file and the key in the message, so this construction cannot fail.
        trees_root=None if trees is None else TreesRoot(trees),
        build=_text(document, _BUILD, path, ""),
        build_timeout=_seconds(document, _BUILD_TIMEOUT, path, ""),
    )


def _project_name(path: Path, spelled: str | None) -> ProjectName:
    """The project's name: its filename, with the in-file `name` key held to agreeing with it.

    Two spellings of one fact, and this is where they are reconciled. Disagreement is refused
    rather than resolved in either direction: the filename decides where `home_layout` puts the
    project's runs, the key is what §3.10 prints, and a file called `myapp.toml` that says
    `name = "other"` would record its runs under a project no lookup by name can find.
    """
    try:
        name = ProjectName(path.stem)
    except InputError as error:
        raise InputError(
            f"{path}: its filename is not a usable project name. {error}"
        ) from error
    if spelled is not None and spelled != str(name):
        raise InputError(
            f"{path}: {_NAME} is {spelled!r} but the file is called {path.name!r}, and a "
            f"project's name is its filename - that is where AGL looks it up and where its runs "
            f"are recorded. Rename the file, or correct the key"
        )
    return name


def _project_files(home: AglHome) -> list[Path]:
    """Every project settings file, sorted, so a scan is deterministic and so is which match wins.

    The listing is the whole of the "glob-scan" that survives, and it happens once per invocation.
    A missing `projects/` directory is an empty list rather than a refusal: an installation that
    has never run `agl init` has no such directory, and `resolve_project` gives it the message that
    says so.

    A directory is filtered out as well as a non-`.toml` file, because `projects/<name>/` - one
    project's runs - sits beside `projects/<name>.toml` and only one of the two is a settings file.
    """
    directory = projects_dir(home)
    try:
        entries = sorted(directory.iterdir())
    except FileNotFoundError:
        return []
    except OSError as error:
        raise InputError(f"{directory} cannot be listed: {error}") from error
    return [entry for entry in entries if entry.suffix == _PROJECT_SUFFIX and entry.is_file()]


def _agent(table: Mapping[str, object], path: Path, section: str) -> FileAgent:
    """One `[agent.<connector>]` section. An absent section arrives here as an empty table."""
    prefix = f"{_AGENT}.{section}."
    _only(table, _AGENT_KEYS, path, prefix)
    return FileAgent(
        enabled=_flag(table, _ENABLED, path, prefix),
        cli_path=_absolute(table, _CLI_PATH, path, prefix),
    )


def _only(table: Mapping[str, object], expected: tuple[str, ...], path: Path, prefix: str) -> None:
    """Refuse any key that is not one of `expected`, naming it and them.

    The strictness the module docstring argues for, in one function so that every table gets it.
    Refused and not ignored: a misspelt key that quietly keeps the default is a setting the
    operator believes they changed.
    """
    for key in table:
        if key not in expected:
            raise InputError(
                f"{path}: {prefix}{key} is not something AGL configures. This file's keys are "
                f"{', '.join(prefix + name for name in expected)}. An unknown key is refused "
                f"rather than ignored, because a misspelt one would keep the default silently"
            )


def _sub_table(
    table: Mapping[str, object], key: str, path: Path, prefix: str
) -> Mapping[str, object]:
    """A nested table, or an empty one where the file was silent. Anything else is refused."""
    raw = table.get(key)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    raise _wrong(path, prefix + key, "a table", raw)


def _flag(table: Mapping[str, object], key: str, path: Path, prefix: str) -> bool | None:
    """A `true`/`false` value, or `None` where the file was silent."""
    raw = table.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    raise _wrong(path, prefix + key, "true or false", raw)


def _text(table: Mapping[str, object], key: str, path: Path, prefix: str) -> str | None:
    """A string value, or `None` where the file was silent."""
    raw = table.get(key)
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    raise _wrong(path, prefix + key, "a string", raw)


def _seconds(table: Mapping[str, object], key: str, path: Path, prefix: str) -> float | None:
    """A number of seconds as a `float`, or `None` where the file was silent.

    `bool` is excluded before the numeric check because Python says `True` is an `int` and a
    build timeout of `true` is not a number anybody meant. Range is not checked here:
    `schema.Project` refuses a non-finite or non-positive timeout, and one copy of that rule is
    enough - this module's job is that what arrives there is a number at all.
    """
    raw = table.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise _wrong(path, prefix + key, "a number of seconds", raw)
    return float(raw)


def _absolute(table: Mapping[str, object], key: str, path: Path, prefix: str) -> Path | None:
    """A path value, refused unless absolute, or `None` where the file was silent.

    One rule for all three paths a file can hold - `repo`, `trees_root`, `cli_path` - because they
    share the reason. A relative path in a settings file resolves against whatever directory AGL
    was invoked from, which for an agent step is a worktree AGL chose; it would name a different
    directory on every read. `AglHome`, `TreesRoot` and both connector sections each refuse one in
    their own constructors, and this refusal is not that one repeated: it is the only one that can
    say which file and which key the operator has to go and fix.
    """
    text = _text(table, key, path, prefix)
    if text is None:
        return None
    value = Path(text)
    if not value.is_absolute():
        raise InputError(
            f"{path}: {prefix}{key} is {text!r}, which is a relative path. Every path in a "
            f"settings file is absolute, because this file is read from wherever AGL happened to "
            f"be invoked and a relative one would name a different directory each time"
        )
    return value


def _already(path: Path, project: ProjectName) -> str:
    """What both halves of the never-overwrite refusal say. One sentence, two call sites.

    It names both ways a project name is held, because from inside this module they are one fact -
    a file at that path - and the two have different fixes. `agl init` is run once per repository,
    so the reader is either somebody who already ran it, or somebody whose second repository has the
    same directory name as their first; §3.6 looks a project up by repository path but addresses it
    on disk by name, which is what makes the second case a collision at all.
    """
    return (
        f"a project named {str(project)!r} is already registered: {path} exists, and `agl init` "
        f"writes that file once per repository and never writes over it. If that is this "
        f"repository, its settings are already there - edit the file to change them, or delete it "
        f"and run `agl init` again. If it is a different repository whose directory happens to "
        f"carry the same name, one of the two has to be renamed: a project's name is its "
        f"directory's name, and that name is the file AGL records its runs beside"
    )


def _quoted(value: str) -> str:
    """One TOML basic string, escaped as the format defines it. The write side of `tomllib`.

    A basic string rather than a literal (single-quoted) one, because a literal string admits no
    escapes at all: a build command holding an apostrophe - `don't` - would end the value early and
    produce a file that will not parse. Basic strings can always be written, at the cost of this
    table.

    Every control character below `\\x20`, and `\\x7f`, takes the `\\u00xx` form, which is the
    format's own fallback for the ones with no short escape. Nothing else is touched: `_absolute`
    and `ids.py` have already refused most of what could be here, and a writer that decided which
    *printable* characters a value may hold would be a second validator with a second opinion.
    """
    escaped = "".join(
        _ESCAPED[character]
        if character in _ESCAPED
        else f"\\u{ord(character):04x}"
        if ord(character) < _FIRST_PRINTABLE or ord(character) == _DELETE
        else character
        for character in value
    )
    return f'"{escaped}"'


def _wrong(path: Path, key: str, expected: str, got: object) -> InputError:
    """The one wording for "that value is not that kind of thing". Returned, so callers raise it."""
    return InputError(
        f"{path}: {key} is {got!r}, which is not {expected}. AGL does not coerce a settings value "
        f"into the type it was expecting - a file that says something other than what it meant is "
        f"worth stopping for"
    )
