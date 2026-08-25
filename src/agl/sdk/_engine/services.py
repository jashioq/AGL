"""`Services` - every port AGL needs, filled in, in the one object a `Run` carries - and one string.

Stage 9 built this class inside `config/container.py`, and built it as a plain frozen dataclass
over port ABCs precisely so that arriving here would be a **move rather than a rewrite**: nothing
in it names an adapter, nothing in it has behaviour, so the type can sit under `sdk/` while the
only module allowed to say `new` goes on constructing it. `docs/agl-build-stages.md` records that
decision against deliverable 10.2. This file is where it lands, and `container.py` keeps building
it and re-exports the name.

## Why `sdk/` and not `config/`, where it was written

`Run.services` has to be annotated with this type, and `Run` is `sdk/workflow.py`. Contract 1 puts
`sdk` below `config`, so `config` may import `sdk` and never the reverse: a `Services` defined in
`config/container.py` and named in `sdk/workflow.py` is the layer stack inverted, and
`lint-imports` says so rather than a reviewer. Moving the type costs the composition root one
import line and keeps the arrow pointing the one direction it may point.

The construction stays where it was, and that is not a compromise. The type is eight ABCs and a
`str`; the construction is eight class names and one field off the project's record, which is the
one thing only the composition root may write. Splitting them along exactly that line is what makes
the move a move.

## Why not `ports/`

`ARCHITECTURE.md` §1 gives that layer one admission rule - "it's an ABC, or a type an ABC speaks" -
and a bundle of ABCs is neither. No port method takes or returns a `Services`; nothing implements
it; it is not vocabulary any capability speaks. It describes AGL's own wiring, which is a fact
about this framework rather than about anything it asks the outside world to do.

That is not only a reading of a table. `.importlinter`'s contract 2 splits `ports/` into pure types
(`source_modules`) and the ABCs that speak them (`forbidden_modules`), and
`tests/test_contract_listings.py` requires every module in that package on **exactly one** of the
two lists. A `ports/services.py` could go on neither: it imports eight ABCs, so it is not a pure
type, and it is not an ABC, so no pure type needs protecting from it. A module the enforcement
cannot place is a module in the wrong ring.

## Why not eight loose parameters

The alternative to a bundle is `Run(params, store, workspaces, history, integrator, verifier,
terminal, clock, agents)`, and the cost of it is measured in what one more field does. With a
bundle, adding one is a field here and a line in `container.real` and `container.fakes`. Without
one, it is every construction site: `api.py`, each of `cli/commands/`, `agl/testing.py`, and every
test that drives a workflow - none of which mention that port or want to. The bundle is what keeps
"add a port" proportional to the port rather than to the number of places a `Run` is built. 14.0
spent that exactly once, on `build`, and it cost the two lines the paragraph promises.

## The ninth field is not a port, and it is here because the plan leaves it nowhere else

`Verifier.verify(command, workdir)` takes the build command **as a parameter**, and its docstring
makes it "exactly as the user wrote it in the project's settings". §3.4 gives that method one call
site: the merge gate inside `integrate()`, which is `sdk/_engine/`. So something above the edge has
to be holding the command - and until 14.0 nothing could. This bundle carried only ports, §3.11
refuses `run.project` as an accessor, and `api.run` takes the project's *name* rather than its
record, on the argument that "the rest of a `Project` ... has already been spent by the container".
For `build` that sentence was not yet true; this field is what makes it true.

§3.11 settles the sibling case in the other direction and the asymmetry is the whole of the
argument: `build_timeout` reaches `ShellVerifier` at construction, "where implementations are
configured", **because** `verify` has no timeout parameter and "a hosted verifier with its own
deadline would carry an argument it could only ignore". The command is the same configuration
travelling the opposite way - the port requires the caller to hold it - and the plan is silent about
where it travels. The alternatives are each refused somewhere else already, and the field's own
docstring names them.

The claim this file used to make is narrowed rather than dropped. "Every field is typed as a port
ABC and not one of them as an adapter" was always about not naming an adapter, and a `str` the user
typed names none; what stops being true is only that the class is ports and nothing else.

It buys a second thing, which is that substituting every implementation at once is one argument.
That is measurable target #8 - every command runs end-to-end on fakes alone - and it is why
`container.fakes()` is a deployment rather than a fixture.

## Why `_engine/` and not the SDK surface proper

A workflow author never names this type. They write `async def fix(run: Run) -> None` and reach the
ports through the members `Run` grows at stages 11 to 13 - `run.step` dispatches to `agents`,
`run.integrate` runs `verifier`, `run.terminal` is `terminal`. The bundle is the plumbing behind
those members, and `sdk/_engine/` is where this package keeps plumbing: "not part of the surface a
workflow author imports", as its `__init__` says. Putting it in `sdk/` proper would advertise it as
something to import, and the first workflow to reach past `run.step` into `run.services.store` is
writing to the ledger the framework owns.

## No behaviour, deliberately

No methods, no `Services.default()`, no `with_store()`, no `Services | None` field. Every one of
those would be a second place that knows how a bundle is assembled, and `container.py` argues at
length that a composition root nobody ever edits is one whose decisions have leaked somewhere else.
This module holds a shape and nothing that could make a decision.
"""

from dataclasses import dataclass

from agl.ports.agent import AgentRunner
from agl.ports.clock import Clock
from agl.ports.history import History
from agl.ports.integration import Integrator
from agl.ports.store import Store
from agl.ports.terminal import Terminal
from agl.ports.verifier import Verifier
from agl.ports.workspace import WorkspaceProvider

__all__ = ["Services"]


@dataclass(frozen=True, slots=True)
class Services:
    """Every port AGL needs, filled in, and the one project setting a port makes its caller hold.

    Eight ABCs and a string. The eight are the bundle proper; the ninth is `build`, which is here
    because `Verifier.verify` takes the build command as a parameter and the only thing that calls
    it lives above the edge - see the field, and the module docstring for what the alternatives
    cost.

    **Every field that is a port is typed as a port ABC and not one of them as an adapter**, which
    is the whole point of the type rather than a convention it happens to follow: a consumer of this
    object cannot tell `GitHistory` from `FakeHistory`, cannot narrow to one, and cannot grow a
    branch on which implementation it got. That is what makes `container.fakes()` a deployment
    instead of a mock, and what makes contract 5 enforceable - a field typed `FilesystemStore` would
    put an adapter's name in every module that reads the bundle. `build` is not an exception being
    made to that rule: it is configuration rather than a capability, so there is no implementation
    of it for a consumer to narrow to and nothing about it a workflow could branch on.

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

    build: str
    """The merge gate's build command - `Project.build`, exactly as the user wrote it.

    **The one field here that is not a port**, and the only piece of project configuration with a
    call site above the edge. `verifier` is the capability and this is the argument that capability
    cannot be exercised without: `Verifier.verify(command, workdir)` puts the command on the call,
    §3.4 gives it one caller, and that caller is `integrate()` inside `sdk/`. Nothing else in a
    `Project` is in that position - `repo` and `trees` are spent building the git adapters,
    `build_timeout` is spent constructing the verifier, and `name` is the run's address - so this is
    the only string that has to travel and the bundle is the only thing that travels.

    The alternatives were each refused somewhere else first. A field on `Run` would be a seventh
    member of §3.3's six, handing every workflow author the project's build command to interpolate
    into a prompt - which §3.2.1 says is a *different* command, "written literally into prompts,
    hand-tuned per project", and two commands under one name is the confusion `Project`'s own
    docstring exists to head off. A field on `RunSpec` would put it in `run.json`, where it becomes
    a stored format compared on resume, for a value that is configuration and may honestly differ
    between two invocations of one run. A second bundle beside this one - "the project, minus the
    parts §3.11 refuses" - is `run.project` under another name, and §3.11 refuses that by name.

    Not validated here. `Project.__post_init__` already refuses a blank one, on the argument that a
    blank command "would make every run's gate pass without building anything", and a second copy of
    that check would be a second copy to drift. Nothing below the edge parses it, splits it or asks
    whether the program in it exists; the adapter that owns that decision is the one that runs it.
    """
