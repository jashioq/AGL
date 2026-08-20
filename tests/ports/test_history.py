"""What `FileChange` promises: a change that reads correctly, or no change at all.

`History` itself is not touched here - not even a null implementation - for `test_agent.py`'s
reason: a suite that writes its own subject writes a subject that passes. The contract belongs to
the stage that writes the first real adapter.

That leaves two things, and both are genuine. **`ChangeKind`'s values are pinned by hand**, one at
a time, because a `StrEnum`'s value is what it looks like when it is written down and a step's
stored result may hold one - so a change to one should have to be typed twice. And **the pairing of
`kind` with `previous_path`** is the module's only validation, checked in both directions, because
each direction fails differently: a rename missing its old name is a change nobody can act on, and
a modification carrying one means whoever assembled it filled in a field they had not thought about.
"""

from dataclasses import FrozenInstanceError, fields

import pytest

from agl.ports.errors import InternalError
from agl.ports.history import ChangeKind, FileChange


def test_the_change_kinds_are_the_strings_a_stored_result_holds() -> None:
    """Pinned by hand. The absent fifth member is the design, so it is asserted and not assumed."""
    assert {member.name: member.value for member in ChangeKind} == {
        "ADDED": "added",
        "MODIFIED": "modified",
        "DELETED": "deleted",
        "RENAMED": "renamed",
    }
    assert not hasattr(ChangeKind, "UNMERGED"), "an unresolved conflict is a Conflict, elsewhere"


def test_a_change_that_is_not_a_rename_need_not_say_where_the_file_was() -> None:
    """Three of the four kinds have no previous path, which is what the default is for."""
    change = FileChange(path="src/agl/ports/history.py", kind=ChangeKind.MODIFIED)
    assert change.previous_path is None
    assert [field.name for field in fields(FileChange)] == ["path", "kind", "previous_path"]


def test_a_rename_carries_both_of_its_names() -> None:
    """Repository-relative, forward slashes, and the two names are the whole of a rename."""
    renamed = {
        "path": "src/agl/ports/history.py",
        "kind": ChangeKind.RENAMED,
        "previous_path": "src/agl/ports/the_old_name.py",
    }
    change = FileChange(**renamed)  # type: ignore[arg-type]
    assert change.previous_path == "src/agl/ports/the_old_name.py"
    assert change == FileChange(**renamed)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"path": "", "kind": ChangeKind.ADDED}, id="names no file"),
        pytest.param({"path": "a.py", "kind": ChangeKind.RENAMED}, id="renamed from nowhere"),
        pytest.param(
            {"path": "a.py", "kind": ChangeKind.RENAMED, "previous_path": ""},
            id="renamed from nothing",
        ),
        pytest.param(
            {"path": "a.py", "kind": ChangeKind.RENAMED, "previous_path": "a.py"},
            id="renamed to itself",
        ),
        pytest.param(
            {"path": "a.py", "kind": ChangeKind.MODIFIED, "previous_path": "b.py"},
            id="modified from somewhere else",
        ),
    ],
)
def test_a_change_that_does_not_read_as_one_is_refused(change: dict[str, object]) -> None:
    """`InternalError`, not `InputError`: an adapter assembled this out of what it read."""
    with pytest.raises(InternalError):
        FileChange(**change)  # type: ignore[arg-type]


def test_a_change_is_frozen() -> None:
    """A value: checked once on the way in, and not editable afterwards."""
    change = FileChange(path="a.py", kind=ChangeKind.ADDED)
    with pytest.raises(FrozenInstanceError):
        change.kind = ChangeKind.DELETED  # type: ignore[misc]
