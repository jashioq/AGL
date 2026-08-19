"""`RunSpec` - the record `run.json` holds - and why there is no `RunStatus`.

A run is a workflow, a label, a place in git to start from, and the parameters the workflow was
handed. `RunSpec` is that and nothing else, and `run.json` at the top of a run's directory
(`home_layout.run_record`) is where it is kept, so `agl resume auth` can pick one up hours later.

**`base_sha` pins the resolved commit, not just the ref name.** `base_ref` records what the user
said - `main`, `origin/main` - and `base_sha` what that meant when the run started. Without the
second, a commit landing on `main` between run and resume moves the first step's starting head
and invalidates every step already recorded against the old one. Which is also why an
*abbreviated* sha is refused; see `_check_sha`.

**`workflow_version` is stamped, never migrated.** Written once and, on resume, compared -
`spec.workflow_version == <the installed workflow's version>` - where a mismatch refuses the run
and tells the user to start a new one. That comparison belongs to resume; this module's job is to
make it the only comparison available. Hence a `str` and not a parsed version object: `==` is the
whole vocabulary, and parsing implies an ordering, an ordering implies "newer than", and "newer
than" is the first line of a migration nobody is going to write. Runs live hours.

`params` is workflow-defined and so is held opaque. `JsonValue` is what survives being written
down and read back, and it is the whole of what this module knows about a param: not that
`concurrent` is a number, not that `request` is required, not that either key exists.

## There is no `RunStatus`

`ARCHITECTURE.md` §6 gives this module's row as "`RunSpec` and `RunStatus`". `RunStatus` is
deliberately absent, and this is the record of why.

The plan removes stored status twice: from §3.6's list of what `run.json` does *not* carry
("stored status (derived from which entries exist)"), and from §3.11's table of what is not built
at all ("Stored status - derivable from which entries exist. Two sources of truth is what forces
`reconcile_on_resume.py` to exist"). The existence of a step's entries **is** the status, so a
`RunStatus` could only ever be a *computed view* over them - and three facts leave nothing here to
compute it from: the entry type does not exist yet, arriving with the journal many stages from
here (`sdk/_engine/journal.py`) and living in `sdk/`, not `ports/`; this module may not reach the
entries even once it does, contract 2 forbidding a pure type in `agl.ports` from importing
`agl.ports.store`, the port that reads them; and nothing asks, the plan having removed the
`status` command outright.

A `RunStatus` written today would therefore be an enum - `RUNNING`, `COMPLETE`, `FAILED` - with
no honest way to populate it, sitting in the one module that serializes `run.json`, one field
away from being stored there. Not a neutral placeholder: precisely the second source of truth
§3.11 names. And still better absent if the view is later wanted, because a view over entries
belongs where the entries are.

## What lives here

`run.json`'s field names *are* this type's wire format, so the mapping in both directions is
here, on the type, and pure: `to_json` and `from_json` take and return a JSON-shaped `dict`, and
this module does not import `json`, never opens a file, and never learns where `run.json` is -
`home_layout` says where, and `Store` writes it atomically. Side by side is what keeps the two
directions agreeing, and they must: a change to the shape below is a change to a file another
version of AGL may be about to read.

Everything wrong with a record raises `InternalError`, including refusals `ids.py` would have
spoken as `InputError`. Nobody types this file - AGL writes it and AGL reads it - and `errors.py`
says the same fault is an `InputError` when the user named it and an `InternalError` when we are
the ones who created it. A missing field, a wrong type, an unknown key, a timestamp that is not
one: each means either that we wrote it wrong or that something outside AGL changed it, and at
this layer those are indistinguishable. Exit 70 reads as "file a bug", right for the first and
survivable for the second; the message names the field either way.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from types import MappingProxyType
from typing import Final

from agl.ports.errors import InputError, InternalError
from agl.ports.ids import RunLabel

__all__ = ["JsonValue", "RunSpec"]


type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
"""Anything that survives being written as JSON and read back as the same value - exactly what
`json` produces and accepts, which is what makes it the type for a value this module stores
without understanding. `Mapping` is deliberately not in it: one that is not a `dict` is not
something `json` will write, so admitting it would make the alias a promise the wire cannot keep.
"""

# `run.json`'s keys, in the order plan §3.6 writes them - the published shape of the file, which a
# later AGL reading an older record depends on. `to_json` spells them out again rather than looping
# here, so the shape is readable where it is produced; the suite pins that the two agree.
_WIRE_KEYS: Final = (
    "workflow", "workflow_version", "label", "base_ref", "base_sha", "branch", "params",
    "created_at",
)

# `2026-08-18T09:14:02Z` - UTC, whole seconds, the `Z` the plan writes and not `isoformat`'s offset.
_WIRE_TIME: Final = "%Y-%m-%dT%H:%M:%SZ"

# A git object id: sha1 is 40 characters of lowercase hexadecimal, sha256 is 64.
_SHA_CHARACTERS: Final = frozenset("0123456789abcdef")
_SHA_LENGTHS: Final = frozenset({40, 64})


@dataclass(frozen=True, slots=True)
class RunSpec:
    """What a run was asked to do: everything a resume needs, and nothing it does not. Frozen, and
    `params` is copied in and out, so a record never shares mutable state with anything."""

    workflow: str
    """The entry-point name the run was started with - `tickets`, `fix`, `split`. A plain `str`: a
    key in the `agl.workflows` table, not a filename and not a git ref, so `ids.py`'s types neither
    fit nor apply, and a name nothing registers is `config/registry.py`'s `NotFoundError`."""

    workflow_version: str
    """That workflow's version when the run started. Stamped, compared with `==`, never migrated."""

    label: RunLabel
    """The run's name, and the one field with a validated type - because it is the one that becomes
    a path segment and a git ref component. `ids.py` validated it precisely so nothing re-checks."""

    base_ref: str
    """What the user named as the starting point: `main`, `origin/main`, `v1.2`. A ref *expression*,
    so `ids.py` does not fit and is not stretched to fit - `origin/main` has a `/` in it and every
    type there refuses one, being single path segments."""

    base_sha: str
    """The commit `base_ref` resolved to when the run started. The pin - full length, lowercase."""

    branch: str
    """The branch the run's work is on: `agl/<label>`, as `tree_layout.run_branch` composes it.

    Stored although derivable, because the plan specifies `run.json`'s shape and this is in it.
    That is a second source of truth, the plan's own charge against stored status - the difference
    being that this one is only ever read, never recomputed and compared. It buys one thing, that a
    run started under one branch-naming scheme keeps its branch when the scheme changes, which is
    also why it is deliberately not checked against `label`."""

    params: Mapping[str, JsonValue]
    """The workflow's own parameters, opaque - see the module docstring."""

    created_at: datetime
    """When the run started. Aware, normalised to UTC and to whole seconds, because whole seconds
    is what the wire form carries and a field cannot honestly hold more than it stores."""

    def __post_init__(self) -> None:
        # Emptiness is the only thing asserted about the plain strings. Everything else about them
        # is somebody else's judgement - a workflow name the registry's, a ref git's.
        for name, value in (
            ("workflow", self.workflow), ("workflow_version", self.workflow_version),
            ("base_ref", self.base_ref), ("branch", self.branch),
        ):
            if not value:
                raise InternalError(f"a run record's {name!r} is empty, and that names nothing")
        _check_sha(self.base_sha)
        object.__setattr__(self, "params", MappingProxyType(_checked_params(self.params)))
        object.__setattr__(self, "created_at", _normalised(self.created_at))

    def to_json(self) -> dict[str, JsonValue]:
        """This record as the `dict` `run.json` holds. A pure function of `self`; writes nothing.
        The keys are written out rather than read off the field names, so renaming a field here
        cannot silently rename a key in a file another version of AGL is about to read."""
        return {
            "workflow": self.workflow,
            "workflow_version": self.workflow_version,
            "label": str(self.label),
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "branch": self.branch,
            "params": _checked_params(self.params),
            "created_at": format(self.created_at, _WIRE_TIME),
        }

    @classmethod
    def from_json(cls, data: object) -> RunSpec:
        """A record read back from `run.json`. Takes `object`, because a parsed file is anything.
        The field checks are the constructor's, so a record built in memory and one read off disk
        are held to one standard by one piece of code; what is left here is the file's own shape -
        an object, with exactly these keys, whose two parsed values parse."""
        if not isinstance(data, Mapping):
            raise InternalError(f"a run record is a JSON object, not a {type(data).__name__}")
        missing = [key for key in _WIRE_KEYS if key not in data]
        unknown = sorted(repr(key) for key in data if key not in _WIRE_KEYS)
        if missing or unknown:
            raise InternalError(
                f"run.json's keys are not a run record's: missing {missing}, unexpected "
                f"{unknown}. A record carrying keys AGL does not know was written by another "
                f"version of it, and this module refuses records rather than migrating them"
            )
        params = data["params"]
        if not isinstance(params, Mapping):
            raise InternalError(
                f"run.json's 'params' is a {type(params).__name__}, and a workflow's params are a "
                f"JSON object - whatever the workflow chose to put in it"
            )
        try:
            # `ids.py` raises `InputError`, which is right when a user typed the name and wrong
            # here: this label is one AGL wrote from a `RunLabel` that had already passed, so if
            # it no longer passes, the file is corrupt. Chained, so the rule broken stays visible.
            label = RunLabel(_wire_text(data, "label"))
            created_at = datetime.fromisoformat(_wire_text(data, "created_at"))
        except (InputError, ValueError) as error:
            raise InternalError(f"run.json holds a value AGL cannot read back: {error}") from error
        return cls(
            workflow=_wire_text(data, "workflow"),
            workflow_version=_wire_text(data, "workflow_version"),
            label=label,
            base_ref=_wire_text(data, "base_ref"),
            base_sha=_wire_text(data, "base_sha"),
            branch=_wire_text(data, "branch"),
            params=params,
            created_at=created_at,
        )


def _wire_text(data: Mapping[str, object], key: str) -> str:
    """One string off the wire. Presence is already settled - `from_json` checked the key set."""
    value = data[key]
    if not isinstance(value, str):
        raise InternalError(
            f"run.json's {key!r} is a {type(value).__name__}, and a record's {key} is a string"
        )
    return value


def _check_sha(value: str) -> None:
    """A full object id, lowercase - or this is not a pin.

    Plan §3.6's example is twenty hex characters, and that same section elides long digests with `…`
    where they would not fit the page, so it is read as abbreviated for readability and not as a
    length. It has to be: git's abbreviations are unique when printed and stop being unique as a
    repository grows, so a short `base_sha` would come loose exactly when a project got big enough
    for the pin to matter. Forty characters is a sha1 object id and sixty-four a sha256 one, and
    requiring one of the two says "not abbreviated" without knowing which hash the repository uses.
    Lowercase for `home_layout`'s reason: a resume compares strings."""
    if len(value) not in _SHA_LENGTHS or not _SHA_CHARACTERS.issuperset(value):
        raise InternalError(
            f"base_sha {value!r} is not a resolved commit: expected 40 characters of lowercase "
            f"hexadecimal (sha1) or 64 (sha256) - a full object id, because an abbreviated one "
            f"stops being unique as the repository grows and so pins nothing"
        )


def _normalised(moment: datetime) -> datetime:
    """The same instant as UTC, to the second - the precision `run.json` can actually hold.

    Naive datetimes are refused rather than converted, and refused *before* `astimezone` is called,
    because `astimezone` on a naive value quietly reads the machine's local timezone, which is the
    kind of hidden input this module must not have. An aware value at another offset is converted:
    every aware spelling denotes one instant."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise InternalError(
            f"created_at {moment!r} has no timezone, and a wall-clock reading with no place is "
            f"not a moment - a run record carries an instant, written as UTC"
        )
    utc = moment.astimezone(UTC)
    return utc - timedelta(microseconds=utc.microsecond)


def _checked_params(params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """A copy of `params`, checked a level down and then all the way down by `_checked_json`."""
    return {
        _checked_key(key): _checked_json(value, f"params.{key}") for key, value in params.items()
    }


def _checked_key(key: object) -> str:
    """A JSON object's keys are strings. `json` would coerce anything else, and so rename it."""
    if not isinstance(key, str):
        raise InternalError(
            f"the param key {key!r} is a {type(key).__name__}, and a JSON object is keyed by "
            f"strings - writing this record would silently rename it"
        )
    return key


def _checked_json(value: object, where: str) -> JsonValue:
    """A copy of `value`, if it is one this module can write down and read back unchanged.

    Shape only, never meaning: it cannot tell you `concurrent` should be a number, only that
    whatever `concurrent` holds survives the round trip. Two refusals are worth naming, since both
    would otherwise surface at read time rather than write time - a non-finite float, which `json`
    writes as a bare `NaN` or `Infinity` token that is not JSON and comes back unequal to itself,
    and a non-string key, which `json` renames. Containers are rebuilt, which is what makes this a
    copy, and a tuple becomes the list it would be on the way back."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise InternalError(
                f"{where} is {value!r}, which JSON has no spelling for: it would be written as a "
                f"bare token no reader accepts, and NaN does not even equal itself"
            )
        return value
    if isinstance(value, Mapping):
        return {
            _checked_key(key): _checked_json(item, f"{where}.{key}") for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_checked_json(item, f"{where}[{index}]") for index, item in enumerate(value)]
    raise InternalError(
        f"{where} is a {type(value).__name__}, which is not a JSON value: a workflow's params are "
        f"stored exactly as given and read back the same, so they have to be writable"
    )
