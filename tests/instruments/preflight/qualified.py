"""A workflow module that reaches its role through a module: `from . import roles`.

The spelling a scan of the workflow's own namespace cannot see. Nothing here binds a `RoleFactory`
- the only name this module imports from next door is `roles`, a module - so a scan of
`vars(sys.modules[...])` alone finds no factory, asks **zero** backends anything, clears second
zero naming no provider, and lets the run die at its first step with whatever the adapter says.
That is the failure `AgentRunner.check_ready` in `src/agl/ports/agent.py` exists to prevent,
arriving with no warning, and `@workflow(roles=[...])` could not have had it because the list
named the roles.

It is a module of its own for `unused.py`'s reason: the claim is about a *namespace*, and
`tests/sdk/test_preflight.py`'s own holds six factories bound directly. A workflow written there
would pass the scan on those and measure nothing about this one.

The step is here rather than omitted, unlike `unstaffed` and `unused`, because the whole point is
that the role really is reached - `roles.implementer()` is what the body runs on, so a preflight
that never asked about `OpenAI.TERRA` admitted a run that was always going to need it.
"""

from agl.sdk import Run, workflow
from instruments.preflight import NoParams, entered

# The import this file exists to be about: a *module*, not a factory. `from .roles import
# implementer` would bind a `RoleFactory` in this namespace and measure the case that already
# worked.
from . import roles

__all__ = ["qualified"]


@workflow(version="1.1")
async def qualified(run: Run[NoParams]) -> None:
    """Steps with a role no scan of this namespace's own bindings could have found."""
    entered.append("qualified")
    await run.step(roles.implementer())
