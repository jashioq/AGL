"""What the authoring model promises: a decorated async function, and a typed `Run`.

Five properties carry this suite.

**The annotation is the declaration**, and the assertions below read it back rather than
describing it. `@workflow(version="1.1")` is the whole line, `Workflow.params` resolves
`run: Run[TicketsParams]` through `get_type_hints`, and a bare `Run` means a workflow with no
parameters at all. Two things are pinned that prose cannot pin: that resolution is **lazy** - a
params class declared *below* its own workflow function resolves, which is a test that goes red the
moment the read moves back to decoration time - and that every way of failing to declare one is an
`InputError` naming the function and the line, never a quiet fall back to "no params". The second is
preflight's own failure one level up, where a scan that under-approximated in silence let a run
start and die at its first step.

**The narrowing `registry.load` performs is driven end to end**, through a hand-constructed
`EntryPoint` pointing at this module - the registration line, resolved - because that is the
whole reason this class exists. `config/registry.py` deferred nominal narrowing to "the object
`@workflow` produces in `sdk/workflow.py`", so the pair is asserted together: a `Workflow` loads,
and something that is not one is refused with the registry's `InputError` rather than reaching
`api.py` as an `Any`.

**The typing promise is asserted at the type level**, with `assert_type` rather than a runtime
check, because the claim is about what *mypy* knows: `run.params.concurrent` is an `int`. A
runtime assertion would pass against a `Run` that had erased its params to `object`, which is
precisely the version of this module worth catching. `mypy --strict` runs over `tests/` too, so
these are gates and not documentation. Both spellings are pinned - `Run[TicketsParams]`
for a workflow that reads its parameters and a bare `Run` for one that does not.

**Every refusal is an `InputError`**, asserted on the class and on the part of the message a reader
acts on next. Two of them are at import time, where a package that cannot be invoked correctly
should fail: the blank `version` when the decorator is *built*, before it is applied, and the
`async def` check when it is applied. The other five are at the first read of `wf.params`, because
resolution is lazy and there is no earlier moment to make them in - and each of those is
asserted to name the function *and* the source line, which is what a reader of a workflow package
they did not write needs in order to have somewhere to go.

**`Stop` is asserted to be the same class object**, not merely a compatible one. A copy would
satisfy `except Stop` inside a workflow, resolve to 7 through `exit_code_for`, and then fail to be
caught by the CLI's handler, which imports the other one - a divergence with no symptom until a
deliberate end is reported as a crash.
"""

import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields, is_dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final, assert_type, cast

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
    """The worked example, written out rather than adapted - the one `test_params.py` parses."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing - `noop`'s shape, and the params class it still needs."""


# What `tickets` was handed, so that a test can assert about the `Run` the framework passed rather
# than about one it built itself. A list at module level because the workflow has to be one too:
# `EntryPoint.load` imports a module and reads an attribute in it, and cannot see a local.
_handed: Final[list[Run[TicketsParams]]] = []


@workflow(version="1.1")
async def tickets(run: Run[TicketsParams]) -> None:
    """The typed spelling. The two `assert_type` calls are this suite's real subject: they are
    checked by `mypy --strict` over `tests/`, and neither survives a `Run` that erased its
    params."""
    assert_type(run.params, TicketsParams)
    assert_type(run.params.concurrent, int)
    _handed.append(run)


@workflow(version="1.1")
async def fix(run: Run) -> None:
    """The `fix` example writes a bare `Run`, and this is that signature literally. It compiles
    only because `Run`'s type parameter has a PEP 696 default - `disallow_any_generics` is on - and
    the default being `object` rather than `Any` is what makes the line below an error to remove.

    This signature is also the *declaration* that this workflow has no parameters, and it is the
    only one: there is no `params=` to contradict it with. This line once carried `params=NoParams`
    beside a bare `Run` and was the one declaration site in the whole repository where the decorator
    and the annotation said different things - legally, `Run` being covariant."""
    assert_type(run.params, object)


@workflow(version="1.1")
async def deferred(run: Run[DeferredParams]) -> None:
    """A workflow whose params class is declared **below** it, which is why the class is.

    This is the laziness asserted by construction rather than by a test that could be written to
    pass either way: `@workflow` runs at import, `DeferredParams` is not bound yet when it does, and
    a resolver that read the annotation there would raise `NameError` and take this module's import
    with it. Python 3.14 evaluates no annotation until something asks, so the `def` itself is fine;
    `Workflow.params` is what asks, and it asks through `fn.__globals__`, where the class is by
    then.

    Declaration order is not exotic - a params class reads better beside the flags it declares than
    above the workflow that never mentions it - so this is a shape an author reaches without
    trying."""
    assert_type(run.params, DeferredParams)


@dataclass(frozen=True)
class DeferredParams:
    """Declared under its own workflow on purpose. See `deferred` above."""

    request: str = arg("-r", "--request", help="what to build")


@dataclass(frozen=True)
class Findings:
    """A reporting payload, so that one of the two roles below is a `Role[Findings]` and the other
    a `Role[None]` - which is what makes the widening to `Role[object]` a real question."""

    high: int


# The motivating pair: one model per provider, in one workflow. Two `@role(model=…)` factories,
# which is what a role declaration is - the model is on the decorator, where preflight can read it
# without calling anything, and the `Role` is what the call below produces. These two names being
# bound *in this module* is the whole of what makes them the workflow below's roles: there is no
# list on the decorator, and the namespace is the registry.


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


@workflow(version="1.1")
async def staffed(run: Run[NoParams]) -> None:
    """A workflow written beside two role factories and declaring neither, because there is
    nothing to declare: the two names above are bound in this module, and the module is what
    preflight reads. Nothing runs it here - `tests/sdk/test_preflight.py` is where the namespace
    is spent."""


# The load that succeeds into the wrong type. `test_registry.py` uses a string for this too.
_not_a_workflow = "a workflow name is not a workflow"


def _returns_an_awaitable(run: Run[NoParams]) -> Awaitable[None]:
    """A plain function satisfying `Callable[[Run[P]], Awaitable[None]]` and never yielding to the
    event loop. It type-checks as a workflow's function exactly, which is why the check that
    refuses it has to be at runtime."""
    raise AssertionError("`@workflow` refuses this before anything can call it")


# --- the five ways a first parameter declares no params, none of which is read as "no params" ----
#
# Each is refused by mypy where it is written - four at the decoration site, and the unannotated one
# at its own `def`, `disallow_untyped_defs` being on. That is the first line of defence and not the
# only one: `@workflow` is read by whatever a workflow package's author ran, or did not run. They
# are declared undecorated here and decorated inside `_params_of` below, so that the one `cast` this
# file needs sits in one place with the argument for it.


async def _takes_nothing() -> None:
    """A workflow function with no parameters at all - not even the `Run` it is handed."""


async def _unannotated(run) -> None:  # type: ignore[no-untyped-def]
    """The one that matters most. A reader sees `run` and reads "a `Run`"; the resolver sees an
    annotation that was never written, and the two must not be treated as the same statement."""


async def _not_a_run(run: int) -> None:
    """An annotation that resolves perfectly and is not a `Run`."""


class _MyRun[P = object](Run[P]):
    """A subclass of `Run`, which nothing in AGL builds and `_declared` therefore refuses."""


async def _a_run_subclass(run: _MyRun[NoParams]) -> None:
    """`_MyRun` names a params class and is still refused: the framework hands a workflow the `Run`
    it built, so the annotation would be describing an object this run cannot produce."""


async def _unresolvable(run: Run[Undeclared]) -> None:  # type: ignore[name-defined] # noqa: F821
    """An annotation naming something nothing binds. Python 3.14 evaluates no annotation at the
    `def`, so this file imports; `get_type_hints` is where the `NameError` arrives."""


def _params_of(fn: Callable[..., Awaitable[None]]) -> type[object]:
    """`@workflow` applied to `fn`, and `wf.params` then read - the two moments, separated.

    The decoration succeeds for all five: what `@workflow` still checks at import is the `version`
    and that the object is a coroutine function, and every one of them is an `async def`. The
    refusal arrives at the read, because a params class declared below its own workflow cannot be
    resolved any earlier - which is the laziness `deferred` above depends on, seen from the failing
    side.

    The `cast` is this helper's whole reason for existing. Every function above is refused by mypy
    where it is written, so none of them can be handed to `workflow()` in typed code at all; putting
    the assertion behind one cast keeps that first line of defence intact everywhere else in this
    file and still drives the second, which is what a package whose author skipped mypy gets.
    """
    declared = cast("Callable[[Run[object]], Awaitable[None]]", fn)
    wf: Workflow[object] = workflow(version="1.1")(declared)
    return wf.params


def _services(tmp_path: Path) -> Services:
    """A bundle from the composition root, on fakes alone, and the only honest way to fill
    eight fields typed as port ABCs. `run.step` is what reads it, and reads it lazily: no port
    below is touched by building a `Run` or by any test in this file."""
    return container.fakes(TreesRoot(tmp_path / "trees")).services


def _run[P](params: P, tmp_path: Path, *, fingerprints: Fingerprints | None = None) -> Run[P]:
    """A `Run` over a fakes bundle at a fixed scope and base.

    `fingerprints` is spelled out rather than defaulted through, because the one test below that
    supplies its own is testing exactly that it can - that is the seam.
    """
    return Run(
        params=params,
        services=_services(tmp_path),
        scope=SCOPE,
        base=BASE,
        fingerprints=Fingerprints() if fingerprints is None else fingerprints,
    )


def _point(name: str, attribute: str) -> EntryPoint:
    """The `tickets = "agl.workflows.tickets:tickets"` entry point, pointed at this module."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)


# --- what the decorator produces ---------------------------------------------------------------


def test_a_decorated_async_function_is_a_workflow_object() -> None:
    """The decorated name *is* the entry point's target, so it has to be the `Workflow` itself."""
    assert isinstance(tickets, Workflow)
    assert_type(tickets, Workflow[TicketsParams])
    assert (tickets.version, tickets.params) == ("1.1", TicketsParams)


def test_the_decorator_holds_the_function_unwrapped() -> None:
    """`api.py` awaits this. Nothing is wrapped around it, so a traceback names the workflow."""
    assert tickets.fn.__qualname__ == "tickets"


# --- what the decorator no longer takes, and where preflight looks instead -----------------------


def test_a_workflow_holds_a_version_and_a_function_and_derives_the_rest() -> None:
    """The whole content of three removals, read off the class rather than off their prose.

    The `roles` field was the one member here that was not a fact about `fn`, and it existed because
    preflight had no other way to see a role before a run started: roles are built inside the
    workflow's own body, so nothing at decoration time could enumerate them. The `@role(model=…)`
    decorator dissolved that - a role is a factory carrying its model on the object bound at import
    - and this is the line that says the field went with it.

    `name` went for the opposite reason: it was not a declaration of something readable elsewhere
    but a second name for what the entry-point key already names, agreeing with it by convention and
    compared with it by nothing. The key is the name now, and there is no copy.

    `params` went a third way again - not deleted but **derived**. It is still
    `wf.params` and still a `type[P]`; what changed is that no caller supplies it, because the
    annotation on `fn`'s own first parameter already says it and mypy already enforces that. So two
    fields are left, and the second one is what the read is over.

    Over `dataclasses.fields` and not over a `hasattr` apiece, so that a *third* field arriving here
    fails this test rather than passing it silently - and `params` is deliberately not in the list
    that follows, a property being exactly the difference between a fact this class is told and one
    it can work out."""
    assert [held.name for held in fields(Workflow)] == ["version", "fn"]
    assert isinstance(vars(Workflow)["params"], property)


def test_the_registry_preflight_reads_is_the_module_the_function_was_written_in() -> None:
    """What replaced the declaration, asserted as a namespace rather than argued as prose.

    `preflight.check` is handed `wf.fn` and reads the `RoleFactory` values in
    `vars(sys.modules[fn.__module__])` - so the *import line above a workflow is its declaration*,
    and this test fails if the two factories declared beside `staffed` ever stop being visible to
    it. `ARCHITECTURE.md`'s "Deliberately not built": one declaration, not two.

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

    The workflow is `fix`, so the chain is walked over the *bare*-`Run` end of it: `wf.params` is
    the empty class a bare `Run` resolves to, and the last line is what says so without
    naming a private class. Two parses of one params class produce equal instances, which is
    exactly what `object` - `Run[P]`'s static default, and not a dataclass - would not do.
    """
    wf: Workflow[object] = registry.load([_point("fix", "fix")], "fix", Workflow)
    assert_type(wf.params, type[object])
    params = parse(wf.params, [])
    assert_type(params, object)
    run = _run(params, tmp_path)
    assert_type(run, Run[object])
    await wf.fn(run)
    assert run.params == parse(wf.params, [])


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
    """The seam, still pinned here where it is cheapest to.

    The counter scopes `n` per `(namespace, step name)`, which only means anything if every
    namespace in a run counts against one object. `run.worktree()` is what passes it -
    `test_run_worktree.py` asserts that it passes *this* object - and what this asserts is that
    there is a way in at all, because a counter built privately in `__post_init__` would look
    identical in a run with one namespace, and would be the fix behind `test_journal.py`'s rule 1
    silently removed the moment a child was cut.
    """
    counter = Fingerprints()
    assert _run(NoParams(), tmp_path, fingerprints=counter).fingerprints is counter


def test_a_run_holds_nothing_it_did_not_declare(tmp_path: Path) -> None:
    """Slotted, so the surface is the fields below, and an attribute a caller attached to a `Run`
    would be one more that nobody declared and that replay would never see.

    `terminal`, the sixth member, arrived without this tuple moving, which is the shape of that
    decision rather than an oversight: it is a property over `services.terminal` and not a field, so
    a `Run` still holds exactly what it was assembled with.
    `tests/sdk/test_run_terminal.py` asserts the other half - it reads the bundle's own object.

    `worktrees` joined the list beside `fingerprints` and for its reason: it is the run's table of
    taken namespaces, defaulted for the root and handed on to every child, so it is a constructor
    keyword rather than something `__post_init__` builds.

    `leases` is the third of exactly the same shape: the lease per integration target, run-wide,
    defaulted for the root and handed on by `_child`. It is a constructor keyword
    for one reason the other two do not have - `api.run` releases it in a `finally` around the
    workflow's function, so the composition root has to be holding the object the run was built
    with.

    `capabilities` is the fourth of that shape: the record of what each model's backend reported,
    asked once per model per run because `capabilities()` is contracted
    stable for the duration of one. It is the only one of the four where sharing is an economy
    rather than the mechanism - a second table merely re-asks - which is why it is also the only one
    a directly-built `Run` can default with nothing arranged.

    `_parent` is the link `integrate()` walks to reach the namespace a child's work lands into. A
    keyword like the three above, defaulted `None` - which is how a root says it is a root - and set
    by `_child` alone. Private, because a `Run`'s surface is six members and a public one would hand
    a workflow author a tree to walk.

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
    """The standing example of a workflow's reason, declared against the SDK's import of `Stop`."""


def test_stop_imported_from_the_sdk_is_the_ports_class_itself() -> None:
    """The same class object, not a compatible copy - see this module's docstring for the cost."""
    assert Stop is errors.Stop


def test_a_workflows_own_stop_subclass_resolves_to_seven() -> None:
    """`exit_code_for` walks the MRO, so a reason the framework never heard of exits 7 anyway."""
    assert exit_code_for(ReviewNotConverging("the reviewer keeps finding the same thing")) == 7


def test_a_broad_except_aglerror_catches_stop_which_is_why_ordering_matters() -> None:
    """The trap, pinned rather than described. A workflow's retry loop written `except AglError`
    around a step swallows a deliberate end and tries again - the one shape of this bug where the
    run keeps working after it was told to stop. The ordering is a requirement, not a habit."""
    with pytest.raises(ReviewNotConverging):
        try:
            raise ReviewNotConverging("nothing left to pick up")
        except AglError as caught:
            assert isinstance(caught, Stop)
            assert exit_code_for(caught) == 7
            raise


# --- the params, read off the annotation the author already wrote ------------------------------


def test_a_subscripted_run_declares_the_class_it_names() -> None:
    """`run: Run[TicketsParams]` and `wf.params is TicketsParams`, which is the whole mechanism.

    The annotation was load-bearing already - `run.params.concurrent` is an `int`
    because of it, and misspelling that field is an error mypy reports today - so reading it back is
    a read of the declaration and not an inference from a coincidence. What went away is the second
    copy that used to sit on the decorator beside it."""
    assert tickets.params is TicketsParams
    assert_type(tickets.params, type[TicketsParams])


def test_a_bare_run_means_no_params_and_not_the_absence_of_a_declaration() -> None:
    """A workflow that never reads its params writes `async def fix(run: Run) -> None`, and
    that is the one spelling that legitimately means "none" - `Run[P]`'s PEP 696 default.

    What it resolves to is a params class like any other, because `params.parse`, `parser_for`,
    `to_json` and `from_json` all require a dataclass and none of them was relaxed. `object` is
    `Run[P]`'s static default and is not a dataclass, so resolving to it would have made every
    `agl run` on a params-less workflow refuse a workflow that had declared itself correctly."""
    assert is_dataclass(fix.params)
    assert fields(fix.params) == ()


def test_agl_run_on_a_params_less_workflow_parses_an_empty_line_and_no_other() -> None:
    """The half of "no params" that a `type[object]` would have got wrong in both directions.

    An empty argv parses, which is what makes `agl run fix -n auth` a run rather than an exit 2; and
    a flag nobody declared is still refused, which is what an ignored-argument reading would have
    lost. `parse` is the very function `api.run` calls, so this is the command line and not a
    stand-in for it."""
    assert parse(fix.params, []) == parse(fix.params, [])
    with pytest.raises(InputError, match="unrecognized arguments"):
        parse(fix.params, ["--anything"])


def test_a_params_class_declared_below_its_own_workflow_resolves() -> None:
    """The laziness, and the test that goes red if the read moves back to decoration time.

    `DeferredParams` is declared *under* `deferred`, so it is not bound when `@workflow` runs. A
    resolver that read the annotation there would raise `NameError` - turned into `InputError` by
    `_hints` - and this module's import would fail, taking every test in the file with it. That is
    the failure mode this asserts against: not a wrong answer, an unimportable package.

    `get_type_hints(fn)` is what makes it work, because it resolves through `fn.__globals__` - the
    module's namespace as it is *now*, not as it was when the decorator returned."""
    assert deferred.params is DeferredParams
    assert parse(deferred.params, ["-r", "add oauth"]) == DeferredParams(request="add oauth")


# --- refusals: two at import time, and five at the first read of `params` -----------------------


def _refused(fn: Callable[..., Awaitable[None]]) -> str:
    """The message `wf.params` refuses `fn` with, having first checked what every one of them has to
    say: **the function and the source line its `def` is on**.

    Both, and neither is decoration. These refusals surface through `agl run`, about a package the
    operator installed and did not write, so a name with no file beside it is a name with nowhere to
    go - and a file with no line is a module docstring to scroll past. `co_filename` and
    `co_firstlineno` are read off the same function the message was built from, so a test here
    cannot drift from a source line the way a hard-coded number would.
    """
    with pytest.raises(InputError) as refusal:
        _params_of(fn)
    message = str(refusal.value)
    assert fn.__qualname__ in message
    assert f"{fn.__code__.co_filename}:{fn.__code__.co_firstlineno}" in message
    return message


@pytest.mark.parametrize("version", ["", "\t"])
def test_a_blank_version_is_refused(version: str) -> None:
    """`RunSpec.workflow_version` refuses an empty one, so a run declared this way could not be
    recorded - which is the argument for the field being a required keyword at all.

    Refused when the decorator is built, before it is applied to anything - and it is one of the
    two things still refused there, the other being the `async def` below. Its sibling over a blank
    `name` went with that parameter: a workflow's name is the entry-point key, and what a key may be
    is the registry's judgement rather than this decorator's. Its sibling over `params=` went with
    that one, where the checks moved to the read because the annotation they are about cannot be
    resolved any earlier."""
    with pytest.raises(InputError, match="version is required"):
        workflow(version=version)


def test_a_function_that_is_not_a_coroutine_function_is_refused() -> None:
    """No `type: ignore` here on purpose: `_returns_an_awaitable` satisfies the declared parameter
    type exactly, and mypy has nothing to say about it. That is the whole case for the check."""
    declare = workflow(version="1.1")
    with pytest.raises(InputError, match="async def"):
        declare(_returns_an_awaitable)


def test_a_workflow_function_taking_no_parameters_is_refused() -> None:
    """There is nowhere for a params class to be declared, and nothing to hand a `Run` to."""
    assert "takes no parameters" in _refused(_takes_nothing)


def test_an_unannotated_first_parameter_is_not_read_as_a_bare_run() -> None:
    """The refusal this deliverable exists to make, and the one a default would have swallowed.

    `async def w(run)` looks like a `Run` to a reader and is not a declaration to anything else.
    Reading it as a bare `Run` would hand the workflow an empty params class and refuse every flag
    the author meant to declare - at the parse, about the flag, and never about the annotation. So
    it is refused here, where the sentence can name the line to edit. It is the exact shape of
    preflight's own failure one level up: a scan that under-approximated in silence, so preflight
    asked about no models and the run died at its first step instead of before it started."""
    assert "annotates nothing on its first parameter" in _refused(_unannotated)


def test_a_first_parameter_that_is_not_a_run_is_refused() -> None:
    """An annotation that resolves perfectly and names something a workflow is never handed."""
    assert "async function taking a `Run`" in _refused(_not_a_run)


def test_a_run_subclass_is_refused_rather_than_read_through() -> None:
    """`_MyRun[NoParams]` names a params class and is still refused, which is the deliberate half.

    There are two spellings and a subclass is neither. Nothing in AGL constructs one - `api.py`
    builds the root and `_child` cuts the rest - so the annotation would be promising an object this
    run cannot produce, and reading the params out of it anyway would make the annotation stop being
    the single source: the class it names and the class the workflow receives would be two things
    again, which is the disagreement the annotation removed. A subclass is also free to add type
    parameters of its own, at which point "the first argument" is a guess about which one meant the
    params."""
    assert "subclass of `Run`" in _refused(_a_run_subclass)


def test_an_annotation_naming_something_unresolvable_is_refused_as_an_input_error() -> None:
    """`get_type_hints` raises `NameError` here, and a workflow package's typo is not a crash.

    `sdk/_declarations.py::annotations_of` catches the same two exceptions for the same situation
    one level down - a params class whose own field annotations will not resolve - and this is that
    shape reused rather than reinvented, with the original chained so the traceback still shows the
    name."""
    assert "cannot be resolved" in _refused(_unresolvable)


def test_the_original_error_is_chained_onto_the_refusal() -> None:
    """`raise ... from error`, so `NameError: name 'Undeclared' is not defined` is still in the
    traceback under the sentence that explains what it meant."""
    with pytest.raises(InputError) as refusal:
        _params_of(_unresolvable)
    assert isinstance(refusal.value.__cause__, NameError)
