"""One role factory and the `Role` it builds at import, so a workflow can bind the value alone.

`prebuilt.py` is the other half and this file has no independent claim. Of the four ways a module
can end up holding a built role, three leave something in the workflow's own namespace for the scan
to find - `@role` written beside the binding, `from .roles import implementer` and then a call, and
`from . import roles` - and only `from .prebuilt_roles import IMPLEMENTER` leaves a `Role` and
nothing else. That is the one this pair exists to hold still, so the factory has to be over here.

`Claude.SONNET` is named by no other module `tests/sdk/test_preflight.py` drives, so a `check_ready`
for it could only have come from this declaration - which is what lets the test next door assert
that none was asked.
"""

from typing import Final
from agl.sdk import Claude, Role, role

__all__ = ["IMPLEMENTER", "implementer"]

@role(model=Claude.SONNET)
def implementer() -> Role:
    """The declaration preflight would have read, in a module the workflow next door never binds."""
    return Role(name="implement", instructions="implement it")

IMPLEMENTER: Final = implementer()
"""Carries a model, unlike a hand-built `Role`: this one went through the factory above."""
