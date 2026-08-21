"""`FilesystemStore` against the `Store` contract, plus the clauses only a filesystem can show.

The first class is the whole of the port: `StoreContract` with its one fixture overridden and
nothing else touched. Everything the port promises is asserted there, by a suite written at stage
3 against the port's docstring and before this adapter existed, which is the inversion the build
rests on (§1.9) - so nothing below re-asserts any of it.

What is below is what that suite deliberately cannot see, because it is written against the port
and a port has no filesystem in it. Four things:

  * **The temp file is in the destination's own directory.** `os.replace` is atomic within one
    filesystem and raises `EXDEV` across two - and, worse, on configurations that paper over that,
    degrades into copy-then-delete, which is a reader watching a file grow. Through the port that
    failure is invisible until the day `AGL_HOME` and `/tmp` are different mounts, so it is checked
    here, at the one place where the source of the rename can be looked at.
  * **A write that fails leaves nothing behind and nothing changed.** The port's clause is about
    what a reader sees; this is about what is on the disk afterwards.
  * **Vendor exceptions are translated.** An adapter's boundary is where an `OSError` stops being
    an `OSError`, and every branch of that mapping is a branch no port-level test can provoke.
  * **The tree is what it says it is** - readable JSON, nothing created by a read, and a
    `worktrees/` container that ignores what AGL did not put there.

Named `test_filesystem_store.py` and not `test_store.py`: `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and two
`test_store.py` under different directories would collide at import.
"""

import hashlib
import json
import os
import shutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final, cast

import pytest

from agl.adapters.filesystem.store import FilesystemStore
from agl.ports.errors import DeniedError, InternalError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.home_layout import AglHome, RunScope, run_record, scope_dir, step_entry
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from contracts.store import StoreContract

# Module-level tests do not inherit the marker `StoreContract` sets on itself, and
# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips - which is
# how a file like this passes against an implementation it never called.
pytestmark = pytest.mark.asyncio

# This file builds its own addresses rather than importing the contract suite's: only
# `StoreContract` is public there, the three `_store_*` modules being the private assembly of it.
RUN: Final = RunScope(ProjectName("myapp"), RunLabel("auth"))
CHILD: Final = Namespace("T-01")
STEP: Final = StepName("implement")
DIGEST: Final = hashlib.sha256(b"one").hexdigest()

# §3.6's four fields, with a value carrying a character no *name* may hold (§3.3): names are ASCII
# and values are not, and the file on disk is asserted to keep the difference.
DOCUMENT: Final[dict[str, JsonValue]] = {
    "fingerprint": DIGEST,
    "value": {"tickets": ["T-01"], "note": "café 日本語"},
    "head": "4a91c07f2b3e8d15c6a0" * 2,
    "at": "2026-08-18T09:16:41Z",
}


@pytest.fixture
def home(tmp_path: Path) -> AglHome:
    """An empty `AGL_HOME`. `tmp_path` is absolute, which is the one thing `AglHome` insists on."""
    return AglHome(tmp_path)


@pytest.fixture
def store(home: AglHome) -> Store:
    """The store the module-level tests drive. The contract suite has its own, on the class."""
    return FilesystemStore(home)


class TestFilesystemStore(StoreContract):
    """The port, in full, against the real thing.

    One override and nothing else, which is what the suite asks for: every address, name and
    document it needs it builds itself out of the pure types, so this is the only place it is
    pointed at an implementation.
    """

    @pytest.fixture
    def store(self, tmp_path: Path) -> Store:
        """A store over an empty `AGL_HOME` per test.

        The suite's own fixture is annotated `Store | Iterator[Store]` so that either shape of
        override typechecks; narrowing the return to `Store` is the first of the two.
        """
        return FilesystemStore(AglHome(tmp_path))


# --- The same-filesystem clause, which nothing else can catch ---------------------------------


async def test_the_partial_file_is_created_in_the_destinations_own_directory(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`os.replace` is atomic within one filesystem, and only within one.

    Across two it raises `EXDEV`, and where something papers over that it becomes copy-then-delete
    - a reader watching a file grow, which is exactly the torn value the port forbids absolutely.
    A temp file in the system temp directory is a different filesystem on any machine where `/tmp`
    is its own mount, so "same directory as the destination" is the property, and the source
    argument of the rename is the only place it can be observed.
    """
    renames: list[tuple[Path, Path]] = []
    real = os.replace

    def watched(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        renames.append((Path(source), Path(destination)))
        real(source, destination)

    monkeypatch.setattr(os, "replace", watched)
    await store.write_record(RUN, DOCUMENT)
    await store.write_entry(RUN.inside(CHILD), STEP, DIGEST, DOCUMENT)

    assert len(renames) == 2, "every write publishes with exactly one rename"
    for source, destination in renames:
        assert source.parent == destination.parent, (
            f"the partial file for {destination} was created in {source.parent}, which is not the "
            f"destination's own directory and so is not guaranteed to be the same filesystem"
        )


async def test_a_write_that_fails_leaves_no_partial_file_and_the_previous_value_intact(
    store: Store, home: AglHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed write is a write that did not happen, on disk as well as through the port."""
    await store.write_entry(RUN, STEP, DIGEST, DOCUMENT)

    def full(source: object, destination: object) -> None:
        raise OSError(28, "No space left on device", str(destination))

    monkeypatch.setattr(os, "replace", full)
    with pytest.raises(UpstreamUnavailable):
        await store.write_entry(RUN, STEP, DIGEST, {"fingerprint": "second"})

    monkeypatch.undo()
    assert await store.read_entry(RUN, STEP, DIGEST) == DOCUMENT
    entry = step_entry(home, RUN, STEP, DIGEST)
    assert [child.name for child in entry.parent.iterdir()] == [entry.name], (
        "the partial file the failed write created is still in the entry's directory"
    )


# --- The boundary: nothing that is not an AglError leaves the adapter -------------------------


async def test_a_refusal_from_the_filesystem_surfaces_as_denied(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DeniedError` is "something reachable said no", and its docstring names this case.

    It is also the module that class was renamed for: `except PermissionError` in the adapter has
    to keep catching the builtin, which it does only because AGL's error is not called that.
    """

    def refuse(source: object, destination: object) -> None:
        raise PermissionError(13, "Permission denied", str(destination))

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(DeniedError, match="refused"):
        await store.write_record(RUN, DOCUMENT)

    def refuse_read(self: Path, **options: object) -> str:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_text", refuse_read)
    with pytest.raises(DeniedError, match="auth"):
        await store.read_record(RUN)


async def test_any_other_os_error_surfaces_as_upstream_unavailable(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing landed at the address, so the same call may succeed later - which is that class."""

    def broken(self: Path, **options: object) -> str:
        raise OSError(5, "Input/output error", str(self))

    monkeypatch.setattr(Path, "read_text", broken)
    with pytest.raises(UpstreamUnavailable):
        await store.read_entry(RUN, STEP, DIGEST)

    def broken_listing(self: Path) -> Iterator[Path]:
        raise OSError(5, "Input/output error", str(self))

    monkeypatch.setattr(Path, "iterdir", broken_listing)
    with pytest.raises(UpstreamUnavailable):
        await store.namespaces(RUN)


async def test_remove_translates_a_refusal_instead_of_asking_rmtree_to_ignore_it(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ignore_errors=True` would turn a directory AGL may not delete into a successful `clear`.

    The port asks `remove` to tolerate *absence*, which is caught by name, and asks for nothing
    about a refusal - so a refusal is translated like every other one. Both halves are pinned: the
    error that comes out, and that the call did not ask `shutil` to swallow errors in the first
    place, which is the half a raised `DeniedError` alone would not show.
    """
    asked: list[Mapping[str, object]] = []

    def refuse(path: object, **options: object) -> None:
        asked.append(options)
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(shutil, "rmtree", refuse)
    with pytest.raises(DeniedError, match="removal"):
        await store.remove(RUN)

    assert asked and not any(options.get("ignore_errors") for options in asked)


async def test_a_file_this_store_cannot_read_back_surfaces_as_upstream_unexpected(
    store: Store, home: AglHome
) -> None:
    """The filesystem answered and the answer is not something we can act on.

    Three ways to be that: not JSON, not UTF-8, and JSON that is not an object. None of the three
    is a state this adapter can produce - it publishes with one atomic rename - so the message says
    the file did not come from AGL rather than blaming the write.
    """
    entry = step_entry(home, RUN, STEP, DIGEST)
    entry.parent.mkdir(parents=True, exist_ok=True)

    entry.write_text('{"fingerprint": "half', encoding="utf-8")
    with pytest.raises(UpstreamUnexpected, match="not JSON"):
        await store.read_entry(RUN, STEP, DIGEST)

    entry.write_bytes(b'{"fingerprint": "\xff\xfe"}')
    with pytest.raises(UpstreamUnexpected, match="utf-8"):
        await store.read_entry(RUN, STEP, DIGEST)

    record = run_record(home, RUN)
    record.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(UpstreamUnexpected, match="JSON object"):
        await store.read_record(RUN)


async def test_a_value_json_cannot_write_surfaces_as_internal_error_and_creates_nothing(
    store: Store, tmp_path: Path
) -> None:
    """Our own invariant, not the world's: something above handed us what AGL cannot write down.

    That nothing is created is the observable half of encoding *first*. The value is turned into
    the bytes that would be written before a directory is made or a file is opened, so a document
    AGL cannot serialise costs an exception and no state - and a caller reusing its builder dict
    cannot reach the ledger.

    The third value is why the temp file is asserted on by name rather than left to the blanket
    assertion below it. A lone surrogate is a `str` that `JsonValue` admits and that UTF-8 has no
    encoding for, and it used to be encoded not in `_encoded` but at the temp file's own handle:
    the write reached `_write_atomically`, made the entry's directory, created `partial-...`, and
    raised a `UnicodeEncodeError` out of `opened.write` - a `ValueError`, which that function's
    `except OSError` neither translated nor unlinked after. Both halves of that are pinned here,
    and the orphan is the half no caller could ever have seen through the port.
    """
    with pytest.raises(InternalError, match="cannot write down"):
        await store.write_entry(RUN, STEP, DIGEST, {"value": float("nan")})
    with pytest.raises(InternalError, match="cannot write down"):
        await store.write_record(RUN, cast(Mapping[str, JsonValue], {"params": object()}))
    with pytest.raises(InternalError, match="cannot write down"):
        await store.write_entry(RUN, STEP, DIGEST, {"value": "\ud800"})

    assert list(tmp_path.rglob("partial-*")) == [], (
        "a write that could not encode left its temp file behind: the encode fails on the "
        "caller's own line, before `_write_atomically` is reached and before a temp file exists"
    )
    assert list(tmp_path.rglob("*")) == [], "a write that could not encode still made something"


async def test_a_digest_that_is_not_a_digest_is_refused_before_any_path_is_spent(
    store: Store, tmp_path: Path
) -> None:
    """The port hands `digest` on opaque and says an implementation spending it as a name checks
    it first. This one does, by not checking it itself: `home_layout._checked_digest` is on the
    path this adapter asks for, which is also what keeps a framework-generated segment inside the
    root it is joined onto."""
    with pytest.raises(InternalError, match="not a digest"):
        await store.read_entry(RUN, STEP, "abc")
    with pytest.raises(InternalError, match="not a digest"):
        await store.write_entry(RUN, STEP, DIGEST.upper(), DOCUMENT)
    assert list(tmp_path.rglob("*")) == []


# --- What the tree looks like -----------------------------------------------------------------


async def test_a_read_that_misses_creates_nothing_under_the_home(
    store: Store, tmp_path: Path
) -> None:
    """A read that made a directory would answer a later `namespaces` with a name that got there
    by being asked about - and `clear` deletes a line of work for every name it is answered with.
    """
    assert await store.read_record(RUN) is None
    assert await store.read_entry(RUN, STEP, DIGEST) is None
    assert await store.read_entry(RUN.inside(CHILD), STEP, DIGEST) is None
    assert await store.namespaces(RUN) == ()
    assert await store.namespaces(RUN.inside(CHILD)) == ()

    assert list(tmp_path.rglob("*")) == [], "a read created something under AGL_HOME"


async def test_namespaces_skips_what_agl_could_not_have_written(
    store: Store, home: AglHome
) -> None:
    """Every write into this tree goes through a `Namespace`, so a name one refuses is foreign.

    Raising on it would make `clear` - this member's one caller - fail on something AGL did not
    write and would not have deleted. `_base` is refused because §3.3 reserves it, `.hidden`
    because a name may not start with a dot, and a plain file is not a line of work at all.
    """
    await store.write_entry(RUN.inside(CHILD), STEP, DIGEST, DOCUMENT)
    container = scope_dir(home, RUN.inside(CHILD)).parent
    (container / "not-a-directory").write_text("", encoding="utf-8")
    (container / "_base").mkdir()
    (container / ".hidden").mkdir()

    assert await store.namespaces(RUN) == (CHILD,)


async def test_namespaces_answers_sorted_by_name(store: Store) -> None:
    """The port asks for a stable order and declines to say sorted by what. This adapter sorts,
    which satisfies it and makes a `clear` traversal reproducible; the suite asserts the set and
    the repeatability, so the tie-break itself is only pinned here."""
    for name in ("T-03", "T-01", "T-02"):
        await store.write_entry(RUN.inside(Namespace(name)), STEP, DIGEST, DOCUMENT)

    assert await store.namespaces(RUN) == (Namespace("T-01"), Namespace("T-02"), Namespace("T-03"))


async def test_an_entry_on_disk_is_indented_utf8_json_a_person_can_read(
    store: Store, home: AglHome
) -> None:
    """§3.6 keeps superseded entries because they answer "why did this re-run", and keeps them for
    a person rather than for the framework - which is the whole of the argument for an indent and
    for `ensure_ascii=False`. A minified line of `\\u`-escapes satisfies every other clause here
    and defeats the one reason the file is still on disk."""
    await store.write_entry(RUN, STEP, DIGEST, DOCUMENT)

    text = step_entry(home, RUN, STEP, DIGEST).read_text(encoding="utf-8")
    assert json.loads(text) == DOCUMENT
    assert "\n  " in text, "the entry is one minified line"
    assert "café 日本語" in text, "the entry's unicode was escaped"
