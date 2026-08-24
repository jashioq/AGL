"""The scripting vocabulary a workflow author writes an agent in: `Reply`, `Call` and `Agent`.

The half of the test harness that lives in `sdk/`, and the split is forced rather than chosen.
`.importlinter`'s contract 1 puts `sdk` below `config`, so nothing here can import the composition
root and nothing here can build a bundle - building one is a composition act. So the *builder* is
`agl/testing.py`, a top-level module beside `api.py`, and what stays here is the vocabulary: what an
agent does for one task, said in ports vocabulary and in no vendor's.

**And it cannot name the fakes' scripting types.** `adapters/claude_code/fake.py` states the
constraint under "How the workflow-facing vocabulary reaches it": `sdk/` and `adapters/` are
siblings and may not import
each other (`ARCHITECTURE.md` §2), so `Script` and `Conversation` are not names this module may
write. What it may write is everything in `ports/` - `AgentTask`, `Question`, `Answer`, `Tool`,
`ToolResult`, `StopReason`, `JsonValue` - which is exactly the vocabulary an agent's conduct is
expressible in, because it is the vocabulary the port itself speaks. `config/container.py` compiles
a `Reply` into the callable each fake consumes, which is the one module allowed to name both sides.

## Why a value and a plain callable, where the adapters' `Script` is a coroutine

Both fakes take `(Conversation) -> Awaitable[AgentOutcome]` and each argues at length that a
callable is right for *them*: "a negotiation is N rounds inside one run - which means what happens
after a question has to be able to depend on the answer", and `await` gives that branch for free.
That argument is about the adapter's own seam and it stands. This layer answers a different
question, which is what a **workflow author** should have to write to test their workflow:

    def agent(task: AgentTask) -> Reply:
        if any(tool.name == "report_findings" for tool in task.tools):
            return Reply(calls=[Call("report_findings", {"summary": "two", "high": 2})])
        return Reply(says="implemented it")

A plain function from a task to a value. The dispatch is an `if` in the author's own file rather
than a table this module would have to invent, so branching on the model, the tools, the workspace,
`context` or `plan_only` costs nothing and needs no vocabulary from here at all - which is the same
reason both fakes give for taking one script per runner rather than a queue: "the script instead
reads `conversation.task` ... and dispatches on whatever it likes". And what it returns is a value,
so it is comparable, printable, and constructible in the body of a `pytest.mark.parametrize`.

**Sync, not async.** Nothing an author computes between reading a task and describing a reply needs
to await anything, and a coroutine here would make the simplest possible agent - `lambda task:
Reply(says="done")` - impossible to write on one line.

## There is no step name on `AgentTask`, so this is what an author keys on

Worth stating outright, because it is the first thing somebody reaches for. A task carries
`instructions`, `workspace`, `model`, `restrictions`, `tools`, `context` and `plan_only`, and
**which step it belongs to is not among them** - deliberately, since `ports/agent.py` keeps AGL's
own ledger vocabulary out of the port and an adapter has no business knowing what a step is. So an
agent dispatching per step keys on what the *role* made visible, and there are two good handles:

  * **the reporting tool's name**, which is the sharpest one: a role reports through exactly one
    tool (`sdk/tools.py`), the author named it, and `task.tools` carries it under that name;
  * **the model**, which is how §3.3's own `fix` splits its two roles - Claude implements, OpenAI
    reviews - and is one comparison against `task.model`.

`instructions` works too and is the least stable of the three, being prose the author is going to
edit. None of this is a shortage to be repaired here: a `step` field on `AgentTask` would be the
framework telling every adapter what a step is, in a port that has spent several paragraphs not
saying so.

## What a negotiation costs, said plainly

§3.7's negotiation is N rounds inside one session, and what happens in round two depends on what the
handler answered in round one. **A `Reply` cannot express that**, and no arrangement of declarative
fields could: the questions are a list computed before the run, so the answers have nowhere to go.
`Reply.asks` therefore puts each question to the handler in order and reads the answers for the
handler's benefit rather than for the agent's - which is enough to prove that a workflow's screen is
reached, that its handler runs, and that its answer arrives, and is not enough to prove that an
agent *changed its mind*.

The escape hatch is named rather than implied, and it is not a downgrade:
`container.fakes(claude=..., openai=...)` still takes a raw `Script` per provider, which is the full
`await`-shaped seam both fakes were built around, and `agl.testing.over()` takes a bundle built
that way and gives it the same harness. So this vocabulary is the ergonomic path and never the only
one. What stage 17's `fix` needs is
one question screen and one answer, which is inside what a `Reply` says; a workflow whose prompt
negotiates until approved is written with a script.

## Refusals

`InputError`, at declaration time, which is `arg()`'s register and `@workflow`'s and
`reporting_tool()`'s: everything below is typed by whoever is writing the test, and exit 70 would
send them looking for a bug in the framework. There is exactly one, and it is `Call`'s: a tool with
no name is a call no session could carry, and the fakes refuse it too - one layer down, and after
the run has started.

Nothing here checks a payload against a tool's `payload_schema`, and that is both fakes' decision
inherited rather than re-made: "the port says the schema is data, not a type", AGL has no schema
validator, and a hand-rolled subset would refuse payloads a real session accepts. What does check it
is the reporting tool itself, inside the run, by rejecting the call - which is the behaviour a test
about a malformed payload wants to observe anyway.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from agl.ports.agent import AgentTask, StopReason
from agl.ports.errors import InputError
from agl.ports.questions import Question
from agl.ports.run import JsonValue

__all__ = ["Agent", "Call", "Reply"]

# What a call that takes no arguments defaults to. A proxy rather than `{}` because `dataclasses`
# refuses a mutable default outright, and rather than a `default_factory` because it never survives:
# `__post_init__` copies every payload into a fresh `dict`, this one included, for the reason that
# field's docstring gives at length. So this object is read once per default and never stored.
_NO_PAYLOAD: Final[Mapping[str, JsonValue]] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Call:
    """One tool call an agent makes: which tool, and the arguments it sends.

        Call("report_findings", {"summary": "two problems", "high": 2})

    **The payload is a mapping and not the dataclass the reporting tool declares**, on purpose: what
    a model sends is JSON, `sdk/tools.py` derives the tool's schema from the payload type precisely
    so that the model is shown the shape, and a `Call` carrying an already-built instance would be
    testing a conversion no session performs. Writing the mapping is also how a test about a
    *malformed* payload is written at all - the tool rejects it inside the run, which is §3.3's
    correction path and the thing worth watching.

    Frozen and slotted for `Role`'s reason: a `Reply` is routinely a module-level constant shared by
    every task a test dispatches, so a call that could be edited by one of them would be edited for
    all of them.
    """

    tool: str
    """The tool's name, exactly as the role declared it - `report_findings`, not the object.

    A `str` rather than the `ReportingTool` itself, because a role's plain `Tool`s are callable too
    and a field admitting both would be a union every reader has to narrow. `REPORT.name` is what an
    author writes when they have the declaration to hand, and it is one attribute."""

    payload: Mapping[str, JsonValue] = _NO_PAYLOAD
    """The arguments, as JSON. Empty is ordinary - a tool may take none.

    Copied on the way in, which is `ports/store.py`'s rule about any mapping a caller hands over: an
    author reusing a builder dict between two `Call`s would otherwise find both of them holding
    whatever the dict said last. The copy is a plain `dict` and **deliberately not a
    `MappingProxyType`**, where `Tool.payload_schema` is one: a payload goes through
    `json.dumps(payload, allow_nan=False)` inside both fakes on its way to the handler, and
    `json.dumps` has no encoder for a proxy - so freezing it here would make every scripted call a
    refusal that named the payload rather than the freezing. §3.6's rule 4 records the same trap one
    layer down, where the journal's walker has to handle `Mapping` recursively for exactly this
    reason. The field's declared type is a `Mapping`, so nothing reading it can write through it
    anyway."""

    def __post_init__(self) -> None:
        if not self.tool:
            raise InputError(
                "a `Call` with an empty tool name names nothing a session could route: a model "
                "calls a tool by the name the role declared it under, and both agent fakes refuse "
                "a call to a tool the task does not declare - refused here, the line that needs "
                "fixing is the one on screen rather than one inside a run"
            )
        object.__setattr__(self, "payload", dict(self.payload))


@dataclass(frozen=True, slots=True)
class Reply:
    """What an agent does for one task: what it reports, what it asks, what it says, how it ends.

        Reply(
            activity=["Edit: src/auth.py"],
            asks=[Question(prompt="Land it, or keep going?")],
            calls=[Call("report_findings", {"summary": "clean", "high": 0})],
            says="reviewed the change",
        )

    Every field is something the port lets an adapter do during a run, and there is nothing here
    that a real backend could not have done - which is the same test `adapters/claude_code/fake.py`
    applies to its own `Conversation`: "a method here that is not one of those three would be a
    thing a script could do that no `AgentRunner` promises". Three of them are the three, and the
    last two are the `AgentOutcome` a run answers with.

    **The order is fixed and it is the one thing a value cannot vary**: every activity line, then
    every question, then every call. An agent that reports, calls, reports again and then calls
    again is a raw script; the module docstring names that escape hatch and this is the other place
    it is wanted. `config/container.py::_performs` is where the order is performed and is the only
    place it is written down.

    Frozen and slotted for `Call`'s reason, and every sequence is normalised to a tuple on the way
    in so that a list the author goes on appending to cannot change what an agent already did.
    """

    calls: Sequence[Call] = ()
    """The tool calls, in order. A reporting step's result is the payload of its reporting tool
    (§3.3), so a reporting step whose agent's `Reply` has no `Call` for that tool records nothing
    and fails with `RoleIncompleteError` - which is the same thing a real agent that forgot to
    report does, and is worth testing on purpose."""

    asks: Sequence[Question] = ()
    """What the agent stops to ask, in order, each put to the role's `on_question` handler.

    A handler that raises ends the run with that exception rather than an outcome, which is both
    fakes' behaviour and how a workflow's `Stop` from inside a screen reaches the caller. With no
    handler declared, each question is answered "nobody is listening" and the agent carries on -
    the port's second edge case, exercised by writing one question here.

    What the answers were is not available to the rest of this `Reply`; the module docstring argues
    why, and what to write instead."""

    activity: Sequence[str] = ()
    """What the agent reports it is doing - §3.7's `run.activity`, in the adapter's own words.

    Passed through untouched, because the port refuses an `Activity` type and any shape imposed on
    what an adapter may say. Live-only and never persisted, so a step replayed from the ledger
    reports none of these, correctly."""

    says: str = ""
    """The agent's closing message - `AgentOutcome.text`. `""` means it said nothing.

    A default here where the port has none, and the difference is who is writing it: `AgentOutcome`
    refuses defaults so that an *adapter* has to state both fields rather than fall into them, and
    an author describing an effect step's agent has genuinely nothing to say."""

    stop_reason: StopReason | None = StopReason.COMPLETED
    """Why it stopped. `COMPLETED` by default - the agent ended its own turn.

    `LIMIT` is what a backend stopping an agent against its will looks like, and it is worth writing
    when the test is about a reporting step that ran out of turns: `RoleIncompleteError`'s message
    reads this to decide whether to send the reader to the limit or to the prompt. `None` says the
    backend did not say, which is a thing a real one may do and this is how to model it."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "calls", tuple(self.calls))
        object.__setattr__(self, "asks", tuple(self.asks))
        object.__setattr__(self, "activity", tuple(self.activity))


type Agent = Callable[[AgentTask], Reply]
"""What a workflow's agents do, as one function of the task in front of them.

One parameter, because an `AgentTask` is the whole of what a backend is handed and dispatching on
any part of it is an ordinary `if`. One agent covers a whole workflow, both providers included -
there is no vendor's name anywhere in this type - which is what lets `container.fakes(agent=...)`
take one argument and serve every role a run addresses.

The return is a value rather than an awaitable for the reason the module docstring gives, and
`Reply` is the only thing it may be: a function returning `None` for "do nothing" would make the
one case that matters - a reporting step whose agent never reports - unwriteable, since that is
`Reply()` and not the absence of a reply."""
