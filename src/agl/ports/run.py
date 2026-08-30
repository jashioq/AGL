
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from types import MappingProxyType
from typing import Final

from agl.ports.errors import InputError, InternalError
from agl.ports.ids import RunLabel

__all__ = ["JsonValue", "RunSpec", "checked_text"]


type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

_WIRE_KEYS: Final = (
    "workflow", "workflow_version", "label", "base_ref", "base_sha", "branch", "params",
    "created_at",
)

_WIRE_TIME: Final = "%Y-%m-%dT%H:%M:%SZ"

_SHA_CHARACTERS: Final = frozenset("0123456789abcdef")
_SHA_LENGTHS: Final = frozenset({40, 64})

_SURROGATE: Final = "Cs"


@dataclass(frozen=True, slots=True)
class RunSpec:

    workflow: str

    workflow_version: str

    label: RunLabel

    base_ref: str

    base_sha: str

    branch: str

    params: Mapping[str, JsonValue]

    created_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("workflow", self.workflow), ("workflow_version", self.workflow_version),
            ("base_ref", self.base_ref), ("branch", self.branch),
        ):
            if not value:
                raise InternalError(f"a run record's {name!r} is empty, and that names nothing")
        _check_sha(self.base_sha)
        checked_text(self.base_ref, "base_ref")
        object.__setattr__(self, "params", MappingProxyType(_checked_params(self.params)))
        object.__setattr__(self, "created_at", _normalised(self.created_at))

    def to_json(self) -> dict[str, JsonValue]:
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
    value = data[key]
    if not isinstance(value, str):
        raise InternalError(
            f"run.json's {key!r} is a {type(value).__name__}, and a record's {key} is a string"
        )
    return value


def _check_sha(value: str) -> None:
    if len(value) not in _SHA_LENGTHS or not _SHA_CHARACTERS.issuperset(value):
        raise InternalError(
            f"base_sha {value!r} is not a resolved commit: expected 40 characters of lowercase "
            f"hexadecimal (sha1) or 64 (sha256) - a full object id, because an abbreviated one "
            f"stops being unique as the repository grows and so pins nothing"
        )


def _normalised(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise InternalError(
            f"created_at {moment!r} has no timezone, and a wall-clock reading with no place is "
            f"not a moment - a run record carries an instant, written as UTC"
        )
    utc = moment.astimezone(UTC)
    return utc - timedelta(microseconds=utc.microsecond)


def _checked_params(params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        _checked_key(key): _checked_json(value, f"params.{key}") for key, value in params.items()
    }


def _checked_key(key: object) -> str:
    if not isinstance(key, str):
        raise InternalError(
            f"the param key {key!r} is a {type(key).__name__}, and a JSON object is keyed by "
            f"strings - writing this record would silently rename it"
        )
    return checked_text(key, f"the param key {key!r}")


def checked_text(value: str, where: str) -> str:
    for index, character in enumerate(value):
        if unicodedata.category(character) == _SURROGATE:
            raise InputError(
                f"{where} holds U+{ord(character):04X} at position {index}, which is a surrogate: "
                f"UTF-8 has no encoding for one at all, so the store refuses the write and this "
                f"refuses it here, where the caller still knows what it handed over"
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
            _checked_key(key): _checked_json(item, f"{where}.{key}") for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_checked_json(item, f"{where}[{index}]") for index, item in enumerate(value)]
    raise InternalError(
        f"{where} is a {type(value).__name__}, which is not a JSON value: a workflow's params are "
        f"stored exactly as given and read back the same, so they have to be writable"
    )
