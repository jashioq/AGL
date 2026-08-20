"""`WorkspaceProvider` and `Workspace` - give me an isolated place to work from this base; take it
back.

An isolated place is one checkout of the target repository that one step has to itself. Work done
in it is invisible to every other checkout until somebody lands it - which is `integration.py`'s
job, not this port's - so two agents editing the same file at the same time is an ordinary
afternoon rather than a race, and a step that leaves a scratch file behind cannot contaminate the
next one. `tree_layout.py` already says where those places go and what the lines of work they
carry are called; this port is what makes and unmakes them.

## The provider is addressed by name, never by a path the caller computed

Plan §1.10's charge against the previous implementation was one line of it:
`paths.run_dir(home, label)` computed a filesystem path and handed it to the `Store` port, so a
helper shaped like a filesystem - not the port, and not the adapter behind it - decided where that
port kept its things. A port that accepts a location has already been told how it is implemented,
and the only implementation it can afterwards have is the one that helper was written for.

Every method on `WorkspaceProvider` therefore takes a `RunLabel` and a `Namespace`, both validated
by `ids.py` and both opaque, and derives its own layout from them. A provider is built by the
container with whatever root or endpoint it needs, exactly as an `AgentRunner` is built with
whatever its backend needs, and is addressed after that only by name.

The asymmetry with `Workspace` is the deliberate half of this, not an oversight. A workspace
**exposes** a `Path` because a workspace genuinely is a directory: an agent is pointed at one
(`AgentTask.workspace`) and a verifier's working directory is one. What a provider must never do is
**accept** one.

## The test every member below was written against

Could a second, structurally different implementation satisfy this honestly? Not "could it be made
to compile" - could it implement this without ignoring a parameter and without raising on something
the shape here implies it supports. Two are worth holding each member against: a snapshot or
overlay filesystem, where a line of work is a chain of snapshots and an isolated place is a mount;
and a service that hands out isolated checkouts on request. Both have to be able to answer
everything below, and neither may be forced to invent a value it does not have.

That is why a commit id and a branch name are plain, opaque `str` on both sides here. The framework
composes branch names in `tree_layout` and never parses one back; it stores commit ids and hands
them back to the same implementation that produced them, and it never abbreviates, compares
lexically or does arithmetic on one. Any implementation whose lines of work have names and whose
states have identities can satisfy that; a more structured type would be this port picking one of
them.

## What is deliberately not here

**No remote of any kind** - no push, no fetch, no credentials. AGL lands local branches and the
user pushes what they want, when they want (§3.9), so a remote here would be a concept the
framework would then have to have an opinion about, in return for nothing v1.1 does.

**No enumeration.** Nothing asks a provider what it holds; the framework derives a run's namespaces
from its own records. The accepted cost is a leak: a crash between provisioning a place and
recording anything under it leaves behind a directory and a line of work that nothing will ever
name again. That is the same trade §3.10 makes for the run branch itself - a retained ref is cheap
and a deleted run is not - and an enumeration method would buy tidiness by requiring that every
implementation be able to list, which a service handing out checkouts to many clients may not
honestly be able to do.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from agl.ports.ids import Namespace, RunLabel

__all__ = ["Workspace", "WorkspaceProvider"]


class WorkspaceProvider(ABC):
    """Make an isolated place, take it back, and delete the line of work it carried.

    Three methods, and the two teardown verbs are separate because `clear` needs them apart (§3.10).
    `clear` takes back every isolated place a run holds unconditionally, deletes the child lines of
    work unconditionally, and deletes the run's own line of work *only if* it is already contained
    in the base ref. That last condition is a question about ancestry, which is `History.contains`'s
    to answer and not this port's - so this port must offer the two halves and hold no policy about
    when either is right.
    """

    @abstractmethod
    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        """Provision an isolated place for these identifiers, or hand back the one already there.

        **Idempotent, and that idempotence is what makes replay work.** A resume walks the same
        workflow again and asks for the same workspaces; if the second ask were an error, every
        step would need an existence check in front of it, and the check and the provisioning would
        race with the run's own concurrency. An existing workspace is returned exactly as it stands,
        with whatever the previous attempt left in it - §3.6's replay is what then decides whether
        to keep that state or `restore` past it.

        **`base` is consulted only when provisioning.** On reopen it is ignored, and that is said
        here plainly rather than left as a parameter that looks honoured and is not. Checking it
        instead would be the dishonest option: a child's base is the run's own line of work, which
        advances with every integration, so a workspace cut an hour ago was correctly cut from an
        earlier state of the very ref being passed now, and a comparison would refuse healthy
        replays. It is a ref expression or a resolved commit id - both, because the run's own place
        is cut from the pinned `RunSpec.base_sha` while a child is cut from the run's branch by
        name, and forcing one form would make one of those two callers resolve on the port's behalf.

        **`namespace=None` means the run's own workspace**, the `_base` of §3.9, and `None` is the
        only way to name it. That is not an arbitrary encoding: §3.3's layout reserves that name,
        and `tree_layout` refuses any `Namespace` that collides with it, so there is deliberately no
        `Namespace` value that could be passed instead. It has no default, for `AgentOutcome`'s
        reason - which of the two workspaces a caller means is a thing to state, not to fall into.

        Raises `ConflictError` if a line of work under this name already exists and is not this
        workspace's: §3.10 has `run` refuse an existing label rather than adopt it, because
        adopting it is how a typo'd label silently continues somebody else's work.
        """

    @abstractmethod
    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Take the isolated place back. The line of work it carried survives.

        This is the half `clear` runs unconditionally, and the half that runs before `discard`: an
        implementation is within its rights to refuse to delete a line of work that something still
        has open, and calling these in this order means no caller has to know whether it does.

        **Tolerant of absence.** Removing what is not there succeeds and says nothing. `clear` after
        a crash is the ordinary case, not the exceptional one, and a teardown that raises on a
        half-finished setup is a teardown people learn to wrap in a bare `except`.
        """

    @abstractmethod
    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Delete the line of work itself - the branch, the snapshot chain, whatever it is there.

        Destructive in the way `remove` is not: `remove` gives back a checkout that can be cut
        again from a name that still exists, and this deletes the name. `clear` calls it
        unconditionally for a run's children, whose work has already been landed into the run's own
        line or deliberately abandoned, and for the run's own line only once `History` has confirmed
        it is contained in the base ref (§3.10). Call `remove` first.

        **Tolerant of absence**, for `remove`'s reason and in the same words.
        """


class Workspace(ABC):
    """One isolated checkout, already provisioned: where it is, what it is called, and the three
    things a step does to it.

    **Deliberately not a context manager.** Exiting a `with` block would take the workspace back at
    exactly the moment its contents are most wanted: §3.3 keeps a failed run's checkout on disk so
    a person can go and look at what the agent actually did, and a run that ends badly is the run
    whose workspace matters. Teardown is `WorkspaceProvider.remove`, called by `clear`, when a
    person has decided they are finished with it.

    **No `is_dirty`.** Nothing in the plan asks. `commit_all` is a no-op when nothing is dirty and
    `restore` does not care what it is throwing away, so between them every use is covered - and a
    predicate would be an invitation to write the branch the framework has already decided not to
    have (§3.3: it does not inspect whether HEAD moved).
    """

    @property
    @abstractmethod
    def path(self) -> Path:
        """The directory to work in - what an `AgentTask` and a `Verifier` are pointed at.

        Absolute, because that is what `AgentTask.workspace` requires and for its reason: a relative
        path resolves against whatever directory a subprocess happens to start in.

        A property and not a call, because it is settled at provisioning and does not change while
        the workspace is open; a `Path`, and so a local one, which is the one place this port
        assumes anything about where the work happens - see this module's docstring.
        """

    @property
    @abstractmethod
    def branch(self) -> str:
        """The name this line of work is published under - `tree_layout`'s composition of it.

        **Opaque.** This port neither parses it nor imposes a format on it. The framework composed
        it (`tree_layout.run_branch`, `tree_layout.worktree_branch`) and reads it back only to
        record it and to print it, and a workspace reports the name it actually carries rather than
        the name today's scheme would compute for it - which is `RunSpec.branch`'s argument for
        storing a derivable value, applied one layer down. A run provisioned under one naming scheme
        keeps its name when the scheme changes.
        """

    @abstractmethod
    async def head(self) -> str:
        """The commit id this workspace is currently at.

        The value §3.6 records in a step's entry, and the value a later step hands back to
        `restore`. It is also the vocabulary `History` accepts: `changed_files` and `contains` are
        asked about ids that came from here, which is honest because one adapter package implements
        both ports over one repository.

        Async, unlike the two properties above, because it is a question about the world rather than
        about this object: it changes under `commit_all`, under `restore`, and under an agent that
        commits during its own run. An implementation has to go and look.
        """

    @abstractmethod
    async def commit_all(self, message: str) -> str:
        """Record everything dirty under `message`, and return the resulting head.

        **A no-op when nothing is dirty**, returning the unchanged head. §3.6 says exactly this, and
        it is what lets the framework do one predictable thing at the end of every effect step
        without inspecting whether anything moved or checking what the role declared (§3.3). A step
        whose agent changed nothing is not an error and is not a special case; it records the head
        it started from and replay carries on.

        Everything dirty, with no path argument and no staging step: the workspace is the unit of
        isolation, so "what this step did" is "what is in here", and a framework that chose a subset
        would be choosing on behalf of an agent whose file writes it deliberately does not track.

        `message` is the workflow author's own domain vocabulary - "implement T-01" - and is outside
        the step's fingerprint (§3.6), so editing it and replaying leaves the existing record alone.
        """

    @abstractmethod
    async def restore(self, head: str) -> None:
        """Put the working tree back at `head` **and remove everything that was not in it**.

        One method doing both halves on purpose, and named so that nobody goes looking for the
        missing "clean". §3.3 is explicit that moving the head alone is not enough, because
        untracked files survive it - and untracked leavings are the exact case this exists for: a
        reviewer's scratch file, an agent's cache directory, a half-written patch. Two methods would
        make "restored but not cleaned" a state a caller could reach by forgetting one line, and the
        one place in AGL where a mistake destroys work rather than costing a re-run is close enough
        already.

        It is also the more portable shape. A snapshot-based implementation restores a snapshot,
        which is one operation that is already both halves; splitting it here would make that
        implementation model two steps of somebody else's tool in order to satisfy a port.

        §3.6 and §3.3 use this same primitive at two moments: before re-running a step whose entry
        is missing, to discard a crashed attempt's leavings, and on the way out of a step that
        passed no `commit=`, so that a read-only step is genuinely read-only. One operation, used
        consistently, and it does not care what it is throwing away.
        """
