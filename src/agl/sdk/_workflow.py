from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from inspect import iscoroutinefunction, signature
from typing import cast, get_args, get_origin, get_type_hints
from agl.ports.errors import InputError, Stop
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace
from agl.ports.integration import Conflict, Integration
from agl.ports.terminal import Terminal
from agl.ports.verifier import VerifierOutcome
from agl.sdk._declarations import named
from agl.sdk._engine.integration import Leases
from agl.sdk._engine.integration import integrate as _integrate
from agl.sdk._engine.journal import Fingerprints
from agl.sdk._engine.preflight import Capabilities
from agl.sdk._engine.services import Services
from agl.sdk._engine.steps import Steps
from agl.sdk._engine.worktrees import Worktrees, _where
from agl.sdk.roles import Role

__all__ = [
    "Conflict",
    "Integration",
    "Namespace",
    "Run",
    "Stop",
    "VerifierOutcome",
    "Workflow",
    "workflow",
]

@dataclass(frozen=True, slots=True)
class Run[P = object]:
    """The run a workflow is handed, with its params, steps and worktrees."""

    params: P
    """The workflow's own parameters, as the flags on `agl run` filled them in."""

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
    def terminal(self) -> Terminal:
        """The terminal this run shows things on.

        Returns:
            The [`Terminal`][agl.sdk.Terminal], shared with every child [`Run`][agl.sdk.Run].
        """
        return self.services.terminal

    @property
    def config(self) -> Mapping[str, str]:
        """The project settings this workflow declares.

        Returns:
            The declared settings by key, exactly as the project file wrote them.

        Raises:
            InputError: Reading a key the workflow's `config` line doesn't declare, through
                `get` and `in` as well as `[]`.
        """
        return self.services.config

    @property
    def label(self) -> str:
        """The run's label, as given with `-n`.

        Returns:
            The label, the same in every child [`Run`][agl.sdk.Run].
        """
        return str(self.scope.label)

    @property
    def namespaces(self) -> tuple[Namespace, ...]:
        """The worktree names from the top-level run down to this one.

        Returns:
            The namespaces this run was opened under, outermost first. Empty for the top-level run.
        """
        return self.scope.namespaces

    async def step[R](self, role: Role[R], *inputs: object, commit: str | None = None) -> R:
        """Runs a [`Role`][agl.sdk.Role] in the worktree this [`Run`][agl.sdk.Run] owns.

        Args:
            role: The role to run, built by a `@role` function.
            inputs: The values the role accepts, at most one per type it declares.
            commit: The message to commit the agent's work under. If omitted, the work is
                thrown away: tracked edits are reverted, untracked files are deleted, and the
                agent's own commits are dropped.

        Returns:
            The payload the role's reporting tool was called with, or `None` where the role
                declares no reporting tool.

        Raises:
            InputError: An input the role doesn't accept, two inputs of one type, or one that
                can't be written down as JSON.
            agl.sdk.NotFoundError: The ref this worktree was cut from names nothing.
            agl.sdk.ConflictError: Another line of work is holding this worktree's place.
            agl.sdk.DeniedError: The backend behind the role's model doesn't offer something
                the role requires.
            agl.sdk.RoleIncompleteError: The agent stopped without reporting a result.
            agl.sdk.UpstreamUnavailable: The agent's backend couldn't be started, or stopped
                without answering.
            agl.sdk.UpstreamUnexpected: The agent's backend answered in a way AGL can't read.
        """
        return await self._steps.step(role, inputs, commit=commit)

    async def verify(self, command: str) -> VerifierOutcome:
        """Runs a command in this run's worktree.

        Args:
            command: The shell command line to run. An empty one passes.

        Returns:
            The [`VerifierOutcome`][agl.sdk.VerifierOutcome], whether the command passed or not.
                A command that failed comes back as a value rather than a refusal.

        Raises:
            InputError: `command` isn't a string.
            agl.sdk.NotFoundError: The ref this worktree was cut from names nothing.
            agl.sdk.ConflictError: Another line of work is holding this worktree's place.
            agl.sdk.UpstreamUnavailable: The command couldn't be started.
            agl.sdk.UpstreamUnexpected: The command's output couldn't be read.
        """
        return await self._steps.verify(command)

    def worktree(self, namespace: str, base: Run[object] | str | None = None) -> Run[P]:
        """Creates a child [`Run`][agl.sdk.Run] with a worktree of its own.

        Args:
            namespace: The worktree's name, unique across the whole run, ignoring case. Asking
                again for a name this run opened hands back that same child.
            base: The `Run` or git ref to start from. If omitted, starts from where this run's
                own line of work has reached. Ignored where the name is already open.

        Returns:
            The child `Run`, which has its own checkout and shares this run's terminal.

        Raises:
            InputError: The name is not one path segment and one git ref component, or it is
                the reserved `_base`.
            agl.sdk.ConflictError: Another worktree in the run already has this name.
        """
        return cast(
            "Run[P]",
            self.worktrees.open(
                namespace, scope=self.scope, base=_starts_at(self, base), build=self._child
            ),
        )

    async def integrate(self) -> Integration:
        """Merges this run's work into the worktree of the [`Run`][agl.sdk.Run] it came from.

        Returns:
            The [`Integration`][agl.sdk.Integration]. On a conflict, finish it with its `retry`
                or `abort`.

        Raises:
            InputError: This is the top-level run, or the workflow declares no `build` setting.
            agl.sdk.NotFoundError: A ref one of the two worktrees was cut from names nothing.
            agl.sdk.ConflictError: Another line of work is holding one of the two places.
            agl.sdk.UpstreamUnavailable: Git or the build command couldn't be run.
            agl.sdk.UpstreamUnexpected: Git refused the landing, or answered unreadably.
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
    """A workflow declared with `@workflow`."""

    fn: _Function[P]

    @property
    def params(self) -> type[P]:
        """The params class this workflow takes.

        Returns:
            The class in the `Run[...]` annotation; an empty one for a bare [`Run`][agl.sdk.Run].

        Raises:
            InputError: The first parameter isn't annotated as a `Run`.
        """
        return cast("type[P]", _declared(self.fn))

def workflow[P](fn: _Function[P] | None = None) -> Workflow[P]:
    """Declares an async function as a workflow `agl run` can start.

    Args:
        fn: The `async def` below a bare `@workflow`. Nothing there means `@workflow()` was
            written with parentheses, which is refused.

    Returns:
        The [`Workflow`][agl.sdk.Workflow] for an entry point to name.

    Raises:
        InputError: `@workflow` was written with parentheses, or `fn` isn't an `async def`.
    """
    if fn is None:
        raise InputError(
            "`@workflow` takes no arguments and is written bare, so `@workflow()` calls it with "
            "no function to decorate and there is nothing for the parentheses to carry. Write "
            "`@workflow` on the line above the `async def`, with no call and no keyword"
        )
    if not iscoroutinefunction(fn):
        raise InputError(
            f"{fn!r} is decorated as a workflow and is not an `async def`. A workflow is one "
            f"async function, the framework awaits it, and a plain function returning "
            f"an awaitable type-checks here and then never yields"
        )
    return Workflow(fn=fn)

def _declared(fn: Callable[..., object]) -> object:
    parameters, hints = _hints(fn)
    if not parameters:
        raise InputError(
            f"the workflow {_written_at(fn)} takes no parameters, and a workflow is one async "
            f"function taking a `Run` - which is also where it declares its own parameters, "
            f"`@workflow` itself taking none. Write `async def {fn.__qualname__}(run: "
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
        f"declares its parameters, `@workflow` itself taking none, so this is not a style note: "
        f"there is nothing here to read the params class out of. Write `{first}: "
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
