"""The `AgentRunner` port - run an agent in a workspace - and the vocabulary it speaks.

One ABC, several backends. A workflow names a model beside the prompt, because the reason for the
choice is semantic: this role touches sensitive code, that one needs deep judgement, this one is
cheap and high-volume. `adapters/routing.py`, assembled once at the composition root from whatever
is configured and installed, dispatches on `task.model.provider`. A workflow sees one
`AgentRunner` and never learns which adapter served it.

## The line this module draws

Model *names* crossing the port is deliberate and correct: naming a model is a domain choice, like
naming a database. Vendor **syntax, types, exceptions and option objects** never cross.

Plan §1.1 records what this port looked like where that line was not drawn: a tuple of strings in
one harness's own permission language, an unvalidated mode string, one vendor's product names in an
enum, and that vendor's session identity in the result. The leak did not stop at the port - two
layers up a workflow held a constant tuple written in that same permission language, and the same
harness's limitations had shaped that workflow's concurrency. A port built around one backend never
announces itself. It simply makes the second one impossible, one plausible field at a time.

So every type below was written against one test, and is worth reading against it: **could a
second, structurally different implementation satisfy this honestly?** Not "could it be made to
compile" - could it implement this without ignoring a field, without inventing a value it does not
have, and without raising on something the port implies it supports. Two of the three
implementations in view drive a command-line harness, which makes *harness* concepts - a session,
an approval mode, a settings file - the leak this module is least likely to notice, since both
would carry it happily. The third is a model behind a plain HTTP API with no harness at all, and it
is the one to ask about each field.

**What this module refuses, it refuses as `InputError`.** Everything here is supplied by a caller -
a workflow author declaring a role, the engine composing a task out of it - and nothing has been
attempted when a constructor turns it down, which is that class exactly. Exit 2 sends the reader to
the declaration; exit 70 would send a workflow author hunting for a bug in the framework. The one
exception is `ModelId.provider`, an `InternalError`, because model ids are this module's own enum
members and nobody types one.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from agl.ports.errors import InputError, InternalError
from agl.ports.questions import Answer, Question
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
    "QuestionHandler",
    "Restriction",
    "StopReason",
    "Tool",
    "ToolResult",
]


# Every enum value below is an explicit string, never `auto()`. A step's fingerprint is canonical
# JSON over its role, inputs and head (§3.6), so a role's `Restriction` set and its tools' payload
# schemas are inside it - and a fingerprint is written down and compared against on resume. These
# strings are therefore a stored format: change one and every step recorded under it stops matching
# and re-runs its agent. `auto()` would hand that to declaration order, where reordering two lines
# is a silent format change.


class Provider(StrEnum):
    """Who serves a model. One adapter per member, held by the routing runner and nowhere else.

    A closed set: a provider is not a string a user configures, it is a backend somebody wrote an
    adapter for, and the two arrive in the same commit."""

    CLAUDE = "claude"
    OPENAI = "openai"


class ModelId(StrEnum):
    """A model AGL may be asked to run, spelled `<provider>:<model>`.

    Deliberately memberless, so the per-provider enums below can extend it: an enum with members is
    closed to subclassing, and this one stays open for the same reason `Provider` stays closed - a
    provider arrives with an adapter, and its models arrive with it.

    These are the vendor names in the codebase, and they are here on purpose. Naming a model is a
    domain choice, like naming a database: the author picked it for a reason they can state, and
    the framework passes it through without interpreting it. What must never follow it across is
    the vendor's syntax, its types, its exceptions or its option objects.
    """

    @property
    def provider(self) -> Provider:
        """Which backend serves this model, read off the prefix before `:`.

        Derived rather than stored beside the value, because the two would have to agree and a
        second field is a second thing that can stop agreeing. `adapters/routing.py` dispatches on
        exactly this, so a member whose prefix names nothing is a run that cannot be routed - and
        it is our typo, in this file, which is why this one refusal is an `InternalError`.
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
    """One provider's models."""

    OPUS = "claude:opus"
    SONNET = "claude:sonnet"
    HAIKU = "claude:haiku"


class OpenAI(ModelId):
    """Another provider's models, in the same three tiers: deep judgement, everyday work, cheap.

    The names are AGL's own, taken from the slugs they stand for rather than copied from them. That
    provider's harness publishes no `gpt-5` at all: its model list at CLI 0.149.0 - a local query
    that costs nothing - puts `gpt-5.6-sol`, `gpt-5.6-terra` and `gpt-5.6-luna` at priorities 1, 2
    and 3, described there as the latest frontier agentic coding model, a balanced one for everyday
    work, and a fast and affordable one. So the tier is the vendor's own ordering rather than our
    reading of it. What is dropped is the version, deliberately: these values are a stored format,
    and a 5.7 release must not re-run every step recorded under one of them.

    **One asymmetry with `Claude` above, worth stating rather than leaving to be found.** Anthropic
    publishes `opus`, `sonnet` and `haiku` as aliases and resolves them itself, so that adapter
    hands over the tier and stops. `sol`, `terra` and `luna` are AGL's own undated spelling of slugs
    that carry their version, so this provider's adapter needs an edit on a release where the Claude
    one does not. That edit is in an adapter, where a vendor's release schedule belongs, and not
    here, where it would be a change to something already written down.
    """

    SOL = "openai:sol"
    TERRA = "openai:terra"
    LUNA = "openai:luna"


class Restriction(StrEnum):
    """What a role may not do, stated as intent and never as anybody's syntax.

    Each member says what AGL means; each adapter renders it in whatever its own backend offers,
    and this module holds no opinion at all about how - naming a mechanism here would be exactly
    the leak §1.1 records, one abstraction later. A backend with no way to enforce one has two
    honest moves and no third: put it to the agent as an instruction, or refuse the task. Silently
    dropping it is neither. They are a set and not a level: any combination, no ordering, and
    nothing here implies anything else.
    """

    NO_VCS_WRITES = "no_vcs_writes"
    NO_FILE_WRITES = "no_file_writes"
    NO_SHELL = "no_shell"
    NO_NETWORK = "no_network"


class Capability(StrEnum):
    """What a backend can actually do - reported by `capabilities()`, checked before a run starts.

    The counterpart to `Restriction`: that is what a workflow forbids, this is what a backend can
    offer at all. A role declares what it requires, preflight compares the two, and a run that
    cannot work dies at second zero instead of forty minutes in at the review step - which is the
    principled form of a vendor limitation that used to be a paragraph in a docstring and a
    structural workaround in a workflow. A member belongs here only if some backend can plausibly
    lack it; that is the whole membership rule, and it is why the list is short."""

    FILE_EDIT = "file_edit"
    SHELL = "shell"
    MID_RUN_QUESTIONS = "mid_run_questions"
    TOOL_CALLING = "tool_calling"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool hands back - and it goes back *to the agent*, not to the framework.

    §3.3: a malformed payload is rejected back to the model inside the same conversation, so it
    corrects itself and carries on. Not an adapter retry, not a workflow retry, and not an
    exception - by the time a call is malformed there is a session in flight holding all the
    reasoning that produced it, and throwing that away to start again is the expensive move.
    """

    text: str
    """What the agent sees. The whole of what the framework says back to it."""

    rejected: bool = False
    """Whether this is a refusal rather than a result, for a backend whose protocol can say so.

    A backend with no error channel renders the refusal into `text` and the model still learns what
    went wrong. That is rendering, not ignoring - the same freedom `Restriction` gives an adapter:
    say it in the mechanism you have, or say it in words."""


@dataclass(frozen=True, slots=True)
class Tool:
    """Something the agent may call, and what happens when it does.

    Defined here rather than in `sdk/` because it crosses the port on `AgentTask.tools` and a port
    may not import the layer above it; `sdk/tools.py` re-exports it and adds a declaration helper,
    which is the whole of that relationship.

    **The handler is why `AgentOutcome` carries no payload.** A reporting step's result is its
    reporting tool's payload (§3.3) - but an adapter that returned "the result" would have to know
    which of the tools it was handed is the reporting one, and that is framework vocabulary living
    inside a vendor adapter, in every adapter, forever. Instead one uniform rule that every backend
    implements identically: the agent calls a tool, the adapter invokes the handler, the handler's
    `text` goes back into the conversation. Capturing the payload is the framework's own handler's
    job, on the framework's side of the port.
    """

    name: str
    """What the model calls it. Unique within a task - see `AgentTask.__post_init__`."""

    description: str
    """What the model reads to decide whether to call it. Prose, in the author's own words."""

    payload_schema: Mapping[str, JsonValue]
    """A JSON Schema object describing the argument the tool takes.

    JSON Schema because every backend in view already speaks it, so this is a shared format and not
    a translation. It is data, not a type: this module never validates against it and holds no
    vocabulary for it - the adapter hands it over, and the handler decides what is acceptable."""

    handler: Callable[[Mapping[str, JsonValue]], Awaitable[ToolResult]]
    """What runs when the agent calls it, awaited by the adapter, its `text` returned to the agent.

    Async because the framework's own handlers write to the store and to the terminal, and a sync
    signature would make every one of those a blocking call inside an adapter's event loop."""

    def __post_init__(self) -> None:
        if not self.name:
            raise InputError("a tool with an empty name cannot be named by anything calling it")
        if not self.description:
            raise InputError(
                f"tool {self.name!r} has an empty description, and the description is the whole of "
                f"what the model reads to decide whether this tool is the one it wants"
            )
        # Copied and wrapped so a caller that kept the dict it passed cannot edit a schema already
        # inside a step's fingerprint. One level, and said rather than implied: deep-freezing means
        # walking a JSON Schema, and this module does not speak that language - see the field.
        object.__setattr__(self, "payload_schema", MappingProxyType(dict(self.payload_schema)))


@dataclass(frozen=True, slots=True)
class AgentTask:
    """Everything an agent is asked to do, as one value.

    A value and nothing more: no callbacks live here. `on_question` and `on_activity` are parameters
    of `AgentRunner.run` instead, which is what keeps this frozen, comparable and loggable - a task
    can go into an error message or sit beside a fingerprint, and a task holding two closures could
    do neither.

    There is no timeout and no budget. §3.7 has no timeouts anywhere, and an agent verifying its own
    work is unbounded by design: it runs the build, reads the failure, fixes it, runs it again, and
    a framework-level clock on that is a framework-level opinion about how long understanding a
    codebase takes. A backend that imposes its own limit reports having done so through
    `StopReason.LIMIT` - a fact about what happened, rather than a knob here.
    """

    instructions: str
    """What to do, in full, as the workflow author wrote it. The prompt, already resolved."""

    workspace: Path
    """The directory the agent works in - an isolated checkout, handed over by `WorkspaceProvider`.

    Absolute, and refused otherwise: a relative path resolves against whatever directory the
    adapter's subprocess happens to start in, and that hidden input is the kind that works on one
    machine for months. `tree_layout.TreesRoot` refuses a relative root for the same reason."""

    model: ModelId
    """Which model. Also, through `.provider`, which adapter - but that is routing's business."""

    restrictions: frozenset[Restriction]
    """What this role may not do. A set, so `frozenset()` is the honest spelling of "nothing"."""

    tools: tuple[Tool, ...]
    """What it may call, in declaration order. Empty is ordinary - an effect step may need none."""

    context: str | None = None
    """Standing context for the whole task, if the workflow has any; `None` when it has none.

    Kept apart from `instructions` rather than joined onto it, because a backend that distinguishes
    standing context from the task at hand can honour the distinction and one that does not joins
    two strings itself. Joining here destroys something a backend can use; not joining costs the
    others one concatenation."""

    plan_only: bool = False
    """Whether the agent is to examine and propose, and change nothing.

    That sentence is the definition, and it is in AGL's terms on purpose: this is the field most at
    risk of being one harness's approval mode under a new name, and an approval mode is exactly what
    §1.1 caught crossing this port as an unvalidated string. As written, all three implementations
    in view satisfy it honestly - a harness with a plan mode selects it; a harness without one says
    so in the prompt and enforces it with what it has; an HTTP backend is simply not offered the
    tools that change anything.

    It is **not** derived from `restrictions` and does not imply them. The two answer different
    questions: `restrictions` is what the agent is prevented from doing, `plan_only` is what it is
    being asked for. A workflow wanting both prevention and intent states both, and the framework
    infers neither from the other - inferring would mean deciding which restrictions "mean"
    planning, a policy this port has no standing to invent."""

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
    """Why the agent stopped - a question with exactly two answers worth telling apart.

    Not an error state. An error is an exception, raised by the adapter that translated whatever its
    backend threw into `errors.py`'s hierarchy at its own boundary; nothing above an adapter sees a
    vendor's stop strings, which is what §1.1 caught this port carrying before.
    """

    COMPLETED = "completed"
    """The agent ended its own turn. It decided it was done, whether or not it was right."""

    LIMIT = "limit"
    """The backend stopped it against its will - turns, tokens, time, budget, any of them.

    One member and not four, because they differ only in which knob was reached and the reader needs
    the same thing from all of them: the agent had more to say. Which one it was belongs in the
    adapter's log, beside the number that caused it."""


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """What came back. Two fields - and the list of what was taken out is the more interesting one.

    Neither field has a default, deliberately. `None` and `""` both mean something specific here,
    "the backend did not say" and "the agent said nothing", and an adapter should have to state them
    rather than fall into them by leaving an argument off.

    **Excluded, each for its own reason:**

    *A session id.* Vendor session identity, the exact thing §1.1 names. Nothing in AGL resumes a
    session: §3.7 accepts in writing that a crash mid-negotiation re-runs the step and re-asks from
    scratch, precisely because mid-session state is not reconstructible from a session id anyway. A
    field kept for the one backend that has one is a field the others return `None` from forever,
    and the shape of the port would then say that resuming sessions is a thing it does.

    *Cost, token counts, turn counts.* The plan removed `events.jsonl` and cost accounting whole;
    nothing in v1.1 reads them. They are also the numbers most likely to differ in meaning between
    backends - a "turn" is not one thing - so a field here would be a column nobody can add up.

    *Changed files.* That is `History`'s question, asked of git after the fact, where the answer is
    true regardless of which backend made the changes or whether it bothered to report them.
    """

    stop_reason: StopReason | None
    """Why it stopped, or `None` when the backend did not say.

    Optional rather than a third `UNKNOWN` member, because "did not say" is a fact about the backend
    and not a way of stopping, and a member would list it beside two things that actually happened.
    A harness that reports nothing here is not broken, and this is how it says so honestly.

    Its consumer is the error message when a reporting step ends with no payload: "it ran out of
    turns" and "it decided it was finished" send a reader to different fixes - raise the limit, or
    fix the prompt - and `None` says the message can offer neither."""

    text: str
    """The agent's closing message. `""` when it said nothing.

    The port's only content channel, which is the argument for it. An **effect** step declares no
    reporting tool, so its result is `null` (§3.3) and there is no payload anywhere: without this
    field, "run an agent" could not return what the agent said, which for a port whose whole job is
    running agents is not a defensible thing to be unable to do. For a backend shaped like a
    completion API rather than a harness this is the *primary* output and the tools are the optional
    part. It is also what makes the failure legible when a reporting step finishes without
    reporting: the error can quote what the agent said instead."""


type QuestionHandler = Callable[[Question], Awaitable[Answer]]
"""What an adapter calls when the agent asks something mid-run. One question in, one answer out.

Async because answering may mean waiting on a person. One parameter because the workflow's handler
is a closure over its own `Run` and needs nothing else from the framework (§3.7)."""

type ActivityReporter = Callable[[str], None]
"""What an adapter calls to say what is happening right now. A string, passed through untouched."""


class AgentRunner(ABC):
    """Run an agent. The whole port - three methods, and nothing that assumes a shape of backend.

    There is no `close()`, no session handle and no settings-file parameter. Each would be a harness
    concept that both command-line backends could carry without noticing and that a model behind a
    plain HTTP API could only implement as a no-op, which is the definition of a field that lies. A
    runner is built by the container with whatever its own backend needs, and is then addressed only
    through what is below.

    `adapters/routing.py` implements this same ABC over one adapter per provider. That is why both
    query methods take a `ModelId`: the routing runner is an `AgentRunner` like any other, and one
    asked "what can you do" with no model named could only answer for some provider or other, which
    is a lie in the shape of an answer.
    """

    @abstractmethod
    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        """What this backend can do when serving `model`, checked at preflight against a role.

        Async because the answer can depend on what is installed - a harness version that gained
        mid-run questions two releases ago - and a sync signature would leave an adapter two bad
        options: answer from a hardcoded table that goes stale, or probe the world at construction
        time, in the container, where a slow or failing backend would break the composition root for
        every run, including the ones that never touch it.

        This is "what can you do", not "can you do it now" - see `check_ready`. Reporting a
        capability is not a promise that the next call succeeds; it is a statement about the kind of
        work this backend can be asked for at all.
        """

    @abstractmethod
    async def check_ready(self, model: ModelId) -> None:
        """Whether this backend can serve `model` right now. Returns nothing, or raises.

        Raise `UpstreamUnavailable` with a reason a person can act on - the harness is not on
        `PATH`, its version is too old, the session is not authenticated. §3.2's first preflight
        check is this call over every provider the workflow's roles name, so a run needing two of
        them dies at second zero on the missing one rather than forty minutes in.

        Deliberately not folded into `capabilities()`, though both are asked at preflight and both
        take a model. They have different failure modes and different lifetimes: a missing
        capability is permanent and the workflow must change, while not being ready is a state of
        the world that a login fixes in ten seconds. One call reporting both would have to invent a
        way of saying which of the two it meant.
        """

    @abstractmethod
    async def run(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        """Run the task to its end and report what happened.

        Raises from `errors.py` and nowhere else: the adapter translates whatever its backend throws
        at its own boundary, so a workflow catches `UpstreamUnavailable` and never learns what the
        thing underneath happened to raise.

        **`on_question` is the mid-run question path** (§3.7). The adapter wires whatever asking
        mechanism it has to this callback: it maps the payload its backend produced into a
        `Question`, awaits the handler, and serialises the `Answer` back into the same session, so a
        negotiation is N rounds inside one run and not N runs. Two edge cases, settled here so that
        no adapter decides them alone:

        * An adapter that cannot ask mid-run says so through `capabilities()` and may simply never
          call the handler. It does not pretend to ask and it does not block on a mechanism it does
          not have; preflight has already refused any role that needs one.
        * If the agent asks while `on_question` is `None`, the adapter must **not** block. It tells
          the agent that no answer is available and lets it carry on with its own judgement. A run
          hanging on a question nobody is listening for is the worst outcome available, because it
          looks exactly like work.

        **`on_activity` takes a plain string** (§3.7). Each adapter formats its own line and it is
        passed through untouched - no `Activity` type, no shared verb taxonomy, no framework lookup
        table, and no shape imposed by this port on what an adapter may say. The cost is cosmetic
        inconsistency between backends; the gain is that no future backend has to map its vocabulary
        onto another's.

        It is a per-call parameter and not a property on the runner because one runner serves many
        concurrent tasks - a workflow's two reviewers run at once against the same instance - and a
        property could not say which one it was speaking for. It is sync, it must not block, and it
        must not be relied on: an adapter with nothing to report calls it never, and activity is
        live-only and never persisted, so a step replayed from cache correctly has none at all.
        """
