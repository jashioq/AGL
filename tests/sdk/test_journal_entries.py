"""What an entry promises: it comes back exactly, or it does not come back at all.

The other half of `sdk/_engine/journal.py`. `test_journal.py` holds the fingerprint - two
computations that must agree, or two that must differ - and this file holds the file that
fingerprint names: its four fields, the two directions of its wire form, and the two accessors
the replay walk will read and write it through. (A second test file for one module has
precedent in `tests/adapters/test_filesystem_store.py` and `test_filesystem_no_lock.py`; here the
seam is the module's own, the two halves sharing nothing but a digest.)

**Every behavioural test runs against both stores**, `MemoryStore` and a real `FilesystemStore`
under `tmp_path`, because the clause the ledger rests on is the `Store`'s atomic write and a
memory-only test proves nothing whatsoever about it. The fixture is the only knob; nothing below
knows which store it is holding, except the two tests at the bottom that are explicitly about what
lands on a disk.

Three claims here fail *silently* if they are got wrong - no exception, no wrong answer, just a
step that never replays and a bill nobody asked for - and each has a test written to be the thing
that notices:

  * a stored `value: null` read back as an absence, which would make every effect step re-run
    forever while looking perfectly healthy;
  * a fingerprint compared against nothing, which would replay an entry filed under a digest it
    does not claim - the expensive direction, a result produced under inputs that were not these;
  * `steps/` and `worktrees/` collapsing into one subtree, which costs a run its `review` step the
    first time a workflow names a worktree after one.

The wire shape is asserted by spelling the four keys out rather than reading them off `Entry`, for
`tests/test_api.py::WIRE_KEYS`'s reason: a record compared against itself agrees with itself, and
what is being pinned is the shape another version of AGL will read.

Named `test_journal_entries.py`: `tests/` carries no `__init__.py` - see `tests/conftest.py` for
why it must not - so pytest's module names are the bare filenames and every one has to be unique.
"""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.filesystem.memory_store import MemoryStore
from agl.adapters.filesystem.store import FilesystemStore
from agl.ports.errors import InternalError
from agl.ports.home_layout import AglHome, RunScope, scope_dir, step_dir, step_entry
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue, RunSpec
from agl.ports.store import Store
from agl.sdk._engine.journal import Entry, read_entry, write_entry

# Every async test below carries its own `@pytest.mark.asyncio`, rather than a module-level
# `pytestmark`: this file mixes async tests with pure ones, and a module-level marker on a
# synchronous test is a `PytestWarning` on every run. `tests/test_api.py` and `tests/sdk/
# test_workflow.py` are mixed the same way and mark the same way. The hazard the marker guards
# against is worth restating where the next async test will be added: `asyncio_mode = "strict"`
# turns a missing marker into a test pytest silently *skips*, which is how a file like this passes
# without ever having awaited anything.

RUN: Final = RunScope(ProjectName("myapp"), RunLabel("auth"))
STEP: Final = StepName("implement")

# The step name that also reads as a worktree's, which is the collision the sibling subtrees
# exist to make impossible.
REVIEW: Final = StepName("review")

# Two digests the way the journal makes them - sha256 hexdigests, 64 lowercase hex characters,
# which is what `home_layout._checked_digest` insists on before spending one as a filename.
FIRST: Final = hashlib.sha256(b"first").hexdigest()
SECOND: Final = hashlib.sha256(b"second").hexdigest()

# A worktree HEAD. Full length and lowercase because a real one is, though `Entry` deliberately
# checks only that it is non-empty; a head that is not one is git's to refuse, at `restore`.
HEAD: Final = "4a91c07f2b3e8d15c6a0b7f31d92e8054c6a0f13"

# A fixed example timestamp, and the moment every entry below is stamped with unless the test
# is about `at` itself.
AT: Final = datetime(2026, 8, 18, 9, 16, 41, tzinfo=UTC)

_MEMORY: Final = "memory"
_FILESYSTEM: Final = "filesystem"


@pytest.fixture(params=[_MEMORY, _FILESYSTEM])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Store:
    """One of the two real `Store` implementations, so every behavioural test runs twice.

    The fake is not a test double - `--dry-run` runs on it - and the real one is what an actual
    resume reads, so a claim about entries that held for only one of them is a claim about nothing.
    The atomic-write clause in particular has no meaning in a dict: `MemoryStore` alone would let
    "the existence of the entry is the ledger" pass as a sentence nobody had checked.
    """
    if request.param == _MEMORY:
        return MemoryStore()
    return FilesystemStore(AglHome(tmp_path))


def _entry(digest: str, *, value: JsonValue = None, head: str = HEAD, at: datetime = AT) -> Entry:
    """One entry, filed under `digest` and claiming it - which is the ordinary, agreeing case.

    `value` defaults to `None` because that is what an effect step records, and because a null
    value is the case the "nothing recorded is not a recorded null" clause turns on.
    """
    return Entry(fingerprint=digest, value=value, head=head, at=at)


# --- The round trip, which is the whole of what an entry is for ---------------------------------


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"tickets": [{"id": "T-01", "title": "add oauth", "blocked_by": []}]},
        ["T-01", "T-02"],
        "the operator said yes",
        4,
        True,
        {},
    ],
    ids=["effect step", "nested object", "list", "human answer", "number", "bool", "empty object"],
)
@pytest.mark.asyncio
async def test_an_entry_written_is_the_entry_read_back(store: Store, value: JsonValue) -> None:
    """Every shape a `value` can be: a tool's payload, a human's answer, or null.

    Equality is over all four fields, so this is also the assertion that nothing is lost on the way
    down and nothing is invented on the way up - a `head` that came back truncated or an `at` that
    came back as text would fail here rather than at the far end of a resume.
    """
    entry = _entry(FIRST, value=value)
    await write_entry(store, RUN, STEP, FIRST, entry)

    found = await read_entry(store, RUN, STEP, FIRST)

    assert found == entry
    assert found is not None and found.value == value


@pytest.mark.asyncio
async def test_a_recorded_null_is_an_entry_and_not_an_absence(store: Store) -> None:
    """The silent failure this test exists to be the notice of.

    An effect step records `value: null` - it committed, it produced no payload - so if a null read
    back as "nothing recorded here", every effect step in every workflow would miss its own entry
    and re-run on every resume, forever, while the run still finished and still produced the right
    answer. The only symptoms would be the bill and the wait.

    `ports/store.py` puts the same separation on the port ("`None` from a read means nothing
    recorded here and can mean nothing else"); this is that clause carried up into the journal,
    where the second question - is there an entry, or is there not - is actually asked.
    """
    effect = _entry(FIRST, value=None)
    await write_entry(store, RUN, STEP, FIRST, effect)

    found = await read_entry(store, RUN, STEP, FIRST)

    assert found is not None, "an effect step has an entry; what is null is the value inside it"
    assert found.value is None
    assert found == effect
    assert await read_entry(store, RUN, STEP, SECOND) is None, "and this is what absence is"


# --- Match on path AND fingerprint ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fingerprint_that_disagrees_with_the_path_is_a_miss(store: Store) -> None:
    """Match on path **and** fingerprint, else re-run - and this is the `and`.

    The filename already is the digest, so AGL never writes the two apart; a disagreement means a
    ledger written by another version of AGL, corrupted, or hand-edited. The answer is `None` and
    the step runs again, which costs tokens and is never wrong - where raising would strand a run
    that could have finished, over a file its owner did not write.

    The middle assertion is what stops this passing for the wrong reason: the misfiled document is
    still on the ledger, so what answered `None` was the comparison and not a write that quietly
    dropped it. The last is the complement - the same entry read at the digest it does claim comes
    back - so a read path that answered `None` to everything would fail here.
    """
    misfiled = _entry(SECOND, value={"tickets": ["T-01"]})

    await write_entry(store, RUN, STEP, FIRST, misfiled)

    assert await read_entry(store, RUN, STEP, FIRST) is None
    document = await store.read_entry(RUN, STEP, FIRST)
    assert document is not None and document["fingerprint"] == SECOND
    await write_entry(store, RUN, STEP, SECOND, misfiled)
    assert await read_entry(store, RUN, STEP, SECOND) == misfiled


@pytest.mark.asyncio
async def test_nothing_in_the_read_path_branches_on_at(store: Store) -> None:
    """The claim, stated: **`at` is recorded and never read for control flow.**

    `at` belongs to debugging and to the view, and `ports/clock.py` rests its whole argument for
    an injectable clock on that - a fake clock changes what is written down and cannot change what
    happens. So two entries identical but for their timestamps, one stamped years stale and one
    stamped in the future, are both readable, each carries its own moment back, and neither the age
    of one nor the freshness of the other changes the answer to a single question the reader asks.

    A reader can check the same claim against the source in one pass: in `journal.py` the field is
    written down, normalised, formatted and parsed, and every occurrence of it sits in a
    constructor, a normalisation or one of the two wire directions - none in a condition, and none
    in `read_entry`, which does not mention it at all.
    """
    stale = _entry(FIRST, value="the same result", at=datetime(2019, 1, 1, tzinfo=UTC))
    future = _entry(SECOND, value="the same result", at=datetime(2031, 12, 31, tzinfo=UTC))

    await write_entry(store, RUN, STEP, FIRST, stale)
    await write_entry(store, RUN, STEP, SECOND, future)

    found_stale = await read_entry(store, RUN, STEP, FIRST)
    found_future = await read_entry(store, RUN, STEP, SECOND)
    assert found_stale == stale, "an old entry replays exactly as a new one does"
    assert found_future == future
    assert found_stale is not None and found_future is not None
    assert found_stale.value == found_future.value == "the same result"
    assert found_stale.at != found_future.at, "the field really did differ between the two"


# --- `steps/` and `worktrees/` are siblings -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_step_and_a_worktree_of_one_name_are_two_entries(store: Store) -> None:
    """`step("review", ...)` in a run and `step("review", ...)` inside `worktree("review")`.

    Same step name, same digest - which is what concurrent siblings produce by construction - and
    different scopes. The layout nests `steps/` inside each worktree rather than pooling them
    precisely so that these two cannot be one address. If they were, the second write would
    supersede the first and the run would replay the child's review as its own.
    """
    inside = RUN.inside(Namespace("review"))
    at_the_run = _entry(FIRST, value="what the run's own review found")
    in_the_worktree = _entry(FIRST, value="what the child's review found")

    await write_entry(store, RUN, REVIEW, FIRST, at_the_run)
    await write_entry(store, inside, REVIEW, FIRST, in_the_worktree)

    assert await read_entry(store, RUN, REVIEW, FIRST) == at_the_run
    assert await read_entry(store, inside, REVIEW, FIRST) == in_the_worktree


# --- Concurrency: one write each, and no coordination anywhere ------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_siblings_each_land_their_own_entry(store: Store) -> None:
    """The concurrent case: `T-01` and `T-02` both finish `implement` at the same moment.

    Their digests are *identical* - same role, no inputs, same parent head - and their namespaces
    are not, which is the whole reason the counter is scoped per namespace
    (`test_journal.py`'s scoped counter) and the whole reason each entry gets its own path. Two
    writes, no lock, no read-modify-write, nothing between them: `asyncio.gather` is as close as one
    event loop gets to asking for both at once, and both must land whole.
    """
    first, second = RUN.inside(Namespace("T-01")), RUN.inside(Namespace("T-02"))
    one, two = _entry(FIRST, value="T-01's work"), _entry(FIRST, value="T-02's work")

    await asyncio.gather(
        write_entry(store, first, STEP, FIRST, one),
        write_entry(store, second, STEP, FIRST, two),
    )

    assert await read_entry(store, first, STEP, FIRST) == one
    assert await read_entry(store, second, STEP, FIRST) == two


@pytest.mark.asyncio
async def test_two_concurrent_runs_of_one_step_land_at_their_own_digests(store: Store) -> None:
    """The other axis of the same clause: one scope, one step name, two digests.

    A retry loop counts `n = 0, 1, 2, ...` inside one `steps/<name>/` directory, so the addresses
    that have to stay independent are not only the ones in different namespaces. A store keeping a
    step's entries as one document would pass every test above and lose one of these two.
    """
    first, second = _entry(FIRST, value="n=0"), _entry(SECOND, value="n=1")

    await asyncio.gather(
        write_entry(store, RUN, STEP, FIRST, first),
        write_entry(store, RUN, STEP, SECOND, second),
    )

    assert await read_entry(store, RUN, STEP, FIRST) == first
    assert await read_entry(store, RUN, STEP, SECOND) == second


@pytest.mark.asyncio
async def test_a_superseded_entry_stays_readable_beside_the_one_that_replaced_it(
    store: Store,
) -> None:
    """Superseded entries are kept on purpose: they are what answers "why did this re-run".

    Sequential rather than concurrent, and a different claim from the test above - not that two
    writes both land, but that a later one does not tidy an earlier one away. Nothing in AGL prunes
    an entry: `clear` removes the run directory wholesale, and there is no delete verb on the port
    at all.
    """
    stale = _entry(FIRST, value="what the prompt produced before it was edited")
    fresh = _entry(SECOND, value="what it produced after")

    await write_entry(store, RUN, STEP, FIRST, stale)
    await write_entry(store, RUN, STEP, SECOND, fresh)

    assert await read_entry(store, RUN, STEP, FIRST) == stale
    assert await read_entry(store, RUN, STEP, SECOND) == fresh


# --- The wire form, held still --------------------------------------------------------------------


def test_the_wire_shape_is_the_four_fields_fingerprint_value_head_and_at() -> None:
    """The published shape, spelled out here rather than read off `Entry`'s own fields.

    A record compared against itself agrees with itself, which is why `tests/test_api.py` pins
    `run.json`'s keys the same way. The order is part of what is pinned: neither store sorts keys,
    so this is the order the four appear in a file somebody opens - and `at`'s text is pinned with
    them, that being the other half of the format.
    """
    document = _entry(FIRST, value={"tickets": []}).to_json()

    assert list(document) == ["fingerprint", "value", "head", "at"]
    assert document == {
        "fingerprint": FIRST,
        "value": {"tickets": []},
        "head": HEAD,
        "at": "2026-08-18T09:16:41Z",
    }


def test_an_entry_read_back_from_its_own_wire_form_is_the_same_entry() -> None:
    """Both directions on one type, which is what keeps the two agreeing (`ports/run.py`'s rule)."""
    entry = _entry(FIRST, value={"rows": [1, None, "two"]})

    assert Entry.from_json(entry.to_json()) == entry


def test_from_json_refuses_a_missing_key_an_unknown_one_and_a_non_object() -> None:
    """`InternalError` for every one: nobody types these files, AGL writes them and AGL reads them.

    A missing key and an unknown one are the same refusal and are together the reason a stored
    `null` cannot be mistaken for a field that is not there - presence is decided by the key set,
    before anything looks at a value. An unknown key is refused rather than ignored because a file
    holding a fifth field was written by a version of AGL that knew something this one does not.
    """
    document = _entry(FIRST, value={"tickets": []}).to_json()

    with pytest.raises(InternalError, match="missing"):
        Entry.from_json({key: value for key, value in document.items() if key != "head"})
    with pytest.raises(InternalError, match="missing"):
        Entry.from_json({key: value for key, value in document.items() if key != "value"})
    with pytest.raises(InternalError, match="unexpected"):
        Entry.from_json({**document, "duration_ms": 1400})
    with pytest.raises(InternalError, match="JSON object"):
        Entry.from_json([document])
    with pytest.raises(InternalError, match="JSON object"):
        Entry.from_json("{}")
    with pytest.raises(InternalError, match="is a int"):
        Entry.from_json({**document, "head": 7})
    with pytest.raises(InternalError, match="cannot read back"):
        Entry.from_json({**document, "at": "last tuesday"})


def test_an_entry_and_a_run_record_write_one_spelling_of_a_timestamp() -> None:
    """`_WIRE_TIME` was a deliberate second copy here; it is now one constant in `ports/run.py`.

    Two spellings of a timestamp in one AGL_HOME is a bug waiting for a reader, and a comment
    saying "the same as run.py's" is not something that fails when it stops being true - so this
    compared the two rendered texts instead. The copy is gone: both records now format through
    `ports/run.py::wire_moment`, and `tests/ports/test_run.py` greps `src/` to hold it at one.
    What this still asserts is the *text* that one format produces, which no amount of sharing
    settles, and the two halves of the normalisation rule the two records share: an offset is
    converted rather than kept, and the microseconds go, because whole seconds is all the wire
    form can hold.
    """
    moment = datetime(2026, 8, 18, 9, 16, 41, 123456, tzinfo=timezone(timedelta(hours=2)))
    entry = Entry(fingerprint=FIRST, value=None, head=HEAD, at=moment)
    spec = RunSpec(
        workflow="tickets",
        workflow_version="1.0.0",
        label=RunLabel("auth"),
        base_ref="main",
        base_sha=hashlib.sha256(b"base").hexdigest()[:40],
        branch="agl/auth",
        params={},
        created_at=moment,
    )

    assert entry.to_json()["at"] == spec.to_json()["created_at"] == "2026-08-18T07:16:41Z"


def test_a_naive_at_is_refused_rather_than_read_as_the_machines_local_time() -> None:
    """Refused *before* `astimezone` is called, which is `WireShape.normalised`'s reason:
    `astimezone` on a naive value quietly reads the local timezone, and an entry that recorded
    where the machine thought it was would be reading a hidden input into the one field an
    injectable clock exists to make answerable."""
    with pytest.raises(InternalError, match="no timezone"):
        Entry(fingerprint=FIRST, value=None, head=HEAD, at=datetime(2026, 8, 18, 9, 16, 41))


def test_one_wire_shape_speaks_for_both_records_and_neither_lost_its_own_words() -> None:
    """The fold's assertion: one implementation, two vocabularies, and the texts unchanged.

    `ports/run.py` and `sdk/_engine/journal.py` each held their own `_wire_text`, `_normalised`,
    `_WIRE_TIME`, `_SURROGATE` and missing/unknown-key block - the same computations, differing
    only in the nouns. They now run one implementation, `ports/run.py::WireShape`, which each
    module instantiates with its own nouns: `run.json`/`a run record`/`a record`/`records`/
    `created_at` here, `a step entry`/`an entry`/`an entry`/`entries`/`a step entry's 'at'` there.

    **The nouns are the whole point of the parameterisation and this is why they are pinned
    literally.** These are what somebody reads at 2am when a record will not load, and the cheap
    version of this fold - one generic sentence about "a record" covering both - would have traded
    a real thing for a line count. `run.json's 'label' is a int, and a record's label is a string`
    against `a step entry's 'at' is a int, and an entry's at is a string`: the reader is told which
    of the two files under AGL_HOME to go and open. So the strings below are spelled out in full
    rather than matched on a fragment, because a fragment stays green while the half that names
    the record drifts, and that half is the half that is useful.

    The messages here are byte for byte what the two modules produced before the fold; they were
    captured from the running code first and compared after.
    """
    document = _entry(FIRST, value={"tickets": []}).to_json()
    record: dict[str, JsonValue] = {
        "workflow": "tickets",
        "workflow_version": "1.0.0",
        "label": "auth",
        "base_ref": "main",
        "base_sha": "8c19f7ae4d2b0913e5f6" * 2,
        "branch": "agl/auth",
        "params": {},
        "created_at": "2026-08-18T09:14:02Z",
    }
    naive = datetime(2026, 8, 18, 9, 16, 41)

    with pytest.raises(InternalError) as entry_field:
        Entry.from_json({**document, "head": 7})
    with pytest.raises(InternalError) as record_field:
        RunSpec.from_json({**record, "label": 7})
    assert str(entry_field.value) == (
        "a step entry's 'head' is a int, and an entry's head is a string"
    )
    assert str(record_field.value) == (
        "run.json's 'label' is a int, and a record's label is a string"
    )

    with pytest.raises(InternalError) as entry_keys:
        Entry.from_json({**document, "duration_ms": 1400})
    with pytest.raises(InternalError) as record_keys:
        RunSpec.from_json({**record, "status": "running"})
    assert str(entry_keys.value) == (
        "a step entry's keys are not an entry's: missing [], unexpected [\"'duration_ms'\"]. An "
        "entry carrying keys AGL does not know was written by another version of it, and this "
        "module refuses entries rather than migrating them"
    )
    assert str(record_keys.value) == (
        "run.json's keys are not a run record's: missing [], unexpected [\"'status'\"]. A record "
        "carrying keys AGL does not know was written by another version of it, and this module "
        "refuses records rather than migrating them"
    )

    with pytest.raises(InternalError) as entry_missing:
        Entry.from_json({key: value for key, value in document.items() if key != "head"})
    with pytest.raises(InternalError) as record_missing:
        RunSpec.from_json({key: value for key, value in record.items() if key != "branch"})
    assert "missing ['head'], unexpected []" in str(entry_missing.value)
    assert "missing ['branch'], unexpected []" in str(record_missing.value)

    with pytest.raises(InternalError) as entry_naive:
        Entry(fingerprint=FIRST, value=None, head=HEAD, at=naive)
    with pytest.raises(InternalError) as record_naive:
        RunSpec.from_json({**record, "created_at": "2026-08-18T09:16:41"})
    assert str(entry_naive.value) == (
        f"a step entry's 'at' {naive!r} has no timezone, and a wall-clock reading with no place "
        f"is not a moment - an entry carries an instant, written as UTC"
    )
    assert str(record_naive.value) == (
        f"created_at {datetime(2026, 8, 18, 9, 16, 41)!r} has no timezone, and a wall-clock "
        f"reading with no place is not a moment - a run record carries an instant, written as UTC"
    )


def test_an_empty_fingerprint_or_head_names_nothing() -> None:
    """The whole of what the two strings are held to - the head's shape is git's to judge, at
    `restore`, and the fingerprint's is settled by the digest it is about to be compared with."""
    with pytest.raises(InternalError, match="'fingerprint'"):
        Entry(fingerprint="", value=None, head=HEAD, at=AT)
    with pytest.raises(InternalError, match="'head'"):
        Entry(fingerprint=FIRST, value=None, head="", at=AT)


# --- What only a disk can be asked ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_two_subtrees_really_are_siblings_on_disk(tmp_path: Path) -> None:
    """The layout, checked against `home_layout` rather than only against the store's answers.

    The behavioural test above would pass against any store that kept the two apart for any reason
    at all, including one that happened to hash the scope into a key. This one spells the layout
    out - `<run>/steps/review/<digest>.json` beside
    `<run>/worktrees/review/steps/review/<digest>.json` - asserts `step_entry` composes exactly
    that, and then asserts a real write put a file at each. The last assertion is the claim in its
    sharpest form: the worktree's entries are not anywhere underneath the run's `steps/`.
    """
    home = AglHome(tmp_path)
    filesystem = FilesystemStore(home)
    inside = RUN.inside(Namespace("review"))

    await write_entry(filesystem, RUN, REVIEW, FIRST, _entry(FIRST, value="the run's own"))
    await write_entry(filesystem, inside, REVIEW, FIRST, _entry(FIRST, value="the child's"))

    at_the_run = step_entry(home, RUN, REVIEW, FIRST)
    in_the_worktree = step_entry(home, inside, REVIEW, FIRST)
    run_dir = scope_dir(home, RUN)
    nested = Path("worktrees") / "review" / "steps" / "review" / f"{FIRST}.json"
    assert at_the_run.relative_to(run_dir) == Path("steps") / "review" / f"{FIRST}.json"
    assert in_the_worktree.relative_to(run_dir) == nested
    assert at_the_run.is_file() and in_the_worktree.is_file()
    assert not in_the_worktree.is_relative_to(run_dir / "steps")


@pytest.mark.asyncio
async def test_one_file_per_step_named_by_its_digest(tmp_path: Path) -> None:
    """Two entries under one step name are two files, which is what makes a completion one write.

    The alternative is the one worth naming: a single `steps.json` would need a
    read-modify-write under a mutex on every completion, and the two writes above would be a queue
    rather than two independent renames. The directory listing is that design, visible.
    """
    home = AglHome(tmp_path)
    filesystem = FilesystemStore(home)

    await write_entry(filesystem, RUN, STEP, FIRST, _entry(FIRST, value="n=0"))
    await write_entry(filesystem, RUN, STEP, SECOND, _entry(SECOND, value="n=1"))

    found = sorted(child.name for child in step_dir(home, RUN, STEP).iterdir())
    assert found == sorted([f"{FIRST}.json", f"{SECOND}.json"])
