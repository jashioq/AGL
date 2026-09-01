
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = [
    "EXIT_CODES",
    "AglError",
    "ConflictError",
    "DeniedError",
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
    ...


class InputError(AglError):
    ...


class NotFoundError(AglError):
    ...


class ConflictError(AglError):
    ...


class DeniedError(AglError):
    ...


class UpstreamError(AglError):
    ...


class UpstreamUnavailable(UpstreamError):
    ...


class UpstreamUnexpected(UpstreamError):
    ...


class Stop(AglError):
    ...


class InternalError(AglError):
    ...


EXIT_CODES: Final[Mapping[type[AglError], int]] = MappingProxyType(
    {
        InputError: 2,
        NotFoundError: 3,
        ConflictError: 4,
        DeniedError: 5,
        UpstreamError: 6,
        Stop: 7,
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
