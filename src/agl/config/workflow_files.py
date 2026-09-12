import hashlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final
from agl.ports.errors import InputError

__all__ = ["content_hash", "digested", "digests", "in_bytecode_cache"]

# Importing a workflow makes CPython write its bytecode into this directory, beside the source it
# compiled and so inside the very directory the import was resolved from. Digest what is in there
# and a run changes the answer it was itself measured by: a map taken before a workflow's first
# import never matches the one taken after it, and nothing is ever resumable.
_BYTECODE: Final = "__pycache__"

# Finder leaves a `.DS_Store` in a folder it opens, so a directory only looked at would measure as
# changed. Names, not a rule: "anything dot-led" would stop seeing an edit to a workflow's own
# `.gitignore` or `.env` and replace it unasked, where a name missing here costs only a false alarm.
# Not `.git`, which replacing a copy deletes with it - `tests/test_update.py` pins that it is asked.
_WRITTEN_BY_FINDER: Final = frozenset({".DS_Store"})

_SEPARATOR: Final = "/"

# A name `iterdir` hands back carries lone surrogates wherever the filesystem held bytes that are
# not valid UTF-8, and `surrogatepass` is the one handler that encodes those back to the bytes they
# came from - so two such names stay two names here rather than collapsing onto one digest.
# `adapters/git/_snapshots.py` spells the same pair for the same reason.
_ENCODING: Final = "utf-8"
_SURROGATES: Final = "surrogatepass"

# The directory's own pyproject.toml is digested along with the rest of it, because the entry point
# written there is what decides which object a run of this workflow calls - change it and the name
# resolves somewhere else. `[project] version` sits in that same file and rides along, so bumping it
# alone is enough to refuse a resume that would otherwise have replayed. That is intended rather
# than an oversight: what no digest can do is tell which line of a file a reader calls load-bearing.
def digests(directory: Path) -> Mapping[str, str]:
    """Every file in a workflow's directory but bytecode and Finder's, by relative POSIX path."""
    found = dict(_walked(directory, ()))
    return {name: _digest(name, _content(found[name])) for name in sorted(found)}

def digested(files: Mapping[str, bytes]) -> Mapping[str, str]:
    """What `digests` answers for a directory holding exactly `files`, with nothing read."""
    return {
        name: _digest(name, files[name])
        for name in sorted(files)
        if not in_bytecode_cache(name) and name.rpartition(_SEPARATOR)[2] not in _WRITTEN_BY_FINDER
    }

def in_bytecode_cache(path: str) -> bool:
    """Whether a relative POSIX path lies inside a directory `digests` never walks into."""
    *directories, _ = path.split(_SEPARATOR)
    return _BYTECODE in directories

# A provenance file keeps this across upgrades of AGL, so it is a scheme every later AGL has to
# reproduce byte for byte - one that moved would read every workflow `agl get` placed as edited.
# `tests/config/test_workflow_files.py` holds it to one known answer.
def content_hash(measured: Mapping[str, str]) -> str:
    """One digest standing for a whole map of per-file digests, whatever order it was built in."""
    combined = hashlib.sha256()
    for name in sorted(measured):
        combined.update(measured[name].encode(_ENCODING))
    return combined.hexdigest()

def _walked(directory: Path, prefix: tuple[str, ...]) -> Iterator[tuple[str, Path]]:
    for entry in _listed(directory):
        if entry.is_file():
            if entry.name not in _WRITTEN_BY_FINDER:
                yield _SEPARATOR.join((*prefix, entry.name)), entry
        # A directory reached through a symlink is not descended into: a link naming an ancestor of
        # itself is a walk with no end, and a filesystem is free to hold one.
        elif entry.is_dir() and not entry.is_symlink() and entry.name != _BYTECODE:
            yield from _walked(entry, (*prefix, entry.name))

def _digest(name: str, content: bytes) -> str:
    spelled = name.encode(_ENCODING, _SURROGATES)
    digest = hashlib.sha256()
    digest.update(f"file {len(spelled)} {len(content)}\n".encode())
    digest.update(spelled)
    digest.update(content)
    return digest.hexdigest()

def _listed(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError as error:
        raise InputError(
            f"{directory} cannot be listed: {error}. AGL digests the files a workflow's own "
            f"directory holds, so that a resume can say whether the workflow it is about to "
            f"replay is still the one that recorded the run - and a directory it cannot read is a "
            f"question it cannot answer either way"
        ) from error

def _content(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise InputError(
            f"{path} cannot be read: {error}. It is one of the files in a workflow's own "
            f"directory that are digested - passing over the one that will not open would "
            f"answer with a digest saying the workflow is unchanged"
        ) from error
