import hashlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final
from agl.ports.errors import InputError

__all__ = ["digests"]

# Importing a workflow makes CPython write its bytecode into this directory, beside the source it
# compiled and so inside the very directory the import was resolved from. Digest what is in there
# and a run changes the answer it was itself measured by: a map taken before a workflow's first
# import never matches the one taken after it, and nothing is ever resumable.
_BYTECODE: Final = "__pycache__"

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
    """Every file in a workflow's directory, keyed by POSIX path relative to it and digested."""
    found = dict(_walked(directory, ()))
    return {name: _digest(name, found[name]) for name in sorted(found)}

def _walked(directory: Path, prefix: tuple[str, ...]) -> Iterator[tuple[str, Path]]:
    for entry in _listed(directory):
        if entry.is_file():
            yield "/".join((*prefix, entry.name)), entry
        # A directory reached through a symlink is not descended into: a link naming an ancestor of
        # itself is a walk with no end, and a filesystem is free to hold one.
        elif entry.is_dir() and not entry.is_symlink() and entry.name != _BYTECODE:
            yield from _walked(entry, (*prefix, entry.name))

def _digest(name: str, path: Path) -> str:
    spelled = name.encode(_ENCODING, _SURROGATES)
    content = _content(path)
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
            f"{directory} cannot be listed: {error}. AGL digests every file a workflow's own "
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
            f"directory, every one of which is digested - passing over the one that will not open "
            f"would answer with a digest saying the workflow is unchanged"
        ) from error
