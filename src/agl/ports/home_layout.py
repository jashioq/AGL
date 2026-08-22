"""Paths under AGL_HOME - the one module that composes them.

`AGL_HOME` is where AGL keeps its own state: which runs exist, what each one has already done,
the per-project settings files, and the operator's own settings file at the top. It is not where
code is checked out. That is the trees root, `tree_layout.py` is the only module that computes
under it, and the plan's rule is that the two are never conflated - so this module speaks
`AglHome`, that one speaks `TreesRoot`, and neither imports the other. Nothing here can be handed
the other root: `mypy --strict` refuses the call, and `_root` below refuses it again at runtime,
because the two wrappers are structurally identical and nothing but the class itself tells them
apart.

**The rule is that one module composes under `AGL_HOME`** - not that everything here is a path
`Store` addresses. Most of it is, and `Store` is why the module was written, but `project_config`
has been here since stage 2 and no store has ever read it, and `settings_file` is read by
`config/` before anything at all has been constructed. What puts a path here is the root it is
joined onto, not who opens the result: a second module that spells `projects/` or `config.toml`
is a second module to find and change the day the layout moves, and that drift is exactly §1.10's
charge against the previous implementation.

The layout, from the plan - §3.6's diagram, with §1.10's global file above it:

    AGL_HOME/
      config.toml                            <- the operator's own settings (§1.10)
      projects/myapp.toml
      projects/myapp/runs/auth/
        run.json
        steps/
          spec/9f2c4e...a71b.json
          tickets/3d81f0...4c92.json
        worktrees/T-01/
          steps/
            implement/1d80ba...3f47.json
            review_quality/aa71c9...08de.json
          worktrees/...                        <- nests arbitrarily

Two facts about that tree shape every signature here.

**Runs are stored per project.** Labels are scoped to a repo, so `agl resume feat1` finds repo
A's run and reports no such label in repo B. A run is addressed by a `ProjectName` *and* a
`RunLabel`, and there is no function here that takes a label alone.

**`steps/` and `worktrees/` are sibling subtrees**, so `worktree("review")` and
`step("review", ...)` in one run cannot collide - and `worktrees/` nests arbitrarily, so a step
inside `T-01/worktrees/sub-b/` sits at the end of a *sequence* of namespaces, not one.
`RunScope` is that sequence and `scope_dir` is the only loop that walks it. Neither `steps/`
nor `worktrees/` is addressable on its own: a caller has nothing to join a namespace onto, so
the nesting rule is written down once and a second copy cannot drift from this one.

**`projects/` is addressable and those two are not**, and the difference is one of kind rather
than a softening of the rule above. `steps/` and `worktrees/` are segments on the way to
something the caller already names - a step, a namespace - so handing back the container hands
back the join, and the nesting rule gains a second author. `projects/` is a directory whose
*contents are the answer*: §3.6 resolves a project by walking up to a git root and looking it up
**by repository path**, a path is not a name, so the names are not known in advance and
enumerating them is the operation. Nothing is left for a caller to compose: a name becomes a file
only through `project_config`, and only if `_checked_project` says it fits.

Every function is a pure function of its arguments. Nothing here creates a directory, asks
whether one exists, reads the environment, or consults the current working directory - `Store`
does the first, and deciding where `AGL_HOME` actually is belongs to `config/`. These functions
receive the root and compute beneath it.

Two path segments arrive without a type from `ids.py` vouching for them, and both are checked
here, at the composition site, because everything downstream is entitled to assume they were:
the digest of a step entry (see `_checked_digest`) and the five bytes `.toml` adds to a project
name (see `_checked_project`).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.ports.errors import InputError, InternalError
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName

__all__ = [
    "AglHome",
    "RunScope",
    "project_config",
    "project_dir",
    "projects_dir",
    "run_record",
    "scope_dir",
    "settings_file",
    "step_dir",
    "step_entry",
]


# The layout's own words. Every one of them appears exactly once below.
_SETTINGS_FILE: Final = "config.toml"
_PROJECTS: Final = "projects"
_RUNS: Final = "runs"
_STEPS: Final = "steps"
_WORKTREES: Final = "worktrees"
_RUN_RECORD: Final = "run.json"
_PROJECT_SUFFIX: Final = ".toml"
_ENTRY_SUFFIX: Final = ".json"

# NAME_MAX, the same cap `ids.py` measures a name against, restated here because this is the
# module that composes a name into a longer filename.
_MAX_SEGMENT_BYTES: Final = 255

# A sha256 hexdigest: 64 characters drawn from this alphabet, and nothing else.
_DIGEST_CHARACTERS: Final = frozenset("0123456789abcdef")
_DIGEST_LENGTH: Final = 64


@dataclass(frozen=True, slots=True)
class AglHome:
    """The root of AGL's own state, wrapped so it cannot be passed where a trees root belongs.

    Both roots are directories and both are a `Path`; the wrapper is the whole of what makes
    them different. Resolving which directory this is - `$AGL_HOME`, or a default beside the
    user's other application state - is `config/`'s job at stage 9. This type receives the
    answer and asserts one thing about it: that it is absolute. A relative root would be
    resolved against whatever directory the process happened to start in, which would make
    every path below it a function of something this module has promised not to read.
    """

    path: Path
    """Where it is. Read it to hand the root itself to something; the layout is the functions."""

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise InputError(
                f"AGL_HOME {str(self.path)!r} cannot be used: it is a relative path, and a "
                f"relative root resolves against the current working directory"
            )


@dataclass(frozen=True, slots=True)
class RunScope:
    """Which run, and how deep inside it - the address everything below a project is computed on.

    A run is a project and a label (`projects/myapp/runs/auth/`). A worktree inside that run is
    the same run plus a namespace (`.../auth/worktrees/T-01/`), and a worktree inside *that* is
    the same run plus two (`.../T-01/worktrees/sub-b/`), which is why the namespaces are a
    sequence and not one name. Depth zero is the run itself, and its `steps/` subtree is where
    the steps a workflow ran before it took any worktree are recorded.

    `inside` is the only way to gain depth, and `run` the only way to lose it: those two, and
    `scope_dir`, are between them the entire nesting rule.
    """

    project: ProjectName
    label: RunLabel
    namespaces: tuple[Namespace, ...] = ()

    def inside(self, namespace: Namespace) -> RunScope:
        """The scope one worktree deeper. Nesting is arbitrary, so this composes with itself."""
        return RunScope(self.project, self.label, (*self.namespaces, namespace))

    @property
    def run(self) -> RunScope:
        """The same run at depth zero - what a per-run file belongs to, whoever asked for it."""
        return RunScope(self.project, self.label)


def settings_file(home: AglHome) -> Path:
    """`AGL_HOME/config.toml` - the operator's own settings, and the only file at the top.

    The connector sections `[agent.claude]` and `[agent.openai]`, and whatever else later
    acquires a setting that is not per-project. `config/` owns the file's *format* and reads it
    before anything at all is constructed; this module owns only where it is, for the reason the
    module docstring gives: one place computes under `AGL_HOME`, whoever opens the result.
    """
    return _root(home) / _SETTINGS_FILE


def projects_dir(home: AglHome) -> Path:
    """`AGL_HOME/projects/` - the registered projects, one settings file and one subtree each.

    The two functions below compose beneath it. Exposed, where `steps/` and `worktrees/`
    deliberately are not, because this is the container whose contents are themselves an answer:
    resolving a project means listing it, since §3.6 looks a project up by repository path and
    the names are not known in advance. The module docstring has the full distinction.
    """
    return _root(home) / _PROJECTS


def project_config(home: AglHome, project: ProjectName) -> Path:
    """`AGL_HOME/projects/<project>.toml` - one project's settings."""
    return projects_dir(home) / f"{_checked_project(project)}{_PROJECT_SUFFIX}"


def project_dir(home: AglHome, project: ProjectName) -> Path:
    """`AGL_HOME/projects/<project>/` - everything AGL has recorded about one project."""
    return projects_dir(home) / _checked_project(project)


def scope_dir(home: AglHome, scope: RunScope) -> Path:
    """The directory a scope addresses: the run at depth zero, a nested worktree below it.

    The one place the `worktrees/` nesting is written down. A scope with namespaces
    `(T-01, sub-b)` lands at `runs/<label>/worktrees/T-01/worktrees/sub-b/`, and because
    `worktrees/` is not itself addressable there is no shorter way for a caller to get there.
    """
    path = project_dir(home, scope.project) / _RUNS / str(scope.label)
    for namespace in scope.namespaces:
        path = path / _WORKTREES / str(namespace)
    return path


def run_record(home: AglHome, scope: RunScope) -> Path:
    """`<run>/run.json` - the run's own record.

    There is one per run and it lives at the top, so a scope's namespaces are not consulted:
    asked from anywhere inside a run, this answers with that run's record. `scope.run` says so
    in the expression rather than in this sentence.
    """
    return scope_dir(home, scope.run) / _RUN_RECORD


def step_dir(home: AglHome, scope: RunScope, step: StepName) -> Path:
    """`<scope>/steps/<step>/` - one step's entries, in the scope that ran it.

    `steps/` and `worktrees/` are siblings under every scope, which is what keeps
    `step("review", ...)` and `worktree("review")` in one run out of each other's way.
    """
    return scope_dir(home, scope) / _STEPS / str(step)


def step_entry(home: AglHome, scope: RunScope, step: StepName, digest: str) -> Path:
    """`<scope>/steps/<step>/<digest>.json` - one recorded run of one step.

    The digest is the step's fingerprint, computed by the journal; see `_checked_digest` for
    what this module insists on before spending it as a filename.
    """
    return step_dir(home, scope, step) / f"{_checked_digest(digest)}{_ENTRY_SUFFIX}"


def _root(home: AglHome) -> Path:
    """The one place this module reads its root, and so the one place it can be the wrong root.

    `AglHome` and `TreesRoot` are both a frozen wrapper around a `Path` in a field called
    `path`. That is what makes them interchangeable to Python and distinct to `mypy --strict`.
    The static answer is the real one, and it is a gate in `scripts/check`; this is the same
    answer at runtime, in the single function every path below flows through, so that "never
    conflated" is something the code does rather than something this docstring says.

    `InternalError`, because no user typed this: a caller mixed up two roots that `config/`
    handed it, and exit 70 sends the reader to the right codebase.
    """
    if not isinstance(home, AglHome):
        raise InternalError(
            f"home_layout was given a {type(home).__name__}, not an AglHome: AGL_HOME and the "
            f"trees root are different directories, and their layouts are never conflated"
        )
    return home.path


def _checked_project(project: ProjectName) -> str:
    """A project's name, with the headroom `<project>.toml` needs and `ids.py` cannot know about.

    `ids.py` caps a name at 255 bytes, which is NAME_MAX and exactly right for a name. This is
    the module that turns a name into a *filename*: `.toml` is five bytes longer, so a 255-byte
    project name yields a 260-byte filename and the write fails with ENAMETOOLONG at the one
    moment - first use of a new project - when the error is least explicable.

    Checked here and not by shrinking the cap in `ids.py`, because the suffix is this layout's
    and a `RunLabel` under the same cap has no such problem. Checked for every path under
    `projects/<project>/` and not only for the file itself, because a project whose settings
    file cannot exist is not a project this layout can hold, and one answer beats two.
    """
    name = str(project)
    length = len(name.encode("utf-8")) + len(_PROJECT_SUFFIX)
    if length > _MAX_SEGMENT_BYTES:
        raise InputError(
            f"project name {name!r} cannot be used: its settings file "
            f"{name + _PROJECT_SUFFIX!r} would be {length} bytes long, and a path segment may "
            f"not exceed {_MAX_SEGMENT_BYTES}"
        )
    return name


def _checked_digest(digest: str) -> str:
    """A step entry's filename stem - the one segment no validated type vouches for.

    The digest is ours, not the user's: the journal computes `sha256(...).hexdigest()` over a
    step's fingerprint, so `ids.py` never sees it and there is no `Digest` to construct. It is
    a path segment all the same, and this module's promise - that nothing it returns leaves the
    root it was given - has to hold for it too. The alphabet is what keeps that promise
    airtight: a name drawn from `0-9a-f` cannot be empty, cannot be `.` or `..`, cannot carry a
    separator, and cannot start with `-`. The length is checked with it, because a digest of
    the wrong length is not the thing the journal said it was writing. Lowercase only: on a
    case-insensitive volume two spellings of one digest are one file.

    `InternalError`, not `InputError` - a digest that is not a digest is our bug, and exit 70
    says so. If the journal ever writes something shorter, `_DIGEST_LENGTH` is where it says so.
    """
    if len(digest) != _DIGEST_LENGTH or not _DIGEST_CHARACTERS.issuperset(digest):
        raise InternalError(
            f"step digest {digest!r} is not a digest: expected {_DIGEST_LENGTH} characters of "
            f"lowercase hexadecimal, which is what sha256 hexdigests are, and what keeps a "
            f"framework-generated path segment inside the root it is joined onto"
        )
    return digest
