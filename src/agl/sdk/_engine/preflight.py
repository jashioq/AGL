import sys
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType, ModuleType
from typing import Any, Final
from agl.ports.agent import AgentRunner, Capability, ModelId, Provider
from agl.ports.errors import DeniedError, InputError, InternalError, UpstreamUnavailable
from agl.ports.history import History
from agl.sdk.roles import Role, RoleFactory

__all__ = ["Capabilities", "check", "checked_inputs"]

type _Declaration = Callable[..., object]

_FROM_TOOLS: Final = (
    f". {str(Capability.TOOL_CALLING)!r} is in this role's `requires` because it declares `tools`: "
    f"`sdk/roles.py` folds it in at declaration time, so there is no line in the workflow to go "
    f"looking for. Either this role names a model whose backend can call a tool, or it offers none "
    f"- and a role with no tools is an effect step, whose result is `null`"
)

_FROM_NO_DECLARATION: Final = (
    ". This role accepts nothing at all, which is what a `Role(...)` built by hand carries: the "
    "declaration is bound onto a `Role` by `RoleFactory.__call__`, so one that no factory was "
    "called for holds none - and a factory written `@role(model=...)` declares none either"
)

# `adapters/openai/runner.py`'s `check_ready` spawns one local process and pays nothing;
# `adapters/claude_code/runner.py`'s spends a turn of the model it asks about - naming that first
# binary here would fail `scripts/check`'s containment gate. Logged into one harness and out of the
# other, a run probing the paid one first buys that turn and is then refused for the other.
_PROBE_COST: Final[Mapping[Provider, int]] = MappingProxyType(
    {Provider.OPENAI: 0, Provider.CLAUDE: 1}
)

class Capabilities:
    def __init__(self) -> None:
        self._known: dict[ModelId, frozenset[Capability]] = {}

    async def require(self, runner: AgentRunner, role: Role[object], *, step: str) -> None:
        held = self._known.get(role.model)
        if held is None:
            held = await runner.capabilities(role.model)
            self._known[role.model] = held
        missing = frozenset(role.requires) - held
        if missing:
            raise DeniedError(_unmet(step, role, missing, held))

def checked_inputs(
    role: Role[object], passed: Sequence[object], *, step: str
) -> Mapping[str, object]:
    inputs: dict[str, object] = {}
    for value in passed:
        matched = tuple(declared for declared in role.accepts if isinstance(value, declared))
        if not matched:
            raise InputError(_unaccepted(step, role, value))
        narrowest = _narrowest(matched)
        if narrowest is None:
            raise InputError(_ambiguous(step, value, matched))
        # The declared type's name and not the instance's: `_engine/prompts.py` fills a `{{Name}}`
        # from this mapping, and the name an author can write there is the one the role declared.
        # The concrete type is not lost - `_engine/journal.py`'s canonicaliser tags the value with
        # its own `module.qualname`, so a subclass fingerprints apart from the base it lands under.
        name = narrowest.__qualname__
        if name in inputs:
            raise InputError(_passed_twice(step, name))
        inputs[name] = value
    return inputs

async def check(runner: AgentRunner, history: History, declared_by: _Declaration) -> None:
    try:
        await history.check_committer_identity()
    except UpstreamUnavailable as unattributable:
        raise UpstreamUnavailable(_no_identity(unattributable)) from unattributable
    # `sorted` is stable, so two models whose probes cost the same are still asked in the order
    # `_demanded` handed them, which is the order the author wrote their roles in.
    for factory in sorted(_demanded(_declared_beside(declared_by)), key=_cost_of):
        try:
            await runner.check_ready(factory.model)
        except UpstreamUnavailable as unavailable:
            raise UpstreamUnavailable(
                _not_ready(unavailable, factory, declared_by.__module__)
            ) from unavailable

def _narrowest(matched: Sequence[type[object]]) -> type[object] | None:
    if not matched:
        return None
    below = matched[0]
    for declared in matched[1:]:
        if issubclass(declared, below):
            below = declared
    return below if all(issubclass(below, declared) for declared in matched) else None

def _cost_of(factory: RoleFactory[..., Any]) -> int:
    return _PROBE_COST[factory.model.provider]

def _declared_beside(declared_by: _Declaration) -> tuple[RoleFactory[..., Any], ...]:
    written_in = sys.modules.get(declared_by.__module__)
    if written_in is None:
        raise InternalError(
            f"the workflow function {declared_by.__qualname__!r} says it was written in "
            f"{declared_by.__module__!r}, and that module is not in `sys.modules`. "
            f"Preflight reads a workflow's role factories out of the namespace its `def` ran in - "
            f"`@workflow` takes no arguments at all, for the reason `ARCHITECTURE.md`'s "
            f"'Deliberately not built' gives - and an entry point is what imported that module, "
            f"so there is no supported way to reach this line"
        )
    beside = tuple(vars(written_in).values())
    return tuple(bound for bound in beside if isinstance(bound, RoleFactory)) + tuple(
        inside
        for bound in beside
        if isinstance(bound, ModuleType)
        for inside in vars(bound).values()
        if isinstance(inside, RoleFactory)
    )

def _demanded(factories: tuple[RoleFactory[..., Any], ...]) -> tuple[RoleFactory[..., Any], ...]:
    first: dict[ModelId, RoleFactory[..., Any]] = {}
    for factory in factories:
        first.setdefault(factory.model, factory)
    return tuple(first.values())

def _no_identity(refusal: UpstreamUnavailable) -> str:
    return (
        f"{refusal} - and AGL asked because it commits the agent's work for it: a step declaring "
        f"`commit=` ends by recording what the agent changed, through `Workspace.commit_all`, "
        f"which invents no identity of its own and leaves the question to the repository. A commit "
        f"git will not make fails at the end of that step, after the agent has finished and before "
        f"the entry is written - so the turn that produced the work is paid for and lost, and a "
        f"resume finds no entry and dispatches the step again. Refused here, nothing is spent"
    )

def _not_ready(
    refusal: UpstreamUnavailable, factory: RoleFactory[..., Any], workflow_module: str
) -> str:
    return (
        f"{refusal} - and AGL asked because {str(factory.model)!r} is the model of the role "
        f"factory `{factory.name}`, declared in {factory.__module__!r} and reached from "
        f"{workflow_module!r}, which is the module this run's workflow is written in. Preflight "
        f"reads the `@role(model=…)` factories in that namespace - and in any module bound in it - "
        f"and asks each distinct model's backend whether it is ready, without calling any of "
        f"them. That scan over-approximates, deliberately: a role imported into a workflow's "
        f"module and never stepped with still demands its provider here, and so does every other "
        f"role of a module imported for one of them, which is the known cost of one declaration "
        f"instead of two. If nothing in {workflow_module!r} steps with `{factory.name}`, this is a "
        f"false refusal and the line that put the demand there is an import - of `{factory.name}` "
        f"itself, or of a module that binds it - so dropping that import drops this demand; "
        f"otherwise the harness above is the thing to fix"
    )

def _unmet(
    step: str, role: Role[object], missing: frozenset[Capability], held: frozenset[Capability]
) -> str:
    wanted = sorted(str(member) for member in missing)
    offered = sorted(str(member) for member in held)
    message = (
        f"the role handed to step {step!r} cannot run on {str(role.model)!r}: it requires "
        f"{wanted}, which the backend serving that model does not offer - it reports {offered}. "
        f"A capability is what a backend can be asked for at all, so this does not clear up on "
        f"its own: either the role names a model whose backend has it, or it stops requiring it"
    )
    if Capability.TOOL_CALLING in missing and role.tools:
        message += _FROM_TOOLS
    return message

def _unaccepted(step: str, role: Role[object], value: object) -> str:
    offered = type(value).__qualname__
    accepted = sorted(declared.__qualname__ for declared in role.accepts)
    message = (
        f"step {step!r} was handed a {offered}, and the role it names accepts {accepted}. An input "
        f"is matched to a declared type by `isinstance` and recorded under that type's name, so "
        f"one nothing declared has no name to go under: it would reach neither the fingerprint "
        f"nor the agent, and the step would be paid for and answered without it. `accepts=` is "
        f"declared on the role's factory - `@role(model=..., accepts=({offered},))` - and never "
        f"on the `Role` itself, so that preflight can read it without calling the factory"
    )
    if not role.accepts:
        message += _FROM_NO_DECLARATION
    return message

def _ambiguous(step: str, value: object, matched: Sequence[type[object]]) -> str:
    offered = type(value).__qualname__
    both = sorted(declared.__qualname__ for declared in matched)
    return (
        f"step {step!r} was handed a {offered}, which is an instance of {both} - every one of the "
        f"types the role it names accepts that could take it, and none of them a subclass of the "
        f"rest. An input is recorded under the name of the declared type it matched, so a value "
        f"matching two unrelated declarations has no single name to go under, and choosing one "
        f"here would be a rule living in the framework about which of the author's own types this "
        f"step meant. Accept the one this role reads, or make one of them a subclass of the other "
        f"- a value matching both then goes under the narrower, which is a declared answer"
    )

def _passed_twice(step: str, name: str) -> str:
    return (
        f"step {step!r} was handed two {name} values, and a step's inputs are recorded one per "
        f"declared type, under the name of the type each was matched to - so a subclass of {name} "
        f"is recorded under {name} as well. The second would take the first's place in the "
        f"fingerprint and in the prompt, so one of the two would be paid for and never read - and "
        f"two calls differing only in the value that was dropped would share a digest, the second "
        f"replaying the first's result. A role that needs two of something declares one type "
        f"holding both"
    )
