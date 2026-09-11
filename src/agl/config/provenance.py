import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.config.workflow_files import content_hash, digested, digests
from agl.ports.errors import InputError
from agl.ports.fetch import FetchedFile
from agl.ports.get_request import RepositoryAtRef, RequestedWorkflow

__all__ = [
    "PROVENANCE_FILE",
    "Provenance",
    "fetched_hash",
    "parsed_provenance",
    "placed_hash",
    "read_provenance",
    "rendered",
]

# JSON, which no import statement resolves and no reader of a pyproject.toml opens, and led by a dot
# the way `api.py`'s `.agl-trees` is: AGL's bookkeeping, in a directory of the workflow's own files.
PROVENANCE_FILE: Final = ".agl-provenance.json"

_OWNER: Final = "owner"
_REPO: Final = "repo"
_PATH: Final = "path"
_REF: Final = "ref"
_COMMIT: Final = "commit"
_CONTENT_HASH: Final = "content_hash"

# In the order the file is written in, and the file's only version: a document holding any other
# set of keys was written by some other AGL or by hand, and is refused rather than read around.
_KEYS: Final = (_OWNER, _REPO, _PATH, _REF, _COMMIT, _CONTENT_HASH)

_ENCODING: Final = "utf-8"

_HEXADECIMAL: Final = frozenset("0123456789abcdef")
# A git object id: sha1 is 40 characters of lowercase hexadecimal, sha256 is 64.
_COMMIT_LENGTHS: Final = frozenset({40, 64})
_DIGEST_LENGTH: Final = 64

@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a placed workflow came from: what was asked for, what that got, and a hash of it."""

    workflow: RequestedWorkflow
    """Its repository's ref is the one asked for, `None` asking for the default branch."""

    commit: str
    """The full object id of the commit the placed files were taken from."""

    content_hash: str
    """`placed_hash` of the directory as `agl get` wrote it, so any other answer is an edit."""

    def __post_init__(self) -> None:
        if len(self.commit) not in _COMMIT_LENGTHS or not _HEXADECIMAL.issuperset(self.commit):
            raise InputError(
                f"{_COMMIT} {self.commit!r} is not a full object id: expected 40 characters of "
                f"lowercase hexadecimal (sha1) or 64 (sha256), which is what names the one commit "
                f"a download was taken from"
            )
        if len(self.content_hash) != _DIGEST_LENGTH or not _HEXADECIMAL.issuperset(
            self.content_hash
        ):
            raise InputError(
                f"{_CONTENT_HASH} {self.content_hash!r} is not a sha256 hexdigest: expected "
                f"{_DIGEST_LENGTH} characters of lowercase hexadecimal"
            )

def rendered(provenance: Provenance) -> bytes:
    """The provenance file's bytes: one JSON object, a key to a line, closed by a newline."""
    repository = provenance.workflow.repository
    document = {
        _OWNER: repository.owner,
        _REPO: repository.repo,
        _PATH: provenance.workflow.directory,
        _REF: repository.ref,
        _COMMIT: provenance.commit,
        _CONTENT_HASH: provenance.content_hash,
    }
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(_ENCODING)

def read_provenance(directory: Path) -> Provenance | None:
    """The provenance file in a workflow's directory, `None` where `agl get` wrote none there."""
    path = directory / PROVENANCE_FILE
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise InputError(f"{path} cannot be read: {error}") from error
    return parsed_provenance(path, content)

def parsed_provenance(path: Path, content: bytes) -> Provenance:
    """`content` as a provenance file, refused as `read_provenance` would refuse one at `path`."""
    try:
        document: object = json.loads(content.decode(_ENCODING))
    except ValueError as error:
        raise InputError(_unreadable(path, f"it is not UTF-8 JSON - {error}")) from error
    if not isinstance(document, dict):
        raise InputError(_unreadable(path, f"it holds a {type(document).__name__}, not an object"))
    if set(document) != set(_KEYS):
        raise InputError(_unreadable(path, _mismatched(document)))
    # The ref and the path are checked by the types `agl get` parsed them into in the first place,
    # so a value that one would refuse on the command line is refused here in the same words.
    try:
        repository = RepositoryAtRef(
            _text(document, _OWNER), _text(document, _REPO), _ref(document)
        )
        directory = _text(document, _PATH)
        workflow = RequestedWorkflow(repository, directory, f"{repository}/{directory}")
        return Provenance(workflow, _text(document, _COMMIT), _text(document, _CONTENT_HASH))
    except InputError as refused:
        raise InputError(_unreadable(path, str(refused))) from refused

def placed_hash(directory: Path) -> str:
    """The content hash of a placed workflow's directory, measured as it stands on disk now."""
    return _hashed(digests(directory))

def fetched_hash(files: Mapping[str, FetchedFile]) -> str:
    """The content hash `files` will have once they are placed, measured before they are."""
    return _hashed(digested({path: file.content for path, file in files.items()}))

# The provenance file holds the hash, so a hash that counted it would have to contain itself, and a
# directory measured from disk would never match the one recorded - every workflow read as edited.
# `tests/config/test_inspection.py` places a workflow and measures it back to hold this.
def _hashed(measured: Mapping[str, str]) -> str:
    return content_hash(
        {path: digest for path, digest in measured.items() if path != PROVENANCE_FILE}
    )

def _text(document: Mapping[str, object], key: str) -> str:
    value = document[key]
    if not isinstance(value, str):
        raise InputError(f"{key} is {value!r}, and it is written as a string")
    return value

def _ref(document: Mapping[str, object]) -> str | None:
    value = document[_REF]
    if value is not None and not isinstance(value, str):
        raise InputError(f"{_REF} is {value!r}, and it is a string, or null for the default branch")
    return value

def _mismatched(document: Mapping[str, object]) -> str:
    missing = [key for key in _KEYS if key not in document]
    unknown = sorted(key for key in document if key not in _KEYS)
    return (
        f"its keys are not a provenance file's: missing {missing}, unexpected {unknown}. The file "
        f"AGL writes holds {', '.join(_KEYS)} and nothing else, so this one was written by another "
        f"version of AGL or edited by hand"
    )

def _unreadable(path: Path, problem: str) -> str:
    return (
        f"{path} is not a provenance file AGL can read: {problem}. `agl get` writes that file "
        f"beside a workflow it places, recording where the workflow came from"
    )
