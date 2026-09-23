import argparse
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from math import isfinite
from string import ascii_letters, digits
from types import MappingProxyType
from typing import Any, Final, NoReturn, overload
from agl.ports.errors import InputError
from agl.ports.run import JsonValue
from agl.sdk._declarations import annotations_of, named

__all__ = [
    "RESERVED_FLAGS",
    "RUN_BASE_REF_FLAGS",
    "RUN_LABEL_FLAGS",
    "RefusingParser",
    "arg",
    "from_json",
    "parse",
    "parser_for",
    "to_json",
]

_METADATA_KEY: Final = "agl.sdk.params"

_FLAG_CHARACTERS: Final = frozenset(ascii_letters + digits + "-_")

# `cli/commands/run.py` declares its own two arguments from these rather than spelling them itself,
# which is what keeps the flag and the refusal below one constant apart instead of two literals a
# rename could separate. It is the direction the dependency rule leaves: `cli` may import `sdk`.
RUN_LABEL_FLAGS: Final = ("-n", "--name")

RUN_BASE_REF_FLAGS: Final = ("--from",)

# `RefusingParser` adds these to every parser that does not turn `add_help` off, and `agl run`'s
# does not - so they are that command's without being declared anywhere in it.
_HELP_FLAGS: Final = ("-h", "--help")

_HELP: Final = "Show this help message and exit."

_ARGUMENTS: Final = "Arguments"

_OPTIONS: Final = "Options"

# `agl run` is the whole of it because it is the only command that hands a workflow argv at all,
# and `tests/cli/test_run_command.py` compares this set against the parser it actually builds - so
# an argument added there and not here fails the build rather than becoming quietly un-refused.
RESERVED_FLAGS: Final = frozenset(RUN_LABEL_FLAGS + RUN_BASE_REF_FLAGS + _HELP_FLAGS)

_RUN_OWNS: Final = ", ".join(
    "/".join(spellings) for spellings in (RUN_LABEL_FLAGS, RUN_BASE_REF_FLAGS, _HELP_FLAGS)
)

_PARSEABLE: Final = (str, int, float)

# `float` admits an `int` because `arg(default=3)` on a float field stores an `int` and `from_json`
# must read back what `to_json` wrote; PEP 484 widens the same way. A `bool` is already an `int`.
_ADMITTED: Final = ((bool, (bool,)), (int, (int,)), (float, (int, float)), (str, (str,)))

@dataclass(frozen=True, slots=True)
class _Declared:
    flags: tuple[str, ...]
    help: str

class _Formatter(argparse.HelpFormatter):
    # `argparse` heads a command table with a row holding its metavar and indents the commands under
    # it; these list the commands alone, measured where they are drawn.
    def _format_action(self, action: argparse.Action) -> str:
        if isinstance(action, argparse._SubParsersAction):
            return "".join(self._format_action(command) for command in action._choices_actions)
        return super()._format_action(action)

    def _iter_indented_subactions(self, action: argparse.Action) -> Generator[argparse.Action]:
        if isinstance(action, argparse._SubParsersAction):
            yield from action._choices_actions

class RefusingParser(argparse.ArgumentParser):
    """An `argparse` parser that raises [`InputError`][agl.sdk.InputError] instead of exiting."""

    def __init__(self, *, add_help: bool = True, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", _Formatter)
        super().__init__(add_help=False, **kwargs)
        self._positionals.title = _ARGUMENTS
        self._optionals.title = _OPTIONS
        if add_help:
            self.add_argument(*_HELP_FLAGS, action="help", default=argparse.SUPPRESS, help=_HELP)
        self.add_help = add_help

    def error(self, message: str) -> NoReturn:
        """Raise [`InputError`][agl.sdk.InputError] instead of exiting.

        Args:
            message: The error message from `argparse`.

        Raises:
            InputError: Always.
        """
        raise InputError(f"{self.format_usage().strip()}\n{message}")

@overload
def arg[T](*flags: str, default: T, help: str = "") -> T: ...
@overload
def arg(*flags: str, help: str = "") -> Any: ...
def arg(*flags: str, default: Any = MISSING, help: str = "") -> Any:
    """Declares a field of a params dataclass as a command-line flag.

    Args:
        flags: The flag's spellings, such as `-n` and `--name`. At least one.
        default: The value when the flag isn't given. If omitted, the flag is required. A `bool`
            field must use `default=False`.
        help: The text `agl workflows <workflow>` shows beside the flag.

    Returns:
        The `dataclasses.field` to assign to the annotated field.

    Raises:
        InputError: No flags, a flag `agl run` uses or can't accept, or a bad default.
    """
    if not flags:
        raise InputError(
            "a parameter is declared with at least one flag - `arg('-r', '--request')`. A field "
            "with none could only be filled by position, and a workflow's parameters are named "
            "flags and nothing else"
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
    """Build the flag parser for a params dataclass.

    Args:
        params: The params dataclass. Every field must be declared with `arg()`.
        prog: The name shown in the usage line. If omitted, uses `sys.argv[0]`.

    Returns:
        A parser that raises [`InputError`][agl.sdk.InputError] instead of exiting.

    Raises:
        InputError: Not a dataclass, a field without `arg()`, or two fields with the same flag.
    """
    if not is_dataclass(params):
        raise InputError(f"{named(params)} is not a dataclass of `arg()` fields")
    parser = RefusingParser(prog=prog, add_help=False, allow_abbrev=False)
    hints = annotations_of(params)
    claimed: dict[str, str] = {}
    for spec in fields(params):
        where = f"{named(params)}.{spec.name}"
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
    """Read a workflow's flags into an instance of its params dataclass.

    Args:
        params: The params dataclass.
        argv: The workflow's own flags, without the ones `agl run` takes.
        prog: The name shown in the usage line. If omitted, uses `sys.argv[0]`.

    Returns:
        An instance of `params` holding the flags' values.

    Raises:
        InputError: A missing required flag, an unknown flag, or a value that won't convert.
    """
    parsed = parser_for(params, prog=prog).parse_args(argv)
    factory: Callable[..., T] = params
    return factory(**vars(parsed))

def to_json(instance: object) -> Mapping[str, JsonValue]:
    """Convert a params instance to JSON values.

    Args:
        instance: The params instance, not its class.

    Returns:
        Each field's value by name, in declaration order.

    Raises:
        InputError: A value that can't be saved as JSON, such as an infinite float.
    """
    if isinstance(instance, type) or not is_dataclass(instance):
        raise InputError(
            f"{named(instance)} is not an instance of a params dataclass: a run record stores "
            f"the parameters a workflow was given, not the class describing them"
        )
    kind = named(type(instance))
    return MappingProxyType({
        spec.name: _storable(f"{kind}.{spec.name}", getattr(instance, spec.name))
        for spec in fields(instance)
    })

def from_json[T](params: type[T], data: Mapping[str, JsonValue]) -> T:
    """Rebuild a params instance from what `to_json` returned.

    Args:
        params: The params dataclass to rebuild.
        data: What `to_json` returned.

    Returns:
        An instance of `params` holding the saved values.

    Raises:
        InputError: A field missing from `data`, a key the class doesn't declare, or a value
            whose type no longer matches its field.
    """
    kind = named(params)
    declared = _field_names(params)
    hints = annotations_of(params)
    missing = [name for name in declared if name not in data]
    unknown = sorted(repr(key) for key in data if key not in declared)
    if missing or unknown:
        whose = f"{kind}'s" if declared else "those of a workflow that takes no parameters"
        raise InputError(
            f"the stored parameters are not {whose}: missing {missing}, unexpected {unknown}. A "
            f"record carries the parameters the run was started with, and `agl resume` digests "
            f"the workflow's own directory before it reads them - so a record whose keys do not "
            f"match was written against a class that comparison does not cover: one declared "
            f"outside that directory, or a run started from entry points a caller handed over "
            f"rather than a workspace. Put the class back, or `agl clear` the run"
        )
    factory: Callable[..., T] = params
    return factory(
        **{name: _restored(f"{kind}.{name}", hints.get(name), data[name]) for name in declared}
    )

def _field_names(params: object) -> tuple[str, ...]:
    if not is_dataclass(params):
        raise InputError(f"{named(params)} is not a dataclass of `arg()` fields")
    return tuple(spec.name for spec in fields(params))

def _restored(where: str, hint: object, value: JsonValue) -> JsonValue:
    for declared, admitted in _ADMITTED:
        if hint is declared:
            if isinstance(value, admitted):
                return value
            raise InputError(
                f"{where} is declared as {named(hint)} and the record holds {value!r}. A run's "
                f"parameters are read back exactly as they were stored and never converted into "
                f"what a field now says it holds, so this is the workflow's params class having "
                f"moved under a version that did not"
            )
    raise InputError(
        f"{where} is declared as {named(hint)}, and a parameter is a str, an int, a float or a "
        f"bool: what a shell hands over as text and what `run.json` holds unchanged. This record "
        f"was written when the field was one of the four, and reading it back needs it to still be"
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
    # `bool("false")` is `True`, which is why a bool field is a switch and never a converter.
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
        f"{where} is declared as {named(hint)}, and a parameter is a str, an int, a float or a "
        f"bool: what a shell hands over as text and what `run.json` holds unchanged"
    )

def _unusable_flag(flag: str) -> str | None:
    if not flag.startswith("-"):
        return "it is a positional, and `agl run <workflow>` already occupies that position"
    name = flag.removeprefix("--") if flag.startswith("--") else flag[1:]
    if not name:
        return "it is dashes and nothing else"
    if not flag.startswith("--") and len(name) != 1:
        return f"a single dash introduces a one-character flag - write '--{name}' for a longer name"
    # A flag's name starts with a letter because `argparse` decides whether `-1` on the command line
    # is a number or a flag by looking at what flags exist - so one such declaration would change
    # how every *other* argument is read.
    if name[0] not in ascii_letters:
        return "a flag's name starts with an ASCII letter"
    for index, character in enumerate(name):
        if character not in _FLAG_CHARACTERS:
            return (
                f"it holds {character!r} at position {index}, and a flag may hold only letters "
                f"A-Z a-z, digits, '-' and '_'"
            )
    if flag in RESERVED_FLAGS:
        return (
            f"`agl run` owns {_RUN_OWNS} and hands a workflow only what it did not recognise "
            f"itself, so this spelling would be taken off the line before the workflow's own "
            f"parser saw it. Every other spelling is a workflow's to take"
        )
    return None
