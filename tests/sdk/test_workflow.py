"""What §3.3's authoring model promises at stage 10: a decorated async function, and a typed `Run`.

Four properties carry this suite.

**The narrowing `registry.load` performs is driven end to end**, through a hand-constructed
`EntryPoint` pointing at this module - §3.3's registration line, resolved - because that is the
whole reason this class exists. `config/registry.py` deferred nominal narrowing to "the object
`@workflow` produces in `sdk/workflow.py`", so the pair is asserted together: a `Workflow` loads,
and something that is not one is refused with the registry's `InputError` rather than reaching
`api.py` as an `Any`.

**The typing promise is asserted at the type level**, with `assert_type` rather than a runtime
check, because §3.3's claim is about what *mypy* knows: `run.params.concurrent` is an `int`. A
runtime assertion would pass against a `Run` that had erased its params to `object`, which is
precisely the version of this module worth catching. `mypy --strict` runs over `tests/` too, so
these are gates and not documentation. Both spellings §3.3 writes are pinned - `Run[TicketsParams]`
for a workflow that reads its parameters and a bare `Run` for one that does not.

**Every refusal is an `InputError`**, asserted on the class and on the part of the message a reader
acts on next. `@workflow`'s three argument checks run when the decorator is *built*, before it is
applied, and the async check when it is applied - both at import time, where a package that cannot
be invoked correctly should fail.

**`Stop` is asserted to be the same class object**, not merely a compatible one. A copy would
satisfy `except Stop` inside a workflow, resolve to 7 through `exit_code_for`, and then fail to be
caught by the CLI's handler, which imports the other one - a divergence with no symptom until a
deliberate end is reported as a crash.
"""

import sys
from collections.abc import Awaitable
from dataclasses import dataclass, fields
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final, assert_type

import pytest

from agl.config import container, registry
from agl.ports import errors
from agl.ports.agent import Claude, OpenAI
from agl.ports.errors import AglError, InputError, exit_code_for
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.sdk._engine.journal import Fingerprints
from agl.sdk._engine.services import Services
from agl.sdk.params import arg, parse
from agl.sdk.roles import Role, RoleFactory, role
from agl.sdk.tools import reporting_tool
from agl.sdk.workflow import Run, Stop, Workflow, workflow

# Where a run's records go and the commit its chain starts at. Nothing in this file takes a step,
# so neither is ever spent; `tests/sdk/test_run_step.py` is where they are.
SCOPE: Final = RunScope(ProjectName("myapp"), RunLabel("auth"))
BASE: Final = "4a91c07f2b3e8d15c6a0f31d8e2b47c9a6013f5e"

# `asyncio_mode = "strict"` turns a missing marker into a test pytest silently skips, so every
# async test below carries `@pytest.mark.asyncio` of its own.


@dataclass(frozen=True)
class TicketsParams:
    """Plan §3.3's example, copied rather than adapted - the same one `test_params.py` parses."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing - `noop` at 10.5, and the params class it still needs."""


# What `tickets` was handed, so that a test can assert about the `Run` the framework passed rather
# than about one it built itself. A list at module level because the workflow has to be one too:
# `EntryPoint.load` imports a module and reads an attribute in it, and cannot see a local.
_handed: Final[list[Run[TicketsParams]]] = []


@workflow(name="tickets", version="1.1", params=TicketsParams)
async def tickets(run: Run[TicketsParams]) -> None:
    """§3.3's typed spelling. The two `assert_type` calls are this suite's real subject: they are
    checked by `mypy --strict` over `tests/`, and neither survives a `Run` that erased its
    params."""
    assert_type(run.params, TicketsParams)
    assert_type(run.params.concurrent, int)
    _handed.append(run)


@workflow(name="fix", version="1.1", params=NoParams)
async def fix(run: Run) -> None:
    """§3.3's `fix` example writes a bare `Run`, and this is that signature literally. It compiles
    only because `Run`'s type parameter has a PEP 696 default - `disallow_any_generics` is on - and
    the default being `object` rather than `Any` is what makes the line below an error to remove."""
    assert_type(run.params, object)


@dataclass(frozen=True)
class Findings:
    """A reporting payload, so that one of the two roles below is a `Role[Findings]` and the other
    a `Role[None]` - which is what makes the widening to `Role[object]` a real question."""

    high: int


# §3.2's motivating pair: one model per provider, in one workflow. Two `@role(model=…)` factories,
# which is what §3.3 says a role declaration is - the model is on the decorator, where preflight can
# read it without calling anything, and the `Role` is what the call below produces. Since UF1.3
# these two names being bound *in this module* is the whole of what makes them the workflow below's
# roles: there is no list on the decorator, and the namespace is the registry.


@role(model=Claude.OPUS)
def implementer() -> Role:
    """An effect role, so that the pair below is one `Role[None]` and one `Role[Findings]`."""
    return Role(name="implement", instructions="implement it")


@role(model=OpenAI.SOL)
def reviewer() -> Role[Findings]:
    """The second provider, and the reporting half of the pair."""
    return Role(
        name="review",
        instructions="review it",
        tools=[reporting_tool("report_findings", "report what you found", Findings)],
    )


@workflow(name="staffed", version="1.1", params=NoParams)
async def staffed(run: Run[NoParams]) -> None:
    """A workflow written beside two role factories and declaring neither, because since UF1.3
    there is nothing to declare: the two names above are bound in this module, and the module is
    what preflight reads. Nothing runs it here - `tests/sdk/test_preflight.py` is where the
    namespace is spent."""


# The load that succeeds into the wrong type. `test_registry.py` uses a string for this too.
_not_a_workflow = "a workflow name is not a workflow"


def _returns_an_awaitable(run: Run[NoParams]) -> Awaitable[None]:
    """A plain function satisfying `Callable[[Run[P]], Awaitable[None]]` and never yielding to the
    event loop. It type-checks as a workflow's function exactly, which is why the check that
    refuses it has to be at runtime."""
    raise AssertionError("`@workflow` refuses this before anything can call it")


def _services(tmp_path: Path) -> Services:
    """A bundle from the composition root, on fakes - target #8's, and the only honest way to fill
    eight fields typed as port ABCs. `run.step` is what reads it, and reads it lazily: no port
    below is touched by building a `Run` or by any test in this file."""
    return container.fakes(TreesRoot(tmp_path / "trees")).services


def _run[P](params: P, tmp_path: Path, *, fingerprints: Fingerprints | None = None) -> Run[P]:
    """A `Run` over a fakes bundle at a fixed scope and base.

    `fingerprints` is spelled out rather than defaulted through, because the one test below that
    supplies its own is testing exactly that it can - that is 13.1's seam.
    """
    return Run(
        params=params,
        services=_services(tmp_path),
        scope=SCOPE,
        base=BASE,
        fingerprints=Fingerprints() if fingerprints is None else fingerprints,
    )


def _point(name: str, attribute: str) -> EntryPoint:
    """§3.3's `tickets = "agl.workflows.tickets:tickets"`, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)


# --- what the decorator produces ---------------------------------------------------------------


def test_a_decorated_async_function_is_a_workflow_object() -> None:
    """The decorated name *is* the entry point's target, so it has to be the `Workflow` itself."""
    assert isinstance(tickets, Workflow)
    assert_type(tickets, Workflow[TicketsParams])
    assert (tickets.name, tickets.version, tickets.params) == ("tickets", "1.1", TicketsParams)


def test_the_decorator_holds_the_function_unwrapped() -> None:
    """`api.py` awaits this. Nothing is wrapped around it, so a traceback names the workflow."""
    assert tickets.fn.__qualname__ == "tickets"


# --- what the decorator no longer takes, and where preflight looks instead -----------------------


def test_a_workflow_holds_four_facts_and_every_one_of_them_is_about_the_function() -> None:
    """UF1.3's whole content, read off the class rather than off its prose.

    16.1's `roles` field was the one member here that was not a fact about `fn`, and it existed
    because §3.2's preflight had no other way to see a role before a run started: roles are built
    inside the workflow's own body, so nothing at decoration time could enumerate them. UF1.2
    dissolved that - a role is a `@role(model=…)` factory carrying its model on the object bound at
    import - and this is the line that says the field went with it.

    Over `dataclasses.fields` and not over three `hasattr`s, so that a *fifth* member arriving here
    fails this test rather than passing it silently."""
    assert [held.name for held in fields(Workflow)] == ["name", "version", "params", "fn"]


def test_the_registry_preflight_reads_is_the_module_the_function_was_written_in() -> None:
    """What replaced the declaration, asserted as a namespace rather than argued as prose.

    `preflight.check` is handed `wf.fn` and reads the `RoleFactory` values in
    `vars(sys.modules[fn.__module__])` - so the *import line above a workflow is its declaration*,
    and this test fails if the two factories declared beside `staffed` ever stop being visible to
    it. §3.11: "One declaration, not two."

    It over-approximates by construction and that is the accepted cost: `staffed` steps with
    neither factory and both models are demanded all the same. `tests/sdk/test_preflight.py`
    measures what that costs a run; what is measured here is only the shape."""
    bound = {
        name: found.model
        for name, found in vars(sys.modules[staffed.fn.__module__]).items()
        if isinstance(found, RoleFactory)
    }
    assert bound == {"implementer": Claude.OPUS, "reviewer": OpenAI.SOL}


# --- the narrowing `registry.load` performs ----------------------------------------------------


def test_the_registry_narrows_a_loaded_entry_point_to_this_class() -> None:
    """The exact `isinstance` `config/registry.py` defers to this deliverable, driven for real."""
    loaded: Workflow[object] = registry.load([_point("tickets", "tickets")], "tickets", Workflow)
    assert loaded is tickets


def test_something_that_is_not_a_workflow_is_refused_with_the_registrys_input_error() -> None:
    """The hole `Workflow` exists to close: an entry point that loads and is the wrong thing.

    A `runtime_checkable` `Protocol` would have let anything carrying the right attribute names
    through, which is `config/registry.py`'s argument for wanting a real class to narrow to.
    """
    with pytest.raises(InputError, match=r"agl\.sdk\.workflow\.Workflow"):
        registry.load([_point("tickets", "_not_a_workflow")], "tickets", Workflow)


@pytest.mark.asyncio
async def test_the_chain_api_py_will_write_carries_no_any(tmp_path: Path) -> None:
    """Registry to params to `Run` to the call, pinned at the type level while it is cheap to.

    `Workflow[object]` is the annotation that converts the `Workflow[Any]` mypy infers for a bare
    generic class in `type[T]` position; passing `Workflow[object]` as `kind` instead is not
    available, `isinstance` refusing a subscripted generic. Everything downstream then follows at
    `object`, which is the honest type for "some workflow's params, and this code does not care".
    """
    wf: Workflow[object] = registry.load([_point("fix", "fix")], "fix", Workflow)
    assert_type(wf.params, type[object])
    params = parse(wf.params, [])
    assert_type(params, object)
    run = _run(params, tmp_path)
    assert_type(run, Run[object])
    await wf.fn(run)
    assert run.params == NoParams()


# --- `run.params`, and the bundle beside it ----------------------------------------------------


@pytest.mark.asyncio
async def test_the_run_carries_the_params_instance_the_workflow_declared(tmp_path: Path) -> None:
    """`agl run tickets -n auth -r "add oauth" -c 4`, from the parse to what the workflow reads."""
    _handed.clear()
    params = parse(TicketsParams, ["-r", "add oauth", "-c", "4"])
    run = _run(params, tmp_path)
    assert_type(run, Run[TicketsParams])
    await tickets.fn(run)
    assert _handed == [run]
    assert _handed[0].params == TicketsParams(request="add oauth", concurrent=4)


def test_the_run_carries_the_bundle_the_container_built(tmp_path: Path) -> None:
    """The same object, not a copy: `run.step` reaches every port through this, so a `Run` holding
    a bundle assembled elsewhere would be a workflow writing to a second ledger."""
    services = _services(tmp_path)
    assert Run(params=NoParams(), services=services, scope=SCOPE, base=BASE).services is services


def test_the_run_carries_the_address_and_the_base_api_py_already_computed(tmp_path: Path) -> None:
    """`scope` and `base` are `api.run`'s two locals, handed over rather than re-derived. Both are
    read on the first step - the address an entry is written under, and the commit the chain starts
    at - and neither is reachable from anything else a `Run` holds."""
    run = _run(NoParams(), tmp_path)
    assert (run.scope, run.base) == (SCOPE, BASE)


def test_a_run_can_be_handed_the_counter_a_parent_is_already_using(tmp_path: Path) -> None:
    """13.1's seam, still pinned here where it is cheapest to.

    §3.6 scopes `n` per `(namespace, step name)`, which only means anything if every namespace in a
    run counts against one object. `run.worktree()` is what passes it - `test_run_worktree.py`
    asserts that it passes *this* object - and what this asserts is that there is a way in at all,
    because a counter built privately in `__post_init__` would look identical at stage 12, where a
    run has one namespace, and would be rule 1's fix silently removed the moment a child was cut.
    """
    counter = Fingerprints()
    assert _run(NoParams(), tmp_path, fingerprints=counter).fingerprints is counter


def test_a_run_holds_nothing_it_did_not_declare(tmp_path: Path) -> None:
    """Slotted, so the surface is the fields below, and an attribute a caller attached to a `Run`
    would be one more that nobody declared and that replay would never see.

    15.1 added §3.3's sixth member and this tuple did not move, which is the shape of that decision
    rather than an oversight: `terminal` is a property over `services.terminal` and not a field, so
    a `Run` still holds exactly what it was assembled with.
    `tests/sdk/test_run_terminal.py` asserts the other half - it reads the bundle's own object.

    `worktrees` joined the list at 13.1, beside `fingerprints` and for its reason: it is the run's
    table of taken namespaces (§3.9), defaulted for the root and handed on to every child, so it is
    a constructor keyword rather than something `__post_init__` builds.

    `leases` joined at 14.1 and is the third of exactly the same shape: §3.4's lease per integration
    target, run-wide, defaulted for the root and handed on by `_child`. It is a constructor keyword
    for one reason the other two do not have - `api.run` releases it in a `finally` around the
    workflow's function, so the composition root has to be holding the object the run was built
    with.

    `capabilities` joined at 16.1 and is the fourth of that shape: §3.2's record of what each
    model's backend reported, asked once per model per run because `capabilities()` is contracted
    stable for the duration of one. It is the only one of the four where sharing is an economy
    rather than the mechanism - a second table merely re-asks - which is why it is also the only one
    a directly-built `Run` can default with nothing arranged.

    `_parent` joined at 14.0 and is the link `integrate()` walks to reach the namespace a child's
    work lands into. A keyword like the three above, defaulted `None` - which is how a root says it
    is a root - and set by `_child` alone. Private, because §3.3's surface is six members and a
    public one would hand a workflow author a tree to walk.

    `_steps` is the engine `step` delegates to, derived in `__post_init__` from the public fields -
    `Entry` sets its own derived field the same way - and it is deliberately not a constructor
    argument: a caller free to supply one could hand a `Run` an engine addressing another
    namespace's checkout.
    """
    assert Run.__slots__ == (
        "params",
        "services",
        "scope",
        "base",
        "fingerprints",
        "worktrees",
        "leases",
        "capabilities",
        "_parent",
        "_steps",
    )
    with pytest.raises(TypeError, match="_steps"):
        Run(
            params=NoParams(),
            services=_services(tmp_path),
            scope=SCOPE,
            base=BASE,
            _steps=None,  # type: ignore[call-arg]
        )


# --- `Stop`, and the ordering hazard it comes with ---------------------------------------------


class ReviewNotConverging(Stop):
    """§3.1's own example of a workflow's reason, declared against the SDK's import of `Stop`."""


def test_stop_imported_from_the_sdk_is_the_ports_class_itself() -> None:
    """The same class object, not a compatible copy - see this module's docstring for the cost."""
    assert Stop is errors.Stop


def test_a_workflows_own_stop_subclass_resolves_to_seven() -> None:
    """`exit_code_for` walks the MRO, so a reason the framework never heard of exits 7 anyway."""
    assert exit_code_for(ReviewNotConverging("the reviewer keeps finding the same thing")) == 7


def test_a_broad_except_aglerror_catches_stop_which_is_why_ordering_matters() -> None:
    """The trap, pinned rather than described. A workflow's retry loop written `except AglError`
    around a step swallows a deliberate end and tries again - the one shape of this bug where the
    run keeps working after it was told to stop. §3.1 makes the CLI's half a 10.3 criterion."""
    with pytest.raises(ReviewNotConverging):
        try:
            raise ReviewNotConverging("nothing left to pick up")
        except AglError as caught:
            assert isinstance(caught, Stop)
            assert exit_code_for(caught) == 7
            raise


# --- refusals, every one of them an InputError at import time ----------------------------------


@pytest.mark.parametrize("name", ["", "   "])
def test_a_blank_workflow_name_is_refused(name: str) -> None:
    """Refused when the decorator is built, before it is applied to anything."""
    with pytest.raises(InputError, match="name is required"):
        workflow(name=name, version="1.1", params=NoParams)


@pytest.mark.parametrize("version", ["", "\t"])
def test_a_blank_version_is_refused(version: str) -> None:
    """`RunSpec.workflow_version` refuses an empty one, so a run declared this way could not be
    recorded - which is the argument for the field being a required keyword at all."""
    with pytest.raises(InputError, match="version is required"):
        workflow(name="fix", version=version, params=NoParams)


def test_a_params_type_that_is_not_a_dataclass_is_refused() -> None:
    with pytest.raises(InputError, match="dataclass of `arg\\(\\)` fields"):
        workflow(name="fix", version="1.1", params=str)


def test_an_instance_where_the_params_class_belongs_is_refused() -> None:
    """mypy refuses this at the decoration site, which is the first line of defence and not the
    only one: `@workflow` is read by whatever a workflow package's author ran, or did not run."""
    with pytest.raises(InputError, match="never an instance"):
        workflow(name="fix", version="1.1", params=NoParams())  # type: ignore[arg-type]


def test_a_function_that_is_not_a_coroutine_function_is_refused() -> None:
    """No `type: ignore` here on purpose: `_returns_an_awaitable` satisfies the declared parameter
    type exactly, and mypy has nothing to say about it. That is the whole case for the check."""
    declare = workflow(name="fix", version="1.1", params=NoParams)
    with pytest.raises(InputError, match="async def"):
        declare(_returns_an_awaitable)
