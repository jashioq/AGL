
import asyncio
from collections.abc import Mapping
from typing import Final, cast

from agl.ports.agent import AgentOutcome, AgentTask, StopReason, Tool, ToolResult
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import Fingerprints, Journal, canonical_json
from agl.sdk._engine.preflight import Capabilities
from agl.sdk._engine.services import Services
from agl.sdk.roles import Role, RoleIncompleteError
from agl.sdk.tools import ReportingTool

__all__ = ["Steps"]

_INPUTS_HEADING: Final = "## Inputs"


class Steps:

    def __init__(
        self,
        services: Services,
        scope: RunScope,
        base: str,
        fingerprints: Fingerprints,
        capabilities: Capabilities,
    ) -> None:
        self._services = services
        self._scope = scope
        self._base = base
        self._fingerprints = fingerprints
        self._capabilities = capabilities
        self._opened: tuple[Journal, Workspace] | None = None
        self._opening = asyncio.Lock()
        self._activity: str | None = None

    @property
    def activity(self) -> str | None:
        return self._activity

    @property
    def last_good(self) -> str:
        return self._base if self._opened is None else self._opened[0].last_good

    async def landing(self) -> tuple[Journal, Workspace]:
        return await self._namespace()

    def _reported(self, line: str) -> None:
        self._activity = line

    async def step[R](
        self, role: Role[R], *, commit: str | None, inputs: Mapping[str, object]
    ) -> R:
        step = StepName(role.name)
        await self._capabilities.require(self._services.agents, role, step=str(step))
        journal, workspace = await self._namespace()

        capture: _Capture[R] | None = None
        tools: list[Tool] = []
        for declared in role.tools:
            if isinstance(declared, ReportingTool):
                capture = _Capture(declared)
                tools.append(capture.tool)
            else:
                tools.append(declared)
        offered = tuple(tools)

        async def _worker() -> JsonValue:
            try:
                outcome = await self._services.agents.run(
                    AgentTask(
                        instructions=_composed(role.instructions, inputs),
                        workspace=workspace.path,
                        model=role.model,
                        restrictions=frozenset(role.restrictions),
                        tools=offered,
                    ),
                    on_activity=self._reported,
                )
            finally:
                self._activity = None
            return None if capture is None else capture.reported(outcome)

        value = await journal.step(
            step,
            instructions=role.instructions,
            model=role.model,
            restrictions=role.restrictions,
            tools=offered,
            inputs=inputs,
            worker=_worker,
            commit=commit,
        )
        if capture is None:
            return cast(R, None)
        return capture.read(value)

    async def _namespace(self) -> tuple[Journal, Workspace]:
        if self._opened is not None:
            return self._opened
        async with self._opening:
            if self._opened is None:
                base = await self._services.history.resolve(self._base)
                workspace = await self._services.workspaces.open(
                    self._scope.label, _namespace_of(self._scope), base
                )
                self._opened = (
                    Journal(
                        self._services.store,
                        self._scope,
                        workspace,
                        self._services.clock,
                        self._fingerprints,
                        base,
                    ),
                    workspace,
                )
            return self._opened


class _Capture[P]:

    def __init__(self, declaration: ReportingTool[P]) -> None:
        self._declaration = declaration
        self._payload: dict[str, JsonValue] | None = None
        self.tool = Tool(
            name=declaration.name,
            description=declaration.description,
            payload_schema=declaration.payload_schema,
            handler=self._called,
        )

    async def _called(self, payload: Mapping[str, JsonValue]) -> ToolResult:
        if self._payload is not None:
            return ToolResult(
                text=(
                    f"{self._declaration.name} has already recorded this step's result: it records "
                    f"one payload per run, and the first one stands. This call changed nothing."
                ),
                rejected=True,
            )
        rejection = self._declaration.rejection(payload)
        if rejection is not None:
            return ToolResult(text=rejection, rejected=True)
        self._payload = dict(payload)
        return ToolResult(
            text=(
                f"{self._declaration.name} recorded this step's result. Nothing further is needed "
                f"from this tool."
            )
        )

    def reported(self, outcome: AgentOutcome) -> JsonValue:
        if self._payload is None:
            raise RoleIncompleteError(_unreported(self._declaration.name, outcome))
        return self._payload

    def read(self, value: object) -> P:
        return self._declaration.read(value)


def _composed(instructions: str, inputs: Mapping[str, object]) -> str:
    if not inputs:
        return instructions
    return "\n\n".join((instructions, _INPUTS_HEADING, canonical_json(inputs)))


def _namespace_of(scope: RunScope) -> Namespace | None:
    return scope.namespaces[-1] if scope.namespaces else None


def _unreported(tool: str, outcome: AgentOutcome) -> str:
    return (
        f"the agent finished without ever calling {tool!r}, so this step produced no result: "
        f"nothing was recorded and it will run again on the next attempt. {_because(outcome)} It "
        f"said this instead of reporting: {outcome.text!r}"
    )


def _because(outcome: AgentOutcome) -> str:
    if outcome.stop_reason is StopReason.LIMIT:
        return (
            "The backend stopped it against its will - turns, tokens, time or budget - so it may "
            "simply have run out of room before it reported: raise the limit."
        )
    if outcome.stop_reason is StopReason.COMPLETED:
        return (
            "It ended its own turn, having decided it was finished, so the limit is not what it "
            "reached: the prompt is what did not read as asking for a report through that tool."
        )
    return (
        "The backend did not say why it stopped, so neither a limit it reached nor a prompt that "
        "never asked for the report can be ruled out from here."
    )
