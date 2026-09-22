from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import assert_never
from agl.ports.errors import InputError, InternalError
from agl.ports.run import JsonValue

__all__ = [
    "ActivityReporter",
    "AgentOutcome",
    "AgentRunner",
    "AgentTask",
    "Capability",
    "ChosenClaude",
    "ChosenOpenAI",
    "Claude",
    "ClaudeEffort",
    "Installation",
    "ModelChoice",
    "ModelEfforts",
    "ModelId",
    "OpenAI",
    "OpenAIEffort",
    "Provider",
    "Restriction",
    "Standing",
    "StopReason",
    "Tool",
    "ToolResult",
    "VersionRange",
    "check_tool_declaration",
    "model_of",
]

class Provider(StrEnum):
    """The vendor whose tool runs a [`ModelId`][agl.sdk.ModelId]."""

    CLAUDE = "claude"
    OPENAI = "openai"

class ModelId(StrEnum):
    """A model a role can run on."""

    @property
    def provider(self) -> Provider:
        """The vendor whose tool runs this model.

        Returns:
            The vendor, which is what routes a step on this model to a backend.
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

class ClaudeEffort(StrEnum):
    """How long a Claude model reasons before answering."""

    # The choices `claude --help` lists for `--effort` in Claude CLI 2.1.277, and the `EffortLevel`
    # literal in `claude_agent_sdk/types.py` 0.2.157.
    LOW = "low"
    """The least reasoning of the five."""

    MEDIUM = "medium"
    """More reasoning than `LOW`."""

    HIGH = "high"
    """More reasoning than `MEDIUM`."""

    XHIGH = "xhigh"
    """More reasoning than `HIGH`."""

    MAX = "max"
    """The most reasoning of the five."""

class OpenAIEffort(StrEnum):
    """How long an OpenAI model reasons before answering."""

    # The union of the reasoning levels the vendor CLI 0.155.1's model listing reports for the
    # three models `OpenAI` names: `gpt-5.6-luna` lists every one of these but `ultra`, and none of
    # the three lists `minimal` or `none`.
    LOW = "low"
    """The least reasoning of the six."""

    MEDIUM = "medium"
    """More reasoning than `LOW`."""

    HIGH = "high"
    """More reasoning than `MEDIUM`."""

    XHIGH = "xhigh"
    """More reasoning than `HIGH`."""

    MAX = "max"
    """More reasoning than `XHIGH`."""

    ULTRA = "ultra"
    """The most reasoning of the six, and offered for some models only."""

class Claude(ModelId):
    """A Claude model a role can run on."""

    OPUS = "claude:opus"
    """The model its backend runs as `opus`."""

    SONNET = "claude:sonnet"
    """The model its backend runs as `sonnet`."""

    HAIKU = "claude:haiku"
    """The model its backend runs as `haiku`."""

    def __call__(self, *, effort: ClaudeEffort) -> ChosenClaude:
        """Chooses how long this model reasons.

        Args:
            effort: The reasoning level, one of Claude's own.

        Returns:
            The model at that effort, to pass as `@role(model=...)`.

        Raises:
            InputError: `effort` is not a [`ClaudeEffort`][agl.sdk.ClaudeEffort].
        """
        return ChosenClaude(self, effort)

class OpenAI(ModelId):
    """An OpenAI model a role can run on."""

    SOL = "openai:sol"
    """The model its backend runs as `gpt-5.6-sol`."""

    TERRA = "openai:terra"
    """The model its backend runs as `gpt-5.6-terra`."""

    LUNA = "openai:luna"
    """The model its backend runs as `gpt-5.6-luna`."""

    def __call__(self, *, effort: OpenAIEffort) -> ChosenOpenAI:
        """Chooses how long this model reasons.

        Args:
            effort: The reasoning level, one of OpenAI's own.

        Returns:
            The model at that effort, to pass as `@role(model=...)`.

        Raises:
            InputError: `effort` is not an [`OpenAIEffort`][agl.sdk.OpenAIEffort].
        """
        return ChosenOpenAI(self, effort)

# Not `str` subclasses: `str()` of one would be its bare member's text, and a step recorded at one
# effort would replay at another. `tests/sdk/test_journal.py` measures that collision in
# `test_a_composite_whose_str_is_the_model_id_is_not_that_members_fingerprint`.
@dataclass(frozen=True, slots=True)
class ChosenClaude:
    """A Claude model with its effort chosen."""

    model: Claude

    effort: ClaudeEffort

    def __post_init__(self) -> None:
        if not isinstance(self.model, Claude) or not isinstance(self.effort, ClaudeEffort):
            raise InputError(
                _not_a_choice(self.model, self.effort, "Claude.OPUS(effort=ClaudeEffort.HIGH)")
            )

@dataclass(frozen=True, slots=True)
class ChosenOpenAI:
    """An OpenAI model with its effort chosen."""

    model: OpenAI

    effort: OpenAIEffort

    def __post_init__(self) -> None:
        if not isinstance(self.model, OpenAI) or not isinstance(self.effort, OpenAIEffort):
            raise InputError(
                _not_a_choice(self.model, self.effort, "OpenAI.SOL(effort=OpenAIEffort.HIGH)")
            )

type ModelChoice = ModelId | ChosenClaude | ChosenOpenAI

def model_of(choice: ModelChoice) -> ModelId:
    """The bare model a choice names, which is what readiness, capabilities and routing ask about.

    Args:
        choice: a bare member, or one called with an effort; the effort is not carried over

    Returns:
        the member itself, which every table keyed by model is looked up with
    """
    match choice:
        case ChosenClaude() | ChosenOpenAI():
            return choice.model
        case ModelId():
            return choice
        case _:
            assert_never(choice)

def _not_a_choice(model: object, effort: object, example: str) -> str:
    return (
        f"{model!r} at effort {effort!r} is not a model with its effort chosen: write a member "
        f"called with its own provider's effort, as in `{example}`. A string is refused even where "
        f"it spells a level, and so is another provider's effort, whose levels are that provider's"
    )

class Restriction(StrEnum):
    """What an agent cannot do."""

    NO_VCS_WRITES = "no_vcs_writes"
    """Takes away the agent's commits, branches, merges, fetches and pushes."""

    NO_FILE_WRITES = "no_file_writes"
    """Takes away the agent's writes to disk."""

    NO_SHELL = "no_shell"
    """Takes away the agent's shell, and the other tools a backend runs commands through."""

    NO_NETWORK = "no_network"
    """Takes away the agent's network tools. On Claude Code, its shell still reaches the network."""

class Capability(StrEnum):
    """Something a role needs its agent to be able to do."""

    FILE_EDIT = "file_edit"
    """Changing files in the checkout the step runs in."""

    SHELL = "shell"
    """Running shell commands."""

    TOOL_CALLING = "tool_calling"
    """Calling the tools a role declares. A role with tools requires it without saying so."""

@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool's handler returns to the agent."""

    text: str
    """What the agent reads back from the call."""

    rejected: bool = False
    """`True` tells the agent the call failed, `False` that it succeeded."""

@dataclass(frozen=True, slots=True)
class Tool:
    """A tool an agent can call."""

    name: str
    """What the agent calls the tool by, unique among a [`Role`][agl.sdk.Role]'s tools."""

    description: str
    """The whole of what the agent reads to decide this is the tool it wants."""

    payload_schema: Mapping[str, JsonValue]
    """The JSON schema of the arguments the agent is asked to fill in."""

    handler: Callable[[Mapping[str, JsonValue]], Awaitable[ToolResult]]
    """Awaited with the arguments. Its result goes to the agent; what it raises ends the step."""

    def __post_init__(self) -> None:
        check_tool_declaration(self.name, self.description)
        object.__setattr__(self, "payload_schema", MappingProxyType(dict(self.payload_schema)))

def check_tool_declaration(name: str, description: str) -> None:
    """Refuse a tool declaration no model could act on, wherever one is being assembled.

    Args:
        name: what a model calls the tool by, and so what it must be able to name
        description: the whole of what a model reads to decide this is the tool it wants

    Raises:
        InputError: either is empty, and nothing has been attempted
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

    model: ModelChoice

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
"""Called with one line for each thing the agent does, as it does it."""

class Standing(StrEnum):
    """Where an installed version sits against a tested range: inside it, outside, or unjudged."""

    WITHIN = "within"
    BELOW = "below"
    ABOVE = "above"
    UNREADABLE = "unreadable"
    UNREPORTED = "unreported"

@dataclass(frozen=True, slots=True)
class VersionRange:
    """The versions of its tool an adapter was exercised against: the oldest and the newest."""

    lowest: str

    highest: str

@dataclass(frozen=True, slots=True)
class ModelEfforts:
    """What one model reasons at, in its own tool's words: the levels offered, and the fallback."""

    # In the tool's own order and never sorted here, because the order is itself something the tool
    # reported: the vendor CLI 0.155.1 lists every model's levels ascending, so its last entry is
    # the most that model reasons at, and a set would throw that away.
    levels: tuple[str, ...]
    """The tool's own spellings, which is why these are strings and not an effort enum's members."""

    default: str | None
    """What the tool reasons at where a task names no level; `None` where it did not say."""

@dataclass(frozen=True, slots=True)
class Installation:
    """What a backend runs on: the tool, its version, where from, the tested range, its efforts."""

    tool: str
    """What to call the tool in a sentence, supplied here because no layer above may spell it."""

    version: str | None
    """As the tool spelled it, unparsed; `None` where none was read, which is never a refusal."""

    tested: VersionRange

    efforts: Mapping[ModelId, ModelEfforts]
    """Every model this backend serves that its tool described; empty where the tool cannot say."""

    where: str | None = None
    """How the binary the version came from was named; `None` where no binary was identified."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "efforts", MappingProxyType(dict(self.efforts)))

    @property
    def standing(self) -> Standing:
        """Where the version that answered sits against the range, derived rather than stored.

        Returns:
            `WITHIN` where nothing needs saying, and four separate reasons to say something
        """
        if self.version is None:
            return Standing.UNREPORTED
        found = _ordered(self.version)
        lowest = _ordered(self.tested.lowest)
        highest = _ordered(self.tested.highest)
        if found is None or lowest is None or highest is None:
            return Standing.UNREADABLE
        if found < lowest:
            return Standing.BELOW
        return Standing.ABOVE if found > highest else Standing.WITHIN

# Two or three dot-separated runs of ASCII digits and nothing else. A component a vendor spells with
# anything more - `0.152.0-rc1`, `2.1.259+build` - is one no ordering written here could place
# honestly, and `Standing.UNREADABLE` is what says so; `str.isdigit` alone admits superscripts,
# which `int` then refuses.
def _ordered(version: str) -> tuple[int, ...] | None:
    parts = version.split(".")
    if not 2 <= len(parts) <= 3 or not all(part.isascii() and part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts) + (0,) * (3 - len(parts))

class AgentRunner(ABC):
    """Every agent backend behind one port: what it can do, what it runs on, if ready, one run."""

    @abstractmethod
    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        """What this backend can do when serving a model, compared against a role at preflight.

        Args:
            model: asked for, because a routing runner cannot answer for every provider at once

        Returns:
            what it can be asked for at all, which is no promise the next call succeeds
        """
        ...

    @abstractmethod
    async def check_ready(self, model: ModelId) -> None:
        """Whether this backend can serve this model right now. Answers with nothing, or refuses.

        Args:
            model: preflight asks once per distinct model a workflow declares, before step one

        Raises:
            UpstreamUnavailable: carrying a reason a person can act on and then start again
        """
        ...

    @abstractmethod
    async def installation(self, model: ModelId) -> Installation:
        """What this backend is running on, against what it was tested. Warns; never refuses.

        Args:
            model: asked for, because a routing runner stands over one tool per provider

        Returns:
            the whole of what a version warning is built from, tool's name included
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

        Args:
            task: the whole of what is asked, as one value; it carries no callbacks itself
            on_activity: sync, must not block, may never fire; what it raises ends the run

        Returns:
            the agent's closing message, and why it stopped where the backend said
        """
        ...
