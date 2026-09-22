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
    """The base of every error AGL raises."""

class InputError(AglError):
    """A value given to AGL can't be used; change it and try again."""

class NotFoundError(AglError):
    """What was named doesn't exist; create it or name another."""

class ConflictError(AglError):
    """Something already there conflicts with the call; AGL won't overwrite it."""

class DeniedError(AglError):
    """AGL refuses the call; retrying won't work until something changes."""

class UpstreamError(AglError):
    """A tool or service AGL calls failed."""

class UpstreamUnavailable(UpstreamError):
    """A tool or service AGL calls is unavailable; retrying later may work."""

class UpstreamUnexpected(UpstreamError):
    """A tool or service AGL calls answered in a way AGL can't read; retrying won't help."""

class Stop(AglError):
    """Raise this, or a subclass of it, to end the run."""

class DisagreeingRefusals(AglError):
    """Named outcomes whose codes differ, so no one code is the answer: read the reason for each."""

class InternalError(AglError):
    """A bug in AGL itself, not in the workflow."""

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

    Args:
        error: an instance or a class; a workflow's own `Stop` subclass need be in no table

    Returns:
        the nearest mapped ancestor's code, and `InternalError`'s where nothing maps
    """
    cls = error if isinstance(error, type) else type(error)
    for ancestor in cls.__mro__:
        code = EXIT_CODES.get(ancestor)
        if code is not None:
            return code
    return EXIT_CODES[InternalError]
