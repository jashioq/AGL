"""`config/provenance.py`: the file `agl get` writes beside a workflow, and the hash inside it.

The file is the only account of where a placed workflow came from, and it is read back by code that
did not write it - so what is pinned here is the round trip, and every way a file that was edited,
truncated or written by some other version of AGL is refused rather than half-read. A refusal names
the file, because the file is the operator's to open.

Nothing it records is re-derived on reading. Owner, repository, ref and path go back through the
very types `agl get` parsed them into off the command line, so a value refused there is refused
here, in the same words; the default branch is `null`, which is what a ref of `None` means to those
types; and the key set is the format's only version, so a document with a key missing or one added
is refused whole.

**The hash is names and bytes, and only those.** The executable bit is left out on purpose: it is
not what a workflow's code is, and a volume that does not keep it - or a caller choosing modes of
its own - would otherwise read a workflow nobody touched as edited. `workflow_digests` in a run's
record leaves it out for the same reason, so "edited" means one thing in both places.
"""

import json
from pathlib import Path
from typing import Final
import pytest
from agl.config.provenance import (
    Provenance,
    fetched_hash,
    parsed_provenance,
    read_provenance,
    rendered,
)
from agl.ports.errors import InputError
from agl.ports.fetch import FetchedFile
from agl.ports.get_request import GetRequest, RequestedWorkflow
from agl.ports.home_layout import PROVENANCE_FILE

_SHA: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

_HASH: Final = "a" * 64

_WRITTEN: Final = ("owner", "repo", "path", "ref", "commit", "content_hash")

def _workflow(ref: str | None = "v1.2.0") -> RequestedWorkflow:
    """Parsed, so that its `spec` is the one `parsed_provenance` rebuilds: the argument alone."""
    at = "" if ref is None else f"@{ref}"
    (workflow,) = GetRequest.parsed([f"JasHioq/my.repo/workflows/mine/triage{at}"]).workflows
    return workflow

def _document(**changed: object) -> bytes:
    """A provenance file as AGL writes one, with the fields named here written over."""
    document = json.loads(rendered(Provenance(_workflow(), _SHA, _HASH)))
    document.update(changed)
    return json.dumps(document).encode()

def _refusal(content: bytes) -> str:
    with pytest.raises(InputError) as refused:
        parsed_provenance(Path("workflows/triage") / PROVENANCE_FILE, content)
    return str(refused.value)

# --- the round trip -------------------------------------------------------------------------------

@pytest.mark.parametrize("ref", ["v1.2.0", "release/1.0", "v1.0.0+build.5", _SHA, None])
def test_a_provenance_rendered_and_read_back_is_the_provenance_it_was(ref: str | None) -> None:
    provenance = Provenance(_workflow(ref), _SHA, _HASH)

    assert parsed_provenance(Path(PROVENANCE_FILE), rendered(provenance)) == provenance

def test_the_file_in_a_workflows_directory_reads_back_through_that_directory(
    tmp_path: Path,
) -> None:
    provenance = Provenance(_workflow(), _SHA, _HASH)
    (tmp_path / PROVENANCE_FILE).write_bytes(rendered(provenance))

    assert read_provenance(tmp_path) == provenance

def test_a_directory_holding_no_provenance_file_reads_back_as_none(tmp_path: Path) -> None:
    """What every workflow `agl new` wrote looks like: nothing to read, and nothing wrong."""
    assert read_provenance(tmp_path) is None

def test_the_file_is_one_json_object_holding_the_six_keys_in_written_order() -> None:
    """The default branch is `null`, a ref of `None` being what the request's own type calls it."""
    written = rendered(Provenance(_workflow(None), _SHA, _HASH))

    assert written.endswith(b"}\n")
    assert list(json.loads(written).items()) == [
        ("owner", "JasHioq"),
        ("repo", "my.repo"),
        ("path", "workflows/mine/triage"),
        ("ref", None),
        ("commit", _SHA),
        ("content_hash", _HASH),
    ]

def test_the_file_is_named_so_that_no_import_and_no_pyproject_reader_takes_it() -> None:
    """JSON and not TOML, so no reader of a project file opens it, and no module name at all."""
    stem, _, suffix = PROVENANCE_FILE.rpartition(".")

    assert suffix == "json"
    assert not stem.isidentifier()

# --- a file that was not written by this AGL, or was edited since ---------------------------------

@pytest.mark.parametrize("content", [b"", b"{not json", b"\xff\xfe{}", b"[]", b'"a string"'])
def test_a_file_that_is_not_a_json_object_is_refused_naming_the_file(content: bytes) -> None:
    said = _refusal(content)

    assert f"workflows/triage/{PROVENANCE_FILE}" in said

@pytest.mark.parametrize("kept", [_WRITTEN[:-1], (*_WRITTEN, "placed_at")])
def test_a_file_with_a_key_missing_or_one_added_is_refused_whole(kept: tuple[str, ...]) -> None:
    """The key set is the format's version: another set was written by another AGL, or by hand."""
    document = {key: json.loads(_document()).get(key, "2026-09-11") for key in kept}

    said = _refusal(json.dumps(document).encode())

    assert "another version of AGL or edited by hand" in said

@pytest.mark.parametrize(
    "changed",
    [
        {"owner": "has/slash"},
        {"repo": ".."},
        {"ref": ""},
        {"ref": 3},
        {"ref": "release//1.0"},
        {"path": "../escaped/triage"},
        {"path": "tools@v2/triage"},
        {"path": "workflows/not-a-name"},
        {"path": 3},
        {"commit": "7fd1a60"},
        {"commit": _SHA.upper()},
        {"content_hash": "not a digest"},
    ],
)
def test_a_value_the_command_line_would_refuse_is_refused_on_reading_it_back(
    changed: dict[str, object],
) -> None:
    (value,) = changed.values()

    said = _refusal(_document(**changed))

    assert f"workflows/triage/{PROVENANCE_FILE}" in said
    assert repr(value) in said

def test_a_provenance_file_that_cannot_be_opened_is_refused_naming_it(tmp_path: Path) -> None:
    (tmp_path / PROVENANCE_FILE).mkdir()

    with pytest.raises(InputError) as refused:
        read_provenance(tmp_path)

    assert str(tmp_path / PROVENANCE_FILE) in str(refused.value)

# --- the hash, measured before anything is placed -------------------------------------------------

def test_every_name_and_every_byte_of_the_files_is_in_the_hash() -> None:
    files = {"__init__.py": FetchedFile(b"one\n"), "prompts/review.md": FetchedFile(b"two\n")}
    renamed = {"__init__.py": files["__init__.py"], "prompts/other.md": files["prompts/review.md"]}
    edited = {**files, "prompts/review.md": FetchedFile(b"two!\n")}

    assert len({fetched_hash(files), fetched_hash(renamed), fetched_hash(edited)}) == 3

def test_the_executable_bit_is_no_part_of_the_hash() -> None:
    """Names and bytes only, which is also all a resume compares - see this module's docstring."""
    plain = {"run.sh": FetchedFile(b"#!/bin/sh\n", executable=False)}
    executable = {"run.sh": FetchedFile(b"#!/bin/sh\n", executable=True)}

    assert fetched_hash(plain) == fetched_hash(executable)
