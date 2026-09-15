"""A workflow module whose two role factories name one model at two different efforts.

Readiness is a property of the model and not of the level it reasons at, and the Claude harness's
`check_ready` spends a turn, so a preflight that de-duplicated on the whole choice would buy one
turn per level an author wrote before a line of work had been done. The claim is a count over a
namespace holding no second model, which `tests/sdk/test_preflight.py`'s own cannot be.

Both roles are stepped, so the dispatch can be asked what reached the adapter: the whole choice,
level included, on each task - the one question about readiness is asked of the bare model alone.
"""

from agl.sdk import Claude, ClaudeEffort, Role, Run, role, workflow
from instruments.preflight import NoParams, entered

__all__ = ["deliberate", "efforts", "hurried"]

@role(model=Claude.OPUS(effort=ClaudeEffort.XHIGH))
def deliberate() -> Role:
    """The model at one level."""
    return Role(name="deliberate", instructions="think it through")

@role(model=Claude.OPUS(effort=ClaudeEffort.LOW))
def hurried() -> Role:
    """The same model at another level, which is no second question about whether it is ready."""
    return Role(name="hurried", instructions="answer at once")

@workflow
async def efforts(run: Run[NoParams]) -> None:
    """Steps with both roles, so both choices reach the adapter behind one readiness question."""
    entered.append("efforts")
    await run.step(deliberate())
    await run.step(hurried())
