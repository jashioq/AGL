"""A workflow module importing a role it never steps with: the stage's known cost, in one file.

`reviewer` is `fix`'s own OpenAI role. It is imported here, called by nothing, and the workflow
below takes no step at all - so the single reason a run of it demands a Codex CLI is the import line
above. That is a **false refusal**, and the stage records it as accepted rather than as a defect:
the registry is a namespace, which of a module's roles a run actually reaches is decided by the
workflow's body, and the body has not run when preflight asks. Erring toward refusing early is the
right direction, because the failure it replaces is silent and expensive where this one is loud and
one deleted import away from being fixed.

**The role is imported rather than declared here, and that is the whole shape of the case.** A
factory written in this file would over-approximate identically, but the thing somebody hitting
this has to find and delete is an *import*, and a test that declared its own role locally would
leave that line out of the measurement. `sdk/_engine/preflight.py`'s refusal names both modules for
the same reason.
"""

from agl.sdk import Run, workflow

# Imported and never called: the line this module exists to be about. `ruff` is told so explicitly,
# because an unused import is normally a defect and here it is the subject.
from agl.workflows.fix.roles import reviewer  # noqa: F401
from instruments.preflight import NoParams, entered

__all__ = ["unused"]


@workflow(version="1.1")
async def unused(run: Run[NoParams]) -> None:
    """Steps with nothing, and demands `reviewer`'s provider at second zero all the same."""
    entered.append("unused")
