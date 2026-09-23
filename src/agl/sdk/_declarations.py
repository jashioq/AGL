from annotationlib import type_repr
from collections.abc import Iterator, Mapping
from types import FunctionType, NoneType, UnionType
from typing import Final, TypeAliasType, get_args, get_origin, get_type_hints
from agl.ports.errors import InputError

__all__ = ["annotations_of", "named"]

_PACKAGE: Final = "agl"

_DOOR: Final = "agl.sdk"

# What `agl.sdk` exports, by where each name is defined. That package imports every module calling
# `named`, and `tests/sdk/test_front_door.py` forbids the reverse, so the names are written out here
# and `tests/sdk/test_declarations.py` holds them to the package.
_EXPORTED: Final = frozenset(
    {
        "agl.ports.agent.ActivityReporter", "agl.ports.agent.Capability", "agl.ports.agent.Claude",
        "agl.ports.agent.ClaudeEffort", "agl.ports.agent.ModelId", "agl.ports.agent.OpenAI",
        "agl.ports.agent.OpenAIEffort", "agl.ports.agent.Restriction", "agl.ports.agent.Tool",
        "agl.ports.agent.ToolResult", "agl.ports.errors.AglError", "agl.ports.errors.ConflictError",
        "agl.ports.errors.DeniedError", "agl.ports.errors.InputError",
        "agl.ports.errors.InternalError", "agl.ports.errors.NotFoundError", "agl.ports.errors.Stop",
        "agl.ports.errors.UpstreamError", "agl.ports.errors.UpstreamUnavailable",
        "agl.ports.errors.UpstreamUnexpected", "agl.ports.ids.Namespace",
        "agl.ports.integration.Conflict", "agl.ports.integration.Integration",
        "agl.ports.run.JsonValue", "agl.ports.terminal.Choice", "agl.ports.terminal.Component",
        "agl.ports.terminal.Response", "agl.ports.terminal.Row", "agl.ports.terminal.Rows",
        "agl.ports.terminal.Screen", "agl.ports.terminal.Terminal", "agl.ports.terminal.Text",
        "agl.ports.terminal.TextInput", "agl.ports.verifier.VerifierOutcome",
        "agl.sdk._workflow.Run", "agl.sdk._workflow.Workflow", "agl.sdk._workflow.workflow",
        "agl.sdk.params.arg", "agl.sdk.roles.Role", "agl.sdk.roles.RoleFactory",
        "agl.sdk.roles.RoleIncompleteError", "agl.sdk.roles.prompt_file", "agl.sdk.roles.role",
        "agl.sdk.tools.ReportingTool", "agl.sdk.tools.describe", "agl.sdk.tools.reporting_tool",
        "agl.sdk.tools.tool",
    }
)

_UNEXPORTED: Final = "a type `agl.sdk` does not export"

def annotations_of(kind: type[object]) -> Mapping[str, object]:
    try:
        return get_type_hints(kind)
    except (NameError, TypeError) as error:
        raise InputError(
            f"{named(kind)} has an annotation that cannot be resolved: {error}. Its fields are "
            f"read for their types, so each has to name something importable where it is"
        ) from error

def named(thing: object) -> str:
    """How a refusal names `thing`: a whole noun phrase, so no article goes in front of it."""
    parts = tuple(_parts(thing))
    if any(_unexported(part) for part in parts):
        return _UNEXPORTED
    if any(_public(part) is not None for part in parts):
        return _spelled(thing)
    if isinstance(thing, type):
        return f"{thing.__module__}.{thing.__qualname__}"
    return repr(thing)

def _parts(thing: object) -> Iterator[object]:
    yield thing
    for inside in (get_origin(thing), *get_args(thing)):
        for part in inside if isinstance(inside, list) else (inside,):
            if part is not None:
                yield from _parts(part)

def _public(part: object) -> str | None:
    if not isinstance(part, type | TypeAliasType | FunctionType):
        return None
    if f"{part.__module__}.{part.__name__}" not in _EXPORTED:
        return None
    return f"{_DOOR}.{part.__name__}"

def _unexported(part: object) -> bool:
    if not isinstance(part, type | TypeAliasType) or _public(part) is not None:
        return False
    module = part.__module__
    return module is not None and module.partition(".")[0] == _PACKAGE

def _spelled(part: object) -> str:
    public = _public(part)
    if public is not None:
        return public
    if isinstance(part, list):
        return f"[{', '.join(_spelled(each) for each in part)}]"
    args = get_args(part)
    if get_origin(part) is UnionType:
        return " | ".join(_spelled(arg) for arg in args)
    if args:
        return f"{_spelled(get_origin(part))}[{', '.join(_spelled(arg) for arg in args)}]"
    return type_repr(None if part is NoneType else part)
