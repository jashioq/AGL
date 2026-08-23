"""`Role` - instructions, model, restrictions, tools and required capabilities, as one value.

§1.2's charge against the previous implementation is that its roles were "five hand-written
near-duplicate functions differing only in prompt, model, tools, and denials", and its verdict is
this module's whole design: *that's data, written as code*. A `Role` is that data. No methods, no
base class and nothing to override - §3.3 lists it beside Params, Tools and Views as one of the four
things a workflow author writes, and everything done *to* one - building an `AgentTask` out of it,
fingerprinting it, routing it to a provider, checking it at preflight - is framework, and §3.3's
table is emphatic that it stays framework.

Frozen and slotted, for `ReportingTool`'s reason. A role is declared once and used many times:
§3.3's tickets example hands every child worktree the same `implementer` and gives its two reviewers
one declaration each for the whole run, so a role that could be edited by one step would be edited
for all of them. (A role carrying `on_question` is built where its `Run` is in scope rather than at
module level - §3.7's handler is a closure over that `Run` - which changes nothing here: the value
is still immutable and still holds nothing belonging to a single invocation of itself.)

## `instructions` is the prompt text, and not a path to it

§3.7's example writes `instructions="prompts/decompose.md"`. **This module reads that as shorthand
and takes the prompt itself, already resolved.** Three things say so, and the third is decisive:

* `ports/agent.py::AgentTask.instructions` is documented as "What to do, in full, as the workflow
  author wrote it. The prompt, already resolved." A role holding a filename would leave `Run.step`
  to do the resolving, which means the SDK reading a file through no port at all, against whatever
  directory the process happens to have started in.
* §3.6 puts `role.instructions` in the step's fingerprint, and says why: "halt, edit the implement
  prompt, resume - without this you replay results produced by the old prompt, which is exactly when
  you are iterating and least want stale output."
* So a role holding `"prompts/decompose.md"` fingerprints **the filename**. Editing the prompt moves
  nothing, the digest still matches, and the resume replays what the old wording produced - the
  exact failure the role term exists to prevent, arriving silently, as a cache hit rather than an
  error. Nothing about the string a Role carries is checked, so there is no version of this that
  fails loudly instead.

A `prompt_file("prompts/decompose.md")` helper that reads the file **at declaration time** and hands
back its text is additive, correct, and deliberately not built here: it fingerprints the text, so it
has none of the problem above, and it needs a decision about what the path is relative to - the
workflow package, presumably - which is a decision about packaging and not about roles.

## `on_question` implies `MID_RUN_QUESTIONS`, and the author does not restate it

§3.2's third preflight check and §3.7's "**This makes `MID_RUN_QUESTIONS` load-bearing**" are stated
as facts about the framework rather than as advice to an author, and they admit no exception: there
is no role that declares a handler and does not need a backend able to ask. A second declaration of
that therefore carries no information - it can only be forgotten. So declaring `on_question` folds
`Capability.MID_RUN_QUESTIONS` into `requires` here, at declaration time, and `role.requires` is the
whole of what a backend must offer.

**What forgetting it would cost, which is why this is not left to discipline.** Preflight passes,
the run starts, and the agent asks into an adapter that (per `AgentRunner.run`) must **not** block:
it tells the agent no answer is available and lets it carry on with its own judgement. The
workflow's approval gate is then simply absent, and §3.7's "propose, ask for approval, revise until
approved" becomes an agent approving itself. Nothing raises, nothing is logged as wrong, and the
step reports a result. A silently wrong answer is the one outcome this design keeps buying checks to
avoid.

**This is not `plan_only`'s case, though it looks like it.** `AgentTask.plan_only` refuses to be
derived from `restrictions` because deriving would mean "deciding which restrictions *mean*
planning, a policy this port has no standing to invent". Here there is no policy to invent: the plan
states one implication, in one direction, naming one member. And it costs nothing downstream -
`base_of` fingerprints instructions, model, restrictions and tools, and neither `requires` nor
`on_question` is a term, so a derived member cannot move a digest.

**The implication runs one way only.** `requires={MID_RUN_QUESTIONS}` with no handler is left
exactly as written: it says the prompt may invite the agent to ask and the author wants a backend
that can, which is over-declaring and is the author's business. Refusing it would be inventing the
policy the paragraph above declines to invent.

**What stage 16 is therefore written against.** One containment and no special case:
`role.requires <= await runner.capabilities(role.model)`, per role, over the providers the
workflow's roles name. One thing worth building into the message: when the missing member is
`MID_RUN_QUESTIONS` and the author never typed it, say that `on_question` put it there - otherwise
the reader goes looking for a line that is not in their file.

## `Role[P]`, and why the default is `None` rather than `object`

`P` is the payload type of this role's reporting tool, and it is what carries §3.3's typing promise
from `reporting_tool()` through to the workflow: 12.1's `Run.step` is
`async def step[P](self, name, role: Role[P], ...) -> P`, so `findings = await run.step("review",
reviewer)` followed by `findings.high()` is checked rather than hoped for.

`sdk/workflow.py` settled the same class of question for `Run[P]` and answered `object`, arguing
that a workflow's params are "genuinely **unknown** and not **unchecked**". Checked here, and
answered differently on purpose: an effect step's result is not unknown. §3.3 says it is `null`, so
`None` is the true statement and `object` would be a vaguer one. `None` also earns something
`object` would not - mypy's `func-returns-value` refuses to let a name be bound to it, so
`outcome = await run.step("implement", implementer)` on an effect role is an error at the line that
wrote it, which is the right answer to a step that has nothing to hand back. The *shape* is
`Run[P]`'s and `ports/terminal.py::Screen[T = None]`'s: `disallow_any_generics` is on under
`--strict`, so a bare `Role` in an annotation needs a type-parameter default to be legal at all.

**Inference, measured under `mypy --strict` rather than assumed.** These infer:

    Role(instructions=..., model=..., tools=[report_findings])      -> Role[Findings]
    Role(instructions=..., model=...)                               -> Role[None]
    Role(instructions=..., model=..., tools=[])                     -> Role[None]
    Role(instructions=..., model=..., tools=[read_spec])            -> Role[None]
    Role(instructions=..., model=..., tools=(read_spec, report_findings)) -> Role[Findings]

and one shape does not: a **list** display mixing a plain `Tool` with a `ReportingTool`. mypy has to
choose one item type for a list before it can solve `P`, and the join of two unrelated classes is
`object`, so no constraint reaches `P`, the default stands, and the item is then refused against
`Tool | ReportingTool[None]`. It fails at the declaration and it fails loudly; it is never silently
`Role[None]`. Two spellings fix it, and `tests/sdk/test_roles.py` pins both:

    tools=(read_spec, report_findings)                              # a tuple, not a list
    Role[Findings](instructions=..., model=..., tools=[read_spec, report_findings])

The explicit spelling is checked and not merely tolerated: `Role[Tickets](tools=[report_findings])`
where the declaration is a `ReportingTool[Findings]` is an error, so naming the wrong parameter is
caught rather than believed.

## What this module refuses, and what it leaves to be refused downstream

`InputError`, throughout, and at declaration time - `sdk/params.py`'s stance and its reason, that a
package which cannot be invoked correctly should fail when it is imported. Everything here was typed
by a workflow author, and exit 70 would send them hunting for a bug in the framework.

Two of the three refusals below are `AgentTask.__post_init__`'s own, made one layer earlier and in
its words, exactly as `ReportingTool.__post_init__` re-makes `Tool`'s two checks. The duplication is
deliberate and it is not free-floating: `AgentTask` is constructed inside `Run.step`, after the
journal missed, after the worktree was reset, and after earlier steps in the run have already paid
for agents. Refused here, the reader is looking at the line they wrote.

Not refused here, and deliberately: **that a step taking no `commit=` uses a role declaring
`Restriction.NO_VCS_WRITES`**. §3.3 calls that pairing "the author's job, by convention and not
enforcement", and the two halves are not in the same place anyway - the restriction is on the role
and the `commit=` is on the call, so a role cannot see how it is being used. Nothing here reaches a
port either: no provider is asked what it can do, no capability is compared against anything, and no
prompt file is read. Preflight is stage 16, and it needs a runner.

## `RoleIncompleteError` has no caller here, and that is deliberate

It is raised by 12.1's `Run.step` when a reporting step's agent finishes without ever firing its
tool, which is a thing this module cannot observe and does not try to. It is named here because the
name says Role and because 12.1 should import it rather than invent it - the one member in this
module whose caller arrives in the next deliverable. Its argument is on the class.
"""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from agl.ports.agent import Capability, ModelId, QuestionHandler, Restriction, Tool
from agl.ports.errors import InputError, UpstreamUnexpected
from agl.sdk.tools import ReportingTool

__all__ = ["Role", "RoleIncompleteError"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Role[P = None]:
    """One agent, as the workflow author declares it. §3.3's "instructions + model + restrictions +
    tools + required capabilities", and nothing besides.

    Keyword-only, following `@workflow` and for its reason. Six fields of which four have defaults,
    and two of those - `restrictions` and `requires` - are both sets of `StrEnum` members, so a
    positional call is a thing to transpose once and be wrong about for the life of a run's records.
    §3.7's own example writes every argument by name.

        reviewer = Role(
            instructions=REVIEW_PROMPT,
            model=OpenAI.SOL,
            restrictions={Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES},
            tools=[report_findings],
            requires={Capability.SHELL},
        )

    `P` is the payload type of the reporting tool in `tools`, defaulting to `None` for an effect
    role - see the module docstring for what infers and what has to be spelled out.
    """

    instructions: str
    """The prompt, in full, as the author wrote it - the text and never a path to it.

    Fingerprinted verbatim by §3.6, which is the whole argument for it being text; the module
    docstring makes it. Interpolating a step's `**inputs` into it is `Run.step`'s business (§3.3),
    so what is stored here is what the author typed and nothing derived from a call."""

    model: ModelId
    """Which model runs this role, named beside the prompt because the reason is semantic (§3.2):
    this role touches sensitive code, that one needs deep judgement, this one is cheap.

    `Claude.OPUS` and `OpenAI.SOL` in one workflow is correct and expected. There is no
    config-level override - ARCHITECTURE.md §6 and §3.2 both say so, and the argument is that an
    override costs a schema, resolution and validation to buy *why is my Opus role running GPT-5?*
    Which adapter serves it is `task.model.provider`'s business and nothing here needs to know."""

    restrictions: AbstractSet[Restriction] = frozenset()
    """What this role may not do, stated as AGL's intent and never as a vendor's syntax.

    A set and not a level: any combination, no ordering, nothing implying anything else. Each
    adapter renders it in whatever its own backend offers - deny patterns, a sandbox policy, or, on
    a backend with no mechanism, an instruction in the prompt or a refusal of the task.

    Declared as an `AbstractSet` so that `restrictions={Restriction.NO_SHELL}` is the spelling, and
    normalised to a `frozenset` on the way in, which is what `AgentTask.restrictions` takes and what
    `base_of` sorts before hashing."""

    tools: Sequence[Tool | ReportingTool[P]] = ()
    """The plain `Tool`s this role offers, and at most one `ReportingTool`.

    Empty is ordinary: an effect step may need none, and its result is `null` either way. At most
    one reporting tool, refused below - two would make "the step's result" ambiguous where §3.3
    defines it as *that tool's payload*, singular.

    Declaration order is kept, and normalised to a tuple to match `AgentTask.tools`. The order is a
    fingerprint term - `base_of` reads the sequence as given and does not sort it, unlike a payload
    schema's `required` - so moving a tool up a line re-runs the step. That is §3.6 rule 4 as
    written, noted here because it is the one place in this declaration where a cosmetic edit
    costs an agent run."""

    requires: AbstractSet[Capability] = frozenset()
    """What a backend must be able to do at all for this role to run on it.

    The counterpart to `restrictions`: that is what the workflow forbids, this is what the backend
    must offer. Compared against `runner.capabilities(model)` at preflight (stage 16), so a run that
    cannot work dies at second zero rather than forty minutes in at the review step. Nothing here
    checks it - this module reaches no port and asks no provider anything.

    Declaring `on_question` adds `MID_RUN_QUESTIONS` to it; the module docstring argues that at
    length. An `AbstractSet` for `restrictions`' reason, normalised to a `frozenset`."""

    on_question: QuestionHandler | None = None
    """What answers the agent when it stops mid-run to ask something. `None` when it never asks.

    §3.7: the framework supplies the asking tool, the adapter maps whatever payload its backend
    produced into a `Question`, awaits this, and serialises the `Answer` back into the same live
    session - so a negotiation is N rounds inside one step and one session, not N steps. One
    parameter, because the handler is a closure over the workflow's own `Run` and needs nothing else
    from the framework.

    Spelled as `ports.agent.QuestionHandler` rather than respelled as a `Callable`, so that the
    shape a role declares and the shape `AgentRunner.run` accepts are one type and cannot drift.

    A callable is safe here where `AgentTask` refuses one: a task sits beside a fingerprint and has
    to stay loggable and comparable, while a role is fingerprinted through four of its fields and
    this is not one of them."""

    def __post_init__(self) -> None:
        if not self.instructions.strip():
            raise InputError(
                f"a role's instructions are the whole of what its agent is asked to do, and this "
                f"one was declared with {self.instructions!r}. `AgentTask` refuses an empty prompt "
                f"too, at the dispatch - refused here, the line that needs fixing is on screen"
            )
        tools = tuple(self.tools)
        reporting = [declared.name for declared in tools if isinstance(declared, ReportingTool)]
        if len(reporting) > 1:
            raise InputError(
                f"this role declares more than one reporting tool: {reporting}. A reporting step's "
                f"result is that tool's payload (§3.3), singular - with two, `run.step` would have "
                f"to pick one, and whichever it picked would be a rule living in the framework "
                f"about a decision the workflow made. A role reports through one tool or none"
            )
        names = [declared.name for declared in tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise InputError(
                f"this role declares these tools more than once: {duplicates}. A model names the "
                f"tool it is calling, so a duplicate is a call no backend can resolve to one "
                f"handler - `AgentTask` refuses it too, one layer down and one run later"
            )
        requires = frozenset(self.requires)
        if self.on_question is not None:
            requires |= {Capability.MID_RUN_QUESTIONS}
        object.__setattr__(self, "restrictions", frozenset(self.restrictions))
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "requires", requires)


class RoleIncompleteError(UpstreamUnexpected):
    """A reporting step's agent finished without ever calling its reporting tool.

    The step declared a tool, the prompt asked the agent to report through it, and the agent ended
    its turn instead. There is no payload, so there is no result, so nothing is written down and the
    step re-runs on the next attempt (§3.3). The run ends at exit 6.

    **`UpstreamUnexpected`, whose own docstring names this exact case** - "an agent finished with no
    reporting-tool payload". The far side worked; what failed is our expectation of what it would
    do, so retrying the same call unchanged tends to produce the same answer, which is what sends
    the reader to the prompt rather than to a retry.

    **Defined here rather than in `ports/errors.py`, and that is the interesting half.**
    `exit_code_for` walks the MRO, so this resolves to `UpstreamError`'s 6 while appearing in no
    table and while nothing in `ports/` learns the word Role - the same mechanism a workflow's own
    `Stop` subclass uses to exit 7 without being listed. `ports/` has no vocabulary for a Role and
    should not acquire one to hold an error name; a hierarchy designed to be extended by name from
    outside is exactly what that walk buys, and this is the framework's own use of it.

    **What its message has to distinguish**, built by 12.1, which is where the outcome is:
    `AgentOutcome.stop_reason` says whether the backend stopped the agent against its will
    (`LIMIT` - raise the limit) or the agent decided it was finished (`COMPLETED` - fix the prompt),
    and `None` means the backend did not say and the message can offer neither. `AgentOutcome.text`
    is what the agent said instead of reporting, and quoting it is what makes the failure legible.
    """
