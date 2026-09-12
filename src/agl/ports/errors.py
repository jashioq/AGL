from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = [
    "EXIT_CODES",
    "AglError",
    "ConflictError",
    "DeniedError",
    "DisagreeingRefusals",
    "InputError",
    "InternalError",
    "NotFoundError",
    "Stop",
    "UpstreamError",
    "UpstreamUnavailable",
    "UpstreamUnexpected",
    "exit_code_for",
]

class AglError(Exception):
    """The base of AGL's own errors: an adapter translates whatever it caught into one of these."""

class InputError(AglError):
    """What AGL was given cannot be used: the value has to change before the call can succeed."""

class NotFoundError(AglError):
    """What was named is not there: name something that exists, or make it before asking for it."""

class ConflictError(AglError):
    """What is there already disagrees with the call: AGL refuses rather than write over it."""

class DeniedError(AglError):
    """A refusal that stands until something changes, so a retry alone is refused the same way."""

class UpstreamError(AglError):
    """Whatever failed beyond a port: a subclass says whether the far side may answer later."""

class UpstreamUnavailable(UpstreamError):
    """A state of the world and not a fault in the call: the same call may get past it later."""

class UpstreamUnexpected(UpstreamError):
    """The far side answered in terms the adapter cannot read, which no retry of the call fixes."""

class Stop(AglError):
    """A workflow ending its own run: subclass it freely, the exit code resolves up the tree."""

class DisagreeingRefusals(AglError):
    """Named outcomes whose codes differ, so no one code is the answer: read the reason for each."""

class InternalError(AglError):
    """An invariant of AGL's own broke, so the fault is here and not in anything a caller wrote."""

EXIT_CODES: Final[Mapping[type[AglError], int]] = MappingProxyType(
    {
        InputError: 2,
        NotFoundError: 3,
        ConflictError: 4,
        DeniedError: 5,
        UpstreamError: 6,
        Stop: 7,
        DisagreeingRefusals: 8,
        InternalError: 70,
    }
)

def exit_code_for(error: AglError | type[AglError]) -> int:
    """The process exit code for an error, resolved through the class tree rather than by lookup.

    :param error: an instance or a class; a workflow's own `Stop` subclass need be in no table
    :return: the nearest mapped ancestor's code, and `InternalError`'s where nothing maps
    """
    cls = error if isinstance(error, type) else type(error)
    for ancestor in cls.__mro__:
        code = EXIT_CODES.get(ancestor)
        if code is not None:
            return code
    return EXIT_CODES[InternalError]
