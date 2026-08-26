"""`Role` - a name, instructions, restrictions, tools and required capabilities, as one value - and
`@role(model=…)`, the factory decorator that is how one is declared.

§1.2's charge against the previous implementation is that its roles were "five hand-written
near-duplicate functions differing only in prompt, model, tools, and denials", and its verdict is
this module's whole design: *that's data, written as code*. A `Role` is that data. No methods, no
base class and nothing to override - §3.3 lists it beside Params, Tools and Views as one of the four
things a workflow author writes, and everything done *to* one - building an `AgentTask` out of it,
fingerprinting it, routing it to a provider, checking it at preflight - is framework, and §3.3's
table is emphatic that it stays framework.

Frozen and slotted, for `ReportingTool`'s reason. One `Role` value is used many times: §3.3's
tickets example hands every child worktree the same `implementer` and `split` runs N chunks against
one of them concurrently, so a role that could be edited by one step would be edited for all of
them. Frozenness is what makes that safe by construction rather than by care - and the factory
below is the other half of the same idea, since a value nobody can edit is worth little while a
second constructor stands beside it that rebuilds it with any field replaced.

## A role is declared by a factory, and the model is on the decorator

§3.3's table says what a role *is*: "a `@role(model=…)` factory returning a frozen `Role`", and
§3.11 rejects by name the thing it replaces - "a bare `replace()` on a module-level `Role` ... lets
a call site change the model or the restrictions, a mutation with pleasant syntax". Those are one
decision read from two sides, and §3.2 writes out what an author types:

    @role(model=Claude.OPUS)
    def implementer(*, on_question: QuestionHandler | None = None) -> Role:
        return Role(name="implement", instructions=prompt_file("prompts/implement.md"),
                    restrictions={Restriction.NO_VCS_WRITES}, on_question=on_question)

**The parameter list is the whole of the override surface, and that is the point.** A call site may
turn `on_question` and nothing else, because `on_question` is the one knob the author put in the
signature; the prompt, the restrictions, the tools and the model are unreachable from outside the
function. `replace(implementer, on_question=answer)` reached all of them instead - every field of a
frozen dataclass is a keyword argument to `replace`, and there is no way to hand `replace` a
whitelist. So the factory buys nothing about immutability, which the value already had. What it
takes away is the *second constructor*: after this, one line in one module decides what a role is
allowed to differ by, and a call site that wants a fifth knob has to go and ask for it there.

**`model=` is on the decorator and appears nowhere in the `Role(...)` call.** §3.3's table lists a
role's contents as "name, instructions, restrictions, tools, required capabilities" and stops. One
declaration, not two: preflight reads the model off the factory *without invoking it* - it has no
arguments to invoke it with - so the model has to be readable on the object that exists before any
call is made, and a second copy typed inside the returned `Role` would be a copy free to disagree
with the one preflight read. The decorator is therefore also what puts the model *on* the value it
receives, which is the next section.

## What the decorator registers, and how preflight reads it back

**Two jobs, deliberately kept apart.** The first is registration: `@role(model=…)` records
`(name, model)` on the factory object at import, which §3.2 says "is all preflight's provider check
needs" - collect the models a workflow's roles name, and ask each provider whether its harness is
installed and authenticated, before the run starts. The second is the override surface above.
Neither needs the other, and reading them as one thing is what makes the decorator look like a
registry when it is mostly a constructor.

**The registry is the workflow module's own namespace, and the factory is the record.**
`RoleFactory` carries `.model` and `.name` as plain attributes, readable without a call, and since
UF1.3 preflight enumerates the `RoleFactory` values in `vars(sys.modules[workflow.fn.__module__])`
and reads `.model` off each. Nothing is written to a process-global table: a module-level dict
keyed by qualname would collect every role in every workflow the interpreter has imported, and
preflight would then demand a provider for a workflow that is not being run. The stage's own "known
cost, accepted" is the evidence for which scope was meant - "a role **imported into a workflow
module** but never used makes preflight demand a provider the run does not need" - which is
precisely the over-approximation a namespace scan makes and a global table does not stop at. It is
the *workflow's* module and never the roles': `fix` declares its two in `workflows/fix/roles.py`
and the import line in `workflows/fix/__init__.py` is what puts them where preflight looks.

**`.name` is the factory's own name and not `Role.name`**, and the two differ on the shipped
workflow: `fix`'s factory is `implementer` and the role it returns is `implement`. It could not be
otherwise - the role's name is inside the function, unreachable without calling it, which is the
thing preflight may not do - so this one is for diagnostics, and the model is what preflight reads.
A refusal that says "the role declared by `implementer`" sends its reader to a line they can find;
`Role.name` is the memo address and is a fact about a value that does not exist yet.

## The model reaches the value through the decorator, and an unbound role refuses loudly

Three framework readers want the model off a `Role` - `base_of` fingerprints it, `Run.step` puts it
on the `AgentTask`, and `Capabilities.require` keys its per-run cache on it - and every one of them
wants a `ModelId` rather than something to check first. (Preflight is not among them, and since
UF1.3 that is exact rather than nearly: it collects distinct models off the *factories*, and never
holds a `Role` at all.) So
`role.model` is a `ModelId` and the optionality lives one field down: `_model: ModelId | None`, a
private init field the decorator is the only sanctioned writer of, behind a `model` property that
raises `InputError` naming `@role(model=…)` when nothing has bound one.

**`replace` and not mutation, which is why the field is an `init` field.** The decorator calls
`replace(built, _model=…)` on the value the author's function returned, so it never writes through
a frozen instance's back - and `dataclasses.replace` on a `Role` goes on working for everyone else,
carrying `_model` across like any other field. That is the property a `field(init=False)` would
have cost: `replace` re-defaults an `init=False` field, so `replace(role, on_question=h)` would
silently hand back a role with no model, and the refusal would arrive at the step rather than at
the line.

**What was rejected, in the order it was considered.**

  * **Leave `model` public and optional.** One field, no property, and the whole cost moves into
    the four readers above as an `if model is None` each - four places that have to invent an
    answer for a state the decorator exists to prevent, and `base_of` would have to accept `None`
    for a term §3.6 says is always there.
  * **`field(init=False)` and `object.__setattr__` in the decorator.** Cheaper to write and it
    breaks `replace` as described - and it is the decorator mutating a frozen value it was handed,
    which is the mutation-with-pleasant-syntax this deliverable removed from call sites. Doing it
    in the framework instead of in a workflow does not make it a different act.
  * **A `BoundRole` subclass the decorator returns.** Two types for one thing: every annotation in
    `sdk/_engine/` becomes a union or a lie, `Role[P]` stops being what §3.3 says an author
    declares, and `replace` on the subclass has the same field problem one class further down.
  * **Keep the model only on the factory and pass it to `run.step` beside the role.** It would
    thread a second argument through `Run.step`, `Journal.step`, `base_of` and
    `Capabilities.require` to keep two halves of one declaration together by hand, and a `Role`
    handed to anything without its model would be a value that means nothing on its own.

## `name` is the memo address, and the step no longer carries one of its own

§3.11: "a `name=` on `run.step`" is a rejected member, because "the role already carries one, so a
per-call-site string is a second place to say the same thing". So `run.step(role, **inputs)` takes
no name and the entry goes to `steps/<role name>/`, which is the whole of what this field is for.
Two calls on one role therefore land in **one** directory and are told apart inside it - by their
inputs, which move the digest, or by §3.6's counter when the inputs match. `fix` is the shipped
instance: the call that implements and the call that repairs are one `implementer` given a
`request` and then some `findings`, and both are recorded under `steps/implement/` at two digests -
which is also why the repair reports as `implement` everywhere a name is printed.

**Validated here, at the line that declares it, by constructing the `StepName` it is about to
become.** That type *is* the rule the layout applies - a path segment out of §3.3's allowlist,
with the length cap and the reserved device names - so asking it here is the only way to check the
name without writing a second copy of that rule inside `sdk/`. Refused at the declaration for the
reason every other refusal in this module is: `sdk/_engine/steps.py` builds the same `StepName` on
the way into a step, which is after the run started, after preflight, and possibly after other
agents have been paid for.

**It is not a fingerprint term, and that is the division of labour worth stating once.**
`base_of` takes instructions, model, restrictions, tools, inputs and head; the name is nowhere in
it and must not be. The name is the *address* - which directory the entries live in - and the
digest is what is compared inside it. Renaming a role therefore moves its whole ledger to a new
directory and re-runs everything under it, not because a digest changed but because nothing is
looked up at the new address; editing the prompt keeps the address and moves the digest. The field
docstring says the same thing where an author reads it.

## `instructions` is the prompt text, and not a path to it

§3.7's example keeps its prompts in files - `instructions=prompt_file("prompts/decompose.md")` -
and what that hands over is **the prompt itself, already resolved.** This field never holds a path.
Three things say so, and the third is decisive:

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

So §3.7's `prompt_file("prompts/decompose.md")` is the sanctioned spelling and it is below. It reads
the file **at declaration time** and hands back its text, which has none of the problem above: the
`Role` holds the prompt, the fingerprint hashes the prompt, and editing the prompt moves the digest
and re-runs the step. It is a function and not a `Role` field, and that is the same decision read
twice - `Role.instructions` stays a `str`, `Role` does no I/O, and there is no second spelling of
`instructions` for a reader to wonder about.

**What the path is relative to was the open question, and the answer is the directory of the module
that called it.** §3.7 writes `prompt_file("prompts/decompose.md")` in `workflows/tickets/roles.py`
and means `workflows/tickets/prompts/decompose.md`, wherever pip put that package. The two
alternatives are both wrong in ways that only show up after installation: the current directory is
whatever the person's shell was in, which is the ambient read stage 11.0 spent a deliverable
removing, and the package root would need this module to guess which of a caller's parent packages
was meant.

**Declaration time moved when the factory arrived, and the sentence above survived it unchanged.**
A module-level `implementer = Role(...)` read its prompt once, at import; a
`@role(model=…) def implementer(...)` reads it on **every call**, which for `fix` is twice a run
and for `split` is once per chunk. Three things make that a non-event and one of them had to be
checked rather than assumed. The digest does not move, because the file is not being edited between
two calls in one run and the text is what is hashed either way. The read is a `read_text` of a file
the author committed beside their workflow, which is measured in microseconds against a step that
pays for an agent. And the resolution rule is still *the calling module's* directory, which is the
one that had to be checked: the caller is now a function body rather than a module body, and a
frame's `f_globals` is its module's either way - so `prompt_file("prompts/implement.md")` written
inside a factory in `workflows/fix/roles.py` still finds `workflows/fix/prompts/implement.md`.
`tests/sdk/test_roles.py` pins that against a package it builds on disk rather than against this
paragraph. What did change is *when a bad prompt is refused*: a missing file used to fail at import
and now fails at the first call, which for a workflow is still before any agent runs, since a
factory is called at the top of the workflow function or at the step that uses it.

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
states this implication itself, in one direction, naming one member. And it costs nothing downstream
- `base_of` fingerprints instructions, model, restrictions and tools, and neither `requires` nor
`on_question` is a term, so a derived member cannot move a digest. (The section below folds a second
member in on the same three arguments, and checks that last one again from scratch, because its
trigger *is* a fingerprint term where `on_question` is not.)

**The implication runs one way only.** `requires={MID_RUN_QUESTIONS}` with no handler is left
exactly as written: it says the prompt may invite the agent to ask and the author wants a backend
that can, which is over-declaring and is the author's business. Refusing it would be inventing the
policy the paragraph above declines to invent.

## `tools=` implies `TOOL_CALLING`, on the same three arguments and by the same three lines

Stage 17 reported the second half of the paragraph above as missing: a role declaring `tools=` and
forgetting `Capability.TOOL_CALLING` in `requires=` was accepted at the line that wrote it and died
at preflight, which is nowhere near the line that needs fixing. 19.2 folded it in here, and the
argument is the one above checked term by term rather than a new one.

**A second declaration carries no information.** There is no role that offers a model a tool and
does not need a backend able to call one - a `Tool` crosses the port on `AgentTask.tools`, an
adapter renders it into whatever its backend calls tools, and a backend without the capability has
nowhere to put it. So `tools=[report_findings], requires={Capability.TOOL_CALLING}` says the same
thing twice and the second copy can only be forgotten. **What forgetting it costs** is the same
shape as the other implication's, one step less silent: the reporting step's agent is never offered
its tool, so it cannot fire it, so `Run.step` raises `RoleIncompleteError` at exit 6 - a real
failure, forty minutes and several agents into a run, naming a prompt that was never the problem.
Containment exists to turn exactly that into a refusal at the step that would have paid for it -
before the dispatch and before anything is provisioned for it, which since UF1.3 is the earliest a
capability mismatch can be caught at all.

**The implication runs one way only**, identically: `requires={TOOL_CALLING}` with a role that
declares no tools is left exactly as written. It says the author wants a backend that can call
tools - perhaps the prompt tells the agent to use the harness's own - which is over-declaring and
is the author's business, and refusing it would be inventing a policy this module has already twice
declined to invent.

**And it moves no digest, which had to be checked here rather than inherited.** The other
implication is trivially free because neither `on_question` nor `requires` is a `base_of` term.
Here the *trigger* is a term: `base_of` fingerprints instructions, model, restrictions and tools, so
`tools` is hashed. That changes nothing about the conclusion and is worth stating rather than
waving at. Adding a tool already moved the digest, before this fold existed and for its own reason
(§3.6 rule 4: name, description and payload schema). What the fold writes is a member of `requires`,
and `requires` is not a term - so the derived member contributes nothing on top of what the tool
already contributed, and no role's digest is different today from what it was yesterday.
`tests/sdk/test_roles.py` measures that against `base_of` rather than restating it.

**What stage 16 is therefore written against.** One containment and no special case:
`role.requires <= await runner.capabilities(role.model)`, per role, over the providers the
workflow's roles name. One thing worth building into the message, now in two versions of itself:
when the missing member is `MID_RUN_QUESTIONS` and the author never typed it, say that
`on_question` put it there, and when it is `TOOL_CALLING`, say that `tools=` did - otherwise the
reader goes looking for a line that is not in their file.

## `Role[P]`, and why the default is `None` rather than `object`

`P` is the payload type of this role's reporting tool, and it is what carries §3.3's typing promise
from `reporting_tool()` through to the workflow: `Run.step` is
`async def step[P](self, role: Role[P], ...) -> P`, so `findings = await run.step(reviewer())`
followed by `findings.high()` is checked rather than hoped for.

`sdk/workflow.py` settled the same class of question for `Run[P]` and answered `object`, arguing
that a workflow's params are "genuinely **unknown** and not **unchecked**". Checked here, and
answered differently on purpose: an effect step's result is not unknown. §3.3 says it is `null`, so
`None` is the true statement and `object` would be a vaguer one. `None` also earns something
`object` would not - mypy's `func-returns-value` refuses to let a name be bound to it, so
`outcome = await run.step(implementer())` on an effect role is an error at the line that wrote it,
which is the right answer to a step that has nothing to hand back. The *shape* is
`Run[P]`'s and `ports/terminal.py::Screen[T = None]`'s: `disallow_any_generics` is on under
`--strict`, so a bare `Role` in an annotation needs a type-parameter default to be legal at all.

**Inference, measured under `mypy --strict` rather than assumed.** These infer:

    Role(name=..., instructions=..., tools=[report_findings])   -> Role[Findings]
    Role(name=..., instructions=...)                            -> Role[None]
    Role(name=..., instructions=..., tools=[])                  -> Role[None]
    Role(name=..., instructions=..., tools=[read_spec])         -> Role[None]
    Role(name=..., instructions=..., tools=(read_spec, report_findings))
                                                                -> Role[Findings]

`RoleFactory[**P, R]` then carries whichever of those the author's function returns out to the call
site: `R` is solved from the declaration's return annotation, so `reviewer() -> Role[Findings]`
makes `run.step(reviewer())` a `Findings` and a bare `-> Role` makes it a `None`. The inference
above is what decides which annotation is honest; the annotation is what the workflow sees.

and one shape does not: a **list** display mixing a plain `Tool` with a `ReportingTool`. mypy has to
choose one item type for a list before it can solve `P`, and the join of two unrelated classes is
`object`, so no constraint reaches `P`, the default stands, and the item is then refused against
`Tool | ReportingTool[None]`. It fails at the declaration and it fails loudly; it is never silently
`Role[None]`. Two spellings fix it, and `tests/sdk/test_roles.py` pins both:

    tools=(read_spec, report_findings)                              # a tuple, not a list
    Role[Findings](name=..., instructions=..., tools=[read_spec, report_findings])

The explicit spelling is checked and not merely tolerated: `Role[Tickets](tools=[report_findings])`
where the declaration is a `ReportingTool[Findings]` is an error, so naming the wrong parameter is
caught rather than believed.

## What this module refuses, and what it leaves to be refused downstream

`InputError`, throughout, and at declaration time - `sdk/params.py`'s stance and its reason, that a
package which cannot be invoked correctly should fail when it is imported. Everything here was typed
by a workflow author, and exit 70 would send them hunting for a bug in the framework.

Two of the four refusals below are `AgentTask.__post_init__`'s own, made one layer earlier and in
its words, exactly as `ReportingTool.__post_init__` re-makes `Tool`'s two checks. The duplication is
deliberate and it is not free-floating: `AgentTask` is constructed inside `Run.step`, after the
journal missed, after the worktree was reset, and after earlier steps in the run have already paid
for agents. Refused here, the reader is looking at the line they wrote.

The fourth is the same move made against a different downstream: `StepName(role.name)` is built by
`sdk/_engine/steps.py` on the way into every step, so a malformed name is refused there too - at a
line in the engine, during a run, rather than at the declaration that typed it.

Not refused here, and deliberately: **that a step taking no `commit=` uses a role declaring
`Restriction.NO_VCS_WRITES`**. §3.3 calls that pairing "the author's job, by convention and not
enforcement", and the two halves are not in the same place anyway - the restriction is on the role
and the `commit=` is on the call, so a role cannot see how it is being used. Nothing here reaches a
port either: no provider is asked what it can do and no capability is compared against anything.
Preflight is stage 16, and it needs a runner. (`prompt_file` is the one piece of I/O in this module
and it is not an exception to that sentence: it reads the author's own source tree, at import, and
`ports/` has no ABC for "open a file the author committed beside their workflow" - see below.)

**The two implications above are not exceptions to it either**, and the distinction is worth
keeping straight now that there are two of them: each *adds* a member to a set the author declared,
and neither refuses anything, asks any provider anything, or compares a capability against
anything. A fold is a declaration completing itself. A refusal would be a judgement about how a
role is being used, which is what the `commit=` pairing would need and is what this module still
makes none of.

## The enums a role is declared out of are re-exported here, and this is not a facade

`Role`'s fields are a `ModelId`, a set of `Restriction`, a set of `Capability` and a
`QuestionHandler`, and all four are `ports/agent.py`'s for the reason `Screen` is
`ports/terminal.py`'s: an `AgentRunner` speaks them, and `ports` may not import `sdk` without
contract 1 inverting on its lowest edge. So an author writing `model=Claude.OPUS` beside a `Role`
would otherwise be reaching into `agl.ports` for half of one declaration - which is exactly what
`ARCHITECTURE.md` §5's facades exist to prevent, one layer over.

They are re-exported **here** rather than in a facade of their own, and here rather than nowhere,
because this is the module an author meets them in: `Claude`, `OpenAI` and `ModelId` are what
`model=` takes, `Restriction` what `restrictions=` takes, `Capability` what `requires=` takes, and
`QuestionHandler` what `on_question=` is. `sdk/tools.py` set the shape - it re-exports
`ports.agent.Tool` and `ToolResult` beside the declaration they belong to, and says in its first
paragraph that it is not one of §5's pure facades either. This module is that same thing: a module
with logic in it that also carries the port vocabulary its own type is spelled in.

`Tool` is deliberately not among them, though this module imports one: it is `sdk/tools.py`'s
re-export, beside `ReportingTool`, and a second copy here would be a second front door for one name.

## `RoleIncompleteError` has no caller here, and that is deliberate

It is raised by 12.1's `Run.step` when a reporting step's agent finishes without ever firing its
tool, which is a thing this module cannot observe and does not try to. It is named here because the
name says Role and because 12.1 should import it rather than invent it - the one member in this
module whose caller arrives in the next deliverable. Its argument is on the class.
"""

import sys
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from functools import update_wrapper
from pathlib import Path
from typing import Protocol

from agl.ports.agent import (
    Capability,
    Claude,
    ModelId,
    OpenAI,
    QuestionHandler,
    Restriction,
    Tool,
)
from agl.ports.errors import InputError, UpstreamUnexpected
from agl.ports.ids import StepName
from agl.sdk.tools import ReportingTool

# Listed rather than computed, for `sdk/terminal.py`'s reason. The six re-exports are the port
# vocabulary `Role`'s own fields and `@role`'s own argument are spelled in - see the module
# docstring - and `sdk/__init__.py` takes them from here rather than from `agl.ports.agent`, so that
# the package's front door and its submodules are one surface rather than two.
__all__ = [
    "Capability",
    "Claude",
    "ModelId",
    "OpenAI",
    "QuestionHandler",
    "Restriction",
    "Role",
    "RoleFactory",
    "RoleIncompleteError",
    "prompt_file",
    "role",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class Role[P = None]:
    """One agent, as the workflow author declares it. §3.3's "instructions + restrictions + tools +
    required capabilities", plus the name its steps are recorded under, and nothing besides.

    **Returned by a `@role(model=…)` factory and not bound to a module-level name**, which is where
    the model comes from and why none is typed here. The module docstring argues both halves; what
    a reader of this class needs is that `Role(...)` alone builds a value whose `model` refuses to
    be read, so the sanctioned spelling is the only one that produces a usable role.

    Keyword-only, following `@workflow` and for its reason. Seven fields of which five have
    defaults, and two of those - `restrictions` and `requires` - are both sets of `StrEnum` members,
    so a positional call is a thing to transpose once and be wrong about for the life of a run's
    records. §3.7's own example writes every argument by name.

        @role(model=OpenAI.SOL)
        def reviewer() -> Role[Findings]:
            return Role(
                name="review",
                instructions=REVIEW_PROMPT,
                restrictions={Restriction.NO_VCS_WRITES, Restriction.NO_FILE_WRITES},
                tools=[report_findings],
                requires={Capability.SHELL},
            )

    `P` is the payload type of the reporting tool in `tools`, defaulting to `None` for an effect
    role - see the module docstring for what infers and what has to be spelled out.
    """

    name: str
    """What this role's steps are recorded under: the directory `steps/<name>/` in every namespace
    it runs in. **The step takes no name of its own** (§3.3) - `run.step(role, **inputs)` reads this
    one, because a per-call-site string would be a second place to say the same thing.

    First, because it is what a reader of a declaration wants first and what an entry path is
    composed out of. Two steps on one role land in one directory and are separated inside it: their
    inputs move the digest, and §3.6's counter separates them when the inputs match. `fix`'s
    `implementer` is the shipped instance of that, serving both the implement and the repair step.

    **Not a fingerprint term, deliberately.** `base_of` takes instructions, model, restrictions,
    tools, inputs and head, and this is none of them. The name is the *address* - which directory
    holds the entries - and the digest is what is compared inside it. So editing a prompt moves the
    digest and re-runs the step at the same address, while renaming a role moves the whole ledger
    to a new address, where nothing is found and everything re-runs. Both are loud; neither is a
    false hit.

    Validated at this declaration by constructing `StepName`, which is the rule the layout will
    apply anyway - a path segment, and never something composed into one here. The module docstring
    argues why the refusal belongs at the line that wrote it."""

    instructions: str
    """The prompt, in full, as the author wrote it - the text and never a path to it.

    Fingerprinted verbatim by §3.6, which is the whole argument for it being text; the module
    docstring makes it. Interpolating a step's `**inputs` into it is `Run.step`'s business (§3.3),
    so what is stored here is what the author typed and nothing derived from a call."""

    _model: ModelId | None = None
    """Where `@role(model=…)` puts the model, and the only field on this class an author does not
    type. `None` is "no factory has bound one yet", and the `model` property below is what every
    reader of a role goes through.

    **An `init` field rather than `init=False`**, which is what keeps `dataclasses.replace` whole:
    `replace` copies every init field across and re-defaults the rest, so a role that went through
    a factory and then through a `replace` still has its model. It is also how the decorator writes
    it - `replace(built, _model=…)` on the value the author's function returned, rather than an
    `object.__setattr__` through the back of a frozen instance.

    Private, because it is not part of what §3.3 says an author writes: `Role(_model=…)` is a
    spelling the framework uses once, in `RoleFactory.__call__`, and typing it by hand would be the
    second declaration of the model that "one declaration, not two" refuses. `mypy` refuses
    `Role(model=…)` outright, which is the error a reader of the old spelling gets first."""

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

    Declaring any tool at all adds `Capability.TOOL_CALLING` to `requires`; the module docstring
    argues that at length, including why a member derived from a fingerprint term is still not one.

    Declaration order is kept, and normalised to a tuple to match `AgentTask.tools`. The order is a
    fingerprint term - `base_of` reads the sequence as given and does not sort it, unlike a payload
    schema's `required` - so moving a tool up a line re-runs the step. That is §3.6 rule 4 as
    written, noted here because it is the one place in this declaration where a cosmetic edit
    costs an agent run."""

    requires: AbstractSet[Capability] = frozenset()
    """What a backend must be able to do at all for this role to run on it.

    The counterpart to `restrictions`: that is what the workflow forbids, this is what the backend
    must offer. Compared against `runner.capabilities(model)` at every `run.step` (stage 16's
    containment), so a role that cannot work is refused before its agent is dispatched and before
    its checkout is cut, rather than forty minutes in with a result nobody can trust. **Not at
    second zero, since UF1.3**: reaching this set means calling the factory that builds the role,
    and preflight has no arguments to call one with - `sdk/_engine/preflight.py` argues what that
    costs. Nothing here checks it either - this module reaches no port and asks no provider
    anything.

    Two members are folded in rather than restated: declaring `on_question` adds
    `MID_RUN_QUESTIONS`, and declaring any `tools` adds `TOOL_CALLING`. The module docstring argues
    both at length, and both run one way only - naming either member without the thing that implies
    it is left exactly as written. An `AbstractSet` for `restrictions`' reason, normalised to a
    `frozenset`."""

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
        # Constructed for its refusal and discarded, exactly as `split`'s `Chunk` does with
        # `Namespace`: `StepName` *is* the rule `steps/<name>/` will be composed under, so asking
        # it here is the only way to check the name without a second copy of §3.3's allowlist
        # living in `sdk/`. Its `InputError` names the character and the position, and it is raised
        # while the author is looking at the declaration rather than at the first step of a run.
        StepName(self.name)
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
        if tools:
            requires |= {Capability.TOOL_CALLING}
        object.__setattr__(self, "restrictions", frozenset(self.restrictions))
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "requires", requires)

    @property
    def model(self) -> ModelId:
        """Which model runs this role, named on the decorator because the reason is semantic
        (§3.2): this role touches sensitive code, that one needs deep judgement, this one is cheap.

        `Claude.OPUS` and `OpenAI.SOL` in one workflow is correct and expected. There is no
        config-level override - ARCHITECTURE.md §6 and §3.2 both say so, and the argument is that
        an override costs a schema, resolution and validation to buy *why is my Opus role running
        GPT-5?* Which adapter serves it is `task.model.provider`'s business and nothing here needs
        to know.

        **A `ModelId` and never an optional**, which is the whole reason this is a property over a
        private field rather than a field of its own: `base_of` fingerprints it, `Run.step` puts it
        on the `AgentTask` and `Capabilities.require` caches on it, and none of those three has an
        answer for a role with no model. So the one place that can be missing is this one, and it
        refuses rather than returning `None` for three callers to invent an answer to. Preflight is
        not a fourth: it reads the model off the *factory*, which is why it can ask about a role it
        must not build.

        **`InputError`, at the first read**, which is this module's register for everything a
        workflow author typed: a `Role` that never went through a factory was built by a line in
        their file, and exit 70 would send them looking for a bug in the framework. It is the one
        refusal here that cannot happen at the declaration - a `Role` is a legal value until
        somebody asks it what it runs on - so it names the decorator instead, which is the line
        that is missing rather than the line that is wrong."""
        if self._model is None:
            raise InputError(
                f"the role named {self.name!r} has no model, so nothing can say which provider "
                f"runs it, fingerprint it or check what its backend can do. A role's model is "
                f"declared on its factory - `@role(model=Claude.OPUS)` above the function that "
                f"returns this `Role` (§3.2, §3.3) - and is deliberately not a field of `Role` "
                f"itself, so that preflight can read it without calling the factory. This value "
                f"came from a bare `Role(...)`, which builds one nothing has bound a model to"
            )
        return self._model


class RoleFactory[**P, R]:
    """What `@role(model=…)` leaves bound to the author's name: a callable that builds the `Role`,
    with the model readable off it before anything is called.

    **Two surfaces, one object, and they answer different callers.** `factory(...)` is the
    workflow's - it runs the author's function and binds the model onto what came back. `.model`
    and `.name` are preflight's, and preflight uses only those: §3.2 says it "never invokes the
    function, which it could not do without arguments it does not have", and this class is what
    makes that sentence a fact about the type rather than a discipline.

    **`RoleFactory[**P, R]` is what keeps the two typing promises §3.3 makes.** `P` is the author's
    own parameter list, so `implementer(on_question=answer)` is checked against the signature they
    wrote and a call that misspells the keyword is an error at that line rather than a role which
    silently cannot ask. `R` is the payload type of the role's reporting tool, carried from
    `reporting_tool()` through the declaration's return annotation to `run.step`, so
    `findings = await run.step(reviewer())` followed by `findings.high()` is checked. Neither is
    `Any`: a decorator returning `Callable[..., Role[Any]]` would type-check every call site in
    both workflows and mean nothing at any of them.

    `update_wrapper` for the ordinary reason - `__doc__`, `__name__`, `__qualname__` and
    `__module__` come from the function, so the long argument an author writes under a role
    declaration is still that name's docstring, and a traceback through a factory still says where
    it was written.
    """

    __name__: str
    __qualname__: str
    """What `update_wrapper` copies off the decorated function, declared here so that `mypy` knows
    the two exist. They are the function's own, not the role's - `.name` below says the same thing
    in this class's own vocabulary, and is the one a caller should read."""

    name: str
    """The **factory's** name - `implementer` - and not the `Role.name` its steps are recorded
    under, which for `fix` is `implement`.

    It could not be the role's: that name is inside the function body, and reaching it means
    calling the factory, which is the one thing preflight may not do. So this is the diagnostic
    half of the `(name, model)` §3.2 says the decorator registers - it names the declaration a
    reader has to go and find - and `.model` is the half preflight acts on."""

    model: ModelId
    """The model every `Role` this factory builds runs on, readable without building one.

    §3.2's provider check is "collect the providers named by the workflow's roles" and then
    `check_ready` per distinct model, at second zero. This attribute is the whole of what that
    needs, and it is why the model is declared on the decorator rather than inside the function:
    everything else about a role is knowable only by calling one."""

    def __init__(self, declaration: Callable[P, Role[R]], model: ModelId) -> None:
        update_wrapper(self, declaration)
        self._declaration = declaration
        self.name = declaration.__name__
        self.model = model

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Role[R]:
        """The author's function, with this factory's model bound onto what it returned.

        `replace` and not `object.__setattr__`: the value the author built is left alone and a new
        one is returned with `_model` filled in, which is the same act the call sites this
        deliverable removed were performing on roles they did not own. Doing it inside the
        framework does not make it a different act - what makes it a different act is that the
        field being set is the one field no author types, and that the value is one line old and
        has been handed to nobody.

        `__post_init__` runs again on the way through, which is free and is worth knowing: the
        capability folds are idempotent - `on_question` implies `MID_RUN_QUESTIONS`, `tools`
        implies `TOOL_CALLING` - and every refusal it makes was already made a microsecond earlier
        inside the function.
        """
        return replace(self._declaration(*args, **kwargs), _model=self.model)


class _RoleDecorator(Protocol):
    """What `role(model=…)` hands back: a decorator that is generic in the function it is given.

    Spelled as a callback protocol because the two type parameters are solved at the *decoration*
    and not at the `role(model=…)` call - `role` knows nothing about the function it is about to be
    applied to, and a `Callable[[Callable[P, Role[R]]], RoleFactory[P, R]]` return annotation would
    bind `P` and `R` one call too early, leaving mypy to solve them against nothing. Private,
    because no author writes it: it is the type of a two-line expression that exists only between
    `@role(model=…)` and the line under it.
    """

    def __call__[**P, R](self, declaration: Callable[P, Role[R]], /) -> RoleFactory[P, R]: ...


def role(*, model: ModelId) -> _RoleDecorator:
    """Declare a role: the model it runs on, over the function that builds it.

        @role(model=Claude.OPUS)
        def implementer(*, on_question: QuestionHandler | None = None) -> Role:
            return Role(name="implement", instructions=prompt_file("prompts/implement.md"),
                        restrictions={Restriction.NO_VCS_WRITES}, on_question=on_question)

    §3.3's "a `@role(model=…)` factory returning a frozen `Role`", and the module docstring holds
    the argument for both halves - why the override surface is the function's parameter list, and
    why the model is on this line rather than in the `Role(...)` under it.

    **Keyword-only, and one argument.** `@role(Claude.OPUS)` would read as well and says nothing
    about *what* the model is being given to, on a decorator that may grow a second registration
    term later; `model=` is the same word the field it replaces was spelled with, so a reader
    coming from the old spelling finds it where they expect. There is no `name=` here: the role
    names itself, and a name on this line would be a second place to say the one thing §3.11 took
    off `run.step`.

    **Nothing is validated here and nothing could be.** A `ModelId` is a `StrEnum` member, so there
    is no malformed value to refuse; everything else about the role is inside a function that has
    not run yet, and running it to check is exactly what preflight may not do. Whether a provider
    can actually serve this model is §3.2's first preflight check, which needs an `AgentRunner` and
    happens at second zero - `sdk/_engine/preflight.py` - and the terms of the `Role` are refused
    by `Role.__post_init__` at the first call.
    """

    def decorate[**P, R](declaration: Callable[P, Role[R]]) -> RoleFactory[P, R]:
        return RoleFactory(declaration, model)

    return decorate


def prompt_file(path: str | Path) -> str:
    """The text of a prompt file, read **now**, at the line that declares the role.

    §3.7's sanctioned spelling, and it takes one argument because that is how §3.7 writes it:

        @role(model=Claude.OPUS)
        def decompose(*, on_question: QuestionHandler | None = None) -> Role[Tickets]:
            return Role(
                name="decompose",
                instructions=prompt_file("prompts/decompose.md"),   # read at declaration
                tools=[report_tickets],
                on_question=on_question,
            )

    **Reading at declaration time is the whole mechanism.** What the `Role` then holds is prompt
    *text*, so §3.6 fingerprints the prompt: edit `prompts/decompose.md`, resume, and the digest has
    moved and the step re-runs against the new wording. A role holding the *filename* would
    fingerprint the filename, the edit would move nothing, and the resume would replay what the old
    wording produced - a cache hit, at the moment you are iterating and least want stale output,
    with nothing anywhere to notice. The module docstring makes that argument at length; this
    function is what makes the honest spelling the short one.

    **A relative path resolves against the directory of the module that called this**, so §3.7's
    `prompt_file("prompts/decompose.md")` in `workflows/tickets/roles.py` finds
    `workflows/tickets/prompts/decompose.md` when that package is installed anywhere. An absolute
    path is used exactly as given. The caller's file comes off the calling frame's `__file__`
    (`sys._getframe`, which is one attribute lookup, where `inspect.stack()` builds a `FrameInfo`
    for every frame on the stack and reads source context for each - and since UF1.2 this runs
    inside a factory rather than at import, so `split` pays for it once per chunk).

    **The calling frame is a factory's body now, and that changes nothing**, which is worth one
    sentence because it is the half of the resolution rule a reader would reasonably doubt. A
    frame's `f_globals` is the globals of the module the *code* was written in, not of whoever
    called it - so a factory defined in `workflows/fix/roles.py` and invoked from
    `workflows/fix/__init__.py`, from `api.py` or from a test still resolves against
    `workflows/fix/`. The module docstring says where that is measured.

    **A caller with no `__file__` - a REPL, an `exec`, a frozen import - is an `InputError` telling
    the author to pass an absolute path, and never a fall back to `Path.cwd()`.** The current
    directory is where the person's shell happened to be, which for an installed workflow is the one
    place its prompts are certainly not; and a fall back would find *a* file often enough to be
    trusted and then read someone else's on the day it did not. Stage 11.0 spent a whole deliverable
    taking that ambient read out of AGL and this is not the place to put one back.

    **Every refusal is an `InputError`, at declaration time**, which is this module's register and
    `arg()`'s and `@workflow`'s and `reporting_tool()`'s before it: a package that cannot be invoked
    correctly should fail in front of the author, rather than forty minutes into a run that has
    already paid for three agents. Since UF1.2 that is the first call of the factory rather than the
    import of the module it is written in - still before any agent, since a workflow calls its
    factories at the step that uses them, and still with the author's own line in the traceback. A
    missing file, a directory, a file that will not open, one that is not UTF-8, and one that is
    empty or nothing but whitespace are the five, and the last is `Role.__post_init__`'s own check
    made one line earlier and for its reason: an empty prompt is the whole of what an agent was
    going to be asked.

    **The text is returned exactly as it was read**, trailing newline and all. Trimming it would be
    this module editing the author's prompt, and - since the text is hashed - a rule about
    whitespace that two people could remember differently is a re-run waiting to happen. The one
    normalisation is Python's own universal newlines, which `read_text` does: a checkout with
    `core.autocrlf` on would otherwise fingerprint every prompt differently from the same commit on
    another machine.

    **UTF-8, and a decode error is a refusal rather than a repair.** No `errors=` argument, so a
    prompt in some other encoding is refused by name instead of being read with replacement
    characters in it - which would be a prompt the author never wrote, hashed into a digest, and
    handed to a model that would do its best with it.
    """
    asked = Path(path)
    # `sys._getframe(1)` is the caller of *this* function, so the lookup has to happen here and not
    # inside the helper below - a frame index is a fact about where the line is written.
    where = asked if asked.is_absolute() else _beside_the_caller(sys._getframe(1).f_globals, asked)
    try:
        text = where.read_text(encoding="utf-8")
    except FileNotFoundError as missing:
        raise InputError(
            f"there is no prompt file at {where}, so the role declared with it would have nothing "
            f"to ask its agent. A relative path is resolved against the directory of the module "
            f"that called `prompt_file` - never against the current directory - so this is the "
            f"path {asked!r} names from where it was written"
        ) from missing
    except IsADirectoryError as directory:
        raise InputError(
            f"{where} is a directory, and a role's instructions are one prompt. Name the file "
            f"inside it that this role is asking its agent to read"
        ) from directory
    except UnicodeDecodeError as undecodable:
        raise InputError(
            f"{where} is not UTF-8 text: {undecodable}. A prompt is read as UTF-8 and nothing "
            f"here repairs one - a prompt read with replacement characters in it is a prompt "
            f"nobody wrote, fingerprinted as though somebody had, and handed to a model that "
            f"would answer it anyway"
        ) from undecodable
    except OSError as unreadable:
        raise InputError(
            f"{where} could not be read: {unreadable}. The prompt is read where the role is "
            f"declared, so this is the role's factory failing rather than the step it was for"
        ) from unreadable
    if not text.strip():
        raise InputError(
            f"the prompt file {where} is empty, and a role's instructions are the whole of what "
            f"its agent is asked to do. `Role` refuses an empty prompt too, one line later, and "
            f"`AgentTask` refuses it again at the dispatch"
        )
    return text


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


def _beside_the_caller(caller: Mapping[str, object], asked: Path) -> Path:
    """`asked`, resolved against the directory of the module whose globals these are.

    `caller` is a frame's `f_globals` and is taken as a `Mapping[str, object]` rather than as the
    `dict[str, Any]` typeshed gives it, so that `__file__` is narrowed by an `isinstance` here
    instead of being trusted by a `cast` there. A module's `__file__` is a `str` when it is on
    disk and absent when there is no file - those are the two cases, and both are answered below.

    Resolved before the parent is taken: `__file__` is absolute for an imported module, but a
    `python some/script.py` in older shapes and a `__main__` under some launchers is not, and
    `Path("roles.py").parent` is `.` - which would silently become exactly the current-directory
    read `prompt_file` refuses to make.
    """
    declared = caller.get("__file__")
    if not isinstance(declared, str):
        raise InputError(
            f"`prompt_file({str(asked)!r})` was called from something with no `__file__` - a REPL, "
            f"an `exec`, or a frozen import - so there is no module directory for a relative path "
            f"to be relative to. Pass an absolute path. AGL will not fall back to the current "
            f"directory: a workflow is read from wherever it was installed, and the directory this "
            f"process happens to have started in is the one place its prompts are certainly not"
        )
    return Path(declared).resolve().parent / asked
