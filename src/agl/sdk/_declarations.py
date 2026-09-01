from collections.abc import Mapping
from typing import get_type_hints
from agl.ports.errors import InputError

__all__ = ["annotations_of", "named"]

def annotations_of(kind: type[object]) -> Mapping[str, object]:
    try:
        return get_type_hints(kind)
    except (NameError, TypeError) as error:
        raise InputError(
            f"{named(kind)} has an annotation that cannot be resolved: {error}. Its fields are "
            f"read for their types, so each has to name something importable where it is"
        ) from error

def named(thing: object) -> str:
    if not isinstance(thing, type):
        return repr(thing)
    return f"{thing.__module__}.{thing.__qualname__}"
