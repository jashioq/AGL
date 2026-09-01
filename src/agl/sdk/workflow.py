from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from inspect import iscoroutinefunction, signature
from typing import cast, get_args, get_origin, get_type_hints
from agl.ports.errors import InputError, Stop
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace
from agl.ports.integration import Conflict
from agl.ports.terminal import Terminal
from agl.ports.verifier import VerifierOutcome
from agl.sdk._declarations import named
from agl.sdk._engine.integration import Integration, Leases
from agl.sdk._engine.integration import integrate as _integrate
from agl.sdk._engine.journal import Fingerprints
from agl.sdk._engine.preflight import Capabilities
from agl.sdk._engine.services import Services
from agl.sdk._engine.steps import Steps
from agl.sdk._engine.worktrees import Worktrees, _where
from agl.sdk.roles import Role

__all__ = ["Conflict", "Namespace", "Run", "Stop", "VerifierOutcome", "Workflow", "workflow"]

@dataclass(frozen=True, slots=True)
class Run[P = object]:
    params: P

    services: Services

    scope: RunScope

    base: str

    fingerprints: Fingerprints = field(default_factory=Fingerprints)

    worktrees: Worktrees[Run[object]] = field(default_factory=Worktrees)

    leases: Leases = field(default_factory=Leases)

    capabilities: Capabilities = field(default_factory=Capabilities)

    _parent: Run[P] | None = field(default=None, repr=False, compare=False)

    _steps: Steps = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_steps",
            Steps(self.services, self.scope, self.base, self.fingerprints, self.capabilities),
        )

    @property
    def activity(self) -> str | None:
        """What the agent serving this run is doing, for a view the terminal redraws every frame.

        :return: the adapter's own line, or `None` between steps and on a step replayed from cache
        """
        return self._steps.activity

    @property
    def terminal(self) -> Terminal:
        """The display this run shows on, and the same object for every run in the tree.

        :return: the terminal the framework opened around the workflow; children share this one
        """
        return self.services.terminal

    async def step[R](self, role: Role[R], *, commit: str | None = None, **inputs: object) -> R:
        """Run one step against this run's checkout, or replay its entry and pay for nothing.

        :param role: carries the step's name, so two calls on one role are told apart by inputs
        :param commit: given, commits whatever is dirty; omitted, resets and cleans it all away
        :param inputs: fingerprint terms, appended to the prompt under a fixed `## Inputs` heading
        :return: the reporting tool's payload as its dataclass, or `None` for a role declaring none
        """
        return await self._steps.step(role, commit=commit, inputs=inputs)

    def worktree(self, namespace: str, base: Run[object] | str | None = None) -> Run[P]:
        """Open a child run with a checkout of its own, which is how two agents work at once.

        :param namespace: unique run-wide and not merely among siblings, compared case-insensitively
        :param base: a run, a ref, or omitted for this run's last recorded head - not its branch tip
        :return: the child; asking again from here hands back that same object and ignores `base`
        :raises ConflictError: this name is held elsewhere in the run, and both scopes are named
        """
        return cast(
            "Run[P]",
            self.worktrees.open(
                namespace, scope=self.scope, base=_starts_at(self, base), build=self._child
            ),
        )

    async def integrate(self) -> Integration:
        """Land this run's work into the worktree of the run that cut it, one landing at a time.

        :return: an outcome holding a lease until `retry` or `abort` settles it, conflicts included
        :raises InputError: this is the root run, which has no parent and no argument naming one
        """
        if self._parent is None:
            raise InputError(_unaddressable(self.scope))
        return await _integrate(
            source=self._steps,
            target=self._parent._steps,
            address=self._parent.scope,
            services=self.services,
            leases=self.leases,
        )

    def _child(self, scope: RunScope, base: str) -> Run[P]:
        return Run(
            params=self.params,
            services=self.services,
            scope=scope,
            base=base,
            fingerprints=self.fingerprints,
            worktrees=self.worktrees,
            leases=self.leases,
            capabilities=self.capabilities,
            _parent=self,
        )

def _starts_at(run: Run[object], base: Run[object] | str | None) -> str:
    if base is None:
        return run._steps.last_good
    if isinstance(base, str):
        return base
    return base._steps.last_good

def _unaddressable(scope: RunScope) -> str:
    return (
        f"there is no parent to integrate into: {_where(scope)} called `run.integrate()`, and a "
        f"landing goes into the worktree of the `Run` that cut this one. Only a child opened "
        f"with `run.worktree(namespace)` has one. There is no argument to point it elsewhere, "
        f"and that is not a policy: AGL never checks out or writes to any ref outside `agl/*`, "
        f"so `main` and every branch of yours is unaddressable rather than protected - "
        f"there is no rule here that could be relaxed and no spelling that would name one"
    )

type _Function[P] = Callable[[Run[P]], Awaitable[None]]

@dataclass(frozen=True, slots=True)
class _NoParams:
    ...

@dataclass(frozen=True, slots=True)
class Workflow[P = object]:
    version: str

    fn: _Function[P]

    @property
    def params(self) -> type[P]:
        """The params class, read off the function's first parameter at every read rather than once.

        :return: the class `params.parse` builds from argv; an empty one for a bare `Run`
        :raises InputError: the annotation is missing, unresolvable, or names anything but a `Run`
        """
        return cast("type[P]", _declared(self.fn))

def workflow[P](*, version: str) -> Callable[[_Function[P]], Workflow[P]]:
    """Declare an async function to be a workflow, stamping the version a resume compares.

    :param version: recorded on every run this starts, and matched exactly before one is resumed
    :return: a decorator refusing anything that is not an `async def`, at import time
    :raises InputError: `version` is empty or only whitespace, so no resume could compare it
    """
    _check_text("version", version)

    def declare(fn: _Function[P]) -> Workflow[P]:
        if not iscoroutinefunction(fn):
            raise InputError(
                f"{fn!r} is decorated as a workflow and is not an `async def`. A workflow is one "
                f"async function, the framework awaits it, and a plain function returning "
                f"an awaitable type-checks here and then never yields"
            )
        return Workflow(version=version, fn=fn)

    return declare

def _check_text(field: str, value: str) -> None:
    if not value.strip():
        raise InputError(
            f"a workflow's {field} is required and cannot be blank: `@workflow` was given "
            f"{value!r}. It is written into every run record this workflow starts, and `RunSpec` "
            f"refuses an empty `workflow_version` - so a run declared this way could not be "
            f"recorded, let alone resumed"
        )

def _declared(fn: Callable[..., object]) -> object:
    parameters, hints = _hints(fn)
    if not parameters:
        raise InputError(
            f"the workflow {_written_at(fn)} takes no parameters, and a workflow is one async "
            f"function taking a `Run` - which is also where it declares its own parameters, "
            f"now that `@workflow` takes only `version=`. Write `async def {fn.__qualname__}(run: "
            f"Run[YourParams])`, or `run: Run` for a workflow that never reads `run.params`"
        )
    first = parameters[0]
    if first not in hints:
        raise InputError(
            f"the workflow {_written_at(fn)} annotates nothing on its first parameter {first!r}, "
            f"and that annotation is the one place a workflow declares its parameters. An "
            f"unannotated parameter is **not** read as a bare `Run`: the two say different things "
            f"and only one of them was written down. Write `{first}: Run[YourParams]`, or "
            f"`{first}: Run` for a workflow that never reads `run.params`"
        )
    annotation = hints[first]
    origin = get_origin(annotation)
    subject = annotation if origin is None else origin
    if subject is Run:
        arguments = get_args(annotation)
        return arguments[0] if arguments else _NoParams
    raise InputError(_not_a_run(fn, first, annotation, subject))

def _not_a_run(fn: Callable[..., object], first: str, annotation: object, subject: object) -> str:
    if isinstance(subject, type) and issubclass(subject, Run):
        return (
            f"the workflow {_written_at(fn)} annotates {first!r} as {named(annotation)}, which "
            f"is a subclass of `Run`. A workflow is handed the `Run` the framework builds, never a "
            f"class of its own, so the annotation would be describing an object this run cannot "
            f"produce - and the params are read from it precisely because it and the object agree. "
            f"There are two spellings and they are the whole list: `Run[YourParams]`, and a bare "
            f"`Run` for a workflow that never reads `run.params`"
        )
    return (
        f"the workflow {_written_at(fn)} annotates {first!r} as {named(annotation)}, and a "
        f"workflow is one async function taking a `Run`. That annotation is also where it "
        f"declares its parameters, now that `@workflow` takes only `version=`, so this is not a "
        f"style note: there is nothing here to read the params class out of. Write `{first}: "
        f"Run[YourParams]`, or `{first}: Run` for a workflow that never reads `run.params`"
    )

def _hints(fn: Callable[..., object]) -> tuple[list[str], Mapping[str, object]]:
    try:
        # `signature` is inside this guard too: 3.14 evaluates no annotation until something asks,
        # and `signature` asks - a first parameter naming a class nothing binds raises before
        # `get_type_hints`.
        return list(signature(fn).parameters), get_type_hints(fn)
    except (NameError, TypeError) as error:
        raise InputError(
            f"the workflow {_written_at(fn)} has an annotation that cannot be resolved: {error}. "
            f"Its first parameter is read for the params class it names, so that annotation "
            f"has to name something importable where it is written - a class defined below the "
            f"function is fine, one that is never bound at all is not"
        ) from error

def _written_at(fn: Callable[..., object]) -> str:
    code = fn.__code__
    return f"`{fn.__qualname__}` at {code.co_filename}:{code.co_firstlineno}"
