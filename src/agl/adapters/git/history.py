"""`GitHistory` - the real `History`: five questions about one repository's past, asked of git.

Where a run starts, what that resolved to, whether one state is already inside another, which files
differ between two states, and the same difference as a patch a person reads. Nothing here changes
anything, which is the port's design and is also why every invocation below is a read: no ref is
written, no index is touched, and the repository this is pointed at is the user's own checkout.

The runner is built here rather than injected, exactly as `workspace.py` builds one, because
`_runner.py` is this package's private plumbing (§3.4): the container hands over a repository and
each of the three git adapters over one repository builds the same runner from it.

## Plumbing, because the porcelain is somebody else's to configure

Both `changed_files` and `diff` ask `git diff-tree`, which is the interface git writes for programs,
and not `git diff`, which is the one it writes for people. The difference is not stylistic. A user
with `diff.external` set - a perfectly ordinary way to prefer a side-by-side viewer - turns `git
diff` into a program AGL has never heard of, and what comes back is not a unified patch at all but
whatever that program prints. `diff.renames = false` turns every move into a deletion and an
addition, `color.diff = always` puts terminal escapes into the string a model is about to read, and
none of the three is a setting the user was wrong to have. Plumbing reads none of them, so this
adapter answers the same way in every repository it is ever pointed at, and the one thing it does
want - rename detection - it asks for by name.

That is the line the flags below are chosen on: what would change *whether the answer is a patch at
all* is refused, and what only changes how one is spelled is left alone. A patch's prefixes, its
context width and how it renders a file that is not text are format, and §3.7's argument for handing
the patch over untouched is precisely that format is not this port's to invent.

## Renames are detected, and both halves of that are paid for

`_history_changes` accepts a move reported either way and argues at length that requiring detection
would be inventing a clause the port declines to make. It is right that the port does not require
it. This adapter does it anyway, for two reasons that are about AGL rather than about git.

The first is that `ChangeKind.RENAMED` and `FileChange.previous_path` exist. If the one
implementation that reads a real repository never produces them, they are vocabulary only a fake can
speak - and a fake saying something no real adapter can is exactly the drift §1.9 built contract
suites to prevent. The second is that `diff` and `changed_files` answer about one change and must
not describe two: git's patch shows a move as a rename, so a structured answer built with
`--no-renames` would report a deletion and an addition for the very thing the patch beside it calls
a rename, and a workflow branching on one while a reviewer reads the other would be looking at two
different accounts of one step.

**The cost is a threshold, and it is git's rather than one chosen here.** `--find-renames` with no
number is git's default of fifty percent similarity, so a file moved and rewritten past that point
is reported as the deletion and the addition it has become. That is a heuristic answering a question
that has no exact answer, and naming a number here would only move the arbitrariness into this file.
What it is not is a guess about *which files changed*: both paths are in the answer either way, and
the port's own consumers - filter, count, put in a prompt - are the ones the difference is smallest
for.

## `contains(x, x)` is `True`, argued from `clear` and not from git

git agrees, and that is a coincidence worth not resting on. The port's one consumer is §3.10's
`clear`, which deletes a run's line of work only when the base ref already holds it: a run whose
workflow committed nothing sits exactly at its base, has nothing to lose and nothing to keep, and
must still be tidied up - which happens only if a state is already inside itself. An implementation
answering `False` there would keep a stale branch for every run that did nothing, forever.

## `NotFoundError` from all five, for a name this repository does not hold

`refusal=NotFoundError` on every call, which is `_runner.py`'s way of saying that a deliberate "no"
from *this* question means the thing was not there. `changed_files` is the sharp one: "nothing
differs from a state that does not exist" is a plausible-looking answer and a lie, and the reason it
cannot be given here is that git is asked to name the two objects before it compares them, so a
made-up commit id is refused rather than treated as an empty tree.

`resolve` and `default_ref` restate that refusal in AGL's own words, and only those two, because
they are the two a person's typing reaches - `agl run --from nosuchbranch` is exit 3 and a sentence,
and "fatal: Needed a single revision" is not that sentence. The three that take ids take them out of
AGL's own records, where git's own reason is the more useful half of the message.

## `--end-of-options`, and what it is worth here specifically

`_runner.py` leaves this to the call site because where it goes depends on the subcommand, and this
is the package's clearest illustration of why it is not optional. `git diff-tree` accepts
`--output=<file>`, so a ref value spelled `--output=/etc/anything` is a *write* performed by a port
whose whole promise is that it changes nothing - argv discipline does not touch it, because the
value never went near a shell. With `--end-of-options` in front of the two revisions git refuses the
argument outright, and the refusal arrives as an ordinary `NotFoundError`. It goes after every
option and before the two revisions; `diff-tree` rejects its own flags if it comes any earlier.

## What is deliberately not here

**No cache.** Two of these over one repository are two `agl` invocations, and `_runner.py` holds no
state for the same reason. A memoised `resolve` would answer with a ref's meaning from before an
agent moved it.

**No shape check on what `resolve` answers.** That a commit id is forty or sixty-four characters of
lowercase hexadecimal is `run.py`'s `_check_sha`, in one place, and restating the rule here would be
a second copy of it free to disagree. What is checked is only that git said something at all.

**`_one` is four lines this package now holds twice.** `workspace.py` has the same helper for the
same one-line answers, and it is private there; sharing it would mean either editing a module this
deliverable does not own or a third module existing for one function. Four repeated lines is the
cheaper of the three.
"""

from pathlib import Path
from typing import Final

from agl.adapters.git._changes import changes
from agl.adapters.git._runner import GitRunner, unreadable
from agl.ports.errors import NotFoundError
from agl.ports.history import FileChange, History

__all__ = ["GitHistory"]


# A backstop for the four calls that read the repository's own data rather than walking a tree: a
# symbolic ref, a ref lookup, an ancestry question. The runner's default is sized for a checkout of
# a large repository, which makes it no guard at all on anything this small, and `_runner.py` says a
# call site that knows its operation's shape passes its own. The two that scale with how much
# changed keep the runner's default.
_ASKING: Final = 30.0

# The peel that makes `resolve` answer about a commit and not merely about a ref. An annotated tag
# names a tag object and a ref can name a tree; each of those has an id of exactly the right shape
# and neither is a state a run can be cut from, so the peel is what turns "this ref exists" into
# "this is the commit behind it". Composing it is not composing a *name* - the name arrived whole
# and the caller typed it - it is asking git a further question about whatever the name found.
_PEELED: Final = "^{commit}"

# Everything both change questions share: git's plumbing diff, recursed into subtrees, with rename
# detection asked for by name. `-r` has no long spelling in this subcommand. The module docstring
# argues every word of it.
_COMPARING: Final = ("diff-tree", "-r", "--find-renames")


class GitHistory(History):
    """`History` over one git repository, bound to it by construction.

    Constructed by `config/container.py` with the repository and nothing else, like every other
    adapter, and holding nothing past it: no cache, no open handle, no lock. Nothing here writes,
    so two of these over one repository - which is what two `agl` invocations are - need no
    arrangement between them.
    """

    def __init__(self, repository: Path) -> None:
        self._git = GitRunner(repository)

    async def default_ref(self) -> str:
        """The branch this repository's own `HEAD` names, in full. §3.9's `--from`, defaulted.

        §3.9 spells the default "the repo's default branch", and the branch `HEAD` names is the
        only default branch a repository records *about itself*: it is what a clone of it checks
        out, what `init` wrote when it was made, and what a bare copy of it would answer. The other
        candidate, `refs/remotes/origin/HEAD`, is a cached copy of a *second* repository's answer to
        this same question, and this port is bound to one repository and declines even the parameter
        that would let it ask about another.

        **In full, `refs/heads/main` rather than `main`**, and the `/` is why the port says this is
        a ref expression rather than one of `ids.py`'s names. A shortened branch name is ambiguous
        in a way the full ref is not: `rev-parse` resolves `refs/tags/<name>` before
        `refs/heads/<name>`, so a repository carrying a tag and a branch of one name would answer
        `resolve` with the tag - and a run would silently start from a state nobody chose. Handing
        on what `symbolic-ref` answered keeps the two members agreeing about which thing was meant.

        A detached `HEAD` names no branch, which is not a repository AGL can pick a default in;
        `NotFoundError` in words that say what to do instead, because exit 3 with "pass --from" is
        an answer and git's "ref HEAD is not a symbolic ref" is a fact about a data structure.
        """
        try:
            answer = await self._git.run(
                "symbolic-ref", "HEAD", refusal=NotFoundError, timeout=_ASKING
            )
        except NotFoundError as absent:
            raise NotFoundError(
                "this repository's HEAD names no branch - it is detached, or sitting on a state "
                "rather than on a line of work - so there is no default for a run to start from. "
                "Name one with `--from <ref>`"
            ) from absent
        return _one(answer, "a branch name")

    async def resolve(self, ref: str) -> str:
        """A ref expression to the full commit id it currently names. What pins `RunSpec.base_sha`.

        `rev-parse --verify` answers with one full object name or refuses, which is the whole of
        what this needs: unabbreviated because `run.py`'s `_check_sha` refuses an abbreviation, and
        one because a ref expression that names several states pins nothing.

        Peeled to a commit, so that a ref which exists and names something else - an annotated tag,
        a ref pointing at a tree - is refused here rather than handed on as an id no workspace can
        be cut from. The refusal is the same one a missing ref gets, and correctly: from a caller's
        side both are "this repository holds no state under that name".
        """
        try:
            answer = await self._git.run(
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{ref}{_PEELED}",
                refusal=NotFoundError,
                timeout=_ASKING,
            )
        except NotFoundError as absent:
            raise NotFoundError(
                f"{ref!r} names no commit in this repository. It is well-formed and this is where "
                f"a run would have started, so either it has not been created yet or it is spelled "
                f"differently here"
            ) from absent
        return _one(answer, "a commit id")

    async def contains(self, ancestor: str, descendant: str) -> bool:
        """Is `ancestor` already part of what `descendant` records? `clear`'s one question (§3.10).

        `merge-base --is-ancestor` is one of git's exit-status questions - 0 yes, 1 no - which is
        what `answers` is for, and anything else is a repository that could not answer rather than a
        third verdict. That distinction is the whole value of asking it this way: a made-up commit
        id exits 128 and raises `NotFoundError`, where a member that read any non-zero status as
        "no" would tell `clear` that unmerged work is unmerged for the one reason that does not mean
        that, and `clear` would keep the branch instead of tidying it - or, asked the other way
        round, delete it.

        Reflexive, because git and the port agree here for different reasons; the module docstring
        argues the port's, which is the one that binds.
        """
        return await self._git.answers(
            "merge-base",
            "--is-ancestor",
            "--end-of-options",
            ancestor,
            descendant,
            refusal=NotFoundError,
            timeout=_ASKING,
        )

    async def changed_files(self, base: str, head: str) -> tuple[FileChange, ...]:
        """Which files differ between two states, and how - in the port's words, never git's.

        The one call in AGL that produces a `ChangeKind`, and the reading of it is `_changes.py`'s
        alone: this member's whole job is to ask the question in a form that answers it exactly
        once per file and to hand the string over without looking at it.

        `--name-status -z` is that form. The status says what happened, `-z` ends every field with
        the one byte a path cannot hold, and `-r` is what makes the answer about files rather than
        about the directories they moved under.

        Directional and not normalised: `base` and `head` reach git in the order they were passed,
        so swapping them gives the inverse answer, which is what makes `ADDED` and `DELETED` mean
        anything at all.
        """
        return changes(
            await self._git.run(
                *_COMPARING,
                "--name-status",
                "-z",
                "--end-of-options",
                base,
                head,
                refusal=NotFoundError,
            )
        )

    async def diff(self, base: str, head: str) -> str:
        """The same change as a unified patch - the half a person or a model reads.

        Handed over exactly as git wrote it: not stripped, not re-wrapped, not parsed. §3.7's
        argument is that a unified patch is the one interchange format every code-review consumer
        already reads, so the value of this member is in having done nothing to it.

        The same `diff-tree` invocation as `changed_files` with `--patch` in place of
        `--name-status`, which is what makes the two agree about a move without either of them
        knowing what the other asked: one rename detection, one threshold, one answer told twice.

        Two identical states produce an empty string, because git prints nothing and there is
        nothing to add.
        """
        return await self._git.run(
            *_COMPARING, "--patch", "--end-of-options", base, head, refusal=NotFoundError
        )


def _one(answer: str, what: str) -> str:
    """git's one-line answer, stripped, or the error for an answer that is not one.

    The runner hands output back whole because a `-z` form's trailing NUL is data; a `rev-parse` is
    the other kind, where the newline is punctuation. An empty answer is `unreadable` rather than an
    empty string handed upwards, because a commit id nobody can use is worse the further it travels
    - §3.6 would write it into an entry and chain the next fingerprint off it.
    """
    stripped = answer.strip()
    if not stripped:
        raise unreadable(what, answer)
    return stripped
