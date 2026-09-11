import io
import stat
import tarfile
import tempfile
import unicodedata
import zlib
from collections.abc import Buffer, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from agl.ports.errors import (
    AglError,
    DeniedError,
    InputError,
    NotFoundError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)
from agl.ports.fetch import FetchAnswer, FetchedFile, FetchedWorkflow, RefusedWorkflow
from agl.ports.get_request import Fetch, RepositoryAtRef, RequestedWorkflow
from agl.ports.run import checked_text

__all__ = ["refused", "unpacked"]

type Received = Callable[[int], bytes]

_SEPARATOR: Final = "/"

_UNWALKABLE: Final = frozenset({"", ".", ".."})

_NUL: Final = "\x00"

# zlib's window for a gzip wrapper, header and trailer both checked: 16 added to the largest window.
_GZIP: Final = 16 + zlib.MAX_WBITS

_CHUNK: Final = 65536

# Where `git archive` records the commit it archived, and codeload's archives carry it - observed:
# the full 40-character sha, in the pax global header `tarfile` hands back as `pax_headers`.
_COMMIT: Final = "comment"

# GitHub names every commit by its SHA-1, forty characters of lowercase hexadecimal.
_SHA_LENGTH: Final = 40
_SHA_CHARACTERS: Final = frozenset("0123456789abcdef")

_STAGING: Final = "agl-get-"

_MEBIBYTE: Final = 1024 * 1024
_MOST_HELD: Final = 64 * _MEBIBYTE

_RECORDED: Final = (
    "and `agl run` records every file of a workflow by name, in a record that refuses one"
)

class _Truncated(Exception):
    """The download stopped before gzip's own end-of-stream marker, however tidily it stopped."""

class _Inflated(io.RawIOBase):
    """The download as gzip inflates it, ending only where gzip's own trailer says it ends."""

    def __init__(self, received: Received) -> None:
        super().__init__()
        self._received = received
        self._inflater = zlib.decompressobj(wbits=_GZIP)
        self.taken = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer, /) -> int:
        target = memoryview(buffer).cast("B")
        while not self._inflater.eof:
            data = self._inflater.unconsumed_tail
            if not data:
                data = self._received(_CHUNK)
                self.taken += len(data)
            if not data:
                raise _Truncated
            try:
                inflated = self._inflater.decompress(data, len(target))
            except zlib.error as error:
                raise tarfile.ReadError(f"it is not gzip data: {error}") from error
            if inflated:
                target[: len(inflated)] = inflated
                return len(inflated)
        return 0

@dataclass
class _Wanted:
    """One workflow's share of a walk: whether it is there, where its files went, any refusal."""

    workflow: RequestedWorkflow

    present: bool = False

    a_directory: bool = True

    refusal: AglError | None = None

    files: dict[str, str] = field(default_factory=dict)
    """Each file's path below the workflow's directory, and its name in the archive."""

    spellings: dict[str, str] = field(default_factory=dict)

    held: int = 0

    def below(self, inside: Sequence[str]) -> tuple[str, ...] | None:
        """The segments of an entry below this workflow's directory, or None for one elsewhere."""
        within = self.workflow.directory.split(_SEPARATOR)
        if list(inside[: len(within)]) != within:
            return None
        return tuple(inside[len(within) :])

    def take(self, member: tarfile.TarInfo, below: tuple[str, ...]) -> None:
        self.present = True
        if self.refusal is not None:
            return
        if not below:
            if member.issym() or member.islnk():
                self.refusal = DeniedError(_linked(self.workflow, "", member))
            elif not member.isdir():
                self.a_directory = False
            return
        relative = _SEPARATOR.join(below)
        if member.issym() or member.islnk():
            self.refusal = DeniedError(_linked(self.workflow, relative, member))
        elif (unrecordable := _unrecordable(self.workflow, relative)) is not None:
            self.refusal = DeniedError(unrecordable)
        else:
            self._remember_spelling(relative)
            if self.refusal is None and member.isreg():
                self.held += member.size
                self.files[relative] = member.name
                if self.held > _MOST_HELD:
                    self.refusal = DeniedError(_too_large(self.workflow))

    def answer(self, commit: str, staging: Path) -> FetchAnswer:
        if self.refusal is not None:
            return RefusedWorkflow(self.workflow, self.refusal)
        if not self.present:
            return RefusedWorkflow(self.workflow, NotFoundError(_absent(self.workflow, commit)))
        if not self.a_directory:
            return RefusedWorkflow(self.workflow, NotFoundError(_not_a_directory(self.workflow)))
        try:
            files = {path: _file_at(staging / name) for path, name in self.files.items()}
        except OSError as error:
            return RefusedWorkflow(self.workflow, UpstreamUnavailable(_unwritten(self, error)))
        return FetchedWorkflow(self.workflow, commit, files)

    # APFS, what a Mac formats a volume as unless somebody chose otherwise, folds case and Unicode
    # normalisation both, so two names this tells apart would be extracted into one file.
    def _remember_spelling(self, relative: str) -> None:
        segments = relative.split(_SEPARATOR)
        for depth in range(1, len(segments) + 1):
            spelled = _SEPARATOR.join(segments[:depth])
            folded = unicodedata.normalize("NFC", spelled.casefold())
            earlier = self.spellings.setdefault(folded, spelled)
            if earlier != spelled:
                self.refusal = DeniedError(_colliding(self.workflow, earlier, spelled))
                return

def refused(fetch: Fetch, refusal: AglError) -> tuple[FetchAnswer, ...]:
    """Every workflow in one fetch refused for one reason, which is what a failed download is."""
    return tuple(RefusedWorkflow(workflow, refusal) for workflow in fetch.workflows)

def unpacked(fetch: Fetch, received: Received, host: str) -> tuple[FetchAnswer, ...]:
    """Each workflow `fetch` asks for, taken out of the gzip-compressed tar `received` reads."""
    try:
        staging = tempfile.TemporaryDirectory(prefix=_STAGING, ignore_cleanup_errors=True)
    except OSError as error:
        return refused(fetch, UpstreamUnavailable(_unstaged(fetch.repository, error)))
    with staging:
        return _walked(fetch, received, host, Path(staging.name))

def _walked(
    fetch: Fetch, received: Received, host: str, staging: Path
) -> tuple[FetchAnswer, ...]:
    repository = fetch.repository
    inflated = _Inflated(received)
    stream = io.BufferedReader(inflated)
    wanted = [_Wanted(workflow) for workflow in fetch.workflows]
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            problem = _problem_walking(archive, wanted, staging)
            commit = archive.pax_headers.get(_COMMIT)
        while problem is None and stream.read(_CHUNK):
            pass
    except _Truncated:
        return refused(fetch, UpstreamUnavailable(_cut_short(host, repository, inflated.taken)))
    except tarfile.FilterError as filtered:
        problem = f"tarfile's data filter refused an entry in it - {filtered}"
        return refused(fetch, UpstreamUnexpected(_unmade(host, repository, problem)))
    except tarfile.TarError as error:
        return refused(fetch, UpstreamUnexpected(_unreadable(host, repository, error)))
    if problem is not None:
        return refused(fetch, UpstreamUnexpected(_unmade(host, repository, problem)))
    if commit is None or len(commit) != _SHA_LENGTH or not _SHA_CHARACTERS.issuperset(commit):
        return refused(fetch, UpstreamUnexpected(_unmade(host, repository, _uncommitted(commit))))
    return tuple(one.answer(commit, staging) for one in wanted)

def _problem_walking(
    archive: tarfile.TarFile, wanted: Sequence[_Wanted], staging: Path
) -> str | None:
    top: str | None = None
    for member in archive:
        segments = member.name.split(_SEPARATOR)
        if _UNWALKABLE.intersection(segments) or _NUL in member.name:
            return (
                f"it holds an entry named {member.name!r}, and git records no absolute path and "
                f"no empty, '.' or '..' segment in one"
            )
        if top is None:
            top = segments[0]
        elif segments[0] != top:
            return (
                f"its entries do not share one top-level directory - {top!r} and {segments[0]!r} "
                f"- where an archive codeload makes holds exactly one"
            )
        takers: list[_Wanted] = []
        for one in wanted:
            below = one.below(segments[1:])
            if below is None:
                continue
            one.take(member, below)
            if below and one.refusal is None:
                takers.append(one)
        if takers:
            _extract(archive, member, takers, staging)
    return None if top is not None else "it holds no entry at all"

def _extract(
    archive: tarfile.TarFile, member: tarfile.TarInfo, takers: Sequence[_Wanted], staging: Path
) -> None:
    try:
        archive.extract(member, staging, filter="data")
    except OSError as error:
        for one in takers:
            one.refusal = UpstreamUnavailable(_unwritten(one, error))

def _file_at(path: Path) -> FetchedFile:
    return FetchedFile(path.read_bytes(), executable=bool(path.stat().st_mode & stat.S_IXUSR))

def _uncommitted(commit: str | None) -> str:
    if commit is None:
        return (
            f"it names no commit - git records the one it archived in the archive's pax header, "
            f"as {_COMMIT!r}, and that is the only account of which commit these files are"
        )
    return f"the commit it names, {commit!r}, is not a full {_SHA_LENGTH}-character sha"

def _located(workflow: RequestedWorkflow) -> str:
    return f"{workflow.directory!r} in {workflow.repository}"

def _absent(workflow: RequestedWorkflow, commit: str) -> str:
    return (
        f"{workflow.repository} has no directory {workflow.directory!r} at commit "
        f"{commit}: the path is matched exactly as it was written, from the repository's root "
        f"down and with case counting"
    )

def _not_a_directory(workflow: RequestedWorkflow) -> str:
    return f"{_located(workflow)} is not a directory, and a workflow is one"

def _linked(workflow: RequestedWorkflow, relative: str, member: tarfile.TarInfo) -> str:
    what = (
        f"a symbolic link to {member.linkname!r}" if member.issym() else "a hard link"
    )
    where = f"holds {relative!r}, {what}" if relative else f"is {what}"
    return (
        f"{_located(workflow)} {where}, and a workflow is placed as regular files alone - a link "
        f"points outside what was downloaded as easily as inside it"
    )

# `tarfile` decodes a name that is not UTF-8 into lone surrogates, and `checked_text` is the one
# refusal of them - the same check the record of a run's workflow files is held to.
def _unrecordable(workflow: RequestedWorkflow, relative: str) -> str | None:
    try:
        checked_text(
            relative, f"{_located(workflow)} holds {relative!r}, whose name", cost=_RECORDED
        )
    except InputError as refused:
        return str(refused)
    return None

def _colliding(workflow: RequestedWorkflow, earlier: str, later: str) -> str:
    return (
        f"{_located(workflow)} holds both {earlier!r} and {later!r}, which differ only in case "
        f"or in how an accent is encoded - on a case-insensitive volume, a Mac's unless somebody "
        f"chose otherwise, the two are one file"
    )

def _too_large(workflow: RequestedWorkflow) -> str:
    return (
        f"{_located(workflow)} holds more than {_MOST_HELD // _MEBIBYTE} MiB of files, which is "
        f"more than AGL takes for one workflow: code and prompts come nowhere near it, so a "
        f"directory that size is carrying something else"
    )

def _unwritten(one: _Wanted, error: OSError) -> str:
    return f"{_located(one.workflow)} could not be unpacked on this machine: {error}"

def _unstaged(repository: RepositoryAtRef, error: OSError) -> str:
    return (
        f"AGL could not make a temporary directory to unpack {repository} into: {error}. "
        f"Nothing from it is used"
    )

def _cut_short(host: str, repository: RepositoryAtRef, taken: int) -> str:
    return (
        f"the download of {repository} from {host} ended after {taken} bytes, before the archive "
        f"did - the connection closed early, or something between here and {host} cut it short. "
        f"Nothing from it is used, and the same command may well work if it is run again"
    )

def _unreadable(host: str, repository: RepositoryAtRef, error: tarfile.TarError) -> str:
    return (
        f"what {host} sent for {repository} is not a gzip-compressed tar archive AGL can read: "
        f"{error}. A proxy or a captive portal answering in {host}'s place does this, and "
        f"nothing from it is used"
    )

def _unmade(host: str, repository: RepositoryAtRef, problem: str) -> str:
    return (
        f"what {host} sent for {repository} is not an archive git makes: {problem}. Nothing from "
        f"it is used - an archive that breaks one of git's own rules vouches for none of its files"
    )
