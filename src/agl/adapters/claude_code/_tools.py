"""What the agent may call: the workflow's own tools, and the one tool that asks a person.

Two in-process MCP servers, built per run, handed to `ClaudeAgentOptions.mcp_servers`. Everything
about *how* a tool call reaches a handler and how an answer reaches the agent lives here;
`runner.py` composes the session and `translate.py` holds the vendor's vocabulary, neither of which
this module reaches into.

## Why an MCP tool, and not Claude Code's own `AskUserQuestion`

§3.7's mid-run question path needs a mechanism this adapter can drive from inside one live session.
Claude Code offers two candidates and only one of them survives being looked at.

**Rejected: intercepting the built-in `AskUserQuestion`.** Three separate reasons, any one of them
sufficient:

  * **It is not there.** A live probe against the installed CLI (2.1.235, `claude_agent_sdk`
    0.2.140) read the session's registered tool list off the `init` system message, with no deny
    rules at all, and `AskUserQuestion` was absent - on a machine whose environment carries
    `CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL`. So its availability is a build-and-flag question
    this adapter cannot answer, and `capabilities()` has to answer `MID_RUN_QUESTIONS` the same way
    on every machine or it is not a precondition anybody can check.
  * **It is unavailable to a subagent**, which §1.1 records as the vendor limitation that reshaped
    a workflow's concurrency: *"Both reviewers run as top-level calls, never subagents:
    `AskUserQuestion` is unavailable to a subagent."* The whole point of this stage is that such a
    limitation becomes a checked precondition rather than a structural workaround, and an adapter
    that adopted the limited mechanism would inherit the workaround along with it. An MCP tool is
    registered for the session, so a `Task` subagent can call it too.
  * **There is no clean way to answer it.** The only interception point the SDK offers is
    `can_use_tool`, whose two answers are allow and deny - so an answer would have to ride back as
    a *refusal message*, and every answered question would reach the model as a denied tool call.

**Chosen: AGL registers its own asking tool.** It exists on every build, needs no flag, is reachable
from a subagent, and its answer goes back as an ordinary tool result - which is literally "the
answer serialised into the same session", the clause §3.7 asks for, with no reinterpretation.

Claude Code's own asker is then **denied by name**, always, so that the agent has exactly one way to
ask and it is the way that reaches `on_question`. The alternative is a session where a model may
pick either mechanism and one of them talks to nobody: in a run with no interactive front end, that
is a question waiting on an answer that cannot arrive, which is the outcome the port calls the worst
one available. The deny costs a startup warning on a build where the tool is not registered, which
is the same trade `translate.py` already makes for `MultiEdit` and `PowerShell`.

**Why the vendor's tool name is spelled here and not in `translate.py`.** That module draws its own
boundary and this falls outside it twice over: it says it holds "no permission mode, and no reading
of `plan_only`" because choosing a harness mechanism "is a decision about how to run one, which is
`runner.py`'s", and it says "**No `Question` mapping.** §3.7's mid-run question path needs the SDK's
tool machinery and a live session to answer back into, which is a session concern rather than a
translation." Denying one asking mechanism because this module supplies another is that decision
exactly - it is not a translation of anything, and putting it in the translation table would make
that table hold a choice rather than a mapping.

## Two servers, so that a workflow can name a tool anything it likes

An SDK MCP tool is addressed as `mcp__<server>__<tool>`, so a workflow tool and AGL's asker would
collide the moment an author called something `ask`. They are on separate servers instead, which
makes the collision unrepresentable rather than checked-for: `mcp__agl__ask` and `mcp__agl_ask__ask`
are different tools, and `AgentTask.__post_init__` already refuses duplicates within the workflow's
own set. A check would have had to decide what to do on a collision, and every answer to that is
worse than not having one.

## The adapter never learns which tool is the reporting one

`ports/agent.py` spends a paragraph on this and it is the rule this module is built around: every
tool below is wrapped identically - invoke the handler, put its `text` back into the conversation,
flag it as an error when `rejected` - and nothing here reads a name, a schema or a payload to decide
what a tool *means*. A reporting tool's payload becoming a step's result is the framework's own
handler's job, on the framework's side of the port. The asking tool is the one tool this module
knows anything about, and it is this module's own, not one of `task.tools`.
"""

from collections.abc import Mapping
from typing import Any, Final

from claude_agent_sdk import McpServerConfig, SdkMcpTool, create_sdk_mcp_server

from agl.ports.agent import QuestionHandler, Tool
from agl.ports.questions import Question
from agl.ports.run import JsonValue

__all__ = ["ASKING_MECHANISMS_DENIED", "Asking", "servers"]

# Claude Code's own mid-run asker, denied for every run - see the module docstring. A tuple rather
# than one string because a harness may grow a second such tool and this is the list to add it to.
ASKING_MECHANISMS_DENIED: Final = ("AskUserQuestion",)

# The two server names. `mcp__<server>__<tool>` is how the model addresses a tool, so these are
# part of what the agent sees, and they are AGL's own words rather than a vendor's.
_SUPPLIED: Final = "agl"
_ASKING: Final = "agl_ask"

_ASK: Final = "ask"

_ASK_DESCRIPTION: Final = (
    "Ask the person running this task a question, and wait for their answer. Use it when a "
    "decision is genuinely theirs to make - which of two approaches to take, whether a proposal "
    "is acceptable - rather than guessing. You may call it as many times as you need; each call "
    "is one question and returns one answer. If no answer is available you will be told so, and "
    "you should then use your own judgement and carry on."
)

_ASK_SCHEMA: Final[Mapping[str, JsonValue]] = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "What you are asking, in full, in your own words.",
        },
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "The answers you are suggesting, if any. Each one is the exact text that may "
                "come back as the answer, so write them as answers and not as labels."
            ),
        },
        "allow_free_text": {
            "type": "boolean",
            "description": (
                "Whether an answer other than the options you offered is acceptable. Defaults "
                "to true; set it to false only when you are asking for a choice among them."
            ),
        },
    },
    "required": ["question"],
    "additionalProperties": False,
}

# What the agent is told when it asks and there is no handler. §3.7 and the port settle the
# wording's job: say that no answer is available and let it carry on with its own judgement. It is
# a result rather than an error, because nothing went wrong - nobody is listening, which the agent
# was told to expect in the tool's own description.
_NOBODY_LISTENING: Final = (
    "No answer is available: this task is running with nobody to ask. Nothing is wrong and this "
    "is not a failure - use your own judgement, decide it yourself, and carry on. Do not wait, "
    "and do not ask again."
)

# What the agent is told when a person answered with nothing at all. `Answer.text` may be the empty
# string and the port says that means nothing was said - which as a bare tool result would reach
# the model as a blank it has to interpret, so it is said in words. The same freedom
# `ToolResult.rejected` gives an adapter in the other direction: say it in the mechanism you have,
# or say it in words.
_SAID_NOTHING: Final = (
    "The person answered with nothing at all. Take that as no preference either way, use your "
    "own judgement, and carry on."
)

# What a call with no question in it is told. The schema makes `question` required, so the SDK's
# own validation catches an omitted key before this is reached; what is left for this is a key
# present and empty, which `Question` refuses and no view could render.
_NO_QUESTION: Final = (
    "That call asked nothing: `question` was empty. A question is the whole of what a person "
    "sees, so write what you are asking in full and call this tool again."
)


def servers(tools: tuple[Tool, ...], asking: Asking) -> dict[str, McpServerConfig]:
    """Both servers for one run, keyed as `ClaudeAgentOptions.mcp_servers` wants them.

    One function and not two, so that the names are spelled once: `mcp__<server>__<tool>` is what
    the model addresses, so a server name is part of the wire and a second module holding a copy of
    one is a copy that can drift. The two are separate servers for the reason the module docstring
    gives - it makes a collision between AGL's asker and a workflow's own tool unrepresentable
    rather than something a check has to decide what to do about.

    Every workflow tool is wrapped by the same three lines and none is treated specially, which is
    the port's rule rather than a simplification: an adapter that knew which tool was the reporting
    one would be holding framework vocabulary inside a vendor adapter, in every adapter, forever.
    """
    return {
        _SUPPLIED: create_sdk_mcp_server(
            name=_SUPPLIED, tools=[_wrapped(declared) for declared in tools]
        ),
        _ASKING: create_sdk_mcp_server(
            name=_ASKING,
            tools=[
                SdkMcpTool(
                    name=_ASK,
                    description=_ASK_DESCRIPTION,
                    input_schema=dict(_ASK_SCHEMA),
                    handler=asking.answered,
                )
            ],
        ),
    }


class Asking:
    """The bridge between one tool call and one `QuestionHandler`, for the length of one run.

    Per run and not per runner, because `on_question` is a per-call parameter: one runner serves
    many concurrent tasks and a workflow's two reviewers run at once against the same instance, so
    a handler stored on the adapter could not say which task it was speaking for.

    **`failure` is why this is a class and not a closure.** A handler that raises is not a
    hypothetical: §3.7's headless terminal raises `UpstreamUnavailable` on any view that needs an
    answer, and a workflow's handler may raise `Stop`. The SDK turns an exception out of a tool
    handler into an error result for the model and carries on, which would spend an hour of agent
    time on a run whose asker has already failed - so the exception is kept here, the model is told
    an answer is not available so that it does not block either, and `_session.py` re-raises it as
    soon as the next message arrives. The first one is kept and later ones are dropped: it is the
    one that explains why the rest went the way they did.
    """

    def __init__(self, on_question: QuestionHandler | None) -> None:
        self._on_question = on_question
        self.asked = 0
        """How many questions reached a handler. Read by nothing in production - it is what makes
        "the agent asked, and it was this adapter that carried it" visible to a test."""

        self.failure: Exception | None = None
        """The first exception a handler raised, or `None`. See the class docstring.

        `Exception` and not `BaseException`, which is the difference between keeping a failure and
        swallowing a cancellation: `asyncio.CancelledError` is a `BaseException`, it means the task
        around this run is being torn down, and catching it here would answer the model politely
        while the caller waited for a cancellation that never landed."""

    async def answered(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Map one payload into a `Question`, await the handler, and hand back the `Answer`.

        Three outcomes, and none of them blocks. A payload with nothing being asked is *refused*
        back to the model, which is §3.3's mechanism used for the adapter's own tool: there is a
        session in flight holding the reasoning that produced the call, and the cheap fix is for
        the model to ask again properly. No handler at all is answered in words, per the port's
        second edge case. Otherwise the handler is awaited and its answer goes back verbatim.
        """
        prompt = payload.get("question")
        if not isinstance(prompt, str) or not prompt.strip():
            return _result(_NO_QUESTION, rejected=True)
        if self._on_question is None:
            return _result(_NOBODY_LISTENING)
        if self.failure is not None:
            return _result(_NOBODY_LISTENING)
        self.asked += 1
        try:
            answer = await self._on_question(_question(prompt, payload))
        except Exception as raised:
            self.failure = raised
            return _result(_NOBODY_LISTENING)
        return _result(answer.text if answer.text else _SAID_NOTHING)


def _question(prompt: str, payload: Mapping[str, Any]) -> Question:
    """Whatever the model produced, as the poorest pair that still carries an exchange.

    Two defensive readings, both of which exist because the payload is a model's and `Question`
    refuses what it cannot be asked with. Options that are not non-empty strings are dropped: an
    option is the exact text that goes back as the answer, so an empty one is unpickable in any
    view and a number is not an answer. And free text is left allowed whenever nothing pickable
    survived, which is the port's own instruction - "an adapter mapping a payload with no choices
    in it leaves free text allowed" - and the difference between an open question and one nobody
    could answer.
    """
    offered = payload.get("options")
    options = (
        tuple(item for item in offered if isinstance(item, str) and item)
        if isinstance(offered, list)
        else ()
    )
    free = payload.get("allow_free_text")
    return Question(
        prompt=prompt,
        options=options,
        allow_free_text=True if not options or not isinstance(free, bool) else free,
    )


def _wrapped(declared: Tool) -> SdkMcpTool[Any]:
    """One `Tool` as something Claude Code can call, with the handler behind it.

    The payload arrives as the mapping the port declares, because the SDK validates it against the
    schema and hands over the parsed arguments; nothing here re-parses text. `ToolResult.rejected`
    becomes the MCP error flag, which is Claude Code's error frame for a tool result - so a refusal
    reaches the model as a refusal rather than as prose it has to notice, and §3.3's "corrects
    itself and carries on" is the mechanism's own behaviour rather than something argued for in a
    string.
    """

    async def invoked(payload: dict[str, Any]) -> dict[str, Any]:
        outcome = await declared.handler(payload)
        return _result(outcome.text, rejected=outcome.rejected)

    return SdkMcpTool(
        name=declared.name,
        description=declared.description,
        input_schema=_schema(declared.payload_schema),
        handler=invoked,
    )


def _schema(payload_schema: Mapping[str, JsonValue]) -> dict[str, Any]:
    """A `payload_schema` in the exact shape the SDK passes through untouched.

    Not a translation and not a validation: the SDK forwards a dict as JSON Schema **only** when it
    carries a string `type` and a `properties` key, and otherwise re-reads the whole dict as a
    `{name: python type}` shorthand - so a schema spelled `{"type": "object"}` would arrive at the
    model as an object with one property called `type`. The port says a `payload_schema` is "a JSON
    Schema object describing the argument the tool takes", so both keys are what it already means;
    supplying the missing one is how that meaning survives the crossing. Anything already carrying
    both is passed through with nothing added.
    """
    schema = dict(payload_schema)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def _result(text: str, *, rejected: bool = False) -> dict[str, Any]:
    """One tool result in the shape the SDK's in-process server expects."""
    return {"content": [{"type": "text", "text": text}], "is_error": rejected}
