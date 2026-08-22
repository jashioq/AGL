"""`FakeAgentRunner` against the `AgentRunner` contract, plus the clauses that suite cannot see.

The first class is the port in full: `AgentContract` with its two fixtures overridden and nothing
else touched. That suite was written at stage 3, against the port's docstrings and before any
adapter existed (§1.9), which is why nothing below re-asserts any of it. It runs **unconditionally**
here - no opt-in, no `check_ready` gate, nothing to authenticate and nothing to install - which is
the difference between a fake and the real adapter one file over, where six of the same eight tests
skip on a logged-out machine. The `model` fixture is parametrised over every model this runner
serves, which `tests/contracts/agent.py` names as "the honest way to cover them all", so the whole
suite runs three times.

What follows the contract subclass is what that suite lists as beyond it, and what a fake owes on
top of the port. In the order they matter:

  * **The four behaviours a script exists to produce** - a mid-run question whose answer visibly
    changes what happens next inside the same run, a tool call, a refused payload corrected back
    into the same conversation, and a `stop_reason` of `None`. The contract suite sees the first
    three only through a model's conduct (its gap 12) and cannot make a backend produce the fourth
    (its gap 10); here they are driven directly, which is what a fake is for.
  * **That the default behaviour is honest rather than tuned to the contract suite's prompts.**
    The suite hands this runner its own five prompts, and a fake that recognised them would go green
    against them and do nothing at all for a workflow author's own prompt. So the default is run
    against prompts nothing in this repository has ever handed it, twice, and the two transcripts
    are compared - which is the only assertion that can tell "it does the same thing whatever it is
    asked" from "it does the right thing when it is asked the right way".
  * **That it is not more permissive than `ClaudeCodeRunner`** (§1.9's whole point, and no gap of
    the suite's - the suite asserts what the port *says*, and every clause here is somewhere the
    port says nothing). Both runners are asked about every `ModelId` the port has, and about their
    capabilities, and the answers are compared rather than each being asserted on its own.
  * **That this module imports on a machine with no `claude_agent_sdk`**, which is the decision its
    docstring argues and the reason it shares no code with the real adapter. Proved by importing it
    in a process where the vendor SDK cannot be imported, with the real runner in the same process
    as the control that proves the block is real.
  * **The port's two settled edge cases and the exceptions around them** - a question with nobody
    listening, a handler that raises - which the suite can see the timing of and not the shape.

Named `test_claude_code_fake.py`, for the module it covers: `tests/` carries no `__init__.py` (see
`tests/conftest.py` for why it must not), so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import subprocess
import sys
from collections.abc import Awaitable, Mapping
from pathlib import Path
from typing import Final, cast

import pytest

from agl.adapters.claude_code.fake import Conversation, FakeAgentRunner, unscripted
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.ports.agent import (
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Claude,
    ModelId,
    OpenAI,
    Restriction,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.errors import InputError, Stop
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue
from contracts._agent_tasks import task, workspace
from contracts.agent import AgentContract


class TestFakeAgentRunner(AgentContract):
    """The port in full, three times over - once per model this runner serves.

    Two overrides and nothing else, which is what the suite asks for. There is no gate on either
    of them: nothing here starts a process, opens a socket or spends a token, so a skip would be
    hiding something rather than declining to do it.
    """

    @pytest.fixture
    def runner(self) -> AgentRunner:
        """The fake with no script, so the whole suite runs against the default behaviour.

        Deliberately not scripted. A fake handed a script written by the author of its own tests
        would be answering an exam it set itself, and the five prompts the suite supplies are the
        one set this module must satisfy without having been shown them.
        """
        return FakeAgentRunner()

    @pytest.fixture(params=list(Claude))
    def model(self, request: pytest.FixtureRequest) -> ModelId:
        """Every model this runner serves, one whole run of the suite each.

        `tests/contracts/agent.py` blesses exactly this - "parametrising the override ... is the
        honest way to cover them all, and it is one line in the subclass" - and there is no reason
        to pick a cheapest one here: nothing this runner does costs anything, so the argument that
        makes the real adapter's suite name `Claude.HAIKU` does not apply.
        """
        return cast(ModelId, request.param)


# --- Helpers: one tool, one question handler, and the tasks they go into ------------------------

NOTE: Final = "record_note"
REPORT: Final = "report_result"

_NOTE_SCHEMA: Final[Mapping[str, JsonValue]] = {
    "type": "object",
    "properties": {"note": {"type": "string", "description": "The note, in one sentence."}},
    "required": ["note"],
    "additionalProperties": False,
}

# Every JSON Schema shape the payload composer has a reading for, in one tool, plus one optional
# property that must not appear in what it composes.
RICH_SCHEMA: Final[Mapping[str, JsonValue]] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "count": {"type": "integer"},
        "ready": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "nested": {
            "type": "object",
            "properties": {"why": {"type": "string"}},
            "required": ["why"],
        },
        "aside": {"type": "string"},
    },
    "required": ["title", "count", "ready", "tags", "verdict", "nested"],
    "additionalProperties": False,
}


class Recorded:
    """One tool, what it was handed, and the shared order the calls across several arrived in.

    `refuses` provokes §3.3's clause the way the contract suite's own `Notes` does - the handler
    turns down that many calls before accepting one - and `received` is `object` for that suite's
    reason: an adapter that handed over the raw text its backend produced is the bug worth
    catching, and a list already claiming to hold mappings could not report it.
    """

    def __init__(
        self,
        name: str,
        *,
        schema: Mapping[str, JsonValue] = _NOTE_SCHEMA,
        refuses: int = 0,
        order: list[str] | None = None,
    ) -> None:
        self.received: list[object] = []
        self._refuses = refuses
        self._order = order
        self.tool = Tool(
            name=name,
            description="Write down what you found. You will be told whether it was accepted.",
            payload_schema=schema,
            handler=self._called,
        )

    async def _called(self, payload: Mapping[str, JsonValue]) -> ToolResult:
        self.received.append(payload)
        if self._order is not None:
            self._order.append(self.tool.name)
        if len(self.received) <= self._refuses:
            return ToolResult(text=f"{self.tool.name} did not accept that.", rejected=True)
        return ToolResult(text=f"{self.tool.name} accepted that.")


class Heard:
    """A question handler answering from a fixed list, repeating the last one once it runs out."""

    def __init__(self, *answers: str) -> None:
        self.asked: list[Question] = []
        self._answers = answers

    async def __call__(self, question: Question) -> Answer:
        self.asked.append(question)
        return Answer(text=self._answers[min(len(self.asked), len(self._answers)) - 1])


class Raises:
    """A question handler that raises, which §3.7 makes ordinary rather than hypothetical."""

    def __init__(self, failure: Exception) -> None:
        self.asked = 0
        self._failure = failure

    async def __call__(self, question: Question) -> Answer:
        self.asked += 1
        raise self._failure


def anything(where: Path, *, tools: tuple[Tool, ...] = ()) -> AgentTask:
    """A task whose instructions nothing in this repository has ever handed this runner."""
    return task(where, Claude.SONNET, "Translate into French: the cat sat on the mat.", tools=tools)


# --- The four behaviours a script exists to produce ---------------------------------------------


@pytest.mark.asyncio
async def test_an_answer_visibly_changes_what_happens_next_inside_the_same_run(
    tmp_path: Path,
) -> None:
    """§3.7: the answer returns into the same session, so a negotiation is rounds and not runs.

    The contract suite can see that two questions were asked and that the last answer came back in
    the closing text. What it cannot see - because it reads a model's conduct rather than an
    adapter's - is that the answer *decided* what happened next. Here one script is run twice
    against two handlers that differ in one word, and the two runs differ in how many questions
    were asked, whether a tool was called at all, and what the run stopped for.

    One `run` each way, which is the clause: an adapter that carried one exchange per run would
    have to start a second to ask the second question, and there is no second here to start.
    """
    landing = Recorded(REPORT)
    landed = Heard("land it")
    kept = Heard("keep going", "about a day")

    async def negotiate(conversation: Conversation) -> AgentOutcome:
        first = await conversation.ask(
            Question(prompt="Land it, or keep going?", options=("land it", "keep going"))
        )
        if first is None:
            return AgentOutcome(stop_reason=None, text="nobody was listening")
        if first.text == "land it":
            await conversation.call(REPORT, {"note": "landed"})
            return AgentOutcome(stop_reason=StopReason.COMPLETED, text=f"landed: {first.text}")
        second = await conversation.ask(Question(prompt="How much further?"))
        said = "" if second is None else second.text
        return AgentOutcome(stop_reason=StopReason.LIMIT, text=f"kept going: {said}")

    runner = FakeAgentRunner(negotiate)
    work = anything(workspace(tmp_path), tools=(landing.tool,))
    one = await runner.run(work, on_question=landed)
    other = await runner.run(work, on_question=kept)

    assert (len(landed.asked), len(kept.asked)) == (1, 2), (
        "the same script asked a different number of questions depending on what it was told, "
        "which is the whole of what 'the answer goes back into the same session' buys"
    )
    assert one.text == "landed: land it" and one.stop_reason is StopReason.COMPLETED
    assert other.text == "kept going: about a day" and other.stop_reason is StopReason.LIMIT
    assert len(landing.received) == 1, (
        f"the tool was called {len(landing.received)} time(s): the answer decides whether it is "
        f"called at all, and only one of these two runs was told to land"
    )


@pytest.mark.asyncio
async def test_a_scripted_tool_call_reaches_the_handler_as_the_mapping_it_was_given(
    tmp_path: Path,
) -> None:
    """The port's uniform rule: invoke the handler, put its `text` back into the conversation.

    Both halves are asserted, because a fake that dropped either would still pass the contract
    suite: the handler is handed the payload the script composed, as a `Mapping` and not as text,
    and the `ToolResult` the handler produced is what the script goes on with. Nothing here reads
    a tool's name to decide what it means - there is one tool and the script names it.
    """
    notes = Recorded(NOTE)
    seen: list[ToolResult] = []

    async def calls(conversation: Conversation) -> AgentOutcome:
        seen.append(await conversation.call(NOTE, {"note": "one sentence"}))
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="done")

    await FakeAgentRunner(calls).run(anything(workspace(tmp_path), tools=(notes.tool,)))

    assert notes.received == [{"note": "one sentence"}], (
        f"the handler was handed {notes.received}, and a handler takes the mapping the port "
        f"declares - a payload that arrived as text makes every handler in the framework parse "
        f"something the port says is already parsed"
    )
    assert [result.text for result in seen] == ["record_note accepted that."], (
        "what the handler said did not come back to the caller, so a script could never correct "
        "itself: the ToolResult is the framework speaking to the agent, which is the port's rule"
    )


@pytest.mark.asyncio
async def test_a_refused_payload_is_corrected_inside_the_same_conversation(
    tmp_path: Path,
) -> None:
    """§3.3, driven rather than inferred: not an adapter retry, not a new run, not an exception.

    The contract suite asserts the trace this leaves - the handler called twice inside one run -
    and says in as many words that it will not look at the mechanism, since `ToolResult.rejected`
    is a channel a backend may not have. Here the mechanism is the thing under test: the refusal
    arrives on the `ToolResult` the script is holding, the script reads it, and the second call
    carries something different because of what it was told.
    """
    notes = Recorded(NOTE, refuses=1)

    async def corrects(conversation: Conversation) -> AgentOutcome:
        said = "a first attempt"
        for _ in range(4):
            result = await conversation.call(NOTE, {"note": said})
            if not result.rejected:
                return AgentOutcome(stop_reason=StopReason.COMPLETED, text=result.text)
            said = f"corrected after: {result.text}"
        raise AssertionError("the handler refused every call, which this test did not ask for")

    work = anything(workspace(tmp_path), tools=(notes.tool,))
    outcome = await FakeAgentRunner(corrects).run(work)

    assert len(notes.received) == 2, (
        f"the handler was called {len(notes.received)} time(s) in one run, and the first call was "
        f"refused. A refusal goes back inside the same conversation so the caller corrects itself"
    )
    assert notes.received[0] != notes.received[1], (
        f"both calls carried {notes.received[0]}, so the refusal was not read - a second identical "
        f"call is a retry, which is the thing §3.3 says a refusal is not"
    )
    assert outcome.text == "record_note accepted that."


@pytest.mark.asyncio
async def test_a_script_may_answer_with_a_stop_reason_of_none(tmp_path: Path) -> None:
    """`None` means "this backend did not say", and it is the value a consumer most easily invents.

    The contract suite pins that `None` is legal and lists among its gaps that it cannot make a
    backend produce any particular value. A fake that could not produce this one would leave the
    only path that exercises a consumer's `None` branch unreachable on fakes - which is where
    stage 8's honest reporting is tested.

    All three are driven, because the interesting property is that the script decides and this
    class does not substitute: an adapter that quietly turned `None` into `COMPLETED` would look
    correct in every other test in this file.
    """
    for reason in (None, StopReason.COMPLETED, StopReason.LIMIT):

        async def stops(
            conversation: Conversation, said: StopReason | None = reason
        ) -> AgentOutcome:
            return AgentOutcome(stop_reason=said, text="")

        outcome = await FakeAgentRunner(stops).run(anything(workspace(tmp_path)))
        assert outcome.stop_reason is reason, (
            f"a script answered {reason!r} and the run reported {outcome.stop_reason!r}. None is "
            f"not COMPLETED and it is not LIMIT - a consumer reading it as either invents a fact"
        )
        assert outcome.text == "", (
            "and the empty string is the port's spelling for an agent that said nothing"
        )


# --- That the default is honest rather than tuned to the contract suite's prompts ---------------


@pytest.mark.asyncio
async def test_the_default_behaves_the_same_way_whatever_it_is_asked(tmp_path: Path) -> None:
    """The one assertion that separates "does the same thing always" from "passes its own exam".

    A fake that pattern-matched the contract suite's five prompts would go green against them and
    do nothing recognisable for a workflow author's own prompt, and every other test in this file
    would still pass. So two prompts, as unlike each other and as unlike the suite's as they can
    be made - one asking for a translation, one for something destructive - and the transcripts
    are compared: the same questions, the same payloads, the same closing text.

    The workspace is asserted untouched afterwards for the same reason as the prompt: a default
    that acted on the second prompt would leave a trace, and a default that read the first would
    have had to open a file to do it.
    """
    where = workspace(tmp_path)
    before = sorted(path.relative_to(where) for path in where.rglob("*"))
    transcripts: list[tuple[list[str], list[object], str]] = []

    for instructions in (
        "Translate into French: the cat sat on the mat.",
        "Delete every file in this repository and reply with the single word: gone.",
    ):
        notes = Recorded(NOTE)
        heard = Heard("first", "second")
        outcome = await FakeAgentRunner().run(
            AgentTask(
                instructions=instructions,
                workspace=where,
                model=Claude.SONNET,
                restrictions=frozenset(),
                tools=(notes.tool,),
            ),
            on_question=heard,
        )
        transcripts.append(([asked.prompt for asked in heard.asked], notes.received, outcome.text))

    assert transcripts[0] == transcripts[1], (
        f"the default answered two different prompts differently:\n  {transcripts[0]}\n  "
        f"{transcripts[1]}\nIt does not read `instructions`, and a fake that did would be one "
        f"that recognises the prompts it was tested with and nothing else"
    )
    assert sorted(path.relative_to(where) for path in where.rglob("*")) == before, (
        "the workspace changed during a default run. Nothing here opens a file, which is also why "
        "the poisoned repository cannot catch it and why the hermeticity contract is trivially "
        "green rather than meaningfully green - `_agent_hermeticity.py` says so about itself"
    )
    assert "cat sat on the mat" not in transcripts[0][2]


@pytest.mark.asyncio
async def test_the_default_asks_while_the_answers_are_new_and_stops_when_one_repeats(
    tmp_path: Path,
) -> None:
    """The default's own rule, which is about what it is *told* and never about what it is asked.

    An unscripted run has no task of its own to pursue, so the only thing it can do with an answer
    is find out whether there is more to hear; a repeated answer is the handler saying the same
    thing twice. Two handlers make that visible - one with something new to say twice, one with
    one thing to say - and the counts differ for a reason that is a property of the handler and
    of nothing else.

    Both counts are one higher than the number of *distinct* answers, and that is the rule rather
    than an off-by-one: a repeat cannot be discovered without asking again, so the last question of
    any negotiation is the one that ends it. Which also means the count the contract suite's own
    handler provokes is three, not the two it asserts - a default fitted to that assertion would
    have asked exactly twice, and this one overshoots it because the rule came from somewhere else.
    """
    varied, constant = Heard("alpha", "bravo"), Heard("the same thing")
    where = workspace(tmp_path)

    varied_outcome = await FakeAgentRunner().run(anything(where), on_question=varied)
    await FakeAgentRunner().run(anything(where), on_question=constant)

    assert len(varied.asked) == 3, (
        f"a handler with two things to say was asked {len(varied.asked)} time(s): the default asks "
        f"again while an answer is one it has not heard, and stops on the first repeat - which is "
        f"the third question here, not the second"
    )
    assert len(constant.asked) == 2, (
        f"a handler with one thing to say was asked {len(constant.asked)} time(s). Two is the "
        f"floor for any rule of this shape: the second question is what establishes that there was "
        f"nothing further to learn, and it is the one that ends the negotiation"
    )
    assert all(isinstance(asked, Question) and asked.prompt for asked in varied.asked)
    assert "bravo" in varied_outcome.text, (
        "the last answer is not in the closing text: an answer that reached the session and "
        "changed nothing about what came back is worth less than not asking"
    )


@pytest.mark.asyncio
async def test_the_default_calls_every_tool_it_is_given_and_singles_none_of_them_out(
    tmp_path: Path,
) -> None:
    """`ports/agent.py`'s rule, and the reason the default calls all of them rather than one.

    "An adapter that returned 'the result' would have to know which of the tools it was handed is
    the reporting one, and that is framework vocabulary living inside a vendor adapter." A default
    that called one tool would have to pick, and every rule for picking is that vocabulary. So it
    calls each one once, in declaration order, and a `--dry-run` of a reporting step gets a payload
    for the same reason an effect step's tools all get one.
    """
    order: list[str] = []
    tools = tuple(
        Recorded(name, order=order).tool for name in ("first_tool", "second_tool", "third_tool")
    )

    await FakeAgentRunner().run(anything(workspace(tmp_path), tools=tools))

    assert order == ["first_tool", "second_tool", "third_tool"], (
        f"the default called {order}. Every declared tool, once each, in declaration order - "
        f"anything else is this module deciding which tool matters, which is the one thing the "
        f"port says an adapter must never know"
    )


@pytest.mark.asyncio
async def test_the_default_composes_a_payload_out_of_the_tools_own_schema(tmp_path: Path) -> None:
    """A required key gets a value of the kind it asked for; an optional one is left out.

    Not validation and not a schema language - the port says a `payload_schema` "is data, not a
    type". It is the one thing a default cannot do without: a reporting step's result *is* its
    reporting tool's payload (§3.3), so a `--dry-run` whose every call was `{}` would fail every
    reporting step in the workflow for a reason that has nothing to do with the workflow.
    """
    rich = Recorded(REPORT, schema=RICH_SCHEMA)

    await FakeAgentRunner().run(anything(workspace(tmp_path), tools=(rich.tool,)))

    assert len(rich.received) == 1
    payload = rich.received[0]
    assert isinstance(payload, Mapping)
    assert sorted(payload) == ["count", "nested", "ready", "tags", "title", "verdict"], (
        f"the composed payload holds {sorted(payload)}: the required properties and nothing else, "
        f"since an optional property is optional and a key a schema never mentioned is a key "
        f"`additionalProperties: false` would refuse"
    )
    assert isinstance(payload["title"], str) and payload["title"]
    assert payload["count"] == 0 and not isinstance(payload["count"], bool)
    assert payload["ready"] is False
    assert payload["tags"] == []
    assert payload["verdict"] == "pass", (
        "a property listing its acceptable values has already answered the question, and a "
        "placeholder string would be refused by any handler that meant the enum"
    )
    assert isinstance(payload["nested"], Mapping) and isinstance(payload["nested"]["why"], str)


# --- That it is not more permissive than the runner it stands in for ----------------------------


@pytest.mark.asyncio
async def test_both_runners_refuse_exactly_the_same_models_in_the_same_way(
    tmp_path: Path,
) -> None:
    """§3.2: "An adapter handed a `ModelId` it does not serve raises `InputError`."

    The contract suite has one `model` fixture and can only ever name a model the runner serves,
    so every refusal is invisible to it. And a fake that served *more* models than the adapter it
    stands in for is the §1.9 failure in its purest form: a workflow naming a model AGL cannot run
    would pass on fakes and die at preflight in anger.

    So this asks both runners about every `ModelId` the port has and compares the answers rather
    than asserting each on its own - which is the device `test_store_parity.py` and
    `test_git_parity.py` use, and the thing that keeps the two served-model tables in agreement now
    that the fake deliberately does not import the real one's.

    **`capabilities` is the member asked of both, and the choice is forced.** It is the only one of
    the three whose refusal happens before the real adapter would touch the world: `check_ready`
    goes on to start a CLI and spend a turn against the far side, and `run` starts an agent. Both
    of those are asked of the real adapter *only* for the models it refuses, where the `InputError`
    lands before anything is attempted - which is a property of the adapter this file can read out
    of the answer it just got, and not one it has to trust.
    """
    fake, real = FakeAgentRunner(), ClaudeCodeRunner()
    for model in (*Claude, *OpenAI):
        answered = await _refusal(fake.capabilities(model))
        assert answered == await _refusal(real.capabilities(model)), (
            f"the two runners disagree about {str(model)!r}: the fake said {answered!r} and the "
            f"real adapter did not. Wherever the port is silent the fake agrees with the real "
            f"thing, and which models a backend serves is the first place it must"
        )
        if answered != "InputError":
            assert await _refusal(fake.check_ready(model)) == "answered", (
                "a model this fake serves must also be one it is ready for: there is nothing to "
                "install, nothing on PATH and nobody to authenticate against"
            )
            continue
        work = task(workspace(tmp_path), model, "Say anything at all.")
        for member, expected in (
            (fake.check_ready(model), real.check_ready(model)),
            (fake.run(work), real.run(work)),
        ):
            assert await _refusal(member) == await _refusal(expected) == "InputError", (
                f"a model both runners refuse to answer questions about must also be one both "
                f"refuse to run - and both must refuse {str(model)!r} before anything is "
                f"attempted, or preflight is all that stands between a workflow and a dead step"
            )


@pytest.mark.asyncio
async def test_both_runners_report_the_same_capabilities_for_a_served_model() -> None:
    """What preflight admits a run on, and the reason this fake claims two it cannot deliver.

    `FILE_EDIT` and `SHELL` are reported by a runner whose scripted agent edits no file and runs no
    command, and that is deliberate: `capabilities()` is "what can this backend be asked for", the
    backend this stands in for can be asked for all four, and preflight refuses a role that
    requires more than is reported. A fake reporting less would have every `--dry-run` of a
    realistic role refused at second zero, which is target #8 dead for a technicality about a fake.

    Written as a comparison rather than as a literal set so that a fifth `Capability` member is one
    decision in one place - `runner.py`'s - rather than two lists that agree today.
    """
    for model in Claude:
        assert await FakeAgentRunner().capabilities(model) == await ClaudeCodeRunner().capabilities(
            model
        ), (
            f"the two runners report different capabilities for {str(model)!r}, so a role admitted "
            f"on fakes could be refused in anger, or the other way round"
        )


@pytest.mark.asyncio
async def test_a_task_carrying_every_restriction_runs_and_is_prevented_from_nothing(
    tmp_path: Path,
) -> None:
    """The honest position, asserted so that it is a decision rather than an omission.

    The port gives a backend with no mechanism two moves - say it to the agent in words, or refuse
    the task - and neither is available here: there is no model to instruct, and refusing every
    restricted task would make this unusable for exactly the roles a real workflow declares. What
    is true instead is that nothing this module does is anything a `Restriction` forbids, so the
    task runs and the restrictions cost nothing. `contracts/agent.py` lists "that a `Restriction`
    was enforced" among what no suite can see from outside, for the same reason.
    """
    outcome = await FakeAgentRunner().run(
        AgentTask(
            instructions="Do the work.",
            workspace=workspace(tmp_path),
            model=Claude.OPUS,
            restrictions=frozenset(Restriction),
            tools=(),
            plan_only=True,
        )
    )
    assert isinstance(outcome.text, str)


@pytest.mark.asyncio
async def test_a_workspace_that_is_not_there_is_run_in_here_and_would_stop_the_runner(
    tmp_path: Path,
) -> None:
    """The second place this fake is deliberately more permissive, pinned rather than assumed.

    A workflow reaches it by removing a worktree and then running an agent, or by computing
    `AgentTask.workspace` itself; `FakeWorkspaceProvider.open` hands over a real directory, so it
    is narrow, and narrow is not the same as decided. The decision is `adapters/shell/fake.py`'s,
    which faces the identical question about `workdir`: a runner refusing a directory that is not
    there is a fact about starting a process, not a clause of the port, and "inventing an agreement
    with it here would mean this class asserting something about the world it cannot see".

    `ports/agent.py` says exactly one thing about `workspace` - that it is absolute - and says it
    in `AgentTask.__post_init__`, where a clause about the value binds every implementation at
    once. Existence is not there and could not be: the task is frozen when it is built and run
    later, and a worktree can go away in between. So the port is silent, and §1.9's rule about
    silence has an answer only where the two implementations *could* agree.

    **Only this end is asserted, and the other end is cited.** `ClaudeCodeRunner` reaches its
    answer by starting a process - the SDK's transport raises `CLIConnectionError("Working
    directory does not exist: ...")` when the spawn's `chdir` fails, and
    `test_claude_code_translate.py` already pins that class to `UpstreamUnavailable`. Provoking it
    for real would mean spawning a CLI, which every test in this file declines to do for free; a
    stub `Transport` could not provoke it either, because it is the spawn itself that fails. What
    a mutation of this fake can be caught by is this half, and this half is what is written down.

    The direction matters more than the divergence. A fake that refused here would stop a
    `--dry-run` on a `--dry-run`'s own terms - it starts no process and has no `chdir` to fail -
    and that is §1.9 running backwards: a run failing on fakes that anger would have carried
    through is fiction in the same way as one passing that anger would have stopped.
    """
    absent = tmp_path / "a-worktree-something-took-away"
    assert not absent.exists(), "the fixture must begin with the directory genuinely not there"

    outcome = await FakeAgentRunner().run(anything(absent))

    assert isinstance(outcome.text, str), (
        f"a run on a workspace that is not there answered {outcome!r}. This runner reads the "
        f"workspace and never looks at it, because whether a directory can be entered is a fact "
        f"about the process the real adapter starts and this one starts none"
    )
    assert not absent.exists(), (
        f"{absent} exists after the run, so this fake made the directory it was pointed at. A "
        f"workspace is provisioned by WorkspaceProvider and by nothing else, and a runner that "
        f"created one would hide the very state this test is about"
    )


def test_this_fake_imports_on_a_machine_with_no_vendor_sdk() -> None:
    """The decision in the module's docstring, proved rather than asserted.

    `agl[claude]` is a pip extra (§3.2.1), and a fake that could only be imported once the vendor
    SDK was installed would make `--dry-run` a mode you first install a vendor to reach - on the
    one machine a fake exists for. So this imports the module in a fresh interpreter in which
    `claude_agent_sdk` cannot be imported at all.

    The real runner is imported in the same process as the control. Without it a green result would
    be indistinguishable from a probe that never blocked anything, which is the shape
    `test_shell_verifier.py` established: a measurement and a control that proves it was armed.
    """
    probe = (
        "import sys\n"
        "sys.modules['claude_agent_sdk'] = None\n"
        "import agl.adapters.claude_code.fake as fake\n"
        "print('fake:', fake.FakeAgentRunner().__class__.__name__)\n"
        "try:\n"
        "    import agl.adapters.claude_code.runner\n"
        "except ImportError:\n"
        "    print('control: the runner could not be imported, so the block is real')\n"
    )
    finished = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )

    assert finished.returncode == 0, (
        f"importing the fake without claude_agent_sdk failed:\n{finished.stderr}\nThe whole of "
        f"what this module may import is stdlib and agl.ports - sharing translate.model_name with "
        f"the real adapter would drag the vendor SDK in through it"
    )
    assert "fake: FakeAgentRunner" in finished.stdout
    assert "control: the runner could not be imported" in finished.stdout, (
        f"the control did not fire, so the SDK was importable after all and this test proved "
        f"nothing:\n{finished.stdout}"
    )


# --- The port's two settled edge cases, and the exceptions around them ---------------------------


@pytest.mark.asyncio
async def test_a_question_with_nobody_listening_is_answered_none_and_never_waited_for(
    tmp_path: Path,
) -> None:
    """The port's second edge case, in the return type so that a script cannot forget it.

    "If the agent asks while `on_question` is `None`, the adapter must **not** block. It tells the
    agent that no answer is available and lets it carry on with its own judgement." A real session
    says that in words because a tool result has no other channel; a script is not a model and
    would have to recognise a sentence, so it is said as `None` and `mypy --strict` makes carrying
    on regardless impossible to write by accident.

    The contract suite asserts the timing of this under a deadline. What it cannot see is the
    shape, or that nothing was recorded as having gone wrong: nobody listening is not a failure.
    """
    seen: list[Answer | None] = []

    async def asks(conversation: Conversation) -> AgentOutcome:
        seen.append(await conversation.ask(Question(prompt="Which of two paths?")))
        assert conversation.failure is None, "nobody listening is not something going wrong"
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="carried on")

    outcome = await FakeAgentRunner(asks).run(anything(workspace(tmp_path)))

    assert seen == [None], f"asking with no handler answered {seen}, and nobody answered"
    assert outcome.text == "carried on"


@pytest.mark.asyncio
async def test_a_question_handler_that_raises_ends_the_run_with_its_own_exception(
    tmp_path: Path,
) -> None:
    """`_session.py`'s behaviour, and it is not an implementation detail of the real adapter.

    §3.7's headless terminal raises `UpstreamUnavailable` on any view that needs an answer and a
    workflow's handler may raise `Stop`, so a fake that swallowed either would turn a run that dies
    in anger into a run that passes on fakes - which is §1.9's failure exactly. The exception comes
    back out of `run` itself, and the handler is not asked again on the way there: spending the
    rest of a run on an asker that has already failed is what the real adapter refuses to do.
    """
    stopping = Stop("the workflow decided there is nothing more to do")
    handler = Raises(stopping)

    async def keeps_asking(conversation: Conversation) -> AgentOutcome:
        for _ in range(3):
            assert await conversation.ask(Question(prompt="Anything?")) is None
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="never reached")

    with pytest.raises(Stop) as raised:
        await FakeAgentRunner(keeps_asking).run(anything(workspace(tmp_path)), on_question=handler)

    assert raised.value is stopping, (
        "the run raised something other than what the handler raised: a workflow's own Stop has to "
        "arrive as itself, or the exit code it carries is decided by an adapter"
    )
    assert handler.asked == 1, (
        f"the handler that raised was called {handler.asked} times. The first exception is the one "
        f"that explains why the rest went the way they did, and later questions are answered "
        f"without calling it again"
    )

    # And the default stops working, which is the other half of `_session.py`'s behaviour: it
    # breaks out of the stream at the very next message rather than spending an hour of a run on a
    # session whose asker has already failed. A script decides that for itself; the default cannot
    # be left to, because it is what `--dry-run` runs and nobody wrote it for the occasion.
    notes = Recorded(NOTE)
    with pytest.raises(Stop):
        await FakeAgentRunner().run(
            anything(workspace(tmp_path), tools=(notes.tool,)), on_question=Raises(stopping)
        )
    assert notes.received == [], (
        "the default carried on calling tools after the asker had already failed, which is an "
        "hour of a real run spent on a session that was over, and here is a step's own handlers "
        "being invoked for a run that is about to raise"
    )


@pytest.mark.asyncio
async def test_a_script_cannot_call_a_tool_the_task_never_declared(tmp_path: Path) -> None:
    """A real session registers exactly `task.tools`, so a call to anything else is not a move.

    Refused rather than accepted quietly, because a script that can call an undeclared tool is a
    script that proves a workflow works with a tool the workflow never declared - and the proof
    evaporates the moment the same workflow meets a real session. `InputError` for the port's own
    reason: it is the caller's, and nothing has been attempted.
    """
    notes = Recorded(NOTE)

    async def calls_nothing_declared(conversation: Conversation) -> AgentOutcome:
        await conversation.call("some_other_tool", {"note": "hello"})
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="unreachable")

    with pytest.raises(InputError, match="record_note"):
        await FakeAgentRunner(calls_nothing_declared).run(
            anything(workspace(tmp_path), tools=(notes.tool,))
        )
    assert notes.received == [], "and the tool that was declared was not called instead"


@pytest.mark.asyncio
async def test_a_payload_no_model_could_have_produced_never_reaches_a_handler(
    tmp_path: Path,
) -> None:
    """A tool payload is JSON in a real session, because it was parsed off a wire.

    A fake that accepted a value JSON has no spelling for would let a workflow build a payload the
    real path could not deliver and the store could not write down (§3.6) - `memory_store.py` makes
    the same argument about the same class of divergence, and calls it the drift in its purest
    form. `NaN` is the sharpest case: `float` is a `JsonValue`, so nothing in the type system
    refuses it, and `json` writes a bare `NaN` token that comes back unequal to itself.
    """
    notes = Recorded(NOTE)

    async def calls_with_nan(conversation: Conversation) -> AgentOutcome:
        await conversation.call(NOTE, {"note": float("nan")})
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="unreachable")

    with pytest.raises(InputError, match="not JSON"):
        await FakeAgentRunner(calls_with_nan).run(
            anything(workspace(tmp_path), tools=(notes.tool,))
        )
    assert notes.received == [], "the handler was handed it anyway, which is the whole of the bug"


@pytest.mark.asyncio
async def test_a_scripts_activity_line_arrives_untouched_and_a_reporter_that_raises_is_not_hidden(
    tmp_path: Path,
) -> None:
    """§3.7: each adapter formats its own line and the framework passes it through untouched.

    The contract suite asserts that whatever arrives is a `str` and says it cannot assert that a
    line was passed through, since it does not know what the adapter meant to say. Here the script
    is the adapter's voice, so the intended line is known.

    The second half is parity: `_session.py` calls the activity callback unguarded, on the argument
    that swallowing an exception would hide a broken reporter for the length of a run. A fake that
    guarded it would hide it only on fakes, which is worse.
    """
    lines: list[str] = []

    async def reports(conversation: Conversation) -> AgentOutcome:
        conversation.report("Read: README.md")
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="done")

    await FakeAgentRunner(reports).run(anything(workspace(tmp_path)), on_activity=lines.append)
    assert lines == ["Read: README.md"]

    def breaks(line: str) -> None:
        raise RuntimeError("this reporter is broken")

    with pytest.raises(RuntimeError, match="this reporter is broken"):
        await FakeAgentRunner(reports).run(anything(workspace(tmp_path)), on_activity=breaks)


@pytest.mark.asyncio
async def test_the_default_is_a_function_a_script_can_delegate_to(tmp_path: Path) -> None:
    """`unscripted` is exported, which is what makes "the usual thing, and then one more" writable.

    A script that had to reimplement the default in order to add one move to it would be a second
    copy of the behaviour this file spends four tests pinning, drifting from the first.
    """
    notes = Recorded(NOTE)

    async def and_then(conversation: Conversation) -> AgentOutcome:
        usual = await unscripted(conversation)
        await conversation.call(NOTE, {"note": "one more"})
        return AgentOutcome(stop_reason=usual.stop_reason, text=f"{usual.text} And one more.")

    work = anything(workspace(tmp_path), tools=(notes.tool,))
    outcome = await FakeAgentRunner(and_then).run(work)

    assert len(notes.received) == 2, "the default called it once and the script called it again"
    assert outcome.text.endswith("And one more.")
    assert outcome.stop_reason is StopReason.COMPLETED


async def _refusal(member: Awaitable[object]) -> str:
    """What a port member did, as one word: the name of what it raised, or `"answered"`.

    A string rather than the exception, so that two runners can be compared with `==` and a failure
    shows both answers side by side rather than two repr'd tracebacks. `Awaitable[object]` because
    the three members answer with three different things and none of them is what is being read
    here - the value is discarded and only the raise is the evidence.
    """
    try:
        await member
    except Exception as raised:
        return type(raised).__name__
    return "answered"
