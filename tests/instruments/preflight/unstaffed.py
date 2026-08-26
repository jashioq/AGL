"""A workflow module with no role factory in it at all - `workflows/noop/`'s shape.

The whole content of this file is an *absence*: nothing here is decorated with `@role`, and nothing
here imports something that is, so `vars(sys.modules[__name__])` holds no `RoleFactory` and
preflight asks no backend anything. That is what keeps a workflow which runs no agent runnable on a
machine with nothing installed, and it is the case that cannot be asserted from
`tests/sdk/test_preflight.py`, whose own namespace holds six factories over two models.

Not merely "it does not fail". A preflight that asked about some default model, or about every
provider the bundle was assembled with, would make such a run depend on a harness the workflow never
named - which is exactly what `workflows/noop/` existed to disprove until 19.1 deleted it, and the
argument outlived the package.
"""

from agl.sdk import Run, workflow
from instruments.preflight import NoParams, entered

__all__ = ["unstaffed"]


@workflow(name="unstaffed", version="1.1", params=NoParams)
async def unstaffed(run: Run[NoParams]) -> None:
    """Runs on a machine where no harness is installed, because its module names no model."""
    entered.append("unstaffed")
