"""A workflow module naming two models of one provider and one of another, one of them at an effort.

Two claims need that shape and neither can be made inside a namespace holding one model per
provider. **The installation probe is asked once per provider**, where readiness is asked once per
model: a backend's `installation` describes the tool it starts rather than the model it was handed,
so a second model on one provider would re-read one binary - and reading it is a subprocess on both
real adapters. Three models over two providers is the smallest namespace where the two counts
differ, and it is why `planner` and `editor` share a provider.

**And a role names a level its model may not have.** `editor` asks for the one level the vendor
CLI 0.152.0 lists for every model it carries except `gpt-5.6-luna`, which is the real case the
warning was written for: nothing refuses it, the tool lowers it, and what the run is owed is a line
saying so before it starts. The effort is on the *declaration* rather than passed at the step,
because that is where preflight can read it without calling anything.

`OpenAI.SOL`, `OpenAI.LUNA` and `Claude.OPUS`, because `Claude.HAIKU`, `Claude.SONNET` and
`OpenAI.TERRA` are each reserved to one module here for a claim that needs them named nowhere else.
"""

from agl.sdk import Claude, OpenAI, OpenAIEffort, Role, Run, role, workflow
from instruments.preflight import NoParams, entered

__all__ = ["broad", "editor", "planner", "reviewer"]

@role(model=OpenAI.SOL)
def planner() -> Role:
    """One of the provider's two models, named bare, so nothing about it names a level."""
    return Role(name="plan", instructions="plan it")

@role(model=OpenAI.LUNA(effort=OpenAIEffort.ULTRA))
def editor() -> Role:
    """The provider's other model, at the level a catalogue may not list for it."""
    return Role(name="edit", instructions="edit it")

@role(model=Claude.OPUS)
def reviewer() -> Role:
    """The second provider, so the two counts this module is about are two and three."""
    return Role(name="review", instructions="review it")

@workflow
async def broad(run: Run[NoParams]) -> None:
    """Steps with the role whose level is in question: a warning is never a refusal in disguise."""
    entered.append("broad")
    await run.step(editor())
