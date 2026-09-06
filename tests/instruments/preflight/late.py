"""A workflow module whose only role factory is written *below* the workflow function.

Which is legal, ordinary, and the reason the namespace is read at preflight rather than snapshotted
at decoration. A module executes top to bottom, so `latecomer` is not bound to anything at the
moment `@workflow` runs on the function above it: a decoration-time scan would find an empty
namespace here, the run would pass preflight naming no model at all, and the first step would reach
a backend nobody had asked about. Reading `vars(sys.modules[...])` at second zero reads the module
after it is whole.

The model is `Claude.HAIKU` because no other module this suite drives names it, so a `check_ready`
for it can only have come from the declaration below.
"""

from agl.sdk import Claude, Role, Run, role, workflow
from instruments.preflight import NoParams, entered

__all__ = ["late", "latecomer"]

@workflow
async def late(run: Run[NoParams]) -> None:
    """Declared above the only role factory in its module, and preflight finds it anyway."""
    entered.append("late")

@role(model=Claude.HAIKU)
def latecomer() -> Role:
    """The factory the decorator above could not have seen, since it was not bound yet."""
    return Role(name="late", instructions="do the late work")
