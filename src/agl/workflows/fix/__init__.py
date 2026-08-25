"""The `fix` workflow: one worktree, sequential steps - Claude implements, OpenAI reviews.

v1.1, and the measurement R1 rests on. §3.3 calls this shape "single-worktree workflow - a
first-class shape" and writes the function out in full; Part 5's second measurable target is that
**`fix` is ~8 lines** and gets fingerprinted replay, a worktree, preflight and exit codes free. The
number is not about this file. It measures the SDK: everything below that is not the four things
§3.3 says an author writes - params, roles, tools, and one async function - would be evidence that
the framework asked a workflow to do the framework's job.

## What it does

One run, one worktree, three sequential steps. Claude implements the change the operator asked for,
OpenAI reviews what Claude wrote, and if the review comes back with high-severity findings Claude
repairs them. **Two providers inside a single run is the entire point of the workflow** (target #4),
and neither this module nor any other in this package names a harness, an SDK or a binary to get
them: `model=Claude.OPUS` and `model=OpenAI.SOL` sit in `roles.py` beside their prompts, and
`task.model.provider` is what routes each to an adapter neither role can see.

There is no `worktree()` here and no `integrate()`. Several agents working in one worktree is just
several steps on the same `Run`; the `await`s are the sequencing, and the second step sees what the
first one left behind. Commits land on `agl/<label>` directly and that branch is the deliverable -
nothing is merged into anything.

## The three steps, and what each one's `commit=` decides

`commit=` is the only difference between the three calls below, and it is not a detail:

| step | `commit=` | what the framework does when it ends |
|---|---|---|
| `implement` | `"implement fix"` | commits everything dirty under that message, records the head |
| `review` | omitted | restores the checkout to that head and deletes everything else |
| `repair` | `"address review findings"` | commits again, on top |

The omission on `review` is the guarantee, not an oversight: a reviewer cannot leave a scratch file,
a cache directory or a half-made edit behind, because the wipe runs whether the step returned or
raised. It is also §3.3's place where "a mistake destroys work rather than merely costing a
re-run" - one of three, the other two being §3.6's unrecorded landing and §3.4's red gate, and the
only one `fix` can reach - and the framework checks nothing about it. `roles.py`'s `reviewer`
docstring is where that argument lives, next to the `Restriction.NO_VCS_WRITES` that is its other
half.

**One coupling worth knowing about, because nothing enforces it.** `prompts/review.md` names the
string `implement fix` - it tells the reviewer which commit is the change under review. A commit
message is deliberately *outside* the fingerprint (§3.6: it is cosmetic, so rewording it must not
re-run an agent), so editing the message on the `implement` call below moves no digest and does not
re-run the review; it just quietly stops agreeing with the prompt. The two are to be edited
together, and the prompt tells the reviewer what to do when it finds no such commit anyway.

## What a resume gets for free, and the one rule it places on this file

Every step is fingerprinted over its role - prompt text, model, restrictions, tool schemas - its
inputs, and the worktree head it started from, so killing this run and resuming it re-runs the step
it died in and replays the ones before it without paying for an agent. Editing
`prompts/implement.md` moves the implement fingerprint, which re-runs it, which changes the head the
review starts from, which re-runs the review: the cascade is what makes iterating on a prompt work
like a build.

The rule that buys it is §3.6's one rule for authors - **branch only on step results.** The single
branch below is `if findings.high():`, over a value that came out of the ledger. Nothing here reads
a clock, a random number or an environment variable, and nothing may.

## Registration

One line in `pyproject.toml`:

    [project.entry-points."agl.workflows"]
    fix = "agl.workflows.fix:fix"

That line and this package are the whole of what stage 17 added. No edit to `cli/`, to `api.py`, to
`sdk/` or to `config/` - which is target #1, and the reason `@workflow` returns the `Workflow`
rather than the function: the decorated name *is* what the entry point resolves to.

## What a person watching this run sees, and what answers the agent

Two screens, both in `views/`, both pure functions re-invoked by the redraw loop ten times a second.
`views.board` is shown once before the first step and stays up for the whole run - the request, and
the live activity line - and `views.agent_question` is what the implementer's mid-run questions are
put on. §3.7: **agent questions are a callback on the Role**, so the mechanism is an `async def`
below, closed over this `Run`, and `replace(implementer, on_question=...)` at the line the role is
used. The handler is written inside the workflow function for the same reason the plan writes it
there: it needs `run.terminal`, and a role built at module level cannot see one.

**The handler is bound to the implementer and never to the reviewer.** The implementer is the agent
that has something to negotiate about - it is writing the change, and §3.7's whole negotiation shape
is propose, ask, revise, inside one step and one session. The reviewer reads a diff it was handed
under `NO_FILE_WRITES` and reports through a tool; there is nothing for a person to decide in the
middle of that. It is also the provider §3.7 names as the one with no second asking mechanism, where
a harness-imposed tool timeout can end a question with nothing to fall back to - "preflight is where
this would be caught if it can be caught at all", and giving that role a handler is precisely the
case preflight exists to refuse. So it does not have one.

## Where the decisions below are tested, and why none of them could be tested by importing this

Every argument in the function body is a decision, and an argument is exactly what importing a
module cannot see: the three `commit=` values, the `request=` input, the branch on
`findings.high()`, the two `show` calls and the `replace` that gives the implementer a handler are
all reachable only by driving a run. `tests/workflows/test_fix.py` drives one - on
`agl.testing`'s all-fakes harness, the way an author outside this repository would - and its second
half is deliverable 17.3: a complete run of each branch, the two commits read back off the fake
repository as a chain of trees and messages, the reviewer's scratch file gone from a checkout the
`review` step wiped, and the whole run interrupted at every step boundary and every *combination* of
boundaries, resumed, and compared against a run that was never interrupted.

One thing that test cannot do, stated there rather than papered over: it **interrupts and does not
kill** - `tests/sdk/test_kill_and_resume.py` is the version that ends a real process. The question
path used to be a second one, drivable only as far as the refusal a headless terminal makes,
because AGL shipped no input-capable `Terminal` an external author could drive; that was stage 16's
finding and 18.0 repaired it with `agl.testing.answering([...])`. So both endings of `answer` below
are asserted now - the refusal an unattended run gets, and a person picking something and the
`Answer` going back into the same live session.
"""

from dataclasses import dataclass, replace

from agl.sdk import Answer, Question, Run, arg, workflow
from agl.workflows.fix import views
from agl.workflows.fix.roles import implementer, reviewer

__all__ = ["FixParams", "fix"]


@dataclass(frozen=True)
class FixParams:
    """What `agl run fix` is invoked with. One flag, because one flag is what the workflow reads.

        agl run fix -n hotfix -r "the retry loop drops the last error"

    Frozen, following §3.3's own example. `arg()` turns the field into a named CLI flag and there
    are no positionals anywhere in a workflow's parameters - `sdk/params.py` refuses a field
    declared without one.

    **Kept to what the workflow actually reads.** A `--reviewer-model`, a `--max-repairs` or a
    `--skip-review` would each be a knob this function would have to branch on, and every branch not
    taken over a step result is a branch replay cannot reproduce. The three steps below are
    unconditional except for the one branch over `findings.high()`, and that is deliberate.

    Persisted into `run.json` under `params` when the run starts, which is why `agl resume hotfix`
    takes no flags: the request the run was started with is read back out of the record rather than
    retyped, so a resumed run cannot quietly become a run of something else.
    """

    request: str = arg("-r", "--request", help="what to fix, in your own words")
    """The change to make, as the operator describes it. Required - `arg()` with no `default` is a
    required flag, the same way `dataclasses.field` without one is a required field - because a
    `fix` run with nothing to fix has no honest default to fall back on.

    Free text, and it reaches the implementer as a step input rather than by being interpolated into
    the prompt: the framework appends `**inputs` as canonical JSON under a fixed heading and
    templates nothing (§3.3). It is therefore also a fingerprint term, so two runs asking for
    different things cannot replay each other's work."""


@workflow(name="fix", version="1.1", params=FixParams, roles=[implementer, reviewer])
async def fix(run: Run[FixParams]) -> None:
    """Implement the requested change, review it, and repair what the review found.

    §3.3's example, with one addition it does not show: `request=run.params.request`, which is how
    the operator's own words reach the agent. The framework appends step inputs to the role's
    prompt and interpolates nothing, so a params field that is never passed to a step is a field
    persisted into `run.json` that no agent ever sees.

    **`review` takes no `commit=`, so its worktree is restored on the way out** - and the `reviewer`
    role it is paired with declares `Restriction.NO_VCS_WRITES` for that reason. Read the two
    together; `roles.py` makes the argument.

    **`repair` runs only when the review found something that must not ship.** `findings.high()` is
    this workflow's own method on its own payload type, `high` is the one severity with a mechanical
    consequence, and the result is passed straight back in as an input - fingerprinted, and appended
    to the implementer's prompt as JSON. It is called twice rather than bound to a name because
    §3.3 writes it that way and because it is a filter over a frozen value: the two calls cannot
    disagree.

    There is no loop around the review. A second review of the repair would be a second `review`
    step with a different name, and a loop would need a bound and a halt policy - which is `split`'s
    business and `tickets`', not one worktree's. If the repair introduces something new, the run
    ends with it in the branch and a human reads the branch.

    **`answer` is the whole of §3.7's "agent questions are a callback on the Role".** It is declared
    here rather than in `roles.py` because it closes over `run` - that is what keeps its signature
    to the one parameter `QuestionHandler` has - and `dataclasses.replace` is what puts it on a role
    without a second copy of the declaration to keep in step. `asking` and `implementer` are the
    same agent, the same prompt, the same model and the same restrictions; the only difference is
    that one of them can be answered. `sdk/roles.py` folds `MID_RUN_QUESTIONS` into `requires` as
    the `replace` happens, so the role that reaches `run.step` requires it whether or not `roles.py`
    said so - and `roles.py` says so anyway, which is what makes preflight's cheap half able to see
    it. The argument for that is on the `implementer` declaration.

    **The board is shown once, and once is enough.** `show` registers this function's arguments, not
    a `Screen`, so the board re-reads `run.activity` every frame for as long as the run lasts, and a
    second `show` would only ever mean putting a *different* view on screen (§3.7). It is awaited
    like every `show` and returns immediately: a passive screen goes to the slot and the workflow
    carries on with it still up, including while a question is preempting it.

    The `request` is passed to the board as a value and to the `implement` step as an input, and
    those are two different things happening to one string: the step's copy is fingerprinted and
    appended to the prompt as canonical JSON, the board's is read by a person.
    """

    async def answer(question: Question) -> Answer:
        """Put the agent's question in front of whoever is watching, and hand back what they said.

        One parameter, because §3.7's handler is a closure over the `Run` and needs nothing else.
        No priority argument: `fix` has one kind of interactive screen, one agent at a time and no
        `integrate()` to preempt anything, so every question this run asks belongs at the default
        level - and a number copied from a workflow with two kinds of question would encode a
        hierarchy this one does not have.

        On a terminal that cannot take input this raises `UpstreamUnavailable` at the first
        question, which is the port's contract and the right outcome: a run whose agent needs a
        person cannot be finished by nobody, and there are no timeouts anywhere to end the wait.
        Nothing here catches it - the run ends at exit 6 and the operator re-runs it attended.
        """
        return await run.terminal.show(views.agent_question, question=question)

    asking = replace(implementer, on_question=answer)
    await run.terminal.show(views.board, run=run, request=run.params.request)
    await run.step("implement", asking, request=run.params.request, commit="implement fix")
    findings = await run.step("review", reviewer)
    if findings.high():
        await run.step(
            "repair", asking, findings=findings.high(), commit="address review findings"
        )
