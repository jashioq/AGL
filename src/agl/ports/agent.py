from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from agl.ports.errors import InputError, InternalError
from agl.ports.run import JsonValue

__all__ = [
    "ActivityReporter",
    "AgentOutcome",
    "AgentRunner",
    "AgentTask",
    "Capability",
    "Claude",
    "ModelId",
    "OpenAI",
    "Provider",
    "Restriction",
    "StopReason",
    "Tool",
    "ToolResult",
    "check_tool_declaration",
]

class Provider(StrEnum):
    CLAUDE = "claude"
    OPENAI = "openai"

class ModelId(StrEnum):
    @property
    def provider(self) -> Provider:
        """Which backend serves this model, read off the prefix before the colon.

        :return: the provider `adapters/routing.py` dispatches on; derived, never stored
        """
        prefix = self.value.partition(":")[0]
        try:
            return Provider(prefix)
        except ValueError as error:
            known = sorted(str(member) for member in Provider)
            raise InternalError(
                f"the model id {self.value!r} does not begin with a provider AGL knows: expected "
                f"one of {known} before a ':'. Model ids are this module's own enum members and "
                f"nobody types one, so a malformed id was written here, not passed in"
            ) from error

class Claude(ModelId):
    OPUS = "claude:opus"
    SONNET = "claude:sonnet"
    HAIKU = "claude:haiku"

class OpenAI(ModelId):
    SOL = "openai:sol"
    TERRA = "openai:terra"
    LUNA = "openai:luna"

class Restriction(StrEnum):
    NO_VCS_WRITES = "no_vcs_writes"
    NO_FILE_WRITES = "no_file_writes"
    NO_SHELL = "no_shell"
    NO_NETWORK = "no_network"

class Capability(StrEnum):
    FILE_EDIT = "file_edit"
    SHELL = "shell"
    TOOL_CALLING = "tool_calling"

@dataclass(frozen=True, slots=True)
class ToolResult:
    text: str

    rejected: bool = False

@dataclass(frozen=True, slots=True)
class Tool:
    name: str

    description: str

    payload_schema: Mapping[str, JsonValue]

    handler: Callable[[Mapping[str, JsonValue]], Awaitable[ToolResult]]

    def __post_init__(self) -> None:
        check_tool_declaration(self.name, self.description)
        object.__setattr__(self, "payload_schema", MappingProxyType(dict(self.payload_schema)))

def check_tool_declaration(name: str, description: str) -> None:
    """Refuse a tool declaration no model could act on, wherever one is being assembled.

    :param name: what a model calls the tool by, and so what it must be able to name
    :param description: the whole of what a model reads to decide this is the tool it wants
    :raises InputError: either is empty, and nothing has been attempted
    """
    if not name:
        raise InputError("a tool with an empty name cannot be named by anything calling it")
    if not description:
        raise InputError(
            f"tool {name!r} has an empty description, and the description is the whole of "
            f"what the model reads to decide whether this tool is the one it wants"
        )

@dataclass(frozen=True, slots=True)
class AgentTask:
    instructions: str

    workspace: Path

    model: ModelId

    restrictions: frozenset[Restriction]

    tools: tuple[Tool, ...]

    context: str | None = None

    plan_only: bool = False

    def __post_init__(self) -> None:
        if not self.instructions:
            raise InputError("an agent task with empty instructions asks the agent for nothing")
        if not self.workspace.is_absolute():
            raise InputError(
                f"workspace {str(self.workspace)!r} cannot be used: it is a relative path, and a "
                f"relative workspace resolves against whatever directory the adapter happens to "
                f"start its work in - a task carries a place, not a way of finding one"
            )
        names = [tool.name for tool in self.tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise InputError(
                f"these tools are declared more than once: {duplicates}. A model names the tool it "
                f"is calling, so a duplicate is a call no backend can resolve to one handler"
            )

class StopReason(StrEnum):
    COMPLETED = "completed"

    LIMIT = "limit"

@dataclass(frozen=True, slots=True)
class AgentOutcome:
    stop_reason: StopReason | None

    text: str

type ActivityReporter = Callable[[str], None]

class AgentRunner(ABC):
    @abstractmethod
    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        """What this backend can do when serving a model, compared against a role at preflight.

        :param model: asked for, because a routing runner cannot answer for every provider at once
        :return: what it can be asked for at all, which is no promise the next call succeeds
        """
        ...

    @abstractmethod
    async def check_ready(self, model: ModelId) -> None:
        """Whether this backend can serve this model right now. Answers with nothing, or refuses.

        :param model: preflight asks once per distinct model a workflow declares, before step one
        :raises UpstreamUnavailable: carrying a reason a person can act on and then start again
        """
        ...

    @abstractmethod
    async def run(
        self,
        task: AgentTask,
        *,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        """Run the task to its end and report what the agent did.

        :param task: the whole of what is asked, as one value; it carries no callbacks itself
        :param on_activity: sync, must not block, may never fire; what it raises ends the run
        :return: the agent's closing message, and why it stopped where the backend said
        """
        ...
