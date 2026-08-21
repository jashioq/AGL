"""`FakeAgentRunner` - Claude Code's `AgentRunner` with a script where the model would be.

**A product feature and not a test double** (§1.9). It is what `--dry-run` runs on and half of what
plan target #8 rests on - *every command runs end-to-end on fakes alone, no network, no git* - and
stages 12 to 18 drive whole workflows through it. So the rule `memory_store.py`, `adapters/git/
fake.py` and `adapters/shell/fake.py` each state for their own port is the rule here:

**Wherever the port is silent, this agrees with `ClaudeCodeRunner`.**

A fake more permissive than the real thing lets a workflow pass on fakes and fail in anger, and the
difference stays invisible until the day somebody drops the `--dry-run`. The places the real runner
refuses something are therefore refused here for the same reason and with the same class - a model
it does not serve above all - and the handful of places the two genuinely cannot agree are listed
below rather than left to be discovered. `tests/contracts/agent.py` holds both to what the port
*says*; `tests/adapters/test_claude_code_fake.py` holds this one to the real one everywhere the
port says nothing.

## This module does not import `claude_agent_sdk`, and that is the decision, not an omission

`agl[claude]` is a pip extra (§3.2.1, `ARCHITECTURE.md` §4). `translate.py`, `runner.py`,
`_tools.py` and `_session.py` all import the vendor SDK, so importing any one of them - even for
`translate.model_name`, which is the one function here that would genuinely like to be shared -
would make **this** module unimportable on a machine that ran `pip install agl` without the extra.
That is the exact machine a fake exists for. A workflow author testing a workflow that names
`Claude.OPUS` would have to install the Anthropic SDK in order to run it *without* an Anthropic
model, and `--dry-run` would be a mode you first install a vendor to reach. So the whole of what
this module imports is stdlib and `agl.ports`, and
`tests/adapters/test_claude_code_fake.py::test_this_fake_imports_on_a_machine_with_no_vendor_sdk`
proves it by importing this module in a process where `claude_agent_sdk` cannot be imported at all.

`adapters/rich_terminal/headless.py` decided the same question the same way one stage earlier, and
its reason is the second half of this one: "Sharing machinery is how a fake stops being an
independent witness." Two implementations of one port that share the table that decides which
models are served are one implementation with two front doors, and the contract suite cannot see
the difference.

**What that costs, stated rather than hidden.** The served-model table is now written twice - once
in `translate._MODEL_NAMES` and once as "every member of `ports.agent.Claude`" below - and two
copies can drift. The drift is not left to chance: `test_claude_code_fake.py` asks both runners
about every `ModelId` in the port and fails if they disagree about which are refused, which is the
same device `test_store_parity.py` and `test_git_parity.py` use for the same kind of divergence.
What is not pinned is the *wording* of the refusal; the sentence below is `model_name`'s, copied,
and a cosmetic improvement to one may leave the other behind.

## What a script is, and why it is a callable

    async def script(conversation: Conversation) -> AgentOutcome:
        answer = await conversation.ask(Question("Land it, or keep going?", options=(...)))
        if answer is not None and answer.text == "land it":
            await conversation.call("report_result", {"summary": "landed"})
        return AgentOutcome(stop_reason=None, text=f"done: {answer}")

    runner = FakeAgentRunner(script)

One argument, one type: `Script` is `(Conversation) -> Awaitable[AgentOutcome]`. Everything the
port lets an adapter do during a run is on `Conversation` - ask, call a tool, report activity - and
everything the port lets it answer with is the `AgentOutcome` the script returns, `stop_reason=None`
included. A script is therefore an agent's *conduct*, expressed in the only vocabulary the port has,
and nothing it can express is something a real backend could not do.

**Why a callable and not a list of canned moves.** §3.7's clause is that an answer returns into the
same live session, so a negotiation is N rounds inside one run - which means what happens after a
question has to be able to depend on the answer. A declarative list cannot branch without growing a
conditional of its own, and a list of moves with an expression language in it is a worse programming
language than the one this file is already written in. `await` gives the branch for free and gives
it the shape a real agent's control flow has.

**Why one script for the runner, rather than one per call, per model or per queue.**
`adapters/shell/fake.py` rejected a queue of answers for a reason that is sharper here: `split` runs
its children concurrently against one runner instance, so anything keyed by call order asserts an
ordering the framework never promised and fails on a change to scheduling. The script instead reads
`conversation.task` - instructions, model, workspace, tools, context, `plan_only` - and dispatches
on whatever it likes. One knob, no ordering, and a runner that is safe to share between two
reviewers running at once, because the only per-run state is the `Conversation` built for that call.

**How stage 11 reaches it.** `sdk/` and `adapters/` are siblings and may not import each other
(`ARCHITECTURE.md` §2), so `sdk/testing.py` cannot name `Script` or `Conversation` at all. The
composition root can name both, and is already the only module that may say `new` - so a
workflow-level scripting vocabulary lives in `sdk/`, and `config/container.py` compiles it into one
of these callables on the way to constructing this class. That is a constraint on stage 11's design
and it is recorded here because this module is where somebody would otherwise expect the sugar to
live.

## What an unscripted run does, and why it does not read the prompt

A `FakeAgentRunner` built with no script runs `unscripted`, and the one thing to know about it is
that **it never reads `task.instructions`**. A fake that recognised prompts would be a fake that
passes whichever exam it was shown, and the contract suite's prompts are an exam: it would go green
against them and do nothing recognisable for the workflow author whose prompt it had never seen.

So the default's behaviour is a function of the *task's shape* and of what it is answered, never of
what it is asked:

  * **It asks while it is still learning something.** One question, and another for as long as each
    answer is one it has not already been given, to a ceiling. An unscripted run has no task of its
    own to pursue, so the only thing it can do with an answer is find out whether there is more to
    hear; a repeated answer is the handler saying the same thing twice, which is where a negotiation
    ends. With no handler at all it asks once, is told nobody is listening, and carries on - which
    is the port's second edge case exercised on every default run rather than only when a test
    remembers to.
  * **It calls every tool the task declares, in declaration order, once each** - and again, with
    what it was told, for as long as the result comes back rejected. Every tool identically: this
    module never learns which one is the reporting one, which is `ports/agent.py`'s rule and not an
    economy. The payload is composed from the tool's own `payload_schema`, because a step whose
    reporting tool is handed `{}` fails on `--dry-run` for a reason that has nothing to do with the
    workflow.
  * **It says what it did**, including the last answer it was given, verbatim, and nothing else -
    it has read no file and has nothing else to report.

## What this fake cannot do, listed rather than left to be found

  * **It changes nothing in the workspace.** Its scripted agent asks, calls and speaks; it does not
    edit files or run a shell, so a workflow whose next step reads what the agent wrote sees an
    empty diff. `capabilities()` still reports `FILE_EDIT` and `SHELL`, because that answer is what
    preflight admits a run on and a fake that reported less would have every `--dry-run` of a
    realistic role refused at second zero - which is target #8 dead for the sake of a technicality
    about a fake. `capabilities()` is "what can this backend be asked for", and the backend this
    stands in for can be asked for all four.
  * **It enforces no `Restriction`, and does not pretend to.** The port gives a backend with no
    mechanism two honest moves - say it to the agent in words, or refuse the task - and neither is
    available: there is no model to instruct, and refusing every restricted task would make this
    unusable for exactly the roles a real workflow declares. What is true instead is that nothing
    this module does is anything a `Restriction` forbids. A *script* holds `task.workspace` and can
    of course write to it with the stdlib, but that is the caller's own code rather than this
    adapter's agent, and a guard here would be this module claiming a boundary it does not have.
  * **A script's tool payload is not checked against the tool's `payload_schema`.** In a real
    session the SDK validates against the schema and a malformed call never reaches the handler.
    Validating JSON Schema is a language this adapter does not speak - `ports/agent.py` says the
    schema "is data, not a type" - and a hand-rolled subset would refuse payloads a real session
    accepts as readily as it waved through ones it should have refused. It *is* held to being JSON,
    for the reason `call` gives.
  * **The two argv refusals have nothing to refuse.** `ClaudeCodeRunner` turns down a model name or
    a deny rule that would parse as a flag when it reached a command line, and takes a `cli_path` to
    apply the same rule to. Nothing here reaches a command line and there is no CLI to point at, so
    there is no constructor argument for one: `adapters/shell/fake.py` settles that shape - taking a
    value "so the signatures matched would be accepting a value this class could only ignore". This
    is where the fake is deliberately more permissive, it is one shape of divergence rather than
    three, and the parity test pins it.
  * **A question handler that raised stops the *default* and cannot stop a script.** `_session.py`
    breaks out of its stream at the very next message, so a real run does no further work once its
    asker has failed; `unscripted` does the same, and a supplied script runs to its end because
    there is no way to interrupt somebody's coroutine that a `try` in it could not swallow. Either
    way `run` raises the handler's exception in place of an outcome, which is the half a caller can
    see and the half that decides a workflow's exit code.
  * **`check_ready` cannot fail.** There is nothing to install, nothing on `PATH` and nobody to
    authenticate against. Simulating `UpstreamUnavailable` on some invented condition would be
    inventing the one thing this class has no evidence about, which is `adapters/shell/fake.py`'s
    argument for the same absence.

## Hermeticity (§3.5) is satisfied by construction, and the contract suite says so about itself

Nothing here opens a file, reads an environment variable or resolves a configuration, so the
poisoned repository cannot catch it doing anything: `tests/contracts/_agent_hermeticity.py` states
in writing that "against a fake runner this test is trivially satisfied", that this is "not a reason
to weaken the test", and that its value is at the real adapter. It runs against this class
unmodified and unweakened, and it is genuinely green here for the reason it names - the imports at
the top of this module are the whole of what it can do, and they are stdlib and `agl.ports`.
"""

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Final, cast

from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    Claude,
    ModelId,
    QuestionHandler,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.errors import InputError
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue

__all__ = ["Conversation", "FakeAgentRunner", "Script", "unscripted"]

# What this backend can be asked for, written out member by member rather than as
# `frozenset(Capability)`, and identical to `runner.py`'s list. Spelling it as "all of them" would
# make a fifth member added to the port a capability this fake silently claims and the real adapter
# does not - a fake more permissive than the real thing, arriving through a line nobody edited.
_CAPABILITIES: Final = frozenset(
    {
        Capability.FILE_EDIT,
        Capability.SHELL,
        Capability.MID_RUN_QUESTIONS,
        Capability.TOOL_CALLING,
    }
)

# How many distinct answers the default will collect before it stops asking, and how many times it
# will re-call a tool that keeps refusing it. Higher than any clause in the port asks for, and low
# enough that a handler which answers differently forever is a test that fails rather than a suite
# that hangs - a fake must never be the thing that loops, which is the outcome the port calls the
# worst one available.
_ROUNDS: Final = 8

# What the default asks, and it is deliberately about the run rather than about the task: this
# module has not read `instructions` and has nothing to ask about them. No options and free text
# allowed, which is what an open question looks like and the one shape every backend can ask.
_QUESTION: Final = (
    "AGL is running this task on its Claude Code fake, with a script where the model would be. "
    "Is there anything this run should be told before it goes on?"
)

# What goes in a string-shaped slot of a composed payload before anything has refused one. Says
# what produced it, so that a handler logging what it was given produces a line a reader can place.
_PLACEHOLDER: Final = "AGL's Claude Code fake produced this: no model was involved."

# The default's closing message, and the whole of what it claims to have done.
_CLOSING: Final = (
    "AGL's Claude Code fake ran this task with a script where the model would be. It read nothing "
    "in the workspace and changed nothing there."
)


class Conversation:
    """One run in flight, as the script sees it: the task, and the three things an adapter may do.

    Built per call and never per runner, for the reason `_tools.py` gives for building its own
    asking bridge per call: `on_question` and `on_activity` are per-call parameters, one runner
    serves a workflow's two concurrent reviewers, and a handler stored on the adapter could not say
    which task it was speaking for. A script is therefore re-entered once per run and must hold no
    state of its own between them; everything that belongs to one run is here.

    There is no `read`, no `write` and no `shell`. The port's whole surface during a run is a
    question, a tool call and an activity line, and a method here that is not one of those three
    would be a thing a script could do that no `AgentRunner` promises.
    """

    def __init__(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> None:
        self.task = task
        """What the run was asked for, unchanged. A script dispatches on whatever part it likes -
        the model, the tools, the workspace, `plan_only` - which is what makes one script enough
        for a whole workflow's worth of steps."""

        self.failure: Exception | None = None
        """The first exception a question handler raised, or `None`.

        Public for the reason `_tools.Asking.failure` is: `run` reads it to decide whether this run
        ends with an outcome or with that exception, and a test reads it to see that a handler
        which raised was not asked again. `Exception` and not `BaseException`, exactly as there -
        `asyncio.CancelledError` means the task around this run is being torn down, and catching it
        would answer politely while the caller waited for a cancellation that never landed."""

        self._on_question = on_question
        self._on_activity = on_activity
        self._tools: dict[str, Tool] = {declared.name: declared for declared in task.tools}

    async def ask(self, question: Question) -> Answer | None:
        """Put `question` to the handler and hand back its `Answer`, or `None` if nobody answered.

        **`None` is the port's second edge case, made unforgettable by the type.** "If the agent
        asks while `on_question` is `None`, the adapter must **not** block. It tells the agent that
        no answer is available and lets it carry on with its own judgement." A real session says
        that in words, because words are the only channel a tool result has; a script is not a model
        and would have to recognise a sentence to act on one, so it is said in the return type
        instead - and `mypy --strict` then makes a script that carries on regardless impossible to
        write by accident. Nothing here waits for anything under any circumstance.

        A handler that raises is kept rather than propagated from here, and `FakeAgentRunner.run`
        raises it in place of returning an outcome. That is `_tools.py` and `_session.py`'s
        behaviour and it is not an implementation detail of theirs: §3.7's headless terminal raises
        `UpstreamUnavailable` on any view that needs an answer and a workflow's handler may raise
        `Stop`, so a fake that swallowed either would turn a run that dies in anger into a run that
        passes on fakes. Once one has raised, later questions are answered `None` without calling it
        again - the same "do not spend the rest of the run on an asker that has already failed".
        """
        if self._on_question is None or self.failure is not None:
            return None
        try:
            return await self._on_question(question)
        except Exception as raised:
            self.failure = raised
            return None

    async def call(self, tool: str, payload: Mapping[str, JsonValue]) -> ToolResult:
        """Invoke `tool`'s handler with `payload` and hand back what it said, refusal included.

        The `ToolResult` comes straight back to the script, which is §3.3's mechanism rather than a
        convenience: a refused payload is "rejected back to the model inside the same conversation,
        so it corrects itself and carries on. Not an adapter retry, not a workflow retry, and not an
        exception." A script reads `rejected` and `text` and calls again, inside this same run.

        Nothing reads the tool's name, its description or its schema to decide what it *means* -
        `ports/agent.py` spends a paragraph on why an adapter must never learn which tool is the
        reporting one, and this module is built around it.

        **The payload makes a round trip through JSON on the way in**, which does three jobs at
        once and is `memory_store.py`'s argument in another port's clothes. It refuses what a model
        could not have produced - a non-`str` key, a `NaN`, an object with no JSON spelling - so a
        script cannot hand a handler something no real session could deliver. It hands the handler
        containers that share nothing with the script's own, as the real path does by construction,
        because there the mapping was parsed out of the wire. And it is the same JSON the step's
        result is written down as (§3.6), so a payload this accepts is one the store can hold.

        `InputError` for both refusals: a tool nobody declared and a payload that is not JSON are
        the caller's, nothing has been attempted, and exit 2 sends the reader to the script they
        wrote. A tool the task did not declare is worth refusing rather than accepting quietly -
        a real session registers exactly `task.tools`, so a call to anything else is not something
        a model could have done, and letting it work here is how a workflow comes to depend on a
        tool it never declared.
        """
        declared = self._tools.get(tool)
        if declared is None:
            known = sorted(self._tools)
            raise InputError(
                f"this task declares no tool called {tool!r}: it declares {known}. A session "
                f"registers exactly the tools the task carries, so a call to anything else is not "
                f"a move any agent could have made, and a script that can make it is a script that "
                f"proves a workflow works with a tool the workflow never declared"
            )
        return await declared.handler(_as_json(payload, tool))

    def report(self, line: str) -> None:
        """Say what is happening right now, or do nothing when nobody asked to be told.

        Passed through untouched (§3.7): the port refuses an `Activity` type and any shape imposed
        on what an adapter may say, so a script's own words arrive as a script's own words.

        Not guarded, deliberately, and for `_session.py`'s reason: the port puts the obligations on
        the caller - it must not block, and it may be called never - and says nothing about an
        exception out of one. Swallowing it here would hide a broken reporter for the length of a
        run, and would hide it only on fakes.
        """
        if self._on_activity is not None:
            self._on_activity(line)


type Script = Callable[[Conversation], Awaitable[AgentOutcome]]
"""What an agent does, in the only vocabulary the port has. See the module docstring.

One parameter because a `Conversation` already carries the task and the two callbacks, and an
`AgentOutcome` out because that is the whole of what the port answers with - which is what makes a
`stop_reason` of `None` something a script simply returns rather than something this class needs a
switch for."""


async def unscripted(conversation: Conversation) -> AgentOutcome:
    """What a `FakeAgentRunner` with no script does. It never reads `task.instructions`.

    The module docstring argues the whole of it and this is the shape: ask while each answer is new,
    then call every declared tool once and again for as long as it is refused, then say what it did
    and stop. Every number here comes from the port's own clauses or from the task's shape, and
    nothing at all comes from the words the task carries - a default that recognised a prompt would
    pass whichever exam it had been shown and do nothing for the prompt it had not.

    Exported so that a script can delegate to it - "the usual thing, and then one more tool call" -
    and so that what the default does is a function somebody can read rather than a behaviour that
    only shows up in a transcript.
    """
    heard: list[str] = []
    while len(heard) < _ROUNDS:
        conversation.report("Ask: whether there is anything this run should be told")
        answer = await conversation.ask(Question(prompt=_QUESTION))
        if answer is None or answer.text in heard:
            break
        heard.append(answer.text)

    called: list[str] = []
    for declared in conversation.task.tools:
        # An asker that has already failed stops the work rather than costing an hour of it -
        # `_session.py` breaks out of its stream at the very next message for the same reason. A
        # supplied script decides this for itself, which is the one place the two cannot agree.
        if conversation.failure is not None:
            break
        said = _PLACEHOLDER
        for _ in range(_ROUNDS):
            conversation.report(f"{declared.name}: {said}")
            result = await conversation.call(declared.name, _payload(declared.payload_schema, said))
            called.append(declared.name)
            if not result.rejected:
                break
            # What a fake can honestly do with a refusal: say back what it was told, so that the
            # next call is visibly not the last one repeated. A model reads the refusal and works
            # out a better payload; this has no way to, and pretending otherwise would be the
            # fiction §1.9 is about.
            said = result.text

    return AgentOutcome(stop_reason=StopReason.COMPLETED, text=_said(heard, called))


class FakeAgentRunner(AgentRunner):
    """`AgentRunner` over a script: the whole port, with nothing behind it that costs a token.

    Constructed the way `ClaudeCodeRunner` is - by `config/container.py`, once, and reached only
    through the port - so a bundle swaps one for the other and nothing above notices. The one
    constructor argument is what the agent does; there is no CLI path, because there is no CLI.

    It holds the script and nothing else: no record of what it was asked, no count of runs, no last
    outcome. `adapters/shell/fake.py` argues that absence at length and the argument carries here -
    a recorder would be a surface tests could assert against that no real implementation has, and
    what a test wants to know is already held by the tool handlers and question handler it supplied
    itself.
    """

    def __init__(self, script: Script | None = None) -> None:
        """`script` is what the agent does, or `None` for `unscripted`.

        A default rather than a required argument, and that is `--dry-run`'s requirement rather
        than a convenience: nothing scripts an agent on the way to running a whole workflow on
        fakes, and a runner that refused to run without a script would make target #8 reachable
        only by writing an agent for every step first.
        """
        self._script: Final = script if script is not None else unscripted

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        """What this fake can be asked for when serving `model`. The same answer every time.

        The four `ClaudeCodeRunner` reports, for the reason the module docstring gives: this stands
        in for that backend, preflight admits a run on this answer, and a fake reporting less would
        have every `--dry-run` of a role that requires file editing refused at second zero.

        The model is checked and then not consulted, exactly as it is there - answering "I can do
        all four" for a model this runner would refuse to run is the kind of preflight answer that
        gets a run admitted and then killed one moment later.
        """
        _served(model)
        return _CAPABILITIES

    async def check_ready(self, model: ModelId) -> None:
        """Whether this fake can serve `model` right now. It always can, and here is why.

        There is nothing to install, nothing to resolve on `PATH` and no far side to authenticate
        against, so the one refusal the port allows this member is unreachable. Inventing a
        condition to fail on - a workspace that is not there, a model that is out of favour - would
        be simulating the one thing this class has no evidence about, which is
        `adapters/shell/fake.py`'s argument for the same absence.

        An unserved `ModelId` still refuses, and that is not a statement about the backend: it is
        §3.2's "an adapter handed a `ModelId` it does not serve raises `InputError`", refused before
        anything is attempted, and the real runner refuses it here too.
        """
        _served(model)

    async def run(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        """Run the script against `task` and answer with whatever it returns.

        The model is checked first and before anything else, because `ClaudeCodeRunner` checks it
        before anything else: a run of a model this adapter does not serve must fail identically on
        fakes, or preflight is the only thing standing between a workflow and a step that would
        have died in anger.

        A question handler that raised is raised from here in place of the outcome - see
        `Conversation.ask`. The script's own exceptions are not caught at all: a script is the
        caller's code, in the same way a tool handler is, and a fake that translated a bug in
        somebody's script into an `AglError` would be reporting it as a backend failure.
        """
        _served(task.model)
        conversation = Conversation(task, on_question=on_question, on_activity=on_activity)
        outcome = await self._script(conversation)
        if conversation.failure is not None:
            raise conversation.failure
        return outcome


def _served(model: ModelId) -> None:
    """`model` is one this fake serves, or `InputError` - `translate.model_name`'s refusal.

    Every member of `Claude` and nothing else, which is the same set `translate._MODEL_NAMES` holds
    and is derived from the port rather than copied out of it, because a copied table goes stale
    silently and this one cannot. The module docstring argues why the two are separate at all and
    what pins them together; the sentence below is `model_name`'s, deliberately, so that a workflow
    author who named an unserved model reads the same explanation whichever runner they hit.
    """
    if not isinstance(model, Claude):
        served = sorted(str(member) for member in Claude)
        raise InputError(
            f"the Claude Code fake cannot run {str(model)!r}: it serves {served} and nothing "
            f"else. It will not stand in another model for this one - the model was named beside "
            f"the prompt because the choice was semantic, and substituting answers a different "
            f"question than the one the workflow asked"
        )


def _as_json(payload: Mapping[str, JsonValue], tool: str) -> dict[str, JsonValue]:
    """`payload` as the fresh JSON tree a real session's handler would have been handed.

    See `Conversation.call` for the three jobs this does. `allow_nan=False` because a bare `NaN` is
    not JSON, comes back unequal to itself, and `ports/run.py` refuses it for that reason - so a
    payload carrying one is a payload the step's own result could never be written down as.
    """
    try:
        return cast(dict[str, JsonValue], json.loads(json.dumps(payload, allow_nan=False)))
    except (TypeError, ValueError) as unwritable:
        raise InputError(
            f"the payload for tool {tool!r} is not JSON: {unwritable}. A tool call reaches a real "
            f"handler as JSON a model produced, and a step's result is written down as JSON "
            f"(§3.6), so a payload that cannot be one is a call no run could have made"
        ) from unwritable


def _payload(schema: Mapping[str, JsonValue], said: str) -> dict[str, JsonValue]:
    """A payload for a tool declaring `schema`, with `said` in every slot that takes text.

    The required properties and nothing else, because they are the whole of what a schema says
    *must* be there and an optional one is optional. A schema this cannot read - no `properties`, no
    `required`, or neither - produces `{}`, which is what a tool taking no argument is called for
    in JSON Schema and the honest answer for a shape this module has no reading of.

    This is not validation and it is not a schema language. It is the one thing the default cannot
    do without: a reporting step's result is its reporting tool's payload (§3.3), so a `--dry-run`
    whose every tool call was `{}` would fail every reporting step in the workflow for a reason
    that has nothing to do with the workflow. `Conversation.call` says why nothing checks a
    *script's* payload against the same schema.
    """
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        return {}
    return {
        name: _value(properties[name], said)
        for name in required
        if isinstance(name, str) and name in properties
    }


def _value(described: JsonValue, said: str) -> JsonValue:
    """One value of the kind `described` asks for, or `said` where text will do.

    An `enum`'s first member wins over its `type`, because a schema that lists the acceptable
    values has already answered the question and a placeholder string would be refused by any
    handler that meant it. Everything else is the seven JSON Schema primitives and a `type` this
    does not recognise falls through to text, which is the kind most likely to be read rather than
    computed with.
    """
    if not isinstance(described, dict):
        return said
    choices = described.get("enum")
    if isinstance(choices, list) and choices:
        return choices[0]
    kind = described.get("type")
    if isinstance(kind, list):
        kind = next((one for one in kind if isinstance(one, str)), None)
    if kind == "object":
        return _payload(described, said)
    if kind == "array":
        return []
    if kind in ("integer", "number"):
        return 0
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return said


def _said(heard: list[str], called: list[str]) -> str:
    """The default's closing message: what it was told, what it called, and nothing invented.

    The last answer goes in verbatim, which is §3.7's clause seen from the outside - an answer that
    reached the session and changed nothing about what came back is worth less than not asking -
    and it is the only text here that came from anywhere but this module. Nothing from the
    workspace appears, because nothing from the workspace was read.
    """
    parts = [_CLOSING]
    if heard:
        parts.append(f"The last answer it was given was: {heard[-1]}")
    if called:
        parts.append(f"It called: {', '.join(called)}.")
    return " ".join(parts)
