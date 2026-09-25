import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Final, cast
from agl.ports.agent import AgentOutcome, AgentTask, StopReason, Tool, ToolResult
from agl.ports.errors import InputError
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue
from agl.ports.verifier import VerifierOutcome
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import Fingerprints, Journal
from agl.sdk._engine.preflight import Capabilities, checked_inputs
from agl.sdk._engine.prompts import composed
from agl.sdk._engine.services import Services
from agl.sdk.roles import Role, RoleIncompleteError
from agl.sdk.tools import ReportingTool

__all__ = ["Steps"]

# What git's cleanup strips from a message, and nothing else: "\v" or "\xa0" alone it records.
_CLEANED_AWAY: Final = " \t\r\n"

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

    @property
    def last_good(self) -> str:
        return self._base if self._opened is None else self._opened[0].last_good

    async def landing(self) -> tuple[Journal, Workspace]:
        return await self._namespace()

    # No restore: on a resume the checkout can be past the replayed head, and a restore loses that.
    async def verify(self, command: str) -> VerifierOutcome:
        if not isinstance(command, str):
            raise InputError(_not_a_command(command))
        journal, workspace = await self._namespace()

        async def _worker() -> VerifierOutcome:
            return await self._services.verifier.verify(command, workspace.path)

        return await journal.verify(command, _worker)

    async def step[R](
        self, role: Role[R], passed: Sequence[object], *, commit: str | None
    ) -> R:
        step = StepName(role.name)
        inputs = checked_inputs(role, passed, step=str(step))
        if commit is not None and not isinstance(commit, str):
            raise InputError(_non_str_commit(str(step), commit))
        if isinstance(commit, str) and not commit.strip(_CLEANED_AWAY):
            raise InputError(_blank_commit(str(step)))
        await self._capabilities.require(self._services.agents, role, step=str(step))
        journal, workspace = await self._namespace()

        capture: _Capture[R] | None = None
        tools: list[Tool] = []
        for declared in role.tools:
            if isinstance(declared, ReportingTool):
                capture = _Capture(str(step), declared)
                tools.append(capture.tool)
            else:
                tools.append(declared)
        offered = tuple(tools)
        prompt = composed(role.instructions, inputs)

        async def _worker() -> JsonValue:
            outcome = await self._services.agents.run(
                AgentTask(
                    instructions=prompt,
                    workspace=workspace.path,
                    model=role.model,
                    restrictions=frozenset(role.restrictions),
                    tools=offered,
                ),
                on_activity=role.on_activity,
            )
            if capture is not None:
                return capture.reported(outcome)
            if outcome.stop_reason is StopReason.LIMIT:
                raise RoleIncompleteError(_curtailed(str(step), outcome))
            return None

        value = await journal.step(
            step,
            instructions=role.instructions,
            model=role.model,
            restrictions=role.restrictions,
            tools=offered,
            inputs=inputs,
            prompt=prompt,
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
                        self._services.history,
                        self._services.clock,
                        self._fingerprints,
                        base,
                    ),
                    workspace,
                )
            return self._opened

class _Capture[P]:
    def __init__(self, step: str, declaration: ReportingTool[P]) -> None:
        self._step = step
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
            raise RoleIncompleteError(_unreported(self._step, self._declaration.name, outcome))
        return self._payload

    def read(self, value: object) -> P:
        return self._declaration.read(value)

def _namespace_of(scope: RunScope) -> Namespace | None:
    return scope.namespaces[-1] if scope.namespaces else None

def _not_a_command(command: object) -> str:
    return (
        f'The command passed to `run.verify` is of type "{type(command).__name__}", not "str", so '
        'it ran nothing and opened no checkout. Pass a string, such as `run.config["build"]`.'
    )

def _non_str_commit(step: str, commit: object) -> str:
    return (
        f'Step "{step}" has a commit message of type "{type(commit).__name__}", not "str". Pass a '
        "string to `commit=`."
    )

def _blank_commit(step: str) -> str:
    return (
        f'Step "{step}" has a commit message that is empty or only spaces, tabs and line breaks, '
        "which git refuses. Write a message for `commit=`."
    )

def _unreported(step: str, tool: str, outcome: AgentOutcome) -> str:
    return (
        f'Step "{step}" recorded nothing and runs again on the next attempt, because its agent '
        f'stopped without calling "{tool}" after saying {_quoted(outcome.text)}. '
        f"{_because(outcome, tool)}"
    )

def _curtailed(step: str, outcome: AgentOutcome) -> str:
    return (
        f'Step "{step}" recorded nothing and runs again on the next attempt, because its agent was '
        "stopped by the backend at a turn, token, time or budget limit after saying "
        f"{_quoted(outcome.text)}. Its role has no reporting tool for saying it finished, so raise "
        "the limit, or give the role one."
    )

def _because(outcome: AgentOutcome, tool: str) -> str:
    if outcome.stop_reason is StopReason.LIMIT:
        return "The backend stopped it at a turn, token, time or budget limit, so raise the limit."
    if outcome.stop_reason is StopReason.COMPLETED:
        return (
            f'The agent ended its own turn, so ask for the report through "{tool}" in the prompt.'
        )
    return (
        "The backend did not say why it stopped, so raise the limit, or ask for the report "
        f'through "{tool}" in the prompt.'
    )

# An agent's closing message can run to paragraphs, which `json.dumps` escapes onto one line.
def _quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)
