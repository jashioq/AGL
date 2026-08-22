"""Typed settings, with a nested section per connector - the shapes, and nothing that fills them.

§1.10 is the violation this answers: the old `config.toml` was flat, had **no `[agent]` section**,
and so put R2 - several vendors inside one run - out of reach of configuration entirely. The fix is
not a bigger flat file but a settings *object* with one nested section per connector, resolved once
at the edge and passed down as data, so "which providers is this run assembled with" has a typed
answer instead of a scatter of `os.environ` reads.

This module holds **types only**. Nothing here opens a file, reads an environment variable, walks up
to a git root, applies a default, or knows that TOML exists. Precedence - flags > env > file >
defaults - is `sources.py` (9.2); the file format is `toml_file.py` (9.3). What is left is a set of
constructors that are pure functions of their arguments, exactly as `ports/home_layout.py` is: the
same values answer the same way on any machine, with any filesystem underneath. That is what makes
these types safe to construct in a test with `/nowhere`, and why validation stops where disk begins.

## Three things this module settles, because they are the point of it

**Configured is not available, and no field here could hold the answer.** §3.2.1 records an
asymmetry a settings schema is tempted to smooth over: the Claude harness arrives through a pip
extra, `agl[claude]`, while OpenAI support is a separately installed binary with *no Python
dependency at all*. So "did the operator ask for this provider" and "can this machine serve it" are
two different questions, and only the first is configuration. This schema records the ask; it
verifies nothing - not that a path exists, not that a binary is executable, not that a session is
authenticated. The second question is `AgentRunner.check_ready(model)` at preflight (§3.2, stage
16), because only an adapter can answer it, and it is asked per run because the answer changes
while a process is running: a session expires, a binary is upgraded, a `PATH` differs between two
shells. An `available: bool` here would be a cached answer to a question this module never asked,
stale the moment it was written, read by a container that must make the real check anyway.

**There is no config-level model override** (§3.11, §3.2.1). A workflow's model choice sits beside
the prompt because the reason for it is semantic - this role touches sensitive code, that one needs
deep judgement - and it is a one-line edit in code the author owns. An override would cost a schema
here, a resolution rule in 9.2, validation of model ids against providers, and one genuinely
confusing failure mode: *why is my Opus role running GPT-5?* It earns its keep only once workflows
are distributed and retargeted without forking, which is not v1.1. So no class below carries a
model, a default model, or a per-role mapping.

**No field on any class below has a default value**, which is the rule that makes 9.2 unable to
forget a layer. A default written here would be a fifth precedence layer, invisible to the four
`sources.py` composes, applied silently at a moment when nothing is recording where a value came
from - so `agl run --cli-path=...` and a value nobody set would be indistinguishable downstream.
Every field is required and every construction states every value. `dataclasses` makes that
mechanical rather than aspirational: omit an argument and the constructor raises `TypeError` before
any validation below runs, and `tests/config/test_schema.py` asserts it field by field.

## Why `Settings` and `Project` are two objects and not one

`Settings` is global and always resolvable. `agl init` runs in a repository AGL has never heard of,
`agl workflows` looks at no repository at all (§3.10), and both need `AGL_HOME` and the agent
sections. `Project` is what `AGL_HOME/projects/<name>.toml` holds, and outside a registered
repository there is no such file - `init` is the command that writes the first one.

Merged, that difference would be carried as `Settings.project: Project | None`, which every consumer
narrows and two commands narrow to `None` every time - load-bearing optionality exactly where it is
least visible, since a command that forgot to narrow would read attributes off a project that did
not exist yet. Two types make "this operation needs a registered project" a fact about which object
a function takes, and leave `NotFoundError` in 9.3 as the refusal for an unregistered repository
rather than a `None` travelling downward.

## Per-connector sections: two named types, not `Mapping[Provider, ConnectorSettings]`

The mapping is the obvious alternative, and it is the shape `RoutingAgentRunner` takes -
`Mapping[Provider, AgentRunner]` - so symmetry argues for it. Three things argue against, and they
are about settings rather than about mappings.

*A mapping's value type is uniform, and these sections will not stay uniform.* Today both carry
`enabled` and `cli_path` and a shared type would fit exactly. The first setting belonging to one
connector and meaningless for the other - anything about a Python SDK for one, a sandbox policy for
the other - forces a choice between a shared class carrying a field half its instances ignore, and
a union every read site narrows. Two named types pay that cost now, at two class statements.

*A mapping cannot promise a key is there.* `settings.agents.claude` is checked statically and cannot
be absent; `settings.agents[Provider.CLAUDE]` is a `KeyError` waiting for the one path nobody
exercised, or a `.get` returning `None` the container has to interpret. The container needs both
sections on every run - it decides from them which runners to construct - so a shape that can be
missing one is a shape that must be checked for one.

*A mapping invites the file to become the schema.* `Provider` is a closed set: "a provider is not a
string a user configures, it is a backend somebody wrote an adapter for, and the two arrive in the
same commit" (`ports/agent.py`). A mapping keyed by it makes an arbitrary `[agents.anthropic]` table
in somebody's TOML look like data to pass along, and the natural implementation carries it. Named
fields make an unknown section a refusal in 9.3, where the reader is still holding the file.

Not using the mapping costs one field here when a third provider arrives - in the same commit as its
adapter, which §3.2 already requires. The mapping still gets built: `config/container.py` composes
one from these sections, at the point where a lookup is the operation.

## What the constructors refuse, and where the refusals stop

`InputError` in every case: an operator supplied a settings value that cannot be used, nothing has
been attempted, exit 2 sends the reader to the configuration rather than to a bug report (§3.1).

Absolute paths are the theme. A relative `repo` or `cli_path` resolves against the process's working
directory, and AGL's is not something an operator can reason about - the CLI is launched from
anywhere inside a repository, and an agent runs with a worktree AGL chose. Such a value is not a
shorthand; it means something different every time it is read. `AglHome` and `TreesRoot` already
refuse a relative root in their own `__post_init__` and are deliberately **not** re-checked here: a
guard that cannot fire is not a guard, and a second copy of the reason is a second copy to drift.

Nothing below touches the filesystem. Whether `repo` is a directory, whether it is a git repository,
whether `cli_path` names an executable - each asks the world, each has a different answer five
minutes later, and each belongs to preflight or to the command about to act on it.
"""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome
from agl.ports.ids import ProjectName
from agl.ports.tree_layout import TreesRoot

__all__ = ["AgentSettings", "ClaudeSettings", "OpenAiSettings", "Project", "Settings"]


@dataclass(frozen=True, slots=True)
class ClaudeSettings:
    """The Claude connector's section: whether the operator asked for it, and where its CLI lives.

    These two fields are exactly what the composition root needs and no more - `ClaudeCodeRunner`
    takes a `Path | None` and nothing else - which is the test this section is held to. A field no
    constructor consumes is one 9.2 must resolve, 9.3 must parse and a reader must account for, and
    nothing about the run is different for it.
    """

    enabled: bool
    """Whether this provider is configured for this installation. Not whether it works.

    Disabled means the container builds no adapter, and a workflow naming a Claude model then gets
    `InputError` from `RoutingAgentRunner` naming the providers that *are* held - the same refusal
    it gets when the harness is missing, because from a workflow's side it is the same fact.
    """

    cli_path: Path | None
    """Where the Claude Code CLI is, or `None` to let the adapter resolve it from `PATH`.

    `None` is the ordinary case and a value rather than an absence: it says "resolve it", which is
    why the field is `Path | None` rather than optional-by-default.
    """

    def __post_init__(self) -> None:
        _check_cli_path(self.cli_path, "claude")


@dataclass(frozen=True, slots=True)
class OpenAiSettings:
    """The OpenAI connector's section. Identical today to its sibling, and deliberately not shared.

    The two classes carry the same two fields and will not necessarily go on doing so, which is the
    whole argument for writing them twice - see the module docstring. The asymmetry that already
    exists is in installation rather than in fields: this provider's harness is a binary installed
    outside pip, with no Python dependency and no extra (§3.2.1), so there is nothing importable to
    detect and `enabled` is the only place an installation says it means to use this backend.
    """

    enabled: bool
    """Whether this provider is configured for this installation. Not whether it works.

    The sibling's note applies. With no pip extra to make "installed" observable, preflight is the
    only thing separating "never asked for" from "asked for and never installed".
    """

    cli_path: Path | None
    """Where the harness binary is, or `None` to let the adapter resolve it from `PATH`."""

    def __post_init__(self) -> None:
        _check_cli_path(self.cli_path, "openai")


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """One section per `Provider` member. The nesting §1.10 says the flat file made impossible.

    One field per member of `ports/agent.py`'s `Provider`, and the correspondence is the invariant:
    a provider with no section is a provider nothing can configure, which is the violation being
    fixed. `tests/config/test_schema.py` compares these field names against the enum's members, so
    a provider added without a section fails a test rather than shipping unconfigurable.

    Both sections are always present, even when both are disabled. A run assembled with no agent
    backend is representable here and refused where it becomes real - `RoutingAgentRunner` raises
    `InputError` on an empty mapping - because that refusal belongs with the object that would have
    to serve the run, and `agl workflows` has no business failing over it.
    """

    claude: ClaudeSettings
    openai: OpenAiSettings


@dataclass(frozen=True, slots=True)
class Settings:
    """What is true of this installation wherever it runs, including outside a registered project.

    `agl init` and `agl workflows` (§3.10) run with no project file in existence and both need this
    object - the first to know where to write, the second to know where AGL's own state lives. So
    everything here resolves from flags, environment and defaults alone: no field's value could
    come only from a project's file, and adding one would leave two commands unable to construct
    the object they need.
    """

    home: AglHome
    """Where AGL keeps its own state. `home_layout.py` is the only module that computes under it."""

    agents: AgentSettings
    """The per-connector sections. Nested rather than flattened - that is §1.10's whole point."""


@dataclass(frozen=True, slots=True)
class Project:
    """One registered repository: exactly what `AGL_HOME/projects/<name>.toml` holds (§3.10).

    The plan writes that file out in full and these five fields are it - `name`, `repo`,
    `trees_root`, `build`, `build_timeout`. Nothing else, deliberately: §3.11 refuses `run.project`
    as an accessor and refuses build commands as framework plumbing, because "build and test
    commands are written literally into prompts, hand-tuned per project" (§3.2.1). The `build` here
    is the *other* one - the merge gate, through the `Verifier` port - independent by design. A
    sixth field would be a sixth thing every project's file has to answer for. The file lives under
    `AGL_HOME`, not in the repository, so AGL never appears in `git status` (§3.5).
    """

    name: ProjectName
    """The name, which is also the filename and the directory under `AGL_HOME/projects/`.

    A validated type rather than a `str`: `ids.py` has already refused the names that cannot be a
    path segment, and `home_layout.py` has already accounted for the five bytes `.toml` adds.
    """

    repo: Path
    """The repository's working directory - the one AGL never touches (§3.5). Absolute, see below.

    A bare `Path`, unlike the two roots: those are wrapped to be told apart from each other, and
    there is nothing here for this one to be confused with.
    """

    trees: TreesRoot
    """Where working checkouts go: `.trees/<label>/...`, computed by `tree_layout.py` alone.

    The file spells this `trees_root`; the field is `trees` because its type says "root" already,
    and mapping one onto the other is 9.3's job, in the module that knows the file format.
    """

    build: str
    """The merge gate's build command, through the `Verifier` port. `./gradlew build` and such.

    Handed to a shell by the adapter that owns that decision: not parsed or split here, and not
    asked whether the program in it exists.
    """

    build_timeout: float
    """Seconds the build may take. Project configuration, which is why `Verifier.verify` has no
    timeout parameter of its own (§3.11): a hosted verifier with its own deadline would carry an
    argument it could only ignore.

    A `float` although the plan's example file writes `600`. An `int` is a `float` to the type
    checker and to `isfinite`; turning what the file holds into what this declares is 9.3's job,
    not a coercion hidden in a constructor.
    """

    def __post_init__(self) -> None:
        # `trees` is a `TreesRoot`, which refuses a relative root in its own `__post_init__`, as
        # `AglHome` does on `Settings`. Neither is re-checked here: a guard that cannot fire is not
        # a guard, and a second copy of that reason is a second copy to drift.
        if not self.repo.is_absolute():
            raise InputError(
                f"repo {str(self.repo)!r} cannot be used: it is a relative path, and a relative "
                f"repository resolves against whatever directory the process started in - which "
                f"for an agent step is a worktree AGL chose, not the one the operator typed it in"
            )
        if not self.build.strip():
            raise InputError(
                f"build {self.build!r} cannot be used: it is the command the merge gate runs, and "
                f"a blank one would make every run's gate pass without building anything. If this "
                f"project has no build, that is a decision to make where the gate is configured, "
                f"not a value that arrives here empty"
            )
        if not isfinite(self.build_timeout) or self.build_timeout <= 0:
            raise InputError(
                f"build_timeout {self.build_timeout!r} cannot be used: it is a number of seconds "
                f"the build is allowed to take, so it must be finite and greater than zero. Zero "
                f"or less kills every build before it starts; an infinite deadline is a run that "
                f"hangs on a build nobody is watching"
            )


def _check_cli_path(cli_path: Path | None, section: str) -> None:
    """Refuse a relative harness path. The one rule both connector sections share, written once.

    A function rather than a base class, so the two sections stay independent shapes: inheritance
    would put a field on both the day either one needs it, the coupling the module docstring argues
    against. This couples them on the rule they have in common and nothing else. `None` passes - it
    is not a path, it means "resolve from `PATH`" - and so does an absolute path naming nothing:
    whether a binary is there is `check_ready`'s answer at preflight.
    """
    if cli_path is not None and not cli_path.is_absolute():
        raise InputError(
            f"{section} cli_path {str(cli_path)!r} cannot be used: it is a relative path, and a "
            f"relative program path resolves against the process's working directory - which for "
            f"an agent run is a worktree AGL chose. Give an absolute path, or leave it unset and "
            f"let the adapter resolve the harness from PATH"
        )
