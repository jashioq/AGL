"""What a plan divides the job into, and the tool the planner reports it through.

`split`'s own vocabulary. The framework stores a reporting tool's payload as JSON and reads it
back as this class, never learning what a chunk is, so `Chunk`, `Chunks` and every rule below
belong here beside the prompt that asks for them - exactly as `fix/findings.py` holds `Finding`.

## The one thing that makes this module unlike `fix`'s: `id` is agent output that becomes a path

`split`'s workflow function passes `chunk.id` to `run.worktree()`, which is `Namespace(name)`,
which is §3.3's allowlist: `[A-Za-z0-9._-]`, non-empty, no leading or trailing `.` or `-`, `_base`
reserved, and unique run-wide by `collision_key` because the trees root is flat (§3.9). A planner
that invents `chunk 1`, `T/01` or two ids differing only in case is a planner whose output the
framework refuses - loudly, correctly, and **after the plan step has been journalled**.

That last clause is the whole argument for the checks below. A refusal at `worktree()` is not a
failure the run recovers from: the entry for `plan` is already written, so `agl resume` replays the
same bad plan out of the ledger as a cache hit and dies at the same line, every time, until
somebody runs `agl clear` and pays for the planner again. Whereas a refusal *here* is a refusal
inside the tool call: `sdk/tools.py::_instance` builds the payload in a `try` and turns whatever it
raises into a rejection carried back into the same conversation, so the planner is told what it did
and sends another call. Same rule, same run, one round trip instead of a dead run.

So the test each check below had to pass is: **would the run otherwise reach a state only `agl
clear` gets it out of?** Three do.

* **An id that is not a legal namespace** - `InputError` at `worktree()`, per above. Checked on
  `Chunk`, because it is a fact about one chunk and `Namespace`'s own message names the character
  and the position.
* **Two ids that collide** - `ConflictError` at the second `worktree()`, per §3.9's run-wide,
  casefolded uniqueness. Checked on `Chunks`, because it is the only place the whole set is
  visible.
* **An empty plan** - no refusal at all, which is worse: the `TaskGroup` below has nothing to
  create, the run ends green, and AGL reports success over a job nobody did. There is always at
  least one chunk; a job too small to divide is a plan with one chunk in it, and `split` runs that
  in one worktree.

And the checks that are deliberately absent are the mirror of that test. `work` and `files` are
unchecked prose: a vague `work` is a worse plan and a wrong `files` is a boundary the implementer
crosses, and neither stops the run or corrupts anything. An empty `files` is the interesting one -
it is admitted, because a planner that could not predict which paths a chunk touches has produced a
worse plan and not an unrunnable one. **Refuse what makes a run unrunnable or a no-op; do not
refuse what only makes a report worse.** That is the same line `fix/findings.py` drew when it
checked `severity` and left `file` and `summary` alone.

## Why the rule is imported rather than restated, and what that import costs

`Chunk.__post_init__` constructs a `Namespace` and throws it away. The alternative was a regex here
spelling `[A-Za-z0-9._-]` a second time, and that is a copy of a rule this workflow does not own:
`ports/ids.py` says in as many words that four types share one validator "for the same reason a
second rule set would be a second thing to get wrong", and a fifth copy living in a workflow could
drift from the framework that is actually going to refuse the name.

The cost is that this is **the first module under `agl/workflows/` to import from `agl.ports`**.
Contract 6 permits it - it forbids `agl.adapters` and `agl.config`, and contract 1 puts `ports`
below `workflows` - but `ARCHITECTURE.md` §5 sets a stronger convention than the contract does: a
workflow author writes `from agl.sdk import ...` and never reaches into `ports`. That convention is
why `sdk/errors.py` exists at all; deliverable 18.0 added it the moment a workflow's own test file
had to reach for `agl.ports.errors`. **`Namespace` is the same tripwire firing a second time**, and
it is reported as a missing re-export on the SDK's front door rather than paid for with a copy of
the allowlist here. Widening `sdk/__init__.py` is a diff outside `workflows/split/`, which is
precisely the measurement stage 18 exists to take, so this module does not make one.

## What §3.6 rule 6 charges for a `__post_init__`, and why it is cheaper here than in `fix`

Rule 6: a `__post_init__` is invisible to the derived schema, so tightening or loosening it changes
what converts while moving no digest, and an entry recorded under the old rules can stop converting
with its fingerprint still matching - `InternalError` out of `ReportingTool.read`, on a resume.
`fix/findings.py` pays that in full, because `SEVERITIES` is a tuple in that module that an author
may edit under a live run.

Two of the three rules here are not this module's to edit: they are `ports/ids.py`'s, and the
framework applies the *identical* rule downstream on every walk, replay included -
`Worktrees.open` constructs `Namespace(name)` each time it is called, not only the first. So a
narrowed allowlist would refuse a resumed run at `worktree()` whether or not this check existed;
what the check changes is which line reports it, not whether the run survives. The third rule -
that a plan is non-empty - is this module's own and is the one that carries the ordinary cost of
the rule, which is small: it can only ever be loosened, and loosening it makes more payloads
convert rather than fewer.

## Tuples, not lists

`Chunks.items` and `Chunk.files` are tuples for `fix/findings.py`'s three reasons, unchanged and
not restated here: a payload is a frozen value that a later step and a replay both read again, a
`list` field on a frozen dataclass is a mutable interior behind an immutable wrapper, and
`sdk/tools.py` builds each field at the type it was declared so the JSON array survives the round
trip as a tuple. `chunk` is passed to `run.step("implement", ...)` as an input, so `_canonical`
walks this whole value and tags each dataclass with its qualified name.
"""

from dataclasses import dataclass
from typing import Final

from agl.ports.ids import Namespace
from agl.sdk import reporting_tool

__all__ = ["Chunk", "Chunks", "report_chunks"]


@dataclass(frozen=True, slots=True)
class Chunk:
    """One independently implementable piece of the job, as the planner divides it.

    Frozen and slotted, following every payload in AGL: this value is handed to a child `Run`'s
    step as an input, fingerprinted, appended to a prompt as canonical JSON and read again on
    replay, and the one thing it must not be is editable by whoever is holding it.
    """

    id: str
    """This chunk's name, and **the namespace its worktree, its branch and its ledger are filed
    under**. `run.worktree(chunk.id)` is where it lands, so it is `[A-Za-z0-9._-]`, non-empty,
    without a leading or trailing `.` or `-`, and not `_base` - §3.3's allowlist, refused below by
    the framework's own `Namespace` rather than by a copy of the rule.

    Opaque to everything above this package: rename `T-01` to `banana` and AGL behaves identically.
    What it buys a person is that `agl/_work/<label>/<id>` and `.trees/<label>/<id>/` are readable
    afterwards, which is why the prompt asks for a short slug of the work rather than a number."""

    work: str
    """What to do, in enough detail that an agent which has never seen the rest of the plan can do
    it. This is the whole of the assignment: each chunk runs in its own session, in its own
    checkout, with no view of its siblings and no memory of the planner's reasoning, so anything
    the planner knew and did not write here is knowledge the implementer does not have.

    Unchecked prose. A vague one is a worse plan and not a broken run - the module docstring draws
    that line and says where it comes from."""

    files: tuple[str, ...]
    """The paths this chunk is expected to touch, relative to the root of the repository, including
    ones it will create.

    **This is what makes the chunks independent, and independence is the whole premise of the
    workflow.** Every chunk is cut from the same commit and merged back into the same target one at
    a time (§3.4), so two chunks editing one file is a textual conflict that stops a landing and
    puts a screen in front of a human. The planner draws the boundaries here; the implementer's
    prompt asks it to stay inside them.

    A boundary rather than a contract: nothing enforces it, the implementer is told to say so when
    it has to cross one, and an empty tuple is admitted as a planner that could not predict the
    paths. Refusing it would be this type having opinions about the quality of a plan."""

    def __post_init__(self) -> None:
        # Constructed for its refusal and discarded: `Namespace` *is* the rule `run.worktree(id)`
        # will apply, so asking it here is the only way to check the id without writing a second
        # copy of §3.3's allowlist inside a workflow. The `InputError` it raises names the
        # character and the position, and `sdk/tools.py` carries that sentence back to the planner
        # inside the same conversation. The module docstring argues both halves at length.
        Namespace(self.id)


@dataclass(frozen=True, slots=True)
class Chunks:
    """A whole plan: the payload of `report_chunks`, and what `run.step("plan", planner)` hands
    back.

    A wrapper around one sequence rather than the sequence itself, because a reporting tool's
    payload is a dataclass (`sdk/tools.py` refuses anything else) and because the two rules that
    need to see every chunk at once need somewhere to live. It is also what lets a later version of
    this workflow grow a second field - a rationale, an ordering - without changing what the step
    returns.
    """

    items: tuple[Chunk, ...]
    """Every chunk, in the order the planner reported them.

    The order is kept and means nothing: `split` opens every worktree from the same base and runs
    them all at once, so nothing here is first. A workflow whose chunks depend on each other passes
    `base=` to `worktree()` and resolves its own graph (§3.3) - that is `tickets`, and it is not
    this workflow."""

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError(
                "a plan with no chunks in it is not a plan: every chunk is a worktree, so this "
                "would be a run that opened nothing, ran nothing and reported success over a job "
                "nobody did. There is always at least one chunk - a job too small to divide is a "
                "plan with one chunk in it, and it runs in one worktree"
            )
        taken: dict[str, str] = {}
        for chunk in self.items:
            # `collision_key` is casefold-then-NFC, and it is the framework's own comparison rather
            # than a lowercasing here: §3.9 checks namespaces run-wide with exactly this, because
            # `parser` and `Parser` are two branches to git and one directory on macOS.
            key = Namespace(chunk.id).collision_key
            first = taken.get(key)
            if first is not None:
                raise ValueError(
                    f"two chunks are named {first!r} and {chunk.id!r}, which are two names to git "
                    f"and one directory on a case-insensitive filesystem, so the second worktree "
                    f"would be the first one's checkout. Every chunk needs a name no other chunk "
                    f"shares, compared without regard to case"
                )
            taken[key] = chunk.id


report_chunks: Final = reporting_tool(
    "report_chunks",
    # The description is the only place the derived schema can carry a rule: `_schema_for` renders
    # a `str` field as `{"type": "string"}` and nothing else, with no per-field `description`
    # anywhere. `prompts/plan.md` says all of this a second time on purpose - the prompt and the
    # tool are read at different moments, and a model that skims one should still meet the rules.
    "Report the chunks this job divides into, and end the planning step. Call this exactly once, "
    "when the plan is complete: it is the only way to record a result, and a planning step that "
    "ends without calling it has produced nothing and will be run again. Each chunk's `id` names "
    "a git branch and a directory, so it may hold only letters A-Z a-z, digits, '.', '_' and '-' "
    "- no spaces, no slashes, no leading or trailing '.' or '-' - it may not be '_base', and no "
    "two chunks may share one, compared without regard to case. Keep ids short and descriptive: a "
    "person reads them as branch names afterwards. `work` is the whole assignment for that chunk, "
    "written for an agent that will never see the rest of this plan. `files` are the paths that "
    "chunk should touch, relative to the repository root, including ones it will create - two "
    "chunks naming one file will collide when their work is merged back. Report at least one "
    "chunk: a job too small to divide is a plan with one chunk in it.",
    Chunks,
)
"""The planner's one tool, and what makes `plan` a reporting step.

Declared here rather than in `roles.py` because §3.3 lists tools and their payload schemas as one
of the four things an author writes, and the payload is above: a description that enumerates the
id rules and a type that enforces them should be able to disagree only by being edited on one
screen."""
