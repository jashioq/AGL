"""One role factory in a module of its own, so a workflow can bind the *module* and not the name.

This file is the other half of `qualified.py` and has no independent claim. §3.3's shipped shape
puts a workflow's roles in a `roles.py` beside it - `workflows/fix/roles.py` is the instance - and
an author then reaches them by one of two imports: `from .roles import implementer`, which binds a
factory in the workflow's namespace, or `from . import roles`, which binds this module and nothing
else. UF1.5 is about the second, and the second needs a module to bind.

`OpenAI.TERRA` is named by no other module `tests/sdk/test_preflight.py` drives, so a `check_ready`
for it can only have come from here, reached through the module binding next door. `Claude.HAIKU`
is `late.py`'s for the same reason and the two must stay distinct.
"""

from agl.sdk import OpenAI, Role, role

__all__ = ["implementer"]


@role(model=OpenAI.TERRA)
def implementer() -> Role:
    """The factory a workflow reaches as `roles.implementer()` rather than as `implementer()`."""
    return Role(name="implement", instructions="implement it")
