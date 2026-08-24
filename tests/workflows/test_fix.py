"""What `workflows/fix/` owns: its payload type, its flag, its two declarations, and the run itself.

Two halves, and the line between them is whether a claim needs a `Run` to be seen at all. The first
half is every value this package declares, asserted by importing it; the second - from *driving the
whole workflow* down - is 17.3, which runs `fix` on an all-fakes bundle, interrupts it at every step
boundary, resumes it and asserts the final state is the one an uninterrupted run leaves. The three
`commit=` decisions, the branch over `findings.high()`, the `request=` input, the two `show` calls
and the `replace` that gives the implementer a handler are reachable *only* from the second half:
they are arguments to calls, and nothing imports an argument.

The three things worth pinning in the first half, in the order this package's own docstrings argue
them:

* **`Findings.high()`**, because §3.3's `if findings.high():` is the workflow's only branch and this
  is the comparison behind it. A filter that answered `()` for a review that found something high
  would skip the repair pass, report success, and raise nothing.
* **The severity vocabulary reaching the model as a rejection**, because a derived schema has no
  per-field `description` and `Finding.__post_init__` is the only thing that can enforce a fixed set
  of strings. The mechanism - `__post_init__` raising, `sdk/tools.py` catching it, the text going
  back into the same conversation - is the one this package leans on and does not own.
* **The pairing between `reviewer` and the step that runs it**, which §3.3 calls the author's job
  and which nothing in the framework checks. Half of it is a role declaration; the other half is the
  missing `commit=` on the `review` call, and that half is asserted in the second half of this file,
  as a commit that is not on the branch and a scratch file that is not on disk.

## The views, and why they need no terminal at all

**A view is a pure function of its arguments**, so every assertion about one is a call and a
comparison against the `Screen` it returned - no display, no redraw loop, no keystrokes, and nothing
that could block. That is the whole of what makes the two screens below testable here rather than at
17.3, and it is worth saying explicitly because the alternative is what stage 16 flagged: answering
an interactive screen needs a `Terminal` that can take input, AGL ships none an author can drive,
and a test that tried to *answer* `agent_question` would be a test of `RichTerminal` wearing this
package's name. Nothing here answers a screen. These tests read the value a person would have been
shown, which is the half this package owns.

The board is the one that costs something, and the cost is on the record: it takes a `Run`, because
§3.7's board reads `run.activity` out of a live object rather than being handed a string that would
be frozen at the moment of the `show`. A `Run` is on the SDK's front door as a *type* and is not
constructible from it - `services`, `scope` and `base` are `_engine`, `ports` and the framework's -
so `_run` below builds one through `agl.testing`, which a test may do and a workflow may not, and
sets the activity through `_steps` because nothing public writes it. Both are named where they
happen.

## The second half is an interruption and not a kill, and the name of this file does not say kill

`agl.testing`'s own docstring is emphatic and this file inherits the whole of it. `Harness.run
(interrupt_after=k)` raises inside the store's `write_entry`, in *this* process, so `api.run`'s
`finally` runs, the terminal's `__aexit__` runs, the git fakes keep their commits in memory because
the interpreter that holds them is still alive, and one interpreter computes both invocations'
digests. A real kill is `os._exit` in a second process and it is `tests/sdk/test_kill_and_resume.py`
over `tests/instruments/replay.py`, which is the framework's own version of this property and is not
re-proved here. **What is proved here is the half a workflow author owns**: that *this* workflow is
resumable, that a resume of it redoes no completed work, and that where it was interrupted makes no
difference to what it finally leaves behind. The sweep below therefore says "interrupted" wherever
it would be tempting to say "killed".

**How the kill-point sweep carries `interrupt_after=`'s counter.** The keyword counts what *this
invocation* wrote, never what the ledger holds - `_Ledger.interrupt_after` resets on every arming -
so a sweep hands each invocation its own number and keeps the running total itself. That reset is
invisible at k=1, where a per-invocation count and a cumulative one both fire on the first write,
and load-bearing from k=2 up. So `_kill_points` below enumerates every *composition* of the step
count (`(1,2)` and `(2,1)` as well as `(3,)` and `(1,1,1)`), the sweep asserts after each invocation
that the ledger holds exactly the running total, and only then compares the whole outcome. The
intermediate assertion is the one with teeth: a final state that is correct however the
interruptions fell would also be correct if this file carried the offset wrongly, because the last
invocation is unbounded and finishes whatever is left.

## What the shipped harness cannot show, stated rather than worked around

**A board that was shown leaves nothing behind.** `HeadlessTerminal` reads a passive `Screen` for
its responses and drops it on the same line, deliberately - it is the terminal that runs unattended
and it accumulates nothing. So the `show(views.board, ...)` before the first step is invisible on
the bundle `testing.harness()` builds, and `_Watching` below is a `Terminal` of this file's own that
keeps what it was handed. It is used by exactly one test and never anywhere else, it answers no
question and claims to be no conforming implementation - `tests/contracts/terminal.py` is what says
how a `Terminal` behaves and this one deliberately does not - and it is written from `agl.sdk`
alone, `Terminal` being on the front door. `tests/sdk/test_run_terminal.py::_Recording` is the same
object for the same reason one layer down.

**A question can be reached but not answered.** 17.2 recorded the gap and this file does not repair
it: AGL ships no input-capable `Terminal` an external author can drive, so a workflow's
`on_question` handler can be driven to the *refusal* and not to an answer. That is still worth
driving, and it is sharper than it sounds - `UpstreamUnavailable` naming `agent_question` says that
the implementer's question reached this workflow's own screen through this workflow's own handler,
and a run that completes instead says the handler was never on the role.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Final, Self, cast

import pytest

from agl import testing

# `agl.ports.errors` is not on the SDK's front door and neither `agl.sdk` nor `agl.testing`
# re-exports a single exception class, so a workflow author asserting *how* their run refused has
# nowhere else to import from. All three below are that reach: `InputError` for a flag a parser
# would not take, `InternalError` for a question no screen could answer, and `UpstreamUnavailable`
# for the refusal a headless terminal makes when this workflow's handler puts a screen up. Reported
# as a finding rather than routed around.
from agl.ports.errors import InputError, InternalError, UpstreamUnavailable
from agl.sdk import (
    Answer,
    Capability,
    Choice,
    Claude,
    OpenAI,
    Question,
    Restriction,
    Row,
    Rows,
    Run,
    Screen,
    Terminal,
    Text,
    TextInput,
)
from agl.sdk import params as sdk_params

# `canonical_json` is `_engine`'s and not on the SDK's front door, which is the point of the one
# test that uses it: `high()`'s docstring claims a tuple of this package's dataclasses survives the
# fingerprint, and a workflow author has no supported way to check that claim. A *test* may reach
# here - `tests/sdk/` does throughout - and the workflow itself may not, and does not.
from agl.sdk._engine.journal import canonical_json
from agl.workflows.fix import FixParams, fix, views
from agl.workflows.fix.findings import HIGH, SEVERITIES, Finding, Findings, report_findings
from agl.workflows.fix.roles import implementer, reviewer
from agl.workflows.fix.views.question import FREE_TEXT

PROMPTS: Final = Path(__file__).resolve().parents[2] / "src/agl/workflows/fix/prompts"

REQUEST: Final = "the retry loop drops the last error"
"""What an operator asked for, in one place, because the board renders it and a step is given it."""

BASE: Final = "4a91c07f2b3e8d15c6a0f31d8e2b47c9a6013f5e"
"""The head a `Run` starts from. Nothing below takes a step, so this is a well-formed sha and not a
commit that exists anywhere."""


def _finding(severity: str, file: str = "src/a.py") -> Finding:
    """One finding at a given severity. The other two fields are prose this package never reads."""
    return Finding(severity=severity, file=file, summary=f"a {severity}-severity problem")


def test_high_returns_the_high_severity_findings_and_only_those() -> None:
    """The filter, over a payload holding one of each severity.

    Asserted as an exact tuple rather than by counting: a `high()` that answered with everything, or
    with the first element, or with the wrong member of the vocabulary, has to fail here.
    """
    high, medium = _finding("high", "a.py"), _finding("medium", "b.py")
    low = _finding("low", "c.py")

    assert Findings((medium, high, low)).high() == (high,)


def test_high_is_empty_when_the_review_found_nothing_that_must_be_fixed() -> None:
    """The other side of the branch: findings exist, none of them is `high`, and the workflow does
    not pay for a repair pass. A filter comparing against the wrong severity passes the test above
    and fails this one."""
    assert Findings((_finding("medium"), _finding("low"))).high() == ()


def test_a_review_that_found_nothing_at_all_has_nothing_to_repair() -> None:
    """The empty payload, which `prompts/review.md` calls the right answer for a sound change."""
    assert Findings(()).high() == ()


def test_high_findings_survive_the_fingerprint_that_the_repair_step_takes_over_them() -> None:
    """`high()`'s docstring claims its result can be passed straight into `run.step(...,
    findings=...)`, which means `_canonical` has to be able to walk it.

    That is the claim worth checking here rather than at 17.3: it is about the *shape* this module
    chose - a tuple of frozen dataclasses, where §3.3's own example passes a list - and it fails as
    an `InputError` at the step rather than as anything a reader would trace back to this file. The
    qualified type name in the output is §3.6 rule 6, and it is what stops a `Finding` and a
    same-shaped type of another name fingerprinting alike.
    """
    encoded = canonical_json({"findings": Findings((_finding("high"),)).high()})

    assert "agl.workflows.fix.findings.Finding" in encoded
    assert '"severity":"high"' in encoded


def test_a_severity_the_workflow_would_silently_skip_is_refused_by_the_type() -> None:
    """`critical` is the shape of this failure: a plausible word, outside the vocabulary, that
    `high()` would filter away without complaint - leaving the repair step unrun and the run
    reporting success over a defect somebody marked as the worst kind."""
    with pytest.raises(ValueError, match="high, medium, low"):
        _finding("critical")


def test_an_invented_severity_reaches_the_model_as_a_rejection_it_can_act_on() -> None:
    """The mechanism the module docstring leans on, end to end through the SDK: the payload walker
    accepts a string, the dataclass refuses this one, and `sdk/tools.py` turns what it raised into
    prose carried back into the same conversation instead of an exception ending the run.

    Asserting the vocabulary is in the text is the part that matters. The schema cannot carry it -
    a derived `str` field is `{"type": "string"}` and nothing else - so this refusal is the only
    place a model that guessed wrong is told what the four words are.
    """
    refusal = report_findings.rejection(
        {"findings": [{"severity": "critical", "file": "a.py", "summary": "b"}]}
    )

    assert refusal is not None
    assert ", ".join(SEVERITIES) in refusal


def test_a_missing_findings_list_is_a_rejection_and_an_empty_one_is_a_result() -> None:
    """Why the field has no default. "Found nothing" and "forgot to fill this in" are different
    answers, and only one of them is a review."""
    assert report_findings.rejection({}) is not None
    assert report_findings.rejection({"findings": []}) is None


def test_the_reviewer_is_declared_read_only_beside_a_step_that_will_wipe_its_worktree() -> None:
    """§3.3's pairing, half of it. The `review` call passes no `commit=`, so the framework restores
    the checkout and deletes everything not in it when the step ends - whatever the agent did. The
    role that gets run there has to be one that was never going to commit.

    Nothing in the framework checks this combination, and §3.3 names it as the one place in AGL
    where a mistake destroys work rather than costing a re-run. The other half - that the call in
    `__init__.py` really does omit `commit=` - is 17.3's, because seeing it means running the
    workflow.
    """
    assert Restriction.NO_VCS_WRITES in reviewer.restrictions
    assert Restriction.NO_FILE_WRITES in reviewer.restrictions


def test_the_implementer_leaves_committing_to_the_framework_that_is_going_to_do_it() -> None:
    """The same restriction on the role whose steps *do* pass `commit=`, and it is not the pairing
    rule above.

    The framework commits whatever this agent leaves dirty at step end, under the message the call
    named, and records the resulting head as the reset target for everything after it. An agent
    that commits on its own account moves the branch under a framework that is about to commit and
    record on top of it, so the restriction is the declaration that committing here is not this
    agent's job. Nothing else in this suite pins it and no gate would notice it going missing."""
    assert Restriction.NO_VCS_WRITES in implementer.restrictions


def test_the_two_roles_name_two_providers_and_no_vendor_syntax() -> None:
    """Target #4 as a declaration: one run, two providers, chosen by naming two models.

    `provider` is derived from the model id rather than declared, so this also pins that the two
    really do route to different adapters - which is the whole reason `fix` is the workflow the
    target is measured on.
    """
    assert implementer.model is Claude.OPUS
    assert reviewer.model is OpenAI.SOL
    assert implementer.model.provider is not reviewer.model.provider


def test_the_reviewer_reports_through_one_tool_and_the_implementer_through_none() -> None:
    """What makes `review` a reporting step and `implement` an effect step - and therefore what
    makes `run.step("review", reviewer)` hand back a `Findings` where the other two hand back
    `None`."""
    assert reviewer.tools == (report_findings,)
    assert implementer.tools == ()
    assert report_findings.payload is Findings


def test_each_role_requires_what_its_prompt_actually_asks_of_a_backend() -> None:
    """`requires` is compared against what a provider can do before the run starts, so an
    over-declaration refuses a backend that would have worked and an under-declaration is a run that
    dies at the step instead of at second zero.

    `MID_RUN_QUESTIONS` is on the implementer and not on the reviewer, and neither half is
    incidental: the implementer is the role the workflow hands a handler to, and the reviewer is the
    one §3.7 names as running on the backend with no second asking mechanism, where declaring a
    handler is the case preflight's third check exists to refuse.
    """
    assert implementer.requires == frozenset(
        {Capability.FILE_EDIT, Capability.SHELL, Capability.MID_RUN_QUESTIONS}
    )
    assert reviewer.requires == frozenset({Capability.SHELL, Capability.TOOL_CALLING})
    assert reviewer.on_question is None
    assert implementer.on_question is None


def test_both_roles_hold_their_prompt_text_and_not_a_path_to_it() -> None:
    """§3.7's rule, and the failure it prevents is silent: a role holding `"prompts/review.md"`
    fingerprints the filename, so editing the prompt moves no digest and a resume replays what the
    old wording produced. `Role` cannot refuse it - the field is a `str` either way - so the only
    place this can be caught is here."""
    assert implementer.instructions == (PROMPTS / "implement.md").read_text(encoding="utf-8")
    assert reviewer.instructions == (PROMPTS / "review.md").read_text(encoding="utf-8")


def test_the_review_prompt_names_the_commit_message_the_workflow_writes() -> None:
    """The one coupling in this package that nothing enforces. A commit message is outside the
    fingerprint (§3.6: it is cosmetic), so editing `commit="implement fix"` re-runs nothing and
    quietly stops agreeing with the prompt that tells the reviewer which commit to read. This is
    what notices."""
    assert "implement fix" in reviewer.instructions


def test_the_review_prompt_promises_no_inputs_block_because_the_step_passes_none() -> None:
    """`run.step("review", reviewer)` passes no `**inputs`, and `_composed` then appends nothing at
    all - no heading, no separator, not a newline. A review prompt that told its agent to read a
    block underneath it would be describing something that is never there."""
    assert "## Inputs" not in reviewer.instructions
    assert "## Inputs" in implementer.instructions


def test_the_request_is_a_required_named_flag_and_there_are_no_positionals() -> None:
    """§3.3's "named flags only", and `--request` required because a `fix` run with nothing to fix
    has no honest default."""
    assert sdk_params.parse(FixParams, ["-r", "the retry loop drops the last error"]) == FixParams(
        request="the retry loop drops the last error"
    )
    assert sdk_params.parse(FixParams, ["--request", "x"]) == FixParams(request="x")
    with pytest.raises(InputError):
        sdk_params.parse(FixParams, [])
    with pytest.raises(InputError):
        sdk_params.parse(FixParams, ["a bare positional"])


def test_the_workflow_declares_its_params_its_version_and_both_roles() -> None:
    """What `@workflow` hands the framework, and the one line of it that is not a fact about the
    function: `roles=`, which is the only way §3.2's preflight can see a role before the run starts.
    A workflow that declared neither role would preflight against nothing and pass."""
    assert fix.name == "fix"
    assert fix.version == "1.1"
    assert fix.params is FixParams
    assert fix.roles == (implementer, reviewer)


def test_the_severity_the_workflow_branches_on_is_one_of_the_ones_it_asks_for() -> None:
    """A one-line consistency check between the constant `high()` compares against and the list the
    tool's description hands the model. They are two spellings of one decision and they are on one
    screen, but the failure if they part is a review that can never produce a repair."""
    assert HIGH in SEVERITIES
    assert HIGH in report_findings.description


# --- the board -------------------------------------------------------------------------------


def _run(where: Path, activity: str | None = None) -> Run[FixParams]:
    """A `Run` to show a board over, with an activity line on it if the test wants one.

    **Two reaches past the SDK's front door, both a test's and neither the workflow's.**
    `agl.testing.harness` is what builds a bundle of fakes - `Run` takes a `services`, a `scope` and
    a base ref, none of which `agl.sdk` exports or could - and `_steps._activity` is written
    directly because activity is set by an adapter inside a running step and by nothing else. A
    workflow author testing their own board hits both of these, and there is no supported spelling
    for either; that is reported as a finding rather than wrapped in a helper that hides it.

    Nothing here runs, commits or shows anything: the bundle exists so that `Run.__post_init__` has
    something to build a `Steps` out of.
    """
    harness = testing.harness(where)
    run = Run(
        params=FixParams(request=REQUEST),
        services=harness.fakes.services,
        scope=harness.scope,
        base=BASE,
    )
    run._steps._activity = activity
    return run


def test_the_board_shows_the_request_and_the_line_the_adapter_last_reported(tmp_path: Path) -> None:
    """The whole board, as one value.

    Asserted as an exact `Screen` rather than by picking cells out of it, which is what value
    equality on every component is for: a board that put the two rows the other way round, labelled
    a cell differently, or grew a third row has to fail here. This is also the comparison the redraw
    loop itself makes ten times a second, so a test that could not write it is a test of something
    the terminal is not doing.
    """
    run = _run(tmp_path, activity="Edit: src/retry.py")

    assert views.board(run, REQUEST) == Screen(
        Rows([Row("request", REQUEST), Row("agent", "Edit: src/retry.py")])
    )


def test_the_board_shows_an_empty_cell_when_nothing_is_running(tmp_path: Path) -> None:
    """`run.activity` is `None` between steps, before an adapter's first line, and for the whole of
    a step replayed from the journal - where nothing is running and reporting anything would be a
    lie. An empty cell is what §3.7's own board renders for a ticket with no run behind it, and the
    alternative - "idle", "waiting" - would be this view asserting a state the framework never
    reported."""
    assert views.board(_run(tmp_path), REQUEST) == Screen(
        Rows([Row("request", REQUEST), Row("agent", "")])
    )


def test_the_board_reads_the_activity_again_on_every_frame(tmp_path: Path) -> None:
    """The property the whole design rests on: `show` registers this function and its arguments, so
    the board must read `run.activity` out of the live object rather than close over a string.

    Two calls either side of a change in what the agent is doing have to differ, and two calls with
    nothing changed in between have to be equal - the second half being what lets the terminal skip
    the write. A board handed the activity as a value would pass every other test in this file and
    fail this one by never changing at all.
    """
    run = _run(tmp_path, activity="Read: src/retry.py")
    first = views.board(run, REQUEST)

    run._steps._activity = "Bash: pytest -q"
    second = views.board(run, REQUEST)

    assert first != second
    assert second == views.board(run, REQUEST)


def test_the_board_is_passive_so_showing_it_never_waits_for_anybody(tmp_path: Path) -> None:
    """What the terminal dispatches on is whether `responses` is empty, and nothing at run time can
    see the `-> Screen` annotation. A board that grew a response would be queued as a question,
    would block `fix` at the `show` before its first step, and would do it identically on both
    terminals - so this is the assertion that the annotation and the value agree."""
    assert views.board(_run(tmp_path, activity="Bash: pytest -q"), REQUEST).responses == ()


# --- the question screen ---------------------------------------------------------------------


def test_the_question_screen_offers_the_agents_own_options_and_a_field_beside_them() -> None:
    """The ordinary question: what it asked, what it suggested, and room to say something else.

    Every option becomes a `Choice` whose label and whose `Answer` are that option verbatim -
    `Question.options` are "the exact string that goes back", not labels for something else - and
    the free-text field comes last, after everything the agent proposed. Compared as a whole
    `Screen`, which works even with a `TextInput` in it because `maps` is excluded from comparison.
    """
    asked = Question(prompt="Rename the helper, or leave it?", options=("rename", "leave"))

    expected: Screen[Answer] = Screen(
        "Rename the helper, or leave it?",
        [
            Choice("rename", value=Answer("rename")),
            Choice("leave", value=Answer("leave")),
            TextInput(FREE_TEXT, maps=Answer),
        ],
    )
    assert views.agent_question(asked) == expected


def test_a_question_that_forbids_free_text_is_shown_without_a_field() -> None:
    """`allow_free_text=False` is the agent saying it asked for a choice among what it offered, and
    honouring it here is the difference between a constraint and a suggestion. A view that offered
    the field anyway would let a person answer something the agent said it could not use, and
    nothing downstream would notice: the `Answer` is one string either way."""
    asked = Question(
        prompt="Which fixture?", options=("tmp_path", "monkeypatch"), allow_free_text=False
    )

    screen = views.agent_question(asked)

    assert screen.responses == (
        Choice("tmp_path", value=Answer("tmp_path")),
        Choice("monkeypatch", value=Answer("monkeypatch")),
    )


def test_a_question_with_no_options_is_answered_in_a_persons_own_words() -> None:
    """The open question - "empty is ordinary", and what every backend that can ask at all can ask.

    One response, and it must be there: a screen built from this question with no responses on it
    would be shown, would be un-dismissable, and would block its step forever, §3.7 having no
    timeouts anywhere.
    """
    screen = views.agent_question(Question(prompt="What should the retry limit be?"))

    assert screen.responses == (TextInput(FREE_TEXT, maps=Answer),)


def test_what_a_person_types_reaches_the_agent_as_the_answer_they_typed() -> None:
    """`maps` is the workflow's half of the free-text field: the terminal collects a string and
    never learns what an `Answer` is. Here the mapping is the `Answer` constructor itself, because
    this workflow has no richer answer type to map down from - so what a person typed is what the
    framework serialises back into the live agent session, unedited."""
    screen = views.agent_question(Question(prompt="What should the retry limit be?"))

    field = screen.responses[-1]
    assert isinstance(field, TextInput)
    assert field.maps("three, and log the last error") == Answer("three, and log the last error")


def test_the_body_is_the_agents_own_prompt_with_nothing_added_to_it() -> None:
    """No heading, no "the agent asks:", no framing sentence. `Question` refuses a header field
    because a backend whose question is the next turn of a conversation has nothing to derive one
    from, and a workflow writing its own words above the prompt would be answering for it. The
    `Text` is the port's own coercion of a bare `str` body, performed on the way in."""
    asked = Question(prompt="Is `src/retry.py` the right file?")

    assert views.agent_question(asked).body == Text("Is `src/retry.py` the right file?")


def test_the_question_this_screen_could_not_answer_cannot_be_built(tmp_path: Path) -> None:
    """The edge this view deliberately does not handle, and the reason it does not have to.

    A question with no options and no free text has no answer anybody could give it, and
    `ports/questions.py` refuses to construct one before any of this is reached. That refusal is
    what stands between `agent_question` and a screen with an empty `responses` tuple - shown,
    un-dismissable, blocking its step until somebody kills the run. It is pinned here rather than
    re-checked in the view because it is an assumption this package rests on and would fail silently
    if the port ever relaxed it.
    """
    with pytest.raises(InternalError):
        Question(prompt="Pick one.", options=(), allow_free_text=False)


# --- what preflight sees before anything is written -------------------------------------------


def test_the_declared_implementer_requires_what_the_negotiating_one_will(tmp_path: Path) -> None:
    """Preflight is two halves and this is what keeps the cheap one honest.

    `fix` hands `run.step` a `replace(implementer, on_question=answer)`, and `sdk/roles.py` folds
    `MID_RUN_QUESTIONS` into that role's `requires` as it is built - so the role that runs needs a
    backend able to ask whether or not `roles.py` says so. Half two of preflight would catch a
    backend that cannot, at the first step, after a record, a worktree and a branch already exist.
    The declaration is what moves that refusal to second zero, and this comparison is what says the
    two halves are asking the same question: if the declared set were ever the smaller one, half one
    would be passing runs that half two is going to refuse.
    """

    async def answer(question: Question) -> Answer:
        return Answer(question.prompt)

    assert replace(implementer, on_question=answer).requires == implementer.requires


# --- driving the whole workflow on fakes ------------------------------------------------------
#
# Everything from here down is 17.3. It drives `fix` the way its author would - `testing.harness`,
# `harness.run`, `harness.resume`, `harness.recorded`, `harness.fakes` - and asserts the decisions
# that live in the workflow function's own body, which is the one place in this package that
# importing something cannot reach.

SEED: Final = {"src/a.py": b"the user's own work\n"}
"""What the repository holds when the run starts: the state `agl/test` is cut from.

One file, and its content is never read by anything below - what it is for is that the checkout a
step is handed is not empty, so "the implementer added a file" and "the worktree was replaced" are
different observations rather than the same one."""

CHANGED: Final = "src/retry.py"
IMPLEMENTED: Final = b"the change the operator asked for\n"
REPAIRED: Final = b"the change, with what the review found put right\n"
SCRATCH: Final = "review-notes.txt"
"""The four things the scripted agent below writes into the checkout, and it does write them.

**A scripted agent that only returns a `Reply` commits nothing**, which is the trap this section is
built around: `commit_all` compares the checkout against the head and returns it unchanged when
nothing moved, so a run whose agents touch no file leaves a branch that never advances and three
`commit=` arguments that no assertion could tell apart. An `Agent` is the author's own function and
a real one edits files, so this one edits files - `task.workspace` is the checkout, on the task the
port hands it. The two contents differ so that the repair pass moves the tree a second time; two
identical writes would be a second no-op commit and the chain below would be one link short.

`SCRATCH` is the reviewer's, and it is the whole of what makes the missing `commit=` on the `review`
call observable: the wipe at the end of that step is what deletes it. A `review` that committed
would leave it on the branch forever."""

AT_IMPLEMENT: Final = {**SEED, CHANGED: IMPLEMENTED}
AT_REPAIR: Final = {**SEED, CHANGED: REPAIRED}
"""The tree at each of the run's two commits, written out rather than read back off the run.

They are what `_chain` recomputes the commit ids from, and writing them here is what makes that
recomputation an assertion rather than a tautology: a run that committed something else produces a
different id from these, and a run that committed the same thing under a different message does
too."""

HIGH_RUN: Final = ("implement", "review", "repair")
CLEAN_RUN: Final = ("implement", "review")
"""The two programmes `fix` has, and the branch over `findings.high()` is the whole difference.

Named as tuples of step names because that is what `harness.recorded` is compared against, and
because their *lengths* are what the kill-point sweep sweeps over."""

MUST_FIX: Final = _finding("high", CHANGED)
WORTH_KNOWING: Final = _finding("medium", CHANGED)
"""What the scripted reviewer reports. The medium one is not decoration: a run whose review found
something, none of it high, is the case that separates "the branch was taken" from "the reviewer
reported nothing at all", and `Findings.high()` is what has to tell them apart."""


def _payload(found: Sequence[Finding]) -> testing.Call:
    """`found` as the call the reviewer makes - the JSON a model sends, not the dataclass.

    `Call.payload` is a mapping and `sdk/testing.py` argues why at length: what a session carries is
    JSON, the tool's schema is derived from the payload type precisely so the model is shown the
    shape, and a call carrying an already-built `Findings` would be testing a conversion no session
    performs. So this writes the three fields out by hand, which is also what lets the assertions
    below compare `Recorded.value` against a mapping nothing in the framework could have invented.
    """
    return testing.Call(
        report_findings.name,
        {
            "findings": [
                {"severity": one.severity, "file": one.file, "summary": one.summary}
                for one in found
            ]
        },
    )


def _wrote(task: testing.AgentTask, name: str, content: bytes) -> None:
    """Put `content` at `name` inside the checkout this task was handed. What an agent does.

    `task.workspace` is the isolated checkout and is absolute, which the port insists on; the
    `mkdir` is because a real agent writes where it likes and the seed tree only happens to have
    made `src/` already.
    """
    place = task.workspace / name
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_bytes(content)


def _agent(seen: list[testing.AgentTask], *, found: Sequence[Finding]) -> testing.Agent:
    """The scripted agent for a whole run of `fix`, keeping every task it was handed.

    **What it keys on, and why it is not the step name.** `AgentTask` carries none, deliberately -
    `ports/agent.py` keeps AGL's ledger vocabulary out of the port. The reviewer is told apart by
    **the reporting tool's name**, which is the sharpest of the two handles `sdk/testing.py` names:
    this role reports through exactly one tool, this package named it, and `task.tools` carries it
    under that name. Its other handle, the model, would serve here too and does not separate the
    other two steps - `implement` and `repair` are one role, one model, one prompt and one empty
    tools tuple, and `roles.py` says why ("they differ in what they are given"). So what tells those
    two apart is the only thing that does differ: **their inputs**, which arrive as canonical JSON
    under a fixed heading, where `'"findings":'` is a key. The prompt's prose spells the same word
    in backticks and never with the quotes and colon a JSON key has, so the two cannot collide.

    **It asks nothing.** The harness builds a `HeadlessTerminal`, `fix` routes its implementer's
    questions to an interactive screen, and that pairing is a refusal - correctly, and it is what
    `test_the_implementers_question_reaches_this_workflows_own_screen` drives on purpose with an
    agent of its own. An agent used to assert anything else has to be explicit and has to not ask.

    `seen` is the instrument, and `config/container.py` says outright that this is where a test's
    knowledge belongs: there is no recorder on any agent fake, because "what a test wants to know is
    already held by the tool handlers and question handler it supplied itself". Every claim below
    about *what an agent was asked* - the composed prompt, the model, the provider, how many times
    it was paid for - is read out of this list.
    """

    def agent(task: testing.AgentTask) -> testing.Reply:
        seen.append(task)
        if any(tool.name == report_findings.name for tool in task.tools):
            _wrote(task, SCRATCH, b"what the reviewer scribbled while it read\n")
            return testing.Reply(calls=[_payload(found)], says="reviewed the change")
        if '"findings":' in task.instructions:
            _wrote(task, CHANGED, REPAIRED)
            return testing.Reply(says="repaired what the review found")
        _wrote(task, CHANGED, IMPLEMENTED)
        return testing.Reply(says="implemented the change")

    return agent


async def _record(harness: testing.Harness) -> Mapping[str, object]:
    """This run's `run.json`, through the store the harness wrapped.

    `agl.testing`'s own docstring sanctions the read - "its `store` is the recording one this
    harness wrapped, which delegates every call, so reading `run.json` back through it reads the
    same ledger the run wrote" - and it is where the branch name and the base commit come from.
    Composing either here instead would mean this file holding a second copy of §3.9's naming
    scheme, which is the thing it wants the run to have got right.
    """
    record = await harness.fakes.store.read_record(harness.scope)
    assert record is not None, "the run wrote no run.json, so it never started"
    return record


def _text(record: Mapping[str, object], key: str) -> str:
    """One string field of the record. `run.json` is `JsonValue`s, and two of them are needed."""
    value = record[key]
    assert isinstance(value, str), f"run.json holds a {type(value).__name__} at {key!r}"
    return value


def _files(where: Path) -> dict[str, bytes]:
    """Every file in a checkout, by its path relative to it. What a person would see in there."""
    return {
        path.relative_to(where).as_posix(): path.read_bytes()
        for path in sorted(where.rglob("*"))
        if path.is_file()
    }


def _chain(harness: testing.Harness, base: str, *commits: tuple[Mapping[str, bytes], str]) -> str:
    """The head `commits` compose, one after another from `base` - trees and messages included.

    **This is how a commit message is asserted, and it is a recomputation because nothing reads one
    back.** `FakeRepository` records a state under an id that is the digest of its tree, its parents
    and its message, and `record` is idempotent - "recording one twice is recording it once" - so
    building the chain this run was supposed to have made and comparing it against `tip` asserts
    every term of every commit at once: what was in it, what it was made on top of, and what it was
    called. Neither git port reads a message back (`tests/contracts/workspace.py` records that as
    something its suite deliberately cannot assert), so the alternative to this was asserting that
    *some* commit happened, which is what a missing `commit=` would also produce.

    Reported as a finding: a workflow author whose whole step-ending decision is a commit message
    has no way to read one, and this recomputation is a fake's internal vocabulary being spent on a
    question the ports do not answer.
    """
    head = base
    for tree, message in commits:
        head = harness.fakes.repository.record(tree, (head,), message)
    return head


@dataclass(frozen=True, slots=True)
class _Outcome:
    """Everything one run of `fix` leaves behind, in the four places it leaves anything.

    **This is the definition of "identical final state" the sweep compares on**, and each field is
    something the operator or the next agent would actually meet:

    * `entries` is the ledger - every step that recorded a result, in order, with the payload it
      recorded. A step that re-ran across two invocations appears here twice, which is §3.6's replay
      stated as an assertion: a replay "returns the stored value without running", writing nothing.
    * `head` is where `agl/<label>` points, and §3.3 makes that branch the deliverable of this
      workflow - nothing is merged into anything, so the branch *is* the result. It is comparable
      between two runs in two directories because the fake repository addresses a state by the
      digest of its content, its parents and its message, exactly as git does.
    * `checkout` is what is in the worktree on disk afterwards. Not implied by `head`: a step whose
      ending failed to wipe leaves a file that is in no commit, and a `head` comparison cannot see
      it.
    * `dispatches` is how many times an agent was paid for. Not part of the state, and in the
      comparison anyway, because a resume that recomputed a fingerprint would produce an identical
      final state and a doubled bill - which is the failure §3.6 calls loud in the bill and silent
      everywhere else.

    `at` timestamps are not here and neither is anything else off the entry: `Recorded` carries the
    `value` and not the digest, deliberately, and a workflow author asserting on a fingerprint would
    be asserting about the framework.
    """

    entries: tuple[testing.Recorded, ...]
    head: str | None
    checkout: Mapping[str, bytes]
    dispatches: int


async def _outcome(harness: testing.Harness, seen: Sequence[testing.AgentTask]) -> _Outcome:
    """Read the four back off a finished run. The checkout is found through the agent's own task.

    `task.workspace` is where the framework put this run's checkout, so a test that kept its tasks
    already knows the directory and needs neither `tree_layout` nor a path of its own composing.
    """
    record = await _record(harness)
    return _Outcome(
        entries=harness.recorded,
        head=harness.fakes.repository.tip(_text(record, "branch")),
        checkout=_files(seen[0].workspace),
        dispatches=len(seen),
    )


async def _finished(where: Path, *, found: Sequence[Finding]) -> _Outcome:
    """One uninterrupted run of `fix`, and what it left. The reference every sweep compares to."""
    seen: list[testing.AgentTask] = []
    harness = testing.harness(where, agent=_agent(seen, found=found), files=SEED)

    await harness.run(fix, "-r", REQUEST)

    return await _outcome(harness, seen)


# --- one complete run, both branches ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_whole_run_implements_reviews_and_repairs_on_fakes_alone(tmp_path: Path) -> None:
    """Target #8 for this workflow: three steps, no network, no git, no process, no display.

    The three assertions are the three things a run of `fix` is. The steps ran in the order the
    function calls them; the review's result is the payload its own agent reported, read back off
    the ledger through the type this package declares; and the repair ran, which is the branch over
    `findings.high()` taken in the direction that costs a second implementer.
    """
    seen: list[testing.AgentTask] = []
    harness = testing.harness(
        tmp_path, agent=_agent(seen, found=(MUST_FIX, WORTH_KNOWING)), files=SEED
    )

    await harness.run(fix, "-r", REQUEST)

    assert [entry.step for entry in harness.recorded] == list(HIGH_RUN)
    assert [entry.namespace for entry in harness.recorded] == [None, None, None]
    assert harness.recorded[1].value == _payload((MUST_FIX, WORTH_KNOWING)).payload


@pytest.mark.asyncio
async def test_a_review_that_found_nothing_high_ends_the_run_after_two_steps(
    tmp_path: Path,
) -> None:
    """The other side of §3.6's one rule for authors, driven rather than declared.

    The reviewer reports a medium finding - so the review found *something*, and the workflow still
    does not pay for a repair pass. That is what makes this test the pair of the one above rather
    than a weaker copy of it: a workflow branching on whether the findings list is empty would pass
    both of the `Findings.high()` unit tests above, run the repair here, and be wrong only in the
    bill and in what lands on the branch.

    The branch is over a value that came out of the ledger, which is the only kind of branch §3.6
    permits - so this test and the one above are the same run of the same function differing in one
    step result, and nothing else about them could have differed.
    """
    seen: list[testing.AgentTask] = []
    harness = testing.harness(tmp_path, agent=_agent(seen, found=(WORTH_KNOWING,)), files=SEED)

    await harness.run(fix, "-r", REQUEST)

    assert [entry.step for entry in harness.recorded] == list(CLEAN_RUN), (
        "a review that found nothing that must be fixed ran a repair pass anyway, so the workflow "
        "is branching on something other than `findings.high()`"
    )
    assert len(seen) == 2, "an agent was paid for a step the ledger says never happened"


# --- what the run leaves in the repository ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_run_commits_twice_under_its_own_messages_and_wipes_the_review(
    tmp_path: Path,
) -> None:
    """The three `commit=` decisions, which are the only difference between the three step calls.

    §3.3's table, asserted as one chain: `implement` commits what it left dirty under `implement
    fix`, `review` commits nothing and has its checkout restored, and `repair` commits on top under
    `address review findings`. `_chain` recomputes the two ids from the trees and the messages the
    workflow was supposed to have used, so every term is in the comparison - a missing `commit=`
    breaks the chain by leaving a link out, an extra one on `review` breaks it by putting the
    reviewer's scratch file into a tree and a third link into the parentage, and a reworded message
    breaks it while the trees still match.

    The second assertion is the wipe seen from the other side, and it is the half §3.3 calls "the
    single place in AGL where a mistake destroys work rather than costing a re-run". The reviewer
    really did write into the checkout; what is on disk afterwards is the repaired tree and nothing
    else, because the ending of a step that passed no `commit=` restores the head *and* removes
    everything that was not in it.
    """
    seen: list[testing.AgentTask] = []
    harness = testing.harness(tmp_path, agent=_agent(seen, found=(MUST_FIX,)), files=SEED)

    await harness.run(fix, "-r", REQUEST)

    record = await _record(harness)
    expected = _chain(
        harness,
        _text(record, "base_sha"),
        (AT_IMPLEMENT, "implement fix"),
        (AT_REPAIR, "address review findings"),
    )
    assert harness.fakes.repository.tip(_text(record, "branch")) == expected, (
        "the branch this run left is not base + `implement fix` + `address review findings`. A "
        "step that lost its `commit=` leaves a link out of that chain; a `review` that gained one "
        "puts a third link in and the reviewer's scratch file into a tree"
    )
    assert _files(seen[0].workspace) == AT_REPAIR, (
        f"the checkout holds {sorted(_files(seen[0].workspace))}. The reviewer wrote {SCRATCH!r} "
        f"into it, and the `review` step passes no `commit=` - so the framework restores the "
        f"checkout and removes everything that was not in it when that step ends"
    )


@pytest.mark.asyncio
async def test_the_operators_own_words_reach_the_implementer_and_the_findings_reach_the_repair(
    tmp_path: Path,
) -> None:
    """`request=run.params.request`, seen where it lands - in the prompt an agent was dispatched
    with.

    A params field that is never passed to a step is a field persisted into `run.json` that no agent
    ever sees, and nothing raises - the run works, the implementer is simply told nothing about what
    to implement. The framework appends `**inputs` as canonical JSON under a fixed heading and
    templates nothing, so the operator's words arrive in `task.instructions` verbatim, under a
    `request` key, and that is what is asserted.

    The repair's half is the same claim about `findings=findings.high()`, and it carries one extra
    term for free: what arrives is `high()`'s result and not the whole payload, so the medium
    finding the reviewer also reported must not be in the block the repair agent was handed.
    """
    seen: list[testing.AgentTask] = []
    harness = testing.harness(
        tmp_path, agent=_agent(seen, found=(MUST_FIX, WORTH_KNOWING)), files=SEED
    )

    await harness.run(fix, "-r", REQUEST)

    implement, _review, repair = seen
    assert f'"request":"{REQUEST}"' in implement.instructions, (
        "the implementer was dispatched without the request in its prompt, so the operator's own "
        "words reached the record and no agent"
    )
    assert implement.instructions.startswith(implementer.instructions)
    assert MUST_FIX.summary in repair.instructions
    assert WORTH_KNOWING.summary not in repair.instructions, (
        "the repair agent was handed every finding rather than `findings.high()`, so it is being "
        "asked to fix what the review said need not be fixed"
    )


@pytest.mark.asyncio
async def test_one_run_addresses_two_providers_and_both_preflight_checks_pass(
    tmp_path: Path,
) -> None:
    """Measurable target #4, proved by the workflow rather than by a framework test.

    "One run addresses two providers - `fix` uses Claude to implement and OpenAI to review, in one
    run, with both preflight checks passing." Three claims and all three are here:

    * **In one run.** One `harness.run`, one label, one worktree, and the tasks below came out of
      it in the order the function calls its steps.
    * **Two providers.** `task.model.provider` is derived from the model id and decides which
      adapter serves the task, so the assertion that the three dispatches are Claude, OpenAI,
      Claude is the assertion that two adapters served one run. Nothing in this package names a
      harness, an SDK or a binary to get that.
    * **Both preflight checks passing.** They already have by the time anything below runs: §3.2's
      preflight is `check_ready` over each distinct model and then `requires <= capabilities()` per
      role, and `api.run` performs it *before* the record is written - so a run that has a
      `run.json` and three entries is a run that passed both, for both providers, at second zero.
      That is the invisible half, so the two questions are asked again here explicitly, of the same
      runner the run used, in the test's own words.

    Asking them means reaching `harness.fakes.services.agents`, which is a field of the port-typed
    bundle rather than anything `FakeServices` exposes - `config/container.py` deliberately does not
    expose the agent runners, on the ground that a caller scripts them going in and reads the
    repository, the store and the terminal coming out. Reported as a finding: preflight is the one
    thing a run's outcome cannot show, because passing it leaves nothing behind.
    """
    seen: list[testing.AgentTask] = []
    harness = testing.harness(tmp_path, agent=_agent(seen, found=(MUST_FIX,)), files=SEED)

    await harness.run(fix, "-r", REQUEST)

    assert [task.model for task in seen] == [Claude.OPUS, OpenAI.SOL, Claude.OPUS]
    assert len({task.model.provider for task in seen}) == 2, (
        "one run of `fix` addressed one provider, so target #4's whole claim - Claude implements "
        "and OpenAI reviews, inside a single run - is not what this run did"
    )
    runner = harness.fakes.services.agents
    for role in (implementer, reviewer):
        # Preflight's two checks, in preflight's own order: availability first, over the model, and
        # then containment of what the role requires. Either one refusing is a run that never
        # starts - exit 6 for the first, exit 5 for the second.
        await runner.check_ready(role.model)
        assert role.requires <= await runner.capabilities(role.model), (
            f"the backend serving {str(role.model)!r} does not offer everything this role "
            f"requires, so preflight would refuse this run at second zero"
        )


# --- the two screens, as a run reaches them ------------------------------------------------------


class _Watching(Terminal):
    """A `Terminal` that keeps what `show` was handed and draws none of it.

    Written from `agl.sdk` alone - `Terminal`, `Screen` - and handed to
    `testing.harness(terminal=)`, which is the harness's own documented seam for a bundle whose
    terminal has to be something other than the headless one. It exists for one question no
    conforming `Terminal` can answer: *what were you given*. `HeadlessTerminal` reads a passive
    screen for its responses and drops it on the same line, deliberately, so a board that was put up
    correctly and a board that was never put up at all are the same observation on the bundle
    `testing.harness()` builds.

    **It is not a second headless terminal and makes no claim to be**, exactly as
    `tests/sdk/test_run_terminal.py::_Recording` says of itself: `tests/contracts/terminal.py` is
    what says how a `Terminal` behaves and this class is under its eye nowhere at all. It is used by
    one test, it answers nothing, and a `Screen` carrying responses is a failure here rather than a
    question it might quietly answer with `None` - which is the shape 17.2 flagged and is not a
    thing this file is going to grow.
    """

    def __init__(self) -> None:
        self.shown: list[tuple[Callable[..., Screen[object]], dict[str, object]]] = []
        """One entry per `show`, holding the view and its arguments exactly as they arrived."""

    async def show[T](
        self,
        view: Callable[..., Screen[T]],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        self.shown.append((cast("Callable[..., Screen[object]]", view), dict(params)))
        if view(**params).responses:
            raise AssertionError(
                f"the view {getattr(view, '__name__', view)!r} asks a question and this terminal "
                f"answers nothing. AGL ships no input-capable `Terminal` a workflow author can "
                f"drive, and a recorder that invented an answer here would be that gap papered over"
            )
        return cast("T", None)

    @property
    def pending(self) -> Mapping[int, int]:
        return {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_the_board_goes_up_once_with_the_run_and_the_request_on_it(tmp_path: Path) -> None:
    """§3.7's board, put up by the workflow rather than called by a test.

    `show` registers this function and its arguments and the loop invokes it again per frame, so
    what is asserted is exactly that: the view that arrived is this package's `board`, the arguments
    are the live `Run` and the request, and invoking the registered pair again produces the screen
    a person would have been looking at. A workflow that passed the activity line as a value rather
    than the run would satisfy every board test in the first half of this file and be frozen at the
    moment of the `show`.

    **Once**, which §3.3's own docstring argues is enough: a board re-reads `run.activity` every
    frame for as long as the run lasts, so a second `show` would only ever mean putting a different
    view on screen. A workflow that showed it per step would show three here.
    """
    watching = _Watching()
    seen: list[testing.AgentTask] = []
    harness = testing.harness(
        tmp_path, agent=_agent(seen, found=(MUST_FIX,)), files=SEED, terminal=watching
    )

    await harness.run(fix, "-r", REQUEST)

    assert [view for view, _params in watching.shown] == [views.board], (
        "the run put something other than exactly one board on screen. `fix` shows its board once, "
        "before its first step, and nothing else passive for the rest of the run"
    )
    view, params = watching.shown[0]
    assert params["request"] == REQUEST
    assert isinstance(params["run"], Run)
    assert view(**params) == Screen(Rows([Row("request", REQUEST), Row("agent", "")]))


@pytest.mark.asyncio
async def test_the_implementers_question_reaches_this_workflows_own_screen(tmp_path: Path) -> None:
    """§3.7's callback on the Role, driven to the one ending a shipped terminal can produce.

    The agent asks; `fix`'s `answer` closure puts the question on `views.agent_question`; the
    headless terminal refuses it because a screen carrying responses needs somebody to answer it and
    there is nobody. The refusal names the view, and that is what makes this a test of *this
    workflow* rather than of the terminal: the string `agent_question` is in the message because the
    handler in `fix`'s own body chose that view for that question.

    **Three of the workflow's decisions are in this one refusal**, and each fails differently:
    a handler routing to the board raises from the view's own signature instead; a workflow handing
    `run.step` the declared `implementer` rather than `replace(implementer, on_question=answer)`
    passes no handler at all, and both fakes then answer the agent "nobody is listening" and let it
    carry on - so the run *completes*, the approval gate silently absent, which is the outcome
    `sdk/roles.py` spends four paragraphs refusing.

    **What this cannot do is answer.** 17.2 recorded the gap - AGL ships no input-capable `Terminal`
    an external author can drive - and this file does not repair it: the question path is asserted
    as far as the screen and no further, and `harness.recorded` being empty is the honest statement
    of where the run stopped. A step that raised writes no entry (§3.6), so the implement step is
    unrecorded, the branch is at its base, and `agl resume` would start it again attended.
    """

    def asking(task: testing.AgentTask) -> testing.Reply:
        return testing.Reply(asks=[Question(prompt="Rename the helper, or leave it?")])

    harness = testing.harness(tmp_path, agent=asking, files=SEED)

    with pytest.raises(UpstreamUnavailable, match="agent_question"):
        await harness.run(fix, "-r", REQUEST)

    assert harness.recorded == (), "a step that died on an unanswerable question left an entry"


# --- kill at every step boundary, resume, assert identical --------------------------------------


def _kill_points(total: int) -> tuple[tuple[int, ...], ...]:
    """Every way a run of `total` steps can be interrupted, as the sizes of its invocations.

    For three steps: `(1,)`, `(2,)`, `(3,)`, `(1,1)`, `(1,2)`, `(2,1)`, `(1,1,1)` - which is every
    boundary the run can stop at, and every *combination* of boundaries it can stop at more than
    once. A sweep over single kill points would cover the first three; the rest are what make the
    per-invocation counter observable, because only an invocation that is not the first can tell a
    count of its own entries from a count of every entry ever.

    The tuples that sum to less than `total` are the runs that were interrupted and then finished;
    the ones that sum to `total` are the runs that recorded everything and were interrupted at the
    very last boundary, where the resume afterwards has nothing left to do and must do nothing.
    """
    found: list[tuple[int, ...]] = []
    for first in range(1, total + 1):
        found.append((first,))
        found.extend((first, *rest) for rest in _kill_points(total - first))
    return tuple(found)


SWEEP: Final = tuple(
    pytest.param(
        high,
        kills,
        id=f"{'repair' if high else 'clean'}-{'+'.join(str(size) for size in kills)}",
    )
    for high in (True, False)
    for kills in _kill_points(len(HIGH_RUN if high else CLEAN_RUN))
)
"""Every kill point of both of `fix`'s programmes: ten cases, seven of them three steps long."""


@pytest.mark.asyncio
@pytest.mark.parametrize(("high", "kills"), SWEEP)
async def test_an_interrupted_run_of_fix_ends_where_an_uninterrupted_one_does(
    high: bool, kills: tuple[int, ...], tmp_path: Path
) -> None:
    """§3.6's acceptance criterion, on this workflow: interrupt at every boundary, resume, compare.

    Two runs of `fix` in two directories. One is never interrupted; the other is interrupted after
    `kills[0]` entries, resumed and interrupted again after `kills[1]`, and so on, and then resumed
    without a bound until it finishes. `_Outcome` is what "identical" means and its docstring is
    where that definition is argued: the ledger, the branch the run is *for*, the checkout on disk,
    and the number of agents anybody was billed for.

    **The intermediate assertion is the one that makes the sweep more than decorative.** The final
    state of a run that was interrupted in the wrong place is still the final state, because the
    last invocation is unbounded and finishes whatever is left - so a file that carried
    `interrupt_after=`'s per-invocation counter wrongly would sweep two boundaries over and over
    and stay green. What that cannot survive is a running total: after each invocation the ledger
    must hold exactly the steps that were asked for, which pins where each interruption landed.

    **And the dispatch count is the replay property.** §3.6's replay "returns the stored value
    without running", writing nothing, so a step that appears in `recorded` twice across two
    invocations is a step whose fingerprint moved between them and whose agent was paid for twice.
    Comparing the whole entry list against the uninterrupted run's says that in one comparison, and
    `dispatches` says it again from the side the operator pays on.

    The harness's interruption is not a kill and this file's docstring says so at length; what is
    asserted here is that *this workflow* is resumable, not that the journal survives a process.
    """
    steps = HIGH_RUN if high else CLEAN_RUN
    found = (MUST_FIX, WORTH_KNOWING) if high else (WORTH_KNOWING,)
    reference = await _finished(tmp_path / "uninterrupted", found=found)
    # The reference pinned rather than assumed. Everything below compares against it, so a
    # reference that did nothing would make every case agree about nothing - and `_Outcome` is a
    # value, so two empty ones are equal.
    assert [entry.step for entry in reference.entries] == list(steps)
    assert reference.dispatches == len(steps)
    assert reference.head is not None

    seen: list[testing.AgentTask] = []
    harness = testing.harness(tmp_path / "interrupted", agent=_agent(seen, found=found), files=SEED)

    done = 0
    for at, size in enumerate(kills):
        if at == 0:
            await harness.run(fix, "-r", REQUEST, interrupt_after=size)
        else:
            await harness.resume(fix, interrupt_after=size)
        done += size
        assert [entry.step for entry in harness.recorded] == list(steps[:done]), (
            f"invocation {at + 1} was asked for {size} step(s) of its own and the ledger holds "
            f"{[entry.step for entry in harness.recorded]} where {list(steps[:done])} was due. "
            f"`interrupt_after=` counts what that invocation wrote, so a sweep carries the running "
            f"total itself - and one that carried it wrongly would interrupt somewhere other than "
            f"where it says and still finish correctly"
        )

    await harness.resume(fix)

    assert await _outcome(harness, seen) == reference, (
        "an interrupted and resumed run of `fix` did not end where the uninterrupted one ends. A "
        "differing ledger is a step that re-ran under a digest the resume computed differently or "
        "one it skipped; a differing head is different work on the branch this workflow exists to "
        "produce; a differing checkout is a step ending that did not run; a differing dispatch "
        "count is an agent paid for twice"
    )
