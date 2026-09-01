from collections.abc import Mapping
from typing import Final
from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    ModelId,
    Provider,
)
from agl.ports.errors import InputError

__all__ = ["RoutingAgentRunner"]

class RoutingAgentRunner(AgentRunner):
    def __init__(self, runners: Mapping[Provider, AgentRunner]) -> None:
        if not runners:
            raise InputError(
                "a routing agent runner was built with no adapters at all, and one holding no "
                "adapter serves no model: every step of every workflow would fail at the step it "
                "reached, naming the provider it wanted, when the fact worth reporting is that "
                "this run was assembled with no agent backend. Configure at least one provider and "
                "install the harness it names"
            )
        self._runners: Final = dict(runners)

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        return await self._serving(model).capabilities(model)

    async def check_ready(self, model: ModelId) -> None:
        await self._serving(model).check_ready(model)

    async def run(
        self,
        task: AgentTask,
        *,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        return await self._serving(task.model).run(task, on_activity=on_activity)

    def _serving(self, model: ModelId) -> AgentRunner:
        provider = model.provider
        runner = self._runners.get(provider)
        if runner is None:
            held = sorted(str(member) for member in self._runners)
            raise InputError(
                f"nothing here can run {str(model)!r}: it is served by {str(provider)!r}, and this "
                f"run was assembled with an adapter for {held} and nothing else. A provider "
                f"arrives with an adapter, so either that provider is not configured or its "
                f"harness is not installed on this machine. No other model is substituted for this "
                f"one - the model was named beside the prompt because the choice was semantic, and "
                f"answering with a different one answers a different question than the one asked"
            )
        return runner
