"""Fingerprints and entries - what decides whether a step replays, and what it replays from.

Two halves of §3.6 that meet at one string. A **fingerprint** is the digest a step's role, inputs
and starting head hash to; an **entry** is the file that digest names, holding what the step
produced. A resume computes the first and looks for the second, and everything else in the design
- `last_good`, the pre-run wipe, a run that survives being killed - is built on those two lines
agreeing about one name.

§3.6 writes the fingerprint in three lines, and the first half of this module is those three lines:

    base   = sha256(canonical_json({role, inputs, head}))
    n      = times `base` was used earlier in this namespace, for this step name  (0, 1, 2, ...)
    digest = sha256(base + ":" + str(n))                            <- the entry's filename

`canonical_json` is the text, `base_of` is the hash of it, and `Fingerprints` is `n`. Three names
rather than one call, deliberately: the replay walk needs them at different moments - a base
computed before there is anything to look up, a counter that ticks once per invocation whether the
step replayed or ran - and a rule that can only be broken all at once is a rule nobody can show is
load-bearing one piece at a time.

**Every rule below fails the same way, and the way is silence.** Not an exception, not a wrong
answer, not a damaged file: a digest that differs from the one already on disk, an entry that is
therefore not found, and a step that runs its agent again and writes a second entry beside the
first. The run still finishes and the output is still right. The only symptoms are the bill and the
wait. That is why §3.6 states three of these in the plan itself rather than leaving them to this
stage, and it is why each rule below is written with its failure attached rather than as a
convention.

**Rule 1 - the counter is scoped per `(namespace, step name)`, and never per invocation.** The key
is `(scope, step, base)`. Concurrent siblings produce identical bases by construction: `T-01` and
`T-02` both call `step("implement", implementer)` with the same role, no inputs, and the same parent
head, so nothing about the two calls differs except which worktree they are in. A per-invocation
counter lets the interleaving decide which of them gets `n = 0`; the interleaving differs on resume,
so on the second run each child looks in its own scope for a digest that is not there and both
re-run, forever, silently. Scoping to the namespace makes it deterministic under concurrency,
because siblings occupy different namespaces. The step name is in the key for a smaller reason that
is just as sharp: two differently-named steps sharing a role, inputs and head are recorded under
different `steps/<name>/` directories, so their counts are separate ledgers and have to be separate
counts.

**Rule 2 - sort every set, wherever it appears.** `frozenset[Restriction]` has no stable iteration
order across processes: `Restriction` is a `StrEnum`, `Enum.__hash__` hashes the member name, and
`PYTHONHASHSEED` randomises it. Measured while this was written, seeds 1, 3, 5, 11, 13 and 31337
produce several different iteration orders of `frozenset(Restriction)` on this machine, which is
the whole failure in one line: same role, same inputs, same head, different digest tomorrow. The
port is right to promise no ordering - a set is not a level and has none - so sorting is this
module's obligation and nobody else's. The obligation is not discharged by sorting `restrictions`
on the way past, either: a set reached through `inputs` has the identical defect, including one
`dataclasses.asdict` hands back out of a frozen dataclass field, which it deep-copies as a
`frozenset` and not as a list. So the sort lives in the walker, at every depth, keyed on each
element's own canonical text - a total order that does not ask the elements to be comparable with
one another.

**Rule 3 - `**inputs` must be JSON-serialisable, and the refusal has to say where.** Dataclasses go
through `dataclasses.asdict` and everything else is refused. §3.3's own tickets example passes
`findings=highs`, a list of the workflow's own dataclasses, and the one-line shortcut that would
make that work is `repr()` - whose default embeds an object id, so the text differs in the next
process and the fingerprint with it, which is rule 2's failure arriving through a different door.
The `InputError` names the offending type *and* the path to it inside `inputs`
(`inputs.findings[0].deadline is a datetime`), because a value nested three levels down a list of
dataclasses is not findable from its type alone, and it says why: this value would be fingerprinted,
and a fingerprint is compared on resume.

**Rule 4 - a tool contributes its name, its description and its payload schema, and nothing else.**
`Tool.__post_init__` wraps `payload_schema` in a `MappingProxyType`, `JsonValue` deliberately
excludes `Mapping`, and `json.dumps` on a `mappingproxy` raises `TypeError` - the one rule in §3.6
that at least fails loudly, and it fails on the first call. The walker rebuilds every `Mapping` as a
`dict`, at every depth rather than once at the top, so a schema holding a nested proxy is covered by
the same line. `Tool.handler` must never enter the fingerprint at all: it is a callable whose `repr`
embeds an object id, so putting it in would make every step's digest differ from the one it wrote
last time. Tools keep their declared tuple order and are **not** sorted - the author wrote that
order, it is stable across processes, and reordering the tools a model is offered is a real change
to the role.

**Rule 5 - canonical JSON means sorted keys and one fixed compact separator.**
`sort_keys=True, separators=(",", ":")`. Without the first, two mappings holding the same pairs in
different insertion orders are two fingerprints; without the second, a `json.dumps` default that
ever changes is a silent reformat of every base ever computed. Both flags are written in exactly one
expression below, `_dumps`, which is what keeps the text that is hashed and the text a set is sorted
on the same text.

## The entry, and why the file existing is the whole of the ledger

`Entry` is the other half, and §3.6 gives it four fields - `fingerprint`, `value`, `head`, `at` -
in that order and with no fifth. There is no completion record, no status and no marker beside it:
**a step is done when its file is there**, which is why `ports/run.py` has no `RunStatus` and why
nothing in AGL stores one. Two consequences follow directly and both are load-bearing.

**The `Store`'s atomic-write clause stops being hygiene and becomes the design.** A torn entry is
not a damaged file to be re-read; it is a step that reads as done, hands back half a result and is
believed, with nothing anywhere to disagree. `adapters/filesystem/store.py` spends an `os.replace`
on that sentence and `ports/store.py` restates it on both writes.

**One file per step, named by its digest.** Two concurrent children each write one path and never
meet - no lock, no coordination, nothing serialised that has no reason to be. A single `steps.json`
would need a read-modify-write under a mutex on every completion, which is the same design charged
with turning concurrent siblings into a queue. Superseded entries stay on disk, because they are
what answers "why did this re-run", and `Store.remove` takes a run away whole rather than pruning.

`value` is JSON and is never deserialised here. It can only have come from a reporting tool's
payload (JSON by construction - it arrived as a tool call), a human's answer, or `null` for an
effect step, and the typed dataclass a workflow eventually sees is the Role's business at stage 12.
A stale entry is discarded rather than failing to parse, and that falls out free: changing the
declared type changes the tool schema, which changes the fingerprint (§3.6).

`head` is the worktree HEAD **after** the step completed - the reset target the replay walk chains
`last_good` from. It is checked non-empty and nothing else. `ports/run.py::_check_sha` is that
module's rule about what a *pin* looks like, for `base_sha`, and a second copy of it here would be
a second source of truth about what a commit name is - free to disagree the day AGL meets a
repository that spells one differently. A head that is not one fails loudly at `restore`, in the
adapter that actually knows what git accepts.

**A `fingerprint` that disagrees with the path is a miss, not a fault.** §3.6: "match on path
**and** fingerprint, else re-run." The filename already *is* the digest, so the two agreeing is
what AGL writes every time and a disagreement means a ledger written by another version of AGL,
corrupted, or hand-edited. `read_entry` answers `None` and the step runs again. Re-running costs
tokens and is never wrong; raising would strand a run that could have finished, over a file the
person holding the terminal did not write.

**`at` is never read for control flow**, which is the whole of what makes an injected `Clock` safe
rather than a hole - `ports/clock.py` makes that argument at length. Below, `at` is written down,
normalised, formatted and parsed - and never compared, never tested and never used to choose
anything. `read_entry` does not mention it at all. That is the shape to keep: grep the field and
every occurrence should sit in a constructor, a normalisation or one of the two wire directions,
and none of them in a condition.

## The walk, and the one value it is forbidden to look up

`Journal` is §3.6's replay loop over one namespace: compute the base from the role, the inputs and
the starting head; take the counter; read; and either hand back what is recorded or restore, run,
commit-or-wipe, and write. The two halves above are what it is built out of, and the loop adds
exactly one piece of state - `last_good`, the commit this namespace is known to be at.

**`last_good` is chained logically from recorded entries and is never read from the physical
worktree**, which is the sentence §3.6 calls load-bearing and the reason `step` computes its own
base rather than accepting a head. The failure is silent and total: the root runs `spec` at H0,
children integrate and advance the run's own line to H5, and a resume that asked the worktree where
it was would recompute `spec` against H5, miss, and re-run - every step, every resume, forever,
with the run still finishing and still right. The only symptoms are the bill and the wait, which is
the failure mode every rule in this module shares.

**Where stage 14's write lands, and what it costs to leave out.** A child landing moves the
parent's physical head, and `integrate()` is not a step, so nothing journals it - the parent's
`last_good` still names a commit from before the landing. §3.6: "`IntegrationOutcome.head` carries
the value; the engine must write it into the parent's chain", and this is "the one path in the
design that destroys work rather than costing a re-run". The write lands on `Journal._last_good`,
from `sdk/_engine/integration.py` at deliverable 14.1, through an `advance(head)` that is
deliberately **not** built here: there is no `integrate()` to call it, and a mutator with no caller
is an untested one. What 11.3 owes 14.1 is that the mechanism stays reachable - `last_good` is
instance state on this object, not a local in a loop - and that the cost of forgetting it is
written down where the field is. Forgetting it does not cost a re-run: the parent's next
fingerprint miss restores to a commit before every landed child and deletes all of it.

## Why `InputError`, where `ports/run.py` says `InternalError`

`ports/run.py::_checked_json` is the direct ancestor of the walker below and refuses most of the
same shapes. It raises `InternalError`, and is right to: AGL writes `run.json` itself, so a value it
cannot store is our bug and exit 70 says so. Here the offending value arrived in a workflow author's
`**inputs`, which is exactly what `errors.py` calls an `InputError` - nothing has been attempted,
and exit 2 sends the reader to their own declaration rather than hunting for a bug in the framework.
The divergence from the file this one is modelled on is deliberate, and is stated here rather than
left to be discovered as an inconsistency.

**The entry half goes back to `InternalError`, and by the same test rather than in spite of it.**
Nobody types a step file: AGL writes it and AGL reads it, so a missing field, an unknown key or an
`at` that is not a timestamp means either that we wrote it wrong or that something outside AGL
changed it - indistinguishable here, and `ports/run.py` says the same of `run.json` in the same
words. Exit 70 reads as "file a bug", which is right for the first and survivable for the second.
The rule is not "this module raises `InputError`"; it is that the class names whoever the fault
belongs to, and the two halves of this module take their values from different people.
"""

import dataclasses
import json
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import Final

from agl.ports.agent import ModelId, Restriction, Tool
from agl.ports.clock import Clock
from agl.ports.errors import InputError, InternalError
from agl.ports.home_layout import RunScope
from agl.ports.ids import StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.workspace import Workspace

__all__ = [
    "Entry",
    "Fingerprints",
    "Journal",
    "base_of",
    "canonical_json",
    "read_entry",
    "write_entry",
]


# Rule 5, and the only place these are written - see `_dumps`.
_SEPARATORS: Final = (",", ":")

# §3.6's four entry fields, in the order that section writes them. This is the published shape of
# every file under `steps/`, which a later AGL reading an older ledger depends on - and which the
# real store preserves, `json.dumps` keeping insertion order where it is not asked to sort.
# `to_json` spells them out again rather than looping over this, so the shape is readable where it
# is produced and renaming a field cannot silently rename a key; the suite pins that the two agree.
_WIRE_KEYS: Final = ("fingerprint", "value", "head", "at")

# `2026-08-18T09:16:41Z` - UTC, whole seconds, the `Z` the plan writes and not `isoformat`'s offset.
# The same twenty characters as `ports/run.py::_WIRE_TIME`, and deliberately a second copy of them:
# that one is private to the module that owns `run.json`, and reaching through another module's
# underscore would tie this stored format to a name that module is free to change. Two spellings of
# a timestamp in one AGL_HOME is a bug waiting for a reader, so the copy is not left to a comment -
# the suite builds an `Entry` and a `RunSpec` from one `datetime` and compares the text they write.
_WIRE_TIME: Final = "%Y-%m-%dT%H:%M:%SZ"

# Unicode's category for a surrogate: the one kind of code point a `str` may hold and UTF-8 cannot
# encode at all. `ports/run.py::_checked_text` refuses these at the store's boundary for its own
# reason; `_checked_text` below argues why a hash that is never read back refuses them too.
_SURROGATE: Final = "Cs"


def canonical_json(value: object) -> str:
    """`value` as canonical JSON text: sorted keys, compact separators, sets sorted, pure ASCII.

    Raises `InputError` naming the type and the path to anything it cannot canonicalise. The text
    exists to be hashed and is never stored, never read back and never parsed - `base_of` is its
    only caller in this module, and the suite is the only other one.
    """
    return _dumps(_canonical(value, "value"))


def base_of(
    *,
    instructions: str,
    model: ModelId,
    restrictions: AbstractSet[Restriction],
    tools: Sequence[Tool],
    inputs: Mapping[str, object],
    head: str,
) -> str:
    """§3.6's `base`: the sha256 hexdigest of the canonical JSON of role, inputs and head.

    The role arrives as its constituents rather than as a `Role`, because `sdk/roles.py` is empty
    until stage 12; the fields it will hold are these, and stage 12 passes them in.

    **Why each term is in it.** The role, so that halting to edit the implement prompt and resuming
    does not replay results the old prompt produced - which is exactly when you are iterating and
    least want stale output, and what gives the cascade its build-system shape. The head, because a
    `review` step takes no inputs at all: it reviews the worktree, so without the head term a
    re-run of `implement` producing different code would leave review's fingerprint unchanged and
    it would wrongly replay. The workspace is an input; it is only not a named one.
    """
    # This shape is a **stored format**. Every digest ever written was computed from these keys in
    # this arrangement, so changing one - renaming `payload_schema`, adding a term, dropping one -
    # makes every step recorded under the old shape miss and re-run its agent. It is the same
    # argument `ports/agent.py` makes at the top about spelling its enum values out instead of
    # using `auto()`, and it is why the object below is written with named keys where §3.6 writes
    # the role as a tuple: a positional array's meaning lives only in this file, and inserting a
    # term into one shifts every element after it.
    role: JsonValue = {
        "instructions": _canonical(instructions, "role.instructions"),
        "model": str(model),
        "restrictions": _canonical(restrictions, "role.restrictions"),
        "tools": [
            {
                "name": _canonical(tool.name, f"role.tools[{index}].name"),
                "description": _canonical(tool.description, f"role.tools[{index}].description"),
                "payload_schema": _canonical(
                    tool.payload_schema, f"role.tools[{index}].payload_schema"
                ),
            }
            for index, tool in enumerate(tools)
        ],
    }
    fingerprinted: JsonValue = {
        "role": role,
        "inputs": _canonical(inputs, "inputs"),
        "head": _canonical(head, "head"),
    }
    return sha256(_dumps(fingerprinted).encode("utf-8")).hexdigest()


class Fingerprints:
    """The counter `n`, scoped per `(namespace, step name)`. One instance per run.

    `next` is called **once per step invocation, whether that step replays or re-runs**, and that
    is the whole mechanism behind §3.6's "`n` is never persisted; replay walks the same calls in
    the same order and reproduces the same values". A counter that ticked only on a miss would
    produce `n = 0` on the second run of a step that replayed at `n = 1` on the first.

    A plain class and not a dataclass, and deliberately mutable: it is the one piece of state the
    journal keeps, it exists to be advanced, and a frozen thing returning a new copy would leave
    every caller responsible for threading it - which is the per-invocation counter rule 1 refuses,
    wearing a different hat.
    """

    def __init__(self) -> None:
        # No lock, and none needed. `next` is synchronous and contains no `await`, so under asyncio
        # the read-modify-write below cannot interleave with another call to it - the engine is
        # single-threaded by construction, and a step's siblings are tasks on one event loop.
        self._counts: dict[tuple[RunScope, StepName, str], int] = {}

    def next(self, scope: RunScope, step: StepName, base: str) -> str:
        """The digest for this invocation, advancing the count for `(scope, step, base)`.

        Shadowing the builtin as a *method* name is fine and is kept: `counter.next(...)` reads as
        the next one, and nothing in this module or any other loses access to `next()` by it.
        """
        key = (scope, step, base)
        count = self._counts.get(key, 0)
        self._counts[key] = count + 1
        return sha256(f"{base}:{count}".encode()).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:
    """One recorded run of one step - §3.6's four fields, and the fact that the step finished.

    Frozen, because an entry is a statement about something that has already happened: the step ran,
    it produced this, and the tree was at that commit when it did. Nothing amends one. A step that
    runs again is a new digest and a new file beside the old one, which is what leaves the ledger
    answering "why did this re-run" instead of only "what is true now".

    Modelled on `ports/run.py::RunSpec` down to the shape of its two mapping methods, and for the
    same reason: the field names below *are* a file's format, so both directions live here, side by
    side, where they can be read against each other. A change to what is written here is a change to
    a file another version of AGL may be about to read.
    """

    fingerprint: str
    """The digest this run of the step was recorded under - the same string the file is named for.

    Written down although the path already carries it, and §3.6 says why in four words: "match on
    path **and** fingerprint". The path is a name a filesystem hands back; this is what the writer
    believed it was writing. `read_entry` compares them and treats a disagreement as a miss."""

    value: JsonValue
    """What the step produced: a reporting tool's payload, a human's answer, or `None` for an
    effect step.

    **A `None` here is a recorded null, not an absence.** The absence is `read_entry` answering
    `None`, and the two are different answers to different questions - `ports/store.py` promises
    exactly that separation ("`None` from a read means nothing recorded here and can mean nothing
    else"), and an effect step, whose value is always null, is the case that turns on it. Confusing
    the two would present as replay simply never hitting for every step that commits."""

    head: str
    """The worktree HEAD **after** this step completed - the reset target.

    Non-empty and nothing more; the module docstring argues why a second copy of
    `ports/run.py::_check_sha` would be a second source of truth rather than a second safety net."""

    at: datetime
    """When the step completed. Debugging and the view (§3.6), and never read for control flow.

    Aware, normalised to UTC and to whole seconds, because whole seconds is what the wire form
    carries and a field cannot honestly hold more than it stores - `RunSpec.created_at` word for
    word, so that one AGL_HOME holds one spelling of a timestamp."""

    def __post_init__(self) -> None:
        # Emptiness is the whole of what is asserted about the two strings, and they get there by
        # different routes. A fingerprint's shape is already settled by what it is compared with -
        # and `home_layout._checked_digest` refuses anything that is not a digest before a file is
        # named for one. A head is git's to judge, at `restore`, where the judging happens anyway.
        for name, value in (("fingerprint", self.fingerprint), ("head", self.head)):
            if not value:
                raise InternalError(f"a step entry's {name!r} is empty, and that names nothing")
        object.__setattr__(self, "at", _normalised(self.at))

    def to_json(self) -> dict[str, JsonValue]:
        """This entry as the `dict` its file holds. A pure function of `self`; writes nothing.

        The keys are written out rather than read off the field names, so renaming a field here
        cannot silently rename a key in a file another version of AGL is about to read - and they
        are written in §3.6's own order, which is the order they appear in the file.
        """
        return {
            "fingerprint": self.fingerprint,
            "value": self.value,
            "head": self.head,
            "at": format(self.at, _WIRE_TIME),
        }

    @classmethod
    def from_json(cls, data: object) -> Entry:
        """An entry read back off the ledger. Takes `object`, because a parsed file is anything.

        The field checks are the constructor's, so an entry built in memory and one read off disk
        are held to one standard by one piece of code. What is left here is the file's own shape:
        an object, with exactly these four keys, whose three text fields are text and whose `at`
        parses. Everything wrong with one is an `InternalError` - nobody types these files.

        **Unknown keys are refused rather than ignored**, which is `RunSpec.from_json`'s stance and
        is worth the cost it carries. A file holding a fifth field was written by a version of AGL
        that knew something this one does not, and replaying from the four fields we recognise
        would be acting on a record we have already been told we do not fully understand. Refusing
        is louder than a miss, deliberately: a miss re-runs one step, and a ledger from another
        version is a whole run's worth of that.
        """
        if not isinstance(data, Mapping):
            raise InternalError(f"a step entry is a JSON object, not a {type(data).__name__}")
        missing = [key for key in _WIRE_KEYS if key not in data]
        unknown = sorted(repr(key) for key in data if key not in _WIRE_KEYS)
        if missing or unknown:
            raise InternalError(
                f"a step entry's keys are not an entry's: missing {missing}, unexpected {unknown}. "
                f"An entry carrying keys AGL does not know was written by another version of it, "
                f"and this module refuses entries rather than migrating them"
            )
        try:
            at = datetime.fromisoformat(_wire_text(data, "at"))
        except ValueError as error:
            raise InternalError(
                f"a step entry holds an 'at' AGL cannot read back: {error}"
            ) from error
        return cls(
            fingerprint=_wire_text(data, "fingerprint"),
            # Passed through exactly as it parsed, and `key in data` above is what already
            # distinguished a stored `null` from a missing field - so an effect step's entry
            # arrives here as a `value` of `None` and stays one. There is deliberately no third
            # copy of `ports/run.py::_checked_json` walking it: `Store.read_entry` answers with a
            # `dict[str, JsonValue]`, so what arrives is JSON by construction - it came out of a
            # `json.loads` in one store or the other - and a value AGL cannot write down is refused
            # by the store at the write, with the address named.
            value=data["value"],
            head=_wire_text(data, "head"),
            at=at,
        )


async def read_entry(store: Store, scope: RunScope, step: StepName, digest: str) -> Entry | None:
    """The entry recorded at this address, or `None` if there is nothing here to replay from.

    Two different absences answer `None`, and §3.6 makes both of them the same instruction - run
    the step: nothing is recorded at the address, which is the port's own `None`; or something is
    recorded and its `fingerprint` disagrees with the digest it is filed under.

    **The second is a miss and not an error.** The filename *is* the digest, so writing the two
    apart is not something AGL does - a disagreement means a ledger written by another version of
    AGL, a corrupted file, or one edited by hand. Re-running the step costs tokens and is never
    wrong. Raising would strand a run that could have finished, at the moment its owner is least
    able to do anything about it, in exchange for a report about a file they did not write. §3.6's
    "match on path **and** fingerprint, else re-run" is that whole sentence in five words, and the
    `and` is the part this function exists to spend.

    A free function taking the `Store`, rather than a method on something holding one: the replay
    walk that calls it is 11.3's, and the object it wants is 11.3's to shape.
    """
    document = await store.read_entry(scope, step, digest)
    if document is None:
        return None
    entry = Entry.from_json(document)
    # Parsed first and compared second, which decides one case worth naming: a file that is both
    # mis-shaped and mis-filed is refused rather than missed. Shape is a fault - AGL reads back
    # what AGL writes - and identity is a question, which is what the comparison answers.
    if entry.fingerprint != digest:
        return None
    return entry


async def write_entry(
    store: Store, scope: RunScope, step: StepName, digest: str, entry: Entry
) -> None:
    """Record what this run of this step produced. The last thing a step does, and the ledger.

    One `Store.write_entry`, which under the real adapter is one `os.replace` on one path: no lock,
    no read-modify-write, nothing serialised. That is what §3.6 buys with a file per step, and the
    reason the alternative is not a smaller version of this - one `steps.json` would put every
    completion behind a mutex and turn concurrent siblings into a queue.

    **The digest is passed and is not taken from `entry.fingerprint`, and nothing here compares
    them.** The address is the caller's, because the port's write takes it, and AGL's own
    composition puts one string in both places. The comparison §3.6 asks for is on read, where a
    disagreement costs a re-run; making it a refusal here would instead throw away the result of a
    step that has already run and already been paid for - a worse answer to a fault whose only
    known cause is a file AGL did not write.

    Superseded entries stay. A second digest under the same step name is a second file beside the
    first, which is what answers "why did this re-run", and `Store.remove` takes a run away whole.
    """
    await store.write_entry(scope, step, digest, entry.to_json())


class Journal:
    """The replay walk over one namespace - §3.6's loop, and the three moments it uses `restore`.

    One of these per namespace: the run's own steps go through the `Journal` built over the run's
    scope and its `_base` workspace, and each child worktree gets its own over `scope.inside(...)`
    and its own checkout. What they share is a `Fingerprints`, and only that; see below.

        entry = read(steps/<name>/<digest>.json) or None
        if entry: last_good = entry.head; return entry.value
        restore(last_good)                       # unconditional - see below
        result = run_worker()
        commit_all(commit) if commit is not None else restore(last_good)
        write(path, {fingerprint, value: result, head: head(), at: now()})
        last_good = head()
        return result

    **`last_good` is initialised to `base` and is never `None`.** §3.6 writes the pre-run guard as
    `if last_good:`, as though there were a moment before the chain starts. There is not, and three
    separate things say so. The first step in a namespace still has a logical starting head, and
    the only honest one is the commit the namespace was opened from - which is why §3.6 makes
    `run.json`'s `base_sha` "pin the resolved commit, not just the ref name", so that "a commit
    landing on `main` between run and resume" cannot change "the first step's starting head": a
    sentence that only means anything if `base_sha` *is* that head. With `None`, a crashed *first*
    step's untracked leavings would survive into the retry, which is the exact contamination the
    wipe exists to prevent. And `base_of` already types `head: str`; making it optional now would
    reopen a settled interface to describe a state that does not exist.

    It follows that `base` here is a **resolved commit id and not a ref expression**.
    `WorkspaceProvider.open` accepts either, deliberately, because a child is cut from the run's
    branch by name - but a ref name reaching this constructor would be hashed into every first
    fingerprint in the namespace and handed to `restore`, and `base_sha` is pinned precisely so
    that neither happens. Stage 13.4 resolves it once, from the run's record.

    **The pre-run `restore(last_good)` is unconditional** - not guarded on HEAD, not guarded on
    `last_good`, not guarded on anything. A crashed read-only step leaves untracked files *without
    moving HEAD*, so a `head() != last_good` guard is false at exactly the moment the wipe is
    needed and the leavings survive into the next step. `Workspace` exposes no `is_dirty`, by
    design and by its own docstring, so the guard cannot be widened into a correct one; restoring
    unconditionally is both right and cheaper than asking.

    **The role arrives as its constituents, not as a `Role`.** `sdk/roles.py` does not exist until
    12.2, and a bundle declared here to carry `instructions`, `model`, `restrictions` and `tools`
    would be `Role` under another name, in `_engine/`, where the workflow author cannot see it.
    Stage 12's `Run.step` spreads a `Role`'s fields into these keywords. The parameter list is long
    for that reason and is expected to shorten by one stage.

    **A crashed step leaves no entry, and there is no failure path here.** No `finally`, no wipe on
    the way out of an exception, nothing shielded: §3.6's pseudocode has none of it, and its own
    argument is that the *next* attempt's unconditional pre-run restore is what makes a crash's
    leavings harmless. The commit-or-wipe that runs "on success and on failure alike" is 12.1's,
    and the `asyncio.shield` a cancelling task needs - `await restore(...)` in a `finally` inside
    one re-raises `CancelledError` before it runs - is 12.4's. Both are named in the build order as
    those deliverables' own acceptance criteria, so anticipating them here would be writing the
    half of them that nothing tests.

    Nothing gets a sequence number: replay walks the workflow in order, so the order is the
    program's and not a field (§3.6, "ordering is free").
    """

    def __init__(
        self,
        store: Store,
        scope: RunScope,
        workspace: Workspace,
        clock: Clock,
        fingerprints: Fingerprints,
        base: str,
    ) -> None:
        """The ledger, the address, the checkout, the stamp, the shared counter, and where it
        starts.

        **`fingerprints` is passed in and is deliberately not constructed here.** There is one per
        run, shared by every namespace's `Journal`. Its key already carries the scope, so sharing
        is what makes the count per-(namespace, step name) rather than per-object - and a counter
        built in this constructor would be per-`Journal`, which for a workflow that opens one
        `Journal` per namespace happens to look identical and for one that opens two over a scope
        is rule 1's failure with rule 1's fix removed.

        `base` is the whole of the initial state, for the reasons the class docstring gives.
        """
        self._store = store
        self._scope = scope
        self._workspace = workspace
        self._clock = clock
        self._fingerprints = fingerprints
        if not base:
            # `Entry.__post_init__`'s check, one step earlier, and for its reason: a head is git's
            # to judge but an empty string names nothing anywhere, and an empty `base` would be
            # hashed into every first fingerprint in this namespace before `restore` ever saw it.
            raise InternalError(
                "a journal was opened at an empty base, and a namespace's starting head names the "
                "commit it was opened from - there is no state in which a walk has no head yet"
            )
        # The chain, and the only mutable thing on this object. Written in exactly two places, both
        # in `step`: from `entry.head` on a hit, and from the worktree's head after a write.
        # Deliverable 14.1 adds a third - `integrate()` writing `IntegrationOutcome.head` here -
        # and the module docstring says what it costs to leave it out.
        self._last_good = base

    async def step(
        self,
        name: StepName,
        *,
        instructions: str,
        model: ModelId,
        restrictions: AbstractSet[Restriction],
        tools: Sequence[Tool],
        inputs: Mapping[str, object],
        worker: Callable[[], Awaitable[JsonValue]],
        commit: str | None = None,
    ) -> JsonValue:
        """Replay this step if it is recorded, and otherwise run it and record it.

        `commit` decides which of §3.6's two endings runs, and nothing else does: given, the
        workspace commits whatever is dirty under that message; omitted, it is restored to
        `last_good`, so a read-only role cannot leave a scratch file, a cache directory or a
        partial edit behind. The framework does not inspect what the role declared and does not
        compare HEAD before and after (§3.3) - it does one predictable thing per `commit=`.

        **The message is not in the fingerprint**, which is `base_of`'s doing and is why this
        parameter is absent from the call below. §3.6: a message is cosmetic, and "including it
        would mean editing the wording re-runs the agent, which is the opposite of what
        fingerprinting is for". The trade is that a replayed step keeps the commit it already made,
        message and all.

        The value comes back as `JsonValue`. Turning it into the dataclass a workflow declared is
        the Role's business at stage 12, and a stale entry is discarded rather than failing to
        parse, because changing the declared type changes the tool schema and so the fingerprint.
        """
        base = base_of(
            # `self._last_good`, and never `await self._workspace.head()`. The class docstring and
            # §3.6 both make this the load-bearing line: a head read from the worktree here is how
            # a run whose children have landed re-runs every one of its own steps on every resume,
            # in silence. A `head` parameter on this method would be the same hole with a caller
            # to blame, which is why there is none - the base is computed here or nowhere.
            instructions=instructions,
            model=model,
            restrictions=restrictions,
            tools=tools,
            inputs=inputs,
            head=self._last_good,
        )
        # Taken here, synchronously, before the first `await` in this method - and this is a
        # precondition of `Fingerprints`' own contract rather than a stylistic preference. Rule 1
        # makes the counter deterministic for *siblings*, because siblings occupy different
        # namespaces; it does nothing for two concurrent steps of one name in one scope, which
        # `asyncio.gather(journal.step("review", ...), journal.step("review", ...))` is. Those two
        # share a `(scope, step, base)` key, so a suspension before this line would let the
        # interleaving decide who gets `n = 0` - and the interleaving differs on resume. With no
        # suspension before it, the order is the order the coroutines were created, which is the
        # program's own order and is the same on every run.
        digest = self._fingerprints.next(self._scope, name, base)
        entry = await read_entry(self._store, self._scope, name, digest)
        if entry is not None:
            # A hit advances the chain from what was recorded, not from where the tree happens to
            # be. This is the assignment §3.6's "chained logically" clause is about: on a resume
            # the physical worktree may be far ahead of this namespace's own history.
            self._last_good = entry.head
            return entry.value

        await self._workspace.restore(self._last_good)
        result = await worker()
        if commit is not None:
            await self._workspace.commit_all(commit)
        else:
            await self._workspace.restore(self._last_good)

        # The *ending* head is read from the worktree, and that is not a contradiction of the rule
        # above: §3.6 defines it as "worktree HEAD after this step completed", and the whole reason
        # it is recorded is that only the worktree knows what the worker committed. One read
        # covering both branches, as §3.6 writes it - `commit_all` also answers with the resulting
        # head, but spending its return value would give the effect ending and the read-only ending
        # two different sources for one field, and the field is the chain.
        head = await self._workspace.head()
        await write_entry(
            self._store,
            self._scope,
            name,
            digest,
            # `fingerprint=digest`: the entry is filed under the digest and claims the digest.
            # `write_entry` records what it is handed without comparing (deliberately - see its
            # docstring), so composing an entry that claimed anything else would pass here and miss
            # on every future read, which is this module's failure mode wearing its best disguise.
            Entry(fingerprint=digest, value=result, head=head, at=self._clock.now()),
        )
        self._last_good = head
        return result


def _dumps(value: JsonValue) -> str:
    """Canonical text for an already-canonicalised value - the one place the flags are written.

    `canonical_json`, `base_of` and the `Set` branch's sort key all come through here, so a change
    to a flag changes all three together. That matters most for the case that is easiest to get
    subtly wrong: a set sorted on text produced under different flags would be ordered by something
    no fingerprint ever contains.
    """
    return json.dumps(value, sort_keys=True, separators=_SEPARATORS, ensure_ascii=True)


def _canonical(value: object, where: str) -> JsonValue:
    """`value` rebuilt as a JSON value that hashes the same in every process, or `InputError`.

    The branch order mirrors `ports/run.py::_checked_json`, which refuses the same shapes for the
    same reasons, and adds the two branches this module needs that a stored `run.json` does not: a
    set, which has to be sorted, and a dataclass instance, which has to be unpacked.
    """
    # `None` and `bool | int` together and first, exactly as `run.py` takes them: `bool` is an
    # `int`, so an `int`-only branch that coerced would make `{"x": True}` and `{"x": 1}` one
    # fingerprint, and a workflow passing a flag where it used to pass a count would replay.
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return _checked_text(value, where)
    if isinstance(value, float):
        # JSON has no spelling for either: `json` writes a bare `NaN` or `Infinity` token no reader
        # accepts, and NaN does not even equal itself, so a value carrying one could never match.
        if not isfinite(value):
            raise InputError(
                f"{where} is {value!r}, which JSON has no spelling for: it would be written as a "
                f"bare token no reader accepts, and NaN does not even equal itself - so a step "
                f"fingerprinted with one could never match the entry it wrote"
            )
        return value
    if isinstance(value, Mapping):
        # Rebuilding as a `dict` is what takes `Tool.payload_schema` out of its `MappingProxyType`,
        # and it happens at every depth rather than once at the top, so a nested proxy inside a
        # schema is covered by the same line. Before the `Set` branch because a `Mapping` is not a
        # `Set` and the order between them decides nothing - but a mapping is the more specific
        # thing and reads better named first, and `dict.keys()` is a `Set` that is not a `Mapping`.
        return {
            _checked_key(key, where): _canonical(item, f"{where}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, AbstractSet):
        # Rule 2. Sorted on each element's own canonical text so the order is total without the
        # elements having to be comparable with each other - `frozenset({1, "a"})` has no `<`.
        # An element's path is `{where}[]`: a set has no positions, so the path names the set and
        # not a slot in it. (Accepted, and named rather than hidden: two distinct elements whose
        # canonical text is identical - a `Point(1, 2)` and a `Vector(1, 2)` in one set - tie, and
        # a stable sort leaves ties in iteration order. Breaking the tie would mean putting a type
        # name into the fingerprint, which is a change to a stored format for an exotic case.)
        return sorted((_canonical(item, f"{where}[]") for item in value), key=_dumps)
    if isinstance(value, list | tuple):
        return [_canonical(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # Rule 3's supported case. A dataclass *class* is not an instance and falls through to the
        # refusal below: `asdict` cannot take one, and a workflow passing a class where it meant an
        # instance wants to hear about it rather than to be given a fingerprint over its name.
        # Sets survive `asdict` as sets, which is the whole reason the branch above exists.
        return _canonical(dataclasses.asdict(value), where)
    raise InputError(
        f"{where} is a {type(value).__name__}, which cannot be canonicalised: a step's inputs are "
        f"fingerprinted, and a fingerprint is what a resume compares to decide whether to replay "
        f"this step or pay for it again. Pass a dataclass, a mapping, a sequence, a set, a string, "
        f"a number, a bool or None"
    )


def _wire_text(data: Mapping[str, object], key: str) -> str:
    """One string off an entry. Presence is already settled - `from_json` checked the key set."""
    value = data[key]
    if not isinstance(value, str):
        raise InternalError(
            f"a step entry's {key!r} is a {type(value).__name__}, and an entry's {key} is a string"
        )
    return value


def _normalised(moment: datetime) -> datetime:
    """The same instant as UTC, to the second - the precision an entry can actually hold.

    `ports/run.py::_normalised`'s rule, applied to the other record AGL keeps, and the second copy
    is the one `_WIRE_TIME` argues for: the format and the normalisation are one decision, and half
    of it shared through another module's private name would be worse than neither.

    Naive datetimes are refused rather than converted, and refused *before* `astimezone` is called,
    because `astimezone` on a naive value quietly reads the machine's local timezone - which would
    make what an entry records depend on where the machine thinks it is, in the one field
    `ports/clock.py` hands to an injectable clock precisely so that it depends on nothing. An aware
    value at another offset is converted: every aware spelling denotes one instant.
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise InternalError(
            f"a step entry's 'at' {moment!r} has no timezone, and a wall-clock reading with no "
            f"place is not a moment - an entry carries an instant, written as UTC"
        )
    utc = moment.astimezone(UTC)
    return utc - timedelta(microseconds=utc.microsecond)


def _checked_key(key: object, where: str) -> str:
    """A JSON object's keys are strings. `json` would coerce anything else, and so rename it.

    Held to `_checked_text` as well, for the reason a key is the same boundary as a value: it goes
    into the same text through the same encoder.
    """
    if not isinstance(key, str):
        raise InputError(
            f"{where} is keyed by {key!r}, a {type(key).__name__}, and a JSON object is keyed by "
            f"strings - canonicalising this would silently rename the key, and a renamed key is a "
            f"different fingerprint from the one this step's entry was written under"
        )
    return _checked_text(key, f"the key {key!r} in {where}")


def _checked_text(value: str, where: str) -> str:
    """`value` itself, if it is text this module can hash - which is every `str` but one kind.

    **Why the text is `ensure_ascii=True`.** It exists only to be UTF-8 encoded and hashed: it is
    never stored, never read back and never parsed. So the argument
    `adapters/filesystem/store.py::_encoded` makes against that flag - that escaping hides a value
    nothing can encode, and the value is still unencodable when it is read back - does not reach
    here, because nothing reads this back. Escaping makes the text pure ASCII, so `.encode("utf-8")`
    is total and no `str` Python can hold can make a fingerprint raise instead of returning.

    **What that costs, and why refusing surrogates is the price of it.** `ensure_ascii=True` writes
    an astral character and a `str` holding the unpaired surrogate pair that encodes it as the same
    text: `json.dumps(chr(0x1F600))` and `json.dumps(chr(0xD83D) + chr(0xDE00))` are byte-identical,
    both `"\\ud83d\\ude00"`, though the two strings are not equal and the second has no UTF-8
    encoding at all. So the escaping is not injective over every `str`, and a collision here is a
    false cache **hit** - the expensive direction, a replayed result produced under inputs that were
    not these. Refusing surrogates closes it and leaves one input to one digest. The two halves are
    one decision, which is why they are argued together.

    Surrogates and only surrogates, as in `ports/run.py`: a workflow's inputs are arbitrary text,
    and a newline, a tab and an emoji are all values somebody is entitled to fingerprint. The
    message names the code point rather than the character, because a surrogate has no name to
    print and putting the character into the message hands the unencodable value to whatever writes
    the message out.
    """
    for index, character in enumerate(value):
        if unicodedata.category(character) == _SURROGATE:
            raise InputError(
                f"{where} holds U+{ord(character):04X} at position {index}, which is a surrogate: "
                f"UTF-8 has no encoding for one at all, and the canonical text escapes it to the "
                f"same characters as the astral code point it stands for - so two different inputs "
                f"would share a fingerprint, and one would replay the other's result"
            )
    return value
