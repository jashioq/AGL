"""The three git ports with no git behind them: `WorkspaceProvider`, `History` and `Integrator`,
over one in-memory repository.

**This is a product feature and not a test double** (§1.9). It is what `--dry-run` runs on and what
plan target #8 rests on - *every command runs end-to-end on fakes alone, no network, no git* - so
the rule `memory_store.py` states for its port is the rule here: **wherever the port is silent,
these three agree with the real adapters.** A fake more permissive than the real thing lets a
workflow pass on fakes and fail in anger, with the difference invisible until the day somebody
drops the `--dry-run`. `tests/contracts/` holds both to everything the ports *say*;
`tests/adapters/test_git_parity.py` holds them to each other, and closes the list of the places
they deliberately differ.

Nothing below starts a process, and the only files it opens are the ones a checkout is made of -
`ports/workspace.py` promises that "a workspace genuinely is a directory: an agent is pointed at
one and a verifier's working directory is one", which is the one thing about the world a fake
cannot hold in a dict. Everything else - the recorded states, the lines of work, which checkout
holds which, and a landing left pending - is `_snapshots.py`'s, and the merge that decides whether
work goes in is `_merging.py`'s.

## Conflict detection is a real three-way merge, and that is the point of this deliverable

A fake that never conflicts makes a merge train look clean that git will reject; a fake that
conflicts on any two changes to one file makes a workflow's conflict screen fire on work that
would have combined. `_merging.py` argues the whole of it and is where the algorithm lives: two
children that touched different files combine, two that wrote incompatible content to one file
collide, and two that edited opposite ends of one file combine - which is the distinction only a
common ancestor can draw, and the distinction that makes this worth trusting.

## Construction, and where it differs from the real adapters

    GitWorkspaceProvider(repository, trees)      FakeWorkspaceProvider(repository, trees)
    GitHistory(repository)                       FakeHistory(repository)
    GitIntegrator(repository)                    FakeIntegrator(repository)

The same three shapes, so that `config/container.py` chooses between them and does not rewrite
around them. The one difference is what `repository` is: the real three are each handed a `Path`
and each build their own `GitRunner` from it, which works because the repository underneath is one
shared object reached through the filesystem. There is no such object for a fake to be handed, so
the container builds one - `FakeRepository()` - and hands the same instance to all three, exactly
as it hands one path to the other three. Stage 9 is where that lands; it is the only difference.

## No lock, and §3.9 is why there is none rather than why there is

`_trees.registry_lock` is a cross-process `flock` on git's worktree registry, taken around
`worktree add` and `prune` because two `agl` invocations are two processes sharing one `.git/`.
The registry here is a dict inside one `FakeRepository`; a second process gets a different one,
with nothing to contend over and no way to see what this one is doing. A lock would serialise
nothing and would let the fake pretend to a guarantee it cannot offer.

## The durable hold, decided rather than defaulted

§3.4 requires a conflicted landing's hold to be durable and readable from the repository, "an
in-memory hold makes a resumed run's `abort()` a silent no-op and leaves the target
half-combined forever" - and adds that a contract suite cannot catch this, which 5.4 confirmed by
passing the whole suite with one. The requirement is about a target that outlives the process. A
`FakeRepository` does not: when the process ends, the states, the lines of work and the pending
landing end with it, and a later invocation starts from a repository in which no target has ever
been landed into. The failure that clause names is unreachable here, because there is nothing left
to be half-combined.

What does carry over is the structural half, and it is honoured rather than assumed away: **the
hold is a fact about the repository and never about a `FakeIntegrator`.** Two integrators built
over one `FakeRepository` are one integrator, and the second sees a hold the first took - which
is the real adapter's own deliverable, in the strongest form a single process admits. What is left
over is stated rather than hidden: a checkout's *directory* does outlive the process, so a crash
leaves directories under the trees root that the next invocation's `FakeRepository` knows nothing
about. `open` reads that the way git does, refusing to provision over a place that already holds
files, and `remove` takes it away.

## An empty commit message, and where the boundary actually is

git refuses to record a commit whose message is empty *after it has cleaned it*, and a `commit=`
template that renders to nothing is how a workflow reaches that: the step passes `--dry-run` and
dies in anger with `Aborting commit due to empty commit message.` - exit 1 out of git, and
`UpstreamUnexpected` out of `GitWorkspaceProvider`, whose `commit` call hands every refusal to
that class. So `commit_all` refuses it here too, in the same class, and the boundary was measured
against git 2.50.1 rather than reasoned about:

  * **Refused**: `''`, `' '`, `'\\t'`, `'\\n'`, `'\\r'`, and every combination of those four - 71
    refusals over 482 message shapes, every one of them with that same sentence.
  * **Accepted**: anything with one other character in it, `'#'` and a bare `'\\x0b'` included. A
    `-m` message is cleaned in git's `whitespace` mode rather than `strip` mode, so a comment line
    is *not* removed and `'# note'` is an ordinary message.
  * **Accepted, and rewritten**: `'   recorded by a step   '` is recorded as
    `'   recorded by a step\\n'` - trailing whitespace off each line, empty lines off both ends,
    runs of blank lines collapsed to one, and a final newline added.

**Only the refusal is reproduced, and the rewriting deliberately is not.** No member of these three
ports reads a message back - `_snapshots.py` says so where it stores one - so the cleaned form is
unobservable from outside, and rewriting here would change nothing but this implementation's own
content-addressed ids, which divergence 5 in `test_git_parity.py` already covers. What is
observable is which messages are refused, and that is what is held to git exactly: not one message
more, because a fake stricter than the thing it stands in for is the same fiction facing the other
way.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.adapters.git._conflicts import collided, unresolved
from agl.adapters.git._merging import combined, contested
from agl.adapters.git._patches import differences, patch
from agl.adapters.git._snapshots import FakeRepository, Hold, Tree
from agl.adapters.git._trees import deleted, made, tidied
from agl.adapters.git._working import applied, restored, snapshot
from agl.ports.errors import ConflictError, InternalError, NotFoundError, UpstreamUnexpected
from agl.ports.history import FileChange, History
from agl.ports.ids import Namespace, RunLabel
from agl.ports.integration import IntegrationOutcome, Integrator
from agl.ports.tree_layout import (
    TreesRoot,
    base_worktree,
    run_branch,
    run_trees_dir,
    worktree_branch,
    worktree_dir,
)
from agl.ports.workspace import Workspace, WorkspaceProvider

__all__ = ["FakeHistory", "FakeIntegrator", "FakeRepository", "FakeWorkspaceProvider"]

# What git's message cleanup takes away, and the whole of it: space, tab, carriage return and line
# feed. Measured character by character rather than taken from a definition of "whitespace" - a
# vertical tab, a form feed, U+0085 and a no-break space are all `str.isspace()` in Python and all
# ordinary characters to git, so a message of one of them is a message git records. See the module
# docstring for the measurement and for why being stricter here would be the same drift backwards.
_CLEANED_AWAY: Final = " \t\r\n"


class FakeWorkspaceProvider(WorkspaceProvider):
    """`WorkspaceProvider` over one in-memory repository: a real directory per namespace.

    Addressed by name and never by a path a caller computed (§1.10), and every name and every path
    below comes out of `tree_layout` - `run_branch`, `worktree_branch`, `base_worktree`,
    `worktree_dir`, `run_trees_dir` - which is what makes a fake workspace and a real one report
    the same `path` and the same `branch` for one address. Nothing is composed here but which pair
    a `namespace` of `None` means.

    It holds no state past the two things it was built with: the registry of which place has which
    line of work open lives in the repository, so two of these over one `FakeRepository` are the
    same provider, exactly as two `GitWorkspaceProvider`s over one repository are.
    """

    def __init__(self, repository: FakeRepository, trees: TreesRoot) -> None:
        self._repository = repository
        self._trees = trees

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        """Provision a checkout for these identifiers, or hand back the one already there.

        A place that is really there, on this line of work, is handed straight back untouched with
        whatever the previous attempt left in it, committed and uncommitted alike - that is the
        clause §3.6's replay is built on, and re-provisioning a clean checkout is how a resume
        starts over. `base` is read on the one path that provisions a name that does not exist yet
        and nowhere else, because a child's base advances with every integration.

        **Really there**, which is why the directory is asked about before the registry is: a crash
        between provisioning a place and recording anything leaves a registration standing over
        nothing, and the prune inside the `checkout_of` below is what clears it before anything is
        provisioned. Provisioning over a directory that already holds files is refused rather than
        merged into, which is git's answer to the same state and the one that does not silently
        adopt somebody else's leavings.
        """
        place = self._place(label, namespace)
        if place.path.is_dir():
            held = self._repository.checked_out_at(place.path)
            if held == place.branch:
                return _FakeWorkspace(place, self._repository)
            if held is not None:
                raise ConflictError(
                    f"the checkout at {place.path} is on {held!r} and not on {place.branch!r}, so "
                    f"it is somebody else's line of work in this run's place. Nothing was changed"
                )
            if snapshot(place.path):
                raise ConflictError(
                    f"{place.path} already exists and holds files, and nothing here has that "
                    f"place open. Something outside this run left it there; nothing was changed"
                )
        elsewhere = self._repository.checkout_of(place.branch)
        if elsewhere is not None:
            raise ConflictError(
                f"{place.branch!r} is already checked out at {elsewhere}, and one line of work "
                f"cannot be open in two places at once. Nothing was changed"
            )
        cut_from = self._repository.tip(place.branch) or self._cut_from(base, place.branch)
        # One `mkdir` makes the run's directory on the way to the place inside it, which is the
        # directory `tidied` takes away again once the last checkout in it has gone (§3.10).
        made(place.path)
        self._repository.attach(place.path, place.branch, cut_from)
        restored(place.path, self._repository.tree_of(cut_from))
        return _FakeWorkspace(place, self._repository)

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Delete the checkout and forget its registration. The line of work survives.

        The registration goes with the files, and so does any landing the place was holding: git
        keeps `MERGE_HEAD` in the worktree's own git directory, which a prune takes away, so a
        checkout that is gone is holding nothing. Tolerant of absence throughout, because `clear`
        after a crash is the ordinary case rather than the exceptional one.
        """
        place = self._place(label, namespace)
        deleted(place.path)
        tidied(run_trees_dir(self._trees, label))
        self._repository.detach(place.path)
        self._repository.prune()

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Delete the line of work itself. Unconditionally: whether it was merged is `clear`'s
        question (§3.10).

        Refused while something still has it open, which is the real adapter's answer to
        `git branch -D` on a checked-out branch and the reason the port says to call `remove`
        first. Tolerant of the name not being there at all.
        """
        place = self._place(label, namespace)
        holder = self._repository.checkout_of(place.branch)
        if holder is not None:
            raise ConflictError(
                f"{place.branch!r} is still checked out at {holder}, so the name cannot be "
                f"deleted. Take the place back first - that is what `remove` is for"
            )
        self._repository.drop(place.branch)

    def _cut_from(self, base: str, branch: str) -> str:
        """The state a new line of work starts at, or the refusal a base nobody can find means.

        `ConflictError` and not `NotFoundError`, which is the real adapter's classification rather
        than this one's taste: `GitWorkspaceProvider` hands `worktree add` a `refusal` of
        `ConflictError`, so every way that command can say no - a base git cannot resolve among
        them - reaches a caller as exit 4. Agreeing with it where the port is silent is the whole
        of §1.9's rule, and a fake answering exit 3 here would be a `--dry-run` that told a person
        to look for a different problem.
        """
        try:
            return self._repository.resolve(base)
        except NotFoundError as absent:
            raise ConflictError(
                f"{base!r} names no state in this repository, so there is nothing to cut "
                f"{branch!r} from. Nothing was changed"
            ) from absent

    def _place(self, label: RunLabel, namespace: Namespace | None) -> _Place:
        """Where this address lives and what it is called - the only place `None` means `_base`.

        There is no `Namespace` that could be passed instead: `ids.py` refuses that word at
        construction in every spelling, so the run's own workspace is named by the absence of a
        namespace rather than by an encoding of one.
        """
        if namespace is None:
            return _Place(base_worktree(self._trees, label), run_branch(label))
        return _Place(
            worktree_dir(self._trees, label, namespace), worktree_branch(label, namespace)
        )


@dataclass(frozen=True, slots=True)
class _Place:
    """One address resolved: the directory it checks out into, and the branch it carries."""

    path: Path
    branch: str


class _FakeWorkspace(Workspace):
    """One checkout, already provisioned: a real directory, and the three verbs over it.

    Private because nothing constructs one but the provider above. It carries the place it was
    provisioned at rather than recomputing it, which is what makes `path` and `branch` properties
    that do not move while an agent is running in the directory they name - and what makes a
    workspace report the name it actually carries rather than the name today's scheme would
    compute for it.
    """

    def __init__(self, place: _Place, repository: FakeRepository) -> None:
        self._at = place
        self._repository = repository

    @property
    def path(self) -> Path:
        """Absolute, because `TreesRoot` refuses to be anything else and `AgentTask` requires it."""
        return self._at.path

    @property
    def branch(self) -> str:
        """`tree_layout`'s composition, carried rather than recomputed. Opaque above this module."""
        return self._at.branch

    async def head(self) -> str:
        """Where this checkout is now - the value §3.6 records and later hands back to `restore`."""
        at = self._repository.tip(self._at.branch)
        if at is None:
            raise NotFoundError(
                f"{self._at.branch!r} names no line of work in this repository any more, so the "
                f"checkout at {self._at.path} is at no state that can be recorded"
            )
        return at

    async def commit_all(self, message: str) -> str:
        """Record everything in the checkout, and answer with the head - unchanged when nothing
        moved.

        The whole directory and no pathspec, because the workspace is the unit of isolation and
        "what this step did" is "what is in here". Which makes the no-op clause a comparison rather
        than a special case: a checkout holding what the head already holds is a checkout with
        nothing to record, and §3.3's framework calls this at the end of every effect step without
        asking whether anything moved.

        There is no `.gitignore` here, so a build directory an agent left behind is recorded where
        git would have left it out. That is the first of the divergences `test_git_parity.py`
        pins, and the reason is that parsing one program's ignore format would be putting that
        program back into the module whose whole claim is that there is none of it.

        **A message git would clean away to nothing is refused, and the boundary below was
        measured rather than assumed.** `_cleaned_away` is the whole of it. The refusal comes
        *after* the no-op comparison because the real adapter's does: `GitWorkspaceProvider` asks
        `diff --cached --quiet` first and returns the head without ever running `commit`, so a step
        that changed nothing is not the place an empty template is caught.
        """
        at = await self.head()
        held = snapshot(self.path)
        if held == self._repository.tree_of(at):
            return at
        _cleaned_away(message, self.path)
        recorded = self._repository.record(held, (at,), message)
        self._repository.move(self._at.branch, recorded)
        return recorded

    async def restore(self, head: str) -> None:
        """Put the checkout back at `head` and take away everything that was not in it.

        One verb doing both halves, because §3.3 is explicit that moving the head alone is not
        enough - untracked files survive it, and a reviewer's scratch file or an agent's cache
        directory is the exact case this exists for. The line of work moves with the checkout, as
        it does under the real adapter's `reset --hard`, so the next `commit_all` records from
        where this left it.
        """
        at = self._repository.resolve(head)
        restored(self.path, self._repository.tree_of(at))
        self._repository.move(self._at.branch, at)


class FakeHistory(History):
    """`History` over one in-memory repository: five questions, none of which changes anything.

    Bound to the repository by construction, which is the port's own design - no method takes one
    - and holding nothing past it. Every answer is derived from the recorded states themselves,
    so two of these are the same history and a resolve is never stale.
    """

    def __init__(self, repository: FakeRepository) -> None:
        self._repository = repository

    async def default_ref(self) -> str:
        """Where a run starts from when the user names none (§3.9's `--from`, defaulted).

        In full - `refs/heads/main` rather than `main` - which is the real adapter's answer rather
        than a hazard of this one's: there are no tags here for a short name to be ambiguous
        against. It is spelled the same way because a `--dry-run` and the run it stands in for
        must record the same `RunSpec.base_ref`, and a resume reads that string back. What the
        branch is called is the repository's own, said when it was built, a fake having no `HEAD`
        on disk to ask.
        """
        return self._repository.default_ref

    async def resolve(self, ref: str) -> str:
        """A ref expression to the full commit id it names. What pins `RunSpec.base_sha`.

        Sixty-four characters of lowercase hexadecimal by construction rather than by a check:
        a state's id is the hash of its contents, so there is no abbreviation to refuse and no
        second copy of `run.py`'s `_check_sha` here to disagree with the one that binds.
        """
        return self._repository.resolve(ref)

    async def contains(self, ancestor: str, descendant: str) -> bool:
        """Is `ancestor` already part of what `descendant` records? `clear`'s one question (§3.10).

        Both sides are resolved first, so a made-up id is refused rather than answered `False`: an
        implementation that read "I have never heard of it" as "no" would tell `clear` that
        unmerged work is unmerged for the one reason that does not mean that.
        """
        return self._repository.contains(
            self._repository.resolve(ancestor), self._repository.resolve(descendant)
        )

    async def changed_files(self, base: str, head: str) -> tuple[FileChange, ...]:
        """Which files differ between two states, and how - in the port's words, never a tool's.

        Directional and not normalised: the two states reach `_patches.py` in the order they were
        passed, so swapping them gives the inverse answer, which is what makes `ADDED` and
        `DELETED` mean anything at all.
        """
        return differences(*self._between(base, head))

    async def diff(self, base: str, head: str) -> str:
        """The same change as a unified patch - the half a person or a model reads.

        Built from the same reading of the same two states as `changed_files`, which is what makes
        the two agree about a move without either of them knowing what the other asked.
        """
        return patch(*self._between(base, head))

    def _between(self, base: str, head: str) -> tuple[Tree, Tree]:
        """The two states, resolved and read. `NotFoundError` for either one this repository lacks.

        The refusal is the sharp one the port names: "nothing differs from a state that does not
        exist" is a plausible-looking answer and a lie, and the way not to give it is to name both
        states before comparing them.
        """
        return (
            self._repository.tree_of(self._repository.resolve(base)),
            self._repository.tree_of(self._repository.resolve(head)),
        )


class FakeIntegrator(Integrator):
    """`Integrator` over an in-memory three-way merge: land, hold, and the two verbs that end it.

    Bound to the repository by construction and holding nothing between calls. That is the design
    rather than an economy - see the module docstring on the durable hold: every question about a
    pending landing is asked of the repository, so two of these over one `FakeRepository` are one
    integrator and neither can be holding something the other cannot see.
    """

    def __init__(self, repository: FakeRepository) -> None:
        self._repository = repository

    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        """Combine `source`'s line of work into `target`'s, and say whether it went in.

        Read off `branch` on both sides and never `path` on the source, which is what the real
        adapter does and what the port's second implementation - one that lands by opening a
        change request - is entitled to do: what is landed is what the source *recorded*, so work
        an agent left uncommitted in its checkout does not go in.

        **Work the target already holds still lands**, reporting the unchanged head and moving
        nothing. That is the ordinary shape of a replayed run (§3.6) and not a failure, not a
        conflict, and not a third case.

        The pre-check is a rule rather than a probe: a landing already pending means the run owes
        this target a `retry` or an `abort` it never made, and merging over one would report the
        old hold's collision as this landing's.

        The refusal below is the real adapter's, and git states it in as many words - a merge that
        would overwrite a file the checkout has changed and not recorded is refused before
        anything is touched. Without it a `--dry-run` would quietly destroy an agent's uncommitted
        work where a real run would have stopped and said so.
        """
        if self._repository.held(target.path) is not None:
            raise InternalError(
                f"a landing into {target.branch!r} is already pending, and this run is asking to "
                f"land {source.branch!r} on top of it. Every path out of a conflicted landing owes "
                f"the target a retry or an abort, so AGL has lost track of a hold it took"
            )
        landing = self._repository.tip(source.branch)
        if landing is None:
            raise UpstreamUnexpected(
                f"{source.branch!r} names no line of work in this repository, so there is nothing "
                f"there to land into {target.branch!r}"
            )
        settled = await target.head()
        if self._repository.contains(landing, settled):
            return IntegrationOutcome(head=settled)

        ancestor = self._repository.merge_base(settled, landing)
        combination = combined(
            self._repository.tree_of(ancestor) if ancestor is not None else {},
            self._repository.tree_of(settled),
            self._repository.tree_of(landing),
            target.branch,
            source.branch,
        )
        wanted = {**combination.tree, **combination.contested}
        recorded = self._repository.tree_of(settled)
        changing = frozenset(
            path
            for path in set(wanted) | set(recorded)
            if wanted.get(path) != recorded.get(path)
        )
        self._refuse_to_overwrite(target, recorded, changing)

        applied(target.path, wanted, changing)
        called = _merged(source.branch, target.branch)
        if not combination.collisions:
            arrived = self._repository.record(combination.tree, (settled, landing), called)
            self._repository.move(target.branch, arrived)
            return IntegrationOutcome(head=arrived)
        self._repository.hold(
            target.path,
            Hold(
                source=landing,
                target=settled,
                combined=combination.tree,
                collisions=combination.collisions,
                message=called,
                touched=changing,
            ),
        )
        return IntegrationOutcome(
            conflict=collided(combination.collisions, source.branch, target.branch, target.path)
        )

    async def retry(self, target: Workspace) -> IntegrationOutcome:
        """Look again at the landing `target` is holding, and conclude it if it can be concluded.

        Called after something *outside this port* changed the situation, and this port has no
        opinion about what they did: it asks which of the colliding files still carry the
        collision this package wrote into them. That is where the real adapter asks git's index,
        and the difference is one `test_git_parity.py` pins - there is no index here and no
        staging verb on this port, so the file is the only place a person's answer can be.

        What is concluded is what combined plus what they left at the colliding paths, which is
        the counterpart of committing an index rather than the working tree: an unrelated scratch
        file beside them is not swept into the target's history.

        **A landing has to be pending**, and `InternalError` is why: `retry` is called only in
        answer to a conflicted outcome, so nothing pending means AGL lost track of a hold it took,
        and the two-case outcome has no honest spelling for "there was nothing to do".
        """
        pending = self._repository.held(target.path)
        if pending is None:
            raise InternalError(
                f"there is no landing pending in {target.branch!r}, so there is nothing to try "
                f"again. This is called only in answer to a conflicted outcome, and a target that "
                f"holds nothing means AGL lost track of a hold it took - or somebody finished the "
                f"landing by hand, which `abort` is the tolerant answer to"
            )
        held = snapshot(target.path)
        still = tuple(path for path in pending.collisions if contested(held.get(path)))
        if still:
            return IntegrationOutcome(conflict=unresolved(still, target.branch, target.path))
        settled = dict(pending.combined)
        for path in pending.collisions:
            resolution = held.get(path)
            if resolution is not None:
                settled[path] = resolution
        arrived = self._repository.record(
            settled, (pending.target, pending.source), pending.message
        )
        self._repository.move(target.branch, arrived)
        self._repository.release(target.path)
        return IntegrationOutcome(head=arrived)

    async def abort(self, target: Workspace) -> None:
        """Give up on the pending landing, putting `target` back exactly where `land` found it.

        Only what the attempt wrote or removed is put back, which is the whole difference between
        this and `Workspace.restore`: "as it was before `land`" is not "as if nothing had ever
        happened", and a person's scratch file beside the collision is theirs.

        **Tolerant of there being nothing pending**, which is why the question is asked before
        anything is undone. A release after a crash is the ordinary case; so is a person who
        finished the held landing by hand, and reading this as "undo the last landing" would
        destroy their work.
        """
        pending = self._repository.held(target.path)
        if pending is None:
            return
        applied(target.path, self._repository.tree_of(pending.target), pending.touched)
        self._repository.move(target.branch, pending.target)
        self._repository.release(target.path)

    def _refuse_to_overwrite(
        self, target: Workspace, recorded: Tree, changing: frozenset[str]
    ) -> None:
        """Refuse a landing that would overwrite work the target's checkout has not recorded.

        git's own refusal, in both of the ways it spells it - an untracked file the merge would
        write over, and a tracked one the checkout has changed since - and one class for both,
        because `GitIntegrator` hands every refusal from `git merge` to `UpstreamUnexpected` and
        the two have to answer alike. Only the paths this landing would touch are looked at: a
        checkout dirty somewhere else is a checkout a landing has no business refusing.
        """
        held = snapshot(target.path)
        blocked = sorted(path for path in changing if held.get(path) != recorded.get(path))
        if blocked:
            raise UpstreamUnexpected(
                f"the checkout at {target.path} holds changes to {blocked} that were never "
                f"recorded, and landing {target.branch!r} would write over them. Record them or "
                f"take them away first; nothing here has been changed"
            )


def _merged(source: str, target: str) -> str:
    """What a landing is called in the target's own past.

    git writes this sentence itself and `--no-edit` accepts it; there is nothing here to accept,
    so it is written in the same words. §3.11's argument against an auto-generated commit message
    is about a message describing *work*, and this one describes an event.
    """
    return f"Merge branch '{source}' into {target}"


def _cleaned_away(message: str, where: Path) -> None:
    """`UpstreamUnexpected` if git would clean `message` away to nothing. See the module docstring.

    `strip` and not `str.strip()`, and the difference is the whole of the care this needs.
    Python's own strip is Unicode-aware and takes a vertical tab, a form feed, U+0085 and a
    no-break space for whitespace; git's cleanup does not, and refusing a message git records
    would be the drift §1.9 names running the other way - a `--dry-run` that stops a step anger
    would have carried through. So the set is written out, and it is the four characters that
    were measured, in the two places they are stripped from.
    """
    if message.strip(_CLEANED_AWAY) == "":
        raise UpstreamUnexpected(
            f"the message for this commit is {message!r}, and git cleans that away to nothing: it "
            f"takes the trailing whitespace off every line of a `--message` and the empty lines "
            f"off both ends, then refuses what is left when nothing is - `Aborting commit due to "
            f"empty commit message.`, exit 1. Nothing in {where} has been recorded, and a step "
            f"whose commit template renders to whitespace fails here exactly as it would in anger"
        )
