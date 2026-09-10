import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from types import MappingProxyType
from typing import Final
from agl.ports.errors import InputError, InternalError
from agl.ports.ids import RunLabel

__all__ = ["JsonValue", "RunSpec", "WireShape", "checked_text", "wire_moment"]

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

_WIRE_KEYS: Final = (
    "workflow", "workflow_digests", "label", "base_ref", "base_sha", "branch", "params",
    "created_at",
)

# The `Z` and not `isoformat`'s `+00:00`, and whole seconds, which is all this wire form holds.
_WIRE_TIME: Final = "%Y-%m-%dT%H:%M:%SZ"

_SHA_CHARACTERS: Final = frozenset("0123456789abcdef")
# A git object id: sha1 is 40 characters of lowercase hexadecimal, sha256 is 64.
_SHA_LENGTHS: Final = frozenset({40, 64})

# Unicode's category for a surrogate: the one kind of code point a `str` may hold and UTF-8 cannot
# encode at all.
_SURROGATE: Final = "Cs"

_STORE_REFUSES: Final = (
    "so the store refuses the write and this refuses it here, where the caller still knows what "
    "it handed over"
)

_PARAM_KEY: Final = "the param key"
_WORKFLOW_FILE: Final = "the workflow file"

@dataclass(frozen=True, slots=True)
class WireShape:
    """One wire schema: the whole key set a document carries, and the nouns its refusals use."""

    keys: tuple[str, ...]

    document: str

    schema_name: str

    instance_name: str

    plural_name: str

    moment_name: str

    def check(self, data: Mapping[str, object]) -> None:
        """Refuse a parsed document whose key set is not this schema's, rather than migrating it.

        :param data: a document read back; a key AGL does not know means another version wrote it
        :raises InternalError: naming the missing and the unexpected keys, in this shape's nouns
        """
        missing = [key for key in self.keys if key not in data]
        unknown = sorted(repr(key) for key in data if key not in self.keys)
        if missing or unknown:
            subject = self.instance_name[0].upper() + self.instance_name[1:]
            raise InternalError(
                f"{self.document}'s keys are not {self.schema_name}'s: missing {missing}, "
                f"unexpected {unknown}. {subject} carrying keys AGL does not know was written by "
                f"another version of it, and this module refuses {self.plural_name} rather than "
                f"migrating them"
            )

    def text(self, data: Mapping[str, object], key: str) -> str:
        """One string field off the wire, once `check` has already settled the key set.

        :param data: a document whose keys are this schema's, so presence is not in question here
        :param key: which field to read; it must be present, which is what `check` has settled
        :return: the value, narrowed to `str`
        :raises InternalError: the value is some other type, named in this schema's nouns
        """
        value = data[key]
        if not isinstance(value, str):
            raise InternalError(
                f"{self.document}'s {key!r} is a {type(value).__name__}, and "
                f"{self.instance_name}'s {key} is a string"
            )
        return value

    def normalised(self, moment: datetime) -> datetime:
        """The same instant, at the precision this wire form can actually hold.

        :param moment: refused when naive, before `astimezone` could read the machine's own zone
        :return: UTC, truncated to whole seconds, which is what the wire spelling carries
        :raises InternalError: the moment has no timezone, so it denotes no instant at all
        """
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise InternalError(
                f"{self.moment_name} {moment!r} has no timezone, and a wall-clock reading with no "
                f"place is not a moment - {self.schema_name} carries an instant, written as UTC"
            )
        utc = moment.astimezone(UTC)
        return utc - timedelta(microseconds=utc.microsecond)

_WIRE: Final = WireShape(
    keys=_WIRE_KEYS,
    document="run.json",
    schema_name="a run record",
    instance_name="a record",
    plural_name="records",
    moment_name="created_at",
)

def wire_moment(moment: datetime) -> str:
    """One moment as a record spells it, which is the only spelling AGL writes down.

    :param moment: normalise it first - the trailing `Z` is a literal and no offset is applied
    :return: `2026-08-18T09:14:02Z`, whole seconds and no fraction
    """
    return format(moment, _WIRE_TIME)

@dataclass(frozen=True, slots=True)
class RunSpec:
    """One run as `run.json` holds it: the workflow, the base it cut from, its params and label."""

    workflow: str

    workflow_digests: Mapping[str, str]

    label: RunLabel

    base_ref: str

    base_sha: str

    branch: str

    params: Mapping[str, JsonValue]

    created_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("workflow", self.workflow), ("base_ref", self.base_ref), ("branch", self.branch),
        ):
            if not value:
                raise InternalError(f"a run record's {name!r} is empty, and that names nothing")
        _check_sha(self.base_sha)
        checked_text(self.base_ref, "base_ref")
        object.__setattr__(
            self, "workflow_digests", MappingProxyType(_checked_digests(self.workflow_digests))
        )
        object.__setattr__(self, "params", MappingProxyType(_checked_params(self.params)))
        object.__setattr__(self, "created_at", _WIRE.normalised(self.created_at))

    def to_json(self) -> dict[str, JsonValue]:
        """This record as the object `run.json` holds. Pure, and it writes nothing anywhere.

        :return: a fresh `dict`, its keys spelled out so that renaming a field cannot rename one
        """
        # Annotated where it is built rather than emitted straight into the object below, because
        # `dict` is invariant: the digests are `str` and a `dict[str, str]` is not a `JsonValue`.
        digests: dict[str, JsonValue] = dict(_checked_digests(self.workflow_digests))
        return {
            "workflow": self.workflow,
            "workflow_digests": digests,
            "label": str(self.label),
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "branch": self.branch,
            "params": _checked_params(self.params),
            "created_at": wire_moment(self.created_at),
        }

    @classmethod
    def from_json(cls, data: object) -> RunSpec:
        """A record read back off the wire, held to exactly the standard a constructed one is.

        :param data: `object`, because a parsed file is anything until this has looked at it
        :return: the record, its fields checked by the constructor rather than a second time here
        :raises InternalError: for every fault, including ones `ids.py` would call `InputError`
        """
        if not isinstance(data, Mapping):
            raise InternalError(f"a run record is a JSON object, not a {type(data).__name__}")
        _WIRE.check(data)
        digests = data["workflow_digests"]
        if not isinstance(digests, Mapping):
            raise InternalError(
                f"run.json's 'workflow_digests' is a {type(digests).__name__}, and a workflow's "
                f"digests are a JSON object - one file of its own directory per key"
            )
        params = data["params"]
        if not isinstance(params, Mapping):
            raise InternalError(
                f"run.json's 'params' is a {type(params).__name__}, and a workflow's params are a "
                f"JSON object - whatever the workflow chose to put in it"
            )
        try:
            label = RunLabel(_WIRE.text(data, "label"))
            created_at = datetime.fromisoformat(_WIRE.text(data, "created_at"))
        except (InputError, ValueError) as error:
            raise InternalError(f"run.json holds a value AGL cannot read back: {error}") from error
        return cls(
            workflow=_WIRE.text(data, "workflow"),
            workflow_digests=digests,
            label=label,
            base_ref=_WIRE.text(data, "base_ref"),
            base_sha=_WIRE.text(data, "base_sha"),
            branch=_WIRE.text(data, "branch"),
            params=params,
            created_at=created_at,
        )

def _check_sha(value: str) -> None:
    if len(value) not in _SHA_LENGTHS or not _SHA_CHARACTERS.issuperset(value):
        raise InternalError(
            f"base_sha {value!r} is not a resolved commit: expected 40 characters of lowercase "
            f"hexadecimal (sha1) or 64 (sha256) - a full object id, because an abbreviated one "
            f"stops being unique as the repository grows and so pins nothing"
        )

# A key here is a path a directory listing produced, so it carries a lone surrogate wherever the
# filesystem held bytes that are not valid UTF-8 - which `checked_text` refuses, the same rule
# `params` and `base_ref` are held to and for the same reason.
def _checked_digests(digests: Mapping[str, str]) -> dict[str, str]:
    checked: dict[str, str] = {}
    for name, digest in digests.items():
        spelled = _checked_key(name, _WORKFLOW_FILE)
        if not isinstance(digest, str):
            raise InternalError(
                f"the digest recorded for {_WORKFLOW_FILE} {spelled!r} is a "
                f"{type(digest).__name__}, and a digest is the one string a resume compares "
                f"against that workflow's directory as it stands now"
            )
        checked[spelled] = checked_text(digest, f"{_WORKFLOW_FILE} {spelled!r}'s digest")
    return checked

def _checked_params(params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        _checked_key(key, _PARAM_KEY): _checked_json(value, f"params.{key}")
        for key, value in params.items()
    }

def _checked_key(key: object, where: str) -> str:
    if not isinstance(key, str):
        raise InternalError(
            f"{where} {key!r} is a {type(key).__name__}, and a JSON object is keyed by "
            f"strings - writing this record would silently rename it"
        )
    return checked_text(key, f"{where} {key!r}")

def checked_text(value: str, where: str, *, cost: str = _STORE_REFUSES) -> str:
    """`value` itself, if it is text AGL can write down - which is every `str` but one kind.

    :param value: refused only for a lone surrogate, which UTF-8 has no encoding for at all
    :param where: names the value in the refusal, so a reader can place which field it was
    :param cost: closes the refusal by saying what the check is protecting at this call site
    :return: the value unchanged
    :raises InputError: naming the code point and its position, never the character itself
    """
    for index, character in enumerate(value):
        if unicodedata.category(character) == _SURROGATE:
            raise InputError(
                f"{where} holds U+{ord(character):04X} at position {index}, which is a surrogate: "
                f"UTF-8 has no encoding for one at all, {cost}"
            )
    return value

def _checked_json(value: object, where: str) -> JsonValue:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return checked_text(value, where)
    if isinstance(value, float):
        if not isfinite(value):
            raise InternalError(
                f"{where} is {value!r}, which JSON has no spelling for: it would be written as a "
                f"bare token no reader accepts, and NaN does not even equal itself"
            )
        return value
    if isinstance(value, Mapping):
        return {
            _checked_key(key, _PARAM_KEY): _checked_json(item, f"{where}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_checked_json(item, f"{where}[{index}]") for index, item in enumerate(value)]
    raise InternalError(
        f"{where} is a {type(value).__name__}, which is not a JSON value: a workflow's params are "
        f"stored exactly as given and read back the same, so they have to be writable"
    )
