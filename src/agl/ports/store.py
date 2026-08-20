"""`Store` - what AGL has already done, addressed by name and written whole.

Two kinds of thing are kept here and no others. A **run record** is what a run was asked to do -
`RunSpec` - one per run, written when the run starts and read back by every resume. A **step
entry** is what one run of one step produced, addressed by the scope that ran it, the step's name,
and the digest identifying that run of it. Everything AGL knows that outlives the process is one
of those two, and both are kept as whole JSON documents this port never looks inside.

## Writes are atomic, and the rest rests on that

**A written value exists complete or not at all**: a reader sees either the whole of a value or
nothing recorded at that address - never a prefix, never a mixture of two values.

That is not tidiness. §3.6 makes the *existence* of a step entry the ledger - a step's status is
derived from which entries exist, which is why nothing in AGL stores a status - so a value that
can be half-written is a step that looks done and is not. The next resume reads it, believes it,
and replays a result that was never produced, with no second record anywhere to disagree.

Declared here because an obligation has to be stated where both sides of it can see it. Stage 3.1
writes the contract suite that asserts this and stage 4.1 writes the implementation held to it;
both are downstream of this sentence, and a requirement invented in a suite is one an
implementation can argue with.

## It speaks identifiers, and never accepts a location

§1.10's charge against the previous implementation is one line of it: `paths.run_dir(home, label)`
computed a filesystem path and handed it to the store, so a helper shaped like one implementation
decided where the port kept its things - and nothing shaped differently could afterwards be put in
its place.

Every method below is addressed by `RunScope`, `StepName` and a digest, which are names the
framework already had. An implementation is constructed with whatever root, endpoint or connection
it needs - by `config/container.py`, like every other adapter - and derives its own layout from
those names: a filesystem implementation has `home_layout` to derive it with, another has whatever
it uses. This module imports `home_layout` for `RunScope` alone, which is two names and a tuple of
a third and carries no location, and calls nothing there. No caller computes an address for this
port, and this port hands none back.

`workspace.py` makes the same argument from the other side, and the asymmetry between the two is
deliberate rather than an oversight. A `Workspace` may *expose* a `Path`, because a workspace
genuinely is a place an agent runs in and something has to point at it. A `Store` may not *accept*
one, because where AGL keeps its own records is the store's business and nobody else's.

## Whole JSON objects, and not an entry type

**Both kinds of document AGL stores are JSON objects.** A run record is `RunSpec`'s eight fields.
A step entry is §3.6's four - `fingerprint`, `value`, `head`, `at` - whose own `value` field may
be `null` for an effect step while the entry around it never is. So the writes take a
`Mapping[str, JsonValue]` and the reads answer with a `dict[str, JsonValue]` or with `None`, and
that narrowing costs nothing: there is no document AGL wants to keep that it turns away.

What it buys is the clause below it. **`None` from a read means "nothing recorded here" and can
mean nothing else** - not a stored `null` that happens to look the same on the way back. That is
what makes the absence of an `exists` member honest rather than merely convenient: the question is
answered exactly, by the read, and not by a habit about what AGL happens to write. Stage 3.1's
suite can assert it as a settled contract.

An object, but not *the* entry type, and the two reasons point the same way. Those four fields are
the journal's shape, and the journal is `sdk/_engine/journal.py`, which `ports` may not import
(contract 1). The run record's field-by-field mapping is already `RunSpec.to_json` and
`from_json`, deliberately on that type, where the two directions can be read side by side and so
keep agreeing. This port therefore keeps documents at addresses and still does not know what is
inside them - which is what lets the journal's shape change, a fifth field or a renamed one,
without this port, its suite or any implementation of it noticing. `JsonValue` comes from
`ports/run.py`, and this direction of import is the one contract 2 leaves open: a port may import
a pure type, and the pure type may not import the port.

`Mapping` on the way in, a `dict` on the way out. In, because a caller should not have to copy
what it already has in order to hand it over - `MappingProxyType` is a `Mapping` and so is the
`dict` `RunSpec.to_json` returns. Out, because a read hands back something the caller owns: an
implementation holding its documents in memory would otherwise be handing out its own state, and
the first caller to edit what it read would edit the store.

## Concurrency

**Distinct addresses are independent.** Two child runs recording a step at the same moment need no
coordination from the caller and must not need any inside the implementation either. §3.6 gives
every step its own address precisely so that a completion is one write - no lock, no
read-modify-write, nothing serialised that has no reason to be serial. An implementation that
would have to put every write behind one mutex, because everything it holds is one document, is
not satisfying this port. Stage 3.1 asserts this as a clause in its own right.

**One address, two writers, one whole value.** Which of the two survives is unspecified and
nothing depends on it: replay writes an entry only after failing to read one, and §3.10 has a run
hold a lock, so AGL does not aim two writers at one address on purpose. The clause is here to
forbid the third outcome - a value made of both - which is the atomic-write requirement again,
stated for the case where the collision is another writer rather than a crash.

## What is deliberately not here

**No `exists`.** A read that returns `None` is that question with the answer already attached -
exactly, because a read answers with an object or with `None` and never with a value that could be
either. A separate predicate would be a second thing every implementation has to keep consistent
with the first, and a second moment at which the answer could already be stale.

**No listing of runs, and none of projects.** §3.10 has no `status` command and no way to ask what
runs there are: `resume` takes a label, `clear` takes a label, and `workflows` lists what is
registered rather than what has run. A member nothing calls is still one every implementation must
provide and every suite must assert.

**No listing of steps or of entries.** Replay computes the digest it is looking for and asks for
that one (§3.6), so nothing enumerates them. Superseded entries are kept - they are what answers
"why did this re-run" - and they are kept for a person to read, not for the framework to walk.

**No delete of a single entry.** The same fact from the other end: nothing prunes and nothing
supersedes on purpose, and `clear` takes a run away whole.

**No transaction, no batch, no flush.** A batch would need a boundary, a boundary would need a
failure mode, and the only invariant AGL actually needs is the one already stated per write. A
flush would be this port admitting to a buffer, which is that same clause's opposite.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping

from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue

__all__ = ["Store"]


class Store(ABC):
    """Run records and step entries, kept at addresses made of names.

    **A written value exists complete or not at all** - see the module docstring for why that one
    clause carries the rest of them. It is restated on both writes because it is the requirement
    an implementation has to go out of its way to meet, and the one a plausible implementation
    fails silently.

    **Every method is `async`, uniformly.** Not because a local implementation needs it, but
    because one that is not local has to be able to await, and because the terminal's redraw loop
    shares this event loop: a read that blocked would stall the display for exactly as long as it
    took. Making the writes awaitable and the reads not would be a distinction every caller has to
    remember, in exchange for nothing.
    """

    @abstractmethod
    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        """The run's own record, or `None` if nothing is recorded for this run.

        `None` is what `resume` turns into a `NotFoundError` and what `run` reads as a free label
        (§3.10). This port reports absence and holds no policy about what it means.

        There is one record per run and it belongs to the run, so a scope's namespaces are not
        consulted: asked from anywhere inside a run, this answers with that run's record.
        `home_layout.run_record` resolves the same way, for the same reason, and says so too.

        The document is whatever was written, in a fresh mapping the caller owns.
        `RunSpec.from_json` is what turns it into a `RunSpec`, and it is that method - not this
        one - that refuses one AGL cannot read back.
        """

    @abstractmethod
    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        """Record what this run was asked to do. Written at the start, read by every resume.

        **The value exists complete or not at all**: a reader sees the whole of it or sees nothing
        recorded there. A half-written record is a run that cannot be resumed and cannot be
        explained, and it is the one value in AGL that has no other copy anywhere.

        Namespaces are not consulted, exactly as in `read_record`. Writing where a record already
        exists supersedes it rather than raising: §3.10 has `run` refuse a label that already
        exists long before anything reaches this port, so a refusal here would do nothing but make
        an interrupted first write unrecoverable.
        """

    @abstractmethod
    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        """One recorded run of one step, or `None` if nothing is recorded at this address.

        The three arguments are the whole address and each carries its own weight. `scope` says
        which line of work ran it - the same step name under two children is two entries, which is
        why §3.6 nests `steps/` inside each worktree rather than pooling them. `step` says which
        step. `digest` says which *run* of that step, because a step re-run against changed inputs
        gets a different digest and its own entry beside the old one.

        `digest` is opaque here: the journal composes it, and this port neither computes it nor
        parses it back. An implementation that spends it as a name of its own checks it first -
        `home_layout._checked_digest` is where a filesystem implementation does - because all this
        port promises is a `str` that the same journal produced.

        `None` is the whole of replay's decision: no entry means run the step (§3.6). It is asked
        once per step on every run and every resume, and an entry comes back as a fresh mapping the
        caller owns - the journal reads fields out of it and holds on to nothing of the store's.
        """

    @abstractmethod
    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        """Record what this run of this step produced.

        **The value exists complete or not at all**: a reader sees the whole of it or sees nothing
        recorded there. This is the write that clause was written for. §3.6 derives a step's status
        from whether its entry exists, so a torn entry is a step that reads as done, hands back a
        truncated result and is believed - there is no stored status to contradict it and nothing
        recomputes it. Landing here is the last thing a step does; until it lands, the step did not
        happen, and that is the property replay is built on.

        Writing where a value already sits supersedes it. Entries at other digests are untouched:
        superseded entries stay on purpose, because they answer "why did this re-run", and they go
        when the run does (§3.6, §3.10).
        """

    @abstractmethod
    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        """The namespaces recorded immediately under this scope, in a stable order.

        Immediate children only, and the caller recurses through `RunScope.inside`: §3.6 nests
        arbitrarily, and a flattened answer would lose which parent each name hung from - which is
        the whole of what the caller needs it for.

        **One consumer, and it is the reason this member exists.** `clear` (§3.10) has to take back
        every child workspace and delete every child line of work, and AGL's own records are the
        only place the set of namespaces a run used is written down: `WorkspaceProvider`
        deliberately offers no enumeration, for the reasons that module states.

        **The accepted cost.** A crash between provisioning a workspace and recording anything
        under it leaves nothing here, so `clear` cannot know about that one and its line of work
        survives. §3.10 calls that the cheap half of the asymmetry - a retained name costs a stale
        ref, a wrongly deleted one costs the run.

        *Stable order* means the same recorded set yields the same sequence every time, so a
        traversal is reproducible and a failure is the same failure twice. Sorting satisfies it;
        this port does not say sorted by what, because the order is nothing but a tie-break.

        **This is the one member asking for more than access by address.** The four above are
        lookups; this is enumeration under a scope, and so is `remove`. An implementation whose own
        addressing can be enumerated gets both for nothing. One that can only get and put by key
        has to keep an index and keep it current under concurrent writers - which is the
        concurrency clause pushing back on it. That cost is real, and it is accepted for the one
        caller above.
        """

    @abstractmethod
    async def remove(self, scope: RunScope) -> None:
        """Remove this scope and everything recorded below it.

        At depth zero that is the run - its record, its entries, and every nested scope under it -
        which is what `clear` wants, §3.10 removing a run wholesale. Deeper, it is that worktree's
        subtree and nothing above it.

        **Tolerant of absence.** Removing what is not there succeeds and says nothing. `clear`
        after a crash is the ordinary case rather than the exceptional one, and a teardown that
        raises on a half-finished setup is a teardown callers learn to wrap in a bare `except`.
        `WorkspaceProvider.remove` says this in the same words, for the same reason.

        **Not required to be atomic**, and it is worth saying why the clause governing every write
        above is not asked for here. A removal that stops halfway leaves less than there was, never
        something that reads as more, and tolerance of absence makes running it again the whole of
        the recovery. Demanding all-or-nothing would ask every implementation for a transaction
        over an unbounded subtree in exchange for a guarantee nothing needs.
        """
