"""Fingerprints and entries - what decides whether a step replays, and what it replays from.

Two halves of §3.6 that meet at one string. A **fingerprint** is the digest a step's role, inputs
and starting head hash to; an **entry** is the file that digest names, holding what the step
produced. A resume computes the first and looks for the second, and everything else in the design
- `last_good`, the pre-run wipe, a run that survives being killed - is built on those two lines
agreeing about one name.

§3.6 writes the fingerprint in three lines, and the first half of this module is those three lines:

    base   = sha256(canonical_json({role, inputs, head}))
    n      = entries claimed earlier in this namespace, for this step name  (0, 1, 2, ...)
    digest = sha256(base + ":" + str(n))                            <- the entry's filename

`canonical_json` is the text, `base_of` is the hash of it, and `Fingerprints` is `n`. Three names
rather than one call, deliberately: the replay walk needs them at different moments - a base
computed before there is anything to look up, and a counter that answers an address before the
step runs but only advances once an entry exists at it - and a rule that can only be broken all at
once is a rule nobody can show is load-bearing one piece at a time.

**Every rule below fails in silence, and most of them fail in the cheap direction.** Not an
exception, not a damaged file: a digest that differs from the one already on disk, an entry that is
therefore not found, and a step that runs its agent again and writes a second entry beside the
first. The run still finishes and the output is still right. The only symptoms are the bill and the
wait. That is why §3.6 states four of these in the plan itself rather than leaving them to this
stage, and it is why each rule below is written with its failure attached rather than as a
convention.

**Two of them fail in the expensive direction instead, and both are collisions.** Rule 6 below and
the surrogate refusal argued in `_checked_text` are the two places where two different inputs could
reach one canonical text - and a collision here is not a miss, it is a false cache **hit**: an
entry found under a digest that something else computed, and its recorded result handed back for a
step whose inputs were not these. Nothing re-runs, nothing raises, and the answer is wrong. Both
are therefore written with the colliding pair spelled out.

**Rule 1 - the counter is scoped per `(namespace, step directory)`, and never per invocation.** The
key is `(scope, step.collision_key, base)`. Concurrent siblings produce identical bases by
construction: `T-01` and `T-02` both call `step(implementer)` with the same role, no inputs, and the
same parent head, so nothing about the two calls differs except which worktree they are in. A
per-invocation counter lets the interleaving decide which of them gets `n = 0`; the interleaving
differs on resume, so on the second run each child looks in its own scope for a digest that is not
there and both re-run, forever, silently. Scoping to the namespace makes it deterministic under
concurrency, because siblings occupy different namespaces. The step name is in the key for a smaller
reason that is just as sharp: two same-based steps under different names are recorded under
different `steps/<name>/` directories, so their counts are separate ledgers and have to be separate
counts - and two roles differing only in `name` fingerprint identically, `name` being no term of
`base_of`, so nothing but this key keeps their ledgers apart.

**And the name enters that key folded, which is UF1.6 and the third collision in this module.** The
sentence above is exact about *why* the name is there - "recorded under different `steps/<name>/`
directories" - and `steps/Review/` and `steps/review/` are not different directories on a
case-insensitive volume, which is macOS by default. `StepName` compares by its raw `value`, so
keyed on the object they are two counts, both `n = 0`, both `sha256(base + ":0")`; and `base_of`
has no name parameter, so two roles alike in every other term have one `base` to begin with. One
directory, one digest, and the second step reads the first step's entry: a **false cache hit**, the
one failure in AGL that returns a wrong answer rather than re-running. `_counter_key` below folds
it, and argues why the fold belongs there and not on the path.

**Since UF1.1 the step name is `role.name`, which is where the counter stops being a corner
case.** §3.3 took the per-call-site name off `run.step`, so two calls on one role in one namespace
are one address, and what separates them is their `base` when their inputs or their heads differ
and `n` when neither does. `fix` is the first kind - its two `implementer` calls pass different
inputs and start from different heads, so both sit at `n = 0` under two digests - and the second
kind is the plain one a workflow reaches by asking one role the same question twice over an
unchanged tree. Nothing but `n` tells those apart, and the two-method shape below is what keeps it
honest across a resume.

**And it advances when an entry is written, not when a step is called** (§3.6, in those words). A
step that raised is not done - "a step is done when its file is there" - so it consumed no slot,
and a retry inside the same run has to land at the address the crashed attempt would have. Advance
on the call instead and the retry lands at `n = 1`, a later resume walks the same calls, asks for
`n = 0`, finds nothing, and pays an agent for work already on the ledger. A replay hit advances it
for the mirror-image reason: the entry exists, so a second identical call must look one slot
further or it replays the first one's result forever. "Claimed" therefore means *written by this
walk or replayed by this walk*, and never *ran*.

**Rule 2 - sort every set, wherever it appears.** `frozenset[Restriction]` has no stable iteration
order across processes: `Restriction` is a `StrEnum`, `Enum.__hash__` hashes the member name, and
`PYTHONHASHSEED` randomises it. Measured while this was written, seeds 1, 3, 5, 11, 13 and 31337
produce several different iteration orders of `frozenset(Restriction)` on this machine, which is
the whole failure in one line: same role, same inputs, same head, different digest tomorrow. The
port is right to promise no ordering - a set is not a level and has none - so sorting is this
module's obligation and nobody else's. The obligation is not discharged by sorting `restrictions`
on the way past, either: a set reached through `inputs` has the identical defect, including one
held in a frozen dataclass's field, which rule 6's walker hands on as the `frozenset` it is and not
as a list. So the sort lives in the walker, at every depth, keyed on each element's own canonical
text - a total order that does not ask the elements to be comparable with one another.

**Rule 3 - `**inputs` must be JSON-serialisable, and the refusal has to say where.** Dataclasses
are unpacked field by field (rule 6) and everything else is refused. §3.3's own tickets example
passes `findings=highs`, a list of the workflow's own dataclasses, and the one-line shortcut that
would make that work is `repr()` - whose default embeds an object id, so the text differs in the
next process and the fingerprint with it, which is rule 2's failure through a different door.
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

**Rule 6 - a dataclass contributes its qualified type name, at every depth.** §3.6, and the one
rule here whose failure is a false cache hit rather than a re-run: unpacked by field name alone,
`Finding("T-01", 3)` and `Ticket("T-01", 3)` are one canonical text, so changing an input's type
while keeping its shape finds the old type's entry and **replays the wrong result**. Nothing
re-runs and nothing raises. `type(value).__module__` and `__qualname__` are the name, because two
identically-named dataclasses in two modules are two types and a workflow that swapped one for the
other changed its inputs.

*The depth is the whole of the implementation.* `dataclasses.asdict` recurses, turning a nested
dataclass into a plain `dict` before any walker here could see it, so tagging what `asdict` returns
names the outermost type and erases every one below it - `Outer(inner=Inner(1))` and
`Outer(inner=Other(1))` would still be one fingerprint. The fields are therefore walked here
(`dataclasses.fields` plus `getattr`) and handed back to `_canonical`, which puts this branch in
the path of every dataclass however deep, and inside lists, tuples, mappings and sets alike.

*The encoding is a stored format, and it is injective by refusal.* A dataclass canonicalises to its
fields plus one reserved key, `_TYPE_KEY`, holding the qualified name. That is only one-to-one if
nothing else can produce the same object, so `_checked_key` refuses that one key everywhere: in a
`Mapping` a workflow passes, and in a dataclass field name too. Loud where the alternative is
silent, and the cost is one string out of every key there is. What it does **not** close is the
collision JSON's own vocabulary imposes and no type name could: a set, a tuple and a list holding
the same members are one array, because JSON has one bracket for all three. That predates this rule
and is unchanged by it.

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
the starting head; take the counter's address; read; and either hand back what is recorded or
restore, run, commit-or-wipe, and write - claiming the slot on whichever of those two endings it
reached. The two halves above are what it is built out of, and the loop adds exactly one piece of
state - `last_good`, the commit this namespace is known to be at - and one lock, because §3.6
serializes steps within a namespace and the class docstring argues what that lock is holding shut.

**`last_good` is chained logically from recorded entries and is never read from the physical
worktree**, which is the sentence §3.6 calls load-bearing and the reason `step` computes its own
base rather than accepting a head. The failure is silent and total: the root runs `spec` at H0,
children integrate and advance the run's own line to H5, and a resume that asked the worktree where
it was would recompute `spec` against H5, miss, and re-run - every step, every resume, forever,
with the run still finishing and still right. The only symptoms are the bill and the wait, which is
the failure mode every rule in this module shares.

**Where the integration write lands, and what it costs to leave out.** A child landing moves the
parent's physical head, and `integrate()` is not a step, so nothing journals it - the parent's
`last_good` still names a commit from before the landing. §3.6: "`IntegrationOutcome.head` carries
the value; the engine must write it into the parent's chain", and this is "one of the three paths in
the design that destroy work rather than costing a re-run". The write lands on `Journal._last_good`
and `advance` below is the door it comes through. 14.0 opened it ahead of its caller and 14.1 is
that caller: `sdk/_engine/integration.py` makes the call after the landing has been checked for
containing the child's work and before the target's lease goes back. Forgetting it does not cost a
re-run - the parent's next fingerprint miss restores to a commit before every landed child and
deletes all of it.

**`exclude_steps` is the second door that same caller comes through**, added at 14.1 and used
nowhere else. A landing writes the target namespace's whole checkout, moves its branch and reads its
head - every one of the things the lock below exists to keep two steps from doing at once - so an
integration into this namespace has to shut this namespace's own step walk, by the same mechanism
and for §3.6's reason. The plan says that nowhere: §3.6 is about steps, §3.4 is about integrations,
and neither is about both. The alternative was for the engine to reach through this class's
underscore at `_running`, which would turn an invariant this module keeps into one everybody keeps.

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

import asyncio
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

# Rule 6's tag: the key a dataclass writes its qualified type name under, and the one key no
# `Mapping` and no dataclass field reaching `_canonical` may be spelled with. This is a **stored
# format** in the same sense `base_of`'s object is - every digest ever written over a dataclass was
# computed with this string in it - so respelling it re-runs every step recorded under the old one.
# Chosen to be a string nobody types by accident and one that reads as not-yours where it turns up
# in `_checked_key`'s refusal, which names AGL rather than leaving the reader to guess whose key it
# is. Note it is a perfectly legal dataclass field name - two trailing underscores mean no name
# mangling - which is why `_checked_key` is spent on field names too and not only on a `Mapping`'s.
_TYPE_KEY: Final = "__agl_type__"

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
    exists to be hashed and is never stored, never read back and never parsed. Nothing in this
    module calls it - `base_of` reaches `_canonical` and `_dumps` directly, because it hashes a
    structure it assembled rather than one it was handed. Its callers are `sdk/_engine/steps.py`,
    which appends the canonical form of a step's inputs to the prompt under `## Inputs`, and the
    suite.
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

    The role arrives as its constituents rather than as a `Role`, because `sdk/roles.py` was empty
    when this was written; those are exactly the fields it holds now, and `Run.step` passes them in.
    `Journal.step` carries the argument for why the signature stayed that way.

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


def _counter_key(scope: RunScope, step: StepName, base: str) -> tuple[RunScope, str, str]:
    """What two invocations are one ledger by: the namespace, the step's *directory*, and the base.

    The name enters folded, by `StepName.collision_key` - "what two names are compared by when the
    question is 'would these collide on disk?'" - and the question here is exactly that one. Rule 1
    puts the name in this key because two names are two `steps/<name>/` directories and so two
    ledgers; `steps/Review/` and `steps/review/` are **one** directory on a case-insensitive volume,
    which is macOS by default, so they are one ledger and have to be one count. Keyed on the
    `StepName` itself they are two, because `StepName` compares by its raw `value` - and `Role`
    names are `[A-Za-z0-9._-]` (§3.3), so `Role(name="Review")` is a legal declaration and nothing
    anywhere makes a corpus lowercase.

    **What the fold buys is the collision, and both digests are wrong without it.** Two roles alike
    in every term `base_of` takes have one `base`, because `base_of` has no name parameter - it is
    the *directory* that was keeping them apart, and on this volume it is not. So both sit at
    `n = 0`, both hash to `sha256(base + ":0")`, and the second step reads the first step's file,
    matches the fingerprint recorded in it, and hands back a value no agent produced for it. That is
    a **false cache hit**, and §3.6 names it as the failure class this module's collisions belong
    to: nothing re-runs, nothing raises, and the answer is wrong.

    **The fold is here and never on the path.** `home_layout.step_dir` composes `steps/<step>/` from
    `str(step)` and must go on doing so: the author's spelling is the directory they are entitled
    to, and folding the segment would have AGL write a directory nobody named and report a path that
    is not the one on a case-sensitive volume. Folding the *count* instead is correct on both kinds
    of volume - on a case-sensitive one the entries really are two files in two directories, and the
    counter is then the only thing that made them two digests at all. `sdk/_engine/worktrees.py`
    made the same trade one field over, keying its run-wide namespace table by `collision_key` while
    leaving `worktree("T-01")` its own checkout directory.

    **This moves no digest that any ledger holds.** `n` is never persisted (§3.6) and a digest is a
    function of `n`'s value rather than of the key it was counted under, so the only way a folded
    key could move one is by changing some name's count - and `collision_key` of an all-lowercase
    name is that name. Any corpus that uses one spelling per name therefore counts identically
    before and after, which is every run ever recorded: every shipped role name is lowercase. This
    is not a stored-format change, and `tests/sdk/test_journal.py` pins the number rather than
    taking that on trust.

    **The scope is not folded, and does not need to be.** A `RunScope`'s namespaces compare by
    their raw value, so `worktrees/T-01/` and `worktrees/t-01/` would be two keys here too - but
    they cannot both occur, because `sdk/_engine/worktrees.py` refuses the second spelling run-wide
    at the moment `worktree()` is called, by this same `collision_key`. The project and the label
    are constant for the life of one `Fingerprints`, there being one per run. So the scope half is
    defended by construction and the name half was defended by nothing, which is the whole of why
    this function exists and why it folds one of its three terms.

    The NFC half of the fold is unreachable, exactly as it is in `worktrees.py` and for the same
    reason: §3.3's ASCII allowlist admits no character with two spellings, so no two accepted names
    differ by normalisation alone. It stays because a name having one spelling is a property of the
    character set and not of this comparison - widen the set and the fold is already correct.
    """
    return (scope, step.collision_key, base)


class Fingerprints:
    """The counter `n`, scoped per `(namespace, step directory)`. One instance per run.

    The step name is the role's (§3.3: the call carries none), so "two calls on one role in one
    namespace, with the same inputs and the same head" is one key three times over and `n` is the
    only thing between them. Rule 1 in the module docstring is where that is argued; it is repeated
    here because this class is where somebody reading the mechanism arrives.

    **"Step directory" and not "step name", which is UF1.6.** The key folds the name's case, by
    `StepName.collision_key`, because what rule 1 needs one count per is one `steps/<name>/`
    directory - and two spellings of one name are one directory on a case-insensitive volume.
    Keyed on the raw name they are two counts at `n = 0`, one digest, and a step replaying an entry
    another step wrote. `_counter_key` above is that fold and the whole of the argument for it.

    **Two methods and not one, which is rule 1's second half.** `digest` answers "what address is
    this invocation's", and `claimed` says "an entry now exists at it". §3.6: "the counter advances
    when an entry is written, not when a step is called". A single read-modify-write cannot say
    that - it advances on every invocation, a step whose worker raised included, and the crash is
    not journalled. So the retry that follows it inside the same run lands at `n = 1`, and a later
    resume walking the same calls asks for `n = 0`, finds nothing there, and pays an agent for work
    that is already on the ledger.

    **A replay hit claims a slot too**, and that half matters just as much in the other direction:
    the entry exists, so a second identical call has to look one slot further or it hands back the
    first one's result forever. "Claimed" is *written by this walk or replayed by this walk*, and
    never *ran* - which is the whole mechanism behind §3.6's "`n` is never persisted; replay walks
    the same calls in the same order and reproduces the same values".

    A plain class and not a dataclass, and deliberately mutable: it is the one piece of state the
    journal keeps, it exists to be advanced, and a frozen thing returning a new copy would leave
    every caller responsible for threading it - which is the per-invocation counter rule 1 refuses,
    wearing a different hat.
    """

    def __init__(self) -> None:
        # No lock, and the reason is no longer "one call, no `await` inside it". The pair below is
        # a read and a later write with the whole of a step between them, so it is not atomic and
        # this object does not pretend otherwise. What makes it safe is where the pair is spent:
        # the scope is in the key, so the only key two coroutines can contend for is one they both
        # reach through the same namespace - and `Journal.step` holds that namespace's lock across
        # both calls. The counter is deterministic under concurrency because of rule 1 and that
        # lock together; neither is sufficient alone.
        #
        # The key is `_counter_key`'s and never a tuple written out here, so that the two methods
        # below cannot disagree about what one ledger is - which they would do silently, `digest`
        # reading a count `claimed` never advanced.
        self._counts: dict[tuple[RunScope, str, str], int] = {}

    def digest(self, scope: RunScope, step: StepName, base: str) -> str:
        """The address for `(scope, step, base)` at its present count: `sha256(base + ":" + n)`.

        A pure query, and that is what lets `Journal.step` take it once - before the walk can
        suspend - and spend the one string on both the read and the write. Asking twice with
        nothing claimed in between gives the same answer twice, deliberately: an address is a
        question about the ledger, and asking it is not an event.

        The `step` is folded into the key and not into the answer: what comes back is a digest, and
        `home_layout.step_entry` joins it under the spelling the author wrote.
        """
        count = self._counts.get(_counter_key(scope, step, base), 0)
        return sha256(f"{base}:{count}".encode()).hexdigest()

    def claimed(self, scope: RunScope, step: StepName, base: str) -> None:
        """Record that an entry now exists at the digest this key last answered with.

        The three arguments are the caller's and nothing here checks that they are the ones the
        digest was taken with - the same stance `write_entry` takes about its address, and for the
        same reason: AGL's own composition puts one triple in both places. Claiming under a
        different key would advance a ledger nothing wrote to *and* leave this one a slot short,
        which is this module's failure mode in both of its directions at once. That is why the two
        calls live inside one method, `Journal.step`, rather than being an interface anything else
        is invited to pair up for itself.
        """
        key = _counter_key(scope, step, base)
        self._counts[key] = self._counts.get(key, 0) + 1


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
        if entry: claim(); last_good = entry.head; return entry.value
        restore(last_good)                       # unconditional - see below
        try:    result = run_worker()
        finally: commit_all(commit) if commit is not None else restore(last_good)
        write(path, {fingerprint, value: result, head: head(), at: now()})
        claim(); last_good = head()
        return result

    **Steps in one namespace are serialized, and the lock is held across the whole of `step`.**
    §3.6: "a namespace's workspace is single-threaded". Rule 1's counter buys determinism at the
    *address* level and no further; the `Workspace` is one checkout, and §3.3's own example gathers
    two reviewers over it. Overlapped, A's pre-run restore wipes the files B's worker has just
    written, B's `commit_all` records A's changes under B's message, and A's `head()` after its own
    commit reads B's - a wrong answer, a mislabelled commit and a corrupted chain, none of which is
    a re-run and none of which raises. So a `gather` over same-namespace steps is legal and simply
    does not overlap. It costs latency and nothing else, and an author who wants real concurrency
    opens a `worktree()`, which is what the trees root is flat for.

    The lock is on this object because the `Workspace` is: one namespace, one checkout, one chain,
    one lock. It is also what makes `Fingerprints`' two calls a pair - `digest` and `claimed` are
    separated by the whole of a step, and the only counter key two coroutines can contend for is
    one they both reach through this `Journal`.

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

    **The role arrives as its constituents, not as a `Role`.** `sdk/roles.py` did not exist when
    this signature was settled, and a bundle declared here to carry `instructions`, `model`,
    `restrictions` and `tools` would have been `Role` under another name, in `_engine/`, where the
    workflow author cannot see it. `Role` exists now and `Run.step` spreads its fields into these
    keywords, which is the arrangement the argument asked for. **The prediction that went with it
    did not come true and is corrected rather than deleted**: this paragraph used to say the
    parameter list was "expected to shorten by one stage", and eight stages later it has not. It
    would shorten only by taking the parameter the paragraph above refuses, so the length is the
    price of the decision rather than a debt against it.

    **A crashed step leaves no entry, and the commit-or-wipe runs anyway.** §3.3: "the wipe runs
    whether the step succeeded or raised", which is one `finally` around the worker and nothing
    else. The two halves are deliberately not symmetrical, and the asymmetry is the design: the
    *ending* runs on both paths, because otherwise a failed reviewer's scratch files sit in the
    checkout the retry is about to work in and the next agent reviews them; the *entry* is written
    only on the way out through the bottom, because "a step is done when its file is there" and a
    step that raised is not done. That is what makes the next attempt re-run it, and it is why the
    write, the claim and the `_last_good` assignment are all below the `try` rather than inside it.

    An exception from the ending itself replaces the worker's, with the worker's kept as its
    `__context__` - ordinary `finally` semantics, and the right ones here: a `commit_all` or a
    `restore` that would not go is a fact about the checkout the next step is about to be handed,
    and is more urgent than the reason this step stopped.

    **And the ending runs to completion even when the task around it is being cancelled**, which
    is `_ended` below and is the one place in this walk where ordinary `await` is not enough.
    Written plainly, `await self._workspace.restore(...)` inside a `finally` is aborted at its own
    first suspension the moment another cancellation arrives - and another one arrives whenever a
    supervisor cancels until the task dies or a person presses Ctrl-C twice - which leaves a wipe
    that got as far as `reset --hard` and no further, and so leaves every untracked file the
    cancelled step created sitting in the checkout the next step is handed. That is §3.3's
    contamination arriving through the one door nothing was watching. `_ended` says what it costs
    to close it, and why `asyncio.shield` on its own is not the closing.

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
        is rule 1's failure with rule 1's fix removed. The serialization lock below is the same
        composition read the other way round: two `Journal`s over one scope would be two locks over
        one namespace, which is not a lock at all.

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
        # The chain, and the only mutable thing on this object. Written in exactly three places:
        # twice inside `step` - from `entry.head` on a hit, and from the worktree's head after a
        # write - and once in `advance`, which is `integrate()` putting `IntegrationOutcome.head`
        # here. The module docstring says what leaving that third write out costs.
        self._last_good = base
        # §3.6's "a namespace's workspace is single-threaded", and this is where it is spent.
        # Constructed here rather than lazily inside `step`: a lock built on first use would be
        # built twice by two coroutines that arrived together, which is two locks and no exclusion,
        # in the exact case the lock exists for. `asyncio.Lock()` has needed no running loop since
        # 3.10, so a `Journal` is still constructible from synchronous code.
        self._running = asyncio.Lock()

    @property
    def last_good(self) -> str:
        """The commit this namespace is known to be at - `base` until an entry, `entry.head` after.

        Read-only, and the read is the whole of what is exposed: `_last_good` is written twice
        inside `step` and once in `advance`, and those three are all of them. A setter here would
        be a fourth writer with nothing of its own to say - `advance` is the seam `integrate()`
        needs, and its docstring argues why a named mutator carrying the occasion beats an
        assignment anything holding a `Journal` may make.

        **Synchronous, and that is what `Run.worktree` needs of it.** A child's base is its parent's
        logical head (§3.6: "the starting head is chained logically, not read from disk"), and
        `worktree()` is a plain call, so the value has to be readable without awaiting. That is not
        a constraint this property strains against: `Workspace.head()` is async precisely because it
        goes and looks, and looking is the thing forbidden here. On a resume a persisted namespace's
        physical head is wherever its last step left it and the run's own is wherever integrations
        advanced it, and neither is where this chain is.
        """
        return self._last_good

    def advance(self, head: str) -> None:
        """Move this namespace's chain to a commit no step of its own produced - `integrate()`'s
        write, and the third writer of `_last_good`.

        §3.6, in those words: "**`integrate()` advances the parent's `last_good`**.
        `IntegrationOutcome.head` carries the value; the engine must write it into the parent's
        chain." `sdk/_engine/integration.py` is the caller and the only one there is.

        **What leaving it out costs is the whole reason it exists.** A child landing moves the
        parent's *physical* head, but this chain is built from step entries and `integrate()` is not
        a step, so nothing journals it: the parent goes on believing it is at the commit its last
        step ended at, which is a commit from before every landing. The next step in the parent to
        miss its fingerprint then restores to that commit - `reset --hard` *and* `clean -fd` - and
        every child that has landed since is gone. **This, a mispaired `commit=` and §3.4's red gate
        reverting a hand-resolved conflict are the three paths in AGL that destroy work rather than
        costing a re-run.** Every other rule this module spends a paragraph on fails by re-running a
        step and paying an agent twice; these three fail by deleting what was already paid for, and
        none of them raises on the way.

        **Synchronous, because it assigns and nothing goes and looks.** The value is the outcome's,
        produced by the integrator that has already landed the work, and `last_good` is chained
        logically rather than read from the worktree (§3.6) - so there is no `head()` behind this
        and nothing for a caller to await. `Run.worktree` needs the same of `last_good` for the same
        reason, one field over.

        **Not a setter on the property, deliberately.** A setter would be a fourth writer of one
        field, reachable from anything holding a `Journal`, saying nothing about when writing it is
        legitimate - which is exactly once per landing, from the one caller with an
        `IntegrationOutcome` in its hand. A named mutator is that same assignment with the occasion
        attached, and it keeps the field's writers countable: three, and all three nameable in one
        sentence.

        **And it writes no entry, which is the design rather than an omission here.** Nothing
        journals an integration: no fingerprint over a landing, no file under `steps/` for one, and
        so nothing on disk a resume could read to learn that a child went in. That is why §3.4's
        "a resumed run must be able to find a hold it did not take" is a problem at all. This write
        lives exactly as long as the process; a resume rebuilds the chain by walking the entries
        again, from the base the namespace was opened at.

        **It takes no lock, and could not - and 14.1 is what makes that safe rather than stated.**
        `_running` is an `asyncio.Lock` and this is a plain call, so an advance arriving while a
        step in this namespace is mid-walk would land between that walk's suspensions, and the
        step, having taken its base before its first one, would record an entry chaining from a
        head this call has already moved past. What keeps the two apart is `exclude_steps` below:
        the caller - `sdk/_engine/integration.py`, the only one there is - holds this namespace's
        step lock from before the landing until after this line, so no step in this namespace can
        be mid-walk when this runs. Acquiring `_running` here would not be a second safety net but
        a deadlock against that same caller, an `asyncio.Lock` being neither reentrant nor
        acquirable from synchronous code. The exclusion belongs one layer up because landing into a
        namespace whose own step is running is two writers of one checkout long before it is
        anything to do with this field.

        An empty `head` is refused for the constructor's reason and in its register: an empty string
        names nothing, and it would be handed to `restore` and hashed into every fingerprint after
        it. `IntegrationOutcome` spells "it did not land" as a conflict and never as an empty head,
        so nothing that got this far honestly has one.
        """
        if not head:
            raise InternalError(
                "an integration tried to advance a namespace's chain to an empty head, and an "
                "empty string names no commit - a landing that went in reports where the target is "
                "now, and one that did not carries a conflict instead of a head"
            )
        self._last_good = head

    async def exclude_steps(self) -> Callable[[], None]:
        """Shut this namespace's step walk, and hand back the one thing that opens it again.

        **Deliverable 14.1's seam, and its caller is `sdk/_engine/integration.py` - `Leases.claim`,
        and nothing else.** §3.6 makes a namespace's workspace single-threaded and the lock below
        is that rule; a landing into this namespace is a *second writer of the same checkout*,
        which the plan never says because §3.6 is about steps and §3.4 is about integrations. So an
        integration holds this shut for as long as it holds §3.4's per-target lease - across a
        conflict included, because a target mid-landing is a tree no step may run in.

        **One call rather than a pair, and the release is the return value.** An acquire and a
        release as two named members would be two things a caller has to keep in step across a
        `return` - and this one is held across one, since a conflicted outcome goes back to the
        workflow with the lock still taken, so `async with` is not available to keep them together.
        Handing back the release makes the pair one expression at the call site and leaves the lock
        itself unreachable: nothing outside this class can wait on it, ask it anything, or acquire
        it a second time.

        Named for what it does to *steps* rather than for the lock it takes, for `Steps.landing`'s
        reason: `_running`'s invariants are this module's to keep, and a member that handed out the
        object would make them everybody's.
        """
        await self._running.acquire()
        return self._running.release

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
        compare HEAD before and after (§3.3) - it does one predictable thing per `commit=`, **on
        success and on failure alike**, and only the entry is conditional on there having been no
        failure. The class docstring argues that asymmetry.

        **The message is not in the fingerprint**, which is `base_of`'s doing and is why this
        parameter is absent from the call below. §3.6: a message is cosmetic, and "including it
        would mean editing the wording re-runs the agent, which is the opposite of what
        fingerprinting is for". The trade is that a replayed step keeps the commit it already made,
        message and all.

        The value comes back as `JsonValue`. Turning it into the dataclass a workflow declared is
        the Role's business at stage 12, and a stale entry is discarded rather than failing to
        parse, because changing the declared type changes the tool schema and so the fingerprint.

        **The lock spans the whole method, and the whole is what §3.6 asks for.** Two steps in one
        namespace share one `Workspace`, and every moment of the walk touches it: the pre-run
        restore, the worker, the commit-or-wipe, the `head()` the entry records. A lock around any
        part of that would leave the rest overlapping, which is the same defect with a smaller
        window. It also covers `_last_good` and the counter's two calls, which is why there is one
        lock here and no second one anywhere.
        """
        async with self._running:
            base = base_of(
                # `self._last_good`, and never `await self._workspace.head()`. The class docstring
                # and §3.6 both make this the load-bearing line: a head read from the worktree here
                # is how a run whose children have landed re-runs every one of its own steps on
                # every resume, in silence. A `head` parameter on this method would be the same
                # hole with a caller to blame, which is why there is none - the base is computed
                # here or nowhere.
                instructions=instructions,
                model=model,
                restrictions=restrictions,
                tools=tools,
                inputs=inputs,
                head=self._last_good,
            )
            # Taken here, synchronously, before this method's first suspension - a precondition of
            # `Fingerprints`' own contract rather than a stylistic preference, and one the lock
            # above does not make redundant. The lock already keeps two same-name steps in this
            # namespace from interleaving at all, so the *order* they take their addresses in is
            # the order they acquired: FIFO, which is creation order, which is the program's own.
            # But that leans on asyncio's wake order, an implementation property of the runtime.
            # Taking the address before anything can suspend makes the counter's order the order
            # the coroutines were created in without asking the runtime for anything - which is
            # what has to be true on the resume too, since the resume differs precisely in timing.
            digest = self._fingerprints.digest(self._scope, name, base)
            entry = await read_entry(self._store, self._scope, name, digest)
            if entry is not None:
                # A hit claims the slot: the entry exists, so the next identical call in this
                # namespace has to look one further or it replays this same result forever.
                self._fingerprints.claimed(self._scope, name, base)
                # And it advances the chain from what was recorded, not from where the tree happens
                # to be. This is the assignment §3.6's "chained logically" clause is about: on a
                # resume the physical worktree may be far ahead of this namespace's own history.
                self._last_good = entry.head
                return entry.value

            await self._workspace.restore(self._last_good)
            try:
                result = await worker()
            finally:
                # §3.3: "the wipe runs whether the step succeeded or raised". A `finally` and not a
                # pair of paths, because the two endings are the same two endings either way - and
                # because the failure this covers is not the crash, it is the *next* step: whatever
                # a step that raised left in the checkout is what the retry's agent would otherwise
                # be looking at. The entry is not written here, and that asymmetry is the class
                # docstring's: the ending runs on both paths and the record only on one. "Both
                # paths" includes the third one a `finally` is not enough for on its own - see
                # `_ended`, which is why this line is a call and not the two it makes.
                await self._ended(commit)

            # The *ending* head is read from the worktree, and that is not a contradiction of the
            # rule above: §3.6 defines it as "worktree HEAD after this step completed", and the
            # whole reason it is recorded is that only the worktree knows what the worker
            # committed. One read covering both branches, as §3.6 writes it - `commit_all` also
            # answers with the resulting head, but spending its return value would give the effect
            # ending and the read-only ending two different sources for one field, and the field is
            # the chain.
            head = await self._workspace.head()
            await write_entry(
                self._store,
                self._scope,
                name,
                digest,
                # `fingerprint=digest`: the entry is filed under the digest and claims the digest.
                # `write_entry` records what it is handed without comparing (deliberately - see its
                # docstring), so composing an entry that claimed anything else would pass here and
                # miss on every future read, which is this module's failure mode in its best
                # disguise.
                Entry(fingerprint=digest, value=result, head=head, at=self._clock.now()),
            )
            # Claimed **after** the write and not before it, which is §3.6's "the counter advances
            # when an entry is written, not when a step is called" at the one line where the two
            # readings differ. Everything above this can raise - the worker most of all - and a
            # step that raised wrote no entry, so it consumed no slot and its retry inside this
            # same run belongs at the address it would have used. Claiming earlier puts the retry
            # at `n = 1`, where a later resume asking for `n = 0` finds nothing and pays again.
            self._fingerprints.claimed(self._scope, name, base)
            self._last_good = head
            return result

    async def _ended(self, commit: str | None) -> None:
        """Run this step's ending, and do not come back until it has actually happened.

        `_ending` below is the whole of what §3.3 asks for and is two lines long. This method is
        the reason it is reached through anything at all, and what it exists for is the third way
        out of a step - not returning and not raising, but being cancelled.

        **A plain `await` in a `finally` is not run to the end inside a task that is being
        cancelled hard.** The first cancellation is what *starts* the ending: it is delivered at
        the worker's own suspension, and the `finally` then begins. A second one - a supervisor
        cancelling until the task dies, a person pressing Ctrl-C again, a scope aborting twice -
        lands on whatever the ending is suspended on and aborts it where it stands. §3.3's wipe is
        `reset --hard` *and* `clean -fd`, so "where it stands" is very often between the two, and
        what survives is exactly the untracked scratch file the wipe exists to remove, in the
        checkout the next step is about to be handed. The step is over either way; the
        contamination is the next step's problem, and it is silent.

        **`asyncio.shield` alone is not the fix, and it fails in the shape that looks like one.**
        `await asyncio.shield(ending)` re-raises `CancelledError` in *this* task the moment this
        task is cancelled, and leaves `ending` running, detached. The `finally` then returns with
        the wipe not done but merely *in progress*, so whether the checkout is clean when anything
        next looks at it is a question about scheduling. A test written against that passes and
        fails by turns and proves nothing either way.

        So the shield is wrapped in a loop over `ending.done()`, and the loop is the half that
        makes this a wait rather than a wrapper: the shield keeps `ending` alive through a
        cancellation, and the loop takes the shield again afterwards, absorbing one cancellation
        per turn, until the ending is genuinely finished. Nothing here can outlast the ending, and
        nothing here cancels it.

        **The cancellation is re-raised, and that is the point rather than a leftover.** A step
        that swallowed one would return normally into a workflow that carried on to the next step,
        which is a run that was told to stop and did not - the worst of the outcomes available, and
        worse than the leavings this method is here to sweep up. What a cancelled step gets from
        this is the promise that its ending happened before it died, and nothing else.

        **Nothing here calls `Task.uncancel()`**, which is worth stating rather than leaving to be
        found. Absorbing a cancellation without uncancelling it leaves `Task.cancelling()` counting
        requests that were swallowed, and `asyncio.timeout` and `TaskGroup` compare exactly that
        count against their own to decide whether a `CancelledError` was theirs - so a step that
        absorbed *extra* cancellations inside one of those scopes hands back a `CancelledError` the
        scope no longer recognises, which is a timeout arriving under the wrong name. It is left
        alone because no such scope exists: nothing in AGL opens a `TaskGroup` or a deadline around
        a step, §3.7 has no timeouts anywhere by design, and matching the bookkeeping of a caller
        nobody has written yet is guessing at it.
        """
        ending = asyncio.create_task(self._ending(commit))
        cancellation: asyncio.CancelledError | None = None
        while not ending.done():
            try:
                await asyncio.shield(ending)
            except asyncio.CancelledError as raised:
                # This task's cancellation and never the ending's: nothing cancels that one, which
                # is the whole of what the shield buys. Kept rather than re-raised here, because
                # re-raising here is precisely the bug - the ending is still running.
                cancellation = raised
            except Exception:
                # The ending itself failed, so `ending` is done and this loop is over. Broken out
                # of rather than propagated from here, so that the failure and any cancellation
                # that arrived alongside it are weighed in one place, below.
                break
        failed = ending.exception()
        if cancellation is not None:
            if failed is not None:
                # Both happened. The cancellation still wins, for the reason above - and the
                # failure is chained rather than dropped, which is also what keeps it from being
                # an exception asyncio logs at collection time as one nobody ever retrieved.
                raise cancellation from failed
            raise cancellation
        if failed is not None:
            raise failed

    async def _ending(self, commit: str | None) -> None:
        """One of §3.3's two endings, chosen by `commit=` and by nothing else.

        A coroutine of its own only because `_ended` runs it as a task; the framework does not
        inspect what the role declared and does not compare HEAD before and after, so this is the
        whole of the decision and there is no third branch to add to it.
        """
        if commit is not None:
            await self._workspace.commit_all(commit)
        else:
            await self._workspace.restore(self._last_good)


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
        # not a slot in it. (A tie - two elements whose canonical text is identical - costs nothing
        # in the array they are sorted into, since equal keys mean equal text and the order between
        # them cannot change the result. What a tie used to cost was a collision between two
        # *different* sets: `{Point(1, 2)}` and `{Vector(1, 2)}` were one fingerprint. Rule 6 closes
        # that one, because each element now carries its own qualified type name. What is left is
        # the collision JSON's vocabulary imposes and no type name can close - a set, a tuple and a
        # list holding the same members are one array, because JSON has one bracket for all three.)
        return sorted((_canonical(item, f"{where}[]") for item in value), key=_dumps)
    if isinstance(value, list | tuple):
        return [_canonical(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # Rule 3's supported case, and rule 6. A dataclass *class* is not an instance and falls
        # through to the refusal below: a workflow passing a class where it meant an instance wants
        # to hear about it rather than to be given a fingerprint over its name.
        #
        # **The fields are walked here rather than through `dataclasses.asdict`, and that is rule
        # 6's whole implementation.** `asdict` recurses, so a nested dataclass arrives as a plain
        # `dict` and a tag applied to what it returned would name the outer type and erase every
        # one below it - `Outer(inner=Inner(1))` and `Outer(inner=Other(1))` would stay one
        # fingerprint. Handing each field back to `_canonical` instead puts this branch in the path
        # of every dataclass at every depth, and inside a list, a tuple, a mapping or a set alike.
        # Nothing is lost by dropping `asdict`: it deep-copies, and this rebuilds. What it does not
        # do is recurse into sets, which is why the branch above already had to exist.
        #
        # The field names go through `_checked_key` for one reason: it refuses `_TYPE_KEY`, and a
        # field spelled that - legal Python, no mangling with two trailing underscores - would
        # otherwise overwrite the tag and hand this dataclass another type's fingerprint.
        kind = type(value)
        tagged: dict[str, JsonValue] = {
            _TYPE_KEY: _checked_text(f"{kind.__module__}.{kind.__qualname__}", f"{where}'s type")
        }
        for field in dataclasses.fields(value):
            tagged[_checked_key(field.name, where)] = _canonical(
                getattr(value, field.name), f"{where}.{field.name}"
            )
        return tagged
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
    """A JSON object's keys are strings, and one string is this module's rather than the caller's.

    Held to `_checked_text` as well, for the reason a key is the same boundary as a value: it goes
    into the same text through the same encoder.

    **`_TYPE_KEY` is refused, and that refusal is the whole of what makes rule 6 injective.** A
    dataclass canonicalises to its fields plus that one key holding its qualified type name, so a
    `Mapping` free to spell the same key could render byte-for-byte as a dataclass and share its
    fingerprint - a false cache **hit**, one input handed back another's recorded result, which is
    the expensive direction and the one this module spends refusals on. Every dataclass field name
    comes through here for the same reason, since `__agl_type__` is a legal one.

    Refusing rather than escaping is the trade this module makes elsewhere: it costs exactly one
    string out of every key there is, it fails loudly at the moment the value is passed, and the
    alternative - reserving nothing and hoping - fails silently a run later and cannot be noticed.
    """
    if not isinstance(key, str):
        raise InputError(
            f"{where} is keyed by {key!r}, a {type(key).__name__}, and a JSON object is keyed by "
            f"strings - canonicalising this would silently rename the key, and a renamed key is a "
            f"different fingerprint from the one this step's entry was written under"
        )
    if key == _TYPE_KEY:
        raise InputError(
            f"{where} is keyed by {_TYPE_KEY!r}, which AGL reserves: it is the key a dataclass "
            f"writes its qualified type name under, so a mapping carrying it would canonicalise to "
            f"the same text as some dataclass and one of the two would replay the other's recorded "
            f"result. Spell the key some other way"
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
