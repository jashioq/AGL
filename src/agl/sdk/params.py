
import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from math import isfinite
from string import ascii_letters, digits
from types import MappingProxyType
from typing import Any, Final, NoReturn, get_type_hints, overload

from agl.ports.errors import InputError
from agl.ports.run import JsonValue

__all__ = ["RefusingParser", "arg", "from_json", "parse", "parser_for", "to_json"]

_METADATA_KEY: Final = "agl.sdk.params"

_FLAG_CHARACTERS: Final = frozenset(ascii_letters + digits + "-_")

_PARSEABLE: Final = (str, int, float)

_ADMITTED: Final = ((bool, (bool,)), (int, (int,)), (float, (int, float)), (str, (str,)))


@dataclass(frozen=True, slots=True)
class _Declared:
    flags: tuple[str, ...]
    help: str


class RefusingParser(argparse.ArgumentParser):

    def error(self, message: str) -> NoReturn:
        raise InputError(f"{self.format_usage().strip()}\n{message}")


@overload
def arg[T](*flags: str, default: T, help: str = "") -> T: ...
@overload
def arg(*flags: str, help: str = "") -> Any: ...
def arg(*flags: str, default: Any = MISSING, help: str = "") -> Any:
    if not flags:
        raise InputError(
            "a parameter is declared with at least one flag - `arg('-r', '--request')`. A field "
            "with none could only be filled by position, and §3.3 gives a workflow no such way"
        )
    for flag in flags:
        reason = _unusable_flag(flag)
        if reason is not None:
            raise InputError(f"{flag!r} cannot be a workflow's flag: {reason}")
    declared = {_METADATA_KEY: _Declared(flags=flags, help=help)}
    if default is MISSING:
        return field(metadata=declared)
    if not isinstance(default, bool | int | float | str):
        raise InputError(
            f"the default {default!r} for {'/'.join(flags)} is a {type(default).__name__}, and a "
            f"parameter is a str, an int, a float or a bool - what a shell hands over as text"
        )
    return field(default=default, metadata=declared)


def parser_for(params: type[object], *, prog: str | None = None) -> RefusingParser:
    if not is_dataclass(params):
        raise InputError(f"{_describe(params)} is not a dataclass of `arg()` fields (§3.3)")
    parser = RefusingParser(prog=prog, add_help=False, allow_abbrev=False)
    hints = _hints(params)
    claimed: dict[str, str] = {}
    for spec in fields(params):
        where = f"{_describe(params)}.{spec.name}"
        declared = spec.metadata.get(_METADATA_KEY)
        if not isinstance(declared, _Declared):
            raise InputError(
                f"{where} is not declared with `arg()`, and every field of a params dataclass is a "
                f"flag: a field without one could never be given a value on the command line"
            )
        for flag in declared.flags:
            if claimed.setdefault(flag, spec.name) != spec.name:
                raise InputError(
                    f"{where} and its sibling {claimed[flag]!r} both declare {flag!r}, so one of "
                    f"the two could never receive a value"
                )
        parser.add_argument(
            *declared.flags, dest=spec.name, required=spec.default is MISSING,
            default=argparse.SUPPRESS, help=declared.help or None,
            **_consumes(where, hints.get(spec.name), spec.default),
        )
    return parser


def parse[T](params: type[T], argv: Sequence[str], *, prog: str | None = None) -> T:
    parsed = parser_for(params, prog=prog).parse_args(argv)
    factory: Callable[..., T] = params
    return factory(**vars(parsed))


def to_json(instance: object) -> Mapping[str, JsonValue]:
    if isinstance(instance, type) or not is_dataclass(instance):
        raise InputError(
            f"{_describe(instance)} is not an instance of a params dataclass: a run record stores "
            f"the parameters a workflow was given, not the class describing them"
        )
    kind = _describe(type(instance))
    return MappingProxyType({
        spec.name: _storable(f"{kind}.{spec.name}", getattr(instance, spec.name))
        for spec in fields(instance)
    })


def from_json[T](params: type[T], data: Mapping[str, JsonValue]) -> T:
    kind = _describe(params)
    declared = _field_names(params)
    hints = _hints(params)
    missing = [name for name in declared if name not in data]
    unknown = sorted(repr(key) for key in data if key not in declared)
    if missing or unknown:
        raise InputError(
            f"the stored parameters are not {kind}'s: missing {missing}, unexpected {unknown}. A "
            f"record carries the parameters the run was started with, and `agl resume` compares "
            f"`workflow_version` before it reads them - so a record whose keys are not this "
            f"class's was written by a workflow that changed its params and kept its version. "
            f"Bump the version, or `agl clear` the run and start it again"
        )
    factory: Callable[..., T] = params
    return factory(
        **{name: _restored(f"{kind}.{name}", hints.get(name), data[name]) for name in declared}
    )


def _field_names(params: object) -> tuple[str, ...]:
    if not is_dataclass(params):
        raise InputError(f"{_describe(params)} is not a dataclass of `arg()` fields (§3.3)")
    return tuple(spec.name for spec in fields(params))


def _restored(where: str, hint: object, value: JsonValue) -> JsonValue:
    for declared, admitted in _ADMITTED:
        if hint is declared:
            if isinstance(value, admitted):
                return value
            raise InputError(
                f"{where} is declared a {_describe(hint)} and the record holds {value!r}. A run's "
                f"parameters are read back exactly as they were stored and never converted into "
                f"what a field now says it holds, so this is the workflow's params class having "
                f"moved under a version that did not"
            )
    raise InputError(
        f"{where} is a {_describe(hint)}, and a parameter is a str, an int, a float or a bool: "
        f"what a shell hands over as text and what `run.json` holds unchanged. This record was "
        f"written when the field was one of the four, and reading it back needs it to still be"
    )


def _storable(where: str, value: object) -> JsonValue:
    try:
        if isinstance(value, bool | int) or (isinstance(value, float) and isfinite(value)):
            return value
        if isinstance(value, str):
            value.encode()
            return value
    except UnicodeEncodeError:
        pass
    raise InputError(
        f"{where} holds {value!r}, which `run.json` cannot: a parameter is a bool, an int, a "
        f"finite float, or a str that UTF-8 can encode"
    )


def _consumes(where: str, hint: object, default: object) -> dict[str, Any]:
    if hint is bool:
        if default is not False:
            raise InputError(
                f"{where} is a bool, so it is a switch and must be declared `default=False`: with "
                f"no default the flag is required and only ever True, and `default=True` it cannot "
                f"turn off"
            )
        return {"action": "store_true"}
    for kind in _PARSEABLE:
        if hint is kind:
            return {"type": kind}
    raise InputError(
        f"{where} is a {_describe(hint)}, and a parameter is a str, an int, a float or a bool: "
        f"what a shell hands over as text and what `run.json` holds unchanged"
    )


def _hints(params: type[object]) -> Mapping[str, object]:
    try:
        return get_type_hints(params)
    except (NameError, TypeError) as error:
        raise InputError(
            f"{_describe(params)} has an annotation that cannot be resolved: {error}. Its fields "
            f"are read for their types, so each has to name something importable where it is"
        ) from error


def _unusable_flag(flag: str) -> str | None:
    if not flag.startswith("-"):
        return "it is a positional, and `agl run <workflow>` already occupies that position (§3.3)"
    name = flag.removeprefix("--") if flag.startswith("--") else flag[1:]
    if not name:
        return "it is dashes and nothing else"
    if not flag.startswith("--") and len(name) != 1:
        return f"a single dash introduces a one-character flag - write '--{name}' for a longer name"
    if name[0] not in ascii_letters:
        return "a flag's name starts with an ASCII letter"
    for index, character in enumerate(name):
        if character not in _FLAG_CHARACTERS:
            return (
                f"it holds {character!r} at position {index}, and a flag may hold only letters "
                f"A-Z a-z, digits, '-' and '_'"
            )
    return None


def _describe(thing: object) -> str:
    if not isinstance(thing, type):
        return repr(thing)
    return f"{thing.__module__}.{thing.__qualname__}"
