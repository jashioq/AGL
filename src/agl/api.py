"""AGL's own operations - run, resume, clear, init, list_workflows - as an importable library.

§1.5's charge is that there was no importable AGL: `main()` *was* the composition, every decision
lived inside an `argparse` callback, and `_cmd_run` ended in a bare `except Exception` rendering any
bug as `error: <str>`. §1.4's is the same fault from the other side - `_cmd_clean` and `_cmd_init`
were use cases living in the CLI, and `Git(Path.cwd())` was constructed four times, once per
command. This module closes both: the five operations §3.10 names are functions here, each callable
from a test, a harness or another program, and `cli/` is left with argv, an event loop and an exit
code.

The division is exact. `cli/main.py` resolves configuration and dispatches to one of the five;
everything that decides anything - which workflow, whether the label is free, what a run's record
says - is here. A command that grew a second `read_record`, or a second opinion about what `--from`
defaults to, would be §1.4 happening again.

## Composition is per-command (§3.10), and the five signatures below are where that is written

"`main.py` resolves settings and dispatches; each operation then resolves its own prerequisites.
`run`, `resume` and `clear` resolve a project and build a container; `init` takes settings alone;
`list_workflows` takes neither." That is not a note about the CLI, it is the shape of this module -
and a uniform signature is exactly what made composition universal in the first place. 10.4 handed
every operation a `Services` so that the dispatch had one shape to remember, and 11.0 is the bill:
`init` *writes* the project file a container needs in order to be constructible, so an `init` taking
a bundle is an operation nothing could ever reach, and `list_workflows` reads packaging metadata, so
a `list_workflows` taking one makes `agl workflows` demand a registered repository in order to list
what is merely installed.

So the three operations addressed to a run take `(services, project, ...)`, `init` takes `Settings`,
and `list_workflows` takes nothing but the entry-point seam this module already had. Five signatures
where there was one shape is the price, and it is paid in exactly one place - `cli/main.py`'s
dispatch, the only caller that has to know all five - rather than by the two operations that would
otherwise have had to be built out of reach.

## No operation builds a port, including the ones that are handed none

`config/container.py` is the only module that may say `new` (contract 5), so an `api` that
constructed its own ports would be a second composition root and `lint-imports` would say so. That
is why `init` losing the bundle is not `init` gaining a container: what it is handed shrank, and
what it may construct is unchanged at nothing. Taking the bundle rather than building one is also
what keeps measurable target #8 reachable: an operation runs end to end on `container.fakes()` with
no network, no git and no process, because substituting every implementation at once is one argument
rather than a fixture. `tests/test_api.py` does exactly that, which is the walking skeleton proved
from the library side before 10.4 wired the argv side.

`run` takes the project's **name** and not `config.schema.Project`. A run's address under `AGL_HOME`
is `RunScope(project, label)` and the name is the whole of what that needs; the rest of a `Project`
- its repository, its trees root, its build command - has already been spent by the container in
constructing the ports handed in beside it. Taking the whole object would put a `config` type in a
signature a library caller has to satisfy, in exchange for seven fields nothing here reads.

## Async where the ports are, and the event loop belongs to `cli/`

There is no `asyncio.run` in this file and there must not be. `Store` and `History` are async
because an implementation may go out of process, and a library that started a loop of its own could
not be called from inside one - which is precisely what 16.5's harness, and every `pytest.mark
.asyncio` test below, do. `list_workflows` is the one operation that is not async, because it awaits
nothing: it reads packaging metadata and sorts strings.

## What `run` does, in order, and the two things it deliberately does not

Load the workflow, refuse a label that is already taken, pin the base ref to a full object name,
write `run.json`, provision the run's own `_base` worktree from that pin, then await the workflow's
function and give back every integration lease it was still holding. The order is load-and-parse
first because those two refuse with no I/O at all - §3.3's "before anything runs" read as strictly
as it can be - then the conflict check, which decides whether this run may exist, then the three
that are addressed to the repository.

**The record is written before the workflow is invoked**, so a crash mid-run leaves something behind
to resume or to clear. It is the one value in AGL with no other copy anywhere (`ports/store.py`), so
the cost of writing it early is a stale record after a crash - which `clear` takes away - and the
cost of writing it late is a run that happened and cannot be named.

**And it is written before the workspace is provisioned**, which is the same argument at the sharper
end and the reason those two lines are in the order they are. `WorkspaceProvider` offers no
enumeration on purpose (`ports/workspace.py`), so `run.json` is the only thing that names a run at
all: a crash after `open()` must still leave a record naming the label, or `agl/<label>` and
`.trees/<label>/_base/` are a branch and a directory nothing can ever reach again. Writing first
costs a record for a run whose checkout was never cut, which is one `agl clear` away; writing second
costs a leak that no command in AGL has a way to address.

**The exposure this changed, stated rather than left to be found.** §3.9's known leak is a crash
between `open()` and the first entry write, and 13.4 makes that window start earlier - at this
function rather than at the first step - so it now covers the whole of a workflow, including one
that never steps at all. What it does **not** widen is the half of that leak nothing can address:
`_base` is addressed by `namespace=None`, which is derivable from the label alone, so a record on
disk is the whole of what `clear` needs in order to reach it, and the two lines above are in the
order that guarantees one. The unreachable half belongs to *children* and is untouched here - a
child's checkout is opened by `sdk/_engine/steps.py` on its first step, `Store.namespaces` lists
only namespaces that have recorded something, so a crash in between leaves a directory `clear`
cannot see and afterwards cannot `rmdir` past. Closing that is not this deliverable's, and widening
this window did not make it worse.

**A worktree and a branch now, and no lock and no persistence beyond `run.json`.** 13.4 is what put
the first two here, and §3.9 is why they belong to this function rather than to the first step: AGL
never writes into the target repository except through a `Workspace` - its own integration branch
included, which lives in `_base` and not in the user's checkout - and "`agl/<label>` is a real ref
from run start and advances with each `integrate()`, so progress is inspectable live - `git log
agl/auth`, `git diff main..agl/auth`". That sentence was false for a run whose workflow had not yet
taken a step, because the checkout was opened lazily by `run.step` and a workflow that ran no steps
opened nothing. `RunSpec.branch` is still written here and still not composed for the provider:
`WorkspaceProvider.open` derives `run_branch(label)` itself, so the record and the ref agree by both
reading `tree_layout` rather than by one of them being handed the other's answer. Steps persist
their own entries, from inside the workflow, through the `Run` built on the last line; integration
is 14. The one lock §3.9 asks for is on git's worktree registry and is taken inside the adapter,
around the two commands that mutate it and nothing else.

## `run` catches nothing at all, which is how the `Stop` ordering hazard is met

§3.1 makes it a stage-10 acceptance criterion: `Stop` descends from `AglError`, so a handler that
catches the base first swallows a deliberate end and reports 6 or 70 where the contract promises 7.
In this module the hazard is *wrapping* rather than reporting - any `except AglError` that
translated, annotated or re-raised would turn a workflow's `ReviewNotConverging(Stop)` into
something else on the way out, and the exit code would be right by accident or wrong by one edit.

So there is no `except` in this file, and there never may be. A workflow's exception leaves
`api.run` as the object it raised, with its own traceback under it, and `cli/exit_codes.exit_status`
answers 7 for it without either module having learned what `ReviewNotConverging` is. That is
stronger than catching `Stop` first, and it is pinned by identity in the suite rather than by class.

**14.1 put a `try` here and the rule is unchanged, because the rule was about catching.** §3.4 gives
the framework a lease per integration target and has it "released when the run exits", so the last
two lines of `run` are a `finally` around the workflow's function. A `finally` sees no exception,
names no class and cannot decide anything: control leaves it carrying whatever arrived, `Stop`
subclass and all. What would break the criterion is an `except` of any width, which is why the
sentence above is written about that word rather than about `try`.

## The registry, and the one seam it left open

`config/registry.py` split itself into a pure core taking entry points and one impure line asking
the interpreter what is installed, "so a test drives them with `EntryPoint` values it constructs
itself". This module keeps that split rather than closing it: `points=` defaults to
`registry.installed()`, which is what every real invocation wants, and a caller that has its own set
- this suite, and 16.5's harness running a workflow the author has not installed yet - supplies one.
The alternative was for `api` to call `installed()` unconditionally and for callers above to
monkeypatch a module attribute to test anything, which is a seam too, without a signature.

`registry.load` is generic over the type its caller expects, and the annotation on the result is
load-bearing: a bare generic class in `type[T]` position infers `Workflow[Any]`, PEP 696 default
notwithstanding, so the call site writes `wf: Workflow[object]` and the `Any` stops here.
`Workflow[object]` cannot be passed as `kind` instead - `isinstance` refuses a subscripted generic.
Everything downstream then follows at `object`, which is the honest type for "some workflow's
params, and this module does not care which".

## `RunSpec.workflow` records the name that was typed, not `wf.name`

The two are the same string by convention and nothing here compares them, which `sdk/workflow.py`
notes is a comparison only this module could make. It is deliberately not made, because the field's
job settles which of the two belongs in it: `resume` reads `run.json` and asks the registry for that
workflow again, and the registry indexes by the **entry-point key**. Storing what the workflow calls
itself would produce a record that resumes only while the two agree, and fails with "no workflow
named ..." on the day a package renames one of them - naming the string the operator never typed.

## Four operations are declared and one is built

§3.10's five verbs are this module's row in `ARCHITECTURE.md` §6, and the CLI's dispatch is written
against the surface rather than against whichever half of it exists today. So `resume`, `clear` and
`init` are here as signatures that refuse, each naming the deliverable that fills it in - 16.2, 16.3
and 16.4 - and the refusal is an `InternalError` because at this stage nothing can reach one: the
CLI has no such verb, so arriving here is our bug and not the caller's mistake.

`list_workflows` is built, because it is genuinely complete: §3.10's `agl workflows` is "list what's
registered", `registry.names` is that list already sorted, and what 16.4 adds is a command that
prints it. A stub would have been a stub of one expression.
"""

from collections.abc import Iterable, Sequence
from importlib.metadata import EntryPoint

from agl.config import registry
from agl.config.schema import Settings
from agl.ports.errors import ConflictError, InternalError
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.run import RunSpec
from agl.ports.tree_layout import run_branch
from agl.sdk import params
from agl.sdk._engine.integration import Leases
from agl.sdk._engine.services import Services
from agl.sdk.workflow import Run, Workflow

__all__ = ["clear", "init", "list_workflows", "resume", "run"]


async def run(
    services: Services,
    project: ProjectName,
    name: str,
    label: RunLabel,
    argv: Sequence[str] = (),
    *,
    base_ref: str | None = None,
    points: Iterable[EntryPoint] | None = None,
) -> None:
    """Start a run: `agl run <workflow> -n <label> [workflow flags] [--from <ref>]` (§3.10).

    `name` indexes the `agl.workflows` entry points and `argv` is the workflow's own flags alone,
    the generic parser having taken its arguments off the front. `base_ref` is `--from`, and `None`
    means the repository's default (§3.9) - the configuration does not record one and the command
    line cannot see the repository, so `History` is what answers.

    Raises, and nothing else reports: `NotFoundError` for a name nothing registers (exit 3),
    `InputError` for flags the workflow's params refuse (exit 2), `ConflictError` for a label that
    already has a record (exit 4), and whatever the workflow itself raises, untouched - a `Stop`
    subclass included, which is the ordering criterion §3.1 makes of this stage.
    """
    wf: Workflow[object] = registry.load(_points(points), name, Workflow)
    # Parsed before any port is touched: a flag the workflow will not accept costs nothing to
    # refuse here and would otherwise be discovered after a record had been written for it.
    given = params.parse(wf.params, argv, prog=f"agl run {name}")

    scope = RunScope(project, label)
    if await services.store.read_record(scope) is not None:
        # §3.10's refusal, verbatim but for the em dash, which no message under `src/` spells.
        raise ConflictError(
            f"run {str(label)!r} already exists - `agl resume {label}` or `agl clear {label}`."
        )

    # `base_ref` is what the user said and `base_sha` what it meant now. Without the second, a
    # commit landing between run and resume moves the first step's starting head (§3.6).
    ref = await services.history.default_ref() if base_ref is None else base_ref
    spec = RunSpec(
        workflow=name,
        workflow_version=wf.version,
        label=label,
        base_ref=ref,
        base_sha=await services.history.resolve(ref),
        branch=run_branch(label),
        params=params.to_json(given),
        created_at=services.clock.now(),
    )
    await services.store.write_record(scope, spec.to_json())

    # §3.9's `_base`, cut eagerly and **after** the record, which is the whole of what these two
    # lines' order buys: `run.json` is the only enumeration `clear` has, so a crash after this call
    # must still leave a record naming the run - see the module docstring, and `ports/workspace.py`
    # for why no provider will ever be able to list what it holds.
    #
    # `spec.base_sha` and never `ref`, never `base_ref`: `open` takes a ref expression or a commit
    # id, `Journal` takes only the second, and the run's own base is pinned precisely so that a
    # commit landing on `main` between this line and the first step cannot move where the checkout
    # was cut from (§3.6). The record and the checkout therefore agree by construction, being the
    # one value spent twice.
    #
    # The `Workspace` is deliberately dropped rather than carried into `Run`. `open` is idempotent
    # by contract - "an existing workspace is returned exactly as it stands" - so `run.step`'s lazy
    # open in `sdk/_engine/steps.py` hands back this very checkout on first use and cuts nothing.
    # Nothing else moves: this call is not a new path into the engine, it is the same call made
    # earlier, so that a workflow which takes no steps at all still leaves `agl/<label>` a real ref.
    await services.workspaces.open(label, None, spec.base_sha)

    # §3.4's lease per integration target, constructed here and not left to `Run`'s own default,
    # because "the lease is released when the run exits" needs something above the workflow to be
    # holding the handle - and a defaulted field is built where nothing can reach it. This is the
    # one of `Run`'s three shared tables the composition root passes.
    leases = Leases()
    # The `Run` is built from what this function already computed and nothing else: `scope` is the
    # address the record above went to, and `base` is the same resolved commit the record pins and
    # the checkout was cut from.
    #
    # **The `try` is a `finally` and never an `except`**, which is what keeps the module docstring's
    # `Stop` argument true: nothing here catches, translates, annotates or re-raises a workflow's
    # exception, so it still leaves this function as the object it raised. What the `finally` adds
    # is that an unresolved conflict does not outlive the run holding a lease and a namespace's step
    # lock - a workflow that returned without deciding, raised, or was stopped mid-decision leaves a
    # live integration, and the object it is reachable from is going away with the workflow.
    #
    # **It releases the lease and deliberately does not abort the adapter's hold.** The hold is
    # durable by design (§3.4) so that a later invocation can find one it did not take, and 14.0
    # made a pre-existing hold answer as a `Conflict` rather than exit 70 - so aborting on the way
    # out would silently discard a partial resolution somebody may be in the middle of making, which
    # is the shortcut §3.4 forbids by name. `sdk/_engine/integration.py` argues the whole of it.
    try:
        await wf.fn(
            Run(
                params=given,
                services=services,
                scope=scope,
                base=spec.base_sha,
                leases=leases,
            )
        )
    finally:
        leases.release_all()


async def resume(services: Services, project: ProjectName, label: RunLabel) -> None:
    """Continue a run from its record: `agl resume <label>` (§3.10). **Deliverable 16.2.**

    The label only - params come from `run.json`, which is why nothing here takes argv - and a
    missing label errors symmetrically with `run`'s refusal of an existing one. It reads the record,
    compares `workflow_version` with `==`, and replays through the journal, none of which exists
    before stages 11 and 12.
    """
    raise _unbuilt("resume", "16.2")


async def clear(
    services: Services, project: ProjectName, label: RunLabel, *, force: bool = False
) -> None:
    """Take a run away: `agl clear <label> [-f]` (§3.10). **Deliverable 16.3.**

    `force` is `git branch -d` versus `-D`: without it the run's branch is deleted only if it is
    already contained in the base ref, and otherwise kept with a warning, because a retained branch
    costs a stale ref and a deleted one costs the entire run.
    """
    raise _unbuilt("clear", "16.3")


async def init(settings: Settings) -> None:
    """Register this repository as a project: `agl init` (§3.10). **Deliverable 16.4.**

    `Settings` and nothing beside it, which is the one signature here that could not have been read
    off `container.real`'s inputs: this is the operation that *creates* the project file every other
    one is already resolved against, so a `Project` does not exist when it is called and a container
    built from one cannot either. Settings alone resolve fine outside a registered repository -
    `schema.Settings` is written to that requirement in as many words - and `home` is the whole of
    what this needs, `AGL_HOME/projects/<name>.toml` being where the answer goes.

    §3.10 has it detect the git root, ask for the build command, pick a trees root and write that
    file. Detecting the git root is left here rather than passed in because `cli/main.py` no longer
    asks the working directory anything: `Path.cwd()` travels inside the callable that resolves a
    project, and a command that has no project to resolve never invokes it.
    """
    raise _unbuilt("init", "16.4")


def list_workflows(*, points: Iterable[EntryPoint] | None = None) -> tuple[str, ...]:
    """Every registered workflow name, sorted: `agl workflows` (§3.10). The command is 16.4's.

    Nothing is imported to answer it, which is `registry.names`' own guarantee: one workflow package
    that fails to import still appears here, and a broken third-party package cannot take down the
    command an operator runs to find out what they have.

    Neither a bundle nor a project, which §3.10 states outright and which the body is the argument
    for: this reads packaging metadata, a fact about the installation and not about any repository.
    10.4 handed it a `Services` it never read, so that the dispatch had one shape - and the shape
    was the defect, because a listing that took a container could only be produced from inside a
    registered repository, which is the one place an operator asking "what do I have installed?" is
    least likely to be standing.

    Sync, because it awaits nothing.
    """
    return registry.names(_points(points))


def _points(points: Iterable[EntryPoint] | None) -> Iterable[EntryPoint]:
    """What is installed, unless the caller brought its own - the seam the module docstring argues.

    One helper rather than the same conditional twice, because the two operations that discover
    workflows must discover the same ones: a listing that answered about a different set from the
    one `run` loads from would be a registry with two answers.
    """
    return registry.installed() if points is None else points


def _unbuilt(operation: str, deliverable: str) -> InternalError:
    """The refusal a declared-but-unbuilt operation raises, naming the deliverable that fills it.

    `InternalError` - exit 70, "file a bug" - because at this stage the CLI has no verb that reaches
    any of them, so a call is a fault in AGL rather than in what the caller supplied. It is not
    `NotImplementedError`: `errors.py`'s classes are the only ones AGL refuses with, and the builtin
    would arrive at `cli/exit_codes` as an untranslated exception, which resolves to the same 70 by
    a route that reads as an accident.
    """
    return InternalError(
        f"`agl {operation}` is declared in `agl.api` and not built yet - deliverable {deliverable} "
        f"is what fills it in. Nothing in this version of AGL should be able to call it: the CLI "
        f"has no {operation} command until then"
    )
