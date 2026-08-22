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

## The hand-off, and the shape stage 16.5 needs

`fakes()` returns a `FakeServices`, which carries the port-typed `Services` a workflow runs on
*and* the concrete fakes a test drives. Both halves are needed and neither substitutes for the
other: the bundle is deliberately port-typed so nothing above can tell it from the real one, which
is precisely what makes it useless for asserting anything - a `Store` has no "what did you write",
a `Terminal` has no "what did you draw". The concrete objects beside it are the same instances, and
they are the only ones a test can ask.

The agent runners are the exception and are not exposed, because their input is the argument: a
caller passes a `Script` per provider and reads what happened through the repository, the store and
the terminal. That keeps the direction honest - scripting is a thing done before the run, and there
is no recorder on any fake for a test to read afterwards, which `adapters/shell/fake.py` argues at
length.

Stage 16.5 builds `sdk/testing.py` on top of this and already knows it "cannot name the fake's
scripting types", `sdk/` and `adapters/` being siblings: a workflow-facing scripting vocabulary
lives there in ports vocabulary, and this module compiles it into the callable the fake consumes.
The shape left for that is a keyword-only, per-provider script parameter - a differently typed
parameter can be added beside `claude=` and `openai=` without moving anything, and the compilation
step has a place to stand that is already allowed to name `Conversation`.

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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path

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
from agl.adapters.routing import RoutingAgentRunner
from agl.adapters.shell.fake import FakeVerifier
from agl.adapters.shell.verifier import ShellVerifier
from agl.adapters.system_clock import ManualClock, SystemClock
from agl.config.schema import AgentSettings, Project, Settings
from agl.ports.agent import AgentRunner, Provider
from agl.ports.clock import Clock
from agl.ports.errors import UpstreamUnavailable
from agl.ports.history import History
from agl.ports.integration import Integrator
from agl.ports.store import Store
from agl.ports.terminal import Terminal
from agl.ports.tree_layout import TreesRoot
from agl.ports.verifier import Verifier
from agl.ports.workspace import WorkspaceProvider

__all__ = ["FakeServices", "Services", "fakes", "real"]


@dataclass(frozen=True, slots=True)
class Services:
    """Every port AGL needs, filled in. The bundle everything above the edge is handed.

    **Every field is typed as a port ABC and not one of them as an adapter**, which is the whole
    point of the type rather than a convention it happens to follow: a consumer of this object
    cannot tell `GitHistory` from `FakeHistory`, cannot narrow to one, and cannot grow a branch on
    which implementation it got. That is what makes `fakes()` a deployment instead of a mock, and
    what makes contract 5 enforceable - a field typed `FilesystemStore` would put an adapter's name
    in every module that reads the bundle.

    Frozen, because a bundle is what this invocation was assembled with and reassigning a field
    halfway through a run would leave two halves of a workflow talking to different stores.
    """

    store: Store
    """Run records and step entries (§3.6). Under `AGL_HOME`, never in the target repository."""

    workspaces: WorkspaceProvider
    """Isolated places to work, and taking them back."""

    history: History
    """What changed and what contains what, over the target repository. Not a run log."""

    integrator: Integrator
    """Landing a workspace into a target, or saying why it would not go."""

    verifier: Verifier
    """The merge gate's build. One call site, inside integration."""

    terminal: Terminal
    """The surface a workflow shows screens on. There is no second display and no selection."""

    clock: Clock
    """The only source of the current time, so that a run's record is reproducible."""

    agents: AgentRunner
    """One runner over every configured provider. A `RoutingAgentRunner` in both bundles, which
    nothing above can see or should: a workflow names a model and never learns what served it."""


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
    """

    services: Services
    """The bundle. Hand this to anything that takes a `Services` and it cannot tell."""

    repository: FakeRepository
    """The one repository behind `workspaces`, `history` and `integrator`. Shared, and the
    module docstring says why that is the invariant this class exists to make unmissable."""

    store: MemoryStore
    """The same object as `services.store`, at the type that can be read back."""

    verifier: FakeVerifier
    """The same object as `services.verifier`. `answers()` scripts a build command's verdict."""

    terminal: HeadlessTerminal
    """The same object as `services.terminal`. `ARCHITECTURE.md` records the headless terminal as
    doubling as the terminal's fake, so there is no third implementation to reach for here."""

    clock: ManualClock
    """The same object as `services.clock`. Exposed because target #10 - kill at every step
    boundary, resume, assert identical final state - needs time to move on purpose rather than by
    itself, and `Clock` has one member and it is a reading."""


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
    )


def fakes(
    trees: TreesRoot,
    *,
    files: Mapping[str, bytes] | None = None,
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

    `claude` and `openai` are one script per provider - an agent's conduct, in the only vocabulary
    the port has - and `None` on either means that provider's `unscripted` default, which is what
    lets a whole workflow run on fakes without anybody writing an agent first. Keyword-only, so
    stage 16.5's workflow-level scripting vocabulary can arrive beside them.
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
            agents=RoutingAgentRunner(
                {
                    Provider.CLAUDE: claude_fake.FakeAgentRunner(claude),
                    Provider.OPENAI: openai_fake.FakeAgentRunner(openai),
                }
            ),
        ),
        repository=repository,
        store=store,
        verifier=verifier,
        terminal=terminal,
        clock=clock,
    )


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
