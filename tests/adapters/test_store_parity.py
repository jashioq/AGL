"""The anti-drift guard: `FilesystemStore` and `MemoryStore` held to each other, not to the port.

`tests/contracts/store.py` holds both stores to everything the port *says*. This file holds them to
everything the port leaves open - and that is where a fake drifts, because a clause nobody wrote
down is a clause no suite can assert. §1.9's rule is that a fake is a product feature: `--dry-run`
and plan target #8 ("every command runs end-to-end on fakes alone") run on `MemoryStore`, so a fake
that accepts a document the real store refuses turns a green all-fakes run into a real run that
crashes, with the difference invisible until the day somebody drops the `--dry-run`.

Every test below asks both stores the same question and asserts they answered alike. `_alike` is
what makes that one line: it runs the call against each store, compares the answers, and hands them
both back so a test can go on to check something the comparison cannot see - `True == 1` in Python,
so two stores agreeing is not by itself two stores keeping a boolean a boolean.

## Where the two deliberately disagree

A divergence papered over is a divergence discovered later, at the worst moment, so each one below
is pinned as a test of its own. **The list is closed**: a fourth divergence appearing is a failing
test here rather than a discovery in production.

  1. **An ill-formed digest.** The real store spends the digest as a path segment and
     `home_layout._checked_digest` refuses one that is not 64 lowercase hex characters, because a
     framework-generated segment has to stay inside the root it is joined onto. The fake spends it
     as one third of a dict key, where every string is as safe as every other. The port grants the
     check to an implementation that needs it rather than requiring it of all of them.
  2. **A project name with no headroom for `.toml`.** The same shape of difference at the other
     end of the address: `home_layout._checked_project` refuses a name whose settings file would
     exceed NAME_MAX, which is a fact about filenames and about nothing else.
  3. **`remove` of a scope two or more deep.** `shutil.rmtree` takes the subtree and deliberately
     does not prune the now-empty parents, so the real store still lists a namespace whose only
     child has been removed; the fake derives `namespaces` from the recorded addresses, as it must
     - an index would be a second structure to keep current under concurrent writers - and so
     answers with nothing. The port's own asymmetry says which side of this is safe: "a retained
     name costs a stale ref, a wrongly deleted one costs the run", and the real store is the one
     that retains.

All three are one family - the real store turns names into paths and checks what it is about to
spend, and the fake spends nothing.

**A lone surrogate is not a fourth, and the history is worth keeping.** `"\\ud800"` - which
`json.loads` produces from a tool payload and which `JsonValue` admits as a `str` - was reported
here in prose as a divergence too, and deliberately left unpinned, because it was a defect rather
than a design difference: the fake round-tripped it, and `FilesystemStore` let a
`UnicodeEncodeError` escape `_write_atomically` untranslated and orphaned the `partial-` file that
branch exists to unlink. Pinning it then would have frozen the bug into the suite. Both stores now
hold their documents as the same UTF-8 bytes and both refuse it as `InternalError`, so it is
asserted below with the rest of what they refuse alike, rather than described up here.

Resource limits are out of scope for the word "divergence" here: a full disk, a path longer than
PATH_MAX, a directory the user may not write to. Those are the world's answers, not the
implementations', and only one of the two stores is standing in the world at all.

Named `test_store_parity.py`: `tests/` carries no `__init__.py` - see `tests/conftest.py` for why -
so pytest's module names are the bare filenames and every one of them has to be unique.
"""

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

import pytest

from agl.adapters.filesystem.memory_store import MemoryStore
from agl.adapters.filesystem.store import FilesystemStore
from agl.ports.errors import AglError, InputError, InternalError
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store

# Module-level tests inherit no marker from anywhere, and `asyncio_mode = "strict"` turns a missing
# one into a test pytest silently skips - which is how a parity file passes against one store.
pytestmark = pytest.mark.asyncio

# The two implementations, by name, so a failure says which one answered differently and so the
# three divergence tests can address one of them without unpacking a tuple in the right order.
_FILESYSTEM: Final = "filesystem"
_MEMORY: Final = "memory"

# This file builds its own addresses rather than importing the contract suite's: only
# `StoreContract` is public there, the three `_store_*` modules being the private assembly of it.
RUN: Final = RunScope(ProjectName("myapp"), RunLabel("auth"))
CHILD: Final = Namespace("T-01")
GRANDCHILD: Final = Namespace("sub-b")
STEP: Final = StepName("implement")
DIGEST: Final = hashlib.sha256(b"one").hexdigest()

DOCUMENT: Final[dict[str, JsonValue]] = {"fingerprint": DIGEST, "value": None, "at": "2026-08-18"}

# Every shape `JsonValue` admits, in one document, built here rather than imported for the reason
# above. The unicode string carries a character no *name* may hold (§3.3): names are ASCII and
# values are not, and a store that confused the two would encode a value the way it encodes an
# address. Non-finite floats are absent because they have their own test, being a refusal.
EVERY_SHAPE: Final[dict[str, JsonValue]] = {
    "null": None,
    "true": True,
    "false": False,
    "zero": 0,
    "negative": -17,
    "wider than a double": 2**53 + 1,
    "float": -2.5,
    "tiny float": 1e-300,
    "empty string": "",
    "unicode": 'café 日本語 \U0001f34c \\ " / \t \n',
    "empty object": {},
    "empty array": [],
    "nested": {"rows": [{"id": "T-01", "blocked_by": []}, {"id": "T-02", "blocked_by": ["T-01"]}]},
    "mixed array": [1, "two", None, True, 3.5, {"four": 4}, [5, [6]]],
}


@pytest.fixture
def stores(tmp_path: Path) -> Mapping[str, Store]:
    """Both implementations of the port, empty, to be asked the same questions in the same order.

    One `tmp_path` per test gives the real store an empty `AGL_HOME`; the fake needs nothing, which
    is the whole of its constructor. They are handed back by name rather than as a tuple so that a
    failure message can say which store answered differently without counting positions.
    """
    return {_FILESYSTEM: FilesystemStore(AglHome(tmp_path)), _MEMORY: MemoryStore()}


async def _alike[T](
    stores: Mapping[str, Store], ask: Callable[[Store], Awaitable[T]]
) -> dict[str, T]:
    """Ask both stores the same thing, assert they answered alike, and hand back both answers.

    Both answers and not one, because equality is where this helper stops being able to see: `True
    == 1` and `1 == 1.0` in Python, so two stores that agree may still both be wrong about which
    type came back, and a caller that cares checks each answer itself.
    """
    answers = {name: await ask(store) for name, store in stores.items()}
    reference = next(iter(answers.values()))
    for name, answer in answers.items():
        assert answer == reference, (
            f"the {name} store answered {answer!r} where the others answered {reference!r}: the "
            f"two implementations of this port have drifted apart somewhere the port is silent"
        )
    return answers


async def _refused[T](
    stores: Mapping[str, Store], ask: Callable[[Store], Awaitable[T]]
) -> type[AglError]:
    """Assert both stores refuse the same call with the same `AglError` subclass, and name it.

    Only `AglError` is caught, on purpose: an adapter translates at its boundary and nothing that
    is not an `AglError` may leave one, so anything else propagating out of here is the failure it
    looks like rather than a refusal this helper should be comparing.
    """
    raised: dict[str, type[AglError] | None] = {}
    for name, store in stores.items():
        try:
            await ask(store)
        except AglError as error:
            raised[name] = type(error)
        else:
            raised[name] = None
    distinct = set(raised.values())
    assert len(distinct) == 1, (
        f"the two stores disagreed about this value: {raised} - a fake that accepts what the real "
        f"store refuses turns a green --dry-run into a real run that crashes"
    )
    refusal = distinct.pop()
    assert refusal is not None, "both stores accepted a value this test expected both to refuse"
    return refusal


def _writing(value: Mapping[str, JsonValue]) -> Callable[[Store], Awaitable[None]]:
    """`write_entry` of one document at one address, as a callable over a store.

    A function returning the closure rather than a `lambda` written at the call site, so that the
    tests below can loop over several values without a closure capturing a loop variable.
    """
    return lambda store: store.write_entry(RUN, STEP, DIGEST, value)


def _assert_json_kinds(document: Mapping[str, JsonValue], where: str) -> None:
    """The four facts about `EVERY_SHAPE` that comparing whole documents cannot establish.

    Python's equality is not JSON's. `True == 1` and `1 == 1.0`, so a store that turned a boolean
    into an integer, or every number into a float, would pass a comparison of whole documents
    against either the original or the other store. The oversized integer catches the third of
    them: a store round-tripping numbers through a double silently edits what it was handed.
    """
    assert document["true"] is True and document["false"] is False, f"{where}: a boolean is not 1"
    zero = document["zero"]
    assert isinstance(zero, int) and not isinstance(zero, bool), f"{where}: an int is not a bool"
    assert isinstance(document["float"], float), f"{where}: a float is not an integer either"
    assert document["wider than a double"] == 2**53 + 1, f"{where}: an integer was approximated"


# --- What both stores refuse --------------------------------------------------------------------


async def test_a_non_finite_float_is_refused_by_both_and_neither_keeps_anything(
    stores: Mapping[str, Store],
) -> None:
    """`JsonValue` admits a `float`, and NaN and the infinities are floats JSON cannot spell.

    The contract suite writes none and says so (item 9): the port has no opinion and an
    implementation may reasonably refuse them. "May reasonably refuse" is exactly the shape of
    clause a fake drifts through, so the two are pinned to one answer here - refuse, with
    `InternalError`, because a bare `NaN` token is not JSON, no other reader accepts it, and it
    comes back unequal to itself, which would break the port's round-trip promise at read time
    instead of failing at write time.

    That nothing is kept is the observable half of encoding *first*: the document becomes text
    before either store touches its state, so a value AGL cannot write down costs an exception and
    no ledger.
    """
    for number in (float("nan"), float("inf"), float("-inf")):
        assert await _refused(stores, _writing({"value": number})) is InternalError

    assert await _refused(stores, _writing({"nested": {"rows": [float("nan")]}})) is InternalError
    for answer in (
        await _alike(stores, lambda store: store.read_entry(RUN, STEP, DIGEST))
    ).values():
        assert answer is None, "a write that could not encode still put something on the ledger"


async def test_a_lone_surrogate_in_a_value_is_refused_by_both_and_neither_keeps_anything(
    stores: Mapping[str, Store],
) -> None:
    """`JsonValue` admits any `str`, and a lone surrogate is a `str` with no UTF-8 encoding at all.

    Reachable rather than theoretical, which is what earns it a test: `json.loads('"\\ud800"')`
    hands back an unpaired UTF-16 code unit without complaint, so an agent's reporting-tool payload
    carries one straight into `write_entry` with nothing in between that would notice.

    The port says nothing about it - which is this file's whole subject, and this is the clause the
    two stores actually drifted apart on. The real store writes a file, so the documents it can
    hold are the ones that can be encoded; the fake held a `str` and escaped its non-ASCII with
    `ensure_ascii=True`, so it took the surrogate, handed it back, and would have let an all-fakes
    run pass over a document the real run could not write down. Both hold UTF-8 bytes now and both
    answer `InternalError`: AGL cannot write this down, which is that class's own sentence.

    Nothing is kept, for `allow_nan`'s reason one test up - the document becomes bytes before
    either store touches its state, so a value AGL cannot encode costs an exception and no ledger.

    The last two writes pin how *narrow* the refusal is. A character outside the BMP is a surrogate
    pair in UTF-16 and is perfectly good UTF-8, so both stores take it: the rule is "an unpaired
    code unit", not "nothing above U+FFFF", and a store that confused the two would refuse the
    emoji a workflow's summary is entitled to hold.
    """
    for surrogate in ("\ud800", "\udfff", "before \udc00 after"):
        assert await _refused(stores, _writing({"value": surrogate})) is InternalError
    assert await _refused(stores, _writing({"nested": {"rows": ["\ud800"]}})) is InternalError
    assert await _refused(stores, _writing({"\ud800": "in a key"})) is InternalError

    for answer in (
        await _alike(stores, lambda store: store.read_entry(RUN, STEP, DIGEST))
    ).values():
        assert answer is None, "a write that could not encode still put something on the ledger"

    paired: dict[str, JsonValue] = {"value": "\U0001f34c"}
    for store in stores.values():
        await store.write_entry(RUN, STEP, DIGEST, paired)
    for answer in (
        await _alike(stores, lambda store: store.read_entry(RUN, STEP, DIGEST))
    ).values():
        assert answer == paired, "a well-formed astral character is not a lone surrogate"


async def test_a_value_json_cannot_write_at_all_is_refused_by_both_with_the_same_error(
    stores: Mapping[str, Store],
) -> None:
    """An `object()` is not a JSON value, at the top level or six containers down.

    `JsonValue` says so and `mypy --strict` enforces it everywhere the annotation reaches, which is
    everywhere except a `params` mapping that came from a workflow author's own untyped code. Both
    stores find out at `json.dumps` and both call it `InternalError`: our own invariant, not the
    world's - something above this port handed us a document AGL cannot write down.
    """
    top = cast(Mapping[str, JsonValue], {"value": object()})
    deep = cast(Mapping[str, JsonValue], {"value": {"rows": [{"payload": object()}]}})
    assert await _refused(stores, _writing(top)) is InternalError
    assert await _refused(stores, _writing(deep)) is InternalError

    proxy = cast(Mapping[str, JsonValue], {"params": MappingProxyType({"request": "add oauth"})})
    assert await _refused(stores, _writing(proxy)) is InternalError, (
        "a Mapping one level down is refused by both: `dict(value)` is taken at the top level and "
        "nowhere else, because `JsonValue` spells its nested objects `dict` and json refuses the "
        "rest - so the two stores agree about where the tolerance stops as well as that it exists"
    )


# --- What both stores accept, and what it turns into ---------------------------------------------


async def test_a_mapping_proxy_is_accepted_by_both_and_reads_back_as_a_plain_dict(
    stores: Mapping[str, Store],
) -> None:
    """The port admits any `Mapping` so a caller need not copy what it already has, and
    `RunSpec.params` really is a `MappingProxyType` - so this is not a hypothetical shape.

    `json` refuses a mapping that is not a `dict`, so both stores take `dict(value)` at the top
    level, and what comes back is `json.loads`'s own container: a plain `dict` the caller owns,
    from either store, never the proxy it handed in.
    """
    proxy: Mapping[str, JsonValue] = MappingProxyType(
        {"workflow": "tickets", "params": {"request": "add oauth", "concurrent": 4}}
    )
    for store in stores.values():
        await store.write_record(RUN, proxy)

    for name, answer in (await _alike(stores, lambda store: store.read_record(RUN))).items():
        assert answer == dict(proxy)
        assert type(answer) is dict, f"the {name} store handed back a {type(answer).__name__}"


async def test_a_tuple_in_a_value_reads_back_as_a_list_from_both(
    stores: Mapping[str, Store],
) -> None:
    """The single clearest reason the fake serialises rather than deep-copying.

    A tuple is not a `JsonValue` and `json.dumps` writes it as an array, so it comes back a list.
    A fake that took a `deepcopy` would hand the tuple straight back, a workflow would index it,
    unpack it, compare it to a tuple - and the real run would be the first thing to disagree.
    """
    written = cast(Mapping[str, JsonValue], {"value": {"tickets": ("T-01", "T-02")}, "at": "now"})
    for store in stores.values():
        await store.write_entry(RUN, STEP, DIGEST, written)

    expected = {"value": {"tickets": ["T-01", "T-02"]}, "at": "now"}
    for name, answer in (
        await _alike(stores, lambda store: store.read_entry(RUN, STEP, DIGEST))
    ).items():
        assert answer == expected, f"the {name} store did not turn a tuple into a list"
        assert answer is not None
        value = answer["value"]
        assert isinstance(value, dict)
        assert type(value["tickets"]) is list


async def test_a_non_string_key_is_renamed_by_both_rather_than_kept_or_refused(
    stores: Mapping[str, Store],
) -> None:
    """A JSON object is keyed by strings, and `json.dumps` coerces anything else rather than
    refusing it - so `1` comes back as `"1"` from both, which is a silent rename and is exactly
    what `RunSpec` refuses upstream at `_checked_json`. This port keeps documents without looking
    inside them, so neither store is the place that refusal belongs; what matters here is that they
    do the same thing with it, because a fake that kept the integer key would let a workflow build
    a document that changes shape on the real run."""
    written = cast(Mapping[str, JsonValue], {1: "one", "two": 2})
    for store in stores.values():
        await store.write_record(RUN, written)

    for answer in (await _alike(stores, lambda store: store.read_record(RUN))).values():
        assert answer == {"1": "one", "two": 2}


async def test_every_shape_of_json_round_trips_identically_from_both(
    stores: Mapping[str, Store],
) -> None:
    """The whole of what `JsonValue` admits, out of both stores, equal to each other and to what
    went in - and then the three type facts that comparing documents cannot establish, checked
    against each store separately because two stores can agree and both be wrong."""
    document: dict[str, JsonValue] = {"fingerprint": DIGEST, "value": EVERY_SHAPE, "at": "now"}
    for store in stores.values():
        await store.write_record(RUN, EVERY_SHAPE)
        await store.write_entry(RUN, STEP, DIGEST, document)

    for name, answer in (await _alike(stores, lambda store: store.read_record(RUN))).items():
        assert answer == EVERY_SHAPE
        assert answer is not None
        _assert_json_kinds(answer, f"the {name} store's record")

    for name, answer in (
        await _alike(stores, lambda store: store.read_entry(RUN, STEP, DIGEST))
    ).items():
        assert answer == document
        assert answer is not None
        value = answer["value"]
        assert isinstance(value, dict)
        _assert_json_kinds(value, f"the {name} store's entry")


async def test_both_answer_namespaces_in_the_same_order_for_the_same_recorded_set(
    stores: Mapping[str, Store],
) -> None:
    """The port asks for a *stable* order and declines to say sorted by what, so the contract suite
    asserts the set and the repeatability and never the sequence.

    That freedom is real and is exactly why it is pinned here: `clear` walks these names and
    deletes a line of work for each one, so a traversal that runs in one order on fakes and another
    in anger is a bug reproducible on only one of them. Both sort by name. The namespaces are
    recorded out of order, and one of them is a prefix of another, so a store comparing anything
    other than the whole name shows it.
    """
    for name in ("T-10", "T-02", "T-2", "T-01"):
        for store in stores.values():
            await store.write_entry(RUN.inside(Namespace(name)), STEP, DIGEST, DOCUMENT)
    for store in stores.values():
        await store.write_entry(RUN.inside(CHILD).inside(GRANDCHILD), STEP, DIGEST, DOCUMENT)

    expected = (Namespace("T-01"), Namespace("T-02"), Namespace("T-10"), Namespace("T-2"))
    for answer in (await _alike(stores, lambda store: store.namespaces(RUN))).values():
        assert answer == expected
    for answer in (
        await _alike(stores, lambda store: store.namespaces(RUN.inside(CHILD)))
    ).values():
        assert answer == (GRANDCHILD,)


# --- Where the two deliberately disagree ---------------------------------------------------------


async def test_an_ill_formed_digest_is_refused_by_the_real_store_and_accepted_by_the_fake(
    stores: Mapping[str, Store],
) -> None:
    """Divergence 1 of 3, and the one the port names.

    `digest` is opaque to the port, which says an implementation *that spends it as a name of its
    own* checks it first. That is a permission granted to the implementation that needs it, not a
    duty laid on every one: the real store joins it onto a path, so `home_layout._checked_digest`
    insists on 64 lowercase hex characters and keeps a framework-generated segment inside the root
    it is joined onto; the fake makes it one third of a dict key, where every string is as safe as
    every other, and `_checked_digest` is private to the module that needs it.

    Pinned rather than papered over, and harmless in the direction it runs: the journal computes
    every digest and no user types one, so an ill-formed digest is AGL's own bug either way, and
    the store that turns it into a filename is the one that has to catch it.
    """
    with pytest.raises(InternalError, match="not a digest"):
        await stores[_FILESYSTEM].write_entry(RUN, STEP, "abc", DOCUMENT)
    with pytest.raises(InternalError, match="not a digest"):
        await stores[_FILESYSTEM].read_entry(RUN, STEP, DIGEST.upper())

    await stores[_MEMORY].write_entry(RUN, STEP, "abc", DOCUMENT)
    assert await stores[_MEMORY].read_entry(RUN, STEP, "abc") == DOCUMENT
    assert await stores[_MEMORY].read_entry(RUN, STEP, DIGEST.upper()) is None


async def test_a_project_name_with_no_room_for_its_settings_file_is_refused_only_by_the_real_store(
    stores: Mapping[str, Store],
) -> None:
    """Divergence 2 of 3: the same difference as the digest, at the other end of the address.

    `ids.py` caps a name at NAME_MAX, which is right for a name; `home_layout._checked_project`
    then refuses one whose `<project>.toml` would be five bytes over, because that module is the
    one that turns a name into a *filename*. So a 251-byte `ProjectName` is a good name that the
    real store cannot hold and the fake can - a fact about filenames, and about nothing the port
    says.

    Not on the list of things `MemoryStore` should learn to check. It has no settings file, and a
    fake that re-implemented the real store's limits would be a second copy of them, drifting from
    the module that owns them, which is what `home_layout` exists to prevent.
    """
    crowded = RunScope(ProjectName("p" * 251), RunLabel("auth"))
    with pytest.raises(InputError, match="settings file"):
        await stores[_FILESYSTEM].write_record(crowded, DOCUMENT)

    await stores[_MEMORY].write_record(crowded, DOCUMENT)
    assert await stores[_MEMORY].read_record(crowded) == DOCUMENT


async def test_removing_a_scope_two_deep_leaves_its_parent_named_by_the_real_store_only(
    stores: Mapping[str, Store],
) -> None:
    """Divergence 3 of 3, and the only one that is not about spending a name as a path.

    `remove` is one `shutil.rmtree` of the scope's directory and deliberately prunes no empty
    parent, so after removing `T-01/sub-b` the directory `T-01/` is still there and `namespaces`
    reports it. The fake derives `namespaces` from the recorded addresses - it must, an index being
    a second structure two concurrent writers would have to agree about, which the port's
    concurrency clause pushes back on - and nothing is recorded under `T-01` any more.

    Both readings are inside what the port says. It promises the namespaces *recorded* under a
    scope, which is the fake's answer to the letter, and it names the asymmetry that makes the real
    store's answer the safe one: "a retained name costs a stale ref, a wrongly deleted one costs
    the run". `clear` removes at depth zero, where the two agree exactly, so nothing AGL does today
    reaches this difference - which is why it is pinned here rather than resolved in either
    direction.
    """
    deep = RUN.inside(CHILD).inside(GRANDCHILD)
    for store in stores.values():
        await store.write_entry(deep, STEP, DIGEST, DOCUMENT)
    for named in (await _alike(stores, lambda store: store.namespaces(RUN))).values():
        assert named == (CHILD,), "the two disagree before the removal, not only after it"

    for store in stores.values():
        await store.remove(deep)

    assert await stores[_FILESYSTEM].namespaces(RUN) == (CHILD,)
    assert await stores[_MEMORY].namespaces(RUN) == ()
    for answer in (
        await _alike(stores, lambda store: store.read_entry(deep, STEP, DIGEST))
    ).values():
        assert answer is None, "the removal itself is not where the two differ"


async def test_removing_a_run_leaves_the_two_agreeing_exactly(
    stores: Mapping[str, Store],
) -> None:
    """The bound on divergence 3, and the case `clear` actually runs (§3.10).

    At depth zero `remove` takes the run's own directory, so no parent survives to be listed and
    the real store's non-pruning cannot show. Asserted so that the divergence above is pinned as
    the narrow thing it is rather than as "the two disagree about `remove`".
    """
    deep = RUN.inside(CHILD).inside(GRANDCHILD)
    for store in stores.values():
        await store.write_record(RUN, DOCUMENT)
        await store.write_entry(deep, STEP, DIGEST, DOCUMENT)
        await store.remove(RUN)

    for named in (await _alike(stores, lambda store: store.namespaces(RUN))).values():
        assert named == ()
    for answer in (await _alike(stores, lambda store: store.read_record(RUN))).values():
        assert answer is None
    for answer in (
        await _alike(stores, lambda store: store.read_entry(deep, STEP, DIGEST))
    ).values():
        assert answer is None
