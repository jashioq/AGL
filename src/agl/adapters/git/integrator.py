"""`GitIntegrator` - the real `Integrator`: land a child's line of work into the run's own, and
hold the target when the two will not combine.

§1.3's charge against the previous implementation was a 27-member port speaking one tool's merge
state machine out loud - `merge_in_progress`, `unmerged_paths`, `abort_merge`, `commit_merge` -
and §3.4's answer is that the state machine stays inside `adapters/git/integrator.py`. This is that
module, and the answer is made true here or nowhere: nothing above an adapter sees a porcelain
code, a marker file, an in-progress predicate or a `GitError`. Three methods leave this file, each
of them a whole thing a consumer wanted done.

A landing is a merge of the source's branch into the target's, run **in the target's own checkout**
- `agl/<label>` is checked out in the run's `_base` worktree and git will not have a branch checked
out twice (§3.9), so `cwd` is `target.path` and never the repository. Nothing here takes the
worktree registry lock: that guards `worktree add` and `prune` (§3.9), which this module never
calls, and holding it across a merge is precisely what `_trees.py` says the lock is never held
across.

## The hold is durable because it is git's own, and not AGL's

§3.4, in as many words: *the hold must be durable, not in-memory. A run that dies holding a target
can only be released by a later invocation, so the hold has to be readable from the repository - an
in-memory hold makes a resumed run's `abort()` a silent no-op and leaves the target half-combined
forever.* The plan adds that a contract suite cannot catch this, since both implementations pass.

A conflicted `git merge` writes `MERGE_HEAD` into the worktree's own git directory -
`.git/worktrees/_base/MERGE_HEAD` for a linked worktree - and **that file is the hold**. There is
nothing else: this class holds a runner, no attribute records a pending landing, no module-level
anything remembers one, and `_held` below is the single predicate all three methods ask. A
`GitIntegrator` constructed in a later process, handed the same target, asks git the same question
and gets the same answer, so `abort` after a crash releases a hold this process never took.

Two consequences worth stating rather than discovering. The hold is **per worktree**, because
`MERGE_HEAD` is per worktree: a landing held in one run's `_base` is invisible to every other run,
which is the isolation §3.9 is built on. And it is **only ever a merge**: a rebase or a cherry-pick
somebody left in the target is not a landing this port took, so `abort` will not touch it.

## Two answers spelled one way, and how they are told apart

`git merge` exits 1 for a conflict *and* for "that is not something we can merge", so a caller
reading the exit status alone cannot tell a held target from a refused one - and the refusals that
are not conflicts are ordinary things: a source whose branch has gone, a target checkout holding
changes the merge would overwrite, histories with no common state. `_runner.py` names this shape
itself: `answers` is "not a way to tolerate a refusal", and tolerance is `run` with a refusal class
and an `except` around it, at the call site, where what is being tolerated can be named.

So the refusal is caught and the world is asked afterwards - `workspace.py::discard`'s shape, and
`_runner.py`'s durable lesson about probing after a failure rather than before every call. A target
that is now held means this merge conflicted; a target that is not means git refused something else
and the error goes on up carrying git's own words. `land` asks the same question *before* it starts,
too, and that one is not a probe but a rule: a landing pending in the target means the framework
skipped a `retry` or an `abort` it owed, and a merge attempted over one would report the old hold's
conflict as this landing's.

**A conflict is never an exception.** It is the ordinary second answer to this port's question, and
the exception above is caught inside this module and turned into a return value before anything
sees it.

## The flags, and what each of them is worth

Every invocation goes through `_runner.py`, so no shell sees any of this. What argv discipline does
not cover is a value read as a git *option*, and `git merge` is the sharpest instance of that in
the package: it takes `--abort`, `--quit` and `--continue`, so a branch named `--abort` would turn
a landing into a release, and `-F <path>` reads a file into the commit message, so one named
`--file=/etc/passwd` would put that file's contents into the target's history. `--end-of-options`
goes after every option and before the branch, and git then refuses the argument as a ref. Branch
names reach here from `tree_layout` through `Workspace.branch` and `ids.py` validated the parts
they are made of, but this is the guarantee and the charset is defence in depth - 5.3 found the
same hazard on `diff-tree --output=` and reproduced it.

The rest are what stops a person's own configuration deciding whether a landing lands. This is
`history.py`'s line - what would change *whether there is an answer at all* is refused, and what
only changes how one is spelled is left alone - applied where there is no plumbing form to hide
behind, because `git merge` is porcelain and has no plumbing equivalent that moves a ref.

  * **`--strategy=ort`.** `pull.twohead = ours` sets the default strategy for a two-head merge, and
    a landing made under it exits 0, reports a head, and **contains none of the child's work**.
    That is the one misconfiguration on this list that loses work silently, so the strategy is
    asked for by name, exactly as `history.py` asks for rename detection by name. `ort` is git's
    own default since 2.34 and this package already requires 2.36 for `worktree list -z`; a git
    that does not have it fails loudly here rather than quietly landing nothing.
  * **`--no-verify-signatures`.** `merge.verifySignatures = true` refuses to merge a commit with no
    GPG signature, which every commit AGL makes is: `commit_all` signs nothing, deliberately. The
    check can only ever fail against AGL's own bookkeeping on branches AGL created minutes ago.
  * **`-c rerere.enabled=false`.** With rerere on, git replays a resolution recorded on *this
    machine* and stages it, so the same two branches conflict on one developer's machine and land
    on another - and the combination the build gate then decides about was resolved by a cache
    nobody in this run saw. §3.4 forbids exactly that: a conflict is "not resolved by guessing".
    Turned off through `-c` because there is no flag for it, and explicitly rather than by
    omission, since an existing `rr-cache` directory turns rerere on by itself.
  * **`--no-ff`.** A landing is an event in the target's history. A fast-forward would leave the
    target's head naming a state the *child* made, so `git log agl/auth` could not say which child
    arrived when and the head a run records for a landing would be a value that exists whether or
    not the landing happened.
  * **`--no-verify` and `--no-gpg-sign`**, for `commit_all`'s reasons and in its words: these are
    the framework's own bookkeeping on a branch AGL created, a hook enforcing a house format would
    reject it, and a signing prompt would hang against a runner that has given its children no
    terminal to ask on.
  * **`--no-edit`.** Both the merge and the commit that concludes one open an editor otherwise, and
    a child with `stdin` on `/dev/null` and no terminal would hang until the timeout.

## What this module does not do

**No `revert`.** §3.11 records that `Integrator.revert()` was deliberately not built: undoing a
landing that *succeeded* is `Workspace.restore(head)`, the same primitive §3.3 and §3.6 already use
before re-running a step and on the way out of a read-only one. The framework reads the target's
head before it calls `land` and hands that same value back when the gate says no. `abort` here is
the different thing: it releases a landing that never completed.

**No opinion about what is inside a file.** Nothing here opens a conflicted file or knows what
`<<<<<<<` means. What decides whether a held landing can be concluded is the index - git's own
record of which paths are unresolved - and a resolution that still holds markers is a resolution
the person made, which the build gate (§3.4) is what catches.

**No message of its own.** git writes the merge message and `--no-edit` keeps it; the commit that
concludes a held landing reuses the one git already wrote. §3.11's argument against an
auto-generated commit message stands, and the way not to invent one is to use the one the tool
already has.

**No lease, no lock and no state.** The lease is the framework's (§3.4) and
`sdk/_engine/integration.py` owns it; the port argues at length why it is not modelled here. What
that leaves is one runner per instance and nothing else, so two of these over one repository -
which is what two `agl` invocations are - need no arrangement between them.
"""

from pathlib import Path
from typing import Final

from agl.adapters.git._conflicts import collided, unmerged, unresolved
from agl.adapters.git._runner import GitRunner
from agl.ports.errors import InternalError, UpstreamUnexpected
from agl.ports.integration import IntegrationOutcome, Integrator
from agl.ports.workspace import Workspace

__all__ = ["GitIntegrator"]


# A backstop for the calls that read the repository's own data rather than walking a tree: the
# pending-landing probe and the index's unresolved entries. The runner's default is sized for a
# checkout of a large repository, which makes it no guard at all on anything this small, and
# `_runner.py` says a call site that knows its operation's shape passes its own. The merge, the
# commit that concludes one and the release all scale with the tree and keep the runner's default.
_ASKING: Final = 30.0

# The landing itself, up to but not including the branch being landed. The module docstring argues
# every flag. The `-c` pair is git's own option and so comes before the subcommand, which is the
# only place a setting can be overridden for one invocation; `--end-of-options` is last because
# that is where it belongs - after every option and before the one value that came from outside.
_MERGING: Final = (
    "-c",
    "rerere.enabled=false",
    "merge",
    "--strategy=ort",
    "--no-ff",
    "--no-edit",
    "--no-verify",
    "--no-gpg-sign",
    "--no-verify-signatures",
    "--end-of-options",
)

# Concluding a landing whose collision somebody resolved. No pathspec and no staging: what is in
# the index is what the person who resolved it put there, and a `--all` here would sweep their
# scratch files into the target's history. No `--message` either - git wrote one when the merge
# stopped, and `--no-edit` is what accepts it.
_CONCLUDING: Final = ("commit", "--no-edit", "--no-verify", "--no-gpg-sign")

# The release. It takes no ref, so nothing from outside this module reaches its arguments and there
# is no option for `--end-of-options` to protect - the whole command is these two words.
_RELEASING: Final = ("merge", "--abort")

# Is a landing pending? `MERGE_HEAD` is written by a conflicted merge and removed when the merge is
# concluded or released, and it lives in the worktree's own git directory - which is what makes the
# hold durable, per-worktree, and nothing of AGL's. `--quiet` is what makes this one of git's
# exit-status questions: 0 yes, 1 no, and anything else is a repository that could not answer.
_PENDING: Final = ("rev-parse", "--verify", "--quiet", "--end-of-options", "MERGE_HEAD")

# Which paths the index holds unresolved. `--full-name` spells them from the repository root, which
# is what `Conflict.paths` promises; `_conflicts.py` argues the rest of the form.
_UNRESOLVED: Final = ("ls-files", "--unmerged", "--full-name", "-z")


class GitIntegrator(Integrator):
    """`Integrator` over git merges: one repository, one runner, and no state between calls.

    Constructed by `config/container.py` with the repository and nothing else, like every other
    adapter. The runner is built here rather than injected because it is this package's private
    plumbing (§3.4): the container hands over a repository and each of the three git adapters over
    one repository builds the same runner from it.

    Holding nothing is not an economy here, it is the design - see the module docstring. Every
    question about a pending landing is asked of the repository, so two of these are the same
    integrator and one built after a crash knows what the one that died was holding.
    """

    def __init__(self, repository: Path) -> None:
        self._git = GitRunner(repository)

    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        """Merge `source`'s branch in `target`'s own checkout, and say what came of it.

        Three answers, of which the port has two. It went in, and the head is the target's own -
        read back through `Workspace.head` rather than out of git a second time, so the state the
        outcome names and the state the gate will run in are one reading. It would not combine, and
        the target is left held with a `Conflict` for the workflow's screen. Or git refused for a
        reason that is not a collision, and that is an error carrying git's own words.

        **Work the target already holds still lands.** git answers "Already up to date", exits 0,
        and the head does not move - which is the port's own clause and the ordinary shape of a
        replayed run (§3.6), not a failure and not a conflict.

        The pre-check is a rule rather than a probe: a landing already pending means the run owes
        this target a `retry` or an `abort` it never made, and merging over one is how the previous
        hold's conflict would be reported as this landing's. It binds a resume, too, and says so
        loudly on purpose - a hold outlives the process that took it, so an invocation that finds
        one it did not take is the invocation that owes it a verb, and landing over it silently
        would throw away a collision somebody may be in the middle of resolving by hand.
        """
        if await self._held(target):
            raise InternalError(
                f"a landing into {target.branch!r} is already pending, and this run is asking to "
                f"land {source.branch!r} on top of it. Every path out of a conflicted landing owes "
                f"the target a retry or an abort, so AGL has lost track of a hold it took"
            )
        try:
            await self._git.run(
                *_MERGING, source.branch, cwd=target.path, refusal=UpstreamUnexpected
            )
        except UpstreamUnexpected:
            # git refused, and the two refusals it spells the same way are told apart by asking
            # what the target is now: held means this merge conflicted, and anything else means git
            # said no to something else and the error is the honest answer.
            if not await self._held(target):
                raise
            return IntegrationOutcome(
                conflict=collided(
                    await self._unresolved(target), source.branch, target.branch, target.path
                )
            )
        return IntegrationOutcome(head=await target.head())

    async def retry(self, target: Workspace) -> IntegrationOutcome:
        """Look again at the landing `target` is holding, and conclude it if it can be concluded.

        Called after something *outside this port* changed the situation, and this port has no
        opinion about what they did: it asks the index which paths are still unresolved, because
        that is git's own record of the question and the only one that is not a guess about what is
        inside a file. Still unresolved is the port's ordinary answer - a `Conflict` again, the
        target still held, the workflow deciding again - and the loop is ended by `abort`.

        Nothing unresolved means somebody staged a resolution, and the landing is concluded with
        the message git wrote when it stopped. What they staged is what goes in, which is the whole
        of this port's opinion about their work.

        **A landing has to be pending**, and the port says why the answer is `InternalError` rather
        than an outcome: `retry` is called only in answer to a conflicted outcome, so nothing
        pending means AGL lost track of a hold it took, and the two-case outcome has no honest
        spelling for "there was nothing to do". A person who finished the landing themselves lands
        here too, and `abort` is the tolerant one for their sake.
        """
        if not await self._held(target):
            raise InternalError(
                f"there is no landing pending in {target.branch!r}, so there is nothing to try "
                f"again. This is called only in answer to a conflicted outcome, and a target that "
                f"holds nothing means AGL lost track of a hold it took - or somebody finished the "
                f"landing by hand, which `abort` is the tolerant answer to"
            )
        still = await self._unresolved(target)
        if still:
            return IntegrationOutcome(conflict=unresolved(still, target.branch, target.path))
        await self._git.run(*_CONCLUDING, cwd=target.path, refusal=UpstreamUnexpected)
        return IntegrationOutcome(head=await target.head())

    async def abort(self, target: Workspace) -> None:
        """Give up on the pending landing, putting `target` back exactly where `land` found it.

        `git merge --abort` is that operation and the whole of it: the head goes back, the files
        the attempt combined go back with it, and what the attempt added is taken away - while
        anything that was in the checkout *before* the landing, a person's scratch file included,
        is left alone. That last part is why there is no `clean` here: "as it was before `land`" is
        not "as if nothing had ever happened", and the one place in AGL where a mistake destroys
        work rather than costing a re-run is close enough already.

        **Tolerant of there being nothing pending**, which is why the question is asked before
        anything is undone rather than after git has refused. A release after a crash is the
        ordinary case; so is a person who finished the held landing by hand, and reading this as
        "undo the last landing" would destroy their work. Doing nothing is the whole of the right
        answer there, and returning at all is the whole of the tolerance clause.

        Two runs racing to release one target could pass the check and then find the landing gone,
        and that is left as an error rather than swallowed: §3.4's lease serialises landings into
        one target, so a second releaser is a broken invariant and not a state to be tidied over.
        """
        if not await self._held(target):
            return
        await self._git.run(*_RELEASING, cwd=target.path, refusal=UpstreamUnexpected)

    async def _held(self, target: Workspace) -> bool:
        """Is a landing pending in this target? The one predicate, and the whole of the hold.

        Asked of the repository every time and cached nowhere - the module docstring argues why
        that is the deliverable rather than a detail. `answers` because this is one of git's
        exit-status questions, and `UpstreamUnexpected` for anything that is neither of the two:
        a repository that cannot say whether a landing is pending must not read as "no", which is
        the answer that would send `abort` away quietly and leave the target half-combined.
        """
        return await self._git.answers(
            *_PENDING, cwd=target.path, refusal=UpstreamUnexpected, timeout=_ASKING
        )

    async def _unresolved(self, target: Workspace) -> tuple[str, ...]:
        """Which paths the held landing has not resolved, in the port's own vocabulary.

        Run in the target's checkout, which is its worktree's root, so the listing covers the whole
        of it: `ls-files` reports what is at or under where it was run, and this is the only place
        it is run from. The reading is `_conflicts.py`'s and nothing here looks at the string.
        """
        return unmerged(
            await self._git.run(
                *_UNRESOLVED, cwd=target.path, refusal=UpstreamUnexpected, timeout=_ASKING
            )
        )
