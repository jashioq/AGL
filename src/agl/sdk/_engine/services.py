"""`Services` - every port AGL needs, filled in, in the one object a `Run` carries.

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

The construction stays where it was, and that is not a compromise. The type is eight ABCs; the
construction is eight class names, which is the one thing only the composition root may write.
Splitting them along exactly that line is what makes the move a move.

## Why not `ports/`

`ARCHITECTURE.md` §6 gives that layer one admission rule - "it's an ABC, or a type an ABC speaks" -
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
terminal, clock, agents)`, and the cost of it is measured in what a ninth port does. With a bundle,
adding one is a field here and a line in `container.real` and `container.fakes`. Without one, it is
every construction site: `api.py`, each of `cli/commands/`, `sdk/testing.py`, and every test that
drives a workflow - none of which mention that port or want to. The bundle is what keeps "add a
port" proportional to the port rather than to the number of places a `Run` is built.

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
    """Every port AGL needs, filled in. The bundle everything above the edge is handed.

    **Every field is typed as a port ABC and not one of them as an adapter**, which is the whole
    point of the type rather than a convention it happens to follow: a consumer of this object
    cannot tell `GitHistory` from `FakeHistory`, cannot narrow to one, and cannot grow a branch on
    which implementation it got. That is what makes `container.fakes()` a deployment instead of a
    mock, and what makes contract 5 enforceable - a field typed `FilesystemStore` would put an
    adapter's name in every module that reads the bundle.

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
