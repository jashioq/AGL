
from collections.abc import Iterator

from agl.ports.errors import EXIT_CODES, AglError, InternalError, exit_code_for

__all__ = ["EXIT_CODES", "exit_code_for", "exit_status", "leaves"]


def exit_status(error: Exception) -> int:
    agreed, *disagreeing = {_resolved(leaf) for leaf in leaves(error)}
    return exit_code_for(InternalError) if disagreeing else agreed


def leaves(error: Exception) -> Iterator[Exception]:
    if not isinstance(error, ExceptionGroup):
        yield error
        return
    for held in error.exceptions:
        yield from leaves(held)


def _resolved(leaf: Exception) -> int:
    if isinstance(leaf, AglError):
        return exit_code_for(leaf)
    return exit_code_for(InternalError)
