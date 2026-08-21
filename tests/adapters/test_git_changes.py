"""The porcelain-code table §1.3 exists to contain, asserted whole and without a repository.

`_changes.py` is a pure function for exactly this reason: `FileStatus.code: str` carried git's raw
status letters across the `History` boundary so that every consumer of a changed file was reading
two characters out of one program's output, `ChangeKind` is the type that refuses it, and a type
refuses only what nothing routes around. So the value of the refusal is the narrowness of the one
place those letters are still allowed to exist - and the way to assert a place is to assert it
directly, rather than to arrange a repository per letter and hope the arrangement produced the one
that was wanted.

Separate from `test_git_history.py`, which covers the adapter that asks git the questions, because
that file sets `pytest.mark.asyncio` on every test in it: `asyncio_mode = "strict"` makes a missing
marker a silently skipped test, so the marker is a module-level statement there rather than eight
decorators anybody could forget one of. Nothing here is asynchronous, and nothing here starts a
process - which is the same seam the two source modules are split on.
"""

import pytest

from agl.adapters.git._changes import changes
from agl.ports.errors import UpstreamUnexpected
from agl.ports.history import ChangeKind, FileChange


def test_every_status_git_spells_becomes_one_kind_or_is_refused_outright() -> None:
    """The mapping, the two readings inside it, and the letters that get no reading at all.

    `A`, `D` and `M` are the port's own three and translate. The two that are readings are the
    interesting half: `T`, a file whose type changed, is one path present in both states with
    different content behind it, and `MODIFIED` is both the closest word the port has and a true
    one; `C`, a copy, has a destination that was not there before and a source it leaves untouched,
    so `ADDED` is accurate and what is lost is provenance, which this port has no vocabulary for.

    The refusals matter as much as the mappings. `U` is the unmerged state `ChangeKind` deliberately
    has no member for - "a state of an operation in flight", which `integration.py` reports as a
    `Conflict` - and a kind guessed here would reach a workflow through a step's stored result with
    nothing left on it to say it was a guess.
    """
    for code, kind in (
        ("A", ChangeKind.ADDED),
        ("D", ChangeKind.DELETED),
        ("M", ChangeKind.MODIFIED),
        ("T", ChangeKind.MODIFIED),
    ):
        assert changes(f"{code}\0one/file.txt\0") == (FileChange("one/file.txt", kind),), (
            f"the status {code!r} did not become the kind the port has for it"
        )
    assert changes("R100\0was/here.txt\0is/here.txt\0") == (
        FileChange("is/here.txt", ChangeKind.RENAMED, "was/here.txt"),
    ), "a rename carries both of its names or it is a modification wearing the wrong label"
    assert changes("C100\0source.txt\0copy.txt\0") == (FileChange("copy.txt", ChangeKind.ADDED),), (
        "a copy names the file that was not there before and does not claim to be a rename - "
        "FileChange pairs previous_path to RENAMED alone, in both directions"
    )

    for refused in ("U", "X", "B", "Z", "", "R1x0", "M100x", "100"):
        with pytest.raises(UpstreamUnexpected):
            changes(f"{refused}\0one/file.txt\0")


def test_a_stream_of_records_comes_back_as_the_changes_it_holds() -> None:
    """One flat stream, and a status that says how many paths belong to it.

    A record has no terminator of its own - only its fields do - so the parse keeps its place by
    knowing that `R` and `C` carry two names and everything else carries one. Losing that place is
    the failure this asserts against: a stream read one field out is a stream where every later path
    arrives as a status letter.
    """
    assert changes("") == (), "nothing changed, and an empty answer is what that is"
    assert changes("M\0a.txt\0A\0b.txt\0R100\0c.txt\0d.txt\0D\0e.txt\0") == (
        FileChange("a.txt", ChangeKind.MODIFIED),
        FileChange("b.txt", ChangeKind.ADDED),
        FileChange("d.txt", ChangeKind.RENAMED, "c.txt"),
        FileChange("e.txt", ChangeKind.DELETED),
    ), (
        "a stream holding four records, one of them a rename with two names in it, did not come "
        "back as those four changes"
    )


def test_a_record_that_runs_out_or_holds_no_name_is_refused_rather_than_shortened() -> None:
    """A changed file this adapter quietly dropped is a file a review step never sees.

    Every one of these is git having answered something this module cannot read, which is
    `UpstreamUnexpected` in that class's own words - the repository is fine and our reading of it is
    not, so the same call answers the same way. The failure worth refusing is the quiet one: a
    truncated stream read as a shorter answer looks exactly like a step that touched fewer files,
    and there is nothing downstream that could tell the difference.
    """
    for broken in (
        "M",
        "M\0",
        "R100\0only-one-name.txt\0",
        "M\0\0",
        "R100\0\0arrived.txt\0",
        "A\0first.txt\0M\0",
    ):
        with pytest.raises(UpstreamUnexpected):
            changes(broken)
