"""What `GitHubFetcher` makes of an archive: every one an honest far side never sends, and links.

`tests/adapters/test_github_fetcher.py` covers the port and the network; this file covers the bytes
once they have arrived. Each archive is built in memory, served by `instruments.codeload` on
127.0.0.1, and read by the real adapter - so every refusal below is the adapter's own, reached the
way a download from codeload would reach it.

**Two kinds of refusal, and which one a test expects is the assertion.** An archive that breaks a
rule git itself keeps - a name climbing out of its directory, a device, two top-level directories,
no commit - says nothing trustworthy about any file in it, so the whole download is refused
`UpstreamUnexpected`, every workflow with it. A workflow holding something git does allow but a
placed workflow may not - a link, two names a case-insensitive volume merges, more than the cap - is
refused alone, `DeniedError`, and a sibling from the same download still comes back. Several tests
ask for that sibling for exactly that reason.

**Which guard answers each hostile archive is deliberate, and proved rather than assumed.** A name
with an empty, `.` or `..` segment is refused by the adapter's own walk before anything is
extracted, and that includes `wf/../../evil`, which `tarfile`'s data filter would let through
because it lands inside the directory being extracted into. A device or a FIFO is refused by the
data filter, named explicitly on the extraction: nothing in the walk looks at an entry's type beyond
links, so the device test below is the filter's alone - with `filter="fully_trusted"` the FIFO is
extracted and the workflow comes back without it. A truncated or corrupted gzip stream is refused
by the adapter's inflating reader, because `tarfile`'s stream mode, measured, reads an archive whose
gzip trailer is missing or whose checksum is wrong as though nothing were amiss.
"""

import tarfile
import tempfile
import unicodedata
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final
import pytest
from agl.adapters.github.fetcher import GitHubFetcher
from agl.ports.errors import DeniedError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.fetch import FetchAnswer, FetchedFile
from agl.ports.get_request import RepositoryAtRef
from contracts.fetch import COMMIT, fetch_of, fetched, refused
from instruments.codeload import Codeload, Entry, archive, directory, link, regular, special, tree

pytestmark = pytest.mark.asyncio

_HELLO: Final = RepositoryAtRef("octo", "hello", None)

_TOP: Final = "hello-HEAD"

_WORKFLOW: Final = (b"async def wf(run):\n    ...\n", False)
_SIBLING: Final = (b"async def sibling(run):\n    ...\n", False)

_MEBIBYTE: Final = 1024 * 1024

@pytest.fixture
def codeload() -> Iterator[Codeload]:
    """A fresh stand-in per test, so no test reads another's requests."""
    with Codeload() as stand_in:
        yield stand_in

def _repository(*extra: Entry) -> list[Entry]:
    """`wf` and `sibling`, each a workflow directory at the root, followed by `extra`."""
    return [*tree(_TOP, {"wf/__init__.py": _WORKFLOW, "sibling/__init__.py": _SIBLING}), *extra]

async def _served(
    codeload: Codeload, body: bytes, *specs: str
) -> tuple[FetchAnswer, ...]:
    codeload.serves(_HELLO.owner, _HELLO.repo, "HEAD", body)
    return await GitHubFetcher(codeload.url).fetch(fetch_of(_HELLO, *specs))

async def _answers(
    codeload: Codeload, entries: Sequence[Entry], *specs: str, commit: str | None = COMMIT
) -> tuple[FetchAnswer, ...]:
    return await _served(codeload, archive(entries, commit=commit), *specs)

def _refused_whole(answers: Sequence[FetchAnswer], expected: str) -> None:
    """Every workflow refused with one `UpstreamUnexpected`, whose message says `expected`."""
    first, *rest = (refused(answer).refusal for answer in answers)
    assert all(refusal is first for refusal in rest), "one download refused for several reasons"
    assert isinstance(first, UpstreamUnexpected), f"refused with {first!r}"
    assert expected in str(first), str(first)

def _refused_alone(answers: Sequence[FetchAnswer], expected: str) -> None:
    """`wf` refused `DeniedError` saying `expected`, and `sibling` back with its one file."""
    wf, sibling = answers
    refusal = refused(wf).refusal
    assert isinstance(refusal, DeniedError), f"refused with {refusal!r}"
    assert expected in str(refusal), str(refusal)
    assert dict(fetched(sibling).files) == {"__init__.py": FetchedFile(_SIBLING[0])}

# --- Bytes that are not an archive git made -----------------------------------------------------

async def test_a_body_that_is_not_gzip_at_all_is_refused_as_something_else_answering(
    codeload: Codeload,
) -> None:
    """A captive portal's page, served with a 200, is the ordinary way this happens."""
    answers = await _served(codeload, b"<html>sign in to the hotel wifi</html>", "wf,sibling")

    refusal = refused(answers[0]).refusal
    assert isinstance(refusal, UpstreamUnexpected)
    assert "is not a gzip-compressed tar archive" in str(refusal)

@pytest.mark.parametrize("cut", [1, 8, 20, 200])
async def test_a_gzip_stream_cut_anywhere_is_refused_as_cut_short_however_tidily_it_ends(
    codeload: Codeload, cut: int
) -> None:
    """Served whole under its own length, so nothing at the HTTP layer looks wrong at all.

    `tarfile`'s stream mode was measured reading an archive with its last eight bytes missing - the
    gzip trailer, which is the checksum and the length - as complete, and one cut inside a later
    entry as an archive that simply ended there. The first hands back files nothing verified; the
    second reports a directory as not there when it was never received. So the adapter inflates
    for itself and refuses any stream that stops before gzip's own end-of-stream.
    """
    whole = archive(_repository(), commit=COMMIT)
    body = whole[:-cut]

    answers = await _served(codeload, body, "wf,sibling")

    for answer in answers:
        refusal = refused(answer).refusal
        assert isinstance(refusal, UpstreamUnavailable)
        assert f"ended after {len(body)} bytes, before the archive did" in str(refusal)

@pytest.mark.parametrize(("offset", "check"), [(-6, "incorrect data check"), (-2, "length check")])
async def test_a_gzip_stream_whose_trailer_disagrees_with_its_contents_is_refused(
    codeload: Codeload, offset: int, check: str
) -> None:
    """The checksum and the length gzip ends with, each flipped, and each read by stream mode."""
    body = bytearray(archive(_repository(), commit=COMMIT))
    body[offset] ^= 0xFF

    answers = await _served(codeload, bytes(body), "wf,sibling")

    refusal = refused(answers[0]).refusal
    assert isinstance(refusal, UpstreamUnexpected) and check in str(refusal)

async def test_an_archive_that_names_no_commit_is_refused_rather_than_guessed_at(
    codeload: Codeload,
) -> None:
    """The pax header's commit is the one account of which commit the files are, observed.

    The directory name is `<repo>-<ref as asked>` and names no commit unless a sha was asked for,
    and asking the API instead would spend a rate-limited call to learn what the archive should
    have said - so an archive without one is not one codeload made.
    """
    answers = await _answers(codeload, _repository(), "wf,sibling", commit=None)

    _refused_whole(answers, "it names no commit")

@pytest.mark.parametrize(
    "commit", ["7fd1a60", "v1.2.0", "7FD1A60B01F91B314F59955A4E4D4E80D8EDF11D"]
)
async def test_a_commit_that_is_not_a_full_lowercase_sha_is_refused_rather_than_recorded(
    codeload: Codeload, commit: str
) -> None:
    """An abbreviated sha stops being unique as a repository grows, and a ref is not a commit."""
    answers = await _answers(codeload, _repository(), "wf,sibling", commit=commit)

    _refused_whole(answers, f"the commit it names, {commit!r}, is not a full 40-character sha")

async def test_an_archive_whose_entries_share_no_one_top_directory_is_refused_whole(
    codeload: Codeload,
) -> None:
    """The top directory is stripped whatever it is called, so there has to be exactly one."""
    entries = [*_repository(), directory("other-HEAD"), regular("other-HEAD/wf/x.py", b"")]

    answers = await _answers(codeload, entries, "wf,sibling")

    _refused_whole(answers, "do not share one top-level directory - 'hello-HEAD' and 'other-HEAD'")

@pytest.mark.parametrize(
    ("commit", "said"),
    [(COMMIT, "AGL can read: end of file header"), (None, "it holds no entry at all")],
)
async def test_an_archive_holding_no_entry_at_all_is_refused_whole(
    codeload: Codeload, commit: str | None, said: str
) -> None:
    """Not even the top directory, which is nothing a repository at a commit is archived as.

    `tarfile` refuses one that has a global header and nothing after it on its own; without the
    header it reads an empty archive happily, and the walk is what refuses it.
    """
    answers = await _answers(codeload, [], "wf,sibling", commit=commit)

    _refused_whole(answers, said)

@pytest.mark.parametrize(
    "name",
    [
        "../escaped.txt",
        "/abs.txt",
        f"{_TOP}/wf/../../evil",
        f"{_TOP}//wf/x",
        f"{_TOP}/./wf/x",
        f"{_TOP}/wf/{'a' * 120}\x00b",
    ],
)
async def test_a_name_git_could_not_have_recorded_refuses_the_whole_archive_before_extracting(
    codeload: Codeload, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No empty, `.` or `..` segment and no leading `/`, anywhere in the archive.

    `wf/../../evil` is the case the data filter would not catch - it resolves inside the directory
    being extracted into - and a leading `/` the data filter strips rather than refuses. Both are
    refused here before a byte is written, which the empty staging area afterwards shows.
    """
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    answers = await _answers(codeload, _repository(regular(name, b"x")), "wf,sibling")

    _refused_whole(answers, f"it holds an entry named {name!r}")
    assert list(tmp_path.iterdir()) == []

@pytest.mark.parametrize(
    "kind",
    [tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE],
    ids=["character-device", "block-device", "fifo"],
)
async def test_a_device_or_a_fifo_under_a_workflow_is_refused_by_the_data_filter(
    codeload: Codeload, kind: bytes
) -> None:
    """The data filter's own refusal, named on the extraction rather than left to a default."""
    answers = await _answers(codeload, _repository(special(f"{_TOP}/wf/thing", kind)), "wf,sibling")

    _refused_whole(answers, "tarfile's data filter refused an entry in it")

async def test_a_device_nowhere_near_a_workflow_asked_for_is_never_extracted_or_judged(
    codeload: Codeload,
) -> None:
    """Only the directories asked for are extracted, so the rest of a repository is not read."""
    answers = await _answers(
        codeload, _repository(special(f"{_TOP}/elsewhere/fifo", tarfile.FIFOTYPE)), "wf,sibling"
    )

    assert [len(fetched(answer).files) for answer in answers] == [1, 1]

# --- What a workflow may hold -------------------------------------------------------------------

@pytest.mark.parametrize("target", ["../../../../etc/passwd", "/etc/passwd", "__init__.py"])
async def test_a_symbolic_link_under_a_workflow_refuses_it_and_spares_its_sibling(
    codeload: Codeload, target: str
) -> None:
    """Out, absolute or pointing at the workflow's own file: a placed workflow is regular files."""
    answers = await _answers(codeload, _repository(link(f"{_TOP}/wf/sneaky", target)), "wf,sibling")

    _refused_alone(answers, f"holds 'sneaky', a symbolic link to {target!r}")

async def test_a_hard_link_under_a_workflow_refuses_it_as_a_symbolic_one_would(
    codeload: Codeload,
) -> None:
    """git records none, so one arriving says the archive was made some other way."""
    entry = link(f"{_TOP}/wf/again", f"{_TOP}/wf/__init__.py", hard=True)

    answers = await _answers(codeload, _repository(entry), "wf,sibling")

    _refused_alone(answers, "holds 'again', a hard link")

async def test_a_workflow_directory_that_is_itself_a_link_is_refused_as_one(
    codeload: Codeload,
) -> None:
    """The path asked for is a link, so there is no directory at it for anything to come from."""
    entries = [*tree(_TOP, {"sibling/__init__.py": _SIBLING}), link(f"{_TOP}/wf", "sibling")]

    answers = await _answers(codeload, entries, "wf,sibling")

    _refused_alone(answers, "is a symbolic link to 'sibling'")

@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("README", "readme"),
        ("prompts/a.md", "Prompts/b.md"),
        (unicodedata.normalize("NFC", "café.md"), unicodedata.normalize("NFD", "café.md")),
    ],
)
async def test_two_names_one_case_insensitive_volume_would_merge_refuse_their_workflow(
    codeload: Codeload, first: str, second: str
) -> None:
    """Two files git keeps apart, which a Mac's volume extracts into one - so neither is trusted."""
    entries = _repository(regular(f"{_TOP}/wf/{first}", b"1"), regular(f"{_TOP}/wf/{second}", b"2"))

    answers = await _answers(codeload, entries, "wf,sibling")

    _refused_alone(answers, "which differ only in case or in how an accent is encoded")

async def test_a_file_whose_name_is_not_utf8_refuses_its_workflow(codeload: Codeload) -> None:
    """A name `agl run` could never record, since the record of a workflow's files refuses one."""
    entries = _repository(regular(f"{_TOP}/wf/caf\udce9.md", b"latin-1, not UTF-8"))

    answers = await _answers(codeload, entries, "wf,sibling")

    _refused_alone(answers, "which is a surrogate: UTF-8 has no encoding for one at all")

async def test_a_workflow_holding_more_than_sixty_four_mebibytes_is_refused_alone(
    codeload: Codeload,
) -> None:
    """A bound on what is held in memory at once, which no workflow's code comes anywhere near."""
    entries = _repository(regular(f"{_TOP}/wf/weights.bin", bytes(64 * _MEBIBYTE + 1)))

    answers = await _answers(codeload, entries, "wf,sibling")

    _refused_alone(answers, "holds more than 64 MiB of files")

async def test_a_name_this_machine_cannot_write_refuses_its_workflow_and_spares_the_rest(
    codeload: Codeload,
) -> None:
    """A segment past 255 bytes is one no common volume stores, so it cannot be placed either."""
    entries = _repository(regular(f"{_TOP}/wf/{'n' * 300}", b""))

    answers = await _answers(codeload, entries, "wf,sibling")

    wf, sibling = answers
    refusal = refused(wf).refusal
    assert isinstance(refusal, UpstreamUnavailable)
    assert "could not be unpacked on this machine" in str(refusal)
    assert fetched(sibling).files

@pytest.mark.parametrize(
    ("mode", "executable"),
    [(0o4755, True), (0o744, True), (0o644, False), (0o611, False)],
    ids=["setuid-0o4755", "owner-only-0o744", "plain-0o644", "others-only-0o611"],
)
async def test_whether_a_file_comes_back_executable_is_its_owners_execute_bit_alone(
    codeload: Codeload, mode: int, executable: bool
) -> None:
    """The data filter's rule: setuid is dropped, and execute bits without the owner's go too."""
    entries = _repository(regular(f"{_TOP}/wf/tool", b"#!/bin/sh\n", mode=mode))

    answers = await _answers(codeload, entries, "wf,sibling")

    assert fetched(answers[0]).files["tool"].executable is executable

async def test_a_workflow_nested_inside_another_asked_for_comes_back_inside_both(
    codeload: Codeload,
) -> None:
    """Two names, so two workflows, and the inner one's files are the outer one's too."""
    entries = tree(_TOP, {"wf/__init__.py": _WORKFLOW, "wf/inner/__init__.py": _SIBLING})

    outer, inner = await _answers(codeload, entries, "wf", "wf/inner")

    assert set(fetched(outer).files) == {"__init__.py", "inner/__init__.py"}
    assert set(fetched(inner).files) == {"__init__.py"}

# --- The staging directory ----------------------------------------------------------------------

async def test_the_directory_unpacked_into_is_gone_afterwards_whether_it_worked_or_not(
    codeload: Codeload, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extraction is not atomic, so it happens somewhere that is removed on every way out.

    The second download refuses on an entry after the workflow's first file was already written,
    which is the case that leaves debris wherever an extraction is not thrown away whole.
    """
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    worked = await _answers(codeload, _repository(), "wf,sibling")
    failed = await _answers(
        codeload, _repository(special(f"{_TOP}/wf/zz", tarfile.FIFOTYPE)), "wf,sibling"
    )

    assert fetched(worked[0]).files and refused(failed[0]).refusal
    assert list(tmp_path.iterdir()) == []

async def test_a_machine_with_nowhere_to_unpack_refuses_every_workflow_rather_than_raising(
    codeload: Codeload, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A temporary directory that cannot be made is this machine's failure, and answered."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "not-there"))

    answers = await _answers(codeload, _repository(), "wf,sibling")

    for answer in answers:
        refusal = refused(answer).refusal
        assert isinstance(refusal, UpstreamUnavailable)
        assert "could not make a temporary directory" in str(refusal)
