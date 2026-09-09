"""A workflow module binding a `Role` that was already built, and no factory beside it.

`from .prebuilt_roles import IMPLEMENTER` binds one value: a `Role` carrying `Claude.SONNET`,
built while the module next door was imported. Preflight reads `@role(model=…)` *factories* out of
this namespace and out of any module bound in it, and there is neither here - so the scan finds
nothing, asks no backend anything, and the run steps on a model nobody probed.

That is this instrument's whole content, and it is a supported shape rather than the hole
`qualified.py` was: the scan is over declarations, a `Role` is what a declaration produces, and
`Capabilities.require` still runs at the step. `tests/sdk/test_preflight.py` holds the reasoning
and the assertions.
"""

from agl.sdk import Run, workflow
from instruments.preflight import NoParams, entered
# The import this file exists to be about: the built role and not the factory that built it.
# `from .prebuilt_roles import implementer` would bind a `RoleFactory` here and measure the case
# that already worked.
from .prebuilt_roles import IMPLEMENTER

__all__ = ["prebuilt"]

@workflow
async def prebuilt(run: Run[NoParams]) -> None:
    """Steps with a role its own module holds as a value rather than as a declaration."""
    entered.append("prebuilt")
    await run.step(IMPLEMENTER)
