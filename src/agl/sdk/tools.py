from collections.abc import Awaitable, Callable, Mapping
from dataclasses import MISSING, Field, dataclass, field, fields, is_dataclass
from math import isfinite
from types import MappingProxyType, UnionType
from typing import Any, Final, get_args, get_origin, overload
from agl.ports.agent import Tool, ToolResult, check_tool_declaration
from agl.ports.errors import InputError, InternalError
from agl.ports.run import JsonValue
from agl.sdk._declarations import annotations_of, named

__all__ = [
    "JsonValue",
    "ReportingTool",
    "Tool",
    "ToolResult",
    "describe",
    "reporting_tool",
    "tool",
]

_SCALARS: Final[Mapping[object, tuple[str, str]]] = MappingProxyType(
    {
        str: ("string", "a string"),
        bool: ("boolean", "true or false"),
        int: ("integer", "a whole number"),
        float: ("number", "a finite number"),
    }
)

_SUPPORTED: Final = (
    "a payload field is a str, a bool, an int, a float, another payload dataclass, a `list[X]` or "
    "`tuple[X, ...]` of any of those, or `X | None`"
)

_SHOWN: Final = 80

_METADATA_KEY: Final = "agl.sdk.tools"

@dataclass(frozen=True, slots=True)
class ReportingTool[P]:
    name: str

    description: str

    payload: type[P]

    payload_schema: Mapping[str, JsonValue] = field(init=False)

    def __post_init__(self) -> None:
        check_tool_declaration(self.name, self.description)
        _check_payload(self.payload, self.name)
        object.__setattr__(
            self, "payload_schema", MappingProxyType(_object_schema(self.payload, self.name, ()))
        )

    def rejection(self, payload: Mapping[str, JsonValue]) -> str | None:
        """Say what is wrong with a payload the agent sent, so it can send another one this turn.

        :param payload: the arguments as the model filled them in; nothing is recorded either way
        :return: every problem at once, each with its path inside the payload, or `None` if it fits
        """
        _, problems = self._read(payload)
        return None if not problems else _refusal(self.name, problems)

    def read(self, value: object) -> P:
        """Build the payload dataclass out of a value AGL itself recorded, fresh run or replay.

        :param value: `object` because on a replay this came off the ledger as parsed JSON
        :return: the instance `Run.step` hands back, at the type the role declared
        :raises InternalError: the ledger and this payload type have come apart; nobody typed this
        """
        instance, problems = self._read(value)
        if instance is None:
            raise InternalError(
                f"a recorded {self.name} payload does not fit {named(self.payload)}: "
                f"{_refusal(self.name, problems)}. AGL wrote this value and AGL is reading it, so "
                f"the ledger and the payload type have come apart - the fingerprint should have "
                f"discarded this entry. It covers a tool's name, description and derived schema, "
                f"so a payload rule enforced only in `__post_init__` changes what converts while "
                f"moving no digest: `tests/sdk/test_tools.py` is where that hole is pinned"
            )
        return instance

    def _read(self, value: object) -> tuple[P | None, tuple[str, ...]]:
        problems: list[str] = []
        built = _instance(self.payload, value, self.name, problems)
        if not isinstance(built, self.payload):
            return None, tuple(problems)
        return built, ()

def reporting_tool[P](name: str, description: str, payload: type[P]) -> ReportingTool[P]:
    """Declare the tool a step reports its result through; without one a step's result is `None`.

    :param name: what the agent calls it; a fingerprint term, and unique among the role's tools
    :param description: what the agent reads to decide to call it; a fingerprint term as well
    :param payload: dataclass the result is read back as; its derived schema is a fingerprint term
    :return: a declaration to put on a role, which may carry one reporting tool at most
    :raises InputError: at declaration time - an empty string, or a payload shape JSON refuses
    """
    return ReportingTool(name=name, description=description, payload=payload)

def tool[P](
    name: str,
    description: str,
    payload: type[P],
    handler: Callable[[P], Awaitable[ToolResult]],
) -> Tool:
    """Build a tool an agent can call, validating its payload before the handler sees it.

    :param name: what the agent calls it; must be unique within a role
    :param description: what the agent is told the tool is for
    :param payload: dataclass the arguments are built into; its schema is a fingerprint term
    :param handler: awaited with the built payload once the agent calls the tool
    :return: a tool ready to go on a role
    """
    _check_payload(payload, name)
    schema = _object_schema(payload, name, ())

    async def _called(sent: Mapping[str, JsonValue]) -> ToolResult:
        problems: list[str] = []
        built = _instance(payload, sent, name, problems)
        if not isinstance(built, payload):
            return ToolResult(text=_refusal(name, tuple(problems)), rejected=True)
        return await handler(built)

    return Tool(name=name, description=description, payload_schema=schema, handler=_called)

@overload
def describe[T](text: str, *, default: T) -> T: ...
@overload
def describe(text: str) -> Any: ...
def describe(text: str, *, default: Any = MISSING) -> Any:
    """Say what one payload field is for, in the schema the agent reads beside the field name.

    :param text: a fingerprint term - editing it re-runs every step reporting through this payload
    :param default: omitted makes the field required, exactly as `dataclasses.field` does
    :return: a `dataclasses.field` carrying the description, assigned to the annotated field
    :raises InputError: `text` is empty or only whitespace, refused where the field is declared
    """
    if not text.strip():
        raise InputError(
            f"a field was described with {text!r}, and a description is what the model reads "
            f"beside the field name to know what belongs in it. Give it a sentence or leave the "
            f"field undescribed - an empty one is a term in every digest this payload writes and "
            f"is nothing at all to the model"
        )
    described = {_METADATA_KEY: text}
    if default is MISSING:
        return field(metadata=described)
    return field(default=default, metadata=described)

def _object_schema(
    kind: type[Any], where: str, inside: tuple[type[Any], ...]
) -> dict[str, JsonValue]:
    if kind in inside:
        raise InputError(
            f"{where} is {named(kind)}, which is already being derived - a payload dataclass "
            f"that contains itself has no finite schema, and a model has no way to know when to "
            f"stop nesting one"
        )
    hints = annotations_of(kind)
    nested = (*inside, kind)
    properties: dict[str, JsonValue] = {}
    required: list[JsonValue] = []
    for spec in fields(kind):
        schema = _schema_for(hints.get(spec.name), _at(where, spec.name), nested)
        described = _description(spec)
        if described is not None:
            schema["description"] = described
        properties[spec.name] = schema
        if _required(spec.default, spec.default_factory):
            required.append(spec.name)
    return {
        "type": "object",
        "title": f"{kind.__module__}.{kind.__qualname__}",
        "properties": properties,
        "required": sorted(required, key=str),
        "additionalProperties": False,
    }

def _schema_for(hint: object, where: str, inside: tuple[type[Any], ...]) -> dict[str, JsonValue]:
    optional = _optional(hint)
    if optional is not None:
        return {"anyOf": [_schema_for(optional, where, inside), {"type": "null"}]}
    scalar = _SCALARS.get(hint)
    if scalar is not None:
        return {"type": scalar[0]}
    item = _item(hint)
    if item is not None:
        return {"type": "array", "items": _schema_for(item, f"{where}[]", inside)}
    if isinstance(hint, type) and is_dataclass(hint):
        return _object_schema(hint, where, inside)
    raise InputError(
        f"{where} is a {named(hint)}, which a tool payload cannot carry: {_SUPPORTED}. A "
        f"payload is filled in as JSON by the model and converted back into this dataclass, and "
        f"where it is also a step's result it is stored and read back the same way, so a field "
        f"type that does not survive JSON unchanged is one nothing could return"
    )

def _instance(kind: type[Any], value: object, where: str, problems: list[str]) -> object:
    before = len(problems)
    given = _given(kind, value, where, problems)
    if len(problems) != before:
        return None
    factory: Callable[..., object] = kind
    try:
        return factory(**given)
    except Exception as raised:
        problems.append(f"`{where}` is not a valid {named(kind)}: {raised}")
        return None

def _given(kind: type[Any], value: object, where: str, problems: list[str]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        problems.append(f"`{where}` should be an object and {_shown(value)} arrived")
        return {}
    hints = annotations_of(kind)
    declared = {spec.name: spec for spec in fields(kind)}
    for key in value:
        if key not in declared:
            problems.append(
                f"`{_at(where, key)}` is not one of this payload's fields. They are: "
                f"{', '.join(declared) or '(none)'}"
            )
    given: dict[str, object] = {}
    for name, spec in declared.items():
        hint, at = hints.get(name), _at(where, name)
        if name in value:
            given[name] = _converted(hint, value[name], at, problems)
        elif _required(spec.default, spec.default_factory):
            problems.append(f"`{at}` is missing, and it is required: {_wording(hint)}")
    return given

def _converted(hint: object, value: object, where: str, problems: list[str]) -> object:
    optional = _optional(hint)
    if optional is not None:
        return None if value is None else _converted(optional, value, where, problems)
    if hint in _SCALARS:
        return _scalar(hint, value, where, problems)
    item = _item(hint)
    if item is not None:
        if not isinstance(value, list):
            _note_wrong(hint, value, where, problems)
            return None
        built = [
            _converted(item, element, f"{where}[{index}]", problems)
            for index, element in enumerate(value)
        ]
        return tuple(built) if get_origin(hint) is tuple else built
    if isinstance(hint, type) and is_dataclass(hint):
        return _instance(hint, value, where, problems)
    _note_wrong(hint, value, where, problems)
    return None

def _scalar(hint: object, value: object, where: str, problems: list[str]) -> object:
    if hint is str and isinstance(value, str):
        return value
    if hint is bool and isinstance(value, bool):
        return value
    if hint is int and isinstance(value, int) and not isinstance(value, bool):
        return value
    if (
        hint is float
        and isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(value)
    ):
        return float(value)
    _note_wrong(hint, value, where, problems)
    return None

def _note_wrong(hint: object, value: object, where: str, problems: list[str]) -> None:
    problems.append(f"`{where}` should be {_wording(hint)} and {_shown(value)} arrived")

def _wording(hint: object) -> str:
    optional = _optional(hint)
    if optional is not None:
        return f"{_wording(optional)} or null"
    scalar = _SCALARS.get(hint)
    if scalar is not None:
        return scalar[1]
    item = _item(hint)
    if item is not None:
        return f"an array of {_wording(item)}"
    if isinstance(hint, type) and is_dataclass(hint):
        return f"an object with the fields of {hint.__qualname__}"
    return f"a {named(hint)}, which is not a payload type at all"

def _optional(hint: object) -> object | None:
    # `Optional[X]` and `X | None` are one type as of 3.14, so `UnionType` covers both spellings.
    if get_origin(hint) is not UnionType:
        return None
    args: tuple[object, ...] = get_args(hint)
    real = [arg for arg in args if arg is not type(None)]
    return real[0] if len(args) == 2 and len(real) == 1 else None

def _item(hint: object) -> object | None:
    origin = get_origin(hint)
    args: tuple[object, ...] = get_args(hint)
    if origin is list and len(args) == 1:
        return args[0]
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        return args[0]
    return None

def _check_payload(payload: object, name: str) -> None:
    if isinstance(payload, type) and is_dataclass(payload):
        return
    raise InputError(
        f"the tool {name!r} was declared with {named(payload)}, and a payload is a "
        f"dataclass - the class itself, never an instance of it. Its fields are what the "
        f"schema is derived from and what the agent is asked to fill in"
    )

def _refusal(name: str, problems: tuple[str, ...]) -> str:
    listed = "\n".join(f"  - {problem}" for problem in problems)
    return (
        f"{name} was not given a payload it can accept, and nothing has been recorded. Fix all of "
        f"these and call it again:\n{listed}"
    )

def _required(default: object, factory: object) -> bool:
    return default is MISSING and factory is MISSING

def _description(spec: Field[Any]) -> str | None:
    held = spec.metadata.get(_METADATA_KEY)
    return held if isinstance(held, str) else None

def _at(where: str, name: object) -> str:
    return f"{where}.{name}"

def _shown(value: object) -> str:
    text = repr(value)
    return text if len(text) <= _SHOWN else f"{text[:_SHOWN]}..."
