"""The names, the files and the one commit helper both of these suites build a repository out of.

A contract suite has one knob per implementation and builds everything else itself (`store.py` says
why at more length), so every name and every file below is this suite's own. An implementer supplies
a provider, a base to cut from, and - for `history.py` - a `History` over the same repository. No
label, no namespace, no file and no commit, so there is no way to point either suite at the state an
implementation happens to be good at.

**This module reaches into `Workspace.path`, and that is the port's own invitation rather than a
backdoor.** The store suite refuses `Path` outright because `Store` never speaks one. This port
does, deliberately: `path` is a `Path` because "a workspace genuinely is a directory: an agent is
pointed at one and a verifier's working directory is one". Making a workspace dirty is the whole of
what a step does to one, and writing a file into that directory is the only vocabulary either port
offers for it. Everything past that is still refused - nothing here starts a subprocess, names a
tool, parses anything a program printed, or learns what a line of work is made of.

**`history.py` builds its past through a `Workspace` for the same reason.** `History` answers
questions about states of the repository and has no member that makes one; `commit_all` is the only
way, across both ports, to add to a repository's recorded past. That is not a liberty this module
takes: `Workspace.head` says the value it answers with "is also the vocabulary `History` accepts",
because one adapter package implements both ports over one repository.

**Everything is written under one directory of this suite's own.** A fixture may hand over a
repository that already holds files - it is somebody's project - and a test asserting that a file
was *added* would be wrong about one that was already there. `assert_absent` is the guard, and it
fails as a fixture problem, in those words, rather than as an implementation one.
"""

from pathlib import Path
from typing import Final

from agl.ports.ids import Namespace, RunLabel
from agl.ports.workspace import Workspace

# One run, two children of it, and the run's own place addressed by `None`: enough to ask whether
# two lines of work are two places, and whether the run's own is a third address or one of them.
LABEL: Final = RunLabel("contract")
CHILD: Final = Namespace("T-01")
SIBLING: Final = Namespace("T-02")

# One directory, and a name nobody's repository holds by accident. See the module docstring.
_UNDER: Final = "agl-contract"

TRACKED: Final = f"{_UNDER}/tracked.txt"
ALPHA: Final = f"{_UNDER}/alpha.txt"
BETA: Final = f"{_UNDER}/beta.txt"
GAMMA: Final = f"{_UNDER}/gamma.txt"
NESTED: Final = f"{_UNDER}/nested/deep.txt"
MOVED_FROM: Final = f"{_UNDER}/moved/original.txt"
MOVED_TO: Final = f"{_UNDER}/moved/renamed.txt"

# The two shapes of leaving `restore` exists for, and they are different shapes on purpose: a file
# beside tracked ones, and a file inside a directory that was not there either. An implementation
# that deletes untracked files without descending into new directories passes on the first and
# fails on the second, which is the whole difference between one tool's `clean -f` and `clean -fd`.
SCRATCH: Final = f"{_UNDER}/scratch.txt"
CACHE_DIR: Final = f"{_UNDER}/cache"
CACHED: Final = f"{CACHE_DIR}/notes.txt"

# How many lines a file this suite writes has. Long, because rename detection is a similarity
# heuristic wherever it exists at all, and a three-line file moved unchanged is a file any
# heuristic is entitled to be unsure about - see `_history_changes` on what is asked of one.
_LINES: Final = 24

# A commit message in the vocabulary a workflow author actually writes, carrying every character an
# implementation that builds a command line by pasting strings together comes apart on. §3.3
# narrowed the charset of a *name* for exactly this hazard and deliberately left messages alone: a
# message is prose, and prose is where the metacharacters live.
AWKWARD_MESSAGE: Final = (
    'implement T-01: "auth" & $(whoami) | tee /dev/null; done\n'
    "\n"
    "Closes the ticket and touches nothing else. Café 日本語."
)

_MESSAGE_PREFIX: Final = "record"


def body(marker: str) -> str:
    """A file's contents, derived from `marker` so that two files differ on every line.

    Differing everywhere rather than in one line is what makes a stale read visible: a workspace
    that handed back the wrong state, or an implementation that restored a file to the wrong
    version, shows up as an inequality rather than as a subtle one.
    """
    lines = [
        f"{marker}: line {index} of {_LINES}, and nothing else is on it."
        for index in range(_LINES)
    ]
    return "\n".join(lines) + "\n"


def _at(workspace: Workspace, name: str) -> Path:
    """Where `name` is inside `workspace`.

    `name` is repository-relative and forward-slash separated, which is what `FileChange.path` is
    and so the one spelling both suites can use for a file and for what `History` calls it. It is
    split rather than pasted on, because a `str` holding `/` is a path only on the platforms that
    spell it that way.
    """
    return workspace.path.joinpath(*name.split("/"))


def write(workspace: Workspace, name: str, text: str) -> None:
    """Put `text` at `name`, making whatever directories it needs on the way."""
    path = _at(workspace, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read(workspace: Workspace, name: str) -> str | None:
    """What is at `name`, or `None` if nothing is - which is what "it was removed" looks like."""
    path = _at(workspace, name)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def is_directory(workspace: Workspace, name: str) -> bool:
    """Whether `name` is a directory in this workspace. Only `restore` asks, and it asks once."""
    return _at(workspace, name).is_dir()


def delete(workspace: Workspace, name: str) -> None:
    """Remove `name`, which is how a `DELETED` change gets made."""
    _at(workspace, name).unlink()


def rename(workspace: Workspace, old: str, new: str) -> None:
    """Move `old` to `new` with its contents untouched, which is how a rename gets made.

    Byte-for-byte identical on purpose: a rename that also edits the file is a rename every
    similarity heuristic is allowed to report as a deletion and an addition, and `_history_changes`
    has enough to argue about without adding a threshold nobody specified.
    """
    source, target = _at(workspace, old), _at(workspace, new)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)


def assert_absent(workspace: Workspace, *names: str) -> None:
    """Refuse to build on a file the fixture's repository already holds.

    A test asserting that a file was *added* between two states is wrong about a file that was
    already there when the workspace was cut, and the failure would read as the implementation's.
    This one names the fixture instead.
    """
    held = [name for name in names if read(workspace, name) is not None]
    assert not held, (
        f"the repository this fixture handed over already holds {held}, and this suite is about "
        f"to add those files and assert that they were added. Point the suite at a repository "
        f"that does not carry a directory named {_UNDER!r}"
    )


async def record(workspace: Workspace, marker: str) -> str:
    """`commit_all` under a message naming `marker`, and hand back the head it answers with.

    A helper because every test that needs a state to ask `History` about needs this line, and
    because the message is the one argument almost no test here has an opinion about. The one that
    does passes `AWKWARD_MESSAGE` itself, and says there what it is asking.
    """
    return await workspace.commit_all(f"{_MESSAGE_PREFIX} {marker}")
