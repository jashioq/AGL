
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any, Final

from agl.ports.agent import AgentRunner, Capability, ModelId
from agl.ports.errors import DeniedError, InternalError, UpstreamUnavailable
from agl.sdk.roles import Role, RoleFactory

__all__ = ["Capabilities", "check"]

type _Declaration = Callable[..., object]

_FROM_TOOLS: Final = (
    f". {str(Capability.TOOL_CALLING)!r} is in this role's `requires` because it declares `tools`: "
    f"`sdk/roles.py` folds it in at declaration time, so there is no line in the workflow to go "
    f"looking for. Either this role names a model whose backend can call a tool, or it offers none "
    f"- and a role with no tools is an effect step, whose result is `null`"
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


async def check(runner: AgentRunner, declared_by: _Declaration) -> None:
    for factory in _demanded(_declared_beside(declared_by)):
        try:
            await runner.check_ready(factory.model)
        except UpstreamUnavailable as unavailable:
            raise UpstreamUnavailable(
                _not_ready(unavailable, factory, declared_by.__module__)
            ) from unavailable


def _declared_beside(declared_by: _Declaration) -> tuple[RoleFactory[..., Any], ...]:
    written_in = sys.modules.get(declared_by.__module__)
    if written_in is None:
        raise InternalError(
            f"the workflow function {declared_by.__qualname__!r} says it was written in "
            f"{declared_by.__module__!r}, and that module is not in `sys.modules`. "
            f"Preflight reads a workflow's role factories out of the namespace its `def` ran in - "
            f"`@workflow` takes no `roles=`, for the reason `ARCHITECTURE.md`'s 'Deliberately not "
            f"built' gives - and an entry point is what imported that module, so there is no "
            f"supported way to reach this line"
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
