"""The repository the three fakes share: recorded states, lines of work, checkouts and holds.

`fake.py` implements three ports and this module is the thing all three of them are over. The real
adapters are each handed a `Path` and each build their own `GitRunner` from it, which works because
the repository underneath is one shared, durable object that git reaches through the filesystem.
The fake has no such object to be handed, so it is given one: this class is the fake's repository,
and the container constructs it once and hands the same instance to the provider, the history and
the integrator exactly as it hands one path to the three real ones.

The seam this module draws is the one 5.2 drew between `workspace.py` and `_trees.py`, and 5.3
between `history.py` and `_changes.py`: **nothing here touches the filesystem and nothing here
imports a port ABC.** What is in here is what a repository *is* - states addressed by their
contents, names pointing at states, which checkout has which name open, and which checkout is
holding a landing. What a step does to a workspace, and what a workspace is on disk, is
`fake.py`'s and `_working.py`'s.

## States are addressed by their contents, which is what makes an id an id

`HistoryContract` constrains exactly one shape and says why: `resolve` must answer forty or
sixty-four characters of lowercase hexadecimal, because `RunSpec._check_sha` refuses an
abbreviation - and it says in as many words that an implementation built on content hashes has
that already and one built on ascending revision numbers must hash rather than count. So a state's
id is the sha256 of its contents, its parents and its message, which is sixty-four characters of
lowercase hexadecimal by construction and needs no rule of its own.

One consequence is worth stating rather than discovering, and `test_git_parity.py` pins it: two
commits of the same contents, from the same parent, under the same message are **one state** here
and are two in git, whose commit object carries a timestamp. That is not the fake being permissive
- it records the same tree either way - and it is the honest behaviour for a store that addresses
by content. It is the last item on that file's closed list of divergences.

## The hold lives here, not on the integrator, and §3.4 is why

§3.4 requires that a conflicted landing's hold be durable rather than in-memory, because a run that
dies holding a target can only be released by a later invocation. For a fake whose entire
repository is in the process, the failure that requirement names cannot happen: a later invocation
gets a new `FakeRepository` with no states, no branches and no target, so there is nothing
half-combined left for an `abort` to be a silent no-op about. What *does* carry over is the
structural half, and it is honoured here rather than assumed away - the hold is a fact about the
repository and not about whichever `FakeIntegrator` happened to take it, so a second integrator
built over the same repository sees a hold the first one took, which is exactly the property the
real adapter has and states as its deliverable.

## No lock

`_trees.registry_lock` is §3.9's cross-process `flock` on git's worktree registry. This registry is
a dict in one process's memory, and a second process gets a different `FakeRepository` with nothing
to contend over, so a lock here would serialise nothing and would only make the fake pretend to a
guarantee it cannot offer. `fake.py` says the same thing where it does not take one.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from agl.ports.errors import NotFoundError

__all__ = ["FakeRepository", "Hold", "Tree"]


# One recorded state's contents: repository-relative, forward-slash separated names to bytes. The
# same spelling `FileChange.path` promises, so nothing between here and the port has to translate.
type Tree = Mapping[str, bytes]

# What a branch is called when it is spelled in full. Composing this is not composing a *name* -
# `tree_layout` hands names over whole - it is qualifying one, so that `refs/heads/main` and `main`
# name the same line of work, which is what `rev-parse` does in the repository the real one reads.
_BRANCH_REF: Final = "refs/heads/"

# The message on the state a fresh repository starts at. It is never read back - no port has a
# member for a message - and exists so that a repository has a state before anything records one.
_INITIAL: Final = "the state this repository starts at"

# Surrogates survive the encode rather than raising. A message is the workflow author's own prose
# and reaches here uninspected; a lone surrogate in one would otherwise leave this module by way of
# a `UnicodeEncodeError`, which is not an `AglError` and is not something a caller can act on.
_ENCODING: Final = "utf-8"
_SURROGATES: Final = "surrogatepass"


@dataclass(frozen=True, slots=True)
class _State:
    """One recorded state: what was in the tree, what it came from, and what it was called."""

    tree: Tree
    parents: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class Hold:
    """A landing left pending in one checkout, and everything needed to end it either way.

    The in-memory counterpart of the `MERGE_HEAD` a conflicted `git merge` leaves in a worktree's
    own git directory, and it carries more than that file does for one reason: git keeps the rest
    of what it knows in the index, and there is no index here. So the merged content for the paths
    that combined, the paths that did not, and the working-tree names the attempt wrote are all
    recorded at the moment the landing stopped - which is what lets `retry` conclude and `abort`
    put the checkout back without either of them re-deriving anything.
    """

    source: str
    """The state being landed - the second parent, if the landing is ever concluded."""

    target: str
    """Where the target stood before the landing, and where `abort` puts it back to."""

    combined: Tree
    """What the paths that *did* combine came to, which is the whole tree bar the collisions."""

    collisions: tuple[str, ...]
    """The paths that would not combine, in the order a `Conflict` reports them."""

    message: str
    """What the landing will be called if it is ever concluded, written when it stopped.

    git writes its own merge message the moment a merge halts and `--no-edit` is what accepts it
    later; there is nothing to accept here, so the sentence is composed once, at the same moment,
    and kept - which is also what saves `retry` from having to be re-supplied a source it is
    deliberately not given.
    """

    touched: frozenset[str]
    """Every working-tree name the attempt wrote or removed, and so every one `abort` restores.

    Everything else in the checkout is left exactly as it stood, which is `abort`'s own clause:
    "as it was before `land`" is not "as if nothing had ever happened", and a person's scratch
    file is theirs.
    """


class FakeRepository:
    """One repository, held in memory: states, branches, checkouts, and pending landings.

    Constructed by `config/container.py` for the all-fakes bundle and handed to all three fakes,
    which is the substitution for the one repository path the three real adapters are each handed.
    Two of these share nothing, which is the honest analogue of two directories on disk.

    `files` seeds the state a fresh repository starts at, so that an all-fakes run has something to
    cut a workspace from and something for a workflow to read; `default_branch` is what
    `History.default_ref` answers about, since a fake has no `HEAD` on disk to ask.

    Everything below the constructor is this package's own vocabulary rather than a public surface:
    nothing outside `agl/adapters/git/` names any of it, exactly as nothing outside names
    `GitRunner`.
    """

    def __init__(
        self, files: Mapping[str, bytes] | None = None, default_branch: str = "main"
    ) -> None:
        self._states: dict[str, _State] = {}
        self._branches: dict[str, str] = {}
        self._checkouts: dict[Path, str] = {}
        self._holds: dict[Path, Hold] = {}
        self._depths: dict[str, int] = {}
        self._default = default_branch
        self._branches[default_branch] = self.record(dict(files or {}), (), _INITIAL)

    # -- states ----------------------------------------------------------------------------------

    @property
    def default_ref(self) -> str:
        """The full ref this repository's default branch is spelled by - `History.default_ref`.

        In full, `refs/heads/main` rather than `main`, because that is what the real adapter
        answers and for the reason it gives: a shortened branch name is ambiguous where a full ref
        is not, and the two members have to agree about which thing was meant.
        """
        return f"{_BRANCH_REF}{self._default}"

    def record(self, tree: Mapping[str, bytes], parents: tuple[str, ...], message: str) -> str:
        """Keep this state and answer with its id. Recording one twice is recording it once.

        The id is the sha256 of the contents, the parents and the message, so the same state under
        the same message from the same parent is the same id - see the module docstring, which
        argues that and names where the difference from git is pinned.
        """
        held = MappingProxyType(dict(tree))
        identity = _identity(held, parents, message)
        self._states.setdefault(identity, _State(held, parents, message))
        return identity

    def resolve(self, ref: str) -> str:
        """A ref expression or a recorded id to the id it names. `NotFoundError` when it names none.

        Ids first, then the branch by either spelling, which is the order that makes a value that
        came out of `head()` answerable without the caller having to say which kind it is - the
        port takes both, "because a run's own place is cut from the pinned `RunSpec.base_sha` while
        a child is cut from the run's branch by name".
        """
        if ref in self._states:
            return ref
        short = ref[len(_BRANCH_REF) :] if ref.startswith(_BRANCH_REF) else ref
        tip = self._branches.get(short)
        if tip is None:
            raise NotFoundError(
                f"{ref!r} names no state in this repository. It is well-formed, so either nothing "
                f"has recorded it yet or it is spelled differently here"
            )
        return tip

    def tree_of(self, state: str) -> Tree:
        """What was in the tree at this recorded state. The id has already been resolved."""
        return self._states[state].tree

    def contains(self, ancestor: str, descendant: str) -> bool:
        """Is `ancestor` already part of what `descendant` records? Reflexive, and §3.10 is why.

        A run whose workflow committed nothing sits exactly at its base, with nothing to lose and
        nothing to keep, and `clear` has to tidy it - which happens only if a state is already
        inside itself. That is the port's argument and it binds here whatever any tool does.
        """
        return ancestor in self._reachable(descendant)

    def merge_base(self, left: str, right: str) -> str | None:
        """The state both of these descend from, or `None` when they share none.

        The deepest common ancestor, measured as the longest path back to a root. That is always a
        *best* common ancestor and not merely a common one: if X is a proper ancestor of Y then
        every path to X extends to Y, so Y is deeper - which means the deepest one can never be an
        ancestor of another candidate. Ties are broken by id, so two lines of work that cross over
        get one answer rather than an arbitrary one, and the same answer every time.
        """
        common = self._reachable(left) & self._reachable(right)
        if not common:
            return None
        return max(common, key=lambda state: (self._depth(state), state))

    # -- lines of work ---------------------------------------------------------------------------

    def tip(self, branch: str) -> str | None:
        """Where this line of work currently is, or `None` if there is no such name."""
        return self._branches.get(branch)

    def move(self, branch: str, state: str) -> None:
        """Put this line of work at this state - what a commit and a restore both do to one."""
        self._branches[branch] = state

    def drop(self, branch: str) -> None:
        """Delete the name. Tolerant of absence, because `clear` after a crash is the ordinary
        case."""
        self._branches.pop(branch, None)

    # -- checkouts -------------------------------------------------------------------------------

    def checked_out_at(self, path: Path) -> str | None:
        """Which line of work this place has open, or `None` if nothing is registered there."""
        return self._checkouts.get(path.resolve())

    def checkout_of(self, branch: str) -> Path | None:
        """Where this line of work is checked out, or `None` if nowhere. Pruned first.

        Asked before provisioning and before deleting a name, because a line of work may not be
        open in two places at once and a name something still holds is not one to delete - both of
        which are refusals git states and this one has to state the same way.
        """
        self.prune()
        for path, held in self._checkouts.items():
            if held == branch:
                return path
        return None

    def attach(self, path: Path, branch: str, state: str) -> None:
        """Register this place as holding this line of work, and put that line at this state."""
        self._checkouts[path.resolve()] = branch
        self._branches.setdefault(branch, state)

    def detach(self, path: Path) -> None:
        """Take the registration back, and with it any landing this place was holding.

        Both halves together because git's are together: a pruned worktree takes its own git
        directory with it, and `MERGE_HEAD` was in there.
        """
        at = path.resolve()
        self._checkouts.pop(at, None)
        self._holds.pop(at, None)

    def prune(self) -> None:
        """Forget every registration whose directory has gone - `worktree prune`, and its reason.

        A crash between provisioning a place and anything else leaves a registration standing over
        nothing, and the next provisioning is refused until it is cleared.
        """
        for path in [path for path in self._checkouts if not path.is_dir()]:
            self.detach(path)

    # -- pending landings ------------------------------------------------------------------------

    def held(self, path: Path) -> Hold | None:
        """The landing pending in this checkout, or `None`. The one predicate the integrator asks.

        Per checkout, because `MERGE_HEAD` is per worktree: a landing held in one run's `_base` is
        invisible to every other run, which is the isolation §3.9 is built on.
        """
        return self._holds.get(path.resolve())

    def hold(self, path: Path, pending: Hold) -> None:
        """Leave this checkout mid-landing, owing a `retry` or an `abort`."""
        self._holds[path.resolve()] = pending

    def release(self, path: Path) -> None:
        """End the landing this checkout was holding. Tolerant of there being none."""
        self._holds.pop(path.resolve(), None)

    # -- ancestry --------------------------------------------------------------------------------

    def _reachable(self, state: str) -> frozenset[str]:
        """Every state reachable from this one, itself included."""
        seen = {state}
        pending = [state]
        while pending:
            for parent in self._states[pending.pop()].parents:
                if parent not in seen:
                    seen.add(parent)
                    pending.append(parent)
        return frozenset(seen)

    def _depth(self, state: str) -> int:
        """The longest path from this state back to a root, memoised because states never change.

        Iterative rather than recursive: a run of any length is a chain, and a chain is exactly the
        shape that turns a recursive walk into a stack overflow.
        """
        known = self._depths
        pending = [state]
        while pending:
            at = pending[-1]
            if at in known:
                pending.pop()
                continue
            parents = self._states[at].parents
            missing = [parent for parent in parents if parent not in known]
            if missing:
                pending.extend(missing)
                continue
            known[at] = 1 + max((known[parent] for parent in parents), default=-1)
            pending.pop()
        return known[state]


def _identity(tree: Tree, parents: tuple[str, ...], message: str) -> str:
    """The sha256 that names this state - sixty-four characters of lowercase hexadecimal.

    Every part is written with its own length in front of it, so that no two different states can
    serialise to one string by running their fields together: a path and the bytes that follow it
    are told apart by a count rather than by a separator no name may hold, which a repository path
    would eventually hold.
    """
    digest = hashlib.sha256()
    for parent in parents:
        digest.update(f"parent {parent}\n".encode())
    for path in sorted(tree):
        content = tree[path]
        name = path.encode(_ENCODING, _SURROGATES)
        digest.update(f"file {len(name)} {len(content)}\n".encode())
        digest.update(name)
        digest.update(content)
    said = message.encode(_ENCODING, _SURROGATES)
    digest.update(f"message {len(said)}\n".encode())
    digest.update(said)
    return digest.hexdigest()
