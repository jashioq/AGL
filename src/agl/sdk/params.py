"""`arg()` - a workflow's params dataclass becomes named CLI flags, and a record in `run.json`.

Plan §3.3 is this module's whole specification:

    @dataclass(frozen=True)
    class TicketsParams:
        request:    str = arg("-r", "--request", help="what to build")
        concurrent: int = arg("-c", "--concurrent", default=3)

driven by `agl run tickets -n auth -r "add oauth" -c 4`, and "persisted into `run.json`, which is
why `agl resume auth` takes no flags" - which is `arg`, then `parser_for` and `parse`, then
`to_json`.

## Named flags only - a rule with two sides

§1.2 charges the old code with putting `--max-concurrent`, one workflow's input, on the *generic*
`run` parser: every workflow paid for one workflow's flag, and it then persisted into a shared
record. The mirror charge is a workflow inventing a *positional*, since the argument after `run` is
the workflow's name and anything put there is read by whichever parser saw it first. So a positional
is refused where it is written, in `arg`, not at the parse that would have gone wrong: a package
that cannot be invoked correctly should not import. One overlap is deliberately not policed - a
workflow declaring a spelling the generic parser also uses is shadowed by whichever runs first, and
encoding that list here would copy one living in `cli/`. Composing the two is where it shows, at
10.4.

## `dataclasses.field`, rather than a mechanism of our own

`arg()` returns a `dataclasses.field(...)` carrying its declaration in `metadata`, under one
namespaced key so nothing else an author puts there can collide. Required-ness is then not a concept
this module has: a field with no `default` is one `dataclasses` insists on at construction, and that
*is* the required flag; a sentinel or a `Required[]` wrapper would answer a settled question twice.
One consequence is inherited whole, its error coming from `dataclasses`: a field with no default may
not follow one with a default, so **required flags are declared first**, constraining source order
and nothing about argv. The typing trick is typeshed's own, mirrored rather than invented - `field`
is overloaded to return `_T` when a `default` is passed and `Any` when one is not, which is what
lets `request: str = arg(...)` typecheck while `arg` knows nothing about `str`. No `cast` here.

## Every refusal is `InputError`, and nothing here exits

§3.3: "Validation failure is `InputError` -> exit 2, before anything runs." That covers a missing
required flag and a value that will not convert - the pair `argparse` handles by calling
`ArgumentParser.error()` -> `sys.exit(2)`. The number is even right and it is still wrong: it is a
second exit-code table, written in `argparse`, bypassing `ports/errors.py`'s one table and the CLI's
handler with it. So `RefusingParser` overrides `error()` to raise, exported because `cli/main.py`
(10.4) builds the *generic* parser and has the identical need. `exit_on_error=False` is not enough:
it converts only what is raised while consuming a value, while a missing required argument and an
unrecognised one still go through `error()`. `exit()` is *not* overridden - `-h` exiting 0 is
right.

Declaration faults - a positional, a flag spelled `-abc`, a field type nothing can parse - are
`InputError` too, worth recording since their author is a workflow package and not the person
typing. `config/registry.py` settled it the same way: a package whose entry point will not load is
`InputError`, because "AGL only read what it declared" and exit 70 sends the reader to the wrong
codebase. `arg()` runs at class-definition time, so its refusal leaves that package's import - past
`registry.load`, which passes all but `ImportError` and `AttributeError` through - as the 2 it is.

## What the params parser is

`add_help=False`, because `-h` belongs to the generic parser, which sees argv first, and two parsers
claiming it would make one word mean two helps depending on where it appeared; it also leaves this
parser no action that can call `sys.exit` at all. `allow_abbrev=False`, so the accepted spellings
are exactly the declared ones: an abbreviation is a spelling nobody wrote down, which stops working
the day a second flag makes it ambiguous. `default=SUPPRESS`, so a flag the user did not pass leaves
no attribute behind and the instance takes the dataclass's own default, which stays written on the
author's one line. And `dest=` is the field name, so spelling and field name stay independent.

## Field types: `str`, `int`, `float`, `bool`, and nothing else

Anything else is refused, naming the field and its type: the four are what a shell hands over as
text and `run.json` holds unchanged, while a `list[str]` or a `Path` would each need a conversion
this module invented - and §3.3's `**inputs` is where real Python values go. **A `bool` field is a
value-less switch** - `--force`, not `--force true` - so it must be declared `default=False`, both
alternatives being refused rather than quietly mangled: with no default it is a *required* switch,
which the user must type and which can then only mean `True`, and with `default=True` the flag
cannot turn it off, so passing it is a no-op and the second state unreachable.
`argparse.BooleanOptionalAction`, which spells `True` as `--force/--no-force`, was rejected: it
invents a spelling the author never declared - this discipline in reverse - and off `-f`, `--no-f`.

**Two values parse cleanly and `run.json` cannot hold them**, and `_storable` refuses both: a
non-finite float (`-c inf`), which `json` writes as a bare token no reader accepts, and a `str`
holding a lone surrogate, which is what `os.fsdecode` makes of an argv byte that is not UTF-8.
`ports/run.py` refuses both as `InternalError`, because at that layer a bad value means AGL wrote
it; here a person typed it, and exit 70 is wrong. `to_json` runs before the run does, so this is
still "before anything runs".

## `to_json` and `from_json`, and why the second one waited for 16.2

`ports/run.py` keeps both directions together and says why: `run.json`'s key names are that type's
wire format, written out by hand, and two hand-written lists that must agree belong in one place.
Neither half reaches here. The keys are the author's field names and the values the author's field
types, both *derived*, so there is nothing here for the two directions to drift apart about - which
is why `from_json` could be written the day it was needed rather than the day `to_json` was, and
why what it costs is one paragraph and not a schema.

**`from_json` is a refusal point and never a coercion point.** It hands back the values the record
holds, at the types the record holds them, and refuses everything else: a key the class does not
declare, a field the record does not carry, and a value whose type the field does not admit. It
does not convert `"4"` into `4`, and there is no version of this that should - a record is what a
previous invocation of *this* workflow wrote through `to_json`, so a value needing conversion is a
value some other params class produced.

**Which is why the refusal is `InputError` and not `ports/run.py`'s `InternalError`.** That module
raises 70 because "nobody types this file - AGL writes it and AGL reads it", and at its layer a bad
record is indistinguishable from our own bug. Here it is distinguishable, because `api.resume`
compares `workflow_version` with `==` before it calls this: a record that got past that comparison
claims to have been written by the very workflow now reading it. So a mismatch here means the
workflow's params class moved and its `version` did not, which is a declaration fault in a package
the operator installed - `config/registry.py`'s case exactly, and this module's own rule ("every
refusal is `InputError`") without an exception being made for it. Exit 2 sends the reader to the
`@workflow(version=...)` line they can change; exit 70 would send them to file a bug against AGL.

Not checked, deliberately: that the params class is **frozen**. A mutable one still parses and still
renders, and probing `__dataclass_params__` - the only way to ask - is the guessing §1.2 charges.
"""

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

# The one key `arg()` writes into `field(metadata=...)`, namespaced because metadata is shared.
_METADATA_KEY: Final = "agl.sdk.params"

# A flag's name, after the leading dashes. An allowlist, for `ids.py`'s reason - a list of what is
# permitted rather than of what is dangerous - and narrow enough that `-1` cannot be declared:
# `argparse` decides whether `-1` on the line is a number or a flag by looking at what flags exist,
# so one such declaration would change how every *other* argument is read.
_FLAG_CHARACTERS: Final = frozenset(ascii_letters + digits + "-_")

# The field types a shell hands over as text, each its own `argparse` converter - which is what
# makes a refusal read "invalid int value: 'banana'". `bool("false")` is `True`: hence the switch.
_PARSEABLE: Final = (str, int, float)

# What a field of each declared type may hold when its value comes back off `run.json` - the read
# side of `_storable`, and the whole of what `from_json` checks a value against.
#
# **`float` admits an `int`, and that is the round trip rather than a courtesy.** `arg(default=3)`
# on a `float`-annotated field is legal - `arg` takes any of the four as a default and `_consumes`
# has a rule about `bool`'s alone - so a run where that flag went unpassed stores the `int` 3, and
# a `from_json` demanding a `float` back would refuse a record AGL itself wrote through `to_json`.
# PEP 484 makes the same widening for the same reason.
#
# **`bool` is deliberately not listed against `int` and does not need to be**: `isinstance(True,
# int)` is already true, which is Python's own answer to whether a `bool` is an `int`, and the same
# `arg(default=True)`-on-an-`int`-field round trip depends on it. Nothing here contradicts that
# answer in order to be tidier than the language.
_ADMITTED: Final = ((bool, (bool,)), (int, (int,)), (float, (int, float)), (str, (str,)))


@dataclass(frozen=True, slots=True)
class _Declared:
    """What `arg()` records on a field: the flags it may be spelled with, and its help line."""
    flags: tuple[str, ...]
    help: str


class RefusingParser(argparse.ArgumentParser):
    """An `ArgumentParser` raising `InputError` where the base class would exit 2. Exported for
    `cli/main.py`, which has the same need; `exit()` is untouched - see the module docstring."""

    def error(self, message: str) -> NoReturn:
        raise InputError(f"{self.format_usage().strip()}\n{message}")


@overload
def arg[T](*flags: str, default: T, help: str = "") -> T: ...
@overload
def arg(*flags: str, help: str = "") -> Any: ...
def arg(*flags: str, default: Any = MISSING, help: str = "") -> Any:
    """Declare one field of a params dataclass as a named CLI flag. `arg("-r", "--request")` is a
    **required** flag and `arg("-c", default=3)` an optional one, because that is what
    `dataclasses.field` does with and without a `default`. Every spelling must be a flag - `-x` or
    `--xyz` - checked here and not at the parse. The return type is `Any` for the required form and
    the default's type for the optional one, which is what makes `request: str = arg(...)`
    typecheck; typeshed types `field` the same way."""
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
    """The flags of `params`, on a parser that refuses by raising rather than exiting. Exposed apart
    from `parse` because a parser can be inspected: it holding no positional is what §3.3 says."""
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
    """`argv` as an instance of `params`, or `InputError` - §3.3's "before anything runs". `argv` is
    the workflow's own flags alone: the generic parser has taken its arguments off the front."""
    parsed = parser_for(params, prog=prog).parse_args(argv)
    # The class is used as a factory of itself. `dataclasses` generates `__init__` at runtime, so no
    # static type can describe what it takes; `Callable[..., T]` says so honestly and keeps the one
    # knowable thing, the type it returns. Not a `cast` in disguise: `T` is inferred, not asserted.
    factory: Callable[..., T] = params
    return factory(**vars(parsed))


def to_json(instance: object) -> Mapping[str, JsonValue]:
    """A params instance as the mapping `RunSpec.params` holds - §3.3's "persisted into `run.json`".
    Field names are the keys, which is what makes it derived, and why no `from_json` sits beside."""
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
    """`RunSpec.params` as the instance of `params` a resumed workflow is handed - `to_json`'s
    inverse, and the one place `agl resume <label>`'s "params come from `run.json`" is performed.

    Exact, for every value `to_json` can produce: the four types `arg()` admits are scalars, so
    there is nothing here to reconstruct and nothing to walk - each value is handed to the
    constructor as the record holds it, and the instance is the one the first invocation held.

    `InputError` for a record this class cannot take, in the three shapes that has: a field the
    record does not carry, a key the class does not declare, and a value of a type the field does
    not admit. Nothing is converted on the way past - the module docstring argues both the refusal
    and the class, and the short version is that `api.resume` has already compared
    `workflow_version` with `==`, so a record reaching here disagreeing with the class is a
    workflow whose params moved while its version stood still.

    The keys are the field names, derived, which is what leaves the two directions with no list to
    keep in agreement - and the reason a change to the shape below is a change to one function
    rather than to a wire format two functions spell out.
    """
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
    # The class as a factory of itself, exactly as `parse` spells it and for `parse`'s reason:
    # `dataclasses` generates `__init__` at runtime, so no static type describes what it takes, and
    # `Callable[..., T]` keeps the one knowable thing. `T` is inferred here too, never asserted.
    factory: Callable[..., T] = params
    return factory(
        **{name: _restored(f"{kind}.{name}", hints.get(name), data[name]) for name in declared}
    )


def _field_names(params: object) -> tuple[str, ...]:
    """This params dataclass's fields, in declaration order - the keys `run.json` holds them under.

    Takes `object` so that `is_dataclass`'s type guard narrows nothing in the caller, where
    `params` has to stay the `type[T]` it was declared or the factory above loses its return type.
    The guard narrows to a dataclass type of typeshed's own naming and not to the `T` mypy solved
    for at the call, so this parameter type is the whole of what keeps the two apart -
    `sdk/tools.py::_check_payload` holds a `type[P]` out of the same guard's way for that reason.
    """
    if not is_dataclass(params):
        raise InputError(f"{_describe(params)} is not a dataclass of `arg()` fields (§3.3)")
    return tuple(spec.name for spec in fields(params))


def _restored(where: str, hint: object, value: JsonValue) -> JsonValue:
    """`value` itself, if this field's declared type admits it - and never a value converted into
    one that would.

    Two refusals, and they are the same one seen from either end. A field declared something the
    record cannot hold at all is `_consumes`' refusal arriving on the read side, at a workflow whose
    params class grew a `list[str]` since the run started. A value the field does not admit is that
    class changing one field's type - `concurrent: str` where the record holds `4` - which the
    version stamp is what should have caught and which converting would hide: the workflow would be
    handed a parameter nobody chose, and every fingerprint taken over it would be taken over a
    value the first invocation never had.
    """
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
    """`value` itself, if `run.json` can hold it - the module docstring argues the two refusals. The
    `str` branch's `encode` *is* the surrogate check, and the only honest form of the question."""
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
    """What `argparse` does with this field's argument: nothing for a switch, else the builtin as
    its own converter. A `bool` is also the one kind with a rule about its own default."""
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
    """Every field's annotation, resolved: `Field.type` holds a *string* under `from __future__`."""
    try:
        return get_type_hints(params)
    except (NameError, TypeError) as error:
        raise InputError(
            f"{_describe(params)} has an annotation that cannot be resolved: {error}. Its fields "
            f"are read for their types, so each has to name something importable where it is"
        ) from error


def _unusable_flag(flag: str) -> str | None:
    """Why `flag` may not be one, or `None` if it may - one sentence per rule, as in `ids.py`."""
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
    """A class as `grep` finds it; an annotation that is not one, `list[str]` say, as written."""
    if not isinstance(thing, type):
        return repr(thing)
    return f"{thing.__module__}.{thing.__qualname__}"
