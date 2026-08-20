"""What the suite hands a runner - a workspace, a task, two callbacks - and a deadline round a run.

A contract suite has one knob per implementation and builds everything else itself (`store.py` says
why at more length), so every task below is assembled here out of the port's own types. An
implementer supplies a runner and the model it serves, and nothing else: no prompt, no tool, no
workspace, and no way to point the suite at the task an implementation happens to be good at.

**The workspace is a real directory, and that is not the backdoor it looks like.** The store suite
refuses `Path` outright, because `Store` never speaks one. `AgentTask.workspace` *is* a `Path`, it
is refused unless absolute, and §3.5's hermeticity clause is a statement about what a directory
contributes - so a suite for this port that would not touch a filesystem could not assert the
promise this port most needs asserted. Everything past that is still refused: nothing here knows how
an adapter starts an agent, what it writes, whether it starts a process, or whether it is local.

**The workspace is deliberately not a git checkout.** A real one is (§3.5, `WorkspaceProvider`), and
building one here would mean running `git` from a contract suite - a binary this port never
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
numbered, literal, and saying what to reply with. Three tests read what the agent did as evidence
about the adapter (a rejected call retried, two questions asked, an answer echoed back), and there
is no other way to see those clauses from outside. Vague prompts would make those tests flaky
against correct adapters, which is a way of teaching a reader to ignore them.
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
    QuestionHandler,
    Tool,
    ToolResult,
)
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue

# A deadline around every run, and not a performance assertion. The port makes exactly one promise
# about time - that an adapter must not block on a question nobody is listening for - and a suite
# cannot assert that without being willing to stop waiting. It is generous because an agent
# verifying its own work is unbounded by design (`AgentTask` refuses to carry a timeout for that
# reason), so anything under this is not slowness, it is a run that is never coming back.
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

    Source code and nothing else is the point (§3.5) - this is what the poisoned repository in
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
    on_question: QuestionHandler | None = None,
    on_activity: ActivityReporter | None = None,
) -> AgentOutcome:
    """`run`, under a deadline, with the two things every test would otherwise assert itself.

    The deadline is what makes "the adapter must not block" testable at all: an await with no
    end looks exactly like an agent that is still thinking, and a suite that could not tell them
    apart would hang instead of failing - which is the same outcome the port forbids, one layer
    up. A timeout is reported as a failed assertion rather than as a `TimeoutError`, because a
    reader needs to be told which clause was broken and not which primitive noticed.

    Every test that does not name `on_activity` leaves it at its default, so the port's "may be
    omitted" is exercised by five of the six runs this suite starts without a test for it.
    """
    try:
        async with asyncio.timeout(RUN_DEADLINE):
            outcome = await runner.run(work, on_question=on_question, on_activity=on_activity)
    except TimeoutError as expired:
        raise AssertionError(
            f"the run did not come back within {RUN_DEADLINE:.0f}s and was cancelled. A run that "
            f"never returns is the worst outcome the port names, because it looks exactly like "
            f"work: if this task asked a question, an adapter with no handler to call must tell "
            f"the agent that no answer is available and let it carry on, never wait for one"
        ) from expired
    assert isinstance(outcome, AgentOutcome), (
        f"run answered with {type(outcome).__name__}, and the port's answer is an AgentOutcome - "
        f"a stop reason, or None where the backend does not distinguish, and the agent's text"
    )
    return outcome


NOTE: Final = "record_note"
_NOTE_SCHEMA: Final[Mapping[str, JsonValue]] = {
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


class Notes:
    """The one tool this suite ever declares, and the record of what was handed to it.

    `reject_first` is how the rejection clause is provoked: the handler refuses that many calls
    before accepting one, so an adapter that puts a refusal back into the conversation gets a
    second call and an adapter that treats it as the end of the run does not. Nothing here asserts
    *how* the refusal was carried - `ToolResult.rejected` is a channel a backend may not have, and
    the port explicitly lets an adapter render the refusal into the text the agent reads instead.

    What arrives is kept as `object` rather than as a mapping. The port says a payload is a
    `Mapping[str, JsonValue]`, and an adapter that hands over the raw JSON string its backend
    produced is exactly the bug worth catching - which a list that already claimed to hold
    mappings could not report.
    """

    def __init__(self, *, reject_first: int = 0) -> None:
        self.received: list[object] = []
        self._reject_first = reject_first
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
        if len(self.received) <= self._reject_first:
            return ToolResult(text=_REJECTION, rejected=True)
        return ToolResult(text=_ACCEPTANCE)


ANSWER_TOKENS: Final = ("alpha-K41", "bravo-Q73")


class Answers:
    """A question handler that answers with a different token each round, and remembers the asking.

    A token per round rather than one for both, because "N rounds inside one run" is the clause
    (§3.7) and an adapter that asked twice while replaying the first answer into both is a thing
    one string could not tell apart from a working one.
    """

    def __init__(self) -> None:
        self.asked: list[object] = []

    async def __call__(self, question: Question) -> Answer:
        self.asked.append(question)
        return Answer(text=ANSWER_TOKENS[min(len(self.asked), len(ANSWER_TOKENS)) - 1])


class Activity:
    """An activity reporter that records and asserts nothing, because it runs inside the adapter.

    A callback that raised would be raising in whatever the adapter was doing at the time, and
    what an adapter does with an exception from this is not something the port settles. So it
    takes everything and the test reads the list afterwards, where a failure is the suite's.
    """

    def __init__(self) -> None:
        self.lines: list[object] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


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

ASK_TWICE: Final = (
    "Before doing anything else you must ask the person running you two questions, one after "
    "the other, using whatever mechanism you have for asking something in the middle of a task. "
    "Do not guess either answer and do not ask them both at once.\n"
    "\n"
    "1. Ask which of two paths to take, and wait for the answer.\n"
    "2. Then, separately, ask which path to take after that, and wait for that answer too.\n"
    "3. Reply with the two answers you were given, copied exactly, separated by a space, and "
    "nothing else.\n"
    "\n"
    "If you have no way of asking, or you are told that no answer is available, reply with the "
    "single word: unanswered"
)

ASK_WITH_NOBODY_LISTENING: Final = (
    "Ask the person running you which of two paths to take, using whatever mechanism you have "
    "for asking something in the middle of a task.\n"
    "\n"
    "If no answer is available to you, do not wait for one: pick a path yourself and carry on. "
    "Either way, reply with the single word: done"
)
