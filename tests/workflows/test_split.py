"""What `workflows/split/` owns, in two halves, of which this is the first.

**The first half is what this package declares** - the payload type a planner reports through, and
the two screens - and none of it needs a terminal or a run: a `Chunks` is built by calling it and a
view is a pure function of its arguments, so every assertion here is a call and a comparison
against the value it returned, with no display, no redraw loop, no gestures and nothing that could
block. **The second half is the run itself**, in `tests/workflows/test_split_runs.py`. The line
between them is `test_fix.py`'s and is drawn in the same place, for the reason that file
argues: what a person would have been shown, and what a model is told when it gets a payload wrong,
are the halves this package owns, and reading them is the cheaper claim and worth keeping cheap.

## The three refusals, which are the only code `chunks.py` has

`Chunk.__post_init__` and `Chunks.__post_init__` are two `if`s and a constructed-and-discarded
`Namespace`, and that module's docstring spends most of its length arguing each one against a single
test: *would the run otherwise reach a state only `agl clear` gets it out of?* Three do - a
malformed id, two ids that collide, and an empty plan - and every one of them fails in a way no
other test in this repository can see, because all three are refusals that never happen on a plan
anybody writes by hand.

**What makes them worth testing here rather than through a run is where they fire.** A rule enforced
inside the payload type is enforced *inside the tool call*: `sdk/tools.py::_instance` builds the
dataclass in a `try` and turns whatever it raises into a rejection carried back into the same
conversation, so the planner is told what it did and sends another call - one round trip instead of
a dead run. The same rule enforced one line later, at `run.worktree(chunk.id)`, is a run whose
`plan` entry is already journalled, so `agl resume` replays the bad plan as a cache hit and dies at
the same line forever. So each test below asserts the refusal **and** that it arrives as
`report_chunks.rejection(...)` rather than as an exception, which is the difference between the two.

The fourth test is the one that gives the other three their teeth: a well-formed plan is accepted
and reads back as what was reported. Without it a payload type that refused everything passes.

## Every screen is asserted whole, and that is not a style preference

Value equality on every component is what the redraw loop itself compares, ten times a second, to
decide whether to write anything at all (`ports/terminal.py`: "that comparison is the entire reason
per-frame re-invocation is cheap"). So a test that picked cells out of a `Screen` would be testing
something the terminal is not doing, and would pass for a board that put its rows the other way
round or grew a fourth one. The comparisons below are the terminal's own.

The one exception is the build-output tail, which is asserted by property rather than as a literal:
a fixture spelling out which lines survive a bound in characters would be this file restating
`_tail`'s arithmetic and agreeing with itself. What is asserted there instead is what the bound is
*for* - that the rows are whole lines of the build's own output, that the end of it is what
survived, and that the beginning of it did not.

## The board needs a `Run` per chunk, and that is now one call each

The board reads `runs[id].activity` out of live child `Run`s rather than being handed strings,
which is the whole reason `show` registers a function and its arguments. So a board test needs real
`Run`s - and `agl.sdk` cannot build one: `services` is `sdk/_engine`'s bundle and `scope` is a
`ports.home_layout.RunScope`, both the framework's to compose. `testing.a_run(harness, params,
activity=...)` is the answer to that, and `testing.reports(run, line)` is what plays the adapter
when a test wants to watch the board *move*.

`split` is the first workflow to want several at once, and what it wants is not several `a_run`s:
it is one, and then `run.worktree(id)` per chunk, which is the workflow's own line and is on the
SDK's front door. `_runs` below is the whole of what that costs, and the argument for building the
fixture that way rather than out of siblings is there.

## One name still comes from `agl.ports`, and it is reported rather than repaired

`Conflict` and `VerifierOutcome` were once reaches into `agl.ports` and are now on `agl.sdk`'s
front door. `JsonValue` below is not, and the argument for leaving it is that it is not a
*workflow's* name: no module under `src/agl/workflows/` mentions it, and what wants it here is a
test building the payload a scripted agent reports and reading a record back afterwards. That is
`agl.testing`'s vocabulary rather than `agl.sdk`'s - `Call.payload` is a `Mapping[str,
JsonValue]` and `agl.testing` re-exports `Call` without it - so the door it is missing from is the
test harness's and not the authoring surface's. Recorded here, unpaid, as the other two were.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final
import pytest
from agl import testing
from agl.ports.run import JsonValue
from agl.sdk import (
    Choice,
    Conflict,
    InputError,
    Row,
    Rows,
    Run,
    Screen,
    VerifierOutcome,
)
from agl.workflows.split import SplitParams, views
from agl.workflows.split.chunks import Chunk, Chunks, report_chunks
from agl.workflows.split.views.conflict import ABORT, RETRY

REQUEST: Final = "split the importer into three pieces"
"""What an operator asked for. Nothing on either screen renders it - `split`'s board shows the
chunks a planner divided it into, not the sentence it was divided from - so it is here only because
`SplitParams` requires it."""

CHUNKS: Final = (
    Chunk(id="parser", work="pull the token reader out", files=("src/parse.py",)),
    Chunk(id="api", work="expose it", files=("src/api.py", "src/__init__.py")),
    Chunk(id="docs", work="write it up", files=()),
)
"""A plan, in the order a planner reported it - **which is not alphabetical, deliberately**.

`Chunks.items` keeps the planner's order and says it means nothing; the board renders it unchanged,
and a view's purity rule names sorting as the first thing it may not do. Ids that sort into a
different order are what makes the exact-`Screen` comparisons below able to notice a board that
sorted them anyway."""

def _runs(where: Path, activities: Mapping[str, str | None]) -> dict[str, Run[SplitParams]]:
    """The live dict the workflow hands its board: one child `Run` per chunk id, at an activity.

    **Built the way the workflow builds it** - `{chunk.id: run.worktree(chunk.id)}` - and not as N
    `a_run`s side by side. `worktree()` is on the SDK's front door and is synchronous and lazy, so
    a child costs nothing here and `a_run`'s promise that nothing it builds opens a workspace still
    holds; what it buys is that these are the same objects `split` puts in `children`, each with its
    own activity cell, rather than N root `Run`s over one scope that only resemble them. A board is
    a view of a dict of children, and a fixture of siblings would be a fixture of something else.

    `a_run`'s `activity=` keyword cannot reach a child, so every line goes on through
    `testing.reports`, which is the same call and the same one sanctioned reach.

    Every key present from the first frame is `split`'s own guarantee - `children` is a
    comprehension over the same `plan.items` the board iterates, before the `TaskGroup` opens - so
    a test that wants the absent-key case leaves an id out of `activities` rather than out of
    `CHUNKS`.
    """
    parent = testing.a_run(testing.harness(where), SplitParams(request=REQUEST))
    children = {chunk_id: parent.worktree(chunk_id) for chunk_id in activities}
    for chunk_id, activity in activities.items():
        testing.reports(children[chunk_id], activity)
    return children

# --- the plan a planner reports ------------------------------------------------------------------

MALFORMED: Final = (
    ("chunk 1", "SPACE"),
    ("src/parse", "'/'"),
    ("-parser", "starts with '-'"),
    ("_base", "the run's own base worktree"),
)
"""Four ids `run.worktree()` would refuse, and a fragment of the reason each one is refused for.

Not an exhaustive tour of `ports/ids.py` - that rule has its own suite and this module does not own
it. These are the four shapes a *planner* actually invents: a phrase with a space in it, a path, a
name that reads as a flag to any command taking it as an argument, and the one word the trees layout
has already spent. The reason fragment is asserted along with the refusal because a message that
did not name the character and the position is one nothing can act on - and the model is the thing
being asked to act on it."""

def _reported(*ids: str) -> dict[str, JsonValue]:
    """A `report_chunks` payload naming `ids`: the JSON a model sends, not a `Chunks`.

    `sdk/tools.py` derives the schema from the payload type precisely so the model is shown the
    shape, so the rejection path is only reachable from the shape a session carries. `work` and
    `files` are the same for every chunk here because neither is checked by anything - the module
    docstring of `chunks.py` draws that line and says where it comes from.
    """
    items: list[JsonValue] = [{"id": one, "work": "do the thing", "files": []} for one in ids]
    return {"items": items}

@pytest.mark.parametrize(("bad", "because"), MALFORMED)
def test_an_id_the_framework_would_refuse_as_a_worktree_is_refused_in_the_tool_call(
    bad: str, because: str
) -> None:
    """`Chunk.__post_init__`'s one line, and the reason it is a line rather than a comment.

    `split` passes `chunk.id` to `run.worktree()`, which is `Namespace(name)`, which is the
    framework's allowlist - so an id like these is refused whatever this module does. What this
    check changes is **when**: here it is inside the tool call, where `sdk/tools.py::_instance`
    catches it and `rejection` carries the sentence back into the same conversation for the planner
    to correct; one line later, at `worktree()`, the `plan` entry is already journalled and `agl
    resume` replays the bad plan as a cache hit and dies at the same line every time until somebody
    runs `agl clear` and pays for the planner again.

    So both halves are asserted, and the second is the one that matters. `InputError` from `Chunk`
    is the rule being applied; `report_chunks.rejection(...)` answering **a string rather than
    raising** is the rule being applied where it costs a round trip instead of a run. A
    `__post_init__` deleted from `Chunk` leaves both of these answering nothing at all, and every
    other test in this package passes.
    """
    with pytest.raises(InputError, match="cannot be used"):
        Chunk(id=bad, work="pull the token reader out", files=("src/parse.py",))

    refusal = report_chunks.rejection(_reported(bad))

    assert refusal is not None, (
        f"a plan naming the chunk {bad!r} was accepted by the tool. `run.worktree({bad!r})` is "
        f"going to refuse it a line later, with the entry for `plan` already on the ledger - which "
        f"is a run no resume can get past and only `agl clear` ends"
    )
    assert because in refusal, (
        f"the rejection does not say why {bad!r} cannot be a name: {refusal!r}. The schema cannot "
        f"carry the rule - a derived `str` field is `{{\"type\": \"string\"}}` and nothing else - "
        f"so this text is the only place a model that guessed wrong is told what it may write"
    )

def test_two_ids_that_are_two_refs_to_git_and_one_directory_are_refused_together() -> None:
    """The rule that needs the whole plan in view, and is therefore on `Chunks` and not `Chunk`.

    A namespace is unique run-wide and compares with `collision_key` - casefold then NFC - because
    `parser` and `Parser` are two branches to git and one directory on macOS. Unchecked here, the
    second `run.worktree()` raises `ConflictError` after `plan` is journalled, which is the same
    dead run the test above is about; and on a case-insensitive filesystem the failure that check
    *prevents* is worse than a refusal, because the second child's checkout would be the first
    one's.

    The comparison is the framework's own and not a lowercasing of this file's, so the assertion is
    on the reason and not only on the class: a message that did not say the two names are one
    directory would leave a model to guess that the ids merely have to differ.
    """
    with pytest.raises(ValueError, match="one directory") as raised:
        Chunks(
            (
                Chunk(id="parser", work="pull the token reader out", files=()),
                Chunk(id="Parser", work="expose it", files=()),
            )
        )

    assert "'parser'" in str(raised.value) and "'Parser'" in str(raised.value), (
        f"the refusal does not name the two chunks it is about: {raised.value}. A plan of six "
        f"chunks refused for a collision nobody can point at is one a planner rewrites at random"
    )
    assert report_chunks.rejection(_reported("parser", "Parser")) is not None, (
        "two chunks whose ids differ only by case were accepted by the tool, so the second "
        "`run.worktree()` raises after the plan is journalled - and on a case-insensitive "
        "filesystem the two children share one checkout"
    )

def test_a_plan_with_no_chunks_in_it_is_refused_because_the_run_would_report_success() -> None:
    """The refusal with no framework behind it, which is what makes it the sharpest of the three.

    A malformed id and a collision are both refused downstream by AGL, loudly, at the wrong moment;
    an **empty** plan is refused nowhere at all. `split`'s `TaskGroup` has nothing to create, the
    workflow returns, `api.run` writes no failure and the operator is told the run succeeded over a
    job nobody did. Nothing raises, nothing is logged, and the branch the run exists to produce is
    at the commit it was cut from.

    That is the one failure in this package that is silent end to end, and this line is the whole of
    what stands between AGL and it.
    """
    with pytest.raises(ValueError, match="not a plan"):
        Chunks(())

    refusal = report_chunks.rejection(_reported())

    assert refusal is not None, (
        "a plan with no chunks was accepted, so a `split` run over it opens nothing, runs nothing "
        "and reports success"
    )
    assert "at least one chunk" in refusal, (
        f"the rejection does not tell the planner what to do instead: {refusal!r}. A job too small "
        f"to divide is a plan with one chunk in it, and a model told only that its answer was "
        f"refused has no way to know that is an answer"
    )

def test_a_well_formed_plan_is_accepted_and_reads_back_as_the_chunks_it_reported() -> None:
    """The other half of the three above, and the reason they are worth having.

    Every refusal in this module is a `__post_init__` that raises, and a type that raised on
    everything would satisfy all three tests above and this package would be unusable. So this is
    the plan `CHUNKS` is - three ids that are legal, distinct and not `_base`, with a real file list
    on two of them and an empty one on the third, which `chunks.py` admits deliberately as a planner
    that could not predict the paths.

    `read` is asserted rather than `rejection is None` alone, because what the workflow does with
    this payload is `plan.items` - so what has to survive the round trip is the tuple of `Chunk`s in
    the planner's own order, not merely the absence of a complaint.
    """
    reported: dict[str, JsonValue] = {
        "items": [
            {"id": chunk.id, "work": chunk.work, "files": list(chunk.files)} for chunk in CHUNKS
        ]
    }

    assert report_chunks.rejection(reported) is None, (
        f"a plan of three legal, distinct ids was refused: {report_chunks.rejection(reported)}. "
        f"Every rule in this module is a `__post_init__` that raises, and one that raises on a "
        f"good plan refuses every plan there is"
    )
    assert report_chunks.read(reported) == Chunks(CHUNKS), (
        "the payload did not read back as the plan that was reported. `split` branches on "
        "`plan.items` and on nothing else, so a round trip that dropped a chunk, reordered them or "
        "lost a file list is a run that divides the job differently from the way it was divided"
    )

# --- the board ---------------------------------------------------------------------------------

def test_the_board_is_a_row_per_chunk_with_the_line_that_chunks_agent_last_reported(
    tmp_path: Path,
) -> None:
    """The whole board over three concurrent chunks, as one value.

    This is the shape `fix`'s board is not: N rows, in the planner's own order, each naming a chunk
    and what its own agent is doing right now - three different lines from three different child
    `Run`s, which is the claim that the activity cell is read per row and not once for the run.

    The middle chunk's agent is between steps, so its cell is empty. That is the same cell an absent
    run gets below, and deliberately so: a person cannot act on the difference, and "idle" or
    "waiting" would be this view asserting a state the framework never reported.
    """
    runs = _runs(
        tmp_path, {"parser": "Edit: src/parse.py", "api": None, "docs": "Bash: mkdocs build"}
    )

    assert views.board(CHUNKS, runs) == Screen(
        Rows(
            [
                Row("parser", "Edit: src/parse.py"),
                Row("api", ""),
                Row("docs", "Bash: mkdocs build"),
            ]
        )
    )

def test_the_board_reads_every_activity_again_on_every_frame(tmp_path: Path) -> None:
    """The property the whole design rests on, and the one a board handed values passes by never
    changing at all.

    `show` registers this function and the dict, not the table it produced, so the board has to read
    `runs[id].activity` out of the live child `Run` on every invocation. Two calls either side of a
    change in what one agent is doing have to differ; two calls with nothing changed in between have
    to be equal, which is the half that lets the terminal skip the write.

    `testing.reports` is what plays the adapter here - the cell behind `run.activity` is written for
    real by a backend reporting from inside a running step, and this stands in for that call. Note
    that it is the *same dict and the same `Run` objects* on both sides: a board that closed over
    the activity lines at composition time, or that cached them against the dict it was handed,
    would render an empty table for the whole run and fail only here.
    """
    runs = _runs(tmp_path, {"parser": "Read: src/parse.py", "api": None, "docs": None})
    first = views.board(CHUNKS, runs)

    testing.reports(runs["parser"], "Bash: pytest -q")
    second = views.board(CHUNKS, runs)

    assert first != second
    assert second == views.board(CHUNKS, runs)

def test_a_chunk_with_no_run_behind_it_gets_the_cell_an_idle_one_gets(tmp_path: Path) -> None:
    """A view may be composed before every child exists, so the workflow guards its own lookups
    with `runs.get(id)`.

    `split` cannot produce this - `children` is a comprehension over the same `plan.items` the board
    iterates, built before any concurrency starts, so every key is present from the first frame. The
    guard is written anyway because the guarantee is the workflow's and the view is a separate
    value: a later edit that provisioned inside the child would turn a missing key into a
    `KeyError` raised inside the redraw loop against a screen already displayed, where
    `ports/terminal.py` says there is no caller left to hand it to.
    """
    runs = _runs(tmp_path, {"parser": "Edit: src/parse.py", "docs": None})

    assert views.board(CHUNKS, runs) == Screen(
        Rows([Row("parser", "Edit: src/parse.py"), Row("api", ""), Row("docs", "")])
    )

def test_the_board_is_passive_so_showing_it_never_waits_for_anybody(tmp_path: Path) -> None:
    """What the terminal dispatches on is whether `responses` is empty, and nothing at run time can
    see the `-> Screen` annotation. A board that grew a response would be queued as a question
    rather than put in the slot, and `split` would block at the `show` between its namespaces and
    its `TaskGroup` - before a single chunk had been dispatched."""
    runs = _runs(tmp_path, {"parser": "Edit: src/parse.py", "api": None, "docs": None})

    assert views.board(CHUNKS, runs).responses == ()

# --- the conflict screen -----------------------------------------------------------------------

COLLIDED: Final = Conflict(
    ("src/api.py", "src/__init__.py"),
    "agl/_work/demo/api will not combine into agl/demo: src/api.py, src/__init__.py. "
    "The landing is held in /trees/demo/_base",
)
"""A textual collision, spelled the way `adapters/git/_conflicts.py` spells one.

The summary names the **source** branch, which is `agl/_work/<label>/<id>` - which is where a person
at this screen reads which chunk it is about, and why the view is not given the `Chunk` as a third
parameter."""

def test_the_screen_for_work_that_would_not_combine_is_the_conflict_and_the_two_verbs() -> None:
    """The ordinary conflict, whole: what stopped it, which files, and the two ways out.

    One row for the summary - the only part of a `Conflict` guaranteed to say anything - and one per
    colliding path, so that a list of files reads as a list rather than as a line. `verdict` is
    `None`, which is `Integration.verdict`'s spelling of "the work would not combine" as against
    "it combined and then failed the gate", and nothing about the build appears.
    """
    expected: Screen[bool] = Screen(
        Rows([Row(COLLIDED.summary), Row("src/api.py"), Row("src/__init__.py")]),
        [Choice(RETRY, value=True), Choice(ABORT, value=False)],
    )

    assert views.conflict(COLLIDED, None) == expected

def test_each_response_produces_the_value_the_workflow_branches_on() -> None:
    """The call site is `if await run.terminal.show(views.conflict, ...)`, so what this screen
    returns is what decides between the two verbs that release the lease.

    Asserted as identities rather than as truthiness: a `Choice` whose value was a non-empty string
    would satisfy the `if` on both branches, and the run would retry a landing a person gave up on -
    forever, since the loop is a `while`. `True` and `False` also compare by value, which is what
    keeps two frames of one unchanged conflict equal and the terminal quiet.
    """
    retry, give_up = views.conflict(COLLIDED, None).responses

    assert isinstance(retry, Choice)
    assert isinstance(give_up, Choice)
    assert retry.value is True
    assert give_up.value is False

def test_a_conflict_that_cannot_name_the_colliding_files_shows_only_its_summary() -> None:
    """`Conflict.paths` is explicit that `()` means "I cannot tell you which" and never "nothing
    collided" - an integrator whose far side answers only "these will not combine cleanly" is a real
    implementation, and the summary is then the whole of what a person has. No rows are invented for
    it, and the screen is still answerable."""
    unnamed = Conflict((), "the two lines of work will not combine, and nothing here can say where")

    assert views.conflict(unnamed, None) == Screen(
        Rows([Row(unnamed.summary)]),
        [Choice(RETRY, value=True), Choice(ABORT, value=False)],
    )

def test_a_red_gate_puts_the_builds_own_output_on_the_screen() -> None:
    """The other kind of conflict: the work combined, and then the build gate said no.

    `verdict` set is how `Integration` tells the two apart, and this is the screen that reads it.
    The build's output is the only thing that says *why*, it is live-only and on the outcome, and if
    this screen drops it nobody ever sees it - so it is here, under a heading naming the status the
    runner reported. The status is carried "so that a person can see it" and nothing branches on it,
    which is exactly what a row of a screen is for.

    The two responses are unchanged, because the decision is unchanged: both kinds of conflict hold
    the lease and both are ended by the same two verbs. That is why this is one view with two bodies
    rather than two views with one decision spread across them.
    """
    gate = VerifierOutcome(passed=False, status=1, output="FAILED tests/test_api.py::test_it")
    refused = Conflict((), "the landing built red: `pytest -q` exited 1. It is held in /trees/demo")

    assert views.conflict(refused, gate) == Screen(
        Rows(
            [
                Row(refused.summary),
                Row("The build exited 1, and its output ended like this:"),
                Row("FAILED tests/test_api.py::test_it"),
            ]
        ),
        [Choice(RETRY, value=True), Choice(ABORT, value=False)],
    )

def test_a_gate_that_printed_nothing_shows_its_status_and_stops_there() -> None:
    """Empty output is legal - `VerifierOutcome.output` says passing builds routinely print nothing,
    and a build killed for memory can print nothing on its way out. The heading still goes up,
    because the status and the fact of the red gate are worth reading on their own, and no empty row
    is invented underneath it to stand for text that does not exist."""
    silent = VerifierOutcome(passed=False, status=137, output="")
    refused = Conflict((), "the landing built red: `make check` exited 137")

    assert views.conflict(refused, silent) == Screen(
        Rows(
            [
                Row(refused.summary),
                Row("The build exited 137, and its output ended like this:"),
            ]
        ),
        [Choice(RETRY, value=True), Choice(ABORT, value=False)],
    )

def test_a_long_build_log_is_shown_from_its_end_in_whole_lines() -> None:
    """The bound, asserted by what it is for rather than by restating its arithmetic.

    This function runs ten times a second for as long as the screen is up, so the work it does may
    not depend on how much a build printed - hence a bound in characters, taken from the end,
    because a failing build's reason is at its end. Three things follow and all three are here: the
    last line the build printed is the last row, the beginning of the log is gone, and **every row
    is a whole line of the build's own output** - the fragment of a line the slice cut through is
    dropped rather than shown, because half a stack frame reads as a whole one.
    """
    printed = [f"tests/test_{index}.py {'.' * (index % 9)}" for index in range(400)]
    noisy = VerifierOutcome(passed=False, status=1, output="\n".join(printed))
    refused = Conflict((), "the landing built red: `pytest -q` exited 1")

    body = views.conflict(refused, noisy).body
    assert isinstance(body, Rows)
    # The summary and the heading, then the log: a conflict with no paths to name so that the two
    # rows in front of it are a constant rather than something this assertion has to count.
    shown = [row.cells[0].value for row in body.rows[2:]]

    assert shown, "a red gate with four hundred lines of output rendered none of them"
    assert shown[-1] == printed[-1]
    assert printed[0] not in shown
    assert all(line in printed for line in shown), (
        "a row of the build log is not a line the build printed, so the slice that bounds the log "
        "cut a line in half and the half was rendered as a whole one"
    )

def test_two_frames_of_one_unchanged_conflict_are_equal() -> None:
    """What lets the terminal write this screen once and then leave a person alone to read it.

    Neither screen in this package has a `TextInput`, so neither leans on `maps`' exclusion from
    comparison - every component here compares by value outright, `Choice.value` included. A screen
    that rebuilt an unequal component each frame would be redrawn ten times a second underneath the
    person deciding, which is the case `ports/terminal.py` calls the one where rewriting costs the
    most.
    """
    gate = VerifierOutcome(passed=False, status=2, output="ERROR: could not import agl.workflows")

    assert views.conflict(COLLIDED, gate) == views.conflict(COLLIDED, gate)


# --- the run itself ----------------------------------------------------------------------------
#
# That half is `tests/workflows/test_split_runs.py`, and it is a second module rather than a
# section here: `split` driven end to end on an all-fakes bundle needs a scripted agent per
# arrangement, a merge gate to hold a landing open and a terminal to answer a conflict on, and none
# of that is anything the screens above need. The line is the one the file docstring draws - what a
# person would have been shown is the cheaper claim and is worth keeping cheap - and the two `show`
# calls are asserted over there, where they are arguments to calls rather than values, and nothing
# imports an argument.
