
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


_SEPARATORS: Final = (",", ":")

_TYPE_KEY: Final = "__agl_type__"

_WIRE_KEYS: Final = ("fingerprint", "value", "head", "at")

_WIRE_TIME: Final = "%Y-%m-%dT%H:%M:%SZ"

_SURROGATE: Final = "Cs"


def canonical_json(value: object) -> str:
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
    return (scope, step.collision_key, base)


class Fingerprints:

    def __init__(self) -> None:
        self._counts: dict[tuple[RunScope, str, str], int] = {}

    def digest(self, scope: RunScope, step: StepName, base: str) -> str:
        count = self._counts.get(_counter_key(scope, step, base), 0)
        return sha256(f"{base}:{count}".encode()).hexdigest()

    def claimed(self, scope: RunScope, step: StepName, base: str) -> None:
        key = _counter_key(scope, step, base)
        self._counts[key] = self._counts.get(key, 0) + 1


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:

    fingerprint: str

    value: JsonValue

    head: str

    at: datetime

    def __post_init__(self) -> None:
        for name, value in (("fingerprint", self.fingerprint), ("head", self.head)):
            if not value:
                raise InternalError(f"a step entry's {name!r} is empty, and that names nothing")
        object.__setattr__(self, "at", _normalised(self.at))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "fingerprint": self.fingerprint,
            "value": self.value,
            "head": self.head,
            "at": format(self.at, _WIRE_TIME),
        }

    @classmethod
    def from_json(cls, data: object) -> Entry:
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
            value=data["value"],
            head=_wire_text(data, "head"),
            at=at,
        )


async def read_entry(store: Store, scope: RunScope, step: StepName, digest: str) -> Entry | None:
    document = await store.read_entry(scope, step, digest)
    if document is None:
        return None
    entry = Entry.from_json(document)
    if entry.fingerprint != digest:
        return None
    return entry


async def write_entry(
    store: Store, scope: RunScope, step: StepName, digest: str, entry: Entry
) -> None:
    await store.write_entry(scope, step, digest, entry.to_json())


class Journal:

    def __init__(
        self,
        store: Store,
        scope: RunScope,
        workspace: Workspace,
        clock: Clock,
        fingerprints: Fingerprints,
        base: str,
    ) -> None:
        self._store = store
        self._scope = scope
        self._workspace = workspace
        self._clock = clock
        self._fingerprints = fingerprints
        if not base:
            raise InternalError(
                "a journal was opened at an empty base, and a namespace's starting head names the "
                "commit it was opened from - there is no state in which a walk has no head yet"
            )
        self._last_good = base
        self._running = asyncio.Lock()

    @property
    def last_good(self) -> str:
        return self._last_good

    def advance(self, head: str) -> None:
        if not head:
            raise InternalError(
                "an integration tried to advance a namespace's chain to an empty head, and an "
                "empty string names no commit - a landing that went in reports where the target is "
                "now, and one that did not carries a conflict instead of a head"
            )
        self._last_good = head

    async def exclude_steps(self) -> Callable[[], None]:
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
        async with self._running:
            base = base_of(
                instructions=instructions,
                model=model,
                restrictions=restrictions,
                tools=tools,
                inputs=inputs,
                head=self._last_good,
            )
            digest = self._fingerprints.digest(self._scope, name, base)
            entry = await read_entry(self._store, self._scope, name, digest)
            if entry is not None:
                self._fingerprints.claimed(self._scope, name, base)
                self._last_good = entry.head
                return entry.value

            await self._workspace.restore(self._last_good)
            try:
                result = await worker()
            finally:
                await self._ended(commit)

            head = await self._workspace.head()
            await write_entry(
                self._store,
                self._scope,
                name,
                digest,
                Entry(fingerprint=digest, value=result, head=head, at=self._clock.now()),
            )
            self._fingerprints.claimed(self._scope, name, base)
            self._last_good = head
            return result

    async def _ended(self, commit: str | None) -> None:
        ending = asyncio.create_task(self._ending(commit))
        cancellation: asyncio.CancelledError | None = None
        while not ending.done():
            try:
                await asyncio.shield(ending)
            except asyncio.CancelledError as raised:
                cancellation = raised
            except Exception:
                break
        failed = ending.exception()
        if cancellation is not None:
            if failed is not None:
                raise cancellation from failed
            raise cancellation
        if failed is not None:
            raise failed

    async def _ending(self, commit: str | None) -> None:
        if commit is not None:
            await self._workspace.commit_all(commit)
        else:
            await self._workspace.restore(self._last_good)


def _dumps(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=_SEPARATORS, ensure_ascii=True)


def _canonical(value: object, where: str) -> JsonValue:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return _checked_text(value, where)
    if isinstance(value, float):
        if not isfinite(value):
            raise InputError(
                f"{where} is {value!r}, which JSON has no spelling for: it would be written as a "
                f"bare token no reader accepts, and NaN does not even equal itself - so a step "
                f"fingerprinted with one could never match the entry it wrote"
            )
        return value
    if isinstance(value, Mapping):
        return {
            _checked_key(key, where): _canonical(item, f"{where}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, AbstractSet):
        return sorted((_canonical(item, f"{where}[]") for item in value), key=_dumps)
    if isinstance(value, list | tuple):
        return [_canonical(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
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
    value = data[key]
    if not isinstance(value, str):
        raise InternalError(
            f"a step entry's {key!r} is a {type(value).__name__}, and an entry's {key} is a string"
        )
    return value


def _normalised(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise InternalError(
            f"a step entry's 'at' {moment!r} has no timezone, and a wall-clock reading with no "
            f"place is not a moment - an entry carries an instant, written as UTC"
        )
    utc = moment.astimezone(UTC)
    return utc - timedelta(microseconds=utc.microsecond)


def _checked_key(key: object, where: str) -> str:
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
    for index, character in enumerate(value):
        if unicodedata.category(character) == _SURROGATE:
            raise InputError(
                f"{where} holds U+{ord(character):04X} at position {index}, which is a surrogate: "
                f"UTF-8 has no encoding for one at all, and the canonical text escapes it to the "
                f"same characters as the astral code point it stands for - so two different inputs "
                f"would share a fingerprint, and one would replay the other's result"
            )
    return value
