""""What changed": `changed_files` and `diff`, the pair the port keeps together on purpose.

Split out of `history.py` along a line the port draws itself. Three of its five members answer where
a run starts, what that resolved to, and whether one state is already inside another; these two
answer what actually happened between two states, and the port pairs them explicitly - "one is for
deciding, the other is for reading. A review step puts this in a prompt; a workflow that wants to
know whether a step touched anything under `docs/` uses the other and does not parse this."

## No porcelain, and `diff`'s format is not this suite's to pin

`ChangeKind` exists because `FileStatus.code: str` used to carry one tool's raw status codes across
this boundary, so that every consumer of a changed file was reading two characters out of a
program's human-facing output. A suite that reintroduced that would defeat the type: nothing here
parses a status, matches a code, or knows what any implementation prints.

`diff` does answer with a `str`, and the format of that string is deliberately not asserted. What a
caller can rely on is asserted instead - that it is text, that it is not empty when something
changed, that it names every path `changed_files` named, and that two identical states leave nothing
to read. How a hunk is spelled, how a header is written and whether a rename is shown as one are
each a choice this port explicitly leaves to whoever implements it.

## Rename detection: required, or not?

**Not required, and this is the argument.** A pure rename below is accepted as *either* one
`RENAMED` carrying both names, or the `DELETED` and `ADDED` pair it is made of - and nothing else.

Rename detection is a similarity heuristic in every implementation that has one, with a threshold
nobody in this plan ever specified; a system that records moves explicitly has it for free, and one
comparing two snapshots of a tree has no way to produce it that is not guesswork. Requiring it here
would mean this suite inventing a promise the port declines to make: `changed_files` is careful to
say what it does *not* fix - "its order is the implementation's, and nothing here promises one" -
and nowhere says a move must be recognised as one. A suite that demanded it would refuse an honest
implementation for reporting, accurately, that one file went away and another arrived.

The cost is stated rather than hidden: **against an implementation that does not detect renames, the
`RENAMED` branch of that test never runs, and `ChangeKind.RENAMED` and `FileChange.previous_path` go
unexercised by this suite.** `history.py` lists it among the gaps.

What is required instead is the part every implementation owes either way, and it is not weak: both
names have to be accounted for. A move is two paths differing between the two states, and an answer
naming only the new one has lost a file the caller was asking about. That catches the real bug in
the neighbourhood - half-detected renames - without demanding the heuristic.

`HistoryContract` in `history.py` inherits this class. Implementers subclass that one, never this
one, and the `history`, `provider` and `base` fixtures these tests take are declared there.
"""

import pytest

from agl.ports.history import ChangeKind, FileChange, History
from agl.ports.workspace import Workspace, WorkspaceProvider

from ._workspace_files import (
    ALPHA,
    BETA,
    CHILD,
    GAMMA,
    LABEL,
    MOVED_FROM,
    MOVED_TO,
    assert_absent,
    body,
    delete,
    read,
    record,
    rename,
    write,
)


async def two_states(workspace: Workspace) -> tuple[str, str]:
    """Two recorded states an addition, a modification and a deletion apart.

    Three kinds in one pair because they are one question - "which files differ, and how" - and
    because an implementation that reports every difference as a modification, or that loses the
    file that is no longer there, is caught by the answer as a whole rather than by three separate
    ones that each look plausible on their own.
    """
    assert_absent(workspace, ALPHA, BETA, GAMMA)
    write(workspace, ALPHA, body("alpha, as first recorded"))
    write(workspace, GAMMA, body("gamma, which does not survive"))
    before = await record(workspace, "the state to be asked about from")

    write(workspace, ALPHA, body("alpha, edited"))
    delete(workspace, GAMMA)
    write(workspace, BETA, body("beta, which was not there before"))
    after = await record(workspace, "the state to be asked about to")

    assert before != after, (
        "two commits with different contents reported the same head, so there is no pair of "
        "states here to ask about"
    )
    return before, after


async def a_rename(workspace: Workspace) -> tuple[str, str]:
    """Two recorded states one move apart, with the file's contents untouched between them.

    Byte-for-byte identical and long enough to be distinctive, so that an implementation with a
    similarity heuristic is not being asked to make a close call: this is the easiest rename there
    is, and one that cannot see this one cannot see any.
    """
    assert_absent(workspace, MOVED_FROM, MOVED_TO)
    write(workspace, MOVED_FROM, body("a file that is about to be moved and not otherwise touched"))
    before = await record(workspace, "the state before the move")

    rename(workspace, MOVED_FROM, MOVED_TO)
    after = await record(workspace, "the state after the move")

    assert read(workspace, MOVED_TO) is not None and read(workspace, MOVED_FROM) is None, (
        "the working tree does not hold the moved file under its new name and only its new name, "
        "so this suite did not manage to build the move it is about to ask about"
    )
    assert before != after, "a move is a change, so the two states are two"
    return before, after


def by_path(changes: tuple[FileChange, ...]) -> dict[str, ChangeKind]:
    """The answer as a mapping, having first checked the two things every answer owes.

    A tuple, because the port says so and gives the reason - the answer is a value that can be
    held, compared and put in a step's result without a caller defending against it changing
    underneath them - and a list satisfies every other assertion in this module.

    One entry per path, because a file is one file: an implementation reporting a move as a rename
    *and* as the deletion it came from would double-count a path, and a consumer counting what a
    step touched would count it twice.

    Order is not asserted anywhere, here or elsewhere. The port declines to promise one, and a
    suite that pinned a sort would be pinning one tool's.
    """
    assert isinstance(changes, tuple), (
        f"changed_files answered with {type(changes).__name__}. It is a tuple so that the answer "
        f"is a value a step's result can hold - a caller that has to copy it before storing it is "
        f"a caller the port was written to spare"
    )
    seen: dict[str, ChangeKind] = {}
    for change in changes:
        assert isinstance(change, FileChange), (
            f"changed_files answered with a {type(change).__name__} among its changes, and the "
            f"port's answer is FileChange - the type that keeps a status code out of the framework"
        )
        assert change.path not in seen, (
            f"{change.path!r} appears twice in one answer, as {seen.get(change.path)} and as "
            f"{change.kind}. One file is one entry: a consumer filtering or counting what a step "
            f"touched has no way to know which of the two to believe"
        )
        seen[change.path] = change.kind
    return seen


class HistoryChangeContract:
    """`changed_files` and `diff`: the structured answer, the readable one, and their agreement.

    `pytestmark` is repeated on every contract class in this package rather than inherited from
    one of them: `asyncio_mode = "strict"` turns a missing marker into a silently skipped test,
    which is the one failure mode a contract suite must not have.
    """

    pytestmark = pytest.mark.asyncio

    async def test_changed_files_reports_what_happened_to_every_file_that_differs(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """Three of the four kinds, in one answer, asserted as a whole and not one at a time.

        As a whole because the failures worth catching are omissions and blurrings: an
        implementation that reports the deleted file as modified, or that answers only about files
        that still exist, produces an answer where each individual entry looks reasonable. An
        equality against the entire mapping is what refuses that.

        Nothing here says which order they arrive in, and nothing reads a status code: `ADDED`,
        `MODIFIED` and `DELETED` are the port's own vocabulary, which is the whole reason
        `ChangeKind` exists instead of the two-character code that used to cross this boundary.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        before, after = await two_states(workspace)

        changes = await history.changed_files(before, after)

        assert by_path(changes) == {
            ALPHA: ChangeKind.MODIFIED,
            BETA: ChangeKind.ADDED,
            GAMMA: ChangeKind.DELETED,
        }, (
            f"between two states one file was edited, one was created and one was removed, and "
            f"changed_files answered {by_path(changes)}. The direction is base to head, which is "
            f"what makes ADDED and DELETED mean anything, and a file that is no longer there is "
            f"still a file that differs between the two states"
        )

    async def test_swapping_base_and_head_gives_the_inverse_answer_rather_than_an_error(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """"Directional, `base` to `head`" - and the port says swapping is a question, not a
        mistake.

        Which is the whole of what makes `ADDED` and `DELETED` mean anything: they are not
        properties of a file, they are what happened to it *in that direction*. An implementation
        that normalised the two arguments, or that refused an order it did not expect, would leave
        a caller unable to ask "what would undoing this look like".
        """
        workspace = await provider.open(LABEL, CHILD, base)
        before, after = await two_states(workspace)

        changes = await history.changed_files(after, before)

        assert by_path(changes) == {
            ALPHA: ChangeKind.MODIFIED,
            BETA: ChangeKind.DELETED,
            GAMMA: ChangeKind.ADDED,
        }, (
            f"asked in the other direction, changed_files answered {by_path(changes)}. Swapping "
            f"the arguments gives the inverse answer rather than an error: the file that arrived "
            f"is the one that goes away, and the one that went away is the one that arrives"
        )

    async def test_two_identical_states_have_no_changed_files_and_nothing_to_read(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """Nothing differs, so there is nothing to report and nothing to put in front of a reader.

        The empty tuple is the port's own type answering honestly; an implementation that raised
        here would make every consumer wrap a comparison of a step's before and after in a `try`,
        and a step whose agent changed nothing is explicitly not an error anywhere in this plan.

        `diff` is asserted to hold nothing rather than to *be* `""`, because pinning the exact
        string would pin whether a trailing newline is part of an empty patch - which is format,
        and format is not this suite's. "Nothing a person would read" is the promise.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        assert_absent(workspace, ALPHA)
        write(workspace, ALPHA, body("one state"))
        head = await record(workspace, "one state")

        assert await history.changed_files(head, head) == (), (
            "a state compared with itself reported changed files, so something other than the "
            "difference between the two arguments is being reported"
        )
        text = await history.diff(head, head)
        assert isinstance(text, str), (
            f"diff answered with {type(text).__name__}. It is a unified patch as text - the one "
            f"interchange format every code-review consumer already reads - and a review step "
            f"puts it straight into a prompt"
        )
        assert not text.strip(), (
            f"a state compared with itself produced {text[:200]!r} to read. Nothing differs, so "
            f"there is nothing to show a person or a model"
        )

    async def test_a_move_is_reported_as_a_rename_or_as_the_pair_it_is_made_of(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """Two legal answers, and this suite requires neither of them over the other.

        Detection is a heuristic and the port never asks for one, so an implementation that reports
        a move as a deletion and an addition is being accurate rather than lazy, and refusing it
        would be this suite inventing a clause. This module's docstring makes that argument at
        length and states its cost: against such an implementation the `RENAMED` branch below never
        runs, and the member goes unexercised.

        What is required of both answers is that no file goes missing. A move changes two paths -
        one stops existing and one starts - and an answer mentioning only the new name has dropped
        a file the caller asked about. Where a rename *is* reported, `previous_path` has to be the
        name it came from: `FileChange.__post_init__` already refuses a rename that carries no
        previous path, so the bug left for a test is a rename that carries the wrong one, or a move
        reported under a kind that has nowhere to put the old name at all.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        before, after = await a_rename(workspace)

        changes = await history.changed_files(before, after)

        kinds = by_path(changes)
        named = {change.path for change in changes} | {
            change.previous_path for change in changes if change.previous_path is not None
        }
        assert named == {MOVED_FROM, MOVED_TO}, (
            f"a file was moved from {MOVED_FROM!r} to {MOVED_TO!r} and the answer names {named}. "
            f"Both paths differ between the two states - one stopped existing and one started - "
            f"so an answer that mentions only one of them has lost a file that was asked about"
        )

        renames = [change for change in changes if change.kind is ChangeKind.RENAMED]
        if not renames:
            assert kinds == {MOVED_TO: ChangeKind.ADDED, MOVED_FROM: ChangeKind.DELETED}, (
                f"a move was not reported as a rename, which is allowed, and was reported as "
                f"{kinds} rather than as the deletion and addition it is made of. An "
                f"implementation without rename detection still owes an accurate account of both "
                f"paths"
            )
            return

        assert kinds == {MOVED_TO: ChangeKind.RENAMED}, (
            f"a move was reported as a rename and as {kinds} besides. A rename is the whole of "
            f"what happened to that file, and reporting the deletion alongside it counts one file "
            f"twice"
        )
        assert renames[0].previous_path == MOVED_FROM, (
            f"a rename to {MOVED_TO!r} says it came from {renames[0].previous_path!r}. A rename "
            f"carries both of its names or it is a modification wearing the wrong label, which is "
            f"why FileChange refuses one without a previous path at all"
        )

    async def test_diff_is_text_that_names_every_path_changed_files_reported(
        self, history: History, provider: WorkspaceProvider, base: str
    ) -> None:
        """The readable half of one change, agreeing with the structured half about what changed.

        The two are paired rather than alternatives, so they cannot describe different things: a
        review step reads this while a workflow branches on the other, and a patch that omits a
        file the structured answer reported would send a reviewer a change that is not the change.

        That is the whole of what is asserted about the text. Not the header, not the hunk markers,
        not the context lines, not whether a rename appears as one - a unified patch is handed over
        untouched precisely so that no implementation has to render its output into a taxonomy this
        port invented, and a suite that pinned the spelling would be inventing one anyway.
        """
        workspace = await provider.open(LABEL, CHILD, base)
        before, after = await two_states(workspace)

        text = await history.diff(before, after)

        assert isinstance(text, str), (
            f"diff answered with {type(text).__name__}, and the port's answer is text a person or "
            f"a model reads"
        )
        assert text.strip(), (
            "three files differ between these two states and diff answered with nothing to read. "
            "It is what a review step puts in front of a model, and an empty patch says the step "
            "did nothing"
        )
        missing = [
            path
            for path in by_path(await history.changed_files(before, after))
            if path not in text
        ]
        assert not missing, (
            f"changed_files reported {missing} and the patch does not name them. The two answer "
            f"about one change - one for deciding, one for reading - and a reviewer handed a "
            f"patch that is missing a file reviews something other than what happened"
        )
