"""`GitWorkspaceProvider` - the real `WorkspaceProvider`: one git worktree per namespace, cut
from a ref, and never the user's own checkout.

§3.9's obstacle was never locking. It was that AGL merged in the user's working directory, so
every run contended over one checked-out branch; the answer is that a run works in worktrees of
its own, under a trees root that is not the repository. `git worktree add -b agl/auth
.trees/auth/_base <sha>` succeeds while `main` is checked out elsewhere - a branch may be
*started from* anywhere, it just cannot be *checked out* twice - so concurrent runs share an
object store and nothing else, and `git status` in `repo/` stays clean while a run is going.

**Not one branch name is composed here.** `tree_layout` owns the scheme - `agl/<label>` for the
run, `agl/_work/<label>/<namespace>` for a child - and owns it because the obvious scheme cannot
exist in git at all: `refs/heads/agl/auth` cannot be both a file and a directory, so `agl/auth`
and `agl/auth/T-01` collide in either creation order. Every name and every path below comes out
of `run_branch`, `worktree_branch`, `base_worktree`, `worktree_dir` and `run_trees_dir`, and the
only thing this module adds is which pair a `namespace` of `None` means. A branch string
assembled from parts here would be that collision, reintroduced one layer down.

## The one contention point, and where it is

`git worktree add` and `git worktree prune` mutate `.git/worktrees/`, and nothing else this module
does touches it. So those two calls - and only those two - happen inside `_trees.registry_lock`,
§3.9's cross-process `flock(2)` on a file in the trees root, which is let go of before anything
long-running starts: never across a merge, a build, or a person deciding something. Every word of
why it is that lock rather than a mutex or a PID file is argued in `_trees.py`, beside the code
that takes it.

That module is the other half of this one, and the seam between them is that **nothing there runs
a process and nothing here mutates the filesystem**. Making a run's directory, deleting a
checkout's files, taking that directory away again and holding the lock are all `mkdir`, `rmtree`,
`rmdir` and `flock` - no git in any of them - so they live together, with the `OSError`
translation that only they can need, and the one platform assumption this package makes goes with
them.

## Reopening is what makes replay work, and it is not re-provisioning

Provisioning a namespace that already has a checkout hands back that checkout, with whatever the
previous attempt left in it, committed and uncommitted alike. §3.6's replay is what then decides
whether to keep that state or `restore` past it, and it cannot decide about something already
thrown away: an implementation that quietly re-cut a clean checkout would pass "opening twice
does not raise" and destroy every resume. So `open` asks whether there is a checkout at this place
and what git says it is on, and touches nothing when the answer is this line of work.

`base` is therefore consulted on exactly one path - the `-b` form below - and read nowhere else.

## Two teardown verbs, because `clear` needs them apart (§3.10)

`remove` deletes the checkout and prunes the registration; the branch survives, so opening again
re-attaches to it and the work that was committed is still there. `discard` deletes the branch.
Both tolerate absence, because `clear` after a crash is the ordinary case.

A checkout is taken back by deleting the directory and then pruning, which is git's own documented
recovery for a linked worktree whose directory has gone. `git worktree remove` was the other
option and refuses a dirty tree without `--force`, refuses again for a submodule, and refuses
outright when the registration is already gone - three refusals to tolerate in a verb whose whole
job is to be unconditional.

`git branch -D` is the one place a refusal has to be read rather than raised: it exits 1 both for a
branch that is not there and for one another worktree still holds, which `_runner.py` names as the
reason `answers` must not be used to tolerate a refusal. So the refusal is caught and the branch is
asked about afterwards - absent means the caller got what it asked for, present means something
still has it open, which is `ConflictError` and is why the port says to call `remove` first.

## What is deleted rather than made configurable

The trunk-branch check and the dirty-repository refusal are both gone (§3.9). They existed only
because AGL worked in the user's directory; a worktree is cut from a *ref*, so what the user has
checked out and whether it is dirty are equally irrelevant. Nothing below looks.

## The arguments that reach git

Every invocation goes through `_runner.py`, so no shell ever sees any of this. `--end-of-options`
is added wherever an argument could begin with a dash - argv discipline stops a value being read
as shell syntax and does nothing about one being read as a git option - and the runner's docstring
says why it belongs here rather than there. One version assumption is worth stating plainly: the
`-z` form of `worktree list --porcelain` (git 2.36) is what makes the registry parse unambiguous
for a path holding a newline, which the newline form documents itself as not being.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.adapters.git._runner import GitRunner, unreadable
from agl.adapters.git._trees import deleted, made, registry_lock, tidied
from agl.ports.errors import ConflictError, NotFoundError, UpstreamUnexpected
from agl.ports.ids import Namespace, RunLabel
from agl.ports.tree_layout import (
    TreesRoot,
    base_worktree,
    run_branch,
    run_trees_dir,
    worktree_branch,
    worktree_dir,
)
from agl.ports.workspace import Workspace, WorkspaceProvider

__all__ = ["GitWorkspaceProvider"]


# A backstop for the calls that ask git a question out of the repository's own data rather than
# walking the working tree: a ref lookup, the worktree registry, a prune, a branch deletion. The
# runner's default is sized for a checkout of a large repository, which makes it no guard at all
# on anything small, and `_runner.py` says a call site that knows its operation's shape passes its
# own. Everything that scales with the tree - `add`, `commit`, `reset`, `clean`, `worktree add` -
# deliberately keeps the runner's default.
_ASKING: Final = 30.0

# git's registry, in the `-z` form: every attribute ends in a NUL and an empty attribute ends the
# record. `worktree` opens one, `branch` carries the full ref of what is checked out there, and an
# entry with neither - a detached HEAD, a bare repository - answers nothing and is skipped.
_ATTRIBUTE_END: Final = "\0"
_REGISTERED_AT: Final = "worktree "
_REGISTERED_ON: Final = "branch "

# What a branch is called when git spells it in full. Composing this is not composing a *name* -
# the name arrived from `tree_layout` whole - it is qualifying one, so that a tag of the same name
# cannot answer a question about a branch.
_BRANCH_REF: Final = "refs/heads/"


class GitWorkspaceProvider(WorkspaceProvider):
    """`WorkspaceProvider` over git worktrees: one repository, one trees root, addressed by name.

    Constructed by `config/container.py` with the two roots it works between and nothing else, and
    never with a path a caller computed - §1.10's charge, which `ports/workspace.py` restates as
    the rule that every method here takes a `RunLabel` and a `Namespace` and derives its own
    layout. It holds no state past those two: two of these over one repository, which is what two
    `agl` invocations are, are the same provider, and the file lock in `_trees.py` is what makes
    that safe rather than an arrangement between them.

    The runner is built here rather than injected because it is this package's private plumbing
    (§3.4) and nothing outside `agl/adapters/git/` may name it - so the container hands over a
    repository, exactly as it does to every other adapter, and each of the three git adapters over
    one repository builds the same runner from it.
    """

    def __init__(self, repository: Path, trees: TreesRoot) -> None:
        self._git = GitRunner(repository)
        self._trees = trees

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        """Cut a worktree for these identifiers, or hand back the one already checked out there.

        A checkout that is really there, on this branch, is handed straight back untouched, with
        whatever the previous attempt left in it. Nothing is reset, nothing is cleaned, and `base`
        is not looked at - a child's base advances with every integration, so re-cutting on reopen
        is how a resume after the first merge would lose that child's work.

        **Really there**, which is why the directory is asked about before the registry is: git
        goes on listing a worktree whose directory has gone, and a crash between the two leaves
        exactly that. Treating a registration as a reopen would hand back a `Path` that is not a
        directory and every later call in that workspace would fail; treating it as a provisioning
        is right, because the `prune` below is precisely what clears it.

        Provisioning is two calls under one lock, and they are §3.9's two: a `prune` first, because
        a crash leaves a registration whose directory is gone and git refuses to add over one
        ("missing but already registered") until it is cleared, and then the `add` itself. Whether
        that add makes a branch or attaches to one already there is the difference between a first
        provisioning and an `open` after a `remove`, and it is decided before the lock is taken -
        the lock guards the registry, not the reading of a ref.

        `-b` in one command rather than a `branch` and then an `add`: git either creates the branch
        and checks it out or does neither, so a failed provisioning cannot leave a half-made line
        of work for the next attempt to re-attach to.
        """
        place = self._place(label, namespace)
        if place.path.is_dir():
            held = await self._branch_at(place.path)
            if held == place.branch:
                return _GitWorkspace(place, self._git)
            if held is not None:
                raise ConflictError(
                    f"the checkout at {place.path} is on {held!r} and not on {place.branch!r}, so "
                    f"it is somebody else's line of work in this run's place. Nothing was changed"
                )

        attaching = await self._branch_exists(place.branch)
        made(run_trees_dir(self._trees, label))
        adding = (
            ("worktree", "add", "--end-of-options", str(place.path), place.branch)
            if attaching
            else ("worktree", "add", "-b", place.branch, "--end-of-options", str(place.path), base)
        )
        async with registry_lock(self._trees):
            await self._git.run("worktree", "prune", refusal=UpstreamUnexpected, timeout=_ASKING)
            await self._git.run(*adding, refusal=ConflictError)
        return _GitWorkspace(place, self._git)

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Delete the checkout and prune its registration. The branch survives.

        Both halves run unconditionally, and the prune runs even when there was nothing to delete:
        the registration is the half of a checkout that git owns, and the state a crash leaves -
        files gone, registration standing - is exactly the one that would otherwise refuse the next
        `open`. Pruning is repository-wide by nature, which costs nothing: an entry is prunable
        only when its directory has already gone.

        The run's own directory is taken away too, once the last checkout in it has gone, so that
        §3.10's `clear` really does remove `.trees/<label>/` while holding only the two verbs this
        port offers; `_trees.tidied` is where that is nothing more than one `rmdir`.
        """
        place = self._place(label, namespace)
        deleted(place.path)
        tidied(run_trees_dir(self._trees, label))
        async with registry_lock(self._trees):
            await self._git.run("worktree", "prune", refusal=UpstreamUnexpected, timeout=_ASKING)

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        """Delete the branch. Unconditionally: whether it was merged is `clear`'s question (§3.10).

        `-D` and not `-d` because the port holds no policy about when deleting a line of work is
        right - `clear` deletes a run's children whatever state they are in, and asks `History`
        about the run's own branch before deleting that one. A `-d` here would put half of that
        policy in the adapter and answer the other half wrongly.

        The refusal is read rather than raised because git spells two answers the same way; the
        module docstring has the argument. Asked *after* the failure and never before it, which is
        `_runner.py`'s durable lesson about this boundary: the check costs one process on the path
        that was already going to raise, instead of one on every call that was going to work.
        """
        place = self._place(label, namespace)
        try:
            await self._git.run(
                "branch",
                "--delete",
                "--force",
                "--end-of-options",
                place.branch,
                refusal=ConflictError,
                timeout=_ASKING,
            )
        except ConflictError:
            if await self._branch_exists(place.branch):
                raise

    def _place(self, label: RunLabel, namespace: Namespace | None) -> _Place:
        """Where this address lives and what it is called - the only place `None` means `_base`.

        There is no `Namespace` that could be passed instead: `ids.py` refuses that word at
        construction in every spelling, so the run's own workspace is named by the absence of a
        namespace rather than by an encoding of one. Both branches read every name they use out of
        `tree_layout` and compose nothing.
        """
        if namespace is None:
            return _Place(base_worktree(self._trees, label), run_branch(label))
        return _Place(
            worktree_dir(self._trees, label, namespace), worktree_branch(label, namespace)
        )

    async def _branch_at(self, path: Path) -> str | None:
        """The branch checked out at `path`, or `None` if git has no worktree registered there.

        A question about the registry and not about the disk - a worktree whose directory has gone
        is listed until something prunes it - so the one caller asks the disk first.

        Read out of `worktree list --porcelain -z`, which is plumbing meant for exactly this and
        the only honest way to ask: a directory that merely *looks* like a checkout answers about
        whatever repository it happens to sit inside, which is a live hazard when the trees root
        is under the repository rather than beside it.

        Both paths are resolved before they are compared. git records the real path of a worktree,
        and a trees root reached through a symlink - `/tmp` on macOS is one - would otherwise
        register under one spelling and be looked up under another, so every reopen would read as
        a fresh place and provisioning would refuse it.
        """
        listing = await self._git.run(
            "worktree", "list", "--porcelain", "-z", refusal=UpstreamUnexpected, timeout=_ASKING
        )
        wanted = path.resolve()
        registered: Path | None = None
        for attribute in listing.split(_ATTRIBUTE_END):
            if attribute.startswith(_REGISTERED_AT):
                registered = Path(attribute[len(_REGISTERED_AT) :]).resolve()
            elif attribute.startswith(_REGISTERED_ON):
                if registered is None:
                    raise unreadable("a worktree registration", listing)
                if registered == wanted:
                    return _short(attribute[len(_REGISTERED_ON) :])
            elif not attribute:
                registered = None
        return None

    async def _branch_exists(self, branch: str) -> bool:
        """Whether this line of work has a name in the repository yet.

        Asked of the fully qualified ref, so that a tag somebody made of the same name cannot
        answer for a branch. `--quiet` is what makes this one of git's exit-status questions -
        0 yes, 1 no - and anything else is a repository that could not answer, which is not one of
        the two and so is `UpstreamUnexpected` rather than a silent "no".
        """
        return await self._git.answers(
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"{_BRANCH_REF}{branch}",
            refusal=UpstreamUnexpected,
            timeout=_ASKING,
        )


@dataclass(frozen=True, slots=True)
class _Place:
    """One address resolved: the directory it checks out into, and the branch it carries.

    The two halves of what `tree_layout` answers about an address, held together so that the
    layout is read once per call and the two cannot disagree afterwards.
    """

    path: Path
    branch: str


class _GitWorkspace(Workspace):
    """One worktree, already checked out: where it is, what it is on, and the three step verbs.

    Private because nothing constructs one but the provider above. It holds the place it was
    provisioned at rather than recomputing it, which is what makes `path` and `branch` properties
    that do not change while an agent is running in the directory they name - and what makes a
    workspace report the name it actually carries rather than the name today's scheme would
    compute for it, so a run keeps its branch when the scheme changes.
    """

    def __init__(self, place: _Place, git: GitRunner) -> None:
        self._at = place
        self._git = git

    @property
    def path(self) -> Path:
        """Absolute, because `TreesRoot` refuses to be anything else and `AgentTask` requires it."""
        return self._at.path

    @property
    def branch(self) -> str:
        """`tree_layout`'s composition, carried rather than recomputed. Opaque above this module."""
        return self._at.branch

    async def head(self) -> str:
        """Where this checkout is now - the value §3.6 records and later hands back to `restore`.

        Asked of the working tree rather than of the branch, because those two disagree exactly
        when it matters: an agent that committed during its own run has moved one of them, and the
        head a step records is the state of the place the next step will find.
        """
        answer = await self._git.run(
            "rev-parse",
            "--verify",
            "--end-of-options",
            "HEAD",
            cwd=self.path,
            refusal=NotFoundError,
            timeout=_ASKING,
        )
        return _one(answer, "a commit id")

    async def commit_all(self, message: str) -> str:
        """Record everything dirty, and answer with the head - unchanged when nothing was.

        Three calls, and the middle one is the port's no-op clause: stage everything, ask git
        whether that came to anything, and commit only if it did. Asking after staging rather than
        before is what makes the answer right for an untracked file, which is dirt no comparison of
        the tree against the index would have seen. `commit` refuses an empty commit, so this is
        also what keeps a step whose agent changed nothing from being an error.

        `--all` with no pathspec, because the workspace is the unit of isolation and "what this
        step did" is "what is in here". What `.gitignore` covers stays out, which is git's own
        answer to what is not part of the state and not one this module is entitled to overrule.

        **`--no-verify` and `--no-gpg-sign`.** These commits are the framework's own bookkeeping on
        a branch AGL created, not a person's commit to a shared one: a `commit-msg` hook enforcing
        a house format would reject the workflow author's sentence, a `pre-commit` hook would be a
        fifth sensor on the target that §3.5 does not have and that the build gate already covers
        properly (§3.4), and a signing prompt would hang against a runner that has deliberately
        given its children no terminal to ask on. The message is passed as its own argument and is
        never interpreted: it is the author's prose, and prose is where the metacharacters live.
        """
        await self._git.run("add", "--all", cwd=self.path, refusal=UpstreamUnexpected)
        if await self._git.answers(
            "diff", "--cached", "--quiet", cwd=self.path, refusal=UpstreamUnexpected
        ):
            return await self.head()
        await self._git.run(
            "commit",
            "--no-verify",
            "--no-gpg-sign",
            "--message",
            message,
            cwd=self.path,
            refusal=UpstreamUnexpected,
        )
        return await self.head()

    async def restore(self, head: str) -> None:
        """Put the tree back at `head` and take away everything that was not in it.

        Two commands because git has no one command for it: `reset --hard` speaks only for what is
        tracked and `clean` only for what is not, and §3.3 is explicit that moving the head alone
        is not enough. That is the whole reason the port is one verb - "restored but not cleaned"
        is not a state a caller can reach by forgetting a line.

        `-fd` descends into a directory that was not there before, which is the agent-cache half of
        what this exists for; the second `-f` takes away a nested repository, which git otherwise
        skips and which is a leaving like any other - an agent that cloned something into its
        workspace left it, and nothing here is going to look inside it first.

        **No `-x`, so what `.gitignore` covers survives**, and that is a decision rather than an
        omission. Those files cannot reach a commit - `add --all` will not stage them - so they
        cannot contaminate the ledger, which is the thing this method protects; what they can be is
        the build cache that makes the next step's tests take seconds instead of minutes, in a
        worktree that was cut fresh anyway. Deleting them on the way out of every read-only step
        would cost a cold build each time and buy nothing the port asks for.
        """
        await self._git.run(
            "reset", "--hard", "--end-of-options", head, cwd=self.path, refusal=NotFoundError
        )
        await self._git.run("clean", "-ffd", cwd=self.path, refusal=UpstreamUnexpected)


def _short(ref: str) -> str:
    """`refs/heads/agl/_work/auth/T-01` -> `agl/_work/auth/T-01`, which is what a branch is called.

    git's registry answers in full refs and `tree_layout` composes short names, so one of the two
    has to be brought to the other. Bringing the ref down is the safe direction: it removes a
    prefix that is git's own and leaves the name exactly as the layout wrote it.
    """
    return ref[len(_BRANCH_REF) :] if ref.startswith(_BRANCH_REF) else ref


def _one(answer: str, what: str) -> str:
    """git's one-line answer, stripped, or the error for an answer that is not one.

    The runner hands output back whole because a `-z` form's trailing NUL is data; a `rev-parse`
    is the other kind, where the newline is punctuation. An empty answer is `unreadable` rather
    than an empty string handed upwards, because a commit id nobody can use is worse the further
    it travels - §3.6 would write it into an entry and chain the next fingerprint off it.
    """
    stripped = answer.strip()
    if not stripped:
        raise unreadable(what, answer)
    return stripped
