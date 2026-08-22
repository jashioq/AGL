"""What the agent may call: the workflow's own tools, and the one tool that asks a person.

Two MCP servers on one loopback listener, built per run, injected into the harness by URL.
`_http.py` carries the bytes and knows nothing about MCP; this module speaks MCP's methods and
knows nothing about sockets; `runner.py` decides what a session is and renders these servers'
addresses into its command line. Everything about *how* a tool call reaches a handler and how an
answer reaches the agent lives here.

## Why a server at all, and why AGL runs it

`docs/codex-cli-findings.md` §0 settles it and the answer is not a preference. The harness accepts
caller-supplied tools **only over MCP**: its richer channel - dynamic tool specifications over its
app-server protocol, which is exactly the shape `AgentTask.tools` wants - is refused by name in the
non-interactive mode this adapter drives, and the binary carries the refusal as a literal string
beside six siblings refusing every approval path. So MCP is the only channel, and MCP means the
harness is the *client*: it connects to a server somebody else is running. There is no in-process
option, and a Python closure over the framework's `Run` cannot be serialised into a subprocess.

Hence a real server, in this process, on the loopback interface, for the length of one run. The
handler runs where it already lives and only the transport changes - which is what
`ports/agent.py` predicted when it refused to make `Tool.handler` transportable: "the right answer
is that the adapter bridges". This module is that bridge and it is the largest single thing this
adapter had to build.

## The asking tool is AGL's own, and the harness's own asker is not available

The harness has a question-asking tool of its own, with a published configuration key whose schema
default is `true` - and it is **refused by name in this mode**, which the shipped binary states in
as many words. Its neighbouring mechanisms are worse rather than better: approvals are all refused
here too and are not questions in any case, and MCP elicitation - a real question mechanism, which
this harness's client does support - is auto-cancelled in this mode with no event on the stream
that could surface one and no channel to answer on.

So the mechanism AGL needs is one AGL supplies, exactly as on the other backend and for a
different reason: not because the harness's own asker was missing from a build, but because it is
switched off by the mode. `MID_RUN_QUESTIONS` for this backend therefore collapses into the
tool-supply question and is not a separate capability of the harness - if a tool call can be made
and answered, an asking tool works.

**Two servers, so that a workflow can name a tool anything it likes.** A tool is addressed as
`mcp__<server>__<tool>`, so a workflow tool called `ask` and AGL's asker would collide on one
server. They are on separate ones instead, which makes the collision unrepresentable rather than
checked-for, and `AgentTask.__post_init__` already refuses duplicates inside the workflow's own
set. One listener carries both, at two paths.

**The 60-second problem, and why `runner.py` raises the timeout.** This harness gives an MCP tool
call `tool_timeout_sec`, which defaults to 60. An asking tool waits on a person. A default that
expires under somebody's thinking time is the specific way this capability dies quietly - the call
fails, the agent is told the tool errored, and it carries on guessing - so the override is not a
tuning knob but the thing that makes the capability real. It is composed in `runner.py`, beside the
rest of the command line, and argued there.

## The adapter never learns which tool is the reporting one

`ports/agent.py` spends a paragraph on this and it is the rule this module is built around. Every
tool below is a `Tool` - the port's own type, including AGL's asker, which is constructed as one
rather than special-cased - and every one is advertised and invoked by the same three lines:
advertise `name`, `description` and `payload_schema`, await `handler`, put `ToolResult.text` back
into the conversation with `rejected` on MCP's own error flag. Nothing here reads a name, a schema
or a payload to decide what a tool *means*. A reporting tool's payload becoming a step's result is
the framework's own handler's job, on the framework's side of the port.

That uniformity is also why the asker being a `Tool` is worth the two lines it costs: the moment
this module had a second way of offering something, it would have a place to put an opinion about
which tools are special.

## What is validated here, and what deliberately is not

**Nothing is checked against `payload_schema`.** The port says the schema "is data, not a type:
this module never validates against it ... the adapter hands it over, and the handler decides what
is acceptable", and AGL has no JSON Schema validator and no dependency that could supply one. The
schema is advertised so the *model* can produce the right shape, and a payload that is wrong
anyway is §3.3's case: the handler refuses it, the refusal goes back into the same conversation,
and the agent corrects itself. This is a real difference from the other adapter, where the vendor's
SDK validates before the handler is reached, and it is a difference in who catches a bad call
rather than in whether one is caught.

**One check is owed and is made**: that the arguments arrived as an object. The port declares a
handler's parameter to be a `Mapping[str, JsonValue]`, and a client that sent an array or a bare
string would otherwise hand a framework handler something it has been promised it cannot get.
"""

from collections.abc import Mapping
from types import MappingProxyType, TracebackType
from typing import Final, Self

from agl.adapters.openai._http import Answer, Listener, token
from agl.ports.agent import QuestionHandler, Tool, ToolResult
from agl.ports.questions import Question
from agl.ports.run import JsonValue

__all__ = ["ASKING_TOOL", "Asking", "Supply"]

# The two server names. `mcp__<server>__<tool>` is how the model addresses a tool - documented, and
# read off this build's own string pool, which carries `mcp__server__tool` as its example - so
# these are part of what the agent sees. They are AGL's own words rather than a vendor's, and the
# other adapter arrived at the same two independently because the reason for splitting them is the
# same on both.
_SUPPLIED: Final = "agl"
_ASKING: Final = "agl_ask"

_ASK: Final = "ask"

# How the asker is addressed. Composed from the two names above rather than spelled out again in
# `runner.py`, which names it in the prompt: `mcp__<server>__<tool>` is the wire, both halves of it
# are this module's, and a second module holding a copy of one is a copy that can drift into
# instructing a model to call a tool no session registers.
ASKING_TOOL: Final = f"mcp__{_ASKING}__{_ASK}"

# The protocol version answered when a client offers nothing readable. A client normally proposes
# one and this module echoes it back - see `_initialize` for why that is the safe direction - so
# this is only ever reached by a client that omitted the field.
_PROTOCOL: Final = "2025-06-18"

# The JSON-RPC code for a method this server does not implement. Answering `resources/list` and
# `prompts/list` this way is correct rather than a gap: those capabilities are not advertised in
# the handshake, and a client that asks anyway is asking about something it was told is not here.
_NO_SUCH_METHOD: Final = -32601

_ASK_DESCRIPTION: Final = (
    "Ask the person running this task a question, and wait for their answer. Use it when a "
    "decision is genuinely theirs to make - which of two approaches to take, whether a proposal "
    "is acceptable - rather than guessing. You may call it as many times as you need; each call "
    "is one question and returns one answer. Waiting is expected and this call will not time out. "
    "If no answer is available you will be told so, and you should then use your own judgement "
    "and carry on."
)

_ASK_SCHEMA: Final[Mapping[str, JsonValue]] = MappingProxyType(
    {
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
)

# What the agent is told when it asks and there is no handler. The port settles the wording's job:
# say that no answer is available and let it carry on with its own judgement. A result rather than
# an error, because nothing went wrong - nobody is listening, which the tool's own description
# already warned it about.
_NOBODY_LISTENING: Final = (
    "No answer is available: this task is running with nobody to ask. Nothing is wrong and this "
    "is not a failure - use your own judgement, decide it yourself, and carry on. Do not wait, "
    "and do not ask again."
)

# What the agent is told when a person answered with nothing at all. `Answer.text` may be empty and
# the port says that means nothing was said, which as a bare tool result would reach the model as a
# blank it has to interpret.
_SAID_NOTHING: Final = (
    "The person answered with nothing at all. Take that as no preference either way, use your "
    "own judgement, and carry on."
)

# What a call with no question in it is told. Nothing validates the payload against the schema here
# (see the module docstring), so this is reached by any call that omitted `question` as well as by
# one that sent an empty string - which `Question` refuses and no view could render.
_NO_QUESTION: Final = (
    "That call asked nothing: `question` was empty or missing. A question is the whole of what a "
    "person sees, so write what you are asking in full and call this tool again."
)


class Asking:
    """The bridge between one tool call and one `QuestionHandler`, for the length of one run.

    Per run and not per runner, because `on_question` is a per-call parameter: one runner serves
    many concurrent tasks - a workflow's two reviewers run at once against the same instance - so a
    handler stored on the adapter could not say which task it was speaking for.

    **`failure` is why this is a class and not a closure.** A handler that raises is not a
    hypothetical: §3.7's headless terminal raises `UpstreamUnavailable` on any view that needs an
    answer, and a workflow's handler may raise `Stop`. Left to itself the model would simply be
    told the tool errored and would carry on, spending an hour of agent time on a run whose asker
    has already failed - so the exception is kept here, the model is told an answer is not
    available so that it does not block either, and `_session.py` ends the run on it as soon as the
    next frame arrives. The first one is kept and later ones are dropped: it is the one that
    explains why the rest went the way they did.
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

    async def answered(self, payload: Mapping[str, JsonValue]) -> ToolResult:
        """Map one payload into a `Question`, await the handler, and hand back the `Answer`.

        Three outcomes, and none of them blocks. A payload with nothing being asked is *refused*
        back to the model, which is §3.3's mechanism used for the adapter's own tool: there is a
        session in flight holding the reasoning that produced the call, and the cheap fix is for
        the model to ask again properly. No handler at all is answered in words, per the port's
        second edge case. Otherwise the handler is awaited and its answer goes back verbatim.
        """
        prompt = payload.get("question")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolResult(text=_NO_QUESTION, rejected=True)
        if self._on_question is None or self.failure is not None:
            return ToolResult(text=_NOBODY_LISTENING)
        self.asked += 1
        try:
            answer = await self._on_question(_question(prompt, payload))
        except Exception as raised:
            self.failure = raised
            return ToolResult(text=_NOBODY_LISTENING)
        return ToolResult(text=answer.text if answer.text else _SAID_NOTHING)


class Supply:
    """Both servers for one run, and the listener under them. An async context manager.

    The lifetime is the point of the shape. The servers must be answering before the harness is
    started, because it connects to them while it is coming up - `startup_timeout_sec` is its
    patience for exactly that - and they must stay answering until it has gone, because a tool call
    can be in flight at any moment until then. `async with` puts both ends in one place, so there
    is no path through `runner.py` on which a run leaves a port open.

    `urls` is what `runner.py` renders into the command line. This module hands over addresses and
    never command-line tokens: which flag carries them, and what else is on that line, is a
    decision about how a session is composed.
    """

    def __init__(self, tools: tuple[Tool, ...], asking: Asking) -> None:
        self._offered = {
            _SUPPLIED: {tool.name: tool for tool in tools},
            _ASKING: {_ASK: _asker(asking)},
        }
        self._path = token()
        self._listener = Listener(
            {
                f"/{self._path}/{name}": _Route(name, offered)
                for name, offered in self._offered.items()
            }
        )

    async def __aenter__(self) -> Self:
        await self._listener.start()
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self._listener.stop()

    @property
    def urls(self) -> Mapping[str, str]:
        """Each server's name and the address the harness should connect to it on.

        A name is what the model sees in front of every tool that server carries, which is why the
        mapping is keyed by it rather than being a list of addresses: `runner.py` composes
        `mcp_servers.<name>` out of the same key, so the name the harness registers and the name in
        `mcp__<server>__<tool>` cannot come apart.
        """
        return {name: f"{self._listener.origin}/{self._path}/{name}" for name in self._offered}


class _Route:
    """The MCP methods one server answers. Five, and everything else is `-32601`.

    Written as a small class rather than a chain of closures because `tools/call` and `tools/list`
    read the same mapping and `initialize` has to answer for the same name - three things sharing
    two values, which is a class.
    """

    def __init__(self, name: str, offered: Mapping[str, Tool]) -> None:
        self._name = name
        self._offered = offered

    async def __call__(self, message: Mapping[str, JsonValue]) -> Answer:
        """One JSON-RPC message. `None` for a notification, which is answered with 202 and no body.

        Presence of `id` and not its truthiness decides that: `0` and `""` are legal request ids,
        and reading a falsy id as "no id" would silently drop the answer to a real request.
        """
        if "id" not in message:
            return None
        ident = message["id"]
        method = message.get("method")
        if method == "initialize":
            return _ok(ident, self._initialize(message.get("params")))
        if method == "tools/list":
            return _ok(ident, {"tools": [_advertised(tool) for tool in self._offered.values()]})
        if method == "tools/call":
            return _ok(ident, _content(await self._called(message.get("params"))))
        if method == "ping":
            return _ok(ident, {})
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "error": {"code": _NO_SUCH_METHOD, "message": f"no method {method!r} on this server"},
        }

    def _initialize(self, params: JsonValue) -> dict[str, JsonValue]:
        """The handshake, answering with the version the client proposed wherever it proposed one.

        Echoing rather than announcing is the safe direction here, and it is a decision. A client
        checks the version it gets back against the ones it knows and hangs up on a stranger, so
        answering with a version this module picked would be the one way a perfectly good session
        fails to start - and there is nothing to lie about, because the surface below is `tools/*`,
        which is spelled identically in every published revision of this protocol. Measured: a
        client proposing `2025-11-25` connected against a server answering `2025-06-18`, so the
        looser answer is not needed to work - it is needed to keep working.
        """
        proposed = params.get("protocolVersion") if isinstance(params, dict) else None
        return {
            "protocolVersion": proposed if isinstance(proposed, str) else _PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self._name, "version": "1"},
        }

    async def _called(self, params: JsonValue) -> ToolResult:
        """Invoke one tool and answer with what it said. Never raises, whatever the handler does.

        Three refusals and one call, and every one of the refusals goes back to the model as a
        *result* rather than as a protocol error. §3.3 is the reason: by the time a call is wrong
        there is a session in flight holding all the reasoning that produced it, and a JSON-RPC
        error is the one answer that gives the model nothing to correct.

        A handler that raises is turned into a refusal carrying what it said, which is what the
        other backend's SDK does with the same situation - so a workflow's tool behaves the same
        way whichever adapter is serving it. `Asking` is the exception and keeps its exception, for
        the reason its own docstring gives.
        """
        if not isinstance(params, dict):
            return ToolResult(text="that call carried no parameters object.", rejected=True)
        name = params.get("name")
        tool = self._offered.get(name) if isinstance(name, str) else None
        if tool is None:
            offered = sorted(self._offered)
            return ToolResult(
                text=f"there is no tool called {name!r} here. This server offers {offered}.",
                rejected=True,
            )
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return ToolResult(
                text=(
                    f"the arguments for {tool.name} arrived as {type(arguments).__name__} and this "
                    f"tool takes a JSON object. Send one and call it again."
                ),
                rejected=True,
            )
        try:
            return await tool.handler(arguments)
        except Exception as raised:  # noqa: BLE001 - the model is told, and the run carries on
            return ToolResult(text=f"{tool.name} failed: {raised}", rejected=True)


def _asker(asking: Asking) -> Tool:
    """AGL's asking tool, as a `Tool` like any other, so that nothing here treats it as special."""
    return Tool(
        name=_ASK,
        description=_ASK_DESCRIPTION,
        payload_schema=_ASK_SCHEMA,
        handler=asking.answered,
    )


def _question(prompt: str, payload: Mapping[str, JsonValue]) -> Question:
    """Whatever the model produced, as the poorest pair that still carries an exchange.

    Two defensive readings, both of which exist because the payload is a model's and `Question`
    refuses what it cannot be asked with. Options that are not non-empty strings are dropped: an
    option is the exact text that goes back as the answer, so an empty one is unpickable in any
    view and a number is not an answer. And free text is left allowed whenever nothing pickable
    survived, which is the port's own instruction and the difference between an open question and
    one nobody could answer.
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


def _advertised(tool: Tool) -> dict[str, JsonValue]:
    """One `Tool` as the entry a client reads off `tools/list`.

    `type` and `properties` are supplied when a schema omits them. The port calls a
    `payload_schema` "a JSON Schema object describing the argument the tool takes", so both keys
    are already what it means; a client that rejects a tool whose schema is missing one would be
    rejecting a tool the port considers perfectly declared. Anything carrying them is passed
    through with nothing added, and nothing here reads any of it.
    """
    schema: dict[str, JsonValue] = dict(tool.payload_schema)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return {"name": tool.name, "description": tool.description, "inputSchema": schema}


def _content(result: ToolResult) -> dict[str, JsonValue]:
    """A `ToolResult` in the shape a tool call answers with.

    `rejected` becomes MCP's own `isError` flag, which is the mechanism's error frame for a tool
    result - so a refusal reaches the model as a refusal rather than as prose it has to notice, and
    §3.3's "corrects itself and carries on" is the mechanism's behaviour rather than something
    argued for in a string.
    """
    return {
        "content": [{"type": "text", "text": result.text}],
        "isError": result.rejected,
    }


def _ok(ident: JsonValue, result: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """One successful JSON-RPC answer, correlated to the request that asked for it."""
    return {"jsonrpc": "2.0", "id": ident, "result": dict(result)}
