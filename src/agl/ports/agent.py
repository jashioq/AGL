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
    """Which backend serves a model: never chosen directly, but read off a `ModelId`'s prefix."""

    CLAUDE = "claude"
    OPENAI = "openai"

class ModelId(StrEnum):
    """Every model AGL can be asked for, as one type: `Claude` and `OpenAI` hold the members."""

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
    """Every model the Claude provider serves: nothing is substituted for one it cannot run."""

    OPUS = "claude:opus"
    SONNET = "claude:sonnet"
    HAIKU = "claude:haiku"

class OpenAI(ModelId):
    """Every model the OpenAI provider serves: nothing is substituted for one it cannot run."""

    SOL = "openai:sol"
    TERRA = "openai:terra"
    LUNA = "openai:luna"

class Restriction(StrEnum):
    """What an agent may not do: a backend enforces each its own way, and tells the model so."""

    NO_VCS_WRITES = "no_vcs_writes"
    NO_FILE_WRITES = "no_file_writes"
    NO_SHELL = "no_shell"
    NO_NETWORK = "no_network"

class Capability(StrEnum):
    """What a backend can do at all: a role wanting one the backend lacks is refused, not run."""

    FILE_EDIT = "file_edit"
    SHELL = "shell"
    TOOL_CALLING = "tool_calling"

@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool handler answers with: the text the model reads, and whether it was refused."""

    text: str

    rejected: bool = False

@dataclass(frozen=True, slots=True)
class Tool:
    """What an agent may call: a name unique to its role, a description, a schema and a handler."""

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
    """One dispatch to one agent: what to do, where, on what model, and under what restrictions."""

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
    """Why an agent stopped where it did: it ended its own turn, or a backend limit cut it off."""

    COMPLETED = "completed"

    LIMIT = "limit"

@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """Everything an agent run hands back: its closing message, and why it stopped, if it said."""

    stop_reason: StopReason | None

    text: str

type ActivityReporter = Callable[[str], None]

class AgentRunner(ABC):
    """Every agent backend behind one port: what it can do, whether it is ready, and one run."""

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
