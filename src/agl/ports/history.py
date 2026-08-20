"""`History` - what changed, and is X already in Y.

Five questions about one repository's recorded past, and nothing that changes it. A run needs to
know where to start from and what that resolved to; a review step needs to know what an
implementation step actually did; `clear` needs to know whether a run's work is already contained
in the base ref before it deletes the name that work is under. Those are the whole of it.

**This is not a run log.** The name invites the confusion, so it is worth saying once and plainly:
nothing here reads or writes AGL's own records. Step entries are `Store`'s, the ledger over them is
`sdk/_engine/journal.py`'s, and what this port answers about is the target repository - which
existed before AGL ran and will be there afterwards, whether or not any of it was AGL's doing.

**Bound to one repository by construction**, which is why no method below takes one. The container
builds it against the project's repository and hands the same instance to everything; a repository
parameter would make every call site carry a value it has no way to get wrong, and would imply this
port can be asked about a second repository, which nothing in AGL ever does.

## What this port refuses

The previous implementation had a single 27-member port spanning inspection, refs, worktrees,
commits, diffs and merges (§1.3), and the merge half of it was one system's state machine written
out as method names. Splitting by consumer question (§3.4) put the isolated places in
`workspace.py`, the landing in `integration.py`, and the reading here. So there is no merge state
here, no conflict vocabulary, no half-finished operation to ask about or abort - `integration.py`
owns all of that, and an implementation that lands work by opening a change request rather than by
merging locally has nothing it must pretend to.

`ChangeKind` is the same refusal one level down: `FileStatus.code: str` used to carry one tool's
raw porcelain codes across this boundary, already recorded as a defect in the previous repository,
so every consumer of a changed file was reading a two-character status from a program's
human-facing output.

## Commit ids are opaque strings, and one thing is asked of them

They are produced by the same implementation that consumes them - a `Workspace.head()` goes into a
step's entry and comes back here as a `base` - and AGL never parses, abbreviates, orders or does
arithmetic on one. The single exception is `resolve`, whose result is pinned by `RunSpec.base_sha`
to a full unabbreviated form; see that method.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from agl.ports.errors import InternalError

__all__ = ["ChangeKind", "FileChange", "History"]


class ChangeKind(StrEnum):
    """What happened to one file between two states of the repository.

    Four members, and the values are explicit strings rather than `auto()` for `agent.py`'s reason:
    a `StrEnum`'s value is what it looks like when it is written down, and a step's stored result
    may well be a list of these, so declaration order must not be able to change a stored format.

    **There is deliberately no `UNMERGED` member.** A file with an unresolved conflict in it is not
    a kind of change - it is a state of an operation in flight, and that operation belongs to
    `integration.py`, which reports it as a `Conflict`. Admitting a fifth member here would put the
    merge state machine §1.3 spent 27 methods on back into a port that answers questions about the
    past, and would hand every consumer of `changed_files` a case it has no business handling.
    """

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class FileChange:
    """One file, and what happened to it.

    **The paths are `str` and not `Path`, deliberately.** A `Path` is a location on this machine,
    with an `exists()` on it and an operating system's separator inside it. These are names inside a
    repository, repository-relative and separated by forward slashes, and the repository being asked
    about may hold states that were never checked out here at all - a `changed_files` between two
    commits is answerable without a working tree. Handing back a `Path` would offer every caller a
    filesystem call that is meaningless for most of what this type describes, and would quietly
    rewrite the separator on a platform that spells it differently.

    That the separator is a forward slash is the adapter's promise and not a rule this type checks,
    because a repository path's own characters are barely constrained: a backslash is a perfectly
    ordinary character in a filename, so a type looking at one cannot tell a wrong separator from a
    strange name. What is checked below is only what would make a change unreadable.
    """

    path: str
    """Where the file is now, repository-relative - or where it was, when it was deleted."""

    kind: ChangeKind
    """What happened to it."""

    previous_path: str | None = None
    """Where it was before, for a rename, and `None` for everything else.

    Defaulted, because three of the four kinds have nothing to put here and should not have to say
    so. Paired with `kind` in both directions by `__post_init__`: a rename that cannot say what it
    was renamed from is not a rename anybody can act on, and a modification carrying a previous path
    means whoever built it filled in a field they had not thought about."""

    def __post_init__(self) -> None:
        # `InternalError` and not `InputError`, for `questions.py`'s reason: nobody types a
        # `FileChange`. An adapter built this out of what it read from the repository, so a
        # malformed one means our reading of that output is wrong, which is a bug in AGL.
        if not self.path:
            raise InternalError("a file change with an empty path names no file")
        if self.kind is ChangeKind.RENAMED:
            if not self.previous_path:
                raise InternalError(
                    f"the rename of {self.path!r} does not say what it was renamed from, and a "
                    f"rename with only one of its two names in it is a modification wearing the "
                    f"wrong label"
                )
            if self.previous_path == self.path:
                raise InternalError(
                    f"{self.path!r} is recorded as renamed to itself, which is not a change any "
                    f"reader can act on"
                )
        elif self.previous_path is not None:
            raise InternalError(
                f"{self.path!r} is {str(self.kind)!r} and also carries a previous path "
                f"{self.previous_path!r}; only a rename has one, and the two disagreeing means the "
                f"change was assembled wrong"
            )


class History(ABC):
    """Read the repository's past. Five methods, none of which changes anything.

    Every one of them raises from `errors.py` and nothing else - `NotFoundError` for a ref or a
    commit id that names nothing in this repository, `UpstreamUnavailable` when the repository
    itself cannot be reached - so a caller never learns what the thing underneath happened to throw.

    All five are async for one reason: an implementation may have to go out of process, or over a
    network, to answer. A synchronous signature would make every one of these a blocking call inside
    the event loop that is running several agents at once.
    """

    @abstractmethod
    async def default_ref(self) -> str:
        """Where a run starts from when the user names none (§3.9: `--from`, defaulting to this).

        It exists because nothing else in AGL can answer it. The configuration does not record it -
        a project's settings hold a repository, a trees root and a build command, none of which
        implies a starting point - and the command line has no view of the repository at all. The
        repository is the only thing that knows, so the port that reads the repository is what asks.

        A ref *expression* and not one of `ids.py`'s validated names, for `RunSpec.base_ref`'s
        reason: what comes back may well have a `/` in it, and every type in `ids.py` refuses one,
        being single path segments.
        """

    @abstractmethod
    async def resolve(self, ref: str) -> str:
        """A ref expression to the full, unabbreviated commit id it currently names.

        This is what pins `RunSpec.base_sha`, and it is the one place in either of these two ports
        where the shape of a commit id is constrained: `run.py`'s `_check_sha` refuses anything that
        is not forty characters of lowercase hexadecimal, or sixty-four. Read that docstring with
        this one - the two have to agree, and this is where the value it checks comes from. The
        reason is `_check_sha`'s: a shortened id is unique when it is printed and stops being unique
        as the repository grows, so an abbreviated pin comes loose exactly when a project gets big
        enough for the pin to matter.

        The cost is worth stating, because it is the one demand these ports make of a second
        implementation that is not purely structural: whatever identifies a state of the repository
        has to be spellable as a hexadecimal string of one of those two lengths. An implementation
        built on content hashes has that already; one built on ascending revision numbers does not,
        and would have to hash rather than count.

        `NotFoundError` when the ref names nothing - `errors.py` lists exactly this case - because
        the user typed something well-formed that this repository does not have.
        """

    @abstractmethod
    async def contains(self, ancestor: str, descendant: str) -> bool:
        """Is `ancestor` already part of what `descendant` records? Is X already in Y.

        The one ancestry question AGL asks, and it is asked in one place: `clear` deletes a run's
        own line of work only if it is already contained in the base ref, and otherwise keeps it
        and says so (§3.10). The costs are asymmetric - a retained name is a stale ref, a deleted
        one is the entire run - so the answer decides between "tidy up" and "leave it alone".

        Nothing more than that. No common-ancestor lookup, no divergence count, no "how far ahead":
        those are the vocabulary §1.3 caught this boundary speaking, each of them a method that
        exists because one tool has a command for it rather than because anything here asks. A
        `bool` is the whole of what the one consumer needs, and a `bool` is answerable by any
        implementation that can say whether one state is reachable from another.
        """

    @abstractmethod
    async def changed_files(self, base: str, head: str) -> tuple[FileChange, ...]:
        """Which files differ between two states, and how - the structured half of "what changed".

        A tuple, so the answer is a value that can be held, compared and put in a step's result
        without a caller having to defend against it changing underneath them. Its order is the
        implementation's, and nothing here promises one: consumers filter and count, and a port that
        promised an ordering would be promising one tool's sort.

        Directional, `base` to `head`, and the direction is what makes `ADDED` and `DELETED` mean
        anything. Swapping the arguments gives the inverse answer rather than an error.
        """

    @abstractmethod
    async def diff(self, base: str, head: str) -> str:
        """The same change as text a person or a model reads. A unified patch.

        The plain `str` is the design here, and it is §3.7's argument for the activity string made
        again. A unified patch is the one interchange format every code-review consumer already
        reads and every model has seen an enormous amount of; handing it over untouched costs
        nothing and loses nothing. Structuring it - hunks, lines, per-line kinds - would mean this
        port inventing a taxonomy no consumer asked for, which every implementation would then have
        to render its own output into, in order to be reassembled into roughly this string by the
        reviewer at the other end.

        Paired with `changed_files` rather than replaced by it: one is for deciding, the other is
        for reading. A review step puts this in a prompt; a workflow that wants to know whether a
        step touched anything under `docs/` uses the other and does not parse this.
        """
