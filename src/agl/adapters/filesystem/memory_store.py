"""`MemoryStore` - the `Store` that keeps its documents in a dict. Not a test double.

This is the store `--dry-run` runs on and the one plan target #8 rests on - "every command runs
end-to-end on fakes alone", no network, no git, nothing under `AGL_HOME`. §1.9's charge against the
previous implementation was that its fakes lived in `tests/fakes.py` and so "cannot power product
modes", with nothing holding them to the port; Rule 3 turns that around, and the consequence for
this module is one sentence:

**Wherever the port is silent, this store agrees with `store.py`.**

A fake that accepts a document the real store refuses turns an all-fakes run that passed into a real
run that crashes, which is exactly the drift a contract suite alone cannot catch - the suite asserts
what the port *says*, and every clause below is somewhere the port says nothing. So `MemoryStore`
runs `tests/contracts/store.py` unmodified alongside `FilesystemStore`, and
`tests/adapters/test_store_parity.py` holds the two to everything the port left open.

## Documents are held as the UTF-8 bytes `store.py` writes, and that is the whole design

`json.dumps` and an encode on the way in, a decode and `json.loads` on the way out, and never a
`deepcopy`. Three reasons, and the last two are the ones that decide the design.

**Independence, in both directions, for free.** §3.6 has the store copy any mapping it is handed
and return copies on read: a caller reusing a builder dict must not silently edit an entry already
on the ledger, and a caller editing what it read must not edit the store. Here there is no
serialisation boundary doing that for you, as there is under a file, so it has to be built. A
top-level `dict(value)` would not be it - a shallow copy shares every nested object with the
caller, so the first caller to reach into `params` or into an entry's `value` edits the store, which
is the same bug one indirection deeper. `json.dumps` reads the mapping once and produces text that
shares nothing with it; `json.loads` builds every container fresh.

**It keeps the fake and the real store the same store.** `json.dumps` is where a tuple becomes a
list, where a non-`str` key is renamed, and where a value JSON has no spelling for is refused. A
`deepcopy`-based fake would accept all three, hand them straight back, and let a workflow build a
document that only fails on the real run - the drift Rule 3 forbids, arriving as a crash in
production after a green `--dry-run`.

**Bytes rather than a `str`, because that makes the agreement exact rather than approximate.** The
sentence above is the one this file argues for, and holding the *same form* the real store holds is
the strongest way to keep it: a `FilesystemStore` document is UTF-8 in a file, so a `MemoryStore`
document is the UTF-8 that file would contain. A document one store can hold is then a document the
other can, by construction - not because two encoders were checked against each other and found to
agree today. The case that made this concrete is a lone surrogate (`"\\ud800"`, an unpaired UTF-16
code unit `json.loads` produces from a tool payload and `JsonValue` admits as a `str`): it has no
UTF-8 encoding at all, so neither store can hold it and both say `InternalError`. Held as a `str`,
this store took it happily and handed it back - a green `--dry-run` over a document the real run
could not write down, which is the drift in its purest form.

## The choices copied from `store.py`, because the port left them open

  * **`dict(value)` at the top level and nowhere below it.** The port admits any `Mapping` so a
    caller need not copy what it already has, `RunSpec.params` really is a `MappingProxyType`, and
    `json` refuses a mapping that is not a `dict`. One level down `JsonValue` spells its objects
    `dict[str, JsonValue]`, so the top level is the only place it is needed - and a nested
    `MappingProxyType` is refused by both stores alike, which the parity suite pins.
  * **`allow_nan=False`.** Left at its default, `json` writes a bare `NaN` or `Infinity` token that
    is not JSON and comes back unequal to itself, so the round-trip promise would break at read
    time instead of failing at write time. `ports/run.py::_checked_json` refuses them for that
    reason and both stores agree with it.
  * **`ensure_ascii=False`, and then the UTF-8 encode.** This one is not a taste copied for
    consistency - it is what the paragraph above rests on. `ensure_ascii=True` escapes every
    non-ASCII character, a lone surrogate included, so the text it produces always encodes and this
    store would go on accepting a document the real one refuses. With `ensure_ascii=False` the
    surrogate is still in the text at encode time and both stores fail on it, together, for the
    same reason.
  * **`TypeError` or `ValueError` out of the serialisation - `json.dumps` and the encode that
    finishes it -> `InternalError`**, naming the address in AGL's own terms - project, label,
    namespaces, step, digest - because that is what a reader has in hand. Our own invariant, not
    the world's: something above this port handed us a document AGL cannot write down.
    `UnicodeEncodeError` is a `ValueError`, so it lands in that branch in both stores alike.
  * **`namespaces` sorted by name.** The port asks for a *stable* order and declines to say sorted
    by what; sorting satisfies it, and both stores sorting the same way is what makes a `clear`
    traversal reproduce the same order on fakes and in anger.

What is deliberately *not* copied is `indent`. That is `store.py`'s concession to §3.6 keeping
superseded entries for a person to read, and there is no file here and no person reading one. It is
whitespace, and whitespace is ASCII: it changes neither what `json.loads` gives back nor whether
the encode succeeds, which makes it the one difference between the two encoders that cannot be
observed through the port. `ensure_ascii` used to be listed here beside it and was not that - the
divergence it hid is the paragraph above.

## The digest is not checked here, on purpose

The port hands `digest` on opaque and says that an implementation *which spends it as a name of its
own* checks it first. That is a permission granted to an implementation that needs it, not an
obligation on every implementation: `FilesystemStore` joins the digest onto a path and so has to
know it cannot be `..` or carry a separator, and `home_layout._checked_digest` - private to the
module that builds that path - is where it finds out. This store uses the digest as one third of a
dict key, where every string is as safe as every other, and needs nothing of it. So a digest the
real store refuses is accepted here, which is reachable only from inside AGL - the journal computes
every digest and no user types one - and is our bug either way.

**That is where the fake is deliberately more permissive**, and it reaches one other name for the
same reason: `home_layout` also refuses a project name whose `<project>.toml` would exceed NAME_MAX.
Both are one shape of divergence - the real store turns a name into a path and checks what it is
about to spend, and this one spends nothing. `tests/adapters/test_store_parity.py` pins them rather
than leaving them to be discovered, and holds the list closed: a new divergence is a failing test
there rather than a crash after a green `--dry-run`.

## No lock, and every method returns without awaiting

No mutex, no `asyncio.Lock`, no queue, nothing serialised. Distinct addresses are independent, and
two children recording their own `implement` step at the same moment write two different dict keys
and never meet - the port states that as a clause of its own and `store.py` has the same absence for
the same reason. A lock here would pass the contract suite, which lists "that distinct addresses are
written without a shared lock" among the things it cannot see, and would surface at stage 13 as
concurrency that quietly is not there.

**A written value exists complete or not at all**, and here that is one dict assignment: the key
holds the whole of the previous document or the whole of the new one, and a reader arriving at any
moment gets one of the two. That assignment is `os.replace`'s counterpart, and it is why the
documents are held encoded rather than as trees that could be half-built.

Nothing below sleeps, adds latency, or fails on purpose - no contract asks for an injected failure,
and a fake that fails on purpose is a fake nobody can build a `--dry-run` on. The only exception any
method raises is the `InternalError` above, and nothing that is not an `AglError` leaves this
module.
"""

import json
from collections.abc import Mapping
from typing import Final

from agl.ports.errors import InternalError
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store

__all__ = ["MemoryStore"]


# `store.py`'s encoding, named here for the same reason it is named there - the default is the
# locale's - and held to because holding the same *bytes* the real store writes is what makes the
# two stores agree about which documents exist at all. Spent once each way: `_encoded`, `_decoded`.
_ENCODING: Final = "utf-8"


# One step entry's whole address, as the port spells it: which line of work ran it, which step, and
# which run of that step. Every part is hashable - `RunScope` and `StepName` are frozen dataclasses
# - so the address is the key and there is no second addressing scheme to keep in step with it.
type _EntryAddress = tuple[RunScope, StepName, str]


class MemoryStore(Store):
    """`Store` over two dicts, constructed with nothing at all.

    Nothing to configure and nothing to point anywhere: `config/container.py` builds this for the
    all-fakes bundle exactly as it builds `FilesystemStore` for the real one, and the difference in
    the wiring is the constructor argument that is not there.

    Two of these share nothing. State is per instance, so a bundle built twice is two stores, which
    is the honest analogue of two `AGL_HOME` roots and is asserted in `test_memory_store.py`.
    """

    def __init__(self) -> None:
        # Serialised documents, keyed by address, and serialised the way `store.py` serialises them
        # - UTF-8 bytes, not text - so that the two stores hold the same form and a document one can
        # hold is a document the other can. Records are keyed by `scope.run` because there is one
        # per run and it belongs to the run - the port's clause, made structural: there is no key a
        # namespace could reach and so nothing to consult.
        self._records: dict[RunScope, bytes] = {}
        self._entries: dict[_EntryAddress, bytes] = {}

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        """The run's own record, or `None`. `scope.run` drops the namespaces, as the port says."""
        return _decoded(self._records.get(scope.run))

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        """Record what this run was asked to do, whole or not at all."""
        # Encoded first and stored second, which is the whole of both clauses: the encode is the
        # copy §3.6 asks for and it happens on the caller's own line of execution, and a document
        # that cannot be encoded costs an exception and no state. The assignment that follows is
        # one step, so a reader sees the old string or the new one and never a mixture.
        payload = _encoded(value, _record_address(scope))
        self._records[scope.run] = payload

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        """One recorded run of one step, or `None`. The digest is a key here, so it is not checked.

        See the module docstring: the port entitles an implementation that spends a digest as a
        *name* to check it first, which is a permission rather than a duty, and this one spends it
        as one third of a dict key. The parity suite pins the difference rather than leaving it.
        """
        return _decoded(self._entries.get((scope, step, digest)))

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        """Record what this run of this step produced. The write §3.6's ledger rests on."""
        # Encoded before it is stored, for `write_record`'s reason and with the same consequence.
        payload = _encoded(value, _entry_address(scope, step, digest))
        self._entries[(scope, step, digest)] = payload

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        """The namespaces recorded immediately under this scope, sorted by name.

        **Derived from the recorded addresses, never from an index.** The port's own answer to "an
        implementation that can only get and put by key has to keep an index and keep it current
        under concurrent writers" is that the cost is real; a second structure updated on every
        write is a second thing two children recording at once would have to agree about, and the
        concurrency clause is pushing back on exactly that. The addresses are already here, so this
        reads them.

        Only entries are scanned, and that is what makes a namespace appear because something was
        **recorded** under it and for no other reason. A run record is written at `scope.run`, so
        writing one from inside a namespace records nothing under that namespace and cannot conjure
        it; a step entry recorded at the run itself carries no namespaces and so is not a child
        line of work. The suite pins both.

        Immediate children only - the caller recurses through `RunScope.inside`, because §3.6 nests
        arbitrarily and a flattened answer would lose which parent each name hung from. Sorted by
        name, which is `store.py`'s choice inside the freedom the port leaves, made here too so
        that a `clear` traversal walks the same order against either store.

        Deriving rather than indexing is also the one place this answer can differ from the real
        store's, and the parity suite pins it: `shutil.rmtree` prunes no empty parent, so after a
        `remove` two or more levels deep the real store still names a namespace nothing is recorded
        under and this one does not. `clear` removes at depth zero, where the two agree exactly.
        """
        depth = len(scope.namespaces)
        found = {
            recorded.namespaces[depth]
            for recorded, _, _ in self._entries
            if _within(recorded, scope) and len(recorded.namespaces) > depth
        }
        return tuple(sorted(found, key=str))

    async def remove(self, scope: RunScope) -> None:
        """Remove this scope and everything recorded below it. Tolerant of absence.

        At depth zero that includes the run's own record, which is what `clear` wants: §3.10 takes
        a run away wholesale. Deeper it must not, because the record lives above the scope being
        removed and belongs to the run rather than to the worktree - `pop` is guarded on depth
        rather than on the record being there, so that reading the guard tells you which it is.

        Absence is tolerated by construction: `pop` is given a default and a subtree with nothing
        in it is an empty list of keys. `clear` after a crash is the ordinary case, and a teardown
        that raised on a half-finished setup is one every caller learns to wrap in a bare `except`.

        What is removed is *deleted*, not marked - a removed address is a free one, and nothing here
        keeps a removed run alive, which is what lets one process `clear` many without growing.
        """
        if not scope.namespaces:
            self._records.pop(scope.run, None)
        # Collected before anything is deleted: a dict may not be mutated while it is iterated,
        # and the list is the addresses rather than the documents, so it costs keys and not copies.
        for address in [address for address in self._entries if _within(address[0], scope)]:
            del self._entries[address]


def _within(address: RunScope, scope: RunScope) -> bool:
    """Whether `address` is `scope` itself or a scope nested anywhere inside it.

    The prefix comparison is the whole of §3.6's nesting rule as this store sees it: a scope's
    namespaces are the path from the run down to it, so everything below it shares that path as a
    prefix. Every part compares by value and by type - a `Namespace` is not equal to a `RunLabel`
    spelled the same way - so these are names being compared rather than text.
    """
    return (
        address.project == scope.project
        and address.label == scope.label
        and address.namespaces[: len(scope.namespaces)] == scope.namespaces
    )


def _encoded(value: Mapping[str, JsonValue], address: str) -> bytes:
    """`value` as the bytes this store will hold - and, by being those bytes, the copy of it.

    `dict(value)` and `allow_nan=False` are `store.py`'s decisions, taken here for the reasons the
    module docstring gives: the port admits a `MappingProxyType` that `json` refuses, and a
    non-finite float would otherwise be written as a token that comes back unequal to itself.

    `ensure_ascii=False` and the encode that follows it are the same decision one step further, and
    the module docstring argues them together: `store.py` writes a file, so its documents are the
    ones that have a UTF-8 encoding, and this store holds exactly those. A lone surrogate has none -
    it is an unpaired UTF-16 code unit, which `json.loads` will hand back from a tool payload and
    `JsonValue` admits as a `str` - so the encode is where both stores refuse it. Left at
    `ensure_ascii=True` the escape `\\ud800` would encode cleanly and this store would keep a
    document the real one cannot, which is precisely the drift §1.9's Rule 3 forbids.

    The refusal is `InternalError` because it is our own invariant that failed rather than the
    world's, and it names the address in AGL's own terms because a path is not something this store
    has to offer a reader. `UnicodeEncodeError` is a `ValueError`, so it needs no branch of its own
    here any more than it does in `store.py`.
    """
    try:
        return json.dumps(dict(value), ensure_ascii=False, allow_nan=False).encode(_ENCODING)
    except (TypeError, ValueError) as error:
        raise InternalError(
            f"{address} holds a value AGL cannot write down: {error}. A stored document is JSON, "
            f"and something above this port handed it one that is not"
        ) from error


def _decoded(payload: bytes | None) -> dict[str, JsonValue] | None:
    """The document `payload` holds, or `None` if nothing is recorded at the address it came from.

    `None` in means nothing recorded, and nothing else can produce it: a stored JSON `null` is a
    recorded value, and it is a value *inside* a document rather than a document, because both
    kinds of thing AGL stores are JSON objects. That is what makes the port's missing `exists`
    honest - absence is decided by the key not being there and never by what parsed.

    The decode is spelled out rather than left to `json.loads`, which would accept the bytes and
    sniff an encoding off their first characters. Sniffing is right for a parser handed input from
    anywhere and wrong here: these bytes came from `_encoded`, one function away, and saying
    `_ENCODING` in both places is what makes them a pair rather than two guesses that happen to
    agree - the same reason `store.py` names it on its read as well as on its write.

    Neither the decode nor the parse is guarded, and the asymmetry with `store.py` is deliberate:
    that module reads a file under `AGL_HOME`, which something other than AGL can have written, so
    it translates a foreign one into `UpstreamUnexpected` and checks that what parsed is an object.
    The only writer of these bytes is `_encoded` - which encodes a `dict`, and encodes it as
    `_ENCODING` - so every one of those branches here would be unreachable, with an error message
    no reader can ever be shown.

    What comes back is `json.loads`'s own containers, built fresh out of the text and deeply
    independent of anything this store holds. The caller may edit it to the bottom.
    """
    if payload is None:
        return None
    document: dict[str, JsonValue] = json.loads(payload.decode(_ENCODING))
    return document


# The three below are `store.py`'s, word for word, duplicated rather than shared because they are
# private to that module. The moment a third `Store` wants them they become a module both import.


def _scope_address(scope: RunScope) -> str:
    """A scope in AGL's own words: the project, the label, and the namespaces it is nested in."""
    nesting = "/".join(str(namespace) for namespace in scope.namespaces)
    inside = f", inside {nesting}" if nesting else ""
    return f"project {str(scope.project)!r}, run {str(scope.label)!r}{inside}"


def _record_address(scope: RunScope) -> str:
    """A run's record. `scope.run` because there is one per run and it belongs to the run."""
    return f"the run record for {_scope_address(scope.run)}"


def _entry_address(scope: RunScope, step: StepName, digest: str) -> str:
    """One step entry: the three parts that are together its address, in the port's vocabulary."""
    return f"the entry for step {str(step)!r} at digest {digest!r} in {_scope_address(scope)}"
