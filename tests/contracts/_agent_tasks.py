"""What the suite hands a runner - a workspace, a task, two callbacks - and a deadline round a run.

A contract suite has one knob per implementation and builds everything else itself (`store.py` says
why at more length), so every task below is assembled here out of the port's own types. An
implementer supplies a runner and the model it serves, and nothing else: no prompt, no tool, no
workspace, and no way to point the suite at the task an implementation happens to be good at.

**The workspace is a real directory, and that is not the backdoor it looks like.** The store suite
refuses `Path` outright, because `Store` never speaks one. `AgentTask.workspace` *is* a `Path`, it
is refused unless absolute, and the hermeticity clause is a statement about what a directory
contributes - so a suite for this port that would not touch a filesystem could not assert the
promise this port most needs asserted. Everything past that is still refused: nothing here knows how
an adapter starts an agent, what it writes, whether it starts a process, or whether it is local.

**The workspace is deliberately not a git checkout.** A real one is - `WorkspaceProvider` cuts one
- and building one here would mean running `git` from a contract suite - a binary this port never
mentions, in a suite whose whole discipline is asserting nothing the port did not promise, and a
second thing to be installed before an implementation can be judged. `workspace` below is the one
place that changes if a harness turns out to refuse a directory that is not a repository, and
nothing else in the suite knows the difference.

**Every task declares no restrictions.** A suite that asked for `NO_FILE_WRITES` would be asking an
adapter to enforce something the suite then cannot check: the port explicitly lets a backend with no
mechanism put a restriction to the agent as an instruction, so a dropped restriction and an agent
that simply did not write a file look identical from out here. Asking for nothing is the honest
position, and `contracts/agent.py` lists it among what this suite does not prove.

**The prompts are instructions to a model, so they are written like instructions to a model** -
numbered, literal, and saying what to reply with. Two tests read what the agent did as evidence
about the adapter (a rejected call retried, a failed call not retried), and there is no other way to
see those clauses from outside. Vague prompts would make those tests flaky against correct adapters,
which is a way of teaching a reader to ignore them.

**There is no asking prompt here any more, and its absence is the deliberate half.** Two used to
sit at the bottom of this file - one ordering the agent to ask twice, one ordering it to ask with
nobody listening - and they drove a tool AGL supplied to every task on every backend. That tool is
gone: a question is an ordinary tool a *workflow* declares, so what an agent may ask is now a fact
about the role that ran it and not about the port, and a contract suite that shipped its own asking
prompt would be asserting a mechanism no implementation is obliged to have. What survives of that
clause is `Notes` and the two tool prompts, which is where it always was: a question reaching a
person is a tool call whose handler happens to block on one.
"""

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final
from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    ModelId,
    Tool,
    ToolResult,
)
from agl.ports.run import JsonValue

# A deadline around every run, and not a performance assertion. The port makes no promise about
# time at all - `AgentTask` refuses to carry a timeout, because an agent verifying its own work is
# unbounded by design - so this bound is the suite's own and exists for one reason: an await with no
# end looks exactly like an agent that is still thinking, and a suite unwilling to stop waiting
# reports a hung adapter as a slow one and then as nothing at all, because somebody kills it by
# hand. It is generous, so anything over it is not slowness, it is a run that is never coming back.
#
# The port used to make one promise here - that an adapter must not block on a question nobody was
# listening for - and this comment was written for it. That clause went with `on_question`: a
# question is an ordinary tool the workflow supplies now, so there is no framework-supplied
# mechanism an agent can call into with nothing behind it. The deadline outlived the clause because
# any handler an adapter awaits can fail to come back, and a tool handler is the caller's code.
RUN_DEADLINE: Final = 300.0

README: Final = "README.md"
_SOURCE: Final = "src/greeting.py"

_README_TEXT: Final = """# greeting

One Python module and nothing else. `greet(name)` returns a one-line greeting for the name it
is given, and that is the whole of the project.
"""

_SOURCE_TEXT: Final = '''def greet(name: str) -> str:
    """Return a one-line greeting for `name`."""
    return f"Hello, {name}."
'''

def workspace(root: Path) -> Path:
    """A workspace holding source code and nothing else, at an absolute path, and hand it back.

    Source code and nothing else is the point - this is what the poisoned repository in
    `_agent_hermeticity` is built on top of, and what every other task here runs in. The README
    exists so that a prompt can ask the agent to read something and say what it found, which is
    how a run produces text worth looking at without depending on the agent's own knowledge.
    """
    repo = root / "repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / README).write_text(_README_TEXT, encoding="utf-8")
    (repo / _SOURCE).write_text(_SOURCE_TEXT, encoding="utf-8")
    return repo.resolve()

def task(
    where: Path, model: ModelId, instructions: str, *, tools: Sequence[Tool] = ()
) -> AgentTask:
    """One task, with the fields this suite has an opinion about and defaults everywhere else."""
    return AgentTask(
        instructions=instructions,
        workspace=where,
        model=model,
        restrictions=frozenset(),
        tools=tuple(tools),
    )

async def outcome_of(
    runner: AgentRunner,
    work: AgentTask,
    *,
    on_activity: ActivityReporter | None = None,
) -> AgentOutcome:
    """`run`, under a deadline, with the one thing every test would otherwise assert itself.

    The deadline is what keeps a hang a *failure*: an await with no end looks exactly like an
    agent that is still thinking, and a suite that could not tell them apart would hang instead of
    reporting. A timeout is reported as a failed assertion rather than as a `TimeoutError`, because
    a reader needs to be told what did not come back and not which primitive noticed.

    Every test that does not name `on_activity` leaves it at its default, so the port's "may be
    omitted" is exercised by four of the seven runs this suite starts without a test for it.
    """
    try:
        async with asyncio.timeout(RUN_DEADLINE):
            outcome = await runner.run(work, on_activity=on_activity)
    except TimeoutError as expired:
        raise AssertionError(
            f"the run did not come back within {RUN_DEADLINE:.0f}s and was cancelled. A run that "
            f"never returns is the worst outcome available, because it looks exactly like work. "
            f"Every await an adapter makes on the caller's behalf is a candidate - a tool handler "
            f"that never returns is the one this suite hands one of"
        ) from expired
    assert isinstance(outcome, AgentOutcome), (
        f"run answered with {type(outcome).__name__}, and the port's answer is an AgentOutcome - "
        f"a stop reason, or None where the backend does not distinguish, and the agent's text"
    )
    return outcome

NOTE: Final = "record_note"
_NOTE_SCHEMA: Final[Mapping[str, JsonValue]] = {
    # `title` is here so that the free instruments exercise it, and for no other reason. This suite
    # is about a port and has no business deriving a schema, so the rest of this dict stays
    # hand-written - but `sdk/tools.py::_object_schema` writes a qualified type name into every
    # derived payload schema at every depth, that schema crosses the port untouched, and until this
    # line existed every free measurement of a tool reaching a real harness was taken on a schema
    # without one. The spelling is `_object_schema`'s own, `f"{module}.{qualname}"`. What is still
    # deferred is a *vendor* accepting it, which needs an installed CLI; what this line closes is
    # everything on AGL's side of the crossing.
    "title": "tests.contracts._agent_tasks.Note",
    "type": "object",
    "properties": {"note": {"type": "string", "description": "The note, in one sentence."}},
    "required": ["note"],
    "additionalProperties": False,
}
_REJECTION: Final = (
    "That note was not accepted: a note has to name the file you read it from. Correct it and "
    "call record_note again."
)
_ACCEPTANCE: Final = "Noted. Nothing else is needed from this tool."
_FAILURE: Final = "the notebook this tool writes into is not there"

class ToolFailed(Exception):
    """What a handler raises when a test asks it to fail rather than to refuse.

    Its own class, and deliberately not one of `errors.py`'s: a handler is the *caller's* code, an
    adapter is entitled to have no reading of what comes out of one, and an exception this suite
    borrowed from the framework's own hierarchy would let an implementation recognise it. That is
    now load-bearing rather than tidy - the clause this class provokes asserts that the object the
    handler raised is the object that comes out of `run`, and an implementation that recognised the
    class could translate it into something from `errors.py` and still look correct. It is not a
    `BaseException` either - both fakes decline to catch those on purpose, and a suite raising one
    would be asking every implementation to swallow a cancellation.
    """

class Notes:
    """The one tool this suite ever declares, and the record of what was handed to it.

    `reject_first` is how the rejection clause is provoked: the handler refuses that many calls
    before accepting one, so an adapter that puts a refusal back into the conversation gets a
    second call and an adapter that treats it as the end of the run does not. Nothing here asserts
    *how* the refusal was carried - `ToolResult.rejected` is a channel a backend may not have, and
    the port explicitly lets an adapter render the refusal into the text the agent reads instead.

    `raise_first` is the *opposite* provocation through the other door, and the two compose in the
    order they are written: the handler raises that many times, then refuses `reject_first` times,
    then accepts. A handler that raises is not a handler that refused politely - it is somebody's
    tool hitting a bug - and every implementation of this port ends the run with that exception
    rather than putting it back to the agent, so the trace it leaves is the opposite trace: one
    call, no second one, and nothing returned from `run` at all.

    **`failure` is built once and raised as itself every time**, which is what makes the identity
    assertable. The clause says the object the handler raised is the object that comes out of
    `run` - not a translation, not a wrapper, not a `raise ... from` - and a fresh instance per
    call would leave `is` unusable and `==` no better, since `Exception` compares by identity too.
    A `Notes(raise_first=1)` raises it exactly once, so the traceback it accumulates is one.

    What arrives is kept as `object` rather than as a mapping. The port says a payload is a
    `Mapping[str, JsonValue]`, and an adapter that hands over the raw JSON string its backend
    produced is exactly the bug worth catching - which a list that already claimed to hold
    mappings could not report.
    """

    def __init__(self, *, reject_first: int = 0, raise_first: int = 0) -> None:
        self.received: list[object] = []
        self.failure = ToolFailed(_FAILURE)
        self._reject_first = reject_first
        self._raise_first = raise_first
        self.tool = Tool(
            name=NOTE,
            description=(
                "Write down one note about what you found. Call it once you have something to "
                "record. You will be told whether the note was accepted."
            ),
            payload_schema=_NOTE_SCHEMA,
            handler=self._record,
        )

    async def _record(self, payload: Mapping[str, JsonValue]) -> ToolResult:
        self.received.append(payload)
        if len(self.received) <= self._raise_first:
            raise self.failure
        if len(self.received) <= self._raise_first + self._reject_first:
            return ToolResult(text=_REJECTION, rejected=True)
        return ToolResult(text=_ACCEPTANCE)

class ReporterFailed(Exception):
    """What an activity reporter raises when a test asks it to fail. `ToolFailed`'s sibling.

    Its own class, and deliberately not one of `errors.py`'s, for that class's reason: a reporter
    is the *caller's* code, and an exception borrowed from the framework's own hierarchy would let
    an implementation recognise it and treat it specially. Not a `BaseException` either - the port
    asks an adapter to write no `try` at all here, so the distinction never arises inside one, but
    a suite raising a `BaseException` would still be asking every implementation to survive
    something that means the task around the run is being torn down.
    """

class Activity:
    """An activity reporter that records, and on request fails. It runs inside the adapter.

    Recording and asserting nothing is the default because a callback that raised would be raising
    in whatever the adapter was doing at the time: the list is read afterwards, out here, where a
    failure is the suite's own.

    `raise_first` is how the port's rule about that is provoked, and it is `Notes(raise_first=...)`
    in another callback's clothes: the reporter records the line, then raises `ReporterFailed` for
    that many calls. The port settles what happens next - the exception ends the run and comes out
    of `run` - so what the clause using this asserts is that it *arrived*, rather than that the
    adapter did something particular with it. The port once said nothing here and this class said
    so; two implementations agreeing is not a contract, and both fakes and both real adapters had
    been agreeing for a long time with nothing written down.
    """

    def __init__(self, *, raise_first: int = 0) -> None:
        self.lines: list[object] = []
        self._raise_first = raise_first

    def __call__(self, line: str) -> None:
        self.lines.append(line)
        if len(self.lines) <= self._raise_first:
            raise ReporterFailed(f"the dashboard this reporter writes to is not there: {line!r}")

SAY_WHAT_THIS_IS: Final = (
    "Read the file README.md at the root of the workspace you were given, and reply with one "
    "sentence saying what the project in it does. Change nothing and create no files."
)

NOTE_WHAT_THIS_IS: Final = (
    "Say what the project in this workspace is, and record it.\n"
    "\n"
    "1. Read README.md at the root of the workspace you were given.\n"
    f"2. Call the {NOTE} tool once, with a note saying what the project does.\n"
    "3. Reply with one sentence saying what the project does.\n"
    "\n"
    "Create no files."
)

CORRECT_A_REFUSED_NOTE: Final = (
    "Record what the project in this workspace is, and keep at it until the note is accepted.\n"
    "\n"
    "1. Read README.md at the root of the workspace you were given.\n"
    f"2. Call the {NOTE} tool once, with a note saying what the project does.\n"
    "3. If you are told the note was not accepted, read what you were told, correct the note, "
    f"and call {NOTE} again. Keep going until a note is accepted.\n"
    "4. Once a note has been accepted, stop and reply with the single word: done"
)

KEEP_CALLING_A_FAILING_NOTE: Final = (
    "Record what the project in this workspace is, and keep at it until a note is recorded.\n"
    "\n"
    "1. Read README.md at the root of the workspace you were given.\n"
    f"2. Call the {NOTE} tool once, with a note saying what the project does.\n"
    "3. If the call comes back as an error, a failure or a refusal of any kind, read what you "
    f"were told and call {NOTE} again. Keep going until a call is accepted.\n"
    "4. Once a call has been accepted, stop and reply with the single word: done"
)
