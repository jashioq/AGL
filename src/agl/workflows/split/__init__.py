"""The `split` workflow: N independent chunks, concurrent, each integrated into the run's base.

v1.1, and the second measurement R1 rests on. Where `fix` proves that two vendors fit in one run,
`split` proves that N agents fit in one run without stepping on each other - and Part 5's target is
that **`split` is ~30 lines** and adds "concurrency, child worktrees, and integration with no
framework change". The number is not about this file. Everything below that is not one of the four
things §3.3 says an author writes - params, roles, tools, and one async function - would be evidence
that the framework asked a workflow to do the framework's job, and a diff outside this package would
be evidence that an abstraction is missing from the SDK.

## What it does

A planner reads the repository and divides the job into chunks that will not collide. Every chunk
gets its own child worktree, cut from the same commit; every one of them runs at once; and each one
lands into the run's own branch as it finishes, behind a lease and a build gate. The run's branch,
`agl/<label>`, is the deliverable, and it grows a commit per chunk that landed.

## The three lines that are not the plan's snippet, and why

§3.3's and Part 4's own sketch writes the loop as `tg.create_task(do_chunk(run, c))`, with the child
taking its namespace inside the coroutine. This one takes every namespace **before** the
`TaskGroup` is entered, into a dict, and hands each child the `Run` it will use. That is three
separate arguments arriving at one line:

* **Ordering.** `worktree()` is synchronous and cheap - a dictionary lookup and an object - but the
  first `await` inside a child hands ordering to the event loop. Deliverable 11.4 measured the
  version of this that provisions inside the child and found the mutation went red at only three of
  four kill points until the worktrees were taken **before** the concurrency started. Nothing may
  await between taking a namespace and dispatching the work that uses it, and the way to guarantee
  that is to have taken them all already.
* **One base.** `run.worktree(name)` with no `base=` reads this Run's *logical head at the moment it
  is called* - the chain, not the branch tip. Called up front, every child is cut from the same
  commit, which is what "N independent chunks" means and what the planner's `files` boundaries were
  drawn against. Called inside a child, a chunk that starts late would be cut from whatever a
  sibling has already landed, and the plan would be about a tree that no longer exists.
* **Failing before anything runs.** A duplicate or malformed id is `ConflictError` or `InputError`
  out of `Namespace`, and taking the namespaces in the comprehension puts that refusal before the
  first agent is dispatched - `chunks.py` argues at length why that refusal should have happened
  earlier still, inside the planner's own conversation.

The dict is not scaffolding for those arguments; it is also what `views.board` is a view of, and
the reason that board is live rather than a table of empty cells. See below.

## Concurrency is the author's, and so is what happens when one chunk fails

`asyncio.TaskGroup` is plain structured-concurrency Python and the framework never spawns a task on
a workflow's behalf. What comes with it is `TaskGroup`'s own failure semantics, which are not the
framework's and are worth knowing before they surprise somebody: **the first chunk to raise cancels
its siblings**, and what leaves this function is a `BaseExceptionGroup` wrapping whatever was
raised. `agl.testing`'s harness splits that group already - it says so, naming this workflow - but
`cli/exit_codes.py` does not, and `exit_status` walks the MRO of a class with no `AglError` in it.
So an `UpstreamError` in one chunk exits 70 out of the CLI where the same failure in `fix` exits 6,
and a workflow `Stop` raised inside a chunk exits 70 rather than 7. That is reported as a finding
against the framework rather than worked around here: an `except*` in this function that unwrapped
the group and re-raised its first member would be a workflow doing the exit-code layer's job, which
is exactly the thing target #1 measures.

**There is no semaphore, and `--chunks` is why.** `tickets` owns a `concurrent` knob because it has
a ready-set loop and a backlog that outlives it; `split` opens every chunk at once, so the number of
agents running is the number of chunks the planner reported, and the ceiling on *that* is the flag.
One knob, applied at the moment the work is divided rather than at the moment it is dispatched.

## Landing: serialized per target, and what that costs this workflow

`integrate()` takes a lease on the target and then the target namespace's step lock, and holds both
until the outcome settles (§3.4). So N children landing into one parent land one at a time, each
building the combined tree before the next is admitted, which is the merge train and the only place
this framework runs a build. Two consequences this workflow lives with rather than works around:

* **A landing shuts the parent's own step walk.** A build holds that lock for minutes, so a parent's
  `run.step` queues behind every child's gate. `split` never pays it: every step this workflow takes
  on the root - there is one, `plan` - happens before the first worktree is opened, so no landing
  is ever in flight while the root wants to step. That is a property of this shape and not a rule,
  and a version of `split` that stepped after its children would meet the cost in full.
* **The gate has no baseline.** A red build means the *combined* tree is broken, not that this chunk
  broke it, and the landing is reverted either way. The implementer's prompt says so plainly,
  because it is the difference between "your work was wrong" and "your work was thrown away".

## The conflict path, which is the one place `split` asks a human anything

`while outcome.conflicted:` is §3.4's spelling and the `if` is a bug it names: a person who presses
retry without having fixed anything gets a conflicted outcome back, the branch falls through, and
the run holds the lease *and* the target's step lock until it exits - which stalls every other
chunk's landing behind a decision that was already made. So the loop is a loop, and the two verbs
that end it are the two that release the lease.

**The decision inside it is `views.conflict`**, shown at `priority=10` so that it preempts an agent
question: `integrate()` holds the target's lease and step lock until the outcome settles, so every
other chunk's landing is stopped behind this screen, and that is the whole justification §3.7 gives
for one level of preemption. A person who picks retry sends the landing round again from wherever
the target now stands and comes back here if it still will not go; a person who gives up releases
the hold and the lease, the next chunk lands, and the chunk that did not land keeps its branch
`agl/_work/<label>/<id>` and its worktree, both of which persist until `agl clear`. Nothing is
lost; a human merges it by hand or re-runs.

That second half is why giving up was an honest placeholder before 18.2 rather than a stub - it is
a real policy with real consequences, and it is still exactly what happens on the `abort` path
below.

Note that the loop cannot be written as `while outcome.conflicted: await outcome.abort()` - an
aborted outcome deliberately *keeps* its `Conflict`, "giving up on a landing does not make the
collision not have happened", so `conflicted` stays true after the verb settles it and the loop
would spin forever. §3.4's own snippet carries the `break` for that reason, and so does this one.

## What a person watching this run sees

Two `show` calls, and `views/` is where both screens live and are argued:

1. **The board**, on the line after `children` is built and before the `TaskGroup` is entered:
   `await run.terminal.show(views.board, chunks=plan.items, runs=children)`. Both arguments are
   already locals at that point, which is what the dict comprehension buys a second time over: the
   board reads `runs[id].activity` on every frame, so a table of N chunks is live with no component
   of its own and no second `show`. It is shown once - a second `show` would only ever mean putting
   a *different* view on screen (§3.7) - and it keeps updating in the slot behind every conflict
   screen the run puts up.
2. **The conflict screen**, inside the `while` in `_implement`, at `priority=10`.

`views/conflict.py` needs `Conflict` and `VerifierOutcome`, and until 19.2 neither was on the
SDK's front door, so it reached into `agl.ports` for them - `chunks.py`'s `Namespace` tripwire
firing a second time, reported rather than paid for because widening `sdk/__init__.py` is a diff
outside this package. 19.2 paid it. Both names come through `agl.sdk` now, and **no module in this
package imports from anywhere but `agl.sdk` and itself**.

## What a resume gets for free, and the one rule it places on this file

Every step is fingerprinted over its role - prompt text, model, restrictions, tool schemas - its
inputs, and the head its namespace started from, so killing this run and resuming it replays what
finished and re-runs only what did not. Concurrency changes nothing about that: each chunk is its
own namespace with its own ledger under `worktrees/<id>/`, and §3.9's flat trees root is why those
names are unique run-wide rather than merely among siblings.

The rule that buys it is §3.6's one rule for authors - **branch only on step results.** The only
thing this function branches on is `plan.items`, which came out of the ledger, and the only thing
`_implement` branches on is `outcome.conflicted`. Nothing here reads a clock, a random number or an
environment variable, and nothing may. An integration is *not* journalled, so a resumed run re-lands
what it already landed - which is why a landing that changes nothing is still a landing, and why
`integrate()` is safe to walk twice.

## Registration

One line in `pyproject.toml`:

    [project.entry-points."agl.workflows"]
    split = "agl.workflows.split:split"

That line and this package were the whole of what stage 18 added: no edit to `cli/`, to `api.py`,
to `sdk/` or to `config/`, which is target #1 and was the measurement stage 18 existed to take.
`sdk/__init__.py` was widened afterwards, at 19.2, to carry the three names this package had had to
import from `agl.ports` - a diff stage 18 deliberately reported instead of making, so that the
measurement said what it measured.
"""

from asyncio import TaskGroup
from dataclasses import dataclass

from agl.sdk import Run, arg, workflow
from agl.workflows.split import views
from agl.workflows.split.chunks import Chunk
from agl.workflows.split.roles import implementer, planner

__all__ = ["SplitParams", "split"]


@dataclass(frozen=True, slots=True)
class SplitParams:
    """What `agl run split` is invoked with. Two flags, because two flags are what it reads.

        agl run split -n auth -r "add oauth to the api" -c 4

    Frozen, following §3.3's own example. `arg()` turns each field into a named CLI flag; there are
    no positionals anywhere in a workflow's parameters, and `sdk/params.py` refuses a field declared
    without a flag. Both are persisted into `run.json` when the run starts, which is why `agl resume
    auth` takes no flags: a resumed run cannot quietly become a run of something else.
    """

    request: str = arg("-r", "--request", help="the job to divide up, in your own words")
    """The job, as the operator describes it. Required - `arg()` with no `default` is a required
    flag - because a `split` run with nothing to split has no honest default.

    It reaches the planner as a step input rather than by being interpolated into the prompt: the
    framework appends `**inputs` as canonical JSON under a fixed heading and templates nothing
    (§3.3). So it is a fingerprint term, and two runs asking for different things cannot replay each
    other's work."""

    chunks: int = arg("-c", "--chunks", default=3, help="the most chunks to divide it into")
    """A ceiling on how many pieces the planner may report - and therefore, since this workflow
    opens every chunk at once, **the only bound there is on how many agents run concurrently**.

    Three by default, following §3.3's own `concurrent: int = arg("-c", "--concurrent", default=3)`,
    and for the same reason: it is the number a person tunes to their machine and their patience,
    and the machine teaches them faster than a default can.

    **It is asked for and not enforced, which is a decision rather than an oversight.** The obvious
    enforcement - comparing `len(plan.items)` against this after the step returns - would refuse
    *after* the plan was journalled, and a resume replays that entry as a cache hit and refuses
    again, so the only way out of an over-eager planner would be `agl clear`. The refusals that can
    be enforced cheaply are the ones a payload type can make inside the tool call, where the model
    is told and corrects itself, and `chunks.py` carries all three of those; a per-run ceiling is
    not among them, because a `__post_init__` sees the payload and never the params. So the ceiling
    is stated in the tool's description and again in the prompt, and a planner that ignores it costs
    money rather than correctness."""


@workflow(version="1.1")
async def split(run: Run[SplitParams]) -> None:
    """Divide the request into chunks, then run and land every one of them at once.

    Part 4's target shape, with the two additions it does not show and the module docstring argues:
    `request=` and `chunks=`, which is how the operator's words reach the planner at all, and the
    `children` dict, which takes every namespace before any concurrency starts.

    **`plan` takes no `commit=`, so its worktree is restored on the way out**, and the `planner`
    role it is paired with declares `NO_VCS_WRITES` and `NO_FILE_WRITES` for that reason. Read the
    two together; `roles.py` makes the argument. The chunks are what that step produced, so every
    line after it branches on a step result and nothing else (§3.6).

    **The comprehension is the concurrency-critical line.** `run.worktree` is synchronous, so the
    whole dict is built without a suspension: every child has its namespace, cut from this Run's
    logical head as it stands right now, before the first task can run. The module docstring gives
    the three arguments for that - ordering, one shared base, and failing before anything is
    dispatched - and 11.4 is where the first was measured rather than assumed.

    **The board goes up between the two**, after the namespaces are taken and before the first task
    can run, which is the only place it can go: `plan.items` and `children` are both locals by then,
    and `show` registers this pair of arguments rather than the table they produce, so every row's
    activity cell is a fresh read of a live child `Run` on every frame. It is awaited like every
    `show` and returns immediately - a passive screen goes to the slot and the workflow carries on
    with it up - and it is shown once, because a second `show` would only ever mean putting a
    different view on screen. Nothing here awaits between the comprehension and the `TaskGroup` that
    could reorder the two: this `show` is the one suspension point in between, and it happens after
    every namespace has been taken, which is what the ordering argument above asks for.

    **There is no line here for the implementer, and that is UF1.4 undoing UF1.2.** The hoist put
    `agent = implementer()` between the board and the `TaskGroup` and threaded the value into
    `_implement` as a third parameter, to save N-1 reads of one prompt file. It bought those reads -
    microseconds each, against a step that runs an agent for minutes - with a bound name, an extra
    parameter and a `Role` import into this module, which is one ceremony traded for another and the
    swap this stage exists to catch. So the role is built at the step that uses it, the way
    `planner()` is on the first line above, and the ordering argument is untouched either way: every
    namespace is taken in the comprehension, and taking a synchronous call *out* of the window
    between that and the `TaskGroup` can only make it shorter.

    **Nothing is gathered.** `TaskGroup` is awaited by its own `async with`, so this function
    returns when the last chunk has landed or been given up on, and the first chunk to raise cancels
    the rest and leaves here as a `BaseExceptionGroup`. That is `TaskGroup`'s contract rather than
    AGL's, and the module docstring names what it costs at the CLI's exit code.
    """
    plan = await run.step(planner(), request=run.params.request, chunks=run.params.chunks)
    children = {chunk.id: run.worktree(chunk.id) for chunk in plan.items}
    await run.terminal.show(views.board, chunks=plan.items, runs=children)
    async with TaskGroup() as group:
        for chunk in plan.items:
            group.create_task(_implement(children[chunk.id], chunk))


async def _implement(w: Run[SplitParams], chunk: Chunk) -> None:
    """One chunk: implement it in its own worktree, then land it in the run's branch.

    Module-level and private, because it is one chunk's half of this workflow and not a second
    workflow - `@workflow` decorates one function, `run` reaches this one through the child `Run` it
    is handed, and there is nothing here a `Run` does not already carry. `w` is the child, spelled
    the way §3.3 and Part 4 both spell it, and the two parameters are the whole of what one chunk
    needs to be told: which namespace it runs in, and what it was assigned. The role is not among
    them - `implementer()` is called on the line that steps with it, so N chunks build N identical
    roles off one declaration and the caller has no third argument to thread down.

    **`commit=` is what makes this step's work exist.** The framework commits whatever the agent
    left dirty under `implement <id>` and records the resulting head; that head is what
    `integrate()` lands, so an agent that commits on its own account puts work outside the record
    the landing carries. `roles.py` argues the `NO_VCS_WRITES` that is the other half of it.

    **`chunk=` is the assignment.** The whole dataclass goes in as one input, so `_canonical` walks
    it, tags it with its qualified name and fingerprints it, and the same JSON is appended to the
    implementer's prompt under `## Inputs`. Passing the fields separately would fingerprint the same
    bytes and give the agent three loose values instead of the object its prompt describes.

    **The `while` is §3.4's, and the `break` is too.** An aborted outcome keeps its `Conflict`, so
    `conflicted` stays true after the verb that settled it: the loop ends by leaving, never by the
    condition going false.

    **And now that there is a screen inside it, the `while` is load-bearing rather than careful.**
    A person who presses retry without having fixed anything gets a conflicted outcome back, and
    `continue` puts the same screen in front of them again. The `if` spelling §3.4 names as a bug
    would instead fall out of the branch holding the lease *and* the target's step lock for the
    rest of the run - which stalls every other chunk's landing behind a decision that was already
    made. The two verbs that end this loop are the two that release the lease, and each appears
    once.
    """
    await w.step(implementer(), chunk=chunk, commit=f"implement {chunk.id}")
    outcome = await w.integrate()
    while outcome.conflicted:
        # `conflict` and `verdict` rather than `outcome`, because the view takes what it renders:
        # the port's `Conflict`, plus the verifier's output when a red gate is what went wrong.
        # Passing the outcome would annotate a workflow author's view with `sdk/_engine`'s own
        # private type and put both verbs in reach of a function that builds a value (§3.4).
        if await w.terminal.show(
            views.conflict, conflict=outcome.conflict, build=outcome.verdict, priority=10
        ):
            # `retry()` moves *this* outcome and returns nothing, so `continue` re-reads
            # `conflicted` off the object the verb just settled - §3.4's `outcome = await
            # outcome.retry()` predates that decision and there is nothing here to rebind.
            await outcome.retry()
            continue
        await outcome.abort()
        break
