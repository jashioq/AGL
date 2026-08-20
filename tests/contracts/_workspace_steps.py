"""What an already-provisioned workspace owes: where it is, what it is called, and the three verbs.

Split out of `workspace.py` along a line the port draws itself. `WorkspaceProvider` makes and
unmakes isolated places; `Workspace` is "one isolated checkout, already provisioned: where it is,
what it is called, and the three things a step does to it". Those three - `head`, `commit_all` and
`restore` - are what §3.6's replay is made of, and they are here together because a test for any one
of them has to use the other two to see anything at all: a commit is visible as a head that moved,
and a restore is visible as a head that moved back and a file that came back with it.

Two of these tests are the reason the deliverable exists.

**`restore` leaves nothing behind.** Stage 2 collapsed reset-and-clean into one method so that
"restored but not cleaned" is a state no caller can reach by forgetting a line. The test therefore
dirties a workspace in both ways at once - a tracked file edited, and two files that were never
recorded, one of them inside a directory that did not exist - because an implementation that resets
tracked files and stops passes every weaker version of this test, and untracked leavings are the
exact case the method exists for.

**`commit_all` is a no-op when nothing is dirty.** The port says so in as many words, and it is what
lets §3.3's framework do one predictable thing at the end of every effect step without inspecting
whether anything moved. It is also, through this interface, the only way to see that a workspace is
*clean*: there is deliberately no `is_dirty`, so "committing again returns the same head" is what
"nothing was left behind" looks like from outside.

`WorkspaceContract` in `workspace.py` inherits this class. Implementers subclass that one, never
this one, and the `provider` and `base` fixtures these tests take are declared there.
"""

import pytest

from agl.ports.workspace import WorkspaceProvider

from ._workspace_files import (
    ALPHA,
    AWKWARD_MESSAGE,
    CACHE_DIR,
    CACHED,
    CHILD,
    LABEL,
    NESTED,
    SCRATCH,
    SIBLING,
    TRACKED,
    assert_absent,
    body,
    is_directory,
    read,
    record,
    write,
)


class WorkspaceStepContract:
    """`path`, `branch`, `head`, `commit_all`, `restore` - one checkout and what is done to it.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_path_is_an_absolute_directory_that_does_not_move_while_the_workspace_is_open(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """Absolute for `AgentTask.workspace`'s reason, and settled at provisioning.

        Absolute because a relative path resolves against whatever directory a subprocess happens
        to start in, and this is the value an agent is pointed at and a verifier runs its build in.
        A directory because that is what both of those do with it.

        Settled is asserted across the two members that change the world underneath it: a commit
        and a restore both move the head, and neither is allowed to move the place. `path` is a
        property rather than a call precisely because it does not change while the workspace is
        open, and an implementation that recomputed it per access is one a caller could not hand
        to a long-running agent.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        where = workspace.path

        assert where.is_absolute(), (
            f"a workspace reported {str(where)!r}, which is relative. It is what an AgentTask and "
            f"a Verifier are pointed at, and a relative path resolves against whatever directory "
            f"the process that received it happens to have started in"
        )
        assert where.is_dir(), (
            f"a workspace reported {str(where)!r}, which is not a directory. An agent runs in it "
            f"and a build runs in it, so provisioning has to have left one there"
        )

        write(workspace, TRACKED, body("something to record"))
        head = await record(workspace, "one state")
        await workspace.restore(head)

        assert workspace.path == where, (
            "a workspace's path changed under a commit and a restore. It is settled at "
            "provisioning, which is why it is a property and not a question - a step hands it to "
            "an agent once and the agent is still in it when the step ends"
        )

    async def test_branch_is_the_opaque_name_this_one_line_of_work_carries(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """A non-empty name, one per line of work, and the same one after the head has moved.

        Nothing here compares it to `tree_layout.run_branch` or `tree_layout.worktree_branch`, and
        that is the clause rather than an omission: the port says a workspace reports the name it
        actually carries rather than the name today's scheme would compute for it, so a run
        provisioned under one naming scheme keeps its name when the scheme changes. A suite that
        recomputed the expected name would be asserting the opposite.

        What is left is what a caller can rely on. It is a string, it is not empty - the framework
        records it and prints it, and neither is possible with nothing - three different lines of
        work carry three different names, and committing does not rename one.
        """
        run = await provider.open(LABEL, None, base)
        child = await provider.open(LABEL, CHILD, base)
        sibling = await provider.open(LABEL, SIBLING, base)

        for workspace in (run, child, sibling):
            assert isinstance(workspace.branch, str) and workspace.branch, (
                f"a workspace reported a branch of {workspace.branch!r}. The framework records it "
                f"in the run's own record and prints it for a person to push, and neither of "
                f"those can be done with nothing"
            )
        names = {run.branch, child.branch, sibling.branch}
        assert len(names) == 3, (
            f"the run's own workspace and its two children report {names} between them, and three "
            f"lines of work have three names - work landed on one of them is invisible to the "
            f"others until somebody lands it, which two sharing a name could not be"
        )

        named = child.branch
        write(child, TRACKED, body("committed"))
        await record(child, "one state")
        assert child.branch == named, (
            "a workspace's branch changed when its head moved. It is the name the line of work is "
            "published under, not the state it is at - that is what `head` answers"
        )

    async def test_commit_all_records_what_is_dirty_moves_the_head_and_leaves_nothing_behind(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """A new head, `head()` agreeing with it, and a workspace that is clean afterwards.

        Everything dirty, with no path argument and no staging step - so the file inside a
        directory that did not exist is recorded too, which is what "the workspace is the unit of
        isolation" means when an agent has been writing wherever it liked.

        "Clean afterwards" has no direct spelling here, because the port refuses an `is_dirty` and
        gives its reason. The clause it does have is that `commit_all` is a no-op when nothing is
        dirty, returning the unchanged head - so committing a second time and getting the same
        head back is what a clean workspace looks like from outside, and an implementation that
        left something uncommitted answers with a second, different head.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        assert_absent(workspace, TRACKED, NESTED)
        start = await workspace.head()

        write(workspace, TRACKED, body("recorded"))
        write(workspace, NESTED, body("recorded from a directory that did not exist"))
        recorded = await workspace.commit_all("implement T-01")

        assert recorded != start, (
            f"committing a dirty workspace answered with the head it started from, {start!r}. A "
            f"step's entry records this value and a later step hands it back to `restore`, so a "
            f"head that did not move is work no replay can ever get back to"
        )
        assert await workspace.head() == recorded, (
            "`head()` disagrees with what `commit_all` just answered. They are the same value "
            "asked for two ways, and §3.6 writes one of them into the entry it then resets to"
        )
        assert await workspace.commit_all("nothing is left to record") == recorded, (
            "committing twice in a row answered with two different heads, so the first commit "
            "left something behind. `commit_all` records *everything* dirty - there is no path "
            "argument and no staging step - and is a no-op when nothing is"
        )
        assert read(workspace, TRACKED) == body("recorded"), "and the work is still in the tree"
        assert read(workspace, NESTED) == body("recorded from a directory that did not exist")

    async def test_committing_a_workspace_with_nothing_dirty_answers_with_the_unchanged_head(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """§3.6's exact sentence, and the whole reason §3.3 does not have to look before it commits.

        Every effect step ends with this call whether or not the agent changed anything, because
        the alternative is the framework inspecting whether the head moved and branching on what
        the role declared - a branch §3.3 deliberately does not have. A step whose agent changed
        nothing is not an error and is not a special case: it records the head it started from and
        replay carries on from there.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        start = await workspace.head()

        assert await workspace.commit_all("nothing happened here") == start, (
            f"committing a workspace with nothing dirty answered with something other than the "
            f"head it was already at, {start!r}. The framework calls this at the end of every "
            f"effect step without asking whether anything moved, so an agent that changed nothing "
            f"must leave a head a replay can chain from rather than an empty state of its own"
        )
        assert await workspace.head() == start, "and nothing was recorded on the way past"

    async def test_a_commit_message_is_the_workflow_s_own_words_and_is_taken_as_written(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """"implement T-01" is domain vocabulary, and domain vocabulary is prose.

        The message carries quotes, an ampersand, a pipe, a semicolon, `$(...)`, a blank line and
        two non-ASCII scripts - not to be difficult, but because a workflow author writes the
        sentence that describes the work and §3.3 narrowed the charset of *names* precisely so that
        argv discipline would not be the only thing standing between an invented string and
        something that later grows a shell. Names got narrower; messages did not, so this is where
        an implementation that pastes one into a command line comes apart.

        What is *not* asserted is that the message was stored, or that a reader later sees it.
        Neither port reads a message back - `History` has no member for one, deliberately - so the
        clause this suite can see is that the message is accepted as written and the commit happens.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        start = await workspace.head()
        write(workspace, TRACKED, body("work worth a sentence"))

        recorded = await workspace.commit_all(AWKWARD_MESSAGE)

        assert recorded != start, (
            "a commit under a message holding ordinary prose punctuation did not move the head. "
            "The message is the workflow author's own words - an implementation that refuses, "
            "escapes or truncates them is refusing the one argument it was told not to interpret"
        )
        assert await workspace.head() == recorded

    async def test_restore_puts_a_tracked_file_back_and_removes_what_was_never_recorded(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """One method, both halves, and the second half is the one that gets forgotten.

        §3.3 is explicit that moving the head alone is not enough, because untracked files survive
        it - and untracked leavings are the exact case this exists for: a reviewer's scratch file,
        an agent's cache directory, a half-written patch. So the workspace is dirtied in both ways
        at once. An implementation that resets tracked files and stops passes a test that only
        edits a tracked file, and the two leavings below are different shapes on purpose: one
        beside the tracked files, one inside a directory that was not there before it.

        §3.6 and §3.3 reach this same primitive at two moments - before re-running a step whose
        entry is missing, and on the way out of a step that passed no `commit=` - and neither of
        them looks at what it is throwing away first.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        assert_absent(workspace, TRACKED, SCRATCH, CACHED)
        write(workspace, TRACKED, body("as recorded"))
        head = await record(workspace, "the state to come back to")

        write(workspace, TRACKED, body("edited by a step that then crashed"))
        write(workspace, SCRATCH, body("a reviewer's scratch file"))
        write(workspace, CACHED, body("an agent's cache directory"))

        await workspace.restore(head)

        assert read(workspace, TRACKED) == body("as recorded"), (
            "a tracked file edited since the recorded head is still edited after a restore, so "
            "the working tree was not put back at all"
        )
        assert read(workspace, SCRATCH) is None, (
            f"{SCRATCH} was never recorded and survived a restore. Putting the head back is not "
            f"enough - untracked files survive that, which is exactly why this method is one verb "
            f"doing both halves and is named so that nobody goes looking for the missing 'clean'"
        )
        assert read(workspace, CACHED) is None, (
            f"{CACHED} was never recorded and survived a restore. It sits inside a directory that "
            f"was not there either, which is the half an implementation deleting untracked files "
            f"without descending into new directories leaves behind - an agent's cache directory "
            f"is named in the port as the case this exists for"
        )
        assert not is_directory(workspace, CACHE_DIR), (
            f"{CACHE_DIR} was not in the recorded state and is still a directory afterwards. "
            f"`restore` removes everything that was not in `head`, and a directory nothing "
            f"recorded is something that was not in it"
        )
        assert await workspace.head() == head, "and the head is the one it was asked for"

    async def test_restore_moves_the_head_back_across_a_commit_it_is_throwing_away(
        self, provider: WorkspaceProvider, base: str
    ) -> None:
        """§3.6's reset-before-rerun: `last_good` may be several states behind where the tree is.

        A crashed attempt leaves no entry, so the next run resets to the last head it recorded and
        starts clean - and an attempt that got as far as committing before it died leaves a head
        the replay has to move *back* past, not merely a dirty tree to tidy. `restore` does not
        care what it is throwing away, and this is the shape of what it throws away.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        assert_absent(workspace, TRACKED, ALPHA)
        write(workspace, TRACKED, body("first"))
        first = await record(workspace, "the last good state")
        write(workspace, TRACKED, body("second"))
        write(workspace, ALPHA, body("second"))
        second = await record(workspace, "an attempt that is about to be discarded")
        assert first != second, "two commits with different contents are two states"

        await workspace.restore(first)

        assert await workspace.head() == first, (
            f"restoring to {first!r} left the workspace at something else. `head` changes under "
            f"`restore` - the port says so - and §3.6 chains the next fingerprint off this value"
        )
        assert read(workspace, TRACKED) == body("first"), "the file is back at the restored state"
        assert read(workspace, ALPHA) is None, (
            "a file that arrived in the discarded commit is still in the tree. Everything that was "
            "not in the restored head goes, whether it was recorded in a later state or never "
            "recorded at all"
        )
