"""What the `Fetcher` port's two answers promise about themselves, whichever fetcher built them.

`tests/contracts/fetch.py` holds what a fetcher owes; this holds what the values it hands back
refuse to be, because two of those refusals are what the rest of `agl get` leans on without
checking again. A file's path runs down from the workflow's own directory and nowhere else - so
placing the files is a join and never a question - and a commit is a full object id, so the
provenance written from it records a commit rather than a ref that has since moved. Both are
`InternalError`: a value that breaks either was built by a fetcher with a bug in it, and no
operator input can arrive that way.
"""

from dataclasses import FrozenInstanceError
from typing import Final
import pytest
from agl.ports.errors import InternalError, NotFoundError
from agl.ports.fetch import FetchedFile, FetchedWorkflow, RefusedWorkflow
from agl.ports.get_request import GetRequest, RequestedWorkflow

_SHA1: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

_SHA256: Final = "4f47eec66a0d318ba1f318c8d9d0648b6ef2ce60c57a3178fc5a20f7e7d1a730"

def _workflow() -> RequestedWorkflow:
    (workflow,) = GetRequest.parsed(["octo/hello/workflows/wf"]).workflows
    return workflow

@pytest.mark.parametrize("commit", [_SHA1, _SHA256])
def test_a_full_sha1_or_sha256_object_id_is_a_commit_a_fetched_workflow_accepts(
    commit: str,
) -> None:
    assert FetchedWorkflow(_workflow(), commit, {}).commit == commit

@pytest.mark.parametrize(
    "commit", ["", "HEAD", "v1.2.0", _SHA1[:7], _SHA1[:-1], _SHA1 + "0", _SHA1.upper()]
)
def test_a_commit_that_is_not_a_full_lowercase_object_id_is_refused_as_a_fetchers_bug(
    commit: str,
) -> None:
    """A ref can move, an abbreviation can become ambiguous and a respelling compares unequal."""
    with pytest.raises(InternalError, match="not a full object id"):
        FetchedWorkflow(_workflow(), commit, {})

@pytest.mark.parametrize(
    "path", ["", "/etc/passwd", "../outside", "a/../../b", "./a", "a//b", "a/", "a/."]
)
def test_a_file_path_that_would_climb_out_of_the_workflow_directory_is_refused(path: str) -> None:
    """Every path is joined onto the workflow's own directory, so none may lead anywhere else."""
    with pytest.raises(InternalError, match="runs down from the workflow's own directory"):
        FetchedWorkflow(_workflow(), _SHA1, {path: FetchedFile(b"")})

def test_nested_paths_and_names_outside_ascii_are_ordinary_file_paths() -> None:
    files = {"__init__.py": FetchedFile(b""), "prompts/café.md": FetchedFile(b"", executable=True)}

    assert dict(FetchedWorkflow(_workflow(), _SHA1, files).files) == files

def test_a_fetched_workflows_files_cannot_be_edited_once_it_is_built() -> None:
    """Copied and read-only: the mapping validated is the mapping every later reader sees."""
    handed = {"__init__.py": FetchedFile(b"one")}
    workflow = FetchedWorkflow(_workflow(), _SHA1, handed)

    handed["../escaped"] = FetchedFile(b"two")

    assert set(workflow.files) == {"__init__.py"}
    with pytest.raises(TypeError):
        workflow.files["../escaped"] = FetchedFile(b"two")  # type: ignore[index]

def test_a_refusal_that_says_nothing_is_refused_itself() -> None:
    """The reason is the whole of what a person is shown for a workflow that did not come back."""
    with pytest.raises(InternalError, match="says nothing"):
        RefusedWorkflow(_workflow(), NotFoundError())

def test_every_value_the_port_speaks_is_frozen_so_nothing_edits_one_after_it_was_checked() -> None:
    fetched = FetchedWorkflow(_workflow(), _SHA1, {})
    refused = RefusedWorkflow(_workflow(), NotFoundError("not there"))
    held = FetchedFile(b"")

    with pytest.raises(FrozenInstanceError):
        fetched.commit = "HEAD"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        refused.refusal = NotFoundError("elsewhere")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        held.executable = True  # type: ignore[misc]

def test_a_fetched_file_is_not_executable_unless_it_says_it_is() -> None:
    assert FetchedFile(b"#!/bin/sh\n").executable is False
