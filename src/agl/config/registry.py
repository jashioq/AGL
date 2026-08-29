
from collections.abc import Iterable, Mapping
from importlib.metadata import EntryPoint, entry_points
from typing import Final

from agl.ports.errors import ConflictError, InputError, NotFoundError

__all__ = ["GROUP", "installed", "load", "names"]

GROUP: Final = "agl.workflows"


def installed() -> tuple[EntryPoint, ...]:
    return tuple(entry_points(group=GROUP))


def names(points: Iterable[EntryPoint]) -> tuple[str, ...]:
    return tuple(sorted(_index(points)))


def load[T](points: Iterable[EntryPoint], name: str, kind: type[T]) -> T:
    index = _index(points)
    point = index.get(name)
    if point is None:
        raise NotFoundError(_unknown(name, index))
    try:
        loaded = point.load()
    except (ImportError, AttributeError) as error:
        raise InputError(
            f"the workflow {name!r} is registered as {point.value!r}, and loading it failed: "
            f"{error}. That declaration is in the {GROUP} entry points of the package that "
            f"provides {name!r}, so the fix is in that package or in how it is installed - AGL "
            f"only read what it declared. The original error is chained below this one"
        ) from error
    if not isinstance(loaded, kind):
        raise InputError(
            f"the workflow {name!r} is registered as {point.value!r}, which loaded and turned "
            f"out to be a {_describe(type(loaded))} rather than a {_describe(kind)}. The "
            f"{GROUP} entry point of the package that provides {name!r} is pointing at the wrong "
            f"object - AGL only read what it declared"
        )
    return loaded


def _index(points: Iterable[EntryPoint]) -> Mapping[str, EntryPoint]:
    index: dict[str, EntryPoint] = {}
    for point in points:
        held = index.get(point.name)
        if held is not None:
            raise ConflictError(
                f"two installed packages both register a workflow named {point.name!r}, as "
                f"{held.value!r} and as {point.value!r}. AGL will not choose between them: running "
                f"the wrong one of two workflows that answer to the same name is a mistake nothing "
                f"downstream could report, so the name stays ambiguous until one of the two "
                f"packages is uninstalled"
            )
        index[point.name] = point
    return index


def _unknown(name: str, index: Mapping[str, EntryPoint]) -> str:
    registered = tuple(sorted(index))
    if not registered:
        return (
            f"there is no workflow named {name!r}, and in fact no workflow is installed at all: "
            f"the {GROUP} entry point group is empty in this environment. A workflow arrives as a "
            f"package that declares one entry point in that group; install one, then `agl "
            f"workflows` lists it"
        )
    return (
        f"there is no workflow named {name!r}. Installed and registered under {GROUP}: "
        f"{', '.join(registered)}. `agl workflows` prints the same list"
    )


def _describe(kind: type[object]) -> str:
    return f"{kind.__module__}.{kind.__qualname__}"
