"""The addresses and documents the store suite builds for itself, and why it builds them itself.

A contract suite has exactly one knob - the fixture handing over the implementation - and
everything else it needs it makes here, out of the pure types the port already speaks. An
implementer who also had to supply a scope, a step name or a digest would have one more way to
point the suite at the wrong thing, and a suite reading its addresses back out of the
implementation could not tell one that loses a write from one that never took it.

Three things below are less arbitrary than they look.

**The digests are real sha256 hexdigests**, derived from a seed rather than written out by hand.
`Store` hands `digest` on as an opaque `str`, and an implementation that spends it as a name of
its own is entitled to check it first - `home_layout._checked_digest` insists on 64 characters of
lowercase hexadecimal, which is what the journal produces. A suite that addressed an entry as
`"abc"` would be refused by a correct implementation, and the refusal would read like the
implementation's bug.

**The documents are shaped like the two AGL really stores**: §3.6's four entry fields, and
`run.json`'s. Not because this port ever looks inside them - it does not, and no test asserts
that it does - but because a suite is also the documentation somebody writes an adapter from, and
what arrives at `write_entry` in anger should be what arrives at it here.

**`EVERY_JSON_SHAPE` is the whole of what `JsonValue` admits**, in one document, because
"reads back equal" is only a promise about documents an implementation is actually given. Two
absences from it are deliberate and are named where the round-trip test asserts over it: the
non-finite floats, and anything that would need a key which is not a `str`.
"""

import hashlib
from typing import Final

from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue

# One project, two runs in it, and a third run in a second project: enough to ask whether a label
# is scoped to its project, which §3.6 says it is.
_PROJECT: Final = ProjectName("myapp")
RUN: Final = RunScope(_PROJECT, RunLabel("auth"))
SIBLING_RUN: Final = RunScope(_PROJECT, RunLabel("payments"))
FOREIGN_RUN: Final = RunScope(ProjectName("otherapp"), RunLabel("auth"))

# Two children of the run and one child of the first, because `worktrees/` nests arbitrarily and
# a suite that only ever went one level deep would not notice an implementation that flattened.
CHILD: Final = Namespace("T-01")
SIBLING: Final = Namespace("T-02")
GRANDCHILD: Final = Namespace("sub-b")

# Two step names, and `review_quality` deliberately shares no prefix with `implement`.
STEP: Final = StepName("implement")
OTHER_STEP: Final = StepName("review_quality")

# An entry's `at` is never read for control flow (§3.6); one constant is enough for every
# document here, and a document that differs from another differs somewhere that matters.
_AT: Final = "2026-08-18T09:16:41Z"


def digest(seed: str) -> str:
    """A digest the way the journal makes one: sha256, hexdigest, 64 lowercase hex characters.

    Derived from `seed` so that distinct seeds are distinct addresses and the same seed is the
    same address in two tests, with nothing to keep in step by hand.
    """
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def entry(marker: str, *, value: JsonValue = None) -> dict[str, JsonValue]:
    """One step entry, §3.6's four fields, every one of them derived from `marker`.

    `value` defaults to `None` because that is what an effect step records, and because an entry
    whose value is null is the case the "nothing recorded is not a recorded null" clause turns on.
    """
    return {
        "fingerprint": digest(f"fingerprint:{marker}"),
        "value": value,
        "head": digest(f"head:{marker}")[:40],
        "at": _AT,
    }


def record(marker: str) -> dict[str, JsonValue]:
    """One run record, shaped like §3.6's `run.json`, carrying a nested `params`.

    `params` is workflow-defined and so is the field a caller is most likely to reach into after
    reading - which is what makes it the right place to try to edit the store through.
    """
    return {
        "workflow": "tickets",
        "workflow_version": "1.0.0",
        "label": marker,
        "base_ref": "main",
        "base_sha": digest(f"base:{marker}")[:40],
        "branch": f"agl/{marker}",
        "params": {"request": marker, "concurrent": 4, "tickets": ["T-01", "T-02"]},
        "created_at": _AT,
    }


# Every shape `JsonValue` admits, as one document. The unicode string carries a character AGL
# refuses in a *name* (§3.3) on purpose: names are ASCII and values are not, and an
# implementation that confused the two would encode a value the way it encodes an address.
EVERY_JSON_SHAPE: Final[dict[str, JsonValue]] = {
    "null": None,
    "true": True,
    "false": False,
    "zero": 0,
    "negative": -17,
    "wider than a double": 2**53 + 1,
    "float": -2.5,
    "tiny float": 1e-300,
    "empty string": "",
    "unicode": 'caf\u00e9 \u65e5\u672c\u8a9e \U0001f34c \\ " / \t \n',
    "empty object": {},
    "empty array": [],
    "nested": {"rows": [{"id": "T-01", "blocked_by": []}, {"id": "T-02", "blocked_by": ["T-01"]}]},
    "mixed array": [1, "two", None, True, 3.5, {"four": 4}, [5, [6]]],
}
