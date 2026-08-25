"""The composition root: the only module that says `new`, and the two bundles it says it into.

Everything above this file receives ports and never picks a class. `.importlinter`'s contract 5 is
that rule made executable - `agl.*` may not import `agl.adapters`, with two ignore expressions
naming this module and nothing else, expressions that matched nothing until the imports below were
written. What the rule buys is measurable target #6: deleting a connector means deleting its
adapter package, its config section and its entry here, because there is no fourth place its name
could be. And it buys target #8 from the other direction - if nothing above names a class, then
substituting every class at once is something this module can do by itself, which is the all-fakes
bundle below and the reason it is a product feature rather than a fixture.

The cost is paid here and is meant to be. This is the one file a reader must open to learn what AGL
is actually made of, and the one file that a new backend, a new store and a new display all have to
touch. That concentration *is* the design: a composition root nobody ever edits is one whose
decisions have leaked somewhere else.

## `Services` moved at stage 10.2; the construction of it did not

The type is now `sdk/_engine/services.py` and is imported here, re-exported in `__all__`, and built
below exactly as it was. The move was decided when the class was written: `Run.services` has to be
annotated with it, `Run` lives in `sdk/workflow.py`, and contract 1 puts `sdk` below `config` - so
a `Services` defined here and named there is the layer stack inverted. Its own module docstring
argues why not `ports/` and why not eight loose parameters.

Nothing about `real()` or `fakes()` changed, and the split is along the one line that matters: the
type is eight ABCs and a `str`, which anything may name, and the construction is eight class names,
which only this module may. `FakeServices` stays here for that reason - it *constructs* nothing, but
three of its fields are still declared at concrete adapter types (`FakeRepository`, `FakeVerifier`,
`ManualClock`, the three whose fakes answer a question their port cannot), so it could not move
without carrying those names into a package that contract 5 forbids them to reach.

## The ninth field, and why the composition root is the thing that fills it

`Services.build` arrived at 14.0 and is not a port. `Verifier.verify` takes the build command as a
parameter, its one call site is the merge gate inside `integrate()`, and until then nothing above
the edge could reach `Project.build` at all - §3.11 refuses `run.project`, and `api.run` takes the
project's name rather than its record. That module's own docstring says the rest of a `Project` "has
already been spent by the container"; `real()` below is where the last field of it is spent, one
line under the `build_timeout` §3.11 routes the other way. `sdk/_engine/services.py` argues the
alternatives at length, and none of them is a second thing this file constructs.

## R2 made physical: the connector table

§3.2's requirement is one workflow, one run, several vendors, and `adapters/routing.py` is the
mechanism - one `AgentRunner` over a `Mapping[Provider, AgentRunner]`, dispatching on
`task.model.provider`, holding no vendor's name and importing no adapter. **This module composes
that mapping, and the composition is one row per provider.** The `connectors` table in `_agents`
below has two rows; a third backend is a third row, plus an adapter package, plus a section on
`schema.AgentSettings`. That is measurable target #3 as a line a reader can point at rather than an
aspiration, and it is the whole of what the framework learns about a provider.

A row is `(provider, whether it is enabled, how to construct it)`, and the third element is
deferred rather than evaluated because a disabled connector must not be constructed - which for the
Claude row means its module must not even be imported. The next section is why.

## Configured is not available (§3.2.1), and the extras are asymmetric on purpose

`agl[claude]` is a pip extra; the OpenAI harness is a separately installed binary with no Python
dependency at all; `rich` is `agl[terminal]`. The consequence lands squarely on this file, because
two adapter modules import their vendor package at module level -
`adapters/claude_code/runner.py` and `adapters/rich_terminal/terminal.py` - so on an installation
without the extra, *importing* them raises `ImportError` before any of their code runs. Meanwhile
`adapters/claude_code/fake.py`, `adapters/openai/*` and `adapters/rich_terminal/headless.py`
import neither, which is exactly why the fakes bundle works on a bare `pip install agl` with no
extras at all.

So the two adapters that need an extra are imported **inside the function that constructs them**,
and nowhere else. A module-level import of either would make every `agl workflows` on a
claude-less machine die at import time, for a connector that run was never going to address. The
deferral is not a style applied evenly: `OpenAiRunner` is imported at the top of this file with
everything else, because there is no extra to be missing, and deferring it anyway would suggest
there were one.

A failed import becomes `UpstreamUnavailable` naming the exact `pip install` that fixes it. That
class and not `InputError`, because §3.2.1 settles it in as many words - "a missing binary is
`UpstreamUnavailable`, not `InputError`" - and a missing extra is that same fact with a package
manager in place of a `PATH` lookup: the operator's configuration is correct, they asked for a
backend they meant to ask for, and what is absent is the harness. `InputError` would send them to
edit a setting that is already right.

A function-level import is still an import statement attributed to this module, so contract 5's
ignore expressions cover it, and contract 3's `allow_indirect_imports` means reaching
`claude_agent_sdk` *through* `agl.adapters.claude_code` is the sanctioned path rather than a
violation. Both were confirmed with `lint-imports` rather than assumed.

## No display selection, and why a fallback would be worse than a refusal

§3.11 rejects a `--display` flag and display selection outright: "nothing to select - a workflow
uses whichever surfaces it wants, and they coexist". So the real bundle builds `RichTerminal`, full
stop. There is no config knob choosing headless, and a missing `rich` is a refusal naming
`agl[terminal]` rather than a quiet downgrade.

The downgrade is the tempting bug and it is worth saying why it is one. `HeadlessTerminal` is a
complete `Terminal` for a dashboard - it drops the frame and returns - but on a `Screen[T]` that
carries responses it raises `UpstreamUnavailable`, because there is nobody to answer. Substituting
it for a missing `rich` would therefore turn "you did not install an extra" into a run that starts
fine, works for forty minutes, and dies at the first interactive view with an error about a
terminal that cannot take input. The install problem would have become a mystery, at the worst
moment, on the one path a person is waiting on. A refusal at construction costs one line of output
and names the fix.

**`answering()` is the third terminal and is not a fourth deployment.** `real()` builds
`RichTerminal`, `fakes()` builds `HeadlessTerminal`, and neither of those two lines moved: a
scripted terminal is something a *test* asks for by name and substitutes with `with_terminal`, so it
is a factory beside the bundles rather than a field in one. There is still no display selection and
no setting that chooses a terminal - what changed is that the one thing a workflow author could not
previously do at all, answering §3.7's approval screen without the `agl[terminal]` extra and a
hand-written `Keys`, is now a list of gestures. `agl/testing.py` re-exports it as the spelling an
author writes, because `agl.testing` may not name an adapter and this module may.

## Construction is sync, eager and inert

This module cannot `await`, which is not a limitation to route around but the reason several
questions are not asked here. Stage 7 argued `check_ready` onto the agent port on exactly this
ground: only an adapter can say whether a harness is installed, on `PATH` and authenticated, and
the answer changes while a process runs. So **nothing below asks whether a binary exists, whether a
session is authenticated, or whether a directory is really a git repository.** Building a bundle on
a machine with nothing installed succeeds; §3.2's preflight (stage 16) is where a run finds out,
per provider, once, before it starts.

That is why `GitWorkspaceProvider`, `GitHistory` and `GitIntegrator` are each handed a `Path` and
each build their own runner from it without anything being checked: the repository underneath is
one shared object reached through the filesystem, and whether it is there is git's answer on the
first call.

## The all-fakes bundle is a product feature

Measurable target #8 is that **every command runs end-to-end on fakes alone - no network, no git**,
and stages 12 through 18 drive every workflow through `fakes()` below. It is not scaffolding and it
does not get less care than `real()`: it is how kill-and-resume is a property test (#10), how three
concurrent runs are asserted (#9), and how a workflow author finds out what their prompt does
before spending a token. Read it as the second supported deployment, because that is what it is.

**The three git fakes share one `FakeRepository`, and the caller cannot get that wrong.** Stage 5
wrote the requirement into `adapters/git/fake.py` under "Construction, and where it differs from
the real adapters": the real three are each handed a `Path` and reach one repository through the
filesystem, but a fake has no durable object behind it, so three separately constructed fakes are
three unrelated repositories that agree about nothing. It said "Stage 9 is where that lands." It
lands as a local: `fakes()` constructs exactly one `FakeRepository` and hands the same instance to
all three, and there is no parameter through which a caller could pass a second - the seed for its
initial state is a parameter, the repository itself is not.

**Both providers' fakes are called `FakeAgentRunner`**, as are both `Script` types, deliberately:
they are two implementations of one idea and contract 4 forbids them sharing a definition. This
file imports the two *modules* and never the two names, which is the pattern `tests/adapters/
test_routing.py` set for the first file to import both. Qualified at every use, one vendor's fake
cannot end up serving both keys.

## The hand-off, and the shape stage 16.5 needed

`fakes()` returns a `FakeServices`, which carries the port-typed `Services` a workflow runs on
*and* the concrete fakes a test drives. Both halves are needed and neither substitutes for the
other: the bundle is deliberately port-typed so nothing above can tell it from the real one, which
is precisely what makes it useless for asserting anything - a `Store` has no "what did you write",
a `Terminal` has no "what did you draw". The concrete objects beside it are the same instances, and
they are the only ones a test can ask.

The agent runners are the exception and are not exposed, because their input is the argument: a
caller passes an agent per provider and reads what happened through the repository, the store and
the terminal. That keeps the direction honest - scripting is a thing done before the run, and there
is no recorder on any fake for a test to read afterwards, which `adapters/shell/fake.py` argues at
length.

**Two names for one object was a defect, and `with_terminal` and `with_store` are the repair.**
Substituting a port used to be `dataclasses.replace(harness.services, terminal=...)`, which reaches
one of the two views and leaves the sibling field pointing at the object that was just discarded -
so `harness.terminal` afterwards named something no run would ever use, silently, and a test reading
both read the wrong one. The two methods below swap a member in **both** views at once, which is the
only shape in which the two cannot come apart.

That is not `Services` growing behaviour, and the distinction is the one that module's own docstring
draws. `Services` is the *type every layer above receives*, so a `with_store()` there would be a
second place that knows how a bundle is assembled, and a member a workflow could reach.
`FakeServices`
is not a bundle: it is a handle on one, produced by exactly one function, in the composition root,
reachable only by a caller that already asked for fakes. Its two methods assemble nothing - each
takes an object the caller built and says "these two names go on meaning it" - so there is no second
answer here to what a bundle is made of.

**Only two of the five fields have one**, and which two is not an accident. `MemoryStore` and
`HeadlessTerminal` add no member to their ports at all, so their fields can be typed at the port
with nothing lost and a substituted implementation can stand in them honestly. `FakeRepository`,
`FakeVerifier` and `ManualClock` each carry the observation surface that is the whole reason the
sibling field exists - `tip`, `answers`, `advance` - so widening one of those to its port would take
away what it is for. A caller substituting one of those three builds a `Services` for a `Run` and
leaves this object alone, which is what `tests/sdk/test_run_integrate.py` does and says.

## The workflow-facing vocabulary, compiled here

Stage 16.5 built `sdk/testing.py` on top of this and already knew it "cannot name the fake's
scripting types", `sdk/` and `adapters/` being siblings: the workflow-facing scripting vocabulary
lives there in ports vocabulary, and **this module compiles it into the callable the fake
consumes**. That is `agent=` below, keyword-only beside `claude=` and `openai=` exactly as this
paragraph promised it would be, and `_performs` is the compilation - the one place allowed to name
`Conversation`, holding the whole of what a `Reply` means.

`agent=` is one parameter and not two because the vocabulary carries no vendor's name: a
`sdk.testing.Agent` dispatches on `AgentTask.model` if it cares, so one of them serves both
providers and a workflow author never writes the word Claude in a test unless their own role does.
The two raw parameters stay, and a raw script for a provider replaces the compiled one **for that
provider only** - the more specific wins, which is the one rule here and the escape hatch for a
negotiation a declarative `Reply` cannot express.

## Errors, and one refusal that is deliberately not here

`agl.ports.errors` classes only, and only two of them are raised: the two missing-extra refusals.
Everything else that could go wrong at construction is already somebody's refusal.
`RoutingAgentRunner` raises `InputError` on an empty mapping - a run assembled with no agent
backend at all - and that refusal is **not** pre-empted or duplicated here. It belongs with the
object that would have had to serve the run: it can say what it holds, its message is written where
those facts are, and a second copy here would be a second copy to drift. A bundle with both
connectors disabled therefore fails in `real()`, with routing's words.

## Deliberately not built

No lazy or cached bundle: `Resolved` is computed once at the edge and so is this, and a
module-level singleton would be a second answer to a question `sources.py` closed. No partial
bundle, no `Services | None` field, no "build me just the store" entry point - a bundle whose
fields might be absent is one every consumer narrows. No fake/real mixing knob: a bundle is one or
the other, and a caller wanting a real store under fake agents is describing an integration test
that should write the four lines itself rather than a switch every reader has to account for.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Final

from agl.adapters.claude_code import fake as claude_fake
from agl.adapters.filesystem.memory_store import MemoryStore
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.fake import (
    FakeHistory,
    FakeIntegrator,
    FakeRepository,
    FakeWorkspaceProvider,
)
from agl.adapters.git.history import GitHistory
from agl.adapters.git.integrator import GitIntegrator
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.openai import fake as openai_fake
from agl.adapters.openai.runner import OpenAiRunner
from agl.adapters.rich_terminal.headless import HeadlessTerminal
from agl.adapters.rich_terminal.scripted import Press, ScriptedTerminal
from agl.adapters.routing import RoutingAgentRunner
from agl.adapters.shell.fake import FakeVerifier
from agl.adapters.shell.verifier import ShellVerifier
from agl.adapters.system_clock import ManualClock, SystemClock
from agl.config.schema import AgentSettings, Project, Settings
from agl.ports.agent import AgentOutcome, AgentRunner, Provider, ToolResult
from agl.ports.errors import UpstreamUnavailable
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.terminal import Terminal
from agl.ports.tree_layout import TreesRoot
from agl.sdk._engine.services import Services
from agl.sdk.testing import Agent, Reply

__all__ = [
    "FAKE_BUILD",
    "FakeServices",
    "Press",
    "ScriptedTerminal",
    "Services",
    "answering",
    "fakes",
    "real",
]

# The build command a fakes bundle carries unless a caller names another, and the string a test
# scripts the gate's verdict against. A constant rather than a literal in two files, because
# `FakeVerifier` keys its script **by command** - "scripting by the thing a test can name in advance
# and hold still", as `adapters/shell/fake.py` puts it - so the bundle's value and the test's have
# to be one string or the script silently never matches and every landing passes. Deliberately not a
# runnable program: this bundle starts no process, and a value that happened to be a real command
# would be one a mistakenly-real verifier could go and run.
FAKE_BUILD: Final = "agl-fake-build"


@dataclass(frozen=True, slots=True)
class FakeServices:
    """The all-fakes bundle, plus the concrete objects a test drives it through.

    Two views of one set of instances. `services` is what a workflow, an engine or a command
    receives - port-typed, indistinguishable from `real()`'s. The rest are the *same objects*,
    named at their own types, because that is the only way to ask them anything: the ports were
    designed for the framework's needs and none of them has a "what did you write", a "what did you
    draw" or a "move time forward".

    The three git fakes are absent by design, not omission: all three are views of `repository`,
    and asserting through the repository is asserting about all of them at once.

    **Substitute through this object and never around it.** `with_terminal` and `with_store` are the
    two members below, and the module docstring argues both why they exist and why only those two
    fields have one. A `replace(harness.services, terminal=...)` reaches one of the two views and
    leaves the other naming the object it just discarded - which nothing anywhere would report.
    """

    services: Services
    """The bundle. Hand this to anything that takes a `Services` and it cannot tell."""

    repository: FakeRepository
    """The one repository behind `workspaces`, `history` and `integrator`. Shared, and the
    module docstring says why that is the invariant this class exists to make unmissable."""

    store: Store
    """The same object as `services.store`, and `with_store` is what keeps that true.

    Typed at the port rather than at `MemoryStore`, which costs nothing: that class adds no member
    to `Store` at all, so the concrete type never bought a question this one cannot answer. What it
    buys is that a caller wrapping the ledger - to watch what a run recorded, or to stop one between
    two steps, which is what `agl/testing.py` does - can put the wrapper here and have both names go
    on meaning it."""

    verifier: FakeVerifier
    """The same object as `services.verifier`. `answers()` scripts a build command's verdict.

    At its own type and with no `with_verifier` beside it, for the module docstring's reason:
    `answers` is the whole point of the field, and a `Verifier`-typed one would be a name with
    nothing to ask."""

    terminal: Terminal
    """The same object as `services.terminal`, and `with_terminal` is what keeps that true.

    Typed at the port for `store`'s reason, one field over: `HeadlessTerminal` adds no member to
    `Terminal`, so nothing is lost, and the terminal is the fake most often substituted - it refuses
    every `Screen[T]` with `UpstreamUnavailable`, correctly, so a test about a workflow that asks a
    person something has to put a terminal here that can answer. `ARCHITECTURE.md` records the
    headless terminal as doubling as the terminal's fake, and it is still what `fakes()` builds."""

    clock: ManualClock
    """The same object as `services.clock`. Exposed because target #10 - kill at every step
    boundary, resume, assert identical final state - needs time to move on purpose rather than by
    itself, and `Clock` has one member and it is a reading."""

    def with_terminal(self, terminal: Terminal) -> FakeServices:
        """This bundle with `terminal` in place of the headless one, in both views at once.

            services = harness.with_terminal(RichTerminal(console, keys)).services

        The substitution `dataclasses.replace(harness.services, terminal=...)` used to be, made
        whole: `services.terminal` and `terminal` are one object afterwards, so a test that shows a
        screen through the run and reads the terminal afterwards is reading the same one. Everything
        else is carried across unchanged and by identity - the repository the three git fakes share
        included, which is what makes the result still one bundle rather than a copy of one.

        A new object rather than a mutation, because this class is frozen for `Services`' reason: a
        bundle is what an invocation was assembled with, and a field reassigned halfway through
        would leave two halves of a run disagreeing about which terminal they were shown on.
        """
        return replace(self, services=replace(self.services, terminal=terminal), terminal=terminal)

    def with_store(self, store: Store) -> FakeServices:
        """This bundle with `store` in place of the in-memory one, in both views at once.

        `with_terminal`'s shape and its whole argument, one field over. The caller this exists for
        is `agl/testing.py`, which wraps the ledger to record what each step wrote and to stop a run
        at a step boundary - both of which are things done *to* the store the bundle already holds,
        so a wrapper that left `store` naming the object underneath it would be the exact defect
        this pair was written to close.
        """
        return replace(self, services=replace(self.services, store=store), store=store)


def real(settings: Settings, project: Project) -> Services:
    """The bundle AGL runs on: real git, a real filesystem, a real shell, real harnesses.

    Sync and eager and inert, in the module docstring's sense - every constructor below stores its
    arguments and returns. Nothing is probed, so this succeeds on a machine with no harness
    installed and no repository at `project.repo`, and preflight is where a run learns otherwise.

    The one exception to "stores its arguments and returns" is the terminal and the Claude runner,
    which may raise `UpstreamUnavailable` because their adapter could not be imported at all. That
    is an installation fact rather than a probe: no process is started and nothing is asked of the
    outside world.
    """
    return Services(
        store=FilesystemStore(settings.home),
        # A `Path` each, and each builds its own git runner from it. Three adapters over one
        # repository, because the repository is the directory - see the module docstring.
        workspaces=GitWorkspaceProvider(project.repo, project.trees),
        history=GitHistory(project.repo),
        integrator=GitIntegrator(project.repo),
        # §3.11: `build_timeout` is project configuration reaching an implementation where
        # implementations are configured, which is here, rather than a parameter on every `verify`.
        verifier=ShellVerifier(build_timeout=project.build_timeout),
        terminal=_terminal(),
        clock=SystemClock(),
        agents=_agents(settings.agents),
        # And the command that same port takes on the call instead, travelling the other way for
        # the same reason: `verify` has no timeout parameter and does have a command one, so the
        # deadline is configured into the adapter and the command has to be carried to the caller.
        # This is the last field of a `Project` to be spent, which is what `api.py` already claims
        # of the whole record when it takes the project's name and nothing else.
        build=project.build,
    )


def fakes(
    trees: TreesRoot,
    *,
    files: Mapping[str, bytes] | None = None,
    build: str = FAKE_BUILD,
    agent: Agent | None = None,
    claude: claude_fake.Script | None = None,
    openai: openai_fake.Script | None = None,
) -> FakeServices:
    """The bundle every command runs end-to-end on (target #8): no network, no git, no process.

    `trees` is where checkouts go and is the one required argument, because the workspace fakes
    make real directories under it - that is the half of a worktree a fake still has on disk.

    `files` seeds the repository's initial state, and it is a parameter here rather than something
    a caller does to `repository` afterwards because `FakeRepository`'s mutators are that package's
    private vocabulary: seeding at construction is the only way in that does not reach across an
    adapter boundary.

    `build` is what `services.build` carries: the merge gate's command, which `integrate()` hands to
    `Verifier.verify`. It defaults to `FAKE_BUILD` so that a test wanting a red gate can script
    `harness.verifier.answers(container.FAKE_BUILD, passed=False)` against a string both halves
    already agree on, and it is a parameter so that a test about a particular command *reaching* the
    gate can choose its own. There is no `build_timeout` beside it: `FakeVerifier` takes none, "a
    build that is a dict lookup cannot run past one".

    `agent` is **the workflow-facing way in** and the one most callers want: a
    `sdk.testing.Agent` is `(AgentTask) -> Reply`, named in ports vocabulary and in no vendor's, and
    it is compiled below into one script per provider. One parameter for both providers, because the
    vocabulary has no provider in it - an agent that cares which model it is serving reads
    `task.model` and says so itself.

    `claude` and `openai` are one raw script per provider - an agent's conduct, in the only
    vocabulary the port has - and are the escape hatch for what a `Reply` cannot express, a
    negotiation branching on an answer above all (`sdk/testing.py` says which cases those are). A
    raw script replaces the compiled one **for its own provider**: the more specific wins, and the
    other provider keeps whatever `agent` gave it.

    `None` everywhere means each provider's `unscripted` default, which is what lets a whole
    workflow
    run on fakes without anybody writing an agent first. All four are keyword-only.
    """
    # One repository, constructed here and handed to all three. There is no parameter through
    # which a caller could supply a second, which is the point: three separately constructed
    # fakes agree about nothing, and `adapters/git/fake.py` says stage 9 is where that lands.
    repository = FakeRepository(files)
    store = MemoryStore()
    verifier = FakeVerifier()
    terminal = HeadlessTerminal()
    clock = ManualClock()
    return FakeServices(
        services=Services(
            store=store,
            workspaces=FakeWorkspaceProvider(repository, trees),
            history=FakeHistory(repository),
            integrator=FakeIntegrator(repository),
            verifier=verifier,
            terminal=terminal,
            clock=clock,
            # Both providers, always, because a fakes bundle models an installation with
            # everything available rather than one operator's configuration - and both fakes cost
            # nothing to hold. Qualified by module on both lines: the two `FakeAgentRunner`s are
            # unrelated classes of one name, and an unqualified import would serve one twice.
            #
            # `_claude_script` and `_openai_script` are the compilation stage 7 left here: they
            # are the two functions in AGL allowed to name a `Conversation`, and each turns the
            # provider-blind `Agent` into that provider's `Script`. A raw script wins over a
            # compiled one, per provider, which is the docstring's one rule.
            agents=RoutingAgentRunner(
                {
                    Provider.CLAUDE: claude_fake.FakeAgentRunner(
                        claude if claude is not None else _claude_script(agent)
                    ),
                    Provider.OPENAI: openai_fake.FakeAgentRunner(
                        openai if openai is not None else _openai_script(agent)
                    ),
                }
            ),
            build=build,
        ),
        repository=repository,
        store=store,
        verifier=verifier,
        terminal=terminal,
        clock=clock,
    )


def answering(responses: Sequence[Press | int] = ()) -> ScriptedTerminal:
    """The `Terminal` a test answers: `responses`, spent in order on whatever screen is in front.

        fakes = container.fakes(trees).with_terminal(container.answering([0, Press(1, "later")]))

    The third terminal AGL constructs, and the one a workflow author reaches - through
    `agl.testing.answering`, which is this function under the name an author writes. It is here
    because it says `new` and contract 5 gives that to no other module: `agl/testing.py` sits two
    layers above `agl.adapters` and may not name one, so a factory here is what carries the class up
    to it. One line, and it takes no decision - `adapters/rich_terminal/scripted.py` argues the
    whole design, including the one trap, which is that a question with no response left waits
    rather than failing.

    **A bare `int` means `Press(int)`**, coerced by the class itself for `ports/terminal.py`'s
    reason - one rule, applied on the way in - so `answering([0, 0])` is two approvals.

    The concrete type comes back rather than a `Terminal`, which is the opposite of `_terminal()`
    below and is deliberate: `remaining`, `displayed()` and `slot()` are the whole reason a test
    holds this object, and a port-typed return would hand the caller a terminal it could show
    screens on and ask nothing. It is still a `Terminal` wherever one is wanted, `with_terminal`
    included.
    """
    return ScriptedTerminal(responses)


def _claude_script(agent: Agent | None) -> claude_fake.Script | None:
    """`agent` as the callable Claude Code's fake consumes, or `None` for its own default.

    Half of the compilation stage 7 named this module for. `adapters/claude_code/fake.py` states
    the constraint in as many words - `sdk/` and `adapters/` are siblings, so the vocabulary module
    "cannot name `Script` or `Conversation` at all", and "the composition root can name both". So
    the two spellings of this function are the seam, and everything they do is in `_performs`.

    Two functions rather than one generic over the conversation type, because the two
    `Conversation` classes are unrelated by construction: contract 4 forbids one adapter importing
    another, so there is no base class and no protocol either of them was written against, and a
    parameter typed as one of them would silently serve that vendor's fake under both keys - which
    is the failure `tests/config/test_container.py` already asks each provider a question only its
    own script can answer to catch.
    """
    if agent is None:
        return None

    async def script(conversation: claude_fake.Conversation) -> AgentOutcome:
        return await _performs(
            agent(conversation.task),
            ask=conversation.ask,
            call=conversation.call,
            report=conversation.report,
        )

    return script


def _openai_script(agent: Agent | None) -> openai_fake.Script | None:
    """`agent` as the callable the OpenAI adapter's fake consumes, or `None` for its own default.

    `_claude_script`'s other half, and its whole argument. The two bodies are the same three lines
    on two unrelated types.
    """
    if agent is None:
        return None

    async def script(conversation: openai_fake.Conversation) -> AgentOutcome:
        return await _performs(
            agent(conversation.task),
            ask=conversation.ask,
            call=conversation.call,
            report=conversation.report,
        )

    return script


async def _performs(
    reply: Reply,
    *,
    ask: Callable[[Question], Awaitable[Answer | None]],
    call: Callable[[str, Mapping[str, JsonValue]], Awaitable[ToolResult]],
    report: Callable[[str], None],
) -> AgentOutcome:
    """Do what `reply` describes, through the three things a `Conversation` offers, and answer.

    **The whole of what a `Reply` means, in one place and in the order `sdk/testing.py` documents**:
    every activity line, then every question, then every call, then the outcome. Written once and
    handed the three bound methods rather than the conversation itself, because that is the one
    shape both vendors' `Conversation` can be passed to - see `_claude_script` for why there is no
    type either of them shares.

    **What comes back from `ask` and from `call` is deliberately dropped here.** A `Reply` is a
    value the author computed before the run and it has nowhere to put an answer, which is the
    limitation `sdk/testing.py` states plainly rather than works around: an agent whose next move
    depends on what it was told is a raw `claude=` or `openai=` script. Neither result is thrown
    away in any sense that matters, either - the answer went to the workflow's own handler and the
    refusal to the workflow's own tool, and both of those are the author's code.
    """
    for line in reply.activity:
        report(line)
    for question in reply.asks:
        await ask(question)
    for made in reply.calls:
        await call(made.tool, made.payload)
    return AgentOutcome(stop_reason=reply.stop_reason, text=reply.says)


def _agents(agents: AgentSettings) -> AgentRunner:
    """The routing runner, holding one adapter per *enabled* connector and nothing else.

    The table is R2's whole physical footprint (see the module docstring): one row per provider,
    and a third backend is a third row. Enabled is read from configuration and availability is not
    read at all - §3.2.1's two questions, and only the first one is answerable here.

    Construction is deferred into a `partial` so that a disabled connector is never built, which
    for Claude means its module is never imported - the difference between an operator who does not
    use that backend and an operator who cannot start AGL without it.

    An empty mapping is left to `RoutingAgentRunner`, which already refuses it with a message
    naming what a run was assembled with. Checking for it here would be a second refusal for one
    mistake, written where fewer of the facts are.
    """
    connectors: tuple[tuple[Provider, bool, Callable[[], AgentRunner]], ...] = (
        (Provider.CLAUDE, agents.claude.enabled, partial(_claude, agents.claude.cli_path)),
        (Provider.OPENAI, agents.openai.enabled, partial(OpenAiRunner, agents.openai.cli_path)),
    )
    return RoutingAgentRunner({name: build() for name, enabled, build in connectors if enabled})


def _claude(cli_path: Path | None) -> AgentRunner:
    """`ClaudeCodeRunner`, or `UpstreamUnavailable` naming the extra that would provide it.

    Imported here and not at the top of the file: `adapters/claude_code/runner.py` imports its
    vendor SDK at module level, so on an installation without `agl[claude]` the import itself
    raises - and a module-level import would take down `agl workflows` on a machine that never
    meant to run this backend.
    """
    try:
        from agl.adapters.claude_code.runner import ClaudeCodeRunner
    except ImportError as error:
        raise UpstreamUnavailable(
            "the Claude connector is enabled, but its harness cannot be loaded in this "
            "environment: the adapter needs the claude-agent-sdk package, which arrives with a "
            "pip extra that is not installed. Install it with `pip install 'agl[claude]'`, or "
            "turn the connector off - AGL_AGENT_CLAUDE_ENABLED=false, or enabled = false under "
            "[agent.claude] in the settings file - and run a workflow whose roles name no Claude "
            "model"
        ) from error
    return ClaudeCodeRunner(cli_path)


def _terminal() -> Terminal:
    """`RichTerminal`, or `UpstreamUnavailable` naming the extra that would provide it.

    There is no second branch and no setting that would produce one. §3.11 refuses display
    selection, and falling back to `HeadlessTerminal` would trade one line of installation advice
    for a run that dies an hour later on the first screen that asks a person something - see the
    module docstring, which argues that at length because it is the plausible mistake.
    """
    try:
        from agl.adapters.rich_terminal.terminal import RichTerminal
    except ImportError as error:
        raise UpstreamUnavailable(
            "AGL cannot build a terminal in this environment: the display adapter needs the rich "
            "package, which arrives with a pip extra that is not installed. Install it with `pip "
            "install 'agl[terminal]'`. There is no headless mode to fall back to - a workflow "
            "shows screens and some of them ask a person a question, so a run started without a "
            "display would fail at the first one instead of here"
        ) from error
    return RichTerminal()
