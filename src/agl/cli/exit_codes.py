from collections.abc import Iterator, Set
from agl.ports.errors import EXIT_CODES, AglError, DisagreeingRefusals, InternalError, exit_code_for

__all__ = ["EXIT_CODES", "exit_code_for", "exit_status", "joint_status", "leaves"]

def exit_status(error: Exception) -> int:
    # `BaseExceptionGroup` refuses an empty sequence at construction, so this set cannot be empty.
    return joint_status({_resolved(leaf) for leaf in leaves(error)})

# `InternalError`'s code is not one answer among the others: it says AGL had no name for what one
# of them raised, which `DisagreeingRefusals`' would hide by saying every one of them was named.
# ARCHITECTURE.md's "Errors at the boundary" argues why no other code is preferred to another.
def joint_status(codes: Set[int]) -> int:
    unnamed = exit_code_for(InternalError)
    if unnamed in codes:
        return unnamed
    agreed, *disagreeing = codes
    return exit_code_for(DisagreeingRefusals) if disagreeing else agreed

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
